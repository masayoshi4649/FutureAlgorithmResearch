"""共通の初回建玉一組へ、未来の元終了を使わず出口部品を適用する。"""

from __future__ import annotations

import numpy as np
from numba import njit

ORDER_COLUMNS = ['row','decision_row','campaign','side','qty','price','reason','opening']
TRADE_COLUMNS = ['campaign','leg','side','qty','entry_price','exit_price','entry_row','exit_row','role','reason','pnl']
CURVE_COLUMNS = ['equity','realized','long','short','drawdown','cash','net_qty','campaign']
PLAN_COLUMNS = ['source_row','qty','stop','trail','partial','target','market_flags',
                'market_reason','market_source','budget_pending','budget_source','extreme','partial_done']
REASONS = {1:'元組損切り',2:'追跡返済',7:'元部分利確',8:'360分等の保有期限',9:'場内返済',
           15:'固定目標の全利確',20:'共通の初回建玉',32:'実組損失予算'}
ENTRY_KEYS = {'row','decision_row','side','qty','price','initial_atr','initial_risk','campaign'}


@njit(cache=True)
def rounded(value: float, tick: float, side: int) -> float:
    """機能: 売買方向に従い旧価格注文と同じ呼値へ丸める。

    引数: value/tick(float)、side(int)。返り値: 呼値上の価格(float)。
    """
    return np.ceil(value/tick-1e-9)*tick if side>0 else np.floor(value/tick+1e-9)*tick


@njit(cache=True)
def simulate(time, price, entry, par, tick, limit, session_close, observed, detail):
    """機能: 一組の有効注文を前行から引き継ぎ、全返済まで原本行を進める。

    引数: time/price/entry/par(ndarray)、tick/limit/session_close(float)、observed/detail(bool)。
    返り値: 注文・返済・曲線・計画・元組・統計(tuple[ndarray,...])。
    """
    n=len(price); start=int(entry[0]); side=int(entry[2]); q0=int(entry[3]); qty=0
    anchor=entry[4]; a=entry[5]; risk=entry[6]; campaign=int(entry[7])
    orders=np.zeros((4,8)); trades=np.zeros((3,11)); cycles=np.zeros((1,10)); oc=0; tc=0; cc=0
    curve=np.zeros((n,8)) if detail else np.zeros((0,8))
    plans=np.full((n,13),np.nan) if detail else np.zeros((0,13))
    realized=0.;cash=0.;high=0.;dd=0.;min_equity=0.;max_equity=0.;max_error=0.
    levels=np.full(4,np.nan);flags=np.zeros(4,np.bool_);extreme=anchor;trail_floor=np.nan
    split_done=False;pending=0;pending_row=-1;budget=False;budget_row=-1;closed=False
    for i in range(start,n):
        t=time[i];p=price[i]
        if not np.isfinite(p) or p<=0:
            if detail and i>start:
                curve[i]=curve[i-1];plans[i]=plans[i-1]
            continue
        if t>=session_close and qty>0:
            raise ValueError('終場までに返済できません')
        reason=0;fill=0.;done=0;source=i-1
        if i==start:
            qty=q0;cash=-side*qty*anchor
            orders[oc]=np.array([i,entry[1],campaign,side,qty,anchor,20.,1.]);oc+=1
        elif qty>0:
            # ----------------------------------------
            # 元市場予約を先に扱い、価格注文の同値順位と実予算の後順位を維持する。
            if pending:
                reason=pending;source=pending_row;fill=p;done=qty
            else:
                best=1e100;prior=price[i-1]
                for z in range(4):
                    level=levels[z];order_side=-side if z<2 else side
                    if not np.isfinite(level) or (not flags[z] and order_side*(p-level)<-1e-8):
                        continue
                    distance=0. if flags[z] else max(0.,order_side*(level-prior))
                    if distance<best-1e-9:
                        best=distance;reason=1 if z==0 else (2 if z==1 else (7 if z==2 else 15))
                        fill=p if observed or flags[z] else level
                        done=max(1,qty//2) if z==2 else qty
                if not reason and budget:
                    reason=32;fill=p;done=qty;source=budget_row
            if reason:
                gain=done*side*(fill-anchor);realized+=gain;cash+=side*done*fill;qty-=done
                orders[oc]=np.array([i,source,campaign,-side,done,fill,reason,0.]);oc+=1
                trades[tc]=np.array([campaign,0.,side,done,anchor,fill,start,i,0.,reason,gain]);tc+=1
                if reason==7:split_done=True
                if qty==0:
                    cycles[cc]=np.array([campaign,start,i,realized,risk,a,q0,q0,side,reason]);cc+=1
                    closed=True;pending=0;budget=False
        equity=realized+side*qty*(p-anchor)
        max_error=max(max_error,abs(equity-(cash+side*qty*p)))
        high=max(high,equity);dd=max(dd,high-equity);min_equity=min(min_equity,equity);max_equity=max(max_equity,equity)
        if detail:
            curve[i]=np.array([equity,realized,qty if side>0 else 0.,qty if side<0 else 0.,dd,cash,side*qty,campaign])
        levels[:]=np.nan;flags[:]=False
        if qty:
            # ----------------------------------------
            # 現在価格による更新は、この行の判定が終わった後にだけ設置する。
            extreme=max(extreme,p) if side>0 else min(extreme,p)
            levels[0]=rounded((-risk-realized+side*qty*anchor)/(side*qty),tick,-side)
            mfe=side*(extreme-anchor)/a
            if par[2]>0 and mfe>=par[3]:
                width=par[2]
                if par[6]>0 and mfe>=par[6]:width=min(width,par[7])
                candidate=rounded(extreme-side*width*a,tick,-side)
                if not np.isfinite(trail_floor) or side*(candidate-trail_floor)>0:
                    trail_floor=candidate
                levels[1]=trail_floor
            if par[1]>0 and not split_done and qty>=2:
                levels[2]=rounded(anchor+side*par[1]*a,tick,side)
            if par[5]>0:levels[3]=rounded(anchor+side*par[5]*a,tick,side)
            if t>=limit:pending=9;pending_row=i
            elif equity<=-risk-1e-8:pending=1;pending_row=i
            elif par[4]>0 and t-time[start]>=par[4]*60:pending=8;pending_row=i
            if par[8]>0 and equity<=-risk and not budget:budget=True;budget_row=i
            for z in range(4):
                order_side=-side if z<2 else side
                flags[z]=np.isfinite(levels[z]) and order_side*(p-levels[z])>=-1e-8
        if detail:
            mask=int(flags[0])+2*int(flags[1])+4*int(flags[2])+8*int(flags[3])
            plans[i]=np.array([i,qty,levels[0],levels[1],levels[2],levels[3],mask,
                               pending,pending_row,int(budget),budget_row,extreme,int(split_done)])
    stats=np.array([realized,dd,q0 if side>0 else 0.,q0 if side<0 else 0.,q0,q0,
                    max_error,min_equity,max_equity,qty,0.])
    return orders[:oc],trades[:tc],cycles[:cc],curve,plans,stats


def run(ready: dict, entry: dict, spec: dict, *, observed_fill: bool=False,
        detail: bool=True, require_complete: bool=True) -> dict:
    """機能: 既知の共通初回から一つの出口を実験し、元の終了行は使用しない。

    引数: ready/entry/spec(dict)、observed_fill/detail/require_complete(bool)。
    返り値: 台帳・曲線・公開計画・完済判定(dict)。金額単位は価格差×枚数。
    """
    if set(entry)!=ENTRY_KEYS:raise ValueError('初回入力は固定8項目だけです。元終了行は渡せません')
    for value in (observed_fill,detail,require_complete):
        if not isinstance(value,(bool,np.bool_)):raise ValueError('検査モードは真偽値です')
    t=np.asarray(ready['time_s']);p=np.asarray(ready['last']);seq=np.asarray(ready['seq'])
    if any(x.ndim!=1 for x in (t,p,seq)) or not len(t) or len(t)!=len(p) or len(t)!=len(seq):
        raise ValueError('時刻・価格・行は同じ長さの一次元配列です')
    if not np.isfinite(t).all() or (np.diff(t)<0).any() or not np.issubdtype(seq.dtype,np.integer) or (np.diff(seq)<=0).any():
        raise ValueError('時刻と原本行順が不正です')
    for k in ('row','decision_row','side','qty','campaign'):
        if isinstance(entry[k],(bool,np.bool_)) or int(entry[k])!=entry[k]:raise ValueError('初回の整数項目が不正です')
    row=int(entry['row']);side=int(entry['side']);qty=int(entry['qty'])
    if not 0<=entry['decision_row']<row<len(p) or side not in (-1,1) or qty not in (5,10):
        raise ValueError('共通初回の判断行・数量・方向が不正です')
    if not np.isfinite(p[row]) or p[row]<=0:raise ValueError('初回には有効観測が必要です')
    for k in ('price','initial_atr','initial_risk'):
        if not np.isfinite(entry[k]) or entry[k]<=0:raise ValueError('初回価格・ATR・Rは有限正値です')
    if not np.isclose(entry['initial_risk'],qty*entry['initial_atr'],rtol=1e-12,atol=1e-10):
        raise ValueError('初期組予算は初回枚数×初期ATRです')
    tick=float(ready['tick']);limit=float(ready['limit']);close=float(ready.get('session_close',limit+600))
    if not np.isfinite([tick,limit,close]).all() or tick<=0 or limit>=close or t[row]>=limit:
        raise ValueError('呼値又は場末時刻が不正です')
    param=spec['params'];names=['stop_atr','split_atr','trail_atr','activation_atr','timeout_min',
                              'target_atr','tighten_atr','tight_width','budget_enabled']
    if set(param)!=set(names) or param['stop_atr']!=1 or not isinstance(param['budget_enabled'],bool):
        raise ValueError('初期1ATR・固定パラメータ集合が必要です')
    par=np.array([param[x] for x in names],float)
    if not np.isfinite(par).all() or (par<0).any():raise ValueError('出口幅は有限非負です')
    ev=np.array([entry[x] for x in ['row','decision_row','side','qty','price','initial_atr','initial_risk','campaign']],float)
    arrays=simulate(t.astype(float),p.astype(float),ev,par,tick,limit,close,bool(observed_fill),bool(detail))
    result=dict(zip(['orders','trades','cycles','curve','plans','stats'],arrays))
    result['closed']=bool(result['stats'][9]==0)
    if require_complete and not result['closed']:raise ValueError('完結入力に未返済玉があります。末尾で架空返済しません')
    return result
