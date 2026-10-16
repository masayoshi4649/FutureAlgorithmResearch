"""順行逆指値・価格反転による返済・ドテンを逐次再生する。"""
from pathlib import Path
import sys
import math
import numpy as np
from numba import njit

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from work.wave_v83.engine import send_entry, send_exit, fill_orders


@njit(cache=True, inline='always')
def after_exit(trades, nt, family, p, pvalid, i):
    """
    機能: 実際に返済できた後の待機方針を決める。
    引数: trades(ndarray)、nt/family/i(int)、p(float)、pvalid(bool)。
    返り値: tuple[int,float,bool,int,int]。再入場方針、基準、基準有効、方向、基準行。
    """
    row = trades[nt - 1]
    opposite = -int(row[3])
    reason = int(row[12])
    mode = 0
    if reason != 6:
        if family == 3 or (family == 5 and row[10] > 0):
            mode = 1
        elif family == 4:
            mode = 2
    return mode, p, pvalid, opposite, i


@njit(cache=True, nogil=True)
def run(record, family, width_ticks, variant, cap, pointvalue, fee,
        delay=0.0, seed=0, slip_ticks=0.0):
    """
    機能: 一方向一建玉で、価格条件と返済完了を確認して売買する。
    引数: record(tuple)はv83 data.as_tuple、family/width_ticks/variant/cap/seed(int)、
          pointvalue/fee/delay/slip_ticks(float)。今回は追加遅延0に限定する。
    返り値: tuple[ndarray,...]。注文16列・決済14列・時価・統計14列・イベント12列。
    """
    assert delay == 0.0
    times, prices, bids, asks, seq, source_i, pok, qok, tick, start, end, limit = record
    n = len(times)
    allocation = max(1024, 2 * n + 64)
    slots = np.zeros((1, 21), np.float64)
    orders = np.zeros((allocation, 16), np.float64)
    trades = np.zeros((allocation, 14), np.float64)
    events = np.zeros((2 * allocation, 12), np.float64)
    cursor = np.zeros(1, np.int64)
    stats = np.zeros(14, np.float64)
    curve = np.zeros(n, np.float64)
    no = 0
    nt = 0
    cash = 0.0
    ticket = 1
    cycle = 0
    width = tick * width_ticks
    exit_width = width * (0.5 if variant == 0 else (1.0 if variant == 1 else 2.0))
    anchor = 0.0
    anchor_valid = False
    anchor_i = -1
    reentry_mode = 0
    next_side = 0
    closing = False
    previous_price = np.nan
    pending_evaluation = False
    last_bid = np.nan
    last_ask = np.nan
    force_time = limit - 60.0
    no_entry_time = limit - 120.0
    base_side = 0
    base_price = 0.0
    base_best = 0.0
    last_add = 0.0
    flatten = False
    flatten_reason = 0

    # ----------------------------------------
    for i in range(n):
        t = times[i]
        p = prices[i]
        if qok[i]:
            last_bid = bids[i]
            last_ask = asks[i]
        if not closing and t >= force_time:
            closing = True
            if slots[0, 0] == 2:
                send_exit(slots, events, cursor, 0, i - 1, force_time, 0., 6)
        before_trades = nt
        changed = False
        if qok[i]:
            no, nt, cash, changed, base_side, base_price, base_best, last_add, flatten, flatten_reason = fill_orders(
                slots, events, cursor, orders, trades, stats, 1, allocation,
                i, t, bids[i], asks[i], tick, slip_ticks, pointvalue, fee, -1, 0.,
                no, nt, cash, base_side, base_price, base_best, last_add, flatten, flatten_reason)
        pending_evaluation = pending_evaluation or changed
        exited_at_start = nt > before_trades
        if exited_at_start:
            reentry_mode, anchor, anchor_valid, next_side, anchor_i = after_exit(trades, nt, family, p, pok[i], i)

        # 返済未約定の間は保有したまま。反対新規を先に出さない。
        if closing and slots[0, 0] == 2:
            send_exit(slots, events, cursor, 0, i, t, 0., 6)
        decision_event = pok[i] and (p != previous_price or pending_evaluation or slots[0, 0] == 0)
        if decision_event:
            pending_evaluation = False
            previous_price = p
            if slots[0, 0] == 2 and not closing:
                side = int(slots[0, 1])
                entry = slots[0, 3]
                if side * (p - slots[0, 7]) > 0:
                    slots[0, 7] = p
                reason = 0
                if side * (p - entry) <= -exit_width:
                    reason = 1
                elif family <= 1 and side * (p - entry) >= 3 * exit_width:
                    reason = 2
                elif family >= 2 and side * (slots[0, 7] - p) >= exit_width:
                    reason = 3
                if reason:
                    send_exit(slots, events, cursor, 0, i, t, 0., reason)
            elif slots[0, 0] == 0 and not closing and t < no_entry_time:
                if not anchor_valid:
                    anchor = p
                    anchor_i = i
                    anchor_valid = True
                direction = 0
                if reentry_mode == 1:
                    direction = next_side
                elif i > anchor_i:
                    if reentry_mode == 2:
                        if next_side * (p - anchor) >= width:
                            direction = next_side
                        elif next_side * (p - anchor) <= -width:
                            reentry_mode = 0
                            anchor = p
                            anchor_i = i
                    elif p >= anchor + width:
                        direction = -1 if family == 0 else 1
                    elif p <= anchor - width:
                        direction = 1 if family == 0 else -1
                if direction != 0:
                    cycle += 1
                    reason = 21 if reentry_mode == 1 else (22 if reentry_mode == 2 else 20)
                    ticket = send_entry(slots, events, cursor, stats, 0, direction, cap, i, t, 0., 0., 0,
                                        exit_width, 3 * exit_width if family <= 1 else 0.,
                                        exit_width if family >= 2 else 0., 0., reason, ticket, cycle)
                    reentry_mode = 0

        # ----------------------------------------
        before_trades = nt
        if qok[i]:
            no, nt, cash, changed, base_side, base_price, base_best, last_add, flatten, flatten_reason = fill_orders(
                slots, events, cursor, orders, trades, stats, 1, allocation,
                i, t, bids[i], asks[i], tick, slip_ticks, pointvalue, fee, -1, 0.,
                no, nt, cash, base_side, base_price, base_best, last_add, flatten, flatten_reason)
            pending_evaluation = pending_evaluation or changed
        if nt > before_trades:
            reentry_mode, anchor, anchor_valid, next_side, anchor_i = after_exit(trades, nt, family, p, pok[i], i)
            if reentry_mode == 1 and pok[i] and not closing and t < no_entry_time:
                # 実返済後だけ反対玉を建てる。この行で新玉の返済条件を再評価しない。
                cycle += 1
                ticket = send_entry(slots, events, cursor, stats, 0, next_side, cap, i, t, 0., 0., 0,
                                    exit_width, 0., exit_width, 0., 21, ticket, cycle)
                reentry_mode = 0
                no, nt, cash, changed, base_side, base_price, base_best, last_add, flatten, flatten_reason = fill_orders(
                    slots, events, cursor, orders, trades, stats, 1, allocation,
                    i, t, bids[i], asks[i], tick, slip_ticks, pointvalue, fee, -1, 0.,
                    no, nt, cash, base_side, base_price, base_best, last_add, flatten, flatten_reason)
                pending_evaluation = pending_evaluation or changed

        # ----------------------------------------
        status = int(slots[0, 0])
        equity = cash
        stats[4:8] = 0.
        if status != 0:
            side = int(slots[0, 1])
            quantity = int(slots[0, 2])
            if status == 1:
                stats[6] = quantity
            else:
                liquidation = last_bid - slip_ticks * tick if side == 1 else last_ask + slip_ticks * tick
                equity += side * quantity * liquidation * pointvalue - math.floor(quantity * fee + 1e-8)
                stats[4 if side == 1 else 5] = quantity
                if status == 3:
                    stats[7] = quantity
        assert stats[2] <= cap and stats[3] <= cap
        assert stats[11] <= cap
        curve[i] = equity
    return orders[:no].copy(), trades[:nt].copy(), curve, stats, events[:cursor[0]].copy()
