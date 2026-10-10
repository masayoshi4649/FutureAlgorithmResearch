"""現在の方向指示だけを受け取る、研究用の場内約定・会計エンジン。"""

from __future__ import annotations

import numpy as np
from numba import njit


REASONS = {0: '新規', 1: '損切り', 2: '利益追跡', 3: '根拠消失', 4: '反対根拠',
           5: '時間上限', 6: '進展不足', 8: '場内返済'}


@njit(cache=True)
def drive(times: np.ndarray, sequences: np.ndarray, prices: np.ndarray, atrs: np.ndarray,
          decisions: np.ndarray, params: np.ndarray, limit: float, finish: bool) -> tuple:
    """機能: 原本を順に渡し、判断の次の有効行で約定・返済する。

    引数: times/sequences/prices/atrs(ndarray)、decisions(ndarray:行位置・方向)、
    params(ndarray:数量・倍率・損切・追跡開始・幅・時間上限・中立返済・不発時間・不発幅・休止秒)、
    limit(float:場内返済判断時刻)、finish(bool:場末検査)。
    返り値: 注文・返済・最終純保有・実現額・時価最大下落(tuple)。
    方向指示の作成・選択はこの関数の機能に含めない。
    """
    orders = np.zeros((40000, 10))
    trades = np.zeros((20000, 16))
    no = nt = cursor = 0
    side = 0
    entry = entry_time = entry_atr = best = 0.
    entry_seq = -1
    pending = 0
    pending_side = 0
    decision_time = decision_seq = decision_atr = 0.
    reason = 0
    realized = peak = drawdown = 0.
    next_entry = 0.
    for i in range(len(prices)):
        price, now, seq = prices[i], times[i], sequences[i]
        if not np.isfinite(price) or price <= 0:
            continue
        # ----------------------------------------
        # 前の行までに決めた指示を、現在の価格で実行する。
        if pending == 1:
            side = pending_side
            entry, entry_time, entry_atr, entry_seq, best = price, now, decision_atr, seq, price
            orders[no] = np.array([decision_time, now, decision_seq, float(seq), 1., float(side), params[0], price, 0., 0.])
            no += 1
            pending = 0
        elif pending == 2:
            best = max(best, price) if side > 0 else min(best, price)
            pnl = side * (price - entry) * params[0] * params[1]
            orders[no] = np.array([decision_time, now, decision_seq, float(seq), 2., float(-side), params[0], price, pnl, float(reason)])
            no += 1
            trades[nt] = np.array([entry_time, now, float(side), params[0], entry, price, pnl,
                                  float(reason), entry_atr, 0., decision_time, float(entry_seq), float(seq),
                                  decision_seq, max(0., side * (best - entry) / entry_atr), (now - entry_time) / 60.])
            nt += 1
            realized += pnl
            side = pending = 0
            next_entry = now + params[9]
        assert no < 40000 and nt < 20000
        equity = realized + side * (price - entry) * params[0] * params[1]
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        # ----------------------------------------
        # すでに保有している時だけ、原本価格で保護条件を判定する。
        if side:
            best = max(best, price) if side > 0 else min(best, price)
            progress = side * (price - entry) / entry_atr
            maximum = side * (best - entry) / entry_atr
            reason = 0
            if now >= limit:
                reason = 8
            elif params[2] > 0 and progress <= -params[2]:
                reason = 1
            elif params[3] > 0 and maximum >= params[3] and side * (best - price) / entry_atr >= params[4]:
                reason = 2
            elif params[5] > 0 and now - entry_time >= params[5]:
                reason = 5
            elif params[7] > 0 and now - entry_time >= params[7] and maximum < params[8]:
                reason = 6
            if reason:
                pending = 2
                decision_time, decision_seq = now, float(seq)
        # ----------------------------------------
        # 現在までに届いた方向指示だけを処理し、先の指示は読まない。
        while cursor < len(decisions) and int(decisions[cursor, 0]) <= i:
            signal = int(decisions[cursor, 1])
            cursor += 1
            if pending:
                continue
            if side:
                if signal == -side or (signal == 0 and params[6] > 0):
                    pending = 2
                    reason = 4 if signal == -side else 3
                    decision_time, decision_seq = now, float(seq)
            elif signal and now < limit - 300 and now >= next_entry and np.isfinite(atrs[i]) and atrs[i] > 0:
                pending, pending_side = 1, signal
                decision_time, decision_seq, decision_atr = now, float(seq), atrs[i]
    if finish and (side != 0 or pending != 0):
        raise ValueError('場内返済に必要な後続価格がありません')
    return orders[:no], trades[:nt], side, realized, drawdown


def execute(ready: dict, decisions: np.ndarray, spec: dict, finish: bool = True) -> dict:
    """機能: 中立の再生器へ設定を渡し、注文と損益を独立に照合する。

    引数: ready(dict:保存入力)、decisions(ndarray:原本配列位置・方向)、spec(dict)、finish(bool)。
    返り値: 場別会計・台帳・時価曲線(dict)。
    """
    qty, value = (5, 1000) if ready['symbol'] == 'TOPIX' else (10, 10)
    params = np.array([qty, value, spec['stop_atr'], spec['activation_atr'], spec['trail_atr'],
                       spec['hold_seconds'], int(spec['exit_neutral']), spec['failure_seconds'],
                       spec['failure_atr'], spec['cooldown_seconds']], float)
    decisions = np.asarray(decisions, float).reshape(-1, 2)
    if len(decisions):
        assert np.all(np.diff(decisions[:, 0]) > 0)
        assert np.isin(decisions[:, 1], [-1, 0, 1]).all()
    orders, trades, side, realized, drawdown = drive(ready['time_s'], ready['seq'], ready['last'], ready['atr'],
                                                   decisions, params, ready['limit'], finish)
    cash = np.zeros(len(ready['last']))
    position_delta = np.zeros_like(cash)
    for order in orders:
        idx = int(np.searchsorted(ready['seq'], int(order[3])))
        assert ready['seq'][idx] == order[3] and order[2] < order[3] and order[0] <= order[1]
        cash[idx] -= order[5] * order[6] * order[7] * value
        position_delta[idx] += order[5] * order[6]
    position = np.cumsum(position_delta)
    curve = np.cumsum(cash) + position * ready['last'] * value
    assert np.max(abs(position), initial=0) <= qty
    if finish:
        assert side == 0 and position[-1] == 0
        np.testing.assert_allclose(curve[-1], realized, rtol=0, atol=1e-6)
    pnl = trades[:, 6]
    np.testing.assert_allclose(pnl, trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4]) * value, rtol=0, atol=1e-7)
    np.testing.assert_allclose(pnl.sum(), realized, rtol=0, atol=1e-6)
    wins, losses, zeros = pnl > 0, pnl < 0, pnl == 0
    return dict(session=ready['session'], symbol=ready['symbol'], orders=orders.tolist(), trades=trades.tolist(),
                curve=curve, profit=float(pnl[wins].sum()), loss=float(-pnl[losses].sum()), net=float(realized),
                win_qty=int(trades[wins, 3].sum()), loss_qty=int(trades[losses, 3].sum()), flat_qty=int(trades[zeros, 3].sum()),
                cycles=len(trades), wins=int(wins.sum()), losses=int(losses.sum()), drawdown=drawdown)
