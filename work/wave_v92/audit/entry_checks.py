"""入口状態を、準備イベントを正答にせず当時価格と注文の実確定だけから復元する。"""

import math

import numpy as np
from numba import njit

import common


def lifecycle(record, result):
    """
    機能: 約定・取消効力・返済判断だけから、新規判断の直前の源占有を復元する。
    引数: record/result (dict)。
    返り値: tuple[ndarray]の2源占有、実全返済純額、通常取消効力。
    準備・極値・回復・中心帰還のイベントを状態生成の根拠にしない。
    """
    n = len(record['time_s'])
    statuses = np.zeros((n, 2), np.int8)
    closed_net = np.full(n, np.nan)
    cancelled = np.zeros(n, bool)
    groups = {}
    for event in result['events']:
        if int(event[3]) <= 7:
            groups.setdefault(int(event[0]), []).append(event)
    status = np.zeros(2, np.int8)
    previous = 0
    for row in sorted(groups):
        statuses[previous:row] = status
        deferred = False
        for event in groups[row]:
            source, code = int(event[2]), int(event[3])
            if code == 1:
                if source == 1:
                    deferred = True
                else:
                    status[source] = 1
            elif code == 2:
                status[source] = 3
            elif code == 4:
                status[source] = 2
            elif code in (5, 6):
                status[source] = 0
                if source == 1 and code == 6 and event[11] == 0:
                    cancelled[row] = True
        statuses[row] = status
        if deferred:
            status[1] = 1
        previous = row + 1
    statuses[previous:] = status
    unit = 1000. if record['symbol'] == 'TOPIX' else 10.
    entries = {}
    for order in result['orders']:
        if order[3] != 1:
            continue
        parent = int(order[2])
        if order[7] == 1:
            entries[parent] = order
        else:
            first = entries.pop(parent)
            closed_net[int(order[0])] = first[4]*(order[6]-first[6])*first[5]*unit-first[9]-order[9]
    return statuses, closed_net, cancelled


@njit(cache=True, nogil=True)
def restore_loop(price, mid, qok, price_valid, current, mode, direction, peer, peer_source, published_peer_source,
                 peer_ok, statuses, closed_net, cancelled, times, width, peer_width, tick,
                 peer_tick, limit, persistent, recovery, confirm, fraction, adverse,
                 witness, reentry, center_fraction, all_closes, release, selection,
                 range_budget, activate_anchor, break_widths):
    """
    機能: 公開済み入力と実注文の確定情報だけから全行の入口仮説を別状態機械で計算する。
    引数: 各価格・源・資格・確定注文の配列(ndarray)、幅等(float)、事前設定(bool/int)。
    返り値: tuple[ndarray]の全行25列状態と、予測した新規判断4列。
    正式エンジンの関数・準備イベント・極値イベント・帰還イベントは呼ばず読まない。
    """
    n = len(times)
    states = np.empty((n, 25), np.float64)
    expected = np.empty((n, 4), np.float64)
    cursor = 0
    center = other_center = np.nan
    own_low = own_high = other_low = other_high = np.nan
    own_lo_at = own_hi_at = other_lo_at = other_hi_at = -1
    prepared = prepared_other = -1
    actual_exit = exit_other = returned_at = -1
    armed = held = seen_self = seen_other = False
    ready = True
    need_prepare = False
    side = 0
    failed_line = np.nan
    episode = cycle = 0
    reset_after = -1
    anchor_row = -1
    previous_eligible = False
    for row in range(n):
        stamp = times[row]
        close = not np.isnan(closed_net[row])
        if close:
            if reentry and np.isfinite(center) and not need_prepare and (all_closes or closed_net[row] > 0):
                held = True
                ready = reentry == 1
                seen_self = seen_other = False
                actual_exit, exit_other = row, published_peer_source[row]
                returned_at = row if ready else -1
                side = 0
                failed_line = np.nan
                armed = persistent
                if ready:
                    cycle += 1
                    own_low = own_high = mid[row]
                    own_lo_at = own_hi_at = row
                    other_low = other_high = peer[row]
                    other_lo_at = other_hi_at = peer_source[row]
                    prepared, prepared_other = row, peer_source[row]
            elif persistent:
                armed = False
                center = other_center = np.nan
                reset_after = row
                held = False
                side = 0
                failed_line = np.nan
                ready = True
            elif need_prepare:
                center = np.nan
                reset_after = row
                held = False
                ready = True
            elif price_valid[row]:
                center = price[row]
                other_center = peer[row]
                cycle += 1
                anchor_row = row
                held = False
                episode += 1
                prepared, prepared_other = row, peer_source[row]
                side = 0
                failed_line = np.nan
                ready = True
        if cancelled[row]:
            reset_after = row
            center = other_center = np.nan
            armed = held = False
            side = 0
            failed_line = np.nan
            ready = True

        # ----------------------------------------
        # 既存持続ガードと、非持続中心保持にだけ加える解除を別に扱う。
        breached = price_valid[row] and np.isfinite(center) and abs(price[row]-center) >= break_widths*width-tick*1e-8
        if persistent and armed:
            against = direction[row] != 0
            if recovery and adverse and side:
                against = direction[row] == -side
            if against or breached:
                armed = False
                reset_after = row
                if statuses[row, 1] == 0:
                    center = np.nan
                held = False
                ready = True
                need_prepare = True
                other_center = np.nan
                side = 0
                seen_self = seen_other = False
        elif held and release and (direction[row] != 0 or breached):
            held = False
            ready = True
            need_prepare = True
            reset_after = row
            side = 0
            other_center = np.nan
            seen_self = seen_other = False
            if statuses[row, 1] == 0:
                center = np.nan

        # ----------------------------------------
        # 帯内の両証拠は同じ観測行の値。昔の帰還をラッチして足し合わせない。
        if held and not ready:
            available = statuses[row, 1] == 0 and row > actual_exit and price_valid[row] and qok[row]
            if available:
                seen_self = price_valid[row] and abs(price[row]-center) <= center_fraction*width+tick*1e-8
                seen_other = (peer_ok[row] and np.isfinite(other_center) and peer_source[row] > max(exit_other, prepared_other)
                              and abs(peer[row]-other_center) <= center_fraction*peer_width+peer_tick*1e-8)
                if seen_self and (reentry != 3 or seen_other):
                    ready = True
                    returned_at = row
                    prepared, prepared_other = row, peer_source[row]
                    own_low = own_high = mid[row]
                    own_lo_at = own_hi_at = row
                    other_low = other_high = peer[row]
                    other_lo_at = other_hi_at = peer_source[row]
                    side = 0
                    cycle += 1
            else:
                seen_self = seen_other = False

        # ----------------------------------------
        # 新規準備と監視は相手格子の実公開を越えて参照しない。
        eligible = (range_budget > 0 and selection != 0 and mode[row] == 2 and statuses[row, 1] == 0
                    and (selection != 1 or statuses[row, 0] == 0) and stamp < limit-120.
                    and price_valid[row] and qok[row] and row > reset_after)
        if range_budget and (price_valid[row] or (recovery and qok[row])) and row > reset_after:
            if persistent:
                if (not armed and statuses[row, 1] == 0 and mode[row] == 2 and current[row]
                        and price_valid[row] and qok[row] and (not recovery or peer_ok[row])
                        and stamp < limit-120. and (selection != 1 or statuses[row, 0] == 0)):
                    armed = True
                    center = price[row]
                    other_center = peer[row]
                    cycle += 1
                    anchor_row = row
                    episode += 1
                    prepared, prepared_other = row, peer_source[row]
                    own_low = own_high = mid[row]
                    own_lo_at = own_hi_at = row
                    other_low = other_high = peer[row]
                    other_lo_at = other_hi_at = peer_source[row]
                    side = 0
                    failed_line = np.nan
                    need_prepare = False
            else:
                can = (not need_prepare or (mode[row] == 2 and current[row] and qok[row]
                       and peer_ok[row] and statuses[row, 1] == 0 and stamp < limit-120.))
                if not np.isfinite(center) and can:
                    center, other_center = price[row], peer[row]
                    cycle += 1
                    anchor_row = row
                    episode += 1
                    prepared, prepared_other = row, peer_source[row]
                    need_prepare = False
                if activate_anchor and eligible and not previous_eligible:
                    center = price[row]
                    if anchor_row != row:
                        cycle += 1
                    anchor_row = row
            if not need_prepare and np.isfinite(center) and not np.isfinite(other_center) and peer_ok[row]:
                other_center = peer[row]
                prepared_other = peer_source[row]

            if recovery and armed and ready and statuses[row, 1] == 0:
                if qok[row]:
                    if not np.isfinite(own_low) or mid[row] < own_low:
                        own_low, own_lo_at = mid[row], row
                    if not np.isfinite(own_high) or mid[row] > own_high:
                        own_high, own_hi_at = mid[row], row
                if peer_ok[row]:
                    if not np.isfinite(other_low) or peer[row] < other_low:
                        other_low, other_lo_at = peer[row], peer_source[row]
                    if not np.isfinite(other_high) or peer[row] > other_high:
                        other_high, other_hi_at = peer[row], peer_source[row]
            if statuses[row, 1] == 0 and stamp < limit-120. and qok[row]:
                candidate = 1 if price[row] <= center-width else -1 if price[row] >= center+width else 0
                allowed = (armed and current[row]) if persistent else (selection == 0 or mode[row] == 2)
                allowed = allowed and not need_prepare
                free = selection != 1 or statuses[row, 0] == 0
                if held:
                    allowed = allowed and ready
                    if reentry != 1:
                        allowed = allowed and row > returned_at
                    elif recovery:
                        allowed = allowed and row > prepared
                if recovery:
                    allowed = allowed and peer_ok[row]
                    if candidate and price_valid[row] and not side and allowed and free:
                        side = candidate
                    low = own_low if side == 1 else own_high
                    at = own_lo_at if side == 1 else own_hi_at
                    other = other_low if side == 1 else other_high
                    other_at = other_lo_at if side == 1 else other_hi_at
                    self_ok = (side != 0 and row > at and np.isfinite(low)
                               and side*(mid[row]-low) >= fraction*width-tick*1e-8)
                    other_ok = (side != 0 and peer_source[row] > other_at and np.isfinite(other)
                                and peer_ok[row] and side*(peer[row]-other) >= fraction*peer_width-peer_tick*1e-8)
                    confirmed = confirm == 0 or (self_ok and (confirm == 1 or other_ok))
                    if side and allowed and free and confirmed:
                        failed_line = low-side*tick if witness else np.nan
                        expected[cursor] = np.array([row, side, 0., cycle])
                        cursor += 1
                elif candidate and allowed and free:
                    expected[cursor] = np.array([row, candidate, center-candidate*width, cycle])
                    cursor += 1
        previous_eligible = eligible
        # 状態番号は公開仕様と同じ語義であり、判定値は上で独立生成したもの。
        phase = 0
        if np.isfinite(center):
            phase = 1
        if held and not ready:
            phase = 5
        if held and ready:
            phase = 6
        if side:
            phase = 2
        if statuses[row, 1] == 1 or (cursor > 0 and expected[cursor-1, 0] == row):
            phase = 3
        elif statuses[row, 1] >= 2:
            phase = 4
        states[row] = np.array([phase,center,other_center,width,peer_width,episode,side,
                               own_low,own_lo_at,own_high,own_hi_at,other_low,other_lo_at,
                               other_high,other_hi_at,held,seen_self,seen_other,actual_exit,
                               exit_other,returned_at,prepared,prepared_other,failed_line,armed])
    return states, expected[:cursor]


def restore(record, signal, config, result):
    """
    機能: 独立公開時計と確定注文から、回復・再参加の全状態と新規判断を計算する。
    引数: record/signal/config/result (dict)。
    返り値: tuple[ndarray]の独立全行状態、新規判断。
    """
    import protocol
    statuses, closed_net, cancelled = lifecycle(record, result)
    latest, fresh, current, direction = protocol.current(record, signal, config)
    safe = np.maximum(latest, 0)
    peer_ok = fresh & signal['peer_valid'][safe] & np.isfinite(signal['peer_mid'][safe]) & (signal['peer_mid'][safe] > 0)
    peer = np.where(peer_ok, signal['peer_mid'][safe], np.nan)
    peer_source = np.where(peer_ok, signal['peer_source'][safe], -1).astype(np.int32)
    published_source = np.where(latest >= 0, signal['peer_source'][safe], -1).astype(np.int32)
    bids, asks = record['bid'], record['ask']
    qok = record['quote_valid'] & np.isfinite(bids) & np.isfinite(asks) & (bids > 0) & (asks > bids)
    mid = np.where(qok, (bids+asks)/2, np.nan)
    width = signal.get('range_width', config['width_ticks']*record['tick'])
    scale = 1 if record['symbol'] == 'TOPIX' else 2
    return restore_loop(record['price'], mid, qok, record['price_valid'], current,
                        protocol.modes(record, signal), direction, peer, peer_source, published_source, peer_ok,
                        statuses, closed_net, cancelled, record['time_s'], width,signal['peer_width'],
                        record['tick'],signal['peer_tick'],record['limit'],config['persistent_arm'],
                        config['range_entry_kind']=='recovery_market',
                        {'none':0,'self':1,'both':2}[config['recovery_confirmation']],
                        config['recovery_fraction'],config['watch_clear_common']=='adverse',
                        config['range_stop_kind']=='witness_extreme',
                        {'legacy':0,'keep':1,'return_self':2,'return_both':3}[config['range_reentry_kind']],
                        config['center_fraction'],config['center_after']=='all',config['center_release'],
                        {'fixed':0,'regime':1,'gated_fixed':2}[config['selection']],
                        config['range_budget']*scale,config['activate_anchor'],config.get('break_widths',3.))


def verify(record, signal, config, result):
    """
    機能: 正式な極値・中心イベントを正答根拠にせず、全行状態と全新規判断を照合する。
    引数: record/signal/config/result (dict)。
    返り値: dict[str,int]の独立検査件数。
    """
    expected, decisions = restore(record,signal,config,result)
    common.same(result['range_state_trace'], expected)
    actual = result['events'][(result['events'][:,2]==1)&(result['events'][:,3]==1)][:,[0,4,7,10]]
    common.same(actual,decisions)
    events = result['events']
    # ----------------------------------------
    # 解除のラベルだけ挿入・削除しても、当時の独立状態変化と対応しなければ拒絶する。
    columns = np.asarray(expected)
    prior_armed = np.r_[False, columns[:-1,24].astype(bool)]
    prepared = columns[:,21].astype(int)
    close_rows = set(int(order[0]) for order in result['orders'] if order[3]==1 and order[7]==0)
    actual_clears = events[(events[:,2]==1)&(events[:,3]==13)]
    for clear in actual_clears:
        row,detail = int(clear[0]),int(clear[11])
        if detail == 3:
            assert row in close_rows, ('実返済なしの全返済解除', row)
        else:
            assert prior_armed[row] and not columns[row,24], ('当時仮説を失わない解除ラベル',row)
    for row in np.flatnonzero(prior_armed & ~columns[:,24].astype(bool)):
        if row in close_rows:
            continue
        assert ((actual_clears[:,0]==row)&np.isin(actual_clears[:,11],(1,2))).sum()==1
    return dict(全行の独立極値と中心帰還=len(expected),回復又は再参加の全新規判断=len(decisions))
