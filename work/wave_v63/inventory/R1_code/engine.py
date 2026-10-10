"""先に待機した指値と次原本行の成行を分け、単一在庫を費用込みで再生する。"""

import numpy as np
from numba import njit


ORDER_COLUMNS = ['id','decision_i','fill_i','decision_time','fill_time','kind','side','qty','price','fee','gross','reason']
GROUP_COLUMNS = ['id','side','qty','entry_i','exit_i','entry_time','exit_time','entry_price','exit_price','gross','fees','net','reason','mfe','mae']
REASONS = {1:'新規',2:'場内返済',3:'初期損切り',4:'利益保護',5:'目標利確',6:'15分期限',7:'場利益保護'}


@njit(cache=True)
def drive(times, bid, ask, signal, width, tick, quantity, multiplier, fee_tenths,
          limit, mode, protect=0, session_lock=0, finish=True):
    """機能: 追加なしの単一在庫を、待機済み指値と次行成行で因果的に再生する。

    引数: times/bid/ask/signal(ndarray)、width/tick/multiplier/limit(float)、quantity/fee_tenths/mode/protect/session_lock(int)、finish(bool)。
    返り値: 注文・全flat組・時価・数量・候補件数・待機件数(tuple)。mode0気配、1新規指値、2新規利確指値、3中値。
    指値は前行から待機していることとラージ1呼値の通過が必要。新規と返済に同一行を再使用しない。
    """
    n=len(times)
    orders=np.empty((n*2,12),np.float64)
    groups=np.empty((n,15),np.float64)
    curve=np.zeros(n,np.float64)
    inventory=np.zeros(n,np.int8)
    no=ng=0
    side=0
    entry=entry_time=entry_fee=0.
    entry_i=-1
    best=worst=stop=target=0.
    pending=0
    decision_i=-1
    pending_reason=0
    waiting_side=0
    waiting_price=waiting_until=0.
    waiting_i=-1
    cash=peak=0.
    cooldown=-1.
    halted=False
    count_signal=count_wait=count_expired=0
    tp_width=np.ceil(1.5*width/tick-1e-12)*tick
    fee=quantity*fee_tenths//10
    for i in range(n):
        now=times[i]
        mid=(bid[i]+ask[i])*.5
        filled=False
        close=False
        fill_price=0.
        reason=0
        fill_decision=-1
        # ----------------------------------------
        # 先に発注済みの成行を実行する。締切後の新規は取り消す。
        if pending!=0:
            if pending==1:
                if now<limit-300 and not halted:
                    side=waiting_side
                    fill_price=mid if mode==3 else (ask[i] if side>0 else bid[i])
                    filled=True
                    fill_decision=decision_i
                waiting_side=0
            else:
                assert side!=0
                assert now<limit+300, '場内返済可能なザラバ時刻を越えました'
                fill_price=mid if mode==3 else (bid[i] if side>0 else ask[i])
                close=True
                reason=pending_reason
                fill_decision=decision_i
            pending=0
        # ----------------------------------------
        # 待機指値の約定は当行の判断より前。現在の判断による過去取消はしない。
        if side==0 and waiting_side!=0 and pending==0:
            if now>=waiting_until or now>=limit-300 or halted:
                waiting_side=0
                count_expired+=1
            elif i>waiting_i and ((waiting_side>0 and ask[i]<=waiting_price-tick) or
                                 (waiting_side<0 and bid[i]>=waiting_price+tick)):
                side=waiting_side
                waiting_side=0
                fill_price=waiting_price
                filled=True
                fill_decision=waiting_i
        if side!=0 and not filled and not close and mode==2 and i>entry_i:
            if (side>0 and bid[i]>=target+tick) or (side<0 and ask[i]<=target-tick):
                close=True
                fill_price=target
                reason=5
                fill_decision=entry_i
        # ----------------------------------------
        # 約定会計は全flatまで一組。各注文ごとの費用を一度だけ計上する。
        if filled:
            entry=fill_price
            entry_time=now
            entry_i=i
            entry_fee=fee
            cash-=fee
            best=worst=(mid if mode==3 else (bid[i] if side>0 else ask[i]))
            stop=entry-side*width
            target=entry+side*tp_width
            orders[no]=np.array([no,fill_decision,i,times[fill_decision],now,1,side,quantity,entry,fee,0.,1.])
            no+=1
        if close:
            last_liquid=mid if mode==3 else (bid[i] if side>0 else ask[i])
            if side*(last_liquid-best)>0:
                best=last_liquid
            if side*(last_liquid-worst)<0:
                worst=last_liquid
            gross=side*(fill_price-entry)*quantity*multiplier
            cash+=gross-fee
            orders[no]=np.array([no,fill_decision,i,times[fill_decision],now,2,-side,quantity,fill_price,fee,gross,reason])
            no+=1
            groups[ng]=np.array([ng,side,quantity,entry_i,i,entry_time,now,entry,fill_price,gross,entry_fee+fee,
                                 gross-entry_fee-fee,reason,max(0.,side*(best-entry)),min(0.,side*(worst-entry))])
            ng+=1
            side=0
            cooldown=now+60.
        # ----------------------------------------
        # 管理は返済可能気配で判定。中値版だけ中値を管理・約定ともに使う。
        liquid=mid if mode==3 else (bid[i] if side>0 else ask[i])
        equity=cash+(side*(liquid-entry)*quantity*multiplier if side else 0.)
        peak=max(peak,equity)
        if side!=0:
            if side*(liquid-best)>0:
                best=liquid
            if side*(liquid-worst)<0:
                worst=liquid
            if protect and side*(best-entry)>=width:
                break_even=entry+side*(2.*fee/(quantity*multiplier)+tick)
                trailing=best-side*np.ceil(.5*width/tick-1e-12)*tick
                desired=max(break_even,trailing) if side>0 else min(break_even,trailing)
                stop=max(stop,desired) if side>0 else min(stop,desired)
            reason=0
            if now>=limit-60:
                reason=2
            elif side*(liquid-stop)<=0:
                reason=4 if side*(stop-entry)>0 else 3
            elif session_lock and peak>=3.*width*quantity*multiplier and equity<=peak-width*quantity*multiplier:
                reason=7
                halted=True
            elif mode!=2 and side*(liquid-target)>=0:
                reason=5
            elif now-entry_time>=900.:
                reason=6
            if reason:
                pending=2
                decision_i=i
                pending_reason=reason
        elif session_lock and peak>=3.*width*quantity*multiplier and equity<=peak-width*quantity*multiplier:
            halted=True
        curve[i]=equity
        inventory[i]=side
        if now>=limit-60:
            waiting_side=0
        if side==0 and pending==0 and waiting_side==0 and now>=cooldown and now<limit-300 and not halted and signal[i]!=0:
            count_signal+=1
            waiting_side=int(signal[i])
            if mode in (1,2):
                waiting_price=bid[i] if waiting_side>0 else ask[i]
                waiting_i=i
                waiting_until=now+60.
                count_wait+=1
            else:
                pending=1
                decision_i=i
    if finish:
        assert side==0 and pending!=2, '全場内返済に必要な次原本行がありません'
    return orders[:no],groups[:ng],curve,inventory,np.array([count_signal,count_wait,count_expired])
