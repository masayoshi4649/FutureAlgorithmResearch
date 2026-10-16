"""正式取引実装を呼ばず、注文・親損益・全原板清算時価を独立に復元する。"""

import math

import numpy as np

SOURCE_NAMES = ('J2', 'O06')
MULTIPLIERS = {'TOPIX': 1000., 'NK225': 10.}
FEES = {'TOPIX': 41.8, 'NK225': 11.}


def restore(record, result, config=None):
    """
    機能: 共通17列注文台帳から源別親と行末気配清算時価を別会計で再計算する。
    引数: record(dict:最良気配・時計)、result(dict:注文17列・決済16列・清算配列)、config(dict|None)。
    返り値: dictの集計、親、決済脚、全行時価及び源別時価。利益源を相殺して親の損失を隠さない。
    """
    symbol = record['symbol']
    unit, fee_unit = MULTIPLIERS[symbol], FEES[symbol]
    cap = 10 if symbol == 'TOPIX' else 20
    n = len(record['time_s'])
    orders = np.asarray(result['orders'], float).reshape(-1, 17)
    trades = np.asarray(result['trades'], float).reshape(-1, 16)
    assert np.isfinite(orders).all() and np.isfinite(trades).all()
    assert (np.diff(orders[:, 0]) >= 0).all()
    cash_changes = np.zeros((n, 2))
    position_changes = np.zeros((n, 2))
    live, parents, legs = {}, {}, []
    intrarow_position = np.zeros(2)
    max_long = max_short = 0
    for order in orders:
        row, decision, parent_id, source, action, quantity, price, new, reason, fee, decision_time, fill_time, limit_price, cycle, method, entry_side, uid = order
        row, decision, parent_id, source, quantity, new, reason, cycle, method, uid = map(int, (row, decision, parent_id, source, quantity, new, reason, cycle, method, uid))
        action, entry_side = int(action), int(entry_side)
        assert 0 <= row < n and 0 <= source < 2 and quantity > 0
        assert action in (-1, 1) and entry_side in (-1, 1) and new in (0, 1)
        assert decision < row or reason in (99, 4), (row, decision, reason)
        assert fill_time == record['time_s'][row]
        if reason == 4 and decision_time == record['limit'] - 60.:
            assert record['time_s'][decision] < record['limit'] - 60. <= fill_time
        else:
            assert decision_time == record['time_s'][decision]
        assert fee == math.floor(quantity * fee_unit + 1e-8), (fee, quantity, fee_unit)
        assert record['quote_valid'][row]
        if method == 1:
            assert new == 1 and source == 1
            assert record['ask'][row] <= limit_price if action == 1 else record['bid'][row] >= limit_price
            expected_price = (record['ask'][row] if action == 1 else record['bid'][row]) if config and config.get('improve_limit') else limit_price
            assert price == expected_price
        else:
            assert method == 0
            expected_price = record['ask'][row] if action == 1 else record['bid'][row]
            assert price == expected_price, (price, expected_price, row, action)
        key = source, parent_id
        if new:
            assert key not in live and key not in parents
            assert action == entry_side and intrarow_position[source] == 0
            live[key] = dict(side=action, quantity=quantity, price=price, fee=fee, row=row, decision=decision,
                             cycle=cycle, entry_reason=reason, method=method)
            parents[key] = dict(parent_id=parent_id, source=source, entry_row=row, entry_decision_row=decision,
                                exit_row=None, side=action, quantity=quantity, entry_price=price, exit_price=None,
                                entry_fee=fee, exit_fee=0., gross=0., net=0., cycle=cycle, entry_reason=reason, exit_reason=None)
        else:
            state = live[key]
            assert action == -state['side'] and entry_side == state['side'] and quantity == state['quantity']
            assert cycle == state['cycle']
            gross = state['side'] * (price - state['price']) * quantity * unit
            net = gross - state['fee'] - fee
            parents[key].update(exit_row=row, exit_price=price, exit_fee=fee, gross=gross, net=net, exit_reason=reason)
            legs.append([parent_id, source, state['row'], row, state['side'], quantity, state['price'], price,
                         state['fee'], fee, gross, net, state['entry_reason'], reason, cycle, state['decision']])
            del live[key]
        cash_changes[row, source] -= action * quantity * price * unit + fee
        position_changes[row, source] += action * quantity
        intrarow_position[source] += action * quantity
        max_long = max(max_long, int(np.maximum(intrarow_position, 0).sum()))
        max_short = max(max_short, int(np.maximum(-intrarow_position, 0).sum()))
        assert max_long <= cap and max_short <= cap
    expected_trades = np.asarray(legs, float).reshape(-1, 16)
    np.testing.assert_allclose(trades, expected_trades, atol=1e-5, rtol=0)
    cash = np.cumsum(cash_changes, axis=0)
    position = np.cumsum(position_changes, axis=0)

    # ----------------------------------------
    # 含み損は全原板行で評価し、源ごとに反対玉を返す料金を残す。
    last_bid = np.full(n, np.nan)
    last_ask = last_bid.copy()
    bid_value = ask_value = 0.
    for row in range(n):
        bid, ask = record['bid'][row], record['ask'][row]
        if record['quote_valid'][row] and np.isfinite(bid) and np.isfinite(ask) and 0 < bid < ask:
            bid_value, ask_value = bid, ask
        last_bid[row], last_ask[row] = bid_value, ask_value
    liquidation_price = np.where(position >= 0, last_bid[:, None], last_ask[:, None])
    liquidation_fee = np.floor(np.abs(position) * fee_unit + 1e-8)
    source_equity = cash + position * liquidation_price * unit - liquidation_fee
    equity = source_equity.sum(axis=1)
    np.testing.assert_allclose(result['curve'], equity, atol=1e-5, rtol=0)
    np.testing.assert_allclose(result['source_curve'], source_equity, atol=1e-5, rtol=0)
    trace = np.asarray(result['target_trace'], float).reshape(n, 6)
    np.testing.assert_array_equal(trace[:, 0], np.maximum(position, 0).sum(axis=1))
    np.testing.assert_array_equal(trace[:, 1], np.maximum(-position, 0).sum(axis=1))
    assert (trace[:, 2] <= cap).all() and (trace[:, 3] <= cap).all()
    assert (trace[:, 2] >= trace[:, 0]).all() and (trace[:, 3] >= trace[:, 1]).all()
    np.testing.assert_array_equal(trace[:, 2] + trace[:, 3] - trace[:, 0] - trace[:, 1], trace[:, 4])
    assert (trace >= 0).all()

    terminal_flat = not live and (position[-1] == 0).all()
    if result.get('finish', True):
        assert terminal_flat, ('場末の残玉', live, position[-1])
    nets = np.array([parent['net'] for parent in parents.values() if parent['exit_row'] is not None])
    completed = [parent for parent in parents.values() if parent['exit_row'] is not None]
    gross = sum(parent['gross'] for parent in completed)
    charges = orders[:, 9].sum()
    if terminal_flat:
        np.testing.assert_allclose(equity[-1], nets.sum(), atol=1e-5, rtol=0)
        np.testing.assert_allclose(gross - charges, nets.sum(), atol=1e-5, rtol=0)
    profit, loss = nets[nets > 0].sum(), -nets[nets < 0].sum()
    peaks = np.maximum.accumulate(np.maximum(equity, 0))
    totals = dict(gross=gross, fees=int(charges), net=float(nets.sum()), profit=float(profit), loss=float(loss),
                  profit_share=float(profit / (profit + loss)) if profit + loss else None,
                  campaigns=len(nets), wins=int((nets > 0).sum()), losses=int((nets < 0).sum()),
                  new_lots=int(orders[orders[:, 7] == 1, 5].sum()), closed_lots=int(orders[orders[:, 7] == 0, 5].sum()),
                  max_long=max_long, max_short=max_short, max_drawdown=float((peaks - equity).max(initial=0)),
                  curve_min=float(equity.min(initial=0)), curve_max=float(equity.max(initial=0)))
    return dict(totals=totals, parents=list(parents.values()), trades=expected_trades, equity=equity,
                source_equity=source_equity, position=position, cash=cash,
                terminal_flat=bool(terminal_flat), orders=len(orders))


def aggregate(rows):
    """
    機能: 商品内の場別清算時価を順につなぎ、会計と最大下落を独立合算する。
    引数: rows(list[dict])はrestore結果。
    返り値: dictの全期間指標。
    """
    totals = {name: sum(row['totals'][name] for row in rows)
              for name in ('gross', 'fees', 'net', 'profit', 'loss', 'campaigns', 'wins', 'losses', 'new_lots', 'closed_lots')}
    offset = 0.
    curves = []
    for row in rows:
        assert row['terminal_flat']
        curves.append(offset + row['equity'])
        offset += row['totals']['net']
    curve = np.concatenate(curves) if curves else np.zeros(0)
    totals['max_drawdown'] = float((np.maximum.accumulate(np.maximum(curve, 0)) - curve).max(initial=0))
    denominator = totals['profit'] + totals['loss']
    totals['profit_share'] = totals['profit'] / denominator if denominator else None
    totals['positive_sessions'] = sum(row['totals']['net'] > 0 for row in rows)
    totals['negative_sessions'] = sum(row['totals']['net'] < 0 for row in rows)
    totals['no_trade_sessions'] = sum(row['totals']['campaigns'] == 0 for row in rows)
    totals['sessions'] = len(rows)
    totals['worst_session'] = min((row['totals']['net'] for row in rows), default=0)
    return totals
