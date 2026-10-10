"""共通方向の入口と、独立した反対確認・建値保護・保有延長・再準備を統合する。"""

import math
import numpy as np
from numba import njit

REASONS={1:'初期損切り',2:'追跡線又は建値保護',3:'保有期限',4:'場内返済',6:'二市場の反対確認',10:'共通方向の新規'}
EVENTS={20:'条件付き15分延長',21:'費用込み建値保護',22:'2連敗休止',23:'共同方向を再準備',24:'休止による新規見送り'}


@njit(cache=True,nogil=True)
def simulate(times,bid,ask,quality,reset,event,mapped,grid,valid,common,fd_long,fd_short,fp_long,fp_short,
             tick,start,limit,quantity,value,fee_unit,width,valid300,trend300,source_top,source_nk,
             flow_mode,protect_fraction,hold_mode,rest_mode):
    """機能: 同じ価格幅と数量のまま管理の四部品を独立に切り替える。

    引数: 原本と共同情報(ndarray)、価格/時刻/料金(float)、数量・管理方式(int)。
    flow_mode=0無/1板反対/2板と価格反対、protect_fraction=0無/.25/.5順行で建値保護。
    hold_mode=0固定30分/1条件付き15分延長最大90分/2固定90分、rest_mode=0無/1連敗後再準備。
    返り値: 注文10列、決済12列、全行清算時価、統計7列、管理イベント6列(tuple)。
    返済線の更新後、その線による返済判断は次の原本行から。確定連敗後30分経過以後に再準備を計測する。
    """
    n=len(times);capacity=max(128,len(grid)*8+64)
    orders=np.zeros((capacity,10));trades=np.zeros((capacity,12));curve=np.zeros(n);events=np.zeros((capacity,6))
    oi=ti=ei=0;side=pending=pending_side=0;decision=reason=-1;entry_i=cid=-1
    entry=peak=stop=0.;cash=last_bid=last_ask=0.;last_exit=-1e30;last_peak=-1e30;deadline=0.
    fee=math.floor(quantity*fee_unit+1e-8);protected=False;maxlong=maxshort=0;latest=-1
    losses=0;blocked=False;blocked_side=0;pause_until=0.;rearm=-1.;prior_grid=-1e30;rearm_a=rearm_b=-1
    for i in range(n):
        stamp=times[i];qok=np.isfinite(bid[i]) and np.isfinite(ask[i]) and bid[i]>0 and ask[i]>=bid[i]
        if qok:last_bid,last_ask=bid[i],ask[i]
        # ----------------------------------------
        # 実約定は常に発注判断より後の有効原本行。約定済みの損益だけで連敗を数える。
        if pending and i>decision and qok:
            if pending==1:
                if stamp<limit-300.:
                    side=pending_side;entry_i=i;cid+=1;entry=ask[i] if side==1 else bid[i]
                    peak=entry;stop=entry-side*width;protected=False;last_peak=stamp
                    deadline=stamp+(5400. if hold_mode==2 else 1800.)
                    cash-=side*quantity*entry*value+fee
                    orders[oi]=np.array([i,decision,cid,side,quantity,entry,10.,1.,fee,0.]);oi+=1
                    maxlong=max(maxlong,quantity if side==1 else 0);maxshort=max(maxshort,quantity if side==-1 else 0)
            else:
                price=bid[i] if side==1 else ask[i];gross=side*(price-entry)*quantity*value;net=gross-2*fee
                orders[oi]=np.array([i,decision,cid,-side,quantity,price,reason,0.,fee,-1.]);oi+=1
                trades[ti]=np.array([cid,entry_i,i,side,quantity,entry,price,fee,fee,gross,net,0.]);ti+=1
                cash+=side*quantity*price*value-fee;last_exit=stamp
                losses=losses+1 if net<0 else 0
                if rest_mode and losses>=2:
                    blocked=True;blocked_side=side;pause_until=stamp+1800.;rearm=-1.;prior_grid=-1e30
                    events[ei]=np.array([i,cid,22.,pause_until,losses,side]);ei+=1
                side=0
            pending=0
        g=int(mapped[i])
        if g>=0:latest=g
        usable=g>=0 and valid[g] and quality[i] and not reset[i]
        # ----------------------------------------
        # 休止30分の後、共通方向が最後の負け方向以外へ変化した有効60秒を待つ。
        if rest_mode and blocked and g>=0 and stamp>=pause_until:
            ok=usable and valid300[g] and trend300[g]!=blocked_side
            gap=grid[g]-prior_grid>5.+1e-8;prior_grid=grid[g]
            if not ok:rearm=-1.
            else:
                if rearm<0 or gap:rearm=grid[g];rearm_a=source_top[g];rearm_b=source_nk[g]
                if grid[g]-rearm>=60. and source_top[g]>rearm_a and source_nk[g]>rearm_b:
                    blocked=False;losses=0;events[ei]=np.array([i,cid,23.,rearm,grid[g],blocked_side]);ei+=1
        # ----------------------------------------
        # 終了、保有期限、既設の保護線、反対確認の順で全返済を判断する。
        if side and pending==0 and i>entry_i:
            reason=0;quote=bid[i] if side==1 else ask[i]
            if stamp>=limit-60.:reason=4
            elif stamp>=deadline:
                fresh=latest>=0 and stamp-grid[latest]<=10.+1e-8 and valid[latest] and quality[i] and not reset[i]
                can_extend=(hold_mode==1 and stamp<deadline+900. and deadline<times[entry_i]+5400.-1e-8 and fresh and common[latest]==side
                    and qok and side*(quote-entry)*quantity*value-2*fee>0 and stamp-last_peak<=300.)
                if can_extend:
                    deadline=min(deadline+900.,times[entry_i]+5400.)
                    events[ei]=np.array([i,cid,20.,deadline,quote,last_peak]);ei+=1
                else:reason=3
            if reason==0 and qok:
                if side*(quote-stop)<=tick*1e-8:reason=1 if abs(peak-entry)<tick*1e-8 and not protected else 2
                else:
                    if side*(quote-peak)>0:peak=quote;last_peak=stamp
                    candidate=peak-side*width
                    if side*(candidate-stop)>0:stop=candidate
                    if protect_fraction>0 and not protected and side*(peak-entry)>=protect_fraction*width:
                        floor_price=entry+side*2*fee/(quantity*value)
                        floor_price=(math.ceil(floor_price/tick-1e-8) if side==1 else math.floor(floor_price/tick+1e-8))*tick
                        if side*(floor_price-stop)>0:stop=floor_price
                        protected=True;events[ei]=np.array([i,cid,21.,stop,peak,side]);ei+=1
            if reason==0 and flow_mode and usable:
                opposed=(fd_long[g] if side==1 else fd_short[g]) if flow_mode==1 else (fp_long[g] if side==1 else fp_short[g])
                if opposed:reason=6
            if reason:pending=2;decision=i
        # ----------------------------------------
        # 元の入口イベントを変えず、休止だけが成立候補を見送る。返済後30秒待つ。
        if side==0 and pending==0 and event[i]!=0 and quality[i] and not reset[i] and qok and stamp>=start+300. and stamp<limit-300. and stamp-last_exit>=30.:
            if blocked:
                events[ei]=np.array([i,cid,24.,event[i],pause_until,blocked_side]);ei+=1
            else:pending=1;pending_side=int(event[i]);decision=i
        curve[i]=cash
        if side:curve[i]+=side*quantity*(last_bid if side==1 else last_ask)*value-fee
    return orders[:oi],trades[:ti],curve,np.array([side,pending,quantity if side else 0,maxlong,maxshort,0,0]),events[:ei]
