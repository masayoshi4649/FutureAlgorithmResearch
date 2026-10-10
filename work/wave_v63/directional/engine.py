"""有利方向の追加と日内損失予算を、気配・手数料・場内返済込みで再生する。"""

import numpy as np
from numba import njit

from fees import instrument, order_fee


REASONS = {1: '初回建値の損切り', 2: '順行後の追跡返済', 3: '初回からの保有期限',
           4: '場内返済', 5: '日内損失予算', 6: '固定回収', 7: '費用を含む建値保護'}
ORDER_COLUMNS = ('decision_time', 'fill_time', 'decision_seq', 'fill_seq', 'action', 'side', 'qty',
                 'price', 'gross', 'fee', 'net_event', 'reason', 'group_id', 'position_after', 'W', 'lot_id')
TRADE_COLUMNS = ('entry_time', 'exit_time', 'side', 'qty', 'entry_price', 'exit_price', 'gross', 'fees', 'net',
                 'reason', 'W', 'exit_decision_time', 'entry_seq', 'exit_seq', 'exit_decision_seq',
                 'mfe_W', 'mae_W', 'hold_minutes', 'entry_decision_seq', 'entry_i', 'exit_i', 'group_id',
                 'group_entry_time', 'entry_action', 'entry_fee', 'exit_fee_allocated', 'lot_id')
CANDIDATE_KEYS = ('consumed', 'scheduled', 'occupied', 'cutoff', 'cooldown', 'cancelled_at_fill', 'halted', 'unreached')


@njit(cache=True)
def fee_for(quantity: int, topix: bool) -> int:
    """機能: 各実行注文の枚数から手数料を整数計算する。

    引数: quantity(int)、topix(bool)。
    返り値: 手数料の円整数(int)。分割注文の端数を合算前に切り捨てる。
    """
    return (418 * quantity // 10) if topix else (11 * quantity)


@njit(cache=True)
def drive(times: np.ndarray, seqs: np.ndarray, mids: np.ndarray, bids: np.ndarray, asks: np.ndarray,
          signals: np.ndarray, initial_qty: int, add_qty: int, cap: int, pyramid: bool,
          value: float, topix: bool, width: float, tick: float, limit: float, holding_seconds: float,
          cooldown: float, quote_mode: bool, finish: bool, exit_mode: int) -> tuple:
    """機能: 次有効原本行だけで約定し、初回期限・共通保護線を維持して全玉返済する。

    引数: 各価格/候補(ndarray)、枚数(int)、倍率/幅/期限(float)、動作モード(bool)。
    返り値: 注文16列、入口ロット別返済27列、候補分類、停止情報(tuple)。
    初回50%の場合、上限20%の追加は残枠まで最大3回。日内予算は含み・発生費用込み。
    """
    capacity = max(1, len(signals))
    orders, trades = np.zeros((capacity * 5, 16)), np.zeros((capacity * 4, 27))
    counts = np.zeros(8, dtype=np.int64)
    no = nt = pointer = pending = side = quantity = reason = 0
    group_id = -1
    pending_side = 0
    pending_qty = 0
    cash = 0.
    halted = False
    halt_time = np.nan
    anchor = group_time = best = decision_time = decision_seq = next_entry = 0.
    next_add = 1
    # 各入口の時刻・価格・数量・費用・原本位置・高安を独立に保持する。
    lots = np.zeros((4, 10))
    lot_count = 0
    budget = 3. * width * cap * value
    for i in range(len(times)):
        now, seq, mid, bid, ask = times[i], seqs[i], mids[i], bids[i], asks[i]
        if pending == 1 or pending == 3:
            action = pending
            if now >= limit - 300.:
                if action == 1:
                    counts[5] += 1
                pending = 0
            else:
                if action == 1:
                    group_id += 1
                    side = pending_side
                    lot_count = quantity = 0
                    next_add = 1
                price = (ask if side > 0 else bid) if quote_mode else mid
                paid = fee_for(pending_qty, topix)
                liquidation = (bid if side > 0 else ask) if quote_mode else mid
                if action == 1:
                    anchor, group_time, best = price, now, liquidation
                lots[lot_count] = np.array([now, price, float(pending_qty), float(paid), float(seq),
                                            decision_seq, float(i), liquidation, liquidation, float(action)])
                quantity += pending_qty
                cash -= side * pending_qty * price * value + paid
                orders[no] = np.array([decision_time, now, decision_seq, float(seq), float(action), float(side),
                                       float(pending_qty), price, 0., float(paid), float(-paid), 0.,
                                       float(group_id), float(side * quantity), width, float(lot_count)])
                no += 1
                lot_count += 1
                if action == 3:
                    next_add += 1
                pending = 0
        elif pending == 2:
            if now >= limit + 300.:
                raise ValueError('次有効行の返済が通常監視区間終端以上です')
            price = (bid if side > 0 else ask) if quote_mode else mid
            paid, group_gross = fee_for(quantity, topix), 0.
            cash += side * quantity * price * value - paid
            for lot_id in range(lot_count):
                lot = lots[lot_id]
                lot[7] = max(lot[7], price) if side > 0 else min(lot[7], price)
                lot[8] = min(lot[8], price) if side > 0 else max(lot[8], price)
                gross = side * lot[2] * (price - lot[1]) * value
                exit_fee = paid * lot[2] / quantity
                total_fee = lot[3] + exit_fee
                group_gross += gross
                mfe, mae = max(0., side * (lot[7] - lot[1]) / width), max(0., -side * (lot[8] - lot[1]) / width)
                trades[nt] = np.array([lot[0], now, float(side), lot[2], lot[1], price, gross, total_fee,
                                       gross - total_fee, float(reason), width, decision_time, lot[4], float(seq),
                                       decision_seq, mfe, mae, (now - lot[0]) / 60., lot[5], lot[6], float(i),
                                       float(group_id), group_time, lot[9], lot[3], exit_fee, float(lot_id)])
                nt += 1
            orders[no] = np.array([decision_time, now, decision_seq, float(seq), 2., float(-side), float(quantity),
                                   price, group_gross, float(paid), group_gross - paid, float(reason),
                                   float(group_id), 0., width, -1.])
            no += 1
            pending = side = quantity = lot_count = 0
            next_entry = now + cooldown
        # ----------------------------------------
        # 注文実行後の当場全資産を計測する。初回からの期限・保護線は追加で延長しない。
        liquidation = ((bid if side > 0 else ask) if quote_mode else mid) if side else mid
        equity = cash + side * quantity * liquidation * value
        if not halted and equity <= -budget:
            halted, halt_time = True, now
        if side and pending == 0:
            best = max(best, liquidation) if side > 0 else min(best, liquidation)
            for lot_id in range(lot_count):
                lots[lot_id, 7] = max(lots[lot_id, 7], liquidation) if side > 0 else min(lots[lot_id, 7], liquidation)
                lots[lot_id, 8] = min(lots[lot_id, 8], liquidation) if side > 0 else max(lots[lot_id, 8], liquidation)
            half_width = np.ceil(.5 * width / tick - 1e-10) * tick
            stop_width = half_width if exit_mode == 2 else width
            stop = anchor - side * stop_width
            use_trail = exit_mode == 0 and side * (best - anchor) >= width
            use_protect = exit_mode == 2 and side * (best - anchor) >= half_width
            if use_trail:
                stop = best - side * width
            elif use_protect:
                roundtrip_fee = 2. * fee_for(quantity, topix)
                protected_gain = np.ceil(roundtrip_fee / (quantity * value * tick) - 1e-10) * tick
                stop = anchor + side * protected_gain
            trigger = 0
            if halted:
                trigger = 5
            elif now >= limit - 60.:
                trigger = 4
            elif side * (liquidation - stop) <= 0:
                trigger = 2 if use_trail else (7 if use_protect else 1)
            elif exit_mode > 0 and side * (liquidation - anchor) >= (half_width if exit_mode == 1 else width):
                trigger = 6
            elif now - group_time >= holding_seconds:
                trigger = 3
            if trigger:
                pending, reason, decision_time, decision_seq = 2, trigger, now, float(seq)
            elif pyramid and quantity < cap and now < limit - 300. and side * (liquidation - anchor) >= next_add * width:
                pending, pending_qty = 3, min(add_qty, cap - quantity)
                decision_time, decision_seq = now, float(seq)
        # ----------------------------------------
        # 保有中・休止中・停止後の候補を過去へ戻して再利用しない。
        while pointer < len(signals) and int(signals[pointer, 0]) <= i:
            signal = signals[pointer]
            pointer += 1
            counts[0] += 1
            if halted:
                counts[6] += 1
            elif side or pending:
                counts[2] += 1
            elif now >= limit - 300.:
                counts[3] += 1
            elif now < next_entry:
                counts[4] += 1
            else:
                counts[1] += 1
                pending, pending_side, pending_qty = 1, int(signal[1]), initial_qty
                decision_time, decision_seq = now, float(seq)
    counts[7] = len(signals) - pointer
    if finish and (side or pending):
        raise ValueError('場内返済を完了する次有効行が不足しています')
    return orders[:no], trades[:nt], counts, halted, halt_time


def equity_curve(ready: dict, quotes: dict, orders: np.ndarray, value: float, quote_mode: bool) -> tuple:
    """機能: 台帳から費用後の全行資産曲線と実建玉を独立再構成する。

    引数: ready/quotes(dict)、orders(ndarray)、value(float)、quote_mode(bool)。
    返り値: 資産曲線と符号付き枚数(tuple[np.ndarray,np.ndarray])。
    """
    cash, position = np.zeros(len(ready['seq'])), np.zeros(len(ready['seq']))
    for order in orders:
        i = int(np.searchsorted(ready['seq'], order[3]))
        d = int(np.searchsorted(ready['seq'], order[2]))
        assert i == d + 1 and ready['seq'][i] == order[3]
        cash[i] -= order[5] * order[6] * order[7] * value + order[9]
        position[i] += order[5] * order[6]
    position = np.cumsum(position)
    liquidation = np.where(position >= 0, quotes['bid'], quotes['ask']) if quote_mode else quotes['mid']
    return np.cumsum(cash) + position * liquidation * value, position


def statistics(trades: np.ndarray, curve: np.ndarray, orders: np.ndarray) -> dict:
    """機能: 各入口ロットと全玉決済組の勝敗を分け、費用・枚数・保有時間を集計する。

    引数: trades/curve/orders(np.ndarray)。
    返り値: 集計辞書(dict)。PFはロット純損益基準、組PFも別保存する。
    """
    net, gross, quantity = trades[:, 8], trades[:, 6], trades[:, 3]
    win, loss = net > 0, net < 0
    profit, damage = float(net[win].sum()), float(-net[loss].sum())
    win_qty, loss_qty = int(quantity[win].sum()), int(quantity[loss].sum())
    group_ids = np.unique(trades[:, 21])
    group_net = np.array([net[trades[:, 21] == group].sum() for group in group_ids])
    group_hold = np.array([(trades[trades[:, 21] == group, 1][0] - trades[trades[:, 21] == group, 22][0]) / 60.
                           for group in group_ids])
    peak = np.maximum.accumulate(np.r_[0., curve])[1:]
    winner, loser = profit / win_qty if win_qty else None, damage / loss_qty if loss_qty else None
    group_profit, group_loss = float(group_net[group_net > 0].sum()), float(-group_net[group_net < 0].sum())
    return dict(gross=float(gross.sum()), gross_pnl=float(gross.sum()), fees=float(orders[:, 9].sum()), net=float(net.sum()),
                gross_profit=float(gross[gross > 0].sum()), gross_loss=float(-gross[gross < 0].sum()),
                profit=profit, loss=damage, pf=profit / damage if damage else None,
                win_qty=win_qty, loss_qty=loss_qty, flat_qty=int(quantity[net == 0].sum()),
                win_per_lot=winner, loss_per_lot=loser, payoff=winner / loser if winner is not None and loser else None,
                lot_trades=len(trades), wins=int(win.sum()), losses=int(loss.sum()),
                win_rate=float(win.mean()) if len(trades) else None,
                cycles=len(group_ids), group_wins=int((group_net > 0).sum()), group_losses=int((group_net < 0).sum()),
                group_profit=group_profit, group_loss=group_loss, group_pf=group_profit / group_loss if group_loss else None,
                group_win_rate=float((group_net > 0).mean()) if len(group_net) else None,
                drawdown=float(np.max(peak - curve, initial=0)), equity_min=float(np.min(curve, initial=0)),
                equity_max=float(np.max(curve, initial=0)),
                hold_mean_minutes=float(group_hold.mean()) if len(group_hold) else None,
                hold_median_minutes=float(np.median(group_hold)) if len(group_hold) else None,
                hold_min_minutes=float(group_hold.min()) if len(group_hold) else None,
                hold_max_minutes=float(group_hold.max()) if len(group_hold) else None,
                group_hold_minutes=group_hold.tolist(),
                additions=int((orders[:, 4] == 3).sum()),
                added_lot_net=float(net[trades[:, 23] == 3].sum()),
                initial_lot_net=float(net[trades[:, 23] == 1].sum()),
                reasons={name: {'cycles': int(((orders[:, 4] == 2) & (orders[:, 11] == code)).sum()),
                                'net': float(net[trades[:, 9] == code].sum())} for code, name in REASONS.items()})


def execute(ready: dict, quotes: dict, signals: np.ndarray, config: dict, quote_mode: bool = True, finish: bool = True) -> dict:
    """機能: 一場・一条件を実行し、気配・枚数上限・ロット配賦・場内返済を検算する。

    引数: ready/quotes/config(dict)、signals(ndarray)、quote_mode/finish(bool)。
    返り値: 会計と注文/返済台帳を持つ辞書(dict)。原本最終約定値は使用しない。
    """
    contract = instrument(ready['symbol'])
    cap, value = contract['max_qty'], contract['value']
    qty, add = int(cap * config['initial_fraction']), int(cap * .2)
    width = max(2 * ready['tick'], np.ceil(quotes['mid'][0] * config['fraction'] / ready['tick'] - 1e-10) * ready['tick'])
    assert qty > 0 and add > 0 and signals.ndim == 2 and signals.shape[1] == 3
    assert not len(signals) or (np.diff(signals[:, 0]) > 0).all()
    assert not len(signals) or (signals[:, 2] == width).all()
    for name in ('seq', 'time_s'):
        np.testing.assert_array_equal(ready[name], quotes[name])
    assert 'last' not in ready and 'last' not in quotes
    orders, trades, counts, halted, halt_time = drive(ready['time_s'], ready['seq'], quotes['mid'], quotes['bid'], quotes['ask'],
        signals, qty, add, cap, config['pyramid'], value, ready['symbol'] == 'TOPIX', width, ready['tick'], ready['limit'],
        config['minutes'] * 60., config['cooldown_minutes'] * 60., quote_mode, finish, config.get('exit_mode', 0))
    curve, position = equity_curve(ready, quotes, orders, value, quote_mode)
    assert np.max(np.abs(position), initial=0) <= cap
    np.testing.assert_allclose(trades[:, 6], trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4]) * value, atol=1e-6)
    np.testing.assert_allclose(trades[:, 8], trades[:, 6] - trades[:, 7], atol=1e-6)
    np.testing.assert_array_equal(orders[:, 9], [order_fee(ready['symbol'], int(row[6])) for row in orders])
    assert counts[0] == counts[1] + counts[2] + counts[3] + counts[4] + counts[6]
    assert counts[0] + counts[7] == len(signals)
    if finish:
        assert position[-1] == 0 and counts[1] == len(np.unique(trades[:, 21])) + counts[5]
        assert not len(trades) or (trades[:, 1] < ready['limit'] + 300.).all()
        np.testing.assert_allclose(trades[:, 7].sum(), orders[:, 9].sum(), atol=1e-6)
        np.testing.assert_allclose(curve[-1], trades[:, 8].sum(), atol=1e-5)
        np.testing.assert_allclose(orders[:, 10].sum(), trades[:, 8].sum(), atol=1e-5)
    result = statistics(trades, curve, orders)
    result.update(session=ready['session'], symbol=ready['symbol'], price_mode='quote' if quote_mode else 'mid',
                  unrealized_start=0., unrealized_end=0. if finish else float(curve[-1] - orders[:, 10].sum()),
                  mtm_change=float(curve[-1]), max_long_qty=int(np.max(position, initial=0)),
                  max_short_qty=int(np.max(-position, initial=0)), budget=3 * width * cap * value,
                  halted=bool(halted), halt_time=float(halt_time), width=width,
                  candidate_count=len(signals), candidate_audit=dict(zip(CANDIDATE_KEYS, map(int, counts))),
                  orders=orders, trades=trades)
    return result
