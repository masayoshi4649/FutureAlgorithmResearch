"""市場を読まず、因果公開足と次原rowの最良気配接続を人工検査する。"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from io import BytesIO
import hashlib
import json
from pathlib import Path

import numpy as np

import input119


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SESSION = "2026-10-16_Day"
START, END = input119.SOURCE.bounds(SESSION)
CHECKS = 0


# ----------------------------------------


def check(value: bool) -> None:
    """
    機能: 純人工の期待条件を数え、不一致なら直ちに停止する。
    引数: value(bool) は期待条件。
    返り値: None。
    """
    global CHECKS
    assert bool(value)
    CHECKS += 1


def record(seconds: float, price: object, bid: object = 4000.0, ask: object = 4000.5,
           quantity: object = 5.0) -> dict:
    """
    機能: 市場と無関係な固定場の合成JSON行を作る。
    引数: seconds(float) は場開始からの秒、price/bid/ask/quantity(object) は合成値。
    返り値: dict は118の抽出契約に対応する一行。
    """
    stamp = datetime.fromtimestamp(START + seconds, timezone(timedelta(hours=9))).isoformat()
    out = dict(Symbol="人工TOPIX", SymbolName="合成", Exchange=23,
               CurrentPriceTime=stamp, CurrentPrice=price,
               TradingVolume=100.0 + seconds, TradingVolumeTime=stamp)
    for side, best, sign in (("Buy", bid, -1), ("Sell", ask, 1)):
        for depth in range(10):
            value = best + sign * depth * .5 if isinstance(best, (int, float)) else best
            out[f"{side}{depth + 1}"] = dict(Price=value, Qty=quantity)
    return out


def arrays(records: list[dict]) -> dict:
    """
    機能: 合成行を118の原列と公表出来高資格へ変換する。
    引数: records(list[dict]) は合成原順。
    返り値: dict[str,ndarray] は未補完の人工原列。
    """
    out = input119.SOURCE.parse_records(records)
    usable, delta = input119.SOURCE.volume_contract(out, START, END)
    out["volume_delta_usable"], out["volume_delta"] = usable, delta
    return out


def info(path: Path | None = None, kind: str = "old_npz") -> dict:
    """
    機能: 純人工入力の小目録を作る。
    引数: path(Path|None) は人工ファイル、kind(str) はloader形式。
    返り値: dict は場・商品・観測窓と存在時の指紋。
    """
    out = dict(session=SESSION, symbol="TOPIX", bounds=[START, END], kind=kind)
    if path is not None:
        payload = path.read_bytes()
        stat = path.stat()
        out.update(path=path.relative_to(ROOT).as_posix(), bytes=len(payload),
                   mtime_ns=stat.st_mtime_ns, SHA256=hashlib.sha256(payload).hexdigest())
    return out


def legacy44(values: dict) -> dict:
    """
    機能: 旧44列loaderの純人工互換fixtureを作る。
    引数: values(dict[str,ndarray]) は合成原列。
    返り値: dict[str,ndarray] は必要原列を保持した44列。旧生成元全体の再検証ではない。
    """
    n = len(values["raw_seq"])
    schema = json.loads((ROOT / "work/topix10pt_20261016/入力目録と時系列分割.json").read_text(encoding="utf-8"))["old_schema"]
    out = {}
    for name, description in schema.items():
        if name in values:
            out[name] = values[name].copy()
        elif name == "normal_execution_row":
            out[name] = np.arange(n, dtype=np.int32)
        elif name == "execution_to_raw_index":
            out[name] = np.arange(n, dtype=np.int64)
        else:
            shape = (n, 10) if len(description["shape"]) == 2 else (n,)
            out[name] = np.zeros(shape, dtype=description["dtype"])
    assert len(out) == 44
    return out


def main() -> None:
    """
    機能: 価格・気配・公開順・欠測・二loaderの純人工検査を保存する。
    引数: なし。
    返り値: None。原市場・実成績・APIへの接続を行わない。
    """
    destination = HERE / "input_artificial119"
    destination.mkdir(exist_ok=False)
    rows = [
        record(0, 4000), record(30, 4001, bid=4002, ask=4002),
        record(60, 4002, bid=4002, ask=4002), record(60, 4002, bid=4001.5, ask=4002),
        record(59, 9999), record(61, None), record(62, 4003, quantity=0),
        record(180, 4004), record(181, 4005, bid=4006, ask=4005),
        record(240, 4006),
    ]
    values = arrays(rows)
    made = input119.prepare(values, info(), "TOPIX")
    bars, quotes, diag = made["bars"], made["quotes"], made["diagnostics"]
    check(quotes["row"].tolist() == [0, 3, 7, 9])
    check(diag["accepted_price_rows"] == 8)
    check(diag["accepted_quote_rows"] == 4)
    check(diag["accepted_price_rows_without_valid_quote"] == 4)
    check(bars["close"][0] == 4001)
    check(bars["high"][0] == 4001)
    check(bars["pub_raw_row"][0] == 2)
    check(bars["anchor"][0] == 4002)
    next_index = np.searchsorted(quotes["row"], bars["pub_raw_row"][0], side="right")
    check(quotes["row"][next_index] == 3)
    check(quotes["time"][next_index] == bars["pub_price_time_s"][0])
    check(bars["closed"][2] and not bars["valid"][2] and np.isnan(bars["close"][2]))
    check(bars["valid"][3] and bars["pub_raw_row"][3] == 9)
    check(not bars["valid"][4] and not bars["closed"][4] and bars["pub_raw_row"][4] == -1)
    check(not diag["window_complete"])
    check(diag["stale_clock_rows"] == 1)
    for name, value in quotes.items():
        check(value.dtype == (np.dtype("int64") if name in ("row", "seq") else np.dtype("float64")))
    check(all(value.shape == (4,) for value in quotes.values()))

    # ----------------------------------------
    # 前方prefixの公開足と正常気配が、未観測の長い接尾で変更されない。
    for cut in range(1, len(rows) + 1):
        short = input119.prepare(arrays(rows[:cut]), info(), "TOPIX")
        q = short["quotes"]
        mask = made["quotes"]["row"] < cut
        for key in q:
            np.testing.assert_array_equal(q[key], made["quotes"][key][mask])
            check(True)
        public = short["bars"]["valid"]
        for key in ("open", "high", "low", "close", "anchor", "pub_raw_row", "pub_price_time_s"):
            np.testing.assert_array_equal(short["bars"][key][public], bars[key][public])
            check(True)

    # ----------------------------------------
    # 入力は作成したfixtureだけ。旧NPZと新JSONLは各一読の同じ足・気配を返す。
    raw_path = destination / "合成.jsonl"
    raw_path.write_text("".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows), encoding="utf-8")
    old_path = destination / "合成.npz"
    memory = BytesIO()
    np.savez_compressed(memory, **legacy44(values))
    old_path.write_bytes(memory.getvalue())
    loaded = [input119.load(info(old_path), "TOPIX"), input119.load(info(raw_path, "jsonl"), "TOPIX")]
    for result in loaded:
        for group in ("bars", "quotes"):
            for key in made[group]:
                np.testing.assert_array_equal(result[group][key], made[group][key])
                check(True)
        check(result["read_metadata"]["reads"] == 1)
        check(result["read_metadata"]["rows"] == len(rows))
    empty = input119.prepare(arrays([record(0, 4000, bid=4001, ask=4000)]), info(), "TOPIX")
    check(all(len(value) == 0 for value in empty["quotes"].values()))
    check(empty["diagnostics"]["accepted_price_rows"] == 1)
    check(empty["diagnostics"]["accepted_quote_rows"] == 0)
    proof = dict(全合格=True, 検査数=CHECKS, 市場入力読取=0, 市場結果読取=0, 金融=0, API=0,
                 合成loader読取=dict(old_npz=1, jsonl=1),
                 観測窓=dict(Day="08:45以上15:40未満", Night="17:00以上翌05:55未満"),
                 上流源SHA256=hashlib.sha256(input119.UPSTREAM.read_bytes()).hexdigest(),
                 源SHA256={name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                              for name in ("input119.py", "artificial_input119.py")})
    output = destination / "現在値と気配の資格及び公開後次原row接続の純人工検査.json"
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == "__main__":
    main()
