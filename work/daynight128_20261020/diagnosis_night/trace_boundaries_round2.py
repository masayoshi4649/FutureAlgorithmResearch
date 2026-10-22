"""保存売買で空き区間を固定し、帯外進行の準備境界だけを再構成する。"""

from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np
from numba import njit

HERE=Path(__file__).resolve().parent
TASK=HERE.parent
ROOT=TASK.parents[1]
JST=timezone(timedelta(hours=9))


@njit(cache=False)
def trace(times,price,atr,history,market,bid,ask,qok,allowed,tick,expected):
    """
    機能: 保存売買で固定した空き区間に限り、Ｎ１６の入口準備状態を復元する。
    引数: 入力列・allowed・expected(ndarray)、tick(float)は原行資料・空き区間・保存判断行。
    返り値: ndarrayは判断行・準備行・境界・幅・判断Ｌａｓｔ距離・新規気配距離。
    売買の生成・約定判定・資金計算はせず、復元発火行の保存判断行との一致だけを検査する。
    """
    out=np.zeros((len(expected),6))
    count=0
    arm=0
    level=0.
    width=0.
    began=-1
    for i in range(len(times)):
        if not allowed[i]:
            continue
        known=np.isfinite(price[i]) and np.isfinite(atr[i]) and atr[i]>0.
        known=known and np.isfinite(history[i,:]).all() and market[i,11]==1.
        known=known and np.isfinite(market[i,4:8]).all()
        if not known:
            continue
        good=qok[i] and np.isfinite(bid[i]) and np.isfinite(ask[i]) and 0.<bid[i]<ask[i]
        if not good:
            continue
        w=max(atr[i],4.*tick)
        spread=ask[i]-bid[i]
        quote_ok=spread<=.25*w and max(ask[i]-price[i],price[i]-bid[i])<=.5*w
        if arm and times[i]-times[began]>1800.:
            arm=0
        if not arm and quote_ok:
            if history[i,5]>=.35:
                if price[i]>history[i,3] and history[i,10]>0. and history[i,11]>0.:
                    arm=1
                    level=history[i,3]
                elif price[i]<history[i,4] and history[i,10]<0. and history[i,11]<0.:
                    arm=-1
                    level=history[i,4]
            if arm:
                width=w
                began=i
        elif arm:
            if arm*(price[i]-level)<-.25*width:
                arm=0
            else:
                support=arm*market[i,4]>0. and arm*market[i,6]>0.
                trigger=times[i]-times[began]>=60. and support and arm*(price[i]-level)>=.25*width
                trigger=trigger and arm*market[i,5]>.05 and arm*market[i,7]>.05
                if trigger and quote_ok:
                    assert count<len(expected) and expected[count]==i
                    quoted=ask[i] if arm>0 else bid[i]
                    out[count]=np.array([i,began,level,width,arm*(price[i]-level)/width,arm*(quoted-level)/width])
                    count+=1
                    arm=0
    assert count==len(expected)
    return out


def main():
    """
    機能: Ｎ１６の全保存入口の固定境界と、既知の追い過ぎ距離を取り出す。
    引数: なし。
    返り値: None。新金融再生は零。
    """
    target=HERE/"第二巡N16の固定突破線と新規距離.json"
    assert not target.exists()
    inputs=json.loads((TASK/"入力準備.json").read_text(encoding="utf8"))
    diagnosis=json.loads((HERE/"第二巡N16とN20の具体診断.json").read_text(encoding="utf8"))
    index={(r["session"],r["symbol"],r["entry_row"]):r for r in diagnosis["trades"] if r["method"]=="N16"}
    rows=[]
    sources=[]
    for ref in inputs["packets"]:
        scene=ref["session"]
        if not scene.endswith("_Night"):
            continue
        packet=pickle.loads((ROOT/ref["path"]).read_bytes())
        histories=np.load(ROOT/ref["features"]["path"],allow_pickle=False)
        for symbol in ("TOPIX","NK225"):
            ready=packet["inputs"][scene,symbol]
            q=packet["quotes"][scene,symbol]
            times=ready["time_s"]
            path=TASK/"round2/measurement"/(symbol+"_"+scene+".npz")
            with np.load(path,allow_pickle=False) as archive:
                orders=archive["N16__orders"]
                trades=archive["N16__trades"]
            new=orders[orders[:,7]==1]
            expected=new[:,1].astype(np.int64)
            allowed=(times>=ready["us_open"]+1320.)&(times<ready["limit"])
            for order,trade in zip(new,trades):
                decision=int(order[1])
                end=int(trade[1])
                next_ready=np.searchsorted(times,times[end]+300.,side="left")
                allowed[decision+1:next_ready]=False
            traces=trace(times,ready["last"],ready["atr"],histories[symbol+"__history"],
                         packet["markets"][scene,symbol],q["bid"],q["ask"],q["quote_valid"],
                         allowed,ready["tick"],expected)
            for order,trade,tr in zip(new,trades,traces):
                e,side=int(order[0]),int(order[3])
                row=dict(index[scene,symbol,e])
                assert np.isclose(trade[11],tr[3])
                row["fixed_boundary"]=float(tr[2])
                row["arm_row"]=int(tr[1])
                row["arm_time"]=datetime.fromtimestamp(float(times[int(tr[1])]),JST).isoformat()
                row["arm_seconds_before_entry"]=float(times[e]-times[int(tr[1])])
                row["decision_last_distance_r"]=float(tr[4])
                row["decision_quote_distance_r"]=float(tr[5])
                row["fill_distance_r"]=float(side*(trade[4]-tr[2])/tr[3])
                row["initial_stop_still_outside_boundary"]=bool(row["fill_distance_r"]>1.)
                rows.append(row)
            sources.append(dict(path=path.relative_to(ROOT).as_posix(),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        print(scene,flush=True)
    summary=[]
    for symbol in ("TOPIX","NK225"):
        part=[r for r in rows if r["symbol"]==symbol]
        summary.append(dict(symbol=symbol,trades=len(part),
            distance_groups=[dict(threshold=limit,
                beyond=dict(trades=sum(r["decision_quote_distance_r"]>limit for r in part),
                            net=sum(r["net"] for r in part if r["decision_quote_distance_r"]>limit),
                            wins=sum(r["net"]>0 for r in part if r["decision_quote_distance_r"]>limit)),
                within=dict(trades=sum(r["decision_quote_distance_r"]<=limit for r in part),
                            net=sum(r["net"] for r in part if r["decision_quote_distance_r"]<=limit),
                            wins=sum(r["net"]>0 for r in part if r["decision_quote_distance_r"]<=limit)))
            for limit in (1.,1.5,2.)]))
    result=dict(passed=True,rows=rows,summary=summary,sources=sources,
        reconstruction="保存注文の判断行から返済後５分までを準備禁止として固定。空き区間の入口状態だけを復元。全１０６発火行が保存新規判断行と一致。",
        limits=["新規を実際に拒否した別戦略の損益ではない。条件別の既存親集計。",
                "約定距離は判断時点では未知。採否条件に使えるのは当時のＬａｓｔ又は新規側気配の距離。",
                "既知開発データ。新しい外部検証ではない。"],
        financial_replays=0,original_market_reads=0,API=0,
        producer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf8")
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
