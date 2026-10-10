"""価格による継続波の独立探索。保存済み足だけを読み、外部通信・注文はしない。"""

from __future__ import annotations

from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
TICKS = {"NK225": 10.0, "TOPIX": 0.5}


def read_frame(symbol: str, session: str, minutes: int = 5) -> pd.DataFrame:
    """機能: 保存足を読み、セッション内の規則的な時刻軸へ配置する。

    引数: symbol (str) は銘柄、session (str) はセッション、minutes (int) は足分数。
    返り値: 足終端を時刻索引とする価格系列 (DataFrame)。
    """
    z = pd.read_csv(ROOT / f"candle_{minutes}min" / symbol / f"{session}.csv")
    z = z[z.closed].copy()
    z["time"] = pd.to_datetime(z.time) + pd.Timedelta(minutes=minutes)
    z = z.set_index("time").sort_index()
    z["observed"] = True
    grid = pd.date_range(z.index[0], z.index[-1], freq=f"{minutes}min")
    z = z.reindex(grid)
    z["observed"] = z.observed.fillna(False).astype(bool)
    z["close"] = z.close.ffill(limit=max(1, 15 // minutes))
    for key in ("open", "high", "low"):
        z[key] = z[key].fillna(z.close)
    z["volume"] = z.volume.fillna(0)
    return z


def features(z: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """機能: 確定済み足から時間幅を統一した特徴を計算する。

    引数: z (DataFrame) は価格系列、minutes (int) は足分数。
    返り値: 因果的特徴量付き系列 (DataFrame)。
    """
    z = z.copy()
    c = z.close
    tr = pd.concat([z.high-z.low, (z.high-c.shift()).abs(), (z.low-c.shift()).abs()], axis=1).max(axis=1)
    z["atr"] = tr.ewm(span=max(4, 60 // minutes), min_periods=max(4, 20 // minutes), adjust=False).mean()
    # ----------------------------------------
    for n in (10, 15, 20, 30, 40, 60, 90):
        w = max(2, n // minutes)
        z[f"ema{n}"] = c.ewm(span=w, adjust=False, min_periods=min(w, max(4, 30 // minutes))).mean()
        z[f"move{n}"] = (c-c.shift(w)) / z.atr
        z[f"er{n}"] = (c-c.shift(w)).abs() / c.diff().abs().rolling(w).sum().replace(0, np.nan)
        z[f"high{n}"] = z.high.rolling(w).max().shift(1)
        z[f"low{n}"] = z.low.rolling(w).min().shift(1)
        x = np.arange(w) - (w-1)/2
        xx = np.dot(x, x)
        z[f"reg{n}"] = c.rolling(w).apply(lambda a: np.dot(x, a) * (w-1) / xx, raw=True) / z.atr
        z[f"r2_{n}"] = c.rolling(w).apply(lambda a: np.dot(x, a-a.mean())**2 / (xx*np.dot(a-a.mean(),a-a.mean())) if np.ptp(a) else 0, raw=True)
    z["slope40"] = (z.ema40-z.ema40.shift(max(1,10//minutes))) / z.atr
    z["slope60"] = (z.ema60-z.ema60.shift(max(1,10//minutes))) / z.atr
    # ----------------------------------------
    volume = z.volume.where(z.volume.gt(0), 0)
    z["vwap"] = ((z.high+z.low+z.close)/3*volume).cumsum() / volume.cumsum()
    # ----------------------------------------
    up, down = z.high.diff(), -z.low.diff()
    plus = up.where((up>down)&(up>0),0).ewm(span=max(4,40//minutes),adjust=False).mean()
    minus = down.where((down>up)&(down>0),0).ewm(span=max(4,40//minutes),adjust=False).mean()
    z["di"] = (plus-minus)/(plus+minus).replace(0,np.nan)
    z["rsi_score"] = c.diff().ewm(span=max(4,30//minutes),adjust=False).mean() / c.diff().abs().ewm(span=max(4,30//minutes),adjust=False).mean().replace(0,np.nan)
    z["age"] = (z.index-z.index[0]).total_seconds()/60 + minutes
    return z


def candidates(z: pd.DataFrame, other: pd.DataFrame, minutes: int, q: float) -> dict[str, pd.Series]:
    """機能: 複数の継続波開始条件を独立に計算する。

    引数: z/other (DataFrame) は自他指数の特徴、minutes (int) は足分数、q (float) は閾値倍率。
    返り値: 名称から方向系列への対応 (dict[str, Series])。
    """
    gap = (z.ema15-z.ema40) / z.atr
    gap_slow = (z.ema20-z.ema60) / z.atr
    peer_gap = (other.ema15-other.ema40).reindex(z.index) / other.atr.reindex(z.index)
    ema = np.sign(gap).where((gap.abs()>=.2*q)&(gap*z.slope40>0),0)
    reg = np.sign(z.reg30).where((z.reg30.abs()>=.8*q)&(z.r2_30>=.35),0)
    er = np.sign(z.move30).where((z.move30.abs()>=.8*q)&(z.er30>=.3),0)
    don = pd.Series(np.where(z.close>z.high30,1,np.where(z.close<z.low30,-1,0)), index=z.index)
    result = {
        "移動平均15_40": ema,
        "移動平均20_60": np.sign(gap_slow).where((gap_slow.abs()>=.2*q)&(gap_slow*z.slope60>0),0),
        "回帰30": reg,
        "回帰60": np.sign(z.reg60).where((z.reg60.abs()>=.8*q)&(z.r2_60>=.3),0),
        "方向効率30": er,
        "方向効率60": np.sign(z.move60).where((z.move60.abs()>=1*q)&(z.er60>=.25),0),
        "高安値30突破": don,
        "方向指数": np.sign(z.di).where((z.di.abs()>=.2*q)&(z.di*z.move20>0),0),
        "相対力": np.sign(z.rsi_score).where((z.rsi_score.abs()>=.2*q)&(z.rsi_score*gap>0),0),
        "二指数平均一致": ema.where(gap*peer_gap>0,0),
        "二時間帯一致": np.sign(z.move20).where((z.move20*z.move40>0)&(z.move20.abs()>=.5*q)&(z.move40.abs()>=.8*q),0),
        "出来高平均回復": np.sign(z.close-z.vwap).where(((z.close-z.vwap).abs()/z.atr>.3*q)&((z.close-z.vwap)*gap>0),0),
    }
    votes = pd.concat([ema, reg, er, np.sign(z.di).where(z.di.abs()>=.2*q,0)],axis=1)
    result["価格四条件多数"] = pd.Series(np.where(votes.eq(1).sum(axis=1)>=3,1,np.where(votes.eq(-1).sum(axis=1)>=3,-1,0)),index=z.index)
    return {name: s.fillna(0).where(z.age>=30,0).astype(int) for name,s in result.items()}


def regime(z: pd.DataFrame, signal: pd.Series, minutes: int, confirm: int, exit_mode: str) -> pd.Series:
    """機能: 入力条件の連続確認と反対方向の確認で継続波状態を更新する。

    引数: z (DataFrame)、signal (Series)、minutes/confirm (int)、exit_mode (str)。
    返り値: ロング１・中立０・ショート−１の持続状態 (Series)。
    """
    state = 0
    streak = 0
    previous = 0
    adverse = 0
    values = []
    gap = ((z.ema15-z.ema40)/z.atr).to_numpy()
    slope = z.slope40.to_numpy()
    neutral = 0
    for i, side in enumerate(signal.to_numpy()):
        if side and side == previous:
            streak += 1
        else:
            streak = 1 if side else 0
        previous = side
        if side and streak >= confirm:
            state = int(side)
        adverse = adverse+1 if state and state*gap[i]<-.1 and state*slope[i]<0 else 0
        neutral = neutral+1 if side==0 else 0
        if exit_mode=="平均逆転" and adverse>=confirm:
            state = 0
        if exit_mode=="中立60分" and neutral*minutes>=60:
            state=0
        values.append(state)
    return pd.Series(values,index=z.index)


def evaluate(z: pd.DataFrame, state: pd.Series, symbol: str, session: str, minutes: int) -> tuple[dict,list[dict]]:
    """機能: 次足始値による参考売買と、明示された代表波との重なりを採点する。

    引数: z (DataFrame)、state (Series)、symbol/session (str)、minutes (int)。
    返り値: 集計辞書と連続波の一覧 (tuple[dict, list[dict]])。
    """
    first = z.index[0]
    end = first.normalize()+pd.Timedelta(hours=15,minutes=35) if "Day" in session else first.normalize()+pd.Timedelta(days=1,hours=5,minutes=50)
    events = []
    active = None
    times = z.index
    opens = z.open.to_numpy()
    closes = z.close.to_numpy()
    observed = z.observed.to_numpy()
    sides = state.to_numpy()
    holding = np.zeros(len(z), dtype=int)
    for i, t in enumerate(times):
        if t>=end:
            if active is not None:
                exact = i+1<len(z) and observed[i+1] and t==end
                prior = np.flatnonzero(observed & (times<=end))
                exit_price = opens[i+1] if exact else closes[prior[-1]]
                active["end"] = end.isoformat()
                active["exit"] = float(exit_price)
                active["exit_approximate"] = not exact
                active["ticks"] = active["side"]*(active["exit"]-active["entry"])/TICKS[symbol]-2
                active["minutes"] = (end-pd.Timestamp(active["start"])).total_seconds()/60
                events.append(active)
                active = None
            break
        if i+1>=len(z) or not bool(observed[i+1]):
            holding[i] = active["side"] if active else 0
            continue
        side = int(sides[i])
        if active is not None and side != active["side"]:
            active["end"] = t.isoformat()
            active["exit"] = float(opens[i+1])
            active["exit_approximate"] = False
            active["ticks"] = active["side"]*(active["exit"]-active["entry"])/TICKS[symbol]-2
            active["minutes"] = (t-pd.Timestamp(active["start"])).total_seconds()/60
            events.append(active)
            active = None
        if active is None and side and t<end:
            active = {"symbol":symbol,"session":session,"side":side,"start":t.isoformat(),"entry":float(opens[i+1])}
        holding[i] = active["side"] if active else 0
    if active is not None:
        raise ValueError(f"セッション内返済を確認できない: {symbol}/{session}")
    result = {"count":len(events),"wins":sum(e["ticks"]>0 for e in events),"ticks":sum(e["ticks"] for e in events),"duration":sum(e["minutes"] for e in events)}
    # ----------------------------------------
    if "Day" in session:
        a,b,side = ("10:45","15:40",1) if session.startswith("2026-09-21") else ("09:20","11:45",-1)
        start = pd.Timestamp(f"{session[:10]} {a}",tz="Asia/Tokyo")
        finish = pd.Timestamp(f"{session[:10]} {b}",tz="Asia/Tokyo")
        effective = state.where(state.index<end,0)
        target = effective[(effective.index>=start)&(effective.index<finish)]
        held = pd.Series(holding,index=z.index)
        held_target = held[(held.index>=start)&(held.index<finish)]
        result["state_coverage"] = float(target.eq(side).mean())
        result["holding_coverage"] = float(held_target.eq(side).mean())
        result["opposite"] = float(target.eq(-side).mean())
        matching = target[target.eq(side)]
        result["first"] = matching.index[0].isoformat() if len(matching) else None
        result["matched_events"] = [e for e in events if e["side"]==side and pd.Timestamp(e["start"])<finish and pd.Timestamp(e["end"])>start]
    return result, events


def main() -> None:
    """機能: 価格開始条件と持続状態の候補を比較し、探索表を保存する。

    引数: なし。返り値: なし (None)。
    """
    all_rows = []
    all_events = {}
    details = {}
    sessions = sorted(p.stem for p in (ROOT/"candle_5min"/"NK225").glob("*.csv"))
    for minutes in (5,1):
        data = {(sym,ses):features(read_frame(sym,ses,minutes),minutes) for sym in TICKS for ses in sessions}
        for q in (.75,1,1.25):
            signals = {(sym,ses):candidates(z,data[("TOPIX" if sym=="NK225" else "NK225",ses)],minutes,q) for (sym,ses),z in data.items()}
            for family in next(iter(signals.values())):
                for confirm in (max(1,5//minutes),max(2,10//minutes)):
                    for exit_mode in ("反対確認","平均逆転","中立60分"):
                        key = f"{minutes}分_{family}_{q}_{confirm}_{exit_mode}"
                        row = {"key":key,"minutes":minutes,"family":family,"q":q,"confirm":confirm,"exit_mode":exit_mode}
                        results=[]
                        events=[]
                        det=[]
                        for (sym,ses),z in data.items():
                            state = regime(z,signals[(sym,ses)][family],minutes,confirm,exit_mode)
                            result, ev = evaluate(z,state,sym,ses,minutes)
                            results.append(result)
                            events.extend(ev)
                            det.append({"symbol":sym,"session":ses,**result})
                        row["count"] = sum(r["count"] for r in results)
                        row["win_rate"] = sum(r["wins"] for r in results) / max(1,row["count"])
                        row["ticks"] = sum(r["ticks"] for r in results)
                        row["mean_minutes"] = sum(r["duration"] for r in results)/max(1,row["count"])
                        target = [r for r in results if "state_coverage" in r]
                        row["target_state_min"] = min(r["state_coverage"] for r in target)
                        row["target_state_mean"] = np.mean([r["state_coverage"] for r in target])
                        row["target_holding_min"] = min(r["holding_coverage"] for r in target)
                        row["target_holding_mean"] = np.mean([r["holding_coverage"] for r in target])
                        row["target_opposite"] = np.mean([r["opposite"] for r in target])
                        for r,d in zip(results,det):
                            row[f'{d["symbol"]}_{d["session"]}_ticks']=r["ticks"]
                            if "state_coverage" in r:
                                row[f'{d["symbol"]}_{d["session"]}_state_coverage']=r["state_coverage"]
                                row[f'{d["symbol"]}_{d["session"]}_holding_coverage']=r["holding_coverage"]
                        all_rows.append(row)
                        all_events[key] = events
                        details[key] = det
    # ----------------------------------------
    table = pd.DataFrame(all_rows)
    table = table.sort_values(["target_holding_min","win_rate","ticks"],ascending=False)
    table.to_csv(OUT/"価格探索.csv",index=False,encoding="utf-8-sig")
    (OUT/"価格探索詳細.json").write_text(json.dumps(details,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"価格探索イベント.json").write_text(json.dumps(all_events,ensure_ascii=False,indent=2),encoding="utf-8")
    print(table[["key","count","win_rate","ticks","target_holding_min","target_holding_mean","target_opposite"]].head(25).to_string(index=False))


if __name__ == "__main__":
    main()
