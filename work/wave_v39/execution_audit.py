"""価格配列から最初に成立する出口を独立探索し、全注文を検算する。"""

from __future__ import annotations

import numpy as np


def check(ready: dict, pulse: np.ndarray, result: dict, delay: float, observed: bool) -> dict:
    """機能: 入口候補と価格先着から全取引を別計算し、会計も照合する。

    引数: ready/result (dict)、pulse (ndarray[int8])、delay (float)、observed (bool)。
    返り値: 合否・原本行数・取引数 (dict)。売買エンジンを期待値生成に呼ばない。
    """
    t,p = ready['time_s'],ready['last']
    n = len(t);trades=[];orders=[];last_row=-1;last_time=-np.inf;accepted=cancelled=0
    for decision in np.flatnonzero(pulse):
        if decision <= last_row or t[decision] < last_time+300 or t[decision] >= ready['limit']-300:
            continue
        if not np.isfinite(ready['atr'][decision]) or ready['atr'][decision] <= 0:
            continue
        accepted += 1
        entered=max(int(decision)+1,int(np.searchsorted(t,t[decision]+delay,side='left')))
        cancellation=int(np.searchsorted(t,ready['limit'],side='left'))
        if cancellation<n and cancellation<=entered:
            last_row=cancellation;cancelled+=1
            continue
        assert entered<n and t[entered]<ready['limit']
        d=int(pulse[decision]);entry=p[entered]
        r=np.ceil(max(ready['atr'][decision],2*ready['tick'])/ready['tick'])*ready['tick']
        mature=max(entered+1,int(np.searchsorted(t,t[entered]+delay,side='left')))
        request_time=min(t[entered]+1800,ready['limit'])
        request=max(entered,int(np.searchsorted(t,request_time,side='left')))
        forced=max(request+1,int(np.searchsorted(t,t[request]+delay,side='left'))) if request<n else n
        stop=entry-d*r;target=entry+d*2*r
        search_end=min(n,forced+1)
        local=p[mature:search_end]
        crossings=np.flatnonzero((d*(local-stop)<=0)|(d*(local-target)>=0))
        if len(crossings):
            exited=mature+int(crossings[0]);source=entered
            reason=1 if d*(p[exited]-stop)<=0 else 2
            fill=p[exited] if observed else stop if reason==1 else target
        else:
            exited=forced;source=request
            assert exited<n
            fill=p[exited]
            reason=4 if t[request]>=ready['limit'] else 3
        assert t[exited]<ready.get('session_close',ready['limit']+600.)
        trades.append([entered,exited,d,entry,fill,r,d*(fill-entry),reason,decision,source])
        orders.extend([[entered,decision,d,1,entry,0,1],[exited,source,-d,1,fill,reason,0]])
        last_row=exited;last_time=t[exited]
    expected_trades=np.asarray(trades,float).reshape((-1,10))
    expected_orders=np.asarray(orders,float).reshape((-1,7))
    np.testing.assert_allclose(result['trades'],expected_trades,rtol=0,atol=1e-9)
    np.testing.assert_allclose(result['orders'],expected_orders,rtol=0,atol=1e-9)
    # ----------------------------------------
    # 全注文と全返済損益から、全原本行の現金・保有・含み損益を独立に復元する。
    changes=np.zeros((n,3))
    for row,source,d,q,price,reason,opening in expected_orders:
        row=int(row);changes[row,:2] += [-d*q*price,d*q]
    for trade in expected_trades:changes[int(trade[1]),2]+=trade[6]
    amounts=changes.cumsum(axis=0)
    equity=amounts[:,0]+amounts[:,1]*p
    dd=np.maximum.accumulate(np.maximum(equity,0))-equity
    curve=np.column_stack([amounts[:,2],equity,amounts[:,1],dd])
    np.testing.assert_allclose(result['curve'],curve,rtol=0,atol=1e-8)
    assert amounts[-1,1]==0 and result['stats'][5]==result['stats'][6]==0
    assert (abs(amounts[:,1])<=1).all()
    np.testing.assert_allclose(result['stats'][:2],[amounts[-1,2],dd.max()],rtol=0,atol=1e-8)
    assert result['stats'][2] == np.count_nonzero(pulse)
    assert result['stats'][3] == accepted and result['stats'][4] == cancelled
    return dict(全注文の成立脱落一致=True,全原本行会計一致=True,
        原本行数=n,取引数=len(trades),場内返済=True,API取得数=0)
