"""固定した構造線、単純な追跡又は2R利確で同じ単位の期待損益を測る。"""

from __future__ import annotations

import numpy as np
from numba import njit


REASONS = {0:'新規',1:'反証線',2:'1R幅の追跡',3:'30分上限',4:'場内返済',5:'2R利確',6:'約定時に反証線を越えた'}


@njit(cache=True)
def drive(times: np.ndarray, seqs: np.ndarray, prices: np.ndarray, signals: np.ndarray,
          qty: int, value: float, trailing: bool, limit: float, finish: bool) -> tuple:
    """機能: 判断後の次有効行で売買し、全玉を同じ固定Rで評価する。

    引数: times/seqs/prices/signals(ndarray)、qty(int)、value/limit(float)、trailing/finish(bool)。
    返り値: 注文・返済・時価用保有区間・ギャップ件数(tuple)。銘柄名は受け取らない。
    """
    orders,legs,groups = np.zeros((12000,13)),np.zeros((6000,16)),np.zeros((6000,11))
    no=nl=cursor=gaps=0
    side=0
    cid=-1
    entry=entry_time=entry_seq=entry_i=entry_atr=risk=planned_risk=best=stop=target=0.
    gap_entry=0
    event_id=kind=0
    pending=pending_side=pending_reason=0
    decision_time=decision_seq=decision_stop=decision_atr=decision_risk=decision_kind=decision_event=0.
    next_entry=0.
    for i in range(len(prices)):
        now,seq,price = times[i],seqs[i],prices[i]
        if not np.isfinite(price) or price<=0:
            continue
        if pending==1:
            side=pending_side
            cid+=1
            entry,entry_time,entry_seq,entry_i,entry_atr=price,now,float(seq),float(i),decision_atr
            stop,best=decision_stop,price
            risk=side*(entry-stop)
            planned_risk,gap_entry=decision_risk,0
            pending=0
            if risk<=0:
                # 発注後の価格は入口判定へ戻さず、実際に建てた玉として即失敗を記録する。
                gaps+=1
                gap_entry=1
                risk=decision_risk
                pending,pending_reason=2,6
            event_id,kind=int(decision_event),int(decision_kind)
            target=entry+side*2*risk
            assert no<len(orders)
            orders[no]=np.array([decision_time,now,decision_seq,float(seq),1.,float(side),float(qty),price,0.,0.,float(cid),float(qty),risk])
            no+=1
            if pending:
                decision_time,decision_seq=now,float(seq)
        elif pending==2:
            pnl=side*(price-entry)*qty*value
            best=max(best,price) if side>0 else min(best,price)
            assert no<len(orders) and nl<len(legs)
            orders[no]=np.array([decision_time,now,decision_seq,float(seq),2.,float(-side),float(qty),price,pnl,float(pending_reason),float(cid),0.,risk])
            legs[nl]=np.array([entry_time,now,float(side),float(qty),entry,price,pnl,float(pending_reason),entry_atr,float(cid),decision_time,entry_seq,float(seq),decision_seq,max(0.,side*(best-entry)/entry_atr),(now-entry_time)/60.])
            groups[nl]=np.array([float(cid),float(kind),float(event_id),risk,pnl/(risk*qty*value),entry_i,float(i),float(side),entry,planned_risk,float(gap_entry)])
            no+=1
            nl+=1
            side,pending=0,0
            next_entry=now+60.
        # ----------------------------------------
        # 全ての価格行で保護を確認する。線は入口で固定し、追跡で緩めることはない。
        if side and not pending:
            best=max(best,price) if side>0 else min(best,price)
            if trailing and side*(best-entry)>=risk:
                line=best-side*risk
                stop=max(stop,line) if side>0 else min(stop,line)
            reason=0
            if now>=limit:
                reason=4
            elif side*(price-stop)<=0:
                reason=2 if side*(stop-entry)>=0 else 1
            elif not trailing and side*(price-target)>=0:
                reason=5
            elif now>=entry_time+1800.:
                reason=3
            if reason:
                pending,pending_reason=2,reason
                decision_time,decision_seq=now,float(seq)
        while cursor<len(signals) and int(signals[cursor,0])<=i:
            row=signals[cursor]
            cursor+=1
            if side or pending or now>=limit-300. or now<next_entry:
                continue
            pending,pending_side=1,int(row[1])
            decision_time,decision_seq=now,float(seq)
            decision_stop,decision_atr,decision_risk=row[2],row[3],row[7]
            decision_kind,decision_event=row[5],row[8]
    if finish and (side or pending):
        raise ValueError('場内返済する次行がありません')
    return orders[:no],legs[:nl],groups[:nl],gaps


def execute(ready: dict, signals: np.ndarray, trailing: bool, qty: int, value: float, finish: bool=True) -> dict:
    """機能: 原本順の売買から金額と固定リスクRの損益曲線を別々に再構成する。

    引数: ready(dict)、signals(ndarray)、trailing/finish(bool)、qty(int)、value(float)。
    返り値: 次行約定の台帳、金額・枚数、リスク効率の評価(dict)。
    """
    assert not len(signals) or np.all(np.diff(signals[:,0])>0)
    orders,legs,groups,gaps=drive(ready['time_s'],ready['seq'],ready['last'],signals,qty,value,trailing,ready['limit'],finish)
    cash,delta=np.zeros(len(ready['last'])),np.zeros(len(ready['last']))
    r_cash,r_delta=np.zeros(len(cash)),np.zeros(len(cash))
    planned_cash,planned_delta=np.zeros(len(cash)),np.zeros(len(cash))
    plans={}
    for o in orders:
        i=int(np.searchsorted(ready['seq'],o[3]))
        assert ready['seq'][i]==o[3] and o[2]<o[3] and o[0]<=o[1]
        if o[4]==1:
            decision_i=int(np.searchsorted(ready['seq'],o[2]))
            k=int(np.searchsorted(signals[:,0],decision_i))
            assert signals[k,0]==decision_i
            plans[int(o[10])]=signals[k,7]
        plan=plans[int(o[10])]
        cash[i]-=o[5]*o[6]*o[7]*value
        delta[i]+=o[5]*o[6]
        r_cash[i]-=o[5]*o[7]/o[12]
        r_delta[i]+=o[5]/o[12]
        planned_cash[i]-=o[5]*o[7]/plan
        planned_delta[i]+=o[5]/plan
    position=np.cumsum(delta)
    curve=np.cumsum(cash)+position*ready['last']*value
    assert np.max(abs(position),initial=0)<=qty
    pnl=legs[:,6]
    np.testing.assert_allclose(pnl,legs[:,2]*legs[:,3]*(legs[:,5]-legs[:,4])*value,atol=1e-6)
    if finish:
        assert position[-1]==0
        np.testing.assert_allclose(curve[-1],pnl.sum(),atol=1e-6)
    # ----------------------------------------
    # 1Rの金額が異なる組同士を、同じ事前リスク予算の仮想単位でも比較する。
    r_curve=np.cumsum(r_cash)+np.cumsum(r_delta)*ready['last']
    planned_curve=np.cumsum(planned_cash)+np.cumsum(planned_delta)*ready['last']
    rs=groups[:,4]
    planned_balance=float(np.sum(groups[:,4]*groups[:,3]/groups[:,9]))
    if finish:
        np.testing.assert_allclose(r_curve[-1],rs.sum(),atol=1e-6)
        np.testing.assert_allclose(planned_curve[-1],planned_balance,atol=1e-6)
    return dict(session=ready['session'],symbol=ready['symbol'],orders=orders.tolist(),trades=legs.tolist(),risk_groups=groups.tolist(),
                curve=curve,r_curve=r_curve,planned_curve=planned_curve,profit=float(pnl[pnl>0].sum()),loss=float(-pnl[pnl<0].sum()),net=float(pnl.sum()),
                win_qty=int((pnl>0).sum()*qty),loss_qty=int((pnl<0).sum()*qty),flat_qty=int((pnl==0).sum()*qty),
                cycles=len(pnl),wins=int((pnl>0).sum()),losses=int((pnl<0).sum()),
                r_net=float(rs.sum()),r_profit=float(rs[rs>0].sum()),r_loss=float(-rs[rs<0].sum()),gap_entries=int(gaps),
                planned_r_net=float(planned_balance),
                drawdown=float(np.max(np.maximum.accumulate(np.r_[0.,curve])[1:]-curve,initial=0)),
                r_drawdown=float(np.max(np.maximum.accumulate(np.r_[0.,r_curve])[1:]-r_curve,initial=0)))
