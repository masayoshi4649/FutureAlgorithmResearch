"""他指数で新規だけを確認し、反転時は中立化を許す価格波探索。"""

import itertools
import json
from pathlib import Path
import numpy as np
import pandas as pd
import research_v2 as core
from price_structure import simulate

OUT=Path(__file__).resolve().parent


def peer_state(z: pd.DataFrame, peer: pd.DataFrame, own_min: float, peer_fit: float) -> pd.Series:
    """機能: 自指数の反転確認で返済し、他指数が一致するときだけ新規方向へ入る。

    引数: z/peer (DataFrame)、own_min/peer_fit (float)。返り値: 持続方向 (Series)。
    """
    score=core.score(z,peer,22)
    raw=np.sign(score).where(score.abs()>=.25,0)
    idx=z.index[z.index.minute%5==4]
    peer=peer.reindex(idx)
    s=0
    values=[]
    for side,reg,fit,preg,pfit,pstale in zip(raw.reindex(idx),z.reg60.reindex(idx),z.fit60.reindex(idx),peer.reg60,peer.fit60,peer.stale_minutes):
        own=side!=0 and side*reg>=own_min and fit>=.2
        matching=side*preg>0 and pfit>=peer_fit and pstale<=10
        if s and side==-s and own:
            s=0
        if s==0 and own and matching:
            s=int(side)
        values.append(s)
    return pd.Series(values,index=idx).reindex(z.index,method="ffill").fillna(0).astype(int)


def main() -> None:
    """機能: 他指数確認９設定を保存足で再生する。

    引数: なし。返り値: なし (None)。
    """
    data=core.load_data(False)
    for _,z in data.values():
        x=np.arange(60)-29.5
        z["reg60"]=z.close.rolling(60).apply(lambda a:np.dot(x,a)*59/np.dot(x,x),raw=True)/z.atr
        z["fit60"]=z.close.rolling(60).apply(lambda a:np.dot(x,a-a.mean())**2/(np.dot(x,x)*np.dot(a-a.mean(),a-a.mean())) if np.ptp(a) else 0,raw=True)
    rows=[]
    details={}
    for own_min,peer_fit in itertools.product((.25,.5,1),(0,.2,.4)):
        key=f"他指数確認_{own_min}_{peer_fit}"
        trades=[]
        targets=[]
        cells=[]
        for (ses,sym),(one,z) in data.items():
            state=peer_state(z,data[ses,"TOPIX" if sym=="NK225" else "NK225"][1],own_min,peer_fit)
            events=simulate(one,z,state,sym,ses,key)
            trades.extend(events)
            targets.extend(core.target_metrics(one,events,sym,ses))
            cells.append({"session":ses,"symbol":sym,"count":len(events),"wins":sum(e["net_points"]>0 for e in events),"ticks":sum(e["net_points"] for e in events)/core.TICKS[sym]})
        counts=[c["count"] for c in cells]
        rows.append({"key":key,"target_pass":sum(t["passed"] for t in targets),"min_capture":min(t["capture_ratio"] for t in targets),"min_coverage":min(t["correct_coverage"] for t in targets),"max_count":max(counts),"min_count":min(counts),"frequency_ok":all(1<=c<=6 for c in counts),"count":len(trades),"win_rate":sum(e["net_points"]>0 for e in trades)/max(1,len(trades)),"ticks":sum(c["ticks"] for c in cells),"topix_night_ticks":next(c["ticks"] for c in cells if c["symbol"]=="TOPIX" and "Night" in c["session"])})
        details[key]={"cells":cells,"targets":targets,"trades":trades}
    table=pd.DataFrame(rows).sort_values(["target_pass","frequency_ok","win_rate"],ascending=False)
    table.to_csv(OUT/"価格他指数探索.csv",index=False,encoding="utf-8-sig")
    (OUT/"価格他指数詳細.json").write_text(json.dumps(details,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    print(table.to_string(index=False))


if __name__=="__main__":
    main()
