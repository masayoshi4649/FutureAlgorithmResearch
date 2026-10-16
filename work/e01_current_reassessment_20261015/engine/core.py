"""構造eventの全量FAKとNative実親を逐次運転し、保有後の新反応だけで支持線を上げる。"""

import numpy as np
from numba import njit
from order_kernel import execute


@njit(cache=True)
def doubled(value):
    """
    機能: 二次元の実注文/診断bufferを倍へ伸ばす。
    引数: value(ndarray[float,二次元]) は私有buffer。
    返り値: ndarray は旧内容を保持した倍長buffer。
    """
    out=np.zeros((len(value)*2,value.shape[1]));out[:len(value)]=value
    return out


@njit(cache=True)
def fee(q,num,den):
    """
    機能: 各実注文料を整数分数で切り捨てる。
    引数: q/num/den(int) は実枚数と片道料金。
    返り値: int は円料。
    """
    return q*num//den


@njit(cache=True)
def simulate(times,prices,bid,ask,qok,quiet,quiet_force,normal,volume_known,price_known,
             volume_gate,price_gate,interval_known,new_up,new_down,strong,candidates,
             start,end,cap,tick,mult,num,den,exit_mode,parent_stop,target,arm,draw,floor,
             scene_stop_fraction,scene_profit_fraction,cost_ratio,initial_capacity=32):
    """
    機能: 当時候補を一回消費し、次normal全量FAK/全量Native返済と支持更新を会計する。
    引数: 時計/価格/BBO/資格/現在票/候補(ndarray)、期間/幅/倍率/率(float)、容量/料/mode(int)。
    返り値: tuple はorders/uids/十四列curve/PUB/判断/執行/十六列origin/支持更新/最大buffer。
    """
    n=len(times);assert n>0 and 0<=exit_mode<=2
    capacity=max(4,initial_capacity);orders=np.zeros((capacity,8));trades=np.zeros((capacity,11));uids=np.full(capacity,-1,np.int64)
    slots=np.zeros((capacity,7));inventory=np.zeros((3,2),np.int64);counters=np.zeros(9);book=np.zeros((capacity,11));book[:,:3]=-1
    pubs=np.zeros((capacity,24));pc=0;judges=np.zeros((capacity,13));jc=0;events=np.zeros((capacity,14));ec=0
    origins=np.zeros((capacity,16));nc=0;updates=np.zeros((capacity,10));uc=0;curve=np.zeros((n,14))
    pointer=0;next_cid=0;pending=False;pending_row=-1;pending_cid=-1;pending_side=0;pending_cap=0.;pending_l=0.;pending_event=-1
    pending_width=0.;pending_allow=0;pending_proof=-1
    actual_cid=-1;side=0;held=0;notional=0.;parent_base=0.;peak=-np.inf;armed=False;support_line=np.nan;entry_row=-1
    exit_pending=False;exit_source=-1;exit_reason=0;paid=0;markbid=0.;markask=0.
    scene_stop=np.nan;scene_goal=np.nan;scene_block=False;scene_reason=0;timer_source=-1;timer_reason=0
    holding_proof=-1;holding_b0=np.nan;holding_a0=np.nan;holding_bp=np.nan;holding_ap=np.nan;holding_lower=0
    previous_good_row=-1;previous_bid=np.nan;previous_ask=np.nan;previous_required=False
    for row in range(n):
        if max(int(counters[0]),int(counters[1]),int(counters[2]),next_cid,pc,jc,ec,nc,uc)>=capacity-3:
            previous=capacity;capacity*=2
            orders=doubled(orders);trades=doubled(trades);slots=doubled(slots);book=doubled(book);book[previous:,:3]=-1
            uu=np.full(capacity,-1,np.int64);uu[:len(uids)]=uids;uids=uu
            pubs=doubled(pubs);judges=doubled(judges);events=doubled(events);origins=doubled(origins);updates=doubled(updates)
        t=times[row];good=bool(qok[row] and np.isfinite(t) and np.isfinite(bid[row]) and np.isfinite(ask[row]) and 0<bid[row]<ask[row])
        usable=bool(good and normal[row] and np.isfinite(prices[row]) and prices[row]>0)
        if not np.isfinite(scene_stop) and start<=t<=end and np.isfinite(prices[row]) and prices[row]>0:
            nominal=prices[row]*cap*mult;scene_stop=nominal*scene_stop_fraction;scene_goal=nominal*scene_profit_fraction
        scheduled=bool(quiet[row] or quiet_force[row] or t>=end)
        if scheduled:
            if timer_source<0:timer_source=max(0,row-1)
            timer_reason=93 if t>=end else 92
        blocked=scheduled or timer_source>=0 or scene_block
        if pending and blocked:
            events[ec]=np.array([row,3.,pending_cid,pending_row,pending_side,cap,pending_cap,timer_reason if not scene_block else scene_reason,0.,pending_allow,pending_l,pending_event,pending_proof,0.]);ec+=1
            pending=False
        if good:
            markbid=bid[row];markask=ask[row]
            # ----------------------------------------
            # 既知timer→既返済予約→既受理FAK。後の情報未知で先の約定を遡及取消しない。
            if held>0 and (timer_source>=0 or exit_pending):
                source=timer_source if timer_source>=0 else exit_source;reason=timer_reason if timer_source>=0 else exit_reason
                assert source<row;price=bid[row] if side>0 else ask[row]
                execute(orders,trades,uids,slots,inventory,counters,book,row,source,actual_cid,-side,held,price,0,-1,reason)
                paid+=fee(held,num,den);events[ec]=np.array([row,2.,actual_cid,source,-side,held,price,reason,1.,0.,support_line,notional,exit_source,exit_reason]);ec+=1
                held=0;exit_pending=False;holding_proof=-1;previous_required=False
            if timer_source>=0:timer_source=-1;timer_reason=0
            if pending and not blocked:
                price=ask[row] if pending_side>0 else bid[row];reached=price<=pending_cap if pending_side>0 else price>=pending_cap
                assert pending_row<row and held==0
                events[ec]=np.array([row,1.,pending_cid,pending_row,pending_side,cap,price,90. if reached else 98.,int(reached),pending_allow,pending_l,pending_event,pending_proof,0.]);ec+=1
                if reached:
                    parent_base=counters[3]*mult-paid;actual_cid=pending_cid;side=pending_side;held=cap;entry_row=row
                    notional=price*cap*mult;peak=-np.inf;armed=False;support_line=pending_l-side*tick
                    execute(orders,trades,uids,slots,inventory,counters,book,row,pending_row,actual_cid,side,cap,price,1,0,90)
                    paid+=fee(cap,num,den);holding_proof=-1;previous_required=False
                    origins[nc]=np.array([actual_cid,pending_event,row,pending_row,side,cap,price,notional,parent_base,
                        pending_l,support_line,pending_width,pending_cap,pending_allow,counters[2]-1,pending_proof]);nc+=1
                pending=False
        longq=int(inventory[:,0].sum());shortq=int(inventory[:,1].sum());assert longq+shortq==held and max(longq,shortq)<=cap
        reserve=fee(held,num,den) if held else 0
        equity=(counters[3]+longq*markbid-shortq*markask)*mult-paid;liquid=equity-reserve;local=liquid-parent_base if actual_cid>=0 else 0.
        if good and held>0:peak=max(peak,local)
        # ----------------------------------------
        # 実約定より後の新反対差分だけを用い、最新一probeで支持線を有利方向に更新する。
        required=usable and volume_known[row] and price_known[row]
        if held>0:
            if not required:holding_proof=-1
            else:
                fresh=int(new_down[row] if side>0 else new_up[row])
                if row>entry_row and interval_known[row] and fresh>=1 and previous_required and previous_good_row==row-1:
                    holding_proof=row;holding_b0=previous_bid;holding_a0=previous_ask;holding_bp=bid[row];holding_ap=ask[row];holding_lower=fresh
                if holding_proof>=0:
                    adverse=side*(bid[row]-holding_b0)<-tick or side*(ask[row]-holding_a0)<-tick
                    if adverse:holding_proof=-1
                    elif row>holding_proof and side*(bid[row]-holding_bp)>=2*tick and side*(ask[row]-holding_ap)>=2*tick:
                        direction=0 if side>0 else 1
                        if volume_gate[row,direction] and price_gate[row,direction]:
                            old_line=support_line;candidate_line=holding_bp-tick if side>0 else holding_ap+tick
                            support_line=max(old_line,candidate_line) if side>0 else min(old_line,candidate_line)
                            assert side*(support_line-old_line)>=0 and holding_proof>entry_row
                            updates[uc]=np.array([row,actual_cid,side,old_line,support_line,holding_proof,holding_bp,holding_ap,holding_lower,holding_proof-1]);uc+=1
                            holding_proof=-1
        else:holding_proof=-1
        previous_required=bool(required and held>0);previous_good_row=row;previous_bid=bid[row];previous_ask=ask[row]
        reason=0;line=0.
        if good and np.isfinite(scene_stop) and not scene_block:
            if liquid<=-scene_stop:scene_block=True;scene_reason=161
            elif liquid>=scene_goal:scene_block=True;scene_reason=162
            if scene_block:
                blocked=True;line=scene_stop if scene_reason==161 else scene_goal
                judges[jc]=np.array([row,actual_cid,-1.,scene_reason,local,liquid,peak,line,held,notional,int(armed),support_line,1.]);jc+=1
                if pending:
                    events[ec]=np.array([row,3.,pending_cid,pending_row,pending_side,cap,pending_cap,scene_reason,0.,pending_allow,pending_l,pending_event,pending_proof,0.]);ec+=1;pending=False
        if held>0 and not exit_pending and not scheduled and timer_source<0:
            if scene_block:reason=scene_reason;line=scene_stop if reason==161 else scene_goal
            elif good and local<=-notional*parent_stop:reason=141;line=notional*parent_stop
            elif good and ((side>0 and bid[row]<=support_line and ask[row]<=support_line) or (side<0 and bid[row]>=support_line and ask[row]>=support_line)):
                reason=143;line=support_line
            elif good and exit_mode==0 and local>=notional*target:reason=140;line=notional*target
            elif good and exit_mode>0:
                if peak>=notional*arm:armed=True
                protective=max(notional*floor,peak-notional*draw)
                if armed and local<=protective:reason=142;line=protective
            if reason:
                exit_pending=True;exit_source=row;exit_reason=reason
                judges[jc]=np.array([row,actual_cid,-1.,reason,local,liquid,peak,line,held,notional,int(armed),support_line,int(scene_block)]);jc+=1
        # ----------------------------------------
        # 共通構造eventは入力段階で各種類一回消費。busy/費用等の拒否を後で復活しない。
        while pointer<len(candidates) and int(candidates[pointer,0])==row:
            event=candidates[pointer];pointer+=1;candidate_side=int(event[2]);direction=0 if candidate_side>0 else 1
            level=event[5];quote=ask[row] if candidate_side>0 else bid[row];spread=ask[row]-bid[row] if good else np.nan
            public_n=quote*cap*mult if good else np.nan;cost=spread*cap*mult+2*fee(cap,num,den) if good else np.nan
            allowance=1 if strong[row,direction] else 0;pricecap=quote+candidate_side*allowance*tick if good else np.nan
            reason=0
            if blocked or scene_block:reason=scene_reason if scene_block else 93 if t>=end else 92
            elif held>0 or pending or exit_pending:reason=94
            elif not(start+300.<=t<end-300.):reason=153
            elif not usable or not np.isfinite(level) or level<=0:reason=96
            elif cost>cost_ratio*public_n*parent_stop:reason=154
            accepted=reason==0;cid=next_cid if accepted else -1
            support_width=candidate_side*(quote-(level-candidate_side*tick)) if good else np.nan
            pubs[pc]=np.array([row,cid,candidate_side,event[3],event[4],level,support_width,cap,spread,public_n,pricecap,allowance,
                int(accepted),reason,event[6],event[9],event[10],event[11],event[12],event[13],cost,cost_ratio*public_n*parent_stop,event[1],event[15]]);pc+=1
            if accepted:
                pending=True;pending_row=row;pending_cid=cid;pending_side=candidate_side;pending_cap=pricecap;pending_l=level
                pending_event=int(event[3]);pending_width=support_width;pending_allow=allowance;pending_proof=int(event[9]);next_cid+=1
        assert pointer>=len(candidates) or int(candidates[pointer,0])>row
        curve[row]=np.array([equity,liquid,local,peak if np.isfinite(peak) else np.nan,longq,shortq,paid,reserve,
            actual_cid,scene_stop,scene_goal,support_line,int(armed),holding_proof])
    assert pointer==len(candidates)
    return orders[:int(counters[0])],uids[:int(counters[0])],curve,pubs[:pc],judges[:jc],events[:ec],origins[:nc],updates[:uc],capacity
