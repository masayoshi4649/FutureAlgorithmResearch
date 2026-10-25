"""日経の固定価格帯を一つの売買エピソードとして扱う。金融再生は呼出側の登録後に行う。"""

import numpy as np
from numba import njit


TRACE_COLUMNS = ('判断原行', '種類', '方向', '入口型', '理由', '親ID', '枚数',
                 '固定境界', '準備極値', '固定R', '停止価格', '固定中心')
REASONS = {1431: '外抜け後の帯内回復', 1432: '突破した固定支持の再確認',
           1433: '低効率帯端からの反発', 1434: '利益保護後の追撃',
           1435: '固定中心で部分返済', 1436: '固定支持又は初回極値の破綻',
           1437: '利益追尾', 93: '場末返済', 94: '米国開始前後の静観'}


def configurations():
    """
    機能: 入口3種類×公開帯3期間と、枚数・静観・部分返済・帯幅・追尾の対照を事前に定義する。
    引数: なし。
    返り値: list[dict]はE01～E16の固定条件。全条件が日経専用・片方向最大5枚。
    """
    names = ('帯外への突破失敗を帯内回復で確認', '突破後の固定支持を押しで確認',
             '低効率帯の端から反発を確認')
    result = []
    for family in (1, 2, 3):
        for window in (20, 40, 60):
            result.append(dict(id=f'E{len(result)+1:02d}', name=f'{window}分・'+names[family-1],
                family=family, window=window, initial=2, maximum=5, partial=True,
                quiet_seconds=0., confirmation=15., trend_confirmation=30.,
                trail_range=.5, activation_r=1., add_step=.5, add_interval=60.,
                entry_cutoff=300., spread_range=.1, min_range_ticks=16., gap_seconds=15.))
    for source, updates, suffix in ((1, dict(initial=1), '・初回1枚'),
                                     (1, dict(quiet_seconds=900.), '・米国前後15分静観'),
                                     (1, dict(partial=False), '・中心で部分返済なし')):
        config = dict(result[source], **updates)
        config.update(id=f'E{len(result)+1:02d}', name=config['name']+suffix)
        result.append(config)
    for source, updates, suffix in ((1, dict(min_range_ticks=8.), '・最小帯幅8刻み'),
                                     (7, dict(min_range_ticks=8.), '・最小帯幅8刻み'),
                                     (4, dict(min_range_ticks=8.), '・最小帯幅8刻み'),
                                     (1, dict(trail_range=1.), '・追尾は帯幅全体')):
        config = dict(result[source], **updates)
        config.update(id=f'E{len(result)+1:02d}', name=config['name']+suffix)
        result.append(config)
    return result


@njit(cache=True)
def _record(out, count, row, source, parent, side, qty, price, reason, new, uid, fee):
    """
    機能: 次正常原行の約定を注文別手数料付き十列へ追記する。
    引数: out(ndarray)、識別子・数量・手数料(int)、price(float)は注文情報。
    返り値: intは追記後の行数。
    """
    assert count < len(out) and row > source and qty > 0
    out[count] = np.array([row, source, parent, side, qty, price, reason, new, uid, qty*fee//10])
    return count+1


@njit(cache=True)
def _trace(out, count, row, kind, side, family, reason, parent, qty, edge, extreme, risk, stop, center):
    """
    機能: 準備・発注・返済と固定水準を原行に対応付けて記録する。
    引数: out(ndarray)、行識別・種類等(int)、水準等(float)は判断内容。
    返り値: intは追記後の行数。
    """
    assert count < len(out)
    out[count] = np.array([row, kind, side, family, reason, parent, qty, edge, extreme, risk, stop, center])
    return count+1


@njit(cache=True)
def simulate(times, bid, ask, good, history, start, end, us_open, tick, fee, p):
    """
    機能: 公開済み帯を準備時に固定し、自己価格の突破失敗・支持維持・反発を売買する。
    引数: times/bid/ask/good/history/p(ndarray)、start/end/us_open/tick(float)、fee(int)。
    返り値: tuple[ndarray,ndarray]は十列約定と十二列判断。場末の未返済は例外。

    返済後の同方向再準備には、その時点以降の新しい境界又は外側極値が必要。
    120秒符号・将来終値・他市場の損益は使用しない。予定済み注文を境界越えで取消扱いにしない。
    """
    family, window, initial, maximum, partial, quiet_seconds, confirmation, trend_confirmation, trail_range, activation_r, add_step, add_interval, entry_cutoff, spread_range, min_range_ticks, gap_seconds = p
    family, initial, maximum = int(family), int(initial), int(maximum)
    n = len(times)
    orders = np.zeros((max(1024, 2*n+16), 10))
    trace = np.zeros((max(1024, 2*n+16), 12))
    held = np.zeros(6, np.int64)
    entries = np.zeros(6)
    locked = np.zeros(2, np.bool_)
    lock_edge = np.zeros(2)
    lock_extreme = np.zeros(2)
    lock_public = np.zeros(2)
    oc = tc = 0
    parent = -1
    uid = side = 0
    base = risk = floor = best = initial_budget = 0.
    band_width = edge = center = episode_extreme = 0.
    arm = stage = 0
    arm_edge = arm_center = arm_width = arm_extreme = arm_time = 0.
    since = -np.inf
    pending = pending_side = pending_qty = pending_reason = 0
    source = -1
    pending_stop = pending_width = pending_edge = pending_center = pending_extreme = 0.
    last_add = -np.inf
    last_add_gain = 0.
    partial_done = False
    campaign_low = campaign_high = 0.
    for i in range(n):
        t = times[i]
        valid = good[i] and np.isfinite(bid[i]) and np.isfinite(ask[i]) and 0. < bid[i] < ask[i]
        terminal = t >= end
        quiet = np.isfinite(us_open) and quiet_seconds > 0. and us_open-quiet_seconds <= t < us_open+quiet_seconds
        if i > 0 and t-times[i-1] > gap_seconds:
            since = -np.inf
        known = valid and np.isfinite(history[i]).all() and history[i, 0] > history[i, 1]
        mid = (bid[i]+ask[i])*.5 if valid else np.nan
        # ----------------------------------------
        # 判断の次の正常原行で約定する。過去の発注を新しい情報によって取り消さない。
        if pending and valid and i > source:
            price = ask[i] if pending_side > 0 else bid[i]
            if pending in (1, 3):
                if pending == 1:
                    parent += 1
                    side = pending_side
                    uid = 0
                    base = price
                    floor = side*(pending_stop-base)
                    risk = max(8.*tick, -floor)
                    initial_budget = pending_qty*max(tick, -floor)
                    band_width, edge, center, episode_extreme = pending_width, pending_edge, pending_center, pending_extreme
                    best = 0.
                    partial_done = False
                    campaign_low = campaign_high = mid
                    last_add_gain = 0.
                else:
                    uid += 1
                held[uid] = pending_qty
                entries[uid] = price
                oc = _record(orders, oc, i, source, parent, side, pending_qty, price, pending_reason, 1, uid, fee)
                last_add = t
            else:
                remaining = int(held.sum()) if pending == 2 else pending_qty
                for u in range(5, -1, -1):
                    if held[u] and remaining:
                        q = min(held[u], remaining)
                        held[u] -= q
                        remaining -= q
                        oc = _record(orders, oc, i, source, parent, -side, q, price, pending_reason, 0, u, fee)
                assert remaining == 0
                if pending == 4:
                    partial_done = True
                    floor = max(floor, 2.*fee/1000.+tick)
                else:
                    k = 0 if side > 0 else 1
                    locked[k] = True
                    lock_edge[k] = history[i, 1] if side > 0 else history[i, 0]
                    if family == 2:
                        lock_edge[k] = history[i, 0] if side > 0 else history[i, 1]
                    if not np.isfinite(lock_edge[k]):
                        lock_edge[k] = edge
                    # 返済の約定原行も旧取引の極値に含め、同じ原行のギャップで再準備しない。
                    closed_low, closed_high = min(campaign_low, mid), max(campaign_high, mid)
                    lock_extreme[k] = closed_low if side > 0 else closed_high
                    if family == 2:
                        lock_extreme[k] = closed_high if side > 0 else closed_low
                    lock_public[k] = history[i, 8] if known else t
                    arm = stage = 0
                    since = -np.inf
            pending = 0
        total = int(held.sum())
        if total and valid:
            campaign_low = min(campaign_low, mid)
            campaign_high = max(campaign_high, mid)
        # ----------------------------------------
        # 固定した無効化価格を保険とし、中心への回帰では一部を返済して残玉だけ追尾する。
        if total and not pending:
            reason = 0
            if terminal or quiet:
                reason = 93 if terminal else 94
            elif valid:
                mark = bid[i] if side > 0 else ask[i]
                gain = side*(mark-base)
                best = max(best, gain)
                if best >= activation_r*risk:
                    floor = max(floor, best-max(8.*tick, trail_range*band_width))
                if gain <= floor:
                    reason = 1437 if floor > 0. else 1436
                if not reason and partial and family != 2 and not partial_done and total >= 2:
                    if side*(mark-center) >= 0. and gain > 2.*fee/1000.+tick:
                        pending, source, pending_side, pending_qty, pending_reason = 4, i, -side, total//2, 1435
                        tc = _trace(trace, tc, i, 4, side, family, 1435, parent, pending_qty, edge, episode_extreme, risk, base+side*floor, center)
            if reason:
                pending, source, pending_side, pending_reason = 2, i, -side, reason
                tc = _trace(trace, tc, i, 4, side, family, reason, parent, total, edge, episode_extreme, risk, base+side*floor, center)
        # ----------------------------------------
        # 初回の利益保護後だけ追加する。全玉の停止線までの損失を初回予算以内へ抑える。
        if total and valid and not pending and total < maximum and uid < 5 and not quiet and t < end-entry_cutoff:
            mark = bid[i] if side > 0 else ask[i]
            gain = side*(mark-base)
            if floor >= 2.*fee/1000. and t-last_add >= add_interval and gain >= last_add_gain+add_step*risk:
                price = ask[i] if side > 0 else bid[i]
                stop_price = base+side*floor
                exposed = 0.
                for u in range(6):
                    exposed += held[u]*max(0., side*(entries[u]-stop_price))
                extra_risk = max(tick, side*(price-stop_price))
                if exposed+extra_risk <= initial_budget and ask[i]-bid[i] <= spread_range*band_width:
                    pending, source, pending_side, pending_qty, pending_reason = 3, i, side, 1, 1434
                    last_add_gain = gain
                    tc = _trace(trace, tc, i, 3, side, family, 1434, parent, 1, edge, episode_extreme, risk, stop_price, center)
        # ----------------------------------------
        # 返済後は同じ価格帯で短期符号だけを見て入り直さず、新境界か新しい外側極値を待つ。
        if not total and not pending and known and start <= t < end-entry_cutoff and not quiet:
            high, low, efficiency = history[i, 0], history[i, 1], history[i, 2]
            width = high-low
            for k in range(2):
                if locked[k]:
                    direction = 1 if k == 0 else -1
                    if family == 2:
                        boundary = high if direction > 0 else low
                        fresh_band = history[i, 8] > lock_public[k] and direction*(boundary-lock_edge[k]) >= 2.*tick
                        fresh_extreme = direction*(mid-lock_extreme[k]) >= 2.*tick
                    else:
                        boundary = low if direction > 0 else high
                        fresh_band = history[i, 8] > lock_public[k] and direction*(lock_edge[k]-boundary) >= 2.*tick
                        fresh_extreme = direction*(lock_extreme[k]-mid) >= 2.*tick
                    if fresh_band or fresh_extreme:
                        locked[k] = False
            qualified = width >= min_range_ticks*tick and ask[i]-bid[i] <= spread_range*width
            if arm and (t-arm_time > window*60. or not qualified):
                arm = stage = 0
                since = -np.inf
            if not arm and qualified:
                candidate = 0
                boundary = 0.
                if family == 1:
                    if mid <= low-2.*tick:
                        candidate, boundary = 1, low
                    elif mid >= high+2.*tick:
                        candidate, boundary = -1, high
                elif family == 2:
                    if mid >= high+2.*tick:
                        candidate, boundary = 1, high
                    elif mid <= low-2.*tick:
                        candidate, boundary = -1, low
                elif efficiency <= .3:
                    if mid <= low+.05*width:
                        candidate, boundary = 1, low
                    elif mid >= high-.05*width:
                        candidate, boundary = -1, high
                k = 0 if candidate > 0 else 1
                if candidate and not locked[k]:
                    arm, arm_edge, arm_center, arm_width = candidate, boundary, (high+low)*.5, width
                    arm_extreme, arm_time, stage, since = mid, t, 0, -np.inf
                    tc = _trace(trace, tc, i, 0, arm, family, 1430+family, parent+1, initial, arm_edge, arm_extreme, 0., 0., arm_center)
            if arm:
                signed = arm*(mid-arm_edge)
                trigger = False
                if family == 2:
                    if signed < -2.*tick:
                        arm = stage = 0
                    elif stage == 0:
                        arm_extreme = max(arm_extreme, mid) if arm > 0 else min(arm_extreme, mid)
                        if arm*(arm_extreme-mid) >= max(2.*tick, .15*arm_width):
                            stage = 1
                            arm_extreme = mid
                    else:
                        arm_extreme = min(arm_extreme, mid) if arm > 0 else max(arm_extreme, mid)
                        trigger = arm*(mid-arm_extreme) >= 2.*tick and signed >= 2.*tick
                    stop_price = arm_edge-arm*2.*tick
                else:
                    arm_extreme = min(arm_extreme, mid) if arm > 0 else max(arm_extreme, mid)
                    if family == 1:
                        trigger = signed >= 2.*tick
                    else:
                        trigger = arm*(mid-arm_extreme) >= max(2.*tick, .125*arm_width) and signed >= 0.
                    stop_price = arm_extreme-arm*max(2.*tick, .1*arm_width)
                if arm and trigger:
                    price = ask[i] if arm > 0 else bid[i]
                    distance = arm*(price-stop_price)
                    reward = arm*(arm_center-price)
                    acceptable = 0. < distance <= .75*arm_width
                    if family != 2:
                        acceptable = acceptable and reward >= max(4.*tick, 2.*(ask[i]-bid[i]))
                    if acceptable:
                        if not np.isfinite(since):
                            since = t
                        wait = trend_confirmation if family == 2 else confirmation
                        if t-since >= wait:
                            pending, source, pending_side, pending_qty, pending_reason = 1, i, arm, initial, 1430+family
                            pending_stop, pending_width, pending_edge, pending_center, pending_extreme = stop_price, arm_width, arm_edge, arm_center, arm_extreme
                            tc = _trace(trace, tc, i, 1, arm, family, pending_reason, parent+1, initial, arm_edge, arm_extreme, max(8.*tick, distance), stop_price, arm_center)
                            arm = stage = 0
                            since = -np.inf
                    else:
                        since = -np.inf
                else:
                    since = -np.inf
        elif not total and (not known or quiet or terminal):
            arm = stage = 0
            since = -np.inf
        assert 0 <= int(held.sum()) <= maximum <= 5
    assert int(held.sum()) == 0 and pending == 0, '場末の次正常返済原行が不足'
    return orders[:oc], trace[:tc]


def replay(data, history, config):
    """
    機能: 日経の原板と選んだ期間の公開済み帯をエピソード売買へ渡す。
    引数: data(dict)はready/quotes/features、history(ndarray)はactive140.historyのN×9、config(dict)。
    返り値: tuple[ndarray,ndarray]は十列注文と十二列判断。履歴の公開遅延は入力側で保証する。
    """
    r, q, c = data['ready'], data['quotes'], config
    assert r['symbol'] == 'NK225' and history.shape == (len(r['time_s']), 9)
    keys = ('family', 'window', 'initial', 'maximum', 'partial', 'quiet_seconds', 'confirmation',
            'trend_confirmation', 'trail_range', 'activation_r', 'add_step', 'add_interval',
            'entry_cutoff', 'spread_range', 'min_range_ticks', 'gap_seconds')
    assert 1 <= c['initial'] <= c['maximum'] <= 5 and c['family'] in (1, 2, 3)
    p = np.array([c[k] for k in keys], dtype=float)
    us_open = np.nan if r['session'].endswith('_Day') else r['us_open']
    return simulate(r['time_s'], q['bid'], q['ask'], q['quote_valid'], history,
                    r['start'], r['limit'], us_open, r['tick'], 385, p)
