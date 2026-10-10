"""速い開始条件と遅い反転確認を分ける継続波の独立探索。"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
import numpy as np
import pandas as pd
import research_v2 as core
from price_structure import simulate

OUT=Path(__file__).resolve().parent


def state_one(z: pd.DataFrame, raw: pd.Series, width: float, window: int, threshold: float) -> pd.Series:
    """機能: 開始後の反転を価格の押し戻し幅と長期回帰の一致で確認する。

    引数: z (DataFrame)、raw (Series)、width/threshold (float)、window (int)。
    返り値: 持続方向 (Series)。
    """
    idx=z.index[z.index.minute%5==4]
    p=z.close.reindex(idx).to_numpy()
    a=z.atr.reindex(idx).to_numpy()
    directions=raw.reindex(idx).to_numpy()
    slow=z[f"slow{window}"].reindex(idx).to_numpy()
    r2=z[f"fit{window}"].reindex(idx).to_numpy()
    result=[]
    state=0
    peak=0
    for price,atr,side,reg,fit in zip(p,a,directions,slow,r2):
        if state==0 and side:
            state=int(side)
            peak=state*price
        elif state:
            peak=max(peak,state*price)
            if side==-state and state*reg<=-threshold and fit>=.2 and peak-state*price>=width*atr:
                state=int(side)
                peak=state*price
        result.append(state)
    return pd.Series(result,index=idx).reindex(z.index,method="ffill").fillna(0).astype(int)


def main() -> None:
    """機能: 回帰継続確認を加えた価格状態の144条件を保存済みデータで比較する。

    引数: なし。返り値: なし (None)。
    """
    data=core.load_data(False)
    for _,z in data.values():
        for n in (30,60):
            x=np.arange(n)-(n-1)/2
            z[f"slow{n}"]=z.close.rolling(n).apply(lambda a: np.dot(x,a)*(n-1)/np.dot(x,x),raw=True)/z.atr
            z[f"fit{n}"]=z.close.rolling(n).apply(lambda a: np.dot(x,a-a.mean())**2/(np.dot(x,x)*np.dot(a-a.mean(),a-a.mean())) if np.ptp(a) else 0,raw=True)
    strengths={(ses,sym,fam):core.score(z,data[ses,"TOPIX" if sym=="NK225" else "NK225"][1],fam) for (ses,sym),(one,z) in data.items() for fam in (3,5,21,22)}
    rows=[]
    details={}
    for family,q,width,window,threshold in itertools.product((3,5,21,22),(.25,.5),(0,.5,1),(30,60),(.25,.5,1)):
        key=f"回帰継続_{family}_{q}_{width}_{window}_{threshold}"
        trades=[]
        targets=[]
        cells=[]
        for (session,symbol),(one,z) in data.items():
            score=strengths[session,symbol,family]
            raw=np.sign(score).where(score.abs()>=q,0)
            state=state_one(z,raw,width,window,threshold)
            events=simulate(one,z,state,symbol,session,key)
            trades.extend(events)
            targets.extend(core.target_metrics(one,events,symbol,session))
            cells.append({"session":session,"symbol":symbol,"count":len(events),"wins":sum(e["net_points"]>0 for e in events),"ticks":sum(e["net_points"] for e in events)/core.TICKS[symbol]})
        counts=[c["count"] for c in cells]
        row={"key":key,"family":family,"q":q,"width":width,"window":window,"threshold":threshold,"target_pass":sum(t["passed"] for t in targets),
             "min_capture":min(t["capture_ratio"] for t in targets),"min_coverage":min(t["correct_coverage"] for t in targets),"max_count":max(counts),
             "min_count":min(counts),"frequency_ok":all(1<=c<=6 for c in counts),"count":len(trades),"win_rate":sum(e["net_points"]>0 for e in trades)/max(1,len(trades)),
             "ticks":sum(c["ticks"] for c in cells),"topix_night_ticks":next(c["ticks"] for c in cells if c["symbol"]=="TOPIX" and "Night" in c["session"])}
        rows.append(row)
        details[key]={"cells":cells,"targets":targets,"trades":trades}
    table=pd.DataFrame(rows).sort_values(["target_pass","frequency_ok","win_rate","min_capture"],ascending=False)
    table.to_csv(OUT/"価格継続探索.csv",index=False,encoding="utf-8-sig")
    (OUT/"価格継続詳細.json").write_text(json.dumps(details,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    print(table.head(20).to_string(index=False))


if __name__=="__main__":
    main()
