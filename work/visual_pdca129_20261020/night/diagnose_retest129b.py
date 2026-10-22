"""強逆流待機の前後を、保存全親と当時の指標へ対応させる。"""

from copy import deepcopy
import json
import pickle
import numpy as np
from diagnose_retest129 import HERE, TASK, ROOT, OLD, read, stamp, build, long_history, trace, record


def main() -> None:
    """
    機能: 第四巡から第六巡への全親差分・待機解除・固定線破綻を診断する。
    引数: なし。
    返り値: None。保存保有期間を固定した準備状態の照合で、注文核は実行しない。
    """
    olddata = read(HERE/"再試験入口の全親と固定線診断.json")
    refs = {r["session"]:r for r in read(OLD/"入力準備.json")["packets"] if r["session"].endswith("_Night")}
    newrows, comparisons, deleted = [], [], []
    for scene,ref in refs.items():
        packet = pickle.loads((ROOT/ref["path"]).read_bytes())
        for method,base,kind in (("NV22","NV15","last"),("NV23","NV17","mid")):
            inputs,markets,histories,_ = build(packet,kind)
            contexts = long_history(inputs)
            for symbol in ("TOPIX","NK225"):
                key = scene,symbol
                rd,q,m,h,c = inputs[key],packet["quotes"][key],markets[key],histories[key],contexts[key]
                ts = rd["time_s"]
                good = q["quote_valid"] & np.isfinite(q["bid"]) & np.isfinite(q["ask"])
                good &= (q["bid"]>0.) & (q["ask"]>q["bid"])
                with np.load(TASK/"round6/measurement"/f"{symbol}_{scene}.npz") as z:
                    orders,trades = z[method+"__orders"],z[method+"__trades"]
                entries = orders[orders[:,7]==1.]
                allowed = (ts>=rd["us_open"]+1320.) & (ts<rd["limit"])
                for order,tr in zip(entries,trades):
                    end = np.searchsorted(ts,ts[int(tr[1])]+300.,side="left")
                    allowed[int(order[1])+1:end] = False
                # ----------------------------------------
                # 純準備復元の発火だけ抑止する。元の観測配列や判断指標は変更しない。
                traced_market = m.copy()
                common = np.isfinite(m[:,5]) & np.isfinite(m[:,7])
                common &= ((m[:,5]<-.25)&(m[:,7]<-.25)) | ((m[:,5]>.25)&(m[:,7]>.25))
                # 方向は準備に従うので、片向きの強逆流でも原30支持と同符号の時だけ抑止する。
                common &= (m[:,4]*m[:,5] < 0.)
                traced_market[common,4] = 0.
                states,_ = trace(ts,rd["last"],rd["atr"],h,traced_market,
                    q["bid"],q["ask"],good,allowed,rd["tick"],entries[:,1].astype(np.int64))
                current = []
                for n,(tr,order,state) in enumerate(zip(trades,entries,states),1):
                    r = record(method,scene,symbol,n,tr,order,rd,q,m,h,c,state)
                    current.append(r);newrows.append(r)
                prior = [r for r in olddata["rows"] if r["method"]==base and r["session"]==scene and r["symbol"]==symbol]
                unchanged,old_changed,new_changed = [],[],[]
                matched = set()
                for previous in prior:
                    exact = [j for j,r in enumerate(current) if all(r[k]==previous[k] for k in
                             ("entry_row","exit_row","side","entry","exit","net","mfe","mae","width"))]
                    if exact:
                        matched.add(exact[0]);unchanged.append(previous["number"])
                    else:
                        old_changed.append(previous)
                new_changed = [r for j,r in enumerate(current) if j not in matched]
                if not old_changed and not new_changed:
                    continue
                total_delta = sum(r["net"] for r in current)-sum(r["net"] for r in prior)
                assert total_delta == sum(r["net"] for r in new_changed)-sum(r["net"] for r in old_changed)
                pairs,paired_new = [],set()
                for previous in old_changed:
                    candidates = [(j,r) for j,r in enumerate(new_changed) if j not in paired_new and
                        r["side"]==previous["side"] and r["entry_row"]<=previous["exit_row"] and
                        r["exit_row"]>=previous["entry_row"]]
                    pair = min(candidates,key=lambda jr:abs(jr[1]["entry_row"]-previous["entry_row"])) if candidates else None
                    if pair is not None:
                        j,currentrow = pair;paired_new.add(j)
                        newd = currentrow["decision_row"]
                        details = dict(old=previous,new=currentrow,delta=currentrow["net"]-previous["net"],
                            wait_price_seconds=float(ts[newd]-ts[previous["decision_row"]]),
                            wait_rows=int(newd-previous["decision_row"]),
                            new_120=[float(previous["side"]*m[newd,k]) for k in (5,7)])
                        pairs.append(details)
                    else:
                        side = previous["side"]
                        ids = np.arange(previous["decision_row"]+1,min(len(ts),
                            np.searchsorted(ts,ts[previous["arm_row"]]+1800.,side="right")))
                        broke = good[ids] & np.isfinite(rd["last"][ids])
                        broke &= side*(rd["last"][ids]-previous["boundary"]) <= -.25*previous["width"]
                        hit = int(ids[broke][0]) if broke.any() else -1
                        details = dict(old=previous,new=None,delta=-previous["net"],
                            cancelled_row=hit,cancelled_time=stamp(ts[hit]) if hit>=0 else None,
                            cancelled_observed_price=float(rd["last"][hit]) if hit>=0 else None,
                            cancellation_line=previous["boundary"]-side*.25*previous["width"])
                        deleted.append(details);pairs.append(details)
                for j,r in enumerate(new_changed):
                    if j not in paired_new:
                        pairs.append(dict(old=None,new=r,delta=r["net"]))
                assert sum(p["delta"] for p in pairs)==total_delta
                comparisons.append(dict(session=scene,symbol=symbol,baseline=base,method=method,
                    old_net=sum(r["net"] for r in prior),new_net=sum(r["net"] for r in current),
                    delta=total_delta,unchanged_parents=unchanged,pairs=pairs))
        print(scene,"保存親前後の対応",flush=True)
    totals = []
    for method,symbol in (("NV22","TOPIX"),("NV22","NK225"),("NV23","TOPIX"),("NV23","NK225")):
        own = [r for r in comparisons if r["method"]==method and r["symbol"]==symbol]
        totals.append(dict(method=method,symbol=symbol,changed_sessions=len(own),delta=sum(r["delta"] for r in own)))
    result = dict(passed=True,financial_replays=0,rows=newrows,comparisons=comparisons,totals=totals,
                  deleted_parents=deleted,limitation="前後の全保存親を対応。重なる同方向親の対応であり、反実仮想の損益足し算ではない。")
    path = HERE/"強逆流待機の全親差分と解除取消し.json"
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=True)+"\n",encoding="utf8")
    print(json.dumps(dict(path=str(path),totals=totals,deleted=[{k:v for k,v in r.items() if k!="old"} for r in deleted]),ensure_ascii=False))


if __name__=="__main__":
    main()
