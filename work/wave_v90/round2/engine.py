"""凍結済み二源の執行へ、指値の気配改善と往復開始時基準だけを独立に追加する。"""

import math
import numpy as np
from numba import njit


ORDER_COLUMNS = ['row', 'decision_row', 'parent_id', 'source', 'action_side', 'quantity', 'price',
                 'is_entry', 'reason', 'fee', 'decision_time', 'fill_time', 'limit_price', 'cycle',
                 'method', 'source_entry_side', 'uid']
TRADE_COLUMNS = ['parent_id', 'source', 'entry_row', 'exit_row', 'side', 'quantity', 'entry_price',
                 'exit_price', 'entry_fee', 'exit_fee', 'gross', 'net', 'entry_reason', 'exit_reason',
                 'cycle', 'entry_decision_row']
TRACE_COLUMNS = ['held_long', 'held_short', 'occupied_long', 'occupied_short', 'pending_entry', 'pending_exit']
EVENT_COLUMNS = ['row', 'parent_id', 'source', 'code', 'side', 'quantity', 'decision_row',
                 'limit_price', 'mode', 'decision_time', 'cycle', 'detail']
STAT_COLUMNS = ['max_held_long', 'max_held_short', 'max_occupied_long', 'max_occupied_short',
                'held_long', 'held_short', 'pending_entry', 'pending_exit', 'max_total_held',
                'range_cancellations', 'cancel_race_fills', 'trend_rejections', 'range_rejections',
                'trend_reservations', 'range_reservations', 'cash']
SLOT_COLUMNS = ['status', 'side', 'quantity', 'parent_id', 'entry_price', 'entry_row', 'entry_fee',
                'peak', 'stop', 'deadline', 'decision_row', 'decision_time', 'limit_price',
                'cancel_decision_row', 'cancel_decision_time', 'cycle', 'entry_decision_row', 'entry_reason']
REASONS = {1: '初期損切り', 2: '追跡返済', 3: '保有期限', 4: '場内返済',
           5: '指値の利確幅到達', 6: '指値の損切り幅到達', 7: '反対の二市場追従で返済',
           10: '共通方向の新規', 11: '上下到達から持続指値新規'}
EVENT_CODES = {1: '新規予約', 2: '返済予約', 3: '取消判断', 4: '新規約定', 5: '返済約定',
               6: '取消有効', 7: '取消前の約定を保持', 8: '親終了', 9: '新規不参加', 10: '指値基準の再設定',
               11: '往復開始時の基準更新'}


@njit(cache=True, inline='always')
def snapshot(slots, stats):
    """
    機能: 同じ行の途中で解消した保有・予約も最大枚数へ反映する。
    引数: slots/stats (ndarray[float])。
    返り値: ndarray[float] は保有・予約・発注待ちの6数量。
    """
    result = np.zeros(6, np.float64)
    for source in range(2):
        status = int(slots[source, 0])
        if status == 0:
            continue
        side = int(slots[source, 1])
        quantity = slots[source, 2]
        result[2 if side == 1 else 3] += quantity
        if status == 1:
            result[4] += quantity
        else:
            result[0 if side == 1 else 1] += quantity
            if status == 3:
                result[5] += quantity
    for index in range(4):
        stats[index] = max(stats[index], result[index])
    stats[8] = max(stats[8], result[0] + result[1])
    return result


@njit(cache=True, inline='always')
def record_event(events, cursor, slots, source, row, code, mode, detail):
    """
    機能: 予約・取消・約定順を原板行と親識別番号付きで追記する。
    引数: events/slots (ndarray)、cursor/source/row/code/mode (int)、detail (float)。
    返り値: int は次の追記位置。
    """
    assert cursor < len(events)
    decision_row = slots[source, 10]
    decision_time = slots[source, 11]
    if code == 3 or (code == 6 and detail == 0):
        decision_row = slots[source, 13]
        decision_time = slots[source, 14]
    events[cursor] = np.array([row, slots[source, 3], source, code, slots[source, 1], slots[source, 2],
                              decision_row, slots[source, 12], mode, decision_time,
                              slots[source, 15], detail])
    return cursor + 1


@njit(cache=True, inline='always')
def reserve_entry(slots, events, cursor, stats, source, side, quantity, row, stamp,
                  limit_price, parent, cycle, mode):
    """
    機能: 一源の新規を予約し、約定前から方向別上限を占有する。
    引数: slots/events/stats (ndarray)、cursor等 (int)、stamp/limit_price (float)。
    返り値: int は次のイベント追記位置。
    """
    slots[source, :] = 0
    slots[source, 0] = 1
    slots[source, 1] = side
    slots[source, 2] = quantity
    slots[source, 3] = parent
    slots[source, 10] = row
    slots[source, 11] = stamp
    slots[source, 12] = limit_price
    slots[source, 13] = -1
    slots[source, 15] = cycle
    slots[source, 16] = row
    slots[source, 17] = 10 if source == 0 else 11
    cursor = record_event(events, cursor, slots, source, row, 1, mode, 0)
    snapshot(slots, stats)
    return cursor


@njit(cache=True, inline='always')
def reserve_exit(slots, events, cursor, source, row, stamp, reason, mode):
    """
    機能: 返済を予約し、次有効気配までは保有数量を残す。
    引数: slots/events (ndarray)、cursor/source/row/reason/mode (int)、stamp (float)。
    返り値: int は次のイベント追記位置。
    """
    slots[source, 0] = 3
    slots[source, 10] = row
    slots[source, 11] = stamp
    return record_event(events, cursor, slots, source, row, 2, mode, reason)


@njit(cache=True, nogil=True)
def simulate(times, prices, bids, asks, price_valid, quote_valid, quality, reset, event, mapped,
             grid, mode_values, tick, start, limit, trend_width, trend_budget, range_budget,
             selection, cancel_pending, exit_opposite_range, value, fee_unit, cap,
             width_ticks, stop_multiple, target_multiple, hold_seconds, improve_limit, activate_anchor):
    """
    機能: 原板順に二源の予約・取消・約定と全原板清算時価を計算する。
    引数: 原板/信号 (ndarray)、価格時刻料金 (float)、数量選択 (int)、取消返済と追加二軸 (bool)。
    返り値: tuple はorders/trades/curve/source_curve/target_trace/events/stats/slots。
    improve_limitは指値成立時の買ask/売bidを使う気配改善代理。
    activate_anchorは往復新規可能のfalse→trueで当時価格を基準にする。
    指値成立を取消効力より先に扱い、通常注文は判断行より後の気配でのみ約定する。
    """
    n = len(times)
    allocation = max(2048, n * 2 + 64)
    orders = np.zeros((allocation, 17), np.float64)
    trades = np.zeros((allocation // 2 + 64, 16), np.float64)
    events = np.zeros((allocation * 2, 12), np.float64)
    curve = np.zeros(n, np.float64)
    source_curve = np.zeros((n, 2), np.float64)
    trace = np.zeros((n, 6), np.float64)
    slots = np.zeros((2, 18), np.float64)
    stats = np.zeros(16, np.float64)
    cash = np.zeros(2, np.float64)
    exit_reason = np.zeros(2, np.int64)
    cycles = np.zeros(2, np.int64)
    last_exit = -1e30
    last_bid = last_ask = np.nan
    latest = -1
    parent = 1
    no = nt = ne = 0
    range_anchor = np.nan
    reset_anchor_after = -1
    last_anchor_row = -1
    previous_range_eligible = False
    previous_price = np.nan
    previous_rejected_side = 0
    width = width_ticks * tick
    entry_cut = limit - 300.0
    range_entry_cut = limit - 120.0
    force_time = limit - 60.0
    closing = False

    for i in range(n):
        stamp = times[i]
        qok = quote_valid[i] and np.isfinite(bids[i]) and np.isfinite(asks[i]) and bids[i] > 0 and asks[i] > bids[i]
        if qok:
            last_bid, last_ask = bids[i], asks[i]
        updated = int(mapped[i])
        if updated >= 0:
            latest = updated
        fresh = latest >= 0 and stamp - grid[latest] <= 10.0 + 1e-8
        mode = int(mode_values[latest]) if fresh else 0

        # ----------------------------------------
        # 既知の場末だけは通常取消・判断遅延と区別して先行させる。
        if stamp >= range_entry_cut and slots[1, 0] == 1:
            ne = record_event(events, ne, slots, 1, i, 6, mode, 1)
            slots[1, 0] = 0
            stats[9] += 1
        if stamp >= entry_cut and slots[0, 0] == 1:
            ne = record_event(events, ne, slots, 0, i, 6, mode, 1)
            slots[0, 0] = 0
        if not closing and stamp >= force_time:
            closing = True
            for source in range(2):
                if slots[source, 0] == 2:
                    exit_reason[source] = 4
                    ne = reserve_exit(slots, events, ne, source, i - 1, force_time, 4, mode)
                    events[ne - 1, 0] = i

        # ----------------------------------------
        # 生きていた指値、次の成行、取消の順。取消前の成立は消さない。
        for source in range(2):
            status = int(slots[source, 0])
            if status != 1 and status != 3:
                continue
            if not qok or i <= slots[source, 10]:
                continue
            side = int(slots[source, 1])
            quantity = int(slots[source, 2])
            is_entry = status == 1
            action = side if is_entry else -side
            fill = asks[i] if action == 1 else bids[i]
            can_fill = True
            if is_entry and source == 1:
                limit_price = slots[source, 12]
                can_fill = asks[i] <= limit_price if side == 1 else bids[i] >= limit_price
                if can_fill and not improve_limit:
                    fill = limit_price
            if can_fill:
                assert no < len(orders)
                fee = math.floor(quantity * fee_unit + 1e-8)
                reason = int(slots[source, 17]) if is_entry else int(exit_reason[source])
                orders[no] = np.array([i, slots[source, 10], slots[source, 3], source, action, quantity,
                                       fill, 1 if is_entry else 0, reason, fee, slots[source, 11], stamp,
                                       slots[source, 12] if is_entry else 0, slots[source, 15],
                                       1 if is_entry and source == 1 else 0, side, no + 1])
                no += 1
                cash[source] -= action * quantity * fill * value + fee
                if is_entry:
                    if source == 1 and slots[source, 13] >= 0:
                        stats[10] += 1
                        ne = record_event(events, ne, slots, source, i, 7, mode, 0)
                    slots[source, 0] = 2
                    slots[source, 4] = fill
                    slots[source, 5] = i
                    slots[source, 6] = fee
                    slots[source, 7] = fill
                    slots[source, 8] = fill - side * trend_width
                    slots[source, 9] = stamp + hold_seconds
                    slots[source, 13] = -1
                    ne = record_event(events, ne, slots, source, i, 4, mode, 0)
                    snapshot(slots, stats)
                else:
                    assert nt < len(trades)
                    gross = side * (fill - slots[source, 4]) * quantity * value
                    trades[nt] = np.array([slots[source, 3], source, slots[source, 5], i, side, quantity,
                                          slots[source, 4], fill, slots[source, 6], fee, gross,
                                          gross - slots[source, 6] - fee, slots[source, 17], reason,
                                          slots[source, 15], slots[source, 16]])
                    nt += 1
                    ne = record_event(events, ne, slots, source, i, 5, mode, reason)
                    ne = record_event(events, ne, slots, source, i, 8, mode, gross - slots[source, 6] - fee)
                    slots[source, 0] = 0
                    if source == 0:
                        last_exit = stamp
                    elif price_valid[i]:
                        range_anchor = prices[i]
                        cycles[1] += 1
                        last_anchor_row = i
                        previous_rejected_side = 0
                        events[ne] = np.array([i, 0, 1, 10, 0, range_budget, i, range_anchor, mode, stamp, cycles[1], 0])
                        ne += 1
            elif source == 1 and slots[source, 13] >= 0 and i > slots[source, 13]:
                ne = record_event(events, ne, slots, source, i, 6, mode, 0)
                slots[source, 0] = 0
                stats[9] += 1
                reset_anchor_after = i
                range_anchor = np.nan
                previous_rejected_side = 0

        # ----------------------------------------
        # 通常返済は新規約定と別の観測から。指標欠測だけで保有を捨てない。
        for source in range(2):
            if slots[source, 0] != 2 or i <= slots[source, 5]:
                continue
            side = int(slots[source, 1])
            reason = 0
            if closing:
                reason = 4
            elif source == 0:
                if stamp >= slots[source, 9]:
                    reason = 3
                elif qok:
                    quote = bids[i] if side == 1 else asks[i]
                    if side * (quote - slots[source, 8]) <= tick * 1e-8:
                        reason = 1 if abs(slots[source, 7] - slots[source, 4]) < tick * 1e-8 else 2
                    else:
                        if side * (quote - slots[source, 7]) > 0:
                            slots[source, 7] = quote
                        candidate = slots[source, 7] - side * trend_width
                        if side * (candidate - slots[source, 8]) > 0:
                            slots[source, 8] = candidate
            elif price_valid[i]:
                progress = side * (prices[i] - slots[source, 4])
                if progress <= -stop_multiple * width:
                    reason = 6
                elif progress >= target_multiple * width:
                    reason = 5
                elif exit_opposite_range and mode == -side:
                    reason = 7
            if reason:
                exit_reason[source] = reason
                ne = reserve_exit(slots, events, ne, source, i, stamp, reason, mode)

        # ----------------------------------------
        # 指値の失効判断。取消効力は次の有効気配、そこでも成立を先に扱う。
        if cancel_pending and slots[1, 0] == 1 and slots[1, 13] < 0 and mode != 2:
            slots[1, 13] = i
            slots[1, 14] = stamp
            ne = record_event(events, ne, slots, 1, i, 3, mode, 0)

        # ----------------------------------------
        # 追従源は元のJ2入口を保持。配分源は独立、選択源は一親の枠を共有する。
        if (trend_budget > 0 and slots[0, 0] == 0 and event[i] != 0 and quality[i]
                and not reset[i] and qok and stamp >= start + 300.0 and stamp < entry_cut
                and stamp - last_exit >= 30.0):
            side = int(event[i])
            allowed = selection == 0 or mode == side
            free = selection != 1 or slots[1, 0] == 0
            if allowed and free:
                cycles[0] += 1
                ne = reserve_entry(slots, events, ne, stats, 0, side, trend_budget, i, stamp,
                                   0, parent, cycles[0], mode)
                parent += 1
                stats[13] += 1
            else:
                stats[11] += 1
                events[ne] = np.array([i, 0, 0, 9, side, trend_budget, i, 0, mode, stamp, cycles[0], 0])
                ne += 1

        # ----------------------------------------
        # 基準O06は初期・全返済だけ更新。追加軸だけ往復参加開始に再基準化する。
        range_eligible = (range_budget > 0 and selection != 0 and mode == 2
                          and slots[1, 0] == 0 and (selection != 1 or slots[0, 0] == 0)
                          and not closing and stamp < range_entry_cut and price_valid[i] and qok
                          and i > reset_anchor_after)
        if range_budget > 0 and price_valid[i] and i > reset_anchor_after:
            if not np.isfinite(range_anchor):
                range_anchor = prices[i]
                cycles[1] += 1
                last_anchor_row = i
                events[ne] = np.array([i, 0, 1, 10, 0, range_budget, i, range_anchor, mode, stamp, cycles[1], 0])
                ne += 1
            # 往復開始時だけ再基準化。保有中・未約定中や取消効力行へ遡らない。
            if activate_anchor and range_eligible and not previous_range_eligible:
                range_anchor = prices[i]
                if last_anchor_row != i:
                    cycles[1] += 1
                last_anchor_row = i
                previous_rejected_side = 0
                events[ne] = np.array([i, 0, 1, 11, 0, range_budget, i, range_anchor, mode, stamp, cycles[1], 0])
                ne += 1
            if slots[1, 0] == 0 and not closing and stamp < range_entry_cut and qok:
                side = 1 if prices[i] <= range_anchor - width else -1 if prices[i] >= range_anchor + width else 0
                allowed = selection == 0 or mode == 2
                free = selection != 1 or slots[0, 0] == 0
                if side:
                    if allowed and free:
                        ne = reserve_entry(slots, events, ne, stats, 1, side, range_budget, i, stamp,
                                           range_anchor - side * width, parent, cycles[1], mode)
                        parent += 1
                        stats[14] += 1
                        previous_rejected_side = 0
                    elif (prices[i] != previous_price or updated >= 0 or side != previous_rejected_side):
                        stats[12] += 1
                        events[ne] = np.array([i, 0, 1, 9, side, range_budget, i, range_anchor - side * width,
                                              mode, stamp, cycles[1], 0])
                        ne += 1
                        previous_rejected_side = side
                else:
                    previous_rejected_side = 0
            previous_price = prices[i]
        previous_range_eligible = range_eligible

        # ----------------------------------------
        # 未返済玉は全行で売bid・買askに清算し、残玉返済料金も控除する。
        trace[i] = snapshot(slots, stats)
        assert stats[2] <= cap and stats[3] <= cap
        for source in range(2):
            equity = cash[source]
            if slots[source, 0] == 2 or slots[source, 0] == 3:
                side = int(slots[source, 1])
                quantity = int(slots[source, 2])
                liquidation = last_bid if side == 1 else last_ask
                equity += side * quantity * liquidation * value - math.floor(quantity * fee_unit + 1e-8)
            source_curve[i, source] = equity
        curve[i] = source_curve[i, 0] + source_curve[i, 1]
    if n:
        stats[4] = trace[-1, 0]
        stats[5] = trace[-1, 1]
        stats[6] = trace[-1, 4]
        stats[7] = trace[-1, 5]
    stats[15] = cash[0] + cash[1]
    return orders[:no].copy(), trades[:nt].copy(), curve, source_curve, trace, events[:ne].copy(), stats, slots


def execute(record, signal, config, finish=True):
    """
    機能: 商品倍率と枚数を設定して二源共通エンジンを実行する。
    引数: record (dict) は原板、signal (dict) は過去状態、config (dict)、finish (bool)。
    返り値: dict は注文・源別決済親・全原板清算時価・予約台帳・列定義。
    finish=Trueでは既知の場末まである完全入力の最終全返済を要求する。
    人工又は未来切断のprefixはfinish=Falseで端点の強制清算を作らない。
    """
    symbol = record['symbol']
    scale, value, fee_unit, cap = (1, 1000.0, 41.8, 10) if symbol == 'TOPIX' else (2, 10.0, 11.0, 20)
    trend_budget = int(config['trend_budget']) * scale
    range_budget = int(config['range_budget']) * scale
    selection = {'fixed': 0, 'regime': 1, 'gated_fixed': 2}[config['selection']]
    assert 0 <= trend_budget <= cap and 0 <= range_budget <= cap
    if selection != 1:
        assert trend_budget + range_budget <= cap
    output = simulate(record['time_s'], record['price'], record['bid'], record['ask'],
                      record['price_valid'], record['quote_valid'], signal['quality'], signal['reset'],
                      signal['event'], signal['mapped'], signal['grid'], signal['mode'], record['tick'],
                      record['start'], record['limit'], signal['trend_width'], trend_budget, range_budget,
                      selection, bool(config['cancel_pending']), bool(config['exit_opposite_range']),
                      value, fee_unit, cap, float(config.get('width_ticks', 8)),
                      float(config.get('stop_widths', 1)), float(config.get('target_widths', 3)),
                      float(config.get('trend_hold_seconds', 1800)),
                      bool(config.get('improve_limit', False)), bool(config.get('activate_anchor', False)))
    names = ('orders', 'trades', 'curve', 'source_curve', 'target_trace', 'events', 'stats', 'slots')
    answer = dict(zip(names, output))
    answer.update(order_columns=ORDER_COLUMNS, trade_columns=TRADE_COLUMNS, trace_columns=TRACE_COLUMNS,
                  event_columns=EVENT_COLUMNS, stat_columns=STAT_COLUMNS, slot_columns=SLOT_COLUMNS,
                  reasons=REASONS, event_codes=EVENT_CODES)
    if finish:
        assert len(record['time_s']) and record['time_s'][-1] >= record['limit'], '完結入力には既知の場末までの原板が必要です'
        assert np.all(answer['slots'][:, 0] == 0), '場末の未返済又は未約定予約が残りました'
        assert abs(answer['curve'][-1] - answer['stats'][15]) < 1e-4
    return answer
