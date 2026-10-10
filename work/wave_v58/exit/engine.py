"""00054の売買器を複製し、補充壁とトレーリングの出口だけを切り分ける。"""

from __future__ import annotations

import numpy as np
from numba import njit


REASONS = {0: '新規', 1: '中値トレーリング', 2: '場内返済', 3: '補充壁の保護線割れ'}
MODES = {'A': '壁と即時トレール', 'B': '壁だけ', 'C': '即時トレールだけ', 'D': '壁と1幅順行後トレール'}


@njit(cache=True)
def drive(times: np.ndarray, seqs: np.ndarray, mids: np.ndarray, signals: np.ndarray,
          qty: int, value: float, limit: float, exit_mode: int, finish: bool) -> tuple:
    """機能: 判断の次の有効原本行の中値で売買し、固定した出口部品を比較する。

    引数: times/seqs/mids/signals(ndarray)、qty/exit_mode(int)、value/limit(float)、finish(bool)。
    返り値: 注文、返済組、幅単位の評価台帳、候補の処理件数(tuple)。銘柄名は参照しない。
    """
    capacity = max(1, len(signals))
    orders, legs, groups = np.zeros((capacity * 2, 13)), np.zeros((capacity, 16)), np.zeros((capacity, 9))
    counts = np.zeros(6, np.int64)
    no = nl = cursor = 0
    side = pending = pending_side = reason = 0
    cid = -1
    entry = entry_time = entry_seq = entry_i = width = best = worst = 0.
    decision_time = decision_seq = decision_width = next_entry = structure = entry_mid = 0.
    for i in range(len(mids)):
        now, seq, mid = times[i], seqs[i], mids[i]
        if not np.isfinite(mid) or mid <= 0:
            continue
        if pending == 1:
            side, pending = pending_side, 0
            cid += 1
            entry, entry_time, entry_seq, entry_i = mid, now, float(seq), float(i)
            width, best, worst, entry_mid = decision_width, mid, mid, mid
            assert width > 0 and no < len(orders)
            orders[no] = np.array([decision_time, now, decision_seq, float(seq), 1., float(side),
                                  float(qty), mid, 0., 0., float(cid), float(qty), width])
            no += 1
        elif pending == 2:
            best = max(best, mid) if side > 0 else min(best, mid)
            worst = min(worst, mid) if side > 0 else max(worst, mid)
            pnl = side * (mid - entry) * qty * value
            mfe, mae = max(0., side * (best - entry_mid) / width), max(0., -side * (worst - entry_mid) / width)
            assert no < len(orders) and nl < len(legs)
            orders[no] = np.array([decision_time, now, decision_seq, float(seq), 2., float(-side),
                                  float(qty), mid, pnl, float(reason), float(cid), 0., width])
            legs[nl] = np.array([entry_time, now, float(side), float(qty), entry, mid, pnl, float(reason),
                                width, float(cid), decision_time, entry_seq, float(seq), decision_seq,
                                mfe, (now - entry_time) / 60.])
            groups[nl] = np.array([float(cid), width, pnl / (width * qty * value), entry_i, float(i),
                                  float(side), entry, mfe, mae])
            no += 1
            nl += 1
            side = pending = 0
            next_entry = now + 60.
        # ----------------------------------------
        # Dの順行到達は約定中値から測る。最良到達値が戻らないため有効化後に解除しない。
        if side and not pending:
            best = max(best, mid) if side > 0 else min(best, mid)
            worst = min(worst, mid) if side > 0 else max(worst, mid)
            trail = best - side * width
            trail_active = exit_mode == 0 or exit_mode == 2 or (exit_mode == 3 and side * (best - entry_mid) >= width)
            wall_used = exit_mode != 2 and (not trail_active or side * (structure - trail) >= 0)
            stop = structure if wall_used else trail
            if now >= limit or side * (mid - stop) <= 0:
                pending, reason = 2, 2 if now >= limit else (3 if wall_used else 1)
                decision_time, decision_seq = now, float(seq)
        # ----------------------------------------
        # 候補は原列を消費する。見送り理由は保有・締切・休止の順で重複なく計上する。
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
            structure = signal[3]
    counts[5] = len(signals) - cursor
    if finish and (side or pending):
        raise ValueError('場内返済する次の有効原本行がありません')
    return orders[:no], legs[:nl], groups[:nl], counts


def execute(ready: dict, frame: dict, signals: np.ndarray, qty: int, value: float,
            mode: str, finish: bool = True) -> dict:
    """機能: 次行中値の台帳と含み損益曲線を作り、候補消費と会計を照合する。

    引数: ready/frame(dict)、signals(ndarray)、qty(int)、value(float)、mode(str)、finish(bool)。
    返り値: 金額、枚数、注文、曲線、幅単位損益と候補消費件数(dict)。
    """
    assert mode in MODES
    assert not len(signals) or np.all(np.diff(signals[:, 0]) > 0)
    mids = frame['mid']
    assert np.all(np.isfinite(mids)) and np.all(mids > 0)
    np.testing.assert_array_equal(ready['seq'], frame['seq'])
    orders, legs, groups, counts = drive(ready['time_s'], ready['seq'], mids, signals, qty, value,
                                        ready['limit'], 'ABCD'.index(mode), finish)
    cash, delta = np.zeros(len(mids)), np.zeros(len(mids))
    w_cash, w_delta = np.zeros(len(cash)), np.zeros(len(cash))
    for order in orders:
        i = int(np.searchsorted(ready['seq'], order[3]))
        decision = int(np.searchsorted(ready['seq'], order[2]))
        assert i == decision + 1 and ready['seq'][i] == order[3] and order[2] < order[3] and order[0] <= order[1]
        assert order[7] == mids[i]
        cash[i] -= order[5] * order[6] * order[7] * value
        delta[i] += order[5] * order[6]
        w_cash[i] -= order[5] * order[7] / order[12]
        w_delta[i] += order[5] / order[12]
    position = np.cumsum(delta)
    curve = np.cumsum(cash) + position * mids * value
    w_curve = np.cumsum(w_cash) + np.cumsum(w_delta) * mids
    pnl, ws = legs[:, 6], groups[:, 2]
    assert np.max(abs(position), initial=0) <= qty
    np.testing.assert_allclose(pnl, legs[:, 2] * legs[:, 3] * (legs[:, 5] - legs[:, 4]) * value, atol=1e-6)
    assert counts[0] == counts[1:5].sum() and counts[0] + counts[5] == len(signals)
    if finish:
        assert position[-1] == 0 and counts[1] == len(legs) and counts[5] == 0
        np.testing.assert_allclose(curve[-1], pnl.sum(), atol=1e-6)
        np.testing.assert_allclose(w_curve[-1], ws.sum(), atol=1e-6)
    return dict(session=ready['session'], symbol=ready['symbol'], orders=orders.tolist(), trades=legs.tolist(),
                width_groups=groups.tolist(), curve=curve, w_curve=w_curve,
                candidate_count=len(signals), candidate_audit=dict(zip(
                    ('consumed', 'accepted', 'occupied', 'cutoff', 'cooldown', 'unreached'), map(int, counts))),
                profit=float(pnl[pnl > 0].sum()), loss=float(-pnl[pnl < 0].sum()), net=float(pnl.sum()),
                win_qty=int((pnl > 0).sum() * qty), loss_qty=int((pnl < 0).sum() * qty), flat_qty=int((pnl == 0).sum() * qty),
                cycles=len(pnl), wins=int((pnl > 0).sum()), losses=int((pnl < 0).sum()),
                w_net=float(ws.sum()), w_profit=float(ws[ws > 0].sum()), w_loss=float(-ws[ws < 0].sum()),
                drawdown=float(np.max(np.maximum.accumulate(np.r_[0., curve])[1:] - curve, initial=0)),
                w_drawdown=float(np.max(np.maximum.accumulate(np.r_[0., w_curve])[1:] - w_curve, initial=0)))
