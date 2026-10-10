"""全ティックIFD条件の台帳・原本気配・時価曲線・期間集計を独立検算する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

from independent_account import reconstruct, fee, near, save, INITIAL, POINT


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
REASONS = (1, 2, 3, 4, 10, 11)


def read(path: Path) -> object:
    """機能: 保存されたJSON又はpickleを読み取り専用で読む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == ".pkl" else json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    """機能: 入力又は保存台帳の指紋を一定メモリーで計算する。

    引数: path(Path)。返り値: SHA256の十六進文字列(str)。
    """
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(4*1024*1024):
            value.update(block)
    return value.hexdigest()


def compare(left: object, right: object, label: str) -> None:
    """機能: 未定義値と数値誤差を区別して集計値を照合する。

    引数: left/right(object)、label(str)。返り値: なし(None)。
    """
    if left is None or right is None:
        assert left is None and right is None, (label, left, right)
    else:
        near(float(left), float(right), label)


def check_account(key: tuple, ready: dict, data: dict, stored: dict, row: dict) -> tuple[dict, np.ndarray]:
    """機能: 元注文をFIFOと次行気配で会計し、取引列と全行曲線指紋を照合する。

    引数: key(tuple)、ready/data/stored/row(dict)。返り値: 独立集計と曲線(tuple[dict,np.ndarray])。
    """
    symbol = key[1]
    for name in ("seq", "time_s", "last"):
        np.testing.assert_array_equal(ready[name], data[name])
    ledger = dict(symbol=symbol, session=key[0], orders=stored["orders"],
        fees=[fee(symbol, int(order[4])) for order in stored["orders"]])
    result, curve = reconstruct(data, ledger)
    quantity, value = INITIAL[symbol], POINT[symbol]
    derived = result.pop("details")
    expected_trades = np.asarray([[trade["campaign"], trade["entry_row"], trade["exit_row"], trade["side"],
        trade["quantity"], trade["entry"], trade["exit"], fee(symbol, trade["quantity"]), fee(symbol, trade["quantity"]),
        trade["gross"], trade["net"]] for trade in derived], dtype=float).reshape((-1, 11))
    np.testing.assert_array_equal(expected_trades, stored["trades"])
    assert hashlib.sha256(curve.tobytes()).hexdigest() == stored["curve_hash"], ("全原本行の清算時価指紋", key)
    result.update(drawdown=result["max_drawdown"], equity_min=result["min_equity"], equity_max=result["max_equity"],
        max_trade_loss=result["max_campaign_loss"], net_ticks=result["net"]/(quantity*value*ready["tick"]))
    result["ideal_net"] = sum(trade["side"]*quantity*value*(data["mid"][trade["exit_row"]]-data["mid"][trade["entry_row"]])
        for trade in derived)-result["fees"]
    result["hold_median"] = float(np.median([ready["time_s"][trade["exit_row"]]-ready["time_s"][trade["entry_row"]]
        for trade in derived])) if derived else None
    for name in ("gross", "fees", "net", "profit", "loss", "wins", "losses", "flats", "trades", "winning_lots",
        "losing_lots", "flat_lots", "max_long", "max_short", "drawdown", "equity_min", "equity_max", "max_trade_loss",
        "net_ticks", "ideal_net", "hold_median"):
        compare(result[name], row[name], f"{key}:{name}")
    counters = stored["counters"]
    assert counters[0] == 0 and counters[1] in (0, 1)
    assert len(stored["orders"]) == 2*len(stored["trades"])
    for name, index in (("parent_submitted", 3), ("parent_triggered", 4), ("parent_canceled", 5)):
        assert row[name] == int(counters[index])
    counts = {str(reason):sum(int(order[6]) == reason for order in stored["orders"]) for reason in REASONS}
    assert counts == row["reasons"]
    result["orders"] = len(stored["orders"])
    result["curve_rows"] = len(curve)
    result["reasons"] = counts
    return result, curve


def check_period(results: dict, curves: dict, symbol: str, names: list[str], stored: dict) -> None:
    """機能: 場会計を合計し、全原本行を連結した料金後の期間下落を独立照合する。

    引数: results/curves(dict)、symbol(str)、names(list[str])、stored(dict)。返り値: なし(None)。
    """
    keys = sorted(key for key in results if key[1] == symbol and key[0] in names)
    rows = [results[key] for key in keys]
    fields = ("profit", "loss", "net", "gross", "fees", "wins", "losses", "flats", "trades", "winning_lots",
        "losing_lots", "flat_lots", "net_ticks")
    total = {name:sum(row[name] for row in rows) for name in fields}
    for name in fields:
        compare(total[name], stored[name], "期間合計:"+name)
    activity = sum(row["trades"] > 0 for row in rows)
    positive = sum(row["net"] > 0 for row in rows)
    assert activity == stored["active_sessions"] and positive == stored["positive_sessions"]
    assert len(rows) == stored["sessions"]
    compare(total["wins"]/total["trades"] if total["trades"] else None, stored["win_rate"], "期間勝率")
    compare(total["net_ticks"]/total["trades"] if total["trades"] else None, stored["mean_net_ticks"], "期間平均呼値")
    payoff = ((total["profit"]/total["winning_lots"])/(total["loss"]/total["losing_lots"])) if total["winning_lots"] and total["losing_lots"] else None
    compare(payoff, stored["payoff"], "期間枚数平均勝負比")
    compare(max((row["max_trade_loss"] for row in rows), default=0.), stored["max_trade_loss"], "最大取引損失")
    compare(max((row["drawdown"] for row in rows), default=0.), stored["max_session_drawdown"], "最大場内下落")
    compare(sum(row["ideal_net"] for row in rows), stored["ideal_net"], "中値価格感度")

    # ----------------------------------------
    # 各場の曲線を累積実現損益へずらして逐行の期間最高値を求める。
    offset = peak = drawdown = 0.0
    for key in keys:
        shifted = curves[key]+offset
        chronological_peak = np.maximum.accumulate(np.maximum(shifted, peak))
        drawdown = max(drawdown, float(np.max(chronological_peak-shifted)))
        peak = max(peak, float(np.max(shifted)))
        offset += results[key]["net"]
    compare(drawdown, stored["drawdown"], "原本時価連結の期間最大下落")
    compare(offset, total["net"], "曲線連結の場末現金")
    compare(total["net"]-max((row["net"] for row in rows), default=0.), stored["without_best_session"], "最大勝ち場除外")


def run(shard: int, shards: int) -> None:
    """機能: 分担した保存条件の全56口座と三期間を独立検算する。

    引数: shard/shards(int)。返り値: なし(None)。
    """
    fixed = read(WORK/"事前固定.json")
    hashes = {name.replace("\\", "/"):value for name, value in fixed["SHA256"].items()}
    assert digest(WORK/"prepared/inputs.pkl") == hashes["prepared/inputs.pkl"]
    assert digest(WORK/"prepared/features.pkl") == hashes["prepared/features.pkl"]
    inputs, features = read(WORK/"prepared/inputs.pkl"), read(WORK/"prepared/features.pkl")
    assert len(inputs) == len(features) == 56
    records = []
    selected = fixed["条件"][shard::shards]
    for config in selected:
        name = config["id"]
        path, ledger_path = WORK/"results"/(name+".json"), WORK/"ledgers"/(name+".pkl")
        packet, ledgers = read(path), read(ledger_path)
        assert packet["config"] == config
        assert digest(ledger_path) == packet["ledger_SHA256"]
        assert set(ledgers) == set(inputs)
        rows = {(row["session"], row["symbol"]):row for row in packet["rows"]}
        assert len(rows) == len(packet["rows"]) == 56
        results, curves = {}, {}
        for key in sorted(inputs):
            results[key], curves[key] = check_account(key, inputs[key], features[key], ledgers[key], rows[key])
        for label, names in (("前16", fixed["前16"]), ("後12", fixed["後12"]), ("全28", fixed["全セッション"])):
            for symbol in ("TOPIX", "NK225"):
                check_period(results, curves, symbol, names, packet["periods"][label][symbol])
        records.append(dict(ID=name, 合格=True, 結果SHA256=digest(path), 台帳SHA256=packet["ledger_SHA256"],
            口座数=len(results), 新規返済注文数=sum(result["orders"] for result in results.values()),
            決済取引数=sum(result["trades"] for result in results.values()),
            全行時価照合数=sum(result["curve_rows"] for result in results.values()),
            口座=list(results.values())))
        if len(records) % 8 == 0 or len(records) == len(selected):
            print(f"分担{shard}/{shards}: {len(records)}/{len(selected)} 条件の独立検算合格", flush=True)
    save(HERE/f"台帳独立監査_{shard}of{shards}.json", dict(全合格=True, 分担=shard, 分担数=shards,
        固定SHA256=digest(WORK/"事前固定.json"), 監査SHA256=digest(Path(__file__)), 記録=records))


def combine(shards: int) -> None:
    """機能: 全分担の監査を集合照合し、漏れのない全192条件の監査証跡を保存する。

    引数: shards(int)。返り値: なし(None)。
    """
    fixed = read(WORK/"事前固定.json")
    records = []
    for shard in range(shards):
        part = read(HERE/f"台帳独立監査_{shard}of{shards}.json")
        assert part["全合格"] and part["固定SHA256"] == digest(WORK/"事前固定.json")
        records.extend(part["記録"])
    assert len(records) == len(fixed["条件"])
    assert {record["ID"] for record in records} == {config["id"] for config in fixed["条件"]}
    result = dict(全合格=True, 条件数=len(records), 口座数=sum(record["口座数"] for record in records),
        注文数=sum(record["新規返済注文数"] for record in records), 決済取引数=sum(record["決済取引数"] for record in records),
        全行時価照合数=sum(record["全行時価照合数"] for record in records),
        固定SHA256=digest(WORK/"事前固定.json"), 監査SHA256=digest(Path(__file__)),
        検査=["判断行より後の原本約定", "買ask売bid", "独立FIFO", "整数注文料金", "全取引列", "全原本行MTM曲線指紋",
            "場内返済", "片方向上限", "利益損失枚数", "前16・後12・全28", "全期間原本時価の最大下落"],
        記録=sorted(records, key=lambda record:record["ID"]))
    save(HERE/"全条件の独立監査.json", result)
    print(result["条件数"], "条件", result["口座数"], "口座", result["注文数"], "注文の独立検算合格", flush=True)


def main() -> None:
    """機能: 指定分担の会計監査、又は完成した全分担の統合を実行する。

    引数: --shard/--shards(int)、--combine(bool)。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--combine", action="store_true")
    args = parser.parse_args()
    assert 0 <= args.shard < args.shards
    combine(args.shards) if args.combine else run(args.shard, args.shards)


if __name__ == "__main__":
    main()
