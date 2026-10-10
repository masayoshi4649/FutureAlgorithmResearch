"""価格構造の反転幅で継続波を数える独立探索。現在セッションへ接続しない。"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
import numpy as np
import pandas as pd
import research_v2 as core

OUT = Path(__file__).resolve().parent


def structure_state(z: pd.DataFrame, kind: str, width: float, floor: float, smooth: int, entry: float) -> pd.Series:
    """機能: 平滑価格の反転幅または追跡価格帯から因果的な継続方向を判定する。

    引数: z (DataFrame)、kind (str)、width/floor/entry (float)、smooth (int)。
    返り値: 各分の末尾に利用できる方向 (Series)。
    """
    sampled = z[z.index.minute%5==4]
    p = sampled.close.ewm(span=smooth,adjust=False).mean()
    span = sampled.close.rolling(12,min_periods=6).max()-sampled.close.rolling(12,min_periods=6).min()
    widths = np.maximum(sampled.atr*width,span*floor)
    values = []
    state = 0
    peak = None
    upper = lower = None
    previous = None
    for i, row in enumerate(sampled.itertuples()):
        px,w = p.iloc[i],widths.iloc[i]
        if row.age<30 or not np.isfinite(w) or row.stale_minutes>10:
            values.append(0)
            continue
        if kind=="中心反転":
            if state==0:
                state = 1 if row.move30>=entry else (-1 if row.move30<=-entry else 0)
                peak = px
            elif state==1:
                peak = max(peak,px)
                if px<=peak-w:
                    state=-1
                    peak=px
            else:
                peak = min(peak,px)
                if px>=peak+w:
                    state=1
                    peak=px
        else:
            new_upper,new_lower=px+w,px-w
            upper=new_upper if upper is None or new_upper<upper or previous>upper else upper
            lower=new_lower if lower is None or new_lower>lower or previous<lower else lower
            if state==0:
                state = 1 if row.move30>=entry else (-1 if row.move30<=-entry else 0)
            elif state==1 and px<lower:
                state=-1
            elif state==-1 and px>upper:
                state=1
            previous=px
        values.append(state)
    result=pd.Series(values,index=sampled.index).reindex(z.index,method="ffill").fillna(0)
    return result.astype(int)


def simulate(one: pd.DataFrame,z: pd.DataFrame,state: pd.Series,symbol: str,session: str,key: str) -> list[dict]:
    """機能: 反転まで一波として保有し、確定１分後以降の実在始値で売買を再生する。

    引数: one/z (DataFrame)、state (Series)、symbol/session/key (str)。
    返り値: 波単位の参考取引 (list[dict])。
    """
    limit=core.deadline(one.index)
    ready=z.index+pd.Timedelta(minutes=2)
    available=pd.DataFrame({"state":state.to_numpy(),"atr":z.atr.to_numpy(),"stale":z.stale_minutes.to_numpy()},index=ready).reindex(one.index,method="ffill")
    active=None
    trades=[]
    tick=core.TICKS[symbol]
    for row,s in zip(one.itertuples(),available.itertuples()):
        now,price=row.Index,float(row.open)
        side=int(s.state) if np.isfinite(s.state) else 0
        if now>=limit:
            side=0
        if active is not None and side!=active["side"]:
            gross=active["side"]*(price-active["entry_price"])
            active.update(exit_time=now,exit_price=price,closed=True,gross_points=gross,net_points=gross-2*tick,stress_points=gross-4*tick,
                          duration_min=(now-active["entry_time"]).total_seconds()/60,reason="セッション返済" if now>=limit else "構造的反転")
            active["net_atr"]=active["net_points"]/active["atr"]
            trades.append(active)
            active=None
        if active is None and side and now<limit-pd.Timedelta(minutes=30) and np.isfinite(s.atr) and s.stale<=10:
            active={"symbol":symbol,"session":session,"config":key,"side":side,"entry_time":now,"entry_price":price,"atr":float(s.atr),"exit_time":None,"closed":False}
    if active is not None:
        raise AssertionError("セッション内返済を確認できません")
    return trades


def main() -> None:
    """機能: 構造反転の160設定を保存済みデータだけで探索する。

    引数: なし。返り値: なし (None)。
    """
    data=core.load_data(False)
    rows=[]
    details={}
    for kind,width,floor,smooth,entry in itertools.product(("中心反転","追跡帯"),(1,1.5,2,2.5,3),(0,.25,.5,.75),(1,3),(.5,1)):
        key=f"{kind}_{width}_{floor}_{smooth}_{entry}"
        trades=[]
        targets=[]
        cells=[]
        for (session,symbol),(one,z) in data.items():
            state=structure_state(z,kind,width,floor,smooth,entry)
            events=simulate(one,z,state,symbol,session,key)
            trades.extend(events)
            targets.extend(core.target_metrics(one,events,symbol,session))
            cells.append({"session":session,"symbol":symbol,"count":len(events),"wins":sum(e["net_points"]>0 for e in events),"ticks":sum(e["net_points"] for e in events)/core.TICKS[symbol]})
        counts=[c["count"] for c in cells]
        row={"key":key,"kind":kind,"width":width,"floor":floor,"smooth":smooth,"entry":entry,"target_pass":sum(t["passed"] for t in targets),
             "min_capture":min(t["capture_ratio"] for t in targets),"min_coverage":min(t["correct_coverage"] for t in targets),"max_count":max(counts),
             "min_count":min(counts),"frequency_ok":all(1<=c<=6 for c in counts),"count":len(trades),"win_rate":sum(e["net_points"]>0 for e in trades)/max(1,len(trades)),
             "ticks":sum(c["ticks"] for c in cells),"topix_night_ticks":next(c["ticks"] for c in cells if c["symbol"]=="TOPIX" and "Night" in c["session"])}
        rows.append(row)
        details[key]={"cells":cells,"targets":targets,"trades":trades}
    table=pd.DataFrame(rows).sort_values(["target_pass","frequency_ok","win_rate","min_capture"],ascending=False)
    table.to_csv(OUT/"価格構造探索.csv",index=False,encoding="utf-8-sig")
    (OUT/"価格構造詳細.json").write_text(json.dumps(details,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    print(table.head(20).to_string(index=False))


if __name__=="__main__":
    main()
