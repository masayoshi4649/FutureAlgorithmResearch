"""凍結監査の旧取消許可前提に、中心解除からの取消という正式新契約を補足する。"""

import numpy as np


def first(rows, after, before=None):
    """
    機能: 昇順の行番号から、指定行より後かつ終端より前の最初行を取得する。
    引数: rows(int配列)、after(int)、before(int|None)。
    返り値: int | None。
    """
    position = np.searchsorted(rows, after, side='right')
    if position == len(rows):
        return None
    row = int(rows[position])
    return row if before is None or row < before else None


def modes(record, signal):
    """
    機能: 格子対応列を前方伝播し、10秒以内の公開済み現在状態を全原板行へ独立接続する。
    引数: record/signal(dict)。
    返り値: int8配列。
    """
    mapped = signal['mapped']
    latest = np.maximum.accumulate(mapped)
    output = np.zeros(len(mapped), np.int8)
    valid = latest >= 0
    valid &= record['time_s'] - signal['grid'][np.maximum(latest, 0)] <= 10. + 1e-8
    output[valid] = signal['mode'][latest[valid]]
    return output


def verify(record, signal, config, result):
    """
    機能: 予約から最初指値成立又は取消効力までの経路と瞬間占有枠を独立検査する。
    引数: record/signal/config/result(dict)。
    返り値: dictの照合件数。正式取引実装は呼ばない。
    """
    orders, events = result['orders'], result['events']
    n = len(record['time_s'])
    assert (np.diff(events[:, 0]) >= 0).all(), 'イベント公開行の遡及があります'
    current_mode = modes(record, signal)
    assert np.array_equal(events[:, 8], current_mode[events[:, 0].astype(int)])
    qok = record['quote_valid'] & np.isfinite(record['bid']) & np.isfinite(record['ask'])
    qok &= (record['bid'] > 0) & (record['ask'] > record['bid'])
    quotes = np.flatnonzero(qok)
    reserve_events = events[events[:, 3] == 1]
    cancel_events = events[events[:, 3] == 3]
    effect_events = events[events[:, 3] == 6]
    forced_time = record['limit'] - 60.
    scale, cap = (1, 10) if record['symbol'] == 'TOPIX' else (2, 20)
    budgets = [config['trend_budget'] * scale, config['range_budget'] * scale]
    checks = dict(新規予約=len(reserve_events), 返済予約=0, 取消判断=len(cancel_events), 最初約定又は取消=0,
                  イベント瞬間上限=0, 全原板占有枠=0, 指値基準=0)
    anchors = events[np.isin(events[:, 3], (10, 11, 12))]
    latest, fresh, current_fresh, direction = current(record, signal, config)
    independent_center = None
    if config.get('center_release'):
        import entry_checks
        independent_center, _ = entry_checks.restore(record, signal, config, result)
    for reserve in reserve_events:
        row, parent, source, code, side, quantity, decision, limit_price, mode, decision_time, cycle, detail = reserve
        row, parent, source, side, quantity, decision, cycle = map(int, (row, parent, source, side, quantity, decision, cycle))
        assert row == decision and decision_time == record['time_s'][row] and quantity == budgets[source]
        if source == 0:
            assert signal['event'][row] == side and signal['quality'][row] and not signal['reset'][row] and qok[row]
            assert record['start'] + 300. <= record['time_s'][row] < record['limit'] - 300.
            assert config.get('ungated_trend') or config['selection'] == 'fixed' or mode == side
        else:
            assert qok[row]
            if config.get('range_entry_kind', 'limit') == 'limit':
                assert record['price_valid'][row]
            assert record['time_s'][row] < record['limit'] - 120.
            if config.get('persistent_arm'):
                assert current_fresh[row]
                if config.get('range_entry_kind', 'limit') == 'limit' and config.get('range_reentry_kind', 'legacy') == 'legacy':
                    previous = events[(events[:, 2] == 1) & np.isin(events[:, 3], (12, 13)) & (events[:, 0] <= row)]
                    assert len(previous) and previous[-1, 3] == 12, ('往復準備なしの新規', row)
            elif config.get('range_reentry_kind', 'legacy') == 'legacy':
                assert config['selection'] == 'fixed' or mode == 2
            if config.get('range_entry_kind', 'limit') == 'limit' and config.get('range_reentry_kind', 'legacy') == 'legacy':
                matching = anchors[(anchors[:, 10] == cycle) & (anchors[:, 0] <= row)]
                assert len(matching) >= 1
                anchor = matching[-1, 7]
                width = signal.get('range_width', record['tick'] * config['width_ticks'])
                assert limit_price == anchor - side * width
                assert side * (record['price'][row] - limit_price) <= 0
                checks['指値基準'] += 1
        fills = orders[(orders[:, 2] == parent) & (orders[:, 7] == 1)]
        cancelled = effect_events[effect_events[:, 1] == parent]
        cancels = cancel_events[cancel_events[:, 1] == parent]
        assert len(fills) <= 1 and len(cancelled) <= 1 and len(cancels) <= 1
        cutoff = int(np.searchsorted(record['time_s'], record['limit'] - (300. if source == 0 else 120.), side='left'))
        market_entry = source == 0 or config.get('range_entry_kind', 'limit') == 'recovery_market'
        candidate_rows = quotes if market_entry else np.flatnonzero(qok & ((record['ask'] <= limit_price) if side == 1 else (record['bid'] >= limit_price)))
        expected_fill = first(candidate_rows, row, cutoff)
        cancel_effect = cutoff if cutoff < n else None
        if len(cancels):
            cancel_row = int(cancels[0, 0])
            assert source == 1 and (config['cancel_pending'] or config.get('persistent_arm')
                                    or config.get('center_release')) and cancel_row >= row
            assert cancels[0, 6] == cancel_row and cancels[0, 9] == record['time_s'][cancel_row]
            if not config.get('persistent_arm') and config.get('center_release'):
                releases = events[(events[:, 3] == 26) & (events[:, 0] == cancel_row)]
                if not config['cancel_pending']:
                    assert len(releases) == 1 and releases[0, 11] in (1, 2), ('中心解除なしの取消', cancel_row)
                    assert cancel_row > 0 and independent_center[cancel_row-1,15] == 1
                    anchor = independent_center[cancel_row-1,1]
                    width = signal.get('range_width', record['tick']*config['width_ticks'])
                    broken = (record['price_valid'][cancel_row] and
                              abs(record['price'][cancel_row]-anchor) >= config.get('break_widths',3.)*width-record['tick']*1e-8)
                    assert direction[cancel_row] != 0 or broken, ('当時入力に中心解除の証拠なし',cancel_row)
                    assert independent_center[cancel_row,15] == 0
                    assert releases[0,11] == (1 if direction[cancel_row] else 2)
                else:
                    assert current_mode[cancel_row] != 2 or len(releases) == 1
            elif not config.get('persistent_arm'):
                assert current_mode[cancel_row] != 2
            else:
                releases = events[(events[:, 3] == 13) & (events[:, 0] == cancel_row)]
                assert len(releases) == 1 and releases[0, 11] in (1, 2)
            normal_effect = first(quotes, cancel_row)
            if normal_effect is not None:
                cancel_effect = min(cancel_effect, normal_effect) if cancel_effect is not None else normal_effect
        # ----------------------------------------
        # 同じ有効観測で指値成立と通常取消が競合したら約定を維持する。
        if expected_fill is not None and (cancel_effect is None or expected_fill <= cancel_effect) and expected_fill < cutoff:
            assert len(fills) == 1 and fills[0, 0] == expected_fill, (parent, source, expected_fill, fills)
            assert not len(cancelled)
        elif cancel_effect is not None and cancel_effect < n:
            assert len(cancelled) == 1 and cancelled[0, 0] == cancel_effect, (parent, source, cancel_effect, cancelled)
            assert not len(fills)
        else:
            assert not len(fills) and not len(cancelled)
        if source == 1 and config['cancel_pending'] and not config.get('persistent_arm'):
            end = int(fills[0, 0]) if len(fills) else cancel_effect if cancel_effect is not None else n
            bad = np.flatnonzero(current_mode[row + 1:end] != 2)
            if len(bad):
                expected_cancel = row + 1 + int(bad[0])
                assert len(cancels) == 1 and cancels[0, 0] == expected_cancel, (parent, expected_cancel, cancels)
            else:
                assert not len(cancels)
        checks['最初約定又は取消'] += 1
    exits = events[events[:, 3] == 2]
    for reserve in exits:
        row, parent, source = map(int, reserve[:3])
        decision = int(reserve[6])
        decision_time, reason = reserve[9], int(reserve[11])
        if reason == 8:
            assert config.get('reverse_sources', 'none') in ('both', 'trend' if source == 0 else 'range')
            side = int(reserve[4])
            assert fresh[row] and signal['reverse_long' if side == 1 else 'reverse_short'][latest[row]], ('反対確認前の返済', row)
        closed = orders[(orders[:, 2] == parent) & (orders[:, 7] == 0)]
        if reason == 4 and decision_time == forced_time:
            assert row >= decision + 1 and record['time_s'][row] >= forced_time
            candidates = quotes[record['time_s'][quotes] >= forced_time]
            expected = first(candidates, decision)
        else:
            assert row == decision and decision_time == record['time_s'][row]
            expected = first(quotes, decision)
        if expected is None:
            assert not len(closed)
        else:
            assert len(closed) == 1 and closed[0, 0] == expected and closed[0, 1] == decision
        checks['返済予約'] += 1

    # ----------------------------------------
    # 状態イベントごとに枠を復元し、行末だけで消える一時的過剰保有も排除する。
    slots = [dict(status=0, side=0, quantity=0, parent=0), dict(status=0, side=0, quantity=0, parent=0)]
    changes = {}
    for event in events:
        row, parent, source, code, side, quantity = map(int, event[:6])
        slot = slots[source]
        if code == 1:
            assert slot['status'] == 0
            if config['selection'] == 'regime':
                assert slots[1 - source]['status'] == 0
            slot.update(status=1, side=side, quantity=quantity, parent=parent)
        elif code == 2:
            assert slot['status'] == 2 and slot['parent'] == parent
            slot['status'] = 3
        elif code == 3:
            assert slot['status'] == 1 and slot['parent'] == parent
        elif code == 4:
            assert slot['status'] == 1 and slot['parent'] == parent
            slot['status'] = 2
        elif code == 5:
            assert slot['status'] == 3 and slot['parent'] == parent
            slot['status'] = 0
        elif code == 6:
            assert slot['status'] == 1 and slot['parent'] == parent
            slot['status'] = 0
        elif code == 7:
            assert slot['status'] == 1 and slot['parent'] == parent
        trace = np.zeros(6)
        for state in slots:
            if not state['status']:
                continue
            trace[2 if state['side'] == 1 else 3] += state['quantity']
            if state['status'] == 1:
                trace[4] += state['quantity']
            else:
                trace[0 if state['side'] == 1 else 1] += state['quantity']
                if state['status'] == 3:
                    trace[5] += state['quantity']
        assert trace[2] <= cap and trace[3] <= cap
        changes[row] = trace.copy()
        checks['イベント瞬間上限'] += 1
    expected_trace = np.zeros((n, 6))
    previous, value = 0, np.zeros(6)
    for row in sorted(changes):
        expected_trace[previous:row] = value
        previous, value = row, changes[row]
    expected_trace[previous:] = value
    np.testing.assert_array_equal(expected_trace, result['target_trace'])
    checks['全原板占有枠'] = n
    return checks


def current(record, signal, config):
    """
    機能: 現在鮮度と共同方向を公開済み格子だけから独立復元する。
    引数: record/signal/config (dict)。
    返り値: tuple[ndarray] の最新格子、格子鮮度、両市場有効性、共同方向。
    """
    latest = np.maximum.accumulate(signal['mapped'])
    size = len(latest)
    safe = np.maximum(latest, 0)
    fresh = (latest >= 0) & (record['time_s'] - signal['grid'][safe] <= 10. + 1e-8)
    valid = signal.get('current_valid', np.ones(len(signal['grid']), bool))
    current_fresh = fresh & valid[safe]
    key = 'arm_trend300' if config.get('arm_direction_kind', 'common') == 'trend300' else 'arm_common'
    raw = signal.get(key, np.zeros(len(signal['grid']), np.int8))
    direction = np.zeros(size, np.int8)
    direction[current_fresh] = raw[safe[current_fresh]]
    return latest, fresh, current_fresh, direction


def arm_state(record, signal, config, result):
    """
    機能: 往復準備と解除の全行資格・最初破綻・不明保持を独立に検査する。
    引数: record/signal/config/result (dict)。
    返り値: dict の準備・解除・全原板資格件数。
    指値源の新規予約だけは準備後の処理として外し、約定・取消は先行して反映する。
    """
    if config.get('range_entry_kind', 'limit') != 'limit' or config.get('range_reentry_kind', 'legacy') != 'legacy':
        import entry_checks
        return entry_checks.verify(record, signal, config, result)
    if config['range_budget']==0 and 'risk_state_trace' in result:
        import entry_checks
        import common
        independent = entry_checks.restore_all(record,signal,config,result)
        common.same(result['risk_state_trace'],independent[2])
        assert len(result.get('range_parent_diagnostics',[]))==0
    if not config.get('persistent_arm'):
        assert not np.isin(result['events'][:, 3], (12, 13)).any()
        return dict(往復準備=0, 往復解除=0, 全原板準備資格=0)
    events = result['events']
    n = len(record['time_s'])
    phase_status = np.zeros((n, 2), np.int8)
    changes = {}
    status = np.zeros(2, np.int8)
    grouped = {}
    for event in events:
        grouped.setdefault(int(event[0]), []).append(event)
    previous = 0
    for row in sorted(grouped):
        phase_status[previous:row] = status
        for event in grouped[row]:
            source, code = int(event[2]), int(event[3])
            if code == 1 and source == 0:
                status[source] = 1
            elif code == 2:
                status[source] = 3
            elif code == 4:
                status[source] = 2
            elif code in (5, 6):
                status[source] = 0
        phase_status[row] = status
        for event in grouped[row]:
            if event[3] == 1 and event[2] == 1:
                status[1] = 1
        previous = row + 1
    phase_status[previous:] = status
    mode = modes(record, signal)
    _, _, current_fresh, direction = current(record, signal, config)
    qok = record['quote_valid'] & np.isfinite(record['bid']) & np.isfinite(record['ask'])
    qok &= (record['bid'] > 0) & (record['ask'] > record['bid'])
    eligible = (config['range_budget'] > 0) & (mode == 2) & current_fresh & qok & record['price_valid']
    eligible &= (phase_status[:, 1] == 0) & (record['time_s'] < record['limit'] - 120.)
    if config['selection'] == 'regime':
        eligible &= phase_status[:, 0] == 0
    width = signal.get('range_width', config['width_ticks'] * record['tick'])
    breaks = float(config.get('break_widths', 3)) * width
    eligible_rows = np.flatnonzero(eligible)
    transitions = events[((events[:, 2] == 1) & np.isin(events[:, 3], (12, 13)))
                        | ((events[:, 2] == 1) & (events[:, 3] == 6) & (events[:, 11] == 0))]
    armed = False
    anchor = np.nan
    reset_row = -1
    arm_row = -1
    prepares = releases = 0
    for event in transitions:
        row, code, detail = int(event[0]), int(event[3]), int(event[11])
        if code == 12:
            assert not armed
            expected = first(eligible_rows, reset_row)
            assert expected == row, ('往復準備の最初資格違い', expected, row)
            assert event[7] == record['price'][row] and event[11] == width
            armed, anchor, arm_row = True, event[7], row
            prepares += 1
        else:
            if armed:
                breached = (direction[arm_row + 1:row + 1] != 0)
                breached |= record['price_valid'][arm_row + 1:row + 1] & (
                    np.abs(record['price'][arm_row + 1:row + 1] - anchor) >= breaks - record['tick'] * 1e-8)
                hit = np.flatnonzero(breached)
                if code == 13 and detail in (1, 2):
                    assert len(hit) and arm_row + 1 + hit[0] == row, ('往復破綻の見逃し', arm_row, row, hit[:1])
                    assert event[7] == anchor
                    assert detail == (1 if direction[row] else 2)
                elif len(hit):
                    assert arm_row + 1 + hit[0] >= row, ('返済までの破綻見逃し', row)
            elif code == 13:
                assert detail == 3, ('未準備で共同解除', row, detail)
            armed = False
            reset_row = row
            releases += int(code == 13)
    if armed:
        breached = direction[arm_row + 1:] != 0
        breached |= record['price_valid'][arm_row + 1:] & (np.abs(record['price'][arm_row + 1:] - anchor) >= breaks - record['tick'] * 1e-8)
        assert not breached.any(), '終端までに往復破綻の未処理があります'
    else:
        assert first(eligible_rows, reset_row) is None, ('往復再準備の欠落', reset_row)
    return dict(往復準備=prepares, 往復解除=releases, 全原板準備資格=n)


def activation(record, signal, config, result):
    """
    機能: 活動開始基準がidle・新規可能のfalse→trueだけで更新されたか全原板行を検査する。
    引数: record/signal/config/result(dict)。
    返り値: dictの状態更新検査件数。
    """
    events = result['events']
    n = len(record['time_s'])
    current_mode = modes(record, signal)
    status_before = np.zeros((n, 2), np.int8)
    status = np.zeros(2, np.int8)
    cancelling = -1
    reset_after = -1
    prior_eligible = False
    updates = []
    grouped = {}
    for event in events:
        grouped.setdefault(int(event[0]), []).append(event)
    closing = False
    for row in range(n):
        if record['time_s'][row] >= record['limit'] - 60.:
            closing = True
        values = grouped.get(row, [])
        # ----------------------------------------
        # 自源の新規判断より前にあった約定・取消と、追従源の予約だけを反映する。
        for event in values:
            source, code = int(event[2]), int(event[3])
            if code == 1 and source == 0:
                status[source] = 1
            elif code == 2:
                status[source] = 3
            elif code == 4:
                status[source] = 2
            elif code == 5:
                status[source] = 0
            elif code == 6:
                status[source] = 0
                if source == 1 and event[11] == 0:
                    reset_after = row
        qok = record['quote_valid'][row] and np.isfinite(record['bid'][row]) and np.isfinite(record['ask'][row])
        qok = qok and 0 < record['bid'][row] < record['ask'][row]
        eligible = (config['selection'] != 'fixed' and current_mode[row] == 2 and status[1] == 0
                    and (config['selection'] != 'regime' or status[0] == 0) and not closing
                    and record['time_s'][row] < record['limit'] - 120. and record['price_valid'][row]
                    and qok and row > reset_after)
        actual = [event for event in values if event[3] == 11]
        expected = bool(config.get('activate_anchor') and config['range_budget'] > 0 and eligible and not prior_eligible)
        assert bool(actual) == expected, ('活動開始基準の時点違い', row, eligible, prior_eligible, actual)
        if expected:
            assert len(actual) == 1 and actual[0][7] == record['price'][row]
            assert actual[0][6] == row and actual[0][9] == record['time_s'][row]
            updates.append(row)
        prior_eligible = bool(eligible)
        for event in values:
            if event[3] == 1 and event[2] == 1:
                status[1] = 1
        status_before[row] = status
    return dict(活動開始基準更新=len(updates), 全原板資格状態=n)
