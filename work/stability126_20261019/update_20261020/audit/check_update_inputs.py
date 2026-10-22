"""追加二場の数値源継承と入力資格を、売買再生なしで独立監査する。"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
UPDATE = HERE.parent
WORK = UPDATE.parent
ROOT = WORK.parents[1]
SCENES = ("2026-10-19_Night", "2026-10-20_Day")
JST = timezone(timedelta(hours=9))
PROOFS = (
    "input_audit/元E01の足公開と共同時計及び終端の独立人工.json",
    "input_audit/rearm_artificial126/既知GとGUの非空旧新同値及び公開時計の独立純人工.json",
    "audit_artificial/原版と十六条件の最終源による独立純人工監査.json",
    "input_audit/bbo_artificial126/最終BBO源と全九出力有限性及びJITの独立純人工.json",
    "input_audit/gated_artificial126/公開気配と低利益床及び商品場内同値引用の最終独立監査.json",
)
READS = []
CHECKS = []
sys.dont_write_bytecode = True


def sha(payload: bytes) -> str:
    """
    機能: 読み取った内容の指紋を求める。
    引数: payload(bytes)は既読内容。
    返り値: strはSHA256。
    """
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path) -> dict:
    """
    機能: 小さな証拠JSONだけを読む。
    引数: path(Path)は証拠の位置。
    返り値: dictは解釈内容。
    """
    assert path.resolve().is_relative_to(ROOT / "work"), str(path)
    return json.loads(path.read_text(encoding="utf-8"))


def save(name: str, value: dict) -> None:
    """
    機能: 監査所有域の未使用位置だけへ有限JSONを保存する。
    引数: name(str)、value(dict)はファイル名と保存内容。
    返り値: None。
    """
    target = HERE / name
    assert target.resolve().parent == HERE and not target.exists(), str(target)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def check(name: str, passed: bool) -> None:
    """
    機能: 独立した不変条件の合否を記録する。
    引数: name(str)、passed(bool)は条件名と結果。
    返り値: None。不合格は直ちに停止する。
    """
    assert bool(passed), name
    CHECKS.append(dict(name=name, passed=True))


def sources() -> dict:
    """
    機能: 旧最終人工証拠と既登録源の指紋を現数値核へ照合する。
    引数: なし。
    返り値: dictは適用可能な人工証拠と全数値源の実指紋。
    """
    expected, proofs = {}, []
    prior = WORK / "rearm126/固定計画.json"
    fixed = read_json(prior)
    for name, digest in fixed["sources"].items():
        if "/engine/" in name and name.endswith(".py"):
            expected[name] = digest
    check("旧登録のエンジン源107個を継承", len(expected) == 107)
    for relative in PROOFS:
        path = WORK / relative
        payload = path.read_bytes()
        proof = json.loads(payload)
        check("人工証拠合格_" + relative, proof.get("passed", proof.get("全合格", False)))
        mapping = dict(proof.get("sources", {}))
        if "実装源指紋" in proof:
            for name, digest in proof["実装源指紋"].items():
                folder = "design" if name == "catalog126.py" else "engine"
                mapping[(WORK / folder / name).relative_to(ROOT).as_posix()] = digest
        for name, digest in mapping.items():
            name = name.replace("\\", "/")
            check("証拠間の源指紋一致_" + name, name not in expected or expected[name] == digest)
            expected[name] = digest
        proofs.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=sha(payload),
                           checks=proof.get("count", proof.get("確認数", len(proof.get("checks", []))))))
    actual = {}
    for name, digest in sorted(expected.items()):
        path = ROOT / name
        check("源がwork内_" + name, path.resolve().is_relative_to(ROOT / "work"))
        actual[name] = sha(path.read_bytes())
        check("最終人工と現数値源が同bytes_" + name, actual[name] == digest)
    return dict(passed=True, proofs=proofs, sources=actual,
                registered_source=dict(path=prior.relative_to(ROOT).as_posix(), sha256=sha(prior.read_bytes())),
                checks=CHECKS.copy(), market_reads=0, financial_replays=0, API=0, real_orders=0,
                reuse="旧最終人工の数値核を同bytes継承。人工金融の再実行や市場売買再生は行わない。",
                producer_sha256=sha(Path(__file__).read_bytes()))


def expected_bounds(scene: str) -> tuple[float, float, float, float]:
    """
    機能: 旧E01と同じ日本時間の場開始・観測終端・返済判断期限を独立に求める。
    引数: scene(str)はセッション名。
    返り値: tuple[float,float,float,float]は開始、観測終端、返済期限、実場末。
    """
    date_text, kind = scene.rsplit("_", 1)
    day = datetime.fromisoformat(date_text).replace(tzinfo=JST)
    if kind == "Day":
        values = (day + timedelta(hours=8, minutes=45), day + timedelta(hours=15, minutes=40),
                  day + timedelta(hours=15, minutes=35), day + timedelta(hours=15, minutes=45))
    else:
        assert kind == "Night"
        values = (day + timedelta(hours=17), day + timedelta(days=1, hours=5, minutes=55),
                  day + timedelta(days=1, hours=5, minutes=50), day + timedelta(days=1, hours=6))
    return tuple(value.timestamp() for value in values)


def market_expected(inputs: dict, key: tuple) -> np.ndarray:
    """
    機能: 売買判断をせず12市場特徴の厳密過去対応を別式で計算する。
    引数: inputs(dict)、key(tuple)は両商品の既読入力と自己キー。
    返り値: np.ndarrayは独立に対応させた12列。
    """
    own = inputs[key]
    other_key = key[0], "NK225" if key[1] == "TOPIX" else "TOPIX"
    peer = inputs[other_key]
    own_time, peer_time = np.asarray(own["time_s"]), np.asarray(peer["time_s"])
    value = np.full((len(own_time), 12), np.nan)
    value[:, 0], value[:, 2] = own["last"], own["atr"]
    differences = {}
    for item_key, ready in ((key, own), (other_key, peer)):
        times, prices, atr = (np.asarray(ready[name]) for name in ("time_s", "last", "atr"))
        for window in (30., 120.):
            rows = np.searchsorted(times, times - window, side="right") - 1
            safe = np.maximum(rows, 0)
            okay = ((rows >= 0) & np.isfinite(atr) & (atr > 0) & np.isfinite(prices) &
                    np.isfinite(prices[safe]) & (times - window - times[safe] >= 0) &
                    (times - window - times[safe] <= 30))
            delta, clock = np.full(len(times), np.nan), np.full(len(times), np.nan)
            delta[okay] = (prices[okay] - prices[safe[okay]]) / atr[okay]
            clock[okay] = times[safe[okay]]
            differences[item_key, window] = delta, clock
    value[:, 4], value[:, 9] = differences[key, 30.]
    value[:, 5] = differences[key, 120.][0]
    rows = np.searchsorted(peer_time, own_time, side="left") - 1
    safe = np.maximum(rows, 0)
    okay = ((rows >= 0) & (peer_time[safe] < own_time) & (own_time - peer_time[safe] <= 15) &
            np.isfinite(own["last"]) & np.isfinite(peer["last"][safe]) &
            np.isfinite(own["atr"]) & (own["atr"] > 0) &
            np.isfinite(peer["atr"][safe]) & (peer["atr"][safe] > 0))
    value[okay, 1], value[okay, 3] = peer["last"][safe[okay]], peer["atr"][safe[okay]]
    value[okay, 6] = differences[other_key, 30.][0][safe[okay]]
    value[okay, 7] = differences[other_key, 120.][0][safe[okay]]
    value[okay, 8] = peer_time[safe[okay]]
    value[okay, 10] = differences[other_key, 30.][1][safe[okay]]
    value[:, 11] = okay.astype(float)
    return value


def packet(item: dict) -> list[dict]:
    """
    機能: 完成した所有packetを一読し、時刻・seq・気配・特徴・終端資格を検査する。
    引数: item(dict)はsession/path/sha256/bytesを持つ目録行。
    返り値: list[dict]は金融へ逆流しない4口座の入力監査記録。
    """
    scene = item["session"]
    check("追加対象のみ_" + scene, scene in SCENES)
    path = ROOT / item["path"]
    check("所有packetの域_" + scene, path.resolve().is_relative_to(UPDATE) and path.suffix == ".pkl")
    raw = path.read_bytes()
    READS.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=sha(raw), bytes=len(raw), reads=1))
    check("packet指紋_" + scene, sha(raw) == item["sha256"] and len(raw) == item["bytes"])
    data = pickle.loads(raw)
    check("packet場名_" + scene, data["session"] == scene)
    keys = {(scene, symbol) for symbol in ("TOPIX", "NK225")}
    check("当場両商品のみ_" + scene, set(data["inputs"]) == keys)
    start, end, limit, close = expected_bounds(scene)
    rows = []
    for key in sorted(keys):
        label = scene + "_" + key[1]
        ready, quotes = data["inputs"][key], data["quotes"][key]
        sequence, times, last, atr = (np.asarray(ready[name]) for name in ("seq", "time_s", "last", "atr"))
        n = len(sequence)
        check("入力列shape_" + label, n > 0 and all(value.shape == (n,) for value in (sequence, times, last, atr)))
        check("原seq厳密過去順_" + label, np.all(np.diff(sequence) > 0))
        check("価格時計有限非逆行_" + label, np.isfinite(times).all() and np.all(np.diff(times) >= 0))
        check("旧場開始と返済期限_" + label, ready["start"] == start and ready["limit"] == limit)
        check("旧観測窓外を混入しない_" + label, np.all((times >= start) & (times < end)))
        check("観測終端と実場末を区別_" + label, ready.get("session_close", close) == close)
        check("返済期限後に有効Lastあり_" + label, np.any((times > limit) & np.isfinite(last) & (last > 0)))
        for field, expected in (("seq", sequence), ("time_s", times)):
            np.testing.assert_array_equal(quotes[field], expected)
            check("同原行気配の" + field + "_" + label, True)
        for field in ("last", "price"):
            if field in quotes:
                np.testing.assert_array_equal(quotes[field], last)
                check("同原行気配Last_" + label, True)
        bid, ask, valid = (np.asarray(quotes[name]) for name in ("bid", "ask", "quote_valid"))
        check("気配shape_" + label, all(value.shape == (n,) for value in (bid, ask, valid)))
        normal = np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask > bid)
        check("正常気配flagは適格価格を要求_" + label, not np.any(valid & ~normal))
        terminal = np.flatnonzero((times > limit) & valid)
        check("次原行場内全返済可能_" + label, len(terminal) > 0 and times[terminal[0]] < close)
        feature = data["features"][key]
        check("元十列を維持_" + label, len(feature["columns"]) == 10 and all(len(value) == n for value in feature["columns"]))
        check("元validとG許可のshape_" + label, np.asarray(feature["valid"]).shape == (n,) and
              np.asarray(data["gates"][key]).shape == (n,) and np.asarray(data["gates"][key]).dtype == np.bool_)
        check("入口信号shape_" + label, np.asarray(data["signals"]["entry"][key]).shape == (n,))
        for code in ("B00", "B01"):
            source = np.asarray(data["signals"][code][key]["source_row"])
            check("信号元row未来参照なし_" + code + "_" + label, source.shape == (n,) and np.all(source <= np.arange(n)))
        expected = market_expected(data["inputs"], key)
        np.testing.assert_array_equal(expected, data["markets"][key])
        check("全市場12列の独立因果対応_" + label, True)
        rows.append(dict(session=scene, symbol=key[1], rows=n, first_seq=int(sequence[0]), last_seq=int(sequence[-1]),
                         start=start, observation_end=end, limit=limit, actual_close=close,
                         first_time=float(times[0]), final_time=float(times[-1]),
                         first_normal_quote_after_limit_row=int(terminal[0]),
                         first_normal_quote_after_limit_time=float(times[terminal[0]]),
                         valid_quotes=int(valid.sum()), gate_allowed_rows=int(np.asarray(data["gates"][key]).sum())))
    return rows


def inputs(manifest_path: Path) -> dict:
    """
    機能: 完成目録と2packetの資格だけを照合する。
    引数: manifest_path(Path)は金融前入力準備目録。
    返り値: dictは合否・読取履歴・4口座の入力資格。
    """
    source_proof_path = HERE / "旧最終人工と現数値核の同bytes継承.json"
    source_proof = read_json(source_proof_path)
    check("数値核継承済み", source_proof["passed"])
    for name, expected in source_proof["sources"].items():
        check("監査後数値核不変_" + name, sha((ROOT / name).read_bytes()) == expected)
    manifest = read_json(manifest_path)
    check("入力準備合格", manifest.get("passed", manifest.get("全合格", False)))
    packets = manifest["packets"]
    check("追加二場だけ", len(packets) == 2 and {item["session"] for item in packets} == set(SCENES))
    accounts = []
    for item in packets:
        accounts.extend(packet(item))
    check("独立した4口座", len(accounts) == 4 and len({(row["session"], row["symbol"]) for row in accounts}) == 4)
    return dict(passed=True, source_proof=dict(path=source_proof_path.relative_to(ROOT).as_posix(),
                                             sha256=sha(source_proof_path.read_bytes())),
                input_manifest=dict(path=manifest_path.relative_to(ROOT).as_posix(), sha256=sha(manifest_path.read_bytes())),
                accounts=accounts, checks=CHECKS, owned_packet_reads=READS,
                original_market_reads=0, financial_replays=0, API=0, real_orders=0,
                limit="板Lastは価格時計。真の配信受信時刻やmini/microの執行可能性を証明しない。G公開120秒/相手60秒・ATR公開360秒は同bytes旧独立人工証拠を適用する。",
                producer_sha256=sha(Path(__file__).read_bytes()))


def main() -> None:
    """
    機能: 指定された源監査又は入力監査を一度だけ保存する。
    引数: コマンドラインの--sources(bool)又は--manifest(str)。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sources", action="store_true")
    group.add_argument("--manifest")
    args = parser.parse_args()
    if args.sources:
        result, name = sources(), "旧最終人工と現数値核の同bytes継承.json"
    else:
        path = (ROOT / args.manifest).resolve()
        result, name = inputs(path), "追加二場の入力と時計及び場内終端の独立監査.json"
    save(name, result)
    print(json.dumps(dict(passed=True, checks=len(CHECKS), output=(HERE / name).relative_to(ROOT).as_posix()), ensure_ascii=False))


if __name__ == "__main__":
    main()
