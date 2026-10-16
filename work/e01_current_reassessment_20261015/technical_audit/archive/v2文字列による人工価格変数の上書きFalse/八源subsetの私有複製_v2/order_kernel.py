"""旧round10のFIFO注文関数を数値変更せず106のJITへ隔離した写し。"""
import numpy as np
from numba import njit

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

