"""第二巡の再参加差と、保存経路にある利益保護前の境界接触を測る。"""

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

HERE=Path(__file__).resolve().parent
TASK=HERE.parent
ROOT=TASK.parents[1]


def identity(row):
    """
    機能: 同じ観測行で同方向へ建てた保存取引を対応する。
    引数: row(dict)は保存取引。
    返り値: tupleは場・商品・新規原行・方向。
    """
    return row["session"],row["symbol"],row["entry_row"],row["side"]


def main():
    """
    機能: 再参加による売買集合の変化と、既存保有経路の閾値接触を区別して保存する。
    引数: なし。
    返り値: None。注文・約定・新しい損益は生成しない。
    """
    source=HERE/"第二巡N16とN20の具体診断.json"
    original=json.loads(source.read_text(encoding="utf8"))
    a={identity(r):r for r in original["trades"] if r["method"]=="N16"}
    b={identity(r):r for r in original["trades"] if r["method"]=="N20"}
    common=set(a)&set(b)
    comparisons=[]
    for symbol in ("TOPIX","NK225"):
        old=[v for k,v in a.items() if k not in b and k[1]==symbol]
        new=[v for k,v in b.items() if k not in a and k[1]==symbol]
        same=[k for k in common if k[1]==symbol]
        for key in same:
            assert all(a[key][field]==b[key][field] for field in
                ("entry_price","exit_price","exit_row","width","net","gross","fee"))
        change=sum(r["net"] for r in new)-sum(r["net"] for r in old)
        assert change==sum(r["net"] for r in b.values() if r["symbol"]==symbol)-sum(r["net"] for r in a.values() if r["symbol"]==symbol)
        comparisons.append(dict(symbol=symbol,same_entries=len(same),same_entry_net_difference=0.,
            removed=old,added=new,removed_net=sum(r["net"] for r in old),
            added_net=sum(r["net"] for r in new),net_difference=change))
    # ----------------------------------------
    # 既存保有の正常気配だけで、保護開始前の逆行と利益返しの通過事実を測る。
    inputs=json.loads((TASK/"入力準備.json").read_text(encoding="utf8"))
    paths=[]
    for item in inputs["packets"]:
        scene=item["session"]
        if not scene.endswith("_Night"):
            continue
        packet=pickle.loads((ROOT/item["path"]).read_bytes())
        for row in [v for v in a.values() if v["session"]==scene]:
            key=scene,row["symbol"]
            quote=packet["quotes"][key]
            start,end=row["entry_row"],row["exit_row"]
            side=row["side"]
            price=quote["bid"] if side>0 else quote["ask"]
            valid=quote["quote_valid"][start:end+1]
            valid=valid&np.isfinite(quote["bid"][start:end+1])&np.isfinite(quote["ask"][start:end+1])
            valid=valid&(quote["bid"][start:end+1]>0)&(quote["bid"][start:end+1]<quote["ask"][start:end+1])
            ix=np.flatnonzero(valid)+start
            movement=side*(price[ix]-row["entry_price"])/row["width"]
            assert len(movement)
            peak=np.maximum.accumulate(np.maximum(movement,0.))
            hit=np.flatnonzero(peak>=1.5)
            pre=movement[:int(hit[0])+1] if len(hit) else movement
            flags={}
            for activation in (.5,1.):
                active=peak>=activation
                crossed=active&(movement<=0.)
                flags[str(activation)]=dict(reached=bool(active.any()),
                    returned_to_entry=bool(crossed.any()),
                    first_return_row=int(ix[np.flatnonzero(crossed)[0]]) if crossed.any() else None)
            paths.append(dict(session=scene,symbol=row["symbol"],cid=row["cid"],
                entry_row=start,entry_time=row["entry_time"],net=row["net"],
                pre_activation_adverse_r=float(pre.min()),maximum_favorable_r=float(peak.max()),
                contact=flags))
    summaries=[]
    for symbol in ("TOPIX","NK225"):
        selected=[r for r in paths if r["symbol"]==symbol]
        summaries.append(dict(symbol=symbol,
            tighter_stop_contacts=[dict(stop_r=limit,
                old_winners=sum(r["net"]>0 and r["pre_activation_adverse_r"]<=-limit for r in selected),
                all_old_winners=sum(r["net"]>0 for r in selected),
                old_losers=sum(r["net"]<0 and r["pre_activation_adverse_r"]<=-limit for r in selected),
                all_old_losers=sum(r["net"]<0 for r in selected)) for limit in (.5,.75)],
            profit_then_entry_contacts=[dict(activation=activation,
                old_winners=sum(r["net"]>0 and r["contact"][str(activation)]["returned_to_entry"] for r in selected),
                old_losers=sum(r["net"]<0 and r["contact"][str(activation)]["returned_to_entry"] for r in selected),
                reached_winners=sum(r["net"]>0 and r["contact"][str(activation)]["reached"] for r in selected),
                reached_losers=sum(r["net"]<0 and r["contact"][str(activation)]["reached"] for r in selected)) for activation in (.5,1.)]))
    target=HERE/"第二巡再参加で失った勝ちと保護前の接触事実.json"
    assert not target.exists()
    result=dict(passed=True,rearm_comparison=comparisons,path_summary=summaries,path_rows=paths,
        sources=[dict(path=source.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(source.read_bytes()).hexdigest()),
                 dict(path="work/daynight128_20261020/入力準備.json")],
        limits=["逆行境界への接触は同じ保有期間内の観測事実。別停止幅で運転した収支ではない。",
                "利益後の建値回帰は清算側気配で採点。実返済は次原行なので建値での約定を保証しない。",
                "再参加比較は同一入口の完全一致と、消えた入口・追加入口を別々に保存。全差額を失った勝ちだけに帰属しない。"],
        financial_replays=0,original_market_reads=0,API=0,
        producer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf8")
    print(json.dumps(summaries,ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
