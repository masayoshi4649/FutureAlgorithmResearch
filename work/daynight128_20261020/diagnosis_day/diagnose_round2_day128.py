"""第二巡D11の残存赤字と、短期支持必須化で見送る勝ち負けを保存親だけで診断する。"""

import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = TASK.parents[1]
OLD = ROOT / "work/stability126_20261019"


def read(path: Path) -> dict:
    """
    機能: 保存JSONを読む。
    引数: path(Path)は既存資料。
    返り値: dictは内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> None:
    """
    機能: 全D11親の通知時支持を分類し、赤字上位場と失う勝ちを具体時刻へ戻す。
    引数: なし。
    返り値: None。既存親の分類だけであり、第三巡の売買再生を行わない。
    """
    target = HERE / "第二巡D11の残存赤字と短期支持条件の取捨.json"
    assert not target.exists()
    diagnostic_source = OLD / "diagnosis_notes/bbo/trace_bbo_loss126.py"
    spec = importlib.util.spec_from_file_location("trace_round2", diagnostic_source)
    trace = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trace)
    result_path, manifest_path = TASK / "round2/全条件の会計.json", TASK / "入力準備.json"
    result, manifest = read(result_path), read(manifest_path)
    cache = {(r["session"], r["symbol"]): r for r in result["cache"] if r["session"].endswith("_Day")}
    packets = {r["session"]: r for r in manifest["packets"]}
    logs, parents, account_data, packet_data = [], [], {}, {}
    for scene in sorted({key[0] for key in cache}):
        packet = pickle.loads(trace.payload(packets[scene], logs, "D11新規時の二市場短期支持"))
        packet_data[scene] = packet
        for symbol in ("TOPIX", "NK225"):
            key = scene, symbol
            with np.load(BytesIO(trace.payload(cache[key], logs, "D11の完成親と注文")), allow_pickle=False) as data:
                actual = {name: data["D11__" + name] for name in ("orders", "cycles", "execution_events")}
            account_data[key] = actual
            ready, market = packet["inputs"][key], packet["markets"][key]
            previous = None
            for cycle in actual["cycles"]:
                cid = int(cycle[0])
                owned = actual["orders"][actual["orders"][:, 2] == cid]
                new = owned[owned[:, 7] == 1.][0]
                row, source, side = int(new[0]), int(new[1]), int(new[3])
                known = market[source, 11] == 1. and np.isfinite(market[source, 4:8]).all()
                support = bool(known and side * market[source, 4] > .05 and side * market[source, 6] > .05)
                mult, rate = (1000., 418) if symbol == "TOPIX" else (10., 110)
                fees = int(((owned[:, 4].astype(np.int64) * rate) // 10).sum())
                parent = dict(
                    session=scene, symbol=symbol, parent=cid, direction=side,
                    source_time=trace.clock(float(ready["time_s"][source])),
                    entry_time=trace.clock(float(ready["time_s"][row])),
                    exit_time=trace.clock(float(ready["time_s"][int(cycle[2])])),
                    entry_price=float(new[5]), fixed_atr=float(cycle[5]),
                    holding_minutes=float((ready["time_s"][int(cycle[2])] - ready["time_s"][row]) / 60.),
                    gross=float(cycle[3] * mult), fees=fees, net=float(cycle[3] * mult - fees),
                    short_support=support, known=bool(known), source_market=market[source].tolist(),
                    prior_parent=None if previous is None else dict(
                        parent=previous["parent"], direction=previous["direction"], net=previous["net"],
                        exit_time=previous["exit_time"], entry_price=previous["entry_price"]),
                )
                parents.append(parent)
                previous = parent
    # ----------------------------------------
    # 短期支持拒否は勝ちも削る。全日中の元親を分類し、取引再生の改善額にはしない。
    classifications, removed_best, rejected_worst = [], [], []
    for symbol in ("TOPIX", "NK225"):
        own = [r for r in parents if r["symbol"] == symbol]
        rejected = [r for r in own if not r["short_support"]]
        approved = [r for r in own if r["short_support"]]
        for name, rows in (("支持あり", approved), ("支持なし又は未知", rejected)):
            classifications.append(dict(
                symbol=symbol, classification=name, parents=len(rows),
                wins=sum(r["net"] > 0 for r in rows), losses=sum(r["net"] < 0 for r in rows),
                gross=sum(r["gross"] for r in rows), fees=sum(r["fees"] for r in rows),
                saved_parent_net=sum(r["net"] for r in rows),
                positive=sum(max(0., r["net"]) for r in rows), negative=-sum(min(0., r["net"]) for r in rows),
                caution="保存親の条件分類であり、第三巡の全経路成績ではない。",
            ))
        removed_best += sorted([r for r in rejected if r["net"] > 0], key=lambda r: -r["net"])[:3]
        rejected_worst += sorted([r for r in rejected if r["net"] < 0], key=lambda r: r["net"])[:3]
    worst = []
    for symbol in ("TOPIX", "NK225"):
        worst += sorted([r for r in result["rows"] if r["method"] == "D11" and r["symbol"] == symbol],
                        key=lambda r: r["net"])[:3]
    empty = dict(orders=np.empty((0, 8)), cycles=np.empty((0, 10)))
    concrete = []
    for chosen in worst:
        key = chosen["session"], chosen["symbol"]
        groups = trace.group_details(packet_data[key[0]], key[1], account_data[key], empty)
        source_parents = {r["parent"]: r for r in parents if (r["session"], r["symbol"]) == key}
        for group in groups:
            group["entry_classification"] = source_parents[group["campaign"]]
            group.pop("Last_comparison")
        concrete.append(dict(account=chosen, parents=groups))
    output = dict(
        passed=True, classifications=classifications, all_parents=parents,
        removed_best_three=removed_best, rejected_worst_three=rejected_worst,
        concrete_worst_sessions=concrete, reads=logs,
        sources=[dict(path=p.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                 for p in (diagnostic_source, result_path, manifest_path, Path(__file__))],
        financial_replays=0, original_market_reads=0, API=0,
        caution="既知全22日中場のD11保存親を分類。条件を変えた後の未参加や後続約定は新金融で別途確認する。",
    )
    target.write_text(json.dumps(trace.primitive(output), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(classifications, ensure_ascii=False))
    print("見送る勝ち上位", json.dumps(removed_best, ensure_ascii=False))
    for account in concrete:
        print(account["account"]["symbol"], account["account"]["session"], account["account"]["net"])
        for group in sorted(account["parents"], key=lambda r: r["entry_time"]):
            c = group["entry_classification"]
            print(group["entry_time"][11:19], group["direction"], group["entry_price"],
                  "→", group["final_time"][11:19], c["net"], "支持", c["short_support"],
                  "30秒", c["source_market"][4], c["source_market"][6], "120秒", c["source_market"][5], c["source_market"][7])


if __name__ == "__main__":
    main()
