"""実注文・源別親・全原板清算時価を、三つの別会計で照合する。"""

import numpy as np

MULTIPLIERS = dict(TOPIX=1000., NK225=10.)
FEES = dict(TOPIX=41.8, NK225=11.)
SOURCES = ('GU', 'M3', 'C03')


def account(ready, result):
    """
    機能: 全実注文へ料金を課し、源と親を維持して利益損失を集計する。
    引数: ready(dict)、result(dict:共通実行結果)。
    返り値: tuple[dict,dict,ndarray,ndarray]。場集計・台帳・料金後時価・源別時価。
    """
    symbol = ready['symbol']
    value, fee = MULTIPLIERS[symbol], FEES[symbol]
    orders = result['orders']
    charges = np.floor(orders[:, 5]*fee+1e-8)
    cash = np.zeros((len(ready['last']), 3))
    delta = np.zeros_like(cash)
    entries, remaining, parents, legs = {}, {}, {}, []
    ordered_position = np.zeros(3)
    ordered_max_long = ordered_max_short = 0
    for order_index, (order, charge) in enumerate(zip(orders, charges)):
        row, decision, source, cid, side, qty, price, reason, new, uid = order
        row, source, cid, uid, qty = int(row), int(source), int(cid), int(uid), int(qty)
        assert price == ready['last'][row] and (decision < row or reason == 99)
        cash[row, source] -= side*qty*price*value+charge
        delta[row, source] += side*qty
        ordered_position[source] += side*qty
        ordered_max_long = max(ordered_max_long, int(np.maximum(ordered_position, 0).sum()))
        ordered_max_short = max(ordered_max_short, int(np.maximum(-ordered_position, 0).sum()))
        key = source, cid
        parent = parents.setdefault(key, dict(source=SOURCES[source], cid=cid, gross=0., fees=0., net=0., initial_qty=0, entry_row=None, exit_row=None))
        parent['fees'] += charge
        if new:
            assert uid not in entries
            entries[uid] = (source, cid, side, qty, price, charge, row)
            remaining[uid] = qty
            parent.update(initial_qty=qty, entry_row=row)
        else:
            es, ec, ed, eq, ep, ef, er = entries[uid]
            assert (es, ec, -ed) == (source, cid, side) and qty <= remaining[uid]
            remaining[uid] -= qty
            gross = ed*(price-ep)*qty*value
            allocated = ef*qty/eq+charge
            parent['gross'] += gross
            parent['exit_row'] = row
            legs.append(dict(source=SOURCES[source], cid=cid, uid=uid, side=int(ed), quantity=qty, entry_row=er, exit_row=row,
                             entry_price=float(ep), exit_price=float(price), gross=float(gross), fees=float(allocated), net=float(gross-allocated), reason=int(reason)))
    assert all(quantity == 0 for quantity in remaining.values())
    for parent in parents.values():
        parent['net'] = parent['gross']-parent['fees']
    position = np.cumsum(delta, axis=0)
    liquidation_fees = np.floor(np.abs(position)*fee+1e-8)
    source_equity = np.cumsum(cash, axis=0)+position*ready['last'][:, None]*value-liquidation_fees
    equity = source_equity.sum(axis=1)
    assert (position[-1] == 0).all()
    cap = 10 if symbol == 'TOPIX' else 20
    long = np.maximum(position, 0).sum(axis=1)
    short = np.maximum(-position, 0).sum(axis=1)
    assert long.max(initial=0) <= cap and short.max(initial=0) <= cap
    assert ordered_max_long <= cap and ordered_max_short <= cap
    nets = np.asarray([parent['net'] for parent in parents.values()])
    gross = float(sum(parent['gross'] for parent in parents.values()))
    fees = int(charges.sum())
    net = float(nets.sum())
    np.testing.assert_allclose(equity[-1], net, rtol=0, atol=1e-5)
    np.testing.assert_allclose(sum(leg['net'] for leg in legs), net, rtol=0, atol=1e-5)
    np.testing.assert_allclose(gross-fees, net, rtol=0, atol=1e-5)
    profit, loss = float(nets[nets>0].sum()), float(-nets[nets<0].sum())
    row = dict(session=ready['session'], symbol=symbol, gross=gross, fees=fees, net=net, profit=profit, loss=loss,
        profit_share=profit/(profit+loss) if profit+loss else None, campaigns=len(nets), wins=int((nets>0).sum()), losses=int((nets<0).sum()),
        new_lots=int(orders[orders[:, 8]==1, 5].sum()), closed_lots=int(orders[orders[:, 8]==0, 5].sum()),
        max_long=ordered_max_long, max_short=ordered_max_short,
        max_drawdown=float((np.maximum.accumulate(np.maximum(equity, 0))-equity).max(initial=0)),
        curve_min=float(equity.min(initial=0)), curve_max=float(equity.max(initial=0)),
        source_totals={name:dict(gross=float(sum(p['gross'] for p in parents.values() if p['source']==name)),
            fees=int(sum(p['fees'] for p in parents.values() if p['source']==name)),
            net=float(source_equity[-1, s])) for s, name in enumerate(SOURCES)})
    assert row['new_lots'] == row['closed_lots']
    changed = np.r_[True, np.any(np.diff(np.column_stack((np.cumsum(cash, axis=0), position)), axis=0)!=0, axis=1)]
    state_rows = np.flatnonzero(changed)
    ledger = dict(orders=orders, fees=charges, parents=list(parents.values()), legs=legs, target_trace=result['target_trace'], slots=result['slots'],
                  cash_position_changes=np.column_stack((state_rows, np.cumsum(cash, axis=0)[changed], position[changed])))
    return row, ledger, equity, source_equity


def aggregate(rows, continuity):
    """
    機能: 商品内だけで場集計を合算し、場内時価を繋いだ下落を計算する。
    引数: rows(list[dict])、continuity(list[tuple[最低値,最高値,場内最大下落]])。
    返り値: dict。
    """
    assert len(rows) == len(continuity)
    out = {key:sum(row[key] for row in rows) for key in ('gross','fees','net','profit','loss','campaigns','wins','losses','new_lots','closed_lots')}
    out['profit_share'] = out['profit']/(out['profit']+out['loss']) if out['profit']+out['loss'] else None
    out.update(positive_sessions=sum(row['net']>0 for row in rows), negative_sessions=sum(row['net']<0 for row in rows),
               no_trade_sessions=sum(row['campaigns']==0 for row in rows), sessions=len(rows),
               worst_session=min((row['net'] for row in rows), default=0), max_long=max((r['max_long'] for r in rows), default=0),
               max_short=max((r['max_short'] for r in rows), default=0))
    offset = peak = drawdown = 0.
    for row, (minimum, maximum, internal) in zip(rows, continuity):
        drawdown = max(drawdown, internal, peak-offset-minimum)
        peak = max(peak, offset+maximum)
        offset += row['net']
    out['max_drawdown'] = drawdown
    out['return_drawdown'] = out['net']/drawdown if drawdown else 0.
    out['best_three_removed'] = out['net']-sum(sorted([r['net'] for r in rows if r['net']>0], reverse=True)[:3])
    return out
