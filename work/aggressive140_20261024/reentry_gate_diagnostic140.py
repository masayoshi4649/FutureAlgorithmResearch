"""実利益で完結した親の後に、新しい押し戻りを待って同方向へ再参加する。"""

import numpy as np
from numba import njit


REENTRY_PARENT_BASE = 2_000_000
DIAGNOSTIC_COLUMNS = ('原行', '種別', '親ID', '起点親ID', '方向', '枚数', '値1', '値2')
DIAGNOSTIC_KINDS = {
    1: '通常親を採用', 2: '通常親を保有中のため見送り', 3: '通常親が実損益で完結',
    4: '利益後の再参加準備', 5: '新しい押し戻りを確認', 6: '再参加発注判断',
    7: '再参加親が実損益で完結', 8: '準備期限切れ', 9: '準備方向の大幅逆行',
    10: '通常親を新規期限後のため見送り',
}


def defaults():
    """
    機能: 利確後一回だけの再参加に使う事前固定の既定設定を返す。
    引数: なし。
    返り値: dictは商品倍率・料金以外の設定。商品固有値は呼出側で上書きする。
    """
    return dict(enabled=True, entry_mode='pullback', quantity=2, cap=10,
                max_reentries=1, cooldown_seconds=60., expiry_seconds=3600.,
                pullback_r=.5, bounce_r=.25, support_hold_seconds=15.,
                support30=.05, support120=.2, maximum_gap_seconds=15.,
                quote_spread_r=.5, maximum_chase_r=.5, setup_failure_r=2.,
                stop_r=1., trail_start_r=1.5, trail_width_r=.75,
                split_at_r=2., split_fraction=.5, entry_cutoff_seconds=600.,
                risk_floor=1., fee_tenths=418, multiplier=1000.,
                core_only=True)


@njit(cache=True)
def _order(out, count, row, source, parent, side, quantity, price, reason, new, uid, fee):
    """
    機能: 既存の十列形式へ一注文を記録し、注文単位の手数料を切り捨てる。
    引数: out(ndarray)、count/row/source/parent/side/quantity/new/uid/fee(int)、price/reason(float)。
    返り値: intは追加後の注文数。
    """
    assert count < len(out) and source < row and quantity > 0
    out[count] = np.array([row, source, parent, side, quantity, price, reason,
                           new, uid, quantity * fee // 10])
    return count + 1


@njit(cache=True)
def _note(out, count, row, kind, parent, origin, side, quantity, value1, value2):
    """
    機能: 当時までに成立した採否・実損益・準備条件の診断を記録する。
    引数: out(ndarray)、count/row/kind/parent/origin/side/quantity(int)、value1/value2(float)。
    返り値: intは追加後の診断数。
    """
    assert count < len(out)
    out[count] = np.array([row, kind, parent, origin, side, quantity, value1, value2])
    return count + 1


@njit(cache=True)
def _run(times, bid, ask, valid, atr, market, baseline, decision_order, fill_order,
         parent_index, ticket_index, parent_ids, ticket_count, end, parameters):
    """
    機能: 原行順に通常通知を採否し、完結した実利益だけから再参加を判断する。
    引数: 原行と通知・索引列(ndarray)、ticket_count(int)、end(float)、parameters(ndarray)。
    返り値: tuple[ndarray,ndarray]は全注文と診断。未返済・未約定が残れば停止する。
    """
    (enabled, mode, quantity, cap, maximum, cooldown, expiry, pullback, bounce,
     support_hold, support30, support120, maxgap, spread_limit, maxchase,
     failure, stop, trail_start, trail_width, split_at, split_fraction,
     cutoff, risk_floor, fee, multiplier, core_only) = parameters
    quantity, cap, maximum, fee = int(quantity), int(cap), int(maximum), int(fee)
    nb, npart = len(baseline), len(parent_ids)
    capacity = nb + npart * maximum * 3 + 16
    orders = np.zeros((capacity, 10))
    notes = np.zeros((nb * 5 + npart * (maximum + 1) * 10 + 32, 8))
    oc = nc = dp = fp = 0
    gate = np.zeros((npart*(maximum+1)+16, 13), np.int64)
    episode = -1
    accepted = np.zeros(nb, np.bool_)
    parent_state = np.full(npart, -1, np.int64)
    parent_qty = np.zeros(npart, np.int64)
    parent_pending = np.zeros(npart, np.int64)
    parent_net = np.zeros(npart)
    parent_side = np.zeros(npart, np.int64)
    parent_core = np.zeros(npart, np.bool_)
    ticket_qty = np.zeros(ticket_count, np.int64)
    ticket_entry = np.zeros(ticket_count)
    ticket_side = np.zeros(ticket_count, np.int64)
    active_base = -1

    # 再参加の準備は基準親の実損益完結時にのみ発生する。
    armed = False
    stage = 0
    pullback_logged = False
    side = origin = used = 0
    arm_time = setup_risk = anchor = favorable = return_extreme = 0.
    return_row = -1
    since = -np.inf
    total_reentries = 0
    re_parent = 0
    held = 0
    entry = risk = peak = floor = net = 0.
    split_done = False
    pending_new = pending_close = -1
    close_qty = close_reason = 0

    for i in range(len(times)):
        now = times[i]
        good = valid[i] and np.isfinite(bid[i]) and np.isfinite(ask[i]) and 0. < bid[i] < ask[i]
        mid = (bid[i] + ask[i]) * .5 if good else np.nan

        # ----------------------------------------
        # 採用済み通常注文は、通知に記録された実約定行に到達して初めて建値・費用へ反映する。
        while fp < nb and int(baseline[fill_order[fp], 0]) == i:
            k = fill_order[fp]
            fp += 1
            if not accepted[k]:
                continue
            o = baseline[k]
            p, ticket = parent_index[k], ticket_index[k]
            direction, qty = int(o[3]), int(o[4])
            assert good and held == 0 and pending_new < 0
            assert abs(o[5] - (ask[i] if direction > 0 else bid[i])) < 1.e-7
            assert int(o[9]) == qty * fee // 10
            orders[oc] = o
            oc += 1
            parent_net[p] -= o[9]
            if int(o[7]) == 1:
                assert ticket_qty[ticket] == 0
                ticket_qty[ticket] = qty
                ticket_entry[ticket] = o[5]
                ticket_side[ticket] = direction
                parent_qty[p] += qty
                parent_pending[p] -= qty
                parent_side[p] = direction
                assert parent_qty[p] <= cap
            else:
                assert ticket_qty[ticket] >= qty and ticket_side[ticket] == -direction
                parent_net[p] += -direction * (o[5] - ticket_entry[ticket]) * qty * multiplier
                ticket_qty[ticket] -= qty
                parent_qty[p] -= qty

        # ----------------------------------------
        # 新しい売買は判断後の次の正常原行で約定。終端や後の通常候補を先読みして取消さない。
        if pending_new >= 0 and i > pending_new and good:
            entry = ask[i] if side > 0 else bid[i]
            held = quantity
            net = -(quantity * fee // 10)
            peak = 0.
            floor = -stop * risk
            split_done = False
            oc = _order(orders, oc, i, pending_new, re_parent, side, held, entry,
                        1401 if mode == 0 else 1402, 1, 0, fee)
            pending_new = -1
        if pending_close >= 0 and i > pending_close and good:
            px = bid[i] if side > 0 else ask[i]
            assert 0 < close_qty <= held
            net += side * (px - entry) * close_qty * multiplier - close_qty * fee // 10
            oc = _order(orders, oc, i, pending_close, re_parent, -side, close_qty, px,
                        close_reason, 0, 0, fee)
            held -= close_qty
            pending_close = -1
            if held == 0:
                nc = _note(notes, nc, i, 7, re_parent, origin, side, 0, net, risk)
                armed = enabled == 1 and net > 0. and used < maximum and now < end - cutoff
                if armed:
                    arm_time = now
                    setup_risk = max(atr[i], risk_floor) if np.isfinite(atr[i]) and atr[i] > 0. else risk
                    anchor = favorable = return_extreme = side * mid
                    stage = 0
                    pullback_logged = False
                    since = -np.inf
                    nc = _note(notes, nc, i, 4, re_parent, origin, side, quantity, setup_risk, mid)
                    episode += 1
                    gate[episode, 0] = i
                    gate[episode, 1] = origin

        # 通常親の全返済と費用を確認してからだけ再参加の権利を作る。部分利確では準備しない。
        if active_base >= 0 and parent_qty[active_base] == 0 and parent_pending[active_base] == 0:
            p = active_base
            active_base = -1
            nc = _note(notes, nc, i, 3, int(parent_ids[p]), int(parent_ids[p]),
                       parent_side[p], 0, parent_net[p], 0.)
            armed = (enabled == 1 and maximum > 0 and parent_net[p] > 0.
                     and (core_only == 0 or parent_core[p]) and good
                     and np.isfinite(atr[i]) and atr[i] > 0. and now < end - cutoff)
            if armed:
                origin = int(parent_ids[p])
                side = parent_side[p]
                used = 0
                arm_time = now
                setup_risk = max(atr[i], risk_floor)
                anchor = favorable = return_extreme = side * mid
                stage = 0
                pullback_logged = False
                since = -np.inf
                nc = _note(notes, nc, i, 4, origin, origin, side, quantity, setup_risk, mid)
                episode += 1
                gate[episode, 0] = i
                gate[episode, 1] = origin

        # ----------------------------------------
        # 通常の新規は判断時点の実保有・予約を見て採否する。同じ行なら通常を優先する。
        while dp < nb and int(baseline[decision_order[dp], 1]) == i:
            k = decision_order[dp]
            dp += 1
            o = baseline[k]
            p = parent_index[k]
            if int(o[7]) == 1:
                if parent_state[p] < 0:
                    blocked = active_base >= 0 or held > 0 or pending_new >= 0 or pending_close >= 0
                    late = now >= end
                    parent_state[p] = 0 if blocked or late else 1
                    nc = _note(notes, nc, i, 10 if late else 2 if blocked else 1,
                               int(o[2]), origin, int(o[3]), int(o[4]), 0., 0.)
                    if parent_state[p] == 1:
                        active_base = p
                        parent_core[p] = int(o[8]) != 999
                        armed = False
                        since = -np.inf
                if parent_state[p] == 1:
                    assert active_base == p
                    parent_pending[p] += int(o[4])
                    assert parent_qty[p] + parent_pending[p] <= cap
                    accepted[k] = True
            elif parent_state[p] == 1:
                accepted[k] = True

        # ----------------------------------------
        # 再参加玉の出口は実建値から毎行更新する。停止・追尾を優先し、その後に一度の部分利確。
        if held > 0 and pending_close < 0 and good:
            movement = side * ((bid[i] if side > 0 else ask[i]) - entry)
            peak = max(peak, movement)
            if peak >= trail_start * risk:
                floor = max(floor, peak - trail_width * risk)
            reason = 0
            take = held
            if now >= end:
                reason = 1409
            elif movement <= floor:
                reason = 1403 if floor < 0. else 1404
            elif split_at > 0. and not split_done and held >= 2 and movement >= split_at * risk:
                reason = 1405
                take = max(1, min(held - 1, int(np.floor(held * split_fraction))))
                split_done = True
            if reason:
                pending_close = i
                close_qty = take
                close_reason = reason

        # ----------------------------------------
        # 利確後に発生した新しい押し戻りだけを使う。以前の高安や将来の通常新規は参照しない。
        if not armed or active_base >= 0 or held > 0 or pending_new >= 0 or pending_close >= 0:
            continue
        gate[episode, 2] += 1
        if now >= end - cutoff or now - arm_time > expiry:
            nc = _note(notes, nc, i, 8, origin, origin, side, 0, now - arm_time, 0.)
            armed = False
            continue
        if not good or not np.isfinite(atr[i]) or atr[i] <= 0.:
            since = -np.inf
            continue
        z = side * mid
        if z < anchor - failure * setup_risk:
            nc = _note(notes, nc, i, 9, origin, origin, side, 0, mid, setup_risk)
            armed = False
            continue
        gap = i > 0 and times[i] - times[i - 1] > maxgap
        if gap:
            stage = 0
            favorable = return_extreme = z
            since = -np.inf
        favorable = max(favorable, z)
        if stage == 0 and favorable - z >= pullback * setup_risk:
            stage = 1
            return_extreme = z
            return_row = i
            since = -np.inf
            if not pullback_logged:
                nc = _note(notes, nc, i, 5, origin, origin, side, 0, mid, setup_risk)
                pullback_logged = True
        if stage == 1:
            return_extreme = min(return_extreme, z)
        current_risk = max(atr[i], risk_floor)
        quoted = ask[i] if side > 0 else bid[i]
        quality = ask[i] - bid[i] <= spread_limit * current_risk
        quality = quality and side * quoted <= anchor + maxchase * setup_risk
        observed_known = market[i, 11] == 1. and np.isfinite(market[i, 4:9]).all()
        observed_known = observed_known and arm_time < market[i, 8] < now and now - market[i, 8] <= maxgap
        observed_support = observed_known and side*market[i, 4] >= support30 and side*market[i, 6] >= support30
        observed_support = observed_support and side*market[i, 5] >= support120 and side*market[i, 7] >= support120
        observed_bounce = stage == 1 and i > return_row and z-return_extreme >= bounce*setup_risk
        gate[episode, 3] += int(stage == 1)
        gate[episode, 4] += int(observed_bounce)
        gate[episode, 5] += int(observed_support)
        if observed_bounce and observed_support:
            gate[episode, 6] += 1
            gate[episode, 7] += int(side*quoted > anchor+maxchase*setup_risk)
            gate[episode, 8] += int(ask[i]-bid[i] > spread_limit*current_risk)
            gate[episode, 9] += int(now-arm_time < cooldown)
            gate[episode, 10] += int(quality and now-arm_time >= cooldown)
        if now - arm_time < cooldown or not quality:
            since = -np.inf
            continue
        trigger = mode == 1
        if mode == 0:
            known = market[i, 11] == 1. and np.isfinite(market[i, 4:9]).all()
            known = known and arm_time < market[i, 8] < now and now - market[i, 8] <= maxgap
            support = known and side * market[i, 4] >= support30 and side * market[i, 6] >= support30
            support = support and side * market[i, 5] >= support120 and side * market[i, 7] >= support120
            trigger = stage == 1 and i > return_row and z - return_extreme >= bounce * setup_risk and support
            if trigger:
                if not np.isfinite(since):
                    since = now
                trigger = now - since >= support_hold
                gate[episode, 11] += int(not trigger)
            else:
                since = -np.inf
        if trigger:
            gate[episode, 12] += 1
            total_reentries += 1
            used += 1
            re_parent = REENTRY_PARENT_BASE + total_reentries
            risk = current_risk
            pending_new = i
            armed = False
            nc = _note(notes, nc, i, 6, re_parent, origin, side, quantity, risk, quoted)

    assert dp == nb and fp == nb, '通常通知の原行が入力の範囲外です'
    assert held == 0 and pending_new < 0 and pending_close < 0, '再参加玉の場内返済に必要な気配が不足しています'
    assert np.all(ticket_qty == 0) and np.all(parent_pending == 0), '通常玉が未返済です'
    return orders[:oc], notes[:nc], gate[:episode+1]


def replay(times, quotes, atr, market12, baseline10, end, config=None):
    """
    機能: 基準通知と利益後再参加を、保有・注文予約の競合まで含めて一口座で再生する。
    引数: times/atr(ndarray)、quotes(dict: bid/ask/quote_valid)、market12(ndarray)、
          baseline10(ndarray)は既存十列約定、end(float)は強制返済判断時刻、config(dict/None)は係数。
    返り値: tuple[ndarray,dict]は十列注文と診断。通常通知は固定対照でありGo本体の完全再現ではない。
    """
    cfg = defaults()
    if config:
        unknown = set(config) - set(cfg)
        assert not unknown, f'未知の設定: {sorted(unknown)}'
        cfg.update(config)
    assert cfg['entry_mode'] in ('pullback', 'delay')
    assert int(cfg['quantity']) == cfg['quantity'] and 1 <= cfg['quantity'] <= cfg['cap'] <= 10
    assert int(cfg['max_reentries']) == cfg['max_reentries'] and 0 <= cfg['max_reentries'] <= 8
    assert 0 < cfg['split_fraction'] < 1 and cfg['multiplier'] > 0 and cfg['risk_floor'] > 0
    for key, value in cfg.items():
        if isinstance(value, (float, int)):
            assert np.isfinite(value) and value >= 0, key
    assert cfg['stop_r'] > 0 and cfg['trail_width_r'] > 0
    times = np.asarray(times, dtype=np.float64)
    atr = np.asarray(atr, dtype=np.float64)
    market = np.asarray(market12, dtype=np.float64)
    baseline = np.asarray(baseline10, dtype=np.float64).reshape(-1, 10)
    bid, ask = (np.asarray(quotes[k], dtype=np.float64) for k in ('bid', 'ask'))
    valid = np.asarray(quotes['quote_valid'], dtype=np.bool_)
    n = len(times)
    assert n > 0 and len(atr) == len(bid) == len(ask) == len(valid) == n and market.shape == (n, 12)
    assert np.isfinite(times).all() and np.all(np.diff(times) >= 0.) and times[0] <= end <= times[-1]
    assert np.isfinite(baseline).all()
    if len(baseline):
        assert np.all((baseline[:, 1] >= 0) & (baseline[:, 1] < baseline[:, 0]) & (baseline[:, 0] < n))
        assert np.all(baseline[:, 2] < REENTRY_PARENT_BASE)
        assert np.all(np.isin(baseline[:, 3], (-1., 1.))) and np.all(np.isin(baseline[:, 7], (0., 1.)))
        assert np.all(baseline[:, 4] > 0.)
    parents, parent_index = np.unique(baseline[:, 2].astype(np.int64), return_inverse=True)
    ticket_keys = baseline[:, [2, 8]].astype(np.int64)
    tickets, ticket_index = np.unique(ticket_keys, axis=0, return_inverse=True)
    parameters = np.array([
        cfg['enabled'], cfg['entry_mode'] == 'delay', cfg['quantity'], cfg['cap'], cfg['max_reentries'],
        cfg['cooldown_seconds'], cfg['expiry_seconds'], cfg['pullback_r'], cfg['bounce_r'],
        cfg['support_hold_seconds'], cfg['support30'], cfg['support120'], cfg['maximum_gap_seconds'],
        cfg['quote_spread_r'], cfg['maximum_chase_r'], cfg['setup_failure_r'], cfg['stop_r'],
        cfg['trail_start_r'], cfg['trail_width_r'], cfg['split_at_r'], cfg['split_fraction'],
        cfg['entry_cutoff_seconds'], cfg['risk_floor'], cfg['fee_tenths'], cfg['multiplier'], cfg['core_only'],
    ], dtype=np.float64)
    orders, events, gate = _run(times, bid, ask, valid, atr, market, baseline,
                         np.argsort(baseline[:, 1], kind='stable'), np.argsort(baseline[:, 0], kind='stable'),
                         parent_index, ticket_index, parents, len(tickets), float(end), parameters)
    skipped = events[np.isin(events[:, 1], (2., 10.))]
    links = events[events[:, 1] == 6.]
    return orders, dict(gate_counts=gate, config=cfg, columns=DIAGNOSTIC_COLUMNS, events=events,
                        skipped_baseline=skipped, reentry_links=links,
                        convention='通常は判断行で採否。再参加保有・予約中の新しい通常親全体を見送る。通常通知自体は固定対照。')
