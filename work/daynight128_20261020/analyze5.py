"""固定条件の前後半と、方向・週・大勝ち依存を集計する。"""

import argparse
import numpy as np
from common128 import HERE, read, save, metrics


def score(groups):
    """
    機能: 両商品の黒字性、黒字場率、最大損失の回収性を優先する固定順位を作る。
    引数: groups(list[dict])は二商品分の集計。
    返り値: tupleは大きいほど優先する比較順位。円額を商品間合算しない。
    """
    return (int(all(x["net"] > 0 for x in groups)),
        min(x["black"]/x["sessions"] for x in groups),
        -max(-x["worst"]/x["mean_black"] if x["mean_black"] > 0 else 1.e10 for x in groups),
        min(x["profit"]/(x["profit"]+x["loss"]) if x["profit"]+x["loss"] else 0. for x in groups))


def main():
    """
    機能: 先に定めた選定順位を前半へ適用し、後半を選び直さず確認する。
    引数: --round(str)は巡名。
    返り値: None。金融再生0で全場参考順位と固定追跡を別々に保存する。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument("--round",default="round5")
    args=parser.parse_args()
    folder=HERE/args.round
    measured=read(folder/"全条件の会計.json")
    measured["rows"] = read(HERE/"round1/全条件の会計.json")["rows"] + read(HERE/"round2/全条件の会計.json")["rows"] + read(HERE/"round3/全条件の会計.json")["rows"] + read(HERE/"round4/全条件の会計.json")["rows"] + measured["rows"]
    baseline=read(HERE/"baseline/基準四十三場の親別手数料会計.json")["rows"]
    meta={(r["session"],r["symbol"]):r for r in baseline}
    rows=[]
    for r in baseline:
        rows.append(dict(r,entries=r["parents"],method="D00" if r["kind"]=="Day" else "N00",
            name="従来のGU_Q",gross=r["gross_net"]))
    for r in measured["rows"]:
        extra=meta[r["session"],r["symbol"]]
        rows.append(dict(r,regime=extra["regime"],week_start=extra["week_start"],
            half_within_kind=extra["half_within_kind"],kind_session_index=extra["kind_session_index"]))
    summaries=[]
    for method in sorted({r["method"] for r in rows}):
        for symbol in ("TOPIX","NK225"):
            chosen=[r for r in rows if r["method"]==method and r["symbol"]==symbol]
            summary=dict(method=method,symbol=symbol,kind=chosen[0]["kind"],**metrics(chosen))
            summary["halves"]={h:metrics([r for r in chosen if r["half_within_kind"]==h]) for h in ("前半","後半")}
            summary["regimes"]={k:metrics([r for r in chosen if r["regime"]==k]) for k in sorted({r["regime"] for r in chosen})}
            summary["weeks"]={w:metrics([r for r in chosen if r["week_start"]==w]) for w in sorted({r["week_start"] for r in chosen})}
            summaries.append(summary)
    selected={}
    for kind in ("Day","Night"):
        methods=sorted({s["method"] for s in summaries if s["kind"]==kind})
        if not methods:
            continue
        ranking=[]
        for method in methods:
            pair=[s for s in summaries if s["method"]==method]
            ranking.append(dict(method=method,train_score=list(score([s["halves"]["前半"] for s in pair])),
                full_score=list(score(pair))))
        by_train=sorted(ranking,key=lambda r:(r["train_score"],r["method"]),reverse=True)
        by_full=sorted(ranking,key=lambda r:(r["full_score"],r["method"]),reverse=True)
        selected[kind]=dict(frozen_on_first_half=by_train[0]["method"],full_development_reference=by_full[0]["method"],
            training_ranking=by_train,development_ranking=by_full)
    save(folder/"前後半と方向別の比較.json",dict(passed=True,selected=selected,summary=summaries,rows=rows,
        financial_replays=0,note="前半で選定、後半は固定。既知資料内であり未知外部テストではない。全場順位は別の事後参考。"))
    for s in summaries:
        print(s["method"],s["symbol"],"収支",int(s["net"]),"黒赤",s["black"],s["red"],
            "無取引",s["sessions"]-s["active"],"後半",int(s["halves"]["後半"]["net"]),
            "上昇",int(s["regimes"].get("上昇",{}).get("net",0)),
            "除上3",int(s["without_top3"]))
    print(selected)


if __name__=="__main__":
    main()
