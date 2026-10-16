"""秒単位の板信号を、到達待ち・指値取消待ち・返済待ちを省略せず再生する。"""

import math
import numpy as np
from numba import njit

REASONS={1:'固定損切り',2:'小幅利確',3:'保有期限',4:'場内撤収',5:'利益追跡',6:'反対信号',10:'新規'}
EVENTS={20:'新規送信判断',21:'上限価格不適合で不成立',22:'指値取消判断',23:'指値取消成立',24:'返済送信判断',28:'新規約定',29:'返済約定',30:'連敗休止'}


@njit(cache=True,nogil=True)
def simulate(times,bid,ask,quality,reset,mapped,grid,states,source_own,source_peer,reference_bid,reference_ask,
             tick,start,limit,quantity,value,fee_unit,latency,entry_mode,target_ticks,stop_ticks,hold_seconds,
             trail_mode,cooldown,repair_mode):
    """機能: 新規と返済の両方を判断から指定秒待ち、原本順に売買する。

    引数: 価格・時計・入口配列(ndarray)、価格単位・セッション・料金(float)、
        entry_mode(int:0成行/1不利1呼値上限の即時判定指値/2最良自己側の待機指値)、
        target_ticks/stop_ticks/hold_seconds/cooldown(float)、trail_mode/repair_mode(int)。
    返り値: 注文18列、決済12列、全行清算時価、残状態統計9列、イベント9列(tuple)。
    指値待機は到達後に反対気配が指値を1呼値通過した時だけ指値価格で全量約定する仮定。
    15秒期限で取消を判断し、その到達まで約定可能。取消到達同時計は取消を優先。
    取消・保有期限タイマーは観測がなくても予定時計に発火。小型商品の真の約定順位は再現しない。
    """
    n=len(times);capacity=max(128,len(grid)//2+256)
    orders=np.zeros((capacity,18));trades=np.zeros((capacity//2+64,12));curve=np.zeros(n);events=np.zeros((max(512,len(grid)*2+256),9))
    oi=ti=ei=0;side=0;pending_entry=False;pending_exit=False;rest=False;cancel=False
    pending_side=0;decision_i=exit_decision_i=entry_i=-1;cid=-1;decision_time=arrival=expiry=cancel_at=0.
    exit_decision_time=exit_arrival=0.;price_limit=entry=peak=stop=0.;entry_grid=exit_grid=-1
    fee=math.floor(quantity*fee_unit+1e-8);cash=last_bid=last_ask=0.;last_exit=-1e30;pause_until=-1e30
    consecutive=0;maxlong=maxshort=cancelled=gapfills=0;exit_reason=0
    for i in range(n):
        assert oi+3<len(orders) and ti+2<len(trades) and ei+8<len(events),'注文又はイベント容量超過'
        stamp=times[i];qok=np.isfinite(bid[i]) and np.isfinite(ask[i]) and bid[i]>0. and ask[i]>=bid[i]
        # ----------------------------------------
        # 時計で決まる取消と返済は、次の価格観測を待たずに発注したものとして待機させる。
        if pending_entry and entry_mode==2 and not cancel:
            due=min(expiry,limit-90.)
            if stamp>=due:
                cancel=True;cancel_at=due+latency
                events[ei]=np.array([max(0,i-1),cid,22.,due,pending_side,price_limit,cancel_at,expiry,grid[entry_grid]]);ei+=1
        if side and not pending_exit and i>entry_i:
            due=max(times[entry_i],min(times[entry_i]+hold_seconds,limit-60.))
            if stamp>=due:
                pending_exit=True;exit_decision_i=i-1;exit_decision_time=due;exit_arrival=due+latency
                exit_reason=4 if limit-60.<=times[entry_i]+hold_seconds else 3;exit_grid=-1
                quote=last_bid if side==1 else last_ask
                events[ei]=np.array([i-1,cid,24.,due,side,quote,exit_arrival,exit_reason,-1.]);ei+=1
        if qok:last_bid,last_ask=bid[i],ask[i]
        g=int(mapped[i]);fresh=g>=0 and stamp-grid[g]<=2.+1e-8
        # ----------------------------------------
        # 到達した注文を先に処理する。待っている間に方向が変わっても成行注文は消えない。
        if pending_exit and i>exit_decision_i and stamp>=exit_arrival and qok:
            price=bid[i] if side==1 else ask[i];gross=side*(price-entry)*quantity*value;net=gross-2*fee
            sg=grid[exit_grid] if exit_grid>=0 else -1.;sa=source_own[exit_grid] if exit_grid>=0 else -1;sb=source_peer[exit_grid] if exit_grid>=0 else -1
            orders[oi]=np.array([i,exit_decision_i,cid,-side,quantity,price,exit_reason,0.,fee,-1.,exit_decision_time,exit_arrival,stamp,i,0.,sg,sa,sb]);oi+=1
            trades[ti]=np.array([cid,entry_i,i,side,quantity,entry,price,fee,fee,gross,net,0.]);ti+=1
            cash+=side*quantity*price*value-fee;last_exit=stamp
            if stamp-exit_arrival>5.:gapfills+=1
            events[ei]=np.array([i,cid,29.,stamp,side,price,exit_arrival,net,sg]);ei+=1
            consecutive=consecutive+1 if net<0 else 0
            if repair_mode==3 and consecutive>=2:
                pause_until=stamp+120.;consecutive=0
                events[ei]=np.array([i,cid,30.,stamp,side,price,pause_until,net,sg]);ei+=1
            side=0;pending_exit=False
        if pending_entry and i>decision_i and stamp>=arrival:
            if entry_mode==2:rest=True
            fill=False;reject=False;price=0.
            if qok:
                price=ask[i] if pending_side==1 else bid[i]
                if entry_mode==0:fill=True
                elif entry_mode==1:
                    fill=pending_side*(price-price_limit)<=1e-8
                    reject=not fill
                elif (not cancel or stamp<cancel_at) and pending_side*(price-price_limit)<=-tick+1e-8:
                    fill=True;price=price_limit
            if fill:
                side=pending_side;entry_i=i;cid+=1;entry=price;peak=entry;stop=entry-side*stop_ticks*tick
                cash-=side*quantity*entry*value+fee
                sg=grid[entry_grid];sa=source_own[entry_grid];sb=source_peer[entry_grid]
                orders[oi]=np.array([i,decision_i,cid,side,quantity,price,10.,1.,fee,0.,decision_time,arrival,stamp,i,entry_mode,sg,sa,sb]);oi+=1
                maxlong=max(maxlong,quantity if side==1 else 0);maxshort=max(maxshort,quantity if side==-1 else 0)
                if stamp-arrival>5. and entry_mode!=2:gapfills+=1
                events[ei]=np.array([i,cid,28.,stamp,side,price,arrival,expiry,sg]);ei+=1
                pending_entry=rest=cancel=False
            elif reject:
                events[ei]=np.array([i,cid,21.,stamp,pending_side,price_limit,arrival,expiry,grid[entry_grid]]);ei+=1
                pending_entry=False;last_exit=stamp;cancelled+=1
            elif entry_mode==2:
                if cancel and stamp>=cancel_at:
                    pending_entry=rest=cancel=False;last_exit=stamp;cancelled+=1
                    events[ei]=np.array([i,cid,23.,stamp,pending_side,price_limit,cancel_at,expiry,grid[entry_grid]]);ei+=1
        # ----------------------------------------
        # 利確・損切りは返済側気配で判断し、その後も返済到達まで建玉を時価評価する。
        if side and not pending_exit and i>entry_i:
            reason=0;quote=bid[i] if side==1 else ask[i]
            if reason==0 and qok:
                if side*(quote-stop)<=1e-8:reason=1 if side*(peak-entry)<target_ticks*tick else 5
                elif not trail_mode and side*(quote-entry)>=target_ticks*tick-1e-8:reason=2
                else:
                    if side*(quote-peak)>0:peak=quote
                    if trail_mode and side*(peak-entry)>=target_ticks*tick:
                        newstop=peak-side*tick
                        if side*(newstop-stop)>0:stop=newstop
            if reason==0 and repair_mode==2 and fresh and states[g]==-side:reason=6
            if reason:
                pending_exit=True;exit_decision_i=i;exit_decision_time=stamp;exit_arrival=stamp+latency;exit_reason=reason;exit_grid=g if fresh else -1
                events[ei]=np.array([i,cid,24.,stamp,side,quote,exit_arrival,reason,grid[g] if fresh else -1.]);ei+=1
        # ----------------------------------------
        # 入口は既知信号だけ。修正1は直前根拠からの追いかけを拒否し、修正3は確定連敗後だけ休止。
        if side==0 and not pending_entry and not pending_exit and fresh and states[g]!=0 and quality[i] and not reset[i] and qok and stamp>=start+60. and stamp<limit-120. and stamp-last_exit>=cooldown and stamp>=pause_until:
            d=int(states[g]);allowed=True
            if repair_mode==1:
                ref=reference_ask[g] if d==1 else reference_bid[g];quote=ask[i] if d==1 else bid[i]
                allowed=np.isfinite(ref) and d*(quote-ref)<=tick+1e-8
            if allowed:
                pending_entry=True;pending_side=d;decision_i=i;decision_time=stamp;arrival=stamp+latency;expiry=arrival+15.;entry_grid=g
                price_limit=(ask[i]+tick if d==1 else bid[i]-tick) if entry_mode==1 else (bid[i] if d==1 else ask[i])
                events[ei]=np.array([i,cid,20.,stamp,d,price_limit,arrival,expiry,grid[g]]);ei+=1
        curve[i]=cash
        if side:curve[i]+=side*quantity*(last_bid if side==1 else last_ask)*value-fee
    return orders[:oi],trades[:ti],curve,np.array([side,int(pending_entry),int(pending_exit),int(rest),maxlong,maxshort,cancelled,ti,gapfills]),events[:ei]
