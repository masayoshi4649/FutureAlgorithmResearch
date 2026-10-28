"""V10の確認ドテンだけに公開40分文脈を追加した第二段階対照。"""

from pathlib import Path
import sys
import numpy as np
from numba import njit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'work/tranche139_20261022'))
import early139
sys.path.insert(0, str(ROOT/'work/conditional142_20261024'))
from entry_selector142 import choose_entry, allow_add
from management_selector142 import select_from_features


def history(times, price, start, window):
    """
    機能: 確定一分終値の過去帯・効率・平均を作り、確定から60秒後に公開する。
    引数: times/price(ndarray)、start(float)、window(int)は原価格時計・中値・開始・期間。
    返り値: ndarrayは高安・効率・差5/期間・短長平均・始値・情報時刻の9列。
    """
    good = np.isfinite(price)
    ts, px = times[good], price[good]
    result = np.full((len(times), 9), np.nan)
    if not len(px):
        return result
    ends = np.arange(start+60., times[-1]+.001, 60.)
    ix = np.searchsorted(ts, ends, side='left')-1
    valid = (ix >= 0) & (ends-ts[np.maximum(ix, 0)] <= 90.)
    close = np.full(len(ends), np.nan)
    close[valid] = px[ix[valid]]
    rows = np.full((len(ends), 9), np.nan)
    for j in range(window, len(ends)):
        section = close[j-window:j+1]
        if not np.isfinite(section).all():
            continue
        path = np.abs(np.diff(section)).sum()
        rows[j] = (section.max(), section.min(), abs(section[-1]-section[0])/path if path else 0.,
                   close[j]-close[j-5], section[-1]-section[0], close[j-4:j+1].mean(),
                   section[1:].mean(), px[0], ends[j])
    selected = np.searchsorted(ends+60., times, side='right')-1
    valid = selected >= 0
    result[valid] = rows[selected[valid]]
    result[times-result[:, 8] >= 120.] = np.nan
    return result


def prepare(packet, window):
    """
    機能: 原板中値・公開済み幅・厳密過去の相手市場を接続する。
    引数: packet(dict)は一場二市場、window(int)は10/20/40分の文脈。
    返り値: dictは市場別の原行特徴。現在足・相手同時刻・未来終値を参照しない。
    """
    early = early139.prepare(packet)
    out = {}
    for key, ready in packet['inputs'].items():
        symbol = key[1]
        e = early[symbol]
        h = history(ready['time_s'], e['price'], ready['start'], window)
        atr = np.where(np.isfinite(ready['atr']), ready['atr'], 2.*e['atr'])
        risk = np.maximum(np.maximum(atr, .5*(h[:, 0]-h[:, 1])), 8.*ready['tick'])
        a = np.full((len(risk), 24), np.nan)
        a[:, :9] = h
        a[:, 9] = risk
        a[:, 10] = e['price']
        a[:, 11] = e['atr']
        a[:, 12] = early139._changes(ready['time_s'], e['price'], risk, 30.)[0]
        a[:, 13] = early139._changes(ready['time_s'], e['price'], risk, 120.)[0]
        out[symbol] = dict(ready=ready, quotes=e['quotes'], features=a)
    for symbol, data in out.items():
        peer = out['TOPIX' if symbol == 'NK225' else 'NK225']
        t, pt = data['ready']['time_s'], peer['ready']['time_s']
        ix = np.searchsorted(pt, t, side='left')-1
        safe = np.maximum(ix, 0)
        valid = (ix >= 0) & (t-pt[safe] <= 15.)
        b, a = peer['features'], data['features']
        for column, source in ((14, 3), (15, 4), (16, 2), (17, 7), (18, 9),
                               (19, 10), (20, 12), (21, 13), (23, 8)):
            a[valid, column] = b[safe[valid], source]
        a[valid, 22] = pt[safe[valid]]
    return out


def configurations():
    """
    機能: 理論別6入口・3期間と出口/投入の対照を損益を見る前に定義する。
    引数: なし。
    返り値: list[dict]は36条件。銘柄ごとの選択を許す。
    """
    names = ['帯突破の定着', '突破後の戻り再進行', '始値方向の押し戻り',
             '短長平均の方向と押し戻り', '低効率帯の端から反転', '効率による追従と反転の切替']
    result = []
    for window in (10, 20, 40):
        for mode in range(6):
            for style in (0, 1):
                result.append(dict(id=f'A{len(result)+1:02d}', name=names[mode], window=window,
                    mode=mode, initial=2, maximum=5 if style else 2, add_step=.5,
                    stop=1., activation=1.25 if style else .75, trail=.75 if style else .5,
                    hold=30., cooldown=120., ttl=1200., peer=True,
                    budget_ticks=40., loss_pause=900., loss_limit=2, quiet_seconds=900.))
    return result


@njit(cache=True)
def emit(out, count, row, source, parent, side, quantity, price, reason, new, uid, fee):
    """
    機能: 注文ごとに手数料を計上して約定列へ記録する。
    引数: out(ndarray)、count/row/source/parent/side/quantity/new/uid/fee(int)、price/reason(float)。
    返り値: intは記録後の件数。
    """
    assert count < len(out) and row > source and quantity > 0
    out[count] = np.array([row, source, parent, side, quantity, price, reason, new, uid, quantity*fee//10])
    return count+1


@njit(cache=True)
def exit_setup(risk, atr, efficiency, tick, settings):
    """
    機能: 初回判断で既知の幅だけから親内で固定する利益単位と適用可否を決める。
    引数: risk/atr/efficiency/tick(float)、settings(ndarray)。
    返り値: tuple[float,bool]は価格単位と新管理の適用可否。
    """
    known = np.isfinite(atr) and atr > 0.
    enabled = True
    if settings[10]:
        enabled = known and risk >= 2.5*max(8.*tick, atr)
    if settings[8] and efficiency >= .35:
        enabled = False
    unit = risk
    if enabled and settings[0] == 1 and known:
        unit = max(8.*tick, min(risk, 1.5*atr))
    elif enabled and settings[0] == 2:
        unit = max(8.*tick, min(risk, 16.*tick))
    return unit, enabled


@njit(cache=True)
def allow_flip40(features, side, level):
    """
    機能: 公開済み40分差と40分平均から、確認ドテンの追加制約だけを判定する。
    引数: features(ndarray)は当時の特徴、side(int)は新方向、level(float)は0/1/2。
    返り値: bool。0は元仕様、1は40分差の一致、2はさらに平均の新方向側を要求する。
    """
    if level == 0.:
        return True
    if not np.isfinite(features[4]) or side*features[4] <= 0.:
        return False
    if level == 2.:
        return np.isfinite(features[6]) and np.isfinite(features[10]) and side*(features[10]-features[6]) > 0.
    return True


@njit(cache=True)
def simulate(times, bid, ask, good, a, atr, settings, start, end, us_open, tick, multiplier, fee,
             mode, initial, maximum, add_step, stop, activation, trail, hold,
             cooldown, ttl, use_peer, budget_ticks, loss_pause, loss_limit, quiet_seconds,
             entry_end, delay=0., entry_guard=0, add_guard=0, exit_guard=0,
             flow_guard=0, evidence_hold=15., partial_exit=False, entry_policy=0, management_policy=0, add_policy=0):
    """
    機能: 当時の条件で準備・発注・返済・再準備を繰り返し、時間に依存せず保有を管理する。
    引数: 原行・特徴(ndarray)、時刻/幅/倍率等(float)、mode/initial/maximum/fee/loss_limit(int)、use_peer(bool)。
    返り値: tuple[ndarray,ndarray,ndarray]は十列約定・清算時価・判断履歴。delayは判断後の固定秒待ち。
    """
    n = len(times)
    out = np.zeros((max(1024, n//2), 10))
    equity = np.zeros(n)
    count = 0
    held = np.zeros(6, np.int64)
    entry = np.zeros(6)
    parent = -1
    side = 0
    risk = 0.
    base_price = 0.
    best = 0.
    floor = 0.
    cash = 0.
    campaign_cash = 0.
    prior_campaign_cash = 0.
    uid = 0
    pending = 0
    source = -1
    pending_side = 0
    pending_risk = 0.
    pending_qty = 0
    reason = 0
    since = -np.inf
    next_ready = start
    arm = 0
    arm_time = 0.
    arm_risk = 0.
    arm_level = 0.
    extreme = 0.
    stage = 0
    arm_mode = 0
    lost = 0
    last_add_time = -np.inf
    previous_bid = np.nan
    previous_ask = np.nan
    actual_initial_risk = 0.
    pivot = 0.
    first_low = 0.
    adverse_since = -np.inf
    partial_done = False
    selected_guard = entry_guard
    failed_by_side = np.zeros(2, np.int64)
    trace = np.zeros((max(1024,2*n), 9))
    trace_count = 0
    previous_action = -1
    last_closed_side = 0
    lot_uid = np.arange(6, dtype=np.int64)
    pending_slot = -1
    pending_close = np.zeros(6, np.int64)
    exit_risk = pending_exit_risk = 0.
    changes = pending_changes = False
    rotation = False
    rotation_anchor = rotation_extreme = 0.
    rotation_stage = 0
    rotation_since = -np.inf
    closed_context = False
    closed_profit = False
    closed_price = closed_unit = 0.
    reentry_extreme = 0.
    reentry_stage = 0
    reentry_since = -np.inf
    reentry_candidate = 0
    for i in range(n):
        t = times[i]
        valid = good[i] and np.isfinite(bid[i]) and np.isfinite(ask[i]) and 0 < bid[i] < ask[i]
        terminal = t >= end
        quiet = np.isfinite(us_open) and us_open-quiet_seconds <= t < us_open+quiet_seconds
        if valid:
            previous_bid, previous_ask = bid[i], ask[i]
        if i > 0 and t-times[i-1] > 15.:
            since = -np.inf
            adverse_since = -np.inf
            previous_action = -1
            rotation_since = reentry_since = -np.inf
        if pending and valid and i > source and t >= times[source]+delay:
            if pending in (1, 3, 6):
                price = ask[i] if pending_side > 0 else bid[i]
                if pending == 1:
                    parent += 1
                    side = pending_side
                    risk = pending_risk
                    base_price = price
                    best = 0.
                    floor = -stop*risk
                    uid = 0
                    prior_campaign_cash = cash
                    actual_initial_risk = pending_qty*stop*risk
                    adverse_since = -np.inf
                    partial_done = False
                    previous_action = -1
                    exit_risk = pending_exit_risk
                    changes = pending_changes
                    rotation = closed_context = False
                    rotation_since = reentry_since = -np.inf
                    lot_uid[:] = np.arange(6)
                else:
                    uid += 1
                slot = pending_slot if pending == 6 else uid
                assert 0 <= slot < 6 and held[slot] == 0
                held[slot] = pending_qty
                entry[slot] = price
                lot_uid[slot] = uid
                cash -= side*pending_qty*price*multiplier + pending_qty*fee//10
                count = emit(out,count,i,source,parent,side,pending_qty,price,reason,1,uid,fee)
                last_add_time = t
                if pending == 6:
                    rotation = False
                    rotation_since = -np.inf
            elif pending in (2,4,5):
                price = bid[i] if side > 0 else ask[i]
                remaining = int(held.sum()) if pending==2 else (int(pending_close.sum()) if pending==5 else max(1,int(held.sum())//2))
                for k in range(6):
                    u = 5-k if pending in (4,5) else k
                    if held[u] and remaining:
                        q = pending_close[u] if pending==5 else min(held[u],remaining)
                        if q == 0:
                            continue
                        assert 0 < q <= held[u]
                        cash += side*q*price*multiplier - q*fee//10
                        count = emit(out,count,i,source,parent,-side,q,price,reason,0,lot_uid[u],fee)
                        held[u] -= q
                        remaining -= q
                if pending==2:
                    campaign_cash = cash-prior_campaign_cash
                    lost = lost+1 if campaign_cash < 0. else 0
                    side_index = 1 if side > 0 else 0
                    if last_closed_side != side:
                        failed_by_side[:] = 0
                    failed_by_side[side_index] = failed_by_side[side_index]+1 if campaign_cash < 0. else 0
                    last_closed_side = side
                    next_ready = t+(loss_pause if lost >= loss_limit else cooldown)
                    closed_context = bool(settings[5] or settings[7])
                    closed_profit = campaign_cash > 0.
                    closed_price = reentry_extreme = price
                    closed_unit = exit_risk
                    reentry_stage = 0
                    reentry_since = -np.inf
                    reentry_candidate = 0
                    if settings[5] and closed_profit:
                        next_ready = t + settings[6]
                    arm = 0
                    since = -np.inf
                else:
                    partial_done = True
                    if pending == 5 and settings[4] and changes:
                        rotation = True
                        rotation_anchor = rotation_extreme = price
                        rotation_stage = 0
                        rotation_since = -np.inf
            pending = 0
        total = int(held.sum())
        if not valid:
            adverse_since = -np.inf
            rotation_since = reentry_since = -np.inf
        # ----------------------------------------
        # 出口は入口資料が欠測しても続ける。終了判断も次の正常気配で約定する。
        if total and not pending:
            if terminal or quiet:
                pending, source, reason = 2, i, 93 if terminal else 94
            elif valid:
                mark = bid[i] if side > 0 else ask[i]
                gain = side*(mark-base_price)
                best = max(best, gain)
                protect_unit = exit_risk if changes else risk
                protect_activation = settings[1] if changes else activation
                protect_trail = settings[2] if changes else trail
                if best >= protect_activation*protect_unit:
                    candidate_floor = best-protect_trail*protect_unit
                    if changes and settings[9] > 0.:
                        candidate_floor = max(candidate_floor, min(settings[9]*best, best-4.*tick))
                    floor = max(floor, candidate_floor)
                if gain <= floor:
                    pending, source, reason = 2, i, 70 if floor > 0. else 32
                # ----------------------------------------
                # 反転を待つ仮説の破綻は、自己と他市場の短期逆行を実時間で確認する。
                adverse = np.isfinite(a[i,12]) and np.isfinite(a[i,13]) and np.isfinite(a[i,20]) and np.isfinite(a[i,21])
                adverse = adverse and side*a[i,12] <= -.1 and side*a[i,20] <= -.1 and side*a[i,13] < 0. and side*a[i,21] < 0.
                if exit_guard == 2:
                    adverse = adverse and np.isfinite(a[i,24]) and np.isfinite(a[i,26]) and side*a[i,24] < 0. and side*a[i,26] < 0.
                if (exit_guard or management_policy) and adverse:
                    if not np.isfinite(adverse_since):
                        adverse_since = t
                    if t-adverse_since >= evidence_hold and not pending:
                        if management_policy:
                            failed_same = failed_by_side[1 if side > 0 else 0]
                            action, decision_reason = select_from_features(management_policy, side, total,
                                gain/risk, best/risk, floor/risk, partial_done, failed_same, a[i], True)
                            if action != previous_action:
                                assert trace_count < len(trace)
                                trace[trace_count] = np.array([i,2,side,action,decision_reason,parent,gain/risk,best/risk,failed_same])
                                trace_count += 1
                                previous_action = action
                            if action == 2:
                                pending, source, reason = 2, i, 1420+management_policy
                            elif action == 1 and not partial_done and total >= 2:
                                pending, source, reason = 4, i, 1430+management_policy
                        elif not partial_exit:
                            pending, source, reason = 2, i, 1411 if exit_guard == 1 else 1412
                        elif not partial_done and total>=2:
                            pending, source, reason = 4, i, 1415
                else:
                    adverse_since = -np.inf
                    previous_action = -1
        # ----------------------------------------
        # 部分利確は利益玉だけを発注時に指定する。回転玉の目標はその玉自身の建値から測る。
        if total >= 2 and valid and not pending and not terminal and not quiet and changes and settings[3] > 0.:
            mark = bid[i] if side > 0 else ask[i]
            pending_close[:] = 0
            if not partial_done and side*(mark-base_price) >= settings[3]*exit_risk:
                remain = total//2
                for j in range(6):
                    slot = 5-j
                    if held[slot] > 0 and side*(mark-entry[slot]) > 0.:
                        qty = min(held[slot], remain)
                        pending_close[slot] = qty
                        remain -= qty
            elif partial_done and settings[4] and not rotation:
                newest = -1
                newest_uid = -1
                for slot in range(6):
                    if held[slot] > 0 and lot_uid[slot] > newest_uid:
                        newest, newest_uid = slot, lot_uid[slot]
                if newest >= 0 and side*(mark-entry[newest]) >= settings[3]*exit_risk:
                    pending_close[newest] = 1
            if pending_close.sum() > 0:
                pending, source, reason = 5, i, 14510
        # ----------------------------------------
        # 同じ利確進捗の使い回しをせず、有利な押戻りと再加速を経た1枚だけを再取得する。
        if total and total < maximum and rotation and valid and not pending and t < entry_end and not quiet:
            mid = (bid[i]+ask[i])*.5
            rotation_extreme = min(rotation_extreme, mid) if side > 0 else max(rotation_extreme, mid)
            if side*(rotation_anchor-rotation_extreme) >= settings[12]*exit_risk:
                rotation_stage = 1
            support = np.isfinite(a[i,12]) and np.isfinite(a[i,13]) and side*a[i,12] > 0. and side*a[i,13] > 0.
            if settings[11]:
                support = support and np.isfinite(a[i,20]) and np.isfinite(a[i,21]) and side*a[i,20] > 0. and side*a[i,21] > 0.
                support = support and np.isfinite(a[i,24]) and np.isfinite(a[i,26]) and side*a[i,24] > 0. and side*a[i,26] >= 0.
            price = ask[i] if side > 0 else bid[i]
            trigger = rotation_stage == 1 and side*(mid-rotation_extreme) >= settings[13]*exit_risk and side*(price-rotation_anchor) <= 0.
            if trigger and support:
                if not np.isfinite(rotation_since):
                    rotation_since = t
                stop_px = base_price + side*floor
                risk_to_stop = max(tick, side*(price-stop_px))
                for slot in range(6):
                    risk_to_stop += held[slot]*max(0., side*(entry[slot]-stop_px))
                if t-rotation_since >= settings[14] and risk_to_stop <= actual_initial_risk and ask[i]-bid[i] <= .25*exit_risk:
                    pending_slot = -1
                    for slot in range(6):
                        if held[slot] == 0:
                            pending_slot = slot
                            break
                    assert pending_slot >= 0
                    pending, source, pending_qty, pending_side, reason = 6, i, 1, side, 14511
            else:
                rotation_since = -np.inf
        if total and valid and not pending and not partial_done and total < maximum and uid < 5 and t < entry_end and not quiet:
            mark = bid[i] if side > 0 else ask[i]
            support = np.isfinite(a[i,12]) and side*a[i,12] > 0.
            support = support and (not use_peer or (np.isfinite(a[i,20]) and side*a[i,20] >= 0.))
            if support and side*(mark-base_price) >= add_step*(uid+1)*risk and t-last_add_time >= 30.:
                # 全玉の現在停止線までの損失を初回と同じ予算内に収めて追加する。
                px = ask[i] if side > 0 else bid[i]
                stop_px = base_price+side*floor
                loss_to_stop = 0.
                for u in range(6):
                    loss_to_stop += held[u]*max(0., side*(entry[u]-stop_px))
                new_risk = max(tick, side*(px-stop_px))
                budget = initial*budget_ticks*tick
                if add_guard in (1, 2) or add_policy:
                    budget = actual_initial_risk
                if add_guard == 2 and floor <= 0.:
                    budget = -1.
                if add_policy and not allow_add(add_policy,a[i],side,floor):
                    budget = -1.
                if loss_to_stop+new_risk <= budget and ask[i]-bid[i] <= .25*risk:
                    pending, source, pending_qty, pending_side, reason = 3, i, 1, side, 142
        # ----------------------------------------
        # 新しい準備は未保有時だけ。先の約定や最終的な場方向で選択しない。
        known = valid and np.isfinite(a[i,:14]).all()
        known = known and (not use_peer or np.isfinite(a[i,14:24]).all())
        if not known:
            reentry_since = -np.inf
            reentry_candidate = 0
        if quiet or terminal:
            closed_context = False
            rotation = False
        # ----------------------------------------
        # 返済の約定後だけ再参加を検討する。時刻待機だけで発注せず、価格の再武装を要求する。
        if not total and not pending and known and closed_context and not terminal and not quiet and t >= next_ready and t < entry_end:
            mid = a[i,10]
            candidate = 0
            if closed_profit and settings[5]:
                reentry_extreme = min(reentry_extreme, mid) if last_closed_side > 0 else max(reentry_extreme, mid)
                if last_closed_side*(closed_price-reentry_extreme) >= settings[12]*closed_unit:
                    reentry_stage = 1
                price = ask[i] if last_closed_side > 0 else bid[i]
                supported = last_closed_side*a[i,12] > 0. and last_closed_side*a[i,13] > 0.
                if reentry_stage == 1 and last_closed_side*(mid-reentry_extreme) >= settings[13]*closed_unit and supported and last_closed_side*(price-closed_price) <= 0.:
                    candidate = last_closed_side
            if settings[7] and a.shape[1] > 30:
                opposite = -last_closed_side
                if np.isfinite(a[i,30]) and opposite*a[i,3] > 0. and opposite*a[i,13] > 0. and opposite*a[i,12] > 0. and opposite*(mid-a[i,30]) > 0.:
                    # 追加制約は確認ドテンだけ。元の入口と同方向再参加は下段へ残す。
                    if allow_flip40(a[i], opposite, settings[15]):
                        candidate = opposite
            if candidate != 0:
                if candidate != reentry_candidate or not np.isfinite(reentry_since):
                    reentry_candidate, reentry_since = candidate, t
                if t-reentry_since >= settings[14] and ask[i]-bid[i] <= .25*a[i,9]:
                    qty = min(initial, int(initial*budget_ticks*tick/(stop*a[i,9])))
                    if qty >= 1:
                        pending, source, pending_side, pending_risk, pending_qty = 1, i, candidate, a[i,9], qty
                        pending_exit_risk, pending_changes = exit_setup(pending_risk, atr[i], a[i,2], tick, settings)
                        reason = 14513 if candidate != last_closed_side else 14512
                        closed_context = False
                        arm = 0
                        since = -np.inf
            else:
                reentry_since = -np.inf
                reentry_candidate = 0
        if not total and not pending and known and not terminal and not quiet and t >= next_ready and t < entry_end:
            r = a[i,9]
            mid = a[i,10]
            if ask[i]-bid[i] > .25*r:
                arm = 0
                equity[i] = cash
                continue
            direction = 1 if a[i,4] > 0. else (-1 if a[i,4] < 0. else 0)
            peer_direction = 1 if a[i,15] > 0. else (-1 if a[i,15] < 0. else 0)
            chosen = mode
            if mode == 5:
                chosen = 1 if a[i,2] >= .35 else (4 if a[i,2] <= .2 else -1)
            if arm and (t-arm_time > ttl or chosen != arm_mode):
                arm = 0
            if not arm:
                candidate = 0
                boundary = 0.
                if chosen in (0, 1):
                    if a[i,2] >= .25:
                        if mid > a[i,0]+.05*r:
                            candidate, boundary = 1, a[i,0]
                        elif mid < a[i,1]-.05*r:
                            candidate, boundary = -1, a[i,1]
                elif chosen in (2, 3):
                    if chosen == 2:
                        candidate = 1 if mid-a[i,7] > .25*r else (-1 if mid-a[i,7] < -.25*r else 0)
                    elif a[i,2] >= .2:
                        candidate = 1 if a[i,5]-a[i,6] > .1*r else (-1 if a[i,5]-a[i,6] < -.1*r else 0)
                    boundary = mid
                elif chosen == 4 and a[i,2] <= .3:
                    if mid <= a[i,1]+.1*r:
                        candidate, boundary = 1, a[i,1]
                    elif mid >= a[i,0]-.1*r:
                        candidate, boundary = -1, a[i,0]
                if candidate and (chosen == 4 or not use_peer or candidate == peer_direction):
                    arm, arm_level, arm_risk, arm_time, extreme, stage, arm_mode = candidate, boundary, r, t, mid, 0, chosen
                    since = -np.inf
                    selected_guard = entry_guard
                    if entry_policy and chosen == 4:
                        failed_same = failed_by_side[1 if arm > 0 else 0]
                        selected_guard, decision_reason = choose_entry(entry_policy,a[i],arm,failed_same)
                        assert trace_count < len(trace)
                        trace[trace_count] = np.array([i,1,arm,selected_guard,decision_reason,parent+1,0.,0.,failed_same])
                        trace_count += 1
            if arm:
                signed = arm*(mid-arm_level)
                trigger = False
                support = arm*a[i,12] >= 0. and (not use_peer or arm*a[i,20] >= 0.)
                if chosen != 4:
                    support = support and (not use_peer or arm == peer_direction)
                if chosen == 0:
                    if signed < -.25*arm_risk:
                        arm = 0
                    else:
                        trigger = signed >= .2*arm_risk
                elif chosen == 1:
                    if signed < -.5*arm_risk:
                        arm = 0
                    elif stage == 0 and signed >= .5*arm_risk:
                        stage = 1
                    elif stage == 1 and signed <= .25*arm_risk:
                        stage, extreme = 2, mid
                    elif stage == 2:
                        extreme = min(extreme, mid) if arm > 0 else max(extreme, mid)
                        trigger = arm*(mid-extreme) >= .25*arm_risk
                elif chosen in (2, 3):
                    if stage == 0:
                        extreme = max(extreme, mid) if arm > 0 else min(extreme, mid)
                        if arm*(extreme-mid) >= .5*arm_risk:
                            stage, extreme = 1, mid
                    else:
                        extreme = min(extreme, mid) if arm > 0 else max(extreme, mid)
                        trigger = arm*(mid-extreme) >= .25*arm_risk
                    if arm*direction < 0. and a[i,2] > .35:
                        arm = 0
                elif chosen == 4:
                    extreme = min(extreme, mid) if arm > 0 else max(extreme, mid)
                    trigger = arm*(mid-extreme) >= .25*arm_risk and signed >= 0.
                    if selected_guard == 2:
                        # 最初の戻りで飛び付かず、安値切上げ/高値切下げ後の再進行を確認する。
                        trigger = False
                        if stage == 0 and arm*(mid-extreme) >= .25*arm_risk:
                            stage, first_low, pivot = 1, extreme, mid
                        elif stage == 1:
                            pivot = max(pivot, mid) if arm > 0 else min(pivot, mid)
                            if arm*(pivot-mid) >= .125*arm_risk:
                                stage, extreme = 2, mid
                        elif stage == 2:
                            extreme = min(extreme, mid) if arm > 0 else max(extreme, mid)
                            if arm*(extreme-first_low) < 2.*tick:
                                stage, extreme = 0, min(first_low, mid) if arm > 0 else max(first_low, mid)
                            else:
                                trigger = arm*(mid-extreme) >= .125*arm_risk and signed >= 0.
                        support = support and arm*a[i,13] >= 0. and (not use_peer or arm*a[i,21] >= 0.)
                    if signed < -.75*arm_risk:
                        arm = 0
                if selected_guard == 1 and arm*direction < 0. and arm*peer_direction < 0.:
                    support = False
                if flow_guard:
                    support = support and np.isfinite(a[i,24]) and np.isfinite(a[i,26]) and arm*a[i,24] > 0. and arm*a[i,26] >= 0.
                if arm and trigger and support:
                    if not np.isfinite(since):
                        since = t
                    if t-since >= hold:
                        qty = min(initial, int(initial*budget_ticks*tick/(stop*arm_risk)))
                        if qty >= 1:
                            pending, source, pending_side, pending_risk, pending_qty, reason = 1, i, arm, arm_risk, qty, 140+chosen
                            pending_exit_risk, pending_changes = exit_setup(pending_risk, atr[i], a[i,2], tick, settings)
                        arm = 0
                        since = -np.inf
                else:
                    since = -np.inf
        elif not total:
            since = -np.inf
            if not known or quiet or terminal:
                arm = 0
        if total:
            liquidation = previous_bid if side > 0 else previous_ask
            equity[i] = cash + side*total*liquidation*multiplier - sum(held)*fee/10.
        else:
            equity[i] = cash
        assert int(held.sum()) <= maximum <= 10
    return out[:count], equity, trace[:trace_count]


def replay(data, baseline_config, variation, fee10=0):
    """
    機能: 元TG04追加の昼夜別入口に、固定した利益保護・回転条件を接続する。
    引数: data/baseline_config/variation(dict)、fee10(int)は十倍手数料。
    返り値: tuple[ndarray,ndarray,ndarray]は全約定・清算時価・判断履歴。
    """
    r, q, c = data['ready'], data['quotes'], baseline_config
    keys = ('exit_unit', 'activation', 'trail', 'partial_at', 'rotate', 'reenter',
            'reentry_wait', 'flip', 'regime', 'profit_fraction', 'high_only', 'flow',
            'pullback', 'rebound', 'confirmation')
    parameters = np.array([variation[k] for k in keys]+[variation.get('flip_guard40', 0)], float)
    return simulate(r['time_s'], q['bid'], q['ask'], q['quote_valid'], data['features'],
        r['atr'], parameters, r['start'], r['limit'],
        np.nan if r['session'].endswith('_Day') else r['us_open'], r['tick'], 100., fee10,
        c['mode'], c['initial'], c['maximum'], c['add_step'], c['stop'], c['activation'],
        c['trail'], c['hold'], c['cooldown'], c['ttl'], c['peer'], c['budget_ticks'],
        c['loss_pause'], c['loss_limit'], c['quiet_seconds'], r['limit']-600., 0.,
        c.get('entry_guard', 0), c.get('add_guard', 0), c.get('exit_guard', 0),
        c.get('flow_guard', 0), c.get('evidence_hold', 15.), c.get('partial_exit', False),
        c.get('entry_policy', 0), c.get('management_policy', 0), c.get('add_policy', 0))

