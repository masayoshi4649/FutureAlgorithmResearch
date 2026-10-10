"""小幅回収と追跡返済を、原本中値の同じ因果時計で比較する売買器。"""

from __future__ import annotations

import numpy as np
from numba import njit


REASONS = {0: '新規', 1: '初期損切り', 2: '固定幅利確', 3: '中値トレーリング',
           4: '10分経過', 5: '範囲条件の破綻', 6: '場内返済'}
CANDIDATE_KEYS = ('consumed', 'accepted', 'occupied', 'cutoff', 'cooldown', 'unreached')


@njit(cache=True)
def drive(times: np.ndarray, seqs: np.ndarray, mids: np.ndarray, signals: np.ndarray,
          qty: int, value: float, tick: float, limit: float, exit_mode: int,
          automatic_exit: bool, finish: bool) -> tuple:
    """機能: 入口判断後の次行で建て、3種類の出口を中値だけで逐次判定する。

    引数: times/seqs/mids/signals(ndarray)、qty/exit_mode(int)、value/tick/limit(float)、automatic_exit/finish(bool)。
    signalsの列は有効原本index、方向、固定幅、破綻下限、破綻上限、状態0反復/1追従。境界なしはNaN。
    返り値: 注文13列、返済16列、幅評価9列、候補処理件数、実出口と入口状態2列(tuple)。
    """
    capacity = max(1, len(signals))
    orders, legs, groups = np.zeros((capacity * 2, 13)), np.zeros((capacity, 16)), np.zeros((capacity, 9))
    modes = np.zeros((capacity, 2), np.int64)
    counts = np.zeros(6, np.int64)
    no = nl = cursor = 0
    side = pending = pending_side = reason = 0
    cid = -1
    entry = entry_time = entry_seq = entry_i = width = best = worst = 0.
    decision_time = decision_seq = decision_width = next_entry = 0.
    lower = upper = np.nan
    target_width = activation_width = trail_width = 0.
    regime = 0
    actual_exit = exit_mode
    for i in range(len(mids)):
        now, seq, mid = times[i], seqs[i], mids[i]
        if not np.isfinite(mid) or mid <= 0:
            continue
        if pending == 1:
            side, pending = pending_side, 0
            cid += 1
            entry, entry_time, entry_seq, entry_i = mid, now, float(seq), float(i)
            width, best, worst = decision_width, mid, mid
            actual_exit = 3 if automatic_exit and regime == 1 else exit_mode
            target_width = width if actual_exit == 1 else np.ceil(1.5 * width / tick - 1e-10) * tick
            activation_width = np.ceil(.5 * width / tick - 1e-10) * tick
            trail_width = activation_width if actual_exit == 2 else width
            assert width > 0 and no < len(orders)
            orders[no] = np.array([decision_time, now, decision_seq, float(seq), 1., float(side),
                                  float(qty), mid, 0., 0., float(cid), float(qty), width])
            no += 1
        elif pending == 2:
            best = max(best, mid) if side > 0 else min(best, mid)
            worst = min(worst, mid) if side > 0 else max(worst, mid)
            pnl = side * (mid - entry) * qty * value
            mfe, mae = max(0., side * (best - entry) / width), max(0., -side * (worst - entry) / width)
            assert no < len(orders) and nl < len(legs)
            orders[no] = np.array([decision_time, now, decision_seq, float(seq), 2., float(-side),
                                  float(qty), mid, pnl, float(reason), float(cid), 0., width])
            legs[nl] = np.array([entry_time, now, float(side), float(qty), entry, mid, pnl, float(reason),
                                width, float(cid), decision_time, entry_seq, float(seq), decision_seq,
                                mfe, (now - entry_time) / 60.])
            groups[nl] = np.array([float(cid), width, pnl / (width * qty *value), entry_i, float(i),
                                  float(side), entry, mfe, mae])
            modes[nl] = np.array([actual_exit, regime])
            no += 1
            nl += 1
            side = pending = 0
            next_entry = now + 60.
        # ----------------------------------------
        # 保護線は価格の観測後にだけ更新する。複数条件同時成立時の優先順を固定する。
        if side and not pending:
            best = max(best, mid) if side > 0 else min(best, mid)
            worst = min(worst, mid) if side > 0 else max(worst, mid)
            initial_stop = entry - side * width
            trail_active = actual_exit == 3 or (actual_exit == 2 and side * (best - entry) >= activation_width)
            trail_stop = best - side * trail_width
            use_trail = trail_active and side * (trail_stop - initial_stop) > 0
            stop = trail_stop if use_trail else initial_stop
            trigger = 0
            if now >= limit:
                trigger = 6
            elif side * (mid - stop) <= 0:
                trigger = 3 if use_trail or actual_exit == 3 else 1
            elif (np.isfinite(lower) and mid < lower) or (np.isfinite(upper) and mid > upper):
                trigger = 5
            elif actual_exit != 3 and side * (mid - entry) >= target_width:
                trigger = 2
            elif actual_exit != 3 and now - entry_time >= 600.:
                trigger = 4
            if trigger:
                pending, reason = 2, trigger
                decision_time, decision_seq = now, float(seq)
        # ----------------------------------------
        # 保有中・休止中も候補を消費し、後から同じ候補を都合よく再利用しない。
        while cursor < len(signals) and int(signals[cursor, 0]) <= i:
            signal = signals[cursor]
            cursor += 1
            counts[0] += 1
            if side or pending:
                counts[2] += 1
                continue
            if now >= limit - 300.:
                counts[3] += 1
                continue
            if now < next_entry:
                counts[4] += 1
                continue
            counts[1] += 1
            pending, pending_side = 1, int(signal[1])
            decision_time, decision_seq, decision_width = now, float(seq), signal[2]
            lower, upper = signal[3], signal[4]
            regime = int(signal[5])
    counts[5] = len(signals) - cursor
    if finish and (side or pending):
        raise ValueError('場内返済する次の有効原本行がありません')
    return orders[:no], legs[:nl], groups[:nl], counts, modes[:nl]


def amount_statistics(legs: np.ndarray, curve: np.ndarray, w_curve: np.ndarray, qty: int) -> dict:
    """機能: 価格評価ごとに利益・損失・勝負枚数と時価最大減少幅をまとめる。

    引数: legs/curve/w_curve(ndarray)、qty(int)。返り値: 会計集計(dict)。
    """
    pnl = legs[:, 6]
    profit, loss = float(pnl[pnl > 0].sum()), float(-pnl[pnl < 0].sum())
    wins, losses, flat = int((pnl > 0).sum()), int((pnl < 0).sum()), int((pnl == 0).sum())
    win_per_lot = profit / (wins * qty) if wins else None
    loss_per_lot = loss / (losses * qty) if losses else None
    return dict(profit=profit, loss=loss, net=float(pnl.sum()), wins=wins, losses=losses, cycles=len(pnl),
                win_qty=wins * qty, loss_qty=losses * qty, flat_qty=flat * qty,
                win_rate=wins / len(pnl) if len(pnl) else None, pf=profit / loss if loss else None,
                win_per_lot=win_per_lot, loss_per_lot=loss_per_lot,
                payoff=win_per_lot / loss_per_lot if loss_per_lot and win_per_lot is not None else None,
                drawdown=float(np.max(np.maximum.accumulate(np.r_[0., curve])[1:] - curve, initial=0)),
                w_drawdown=float(np.max(np.maximum.accumulate(np.r_[0., w_curve])[1:] - w_curve, initial=0)))


def curves(ready: dict, mids: np.ndarray, orders: np.ndarray, fill_prices: np.ndarray,
           value: float, qty: int) -> tuple:
    """機能: 指定約定価格の現金収支と中値含み評価から曲線を作る。

    引数: ready(dict)、mids/orders/fill_prices(ndarray)、value(float)、qty(int)。
    返り値: 金額曲線、幅単位曲線、保有数量(tuple)。気配評価も含みは中値で統一する。
    """
    cash, delta = np.zeros(len(mids)), np.zeros(len(mids))
    w_cash, w_delta = np.zeros(len(mids)), np.zeros(len(mids))
    for order, price in zip(orders, fill_prices):
        i = int(np.searchsorted(ready['seq'], order[3]))
        decision = int(np.searchsorted(ready['seq'], order[2]))
        assert i == decision + 1 and ready['seq'][i] == order[3] and order[0] <= order[1]
        cash[i] -= order[5] * order[6] * price * value
        delta[i] += order[5] * order[6]
        w_cash[i] -= order[5] * price / order[12]
        w_delta[i] += order[5] / order[12]
    position = np.cumsum(delta)
    assert np.max(abs(position), initial=0) <= qty
    curve = np.cumsum(cash) + position * mids * value
    w_curve = np.cumsum(w_cash) + np.cumsum(w_delta) * mids
    return curve, w_curve, position


def execute(ready: dict, quotes: dict, signals: np.ndarray, qty: int, value: float,
            exit_mode: int, automatic_exit: bool = False, finish: bool = True) -> dict:
    """機能: 同じ注文の中値約定と売買気配約定を会計し、全注文と含みを照合する。

    引数: ready/quotes(dict)、signals(ndarray)、qty/exit_mode(int)、value(float)、automatic_exit/finish(bool)。
    返り値: 中値の台帳・曲線・集計、同一注文の売買気配感度と候補処理件数(dict)。
    """
    assert exit_mode in (1, 2, 3)
    assert signals.ndim == 2 and signals.shape[1] == 6
    assert not len(signals) or np.all(np.diff(signals[:, 0]) > 0)
    mids = quotes['mid']
    np.testing.assert_array_equal(ready['seq'], quotes['seq'])
    assert np.all(np.isfinite(mids)) and np.all(mids > 0)
    orders, legs, groups, counts, modes = drive(ready['time_s'], ready['seq'], mids, signals, qty, value,
                                               ready['tick'], ready['limit'], exit_mode, automatic_exit, finish)
    curve, w_curve, position = curves(ready, mids, orders, orders[:, 7], value, qty)
    np.testing.assert_allclose(legs[:, 6], legs[:, 2] * legs[:, 3] * (legs[:, 5] - legs[:, 4]) * value, atol=1e-6)
    assert counts[0] == counts[1:5].sum() and counts[0] + counts[5] == len(signals)
    if finish:
        assert position[-1] == 0 and counts[1] == len(legs) and counts[5] == 0
        np.testing.assert_allclose(curve[-1], legs[:, 6].sum(), atol=1e-6)
        np.testing.assert_allclose(w_curve[-1], groups[:, 2].sum(), atol=1e-6)
    # ----------------------------------------
    # 約定価格の感度だけを変える。気配価格で入口や保護線を再判断する別戦略ではない。
    order_indices = np.searchsorted(ready['seq'], orders[:, 3])
    quote_prices = np.where(orders[:, 5] > 0, quotes['ask'][order_indices], quotes['bid'][order_indices])
    assert np.all(np.isfinite(quote_prices)) and np.all(quote_prices > 0)
    quote_legs = legs.copy()
    entry_indices = np.searchsorted(ready['seq'], legs[:, 11])
    exit_indices = np.searchsorted(ready['seq'], legs[:, 12])
    quote_legs[:, 4] = np.where(legs[:, 2] > 0, quotes['ask'][entry_indices], quotes['bid'][entry_indices])
    quote_legs[:, 5] = np.where(legs[:, 2] > 0, quotes['bid'][exit_indices], quotes['ask'][exit_indices])
    quote_legs[:, 6] = quote_legs[:, 2] * quote_legs[:, 3] * (quote_legs[:, 5] - quote_legs[:, 4]) * value
    quote_curve, quote_w_curve, quote_position = curves(ready, mids, orders, quote_prices, value, qty)
    np.testing.assert_array_equal(position, quote_position)
    if finish:
        np.testing.assert_allclose(quote_curve[-1], quote_legs[:, 6].sum(), atol=1e-6)
    sensitivity = amount_statistics(quote_legs, quote_curve, quote_w_curve, qty)
    sensitivity.update(curve=quote_curve, w_curve=quote_w_curve,
                       w_net=float(np.sum(quote_legs[:, 6] / (quote_legs[:, 8] * qty * value))))
    return dict(session=ready['session'], symbol=ready['symbol'], orders=orders.tolist(), trades=legs.tolist(),
                quote_order_prices=quote_prices.tolist(), width_groups=groups.tolist(), trade_modes=modes.tolist(),
                curve=curve, w_curve=w_curve,
                sensitivity={'売買気配': sensitivity},
                candidate_count=len(signals), candidate_audit=dict(zip(CANDIDATE_KEYS, map(int, counts))),
                w_net=float(groups[:, 2].sum()), w_profit=float(groups[groups[:, 2] > 0, 2].sum()),
                w_loss=float(-groups[groups[:, 2] < 0, 2].sum()),
                **amount_statistics(legs, curve, w_curve, qty))
