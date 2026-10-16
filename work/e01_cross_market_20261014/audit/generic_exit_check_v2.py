"""逐次保護の8源を、独立実料book・初先着・次正常UID返済・未完了接頭で確認する。"""

from pathlib import Path
import copy
import hashlib
import json
import os
import sys

import numpy as np
import numba

from cash_distance_oracle import fee


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=HERE.parent/'engine'
sys.dont_write_bytecode=True
sys.path.insert(0,str(SOURCE))
import common
os.environ['NUMBA_CACHE_DIR']=str(HERE/'generic_exit_jit')
numba.config.CACHE_DIR=str(HERE/'generic_exit_jit')
import daily
import context
import exit_core
import exit_policy


def book(orders: np.ndarray, uids: np.ndarray, quotes: dict, symbol: str) -> tuple:
    """
    機能: 実注文接頭だけから、現金・実料・残UID・清算時価を独立計算する。
    引数: orders/uids(ndarray)、quotes(dict)、symbol(str)は人工の実注文と気配。
    返り値: tupleは費用5曲線と終端UID。daily会計又は保存市場資料を使わない。
    """
    value=1000 if symbol=='TOPIX' else 10;budget=5000 if symbol=='TOPIX' else 2000
    curve=np.zeros((len(quotes['bid']),5));held={};cash=0.;paid=0;cursor=0;last=None
    for row in range(len(curve)):
        while cursor<len(orders) and orders[cursor,0]==row:
            order=orders[cursor];side,q,cid,new=map(int,(order[3],order[4],order[2],order[7]))
            cash-=side*q*order[5];paid+=fee(q,symbol)
            if new:held[int(uids[cursor])]=dict(uid=int(uids[cursor]),cid=cid,side=side,remaining=q)
            else:
                need=q
                for item in held.values():
                    if item['cid']==cid and item['side']==-side:
                        closed=min(need,item['remaining']);item['remaining']-=closed;need-=closed
                assert need==0
            cursor+=1
        if quotes['quote_valid'][row] and 0<quotes['bid'][row]<quotes['ask'][row]:last=row
        reserve=sum(fee(item['remaining'],symbol) for item in held.values() if item['remaining'])
        mark=cash if last is None else cash+sum(item['side']*item['remaining']*quotes['bid' if item['side']==1 else 'ask'][last] for item in held.values())
        equity=mark*value-paid;liquid=equity-reserve;curve[row]=(paid,reserve,equity,liquid,max(0.,budget+liquid))
    return curve,held


def fixture(symbol: str, side: int=1, canceled: bool=False, missing: bool=False, cut: int=18) -> tuple:
    """
    機能: 部分返済・前親確定益・次親spread料と取消初回を含む独立人工を作る。
    引数: symbol(str)、side(int)、canceled/missing(bool)、cut(int)は人工の種類と接頭長。
    返り値: tupleは口座と二保存GU台帳。実市場又は旧結果を読まない。
    """
    n=18;tick=.5 if symbol=='TOPIX' else 10.;base=100. if symbol=='TOPIX' else 1000.
    full=5 if symbol=='TOPIX' else 10;q1=2 if symbol=='TOPIX' else 3;q2=3 if symbol=='TOPIX' else 2
    moves=np.array([0,0,0,0,2,4,3,2,2,2,2,2,1,0,0,0,0,0],float)
    bid=base+side*moves*tick;ask=bid+tick;normal=np.ones(n,bool)
    if missing:normal[12:14]=False
    seq=np.arange(700,700+n,dtype=np.int64);clock=np.arange(n,dtype=float)/2
    quotes=dict(bid=bid,ask=ask,quote_valid=normal,seq=seq,time_s=clock)
    orders=[];uids=[]
    if not canceled:
        orders.extend([[3,2,0,side,q1,quotes['ask' if side==1 else 'bid'][3],0,1],
            [6,5,0,-side,1,quotes['bid' if side==1 else 'ask'][6],91,0],
            [8,7,0,-side,q1-1,quotes['bid' if side==1 else 'ask'][8],91,0]])
        uids.extend([101,-1,-1])
    orders.extend([[10,9,1,side,q2,quotes['ask' if side==1 else 'bid'][10],0,1],
        [15,14,1,-side,q2,quotes['bid' if side==1 else 'ask'][15],91,0]])
    uids.extend([202,-1]);orders=np.asarray(orders,float);uids=np.asarray(uids,np.int64)
    orders_mask=orders[:,0]<cut;orders=orders[orders_mask];uids=uids[orders_mask]
    quotes={k:v[:cut].copy() for k,v in quotes.items()}
    account=dict(symbol=symbol,record=dict(price=(quotes['bid']+quotes['ask'])/2,seq=quotes['seq'],time_s=quotes['time_s'],tick=tick,limit=8.5),quotes=quotes)
    curve,_=book(orders,uids,quotes,symbol)
    events=[]
    for row,cid,q,atr in ((2,0,q1,1.5 if symbol=='TOPIX' else 40.),(9,1,q2,1.25 if symbol=='TOPIX' else 65.)):
        if row<cut:
            events.append([row,cid,side,full,q,atr,tick,atr*(1000 if symbol=='TOPIX' else 10),
                curve[row,3],curve[row,4],0,curve[row,0],curve[row,1],0,1,1])
    ledger=dict(key=('人工',symbol),shadow_GU_orders=orders,shadow_GU_uids=uids,
        execution_events=np.empty((0,12)),execution_states=np.zeros((cut,10)),limit_events=np.empty((0,18)),
        sizing_events=np.asarray(events,float).reshape((-1,16)),sizing_fee_curve=curve)
    return account,ledger,copy.deepcopy(ledger)


def scan_oracle(curve: np.ndarray, normal: np.ndarray, start: int, arm: float, draw: float, floor: float,
                loss: float|None, target: float|None) -> tuple:
    """
    機能: 現在までの清算だけで高水準と保護線を更新し、独立に初先着を探す。
    引数: curve/normal(ndarray)、start(int)、閾値(float/None)は人工清算と固定線。
    返り値: tupleは行・理由・途中4曲線。事後max又は将来suffixを使わない。
    """
    peak=0.;armed=False;line=np.nan;decision=-1;reason=0;trace=[]
    for row,value in enumerate(curve):
        if row>=start and normal[row] and decision<0:
            peak=max(peak,value)
            if loss is not None and value<=-loss:decision=row;reason=1
            elif target is not None and value>=target:decision=row;reason=2
            else:
                armed=armed or value>=arm
                if armed:
                    line=max(floor,peak-draw) if np.isnan(line) else max(line,floor,peak-draw)
                    if value<=line:decision=row;reason=3
        trace.append([peak,int(armed),line,reason])
    return decision,reason,np.asarray(trace,float)


def close_oracle(ctx: dict, decision: int) -> tuple:
    """
    機能: 判断までの注文と残UIDだけから次正常返済を独立に構成する。
    引数: ctx(dict)、decision(int)は人工共通文脈と判断行。-1は発動無し。
    返り値: tupleは注文・UID・対象UID・未観測予約。未来の親返済テンプレートを使わない。
    """
    original=ctx['values'][0];uids=ctx['values'][5]
    if decision<0:return original.copy(),uids.copy(),np.full(len(uids),-1,np.int64),False
    keep=original[:,0]<=decision;orders=original[keep].copy();ids=uids[keep].copy()
    _,state=book(orders,ids,ctx['quotes'],ctx['key'][1]);remaining=[s for s in state.values() if s['remaining']]
    targets=[-1]*len(orders);future=np.flatnonzero(ctx['normal'][decision+1:])
    if remaining and not len(future):return orders,ids,np.asarray(targets,np.int64),True
    if remaining:
        fill=decision+1+int(future[0]);extra=[]
        for item in remaining:
            side=-item['side'];price=ctx['quotes']['ask' if side==1 else 'bid'][fill]
            extra.append([fill,decision,item['cid'],side,item['remaining'],price,96,0]);targets.append(item['uid'])
        orders=np.concatenate((orders,np.asarray(extra,float)));ids=np.concatenate((ids,np.full(len(extra),-1,np.int64)))
    return orders,ids,np.asarray(targets,np.int64),False


# ----------------------------------------
def main() -> None:
    """
    機能: 8源固定後の逐次保護・実料・partial・取消・前親益・接頭予約を独立人工で確認する。
    引数: なし。正式16条件は別の固定後に監査する。
    返り値: Noneは自所有準備証跡。金融結果・packet・台帳・APIは読まない。
    """
    owner=SOURCE/'汎用出口の基準同値と因果保全及び実UID接頭の人工検査_v2.json'
    raw=owner.read_bytes();proof=json.loads(raw.decode('utf-8'));sources=proof['source_SHA256']
    assert proof['全合格'] and len(sources)==8
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==sha for p,sha in sources.items())
    scope=HERE/'汎用出口8源の独立人工範囲固定_v2.json';target_path=HERE/'汎用出口の逐次保護と実料接頭及び未来suffixの独立人工_v2.json'
    assert not scope.exists() and not target_path.exists()
    scope.write_text(json.dumps(dict(source_SHA256=sources,市場資料=0,金融=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    cases=0;arrays=0;prefixes=0;findings=[]
    for symbol in ('TOPIX','NK225'):
        for side in (1,-1):
            for canceled,missing in ((False,False),(True,False),(False,True)):
                account,one,two=fixture(symbol,side,canceled,missing)
                ctx=context.prepare(account,one,two);expected_curve,state=book(ctx['values'][0],ctx['values'][5],ctx['quotes'],symbol)
                for index,name in ((0,'cumulative_fees'),(1,'reserved_exit_fees'),(2,'equity_yen'),(3,'liquidation_yen')):
                    np.testing.assert_allclose(ctx['base'][name],expected_curve[:,index],rtol=1e-12,atol=1e-6);arrays+=1
                assert ctx['anchor']['row']==2 and ctx['anchor']['quantity']==(2 if symbol=='TOPIX' else 3)
                if canceled:assert ctx['values'][0][0,2]==1 and ctx['anchor']['parent']==0
                for arm,draw,hard,target in ((100.,300.,5000.,None),(400.,800.,5000.,None),(100.,300.,5000.,600.),(1500.,700.,400.,None)):
                    decision,reason,trace=scan_oracle(expected_curve[:,3],ctx['normal'],2,arm,draw,0.,hard,target)
                    got=exit_policy.protection(ctx,arm,draw,0.,hard,target,python=True)
                    assert got['row']==(None if decision<0 else decision) and got['reason']==(None if not reason else reason)
                    np.testing.assert_array_equal(got['trace'],trace);arrays+=1
                    native=exit_policy.protection(ctx,arm,draw,0.,hard,target)
                    np.testing.assert_array_equal(native['trace'],trace);arrays+=1
                    assert native['row']==got['row'] and native['reason']==got['reason']
                    out=exit_policy.close_prefix(ctx,got);orders,uids,targets,pending=close_oracle(ctx,decision)
                    assert not pending
                    for field,expect in (('orders',orders),('order_uids',uids),('exit_target_uids',targets)):
                        np.testing.assert_array_equal(out[field],expect);arrays+=1
                    closed_curve,_=book(orders,uids,ctx['quotes'],symbol)
                    for index,name in ((0,'cumulative_fees'),(1,'reserved_exit_fees'),(2,'equity_yen'),(3,'liquidation_yen')):
                        np.testing.assert_allclose(out[name],closed_curve[:,index],rtol=1e-12,atol=1e-6);arrays+=1
                    assert out['summary']['費用']==sum(fee(int(o[4]),symbol) for o in orders)
                    if decision>=0:assert not np.any(orders[(orders[:,0]>decision)&(orders[:,7]==1)])
                    for cut in (2,3,4,6,7,9,11,13,16):
                        a,b,c=fixture(symbol,side,canceled,missing,cut);past=context.prepare(a,b,c,finish=False)
                        short=exit_policy.protection(past,arm,draw,0.,hard,target,python=True)
                        if past['anchor'] is None:assert short['row'] is None and short['trace'] is None;continue
                        np.testing.assert_array_equal(short['trace'],trace[:cut]);arrays+=1
                        assert short['row']==(decision if 0<=decision<cut else None)
                        current=exit_policy.close_prefix(past,short)
                        expected_orders,expected_uids,expected_targets,reserved=close_oracle(past,-1 if short['row'] is None else short['row'])
                        for field,expect in (('orders',expected_orders),('order_uids',expected_uids),('exit_target_uids',expected_targets)):
                            np.testing.assert_array_equal(current[field],expect);arrays+=1
                        assert not current['summary']['全会計合格']
                        if short['row'] is not None:assert current['control']['返済予約']==reserved
                        # fullの未来清算だけを大きく改変する部品ストレス。前方traceは不変。
                        altered=copy.deepcopy(ctx)
                        altered['base']['liquidation_yen'][cut:]=1000000.+np.arange(18-cut)
                        repeated=exit_policy.protection(altered,arm,draw,0.,hard,target,python=True)
                        np.testing.assert_array_equal(repeated['trace'][:cut],short['trace']);arrays+=1;prefixes+=1
                    cases+=1
                if not canceled:
                    assert ctx['base']['liquidation_yen'][9]>0
                    assert ctx['base']['liquidation_yen'][10]<ctx['base']['liquidation_yen'][9]
                    findings.append(dict(商品=symbol,方向=side,前親返済後清算=ctx['base']['liquidation_yen'][9],
                        次親新規spread料後清算=ctx['base']['liquidation_yen'][10],partial料金=sum(fee(int(o[4]),symbol) for o in ctx['values'][0] if o[2]==0)))
    # 未来正常quoteが未観測なら残UID予約のまま。先着を後の大peakで選び直さない。
    curve=np.array([0,0,500,450,100,5000],float);normal=np.ones(6,bool)
    decision,reason,trace=exit_core.scan.py_func(curve,normal,0,200.,300.,0.,5000.,np.nan)
    assert decision==4 and reason==3 and trace[5,0]==500 and trace[5,2]==200
    altered=curve.copy();altered[5]=-50000
    _,_,changed=exit_core.scan.py_func(altered,normal,0,200.,300.,0.,5000.,np.nan)
    np.testing.assert_array_equal(trace,changed);arrays+=1
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==sha for p,sha in sources.items())
    result=dict(全合格=True,source_SHA256=sources,所有人工v2_SHA256=hashlib.sha256(raw).hexdigest(),
        独立source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),人工条件=cases,配列照合=arrays,接頭=prefixes,
        前親実現と次親費用の人工例=findings,
        v1確認範囲の訂正='v1は接頭複写を将来変更と呼ぶコメントが不適切だった。v1源・green証跡は保持。v2でfull清算suffixを100万円へ実際に変更した部品ストレスを追加。汎用8源変更0。',
        留保=['汎用出口8源だけの準備人工。正式16条件・入口mask・二市場時計資格・金融結果は別途監査する。',
              '保護floor0は判断時の線で、次正常気配の返済収支0を保証しない。',
              '初回受理取消後の初期尺度保持を確認。実fill数量へ選び直さない。'],
        正式金融=0,正式結果=0,原板=0,NPZ=0,packet=0,ledger=0,API=0,旧source及び旧JIT変更=0)
    target_path.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,条件=cases,配列=arrays,接頭=prefixes,SHA256=hashlib.sha256(target_path.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':main()
