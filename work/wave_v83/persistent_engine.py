"""固定代表の指値だけを持続注文へ変えた因果比較。元エンジンは変更しない。"""
import math
import numpy as np
from numba import njit


@njit(cache=True, inline='always')
def update_peaks(slots, stats):
    """
    機能: 同一行中に解消する注文・建玉を含めて最大数量を保存する。
    引数: slots/stats(ndarray)。
    返り値: なし。
    """
    long_held = 0.0
    short_held = 0.0
    long_reserved = 0.0
    short_reserved = 0.0
    for j in range(len(slots)):
        if slots[j, 0] == 0:
            continue
        if slots[j, 1] == 1:
            long_reserved += slots[j, 2]
            if slots[j, 0] != 1:
                long_held += slots[j, 2]
        else:
            short_reserved += slots[j, 2]
            if slots[j, 0] != 1:
                short_held += slots[j, 2]
    stats[0] = max(stats[0], long_held)
    stats[1] = max(stats[1], short_held)
    stats[2] = max(stats[2], long_reserved)
    stats[3] = max(stats[3], short_reserved)
    stats[11] = max(stats[11], long_held + short_held)


@njit(cache=True, inline='always')
def event(events, cursor, slots, j, row_i, code):
    """
    機能: 予約と失効を追記し、未約定注文の枚数検算を可能にする。
    引数: events/slots(ndarray)、cursor(ndarray[int])、j/row_i/code(int)。
    返り値: なし。
    """
    k = cursor[0]
    assert k < len(events)
    events[k, 0] = row_i
    events[k, 1] = slots[j, 6]
    events[k, 2] = j
    events[k, 3] = code
    events[k, 4] = -slots[j, 1] if code == 2 or code == 5 else slots[j, 1]
    events[k, 5] = slots[j, 2]
    events[k, 6] = slots[j, 9]
    events[k, 7] = slots[j, 10]
    events[k, 8] = slots[j, 11]
    events[k, 9] = slots[j, 12]
    events[k, 10] = slots[j, 17]
    events[k, 11] = slots[j, 20]
    cursor[0] += 1


@njit(cache=True, inline='always')
def send_entry(slots, events, cursor, stats, j, side, qty, i, t, delay, price_limit, is_limit,
               stop, target, trail, activation, reason, ticket, cycle):
    """
    機能: 新規注文を予約し、約定前から枚数を占有する。
    引数: slots(ndarray)、j/side/qty/i/reason/ticket/cycle(int)、その他(float)。
    返り値: int。次に使用する建玉識別番号。
    """
    slots[j, :] = 0.0
    slots[j, 0] = 1
    slots[j, 1] = side
    slots[j, 2] = qty
    slots[j, 6] = ticket
    slots[j, 8] = i
    slots[j, 9] = t
    slots[j, 10] = t + delay
    slots[j, 11] = price_limit
    slots[j, 12] = 2 if is_limit else 0
    slots[j, 13] = stop
    slots[j, 14] = target
    slots[j, 15] = trail
    slots[j, 16] = activation
    slots[j, 17] = reason
    slots[j, 18] = reason
    slots[j, 20] = cycle
    event(events, cursor, slots, j, i, 1)
    update_peaks(slots, stats)
    return ticket + 1


@njit(cache=True, inline='always')
def send_exit(slots, events, cursor, j, i, t, delay, reason):
    """
    機能: 返済を予約する。約定までは保有数量を減らさない。
    引数: slots(ndarray)、j/i/reason(int)、t/delay(float)。
    返り値: なし。
    """
    slots[j, 0] = 3
    slots[j, 8] = i
    slots[j, 9] = t
    slots[j, 10] = t + delay
    slots[j, 11] = 0
    slots[j, 12] = 0
    slots[j, 17] = reason
    event(events, cursor, slots, j, i, 2)


@njit(cache=True)
def fill_orders(slots, events, cursor, orders, trades, stats, count_slots, allocation,
                i, t, bid, ask, tick, slip_ticks, pointvalue, fee, family, delay,
                no, nt, cash, base_side, base_price, base_best, last_add, flatten, flatten_reason):
    """
    機能: 到達済注文を約定し、独立した各脚の損益と手数料を記録する。
    引数: slots等(ndarray)は台帳、i/count_slots等(int)、t/bid/ask等(float)は当該観測値。
    返り値: tuple。台帳件数・現金・状態変化・主玉の追尾状態・全玉清算状態。
    """
    changed = False
    for j in range(count_slots):
        status = int(slots[j, 0])
        if status != 1 and status != 3:
            continue
        if i < slots[j, 8] or (delay > 0 and i == slots[j, 8]) or t < slots[j, 10]:
            continue
        held_side = int(slots[j, 1])
        action_side = held_side if status == 1 else -held_side
        quantity = int(slots[j, 2])
        fill = ask + slip_ticks * tick if action_side == 1 else bid - slip_ticks * tick
        if status == 1 and slots[j, 12] != 0:
            lim = slots[j, 11]
            if (action_side == 1 and fill > lim) or (action_side == -1 and fill < lim):
                if slots[j, 12] == 2:
                    continue
                event(events, cursor, slots, j, i, 3)
                slots[j, 0] = 0
                stats[8] += 1
                changed = True
                continue
        if status == 1 and slots[j, 12] == 2:
            # 気配が指値を通過しても、その後の有利な値で埋めず元の指値で約定する。
            fill = slots[j, 11]
        charge = math.floor(quantity * fee + 1e-8)
        assert no < allocation
        orders[no, 0] = i
        orders[no, 1] = slots[j, 8]
        orders[no, 2] = slots[j, 6]
        orders[no, 3] = action_side
        orders[no, 4] = quantity
        orders[no, 5] = fill
        orders[no, 6] = 1 if status == 1 else 0
        orders[no, 7] = slots[j, 17]
        orders[no, 8] = charge
        orders[no, 9] = slots[j, 9]
        orders[no, 10] = slots[j, 10]
        orders[no, 11] = t
        orders[no, 12] = j
        orders[no, 13] = slots[j, 11]
        orders[no, 14] = slots[j, 20]
        orders[no, 15] = slots[j, 12]
        no += 1
        event(events, cursor, slots, j, i, 4 if status == 1 else 5)
        cash -= action_side * quantity * fill * pointvalue + charge
        changed = True
        if status == 1:
            slots[j, 0] = 2
            slots[j, 3] = fill
            slots[j, 4] = charge
            slots[j, 5] = i
            slots[j, 7] = fill
            stats[9] += 1
            update_peaks(slots, stats)
            if (family == 9 or family == 11) and base_price == 0:
                base_side = held_side
                base_price = fill
                base_best = fill
            if family == 9:
                last_add = fill
        else:
            gross = held_side * quantity * (fill - slots[j, 3]) * pointvalue
            net = gross - charge - slots[j, 4]
            assert nt < allocation
            trades[nt, 0] = slots[j, 6]
            trades[nt, 1] = slots[j, 5]
            trades[nt, 2] = i
            trades[nt, 3] = held_side
            trades[nt, 4] = quantity
            trades[nt, 5] = slots[j, 3]
            trades[nt, 6] = fill
            trades[nt, 7] = slots[j, 4]
            trades[nt, 8] = charge
            trades[nt, 9] = gross
            trades[nt, 10] = net
            trades[nt, 11] = slots[j, 18]
            trades[nt, 12] = slots[j, 17]
            trades[nt, 13] = slots[j, 20]
            nt += 1
            stats[10] += 1
            slots[j, 0] = 0
            if family == 11 and j == 0:
                flatten = True
                flatten_reason = 9

    return no, nt, cash, changed, base_side, base_price, base_best, last_add, flatten, flatten_reason


@njit(cache=True, nogil=True)
def run(record, family, width_ticks, variant, cap, pointvalue, fee,
        delay=0.0, seed=0, slip_ticks=0.0):
    """
    機能: 先読みなしに新規・返済を順次執行し、全玉会計を返す。
    引数: record(tuple)はdata.as_tuple。family/width_ticks/variant/cap/seed(int)、
          pointvalue/fee/delay/slip_ticks(float)は倍率・片道料金・遅延秒・追加悪化呼値。
    返り値: tuple。注文16列・決済14列・全玉清算時価・統計14列・予約失効イベント12列。
    """
    times, prices, bids, asks, seq, source_i, pok, qok, tick, start, end, limit = record
    n = len(times)
    count_slots = 1
    if family == 2 or family == 3 or family == 8 or family == 10:
        count_slots = 2
    elif family == 7:
        count_slots = 10
    elif family == 9:
        count_slots = 5
    elif family == 11:
        count_slots = 6
    slots = np.zeros((count_slots, 21), np.float64)
    armed = np.ones(count_slots, np.bool_)
    price_changes = 1
    for i in range(1, n):
        if prices[i] != prices[i - 1]:
            price_changes += 1
    # 多段注文は一回の価格跳躍で全段発動し得る。静かな実原板では過大確保しない。
    allocation = max(1024, n * 2 + 64, price_changes * count_slots * 2 + 64)
    orders = np.zeros((allocation, 16), np.float64)
    trades = np.zeros((allocation, 14), np.float64)
    curve = np.zeros(n, np.float64)
    stats = np.zeros(14, np.float64)
    events = np.zeros((allocation * 2, 12), np.float64)
    cursor = np.zeros(1, np.int64)
    no = 0
    nt = 0
    cash = 0.0
    anchor = 0.0
    low = 0.0
    high = 0.0
    previous_price = np.nan
    cycle_cash = 0.0
    cycle = 0
    cycle_started = False
    closing = False
    flatten = False
    flatten_reason = 5
    initialized = False
    pending_evaluation = False
    ticket = 1
    random_state = (int(seed) + 1) % 2147483648
    alternate = 1
    base_side = 0
    base_price = 0.0
    base_best = 0.0
    last_add = 0.0
    previous_bid = np.nan
    previous_ask = np.nan
    width = tick * width_ticks
    unit = cap // 5
    bracket_stop = width * (2 if variant == 3 else 1)
    bracket_target = width * (1 if variant == 0 else (2 if variant == 1 else (3 if variant == 2 else 4)))
    trail_stop = width * (1 if variant < 2 else 2)
    trail_activation = width * (0 if variant == 0 else (2 if variant == 3 else 1))
    trail_width = width * (2 if variant == 2 else 1)
    force_time = limit - 60.0
    no_entry_time = limit - 120.0

    # ----------------------------------------
    for i in range(n):
        t = times[i]
        p = prices[i]
        if qok[i]:
            previous_bid = bids[i]
            previous_ask = asks[i]
        changed = False
        previous_fill = pending_evaluation

        # 未約定指値は既知の新規終了時刻で取り消す。取引所待ち順位の利益は仮定しない。
        if t >= no_entry_time:
            for j in range(count_slots):
                if slots[j, 0] == 1 and slots[j, 12] == 2:
                    event(events, cursor, slots, j, i, 6)
                    slots[j, 0] = 0
                    stats[8] += 1
                    changed = True

        # 既知の時計で返済予約。データ欠落時も終了指示時刻を後ろへずらさない。
        if not closing and t >= force_time:
            closing = True
            flatten = True
            flatten_reason = 6
            for j in range(count_slots):
                if slots[j, 0] == 2:
                    send_exit(slots, events, cursor, j, i - 1, force_time, delay, 6)

        if qok[i]:
            no, nt, cash, changed, base_side, base_price, base_best, last_add, flatten, flatten_reason = fill_orders(
                slots, events, cursor, orders, trades, stats, count_slots, allocation,
                i, t, bids[i], asks[i], tick, slip_ticks, pointvalue, fee, family, delay,
                no, nt, cash, base_side, base_price, base_best, last_add, flatten, flatten_reason)

        # ----------------------------------------
        active = 0
        pending_entries = 0
        for j in range(count_slots):
            if slots[j, 0] > 0:
                active += 1
            if slots[j, 0] == 1:
                pending_entries += 1
        if pok[i] and (not initialized or (active == 0 and cycle_started)):
            if cycle_started:
                alternate = -alternate
            cycle += 1
            anchor = p
            low = p
            high = p
            cycle_cash = cash
            cycle_started = False
            initialized = True
            base_price = 0.0
            base_side = 0
            last_add = 0.0
            base_best = 0.0
            armed[:] = True
            if not closing:
                flatten = False
        pending_evaluation = pending_evaluation or changed
        decision_event = pok[i] and (p != previous_price or changed or previous_fill or not cycle_started)
        # 注文条件は現在値だけを参照。気配は執行・会計にのみ使う。
        if decision_event and initialized:
            pending_evaluation = False
            previous_price = p
            low = min(low, p)
            high = max(high, p)
            mark = cash - cycle_cash
            for j in range(count_slots):
                if slots[j, 0] == 2 or slots[j, 0] == 3:
                    mark += slots[j, 1] * slots[j, 2] * p * pointvalue
                    mark -= math.floor(slots[j, 2] * fee + 1e-8)
            basket_stop = ((family == 7 and variant == 3) or (family == 8 and variant > 0) or family == 11)
            if basket_stop and not flatten and mark <= -4 * cap * width * pointvalue:
                flatten = True
                flatten_reason = 5
                stats[12] += 1
            if family == 9 and base_price != 0 and not flatten:
                if base_side * (p - base_best) > 0:
                    base_best = p
                if base_side * (p - base_price) <= -trail_stop:
                    flatten = True
                    flatten_reason = 1
                elif base_side * (base_best - base_price) >= trail_activation and base_side * (base_best - p) >= trail_width:
                    flatten = True
                    flatten_reason = 3
            for j in range(count_slots):
                if flatten and slots[j, 0] == 1 and slots[j, 12] == 2:
                    event(events, cursor, slots, j, i, 6)
                    slots[j, 0] = 0
                    stats[8] += 1
                if slots[j, 0] != 2:
                    continue
                if flatten:
                    send_exit(slots, events, cursor, j, i, t, delay, flatten_reason)
                    continue
                side = slots[j, 1]
                entry = slots[j, 3]
                if side * (p - slots[j, 7]) > 0:
                    slots[j, 7] = p
                profit = side * (p - entry)
                best_profit = side * (slots[j, 7] - entry)
                reason = 0
                if slots[j, 13] > 0 and profit <= -slots[j, 13]:
                    reason = 1
                elif slots[j, 14] > 0 and profit >= slots[j, 14]:
                    reason = 2
                elif slots[j, 15] > 0 and best_profit >= slots[j, 16] and side * (slots[j, 7] - p) >= slots[j, 15]:
                    reason = 3
                if reason:
                    send_exit(slots, events, cursor, j, i, t, delay, reason)

            # ----------------------------------------
            if not flatten and t < no_entry_time:
                if family == 0 or family == 1:
                    if not cycle_started:
                        side = alternate
                        if family == 0:
                            random_state = (1103515245 * random_state + 12345) % 2147483648
                            side = 1 if random_state >= 1073741824 else -1
                        ticket = send_entry(slots, events, cursor, stats, 0, side, cap, i, t, delay, 0, 0,
                                            bracket_stop, bracket_target, 0, 0, 10, ticket, cycle)
                        cycle_started = True
                elif family == 2 or family == 3:
                    if not cycle_started:
                        for j in range(2):
                            side = 1 if j == 0 else -1
                            stop = bracket_stop if family == 2 else trail_stop
                            target = bracket_target if family == 2 else 0
                            trailing = 0 if family == 2 else trail_width
                            activation = 0 if family == 2 else trail_activation
                            ticket = send_entry(slots, events, cursor, stats, j, side, cap, i, t, delay, 0, 0,
                                                stop, target, trailing, activation, 11, ticket, cycle)
                        cycle_started = True
                elif family == 4 or family == 5 or family == 6 or family == 9 or family == 10:
                    if not cycle_started:
                        buy = p >= anchor + width
                        sell = p <= anchor - width
                        if family == 5:
                            buy = p >= low + width
                            sell = p <= high - width
                        if family == 6:
                            buy = p <= anchor - width
                            sell = p >= anchor + width
                        if buy and sell:
                            # 両条件が同時成立した曖昧な跳躍では片側を恣意的に選ばない。
                            stats[13] += 1
                            anchor = p
                            low = p
                            high = p
                        elif buy or sell:
                            side = 1 if buy else -1
                            if family == 10:
                                for j in range(2):
                                    ticket = send_entry(slots, events, cursor, stats, j, side, cap // 2, i, t, delay, 0, 0,
                                                        trail_stop, width if j == 0 else 0,
                                                        0 if j == 0 else trail_width, trail_activation, 12, ticket, cycle)
                            else:
                                islim = 1 if family == 6 else 0
                                lim = anchor - side * width if family == 6 else 0
                                stop = bracket_stop if family == 6 else (0 if family == 9 else trail_stop)
                                target = bracket_target if family == 6 else 0
                                trailing = trail_width if family == 4 or family == 5 else 0
                                quantity = unit if family == 9 else cap
                                ticket = send_entry(slots, events, cursor, stats, 0, side, quantity, i, t, delay, lim, islim,
                                                    stop, target, trailing, trail_activation, 12, ticket, cycle)
                            cycle_started = True
                    elif family == 9 and base_price != 0 and pending_entries == 0 and base_side * (p - last_add) >= width:
                        for j in range(count_slots):
                            if slots[j, 0] == 0:
                                ticket = send_entry(slots, events, cursor, stats, j, base_side, unit, i, t, delay, 0, 0,
                                                    0, 0, 0, 0, 14, ticket, cycle)
                                break
                elif family == 7:
                    for j in range(count_slots):
                        side = 1 if j < 5 else -1
                        level = anchor - side * (j % 5 + 1) * width
                        if side * (p - level) > 0:
                            armed[j] = True
                        if slots[j, 0] == 0 and armed[j] and side * (p - level) <= 0:
                            stop = (2 if variant == 0 else (4 if variant == 1 else 8)) * width if variant < 3 else 0
                            ticket = send_entry(slots, events, cursor, stats, j, side, unit, i, t, delay, level, 1,
                                                stop, width, 0, 0, 13, ticket, cycle)
                            armed[j] = False
                            cycle_started = True
                elif family == 8:
                    for j in range(2):
                        if slots[j, 0] == 0:
                            side = 1 if j == 0 else -1
                            target = width if variant < 2 else 0
                            trailing = 0 if variant < 2 else (tick if variant == 2 else width)
                            activation = width if variant < 3 else 2 * width
                            ticket = send_entry(slots, events, cursor, stats, j, side, cap, i, t, delay, 0, 0,
                                                0, target, trailing, activation, 15, ticket, cycle)
                            cycle_started = True
                elif family == 11:
                    if not cycle_started:
                        ticket = send_entry(slots, events, cursor, stats, 0, alternate, cap, i, t, delay, 0, 0,
                                            8 * width, 0, 0, 0, 16, ticket, cycle)
                        cycle_started = True
                    elif base_price != 0 and slots[0, 0] == 2:
                        for j in range(1, count_slots):
                            level = base_price - base_side * j * width
                            if base_side * (p - level) > 0:
                                armed[j] = True
                            if slots[j, 0] == 0 and armed[j] and base_side * (p - level) <= 0:
                                ticket = send_entry(slots, events, cursor, stats, j, -base_side, unit, i, t, delay, 0, 0,
                                                    2 * width, 0, trail_width, trail_activation, 17, ticket, cycle)
                                armed[j] = False

        # データ有効値が変化しない場合にも、遅れて約定した新規を必ず場内清算する。
        if flatten:
            for j in range(count_slots):
                if slots[j, 0] == 2:
                    send_exit(slots, events, cursor, j, i, t, delay, flatten_reason)

        # 遅延ゼロでは判断した当該観測の気配で直ちに執行する。
        # 新規約定で初めて有効になる通常の返済条件は、次の観測から監視する。
        # この同じ行で新サイクルを繰り返さない。
        if delay == 0 and qok[i]:
            no, nt, cash, changed, base_side, base_price, base_best, last_add, flatten, flatten_reason = fill_orders(
                slots, events, cursor, orders, trades, stats, count_slots, allocation,
                i, t, bids[i], asks[i], tick, slip_ticks, pointvalue, fee, family, delay,
                no, nt, cash, base_side, base_price, base_best, last_add, flatten, flatten_reason)
            pending_evaluation = pending_evaluation or changed

        # ----------------------------------------
        longs = 0
        shorts = 0
        reserved_longs = 0
        reserved_shorts = 0
        pe = 0
        px = 0
        equity = cash
        for j in range(count_slots):
            status = int(slots[j, 0])
            if status == 0:
                continue
            side = int(slots[j, 1])
            quantity = int(slots[j, 2])
            if side == 1:
                reserved_longs += quantity
            else:
                reserved_shorts += quantity
            if status == 1:
                pe += quantity
            else:
                if side == 1:
                    longs += quantity
                    liquidation = previous_bid - slip_ticks * tick
                else:
                    shorts += quantity
                    liquidation = previous_ask + slip_ticks * tick
                equity += side * quantity * liquidation * pointvalue - math.floor(quantity * fee + 1e-8)
                if status == 3:
                    px += quantity
        assert stats[2] <= cap and stats[3] <= cap
        curve[i] = equity
        stats[0] = max(stats[0], longs)
        stats[1] = max(stats[1], shorts)
        stats[2] = max(stats[2], reserved_longs)
        stats[3] = max(stats[3], reserved_shorts)
        stats[4] = longs
        stats[5] = shorts
        stats[6] = pe
        stats[7] = px
        stats[11] = max(stats[11], longs + shorts)
    return orders[:no].copy(), trades[:nt].copy(), curve, stats, events[:cursor[0]].copy()
