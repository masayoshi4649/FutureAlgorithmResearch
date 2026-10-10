"""補充壁の破綻と中値トレーリングを監視する、原本順の仮想売買器。"""

from __future__ import annotations

import numpy as np
from numba import njit


REASONS = {0: '新規', 1: '中値トレーリング', 2: '場内返済', 3: '補充壁の保護線割れ'}


@njit(cache=True)
def drive(times: np.ndarray, seqs: np.ndarray, prices: np.ndarray, mids: np.ndarray, signals: np.ndarray,
          qty: int, value: float, limit: float, finish: bool) -> tuple:
    """機能: 判断後の次の有効原本行で売買し、壁と中値の一定幅で保護する。

    引数: times/seqs/prices/mids/signals(ndarray)、qty(int)、value/limit(float)、finish(bool)。
    返り値: 注文、返済組、幅を単位とする評価台帳(tuple)。銘柄名を受け取らない。
    """
    orders, legs, groups = np.zeros((12000, 13)), np.zeros((6000, 16)), np.zeros((6000, 9))
    no = nl = cursor = 0
    side = pending = pending_side = reason = 0
    cid = -1
    entry = entry_time = entry_seq = entry_i = width = best = worst = 0.
    decision_time = decision_seq = decision_width = next_entry = structure = entry_mid = 0.
    for i in range(len(prices)):
        now, seq, price, mid = times[i], seqs[i], prices[i], mids[i]
        if not np.isfinite(price) or price <= 0:
            continue
        if pending == 1:
            side, pending = pending_side, 0
            cid += 1
            entry, entry_time, entry_seq, entry_i = price, now, float(seq), float(i)
            width, best, worst, entry_mid = decision_width, mid, mid, mid
            assert width > 0 and no < len(orders)
            orders[no] = np.array([decision_time, now, decision_seq, float(seq), 1., float(side),
                                   float(qty), price, 0., 0., float(cid), float(qty), width])
            no += 1
        elif pending == 2:
            best = max(best, mid) if side > 0 else min(best, mid)
            worst = min(worst, mid) if side > 0 else max(worst, mid)
            pnl = side * (price - entry) * qty * value
            mfe, mae = max(0., side * (best - entry_mid) / width), max(0., -side * (worst - entry_mid) / width)
            assert no < len(orders) and nl < len(legs)
            orders[no] = np.array([decision_time, now, decision_seq, float(seq), 2., float(-side),
                                   float(qty), price, pnl, float(reason), float(cid), 0., width])
            legs[nl] = np.array([entry_time, now, float(side), float(qty), entry, price, pnl, float(reason),
                                width, float(cid), decision_time, entry_seq, float(seq), decision_seq,
                                mfe, (now - entry_time) / 60.])
            groups[nl] = np.array([float(cid), width, pnl / (width * qty * value), entry_i, float(i),
                                  float(side), entry, mfe, mae])
            no += 1
            nl += 1
            side = pending = 0
            next_entry = now + 60.
        # ----------------------------------------
        # 補充壁は固定し、中値の最良到達から追跡した線との有利な方を使う。
        if side and not pending:
            best = max(best, mid) if side > 0 else min(best, mid)
            worst = min(worst, mid) if side > 0 else max(worst, mid)
            trail = best - side * width
            wall_used = side * (structure - trail) >= 0
            stop = structure if wall_used else trail
            if now >= limit or side * (mid - stop) <= 0:
                pending, reason = 2, 2 if now >= limit else (3 if wall_used else 1)
                decision_time, decision_seq = now, float(seq)
        while cursor < len(signals) and int(signals[cursor, 0]) <= i:
            signal = signals[cursor]
            cursor += 1
            if side or pending or now >= limit - 300. or now < next_entry:
                continue
            pending, pending_side = 1, int(signal[1])
            decision_time, decision_seq, decision_width = now, float(seq), signal[2]
            structure = signal[3]
    if finish and (side or pending):
        raise ValueError('場内返済する次の有効原本行がありません')
    return orders[:no], legs[:nl], groups[:nl]


def execute(ready: dict, frame: dict, signals: np.ndarray, qty: int, value: float, finish: bool = True) -> dict:
    """機能: 取引台帳と含み損益を含む金額・初期幅単位の曲線を作る。

    引数: ready/frame(dict)、signals(ndarray)、qty(int)、value(float)、finish(bool)。
    返り値: 口座別の金額、枚数、注文、曲線、固定幅単位の損益(dict)。
    """
    assert not len(signals) or np.all(np.diff(signals[:, 0]) > 0)
    orders, legs, groups = drive(ready['time_s'], ready['seq'], ready['last'], frame['mid'], signals,
                                 qty, value, ready['limit'], finish)
    cash, delta = np.zeros(len(ready['last'])), np.zeros(len(ready['last']))
    w_cash, w_delta = np.zeros(len(cash)), np.zeros(len(cash))
    for order in orders:
        i = int(np.searchsorted(ready['seq'], order[3]))
        assert ready['seq'][i] == order[3] and order[2] < order[3] and order[0] <= order[1]
        cash[i] -= order[5] * order[6] * order[7] * value
        delta[i] += order[5] * order[6]
        w_cash[i] -= order[5] * order[7] / order[12]
        w_delta[i] += order[5] / order[12]
    position = np.cumsum(delta)
    curve = np.cumsum(cash) + position * ready['last'] * value
    w_curve = np.cumsum(w_cash) + np.cumsum(w_delta) * ready['last']
    pnl, ws = legs[:, 6], groups[:, 2]
    assert np.max(abs(position), initial=0) <= qty
    np.testing.assert_allclose(pnl, legs[:, 2] * legs[:, 3] * (legs[:, 5] - legs[:, 4]) * value, atol=1e-6)
    if finish:
        assert position[-1] == 0
        np.testing.assert_allclose(curve[-1], pnl.sum(), atol=1e-6)
        np.testing.assert_allclose(w_curve[-1], ws.sum(), atol=1e-6)
    sensitivity = {}
    for mode in ('中値', '売買気配'):
        repriced = legs.copy()
        entry_indices = np.searchsorted(ready['seq'], legs[:, 11])
        exit_indices = np.searchsorted(ready['seq'], legs[:, 12])
        if mode == '中値':
            repriced[:, 4], repriced[:, 5] = frame['mid'][entry_indices], frame['mid'][exit_indices]
        else:
            repriced[:, 4] = np.where(legs[:, 2] > 0, frame['ask'][entry_indices], frame['bid'][entry_indices])
            repriced[:, 5] = np.where(legs[:, 2] > 0, frame['bid'][exit_indices], frame['ask'][exit_indices])
        repriced[:, 6] = repriced[:, 2] * repriced[:, 3] * (repriced[:, 5] - repriced[:, 4]) * value
        amounts = repriced[:, 6]
        sensitivity[mode] = dict(profit=float(amounts[amounts > 0].sum()), loss=float(-amounts[amounts < 0].sum()),
                                 net=float(amounts.sum()), win_qty=int((amounts > 0).sum() * qty),
                                 loss_qty=int((amounts < 0).sum() * qty), flat_qty=int((amounts == 0).sum() * qty),
                                 wins=int((amounts > 0).sum()), losses=int((amounts < 0).sum()), cycles=len(amounts))
    return dict(session=ready['session'], symbol=ready['symbol'], orders=orders.tolist(), trades=legs.tolist(),
                sensitivity=sensitivity,
                width_groups=groups.tolist(), curve=curve, w_curve=w_curve,
                profit=float(pnl[pnl > 0].sum()), loss=float(-pnl[pnl < 0].sum()), net=float(pnl.sum()),
                win_qty=int((pnl > 0).sum() * qty), loss_qty=int((pnl < 0).sum() * qty), flat_qty=int((pnl == 0).sum() * qty),
                cycles=len(pnl), wins=int((pnl > 0).sum()), losses=int((pnl < 0).sum()),
                w_net=float(ws.sum()), w_profit=float(ws[ws > 0].sum()), w_loss=float(-ws[ws < 0].sum()),
                drawdown=float(np.max(np.maximum.accumulate(np.r_[0., curve])[1:] - curve, initial=0)),
                w_drawdown=float(np.max(np.maximum.accumulate(np.r_[0., w_curve])[1:] - w_curve, initial=0)))
