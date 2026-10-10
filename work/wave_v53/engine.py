"""原本順の次行約定と、分割返済を含む場内資金管理を行う。"""

from __future__ import annotations

import numpy as np
from numba import njit


REASONS = {0: '新規', 1: '初期の損失制限', 2: '追跡・構造保護', 3: '反対の入口信号',
           4: '保有時間上限', 5: '値幅が進まない', 6: '回帰目標で半減', 7: '板の悪化で半減', 8: '場内返済'}
DECISION_COLUMNS = ['raw_index', 'entry_signal', 'raw_signal', 'invalidation', 'target', 'atr5',
                    'regime', 'trend_direction', 'book_direction', 'protect_long', 'protect_short']


@njit(cache=True)
def protected_stop(stop: float, side: int, best: float, entry: float, risk: float, atr: float,
                   age: float, regime: int, trend: int, book: int) -> float:
    """機能: 最新状況と経過時間から、緩めることなく利益保護線を更新する。

    引数: stop/best/entry/risk/atr/age(float)、side/regime/trend/book(int)。
    返り値: 新しいストップ価格(float)。
    """
    mfe = side * (best - entry) / risk
    if mfe < .5:
        return stop
    width = max(.5 * atr, .5 * risk) if regime == 1 and trend == side else max(.3 * atr, .25 * risk)
    if age >= 900.:
        width *= .75
    if age >= 1800.:
        width *= .75
    if book == -side:
        width = min(width, .3 * risk)
    line = best - side * max(width, .15 * risk)
    if mfe >= 1.:
        line = max(line, entry) if side > 0 else min(line, entry)
    return max(stop, line) if side > 0 else min(stop, line)


@njit(cache=True)
def drive(times: np.ndarray, seqs: np.ndarray, prices: np.ndarray, decisions: np.ndarray,
          qty: int, value: float, advanced: bool, limit: float, finish: bool) -> tuple:
    """機能: 現在行までの指示だけで新規・保護・一度の半減・全返済を実行する。

    引数: times/seqs/prices/decisions(ndarray)、qty(int)、value(float)、advanced(bool)、
    limit(float:場内返済時刻)、finish(bool:場末検査)。返り値: 注文・返済脚・保有枚数(tuple)。
    先の指示を読まず、判断した後の次有効原本行でだけ約定する。
    """
    orders = np.zeros((12000, 13))
    legs = np.zeros((10000, 16))
    no = nl = cursor = 0
    side = position = 0
    cid = -1
    entry = entry_time = entry_atr = initial_risk = entry_seq = best = stop = target = 0.
    deadline = 0.
    stop_reason = 1
    current_atr = 0.
    regime = trend = book = 0
    reduced = False
    group_pnl = 0.
    loss_streak = 0
    next_entry = 0.
    pending = pending_qty = pending_side = pending_reason = 0
    decision_time = decision_seq = decision_atr = decision_stop = decision_target = 0.
    decision_regime = 0
    for i in range(len(prices)):
        price, now, seq = prices[i], times[i], seqs[i]
        if not np.isfinite(price) or price <= 0:
            continue
        # ----------------------------------------
        # 次行約定。分割返済も実際に返した枚数だけを記録する。
        if pending == 1:
            cid += 1
            side, position = pending_side, pending_qty
            entry, entry_time, entry_seq = price, now, seq
            entry_atr, current_atr, stop, target = decision_atr, decision_atr, decision_stop, decision_target
            initial_risk = max(side * (entry - stop), .1 * entry_atr)
            best, reduced, stop_reason, group_pnl = price, False, 1, 0.
            duration = (5400. if decision_regime == 1 else 900. if decision_regime == 2 else 1800.) if advanced else 1800.
            deadline = entry_time + duration
            assert no < len(orders)
            orders[no] = np.array([decision_time, now, decision_seq, float(seq), 1., float(side), float(position),
                                   price, 0., 0., float(cid), float(position), initial_risk])
            no += 1
            pending = 0
        elif pending == 2:
            best = max(best, price) if side > 0 else min(best, price)
            close_qty = min(position, pending_qty)
            pnl = side * (price - entry) * close_qty * value
            group_pnl += pnl
            position -= close_qty
            assert no < len(orders) and nl < len(legs)
            orders[no] = np.array([decision_time, now, decision_seq, float(seq), 2., float(-side), float(close_qty),
                                   price, pnl, float(pending_reason), float(cid), float(position), initial_risk])
            legs[nl] = np.array([entry_time, now, float(side), float(close_qty), entry, price, pnl,
                                float(pending_reason), entry_atr, float(cid), decision_time,
                                float(entry_seq), float(seq), decision_seq,
                                max(0., side * (best - entry) / entry_atr), (now - entry_time) / 60.])
            no += 1
            nl += 1
            pending = 0
            if not position:
                side = 0
                loss_streak = loss_streak + 1 if group_pnl < 0 else 0
                next_entry = now + 60.
                if advanced and loss_streak >= 2:
                    next_entry = now + 900.
                    loss_streak = 0
            else:
                reduced = True
                if side * (entry - stop) > 0:
                    stop, stop_reason = entry, 2
        # ----------------------------------------
        # 原本全行で保護条件を確認する。ストップは保有中に緩めない。
        if position:
            best = max(best, price) if side > 0 else min(best, price)
            mfe = side * (best - entry) / initial_risk
            age = now - entry_time
            if advanced and mfe >= .5:
                line = protected_stop(stop, side, best, entry, initial_risk, current_atr, age, regime, trend, book)
                if side * (line - stop) > 0:
                    stop, stop_reason = line, 2
            elif not advanced and mfe >= 1.:
                line = best - side * initial_risk
                if side * (line - stop) > 0:
                    stop, stop_reason = line, 2
            reason = 0
            if now >= limit:
                reason = 8
            elif side * (price - stop) <= 0:
                reason = stop_reason
            elif now >= deadline:
                reason = 4
            elif advanced and age >= 300. and mfe < .25:
                reason = 5
            if reason:
                pending, pending_qty, pending_reason = 2, position, reason
                decision_time, decision_seq = now, float(seq)
        # ----------------------------------------
        # 確定足の公開行に達した時だけ、状況や構造線を更新する。
        while cursor < len(decisions) and int(decisions[cursor, 0]) <= i:
            row = decisions[cursor]
            cursor += 1
            regime, trend, book = int(row[6]), int(row[7]), int(row[8])
            if np.isfinite(row[5]) and row[5] > 0:
                current_atr = row[5]
            if pending:
                continue
            signal, raw_signal = int(row[1]), int(row[2])
            if position:
                if raw_signal == -side:
                    pending, pending_qty, pending_reason = 2, position, 3
                elif advanced:
                    duration = 5400. if regime == 1 and trend == side else 900. if regime == 2 else 1800.
                    deadline = min(deadline, entry_time + duration)
                    line = protected_stop(stop, side, best, entry, initial_risk, current_atr, now-entry_time, regime, trend, book)
                    if side * (line - stop) > 0:
                        stop, stop_reason = line, 2
                    mfe = side * (best - entry) / initial_risk
                    structure = row[9] if side > 0 else row[10]
                    if mfe >= .5 and np.isfinite(structure):
                        line = structure - side * .1 * current_atr
                        if side * (line - stop) > 0:
                            stop, stop_reason = line, 2
                    progress = side * (price - entry) / initial_risk
                    target_hit = np.isfinite(target) and side * (target - entry) >= .5 * initial_risk and side * (price - target) >= 0
                    if side * (price - stop) <= 0:
                        pending, pending_qty, pending_reason = 2, position, 2
                    elif now >= deadline:
                        pending, pending_qty, pending_reason = 2, position, 4
                    elif not reduced and position > 1 and progress >= .5 and (target_hit or book == -side):
                        pending, pending_qty = 2, max(1, qty // 2)
                        pending_reason = 6 if target_hit else 7
                if pending:
                    decision_time, decision_seq = now, float(seq)
            elif signal and now < limit - 300. and now >= next_entry and np.isfinite(row[5]) and row[5] > 0:
                distance = signal * (price - row[3])
                if not np.isfinite(distance) or distance <= 0:
                    continue
                width = min(max(distance, .5 * row[5]), 1.5 * row[5])
                pending, pending_side, pending_qty = 1, signal, qty
                decision_time, decision_seq, decision_atr = now, float(seq), row[5]
                decision_stop, decision_target, decision_regime = price - signal * width, row[4], regime
    if finish and (position or pending):
        raise ValueError('場内返済に必要な後続価格がありません')
    return orders[:no], legs[:nl], position


def execute(ready: dict, decisions: np.ndarray, advanced: bool, finish: bool = True) -> dict:
    """機能: 分割返済の金額・枚数と新規から全返済までの組勝率を区別して集計する。

    引数: ready(dict)、decisions(ndarray)、advanced(bool)、finish(bool)。
    返り値: 注文・返済脚・組数・時価曲線・損益(dict)。
    """
    qty, value = (5, 1000) if ready['symbol'] == 'TOPIX' else (10, 10)
    decisions = np.asarray(decisions, float).reshape(-1, len(DECISION_COLUMNS))
    assert not len(decisions) or np.all(np.diff(decisions[:, 0]) > 0)
    orders, legs, position = drive(ready['time_s'], ready['seq'], ready['last'], decisions,
                                  qty, value, advanced, ready['limit'], finish)
    cash = np.zeros(len(ready['last']))
    dq = np.zeros_like(cash)
    for row in orders:
        ix = int(np.searchsorted(ready['seq'], row[3]))
        assert ready['seq'][ix] == row[3] and row[2] < row[3] and row[0] <= row[1]
        cash[ix] -= row[5] * row[6] * row[7] * value
        dq[ix] += row[5] * row[6]
    positions = np.cumsum(dq)
    curve = np.cumsum(cash) + positions * ready['last'] * value
    assert np.max(abs(positions), initial=0) <= qty
    pnl = legs[:, 6]
    np.testing.assert_allclose(pnl, legs[:, 2] * legs[:, 3] * (legs[:, 5] - legs[:, 4]) * value, atol=1e-6)
    if finish:
        assert position == 0 and positions[-1] == 0
        np.testing.assert_allclose(curve[-1], pnl.sum(), atol=1e-6)
    groups = np.array([legs[legs[:, 9] == cid, 6].sum() for cid in np.unique(legs[:, 9])])
    peaks = np.maximum.accumulate(np.r_[0., curve])[1:]
    return dict(session=ready['session'], symbol=ready['symbol'], orders=orders.tolist(), trades=legs.tolist(),
                curve=curve, profit=float(pnl[pnl > 0].sum()), loss=float(-pnl[pnl < 0].sum()), net=float(pnl.sum()),
                win_qty=int(legs[pnl > 0, 3].sum()), loss_qty=int(legs[pnl < 0, 3].sum()), flat_qty=int(legs[pnl == 0, 3].sum()),
                cycles=len(groups), wins=int((groups > 0).sum()), losses=int((groups < 0).sum()),
                group_nets=groups.tolist(), repayment_legs=len(legs), drawdown=float(np.max(peaks-curve, initial=0)))
