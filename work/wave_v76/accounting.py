# 二市場検証の会計。wave74の全決済会計3関数を意味変更せず再利用する。

import math
import numpy as np
import engine


def metric(a: dict) -> dict:
    """機能: 全明細の費用後金額から損失割合と平均損益を計算する。

    引数: a(dict)。返り値: 指標を追加した同じ会計(dict)。
    """
    p, loss, count = a['profit'], a['loss'], a['trades']
    a.update(money_loss_share=loss/(p+loss) if p+loss else None,
             profit_loss_ratio=p/loss if loss else None,
             average_win=p/a['wins'] if a['wins'] else None,
             average_loss=loss/a['losses'] if a['losses'] else None,
             average_net=a['net']/count if count else None,
             win_rate=a['wins']/count if count else None,
             payoff=(p/a['wins'])/(loss/a['losses']) if a['wins'] and a['losses'] else None,
             average_hold_seconds=a['hold_seconds']/count if count else None)
    return a


def aggregate(rows: list[dict], symbol: str, sessions: list[str]) -> dict:
    """機能: 同じ銘柄の金額・枚数・休止を合算し、比率を合計金額から計算する。

    引数: rows(list[dict])、symbol(str)、sessions(list[str])。返り値: 集計(dict)。
    """
    subset = sorted((r for r in rows if r['symbol'] == symbol and r['session'] in sessions), key=lambda r:r['session'])
    fields = ('profit','loss','net','gross','fees','wins','losses','flats','trades','winning_lots','losing_lots',
              'flat_lots','pause_count','resume_count','paused_seconds','resumed_trades','resumed_net','hold_seconds','spread_drag')
    a = {k:sum(r[k] for r in subset) for k in fields}
    a.update(active_sessions=sum(r['trades'] > 0 for r in subset),positive_sessions=sum(r['net'] > 0 for r in subset),
             max_trade_loss=max((r['max_trade_loss'] for r in subset), default=0.),
             without_best_session=a['net']-max((r['net'] for r in subset), default=0.),
             max_long=max((r['max_long'] for r in subset), default=0),max_short=max((r['max_short'] for r in subset), default=0),
             missing_reference_sessions=sum(r['missing_reference'] for r in subset))
    total = peak = dd = 0.
    for r in subset:
        dd = max(dd, r['drawdown'], peak-total-r['equity_min'])
        peak = max(peak, total+r['equity_max'])
        total += r['net']
    a['drawdown'] = dd
    return metric(a)


def account(c: dict, key: tuple, args: tuple, output: tuple, missing_previous: bool) -> dict:
    """機能: 全決済損失を相殺せず集計し、休止解除後の成績も記録する。

    引数: c(dict)、key/args/output(tuple)、missing_previous(bool)。返り値: 場会計(dict)。
    """
    orders, trades, curve, pauses, stats = output
    assert stats[0] == 0 and stats[1] in (0,1), ('場末未返済',key,c['id'],stats)
    assert len(orders) == 2*len(trades)
    assert all(int(o[0]) > int(o[1]) >= 0 for o in orders)
    net = trades[:,10]
    wins, losses, flats = net > 0, net < 0, net == 0
    fees = sum(math.floor(o[4]*args[12]+1e-8) for o in orders)
    assert abs(net.sum()-curve[-1]) < 1e-4 and fees == trades[:,7:9].sum()
    starts = list(pauses[pauses[:,1] == 0,0].astype(int))
    ends = list(pauses[pauses[:,1] == 1,0].astype(int))
    times = args[0]
    paused_seconds = sum(max(0.,min(times[ends[j]],args[9]-60.)-times[i]) if j < len(ends)
                         else max(0.,args[9]-60.-times[i]) for j,i in enumerate(starts))
    resumed = set()
    for end in ends:
        candidates = np.flatnonzero(trades[:,1] > end)
        if len(candidates):
            resumed.add(int(candidates[0]))
    qty, value = args[10], args[11]
    mid = (args[1]+args[2])/2.
    ideal_gross = sum(t[3]*(mid[int(t[2])]-mid[int(t[1])])*qty*value for t in trades)
    a = dict(session=key[0],symbol=key[1],profit=float(net[wins].sum()),loss=float(-net[losses].sum()),
             net=float(net.sum()),gross=float(trades[:,9].sum()),fees=int(fees),wins=int(wins.sum()),losses=int(losses.sum()),
             flats=int(flats.sum()),trades=len(trades),winning_lots=int(trades[wins,4].sum()),
             losing_lots=int(trades[losses,4].sum()),flat_lots=int(trades[flats,4].sum()),
             max_trade_loss=float(max(0.,-net.min())) if len(net) else 0.,
             max_long=qty if np.any(trades[:,3] == 1) else 0,max_short=qty if np.any(trades[:,3] == -1) else 0,
             drawdown=float((np.maximum.accumulate(np.maximum(curve,0.))-curve).max()),
             equity_min=float(curve.min()),equity_max=float(curve.max()),
             pause_count=int(stats[5]),resume_count=int(stats[6]),paused_seconds=float(paused_seconds),
             resumed_trades=len(resumed),resumed_net=float(sum(net[j] for j in resumed)),
             hold_seconds=float(sum(times[int(t[2])]-times[int(t[1])] for t in trades)),
             width=args[13],entry_width=args[14],spread_drag=float(ideal_gross-trades[:,9].sum()),
             missing_reference=missing_previous and c['reference'] in (1,2),
             reasons={str(code):int(((orders[:,6] == code)&(orders[:,7] == 0)).sum()) for code in engine.REASONS})
    return metric(a)
