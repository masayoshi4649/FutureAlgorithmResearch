"""旧気配の執行を保持し、独立価格の現在可観測性を初回回復へ接続する。"""

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
RANGE_STATE_COLUMNS = ['phase', 'range_anchor', 'peer_anchor', 'width', 'peer_width', 'episode',
                       'watch_side', 'own_low', 'own_low_row', 'own_high', 'own_high_row',
                       'peer_low', 'peer_low_source', 'peer_high', 'peer_high_source',
                       'center_held', 'center_self_seen', 'center_peer_seen', 'last_exit_row',
                       'last_exit_peer_source', 'center_return_row', 'prepared_row',
                       'prepared_peer_source', 'witness_stop', 'range_armed']
RISK_STATE_COLUMNS = ['gate_consumed', 'gate_row', 'gate_accepted', 'gate_side', 'planned_entry',
                      'planned_liquidation', 'spread', 'fee_width', 'planned_extreme_risk',
                      'center_gain', 'risk_proxy', 'center_ratio', 'entry_failure_line',
                      'entry_target_line', 'entry_center', 'entry_peer_center', 'entry_width',
                      'entry_peer_width', 'exit_width_flag', 'exit_witness_flag', 'exit_target_flag',
                      'failure_paused', 'failure_center', 'failure_peer_center', 'failure_width',
                      'failure_peer_width', 'failure_exit_row', 'failure_exit_time',
                      'failure_exit_own_source', 'failure_exit_peer_source', 'failure_false_seen',
                      'failure_false_grid', 'failure_false_own_source', 'failure_false_peer_source',
                      'failure_release_row', 'failure_self_seen', 'failure_peer_seen',
                      'raw_observable', 'raw_range', 'raw_oldest_time']
RANGE_PARENT_COLUMNS = ['parent_id', 'decision_row', 'entry_row', 'exit_row', 'side', 'quantity',
                        'episode', 'center', 'peer_center', 'width', 'peer_width', 'extreme',
                        'extreme_row', 'failure_line', 'planned_entry', 'planned_liquidation',
                        'spread', 'fee_width', 'planned_extreme_risk', 'center_gain', 'risk_proxy',
                        'center_ratio', 'target_line', 'actual_extreme_risk', 'exit_decision_row',
                        'exit_width_flag', 'exit_witness_flag', 'exit_target_flag', 'net',
                        'entry_peer_source', 'exit_peer_source', 'exit_time', 'failure_pause_started']
PRICE_SOURCE_COLUMNS = ['lane', 'grid', 'price_own_index', 'price_peer_index',
                        'price_own_raw_seq', 'price_peer_raw_seq', 'execution_own_index',
                        'execution_peer_index', 'price_own_time', 'price_peer_time',
                        'execution_own_time', 'execution_peer_time', 'price_own_valid',
                        'price_peer_valid', 'price_observable', 'mode', 'context_kind',
                        'context_decision_row', 'context_accepted', 'execution_current_valid',
                        'execution_peer_valid', 'price_mode']
REASONS = {1: '初期損切り', 2: '追跡返済', 3: '保有期限', 4: '場内返済',
           5: '指値の利確幅到達', 6: '指値の損切り幅到達', 7: '反対の二市場追従で返済',
           8: '独立した二市場の反対確認で返済', 9: '往復利益の追跡返済',
           10: '共通方向の新規', 11: '上下到達から持続指値新規',
           12: '逸脱後の回復確認で成行新規', 13: '観測極値の失敗線で返済',
           14: '固定幅と観測極値の停止ORで返済', 15: '準備時中心の利益目標で返済'}
EVENT_CODES = {1: '新規予約', 2: '返済予約', 3: '取消判断', 4: '新規約定', 5: '返済約定',
               6: '取消有効', 7: '取消前の約定を保持', 8: '親終了', 9: '新規不参加', 10: '指値基準の再設定',
               11: '往復開始時の基準更新', 12: '往復仮説を準備', 13: '往復仮説を解除',
               14: '往復利益の追跡を開始', 15: '往復利益の追跡線を更新',
               16: '相手市場の中心を確定', 17: '逸脱方向を一度だけ選択',
               18: '自己市場の安値を更新', 19: '自己市場の高値を更新',
               20: '相手市場の安値を更新', 21: '相手市場の高値を更新',
               22: '回復確認を成立', 23: '実返済後も中心を保持',
               24: '中心帯への帰還を成立', 25: '次の逸脱を再準備',
               26: '中心保持エピソードを解除', 27: '初回回復の入口余地を判定',
               28: '極値失敗の実損切り後に休止', 29: '失敗後の有効なraw往復否定を観測',
               30: '失敗後休止を新観測で解除'}


@njit(cache=True, inline='always')
def range_event(events, cursor, row, code, side, quantity, center, mode, stamp, cycle, detail):
    """
    機能: 保有前後の中心・極値・帰還を当時行に対応する証拠として記録する。
    引数: events(ndarray)、cursor/row/code/side/quantity/mode/cycle(int)、その他(float)。
    返り値: int は次の追記位置。detailの源番号は相手市場の保持済み原板行である。
    """
    assert cursor < len(events)
    events[cursor] = np.array([row, 0, 1, code, side, quantity, row, center,
                              mode, stamp, cycle, detail])
    return cursor + 1


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
             width_ticks, stop_multiple, target_multiple, hold_seconds, improve_limit, activate_anchor,
             persistent_arm, ungated_trend, current_valid, arm_common, reverse_long, reverse_short,
             reverse_trend, reverse_range, actual_range_width, break_widths, profit_trail,
             profit_activate_widths, profit_trail_widths, recovery_market, recovery_confirmation,
             recovery_fraction, adverse_watch_clear, witness_extreme, reentry_kind,
             center_fraction, center_after_all, center_release, peer_mid_values,
             peer_source_values, peer_valid_values, peer_width, peer_tick,
             entry_max_risk_widths, entry_min_center_ratio, stop_or, target_kind,
             center_target_offset, failure_reentry_kind, failure_center_fraction,
             own_source_values, own_source_times, peer_source_times, raw_range_valid,
             raw_range_eligible, raw_oldest_times, price_lane, context_kind,
             price_observable_values, price_own_indices, price_peer_indices,
             price_own_sequences, price_peer_sequences, price_own_times, price_peer_times,
             price_own_valid, price_peer_valid, price_mode_values):
    """
    機能: 原板順に二源の予約・取消・約定と全原板清算時価を計算する。
    引数: 原板/信号 (ndarray)、価格時刻料金と固定幅 (float)、数量選択 (int)、取消返済等 (bool)。
    返り値: tuple は旧8台帳、旧range_state_trace、新risk_state_traceと源別親診断。
    improve_limitは指値成立時の買ask/売bidを使う気配改善代理。
    persistent_armは一度の往復準備を不明状態で引き直さず、明確共同方向又は3幅破綻で解除する。
    reverse_long/shortは入口ERと別に作った格子別の反対確認である。
    指値成立を取消効力より先に扱い、通常注文は判断行より後の気配でのみ約定する。
    """
    n = len(times)
    allocation = max(2048, n * 2 + 64)
    orders = np.zeros((allocation, 17), np.float64)
    trades = np.zeros((allocation // 2 + 64, 16), np.float64)
    events = np.zeros((allocation * 4, 12), np.float64)
    curve = np.zeros(n, np.float64)
    source_curve = np.zeros((n, 2), np.float64)
    trace = np.zeros((n, 6), np.float64)
    range_state_trace = np.zeros((n, 25), np.float64)
    risk_state_trace = np.zeros((n, 40), np.float64)
    price_source_trace = np.zeros((n, 22), np.float64)
    range_parents = np.zeros((allocation // 2 + 64, 33), np.float64)
    range_parent = np.full(33, np.nan)
    slots = np.zeros((2, 18), np.float64)
    stats = np.zeros(16, np.float64)
    cash = np.zeros(2, np.float64)
    exit_reason = np.zeros(2, np.int64)
    cycles = np.zeros(2, np.int64)
    last_exit = -1e30
    last_bid = last_ask = np.nan
    latest = -1
    parent = 1
    no = nt = ne = nrp = 0
    range_anchor = np.nan
    reset_anchor_after = -1
    last_anchor_row = -1
    previous_range_eligible = False
    previous_price = np.nan
    previous_rejected_side = 0
    width = actual_range_width if actual_range_width > 0 else width_ticks * tick
    range_armed = False
    range_trail_active = False
    new_state_enabled = recovery_market or reentry_kind != 0
    peer_anchor = np.nan
    own_low = own_high = peer_low = peer_high = np.nan
    own_low_row = own_high_row = peer_low_source = peer_high_source = -1
    prepared_row = prepared_peer_source = -1
    episode = 0
    watch_side = 0
    witness_stop = np.nan
    center_held = False
    center_self_seen = center_peer_seen = False
    last_range_exit_row = last_range_exit_peer_source = -1
    center_return_row = -1
    reentry_ready = True
    require_reprepare = False
    gate_consumed = False
    gate_row = -1
    gate_accepted = gate_side = 0
    planned_entry = planned_liquidation = planned_spread = fee_width = np.nan
    planned_risk = center_gain = risk_proxy = center_ratio = np.nan
    entry_failure_line = entry_target_line = entry_center = entry_peer_center = np.nan
    entry_width = entry_peer_width = np.nan
    exit_width_flag = exit_witness_flag = exit_target_flag = False
    failure_paused = False
    failure_center = failure_peer_center = failure_width = failure_peer_width = np.nan
    failure_exit_row = failure_exit_own_source = failure_exit_peer_source = -1
    failure_exit_time = -1e30
    failure_false_seen = False
    failure_false_grid = failure_false_own_source = failure_false_peer_source = -1
    failure_release_row = -1
    failure_self_seen = failure_peer_seen = False
    context_decision_row = -1
    context_accepted = 0
    gated_entry = entry_max_risk_widths > 0 or entry_min_center_ratio > 0 or context_kind != 0
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
        current_fresh = fresh and current_valid[latest]
        joint_direction = int(arm_common[latest]) if current_fresh else 0
        peer_ok = (fresh and peer_valid_values[latest] and np.isfinite(peer_mid_values[latest])
                   and peer_mid_values[latest] > 0)
        peer_mid = peer_mid_values[latest] if peer_ok else np.nan
        peer_source = int(peer_source_values[latest]) if peer_ok else -1
        # 欠測でも判断器へ既に公開された源番号は失わない。真の受信時計とは区別する。
        published_peer_source = int(peer_source_values[latest]) if latest >= 0 else -1
        published_own_source = int(own_source_values[latest]) if latest >= 0 else -1
        own_source_time = own_source_times[latest] if latest >= 0 else np.nan
        peer_source_time = peer_source_times[latest] if latest >= 0 else np.nan
        raw_observable = fresh and raw_range_valid[latest]
        raw_range = raw_observable and raw_range_eligible[latest]
        raw_oldest_time = raw_oldest_times[latest] if latest >= 0 else np.nan
        price_observable = fresh and price_observable_values[latest]
        price_mode = int(price_mode_values[latest]) if fresh else 0
        own_mid = .5 * (bids[i] + asks[i]) if qok else np.nan

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
            if is_entry and source == 1 and not recovery_market:
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
                                       1 if is_entry and source == 1 and not recovery_market else 0,
                                       side, no + 1])
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
                    if source == 1 and profit_trail:
                        slots[source, 8] = fill - side * stop_multiple * width
                        range_trail_active = False
                    slots[source, 9] = stamp + hold_seconds
                    slots[source, 13] = -1
                    if source == 1 and recovery_market:
                        range_parent[2] = i
                        range_parent[23] = side * (fill - entry_failure_line)
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
                    elif recovery_market:
                        range_parent[3] = i
                        range_parent[24] = slots[source, 10]
                        range_parent[25] = exit_width_flag
                        range_parent[26] = exit_witness_flag
                        range_parent[27] = exit_target_flag
                        range_parent[28] = gross - slots[source, 6] - fee
                        range_parent[30] = published_peer_source
                        range_parent[31] = stamp
                        range_parent[32] = (failure_reentry_kind != 0 and exit_witness_flag
                                            and range_parent[28] < 0)
                        range_parents[nrp] = range_parent
                        nrp += 1
                    if (source == 1 and failure_reentry_kind != 0 and exit_witness_flag
                            and gross - slots[source, 6] - fee < 0):
                        # 返済予約時の証拠と実返済純額の双方で初めて失敗を確定する。
                        failure_paused = True
                        failure_center, failure_peer_center = entry_center, entry_peer_center
                        failure_width, failure_peer_width = entry_width, entry_peer_width
                        failure_exit_row, failure_exit_time = i, stamp
                        failure_exit_own_source, failure_exit_peer_source = published_own_source, published_peer_source
                        failure_false_seen = False
                        failure_false_grid = failure_false_own_source = failure_false_peer_source = -1
                        failure_release_row = -1
                        failure_self_seen = failure_peer_seen = False
                        range_armed = False
                        range_anchor = peer_anchor = np.nan
                        reset_anchor_after = i
                        range_trail_active = False
                        previous_rejected_side = 0
                        center_held = False
                        watch_side = 0
                        witness_stop = np.nan
                        reentry_ready = True
                        require_reprepare = True
                        ne = range_event(events, ne, i, 28, side, range_budget, failure_center,
                                         mode, stamp, cycles[1], gross - slots[source, 6] - fee)
                    elif (reentry_kind != 0 and np.isfinite(range_anchor) and not require_reprepare
                          and source == 1
                          and (center_after_all or gross - slots[source, 6] - fee > 0)):
                        # 黒字限定は実約定と両側料金の確定netだけで判定する。
                        center_held = True
                        reentry_ready = reentry_kind == 1
                        center_self_seen = center_peer_seen = False
                        last_range_exit_row = i
                        last_range_exit_peer_source = published_peer_source
                        center_return_row = i if reentry_ready else -1
                        range_trail_active = False
                        watch_side = 0
                        witness_stop = np.nan
                        range_armed = persistent_arm
                        ne = range_event(events, ne, i, 23, 0, range_budget, range_anchor,
                                         mode, stamp, cycles[1], gross - slots[source, 6] - fee)
                        if reentry_ready:
                            cycles[1] += 1
                            own_low = own_high = own_mid
                            own_low_row = own_high_row = i
                            peer_low = peer_high = peer_mid
                            peer_low_source = peer_high_source = peer_source
                            prepared_row, prepared_peer_source = i, peer_source
                            ne = range_event(events, ne, i, 25, 0, range_budget, range_anchor,
                                             mode, stamp, cycles[1], peer_source)
                    elif source == 1 and persistent_arm:
                        range_armed = False
                        range_anchor = np.nan
                        reset_anchor_after = i
                        range_trail_active = False
                        previous_rejected_side = 0
                        events[ne] = np.array([i, 0, 1, 13, 0, range_budget, i, 0,
                                              mode, stamp, cycles[1], 3])
                        ne += 1
                        if new_state_enabled:
                            center_held = False
                            peer_anchor = np.nan
                            watch_side = 0
                            witness_stop = np.nan
                            reentry_ready = True
                    elif source == 1 and new_state_enabled and require_reprepare:
                        # 解除済みの保有が後に黒字になっても無効な中心を復活させない。
                        range_anchor = peer_anchor = np.nan
                        center_held = False
                        reset_anchor_after = i
                        watch_side = 0
                        witness_stop = np.nan
                        reentry_ready = True
                    elif source == 1 and price_valid[i]:
                        range_anchor = prices[i]
                        cycles[1] += 1
                        last_anchor_row = i
                        previous_rejected_side = 0
                        events[ne] = np.array([i, 0, 1, 10, 0, range_budget, i, range_anchor, mode, stamp, cycles[1], 0])
                        ne += 1
                        if new_state_enabled:
                            center_held = False
                            peer_anchor = peer_mid
                            episode += 1
                            prepared_row, prepared_peer_source = i, peer_source
                            watch_side = 0
                            witness_stop = np.nan
                            reentry_ready = True
                            if peer_ok:
                                ne = range_event(events, ne, i, 16, 0, range_budget, peer_anchor,
                                                 mode, stamp, cycles[1], peer_source)
            elif source == 1 and slots[source, 13] >= 0 and i > slots[source, 13]:
                ne = record_event(events, ne, slots, source, i, 6, mode, 0)
                slots[source, 0] = 0
                stats[9] += 1
                reset_anchor_after = i
                range_anchor = np.nan
                range_armed = False
                previous_rejected_side = 0
                if new_state_enabled:
                    center_held = False
                    peer_anchor = np.nan
                    watch_side = 0
                    witness_stop = np.nan
                    reentry_ready = True

        # ----------------------------------------
        # 通常返済は新規約定と別の観測から。指標欠測だけで保有を捨てない。
        for source in range(2):
            if slots[source, 0] != 2 or i <= slots[source, 5]:
                continue
            side = int(slots[source, 1])
            reason = 0
            width_hit = (source == 1 and (not witness_extreme or stop_or) and price_valid[i]
                         and side * (prices[i] - slots[source, 4]) <= -stop_multiple * width)
            witness_hit = (source == 1 and witness_extreme and qok and np.isfinite(witness_stop)
                           and side * ((bids[i] if side == 1 else asks[i]) - witness_stop) <= tick * 1e-8)
            if closing:
                reason = 4
            elif ((reverse_trend if source == 0 else reverse_range) and fresh
                  and (reverse_long[latest] if side == 1 else reverse_short[latest])):
                reason = 8
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
            elif stop_or and (width_hit or witness_hit):
                reason = 14
            elif witness_hit:
                reason = 13
            elif price_valid[i]:
                progress = side * (prices[i] - slots[source, 4])
                if not witness_extreme and progress <= -stop_multiple * width:
                    reason = 6
                elif not profit_trail and target_kind != 0 and np.isfinite(entry_target_line) and (
                        side * (prices[i] - entry_target_line) >= -tick * 1e-8):
                    reason = 15
                elif not profit_trail and target_kind == 0 and progress >= target_multiple * width:
                    reason = 5
                elif exit_opposite_range and mode == -side:
                    reason = 7
                elif profit_trail and qok:
                    quote = bids[i] if side == 1 else asks[i]
                    profit = side * (quote - slots[source, 4])
                    if range_trail_active and side * (quote - slots[source, 8]) <= tick * 1e-8:
                        reason = 9
                    else:
                        if not range_trail_active and profit >= profit_activate_widths * width:
                            range_trail_active = True
                            ne = record_event(events, ne, slots, source, i, 14, mode, profit)
                        if side * (quote - slots[source, 7]) > 0:
                            slots[source, 7] = quote
                        if range_trail_active:
                            candidate = slots[source, 7] - side * profit_trail_widths * width
                            if side * (candidate - slots[source, 8]) > 0:
                                slots[source, 8] = candidate
                                ne = record_event(events, ne, slots, source, i, 15, mode, candidate)
            if reason:
                if source == 1:
                    # 停止ORの双方証拠は表示理由の優先に依存させず親へ固定する。
                    exit_width_flag = width_hit if reason in (6, 13, 14) else False
                    exit_witness_flag = witness_hit if reason in (6, 13, 14) else False
                    exit_target_flag = reason == 5 or reason == 15
                exit_reason[source] = reason
                ne = reserve_exit(slots, events, ne, source, i, stamp, reason, mode)

        # ----------------------------------------
        # 指値の失効判断。取消効力は次の有効気配、そこでも成立を先に扱う。
        if (not persistent_arm and cancel_pending and slots[1, 0] == 1
                and slots[1, 13] < 0 and mode != 2):
            slots[1, 13] = i
            slots[1, 14] = stamp
            ne = record_event(events, ne, slots, 1, i, 3, mode, 0)

        # ----------------------------------------
        # 往復仮説は分類不明で保持し、明確な二市場方向又は固定幅の破綻だけで解除する。
        if persistent_arm and range_armed:
            broken = (price_valid[i] and abs(prices[i] - range_anchor) >= break_widths * width - tick * 1e-8)
            common_break = joint_direction != 0
            if recovery_market and adverse_watch_clear and watch_side != 0:
                common_break = joint_direction == -watch_side
            if common_break or broken:
                range_armed = False
                reset_anchor_after = i
                detail = 1 if common_break else 2
                events[ne] = np.array([i, slots[1, 3] if slots[1, 0] else 0, 1, 13,
                                      slots[1, 1] if slots[1, 0] else 0,
                                      slots[1, 2] if slots[1, 0] else range_budget,
                                      i, range_anchor, mode, stamp, cycles[1], detail])
                ne += 1
                if slots[1, 0] == 1 and slots[1, 13] < 0:
                    slots[1, 13] = i
                    slots[1, 14] = stamp
                    ne = record_event(events, ne, slots, 1, i, 3, mode, detail)
                elif slots[1, 0] == 0:
                    range_anchor = np.nan
                if new_state_enabled:
                    center_held = False
                    reentry_ready = True
                    require_reprepare = True
                    peer_anchor = np.nan
                    watch_side = 0
                    center_self_seen = center_peer_seen = False
        elif center_held and center_release:
            # 非持続型の中心保持だけに追加する解除。初回入口の条件は変えない。
            broken = (price_valid[i] and abs(prices[i] - range_anchor) >= break_widths * width - tick * 1e-8)
            if joint_direction != 0 or broken:
                ne = range_event(events, ne, i, 26, 0, range_budget, range_anchor,
                                 mode, stamp, cycles[1], 1 if joint_direction != 0 else 2)
                center_held = False
                reentry_ready = True
                require_reprepare = True
                reset_anchor_after = i
                watch_side = 0
                peer_anchor = np.nan
                center_self_seen = center_peer_seen = False
                if slots[1, 0] == 1 and slots[1, 13] < 0:
                    slots[1, 13] = i
                    slots[1, 14] = stamp
                    ne = record_event(events, ne, slots, 1, i, 3, mode, 1)
                elif slots[1, 0] == 0:
                    range_anchor = np.nan

        # ----------------------------------------
        # 帰還は実返済後の新源を同じ判断行で確認し、別行から次の逸脱を監視する。
        if (new_state_enabled and center_held and not reentry_ready and slots[1, 0] == 0
                and i > last_range_exit_row and price_valid[i] and qok):
            center_self_seen = (price_valid[i] and abs(prices[i] - range_anchor)
                                <= center_fraction * width + tick * 1e-8)
            center_peer_seen = (peer_ok and np.isfinite(peer_anchor)
                                and peer_source > max(last_range_exit_peer_source, prepared_peer_source)
                                and abs(peer_mid - peer_anchor) <= center_fraction * peer_width + peer_tick * 1e-8)
            returned = center_self_seen and (reentry_kind != 3 or center_peer_seen)
            if returned:
                reentry_ready = True
                center_return_row = i
                prepared_row, prepared_peer_source = i, peer_source
                own_low = own_high = own_mid
                own_low_row = own_high_row = i
                peer_low = peer_high = peer_mid
                peer_low_source = peer_high_source = peer_source
                watch_side = 0
                cycles[1] += 1
                ne = range_event(events, ne, i, 24, 0, range_budget, range_anchor,
                                 mode, stamp, cycles[1], peer_source)
                ne = range_event(events, ne, i, 25, 0, range_budget, range_anchor,
                                 mode, stamp, cycles[1], peer_source)
        elif new_state_enabled and center_held and not reentry_ready:
            center_self_seen = center_peer_seen = False

        # ----------------------------------------
        # 失敗中心は新注文の中心から隔離し、実返済後の新しい観測だけで休止を解く。
        if failure_paused and slots[1, 0] == 0 and i > failure_exit_row:
            failure_self_seen = (price_valid[i] and qok and np.isfinite(failure_center)
                                 and abs(prices[i] - failure_center)
                                 <= failure_center_fraction * failure_width + tick * 1e-8)
            failure_peer_seen = (peer_ok and np.isfinite(failure_peer_center)
                                 and peer_source > failure_exit_peer_source
                                 and np.isfinite(peer_source_time) and peer_source_time > failure_exit_time
                                 and abs(peer_mid - failure_peer_center)
                                 <= failure_center_fraction * failure_peer_width + peer_tick * 1e-8)
            released = False
            if failure_reentry_kind == 1:
                released = failure_self_seen
            elif failure_reentry_kind == 2:
                released = failure_self_seen and failure_peer_seen
            elif failure_reentry_kind == 3:
                # 300秒・180秒・共同方向窓の最古の実源まで実返済後であることを要求する。
                new_observation = (updated >= 0 and raw_observable
                                   and np.isfinite(raw_oldest_time) and raw_oldest_time > failure_exit_time
                                   and published_own_source > failure_exit_own_source
                                   and published_peer_source > failure_exit_peer_source
                                   and np.isfinite(own_source_time) and own_source_time > failure_exit_time
                                   and np.isfinite(peer_source_time) and peer_source_time > failure_exit_time)
                if new_observation and not raw_range and not failure_false_seen:
                    failure_false_seen = True
                    failure_false_grid = latest
                    failure_false_own_source, failure_false_peer_source = published_own_source, published_peer_source
                    ne = range_event(events, ne, i, 29, 0, range_budget, failure_center,
                                     mode, stamp, cycles[1], latest)
                if (new_observation and failure_false_seen and latest > failure_false_grid
                        and raw_range and mode == 2
                        and published_own_source > failure_false_own_source
                        and published_peer_source > failure_false_peer_source):
                    released = True
            if released:
                failure_paused = False
                failure_release_row = i
                reset_anchor_after = i
                range_anchor = peer_anchor = np.nan
                range_armed = False
                require_reprepare = True
                ne = range_event(events, ne, i, 30, 0, range_budget, failure_center,
                                 mode, stamp, cycles[1], failure_reentry_kind)

        # ----------------------------------------
        # 追従源は元のJ2入口を保持。配分源は独立、選択源は一親の枠を共有する。
        if (trend_budget > 0 and slots[0, 0] == 0 and event[i] != 0 and quality[i]
                and not reset[i] and qok and stamp >= start + 300.0 and stamp < entry_cut
                and stamp - last_exit >= 30.0):
            side = int(event[i])
            allowed = ungated_trend or selection == 0 or mode == side
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
        # 持続仮説だけ低ERの初回に準備し、旧対照の基準更新を独立した分岐で保持する。
        range_eligible = (range_budget > 0 and selection != 0 and mode == 2
                          and slots[1, 0] == 0 and (selection != 1 or slots[0, 0] == 0)
                          and not closing and stamp < range_entry_cut and price_valid[i] and qok
                          and i > reset_anchor_after and not failure_paused)
        if (range_budget > 0 and (price_valid[i] or (recovery_market and qok))
                and i > reset_anchor_after and not failure_paused):
            if persistent_arm:
                if (not range_armed and slots[1, 0] == 0 and mode == 2 and current_fresh
                        and price_valid[i] and qok and (not recovery_market or peer_ok)
                        and not closing and stamp < range_entry_cut
                        and (selection != 1 or slots[0, 0] == 0)):
                    range_armed = True
                    range_anchor = prices[i]
                    cycles[1] += 1
                    last_anchor_row = i
                    previous_rejected_side = 0
                    events[ne] = np.array([i, 0, 1, 12, 0, range_budget, i, range_anchor,
                                          mode, stamp, cycles[1], width])
                    ne += 1
                    if new_state_enabled:
                        peer_anchor = peer_mid
                        episode += 1
                        prepared_row, prepared_peer_source = i, peer_source
                        own_low = own_high = own_mid
                        own_low_row = own_high_row = i
                        peer_low = peer_high = peer_mid
                        peer_low_source = peer_high_source = peer_source
                        watch_side = 0
                        witness_stop = np.nan
                        require_reprepare = False
                        gate_consumed = False
                        gate_row = -1
                        gate_accepted = gate_side = 0
                        context_decision_row = -1
                        context_accepted = 0
                        planned_entry = planned_liquidation = planned_spread = fee_width = np.nan
                        planned_risk = center_gain = risk_proxy = center_ratio = np.nan
                        if peer_ok:
                            ne = range_event(events, ne, i, 16, 0, range_budget, peer_anchor,
                                             mode, stamp, cycles[1], peer_source)
            else:
                can_prepare = (not require_reprepare or (mode == 2 and current_fresh and qok
                               and peer_ok and slots[1, 0] == 0 and not closing
                               and stamp < range_entry_cut))
                if not np.isfinite(range_anchor) and can_prepare:
                    range_anchor = prices[i]
                    cycles[1] += 1
                    last_anchor_row = i
                    events[ne] = np.array([i, 0, 1, 10, 0, range_budget, i, range_anchor, mode, stamp, cycles[1], 0])
                    ne += 1
                    if new_state_enabled:
                        peer_anchor = peer_mid
                        episode += 1
                        prepared_row, prepared_peer_source = i, peer_source
                        require_reprepare = False
                        if peer_ok:
                            ne = range_event(events, ne, i, 16, 0, range_budget, peer_anchor,
                                             mode, stamp, cycles[1], peer_source)
                # 旧A対照は往復参加開始時だけ再基準化する。
                if activate_anchor and range_eligible and not previous_range_eligible:
                    range_anchor = prices[i]
                    if last_anchor_row != i:
                        cycles[1] += 1
                    last_anchor_row = i
                    previous_rejected_side = 0
                    events[ne] = np.array([i, 0, 1, 11, 0, range_budget, i, range_anchor, mode, stamp, cycles[1], 0])
                    ne += 1
            # 相手格子がまだ無い初回は、最初に公開された有効源で中心を確定する。
            if (new_state_enabled and not require_reprepare and np.isfinite(range_anchor)
                    and not np.isfinite(peer_anchor) and peer_ok):
                peer_anchor = peer_mid
                # 初めての相手中心作成は帰還ではない。この源より新たな公開を待つ。
                prepared_peer_source = peer_source
                ne = range_event(events, ne, i, 16, 0, range_budget, peer_anchor,
                                 mode, stamp, cycles[1], peer_source)

            # ----------------------------------------
            # 極値は実価格が進んだ時だけ更新し、同値へ新しい源時刻を貼り直さない。
            if recovery_market and range_armed and reentry_ready and slots[1, 0] == 0:
                if qok:
                    if not np.isfinite(own_low) or own_mid < own_low:
                        own_low, own_low_row = own_mid, i
                        ne = range_event(events, ne, i, 18, watch_side, range_budget, own_low,
                                         mode, stamp, cycles[1], own_low_row)
                    if not np.isfinite(own_high) or own_mid > own_high:
                        own_high, own_high_row = own_mid, i
                        ne = range_event(events, ne, i, 19, watch_side, range_budget, own_high,
                                         mode, stamp, cycles[1], own_high_row)
                if peer_ok:
                    if not np.isfinite(peer_low) or peer_mid < peer_low:
                        peer_low, peer_low_source = peer_mid, peer_source
                        ne = range_event(events, ne, i, 20, watch_side, range_budget, peer_low,
                                         mode, stamp, cycles[1], peer_low_source)
                    if not np.isfinite(peer_high) or peer_mid > peer_high:
                        peer_high, peer_high_source = peer_mid, peer_source
                        ne = range_event(events, ne, i, 21, watch_side, range_budget, peer_high,
                                         mode, stamp, cycles[1], peer_high_source)
            if slots[1, 0] == 0 and not closing and stamp < range_entry_cut and qok:
                side = 1 if prices[i] <= range_anchor - width else -1 if prices[i] >= range_anchor + width else 0
                allowed = (range_armed and current_fresh) if persistent_arm else (selection == 0 or mode == 2)
                free = selection != 1 or slots[0, 0] == 0
                if new_state_enabled:
                    allowed = allowed and not require_reprepare
                    if center_held:
                        allowed = allowed and reentry_ready
                        if reentry_kind != 1:
                            allowed = allowed and i > center_return_row
                        elif recovery_market:
                            allowed = allowed and i > prepared_row
                if recovery_market:
                    allowed = allowed and peer_ok and not gate_consumed
                    if side and watch_side == 0 and price_valid[i] and allowed and free:
                        watch_side = side
                        ne = range_event(events, ne, i, 17, side, range_budget,
                                         range_anchor - side * width, mode, stamp, cycles[1], prices[i])
                    side = watch_side
                    own_extreme = own_low if side == 1 else own_high
                    own_extreme_row = own_low_row if side == 1 else own_high_row
                    peer_extreme = peer_low if side == 1 else peer_high
                    peer_extreme_source = peer_low_source if side == 1 else peer_high_source
                    self_recovered = (side != 0 and i > own_extreme_row and np.isfinite(own_extreme)
                                      and side * (own_mid - own_extreme) >= recovery_fraction * width - tick * 1e-8)
                    peer_recovered = (side != 0 and peer_source > peer_extreme_source
                                      and np.isfinite(peer_extreme) and peer_ok
                                      and side * (peer_mid - peer_extreme)
                                      >= recovery_fraction * peer_width - peer_tick * 1e-8)
                    confirmed = (recovery_confirmation == 0 or (self_recovered and
                                 (recovery_confirmation == 1 or peer_recovered)))
                    if side and allowed and free and confirmed:
                        # 判断行の予定気配と観測極値だけを使い、次約定へ先取りしない。
                        planned_entry = asks[i] if side == 1 else bids[i]
                        planned_liquidation = bids[i] if side == 1 else asks[i]
                        planned_spread = asks[i] - bids[i]
                        fee_width = 2. * math.floor(range_budget * fee_unit + 1e-8) / (range_budget * value)
                        candidate_failure = own_extreme - side * tick
                        planned_risk = side * (planned_entry - candidate_failure)
                        center_gain = side * (range_anchor - planned_entry) - planned_spread - fee_width
                        risk_proxy = min(planned_risk, width + planned_spread) + fee_width
                        center_ratio = center_gain / risk_proxy if risk_proxy > 0 else np.nan
                        accepted = True
                        if context_kind != 0:
                            accepted = price_observable and (context_kind != 2 or price_mode == 2)
                            context_decision_row, context_accepted = i, int(accepted)
                        if entry_max_risk_widths > 0:
                            accepted = (accepted and planned_risk > 0
                                        and planned_risk <= entry_max_risk_widths * width + tick * 1e-8)
                        if entry_min_center_ratio > 0:
                            accepted = (accepted and planned_risk > 0 and center_gain > 0 and risk_proxy > 0
                                        and side * (planned_liquidation - candidate_failure) > tick * 1e-8
                                        and center_ratio >= entry_min_center_ratio - 1e-12)
                        if gated_entry:
                            gate_consumed = True
                            gate_row, gate_accepted, gate_side = i, int(accepted), side
                            ne = range_event(events, ne, i, 27, side, range_budget, planned_entry,
                                             mode, stamp, cycles[1], 1 if accepted else 0)
                        if accepted:
                            entry_failure_line = candidate_failure
                            entry_center, entry_peer_center = range_anchor, peer_anchor
                            entry_width, entry_peer_width = width, peer_width
                            entry_target_line = (range_anchor + side * center_target_offset * width
                                                 if target_kind != 0 else np.nan)
                            exit_width_flag = exit_witness_flag = exit_target_flag = False
                            witness_stop = entry_failure_line if witness_extreme else np.nan
                            range_parent[:] = np.nan
                            range_parent[0] = parent
                            range_parent[1] = i
                            range_parent[4:23] = np.array([side, range_budget, episode, entry_center,
                                entry_peer_center, width, peer_width, own_extreme, own_extreme_row,
                                entry_failure_line, planned_entry, planned_liquidation, planned_spread,
                                fee_width, planned_risk, center_gain, risk_proxy, center_ratio, entry_target_line])
                            range_parent[29] = peer_source
                            ne = range_event(events, ne, i, 22, side, range_budget, own_extreme,
                                             mode, stamp, cycles[1], peer_extreme_source)
                            ne = reserve_entry(slots, events, ne, stats, 1, side, range_budget, i, stamp,
                                               0, parent, cycles[1], mode)
                            slots[1, 17] = 12
                            parent += 1
                            stats[14] += 1
                            previous_rejected_side = 0
                    elif side and (prices[i] != previous_price or updated >= 0 or side != previous_rejected_side):
                        stats[12] += 1
                        events[ne] = np.array([i, 0, 1, 9, side, range_budget, i, 0,
                                              mode, stamp, cycles[1], 0])
                        ne += 1
                        previous_rejected_side = side
                    elif not side:
                        previous_rejected_side = 0
                elif side:
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
        if new_state_enabled:
            phase = 1 if np.isfinite(range_anchor) else 0
            if center_held:
                phase = 6 if reentry_ready else 5
            if watch_side != 0:
                phase = 2
            if slots[1, 0] == 1:
                phase = 3
            elif slots[1, 0] == 2 or slots[1, 0] == 3:
                phase = 4
            range_state_trace[i] = np.array([phase, range_anchor, peer_anchor, width, peer_width,
                                             episode, watch_side, own_low, own_low_row, own_high,
                                             own_high_row, peer_low, peer_low_source, peer_high,
                                             peer_high_source, center_held, center_self_seen,
                                             center_peer_seen, last_range_exit_row,
                                             last_range_exit_peer_source, center_return_row,
                                             prepared_row, prepared_peer_source, witness_stop, range_armed])
        risk_state_trace[i] = np.array([gate_consumed, gate_row, gate_accepted, gate_side,
            planned_entry, planned_liquidation, planned_spread, fee_width, planned_risk, center_gain,
            risk_proxy, center_ratio, entry_failure_line, entry_target_line, entry_center,
            entry_peer_center, entry_width, entry_peer_width, exit_width_flag, exit_witness_flag,
            exit_target_flag, failure_paused, failure_center, failure_peer_center, failure_width,
            failure_peer_width, failure_exit_row, failure_exit_time, failure_exit_own_source,
            failure_exit_peer_source, failure_false_seen, failure_false_grid, failure_false_own_source,
            failure_false_peer_source, failure_release_row, failure_self_seen, failure_peer_seen,
            raw_observable, raw_range, raw_oldest_time])
        if latest >= 0:
            price_source_trace[i] = np.array([price_lane, latest, price_own_indices[latest],
                price_peer_indices[latest], price_own_sequences[latest], price_peer_sequences[latest],
                published_own_source, published_peer_source, price_own_times[latest],
                price_peer_times[latest], own_source_time, peer_source_time, price_own_valid[latest],
                price_peer_valid[latest], price_observable, mode, context_kind, context_decision_row,
                context_accepted, current_fresh, peer_ok, price_mode])
        else:
            price_source_trace[i] = np.array([price_lane, -1, -1, -1, -1, -1, -1, -1,
                np.nan, np.nan, np.nan, np.nan, 0, 0, 0, 0, context_kind,
                context_decision_row, context_accepted, 0, 0, 0])
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
    return (orders[:no].copy(), trades[:nt].copy(), curve, source_curve, trace,
            events[:ne].copy(), stats, slots, range_state_trace, risk_state_trace,
            range_parents[:nrp].copy(), price_source_trace)


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
    reverse_sources = config.get('reverse_sources', 'none')
    assert reverse_sources in ('none', 'trend', 'range', 'both')
    persistent_arm = bool(config.get('persistent_arm', False))
    assert not persistent_arm or float(config.get('break_widths', 3)) >= 3
    assert config.get('arm_direction_kind', 'common') in ('common', 'trend300')
    profit_mode = config.get('range_profit_mode', 'target')
    assert profit_mode in ('target', 'trail')
    entry_kind = config.get('range_entry_kind', 'limit')
    assert entry_kind in ('limit', 'recovery_market')
    confirmation = config.get('recovery_confirmation', 'none')
    assert confirmation in ('none', 'self', 'both')
    reentry_kind = config.get('range_reentry_kind', 'legacy')
    assert reentry_kind in ('legacy', 'keep', 'return_self', 'return_both')
    stop_kind = config.get('range_stop_kind', 'width')
    assert stop_kind in ('width', 'witness_extreme', 'width_or_witness')
    assert stop_kind == 'width' or entry_kind == 'recovery_market'
    target_kind = config.get('range_target_kind', 'widths')
    assert target_kind in ('widths', 'center', 'center_plus')
    target_offset = float(config.get('range_center_target_offset', 0))
    assert target_offset >= 0
    assert target_kind != 'center' or target_offset == 0
    failure_kind = config.get('range_failure_reentry_kind', 'legacy')
    assert failure_kind in ('legacy', 'return_self', 'return_both', 'prepare_reset')
    assert failure_kind == 'legacy' or stop_kind == 'width_or_witness'
    max_risk = float(config.get('range_entry_max_risk_widths', 0))
    min_ratio = float(config.get('range_entry_min_center_ratio', 0))
    price_lane = config.get('price_lane', 'I0')
    context = config.get('range_entry_context', 'legacy')
    assert price_lane in ('I0', 'I1', 'I2', 'I3')
    assert context in ('legacy', 'observable', 'confirmed_range')
    assert context == 'legacy' or entry_kind == 'recovery_market'
    assert max_risk >= 0 and min_ratio >= 0
    assert not (max_risk > 0 or min_ratio > 0 or target_kind != 'widths') or entry_kind == 'recovery_market'
    assert target_kind == 'widths' or profit_mode == 'target'
    assert config.get('watch_clear_common', 'any') in ('any', 'adverse')
    assert config.get('center_after', 'profit') in ('profit', 'all')
    size = len(signal['grid'])
    default_valid = np.ones(size, dtype=bool)
    default_direction = np.zeros(size, dtype=np.int8)
    default_reverse = np.zeros(size, dtype=bool)
    if failure_kind != 'legacy':
        for field in ('own_source', 'own_source_time', 'peer_source_time', 'raw_range_valid',
                      'raw_range_eligible', 'raw_oldest_time'):
            assert field in signal, f'失敗後の新観測確認には{field}が必要です'
    if context != 'legacy':
        assert 'price_observable' in signal, '現在の新規資格には独立価格の可観測性が必要です'
    output = simulate(record['time_s'], record['price'], record['bid'], record['ask'],
                      record['price_valid'], record['quote_valid'], signal['quality'], signal['reset'],
                      signal['event'], signal['mapped'], signal['grid'], signal['mode'], record['tick'],
                      record['start'], record['limit'], signal['trend_width'], trend_budget, range_budget,
                      selection, bool(config['cancel_pending']), bool(config['exit_opposite_range']),
                      value, fee_unit, cap, float(config.get('width_ticks', 8)),
                      float(config.get('stop_widths', 1)), float(config.get('target_widths', 3)),
                      float(config.get('trend_hold_seconds', 1800)),
                      bool(config.get('improve_limit', False)), bool(config.get('activate_anchor', False)),
                      persistent_arm, bool(config.get('ungated_trend', False)),
                      signal.get('current_valid', default_valid),
                      signal.get('arm_trend300' if config.get('arm_direction_kind', 'common') == 'trend300'
                                 else 'arm_common', default_direction),
                      signal.get('reverse_long', default_reverse), signal.get('reverse_short', default_reverse),
                      reverse_sources in ('trend', 'both'), reverse_sources in ('range', 'both'),
                      float(signal.get('range_width', 0)), float(config.get('break_widths', 3)),
                      profit_mode == 'trail', float(config.get('profit_activate_widths', 1)),
                      float(config.get('profit_trail_widths', .5)), entry_kind == 'recovery_market',
                      {'none': 0, 'self': 1, 'both': 2}[confirmation],
                      float(config.get('recovery_fraction', .25)),
                      config.get('watch_clear_common', 'any') == 'adverse',
                      stop_kind in ('witness_extreme', 'width_or_witness'),
                      {'legacy': 0, 'keep': 1, 'return_self': 2, 'return_both': 3}[reentry_kind],
                      float(config.get('center_fraction', .25)), config.get('center_after', 'profit') == 'all',
                      bool(config.get('center_release', False)),
                      signal.get('peer_mid', np.full(size, np.nan)),
                      signal.get('peer_source', np.full(size, -1, dtype=np.int64)),
                      signal.get('peer_valid', np.zeros(size, dtype=bool)),
                      float(signal.get('peer_width', 0)), float(signal.get('peer_tick', 0)),
                      max_risk, min_ratio, stop_kind == 'width_or_witness',
                      {'widths': 0, 'center': 1, 'center_plus': 2}[target_kind], target_offset,
                      {'legacy': 0, 'return_self': 1, 'return_both': 2, 'prepare_reset': 3}[failure_kind],
                      float(config.get('failure_center_fraction', .25)),
                      signal.get('own_source', np.full(size, -1, dtype=np.int64)),
                      signal.get('own_source_time', np.full(size, np.nan)),
                      signal.get('peer_source_time', np.full(size, np.nan)),
                      signal.get('raw_range_valid', np.zeros(size, dtype=bool)),
                      signal.get('raw_range_eligible', np.zeros(size, dtype=bool)),
                      signal.get('raw_oldest_time', np.full(size, np.nan)),
                      {'I0': 0, 'I1': 1, 'I2': 2, 'I3': 3}[price_lane],
                      {'legacy': 0, 'observable': 1, 'confirmed_range': 2}[context],
                      signal.get('price_observable', np.zeros(size, dtype=bool)),
                      signal.get('price_own_index', np.full(size, -1, dtype=np.int64)),
                      signal.get('price_peer_index', np.full(size, -1, dtype=np.int64)),
                      signal.get('price_own_raw_seq', np.full(size, -1, dtype=np.int64)),
                      signal.get('price_peer_raw_seq', np.full(size, -1, dtype=np.int64)),
                      signal.get('price_own_time', np.full(size, np.nan)),
                      signal.get('price_peer_time', np.full(size, np.nan)),
                      signal.get('price_own_valid', np.zeros(size, dtype=bool)),
                      signal.get('price_peer_valid', np.zeros(size, dtype=bool)),
                      signal.get('price_mode', signal['mode']))
    names = ('orders', 'trades', 'curve', 'source_curve', 'target_trace', 'events', 'stats', 'slots',
             'range_state_trace', 'risk_state_trace', 'range_parent_diagnostics', 'price_source_trace')
    answer = dict(zip(names, output))
    answer.update(order_columns=ORDER_COLUMNS, trade_columns=TRADE_COLUMNS, trace_columns=TRACE_COLUMNS,
                  event_columns=EVENT_COLUMNS, stat_columns=STAT_COLUMNS, slot_columns=SLOT_COLUMNS,
                  reasons=REASONS, event_codes=EVENT_CODES, range_state_columns=RANGE_STATE_COLUMNS,
                  risk_state_columns=RISK_STATE_COLUMNS, range_parent_columns=RANGE_PARENT_COLUMNS,
                  price_source_columns=PRICE_SOURCE_COLUMNS)
    if finish:
        assert len(record['time_s']) and record['time_s'][-1] >= record['limit'], '完結入力には既知の場末までの原板が必要です'
        assert np.all(answer['slots'][:, 0] == 0), '場末の未返済又は未約定予約が残りました'
        assert abs(answer['curve'][-1] - answer['stats'][15]) < 1e-4
    return answer
