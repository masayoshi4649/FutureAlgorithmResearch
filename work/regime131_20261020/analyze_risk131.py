"""減枚前後の同一取引を対応させ、消える利益・減る損失・整数下限を開示する。"""

import numpy as np
from common131 import HERE, read, reference, save
from analyze131 import statistics


def main():
    """
    機能: 第四巡と第三巡の入口出口同一性、初期予算、赤字場の深さを再集計する。
    引数: なし。固定済みround3/round4を参照する。
    返り値: None。保存会計の比較のみであり新金融再生はしない。
    """
    current = read(HERE/"round4/全条件の会計.json")
    prior = read(HERE/"round3/全条件の会計.json")
    previous = {(r["method"],r["session"],r["symbol"]):r for r in prior["rows"]}
    configs = {c["id"]:c for c in current["configs"]}
    pairs = []
    for ref in current["cache"]:
        scene, symbol = ref["session"], ref["symbol"]
        now = np.load(HERE/"round4/measurement"/(symbol+"_"+scene+".npz"))
        old = np.load(HERE/"round3/measurement"/(symbol+"_"+scene+".npz"))
        tick, base, multiplier = (.5,5,1000.) if symbol=="TOPIX" else (10.,10,10.)
        for config in current["configs"]:
            method = config["id"]
            original = "T04" if config["schedule"] == 2 else "T05"
            new_trades, old_trades = now[method+"__extra_trades"], old[original+"__extra_trades"]
            new_orders, old_orders = now[method+"__extra_orders"], old[original+"__extra_orders"]
            assert np.array_equal(now[method+"__core_orders"],old[original+"__core_orders"])
            assert new_trades.shape == old_trades.shape and new_orders.shape == old_orders.shape
            for field in (0,1,2,3,5,6,10,11,12,13,14,15,16):
                assert np.array_equal(new_trades[:,field],old_trades[:,field])
            for field in (0,1,2,3,5,6,7,9,10,11):
                assert np.array_equal(new_orders[:,field],old_orders[:,field])
            for nt, ot in zip(new_trades,old_trades):
                risk, quantity = nt[10], int(nt[4])
                target = base*config["budget_ticks"]*tick*multiplier
                expected = max(1,min(base,int(base*config["budget_ticks"]*tick/risk)))
                assert quantity == expected
                pairs.append(dict(method=method, base_method=original, session=scene,
                    kind=scene.split("_")[1],symbol=symbol,old_quantity=int(ot[4]),quantity=quantity,
                    risk=float(risk), target_risk=target, initial_risk=quantity*risk*multiplier,
                    minimum_over_budget=quantity==1 and risk*multiplier>target,
                    old_net=float(ot[9]),net=float(nt[9]),change=float(nt[9]-ot[9])))
    summary = []
    for config in current["configs"]:
        for symbol in ("TOPIX","NK225"):
            for kind in ("全体","Day","Night"):
                rows = [r for r in current["rows"] if r["method"]==config["id"] and r["symbol"]==symbol
                        and (kind=="全体" or r["kind"]==kind)]
                trades = [p for p in pairs if p["method"]==config["id"] and p["symbol"]==symbol
                          and (kind=="全体" or p["kind"]==kind)]
                losses = [-r["net"] for r in rows if r["net"]<0]
                original = "T04" if config["schedule"]==2 else "T05"
                baseline = [previous[original,r["session"],symbol] for r in rows]
                positives = [p for p in trades if p["old_net"]>0]
                negatives = [p for p in trades if p["old_net"]<0]
                row = dict(method=config["id"],symbol=symbol,kind=kind,
                    **statistics(rows), median_loss=float(np.median(losses)) if losses else None,
                    baseline=statistics(baseline),
                    removed_profit=-sum(p["change"] for p in positives),
                    reduced_loss=sum(p["change"] for p in negatives),
                    changed_quantity=sum(p["quantity"]!=p["old_quantity"] for p in trades),
                    extra_entries=len(trades),minimum_quantity=min((p["quantity"] for p in trades),default=None),
                    maximum_quantity=max((p["quantity"] for p in trades),default=None),
                    minimum_over_budget=sum(p["minimum_over_budget"] for p in trades))
                summary.append(row)
                if kind=="Night":
                    print(config["id"],symbol,"夜",round(row["net"]),"黒赤",row["black"],row["red"],
                          "赤平均/中央",round(row["mean_red"]),row["median_loss"],
                          "最大",round(-row["worst"]),"上3除外",round(row["without_top3"]),
                          "失う利益/減る損失",round(row["removed_profit"]),round(row["reduced_loss"]),flush=True)
    save(HERE/"round4/枚数変更と失う利益の対応.json",dict(passed=True,summary=summary,pairs=pairs,
        sources=[reference(HERE/"round4/全条件の会計.json"),reference(HERE/"round3/全条件の会計.json")],
        financial_replays=0,note="全旧新の入口・出口時刻と価格を照合。予算超過と約定飛びは別。"))


if __name__ == "__main__":
    main()
