"""段階トレーリング新規と玉別利確を、残損失も含む場内会計へ写す。"""

import math
import os
from pathlib import Path

import numpy as np

os.environ.setdefault('NUMBA_CACHE_DIR', str(Path(__file__).resolve().parent / 'numba_runtime'))
from numba import njit


ORDER_COLUMNS = ('uid', 'kind', 'side', 'decision_row', 'fill_row', 'decision_time', 'fill_time',
                 'price', 'fee', 'reason', 'rung', 'quantity', 'decision_mid', 'fill_last',
                 'fill_bid', 'fill_ask', 'net', 'trigger_price')
LOT_COLUMNS = ('uid', 'side', 'rung', 'entry_decision_row', 'entry_row', 'entry_time', 'entry_price',
               'exit_decision_row', 'exit_row', 'exit_time', 'exit_price', 'gross', 'fees', 'net',
               'reason', 'mfe', 'mae', 'entry_last', 'exit_last')
CURVE_COLUMNS = ('row', 'time', 'equity', 'cash', 'realized_net', 'long', 'short', 'drawdown')
SUMMARY_COLUMNS = ('net', 'cash', 'profit', 'loss', 'fees', 'closed_lots', 'wins', 'losses', 'unclosed',
                   'max_long', 'max_short', 'max_drawdown', 'min_equity', 'entries', 'canceled',
                   'clock_rejected', 'step', 'held_entry_fees', 'last_equity', 'last_time')
REASONS = {1: '利益玉の個別追尾', 2: '反対注文を返済へ', 3: '反転して持替え',
           4: '利益準備金で損失玉整理', 5: '個別初期停止', 7: '同方向全玉の返済対照',
           8: '方向別の固定合計損失停止', 9: '場内時刻返済'}


@njit(cache=False, boundscheck=True)
def push(table, count, values):
    """
    機能: 必要な分だけ拡張して注文又は玉の証跡を追記する。
    引数: table(float二次元配列)、count(int)、values(float一次元配列)。
    返り値: tuple[配列,int]。全気配数×最大玉数の巨大な先行確保を避ける。
    """
    if count == len(table):
        expanded = np.empty((max(8, count * 2), table.shape[1]), np.float64)
        expanded[:count] = table
        table = expanded
    table[count] = values
    return table, count + 1


@njit(cache=False, boundscheck=True)
def replay(rows, times, last, bid, ask, cap, multiplier, fee, observed_tick,
           fraction, mode, trail, session_start, entry_end, close_time, session_end):
    """
    機能: 二方向の独立追尾注文・玉別返済・枠再利用を原行順で逐次実行する。
    引数: rows(int配列)、times/last/bid/ask(float配列)は保存正常気配。
        cap/mode(int)、multiplier/fee/observed_tick/fraction/trail/各時刻(float)。
        modeは0両建て、1反対を返済、2反転、3利益整理、4個別停止、5極値追尾なし、
        6再利用なし、7利益玉追尾の成立時に同方向全玉を返済。
        8利益条件追加と方向別合計停止、9片方向限定、10新規価格限定、11広気配回避。
    返り値: tuple[orders,lots,curve,summary]。約定は必ず判断より後の原行気配。
        一枚ごと別注文。利確判断後の値飛びも実損失として残し、EOFを返済時刻にしない。
    """
    state = np.zeros((2, cap), np.int8)  # 0待機、1新規予約、2保有、3返済予約
    anchor = np.zeros((2, cap))
    price = np.zeros((2, cap))
    uid = np.zeros((2, cap), np.int64)
    drow = np.zeros((2, cap), np.int64)
    dtime = np.zeros((2, cap))
    dmid = np.zeros((2, cap))
    trigger = np.zeros((2, cap))
    entry_limit = np.zeros((2, cap))
    erow = np.zeros((2, cap), np.int64)
    edrow = np.zeros((2, cap), np.int64)
    etime = np.zeros((2, cap))
    elast = np.zeros((2, cap))
    peak = np.zeros((2, cap))
    trough = np.zeros((2, cap))
    why = np.zeros((2, cap), np.int8)
    armed = np.zeros((2, cap), np.bool_)
    disabled = np.zeros((2, cap), np.bool_)
    orders = np.empty((2048, 18))
    lots = np.empty((1024, 19))
    curve = np.empty((2048, 8))
    oc = lc = cc = 0
    sequence = entries = canceled = rejected = wins = losses = 0
    cash = realized = profit = loss = paid = high = maxdd = mineq = 0.
    maxlong = maxshort = 0
    first = True
    lastclock = -np.inf
    curveclock = -np.inf
    step = np.nan
    equity = 0.
    fee_one = math.floor(fee + 1e-9)
    lastrow, lasttime = -1, np.nan
    lastbid = lastask = np.nan
    previous_mid = np.nan
    for i in range(len(rows)):
        now, raw = times[i], rows[i]
        if not math.isfinite(now) or now < session_start or now > session_end or now < lastclock:
            rejected += 1
            continue
        if not (math.isfinite(bid[i]) and math.isfinite(ask[i]) and 0 < bid[i] <= ask[i]):
            rejected += 1
            continue
        lastclock = now
        lastrow, lasttime, lastbid, lastask = raw, now, bid[i], ask[i]
        mid = (bid[i] + ask[i]) * .5
        reference = last[i]
        if first:
            step = max(observed_tick, math.floor(mid * fraction / observed_tick + .5) * observed_tick)
            anchor[:, :] = reference
            previous_mid = reference
            first = False
        held_before = np.zeros(2, np.int64)
        if mode >= 8:
            for s in range(2):
                held_before[s] = np.count_nonzero(state[s] >= 2)
        # ----------------------------------------
        # 後続気配で既発注を実行する。返済を先に処理し、新規の同原行返済をしない。
        for s in range(2):
            side = 1 if s == 0 else -1
            xp = bid[i] if side == 1 else ask[i]
            for j in range(cap):
                if state[s, j] == 3 and raw > drow[s, j]:
                    gross = side * (xp - price[s, j]) * multiplier
                    net = gross - 2 * fee_one
                    cash += gross - fee_one
                    realized += net
                    paid += fee_one
                    profit += max(0., net)
                    loss += max(0., -net)
                    wins += int(net > 0.)
                    losses += int(net < 0.)
                    orders, oc = push(orders, oc, np.array([uid[s, j], 2., -side, drow[s, j], raw,
                        dtime[s, j], now, xp, fee_one, why[s, j], j, 1., dmid[s, j], last[i],
                        bid[i], ask[i], net, trigger[s, j]]))
                    lots, lc = push(lots, lc, np.array([uid[s, j], side, j, edrow[s, j], erow[s, j],
                        etime[s, j], price[s, j], drow[s, j], raw, now, xp, gross, 2 * fee_one, net,
                        why[s, j], max(peak[s, j], net), min(trough[s, j], net), elast[s, j], last[i]]))
                    state[s, j] = 0
                    if mode == 6:
                        disabled[s, j] = True
                    anchor[s, j] = reference
                    armed[s, j] = False
        for s in range(2):
            side = 1 if s == 0 else -1
            for j in range(cap):
                if state[s, j] != 1:
                    continue
                if now >= entry_end:
                    state[s, j] = 0
                    anchor[s, j] = reference
                    canceled += 1
                elif raw > drow[s, j]:
                    actual_price = ask[i] if side == 1 else bid[i]
                    affordable = actual_price <= entry_limit[s, j] if side == 1 else actual_price >= entry_limit[s, j]
                    if mode >= 10 and (not affordable or (mode == 11 and ask[i]-bid[i] > step)):
                        state[s, j] = 0
                        anchor[s, j] = reference
                        canceled += 1
                        continue
                    sequence += 1
                    entries += 1
                    uid[s, j] = sequence
                    price[s, j] = ask[i] if side == 1 else bid[i]
                    erow[s, j], edrow[s, j], etime[s, j] = raw, drow[s, j], now
                    elast[s, j] = last[i]
                    cash -= fee_one
                    paid += fee_one
                    initial = side * ((bid[i] if side == 1 else ask[i]) - price[s, j]) * multiplier - 2 * fee_one
                    peak[s, j], trough[s, j] = initial, initial
                    state[s, j] = 2
                    armed[s, j] = False
                    orders, oc = push(orders, oc, np.array([sequence, 1., side, drow[s, j], raw,
                        dtime[s, j], now, price[s, j], fee_one, 0., j, 1., dmid[s, j], last[i],
                        bid[i], ask[i], 0., trigger[s, j]]))
        if mode >= 8:
            for s in range(2):
                if held_before[s] > 0 and not np.any(state[s] >= 2):
                    for j in range(cap):
                        if state[s, j] == 0:
                            anchor[s, j] = reference
        # ----------------------------------------
        # 全残玉を返済側気配と未払返済料で評価する。利益玉だけの現金を成績にしない。
        equity = cash
        countlong = countshort = 0
        for s in range(2):
            side = 1 if s == 0 else -1
            xp = bid[i] if side == 1 else ask[i]
            for j in range(cap):
                if state[s, j] < 2:
                    continue
                countlong += int(s == 0)
                countshort += int(s == 1)
                net = side * (xp - price[s, j]) * multiplier - 2 * fee_one
                peak[s, j] = max(peak[s, j], net)
                trough[s, j] = min(trough[s, j], net)
                equity += net + fee_one
                if state[s, j] == 3:
                    continue
                reason = 0
                if now >= close_time:
                    reason = 9
                elif mode == 4 and net <= -3. * step * multiplier:
                    reason = 5
                else:
                    if peak[s, j] >= (trail + 1.) * step * multiplier:
                        armed[s, j] = True
                    if armed[s, j] and net > 0. and peak[s, j] - net >= trail * step * multiplier:
                        reason = 1
                if reason == 1 and mode == 7:
                    reason = 7
                    for k in range(cap):
                        if state[s, k] == 2:
                            state[s, k], why[s, k] = 3, 7
                            drow[s, k], dtime[s, k], dmid[s, k], trigger[s, k] = raw, now, mid, xp
                if reason:
                    state[s, j], why[s, j] = 3, reason
                    drow[s, j], dtime[s, j], dmid[s, j], trigger[s, j] = raw, now, mid, xp
        maxlong, maxshort = max(maxlong, countlong), max(maxshort, countshort)
        high, mineq = max(high, equity), min(mineq, equity)
        maxdd = max(maxdd, high - equity)
        if now >= curveclock + 60.:
            curve, cc = push(curve, cc, np.array([raw, now, equity, cash, realized, countlong, countshort, high - equity]))
            curveclock = now
        # ----------------------------------------
        # 新規を利益で支える型は、玉別ではなく方向別の全清算損失を一枚分の三単位で止める。
        if mode >= 8:
            for s in range(2):
                side = 1 if s == 0 else -1
                xp = bid[i] if side == 1 else ask[i]
                side_net = 0.
                for j in range(cap):
                    if state[s, j] >= 2:
                        side_net += side * (xp-price[s, j]) * multiplier - 2 * fee_one
                if side_net <= -3. * step * multiplier:
                    for j in range(cap):
                        if state[s, j] == 2:
                            state[s, j], why[s, j] = 3, 8
                            drow[s, j], dtime[s, j], dmid[s, j], trigger[s, j] = raw, now, mid, xp
                        elif state[s, j] == 1:
                            state[s, j], anchor[s, j] = 0, reference
                            canceled += 1
                        else:
                            anchor[s, j] = reference
        # ----------------------------------------
        # 確定利益の半分以内で最悪損失玉一枚を整理する。準備金の使用は実返済後に反映する。
        if mode == 3 and now < close_time and realized > 0.:
            worst, ws, wj = 0., -1, -1
            for s in range(2):
                side = 1 if s == 0 else -1
                xp = bid[i] if side == 1 else ask[i]
                for j in range(cap):
                    if state[s, j] == 2:
                        net = side * (xp - price[s, j]) * multiplier - 2 * fee_one
                        if net < worst:
                            worst, ws, wj = net, s, j
            if ws >= 0 and realized >= -2. * worst:
                state[ws, wj], why[ws, wj] = 3, 4
                drow[ws, wj], dtime[ws, wj], dmid[ws, wj], trigger[ws, wj] = raw, now, mid, mid
        move = reference - previous_mid
        previous_mid = reference
        if now >= entry_end:
            continue
        # ----------------------------------------
        # 空き玉枠だけで極値を更新。固定rungは3,4,5...、約定又は返済で当該枠だけ再準備する。
        for s in range(2):
            side, other = (1 if s == 0 else -1), 1 - s
            for j in range(cap):
                if state[s, j] != 0 or disabled[s, j]:
                    continue
                if mode >= 9 and np.any(state[other] != 0):
                    anchor[s, j] = reference
                    continue
                if mode == 11 and ask[i]-bid[i] > step:
                    continue
                if mode != 5:
                    anchor[s, j] = min(anchor[s, j], reference) if side == 1 else max(anchor[s, j], reference)
                line = anchor[s, j] + side * (3. + j) * step
                crossed = reference >= line and move > 0. if side == 1 else reference <= line and move < 0.
                if not crossed:
                    continue
                if mode >= 8:
                    pending_count = 0
                    held_count = 0
                    liquid_net = 0.
                    closing = False
                    for k in range(cap):
                        pending_count += int(state[s, k] == 1)
                        if state[s, k] >= 2:
                            held_count += 1
                            liquid_net += side * ((bid[i] if side == 1 else ask[i])-price[s,k]) * multiplier - 2*fee_one
                        closing = closing or state[s,k] == 3
                    if closing:
                        continue
                    if held_count == 0:
                        if pending_count:
                            continue
                    elif liquid_net < 3. * step * multiplier * (pending_count+1):
                        continue
                if mode == 1:
                    worst, target, opposite = np.inf, -1, False
                    for k in range(cap):
                        if state[other, k] >= 2:
                            opposite = True
                            if state[other, k] == 2:
                                xp = ask[i] if side == 1 else bid[i]
                                net = -side * (xp - price[other, k]) * multiplier - 2 * fee_one
                                if net < worst:
                                    worst, target = net, k
                    if opposite:
                        if target >= 0:
                            state[other, target], why[other, target] = 3, 2
                            drow[other, target], dtime[other, target] = raw, now
                            dmid[other, target], trigger[other, target] = mid, line
                        anchor[s, j] = reference
                        continue
                elif mode == 2:
                    for k in range(cap):
                        if state[other, k] == 1:
                            state[other, k], anchor[other, k] = 0, reference
                            canceled += 1
                        elif state[other, k] == 2:
                            state[other, k], why[other, k] = 3, 3
                            drow[other, k], dtime[other, k] = raw, now
                            dmid[other, k], trigger[other, k] = mid, line
                state[s, j] = 1
                drow[s, j], dtime[s, j], dmid[s, j], trigger[s, j] = raw, now, mid, line
                entry_limit[s, j] = ask[i]+observed_tick if side == 1 else bid[i]-observed_tick
    # ----------------------------------------
    # 最終行で架空返済しない。残玉は未清算として明示し、実現利益と時価を分ける。
    remaining = 0
    for s in range(2):
        for j in range(cap):
            remaining += int(state[s, j] >= 2)
            canceled += int(state[s, j] == 1)
    if lastrow >= 0:
        curve, cc = push(curve, cc, np.array([lastrow, lasttime, equity, cash, realized,
            np.count_nonzero(state[0] >= 2), np.count_nonzero(state[1] >= 2), high - equity]))
    summary = np.array([equity, cash, profit, loss, paid, lc, wins, losses, remaining,
        maxlong, maxshort, maxdd, mineq, entries, canceled, rejected, step,
        remaining * fee_one, equity, lasttime])
    return orders[:oc], lots[:lc], curve[:cc], summary
