"""影paperと実親を分け、保有容量・親純清算・次正常返済を逐次運転する。"""

import numpy as np
from numba import njit
from order_kernel import execute


@njit(cache=True)
def fee(quantity, numerator, denominator):
    """
    機能: 一実注文の税込料金を整数有理数から切り捨てる。
    引数: quantity/numerator/denominator(int) は枚数と片道料の分数。
    返り値: int は一注文の支払円額。
    """
    return quantity*numerator//denominator


@njit(cache=True)
def simulate(times,prices,bid,ask,qok,feed,quiet,quiet_force,start,end,cap,tick,multiplier,
             numerator,denominator,accepted,allowances,requested,quantity_mode,exit_mode,
             choice_fraction,parent_stop_fraction,target_fraction,arm_fraction,draw_fraction,
             floor_fraction,partial_arm_fraction,partial_fraction,session_stop_fraction):
    """
    機能: 公開FAKと影全候補を保ち、実親の独立出口・部分・場停止を次正常へ予約する。
    引数: 時計/価格/両気配/資格/feed/静観/accepted/allowances(ndarray)、期間/倍率/率(float)、容量/枚数/mode/料(int)。
    返り値: tuple は注文・UID・十列清算・二十列公開・十二列判断・十六列執行・十二列実親起点。
    """
    n=len(times);assert n>0 and len(accepted)==len(allowances)==n
    assert 0<requested<=cap and quantity_mode in (0,1) and exit_mode in (0,1,2,3)
    assert np.all((allowances==0)|(allowances==1))
    capacity=max(128,len(feed)*8+32)
    if len(feed):capacity=max(capacity,int(feed[:,2].max())+2)
    orders=np.zeros((capacity,8));trades=np.zeros((capacity*max(2,cap),11))
    uids=np.full(capacity,-1,np.int64);slots=np.zeros((capacity,7));inventory=np.zeros((3,2),np.int64)
    counters=np.zeros(9);bookparents=np.zeros((capacity,11));bookparents[:,0:3]=-1
    curve=np.zeros((n,10));publications=np.zeros((capacity,20));pc=0
    judgments=np.zeros((capacity*6,12));jc=0;events=np.zeros((capacity*6,16));ec=0
    origins=np.zeros((capacity,12));origin_count=0
    queue_source=np.zeros(capacity,np.int64);queue_quantity=np.zeros(capacity,np.int64);queue_reason=np.zeros(capacity,np.int64);queued=0
    paid=0;markbid=0.;markask=0.;pointer=0;virtual_cid=-1;vcore=0;virtual_initial=0
    pending=False;pubrow=-1;pendingcid=-1;pending_side=0;pendingqty=0;pendingcap=0.;pendingatr=0.;pending_allowance=0
    realcid=-1;side=0;initialqty=0;remaining=0;actualentry=0.;notional=0.;parent_base=0.;parent_peak=-np.inf
    armed=False;partial_done=False;full_pending=False;gu_reserved=0;entryrow=-1
    first_price=np.nan;scene_stop=np.nan;scene_block=False;timer_source=-1;timer_reason=0
    for i in range(n):
        t=times[i]
        if not np.isfinite(first_price) and start<=t<=end and np.isfinite(prices[i]) and prices[i]>0:
            first_price=prices[i];scene_stop=first_price*cap*multiplier*session_stop_fraction
        scheduled=bool(quiet[i] or quiet_force[i] or t>=end)
        if scheduled:
            if timer_source<0:timer_source=max(0,i-1)
            timer_reason=93 if t>=end else 92
        blocked_row=scheduled or timer_source>=0 or scene_block
        row_timer_reason=timer_reason
        if pending and (scheduled or timer_source>=0 or scene_block):
            events[ec]=np.array([i,3.,pendingcid,pubrow,pending_side,pendingqty,pendingcap,pending_allowance,
                -1.,0.,0.,timer_reason if not scene_block else 143.,-1.,pendingatr,np.nan,np.nan]);ec+=1
            pending=False
        good=bool(qok[i] and np.isfinite(bid[i]) and np.isfinite(ask[i]) and 0<bid[i]<ask[i])
        if good:
            markbid=bid[i];markask=ask[i]
            # ----------------------------------------
            # 既知timerを優先し、その後に前行までの通常返済予約を注文毎に処理する。
            if remaining>0 and timer_source>=0:
                assert timer_source<i
                qty=remaining;price=ask[i] if side<0 else bid[i]
                execute(orders,trades,uids,slots,inventory,counters,bookparents,i,timer_source,realcid,-side,qty,price,0,-1,timer_reason)
                paid+=fee(qty,numerator,denominator);remaining=0;queued=0;full_pending=False
                events[ec]=np.array([i,2.,realcid,timer_source,-side,qty,price,-1.,-1.,1.,0.,timer_reason,-1.,notional,np.nan,np.nan]);ec+=1
            elif queued>0:
                for k in range(queued):
                    qty=int(queue_quantity[k]);source=int(queue_source[k]);reason=int(queue_reason[k])
                    assert source<i and 0<qty<=remaining
                    price=ask[i] if side<0 else bid[i]
                    execute(orders,trades,uids,slots,inventory,counters,bookparents,i,source,realcid,-side,qty,price,0,-1,reason)
                    paid+=fee(qty,numerator,denominator);remaining-=qty
                    events[ec]=np.array([i,2.,realcid,source,-side,qty,price,-1.,-1.,1.,remaining,reason,-1.,notional,np.nan,np.nan]);ec+=1
                queued=0
                if remaining==0:full_pending=False
            if timer_source>=0:timer_source=-1;timer_reason=0
            if pending and not blocked_row:
                price=ask[i] if pending_side>0 else bid[i]
                reached=price<=pendingcap if pending_side>0 else price>=pendingcap
                assert pubrow<i and remaining==0 and queued==0
                events[ec]=np.array([i,1.,pendingcid,pubrow,pending_side,pendingqty,pendingcap,pending_allowance,
                    1. if reached else 0.,1.,0.,0. if reached else 98.,counters[2] if reached else -1.,pendingatr,bid[i],ask[i]]);ec+=1
                if reached:
                    parent_base=counters[3]*multiplier-paid
                    realcid=pendingcid;side=pending_side;initialqty=pendingqty;remaining=pendingqty
                    actualentry=price;entryrow=i;notional=price*initialqty*multiplier
                    parent_peak=-np.inf;armed=False;partial_done=False;full_pending=False;gu_reserved=0
                    execute(orders,trades,uids,slots,inventory,counters,bookparents,i,pubrow,realcid,side,initialqty,price,1,0,90)
                    paid+=fee(initialqty,numerator,denominator)
                    origins[origin_count]=np.array([realcid,i,pubrow,side,initialqty,price,notional,parent_base,
                        pendingatr,pendingcap,pending_allowance,counters[2]-1]);origin_count+=1
                pending=False
        # ----------------------------------------
        # 紙上親は実保有とは別に進める。busy候補で実親の数量や名目額を上書きしない。
        while pointer<len(feed) and int(feed[pointer,0])==i:
            order=feed[pointer];pointer+=1;cid=int(order[2]);paper_side=int(order[3]);paper_qty=int(order[4]);new=int(order[7])
            assert paper_side in (-1,1) and paper_qty>0 and int(order[8])==0
            if new:
                assert vcore==0
                virtual_cid=cid;virtual_initial=paper_qty;vcore=paper_side*paper_qty
                reserve=fee(remaining,numerator,denominator) if remaining>0 else 0
                global_liquid=(counters[3]+inventory[:,0].sum()*markbid-inventory[:,1].sum()*markask)*multiplier-paid-reserve
                atr=order[9];paperprice=order[5];spread=ask[i]-bid[i] if good else np.nan
                budget=paperprice*cap*multiplier*choice_fraction if np.isfinite(paperprice) and paperprice>0 else np.nan
                available=max(0.,budget+min(0.,global_liquid)) if np.isfinite(budget) else np.nan
                chosen=0;reason=0
                if not good or not np.isfinite(atr) or atr<=0 or not np.isfinite(budget):reason=96
                elif quantity_mode==0:chosen=requested
                else:
                    per_unit=(atr+spread)*multiplier
                    for q in range(1,requested+1):
                        if q*per_unit+2*fee(q,numerator,denominator)<=available:chosen=q
                    if chosen==0:reason=97
                busy=remaining>0 or queued>0 or pending
                if blocked_row:reason=143 if scene_block else row_timer_reason
                elif busy:reason=94
                elif not accepted[i]:reason=95
                allowed=bool(chosen>0 and reason==0)
                tolerance=int(allowances[i]);pricecap=ask[i]+tolerance*tick if paper_side>0 else bid[i]-tolerance*tick
                publications[pc]=np.array([i,cid,paper_side,paper_qty,requested,chosen,atr,spread,budget,available,
                    global_liquid,int(accepted[i]),tolerance,pricecap,int(allowed),reason,int(busy),int(good),paperprice,int(scene_block)]);pc+=1
                if allowed:
                    pending=True;pubrow=i;pendingcid=cid;pending_side=paper_side;pendingqty=chosen
                    pendingcap=pricecap;pendingatr=atr;pending_allowance=tolerance
            else:
                assert cid==virtual_cid and paper_side*vcore<0 and paper_qty<=abs(vcore)
                vcore+=paper_side*paper_qty
                if pending and pendingcid==cid:
                    events[ec]=np.array([i,3.,cid,pubrow,pending_side,pendingqty,pendingcap,pending_allowance,
                        -1.,0.,0.,int(order[6]),-1.,pendingatr,np.nan,np.nan]);ec+=1;pending=False
                elif exit_mode==0 and remaining>0 and cid==realcid and not full_pending and not scheduled and not scene_block:
                    cumulative=virtual_initial-abs(vcore)
                    target=initialqty if vcore==0 else initialqty*cumulative//virtual_initial
                    amount=target-gu_reserved;assert amount>=0
                    if amount>0:
                        queue_source[queued]=i;queue_quantity[queued]=amount;queue_reason[queued]=91;queued+=1;gu_reserved+=amount
        assert pointer>=len(feed) or int(feed[pointer,0])>i
        longqty=int(inventory[:,0].sum());shortqty=int(inventory[:,1].sum())
        assert 0<=longqty<=cap and 0<=shortqty<=cap and longqty+shortqty==remaining
        reserve=fee(remaining,numerator,denominator) if remaining>0 else 0
        equity=(counters[3]+longqty*markbid-shortqty*markask)*multiplier-paid
        liquidation=equity-reserve;local=liquidation-parent_base if realcid>=0 else 0.
        if good and remaining>0:parent_peak=max(parent_peak,local)
        # ----------------------------------------
        # 現在までの清算だけで初先着を判定し、同じ行で返済を約定させない。
        scene_hit=bool(good and np.isfinite(scene_stop) and liquidation<=-scene_stop)
        if scene_hit and not scene_block:
            scene_block=True
            judgments[jc]=np.array([i,realcid,4.,143.,local,liquidation,parent_peak,scene_stop,remaining,notional,0.,0.]);jc+=1
            if pending:
                events[ec]=np.array([i,3.,pendingcid,pubrow,pending_side,pendingqty,pendingcap,pending_allowance,
                    -1.,0.,0.,143.,-1.,pendingatr,np.nan,np.nan]);ec+=1;pending=False
        reason=0
        if good and remaining>0 and not scheduled and timer_source<0 and not full_pending:
            if scene_block:reason=143
            elif local<=-notional*parent_stop_fraction:reason=141
            elif exit_mode==1 and local>=notional*target_fraction:reason=140
            elif exit_mode in (2,3):
                if parent_peak>=notional*arm_fraction:armed=True
                protective=max(notional*floor_fraction,parent_peak-notional*draw_fraction)
                if armed and local<=protective:reason=142
            if reason:
                outstanding=0
                for k in range(queued):outstanding+=int(queue_quantity[k])
                amount=remaining-outstanding;assert amount>=0
                if amount>0:
                    queue_source[queued]=i;queue_quantity[queued]=amount;queue_reason[queued]=reason;queued+=1
                full_pending=True
                judgments[jc]=np.array([i,realcid,1.,reason,local,liquidation,parent_peak,
                    notional*parent_stop_fraction,remaining,notional,int(armed),int(partial_done)]);jc+=1
            elif exit_mode==3 and not partial_done and local>=notional*partial_arm_fraction:
                amount=int(np.floor(initialqty*partial_fraction));partial_done=True
                if amount>0:
                    assert amount<remaining and queued==0
                    queue_source[queued]=i;queue_quantity[queued]=amount;queue_reason[queued]=144;queued+=1
                judgments[jc]=np.array([i,realcid,2.,144.,local,liquidation,parent_peak,
                    notional*partial_arm_fraction,amount,notional,int(armed),1.]);jc+=1
        curve[i]=np.array([equity,liquidation,local,parent_peak if np.isfinite(parent_peak) else np.nan,
            longqty,shortqty,paid,reserve,realcid,scene_stop])
        assert ec<len(events)-8 and jc<len(judgments)-8 and pc<len(publications)-2
    assert pointer==len(feed)
    return orders[:int(counters[0])],uids[:int(counters[0])],curve,publications[:pc],judgments[:jc],events[:ec],origins[:origin_count]
