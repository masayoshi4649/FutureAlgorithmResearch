"""追加玉の負けを相殺して隠さず、建値別金額比率と一組の勝率を区別する。"""

import numpy as np


SUM_FIELDS=('profit','loss','net','gross','fees','trades','wins','losses','flats','legs','winning_legs','losing_legs',
            'winning_lots','losing_lots','flat_lots','campaign_profit','campaign_loss','hold_seconds','adds','risk_excesses','spread_drag')


def metrics(a: dict) -> dict:
    """機能: 全建値の金額比率と全返済組の勝率を別々に計算する。

    引数: a(dict)。返り値: 指標追加済みの会計(dict)。
    """
    p,l=a['profit'],a['loss'];a['profit_share']=p/(p+l) if p+l else None
    a['money_loss_share']=l/(p+l) if p+l else None;a['profit_loss_ratio']=p/l if l else None
    a['average_win']=p/a['winning_legs'] if a['winning_legs'] else None
    a['average_loss']=l/a['losing_legs'] if a['losing_legs'] else None
    a['payoff']=a['average_win']/a['average_loss'] if a['average_win'] is not None and a['average_loss'] else None
    a['win_rate']=a['wins']/a['trades'] if a['trades'] else None
    a['average_net']=a['net']/a['trades'] if a['trades'] else None
    a['average_hold_seconds']=a['hold_seconds']/a['trades'] if a['trades'] else None
    cp,cl=a['campaign_profit'],a['campaign_loss'];a['campaign_profit_share']=cp/(cp+cl) if cp+cl else None
    a['goal80']=bool(p+l>0 and p>=4*l and p>0)
    return a


def account(key: tuple,args: tuple,out: tuple) -> dict:
    """機能: 全注文料金、建値別損益、一組の勝敗、全行清算時価を会計する。

    引数: key(tuple)、args/out(tuple)。返り値: 一場一商品会計(dict)。
    """
    orders,trades,curve,stats,risks=out
    assert stats[0]==stats[1]==stats[2]==0,'保存末尾に建玉又は未解決注文'
    t=trades;net=t[:,10];p=float(net[net>0].sum());l=float(-net[net<0].sum())
    fees=float(t[:,7:9].sum());gross=float(t[:,9].sum());total=float(net.sum())
    assert abs(fees-orders[:,8].sum())<1e-6 and abs(total-(gross-fees))<1e-5 and abs(total-curve[-1])<1e-5
    opened=orders[orders[:,7]==1];closed=orders[orders[:,7]==0]
    assert len(closed)==len(set(t[:,0])) and len(opened)==len(t)
    assert np.all(orders[:,0]>orders[:,1]) and np.all(orders[:,4]>0)
    times=args[0];cap=args[17];value=args[18]
    assert stats[3]<=cap and stats[4]<=cap
    campaigns=[];hold=0.;reasons={}
    for close in closed:
        chosen=t[t[:,0]==close[2]];campaigns.append(float(chosen[:,10].sum()))
        hold+=float(times[int(close[0])]-times[int(chosen[:,1].min())])
        r=str(int(close[6]));reasons[r]=reasons.get(r,0)+1
        assert int(chosen[:,4].sum())==int(close[4]) and abs(chosen[:,8].sum()-close[8])<1e-7
    campaigns=np.asarray(campaigns)
    peaks=np.maximum.accumulate(np.r_[0.,curve]);drawdown=float(np.max(peaks[1:]-curve))
    mid=(args[1]+args[2])/2
    spread=0.
    for o in orders:
        i=int(o[0]);spread+=float(o[3]*(o[5]-mid[i])*o[4]*value)
    a=dict(session=key[0],symbol=key[1],profit=p,loss=l,net=total,gross=gross,fees=fees,
        trades=len(campaigns),wins=int((campaigns>0).sum()),losses=int((campaigns<0).sum()),flats=int((campaigns==0).sum()),
        legs=len(t),winning_legs=int((net>0).sum()),losing_legs=int((net<0).sum()),
        winning_lots=int(t[net>0,4].sum()),losing_lots=int(t[net<0,4].sum()),flat_lots=int(t[net==0,4].sum()),
        campaign_profit=float(campaigns[campaigns>0].sum()),campaign_loss=float(-campaigns[campaigns<0].sum()),
        hold_seconds=hold,drawdown=drawdown,curve_min=min(0.,float(curve.min())),curve_max=max(0.,float(curve.max())),max_trade_loss=max(0.,-float(campaigns.min())) if len(campaigns) else 0.,
        max_leg_loss=max(0.,-float(net.min())) if len(net) else 0.,max_long=int(stats[3]),max_short=int(stats[4]),
        adds=int(stats[5]),risk_excesses=int(stats[6]),spread_drag=spread,reasons=reasons,
        active_sessions=int(len(campaigns)>0))
    return metrics(a)


def aggregate(rows: list[dict],symbol: str,sessions: list[str]) -> dict:
    """機能: 同じ商品だけを期間合計し、大勝ち一場除外後も評価する。

    引数: rows(list[dict])、symbol(str)、sessions(list[str])。返り値: 期間会計(dict)。
    """
    rs=sorted([r for r in rows if r['symbol']==symbol and r['session'] in sessions],key=lambda r:sessions.index(r['session']))
    a={k:sum(r[k] for r in rs) for k in SUM_FIELDS}
    for k in ('max_trade_loss','max_leg_loss','max_long','max_short'):a[k]=max((r[k] for r in rs),default=0.)
    a['active_sessions']=sum(r['trades']>0 for r in rs);a['winning_sessions']=sum(r['net']>0 for r in rs)
    # ----------------------------------------
    # 場ごとの独立口座清算時価を、日付順に連結した最大下落を計算する。
    balance=peak=drawdown=0.
    for r in rs:
        drawdown=max(drawdown,r['drawdown'],peak-balance-r['curve_min'])
        peak=max(peak,balance+r['curve_max'])
        balance+=r['net']
    # 既往の最高値からの下落と場内の時系列DDを別に取るため、最高値と最低値の順序を逆転しない。
    a['max_session_drawdown']=max((r['drawdown'] for r in rs),default=0.)
    a['drawdown']=drawdown
    best=max(rs,key=lambda r:r['net'],default=None)
    a['without_best_session']=a['net']-best['net'] if best else 0.
    p=a['profit']-(best['profit'] if best else 0.);l=a['loss']-(best['loss'] if best else 0.)
    a['without_best_profit_share']=p/(p+l) if p+l else None
    a['without_best_profit_loss_ratio']=p/l if l else None
    return metrics(a)
