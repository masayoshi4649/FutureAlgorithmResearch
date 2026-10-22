"""発生済みの親通知を土台に、複数追撃と玉別出口を因果的に比較する。"""

import numpy as np
from numba import njit


@njit(cache=True)
def _emit(out, count, row, decision, parent, side, quantity, price, reason, new, uid, fee_tenths):
    """
    機能: 一注文を十列形式で追加し、注文単位に手数料を切り捨てる。
    引数: out(ndarray)、count/row/decision/parent/side/quantity/new/uid/fee_tenths(int)、price/reason(float)。
    返り値: intは追加後の注文数。
    """
    assert count < len(out)
    out[count] = np.array([row, decision, parent, side, quantity, price, reason,
                           new, uid, quantity * fee_tenths // 10])
    return count + 1


@njit(cache=True)
def campaign(times, bid, ask, valid, atr, market, phase, original,
             initial, adaptive, target, increments, steps, fill_last,
             support_hold, min_after_initial, add_min_gap,
             activation, widths, tighten_at, tight_widths, stops, profit_take,
             recycle_rounds, cooldown, recycle_step, initial_wait, total_allocation,
             risk_floor, fee_tenths, multiplier):
    """
    機能: 一親の通知だけを発生順に読み、複数の追撃玉を独立して管理する。
    引数: 原行配列とoriginal(ndarray)、枚数・時刻・幅の事前固定条件(int/float/bool/ndarray)。
          玉別配列は初回を添字0、通常追撃を1以降、再追加を通常段数以後に割り当てる。
    返り値: ndarrayは約定原行・判断原行・親ID・方向・枚数・価格・理由・新規・玉UID・費用。
    """
    stages = len(increments)
    slots = stages + recycle_rounds + 1
    out = np.zeros((max(256, (len(original) + 5) * (slots + 1)), 10))
    count = 0
    parent = int(original[0, 2])
    side = int(original[0, 3])
    virtual = int(original[0, 4])
    risk = max(risk_floor, atr[int(original[0, 1])])
    assert np.isfinite(risk) and risk > 0.
    held = np.zeros(slots, np.int64)
    entry = np.zeros(slots)
    style = np.zeros(slots, np.int64)
    peak = np.full(slots, -np.inf)
    floor = np.full(slots, -np.inf)
    done = np.zeros(slots, np.bool_)
    cash = np.zeros(slots)
    pending_close = np.full(slots, -1, np.int64)
    pending_reason = np.zeros(slots)
    next_uid = 1
    stage = 0
    recycle_used = 0
    recycle_credit = 0
    recycle_anchor = -np.inf
    last_profit_exit = -np.inf
    favorable = -np.inf
    last_added = -np.inf
    first_time = -np.inf
    initial_price = 0.
    since = -np.inf
    pointer = 0
    reduced = False
    pending_add = -1
    pending_qty = 0
    pending_style = 0
    pending_recycle = False

    for i in range(int(original[0, 0]), int(original[-1, 0]) + 1):
        good = valid[i] and np.isfinite(bid[i]) and np.isfinite(ask[i]) and 0 < bid[i] < ask[i]
        mark = bid[i] if side > 0 else ask[i]
        if good:
            favorable = max(favorable, side * mark)

        # ----------------------------------------
        # 元親の当行通知を先に処理する。将来の勝敗・返済価格を条件にしない。
        while pointer < len(original) and int(original[pointer, 0]) == i:
            o = original[pointer]
            pointer += 1
            if int(o[7]) == 1:
                assert first_time == -np.inf
                quantity = initial
                src = int(o[1])
                if adaptive:
                    strong = market[src, 11] == 1. and side * market[src, 4] >= .05 and side * market[src, 6] >= .05
                    strong = strong and side * market[src, 5] >= .2 and side * market[src, 7] >= .2
                    if strong and phase[src] not in (0, 2, 7, 9):
                        quantity = target
                    if phase[src] in (0, 2, 7, 9):
                        quantity = 1
                quantity = min(quantity, target)
                held[0] = quantity
                entry[0] = o[5]
                initial_price = o[5]
                cash[0] = -side * quantity * o[5] * multiplier - quantity * fee_tenths // 10
                first_time = times[i]
                last_added = times[i]
                count = _emit(out, count, i, int(o[1]), parent, side, quantity, o[5], o[6], 1, 0, fee_tenths)
            else:
                before = virtual
                virtual -= int(o[4])
                assert virtual >= 0
                reduced = True
                pending_add = -1
                remain_by_leg = np.zeros(slots, np.int64)
                if virtual and total_allocation:
                    eligible = 0
                    fractions = np.full(slots, -1.)
                    assigned = 0
                    for leg in range(next_uid):
                        if initial_wait and leg == 0:
                            remain_by_leg[leg] = held[leg]
                            continue
                        expected = held[leg] * virtual / before
                        remain_by_leg[leg] = int(np.floor(expected))
                        assigned += remain_by_leg[leg]
                        eligible += held[leg]
                        fractions[leg] = expected - remain_by_leg[leg] if held[leg] else -1.
                    # 総残数を先に確定し、端数の大きい玉から残す。同率は古い玉を優先する。
                    desired = int(np.floor(eligible * virtual / before + .5))
                    while assigned < desired:
                        selected = -1
                        fraction = -1.
                        for leg in range(next_uid):
                            if fractions[leg] > fraction:
                                selected = leg
                                fraction = fractions[leg]
                        assert selected >= 0
                        remain_by_leg[selected] += 1
                        fractions[selected] = -1.
                        assigned += 1
                for leg in range(next_uid):
                    pending_close[leg] = -1
                    if virtual and initial_wait and leg == 0:
                        continue
                    remain = remain_by_leg[leg] if total_allocation else (int(np.floor(held[leg] * virtual / before + .5)) if virtual else 0)
                    take = held[leg] - remain
                    if take:
                        count = _emit(out, count, i, int(o[1]), parent, -side, take, o[5], o[6], 0, leg, fee_tenths)
                        cash[leg] += side * take * o[5] * multiplier - take * fee_tenths // 10
                        held[leg] = remain

        # ----------------------------------------
        # 玉別の発注済み返済を次の正常気配で執行する。約定前に利益を保証しない。
        for leg in range(next_uid):
            if pending_close[leg] < 0 or i <= pending_close[leg] or not good or held[leg] == 0:
                continue
            take = held[leg] if profit_take == 0 or pending_reason[leg] == 1392. else min(held[leg], profit_take)
            count = _emit(out, count, i, pending_close[leg], parent, -side, take, mark,
                          pending_reason[leg], 0, leg, fee_tenths)
            cash[leg] += side * take * mark * multiplier - take * fee_tenths // 10
            held[leg] -= take
            pending_close[leg] = -1
            done[leg] = True
            if leg > 0 and held[leg] == 0 and cash[leg] > 0. and pending_reason[leg] == 1391.:
                recycle_credit += take
                recycle_anchor = max(recycle_anchor, favorable)
                last_profit_exit = times[i]
                since = -np.inf

        # ----------------------------------------
        # 一度に一段を執行し、各玉に再利用しないUIDと自身の順行履歴を与える。
        if pending_add >= 0 and i > pending_add and good:
            if held[0] > 0 and not reduced:
                quantity = min(pending_qty, target - int(held.sum()))
                if quantity > 0:
                    uid = next_uid
                    next_uid += 1
                    assert uid < slots
                    held[uid] = quantity
                    entry[uid] = ask[i] if side > 0 else bid[i]
                    style[uid] = pending_style
                    cash[uid] = -side * quantity * entry[uid] * multiplier - quantity * fee_tenths // 10
                    count = _emit(out, count, i, pending_add, parent, side, quantity, entry[uid],
                                  1393. if pending_recycle else 901., 1, uid, fee_tenths)
                    last_added = times[i]
                    since = -np.inf
                    if pending_recycle:
                        recycle_credit -= quantity
            pending_add = -1

        # ----------------------------------------
        # 自身の建値以後の利益に応じて保護を始める。停止は利益保護とは独立である。
        for leg in range(next_uid):
            if not good or held[leg] == 0 or pending_close[leg] >= 0:
                continue
            idx = style[leg]
            move = side * (mark - entry[leg])
            peak[leg] = max(peak[leg], move)
            if stops[idx] > 0. and move <= -stops[idx] * risk:
                pending_close[leg] = i
                pending_reason[leg] = 1392.
            elif not done[leg] and activation[idx] > 0. and peak[leg] >= activation[idx] * risk:
                width = tight_widths[idx] if tighten_at[idx] > 0. and peak[leg] >= tighten_at[idx] * risk else widths[idx]
                floor[leg] = max(floor[leg], peak[leg] - width * risk)
                if move <= floor[leg]:
                    pending_close[leg] = i
                    pending_reason[leg] = 1391.

        # ----------------------------------------
        # 追撃は保有状態へフィードバックする。元親の部分返済後と初回玉消滅後は追加しない。
        if not good or (i > 0 and times[i] - times[i - 1] > 15.):
            since = -np.inf
        if not good or reduced or held[0] == 0 or pending_add >= 0 or np.any(pending_close >= 0):
            continue
        if int(held.sum()) >= target:
            continue
        recycling = stage >= stages
        if recycling and (recycle_rounds == 0 or recycle_used >= recycle_rounds or recycle_credit == 0):
            continue
        anchor = max(last_added, last_profit_exit) if recycling else last_added
        support = market[i, 11] == 1. and side * market[i, 4] >= .05 and side * market[i, 6] >= .05
        support = support and side * market[i, 5] >= .2 and side * market[i, 7] >= .2
        support = support and market[i, 8] > anchor and times[i] >= first_time + min_after_initial
        if support:
            if not np.isfinite(since):
                since = times[i]
        else:
            since = -np.inf
        passed = support and times[i] - since >= support_hold and times[i] - last_added >= add_min_gap
        if adaptive and phase[i] in (0, 2, 7, 9):
            passed = False
        if recycling:
            passed = passed and times[i] - last_profit_exit >= cooldown and side * mark >= recycle_anchor + recycle_step * risk
        else:
            passed = passed and side * (mark - initial_price) >= steps[stage] * risk
        if passed:
            pending_add = i
            pending_recycle = recycling
            if recycling:
                pending_qty = min(recycle_credit, target - int(held.sum()))
                pending_style = stages + recycle_used + 1
                recycle_used += 1
            else:
                pending_qty = target - int(held.sum()) if fill_last and stage == stages - 1 else min(int(increments[stage]), target - int(held.sum()))
                pending_style = stage + 1
                stage += 1
    assert held.sum() == 0 and virtual == 0
    return out[:count]


def _expanded(value, length, default):
    """
    機能: 玉別設定の不足分を末尾の値で補い、単一値も同じ配列へ変換する。
    引数: value(float/list[float]/None)、length(int)、default(float)。
    返り値: ndarrayは必要長のfloat64配列。
    """
    if value is None:
        values = [default]
    elif np.isscalar(value):
        values = [float(value)]
    else:
        values = list(value)
        if not values:
            values = [default]
    return np.asarray((values + [values[-1]] * length)[:length], dtype=np.float64)


def replay(times, quotes, atr, market, phase, core, config):
    """
    機能: 主担当の全親を別々に再生し、初回・通常追撃・再追加の注文を返す。
    引数: times/atr/market/phase/core(ndarray)、quotes(dict)はbid/ask/quote_valid、config(dict)は固定条件。
          increments/stepsは通常段階、玉別exit_activation/exit_width/tighten_at/tight_width/stop_widthはR倍率。
          再追加は通常段階を終えた後、利益追尾で完全返済した追加枚数だけを新極値と新支持で補充する。
          initial_waitは元親の部分返済時だけ初回玉を残す。元親全返済は常に優先する。
          partial_allocationはtotalで総残数を先に丸め、legacyは旧研究との同値用に玉別で丸める。
    返り値: ndarrayは十列注文。補完担当の合算と口座上限監査は呼出側で行う。
    """
    if config.get('native_exit', False):
        raise ValueError('この核は元親全返済を遵守します。独立出口は別の比較として実装してください。')
    initial = int(config.get('initial', 2))
    target = int(config.get('target', 5))
    assert 1 <= initial <= target <= 10
    increments = np.asarray(config.get('increments', []), dtype=np.int64)
    steps = np.asarray(config.get('steps', []), dtype=np.float64)
    assert len(increments) == len(steps) and np.all(increments > 0) and np.all(steps >= 0.)
    rounds = int(config.get('recycle_rounds', 0))
    assert 0 <= rounds <= 16 and len(increments) <= 16
    allocation = config.get('partial_allocation', 'total')
    assert allocation in ('total', 'legacy')
    length = len(increments) + rounds + 1
    activation = _expanded(config.get('exit_activation'), length, 0.)
    widths = _expanded(config.get('exit_width'), length, 1.)
    tighten_at = _expanded(config.get('tighten_at'), length, 0.)
    tight_widths = _expanded(config.get('tight_width'), length, 1.)
    stops = _expanded(config.get('stop_width'), length, 0.)
    assert np.all(np.isfinite(activation)) and np.all(activation >= 0.)
    assert np.all(np.isfinite(widths)) and np.all(widths > 0.)
    assert np.all(np.isfinite(tight_widths)) and np.all(tight_widths > 0.)
    assert np.all(np.isfinite(stops)) and np.all(stops >= 0.)
    parts = []
    for cid in np.unique(core[:, 2]) if len(core) else []:
        original = np.asarray(core[core[:, 2] == cid], dtype=np.float64)
        assert np.count_nonzero(original[:, 7] == 1) == 1
        assert original[0, 7] == 1 and np.all(np.diff(original[:, 0]) >= 0)
        assert np.all(original[:, 1] < original[:, 0])
        parts.append(campaign(times, quotes['bid'], quotes['ask'], quotes['quote_valid'], atr,
                              market, phase, original, initial, bool(config.get('adaptive', False)), target,
                              increments, steps, bool(config.get('fill_last', True)),
                              float(config.get('support_hold', 15.)), float(config.get('min_after_initial', 30.)),
                              float(config.get('add_min_gap', 0.)), activation, widths, tighten_at, tight_widths,
                              stops, int(config.get('profit_take', 0)), rounds, float(config.get('cooldown', 30.)),
                              float(config.get('recycle_step', .25)), bool(config.get('initial_wait', False)),
                              allocation == 'total',
                              float(config.get('risk_floor', 20.)), int(config.get('fee_tenths', 385)),
                              float(config.get('multiplier', 100.))))
    result = np.concatenate(parts) if parts else np.empty((0, 10))
    return result[np.argsort(result[:, 0], kind='stable')] if len(result) else result
