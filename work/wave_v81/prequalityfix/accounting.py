"""新規・返済の待ち時間と取消を含む秒売買を、商品内の金額で評価する。"""

import numpy as np


def metrics(a: dict) -> dict:
    """機能: 勝率と金額利益割合を分ける。

    引数: a(dict)。返り値: 比率追加済み会計(dict)。
    """
    p,l=a['profit'],a['loss'];a['profit_share']=p/(p+l) if p+l else None;a['profit_loss_ratio']=p/l if l else None
    a['win_rate']=a['wins']/a['trades'] if a['trades'] else None
    a['average_win']=p/a['wins'] if a['wins'] else None;a['average_loss']=l/a['losses'] if a['losses'] else None
    a['payoff']=a['average_win']/a['average_loss'] if a['average_win'] is not None and a['average_loss'] else None
    a['average_net']=a['net']/a['trades'] if a['trades'] else None
    a['average_hold_seconds']=a['hold_seconds']/a['trades'] if a['trades'] else None
    return a


def account(key: tuple,args: tuple,out: tuple) -> dict:
    """機能: 全決済、料金、気配差、発注遅れ、全原本の清算時価を会計する。

    引数: key(tuple)、args/out(tuple)。返り値: 一場一商品会計(dict)。
    """
    orders,trades,curve,stats,events=out
    assert np.all(stats[:4]==0),(key,'残建玉又は待機注文',stats)
    times,bid,ask=args[:3];quantity,value,fee_unit,latency=args[15:19]
    assert len(orders)==2*len(trades)
    assert len(orders)==0 or np.all((orders[:,0]>orders[:,1])&(orders[:,12]>=orders[:,11])&(orders[:,11]>=orders[:,10]+latency-1e-8))
    net=trades[:,10];gross=float(trades[:,9].sum());fees=float(orders[:,8].sum());total=float(net.sum())
    assert abs(total-(gross-fees))<1e-5 and abs(total-curve[-1])<1e-4
    assert max(stats[4:6])<=quantity
    hold=float(sum(times[int(t[2])]-times[int(t[1])] for t in trades));mid=(bid+ask)/2.
    spread=float(sum(o[3]*(o[5]-mid[int(o[0])])*o[4]*value for o in orders))
    valid=np.isfinite(bid)&np.isfinite(ask)&(bid>0)&(ask>=bid)
    known=np.maximum.accumulate(np.where(valid,np.arange(len(times)),-1))
    lagcost=0.;missing_quote=stale_quote=0
    for o in orders:
        source=int(known[int(o[1])])
        if source<0:missing_quote+=1;continue
        stale_quote+=int(source!=int(o[1]))
        quote=ask[source] if o[3]==1 else bid[source]
        lagcost+=float(o[3]*(o[5]-quote)*o[4]*value)
    peaks=np.maximum.accumulate(np.r_[0.,curve]);drawdown=float(np.max(peaks[1:]-curve))
    reasons={str(int(code)):int(np.sum(orders[:,6]==code)) for code in np.unique(orders[orders[:,7]==0,6])}
    a=dict(session=key[0],symbol=key[1],profit=float(net[net>0].sum()),loss=float(-net[net<0].sum()),net=total,gross=gross,fees=fees,
        trades=len(trades),wins=int(np.sum(net>0)),losses=int(np.sum(net<0)),flats=int(np.sum(net==0)),
        winning_lots=int(trades[net>0,4].sum()),losing_lots=int(trades[net<0,4].sum()),hold_seconds=hold,
        spread_drag=spread,decision_to_fill_cost=lagcost,max_trade_loss=max(0.,-float(net.min())) if len(net) else 0.,
        drawdown=drawdown,curve_min=min(0.,float(curve.min())),curve_max=max(0.,float(curve.max())),max_long=int(stats[4]),max_short=int(stats[5]),
        cancellations=int(stats[6]),delayed_gap_fills=int(stats[8]),reasons=reasons,entry_requests=int(np.sum(events[:,2]==20)),
        pauses=int(np.sum(events[:,2]==30)),decision_quote_missing=missing_quote,decision_quote_last_valid=stale_quote,
        average_order_wait=float(np.mean(orders[:,12]-orders[:,10])) if len(orders) else None)
    return metrics(a)


def aggregate(rows: list,symbol: str,sessions: list) -> dict:
    """機能: 同一商品だけの期間損益と安定性を集計する。

    引数: rows(list)、symbol(str)、sessions(list)。返り値: 期間会計(dict)。
    """
    rs=sorted([r for r in rows if r['symbol']==symbol and r['session'] in sessions],key=lambda r:sessions.index(r['session']))
    fields=('profit','loss','net','gross','fees','trades','wins','losses','flats','winning_lots','losing_lots','hold_seconds','spread_drag','decision_to_fill_cost','cancellations','delayed_gap_fills','entry_requests','pauses','decision_quote_missing','decision_quote_last_valid')
    a={f:sum(r[f] for r in rs) for f in fields}
    for f in ('max_trade_loss','max_long','max_short'):a[f]=max((r[f] for r in rs),default=0.)
    a['sessions']=len(rs);a['active_sessions']=sum(r['trades']>0 for r in rs);a['winning_sessions']=sum(r['net']>0 for r in rs)
    a['losing_sessions']=sum(r['net']<0 for r in rs);a['no_trade_sessions']=sum(r['trades']==0 for r in rs)
    a['worst_session']=min((r['net'] for r in rs),default=0.);a['without_best_session']=a['net']-max((r['net'] for r in rs),default=0.)
    balance=peak=drawdown=0.
    for r in rs:
        drawdown=max(drawdown,r['drawdown'],peak-balance-r['curve_min']);peak=max(peak,balance+r['curve_max']);balance+=r['net']
    a['drawdown']=drawdown
    return metrics(a)
