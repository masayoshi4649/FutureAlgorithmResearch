"""30〜60分の期限と早期損切りを、気配約定と注文手数料込みで独立再生する。"""

from __future__ import annotations

import numpy as np
from numba import njit

from fees import instrument


REASONS = {1: '初期損切り', 2: '固定利確', 3: '利益到達後の追跡返済', 4: '保有期限', 5: '場内返済'}
ORDER_COLUMNS = ('decision_time', 'fill_time', 'decision_seq', 'fill_seq', 'action', 'side', 'qty', 'price',
                 'gross', 'fee', 'net_event', 'reason', 'trade_id', 'position_after', 'W')
TRADE_COLUMNS = ('entry_time', 'exit_time', 'side', 'qty', 'entry_price', 'exit_price', 'gross', 'fees', 'net',
                 'reason', 'W', 'exit_decision_time', 'entry_seq', 'exit_seq', 'exit_decision_seq',
                 'mfe_W', 'mae_W', 'hold_minutes', 'entry_decision_seq', 'entry_i', 'exit_i', 'trade_id')
CANDIDATE_KEYS = ('consumed', 'scheduled', 'occupied', 'cutoff', 'cooldown', 'cancelled_at_fill', 'unreached')


@njit(cache=True)
def drive(times: np.ndarray, seqs: np.ndarray, mids: np.ndarray, bids: np.ndarray, asks: np.ndarray,
          signals: np.ndarray, qty: int, value: float, fee: int, tick: float, limit: float,
          exit_mode: int, holding_seconds: float, quote_mode: bool, finish: bool) -> tuple:
    """機能: 判断の次有効原本行で約定し、実建値と返済側価格で出口を判断する。

    引数: times/seqs/mids/bids/asks/signals(ndarray)、qty/fee/exit_mode(int)、value/tick/limit/holding_seconds(float)、quote_mode/finish(bool)。
    返り値: 注文15列、返済22列、候補処理7分類(tuple[np.ndarray,np.ndarray,np.ndarray])。
    quote_mode=False は中値で別に売買判断する参考再生で、注文価格の事後置換ではない。
    """
    capacity = max(1, len(signals))
    orders = np.zeros((capacity * 2, 15))
    trades = np.zeros((capacity, 22))
    counts = np.zeros(7, np.int64)
    no = nt = pointer = 0
    pending = side = pending_side = reason = 0
    trade_id = -1
    entry = entry_time = entry_seq = entry_i = best = worst = width = target_width = 0.
    decision_time = decision_seq = decision_width = entry_decision_seq = next_entry = 0.
    for i in range(len(times)):
        now, seq, mid, bid, ask = times[i], seqs[i], mids[i], bids[i], asks[i]
        if pending == 1:
            if now >= limit - 300.:
                counts[5] += 1
                pending = 0
            else:
                pending, side = 0, pending_side
                trade_id += 1
                entry = (ask if side > 0 else bid) if quote_mode else mid
                entry_time, entry_seq, entry_i = now, float(seq), float(i)
                entry_decision_seq = decision_seq
                width = decision_width
                target_width = np.ceil(1.5 * width / tick - 1e-10) * tick
                liquidation = (bid if side > 0 else ask) if quote_mode else mid
                best = worst = liquidation
                orders[no] = np.array([decision_time, now, decision_seq, float(seq), 1., float(side),
                                       float(qty), entry, 0., float(fee), float(-fee), 0.,
                                       float(trade_id), float(side * qty), width])
                no += 1
        elif pending == 2:
            if now > limit:
                raise ValueError('返済判断後の次有効行が場内返済期限を超えています')
            liquidation = (bid if side > 0 else ask) if quote_mode else mid
            best = max(best, liquidation) if side > 0 else min(best, liquidation)
            worst = min(worst, liquidation) if side > 0 else max(worst, liquidation)
            gross = side * (liquidation - entry) * qty * value
            total_fee = 2 * fee
            mfe = max(0., side * (best - entry) / width)
            mae = max(0., -side * (worst - entry) / width)
            orders[no] = np.array([decision_time, now, decision_seq, float(seq), 2., float(-side),
                                   float(qty), liquidation, gross, float(fee), gross - fee,
                                   float(reason), float(trade_id), 0., width])
            trades[nt] = np.array([entry_time, now, float(side), float(qty), entry, liquidation,
                                   gross, float(total_fee), gross - total_fee, float(reason), width,
                                   decision_time, entry_seq, float(seq), decision_seq, mfe, mae,
                                   (now - entry_time) / 60., entry_decision_seq, entry_i, float(i), float(trade_id)])
            no += 1
            nt += 1
            side = pending = 0
            next_entry = now + 300.
        # ----------------------------------------
        # 価格は現在行の返済可能側を用い、損切りを期限到来まで遅らせない。
        if side and pending == 0:
            liquidation = (bid if side > 0 else ask) if quote_mode else mid
            best = max(best, liquidation) if side > 0 else min(best, liquidation)
            worst = min(worst, liquidation) if side > 0 else max(worst, liquidation)
            initial_stop = entry - side * width
            trail_active = exit_mode == 2 and side * (best - entry) >= width
            trail_stop = best - side * width
            use_trail = trail_active and side * (trail_stop - initial_stop) > 0
            stop = trail_stop if use_trail else initial_stop
            trigger = 0
            if now >= limit - 60.:
                trigger = 5
            elif side * (liquidation - stop) <= 0:
                trigger = 3 if use_trail else 1
            elif exit_mode == 1 and side * (liquidation - entry) >= target_width:
                trigger = 2
            elif now - entry_time >= holding_seconds:
                trigger = 4
            if trigger:
                pending, reason = 2, trigger
                decision_time, decision_seq = now, float(seq)
        # ----------------------------------------
        # 保有・休止・場末で見送った候補も消費し、後から都合よく再利用しない。
        while pointer < len(signals) and int(signals[pointer, 0]) <= i:
            signal = signals[pointer]
            pointer += 1
            counts[0] += 1
            if side or pending:
                counts[2] += 1
            elif now >= limit - 300.:
                counts[3] += 1
            elif now < next_entry:
                counts[4] += 1
            else:
                counts[1] += 1
                pending, pending_side = 1, int(signal[1])
                decision_time, decision_seq, decision_width = now, float(seq), signal[2]
    counts[6] = len(signals) - pointer
    if finish and (side != 0 or pending != 0):
        raise ValueError('場内返済を完了する次の有効原本行が不足しています')
    return orders[:no], trades[:nt], counts


def equity_curve(ready: dict, quotes: dict, orders: np.ndarray, value: float, quote_mode: bool) -> tuple[np.ndarray, np.ndarray]:
    """機能: 注文時の手数料と返済可能側の含み価格から口座曲線を作る。

    引数: ready/quotes(dict)、orders(ndarray)、value(float)、quote_mode(bool)。
    返り値: 手数料後の資産曲線と符号付き枚数(tuple[np.ndarray,np.ndarray])。
    """
    size = len(ready['seq'])
    cash_delta, position_delta = np.zeros(size), np.zeros(size)
    for row in orders:
        index = int(np.searchsorted(ready['seq'], row[3]))
        decision = int(np.searchsorted(ready['seq'], row[2]))
        assert index == decision + 1 and ready['seq'][index] == row[3]
        assert row[1] >= row[0]
        cash_delta[index] -= row[5] * row[6] * row[7] * value + row[9]
        position_delta[index] += row[5] * row[6]
    position = np.cumsum(position_delta)
    valuation = np.where(position >= 0, quotes['bid'], quotes['ask']) if quote_mode else quotes['mid']
    curve = np.cumsum(cash_delta) + position * valuation * value
    return curve, position


def statistics(trades: np.ndarray, curve: np.ndarray, orders: np.ndarray) -> dict:
    """機能: 費用前後の金額・勝負枚数・保有時間・返済理由を集計する。

    引数: trades/curve/orders(np.ndarray) は一口座の完成台帳。
    返り値: 同値除外勝率を併記した会計辞書(dict)。利益損失分類は手数料後で行う。
    """
    net, gross = trades[:, 8], trades[:, 6]
    winning, losing, flat = net > 0, net < 0, net == 0
    win_qty, loss_qty = int(trades[winning, 3].sum()), int(trades[losing, 3].sum())
    profit, loss = float(net[winning].sum()), float(-net[losing].sum())
    mean_win, mean_loss = profit / win_qty if win_qty else None, loss / loss_qty if loss_qty else None
    hold = trades[:, 17]
    peak = np.maximum.accumulate(np.r_[0., curve])[1:]
    return dict(gross=float(gross.sum()), gross_pnl=float(gross.sum()), fees=float(orders[:, 9].sum()), net=float(net.sum()),
                profit=profit, loss=loss, gross_profit=float(gross[gross > 0].sum()), gross_loss=float(-gross[gross < 0].sum()),
                cycles=len(trades), wins=int(winning.sum()), losses=int(losing.sum()),
                win_qty=win_qty, loss_qty=loss_qty, flat_qty=int(trades[flat, 3].sum()),
                win_rate=float(winning.mean()) if len(trades) else None,
                win_rate_excluding_flat=float(winning.sum() / (winning.sum() + losing.sum())) if (winning | losing).any() else None,
                pf=profit / loss if loss else None, win_per_lot=mean_win, loss_per_lot=mean_loss,
                payoff=mean_win / mean_loss if mean_win is not None and mean_loss else None,
                drawdown=float(np.max(peak - curve, initial=0)),
                equity_min=float(np.min(curve, initial=0)), equity_max=float(np.max(curve, initial=0)),
                hold_mean_minutes=float(hold.mean()) if len(hold) else None,
                hold_median_minutes=float(np.median(hold)) if len(hold) else None,
                hold_min_minutes=float(hold.min()) if len(hold) else None,
                hold_max_minutes=float(hold.max()) if len(hold) else None,
                hold_under_30_minutes=int((hold < 30).sum()),
                hold_30_to_60_minutes=int(((hold >= 30) & (hold <= 60)).sum()),
                hold_over_60_minutes=int((hold > 60).sum()),
                reasons={label: {'cycles': int((trades[:, 9] == code).sum()),
                                 'net': float(trades[trades[:, 9] == code, 8].sum())}
                         for code, label in REASONS.items()})


def execute(ready: dict, quotes: dict, signals: np.ndarray, exit_mode: int,
            minutes: int, quote_mode: bool = True, finish: bool = True) -> dict:
    """機能: 一口座・一条件を独立再生し、次行約定・費用・数量上限・場内返済を検算する。

    引数: ready/quotes(dict)、signals(ndarray)、exit_mode/minutes(int)、quote_mode/finish(bool)。
    返り値: 会計集計・注文配列・取引配列・候補消費を持つ辞書(dict)。
    """
    contract = instrument(ready['symbol'])
    assert exit_mode in (1, 2) and minutes in (30, 45, 60)
    assert signals.ndim == 2 and signals.shape[1] == 3
    assert not len(signals) or np.all(np.diff(signals[:, 0]) > 0)
    for name in ('seq', 'time_s'):
        np.testing.assert_array_equal(ready[name], quotes[name])
    assert 'last' not in ready and 'last' not in quotes
    orders, trades, counts = drive(ready['time_s'], ready['seq'], quotes['mid'], quotes['bid'], quotes['ask'],
                                   signals, contract['qty'], contract['value'], contract['fee'], ready['tick'], ready['limit'],
                                   exit_mode, minutes * 60., quote_mode, finish)
    curve, position = equity_curve(ready, quotes, orders, contract['value'], quote_mode)
    assert np.max(np.abs(position), initial=0) <= contract['qty'] <= contract['max_qty']
    np.testing.assert_allclose(trades[:, 6], trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4]) * contract['value'], atol=1e-6)
    np.testing.assert_array_equal(trades[:, 7], np.full(len(trades), 2 * contract['fee']))
    np.testing.assert_allclose(trades[:, 8], trades[:, 6] - trades[:, 7], atol=1e-6)
    assert counts[0] == counts[1] + counts[2] + counts[3] + counts[4]
    assert counts[0] + counts[6] == len(signals)
    if finish:
        assert position[-1] == 0 and counts[1] == len(trades) + counts[5]
        assert len(orders) == 2 * len(trades) and counts[6] == 0
        assert not len(trades) or np.all(trades[:, 1] <= ready['limit'])
        np.testing.assert_allclose(curve[-1], trades[:, 8].sum(), atol=1e-5)
        np.testing.assert_allclose(orders[:, 10].sum(), trades[:, 8].sum(), atol=1e-5)
    result = statistics(trades, curve, orders)
    if finish:
        np.testing.assert_allclose(result['gross'] - result['fees'], result['net'], atol=1e-5)
    result.update(session=ready['session'], symbol=ready['symbol'], quote_mode=quote_mode,
                  price_mode='quote' if quote_mode else 'mid',
                  unrealized_start=0., unrealized_end=0. if finish else float(curve[-1] - orders[:, 10].sum()),
                  mtm_change=float(curve[-1]), max_long_qty=int(np.max(position, initial=0)),
                  max_short_qty=int(np.max(-position, initial=0)),
                  candidate_count=len(signals), candidate_audit=dict(zip(CANDIDATE_KEYS, map(int, counts))),
                  orders=orders, trades=trades)
    return result
