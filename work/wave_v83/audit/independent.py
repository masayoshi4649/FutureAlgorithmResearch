"""保存約定だけから現金・両側建玉・親組を組み直す独立会計。"""

from collections import Counter
import hashlib
import numpy as np


def near(a, b, label: str) -> None:
    """機能: 円未満の浮動小数誤差だけを許して比較する。

    引数: a/b(数値又は配列)、label(str)。返り値: なし(None)。
    """
    if np.isscalar(a) and np.isscalar(b):assert abs(a-b)<1e-4,(label,a,b)
    else:np.testing.assert_allclose(a,b,rtol=0,atol=1e-5,err_msg=label)


def ratios(row: dict) -> dict:
    """機能: 決済脚と全玉終了組について、同一商品内の比率を計算する。

    引数: row(dict)。返り値: 比率を付加した会計(dict)。
    """
    for prefix,count in [('', 'trades'),('cycle_','cycles')]:
        p,l,n,w,b=row[prefix+'profit'],row[prefix+'loss'],row[count],row[prefix+'wins'],row[prefix+'losses']
        row.update({prefix+'profit_share':p/(p+l) if p+l else None,
                    prefix+'profit_loss_ratio':p/l if l else None,
                    prefix+'win_rate':w/n if n else None,
                    prefix+'average_win':p/w if w else None,
                    prefix+'average_loss':l/b if b else None,
                    prefix+'payoff':p*b/(l*w) if l and w and b else None,
                    prefix+'average_net':row[prefix+'net']/n if n else None})
    row['average_hold_seconds']=row['hold_seconds']/row['trades'] if row['trades'] else None
    row['cycle_average_hold_seconds']=row['cycle_hold_seconds']/row['cycles'] if row['cycles'] else None
    row['average_order_wait_seconds']=row['order_wait_seconds']/row['orders'] if row['orders'] else None
    return row


def account(key: tuple, record: tuple, saved: dict, run: dict, fee_override=None) -> tuple:
    """機能: 全約定から独立台帳と各行清算時価を作り、保存値を検算する。

    引数: key(tuple)、record(tuple)、saved(dict)、run(dict)、fee_override(None|float)。返り値: 会計・時価(tuple)。
    未保存の予約イベントの最大値は出力統計から引き継ぎ、最終代表の別監査で確認する。
    """
    t,p,bid,ask,seq,source,pok,qok,tick,start,end,limit=record
    symbol=key[1];cap,value=(10,1000.) if symbol=='TOPIX' else (20,10.)
    orders=saved['orders'];stored=saved['trades'];stats=saved['stats'];n=len(t)
    assert orders.shape[1]==16 and stored.shape[1]==14 and stats.shape==(14,)
    assert not np.any(stats[4:8]) and max(stats[:4])<=cap
    delay=float(run['delay']);slip=float(run['slip_ticks'])
    rows=orders[:,0].astype(np.int64);decision=orders[:,1].astype(np.int64)
    assert np.all(rows>=decision) and np.all(np.diff(rows)>=0) and np.all(decision>=0)
    if delay>0:assert np.all(rows>decision)
    np.testing.assert_array_equal(orders[:,11],t[rows])
    np.testing.assert_array_equal(orders[:,10],orders[:,9]+delay)
    assert np.all(orders[:,11]>=orders[:,10]) and np.all(qok[rows])
    expected_price=np.where(orders[:,3]==1,ask[rows]+slip*tick,bid[rows]-slip*tick)
    persistent=(orders[:,6]==1)&(orders[:,15]==2)
    assert np.all(orders[persistent,3]*(expected_price[persistent]-orders[persistent,13])<=0)
    expected_price[persistent]=orders[persistent,13]
    near(orders[:,5],expected_price,'売買側約定')
    quantities=orders[:,4].astype(np.int64)
    charge=quantities*418//10 if symbol=='TOPIX' else quantities*11
    if fee_override is not None:
        assert fee_override==0.,'理論対照だけ料金0を許可する'
        charge=np.zeros(len(quantities),dtype=np.int64)
    np.testing.assert_array_equal(orders[:,8],charge)
    timed=orders[:,9]!=t[decision]
    assert np.all(orders[timed,7]==6) and np.all(orders[timed,6]==0)
    assert np.all(orders[timed,9]==limit-60.)
    assert np.all(t[decision[timed]]<orders[timed,9])
    assert np.all(t[decision[timed]+1]>=orders[timed,9])
    # ----------------------------------------
    # 各玉をticketで照合し、損益や親組を保存計算の値から借りない。
    live={};rebuilt=[];cycles={};validrows=np.flatnonzero(qok);validtimes=t[validrows]
    for o in orders:
        ticket=int(o[2]);i=int(o[0]);d=int(o[1]);side=int(o[3]);qty=int(o[4]);cy=int(o[14])
        earliest=max(int(np.searchsorted(validtimes,o[10],side='left')),
                     int(np.searchsorted(validrows,d+(1 if delay>0 else 0),side='left')))
        if o[6] and o[15]==2:
            candidates=validrows[earliest:int(np.searchsorted(validrows,i,side='right'))]
            eligible=candidates[(ask[candidates]+slip*tick<=o[13]) if side==1 else (bid[candidates]-slip*tick>=o[13])]
            assert len(eligible) and eligible[0]==i and t[i]<limit-120.
        else:
            assert earliest<len(validrows) and validrows[earliest]==i
        if o[6]:
            assert ticket not in live and o[9]<limit-120.
            if o[15]:assert side*(o[5]-o[13])<=1e-8
            live[ticket]=o
        else:
            entry=live.pop(ticket)
            assert side==-entry[3] and qty==entry[4] and cy==entry[14]
            gross=entry[3]*qty*(o[5]-entry[5])*value
            fee=entry[8]+o[8];net=gross-fee
            rebuilt.append([ticket,entry[0],i,entry[3],qty,entry[5],o[5],entry[8],o[8],gross,net,entry[7],o[7],cy])
            if cy not in cycles:cycles[cy]=[cy,int(entry[0]),i,0,0.,0.,0.,0.]
            c=cycles[cy];c[1]=min(c[1],int(entry[0]));c[2]=max(c[2],i);c[3]+=1
            c[4]+=gross;c[5]+=fee;c[6]+=net;c[7]+=qty
    assert not live
    trades=np.asarray(rebuilt,dtype=float).reshape(-1,14)
    cyclearray=np.asarray([cycles[c] for c in sorted(cycles)],dtype=float).reshape(-1,8)
    near(trades,stored,'独立決済脚台帳');near(cyclearray,saved['cycles'],'独立全玉終了組台帳')
    # ----------------------------------------
    # 現金、両方向数量、各脚の返済料金を差分加算して全原板に展開する。
    opening=np.where(orders[:,6]==1,1.,-1.)
    heldside=orders[:,3]*opening
    dl=np.where(heldside==1,opening*quantities,0.)
    ds=np.where(heldside==-1,opening*quantities,0.)
    long_orders=np.cumsum(dl);short_orders=np.cumsum(ds)
    for balance in [long_orders,short_orders]:
        assert balance.min(initial=0)>=0 and balance.max(initial=0)<=cap
        assert not len(balance) or balance[-1]==0
    cashdelta=np.bincount(rows,weights=-orders[:,3]*quantities*orders[:,5]*value-charge,minlength=n)
    longs=np.cumsum(np.bincount(rows,weights=dl,minlength=n))
    shorts=np.cumsum(np.bincount(rows,weights=ds,minlength=n))
    repayfee=np.cumsum(np.bincount(rows,weights=charge*opening,minlength=n))
    lastrow=np.maximum.accumulate(np.where(qok,np.arange(n),-1))
    lastbid=np.r_[0.,bid][lastrow+1];lastask=np.r_[0.,ask][lastrow+1]
    equity=np.cumsum(cashdelta)+longs*(lastbid-slip*tick)*value-shorts*(lastask+slip*tick)*value-repayfee
    assert np.isfinite(equity).all()
    assert hashlib.sha256(equity.tobytes()).hexdigest()==saved['curve_hash'],'全行清算時価SHA不一致'
    maxlong=int(long_orders.max(initial=0));maxshort=int(short_orders.max(initial=0))
    maxgross=int((long_orders+short_orders).max(initial=0));maxnet=int(np.abs(long_orders-short_orders).max(initial=0))
    np.testing.assert_array_equal(stats[[0,1,9,10,11]],
        [maxlong,maxshort,int(np.sum(orders[:,6]==1)),len(trades),maxgross])
    net=trades[:,10];cnet=cyclearray[:,6];total=float(net.sum());fees=int(charge.sum())
    near(total,equity[-1],'終端全清算時価');near(total,float(cnet.sum()),'親組収支一致')
    mids=(bid+ask)/2.
    midpoint=float(np.sum(trades[:,3]*trades[:,4]*value*(mids[trades[:,2].astype(int)]-mids[trades[:,1].astype(int)])))
    spread=float(np.sum(orders[:,3]*(orders[:,5]-mids[rows])*quantities*value))
    near(midpoint-spread-fees,total,'中値と費用分解')
    samequote=np.where(orders[:,3]==1,ask[decision],bid[decision])
    lag=float(np.sum(orders[:,3]*(orders[:,5]-samequote)*quantities*value))
    waits=orders[:,11]-orders[:,9]
    peaks=np.maximum.accumulate(np.r_[0.,equity])[1:]
    result=dict(session=key[0],symbol=symbol,profit=float(net[net>0].sum()),loss=float(-net[net<0].sum()),
        net=total,gross=float(trades[:,9].sum()),fees=fees,midpoint_gross=midpoint,spread_drag=spread,decision_to_fill_cost=lag,
        trades=len(trades),wins=int(np.sum(net>0)),losses=int(np.sum(net<0)),flats=int(np.sum(net==0)),
        winning_lots=int(trades[net>0,4].sum()),losing_lots=int(trades[net<0,4].sum()),flat_lots=int(trades[net==0,4].sum()),
        cycle_profit=float(cnet[cnet>0].sum()),cycle_loss=float(-cnet[cnet<0].sum()),cycle_net=total,
        cycles=len(cnet),cycle_wins=int(np.sum(cnet>0)),cycle_losses=int(np.sum(cnet<0)),cycle_flats=int(np.sum(cnet==0)),
        hold_seconds=float(np.sum(t[trades[:,2].astype(int)]-t[trades[:,1].astype(int)])),
        cycle_hold_seconds=float(np.sum(t[cyclearray[:,2].astype(int)]-t[cyclearray[:,1].astype(int)])),
        drawdown=float(np.max(peaks-equity)),curve_min=min(0.,float(equity.min())),curve_max=max(0.,float(equity.max())),
        max_trade_loss=max(0.,-float(net.min(initial=0))),max_cycle_loss=max(0.,-float(cnet.min(initial=0))),
        max_long=maxlong,max_short=maxshort,max_reserved_long=int(stats[2]),max_reserved_short=int(stats[3]),
        max_gross_lots=maxgross,max_gross=maxgross,max_net=maxnet,cancellations=int(stats[8]),
        basket_stops=int(stats[12]),ties=int(stats[13]),orders=len(orders),entry_orders=int(np.sum(orders[:,6]==1)),
        exit_orders=int(np.sum(orders[:,6]==0)),order_wait_seconds=float(waits.sum()),max_order_wait_seconds=float(waits.max(initial=0)),
        reasons={str(k):v for k,v in sorted(Counter(orders[:,7].astype(int)).items())})
    return ratios(result),equity


def compare(actual: dict, expected: dict) -> int:
    """機能: 数字・欠損・理由別件数を公開予定の会計へ照合する。

    引数: actual/expected(dict)。返り値: 照合項目数(int)。
    """
    assert set(actual)==set(expected),(set(actual)-set(expected),set(expected)-set(actual))
    for name,a in actual.items():
        b=expected[name]
        if isinstance(a,(int,float,np.number)) and isinstance(b,(int,float,np.number)):near(a,b,name)
        else:assert a==b,(name,a,b)
    return len(actual)


def aggregate(rows: list, symbol: str, sessions: list) -> dict:
    """機能: 独立再計算した場会計から期間損益と連続DDを求める。

    引数: rows(list)、symbol(str)、sessions(list)。返り値: 期間会計(dict)。
    """
    bykey={r['session']:r for r in rows if r['symbol']==symbol}
    chosen=[bykey[s] for s in sessions if s in bykey]
    sums=['profit','loss','net','gross','fees','midpoint_gross','spread_drag','decision_to_fill_cost',
        'cycle_profit','cycle_loss','cycle_net','hold_seconds','cycle_hold_seconds','order_wait_seconds',
        'trades','wins','losses','flats','winning_lots','losing_lots','flat_lots','cycles','cycle_wins','cycle_losses','cycle_flats',
        'orders','entry_orders','exit_orders','cancellations','basket_stops','ties']
    maxima=['max_trade_loss','max_cycle_loss','max_long','max_short','max_reserved_long','max_reserved_short',
        'max_gross_lots','max_gross','max_net','max_order_wait_seconds']
    result={name:sum(r[name] for r in chosen) for name in sums}
    result.update({name:max([0]+[r[name] for r in chosen]) for name in maxima})
    nets=[r['net'] for r in chosen];active=sum(r['trades']>0 for r in chosen)
    result.update(sessions=len(chosen),active_sessions=active,winning_sessions=sum(v>0 for v in nets),
        losing_sessions=sum(v<0 for v in nets),no_trade_sessions=sum(r['trades']==0 for r in chosen),
        traded_flat_sessions=sum(r['trades']>0 and r['net']==0 for r in chosen),
        best_session=max(nets) if nets else 0.,worst_session=min(nets) if nets else 0.)
    result['losing_session_share']=result['losing_sessions']/active if active else None
    result['without_best_session']=result['net']-result['best_session']
    balance=high=drawdown=0.
    for row in chosen:
        drawdown=max(drawdown,row['drawdown'],high-(balance+row['curve_min']))
        high=max(high,balance+row['curve_max']);balance+=row['net']
    result['drawdown']=drawdown
    reason=Counter()
    for row in chosen:reason.update(row['reasons'])
    result['reasons']=dict(sorted(reason.items()))
    return ratios(result)
