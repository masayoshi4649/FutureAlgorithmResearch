"""確定足と一分先行の特徴を別実装で照合し、金融開始前の入力を監査する。"""

from __future__ import annotations

import collections
import hashlib
from io import BytesIO
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OWNER = HERE.parent
MANIFEST = OWNER / "保存済み気配と先行確定足の八十二入力.json"
SOURCE = OWNER / "prepare125.py"
CHECKS = 0
READS = 0


def check(value: bool, note: str) -> None:
    """
    機能: 独立期待値の一致を数えて検査する。
    引数: value (bool) 条件、note (str) 検査名。
    返り値: None。
    """
    global CHECKS
    assert bool(value), note
    CHECKS += 1


def equal(actual: np.ndarray, expected: np.ndarray, note: str) -> None:
    """
    機能: 形状・未知位置・値を厳密な許容差で比較する。
    引数: actual/expected (ndarray) 配列、note (str) 検査名。
    返り値: None。
    """
    check(actual.shape == expected.shape, note + "形状")
    check(np.array_equal(np.isnan(actual), np.isnan(expected)), note + "未知位置")
    check(np.allclose(actual, expected, atol=1e-10, rtol=1e-12, equal_nan=True), note + "値")


def oracle_bars(quotes: dict, start: float, end: float, tick: float) -> dict:
    """
    機能: 各半開区間を二分探索し、16終値と15本範囲を独立算出する。
    引数: quotes (dict) 原行列、start/end/tick (float) 場範囲と呼値。
    返り値: dict 公開時刻と8列の足特徴。
    """
    count = round((end - start) / 60)
    publications = start + np.arange(1, count + 1) * 60
    closes = np.full(count, np.nan)
    highs = np.full(count, np.nan)
    lows = np.full(count, np.nan)
    for minute in range(count):
        lo = int(np.searchsorted(quotes["time"], start + minute * 60, side="left"))
        hi = int(np.searchsorted(quotes["time"], start + (minute + 1) * 60, side="left"))
        if hi > lo:
            segment = quotes["last"][lo:hi]
            closes[minute] = segment[-1]
            highs[minute] = max(segment)
            lows[minute] = min(segment)
    values = np.full((count, 8), np.nan)
    for minute in range(count):
        values[minute, 0] = closes[minute]
        values[minute, 1] = closes[minute - 1] if minute else np.nan
        if minute < 15:
            continue
        window = closes[minute - 15:minute + 1]
        if not np.isfinite(window).all():
            continue
        movements = [float(window[i + 1] - window[i]) for i in range(15)]
        magnitude = sum(abs(x) for x in movements)
        change = float(window[-1] - window[0])
        absolute = sorted(abs(x) for x in movements)
        quantile75 = (absolute[10] + absolute[11]) / 2
        values[minute, 2] = max(highs[minute - 14:minute + 1])
        values[minute, 3] = min(lows[minute - 14:minute + 1])
        values[minute, 4] = sum(closes[minute - 14:minute + 1]) / 15
        values[minute, 5] = abs(change) / magnitude if magnitude else 0
        values[minute, 6] = change
        values[minute, 7] = max(8 * tick, 3 * quantile75)
    return {"minute": publications, "values": values}


def oracle_features(quotes: dict, own: dict, peer: dict) -> tuple[np.ndarray, np.ndarray]:
    """
    機能: 各公開時刻を最初の未来でない自己行に割当て、相手を一分前までに限定する。
    引数: quotes/own/peer (dict) 自己観測と二市場の確定足。
    返り値: tuple[ndarray, ndarray] 公開元行と12列。空分を後から補完しない。
    """
    mapped = {}
    for index, published in enumerate(own["minute"]):
        matches = np.searchsorted(quotes["time"], published, side="left")
        if matches == len(quotes["row"]):
            continue
        value = np.full(12, np.nan)
        value[:8] = own["values"][index]
        candidates = np.flatnonzero(peer["minute"] <= published - 60)
        if len(candidates):
            p = int(candidates[-1])
            age = float(published - peer["minute"][p])
            if age <= 120 and np.isfinite(peer["values"][p, [5, 6]]).all():
                change = peer["values"][p, 6]
                value[8:] = (1 if change > 0 else -1 if change < 0 else 0, peer["values"][p, 5], age, change)
        mapped[int(quotes["row"][matches])] = value
    return np.asarray(list(mapped), dtype=np.int64), np.asarray(list(mapped.values()), dtype=float).reshape((-1, 12))


def quotes_fixture(minutes: int = 40) -> dict:
    """
    機能: 同じ価格時計を含む正の人工観測を作る。
    引数: minutes (int) 人工分数。
    返り値: dict 自己原行・秒・Last・両気配。
    """
    times = np.asarray([minute * 60 + second for minute in range(minutes) for second in (0, 0, 23, 59)], dtype=float)
    prices = np.asarray([4000 + minute + second / 100 for minute in range(minutes) for second in (0, 1, 23, 59)], dtype=float)
    return {"row": np.arange(len(times), dtype=np.int64) * 3 + 100, "time": times, "last": prices, "bid": prices - .5, "ask": prices + .5}


def artificial(module: dict) -> dict:
    """
    機能: 欠測・16終値・同時計・peer境界・接頭不変を人工観測で確認する。
    引数: module (dict) SHA固定した親準備関数。
    返り値: dict 純人工検査の合格と項目。
    """
    start_checks = CHECKS
    q = quotes_fixture()
    base = module["bars"](q, 0., 40 * 60., .5)
    independent = oracle_bars(q, 0., 40 * 60., .5)
    equal(base["values"], independent["values"], "人工正常足")
    check(not np.isfinite(base["values"][14]).all(), "15終値だけでは完全特徴にならない")
    check(np.isfinite(base["values"][15]).all(), "16連続終値から完全特徴")
    # ----------------------------------------
    missing = {key: value[(q["time"] < 10 * 60) | (q["time"] >= 11 * 60)] for key, value in q.items()}
    gap = module["bars"](missing, 0., 40 * 60., .5)
    equal(gap["values"], oracle_bars(missing, 0., 40 * 60., .5)["values"], "人工空分")
    check(np.isnan(gap["values"][10, 0]), "空分終値の補完禁止")
    check(not np.isfinite(gap["values"][25]).all() and np.isfinite(gap["values"][26]).all(), "欠測後は新16終値が必要")
    # ----------------------------------------
    fr, fv = module["features"](q, base, base)
    ofr, ofv = oracle_features(q, independent, independent)
    equal(fr, ofr, "人工公開原row")
    equal(fv, ofv, "人工12特徴")
    row16 = q["row"][np.flatnonzero(q["time"] == 16 * 60)[0]]
    row17 = q["row"][np.flatnonzero(q["time"] == 17 * 60)[0]]
    i16 = int(np.flatnonzero(fr == row16)[0])
    i17 = int(np.flatnonzero(fr == row17)[0])
    check(np.isfinite(fv[i16, :8]).all() and np.isnan(fv[i16, 8:]).all(), "自己16終値でも同時刻の相手初有効足を使わない")
    check(np.isfinite(fv[i17]).all() and fv[i17, 10] == 60, "次分から60秒先行の相手有効足を利用")
    # ----------------------------------------
    # 公開時刻と同じ価格時計の後続原rowは当該公開足の材料に使わない。
    cut = int(np.flatnonzero(q["row"] == row16)[0])
    prefix = {key: value[:cut + 1].copy() for key, value in q.items()}
    pb = module["bars"](prefix, 0., 40 * 60., .5)
    pfr, pfv = module["features"](prefix, pb, pb)
    equal(pfr, fr[fr <= row16], "接頭公開原row不変")
    equal(pfv, fv[fr <= row16], "接頭公開特徴不変")
    changed = {key: value.copy() for key, value in q.items()}
    changed["last"][cut + 1:] += 12345
    cb = module["bars"](changed, 0., 40 * 60., .5)
    cfr, cfv = module["features"](changed, cb, cb)
    equal(cfv[cfr <= row16], fv[fr <= row16], "同時計後続と将来の変更が過去へ影響しない")
    # ----------------------------------------
    # peerの同時刻・59秒前は不可、60/120秒前は可、180秒前は不可。
    one = {key: value[-1:].copy() for key, value in q.items()}
    one["time"][:] = 1000
    own = {"minute": np.asarray([1000.]), "values": np.zeros((1, 8))}
    peer_values = np.zeros((1, 8))
    peer_values[0, 5:7] = (.5, 8)
    for age, known in [(0, False), (59, False), (60, True), (120, True), (180, False)]:
        peer = {"minute": np.asarray([1000. - age]), "values": peer_values}
        _, values = module["features"](one, own, peer)
        check(bool(np.isfinite(values[0, 8:]).all()) == known, f"peer時間差{age}秒の資格")
    peer = {"minute": np.asarray([940.]), "values": np.full((1, 8), np.nan)}
    _, values = module["features"](one, own, peer)
    check(np.isnan(values[0, 8:]).all(), "相手欠測を方向0へ補完しない")
    # ----------------------------------------
    sparse = {key: value[(q["time"] < 20 * 60) | (q["time"] >= 23 * 60)] for key, value in q.items()}
    sb = module["bars"](sparse, 0., 40 * 60., .5)
    sr, sv = module["features"](sparse, sb, base)
    er, ev = oracle_features(sparse, oracle_bars(sparse, 0., 40 * 60., .5), independent)
    equal(sr, er, "観測gap後の重複公開rowは一つ")
    equal(sv, ev, "観測gap後の最新空分は未知のまま")
    check(np.all(np.diff(sr) > 0), "feature原row厳密増加")
    empty = {key: value[:0] for key, value in q.items()}
    eb = module["bars"](empty, 0., 40 * 60., .5)
    er, ev = module["features"](empty, eb, eb)
    check(er.shape == (0,) and ev.shape == (0, 12), "空観測の形状を保持")
    return {"passed": True, "checks": CHECKS - start_checks, "項目": ["16連続終値境界", "欠測を補完しない", "公開時刻以上の最初の原row", "同時計後続を前足へ入れない", "自己/相手の接頭未来不変", "peer同時刻・59秒前禁止", "peer60秒・120秒前許可、180秒前禁止", "gapで複数公開が一rowへ写る場合の最新状態", "空観測"]}


def main() -> None:
    """
    機能: SHAを固定した82入力を各一回読み、列資格と全特徴を別算術で検査する。
    引数: なし。
    返り値: None。金融再生と元市場・旧気配cache読取は0。
    """
    global READS
    manifest_raw = MANIFEST.read_bytes()
    manifest = json.loads(manifest_raw)
    source_raw = SOURCE.read_bytes()
    source_sha = hashlib.sha256(source_raw).hexdigest()
    check(source_sha == manifest["source_sha256"], "親の準備源は目録固定版")
    check(manifest["passed"] and len(manifest["inputs"]) == 82 and len(manifest["sessions"]) == 41, "41場82入力の完成目録")
    check(manifest["financial_replays"] == manifest["original_market_reads"] == manifest["API"] == manifest["real_orders"] == 0, "親準備に金融原本API実注文なし")
    (HERE / "親準備源の固定保存.py.txt").write_bytes(source_raw)
    namespace = {"__name__": "_independent_prepare125", "__file__": str(SOURCE)}
    exec(compile(source_raw, str(SOURCE), "exec"), namespace)
    proof = artificial(namespace)
    rows = {}
    per_input = []
    expected_keys = {(scene, symbol) for scene in manifest["sessions"] for symbol in ("TOPIX", "NK225")}
    check({(item["session"], item["symbol"]) for item in manifest["inputs"]} == expected_keys, "全82識別の欠落重複なし")
    check(len(manifest["feature_columns"]) == 12 and tuple(manifest["feature_columns"]) == namespace["FEATURE_COLUMNS"], "12特徴の列名一致")
    for item in manifest["inputs"]:
        path = ROOT / item["path"]
        check(path.resolve().is_relative_to(OWNER / "prepared"), "所有125入力だけ")
        stat = path.stat()
        raw = path.read_bytes()
        READS += 1
        check(hashlib.sha256(raw).hexdigest() == item["sha256"] and path.stat().st_size == stat.st_size and path.stat().st_mtime_ns == stat.st_mtime_ns, "保存NPZ同bytes不変")
        with np.load(BytesIO(raw), allow_pickle=False) as data:
            check(set(data.files) == {"row", "time", "last", "bid", "ask", "feature_rows", "features"}, "保存列集合")
            q = {key: data[key].copy() for key in ("row", "time", "last", "bid", "ask")}
            fr, fv = data["feature_rows"].copy(), data["features"].copy()
        n = len(q["row"])
        check(n == item["quote_rows"] and n > 0 and all(value.shape == (n,) for value in q.values()), "気配列の長さ")
        check(all(np.isfinite(value).all() for value in q.values()), "全気配列は有限")
        check(np.issubdtype(q["row"].dtype, np.integer) and np.all(np.diff(q["row"]) > 0) and np.all(np.diff(q["time"]) >= 0), "原row厳密増加と価格時計非減少")
        check(np.all((q["last"] > 0) & (q["bid"] > 0) & (q["ask"] > q["bid"])), "Last正と正常BBO")
        start, end = namespace["bounds"](item["session"])
        check(start == item["start"] and end == item["end"], "場の開始終了固定")
        check(np.all((q["time"] >= start) & (q["time"] <= end)), "採用価格時計は当場範囲内")
        check(fr.shape == (item["feature_rows"],) and np.issubdtype(fr.dtype, np.integer) and fv.shape == (len(fr), 12) and np.all(np.diff(fr) > 0), "公開原row・12列形状")
        indices = np.searchsorted(q["row"], fr)
        check(np.all(indices < n) and np.array_equal(q["row"][indices], fr), "全公開原rowが気配原rowに実在")
        check(int(np.isfinite(fv[:, :8]).all(axis=1).sum()) == item["valid_features"], "完全自己特徴数")
        check(not np.isinf(fv).any(), "特徴の未知はNaNで無限値なし")
        key = item["session"], item["symbol"]
        rows[key] = (q, fr, fv, item)
        per_input.append({"session": key[0], "symbol": key[1], "path": item["path"], "sha256": item["sha256"], "quote_rows": n, "feature_rows": len(fr), "valid_features": item["valid_features"]})
    # ----------------------------------------
    # 同じ保存入力をメモリ上で再利用し、原本・旧cacheを再読しない。
    all_bars = {}
    for (scene, symbol), (q, fr, fv, item) in rows.items():
        all_bars[scene, symbol] = oracle_bars(q, item["start"], item["end"], .5 if symbol == "TOPIX" else 10.)
    for (scene, symbol), (q, fr, fv, item) in rows.items():
        peer = "NK225" if symbol == "TOPIX" else "TOPIX"
        er, ev = oracle_features(q, all_bars[scene, symbol], all_bars[scene, peer])
        equal(fr, er, "全実入力の独立公開原row")
        equal(fv, ev, "全実入力の独立12特徴")
    check(READS == 82, "保存82入力は各一読")
    check(hashlib.sha256(SOURCE.read_bytes()).hexdigest() == source_sha, "監査前後で親源不変")
    check(hashlib.sha256(MANIFEST.read_bytes()).hexdigest() == hashlib.sha256(manifest_raw).hexdigest(), "監査前後で目録不変")
    output = {"passed": True, "全合格": True, "source_sha256": source_sha, "manifest": {"path": MANIFEST.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(manifest_raw).hexdigest()}, "audit_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "checks": CHECKS, "artificial": proof, "inputs": per_input, "保存入力読取": READS, "保存原観測数": sum(row["quote_rows"] for row in per_input), "保存特徴数": sum(row["feature_rows"] for row in per_input), "自己有効特徴数": sum(row["valid_features"] for row in per_input), "全82の12特徴と公開原rowを別実装で照合": True, "original_market_reads": 0, "old_quote_cache_reads": 0, "financial_replays": 0, "API": 0, "real_orders": 0, "限界": "価格時計代理上の確定公開・一分先行の検証。受信時刻・BBO市場eventTimeが未保存なので、真の二市場の受信順や通信遅延を証明しない。元気配cacheとの同値性は親の正式SHAと既存監査へ委譲し、元原本や旧cacheは再読しない。"}
    target = HERE / "保存入力八十二と先行確定足の独立監査.json"
    check(not target.exists(), "監査の成功を上書きしない")
    payload = (json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    target.write_bytes(payload)
    print(json.dumps({"path": target.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(payload).hexdigest(), "checks": CHECKS, "source_sha256": source_sha, "保存入力読取": READS}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        target = HERE / "途中失敗.json"
        if not target.exists():
            target.write_text(json.dumps({"passed": False, "型": type(exc).__name__, "理由": str(exc), "checks": CHECKS, "保存入力読取": READS, "金融再生": 0, "原本": 0}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
