"""当行の仮想約定を受け、次の有効観測で実建玉を作る三つの実行層。"""
import numpy as np
from numba import njit

EVENT_COLUMNS=['行','種別','根拠行','仮想組','方向又は目標','枚数','価格','役割','新規区分','仮想コア差引','仮想保険差引','実コア側でなく全差引']
STATE_COLUMNS=['仮想組','仮想コア差引','仮想保険差引','実組','実買枚数','実売枚数','次目標組','次差引目標','終了抑止','未処理仮想注文数']


@njit(cache=True)
def execute(orders,trades,uids,slots,inventory,counters,parent,row,source,cid,side,qty,price,new,role,reason):
    """
    機能: 実注文を一つ記録し、建値別UIDの実玉を新規又はFIFO返済する。
    引数: 注文・脚・UID・枠・枚数・状態・親組(ndarray)、行/組/方向/枚数/種別/役割/理由(int)、価格(float)。
    返り値: None。注文料金は後会計でこの実注文単位に課す。
    """
    assert qty>0 and source>=0 and source<row
    oc=int(counters[0]);tc=int(counters[1]);ticket=int(counters[2])
    assert oc<len(orders)-1
    orders[oc]=np.array([row,source,cid,side,qty,price,reason,new]);uids[oc]=-1
    if new:
        assert role>=0
        assert ticket<len(slots)-1
        slots[ticket]=np.array([qty,side,price,row,ticket,role,cid])
        inventory[role,0 if side>0 else 1]+=qty
        uids[oc]=ticket;ticket+=1
        if parent[cid,1]<0:parent[cid,1]=row
        parent[cid,6]=1
    else:
        held=-side;left=qty
        for k in range(ticket):
            if left==0:break
            if slots[k,0]<=0 or int(slots[k,1])!=held or int(slots[k,6])!=cid:continue
            if role>=0 and int(slots[k,5])!=role:continue
            take=min(left,int(slots[k,0]));gain=held*take*(price-slots[k,2])
            assert tc<len(trades)-1
            trades[tc]=np.array([cid,slots[k,4],held,take,slots[k,2],price,slots[k,3],row,slots[k,5],reason,gain]);tc+=1
            slots[k,0]-=take;inventory[int(slots[k,5]),0 if held>0 else 1]-=take
            counters[4]+=gain;parent[cid,2]=row;parent[cid,7]+=gain;parent[cid,10]=reason
            left-=take
        assert left==0
    counters[3]-=side*qty*price
    counters[0]=oc+1;counters[1]=tc;counters[2]=ticket
    longqty=int(inventory[:,0].sum());shortqty=int(inventory[:,1].sum())
    assert longqty>=0 and shortqty>=0
    counters[5]=max(counters[5],longqty);counters[6]=max(counters[6],shortqty)
    counters[7]=max(counters[7],longqty+shortqty);counters[8]=max(counters[8],abs(longqty-shortqty))
    parent[cid,8]=max(parent[cid,8],longqty+shortqty)
    parent[cid,9]=max(parent[cid,9],abs(longqty-shortqty))


@njit(cache=True)
def simulate(times,prices,feed,quiet,quiet_force,end,mode,cap):
    """
    機能: 前回の実注文計画を約定後、当行までの仮想注文だけから次回目標を作る。
    引数: times/prices/quiet/quiet_force(ndarray)、feed(ndarray10列)、end(float)、mode/cap(int)。
    返り値: tuple。注文8列・脚11列・時価8列・統計11列・親組10列・新規UID・証跡12列・状態10列。
    feedは仮想注文8列に役割0コア/1保険と当行新規ATRを加えたもの。将来の親終了行を受け取らない。
    """
    n=len(times);capacity=max(128,len(feed)*8+32)
    if len(feed):capacity=max(capacity,int(feed[:,2].max())+2)
    orders=np.zeros((capacity,8));trades=np.zeros((capacity*max(2,cap),11));uids=np.full(capacity,-1,np.int64)
    slots=np.zeros((capacity,7));inventory=np.zeros((3,2),np.int64);counters=np.zeros(9)
    parent=np.zeros((capacity,11));parent[:,0:3]=-1
    curve=np.zeros((n,8));states=np.zeros((n,10));events=np.zeros((capacity*8,12));ec=0
    pointer=0;virtual_cid=-1;real_cid=-1;vcore=0;vsat=0;closed=False
    pending=False;source=-1;target_cid=-1;target=0;queue_from=0;queue_to=0
    force_source=-1;force_reason=0;last_price=0.;peak=0.;dd=0.;maxlong=maxshort=maxgross=maxnet=0
    for i in range(n):
        t=times[i];p=prices[i]
        scheduled=bool(quiet[i] or quiet_force[i] or t>=end)
        if scheduled:
            if force_source<0:force_source=max(0,i-1)
            force_reason=93 if t>=end else 92
            pending=False;queue_from=queue_to
        if not np.isfinite(p) or p<=0:
            assert pointer>=len(feed) or int(feed[pointer,0])!=i
            if i:curve[i]=curve[i-1];states[i]=states[i-1]
            continue
        last_price=p
        # ----------------------------------------
        # 既知の予定は待機注文より先。欠測中に予定到来した場合も最初の有効観測で清算する。
        blocked=scheduled or force_source>=0
        if blocked:
            for side in (1,-1):
                qty=int(inventory[:,0 if side>0 else 1].sum())
                if qty:
                    assert force_source<i
                    execute(orders,trades,uids,slots,inventory,counters,parent,i,force_source,real_cid,-side,qty,p,0,-1,force_reason)
                    events[ec]=np.array([i,4.,force_source,real_cid,-side,qty,p,-1.,0.,vcore,vsat,0.]);ec+=1
            pending=False;queue_from=queue_to;force_source=-1;force_reason=0
        elif pending:
            assert source<i
            if mode==0:
                for k in range(queue_from,queue_to):
                    o=feed[k];cid=int(o[2]);side=int(o[3]);qty=int(o[4]);new=int(o[7]);role=int(o[8])
                    if new:
                        if cid!=real_cid:assert inventory.sum()==0;real_cid=cid
                    execute(orders,trades,uids,slots,inventory,counters,parent,i,source,cid,side,qty,p,new,role,90 if new else 91)
            else:
                if real_cid!=target_cid:
                    for side in (1,-1):
                        qty=int(inventory[:,0 if side>0 else 1].sum())
                        if qty:execute(orders,trades,uids,slots,inventory,counters,parent,i,source,real_cid,-side,qty,p,0,-1,94)
                    real_cid=target_cid
                current=int(inventory[:,0].sum()-inventory[:,1].sum())
                if current and (target==0 or current*target<=0 or abs(target)<abs(current)):
                    qty=abs(current) if target*current<=0 else abs(current)-abs(target)
                    side=1 if current>0 else -1
                    execute(orders,trades,uids,slots,inventory,counters,parent,i,source,real_cid,-side,qty,p,0,-1,91)
                    current=int(inventory[:,0].sum()-inventory[:,1].sum())
                if abs(target)>abs(current):
                    side=1 if target>0 else -1;qty=abs(target)-abs(current)
                    execute(orders,trades,uids,slots,inventory,counters,parent,i,source,real_cid,side,qty,p,1,2,90)
            assert int(inventory[:,0].sum()-inventory[:,1].sum())==target
            events[ec]=np.array([i,3.,source,target_cid,target,0.,p,-1.,-1.,vcore,vsat,target]);ec+=1
            pending=False
        # ----------------------------------------
        # 仮想注文は当行の分だけ読む。親組情報はコアの新規が当行までに発生して初めて登録する。
        first=pointer
        while pointer<len(feed) and int(feed[pointer,0])==i:
            o=feed[pointer];pointer+=1
            cid=int(o[2]);side=int(o[3]);qty=int(o[4]);new=int(o[7]);role=int(o[8])
            if role==0 and new:
                assert vcore==0 and vsat==0
                virtual_cid=cid;closed=False
                assert 0<=cid<capacity and o[9]>0
                parent[cid,0]=i;parent[cid,3]=qty*o[9];parent[cid,4]=o[9];parent[cid,5]=side
            assert cid==virtual_cid
            if role==0:
                vcore+=side*qty
                if not new and vcore==0:closed=True
            else:vsat+=side*qty
            events[ec]=np.array([i,1.,i,cid,side,qty,o[5],role,new,vcore,vsat,inventory[:,0].sum()-inventory[:,1].sum()]);ec+=1
        assert pointer>=len(feed) or int(feed[pointer,0])>i
        desired=0 if mode==2 and closed else vcore+vsat
        if not blocked and pointer>first:
            target_cid=virtual_cid;target=desired;source=i
            queue_from=first;queue_to=pointer
            if mode==0:
                pending=True
            else:
                current=int(inventory[:,0].sum()-inventory[:,1].sum())
                pending=target!=current or (real_cid!=target_cid and inventory.sum()>0)
                if not pending and inventory.sum()==0:real_cid=target_cid
            if pending:
                events[ec]=np.array([i,2.,i,target_cid,target,0.,p,-1.,-1.,vcore,vsat,inventory[:,0].sum()-inventory[:,1].sum()]);ec+=1
        longqty=int(inventory[:,0].sum());shortqty=int(inventory[:,1].sum())
        assert longqty<=cap and shortqty<=cap and longqty>=0 and shortqty>=0
        maxlong=max(maxlong,longqty);maxshort=max(maxshort,shortqty);maxgross=max(maxgross,longqty+shortqty);maxnet=max(maxnet,abs(longqty-shortqty))
        if real_cid>=0:
            parent[real_cid,8]=max(parent[real_cid,8],longqty+shortqty)
            parent[real_cid,9]=max(parent[real_cid,9],abs(longqty-shortqty))
        equity=counters[3]+(longqty-shortqty)*p;peak=max(peak,equity);dd=max(dd,peak-equity)
        curve[i]=np.array([equity,counters[4],longqty,shortqty,dd,counters[3],longqty-shortqty,real_cid])
        states[i]=np.array([virtual_cid,vcore,vsat,real_cid,longqty,shortqty,target_cid,target,int(closed),queue_to-queue_from if pending else 0])
        assert ec<len(events)-16
    oc=int(counters[0]);tc=int(counters[1]);cycles=np.zeros((capacity,10));cc=0
    # ----------------------------------------
    # 完了した実親組を後会計へ渡す。途中で差引ゼロになっても新たな親組へ分割しない。
    for cid in range(capacity):
        if parent[cid,6]==0:continue
        residual=0
        for k in range(int(counters[2])):
            if int(slots[k,6])==cid:residual+=int(slots[k,0])
        active_virtual=cid==virtual_cid and (vcore!=0 or vsat!=0)
        if residual or active_virtual:continue
        cycles[cc]=np.array([cid,parent[cid,1],parent[cid,2],parent[cid,7],parent[cid,3],parent[cid,4],parent[cid,8],parent[cid,9],parent[cid,5],parent[cid,10]]);cc+=1
    assert counters[5]<=cap and counters[6]<=cap
    stats=np.array([counters[4],dd,counters[5],counters[6],counters[7],counters[8],0.,min(0.,curve[:,0].min()),max(0.,curve[:,0].max()),inventory.sum(),0.])
    return orders[:oc],trades[:tc],curve,stats,cycles[:cc],uids[:oc],events[:ec],states
