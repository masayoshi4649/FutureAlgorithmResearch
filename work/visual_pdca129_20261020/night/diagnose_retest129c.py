"""保存保有区間を固定し、強逆流による準備破棄と新準備の対応を調べる。"""

import json
import pickle
import numpy as np
from numba import njit
from diagnose_retest129 import HERE, TASK, ROOT, OLD, read, stamp, build, long_history, record


@njit(cache=False)
def trace_discard(times,price,atr,h,m,bid,ask,good,allowed,tick,expected):
    """
    機能: 保存された非保有区間だけから固定線・段階・強逆流破棄を復元する。
    引数: 原行列・allowed・expected(ndarray)、tick(float)は既知入力と保存判断行。
    返り値: tuple[ndarray,ndarray]は保存新規対応状態と破棄履歴。発注・損益は作らない。
    """
    entries = np.zeros((len(expected),9))
    cancelled = np.zeros((len(times),10))
    arm,stage,count,cc,began,progress,returned = 0,0,0,0,-1,-1,-1
    level,width,extreme = 0.,0.,0.
    for i in range(len(times)):
        if not allowed[i]:
            arm = 0
            continue
        if not good[i]:
            continue
        if arm and np.isfinite(price[i]) and arm*(price[i]-level)<=-.25*width:
            arm = 0
        known = np.isfinite(price[i]) and np.isfinite(atr[i]) and atr[i]>0.
        known = known and np.isfinite(h[i]).all() and m[i,11]==1.
        known = known and np.isfinite(m[i,4]) and np.isfinite(m[i,6])
        if not known:
            continue
        w = max(atr[i],4.*tick)
        quote = ask[i]-bid[i]<=.25*w and max(ask[i]-price[i],price[i]-bid[i])<=.5*w
        if arm and times[i]-times[began]>1800.:
            arm = 0
        if not arm and quote:
            if h[i,5]>=.35:
                if price[i]>h[i,3] and h[i,10]>0. and h[i,11]>0.:
                    arm,level = 1,h[i,3]
                elif price[i]<h[i,4] and h[i,10]<0. and h[i,11]<0.:
                    arm,level = -1,h[i,4]
            if arm:
                width,began,extreme,stage = w,i,price[i],0
                progress,returned = -1,-1
                if arm*(price[i]-level)>=.75*width:
                    stage,progress = 1,i
        elif arm:
            advance = arm*(price[i]-level)
            trigger = False
            if advance<=-.25*width:
                arm = 0
            elif stage==0:
                if advance>=.75*width:
                    stage,progress = 1,i
            elif stage==1:
                if i>progress and advance<=.25*width:
                    stage,returned,extreme = 2,i,price[i]
            else:
                if arm*(price[i]-extreme)<0.:
                    extreme = price[i]
                trigger = i>returned and times[i]-times[began]>=60.
                trigger = trigger and arm*m[i,4]>0. and arm*m[i,6]>0.
                trigger = trigger and arm*(price[i]-extreme)>=.25*width
            if arm and trigger:
                trigger = arm*h[i,10]>0. and arm*h[i,11]>0.
            if arm and trigger and quote:
                if np.isfinite(m[i,5]) and np.isfinite(m[i,7]) and arm*m[i,5]<-.25 and arm*m[i,7]<-.25:
                    cancelled[cc] = np.array([i,began,arm,level,width,progress,returned,extreme,arm*m[i,5],arm*m[i,7]])
                    cc += 1
                    arm,stage,progress,returned,extreme = 0,0,-1,-1,0.
                else:
                    assert count<len(expected) and expected[count]==i
                    entries[count] = np.array([i,began,level,width,progress,returned,extreme,arm,times[i]-times[returned]])
                    count += 1
                    arm = 0
    assert count==len(expected)
    return entries,cancelled[:cc]


def main() -> None:
    """
    機能: 第七巡保存結果の全親を前巡と対応させ、準備破棄時刻と新準備を添える。
    引数: なし。
    返り値: None。完成済み結果だけを読み、注文核を実行しない。
    """
    account = read(TASK/"round7/全条件の会計.json")
    assert account["passed"]
    olddata = read(HERE/"強逆流待機の全親差分と解除取消し.json")
    refs = {r["session"]:r for r in read(OLD/"入力準備.json")["packets"] if r["session"].endswith("_Night")}
    rows,comparisons,cancellations = [],[],[]
    for scene,ref in refs.items():
        packet = pickle.loads((ROOT/ref["path"]).read_bytes())
        for method,base,kind in (("NV24","NV22","last"),("NV25","NV23","mid")):
            inputs,markets,hs,_ = build(packet,kind)
            contexts = long_history(inputs)
            for symbol in ("TOPIX","NK225"):
                key = scene,symbol
                rd,q,m,h = inputs[key],packet["quotes"][key],markets[key],hs[key]
                ts = rd["time_s"]
                good = q["quote_valid"] & np.isfinite(q["bid"]) & np.isfinite(q["ask"])
                good &= (q["bid"]>0.) & (q["ask"]>q["bid"])
                with np.load(TASK/"round7/measurement"/f"{symbol}_{scene}.npz") as z:
                    orders,trades = z[method+"__orders"],z[method+"__trades"]
                entries = orders[orders[:,7]==1.]
                allowed = (ts>=rd["us_open"]+1320.) & (ts<rd["limit"])
                for order,tr in zip(entries,trades):
                    end = np.searchsorted(ts,ts[int(tr[1])]+300.,side="left")
                    allowed[int(order[1])+1:end] = False
                states,cancels = trace_discard(ts,rd["last"],rd["atr"],h,m,q["bid"],q["ask"],
                    good,allowed,rd["tick"],entries[:,1].astype(np.int64))
                cc = [dict(method=method,session=scene,symbol=symbol,row=int(c[0]),
                      time=stamp(ts[int(c[0])]),arm_row=int(c[1]),arm_time=stamp(ts[int(c[1])]),
                      side=int(c[2]),boundary=float(c[3]),width=float(c[4]),
                      return_extreme=float(c[7]),own120=float(c[8]),peer120=float(c[9])) for c in cancels]
                cancellations.extend(cc)
                current = [record(method,scene,symbol,n,tr,order,rd,q,m,h,contexts[key],state)
                           for n,(tr,order,state) in enumerate(zip(trades,entries,states),1)]
                rows.extend(current)
                previous = [r for r in olddata["rows"] if r["method"]==base and r["session"]==scene and r["symbol"]==symbol]
                oldchanged,newchanged,matched = [],[],set()
                for old in previous:
                    eq = [j for j,r in enumerate(current) if all(r[k]==old[k] for k in
                          ("entry_row","exit_row","side","entry","exit","net","mfe","mae","width"))]
                    if eq:
                        matched.add(eq[0])
                    else:
                        oldchanged.append(old)
                newchanged = [r for j,r in enumerate(current) if j not in matched]
                if not oldchanged and not newchanged:
                    continue
                delta = sum(r["net"] for r in current)-sum(r["net"] for r in previous)
                assert delta==sum(r["net"] for r in newchanged)-sum(r["net"] for r in oldchanged)
                pairs,paired = [],set()
                for old in oldchanged:
                    cand = [(j,r) for j,r in enumerate(newchanged) if j not in paired and r["side"]==old["side"]
                            and r["entry_row"]<=old["exit_row"] and r["exit_row"]>=old["entry_row"]]
                    pair = min(cand,key=lambda jr:abs(jr[1]["entry_row"]-old["entry_row"])) if cand else None
                    if pair:
                        j,r = pair;paired.add(j)
                        pairs.append(dict(old=old,new=r,delta=r["net"]-old["net"]))
                    else:
                        pairs.append(dict(old=old,new=None,delta=-old["net"]))
                for j,r in enumerate(newchanged):
                    if j not in paired:
                        pairs.append(dict(old=None,new=r,delta=r["net"]))
                assert sum(p["delta"] for p in pairs)==delta
                comparisons.append(dict(method=method,baseline=base,session=scene,symbol=symbol,
                    old_net=sum(r["net"] for r in previous),new_net=sum(r["net"] for r in current),
                    delta=delta,pairs=pairs,cancellations=cc))
        print(scene,"準備破棄の保存対応",flush=True)
    totals = []
    for method,symbol in (("NV24","TOPIX"),("NV24","NK225"),("NV25","TOPIX"),("NV25","NK225")):
        totals.append(dict(method=method,symbol=symbol,
            delta=sum(r["delta"] for r in comparisons if r["method"]==method and r["symbol"]==symbol)))
    target = HERE/"強逆流準備破棄の全親差分と新準備.json"
    target.write_text(json.dumps(dict(passed=True,financial_replays=0,rows=rows,comparisons=comparisons,
        cancellations=cancellations,totals=totals),ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(dict(path=str(target),totals=totals,changed_accounts=len(comparisons)),ensure_ascii=False))


if __name__=="__main__":
    main()
