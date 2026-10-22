"""第二巡の原板活動入口が作った、見送り後の全親経路を診断する。"""

import pickle
import sys
from pathlib import Path

import numpy as np

from diagnose_entry130 import HERE, ROOT, OLD, PREV, read, save
from diagnose_round1_130 import stamp
sys.path.insert(0, str(PREV))
import features129

TASK = HERE.parent


def collect(method: str, scene: str, symbol: str, rd: dict, market: np.ndarray,
            activity: dict) -> list[dict]:
    """
    機能: 第二巡と元方式の保存親に、入口の公表活動と二市場方向を添える。
    引数: method/scene/symbol(str)、rd(dict)、market(ndarray)、activity(dict)は保存入力。
    返り値: list[dict]は因果特徴を付けた保存親。売買を生成しない。
    """
    folder = TASK / "round2" if method.startswith("W") else PREV / ("round1" if method == "NV01" else "round7")
    with np.load(folder / "measurement" / f"{symbol}_{scene}.npz") as saved:
        orders, trades = saved[method + "__orders"], saved[method + "__trades"]
    out = []
    for order in orders[orders[:, 7] == 1.]:
        parent, d, e, side = int(order[2]), int(order[1]), int(order[0]), int(order[3])
        closes = orders[(orders[:, 2] == parent) & (orders[:, 7] == 0.)]
        owned = trades[trades[:, 14] == parent] if trades.shape[1] > 14 else trades[trades[:, 0] == order[0]]
        assert len(closes) == len(owned) == 1
        exit_order, tr = closes[0], owned[0]
        xd, xf = int(exit_order[1]), int(exit_order[0])
        obs, details = activity["activity"][d], activity["details"][d]
        accepted = obs[3] == 1. and side*obs[0] > 0. and side*obs[2] < 0. and obs[1] > 0.
        if method.startswith("W"):
            assert accepted
        out.append(dict(method=method, session=scene, symbol=symbol, parent=parent,
            entry_row=e, decision_row=d, side=side, quantity=int(order[4]), entry=float(order[5]),
            entry_time=stamp(rd["time_s"][e]), decision_time=stamp(rd["time_s"][d]),
            width=float(tr[11]), exit_row=xf, exit_decision_row=xd, exit_time=stamp(rd["time_s"][xf]),
            exit_decision_time=stamp(rd["time_s"][xd]), exit=float(tr[5]), net=float(tr[8]),
            gross=float(tr[6]), fee=float(tr[7]), mfe=float(tr[9]), mae=float(tr[10]), reason=int(tr[12]),
            activity_accepted=bool(accepted), activity=[float(v) for v in obs], detail=[float(v) for v in details],
            own30=float(side*market[d,4]), own120=float(side*market[d,5]),
            peer30=float(side*market[d,6]), peer120=float(side*market[d,7]),
            exit_own30=float(side*market[xd,4]), exit_own120=float(side*market[xd,5]),
            exit_peer30=float(side*market[xd,6]), exit_peer120=float(side*market[xd,7])))
    return out


def main() -> None:
    """
    機能: 第二巡84商品場の保存会計を具体親の除去・新発生へ完全分解する。
    引数: なし。
    返り値: None。会計完成後の保存診断のみを実施する。
    """
    financial = read(TASK / "round2/全条件の会計.json")
    assert financial["passed"]
    accounts_index = {(r["method"], r["session"], r["symbol"]): r for r in financial["rows"]}
    refs = [r for r in read(OLD / "入力準備.json")["packets"] if r["session"].endswith("_Night")]
    records, accounts = [], []
    for ref in refs:
        scene = ref["session"]
        packet = pickle.loads((ROOT / ref["path"]).read_bytes())
        for base, method, kind in (("NV01", "W07", "last"), ("NV25", "W08", "mid")):
            inputs, markets, _, _ = features129.build(packet, kind)
            for symbol in ("TOPIX", "NK225"):
                activity = dict(np.load(TASK / "prepared" / f"{symbol}_{scene}.npz"))
                old = collect(base, scene, symbol, inputs[scene,symbol], markets[scene,symbol], activity)
                new = collect(method, scene, symbol, inputs[scene,symbol], markets[scene,symbol], activity)
                records.extend(old + new)
                matched, pairs = set(), []
                for r in new:
                    previous = next((o for o in old if (o["entry_row"],o["side"],o["entry"]) ==
                                     (r["entry_row"],r["side"],r["entry"])), None)
                    if previous:
                        matched.add(previous["parent"])
                        # 入口・出口条件が同じ同一親は保有経路も同一であるべき。
                        assert all(previous[k] == r[k] for k in ("exit_row","exit","net","mfe","mae"))
                    prior_candidate = [o for o in old if o["side"] == r["side"] and o["decision_row"] < r["decision_row"]]
                    nearest = max(prior_candidate,key=lambda v:v["decision_row"]) if prior_candidate else None
                    pairs.append(dict(kind="同一親を維持" if previous else "新しい入口経路の親",
                        old=previous,new=r,delta=r["net"]-(previous["net"] if previous else 0.),
                        previous_same_side_old=nearest,
                        during_old_parent=[o["parent"] for o in old if o["decision_row"]<r["decision_row"]<=o["exit_row"]]))
                for o in old:
                    if o["parent"] not in matched:
                        pairs.append(dict(kind="元の親が消えた",old=o,new=None,delta=-o["net"],
                            previous_same_side_old=None,during_old_parent=[]))
                newnet=sum(r["net"]for r in new)
                assert newnet==accounts_index[method,scene,symbol]["net"]
                delta=newnet-sum(o["net"]for o in old)
                assert sum(p["delta"]for p in pairs)==delta
                accounts.append(dict(method=method,base=base,session=scene,symbol=symbol,
                    old_net=sum(o["net"]for o in old),new_net=newnet,delta=delta,pairs=pairs))
        print(scene,"第二巡の保存親対応",flush=True)
    groups=[]
    for method in ("W07","W08"):
        for symbol in ("TOPIX","NK225"):
            related=[a for a in accounts if a["method"]==method and a["symbol"]==symbol]
            pairs=[p for a in related for p in a["pairs"]]
            groups.append(dict(method=method,symbol=symbol,
                old_net=sum(a["old_net"]for a in related),new_net=sum(a["new_net"]for a in related),
                kept=sum(p["kind"]=="同一親を維持"for p in pairs),
                disappeared=sum(p["kind"]=="元の親が消えた"for p in pairs),
                created=sum(p["kind"]=="新しい入口経路の親"for p in pairs),
                removed_component=sum(p["delta"]for p in pairs if p["kind"]=="元の親が消えた"),
                new_component=sum(p["delta"]for p in pairs if p["kind"]=="新しい入口経路の親"),
                worst=[dict(session=a["session"],net=a["new_net"],delta=a["delta"])for a in sorted(related,key=lambda v:v["new_net"])[:3]],
                worsened=[dict(session=a["session"],net=a["new_net"],delta=a["delta"])for a in sorted(related,key=lambda v:v["delta"])[:3]]))
    save(HERE/"第二巡の入口見送り後の全親差分.json",dict(passed=True,financial_replays=0,
        records=records,accounts=accounts,groups=groups,
        note="親番号で機械対応せず、同じ新規原行・方向・値段で照合。新しい入口を旧親の同一延長と断定しない。"))
    print(groups)


if __name__=="__main__":
    main()
