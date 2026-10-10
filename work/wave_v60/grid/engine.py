"""有限段グリッドを原本順に運用し、週内持越しと実注文単位の費用を会計する。"""

from __future__ import annotations

import numpy as np
from numba import njit

from accounting import order_fee


REASONS = {0: '格子新規', 1: '週末清算', 2: '調査終了清算', 3: '場内清算', 4: '週損失予算',
           5: '運用組の下落幅', 6: '逆方向の整理', 7: 'カバー新規', 8: 'カバー方向終了',
           9: 'カバー追跡返済', 10: '段ごとの利確', 11: '個別初期損切り', 12: '個別追跡返済'}
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
        levels[j] = anchor + side * distance if family == 4 else anchor - side * distance
        armed[j] = False
        placed[j] = i


@njit(cache=True)
def entry_condition(side: int, level: float, i: int, mid: np.ndarray, bid: np.ndarray, ask: np.ndarray,
                    family: int, mode: int, tick: float) -> bool:
    """機能: 条件注文又は通過確認付き待機指値の成立を判定する。

    引数: side/i/family/mode(int)、level/tick(float)、mid/bid/ask(ndarray)。返り値: 成立(bool)。
    """
    if family == 4:
        return side * (mid[i] - level) >= 0
    if mode == 2:
        return ask[i] <= level - tick if side > 0 else bid[i] >= level + tick
    return side * (mid[i] - level) <= 0


@njit(cache=True)
def replay(times: np.ndarray, seqs: np.ndarray, mid: np.ndarray, bid: np.ndarray, ask: np.ndarray,
           sessions: np.ndarray, limits: np.ndarray, events: np.ndarray, final_reason: int,
           family: int, steps: int, carry: int, mode: int, fraction: float,
           cap: int, value: float, tick: float, fee_tenths: int, finish: bool = True) -> tuple:
    """機能: 一銘柄一週の有限グリッドと保護を原本順に再生する。

    引数: 価格・時刻・場・公開方向のndarray群、final_reason/family/steps/carry/mode/cap/fee_tenths(int)、fraction/value/tick(float)、finish(bool)。
    返り値: 注文、返済、清算時価、中値時価、保有・含みリスク、cycle変更記録、残玉、未約定予約、現金会計(tuple)。
    modeは0気配、1中値、2待機指値通過モデル。注文モデルを独立再生し、成績で選び直さない。
    """
    assert cap % steps == 0 and family >= 0 and family <= 4 and mode >= 0 and mode <= 2
    slots, cover = 2 * steps + 1, 2 * steps
    quantity = cap // steps
    delta = max(2 * tick, np.ceil(mid[0] * fraction / tick - 1e-10) * tick)
    anchor = mid[0]
    pos = np.zeros((slots, 10))
    pending = np.zeros((slots, 6))  # kind、判断index、枚数、理由、集約印、方向。
    sides = np.zeros(slots, np.int64)
    levels = np.zeros(slots)
    armed = np.zeros(slots, np.bool_)
    placed = np.zeros(slots, np.int64)
    arm_index = np.zeros(slots, np.int64)
    tp_since = np.full(slots, -1, np.int64)
    place_levels(levels, sides, armed, placed, anchor, delta, steps, family, -1)
    orders, trades = np.zeros((1024, 20)), np.zeros((1024, 23))
    resets = np.zeros((128, 5))
    cancellations = np.zeros((128, 4))
    oc = tc = rc = nc = 0
    book = np.zeros(4)
    equity, mid_equity = np.zeros(len(mid)), np.zeros(len(mid))
    risks = np.zeros((len(mid), 5))  # 買枚数、売枚数、買含み、売含み、負け玉含み。
    cycle = 0
    cycle_peak = 0.
    next_cycle = 0.
    cover_after = 0.
    week_halted = False
    paused = False
    pause_after_closure = False
    closing = False
    direction = 0
    valid_direction = False
    previous_session = -1
    event_cursor = 0
    selected = np.zeros(slots, np.bool_)
    for i in range(len(mid)):
        now, sid = times[i], int(sessions[i])
        if sid != previous_session:
            if previous_session >= 0 and carry == 0 and (np.any(pos[:, 1] > 0) or np.any(pending[:, 0] != 0)):
                raise ValueError('場内型の返済が前場で完了していないため、次場へ持ち越して約定できません')
            direction, valid_direction = 0, False
            previous_session = sid
            armed[:] = False
            placed[:] = i - 1
        final_session = sid == len(limits) - 1
        force = (final_session and final_reason > 0) or carry == 0
        if force and now >= limits[sid] + 300. and (np.any(pos[:, 1] > 0) or np.any(pending[:, 0] != 0)):
            raise ValueError('同一ザラバ終了前の次の有効行が無く、期限内返済を保証できません')
        # ----------------------------------------
        # 前行の成行予約を先に実行する。休場中を補間せず、再開後の実価格を使う。
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
                if selected[k]:
                    pending[k] = 0.
                    tp_since[k] = -1
                    armed[k] = False
                    placed[k] = i
                    if k == cover:
                        cover_after = now + 900.
        for j in range(slots):
            if pending[j, 0] != 1:
                continue
            side, amount = int(pending[j, 5]), int(pending[j, 2])
            decision, reason = int(pending[j, 1]), int(pending[j, 3])
            if j < cover and (sessions[decision] != sid or now >= limits[sid] - 300.):
                cancellations = append_row(cancellations, nc, np.array([decision, i, j, amount]))
                nc += 1
                pending[j] = 0.
                armed[j], placed[j] = False, i
                continue
            price = execution_price(side, i, mid, bid, ask, mode)
            liquidation = liquidation_price(side, i, mid, bid, ask, mode)
            orders, oc = open_slot(pos, j, side, amount, price, decision, i, int(j == cover), reason,
                                  cycle, delta, fee_tenths, value, times, seqs, sessions, liquidation, orders, oc, book)
            pending[j] = 0.
            tp_since[j] = i
        covered = pos[cover, 1] > 0
        for j in range(cover):
            if covered:
                tp_since[j] = -1
            elif pos[j, 1] > 0 and tp_since[j] < 0:
                tp_since[j] = i
        # ----------------------------------------
        # 前行以前から待機した指値を約定する。今回判明する方向やriskで過去へ取消しない。
        if mode == 2:
            if not covered:
                for j in range(cover):
                    if pos[j, 1] <= 0 or tp_since[j] < 0 or i <= tp_since[j] or pending[j, 0] != 0:
                        continue
                    side = int(pos[j, 0])
                    target = pos[j, 2] + side * delta * (2. if family == 4 else 1.)
                    passed = bid[i] >= target + tick if side > 0 else ask[i] <= target - tick
                    if passed:
                        assert abs(target / (tick / 2.) - np.round(target / (tick / 2.))) < 1e-7
                        selected[:] = False
                        selected[j] = True
                        orders, oc, trades, tc = close_slots(pos, selected, target, int(tp_since[j]), i, 10, delta,
                            fee_tenths, value, times, seqs, sessions, orders, oc, trades, tc, book)
                        tp_since[j], placed[j], armed[j] = -1, i, False
            if family != 4 and not covered and not closing and not paused and not week_halted and now < limits[sid] - 300.:
                for j in range(cover):
                    if pos[j, 1] > 0 or pending[j, 0] != 0 or not armed[j] or i <= arm_index[j]:
                        continue
                    if entry_condition(int(sides[j]), levels[j], i, mid, bid, ask, family, mode, tick):
                        side = int(sides[j])
                        assert abs(levels[j] / (tick / 2.) - np.round(levels[j] / (tick / 2.))) < 1e-7
                        liquidation = liquidation_price(side, i, mid, bid, ask, mode)
                        orders, oc = open_slot(pos, j, side, quantity, levels[j], int(arm_index[j]), i, 0, 0,
                            cycle, delta, fee_tenths, value, times, seqs, sessions, liquidation, orders, oc, book)
                        armed[j], tp_since[j] = False, i
        # ----------------------------------------
        # ここから現行観測で新しい判断を行う。方向は確定足公開行でだけ更新する。
        published = False
        while event_cursor < len(events) and int(events[event_cursor, 0]) <= i:
            event = events[event_cursor]
            event_cursor += 1
            published = True
            valid_direction = event[3] == 1
            direction = 0
            if valid_direction and event[1] >= 2 * delta and event[2] >= delta:
                direction = 1
            elif valid_direction and event[1] <= -2 * delta and event[2] <= -delta:
                direction = -1
        for j in range(slots):
            if pos[j, 1] > 0:
                side = int(pos[j, 0])
                price = liquidation_price(side, i, mid, bid, ask, mode)
                pos[j, 7] = max(pos[j, 7], price) if side > 0 else min(pos[j, 7], price)
        marked = inventory(pos, i, mid, bid, ask, mode, value, book[0])
        current, current_mid, lqty, sqty, lpnl, spnl, losing = marked
        assert lqty <= cap and sqty <= cap
        # この位置では前行の全予約を処理済みで、当行の新予約はまだ作っていない。
        flat = lqty + sqty == 0
        if closing and flat:
            closing = False
            if pause_after_closure:
                paused, next_cycle = True, now + 1800.
                pause_after_closure = False
        if paused and now >= next_cycle and flat and not week_halted:
            paused = False
            cycle += 1
            anchor, cycle_peak = mid[i], current
            place_levels(levels, sides, armed, placed, anchor, delta, steps, family, i)
            resets = append_row(resets, rc, np.array([i, now, cycle, anchor, 2.]))
            rc += 1
        if published and flat and not paused and not week_halted and abs(mid[i] - anchor) >= delta:
            cycle += 1
            anchor, cycle_peak = mid[i], current
            place_levels(levels, sides, armed, placed, anchor, delta, steps, family, i)
            resets = append_row(resets, rc, np.array([i, now, cycle, anchor, 1.]))
            rc += 1
        if not paused and not closing:
            cycle_peak = max(cycle_peak, current)
        # ----------------------------------------
        # 清算、週損失予算、cycle下落幅は個別利確や新規より優先する。
        global_reason = 0
        if force and now >= limits[sid] - 60.:
            global_reason = final_reason if final_session and final_reason > 0 else 3
        elif family > 0 and not week_halted and current <= -6. * cap * delta * value:
            global_reason = 4
            week_halted = True
        elif family > 0 and not week_halted and not paused and not closing and current <= cycle_peak - 2. * cap * delta * value:
            global_reason = 5
            pause_after_closure = True
        if global_reason:
            armed[:] = False
            for j in range(slots):
                if pending[j, 0] == 1:
                    pending[j] = 0.
                if pos[j, 1] > 0:
                    pending[j] = np.array([2., i, pos[j, 1], global_reason, 1., pos[j, 0]])
            closing = np.any(pos[:, 1] > 0)
            if global_reason == 5 and not closing:
                paused, next_cycle, pause_after_closure = True, now + 1800., False
        # ----------------------------------------
        # 逆玉整理とカバー管理。方向unknownを中立とはみなさない。
        covered = pos[cover, 1] > 0 or pending[cover, 0] == 1
        if not global_reason and not closing and not paused and not week_halted:
            if family == 2 and valid_direction and direction != 0:
                for j in range(cover):
                    if pos[j, 1] > 0 and pos[j, 0] != direction:
                        pending[j] = np.array([2., i, pos[j, 1], 6., 1., pos[j, 0]])
            if family == 3:
                if pos[cover, 1] > 0 and pending[cover, 0] == 0:
                    side = int(pos[cover, 0])
                    price = liquidation_price(side, i, mid, bid, ask, mode)
                    reason = 0
                    if valid_direction and direction != side:
                        reason = 8
                    elif side * (price - (pos[cover, 7] - side * delta)) <= 0:
                        reason = 9
                    if reason:
                        pending[cover] = np.array([2., i, pos[cover, 1], reason, 0., side])
                elif not covered and valid_direction and direction != 0 and now >= cover_after:
                    net_core = 0
                    for j in range(cover):
                        net_core += int(pos[j, 0] * pos[j, 1])
                    if net_core * direction < 0:
                        amount = abs(net_core)
                        held = lqty if direction > 0 else sqty
                        amount = min(amount, cap - held)
                        if amount > 0:
                            pending[cover] = np.array([1., i, amount, 7., 0., direction])
                            covered = True
                            armed[:] = False
                            tp_since[:cover] = -1
            # ----------------------------------------
            # 各玉の保護・利確。カバー中のcore利確は止め、全体保護は上で継続する。
            if not covered:
                for j in range(cover):
                    if pos[j, 1] <= 0 or pending[j, 0] != 0:
                        continue
                    side = int(pos[j, 0])
                    price = liquidation_price(side, i, mid, bid, ask, mode)
                    reason = 0
                    if family == 4:
                        stop = pos[j, 2] - side * delta
                        favorable = side * (pos[j, 7] - pos[j, 2])
                        if favorable >= delta:
                            stop = pos[j, 7] - side * delta
                        if side * (price - stop) <= 0:
                            reason = 12 if favorable >= delta else 11
                    if reason == 0 and mode != 2 and side * (price - pos[j, 2]) >= delta * (2. if family == 4 else 1.):
                        reason = 10
                    if reason:
                        pending[j] = np.array([2., i, pos[j, 1], reason, 0., side])
            # ----------------------------------------
            # 新規は方向準備後だけ。禁止中は待機注文を取消し、再許可後も新たな不成立観測を要求する。
            for j in range(cover):
                side = int(sides[j])
                allowed = valid_direction and now < limits[sid] - 300. and not covered
                if family in (2, 4) and direction != 0 and side != direction:
                    allowed = False
                if not allowed:
                    armed[j], placed[j] = False, i
                    continue
                if pos[j, 1] > 0 or pending[j, 0] != 0 or i <= placed[j]:
                    continue
                condition = entry_condition(side, levels[j], i, mid, bid, ask, family, mode, tick)
                if not condition:
                    if not armed[j]:
                        armed[j], arm_index[j] = True, i
                elif armed[j] and not (mode == 2 and family != 4):
                    reserved = lqty if side > 0 else sqty
                    for k in range(slots):
                        if pending[k, 0] == 1 and pending[k, 5] == side:
                            reserved += int(pending[k, 2])
                    if reserved + quantity <= cap:
                        pending[j] = np.array([1., i, quantity, 0., 0., side])
                    armed[j] = False
        else:
            armed[:] = False
            placed[:] = i
        # ここまでの新判断は次行の予約だけなので、上の時価と保有量は変化しない。
        equity[i], mid_equity[i] = current, current_mid
        risks[i, 0], risks[i, 1] = lqty, sqty
        risks[i, 2], risks[i, 3], risks[i, 4] = lpnl, spnl, losing
        assert lqty <= cap and sqty <= cap
    if finish:
        assert not np.any(pos[:, 1] > 0) and not np.any(pending[:, 0] != 0), '週末又は資料端の返済が完了していません'
    assert abs(equity[-1] - (book[2] - book[3] - book[1] + risks[-1, 2] + risks[-1, 3])) < 1e-5
    return orders[:oc], trades[:tc], equity, mid_equity, risks, resets[:rc], pos, pending, book, cancellations[:nc]
