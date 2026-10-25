"""00143 の保存入力・通知・約定を Go 移植照合用へ分離する。売買核は実行しない。"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESEARCH = ROOT / "work/nikkei143_20261024"
sys.path.insert(0, str(RESEARCH))
import common143 as shared

SCENES = ("2026-10-22_Day", "2026-10-21_Night", "2026-10-15_Day", "2026-09-29_Day")
ORDER_COLUMNS = ["約定行", "判断行", "親ID", "注文方向", "枚数", "約定価格", "理由", "新規", "玉ID", "手数料円"]
NOTICE_COLUMNS = ["判断行", "親ID", "注文方向", "枚数", "理由", "新規", "玉ID"]
MARKET_COLUMNS = ["価格時計", "Last", "bid", "ask", "気配正常", "公開ATR", "原seq"]
FEATURE_COLUMNS = ["高40", "安40", "効率40", "差5", "差40", "平均5", "平均40", "始値中値", "帯資料時計",
    "正規化幅", "中値", "短ATR", "自己30秒比", "自己120秒比", "相手差5", "相手差40", "相手効率40",
    "相手始値中値", "相手正規化幅", "相手中値", "相手30秒比", "相手120秒比", "相手原時計", "相手帯時計",
    "自己OFI30秒平均", "自己距離厚さ30秒平均", "相手OFI30秒平均", "相手距離厚さ30秒平均", "自己差20", "相手差20"]
BAND_COLUMNS = ["高値", "安値", "効率", "差5", "差期間", "平均5", "平均期間", "始値中値", "資料時計"]
HISTORY_COLUMNS = ["平均5", "平均20", "標準偏差20", "高20", "安20", "効率20", "差5", "差20", "始値", "資料時計", "相手差5", "相手差20", "相手効率20", "相手始値差", "相手資料時計"]


def digest(path):
    """
    機能: 元ファイルを変更せず SHA256 を算出する。
    引数: path(Path) は読取対象。
    返り値: str は内容指紋。
    """
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value, compressed=False):
    """
    機能: JSON を再現可能な gzip 又は UTF-8 へ保存する。
    引数: path(Path)、value(dict)、compressed(bool) は出力条件。
    返り値: None。NaN は許さず、将来資料は期待ファイルに限る。
    """
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    path.write_bytes(gzip.compress(raw, compresslevel=6, mtime=0) if compressed else raw)


def matrix(path, values, columns):
    """
    機能: 行を間引かず little-endian float64 行列を gzip 保存する。
    引数: path(Path)、values(ndarray)、columns(list[str]) は出力と列仕様。
    返り値: dict は行列の型・寸法・指紋。NaN は未知値として保持する。
    """
    values = np.ascontiguousarray(values, dtype="<f8")
    assert values.ndim == 2 and values.shape[1] == len(columns)
    raw = values.tobytes()
    path.write_bytes(gzip.compress(raw, compresslevel=6, mtime=0))
    return dict(file=path.name, rows=len(values), columns=columns, dtype="little-endian float64", order="row-major",
                bytes=path.stat().st_size, sha256=digest(path), uncompressed_sha256=hashlib.sha256(raw).hexdigest())


def notices(orders):
    """
    機能: 保存注文から当時の判断通知だけを抽出する。
    引数: orders(ndarray[M,10]) は凍結した注文。
    返り値: list[list[int]] は判断行で配信する通知。約定行・約定値・費用・完結損益を含まない。
    """
    ix = np.argsort(orders[:, 1], kind="stable")
    return orders[ix][:, [1, 2, 3, 4, 6, 7, 8]].astype(np.int64).tolist()


def validate_saved(orders, ready, quotes):
    """
    機能: 凍結注文の数量・気配・会計を独立に検算する。
    引数: orders(ndarray[M,10])、ready/quotes(dict) は既存保存値。
    返り値: dict は保存会計。新しい発注判断は生成しない。
    """
    normal = np.flatnonzero(quotes["quote_valid"] & np.isfinite(quotes["bid"]) & np.isfinite(quotes["ask"])
        & (quotes["bid"] > 0) & (quotes["ask"] > quotes["bid"]))
    balance, gross, fees = {}, 0., 0.
    for row in orders:
        fill, source, parent, side, qty, price, reason, new, ticket, fee = row
        fill, source = int(fill), int(source)
        assert fill > source and fill == normal[np.searchsorted(normal, source, side="right")]
        actual = quotes["ask" if side > 0 else "bid"][fill]
        assert abs(price-actual) < 1e-8
        assert fee == int(qty*385)//10
        key = int(parent), int(ticket)
        balance[key] = balance.get(key, 0) + int(qty) * (1 if new else -1)
        assert balance[key] >= 0
        gross -= side*qty*price*100
        fees += fee
    assert all(q == 0 for q in balance.values())
    return dict(orders=len(orders), gross=gross, fees=fees, net=gross-fees, flat=True)


def extract(scene, packet_item, output):
    """
    機能: 一場の当時観測と源通知を、期待約定・期待判断から物理分離する。
    引数: scene(str)、packet_item(dict)、output(Path) は対象と出力。
    返り値: dict は入出力の目録。特徴準備以外の再生関数は呼ばない。
    """
    packet = shared.packet_from(packet_item)
    data, _, _, histories = shared.previous.prepared(packet)
    references = {packet_item["path"]: packet_item["sha256"]}
    key = scene, "NK225"
    ready, quote = data["NK225"]["ready"], data["NK225"]["quotes"]
    day = scene.endswith("_Day")
    archives = []
    for round_no in (1, 2, 3):
        path = RESEARCH/f"round{round_no}/measurement/NK225_{scene}.npz"
        references[str(path.relative_to(ROOT))] = digest(path)
        with np.load(path) as z:
            archives.append({name: z[name] for name in z.files})
    a, b, c = archives
    sources = dict(B0=a["B0"], CG00=b["O17"] if day else a["O02"], A3=a["A3"],
                   CA00=a["E01"] if day else b["R00"], CS00=a["S01"] if day else b["L00"])
    for name in ("CG00", "CA00", "CS00"):
        np.testing.assert_array_equal(sources[name], c[name])
    matrices = {}
    for symbol in ("NK225", "TOPIX"):
        d = data[symbol]; r, q = d["ready"], d["quotes"]
        prefix = f"{symbol}_{scene}"
        market = np.column_stack((r["time_s"], r["last"], q["bid"], q["ask"], q["quote_valid"], r["atr"], r["seq"]))
        h20 = shared.previous.first.original.history(r["time_s"], d["features"][:, 10], r["start"], 20)
        h40 = shared.previous.first.original.history(r["time_s"], d["features"][:, 10], r["start"], 40)
        fields = dict(market=matrix(output/(prefix+"_market.f64.gz"), market, MARKET_COLUMNS),
                      features=matrix(output/(prefix+"_features.f64.gz"), d["features"], FEATURE_COLUMNS),
                      band20=matrix(output/(prefix+"_band20.f64.gz"), h20, BAND_COLUMNS),
                      band40=matrix(output/(prefix+"_band40.f64.gz"), h40, BAND_COLUMNS),
                      history=matrix(output/(prefix+"_history.f64.gz"), histories[scene,symbol], HISTORY_COLUMNS))
        matrices[symbol] = fields
        raw_features = ROOT/f"work/raw_diagnosis141_20261024/raw_features/{prefix}.npz"
        references[str(raw_features.relative_to(ROOT))] = digest(raw_features)
    source = dict(schema=1, session=scene, symbol="NK225", start=float(ready["start"]), end=float(ready["limit"]),
        us_open=float(ready["us_open"]) if np.isfinite(ready["us_open"]) else None,
        tick=float(ready["tick"]), point_value=100, fee_per_contract=38.5, matrices=matrices,
        notice_columns=NOTICE_COLUMNS, notices={name:notices(o) for name,o in sources.items()},
        warning="通知は判断行に到達してから公開する。期待ファイルは戦略へ渡さない。価格時計同秒でも原行を保持する。")
    input_path = output/(scene+"_input.json.gz")
    write_json(input_path, source, True)
    selected = dict(sources, **{name:c[name] for name in ("CG04", "CA04", "CS04", "TG04", "PG04")})
    accounts = {name:validate_saved(o, ready, quote) for name,o in selected.items()}
    path = RESEARCH/f"round3/traces/NK225_{scene}.npz"
    references[str(path.relative_to(ROOT))] = digest(path)
    with np.load(path) as z:
        traces = {name:z[name].tolist() for name in ("CG04", "CA04", "CS04")}
    expected = dict(schema=1, session=scene, order_columns=ORDER_COLUMNS,
        orders={name:o.tolist() for name,o in selected.items()}, traces=traces, accounts=accounts,
        warning="期待値専用。親の未来損益・約定価格・約定行を実行判断へ渡さない。")
    expected_path = output/(scene+"_expected.json.gz")
    write_json(expected_path, expected, True)
    residual = {name:dict(retained=sum(int(x[2])==3 for x in rows), skipped=sum(int(x[2])==1 and int(x[4])==0 for x in rows)) for name,rows in traces.items()}
    return dict(session=scene, input=input_path.name, input_sha256=digest(input_path), expected=expected_path.name,
        expected_sha256=digest(expected_path), references=references, residual=residual,
        input_rows={s:m["market"]["rows"] for s,m in matrices.items()}, accounts=accounts,
        matrix_bytes=sum(m["bytes"] for s in matrices.values() for m in s.values()))


def main():
    """
    機能: 指定四場を保存結果だけから抽出し、全資料の指紋と限界を残す。
    引数: CLI --sessions は既存場名、--output は生成先。
    返り値: None。研究の注文核・API・実注文は実行しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", nargs="+", default=list(SCENES))
    parser.add_argument("--output", type=Path, default=HERE/"fixtures")
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    packets, _, _ = shared.material(); packets = {p["session"]:p for p in packets}
    cases = []
    for scene in args.sessions:
        cases.append(extract(scene, packets[scene], args.output))
        print(scene, "保存資料の抽出完了", cases[-1]["input_rows"], flush=True)
    source_files = [Path(__file__), RESEARCH/"common143.py", RESEARCH/"profit_residual143.py",
        RESEARCH/"core_overlay_v2_143.py", ROOT/"work/conditional142_20261024/run142.py",
        ROOT/"work/aggressive140_20261024/active140_v2.py", ROOT/"work/raw_diagnosis141_20261024/evidence141.py"]
    manifest = dict(schema=1, scope="既存00143仕様の移植同値。新金融探索・成績の追加証拠ではない。",
        code={str(p.relative_to(ROOT)):digest(p) for p in source_files}, cases=cases,
        limitations=["ラージBBOをmini約定へ代用", "価格時計・原行順であり実受信遅延ではない",
            "板24～27列は全原行特徴を参照する。packetのみ再生では原板欠落行の分だけ異なり得る。",
            "入力特徴の生成検査と入力特徴からの売買核検査を分ける。"], new_financial_replays=0, live_orders=0)
    write_json(args.output/"manifest.json", manifest)


if __name__ == "__main__":
    main()
