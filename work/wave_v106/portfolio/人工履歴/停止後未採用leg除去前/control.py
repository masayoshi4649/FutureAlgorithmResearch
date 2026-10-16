"""実腿の当時合算時価で、複数親を次正常気配へ全返済予約する。"""

from copy import deepcopy
import math

import numpy as np


def valid_rows(record: dict) -> np.ndarray:
    """
    機能: 元106と同じ正常清算気配だけを選ぶ。
    引数: record(dict)は正常原行の保存列。
    返り値: ndarray[bool]は時刻/BBO/quote_validの全資格。入口qualityとは分離する。
    """
    return (record['quote_valid'] & np.isfinite(record['time_s']) & np.isfinite(record['bid']) &
        np.isfinite(record['ask']) & (record['bid']>0) & (record['ask']>record['bid']))


def economic_path(record: dict, orders: np.ndarray) -> tuple[np.ndarray,np.ndarray]:
    """
    機能: 全物理注文から現金・方向別保有・腿別返済料を独立に積み上げる。
    引数: record(dict)、orders(ndarray[float64,17列])は同原行の価格と実注文。
    返り値: tuple[ndarray,ndarray]は全行清算時価と6列保有。両建てをnet相殺しない。
    """
    n=len(record['seq']);cap=10 if record['symbol']=='TOPIX' else 20
    multiplier,fee_unit=(1000.,41.8) if record['symbol']=='TOPIX' else (10.,11.)
    qok=valid_rows(record);normal=np.flatnonzero(qok)
    cash_change=np.zeros(n);long_change=np.zeros(n);short_change=np.zeros(n);fee_change=np.zeros(n)
    for order in orders:
        row,decision,side,q=int(order[0]),int(order[1]),int(order[4]),int(order[5])
        assert 0<=decision<row<n and qok[row] and 0<q<=cap
        after=normal[np.searchsorted(normal,decision,side='right'):]
        if not order[7]:after=after[record['time_s'][after]>=order[10]]
        assert len(after) and after[0]==row
        price=record['ask'][row] if side==1 else record['bid'][row]
        assert order[6]==price and order[9]==math.floor(q*fee_unit+1e-8)
        cash_change[row]-=side*q*price*multiplier+order[9]
        delta=q if order[7] else -q
        (long_change if order[15]==1 else short_change)[row]+=delta
        fee_change[row]+=order[9] if order[7] else -order[9]
    longs,shorts=np.cumsum(long_change),np.cumsum(short_change)
    assert np.all((longs>=0)&(shorts>=0)&(longs<=cap)&(shorts<=cap))
    future_fee=np.cumsum(fee_change);assert future_fee.min(initial=0)>=-1e-8
    latest=np.maximum.accumulate(np.where(qok,np.arange(n),-1));held=(longs+shorts)>0
    assert np.all(latest[held]>=0)
    curve=np.cumsum(cash_change);p=latest[held]
    curve[held]+=(longs[held]*record['bid'][p]-shorts[held]*record['ask'][p])*multiplier
    curve-=future_fee
    trace=np.column_stack((longs,shorts,longs,shorts,np.zeros(n),np.zeros(n))).astype(np.int32)
    return curve,trace


def simulate(record: dict, baseline: dict, goal: float | None, loss: float | None,
             finish: bool=True) -> dict:
    """
    機能: 当時閾値への最初の到達以後だけ、全親返済と新規停止へ置き換える。
    引数: record/baseline(dict)、goal/loss(float|None)は円額、finish(bool)は完全入力の要求。
    返り値: dictは同旧出力契約と停止記録。保有接頭に未来清算は足さない。
    """
    n=len(record['seq']);assert baseline['curve'].shape==(n,)
    assert (goal is None or goal>0) and (loss is None or loss>0)
    if finish:assert n and record['time_s'][-1]>=record['limit']
    qok=valid_rows(record)
    hits=qok & ((baseline['curve']>=goal) if goal is not None else False)
    if loss is not None:hits|=qok & (baseline['curve']<=-loss)
    candidate=np.flatnonzero(hits)
    if not len(candidate):
        result=dict(baseline,stopped=False,stop_reason='未到達',decision_row=None,fill_row=None,goal=goal,loss=loss)
        if finish:assert not result['target_trace'][-1].any()
        return result
    decision=int(candidate[0]);reason=90 if goal is not None and baseline['curve'][decision]>=goal else 91
    orders=baseline['orders'][baseline['orders'][:,0]<=decision].copy()
    trades=baseline['trades'][baseline['trades'][:,3]<=decision].copy()
    cohorts=baseline['growth_cohorts'][baseline['growth_cohorts'][:,14]<=decision].copy()
    entries=orders[orders[:,7]==1];closed=set(trades[:,0]);opens=entries[~np.isin(entries[:,2],list(closed))]
    assert len(set(opens[:,2]))==len(opens),'増玉なしの実腿だけを対象とする'
    future=np.flatnonzero(qok & (np.arange(n)>decision));fill=int(future[0]) if len(future) and len(opens) else None
    multiplier=1000. if record['symbol']=='TOPIX' else 10.
    uid=int(orders[:,16].max(initial=0))
    if fill is not None:
        for entry in opens:
            parent,source,side,q=int(entry[2]),int(entry[3]),int(entry[4]),int(entry[5])
            price=float(record['bid'][fill] if side==1 else record['ask'][fill]);fee=entry[9]
            uid+=1;exit_order=entry.copy()
            exit_order[[0,1,4,6,7,8,10,11,12,14,16]]=[fill,decision,-side,price,0,reason,
                record['time_s'][decision],record['time_s'][fill],0,reason,uid]
            orders=np.vstack((orders,exit_order));gross=side*q*(price-entry[6])*multiplier
            trade=np.array([parent,source,entry[0],fill,side,q,entry[6],price,fee,fee,gross,gross-2*fee,
                entry[8],reason,entry[13],entry[1]],float)
            trades=np.vstack((trades,trade))
            # ----------------------------------------
            # 当時新規の事実だけから玉を作り、未来の元決済行をテンプレートにしない。
            initial_width=float(baseline.get('initial_width',0.))
            cohort=np.array([parent,parent,source,side,q,entry[1],record['seq'][int(entry[1])],entry[10],
                entry[0],record['seq'][int(entry[0])],entry[11],entry[6],fee,entry[16],fill,
                record['seq'][fill],record['time_s'][fill],price,fee,gross,gross-2*fee,
                initial_width*q*multiplier,q,entry[8],q],float)
            cohorts=np.vstack((cohorts,cohort))
    elif finish and len(opens):
        raise AssertionError('停止判断後の次正常気配がない。架空清算はしない')
    curve,trace=economic_path(record,orders)
    np.testing.assert_allclose(curve[:decision+1],baseline['curve'][:decision+1],rtol=0,atol=1e-4)
    trace[:decision]=baseline['target_trace'][:decision]
    last=n if fill is None else fill
    if len(opens):trace[decision:last,5]=trace[decision:last,:2].sum(axis=1)
    events=baseline['events'][baseline['events'][:,0]<=decision].copy()
    added=[]
    for entry in opens:
        added.append([decision,entry[2],entry[3],2,entry[4],entry[5],decision,0,0,record['time_s'][decision],entry[13],reason])
        if fill is not None:added.append([fill,entry[2],entry[3],5,entry[4],entry[5],decision,0,0,record['time_s'][decision],entry[13],reason])
    for family,qty in enumerate(baseline.get('allocations',(baseline.get('quantity',0),))):
        legs=baseline.get('legs',{})
        leg=legs.get('C' if family==0 else 'R')
        pending=int(leg['target_trace'][decision,4]) if leg is not None else int(baseline['target_trace'][decision,4])
        if pending:added.append([decision,0,family,6,0,pending,decision,0,0,record['time_s'][decision],0,reason])
    if added:events=np.vstack((events,np.asarray(added,float)))
    result=dict(baseline,orders=orders,trades=trades,growth_cohorts=cohorts,curve=curve,target_trace=trace,
        events=events,stopped=True,stop_reason='利益目標' if reason==90 else '損失予算',
        decision_row=decision,decision_seq=int(record['seq'][decision]),decision_time=float(record['time_s'][decision]),
        decision_equity=float(baseline['curve'][decision]),fill_row=fill,goal=goal,loss=loss,
        open_parent_count_at_stop=len(opens),cancelled_pending_entry=int(baseline['target_trace'][decision,4]),
        pending_liquidation=bool(len(opens) and fill is None),
        stop_note='全腿の同原行清算時価で判断。新規未約定は取消、保有全親は次正常quoteへ全量返済。')
    sources=[]
    for source in (0,1):
        sources.append(economic_path(record,orders[orders[:,3]==source])[0])
    result['source_curve']=np.column_stack(sources)
    for field in ('judgments','candidate_controls','candidate_integer_keys','candidate_diagnostics','control_judgments',
                  'control_events','control_integer_events'):
        if field in result:result[field]=result[field][result[field][:,0]<=decision].copy()
    stats=np.zeros(16);stats[:4]=trace[:,:4].max(axis=0,initial=0)
    if n:stats[4:8]=trace[-1,[0,1,4,5]]
    stats[8]=(trace[:,0]+trace[:,1]).max(initial=0);stats[15]=float(trades[:,11].sum())
    result['stats']=stats
    result['raw_entry_diagnostics']=[d for d in baseline['raw_entry_diagnostics'] if d['fill_row']<=decision]
    if finish:assert not trace[-1].any()
    return result


def trade_map(output: dict, record: dict) -> dict:
    """
    機能: 異なる腿の同時入口も区別して寄与を比較する。
    引数: output/record(dict)は台帳と正常原行。
    返り値: dictはsource/入口原seq/方向を鍵にした経済。親ID変化に依存しない。
    """
    result={}
    for trade in output['trades']:
        decision,side,source=int(trade[15]),int(trade[4]),int(trade[1])
        key=f'{source}|{int(record["seq"][decision])}|{side}';assert key not in result
        result[key]=dict(net=float(trade[11]),entry_row=int(trade[2]),quantity=int(trade[5]),entry_price=float(trade[6]))
    return result
