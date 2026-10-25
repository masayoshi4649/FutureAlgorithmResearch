"""有利な指値は最初の元返済まで待ち、成立後は元返済の順序を写す。"""
from pathlib import Path
import importlib.util
import sys
import numpy as np
from numba import njit

EVENT_COLUMNS=['行','種別','根拠行','親組','注文方向','枚数','観測価格','役割','新規区分','元GU残差引','未約定待機','実差引']
STATE_COLUMNS=['元GU組','元GU差引','実組','実買枚数','実売枚数','指値待機','永久取消','実新規済み','指値線','未実行返済数']
LIMIT_COLUMNS=['行','種別','親組','予約元行','方向','初回枚数','紙上建値','固定ATR','指値線','観測価格','実新規行','紙上残枚数','実残枚数','未約定待機','永久取消','有利幅ATR','当行紙上注文行','理由']

_name='wave87_round10_engine'
if _name not in sys.modules:
    _spec=importlib.util.spec_from_file_location(_name,Path(__file__).resolve().parent.parent/'round10/engine.py')
    _module=importlib.util.module_from_spec(_spec);sys.modules[_name]=_module;_spec.loader.exec_module(_module)
execute=sys.modules[_name].execute


@njit(cache=True)
def simulate(times,prices,feed,quiet,quiet_force,end,cap,tick,offset,unconditional):
    """
    機能: 紙上新規から知った有利指値を次観測へ置き、紙上初返済前だけ新規可能にする。
    引数: 原価格・紙上注文・予定(ndarray)、end/tick/offset(float)、cap(int)、unconditional(bool)。
    返り値: tuple。注文、脚、時価、統計、親組、UID、実行証跡、全行状態、指値証跡。
    """
    n=len(times);capacity=max(128,len(feed)*8+32)
    if len(feed):capacity=max(capacity,int(feed[:,2].max())+2)
    orders=np.zeros((capacity,8));trades=np.zeros((capacity*max(2,cap),11));uids=np.full(capacity,-1,np.int64)
    slots=np.zeros((capacity,7));inventory=np.zeros((3,2),np.int64);counters=np.zeros(9)
    parent=np.zeros((capacity,11));parent[:,0:3]=-1
    curve=np.zeros((n,8));states=np.zeros((n,10));events=np.zeros((capacity*8,12));ec=0
    proof=np.zeros((capacity*4,18));pc=0;exitqueue=np.zeros(capacity,np.int64);queued=0;exit_source=-1
    pointer=0;virtual_cid=-1;vcore=0;real_cid=-1;pending=False;cancelled=False;filled=False
    entry_source=-1;entry_side=0;entry_qty=0;entry_price=0.;atr=0.;line=0.
    force_source=-1;force_reason=0;peak=0.;dd=0.
    for i in range(n):
        t=times[i];p=prices[i]
        scheduled=bool(quiet[i] or quiet_force[i] or t>=end)
        if scheduled:
            if force_source<0:force_source=max(0,i-1)
            force_reason=93 if t>=end else 92
            queued=0
            if pending:
                pending=False;cancelled=True
                proof[pc]=np.array([i,4.,virtual_cid,entry_source,entry_side,entry_qty,entry_price,atr,line,p,-1.,abs(vcore),inventory.sum(),0.,1.,offset,-1.,force_reason]);pc+=1
        if not np.isfinite(p) or p<=0:
            assert pointer>=len(feed) or int(feed[pointer,0])!=i
            if i:curve[i]=curve[i-1];states[i]=states[i-1]
            continue
        # ----------------------------------------
        # 既知の予定を優先し、前行までに送信した返済と指値を当行情報の更新前に約定する。
        blocked=scheduled or force_source>=0
        if blocked:
            for side in (1,-1):
                qty=int(inventory[:,0 if side>0 else 1].sum())
                if qty:
                    assert force_source<i
                    execute(orders,trades,uids,slots,inventory,counters,parent,i,force_source,real_cid,-side,qty,p,0,-1,force_reason)
                    events[ec]=np.array([i,4.,force_source,real_cid,-side,qty,p,-1.,0.,vcore,0.,0.]);ec+=1
            queued=0;pending=False;force_source=-1;force_reason=0
        else:
            for q in range(queued):
                o=feed[exitqueue[q]];cid=int(o[2]);side=int(o[3]);qty=int(o[4])
                assert cid==real_cid and int(o[7])==0 and exit_source<i
                execute(orders,trades,uids,slots,inventory,counters,parent,i,exit_source,cid,side,qty,p,0,0,91)
                events[ec]=np.array([i,3.,exit_source,cid,side,qty,p,0.,0.,vcore,int(pending),inventory[:,0].sum()-inventory[:,1].sum()]);ec+=1
            queued=0
            if pending and (unconditional or (entry_side>0 and p<=line) or (entry_side<0 and p>=line)):
                assert entry_source<i and not filled and not cancelled and inventory.sum()==0
                real_cid=virtual_cid
                execute(orders,trades,uids,slots,inventory,counters,parent,i,entry_source,real_cid,entry_side,entry_qty,p,1,0,90)
                pending=False;filled=True
                events[ec]=np.array([i,3.,entry_source,real_cid,entry_side,entry_qty,p,0.,1.,vcore,0.,inventory[:,0].sum()-inventory[:,1].sum()]);ec+=1
                proof[pc]=np.array([i,2.,virtual_cid,entry_source,entry_side,entry_qty,entry_price,atr,line,p,i,abs(vcore),inventory.sum(),0.,0.,offset,-1.,90.]);pc+=1
        # ----------------------------------------
        # 当行紙上注文だけを読み、初回の返済前にまだ指値未成立ならその親で永久取消する。
        while pointer<len(feed) and int(feed[pointer,0])==i:
            o=feed[pointer];feed_index=pointer;pointer+=1
            cid=int(o[2]);side=int(o[3]);qty=int(o[4]);new=int(o[7]);reason=int(o[6])
            assert int(o[8])==0
            if new:
                assert vcore==0 and o[9]>0
                virtual_cid=cid;entry_source=i;entry_side=side;entry_qty=qty;entry_price=o[5];atr=o[9]
                cancelled=blocked;filled=False;pending=not blocked
                raw=entry_price-side*offset*atr
                line=np.floor(raw/tick+1e-12)*tick if side>0 else np.ceil(raw/tick-1e-12)*tick
                parent[cid,0]=i;parent[cid,3]=qty*atr;parent[cid,4]=atr;parent[cid,5]=side
                vcore+=side*qty
                proof[pc]=np.array([i,1.,cid,entry_source,side,qty,entry_price,atr,line,p,-1.,abs(vcore),inventory.sum(),int(pending),int(cancelled),offset,i,reason]);pc+=1
            else:
                assert cid==virtual_cid and side*entry_side<0 and qty<=abs(vcore)
                vcore+=side*qty
                if pending:
                    pending=False;cancelled=True
                    proof[pc]=np.array([i,3.,cid,entry_source,entry_side,entry_qty,entry_price,atr,line,p,-1.,abs(vcore),inventory.sum(),0.,1.,offset,i,reason]);pc+=1
                elif filled and not blocked and real_cid==cid and inventory.sum()>0:
                    exitqueue[queued]=feed_index;queued+=1;exit_source=i
            events[ec]=np.array([i,1.,i,cid,side,qty,o[5],0.,new,vcore,int(pending),inventory[:,0].sum()-inventory[:,1].sum()]);ec+=1
        assert pointer>=len(feed) or int(feed[pointer,0])>i
        longqty=int(inventory[:,0].sum());shortqty=int(inventory[:,1].sum())
        assert 0<=longqty<=cap and 0<=shortqty<=cap
        equity=counters[3]+(longqty-shortqty)*p;peak=max(peak,equity);dd=max(dd,peak-equity)
        curve[i]=np.array([equity,counters[4],longqty,shortqty,dd,counters[3],longqty-shortqty,real_cid])
        states[i]=np.array([virtual_cid,vcore,real_cid,longqty,shortqty,int(pending),int(cancelled),int(filled),line,queued])
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
