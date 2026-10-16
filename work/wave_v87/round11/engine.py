"""相手元GUの当時状態を参照し、自己目標だけを次観測へ実行する。"""
import numpy as np
from numba import njit

EVENT_COLUMNS=['行','種別','根拠行','仮想組','方向又は目標','枚数','価格','役割','新規区分','仮想自己差引','相手差引','実差引']
STATE_COLUMNS=['仮想組','仮想自己差引','相手差引','実組','実買枚数','実売枚数','次目標組','次目標','途中縮小済み','未実行目標']
PEER_COLUMNS=['自己行','種別','自己組','自己方向','相手参照又は停止行','相手時計','相手組','相手差引','相手清算又は完了収支','相手現在順行ATR','自己仮想残枚数','実残枚数','入口方式','途中方式','許可又は発火','相手理由','古さ秒','相手新規行','自己仮想新規行','相手初回ATR','相手初回建値']

# ----------------------------------------
# 実注文のUID会計部品は凍結済み第十段階を読み取って再利用する。
import importlib.util
import sys
from pathlib import Path
_name='wave87_round10_engine'
if _name not in sys.modules:
    _spec=importlib.util.spec_from_file_location(_name,Path(__file__).resolve().parent.parent/'round10/engine.py')
    _module=importlib.util.module_from_spec(_spec);sys.modules[_name]=_module;_spec.loader.exec_module(_module)
execute=sys.modules[_name].execute


@njit(cache=True)
def simulate(times,prices,feed,quiet,quiet_force,end,entry_mode,holding_mode,cap,
        peer_times,peer_prices,peer_feed,peer_refs,peer_value,peer_fee):
    """
    機能: 仮想注文を当行までだけ適用し、相手入口制限と一回の途中縮小を次観測へ送る。
    引数: 原価格・仮想注文・予定・相手素材(ndarray)、end/peer_value/peer_fee(float)、方式と上限(int)。
    返り値: tuple。注文、脚、全行時価、統計、親組、UID、実行証跡、全行状態、相手証跡。
    相手の将来親組収支・終了行・MFEを受け取らず、peer_feedの公開済み注文から復元する。
    """
    n=len(times);capacity=max(128,len(feed)*8+len(peer_feed)*4+32)
    if len(feed):capacity=max(capacity,int(feed[:,2].max())+2)
    orders=np.zeros((capacity,8));trades=np.zeros((capacity*max(2,cap),11));uids=np.full(capacity,-1,np.int64)
    slots=np.zeros((capacity,7));inventory=np.zeros((3,2),np.int64);counters=np.zeros(9)
    parent=np.zeros((capacity,11));parent[:,0:3]=-1
    curve=np.zeros((n,8));states=np.zeros((n,10));events=np.zeros((capacity*8,12));ec=0
    proof=np.zeros((capacity*4,21));pc=0
    pointer=0;virtual_cid=-1;real_cid=-1;vcore=0;own_entry=-1;own_side=0
    allowed=False;reduced=False;pending=False;source=-1;target_cid=-1;target=0
    force_source=-1;force_reason=0;peak=0.;dd=0.
    pp=0;peer_cid=-1;peer_qty=0;peer_side=0;peer_entry=-1;peer_entry_price=0.;peer_atr=0.
    peer_cash=0.;peer_paid=0.
    for i in range(n):
        t=times[i];p=prices[i]
        scheduled=bool(quiet[i] or quiet_force[i] or t>=end)
        if scheduled:
            if force_source<0:force_source=max(0,i-1)
            force_reason=93 if t>=end else 92
            pending=False
        if not np.isfinite(p) or p<=0:
            assert pointer>=len(feed) or int(feed[pointer,0])!=i
            if i:curve[i]=curve[i-1];states[i]=states[i-1]
            continue
        # ----------------------------------------
        # 既知の予定を最優先。新しい相手情報を読む前に前行の実目標を約定する。
        blocked=scheduled or force_source>=0
        if blocked:
            for side in (1,-1):
                qty=int(inventory[:,0 if side>0 else 1].sum())
                if qty:
                    assert force_source<i
                    execute(orders,trades,uids,slots,inventory,counters,parent,i,force_source,real_cid,-side,qty,p,0,-1,force_reason)
                    events[ec]=np.array([i,4.,force_source,real_cid,-side,qty,p,-1.,0.,vcore,peer_qty,0.]);ec+=1
            pending=False;force_source=-1;force_reason=0
        elif pending:
            assert source<i
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
            events[ec]=np.array([i,3.,source,target_cid,target,0.,p,-1.,-1.,vcore,peer_qty,target]);ec+=1
            pending=False
        # ----------------------------------------
        # 自己の無変更仮想注文を当行まで適用する。初回条件は相手公開後に一度だけ判定する。
        first=pointer;new_parent=False
        while pointer<len(feed) and int(feed[pointer,0])==i:
            o=feed[pointer];pointer+=1
            cid=int(o[2]);side=int(o[3]);qty=int(o[4]);new=int(o[7])
            assert int(o[8])==0
            if new:
                assert vcore==0 and not new_parent
                virtual_cid=cid;own_entry=i;own_side=side;allowed=False;reduced=False;new_parent=True
                assert 0<=cid<capacity and o[9]>0
                parent[cid,0]=i;parent[cid,3]=qty*o[9];parent[cid,4]=o[9];parent[cid,5]=side
            assert cid==virtual_cid
            vcore+=side*qty
            events[ec]=np.array([i,1.,i,cid,side,qty,o[5],0.,new,vcore,peer_qty,inventory[:,0].sum()-inventory[:,1].sum()]);ec+=1
        assert pointer>=len(feed) or int(feed[pointer,0])>i
        # ----------------------------------------
        # 相手の注文を厳密過去の有効価格行まで読む。停止はこの初公開行で一度だけ消費する。
        ref=int(peer_refs[i]);h_changed=False
        if ref>=0:assert peer_times[ref]<t and np.isfinite(peer_prices[ref]) and peer_prices[ref]>0
        while pp<len(peer_feed) and int(peer_feed[pp,0])<=ref:
            o=peer_feed[pp];pp+=1;row=int(o[0]);cid=int(o[2]);side=int(o[3]);qty=int(o[4]);new=int(o[7]);reason=int(o[6])
            assert peer_times[row]<t and 0<=int(o[1])<row and np.isfinite(peer_prices[row]) and peer_prices[row]>0
            if new:
                assert peer_qty==0 and o[9]>0
                peer_cid=cid;peer_side=side;peer_entry=row;peer_entry_price=o[5];peer_atr=o[9];peer_cash=0.;peer_paid=0.
            else:
                assert cid==peer_cid and side==-peer_side and qty<=abs(peer_qty)
            peer_qty+=side*qty;peer_cash-=side*qty*o[5]*peer_value
            peer_paid+=np.floor(qty*peer_fee+1e-8)
            if not new and peer_qty==0 and reason in (1,32) and peer_cash-peer_paid<0:
                age=t-peer_times[row];actual=int(inventory[:,0].sum()-inventory[:,1].sum())
                trigger=(holding_mode>0 and not reduced and allowed and not blocked and vcore!=0 and
                    own_side==peer_side and own_entry<i and real_cid==virtual_cid and actual*own_side>0 and
                    parent[virtual_cid,1]>=0 and parent[virtual_cid,1]<=i and age<=180.)
                proof[pc]=np.array([i,2.,virtual_cid,own_side,row,peer_times[row],peer_cid,peer_qty,peer_cash-peer_paid,0.,abs(vcore),abs(actual),entry_mode,holding_mode,int(trigger),reason,age,peer_entry,own_entry,peer_atr,peer_entry_price]);pc+=1
                if trigger:
                    reduced=True;h_changed=True
                    proof[pc]=proof[pc-1];proof[pc,1]=3.;pc+=1
        # ----------------------------------------
        # 入口の許可は初回だけ。E3は現在順行であり、最大順行やE2を追加要求しない。
        if new_parent:
            age=t-peer_times[ref] if ref>=0 else -1.
            fresh=ref>=0 and age<=180.
            liquidation=0.;progress=0.
            if ref>=0 and peer_qty!=0:
                liquidation=peer_cash+peer_qty*peer_prices[ref]*peer_value-peer_paid-np.floor(abs(peer_qty)*peer_fee+1e-8)
                progress=peer_side*(peer_prices[ref]-peer_entry_price)/peer_atr
            same=fresh and peer_qty*own_side>0
            allowed=entry_mode==0 or (same and (entry_mode==1 or (entry_mode==2 and liquidation>=0.) or (entry_mode==3 and progress>=.25)))
            proof[pc]=np.array([i,1.,virtual_cid,own_side,ref,peer_times[ref] if ref>=0 else -1.,peer_cid,peer_qty,liquidation,progress,abs(vcore),inventory.sum(),entry_mode,holding_mode,int(allowed),0.,age,peer_entry,own_entry,peer_atr,peer_entry_price]);pc+=1
        desired=vcore if allowed else 0
        if reduced:
            desired=0 if holding_mode==2 or vcore==0 else own_side*((abs(vcore)+1)//2)
        if not blocked and (pointer>first or h_changed):
            target_cid=virtual_cid;target=desired;source=i
            current=int(inventory[:,0].sum()-inventory[:,1].sum())
            pending=target!=current or (real_cid!=target_cid and inventory.sum()>0)
            if not pending and inventory.sum()==0:real_cid=target_cid
            if pending:
                events[ec]=np.array([i,2.,i,target_cid,target,0.,p,-1.,-1.,vcore,peer_qty,current]);ec+=1
        longqty=int(inventory[:,0].sum());shortqty=int(inventory[:,1].sum())
        assert longqty<=cap and shortqty<=cap and longqty>=0 and shortqty>=0
        if real_cid>=0:
            parent[real_cid,8]=max(parent[real_cid,8],longqty+shortqty)
            parent[real_cid,9]=max(parent[real_cid,9],abs(longqty-shortqty))
        equity=counters[3]+(longqty-shortqty)*p;peak=max(peak,equity);dd=max(dd,peak-equity)
        curve[i]=np.array([equity,counters[4],longqty,shortqty,dd,counters[3],longqty-shortqty,real_cid])
        states[i]=np.array([virtual_cid,vcore,peer_qty,real_cid,longqty,shortqty,target_cid,target,int(reduced),int(pending)])
        assert ec<len(events)-16 and pc<len(proof)-16
    oc=int(counters[0]);tc=int(counters[1]);cycles=np.zeros((capacity,10));cc=0
    for cid in range(capacity):
        if parent[cid,6]==0:continue
        residual=0
        for k in range(int(counters[2])):
            if int(slots[k,6])==cid:residual+=int(slots[k,0])
        if residual or (cid==virtual_cid and vcore!=0):continue
        cycles[cc]=np.array([cid,parent[cid,1],parent[cid,2],parent[cid,7],parent[cid,3],parent[cid,4],parent[cid,8],parent[cid,9],parent[cid,5],parent[cid,10]]);cc+=1
    assert counters[5]<=cap and counters[6]<=cap
    stats=np.array([counters[4],dd,counters[5],counters[6],counters[7],counters[8],0.,min(0.,curve[:,0].min()),max(0.,curve[:,0].max()),inventory.sum(),0.])
    return orders[:oc],trades[:tc],curve,stats,cycles[:cc],uids[:oc],events[:ec],states,proof[:pc]
