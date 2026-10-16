"""新価格票と新しいgeometryから再参加し、影撤回と純益保護を次正常へ予約する。"""

import numpy as np
from numba import njit
from order_kernel import execute


@njit(cache=True)
def doubled(value):
    """
    機能: 診断/注文の二次元bufferを倍へ増やし、旧内容を保つ。
    引数: value(ndarray[float,二次元]) は所有buffer。
    返り値: ndarray は倍長のbuffer。実親数をpaper親数へ制限しない。
    """
    out=np.zeros((len(value)*2,value.shape[1]));out[:len(value)]=value
    return out


@njit(cache=True)
def fee(q,num,den):
    """
    機能: 各実注文の料金を整数分数から円で切り捨てる。
    引数: q/num/den(int) は実枚数と片道料。
    返り値: int は実注文料金。
    """
    return q*num//den


@njit(cache=True)
def simulate(times,prices,bid,ask,qok,feed,quiet,quiet_force,own_normal,own_known,own_count,own_balance,
             peer_known,peer_count,peer_balance,start,end,cap,tick,mult,num,den,reentry_mode,exit_mode,
             parent_stop_fraction,target_fraction,arm_fraction,draw_fraction,floor_fraction,
             scene_stop_fraction,scene_profit_fraction,pull_fraction,recover_fraction,break_fraction,
             initial_capacity=32,enable_opposed_price_exit=True):
    """
    機能: 現在価格票・影方向・実flat後の新支持で、全量FAK/保護/撤回を逐次運転する。
    引数: 時計/価格/BBO/票/影feed/静観(ndarray)、期間/倍率/率(float)、容量/料/mode(int)、enable_opposed_price_exit(bool) は反対価格票単独退出のON/OFF。
    返り値: tuple は注文/UID/十四列清算/公開/判断/執行/実親起点/geometry/最大buffer長。
    """
    n=len(times);assert n>0 and 0<=reentry_mode<=3 and 0<=exit_mode<=2
    capacity=max(initial_capacity,len(feed)*4+16)
    orders=np.zeros((capacity,8));trades=np.zeros((capacity,11));uids=np.full(capacity,-1,np.int64)
    slots=np.zeros((capacity,7));inventory=np.zeros((3,2),np.int64);counters=np.zeros(9)
    book=np.zeros((capacity,11));book[:,:3]=-1
    pubs=np.zeros((capacity,22));pc=0;judges=np.zeros((capacity,13));jc=0
    events=np.zeros((capacity,18));ec=0;origins=np.zeros((capacity,14));nc=0
    curve=np.zeros((n,14));geometry=np.full((n,7),np.nan)
    pointer=0;paper_cid=-1;paper_v=0;paper_price=np.nan;paper_atr=np.nan
    pending=False;pending_row=-1;pending_cid=-1;pending_paper=-1;pending_side=0;pending_cap=0.;pending_allow=0
    pending_price=0.;pending_atr=0.;next_cid=0
    actual_cid=-1;actual_paper=-1;side=0;held=0;notional=0.;parent_base=0.;peak=-np.inf;armed=False
    exit_pending=False;exit_source=-1;exit_reason=0
    paid=0;markbid=0.;markask=0.;scene_stop=np.nan;scene_goal=np.nan;scene_block=False;scene_block_reason=0
    timer_source=-1;timer_reason=0
    anchor_row=-1;anchor=np.nan;extreme=np.nan;trough=np.nan;pull_row=-1;stage=0
    for i in range(n):
        if max(int(counters[0]),int(counters[1]),int(counters[2]),next_cid,pc,jc,ec,nc)>=capacity-12:
            previous=capacity;capacity*=2
            orders=doubled(orders);trades=doubled(trades);slots=doubled(slots);book=doubled(book);book[previous:,:3]=-1
            uu=np.full(capacity,-1,np.int64);uu[:len(uids)]=uids;uids=uu
            pubs=doubled(pubs);judges=doubled(judges);events=doubled(events);origins=doubled(origins)
        t=times[i];good=bool(qok[i] and np.isfinite(t) and np.isfinite(bid[i]) and np.isfinite(ask[i]) and 0<bid[i]<ask[i])
        usable=bool(good and own_normal[i] and np.isfinite(prices[i]) and prices[i]>0)
        if not np.isfinite(scene_stop) and start<=t<=end and np.isfinite(prices[i]) and prices[i]>0:
            nominal=prices[i]*cap*mult;scene_stop=nominal*scene_stop_fraction;scene_goal=nominal*scene_profit_fraction
        scheduled=bool(quiet[i] or quiet_force[i] or t>=end)
        if scheduled:
            if timer_source<0:timer_source=max(0,i-1)
            timer_reason=93 if t>=end else 92
        blocked=scheduled or timer_source>=0 or scene_block
        if pending and blocked:
            events[ec]=np.array([i,3.,pending_cid,pending_row,pending_paper,pending_side,cap,pending_cap,
                timer_reason if not scene_block else scene_block_reason,0.,pending_allow,pending_price,pending_atr,0.,0.,0.,0.,0.]);ec+=1
            pending=False;anchor_row=-1;stage=0
        if good:
            markbid=bid[i];markask=ask[i]
            # ----------------------------------------
            # 既知timer→既返済予約→既pendingFAKの順。約定済みを後の票変化で取消しない。
            if held>0 and (timer_source>=0 or exit_pending):
                source=timer_source if timer_source>=0 else exit_source;reason=timer_reason if timer_source>=0 else exit_reason
                assert source<i
                price=bid[i] if side>0 else ask[i]
                execute(orders,trades,uids,slots,inventory,counters,book,i,source,actual_cid,-side,held,price,0,-1,reason)
                paid+=fee(held,num,den)
                events[ec]=np.array([i,2.,actual_cid,source,actual_paper,-side,held,price,reason,1.,0.,notional,
                    exit_source,exit_reason,0.,0.,0.,0.]);ec+=1
                held=0;exit_pending=False;anchor_row=-1;stage=0
            if timer_source>=0:timer_source=-1;timer_reason=0
            if pending and not blocked:
                price=ask[i] if pending_side>0 else bid[i]
                reached=price<=pending_cap if pending_side>0 else price>=pending_cap
                assert pending_row<i and held==0
                events[ec]=np.array([i,1.,pending_cid,pending_row,pending_paper,pending_side,cap,price,
                    90. if reached else 98.,int(reached),pending_allow,pending_cap,pending_atr,bid[i],ask[i],0.,0.,0.]);ec+=1
                if reached:
                    parent_base=counters[3]*mult-paid
                    actual_cid=pending_cid;actual_paper=pending_paper;side=pending_side;held=cap
                    notional=price*cap*mult;peak=-np.inf;armed=False
                    execute(orders,trades,uids,slots,inventory,counters,book,i,pending_row,actual_cid,side,cap,price,1,0,90)
                    paid+=fee(cap,num,den)
                    origins[nc]=np.array([actual_cid,actual_paper,i,pending_row,side,cap,price,notional,parent_base,
                        pending_price,pending_atr,pending_cap,pending_allow,counters[2]-1]);nc+=1
                pending=False;anchor_row=-1;stage=0
        # ----------------------------------------
        # 影親・方向だけ進め、旧部分EXITを実枚数へ写さない。未約定は部分EXITでも撤回。
        original=False;origin_withdrawn=False
        while pointer<len(feed) and int(feed[pointer,0])==i:
            order=feed[pointer];pointer+=1;cid=int(order[2]);s=int(order[3]);q=int(order[4]);new=int(order[7])
            assert s in (-1,1) and q>0
            if new:
                assert paper_v==0;paper_cid=cid;paper_v=s*q;paper_price=order[5];paper_atr=order[9]
                original=True;origin_withdrawn=False;anchor_row=-1;stage=0
            else:
                assert cid==paper_cid and s*paper_v<0 and q<=abs(paper_v)
                paper_v+=s*q
                if original:origin_withdrawn=True
                if pending and pending_paper==cid:
                    events[ec]=np.array([i,3.,pending_cid,pending_row,pending_paper,pending_side,cap,pending_cap,
                        151.,0.,pending_allow,pending_price,pending_atr,0.,0.,0.,0.,0.]);ec+=1
                    pending=False;anchor_row=-1;stage=0
        assert pointer>=len(feed) or int(feed[pointer,0])>i
        direction=1 if paper_v>0 else -1 if paper_v<0 else 0
        longq=int(inventory[:,0].sum());shortq=int(inventory[:,1].sum());assert longq+shortq==held and max(longq,shortq)<=cap
        reserve=fee(held,num,den) if held else 0
        equity=(counters[3]+longq*markbid-shortq*markask)*mult-paid;liquid=equity-reserve
        local=liquid-parent_base if actual_cid>=0 else 0.
        if good and held>0:peak=max(peak,local)
        scene_reason=0
        if good and np.isfinite(scene_stop) and not scene_block:
            if liquid<=-scene_stop:scene_reason=161
            elif liquid>=scene_goal:scene_reason=162
            if scene_reason:
                scene_block=True;scene_block_reason=scene_reason;blocked=True
                judges[jc]=np.array([i,actual_cid,paper_cid,scene_reason,local,liquid,peak,
                    scene_stop if scene_reason==161 else scene_goal,held,notional,int(armed),direction,1.]);jc+=1
                if pending:
                    events[ec]=np.array([i,3.,pending_cid,pending_row,pending_paper,pending_side,cap,pending_cap,
                        scene_reason,0.,pending_allow,pending_price,pending_atr,0.,0.,0.,0.,0.]);ec+=1;pending=False
        # ----------------------------------------
        # 純清算保護と影撤回は実親ごとに一回予約。未知票だけでは新しい撤回を作らない。
        reason=0;line=0.
        if held>0 and not exit_pending and not scheduled and timer_source<0:
            opposed=own_known[i] and peer_known[i] and own_count[i]>=2 and peer_count[i]>=2 and side*own_balance[i]<=-.25 and side*peer_balance[i]<=-.25
            if scene_block:reason=scene_block_reason;line=scene_stop if reason==161 else scene_goal
            elif good and local<=-notional*parent_stop_fraction:reason=141;line=notional*parent_stop_fraction
            elif direction==0 or direction!=side:reason=151
            elif enable_opposed_price_exit and opposed:reason=152
            elif good and exit_mode==0 and local>=notional*target_fraction:reason=140;line=notional*target_fraction
            elif good and exit_mode>0:
                if peak>=notional*arm_fraction:armed=True
                protective=max(notional*floor_fraction,peak-notional*draw_fraction)
                if armed and local<=protective:reason=142;line=protective
            if reason:
                exit_pending=True;exit_source=i;exit_reason=reason
                judges[jc]=np.array([i,actual_cid,paper_cid,reason,local,liquid,peak,line,held,notional,int(armed),direction,int(scene_block)]);jc+=1
        # ----------------------------------------
        # 実flatからの新geometryを消費する。FAK失効後も旧注文を復活させない。
        kind=-1;attempt=False
        if held==0 and not pending and direction!=0 and not blocked:
            if usable:
                oriented=direction*prices[i]
                if anchor_row<0:
                    anchor_row=i;anchor=prices[i];extreme=oriented;trough=oriented;stage=0;pull_row=-1
                elif i>anchor_row:
                    if stage==0:
                        extreme=max(extreme,oriented)
                        if extreme-oriented>=paper_price*pull_fraction:
                            stage=1;trough=oriented;pull_row=i
                    else:trough=min(trough,oriented)
                pull=stage==1 and i>pull_row and oriented>=trough+paper_price*recover_fraction
                breakout=i>anchor_row and oriented>=direction*anchor+paper_price*break_fraction
                strong=bool(own_known[i] and peer_known[i] and direction*own_balance[i]>=.75 and direction*peer_balance[i]>=.75)
                if original:attempt=True;kind=0
                elif reentry_mode==1 and pull:attempt=True;kind=1
                elif reentry_mode==2 and breakout:attempt=True;kind=2
                elif reentry_mode==3 and ((strong and breakout) or (not strong and pull)):
                    attempt=True;kind=2 if strong else 1
        elif held==0 and direction==0:anchor_row=-1;stage=0
        if original and not attempt:attempt=True;kind=0
        if attempt:
            spread=ask[i]-bid[i] if good else np.nan;quote=ask[i] if direction>0 else bid[i]
            public_n=quote*cap*mult if good else np.nan;cost=spread*cap*mult+2*fee(cap,num,den) if good else np.nan
            allowance=1 if own_known[i] and peer_known[i] and direction*own_balance[i]>=.75 and direction*peer_balance[i]>=.75 else 0
            pricecap=quote+direction*allowance*tick if good else np.nan
            reason=0
            if blocked or scene_block:reason=scene_block_reason if scene_block else 93 if t>=end else 92
            elif held>0 or pending or exit_pending:reason=94
            elif original and origin_withdrawn:reason=151
            elif not(start+300.<=t<end-300.):reason=153
            elif direction==0 or not usable or not np.isfinite(paper_price) or paper_price<=0 or not np.isfinite(paper_atr) or paper_atr<=0:reason=96
            elif not own_known[i] or not peer_known[i] or own_count[i]<2 or peer_count[i]<2 or not(direction*own_balance[i]>=.25 and direction*peer_balance[i]>=.25):reason=95
            elif cost>.5*public_n*parent_stop_fraction:reason=154
            accepted=reason==0;cid=next_cid if accepted else -1
            pubs[pc]=np.array([i,cid,paper_cid,direction,kind,cap,paper_price,paper_atr,spread,public_n,pricecap,allowance,
                int(accepted),reason,own_count[i],own_balance[i],peer_count[i],peer_balance[i],cost,
                .5*public_n*parent_stop_fraction,anchor_row,anchor]);pc+=1
            if accepted:
                pending=True;pending_row=i;pending_cid=cid;pending_paper=paper_cid;pending_side=direction
                pending_cap=pricecap;pending_allow=allowance;pending_price=paper_price;pending_atr=paper_atr;next_cid+=1
            anchor_row=i if usable else -1;anchor=prices[i] if usable else np.nan
            extreme=direction*anchor;trough=extreme;stage=0;pull_row=-1
        curve[i]=np.array([equity,liquid,local,peak if np.isfinite(peak) else np.nan,longq,shortq,paid,reserve,
            actual_cid,scene_stop,scene_goal,paper_cid,direction,abs(paper_v)])
        geometry[i]=np.array([anchor_row,anchor,extreme,trough,stage,paper_cid,pull_row])
    assert pointer==len(feed)
    return orders[:int(counters[0])],uids[:int(counters[0])],curve,pubs[:pc],judges[:jc],events[:ec],origins[:nc],geometry,capacity
