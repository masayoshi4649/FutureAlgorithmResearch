"""有限段グリッドを原本順に運用し、週内持越しと実注文単位の費用を会計する。"""

from __future__ import annotations

import numpy as np
from numba import njit

from accounting import order_fee


REASONS = {0:'格子新規',1:'場内清算',2:'当場損失予算',3:'資産下落予算',4:'逆玉整理',5:'カバー新規',6:'カバー方向終了',7:'カバー追跡返済',8:'段利確',9:'個別損切り',10:'順行追跡',11:'個別保有期限',12:'カバー組期限',13:'カバー組損切り',14:'在庫FIFO返済'}
ORDER_COLUMNS = ['order_id', 'decision_index', 'fill_index', 'decision_time', 'fill_time',
                 'decision_session', 'fill_session', 'decision_seq', 'fill_seq', 'kind', 'side',
                 'qty', 'price', 'fee', 'gross_pnl', 'reason', 'cycle', 'slot', 'role', 'delta']
TRADE_COLUMNS = ['trade_id', 'slot', 'role', 'side', 'qty', 'entry_order', 'exit_order', 'entry_index',
                 'exit_index', 'entry_time', 'exit_time', 'entry_session', 'exit_session', 'entry_price',
                 'exit_price', 'gross_pnl', 'entry_fee', 'exit_fee', 'net_pnl', 'reason', 'cycle',
                 'delta', 'hold_minutes']
# 建玉列: 方向、枚数、建値、入口費用、有効行、注文番号、場番号、返済気配の有利極値、cycle、役割。


@njit(cache=True)
def append_row(rows: np.ndarray, count: int, row: np.ndarray) -> np.ndarray:
    """機能: 注文・返済台帳の容量を必要時だけ倍増する。

    引数: rows/row(ndarray)、count(int)。返り値: 追記後の配列(ndarray)。
    """
    if count >= len(rows):
        larger = np.zeros((max(16, len(rows) * 2), rows.shape[1]))
        larger[:len(rows)] = rows
        rows = larger
    rows[count] = row
    return rows


@njit(cache=True)
def execution_price(side: int, i: int, mid: np.ndarray, bid: np.ndarray, ask: np.ndarray, mode: int) -> float:
    """機能: 現在の観測値から、その売買方向の約定価格を選ぶ。

    引数: side/i/mode(int)、mid/bid/ask(ndarray)。返り値: 中値参考又は買ask・売bid(float)。
    """
    return mid[i] if mode == 1 else (ask[i] if side > 0 else bid[i])


@njit(cache=True)
def liquidation_price(side: int, i: int, mid: np.ndarray, bid: np.ndarray, ask: np.ndarray, mode: int) -> float:
    """機能: 建玉を今返済する側の価格を求める。

    引数: side/i/mode(int)、mid/bid/ask(ndarray)。返り値: 買玉bid・売玉ask又は中値(float)。
    """
    return mid[i] if mode == 1 else (bid[i] if side > 0 else ask[i])


@njit(cache=True)
def open_slot(pos: np.ndarray, slot: int, side: int, quantity: int, price: float, decision: int, i: int,
              role: int, reason: int, cycle: int, delta: float, fee_tenths: int, value: float,
              times: np.ndarray, seqs: np.ndarray, sessions: np.ndarray, liquidation: float,
              orders: np.ndarray, oc: int, book: np.ndarray) -> tuple:
    """機能: 一段又はカバーを一注文で建て、注文費用をその時点で計上する。

    引数: 建玉・時刻・場・台帳・会計のndarray群、数量/行/役割/理由/cycle/fee_tenths/oc(int)、価格等(float)。
    返り値: 注文配列と注文件数(tuple)。bookは現金・費用・粗利益・粗損失を更新する。
    """
    assert pos[slot, 1] == 0 and quantity > 0 and i > decision
    fee = order_fee(quantity, fee_tenths)
    row = np.array([oc, decision, i, times[decision], times[i], sessions[decision], sessions[i],
                    seqs[decision], seqs[i], 1., side, quantity, price, fee, 0., reason, cycle, slot, role, delta])
    orders = append_row(orders, oc, row)
    pos[slot] = np.array([side, quantity, price, fee, i, oc, sessions[i], liquidation, cycle, role])
    book[0] -= side * quantity * price * value + fee
    book[1] += fee
    return orders, oc + 1


@njit(cache=True)
def close_slots(pos: np.ndarray, selected: np.ndarray, price: float, decision: int, i: int,
                reason: int, delta: float, fee_tenths: int, value: float,
                times: np.ndarray, seqs: np.ndarray, sessions: np.ndarray,
                orders: np.ndarray, oc: int, trades: np.ndarray, tc: int, book: np.ndarray) -> tuple:
    """機能: 指定した同方向の建玉を一注文で返済し、費用を数量比例で各玉へ配分する。

    引数: 建玉・選択・時刻・場・台帳・会計のndarray群、行/理由/fee_tenths/件数(int)、価格等(float)。
    返り値: 注文配列・件数・返済配列・件数(tuple)。配分残差は最後の玉へ付け総費用を保存する。
    """
    quantity = 0
    last = -1
    side = 0
    role = -1
    cycle = -1
    gross = 0.
    count = 0
    for j in range(len(pos)):
        if selected[j] and pos[j, 1] > 0:
            assert side == 0 or side == int(pos[j, 0])
            side = int(pos[j, 0])
            quantity += int(pos[j, 1])
            gross += side * pos[j, 1] * (price - pos[j, 2]) * value
            role = int(pos[j, 9]) if role == -1 else (role if role == int(pos[j, 9]) else 2)
            cycle = int(pos[j, 8])
            last, count = j, count + 1
    assert quantity > 0 and i > decision
    fee = order_fee(quantity, fee_tenths)
    row = np.array([oc, decision, i, times[decision], times[i], sessions[decision], sessions[i],
                    seqs[decision], seqs[i], 2., -side, quantity, price, fee, gross, reason, cycle,
                    last if count == 1 else -1, role, delta])
    orders = append_row(orders, oc, row)
    allocated = 0.
    for j in range(len(pos)):
        if not selected[j] or pos[j, 1] <= 0:
            continue
        p = pos[j]
        exit_fee = fee - allocated if j == last else fee * p[1] / quantity
        allocated += exit_fee
        amount = side * p[1] * (price - p[2]) * value
        net = amount - p[3] - exit_fee
        if abs(net) < 1e-8:
            net = 0.
        trade = np.array([tc, j, p[9], side, p[1], p[5], oc, p[4], i, times[int(p[4])], times[i],
                          p[6], sessions[i], p[2], price, amount, p[3], exit_fee, net, reason, p[8], delta,
                          (times[i] - times[int(p[4])]) / 60.])
        trades = append_row(trades, tc, trade)
        tc += 1
        book[2] += max(0., amount)
        book[3] += max(0., -amount)
        pos[j, 1] = 0.
    assert abs(allocated - fee) < 1e-8
    book[0] += side * quantity * price * value - fee
    book[1] += fee
    return orders, oc + 1, trades, tc


@njit(cache=True)
def inventory(pos: np.ndarray, i: int, mid: np.ndarray, bid: np.ndarray, ask: np.ndarray,
              mode: int, value: float, cash: float) -> tuple:
    """機能: 全建玉を返済可能価格で評価し、相殺前の数量と片側含み損も求める。

    引数: pos/mid/bid/ask(ndarray)、i/mode(int)、value/cash(float)。
    返り値: 清算時価、中値時価、買枚数、売枚数、買含み、売含み、負け玉含み合計(tuple)。
    """
    equity, mid_equity = cash, cash
    long_qty = short_qty = 0
    long_pnl = short_pnl = losing = 0.
    for j in range(len(pos)):
        if pos[j, 1] <= 0:
            continue
        side, quantity = int(pos[j, 0]), int(pos[j, 1])
        mark = liquidation_price(side, i, mid, bid, ask, mode)
        pnl = side * quantity * (mark - pos[j, 2]) * value
        equity += side * quantity * mark * value
        mid_equity += side * quantity * mid[i] * value
        losing += min(0., pnl)
        if side > 0:
            long_qty += quantity
            long_pnl += pnl
        else:
            short_qty += quantity
            short_pnl += pnl
    return equity, mid_equity, long_qty, short_qty, long_pnl, short_pnl, losing


@njit(cache=True)
def place_levels(levels: np.ndarray, sides: np.ndarray, armed: np.ndarray, placed: np.ndarray,
                 anchor: float, delta: float, steps: int, family: int, i: int) -> None:
    """機能: 中心から上下に固定間隔の段を配置し、以前の武装状態を破棄する。

    引数: levels/sides/armed/placed(ndarray)、anchor/delta(float)、steps/family/i(int)。
    返り値: なし(None)。配置行そのものでは発火せず、以後の不成立側観測を必要とする。
    """
    for j in range(2 * steps):
        side = 1 if j < steps else -1
        distance = (j % steps + 1) * delta
        sides[j] = side
        levels[j] = anchor + side * distance if family == 3 else anchor - side * distance
        armed[j] = False
        placed[j] = i


@njit(cache=True)
def entry_condition(side: int, level: float, i: int, mid: np.ndarray, bid: np.ndarray, ask: np.ndarray,
                    family: int, mode: int, tick: float) -> bool:
    """機能: 条件注文又は通過確認付き待機指値の成立を判定する。

    引数: side/i/family/mode(int)、level/tick(float)、mid/bid/ask(ndarray)。返り値: 成立(bool)。
    """
    if family == 3:
        return side * (mid[i] - level) >= 0
    if mode == 2:
        return ask[i] <= level - tick if side > 0 else bid[i] >= level + tick
    return side * (mid[i] - level) <= 0


@njit(cache=True)
def oldest_opposite(pos: np.ndarray, pending: np.ndarray, side: int, cover: int, i: int) -> int:
    """機能: 新しい注文と逆方向にある、返済予約のない最古の元玉を選ぶ。

    引数: pos/pending(ndarray)、side/cover/i(int)。返り値: 段番号(int)、対象なしは-1。
    """
    chosen, oldest = -1, i
    for j in range(cover):
        if pos[j, 1] > 0 and pos[j, 0] == -side and pending[j, 0] == 0 and pos[j, 4] < oldest:
            chosen, oldest = j, int(pos[j, 4])
    return chosen


@njit(cache=True)
def refresh_empty(pos: np.ndarray, levels: np.ndarray, sides: np.ndarray, armed: np.ndarray,
                  placed: np.ndarray, anchor: float, delta: float, steps: int, family: int, i: int) -> None:
    """機能: 未保有の段だけを再配置し、元玉の建値・期限・保護線を変更しない。

    引数: pos/levels/sides/armed/placed(ndarray)、anchor/delta(float)、steps/family/i(int)。返り値: なし(None)。
    """
    for j in range(2 * steps):
        if pos[j, 1] > 0:
            continue
        side = int(sides[j])
        distance = (j % steps + 1) * delta
        levels[j] = anchor + side * distance if family == 3 else anchor - side * distance
        armed[j], placed[j] = False, i


@njit(cache=True)
def replay(times: np.ndarray, seqs: np.ndarray, mid: np.ndarray, bid: np.ndarray, ask: np.ndarray,
           sessions: np.ndarray, limits: np.ndarray, events: np.ndarray, family: int, steps: int,
           mode: int, fraction: float, cap: int, value: float, tick: float, fee_tenths: int,
           minutes: int, cooldown_seconds: int, finish: bool = True) -> tuple:
    """機能: 一場だけの有限寿命在庫を、原本順・注文単位費用・全玉時価で再生する。

    引数: 観測・場・方向材料のndarray群、family/steps/mode/cap/fee_tenths/minutes/cooldown_seconds(int)、fraction/value/tick(float)、finish(bool)。
    返り値: 注文/返済/清算時価/中値時価/保有リスク/中心変更/残玉/予約/現金会計/取消/候補件数の11配列(tuple)。
    familyは0期限格子、1在庫中心、2追加停止整理、3利益方向追加、4期限カバー。各元玉時計を延長しない。
    """
    assert len(limits) == 1 and np.all(sessions == 0) and cap % steps == 0
    slots, cover = 2 * steps + 1, 2 * steps
    quantity = cap // steps
    delta = max(2 * tick, np.ceil(mid[0] * fraction / tick - 1e-10) * tick)
    anchor, cycle = mid[0], 0
    pos, pending = np.zeros((slots, 10)), np.zeros((slots, 7))
    sides, levels = np.zeros(slots, np.int64), np.zeros(slots)
    armed, placed = np.zeros(slots, np.bool_), np.zeros(slots, np.int64)
    arm_index, tp_since = np.zeros(slots, np.int64), np.full(slots, -1, np.int64)
    rearm_after = np.zeros(slots)
    last_add_price = np.zeros(2)
    place_levels(levels, sides, armed, placed, anchor, delta, steps, family, -1)
    orders, trades = np.zeros((1024, 20)), np.zeros((1024, 23))
    resets, cancellations = np.zeros((128, 5)), np.zeros((128, 4))
    oc = tc = rc = nc = 0
    book = np.zeros(4)
    counts = np.zeros(3, np.int64)  # 格子の発火候補、FIFOへ切替えた候補、カバー予約。
    equity, mid_equity, risks = np.zeros(len(mid)), np.zeros(len(mid)), np.zeros((len(mid), 5))
    selected = np.zeros(slots, np.bool_)
    cycle_peak = resume_after = cover_after = 0.
    halted = closing = pause_after_closure = was_positioned = False
    valid_direction, direction, event_cursor = False, 0, 0
    for i in range(len(mid)):
        now = times[i]
        if now >= limits[0] + 300. and (np.any(pos[:, 1] > 0) or np.any(pending[:, 0] != 0)):
            raise ValueError('同場のザラバ終端までに返済できる次行がありません')
        # ----------------------------------------
        # 過去行の返済予約、続いて新規予約を現在の実観測で約定する。
        for j in range(slots):
            if pending[j, 0] != 2:
                continue
            selected[:] = False
            selected[j] = True
            side, reason, decision = int(pos[j, 0]), int(pending[j, 3]), int(pending[j, 1])
            if pending[j, 4] == 1:
                for k in range(j + 1, slots):
                    if pending[k, 0] == 2 and pending[k, 3] == reason and pos[k, 0] == side:
                        selected[k] = True
            price = execution_price(-side, i, mid, bid, ask, mode)
            orders, oc, trades, tc = close_slots(pos, selected, price, decision, i, reason, delta, fee_tenths,
                value, times, seqs, sessions, orders, oc, trades, tc, book)
            for k in range(slots):
                if not selected[k]:
                    continue
                trigger = int(pending[k, 6])
                if trigger >= 0:
                    armed[trigger], placed[trigger] = False, i
                    rearm_after[trigger] = now + cooldown_seconds
                pending[k] = 0.
                armed[k], placed[k], tp_since[k] = False, i, -1
                rearm_after[k] = now + cooldown_seconds
                if k == cover:
                    cover_after = now + 900.
                else:
                    distance = (k % steps + 1) * delta
                    levels[k] = anchor + sides[k] * distance if family == 3 else anchor - sides[k] * distance
        for j in range(slots):
            if pending[j, 0] != 1:
                continue
            side, decision = int(pending[j, 5]), int(pending[j, 1])
            amount, reason = int(pending[j, 2]), int(pending[j, 3])
            if j < cover and now >= limits[0] - 300.:
                cancellations = append_row(cancellations, nc, np.array([decision, i, j, amount]))
                nc += 1
                pending[j] = 0.
                armed[j], placed[j] = False, i
                continue
            price = execution_price(side, i, mid, bid, ask, mode)
            mark = liquidation_price(side, i, mid, bid, ask, mode)
            orders, oc = open_slot(pos, j, side, amount, price, decision, i, int(j == cover), reason,
                cycle, delta, fee_tenths, value, times, seqs, sessions, mark, orders, oc, book)
            pending[j] = 0.
            tp_since[j] = i
            if j < cover:
                last_add_price[0 if side > 0 else 1] = price
        covered = pos[cover, 1] > 0
        for j in range(cover):
            if covered:
                tp_since[j] = -1
            elif pos[j, 1] > 0 and tp_since[j] < 0:
                tp_since[j] = i
        # ----------------------------------------
        # 前観測から存在した指値だけを通過確認で約定し、当行判断で過去へ取消しない。
        if mode == 2 and not covered:
            for j in range(cover):
                if pos[j, 1] <= 0 or tp_since[j] < 0 or i <= tp_since[j] or pending[j, 0] != 0:
                    continue
                side = int(pos[j, 0])
                target = pos[j, 2] + side * delta * (2. if family == 3 else 1.)
                if not (bid[i] >= target + tick if side > 0 else ask[i] <= target - tick):
                    continue
                assert abs(target / (tick / 2.) - np.round(target / (tick / 2.))) < 1e-7
                selected[:] = False
                selected[j] = True
                orders, oc, trades, tc = close_slots(pos, selected, target, int(tp_since[j]), i, 8, delta,
                    fee_tenths, value, times, seqs, sessions, orders, oc, trades, tc, book)
                armed[j], placed[j], tp_since[j], rearm_after[j] = False, i, -1, now + cooldown_seconds
                distance = (j % steps + 1) * delta
                levels[j] = anchor + sides[j] * distance if family == 3 else anchor - sides[j] * distance
            if family != 3 and not closing and not halted and now >= resume_after and now < limits[0] - 300.:
                for j in range(cover):
                    if pos[j, 1] > 0 or pending[j, 0] != 0 or not armed[j] or i <= arm_index[j]:
                        continue
                    side = int(sides[j])
                    if not entry_condition(side, levels[j], i, mid, bid, ask, family, mode, tick):
                        continue
                    counts[0] += 1
                    assert abs(levels[j] / (tick / 2.) - np.round(levels[j] / (tick / 2.))) < 1e-7
                    opposite = oldest_opposite(pos, pending, side, cover, i) if family == 1 else -1
                    if opposite >= 0:
                        counts[1] += 1
                        selected[:] = False
                        selected[opposite] = True
                        orders, oc, trades, tc = close_slots(pos, selected, levels[j], int(arm_index[j]), i, 14, delta,
                            fee_tenths, value, times, seqs, sessions, orders, oc, trades, tc, book)
                        armed[opposite], placed[opposite], tp_since[opposite] = False, i, -1
                        rearm_after[opposite] = now + cooldown_seconds
                        rearm_after[j] = now + cooldown_seconds
                        levels[opposite] = anchor - sides[opposite] * (opposite % steps + 1) * delta
                    else:
                        mark = liquidation_price(side, i, mid, bid, ask, mode)
                        orders, oc = open_slot(pos, j, side, quantity, levels[j], int(arm_index[j]), i, 0, 0,
                            cycle, delta, fee_tenths, value, times, seqs, sessions, mark, orders, oc, book)
                        tp_since[j] = i
                    armed[j], placed[j] = False, i
        # ----------------------------------------
        # 現在行から先にのみ影響する、確定足・在庫・損失予算の判断を行う。
        published = False
        while event_cursor < len(events) and int(events[event_cursor, 0]) <= i:
            event = events[event_cursor]
            event_cursor += 1
            published, valid_direction, direction = True, event[3] == 1, 0
            if valid_direction and event[1] >= 2 * delta and event[2] >= delta:
                direction = 1
            elif valid_direction and event[1] <= -2 * delta and event[2] <= -delta:
                direction = -1
        for j in range(slots):
            if pos[j, 1] > 0:
                mark = liquidation_price(int(pos[j, 0]), i, mid, bid, ask, mode)
                pos[j, 7] = max(pos[j, 7], mark) if pos[j, 0] > 0 else min(pos[j, 7], mark)
        current, current_mid, lqty, sqty, lpnl, spnl, losing = inventory(pos, i, mid, bid, ask, mode, value, book[0])
        flat = lqty + sqty == 0
        if flat and was_positioned:
            resume_after = max(resume_after, now + (900. if pause_after_closure else cooldown_seconds))
            closing, pause_after_closure = False, False
            cycle += 1
            anchor, cycle_peak = mid[i], current
            refresh_empty(pos, levels, sides, armed, placed, anchor, delta, steps, family, i)
            resets = append_row(resets, rc, np.array([i, now, cycle, anchor, 1.]))
            rc += 1
        if published and now >= resume_after and not closing and not halted:
            new_anchor = anchor
            if family == 1:
                unit_tick = tick / 2.
                target = mid[i] - (lqty - sqty) / cap * delta
                new_anchor = np.floor(target / unit_tick + .5) * unit_tick
            elif flat and abs(mid[i] - anchor) >= delta:
                new_anchor = mid[i]
            if abs(new_anchor - anchor) >= tick / 2.:
                anchor = new_anchor
                if flat:
                    cycle_peak = current
                    cycle += 1
                refresh_empty(pos, levels, sides, armed, placed, anchor, delta, steps, family, i)
                resets = append_row(resets, rc, np.array([i, now, cycle, anchor, 2.]))
                rc += 1
        if not closing and now >= resume_after:
            cycle_peak = max(cycle_peak, current)
        global_reason = 0
        if now >= limits[0] - 60.:
            global_reason = 1
        elif not halted and current <= -4. * cap * delta * value:
            global_reason, halted = 2, True
        elif not halted and not closing and now >= resume_after and current <= cycle_peak - 2. * cap * delta * value:
            global_reason, pause_after_closure = 3, True
        if family == 4 and covered and not global_reason:
            deadline = times[int(pos[cover, 4])] + min(900., minutes * 30.)
            stop_hit = False
            for j in range(cover):
                if pos[j, 1] > 0:
                    deadline = min(deadline, times[int(pos[j, 4])] + minutes * 60.)
                    mark = liquidation_price(int(pos[j, 0]), i, mid, bid, ask, mode)
                    stop_hit |= pos[j, 0] * (mark - pos[j, 2]) <= -2. * delta
            if now >= deadline:
                global_reason = 12
            elif stop_hit:
                global_reason = 13
        if global_reason:
            armed[:] = False
            for j in range(slots):
                if pending[j, 0] == 1:
                    pending[j] = 0.
                if pos[j, 1] > 0:
                    pending[j] = np.array([2., i, pos[j, 1], global_reason, 1., pos[j, 0], -1.])
            closing = not flat
            if global_reason == 3 and flat:
                resume_after, pause_after_closure = now + 900., False
                cycle_peak = current
        if not global_reason and not closing and not halted:
            # 個別の期限はカバーや再配置で延長せず、損切り・期限中も休止を無視して保護する。
            covered = pos[cover, 1] > 0
            if family == 4 and covered:
                side = int(pos[cover, 0])
                mark = liquidation_price(side, i, mid, bid, ask, mode)
                reason = 6 if valid_direction and direction != side else 0
                if not reason and side * (mark - pos[cover, 7]) <= -delta:
                    reason = 7
                if reason:
                    pending[cover] = np.array([2., i, pos[cover, 1], reason, 0., side, -1.])
            for j in range(cover):
                if pos[j, 1] <= 0 or pending[j, 0] != 0:
                    continue
                side = int(pos[j, 0])
                mark = liquidation_price(side, i, mid, bid, ask, mode)
                distance = side * (mark - pos[j, 2])
                reason = 0
                stop = delta if family == 3 else 2. * delta
                if distance <= -stop:
                    reason = 9
                elif family == 3 and side * (pos[j, 7] - pos[j, 2]) >= delta and side * (mark-pos[j, 7]) <= -delta:
                    reason = 10
                elif now >= times[int(pos[j, 4])] + minutes * 60.:
                    reason = 11
                elif family == 2 and valid_direction and direction == -side and distance <= -delta:
                    reason = 4
                elif not covered and mode != 2 and distance >= delta * (2. if family == 3 else 1.):
                    reason = 8
                if reason:
                    pending[j] = np.array([2., i, pos[j, 1], reason, 1. if reason in (4, 11) else 0., side, -1.])
            core_exit = np.any(pending[:cover, 0] == 2)
            if family == 4 and not covered and not core_exit and valid_direction and direction != 0 and now >= cover_after:
                net = lqty - sqty
                if net * direction < 0:
                    held = lqty if direction > 0 else sqty
                    amount = min(abs(net), cap-held)
                    if amount > 0:
                        counts[2] += 1
                        pending[cover] = np.array([1., i, amount, 5., 0., direction, -1.])
                        covered = True
                        armed[:] = False
                        tp_since[:cover] = -1
            for j in range(cover):
                side = int(sides[j])
                entry_ready = True
                allowed = valid_direction and now >= resume_after and now >= rearm_after[j] and now < limits[0]-300. and not covered
                if family == 2 and direction != 0 and direction != side:
                    allowed = False
                if family == 3:
                    allowed = allowed and direction == side
                    existing, pnl, entry_fees = 0, 0., 0.
                    for k in range(cover):
                        if pos[k, 1] > 0 and pos[k, 0] == side:
                            existing += int(pos[k, 1])
                            pnl += side * pos[k, 1] * (liquidation_price(side, i, mid, bid, ask, mode)-pos[k, 2]) * value
                            entry_fees += pos[k, 3]
                    if existing:
                        entry_ready = pnl > entry_fees and side*(mid[i]-last_add_price[0 if side > 0 else 1]) >= delta
                    # 同一原本行で、未約定の初回から複数段を仮想的に追加しない。
                    for k in range(cover):
                        if pending[k, 0] == 1 and pending[k, 5] == side:
                            entry_ready = False
                if not allowed:
                    armed[j], placed[j] = False, i
                    continue
                if pos[j, 1] > 0 or pending[j, 0] != 0 or i <= placed[j]:
                    continue
                condition = entry_condition(side, levels[j], i, mid, bid, ask, family, mode, tick)
                if not condition:
                    if not armed[j]:
                        armed[j], arm_index[j] = True, i
                elif armed[j] and not (mode == 2 and family != 3):
                    if not entry_ready:
                        continue
                    counts[0] += 1
                    opposite = oldest_opposite(pos, pending, side, cover, i) if family == 1 else -1
                    if opposite >= 0:
                        counts[1] += 1
                        pending[opposite] = np.array([2., i, pos[opposite, 1], 14., 0., pos[opposite, 0], j])
                    else:
                        reserved = lqty if side > 0 else sqty
                        for k in range(slots):
                            if pending[k, 0] == 1 and pending[k, 5] == side:
                                reserved += int(pending[k, 2])
                        if reserved + quantity <= cap:
                            pending[j] = np.array([1., i, quantity, 0., 0., side, -1.])
                    armed[j] = False
        else:
            armed[:] = False
            placed[:] = i
        equity[i], mid_equity[i] = current, current_mid
        risks[i, 0], risks[i, 1], risks[i, 2], risks[i, 3], risks[i, 4] = lqty, sqty, lpnl, spnl, losing
        was_positioned = not flat
        assert lqty <= cap and sqty <= cap
    if finish:
        assert not np.any(pos[:, 1] > 0) and not np.any(pending[:, 0] != 0), '場内返済が完了していません'
    assert abs(equity[-1]-(book[2]-book[3]-book[1]+risks[-1, 2]+risks[-1, 3])) < 1e-5
    return orders[:oc], trades[:tc], equity, mid_equity, risks, resets[:rc], pos, pending, book, cancellations[:nc], counts


