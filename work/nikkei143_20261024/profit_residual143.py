"""元の利益追尾返済から最古の利益玉一枚だけを、他玉の実現利益予算で残す。

保存通知は並行する仮想候補であり、原行に到着するまで参照しない。残玉がある
間に届く後続親は初回通知時に全体を見送る。未来の次親で残玉を消さない。
判断時BBOによる見込資格と、他玉を次正常原行で返済した後の実現予算を分ける。
残玉の新規料は既払い費用に全額含め、残玉返済料も損失境界に含める。
利確前の高値を残玉トレールへ流用せず、予算確定時から新しく最高進捗を追跡する。
"""

import numpy as np
from numba import njit


TRACE_COLUMNS = ['原行', '親ID', '種類', '方向', '枚数', '理由', '見込他玉純益',
                 '実現他玉純益', '残玉損失予算', '初回固定R', '現在残玉進捗',
                 '残玉化後最高進捗', '元予約件数']
TRACE_KINDS = {1: '親の初回採否', 2: '利益玉一枚の留保を決定',
               3: '他玉約定後に利益予算確定', 4: '残玉返済判断'}
REASONS = {0: '元親を採用', 93: '場末全返済', 94: '米国開始前後の静観',
           14380: '残玉の広い利益追尾', 14381: '実現利益からの許容損失',
           14382: '他玉約定後の実現利益不足', 14384: '先行親又は残玉保有中の次親を見送り'}


def configurations():
    """
    機能: 無変更対照と追尾二幅・実現利益予算二割合の四条件を返す。
    引数: なし。
    返り値: list[dict]はH00～H04。対象理由は元の利益追尾全返済だけ。
    """
    result = [dict(id='H00', enabled=False, trail_r=2., profit_fraction=.5,
                   eligible_reasons=[2, 70, 1437], quiet_seconds=900.)]
    for index, (trail, fraction) in enumerate(((2., .5), (2., 1.), (3., .5), (3., 1.)), 1):
        result.append(dict(id=f'H{index:02d}', enabled=True, trail_r=trail,
                           profit_fraction=fraction, eligible_reasons=[2, 70, 1437],
                           quiet_seconds=900.))
    return result


@njit(cache=True)
def _replay(times, bid, ask, valid, atr, tick, end, us_open, rows, event_parent,
            event_ticket, parent_values, ticket_parent, ticket_values, reasons, trail_r,
            fraction, quiet_seconds, fee10, multiplier):
    """
    機能: 全元通知を一つの時系列で処理し、利益予算の残玉と後続親の占有を管理する。
    引数: 原行・元注文・親UID対応・対象理由(ndarray)、幅・時刻・予算割合(float)、fee10(int)。
    返り値: tuple[ndarray,ndarray]は十列約定と十三列判断記録。末尾の未完了注文は捏造しない。
    """
    n, count = len(times), len(rows)
    npart, nticket = len(parent_values), len(ticket_values)
    out = np.empty((count + npart + 8, 11))
    log = np.empty((count * 2 + npart * 4 + 20, 13))
    no = nl = 0
    status = np.zeros(npart, np.int64)
    virtual = np.zeros(npart, np.int64)
    actual = np.zeros(nticket, np.int64)
    entry = np.zeros(nticket)
    first_fill = np.full(nticket, n + 1, np.int64)
    cash = np.zeros(npart)
    fixed_r = np.full(npart, np.nan)
    parent_side = np.zeros(npart, np.int64)
    effective = np.zeros(count, np.int64)
    issued = np.zeros(count, np.bool_)
    decision_order = np.argsort(rows[:, 1], kind='mergesort')
    fill_order = np.argsort(rows[:, 0], kind='mergesort')
    di = fi = pending = 0
    owner = -1
    total = 0
    retained = -1
    stage = 0
    budget = estimate = best = 0.
    force_reason = 0
    synthetic_decision = -1
    synthetic_reason = 0
    fee_one = fee10 // 10
    for i in range(n):
        now = times[i]
        terminal = now >= end
        quiet = np.isfinite(us_open) and us_open - quiet_seconds <= now < us_open + quiet_seconds
        # ----------------------------------------
        # 元の発注済み注文は、現在の逆行・時刻境界を理由に取り消さない。
        while fi < count and int(rows[fill_order[fi], 0]) <= i:
            k = fill_order[fi]
            p, u = event_parent[k], event_ticket[k]
            q = effective[k]
            if issued[k]:
                assert owner == p and valid[i] and int(rows[k, 0]) == i
                price = rows[k, 5]
                fee = q * fee10 // 10
                side = parent_side[p]
                if rows[k, 7] > 0.:
                    old = actual[u]
                    entry[u] = (entry[u] * old + price * q) / (old + q)
                    actual[u] += q
                    total += q
                    first_fill[u] = min(first_fill[u], i)
                    cash[p] -= fee
                else:
                    assert actual[u] >= q
                    cash[p] += side * (price - entry[u]) * q * multiplier - fee
                    actual[u] -= q
                    total -= q
                out[no, :10] = rows[k]
                out[no, 4] = q
                out[no, 9] = fee
                out[no, 10] = k
                no += 1
                pending -= 1
            fi += 1
        # ----------------------------------------
        # 残玉の新管理が出した返済も、判断の後の自己次正常原行でのみ約定する。
        if synthetic_decision >= 0 and i > synthetic_decision and valid[i]:
            assert owner >= 0 and total == 1 and actual[retained] == 1
            p, side = owner, parent_side[owner]
            price = bid[i] if side > 0 else ask[i]
            out[no] = np.array([i, synthetic_decision, parent_values[p], -side, 1,
                               price, synthetic_reason, 0, ticket_values[retained], fee_one, 1.e12 + no])
            no += 1
            cash[p] += side * (price - entry[retained]) * multiplier - fee_one
            actual[retained] = 0
            total = 0
            retained = -1
            stage = 0
            synthetic_decision = -1
            force_reason = 0
        if owner >= 0 and total == 0 and pending == 0 and stage == 0:
            owner = -1
        if stage > 0:
            if terminal:
                force_reason = 93
            elif quiet and force_reason == 0:
                force_reason = 94
        # ----------------------------------------
        # この行の通知だけをまとめ、全返済か・理由が利益追尾かを確認する。
        stop = di
        while stop < count and int(rows[decision_order[stop], 1]) == i:
            stop += 1
        withheld_event = -1
        if (owner >= 0 and stage == 0 and pending == 0 and total >= 1 and valid[i]
                and not terminal and not quiet and stop > di):
            new_quantity = close_quantity = 0
            eligible = True
            for pos in range(di, stop):
                k = decision_order[pos]
                if event_parent[k] == owner:
                    if rows[k, 7] > 0.:
                        new_quantity += int(rows[k, 4])
                    else:
                        close_quantity += int(rows[k, 4])
                        eligible = eligible and np.any(reasons == int(rows[k, 6]))
            if eligible and new_quantity == 0 and close_quantity > 0 and close_quantity == virtual[owner]:
                side = parent_side[owner]
                price = bid[i] if side > 0 else ask[i]
                candidate = -1
                age = n + 2
                for u in range(nticket):
                    profitable = side * (price - entry[u]) * multiplier > fee_one
                    if (ticket_parent[u] == owner and actual[u] > 0 and profitable
                            and first_fill[u] < age):
                        candidate, age = u, first_fill[u]
                if candidate >= 0:
                    estimate = cash[owner]
                    trial_event = -1
                    for pos in range(di, stop):
                        k = decision_order[pos]
                        if event_parent[k] != owner or rows[k, 7] > 0.:
                            continue
                        q, u = int(rows[k, 4]), event_ticket[k]
                        if u == candidate and trial_event < 0:
                            q -= 1
                            trial_event = k
                        estimate += side * (price - entry[u]) * q * multiplier - q * fee10 // 10
                    if estimate > 0. and trial_event >= 0:
                        withheld_event = trial_event
                        retained = candidate
                        stage = 1
                        force_reason = 0
                        log[nl] = np.array([i, parent_values[owner], 2, side, 1, 0,
                                           estimate, cash[owner], 0., fixed_r[owner],
                                           side * (price - entry[retained]), 0., pending])
                        nl += 1
        # ----------------------------------------
        # 初回通知時に親を占有する。後続親の未来損益を見ず、残玉保有中は親全体を見送る。
        while di < stop:
            k = decision_order[di]
            p, u = event_parent[k], event_ticket[k]
            q = int(rows[k, 4])
            assert int(rows[k, 1]) == i and int(rows[k, 0]) > i
            if rows[k, 7] > 0.:
                virtual[p] += q
                if status[p] == 0:
                    admitted = owner < 0
                    status[p] = 1 if admitted else -1
                    parent_side[p] = int(rows[k, 3])
                    r = max(atr[i], 8. * tick) if np.isfinite(atr[i]) and atr[i] > 0. else 8. * tick
                    fixed_r[p] = r
                    if admitted:
                        owner = p
                    log[nl] = np.array([i, parent_values[p], 1, parent_side[p], q if admitted else 0,
                                       0 if admitted else 14384, 0., 0., 0., r, 0., 0., pending])
                    nl += 1
            else:
                virtual[p] -= q
                assert virtual[p] >= 0
            use = q if status[p] == 1 else 0
            if k == withheld_event:
                use -= 1
            assert use >= 0
            if use:
                assert owner == p
                effective[k] = use
                issued[k] = True
                pending += 1
            di += 1
        # ----------------------------------------
        # 既払新規料を全て引いた実現利益だけを予算にする。残玉の含み益は予算へ足さない。
        if stage == 1 and pending == 0:
            assert owner >= 0 and total == 1 and actual[retained] == 1
            side = parent_side[owner]
            if cash[owner] <= 0.:
                force_reason = 14382 if force_reason == 0 else force_reason
            budget = max(0., cash[owner]) * fraction
            price = bid[i] if side > 0 else ask[i]
            best = side * (price - entry[retained])
            stage = 2
            log[nl] = np.array([i, parent_values[owner], 3, side, 1, force_reason,
                               estimate, cash[owner], budget, fixed_r[owner], best, best, pending])
            nl += 1
        if stage == 2 and synthetic_decision < 0:
            side = parent_side[owner]
            reason = force_reason
            gain = np.nan
            if valid[i]:
                price = bid[i] if side > 0 else ask[i]
                gain = side * (price - entry[retained])
                best = max(best, gain)
                budget_floor = (fee_one - budget) / multiplier
                trail_floor = best - trail_r * fixed_r[owner]
                if reason == 0 and gain <= max(budget_floor, trail_floor):
                    reason = 14381 if budget_floor >= trail_floor else 14380
            if reason:
                synthetic_decision, synthetic_reason = i, reason
                log[nl] = np.array([i, parent_values[owner], 4, side, 1, reason,
                                   estimate, cash[owner], budget, fixed_r[owner], gain, best, pending])
                nl += 1
        assert total >= 0 and pending >= 0
    # ----------------------------------------
    # 場末判断直後で入力を切った因果性検査では、次正常原行の未到来を未約定のまま残す。
    unfinished_tail = synthetic_decision >= 0 and not np.any(valid[synthetic_decision + 1:])
    if len(times) and times[-1] >= end and np.max(rows[:, 0]) < n and not unfinished_tail:
        assert total == 0 and pending == 0 and stage == 0
    return out[:no], log[:nl]


def replay(data, baseline, config):
    """
    機能: 利益追尾の全返済通知を、既確定利益で支える一枚残玉へ変更する。
    引数: data(dict)はready/quotes、baseline(ndarray[N,10])は元仮想通知、config(dict)は固定条件。
    返り値: tuple[ndarray[M,10],ndarray[K,13]]は実約定とTRACE_COLUMNSの記録。
    """
    baseline = np.asarray(baseline, dtype=float).reshape(-1, 10)
    ready, quotes = data['ready'], data['quotes']
    times = np.asarray(ready['time_s'], dtype=float)
    assert ready['symbol'] == 'NK225'
    assert np.all(np.diff(times) >= 0.)
    assert np.all(baseline[:, 0] > baseline[:, 1])
    if not len(baseline) or not config['enabled']:
        return baseline[baseline[:, 0] < len(times)].copy(), np.empty((0, len(TRACE_COLUMNS)))
    bid, ask = np.asarray(quotes['bid']), np.asarray(quotes['ask'])
    good = np.asarray(quotes['quote_valid'], bool) & np.isfinite(bid) & np.isfinite(ask) & (bid > 0.) & (ask > bid)
    parents = list(dict.fromkeys(baseline[:, 2]))
    pmap = {p: i for i, p in enumerate(parents)}
    tickets = list(dict.fromkeys((row[2], row[8]) for row in baseline))
    tmap = {key: i for i, key in enumerate(tickets)}
    ep = np.array([pmap[row[2]] for row in baseline], np.int64)
    et = np.array([tmap[row[2], row[8]] for row in baseline], np.int64)
    tp = np.array([pmap[p] for p, _ in tickets], np.int64)
    tv = np.array([u for _, u in tickets], float)
    for p in parents:
        rows = baseline[baseline[:, 2] == p]
        first = rows[np.argmin(rows[:, 1])]
        assert first[7] == 1.
        assert np.all(rows[rows[:, 7] == 1, 3] == first[3])
        assert np.all(rows[rows[:, 7] == 0, 3] == -first[3])
    result, trace = _replay(times, bid, ask, good, np.asarray(ready['atr']), float(ready['tick']),
        float(ready['limit']), float(ready.get('us_open', np.nan)), baseline, ep, et,
        np.array(parents, float), tp, tv, np.array(config['eligible_reasons'], np.int64),
        float(config['trail_r']), float(config['profit_fraction']), float(config['quiet_seconds']), 385, 100.)
    orders = result[np.lexsort((result[:, 10], result[:, 0])), :10] if len(result) else result[:, :10]
    return orders, trace
