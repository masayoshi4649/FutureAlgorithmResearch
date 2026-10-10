"""管理比較台帳を原本気配と別会計器から全件検算する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

from independent_account import reconstruct, near, save


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]


def read(path: Path) -> object:
    """機能: 既存 JSON 又は pickle を読み取り専用で取得する。

    引数: path(Path)。返り値: 内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == ".pkl" else json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    """機能: 保存ファイルの実バイト列の指紋を算出する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trade_array(details: list[dict]) -> np.ndarray:
    """機能: 別会計の部分決済を被検査台帳と同じ列順へ変換する。

    引数: details(list[dict])。返り値: 12 列の決済配列(np.ndarray)。
    """
    return np.asarray([[t["campaign"], t["entry_row"], t["exit_row"], t["side"],
        t["quantity"], t["entry"], t["exit"], t["entry_fee"], t["exit_fee"],
        t["gross"], t["net"], t["role"]] for t in details], dtype=float).reshape((-1, 12))


def check_account(key: tuple, data: dict, stored: dict, reported: dict) -> dict:
    """機能: 一口座の全注文・部分決済・全行評価指紋を独立照合する。

    引数: key(tuple)、data/stored/reported(dict)。返り値: 監査指標(dict)。
    """
    account, curve = reconstruct(data, dict(symbol=key[1], session=key[0], orders=stored["orders"]))
    other_trades = trade_array(account["details"])
    assert stored["trades"].shape == other_trades.shape
    np.testing.assert_allclose(stored["trades"], other_trades, atol=1.e-4, rtol=0)
    assert stored["curve_hash"] == account["curve_hash"], ("全原本行 MTM 指紋", key)
    required = ("gross", "fees", "net", "profit", "loss", "wins", "losses", "trades",
        "winning_lots", "losing_lots", "flat_lots", "drawdown", "equity_min", "equity_max",
        "max_long", "max_short")
    for field in required:
        assert field in reported, ("報告指標なし", field)
        near(float(reported[field]), float(account[field]), field)
    for field in ("campaigns", "campaign_profit", "campaign_loss", "campaign_wins", "campaign_losses",
        "campaign_flats", "max_campaign_loss", "entry_orders", "exit_orders", "flats", "core_net", "cover_net"):
        if field in reported:
            near(float(reported[field]), float(account[field]), field)
    counters = stored["counters"]
    if isinstance(counters, dict):
        assert counters["終端買い保有"] == counters["終端売り保有"] == counters["継続組数"] == 0
        assert counters["最大買い保有"] == account["max_long"]
        assert counters["最大売り保有"] == account["max_short"]
    else:
        assert counters[0] == account["max_long"] and counters[1] == account["max_short"]
        assert counters[2] == counters[3] == counters[4] == 0
        assert counters[5] == account["campaigns"]
    first = []
    for campaign in sorted({int(order[2]) for order in stored["orders"]}):
        order = next(order for order in stored["orders"] if int(order[2]) == campaign)
        assert int(order[7]) == 1 and int(order[8]) == 0, ("初回元玉", order)
        assert int(order[4]) == (10 if key[1] == "TOPIX" else 20), ("初回最大枚数", order)
        first.append([int(order[0]), int(order[1]), int(order[3]), int(order[4])])
    del account["details"]
    account["initial_orders"] = first
    account["原本行数"] = len(curve)
    account["注文数"] = len(stored["orders"])
    account["合格"] = True
    return account


def main() -> None:
    """機能: 指定 shard の全管理条件を検算し監査専用 JSON を保存する。

    引数: CLI の shard/shards(int)。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--area", default="")
    parser.add_argument("--label", default="台帳独立監査")
    args = parser.parse_args()
    ready = read(ROOT / "work/wave_v69/prepared/inputs.pkl")
    features = read(ROOT / "work/wave_v69/prepared/features.pkl")
    schedule = read(WORK / "inputs/schedule.pkl")
    area = WORK / args.area
    assert area.resolve().is_relative_to(WORK)
    paths = sorted((area / "results").glob("*.json"))[args.shard::args.shards]
    assert paths, "被検査結果なし"
    records = []
    count = 0
    for path in paths:
        packet = read(path)
        identifier = packet["config"]["id"]
        ledger_path = area / "ledgers" / (identifier + ".pkl")
        ledgers = read(ledger_path)
        assert packet["ledger_SHA256"] == digest(ledger_path)
        rows = {(r["session"], r["symbol"]): r for r in packet["rows"]}
        assert len(rows) == len(ledgers) == 56
        details = []
        for key, stored in sorted(ledgers.items()):
            data = dict(time_s=ready[key]["time_s"], seq=ready[key]["seq"],
                bid=features[key]["bid"], ask=features[key]["ask"])
            other = check_account(key, data, stored, rows[key])
            common = schedule[key][packet["config"]["source_index"]]
            expected = [[int(o[0]), int(o[1]), int(o[3]), 10 if key[1] == "TOPIX" else 20] for o in common]
            assert other["initial_orders"] == expected, ("全管理の共通満額入口", key, identifier)
            details.append(other)
            count += 1
        records.append(dict(ID=identifier, 設定=packet["config"], 合格=True,
            口座=details, 台帳SHA256=digest(ledger_path), 結果SHA256=digest(path)))
        print(f"独立会計 {identifier}: 56 口座合格", flush=True)
    save(HERE / f"{args.label}_{args.shard}of{args.shards}.json", dict(
        合格=True, 条件数=len(records), 口座数=count, 条件=records))


if __name__ == "__main__":
    main()
