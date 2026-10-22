"""夜間専用の帯外進行・抜け失敗・押し戻りを扱う注文状態機械。"""

import numpy as np
from numba import njit

ORDER_COLUMNS = ("約定原行", "判断原行", "組番号", "注文方向", "枚数", "約定値", "理由", "新規")
TRADE_COLUMNS = ("新規原行", "返済原行", "建方向", "枚数", "建値", "返済値",
                 "粗収支", "料金", "差引収支", "最大順行", "最大逆行", "幅", "出口理由", "入口型")


@njit(cache=True)
def simulate(times, prices, bid, ask, qok, atrs, history, market, start, end,
             us_open, tick, quantity, multiplier, fee_tenths, parameters):
    """
    機能: 夜間の対称状態機械で判断し、次正常原行へ成行を予約する。
    引数: 原行列・history/market/parameters(ndarray)、時計/刻み/倍率(float)、数量/料率(int)。
    返り値: tuple[ndarray,...]は注文、完結取引、全行時価。判断価格での約定保証は置かない。
    """
    mode, stop, activation, trail, phase, cooldown, bounce, buffer, efficiency, distance = parameters[:10]
    entry_confirm, exit_mode, rearm = parameters[10:13]
    n = len(times)
    orders = np.zeros((n, 8))
    trades = np.zeros((n, 14))
    curve = np.zeros((n, 4))
    oc = 0
    tc = 0
    position = 0
    pending = 0
    pending_source = -1
    pending_reason = 0
    pending_width = 0.
    pending_mode = 0
    entry = 0.
    entry_row = -1
    width = 0.
    peak = 0.
    adverse = 0.
    floor = -np.inf
    entry_mode = 0
    entry_boundary = 0.
    pending_boundary = 0.
    failed_price = np.full(2, np.nan)
    failed_width = np.zeros(2)
    cash = 0.
    fees = 0.
    ready_after = start
    last_good_bid = np.nan
    last_good_ask = np.nan
    arm = 0
    arm_level = 0.
    arm_width = 0.
    arm_extreme = 0.
    arm_mode = 0
    arm_time = 0.
    pullback = False
    for i in range(n):
        t = times[i]
        good = qok[i] and np.isfinite(bid[i]) and np.isfinite(ask[i]) and 0 < bid[i] < ask[i]
        quiet = np.isfinite(us_open) and us_open-buffer <= t < us_open+buffer
        terminal = t >= end
        if (quiet or terminal) and not position:
            pending = 0
        if good:
            last_good_bid = bid[i]
            last_good_ask = ask[i]
        # ----------------------------------------
        # 前行で成立した注文を先に実行する。当行の不都合で約定を取消さない。
        if pending and good and i > pending_source:
            if position == 0:
                position = pending
                entry = ask[i] if position > 0 else bid[i]
                width = pending_width
                entry_mode = pending_mode
                entry_boundary = pending_boundary
                entry_row = i
                peak = 0.
                adverse = 0.
                floor = -stop * width
                one_fee = quantity * fee_tenths // 10
                cash -= one_fee
                fees += one_fee
                orders[oc] = np.array([i, pending_source, tc, position, quantity, entry, 1., 1.])
                oc += 1
            else:
                fill = bid[i] if position > 0 else ask[i]
                peak = max(peak, position*(fill-entry))
                adverse = min(adverse, position*(fill-entry))
                gross = position * (fill-entry) * quantity * multiplier
                one_fee = quantity * fee_tenths // 10
                cash += gross - one_fee
                fees += one_fee
                orders[oc] = np.array([i, pending_source, tc, -position, quantity, fill, pending_reason, 0.])
                oc += 1
                trades[tc] = np.array([entry_row,i,position,quantity,entry,fill,gross,
                    2*one_fee,gross-2*one_fee,peak,adverse,width,pending_reason,entry_mode])
                tc += 1
                if gross-2*one_fee < 0. and rearm > 0.:
                    slot = 0 if position > 0 else 1
                    failed_price[slot] = entry
                    failed_width[slot] = width
                position = 0
                ready_after = t + cooldown
                arm = 0
            pending = 0
        if position and good:
            mark = bid[i] if position > 0 else ask[i]
            movement = position * (mark-entry)
            peak = max(peak, movement)
            adverse = min(adverse, movement)
            if peak >= activation*width:
                floor = max(floor, peak-trail*width)
            reason = 0
            if terminal:
                reason = 93
            elif quiet:
                reason = 94
            elif movement <= floor:
                reason = 32 if floor < 0. else 70
            elif entry_mode == 1 and np.isfinite(history[i,1]) and position*(prices[i]-history[i,1]) >= 0.:
                reason = 71
            # 撤退は正常な小押しではなく、両市場が二分で元方向の逆に進む時に限定。
            elif entry_mode != 1 and market[i,11] == 1.:
                opposite = position*market[i,5] < -.25 and position*market[i,7] < -.25
                if exit_mode == 0. and opposite and movement < .5*width:
                    reason = 72
                elif exit_mode == 2. and np.isfinite(history[i,11]):
                    if position*(prices[i]-entry_boundary) < -.25*width and position*history[i,11] < 0.:
                        reason = 72
            if reason and not pending:
                pending = -position
                pending_source = i
                pending_reason = reason
        # ----------------------------------------
        # 入り直しの条件はその時までの資料から再形成。上昇・下落の未来分類は使わない。
        if not position and not pending and t >= ready_after and not quiet and not terminal and good:
            known = np.isfinite(prices[i]) and np.isfinite(atrs[i]) and atrs[i] > 0.
            known = known and np.isfinite(history[i, :]).all() and market[i,11] == 1.
            known = known and np.isfinite(market[i,4:8]).all()
            allowed_phase = not (phase == 1. and t < us_open+1200.)
            allowed_phase = allowed_phase and not (phase == 2. and t >= us_open-buffer)
            # 米開始後の判定は、開始後だけの20分以上の観測を待つ。
            allowed_phase = allowed_phase and not (us_open+buffer <= t < us_open+1320.)
            if known and allowed_phase:
                w = max(atrs[i], 4.*tick)
                spread = ask[i]-bid[i]
                quote_ok = spread <= .25*w and max(ask[i]-prices[i], prices[i]-bid[i]) <= .5*w
                selected = int(mode)
                if mode == 4.:
                    selected = 1 if t < us_open else 2
                elif mode == 5.:
                    selected = 1 if t < us_open else 3
                elif mode == 6.:
                    selected = 1 if history[i,5] < .3 else 2 if history[i,5] >= .45 else 0
                if arm and (selected != arm_mode or t-arm_time > 1800.):
                    arm = 0
                if not arm and quote_ok:
                    if selected == 1:
                        if prices[i] > history[i,3] + distance*w:
                            arm = -1
                            arm_level = history[i,3]
                        elif prices[i] < history[i,4] - distance*w:
                            arm = 1
                            arm_level = history[i,4]
                    elif selected == 2 and history[i,5] >= efficiency:
                        if prices[i] > history[i,3] and history[i,10] > 0. and history[i,11] > 0.:
                            arm = 1
                            arm_level = history[i,3]
                        elif prices[i] < history[i,4] and history[i,10] < 0. and history[i,11] < 0.:
                            arm = -1
                            arm_level = history[i,4]
                    elif selected == 3:
                        if prices[i] > history[i,1] and history[i,6] > 0. and history[i,10] > 0.:
                            arm = 1
                        elif prices[i] < history[i,1] and history[i,6] < 0. and history[i,10] < 0.:
                            arm = -1
                        arm_level = prices[i]
                    if arm:
                        arm_mode = selected
                        arm_width = w
                        arm_extreme = prices[i]
                        arm_time = t
                        pullback = False
                elif arm:
                    support = arm*market[i,4] > 0. and arm*market[i,6] > 0.
                    trigger = False
                    if arm_mode == 1:
                        # 越えた境界が固定されたまま、内側へ戻り相手も向き直した時だけ。
                        trigger = arm*(prices[i]-arm_level) >= 0. and support and arm*history[i,10] >= 0.
                        quoted_entry = ask[i] if arm > 0 else bid[i]
                        trigger = trigger and arm*(history[i,1]-quoted_entry) >= max(arm_width,4.*spread)
                    elif arm_mode == 2:
                        if arm*(prices[i]-arm_level) < -.25*arm_width:
                            arm = 0
                        else:
                            trigger = t-arm_time >= 60. and support and arm*(prices[i]-arm_level) >= .25*arm_width
                    elif arm_mode == 3:
                        if not pullback:
                            if arm*(prices[i]-arm_extreme) > 0.:
                                arm_extreme = prices[i]
                            if arm*(prices[i]-arm_extreme) <= -.5*arm_width:
                                pullback = True
                                arm_extreme = prices[i]
                        else:
                            if arm*(prices[i]-arm_extreme) < 0.:
                                arm_extreme = prices[i]
                            trigger = arm*(prices[i]-arm_extreme) >= bounce*arm_width and support
                            trigger = trigger and arm*(prices[i]-history[i,1]) > 0.
                    if arm and trigger:
                        if entry_confirm >= 1.:
                            trigger = arm*market[i,5] > .05 and arm*market[i,7] > .05
                        if entry_confirm == 2.:
                            trigger = trigger and arm*history[i,6] > 0. and arm*history[i,7] > 0.
                            trigger = trigger and arm*history[i,10] > 0. and arm*history[i,11] > 0.
                        slot = 0 if arm > 0 else 1
                        if np.isfinite(failed_price[slot]):
                            renewed = arm*(prices[i]-failed_price[slot]) >= .5*failed_width[slot]
                            renewed = renewed and arm*market[i,5] > .05 and arm*market[i,7] > .05
                            if renewed:
                                failed_price[slot] = np.nan
                            else:
                                trigger = False
                    if arm and trigger and quote_ok:
                        pending = arm
                        pending_source = i
                        pending_width = arm_width
                        pending_mode = arm_mode
                        pending_boundary = arm_level
                        arm = 0
        if quiet or terminal:
            arm = 0
        unrealized = 0.
        if position:
            mark = last_good_bid if position > 0 else last_good_ask
            unrealized = position * (mark-entry) * quantity * multiplier
        curve[i] = np.array([cash+unrealized, position*quantity, fees, cash])
    assert position == 0 and pending == 0
    return orders[:oc], trades[:tc], curve
