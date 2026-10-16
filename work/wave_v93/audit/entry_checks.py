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
                 range_budget, activate_anchor, break_widths, bids, asks, fee_unit, multiplier,
                 max_risk, min_ratio, stop_kind, target_kind, target_offset, failure_kind,
                 failure_fraction, latest, fresh, own_sources, own_times, peer_times,
                 raw_valid, raw_range, oldest_time, entry_fill_price, entry_fill_row,
                 exit_decision, exit_reason_values, range_side, mapped):
    """
    機能: 公開済み入力と実注文の確定情報だけから全行の入口仮説を別状態機械で計算する。
    引数: 各価格・源・資格・確定注文の配列(ndarray)、幅等(float)、事前設定(bool/int)。
    返り値: tuple[ndarray]の全行25列状態と、予測した新規判断4列。
    正式エンジンの関数・準備イベント・極値イベント・帰還イベントは呼ばず読まない。
    """
    n = len(times)
    states = np.empty((n, 25), np.float64)
    risk = np.empty((n, 40), np.float64)
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
    consumed = False
    gate_row = -1
    gate_accept = gate_side = 0
    planned_entry = planned_liq = spread = fee_width = np.nan
    planned_risk = center_gain = proxy = ratio = np.nan
    fixed_failure = fixed_target = entry_center = entry_peer_center = np.nan
    entry_width = entry_peer_width = np.nan
    width_flag = witness_flag = target_flag = False
    paused = False
    failure_center = failure_peer_center = failure_width = failure_peer_width = np.nan
    failure_exit_row = failure_exit_own = failure_exit_peer = -1
    failure_exit_time = -1e30
    false_seen = False
    false_grid = false_own = false_peer = release_row = -1
    failure_self = failure_peer = False
    for row in range(n):
        stamp = times[row]
        g = latest[row]
        own_source = own_sources[g] if g >= 0 else -1
        own_time = own_times[g] if g >= 0 else np.nan
        peer_time = peer_times[g] if g >= 0 else np.nan
        observable = fresh[row] and raw_valid[g] if g >= 0 else False
        raw_eligible = observable and raw_range[g] if g >= 0 else False
        oldest = oldest_time[g] if g >= 0 else np.nan
        close = not np.isnan(closed_net[row])
        if close:
            if failure_kind and witness_flag and closed_net[row] < 0:
                paused = True
                failure_center, failure_peer_center = entry_center, entry_peer_center
                failure_width, failure_peer_width = entry_width, entry_peer_width
                failure_exit_row, failure_exit_time = row, stamp
                failure_exit_own, failure_exit_peer = own_source, published_peer_source[row]
                false_seen = False
                false_grid = false_own = false_peer = -1
                release_row = -1
                failure_self = failure_peer = False
                need_prepare = True
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
        # 返済採否の正答は別の最初trigger監査で照合し、証拠自体は当時板から再計算する。
        if exit_decision[row] >= 0:
            position_side = range_side[row]
            entry = entry_fill_price[row]
            width_hit = stop_kind != 1 and price_valid[row] and position_side*(price[row]-entry) <= -width
            quote = bids[row] if position_side == 1 else asks[row]
            witness_hit = stop_kind != 0 and qok[row] and np.isfinite(fixed_failure) and position_side*(quote-fixed_failure) <= tick*1e-8
            target_hit = price_valid[row] and np.isfinite(fixed_target) and position_side*(price[row]-fixed_target) >= -tick*1e-8
            reason = exit_reason_values[row]
            width_flag = width_hit if reason in (6, 13, 14) else False
            witness_flag = witness_hit if reason in (6, 13, 14) else False
            target_flag = reason in (5, 15)

        # ----------------------------------------
        # 実失敗の中心は歴史的な解除基準として隔離し、新たな注文中心へ使い回さない。
        if paused and row > failure_exit_row and statuses[row,1] == 0:
            failure_self = (price_valid[row] and qok[row] and
                            abs(price[row]-failure_center) <= failure_fraction*failure_width+tick*1e-8)
            failure_peer = (peer_ok[row] and peer_source[row] > failure_exit_peer
                            and peer_time > failure_exit_time and
                            abs(peer[row]-failure_peer_center) <= failure_fraction*failure_peer_width+peer_tick*1e-8)
            can_release = False
            if failure_kind == 1:
                can_release = failure_self
            elif failure_kind == 2:
                can_release = failure_self and failure_peer
            else:
                sufficient = (mapped[row] >= 0 and observable and
                              own_source > failure_exit_own and published_peer_source[row] > failure_exit_peer
                              and own_time > failure_exit_time and peer_time > failure_exit_time
                              and oldest > failure_exit_time)
                if sufficient and not raw_eligible and not false_seen:
                    false_seen = True
                    false_grid, false_own, false_peer = g, own_source, published_peer_source[row]
                elif (sufficient and false_seen and raw_eligible and mode[row] == 2
                      and g > false_grid and own_source > false_own and published_peer_source[row] > false_peer):
                    can_release = True
            if can_release:
                paused = False
                release_row = row
                reset_after = row
                center = other_center = np.nan
                armed = held = False
                side = 0
                ready = True
                need_prepare = True
        elif paused:
            failure_self = failure_peer = False

        # ----------------------------------------
        # 既存持続ガードと、非持続中心保持にだけ加える解除を別に扱う。
        breached = price_valid[row] and np.isfinite(center) and abs(price[row]-center) >= break_widths*width-tick*1e-8
        if persistent and armed and not paused:
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
        if range_budget and not paused and (price_valid[row] or (recovery and qok[row])) and row > reset_after:
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
                    consumed = False
                    gate_row = -1
                    gate_accept = gate_side = 0
                    planned_entry = planned_liq = spread = fee_width = np.nan
                    planned_risk = center_gain = proxy = ratio = np.nan
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
                    allowed = allowed and peer_ok[row] and not consumed
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
                        planned_entry = asks[row] if side == 1 else bids[row]
                        planned_liq = bids[row] if side == 1 else asks[row]
                        spread = asks[row]-bids[row]
                        fee_width = 2*math.floor(range_budget*fee_unit+1e-8)/(range_budget*multiplier)
                        candidate_stop = low-side*tick
                        planned_risk = side*(planned_entry-candidate_stop)
                        center_gain = side*(center-planned_entry)-spread-fee_width
                        proxy = min(planned_risk,width+spread)+fee_width
                        ratio = center_gain/proxy if proxy > 0 else np.nan
                        accepted = True
                        if max_risk > 0:
                            accepted = planned_risk > 0 and planned_risk <= max_risk*width+tick*1e-8
                        if min_ratio > 0:
                            accepted = (accepted and planned_risk > 0 and center_gain > 0 and proxy > 0
                                        and side*(planned_liq-candidate_stop) > tick*1e-8
                                        and ratio >= min_ratio-1e-12)
                        if max_risk > 0 or min_ratio > 0:
                            consumed = True
                            gate_row,gate_accept,gate_side = row,int(accepted),side
                        if accepted:
                            fixed_failure = candidate_stop
                            entry_center,entry_peer_center = center,other_center
                            entry_width,entry_peer_width = width,peer_width
                            fixed_target = center+side*target_offset*width if target_kind else np.nan
                            width_flag = witness_flag = target_flag = False
                            failed_line = fixed_failure if witness else np.nan
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
        risk[row] = np.array([consumed,gate_row,gate_accept,gate_side,planned_entry,planned_liq,spread,
                              fee_width,planned_risk,center_gain,proxy,ratio,fixed_failure,fixed_target,
                              entry_center,entry_peer_center,entry_width,entry_peer_width,width_flag,
                              witness_flag,target_flag,paused,failure_center,failure_peer_center,
                              failure_width,failure_peer_width,failure_exit_row,failure_exit_time,
                              failure_exit_own,failure_exit_peer,false_seen,false_grid,false_own,false_peer,
                              release_row,failure_self,failure_peer,observable,raw_eligible,oldest])
    return states, expected[:cursor],risk


def restore_all(record, signal, config, result):
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
    n, size = len(record['time_s']), len(signal['grid'])
    entry_prices = np.full(n,np.nan)
    entry_rows = np.full(n,-1,np.int64)
    range_sides = np.zeros(n,np.int64)
    entries = result['orders'][(result['orders'][:,3]==1)&(result['orders'][:,7]==1)]
    exits = result['orders'][(result['orders'][:,3]==1)&(result['orders'][:,7]==0)]
    for order in entries:
        first = int(order[0])
        closed = exits[exits[:,2]==order[2]]
        end = int(closed[0,0])+1 if len(closed) else n
        entry_prices[first:end] = order[6]
        entry_rows[first:end] = first
        range_sides[first:end] = int(order[4])
    exit_decision = np.full(n,-1,np.int64)
    reasons = np.zeros(n,np.int64)
    for event in result['events'][(result['events'][:,2]==1)&(result['events'][:,3]==2)]:
        row = int(event[0])
        exit_decision[row] = row
        reasons[row] = int(event[11])
    return restore_loop(record['price'], mid, qok, record['price_valid'], current,
                        protocol.modes(record, signal), direction, peer, peer_source, published_source, peer_ok,
                        statuses, closed_net, cancelled, record['time_s'], width,signal['peer_width'],
                        record['tick'],signal['peer_tick'],record['limit'],config['persistent_arm'],
                        config['range_entry_kind']=='recovery_market',
                        {'none':0,'self':1,'both':2}[config['recovery_confirmation']],
                        config['recovery_fraction'],config['watch_clear_common']=='adverse',
                        config['range_stop_kind'] in ('witness_extreme','width_or_witness'),
                        {'legacy':0,'keep':1,'return_self':2,'return_both':3}[config['range_reentry_kind']],
                        config['center_fraction'],config['center_after']=='all',config['center_release'],
                        {'fixed':0,'regime':1,'gated_fixed':2}[config['selection']],
                        config['range_budget']*scale,config['activate_anchor'],config.get('break_widths',3.),
                        bids,asks,41.8 if scale==1 else 11.,1000. if scale==1 else 10.,
                        config.get('range_entry_max_risk_widths',0.),config.get('range_entry_min_center_ratio',0.),
                        {'width':0,'witness_extreme':1,'width_or_witness':2}[config['range_stop_kind']],
                        {'widths':0,'center':1,'center_plus':2}[config.get('range_target_kind','widths')],
                        config.get('range_center_target_offset',0.),
                        {'legacy':0,'return_self':1,'return_both':2,'prepare_reset':3}[config.get('range_failure_reentry_kind','legacy')],
                        config.get('failure_center_fraction',.25),latest,fresh,
                        signal.get('own_source',np.full(size,-1,np.int64)),
                        signal.get('own_source_time',np.full(size,np.nan)),
                        signal.get('peer_source_time',np.full(size,np.nan)),
                        signal.get('raw_range_valid',np.zeros(size,bool)),
                        signal.get('raw_range_eligible',np.zeros(size,bool)),
                        signal.get('raw_oldest_time',np.full(size,np.nan)),
                        entry_prices,entry_rows,exit_decision,reasons,range_sides,signal['mapped'])


def restore(record,signal,config,result):
    """
    機能: 旧監査の呼出契約へ独立入口状態と新規判断だけを返す。
    引数: record/signal/config/result(dict)。
    返り値: tuple[ndarray,ndarray]。新risk状態はrestore_allで独立検査する。
    """
    return restore_all(record,signal,config,result)[:2]


def parent_diagnostics(record,signal,config,result,states,risk):
    """
    機能: 独立復元した入口当時量と確定約定から、親別固定距離・停止証拠・休止を検算する。
    引数: record/signal/config/result(dict)、states/risk(ndarray)。
    返り値: ndarray[親数,33]。正式親診断や状態イベントを正答根拠にしない。
    """
    import protocol
    latest,_,_,_ = protocol.current(record,signal,config)
    rows = []
    for trade in result['trades']:
        if int(trade[1]) != 1:
            continue
        parent,entry,closed,side = map(int,(trade[0],trade[2],trade[3],trade[4]))
        decision = int(trade[15])
        closing = result['orders'][(result['orders'][:,2]==parent)&(result['orders'][:,7]==0)]
        assert len(closing)==1
        exit_decision = int(closing[0,1])
        values = risk[decision]
        extreme_column = 7 if side==1 else 9
        entry_source = int(signal['peer_source'][latest[decision]]) if latest[decision]>=0 else -1
        exit_source = int(signal['peer_source'][latest[closed]]) if latest[closed]>=0 else -1
        flags = risk[closed,18:21]
        pause = (config.get('range_failure_reentry_kind','legacy')!='legacy' and flags[1] and trade[11]<0)
        rows.append([parent,decision,entry,closed,side,trade[5],states[decision,5],
                     values[14],values[15],values[16],values[17],states[decision,extreme_column],
                     states[decision,extreme_column+1],values[12],*values[4:12],values[13],
                     side*(trade[6]-values[12]),exit_decision,*flags,trade[11],
                     entry_source,exit_source,record['time_s'][closed],pause])
    return np.array(rows,float).reshape(-1,33)


def verify(record, signal, config, result):
    """
    機能: 正式な極値・中心イベントを正答根拠にせず、全行状態と全新規判断を照合する。
    引数: record/signal/config/result (dict)。
    返り値: dict[str,int]の独立検査件数。
    """
    expected, decisions, risk = restore_all(record,signal,config,result)
    common.same(result['range_state_trace'], expected)
    common.same(result['risk_state_trace'],risk)
    common.same(result['range_parent_diagnostics'],parent_diagnostics(record,signal,config,result,expected,risk))
    actual = result['events'][(result['events'][:,2]==1)&(result['events'][:,3]==1)][:,[0,4,7,10]]
    common.same(actual,decisions)
    events = result['events']
    # ----------------------------------------
    # 新ラベルの追加・欠落だけで正しい観測履歴に見せることを防ぐ。
    gates = np.unique(risk[risk[:,1]>=0,1]).astype(int)
    actual_gates = events[(events[:,2]==1)&(events[:,3]==27)]
    common.same(actual_gates[:,0],gates)
    for event in actual_gates:
        row = int(event[0])
        common.same(event[[4,7,11]],risk[row,[3,4,2]])
    pauses = np.flatnonzero(risk[:,21].astype(bool)&~np.r_[False,risk[:-1,21].astype(bool)])
    common.same(events[(events[:,2]==1)&(events[:,3]==28)][:,0],pauses)
    releases = np.flatnonzero((risk[:,34]>=0)&(risk[:,34]!=np.r_[-1,risk[:-1,34]]))
    common.same(events[(events[:,2]==1)&(events[:,3]==30)][:,0],releases)
    falses = np.flatnonzero((risk[:,31]>=0)&(risk[:,31]!=np.r_[-1,risk[:-1,31]]))
    common.same(events[(events[:,2]==1)&(events[:,3]==29)][:,0],falses)
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
    return dict(全行の独立極値と中心帰還=len(expected),回復又は再参加の全新規判断=len(decisions),
                全行予定距離と損切り後休止=len(risk),入口予定余地判定=len(gates),実構造失敗休止=len(pauses),
                損切り後新観測解除=len(releases),独立親固定診断=len(result['range_parent_diagnostics']))
