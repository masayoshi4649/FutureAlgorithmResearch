"""活動待ちで見送った最初の候補より不利な判断価格を追わない。"""

import numpy as np
from numba import njit

ORDER_COLUMNS = ("約定原行", "判断原行", "組番号", "注文方向", "枚数", "約定値", "理由", "新規")
TRADE_COLUMNS = ("新規原行", "返済原行", "建方向", "枚数", "建値", "返済値",
                 "粗収支", "料金", "差引収支", "最大順行", "最大逆行", "幅", "出口理由", "入口型", "親番号")


@njit(cache=True)
def simulate(times, prices, bid, ask, qok, atrs, history, market, start, end,
             us_open, tick, quantity, multiplier, fee_tenths, parameters, retest_mode=0, exit_style=0,
             activity=None, activity_mode=0, budget_mode=0):
    """
    機能: 旧入口又は突破後の再試験で判断し、次正常原行へ注文を予約する。
    引数: 原行列・history/market/parameters(ndarray)、時計/刻み/倍率(float)、数量/料率(int)、
          retest_mode(int)は0で旧入口、1で再試験。exit_style(int)は0旧出口、1連続床、2部分返済、3両方。
          activity(None又はndarray[N,4])は中値差・正出来高増分・符号付き増分・既知。
          activity_mode(int)は0で厳密旧互換、1で価格応答と逆向き代理量を必須とする。
          budget_mode(int)は0で活動入口互換、1で最初に見送った判断BBOの方向別予算を保持する。
    返り値: tuple[ndarray,...]は注文、完結取引、全行時価。判断価格での約定保証は置かない。
    """
    mode, stop, activation, trail, phase, cooldown, bounce, buffer, efficiency, distance = parameters[:10]
    entry_confirm, exit_mode, rearm = parameters[10:13]
    maximum_extension = parameters[13]
    assert retest_mode == 0 or retest_mode == 1
    assert retest_mode == 0 or (mode == 2. and rearm == 0.)
    assert (entry_confirm != 4. and entry_confirm != 5. and entry_confirm != 6.) or retest_mode == 1
    assert exit_style >= 0 and exit_style <= 3
    n = len(times)
    assert activity_mode == 0 or activity_mode == 1
    assert budget_mode == 0 or budget_mode == 1
    assert budget_mode == 0 or activity_mode == 1
    if activity_mode == 1:
        assert activity is not None
        assert activity.shape[0] == n and activity.shape[1] == 4
    orders = np.zeros((n, 8))
    trades = np.zeros((n, 15))
    curve = np.zeros((n, 4))
    oc = 0
    tc = 0
    parent_count = 0
    active_parent = -1
    held = 0
    pending_quantity = 0
    entry_fee_total = 0
    entry_fee_remaining = 0
    parent_net = 0.
    partial_done = False
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
    budget_quote = np.full(2, np.nan)
    budget_level = np.zeros(2)
    budget_width = np.zeros(2)
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
    retest_stage = 0
    progress_row = -1
    return_row = -1
    return_extreme = 0.
    for i in range(n):
        t = times[i]
        good = qok[i] and np.isfinite(bid[i]) and np.isfinite(ask[i]) and 0 < bid[i] < ask[i]
        quiet = np.isfinite(us_open) and us_open-buffer <= t < us_open+buffer
        terminal = t >= end
        if budget_mode == 1:
            # ----------------------------------------
            # 保存境界の破綻は自己の有限価格だけで解除する。既発注の予約には触れない。
            for budget_slot in range(2):
                budget_side = 1 if budget_slot == 0 else -1
                expired = quiet or terminal
                if np.isfinite(budget_quote[budget_slot]) and np.isfinite(prices[i]):
                    expired = expired or budget_side*(prices[i]-budget_level[budget_slot]) <= -.25*budget_width[budget_slot]
                if expired:
                    budget_quote[budget_slot] = np.nan
                    budget_level[budget_slot] = 0.
                    budget_width[budget_slot] = 0.
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
                held = quantity
                active_parent = parent_count
                parent_count += 1
                partial_done = False
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
                entry_fee_total = one_fee
                entry_fee_remaining = one_fee
                parent_net = -float(one_fee)
                orders[oc] = np.array([i, pending_source, active_parent, position, quantity, entry, 1., 1.])
                oc += 1
            else:
                fill = bid[i] if position > 0 else ask[i]
                peak = max(peak, position*(fill-entry))
                adverse = min(adverse, position*(fill-entry))
                closed = min(held, pending_quantity)
                assert closed > 0
                gross = position * (fill-entry) * closed * multiplier
                one_fee = closed * fee_tenths // 10
                assigned = entry_fee_remaining if closed == held else entry_fee_total * closed // quantity
                entry_fee_remaining -= assigned
                cash += gross - one_fee
                parent_net += gross - one_fee
                fees += one_fee
                orders[oc] = np.array([i, pending_source, active_parent, -position, closed, fill, pending_reason, 0.])
                oc += 1
                trade_fee = assigned + one_fee
                trades[tc] = np.array([entry_row,i,position,closed,entry,fill,gross,
                    trade_fee,gross-trade_fee,peak,adverse,width,pending_reason,entry_mode,active_parent])
                tc += 1
                held -= closed
                if held == 0:
                    if parent_net < 0. and rearm > 0.:
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
            if exit_style == 1 or exit_style == 3:
                # 起動前に損失床を据え置かず順行に応じて上げる。1Rでの0.25R上昇は残る。
                floor = max(floor, peak-stop*width)
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
                pending_quantity = held
            elif not pending and (exit_style == 2 or exit_style == 3) and not partial_done:
                # 全返済の条件が先。半分の利益を残し、残玉には従来の出口を継続する。
                if quantity >= 2 and peak >= .5*width and movement <= peak-.25*width:
                    pending = -position
                    pending_source = i
                    pending_reason = 76
                    pending_quantity = quantity // 2
                    partial_done = True
        # ----------------------------------------
        # 入り直しの条件はその時までの資料から再形成。上昇・下落の未来分類は使わない。
        if not position and not pending and t >= ready_after and not quiet and not terminal and good:
            # 再試験の境界破綻は、相手資料や現在ATRが欠けても観測済み自己価格だけで取消す。
            if retest_mode == 1 and arm and np.isfinite(prices[i]):
                if arm*(prices[i]-arm_level) <= -.25*arm_width:
                    arm = 0
            known = np.isfinite(prices[i]) and np.isfinite(atrs[i]) and atrs[i] > 0.
            known = known and np.isfinite(history[i, :]).all() and market[i,11] == 1.
            if retest_mode == 1 and (entry_confirm == 4. or entry_confirm == 5. or entry_confirm == 6.):
                known = known and np.isfinite(market[i,4]) and np.isfinite(market[i,6])
            else:
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
                        retest_stage = 0
                        progress_row = -1
                        return_row = -1
                        return_extreme = prices[i]
                        if retest_mode == 1 and arm_mode == 2:
                            if arm*(prices[i]-arm_level) >= .75*arm_width:
                                retest_stage = 1
                                progress_row = i
                elif arm:
                    support = arm*market[i,4] > 0. and arm*market[i,6] > 0.
                    trigger = False
                    if arm_mode == 1:
                        # 越えた境界が固定されたまま、内側へ戻り相手も向き直した時だけ。
                        trigger = arm*(prices[i]-arm_level) >= 0. and support and arm*history[i,10] >= 0.
                        quoted_entry = ask[i] if arm > 0 else bid[i]
                        trigger = trigger and arm*(history[i,1]-quoted_entry) >= max(arm_width,4.*spread)
                    elif arm_mode == 2:
                        if retest_mode == 0:
                            if arm*(prices[i]-arm_level) < -.25*arm_width:
                                arm = 0
                            else:
                                trigger = t-arm_time >= 60. and support and arm*(prices[i]-arm_level) >= .25*arm_width
                        else:
                            # ----------------------------------------
                            # 固定線を一度離れ、後の原行で戻り、さらに別の原行で再進行を観測する。
                            advance = arm*(prices[i]-arm_level)
                            if advance <= -.25*arm_width:
                                arm = 0
                            elif retest_stage == 0:
                                if advance >= .75*arm_width:
                                    retest_stage = 1
                                    progress_row = i
                            elif retest_stage == 1:
                                if i > progress_row and advance <= .25*arm_width:
                                    retest_stage = 2
                                    return_row = i
                                    return_extreme = prices[i]
                            else:
                                if arm*(prices[i]-return_extreme) < 0.:
                                    return_extreme = prices[i]
                                trigger = i > return_row and t-arm_time >= 60. and support
                                trigger = trigger and arm*(prices[i]-return_extreme) >= .25*arm_width
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
                        if entry_confirm >= 1. and entry_confirm != 4. and entry_confirm != 5. and entry_confirm != 6.:
                            trigger = arm*market[i,5] > .05 and arm*market[i,7] > .05
                        if entry_confirm == 2.:
                            trigger = trigger and arm*history[i,6] > 0. and arm*history[i,7] > 0.
                            trigger = trigger and arm*history[i,10] > 0. and arm*history[i,11] > 0.
                        elif entry_confirm == 3. or entry_confirm == 4. or entry_confirm == 5. or entry_confirm == 6.:
                            trigger = trigger and arm*history[i,10] > 0. and arm*history[i,11] > 0.
                        # 確認5は既知の両120秒強逆流だけを拒否。未知を支持や反対へ補完しない。
                        if (entry_confirm == 5. or entry_confirm == 6.) and np.isfinite(market[i,5]) and np.isfinite(market[i,7]):
                            if arm*market[i,5] < -.25 and arm*market[i,7] < -.25:
                                if entry_confirm == 6. and trigger and quote_ok and arm_mode == 2:
                                    quoted_candidate = ask[i] if arm > 0 else bid[i]
                                    if arm*(quoted_candidate-arm_level) <= maximum_extension*arm_width:
                                        # 発注資格の揃った候補だけ破棄。次行の新準備は全段階をやり直す。
                                        arm = 0
                                        retest_stage = 0
                                        progress_row = -1
                                        return_row = -1
                                        return_extreme = 0.
                                trigger = False
                        slot = 0 if arm > 0 else 1
                        if np.isfinite(failed_price[slot]):
                            renewed = arm*(prices[i]-failed_price[slot]) >= .5*failed_width[slot]
                            renewed = renewed and arm*market[i,5] > .05 and arm*market[i,7] > .05
                            if renewed:
                                failed_price[slot] = np.nan
                            else:
                                trigger = False
                    if arm and trigger and arm_mode == 2:
                        quoted_entry = ask[i] if arm > 0 else bid[i]
                        trigger = arm*(quoted_entry-arm_level) <= maximum_extension*arm_width
                    if arm and trigger and quote_ok and budget_mode == 1:
                        # ----------------------------------------
                        # 資格の揃った候補だけを比較する。好条件と等値は許し、保存価格は更新しない。
                        budget_slot = 0 if arm > 0 else 1
                        current_quote = ask[i] if arm > 0 else bid[i]
                        if np.isfinite(budget_quote[budget_slot]) and arm*(current_quote-budget_quote[budget_slot]) > 0.:
                            arm = 0
                            arm_level = 0.
                            arm_width = 0.
                            arm_extreme = 0.
                            arm_mode = 0
                            arm_time = 0.
                            pullback = False
                            retest_stage = 0
                            progress_row = -1
                            return_row = -1
                            return_extreme = 0.
                    if arm and trigger and quote_ok and activity_mode == 1 and activity is not None:
                        # ----------------------------------------
                        # 旧発注資格の揃った当行だけで確認し、未知・不適格なら全準備を捨てる。
                        activity_ok = activity[i, 3] == 1. and np.isfinite(activity[i, :3]).all()
                        activity_ok = activity_ok and arm*activity[i, 0] > 0.
                        activity_ok = activity_ok and activity[i, 1] > 0. and arm*activity[i, 2] < 0.
                        if not activity_ok:
                            if budget_mode == 1:
                                budget_slot = 0 if arm > 0 else 1
                                if not np.isfinite(budget_quote[budget_slot]):
                                    budget_quote[budget_slot] = ask[i] if arm > 0 else bid[i]
                                    budget_level[budget_slot] = arm_level
                                    budget_width[budget_slot] = arm_width
                            arm = 0
                            arm_level = 0.
                            arm_width = 0.
                            arm_extreme = 0.
                            arm_mode = 0
                            arm_time = 0.
                            pullback = False
                            retest_stage = 0
                            progress_row = -1
                            return_row = -1
                            return_extreme = 0.
                    if arm and trigger and quote_ok:
                        pending = arm
                        pending_quantity = quantity
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
            unrealized = position * (mark-entry) * held * multiplier
        curve[i] = np.array([cash+unrealized, position*held, fees, cash])
    assert position == 0 and pending == 0 and held == 0 and entry_fee_remaining == 0
    return orders[:oc], trades[:tc], curve
