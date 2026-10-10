"""実原本での入口後因果検査と、前半だけの四機構選定を独立照合する。"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys

import numba
import numpy as np

from audit_all import read, digest
from independent_account import save, INITIAL, POINT, near


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
numba.config.CACHE_DIR = str(HERE/"numba_cache")
SPEC = importlib.util.spec_from_file_location("tick69_real_prefix_audit_engine", WORK/"engine.py")
ENGINE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ENGINE
SPEC.loader.exec_module(ENGINE)


def replay(ready: dict, feature: dict, signal: np.ndarray, config: dict, cut: int | None = None,
    modified: int | None = None) -> tuple:
    """機能: 保存原本を途中で切断又は未来だけ変更し、固定した親子設定で再生する。

    引数: ready/feature/config(dict)、signal(np.ndarray)、cut/modified(int|None)。
    返り値: 注文・取引・曲線・統計(tuple)。
    """
    times, bid, ask, direction, reset = [np.asarray(value).copy() for value in (
        ready["time_s"], feature["bid"], feature["ask"], signal, feature["reset"])]
    if cut is not None:
        times, bid, ask, direction, reset = [value[:cut] for value in (times, bid, ask, direction, reset)]
    if modified is not None:
        bid[modified:] = bid[modified]+500*ready["tick"]+np.arange(len(bid)-modified)*ready["tick"]
        ask[modified:] = bid[modified:]+7*ready["tick"]
        times[modified:] = times[modified]+np.arange(len(times)-modified)*60
        direction[modified:] *= -1
        reset[modified:] = True
    symbol = ready["symbol"]
    return ENGINE.simulate(times, bid, ask, direction, reset, ready["tick"], ready["start"], ready["limit"],
        INITIAL[symbol], POINT[symbol], 41.8 if symbol == "TOPIX" else 11., config["entry_type"], config["entry_width"],
        config["initial_stop"], config["activation"], config["trail_width"], config["hold_seconds"],
        config["parent_ttl"], config["cooldown"])


def real_prefix(fixed: dict, selected: dict, inputs: dict, features: dict) -> list[dict]:
    """機能: 前半選定四候補の実原本八口座で注文・約定・時価の過去不変性を確認する。

    引数: fixed/selected/inputs/features(dict)。返り値: 各口座・各候補の検査記録(list[dict])。
    """
    signals = read(WORK/"signals/signals.pkl")
    sessions = ("2026-09-21_Day", "2026-09-30_Day", "2026-10-02_Day", "2026-10-08_Night")
    keys = sorted(key for key in inputs if key[0] in sessions)
    assert len(keys) == 8
    configs = {config["id"]:config for config in fixed["条件"]}
    records = []
    for selection in selected["選定"]:
        config = configs[selection["id"]]
        for key in keys:
            ready, feature = inputs[key], features[key]
            normal = replay(ready, feature, signals[key][config["signal"]], config)
            cuts = sorted({int(len(ready["time_s"])*fraction) for fraction in (.33, .71)})
            for cut in cuts:
                prefix = replay(ready, feature, signals[key][config["signal"]], config, cut=cut)
                changed = replay(ready, feature, signals[key][config["signal"]], config, modified=cut)
                for result in (prefix, changed):
                    np.testing.assert_array_equal(normal[0][normal[0][:, 0] < cut], result[0][result[0][:, 0] < cut])
                    np.testing.assert_array_equal(normal[1][normal[1][:, 2] < cut], result[1][result[1][:, 2] < cut])
                    np.testing.assert_array_equal(normal[2][:cut], result[2][:cut])
            records.append(dict(ID=config["id"], セッション=key[0], 銘柄=key[1], 途中切断=list(cuts),
                未来変更="価格・気配差・方向信号・reset・時計", 過去一致=True))
    return records


def front_summary(packet: dict, names: list[str], inputs: dict) -> dict:
    """機能: 後半を読まず、前半の場損益・取引数・枚数から選定用の指標を計算する。

    引数: packet(dict)、names(list[str])、inputs(dict)。返り値: 商品別前半指標(dict)。
    """
    result = {}
    for symbol in ("TOPIX", "NK225"):
        rows = [row for row in packet["rows"] if row["symbol"] == symbol and row["session"] in names]
        trades = sum(row["trades"] for row in rows)
        ticks = sum(row["net"]/(INITIAL[symbol]*POINT[symbol]*inputs[(row["session"], symbol)]["tick"]) for row in rows)
        profit, loss = sum(row["profit"] for row in rows), sum(row["loss"] for row in rows)
        won, lost = sum(row["winning_lots"] for row in rows), sum(row["losing_lots"] for row in rows)
        result[symbol] = dict(trades=trades, active=sum(row["trades"] > 0 for row in rows),
            net=sum(row["net"] for row in rows), mean=ticks/trades if trades else None,
            payoff=(profit/won)/(loss/lost) if won and lost else None)
    return result


def check_selection(fixed: dict, selected: dict, inputs: dict) -> list[dict]:
    """機能: 固定された前半の活動基準・最弱商品平均呼値順で四候補を独立再選定する。

    引数: fixed/selected/inputs(dict)。返り値: 独立順位照合の結果(list[dict])。
    """
    packets = [read(WORK/"results"/(config["id"]+".json")) for config in fixed["条件"]]
    summaries = {packet["config"]["id"]:front_summary(packet, fixed["前16"], inputs) for packet in packets}
    records = []
    for family in (1, 2, 3, 4):
        candidates = [packet for packet in packets if packet["config"]["family"] == family and all(
            value["trades"] >= 20 and value["active"] >= 8 for value in summaries[packet["config"]["id"]].values())]
        ranked = sorted(candidates, key=lambda packet:(-min(value["mean"] for value in summaries[packet["config"]["id"]].values()), packet["config"]["id"]))
        ids = [packet["config"]["id"] for packet in ranked]
        parent = next(value for value in selected["選定"] if value["family"] == family)
        assert ids == parent["front_rank"] and len(ids) == parent["candidate_count"]
        assert ids[0] == parent["id"] and parent["later_used_for_selection"] is False
        best = summaries[ids[0]]
        eligible = all(value["net"] > 0 and value["payoff"] is not None and value["payoff"] > 1 for value in best.values())
        assert eligible == parent["eligible"]
        near(min(value["mean"] for value in best.values()), parent["mean_worst_ticks"], "独立選定の最弱平均呼値")
        records.append(dict(機構=family, ID=ids[0], 有望基準合格=eligible, 候補数=len(ids), 全順位一致=True, 後半参照=False))
    return records


def main() -> None:
    """機能: 前半選定と実原本因果検査を実行し、独立監査証跡を保存する。

    引数: なし。返り値: なし(None)。
    """
    fixed, selected = read(WORK/"事前固定.json"), read(WORK/"機構別の前半選定.json")
    inputs, features = read(WORK/"prepared/inputs.pkl"), read(WORK/"prepared/features.pkl")
    selections = check_selection(fixed, selected, inputs)
    prefix = real_prefix(fixed, selected, inputs, features)
    save(HERE/"実原本因果検査と前半選定照合.json", dict(合格=True, 独立選定=selections,
        候補口座条件数=len(prefix), 途中切断数=sum(len(record["途中切断"]) for record in prefix),
        将来改変数=sum(len(record["途中切断"]) for record in prefix), 実原本検査=prefix,
        engine_SHA256=digest(WORK/"engine.py"), 固定SHA256=digest(WORK/"事前固定.json"),
        監査SHA256=digest(Path(__file__))))
    print("四機構前半選定順位と実原本", len(prefix), "候補口座条件の因果検査合格", flush=True)


if __name__ == "__main__":
    main()
