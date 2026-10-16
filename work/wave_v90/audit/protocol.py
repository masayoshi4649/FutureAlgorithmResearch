"""原板の最初有効観測と予約台帳から、約定・取消の順を独立に復元する。"""

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
    anchors = events[events[:, 3] == 10]
    for reserve in reserve_events:
        row, parent, source, code, side, quantity, decision, limit_price, mode, decision_time, cycle, detail = reserve
        row, parent, source, side, quantity, decision, cycle = map(int, (row, parent, source, side, quantity, decision, cycle))
        assert row == decision and decision_time == record['time_s'][row] and quantity == budgets[source]
        if source == 0:
            assert signal['event'][row] == side and signal['quality'][row] and not signal['reset'][row] and qok[row]
            assert record['start'] + 300. <= record['time_s'][row] < record['limit'] - 300.
            assert config['selection'] == 'fixed' or mode == side
        else:
            assert qok[row] and record['price_valid'][row]
            assert record['time_s'][row] < record['limit'] - 120.
            assert config['selection'] == 'fixed' or mode == 2
            matching = anchors[(anchors[:, 10] == cycle) & (anchors[:, 0] <= row)]
            assert len(matching) == 1
            anchor = matching[0, 7]
            width = record['tick'] * config['width_ticks']
            assert limit_price == anchor - side * width
            assert side * (record['price'][row] - limit_price) <= 0
            checks['指値基準'] += 1
        fills = orders[(orders[:, 2] == parent) & (orders[:, 7] == 1)]
        cancelled = effect_events[effect_events[:, 1] == parent]
        cancels = cancel_events[cancel_events[:, 1] == parent]
        assert len(fills) <= 1 and len(cancelled) <= 1 and len(cancels) <= 1
        cutoff = int(np.searchsorted(record['time_s'], record['limit'] - (300. if source == 0 else 120.), side='left'))
        candidate_rows = quotes if source == 0 else np.flatnonzero(qok & ((record['ask'] <= limit_price) if side == 1 else (record['bid'] >= limit_price)))
        expected_fill = first(candidate_rows, row, cutoff)
        cancel_effect = cutoff if cutoff < n else None
        if len(cancels):
            cancel_row = int(cancels[0, 0])
            assert source == 1 and config['cancel_pending'] and cancel_row > row
            assert cancels[0, 6] == cancel_row and cancels[0, 9] == record['time_s'][cancel_row]
            assert current_mode[cancel_row] != 2
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
        if source == 1 and config['cancel_pending']:
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
