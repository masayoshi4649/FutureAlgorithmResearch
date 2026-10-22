"""予定時刻と過去の進行・往復を分け、全場参加を同一の因果処理で行う。"""

import numpy as np
from numba import njit


@njit(cache=True)
def sign(value):
    """
    機能: 値の向きを買い売り対称に分類する。
    引数: value(float)は有限の差。
    返り値: intは正で1、負で−1、零で0。
    """
    return 1 if value > 0. else (-1 if value < 0. else 0)


@njit(cache=True)
def state(h, phase, selector):
    """
    機能: 当時の価格履歴と予定区分から順行又は往復を選ぶ。
    引数: h(ndarray)は公開済み履歴、phase/selector(int)は時計区分と固定比較仕様。
    返り値: intは順行1又は往復2。将来の場方向は使わない。
    """
    if selector == 0:
        return 1
    if selector == 1:
        return 2
    active = phase == 1 or phase == 3 or (phase >= 8 and phase <= 11)
    if selector == 2:
        return 1 if active else 2
    threshold = .35
    if selector == 4:
        threshold = .25 if active else .45
    coherent = h[7]*h[11] > 0.
    return 1 if h[5] >= threshold and coherent else 2


@njit(cache=True)
def simulate(times, bid, ask, qok, atr, h, market, phase, start, end, tick,
             quantity, multiplier, fee_per_contract, parameters):
    """
    機能: 追随・帯回帰・状態切替を次正常原行気配で売買し、全建玉を場内返済する。
    引数: times等(ndarray)は保存順の当時資料、start/end/tick(float)は場時刻と刻み、
          quantity(int)、multiplier/fee_per_contract(float)は数量・倍率・片道料金、
          parameters(ndarray)は選択方式、幅方式、停止幅、追尾起動、追尾幅、
          機会上限、初回参加期限秒、回帰から追随への移行、途中撤退の9指定。
    返り値: tuple[ndarray,...]は注文、完結取引、各原行の清算時価。
            原時計を実受信時計とはみなさず、ミニ・マイクロ実板は未再現。
    """
    selector, width_mode = int(parameters[0]), int(parameters[1])
    stop_multiple, trail_start, trail_width = parameters[2:5]
    per_phase, participation_seconds = int(parameters[5]), parameters[6]
    allow_conversion, withdrawal = int(parameters[7]), int(parameters[8])
    n = len(times)
    orders = np.zeros((512, 12)); trades = np.zeros((256, 17))
    curve = np.zeros((n, 5))
    oc = 0; tc = 0; entries = 0
    held = 0; entry_price = 0.; entry_row = -1; entry_fee = 0.
    risk = 0.; mode = 0; target = 0.; floor = -np.inf
    mfe = 0.; mae = 0.; failure_since = -np.inf; entry_phase = -1; entry_reason = 0
    pending = 0; source = -1; pending_side = 0; pending_risk = 0.
    pending_target = 0.; pending_mode = 0; pending_reason = 0
    arm_side = 0; arm_mode = 0; arm_extreme = 0.; arm_risk = 0.
    arm_target = 0.; arm_row = -1
    last_phase = -1; phase_entries = 0
    last_exit = -np.inf
    realized = 0.; peak = 0.; maxdd = 0.; last_bid = np.nan; last_ask = np.nan
    # ----------------------------------------
    # 発注済みを先に処理し、同じ行の新情報による遡及取消しを行わない。
    for i in range(n):
        t = times[i]
        good = qok[i] and np.isfinite(bid[i]) and np.isfinite(ask[i]) and ask[i] > bid[i] > 0.
        if not good or market[i,11] != 1. or (i > 0 and t-times[i-1] > 15.):
            failure_since = -np.inf
        if not good or (i > 0 and t-times[i-1] > 15.):
            arm_side = 0
        p = int(phase[i])
        if p != last_phase:
            last_phase = p; phase_entries = 0; arm_side = 0
        terminal = t >= end
        if terminal:
            arm_side = 0
            if pending == 1:
                pending = 0
            if held and pending != 2:
                pending = 2; source = i; pending_reason = 93
        if good:
            last_bid, last_ask = bid[i], ask[i]
            if pending and i > source:
                if pending == 2 and held:
                    fill = bid[i] if held > 0 else ask[i]
                    fee = int(quantity*fee_per_contract)
                    gross = held*(fill-entry_price)*quantity*multiplier
                    net = gross-entry_fee-fee
                    movement = held*(fill-entry_price)
                    mfe = max(mfe,movement); mae = min(mae,movement)
                    realized += gross-fee
                    orders[oc] = np.array([i,source,entries-1,-held,quantity,fill,
                                          pending_reason,0,fee,t,times[source],p]); oc += 1
                    trades[tc] = np.array([entries-1,entry_row,i,held,quantity,entry_price,fill,
                                          gross,entry_fee+fee,net,risk,mfe,mae,entry_phase,
                                          mode,entry_reason,pending_reason]); tc += 1
                    held = 0; pending = 0; last_exit = t; arm_side = 0
                elif pending == 1 and not held and not terminal:
                    held = pending_side
                    entry_price = ask[i] if held > 0 else bid[i]
                    entry_row = i; risk = pending_risk; mode = pending_mode
                    target = pending_target; floor = -stop_multiple*risk
                    mfe = 0.; mae = 0.; failure_since = -np.inf
                    entry_phase = p; entry_reason = pending_reason
                    entry_fee = int(quantity*fee_per_contract)
                    realized -= entry_fee
                    orders[oc] = np.array([i,source,entries,held,quantity,entry_price,
                                          pending_reason,1,entry_fee,t,times[source],p]); oc += 1
                    entries += 1; phase_entries += 1; pending = 0; arm_side = 0
        # ----------------------------------------
        # 返済条件は当時の清算気配で判断し、必ず後の原行で実行する。
        known = np.isfinite(h[i]).all() and np.isfinite(atr[i]) and atr[i] > 0.
        if not known:
            arm_side = 0
        current_mode = state(h[i],p,selector) if known else 0
        if held and good and not pending and not terminal:
            mark = bid[i] if held > 0 else ask[i]
            gain = held*(mark-entry_price)
            mfe = max(mfe,gain); mae = min(mae,gain)
            if allow_conversion and mode == 2 and known and current_mode == 1 and held*h[i,7] > 0.:
                mode = 1
            if mfe >= trail_start*risk:
                floor = max(floor,mfe-trail_width*risk)
            reason = 0
            if gain <= floor:
                reason = 32 if floor < 0. else 70
            elif mode == 2 and held*(mark-target) >= 0.:
                reason = 71
            if withdrawal and not reason:
                fresh = market[i,11] == 1. and np.isfinite(market[i,4:8]).all()
                adverse = fresh and held*market[i,5] < -.25 and held*market[i,7] < -.25
                if adverse and known and held*h[i,6] < 0. and gain < 0.:
                    if not np.isfinite(failure_since):
                        failure_since = t
                    if t-failure_since >= 60.:
                        reason = 75
                else:
                    failure_since = -np.inf
            if reason:
                pending = 2; source = i; pending_reason = reason
        # ----------------------------------------
        # 初回の参加期限も現在までの二市場方向だけで判定し、未来の無取引を参照しない。
        idle = not held and not pending and not terminal and t < end-600.
        if idle and good and known and t-last_exit >= 300.:
            r = max(atr[i],4.*tick)
            if width_mode:
                r = max(r,.5*(h[i,3]-h[i,4]))
            budget = ask[i]-bid[i] <= .5*r
            if entries == 0 and t >= start+participation_seconds and budget:
                direction = sign(sign(h[i,7])+sign(h[i,11])+.5*(sign(h[i,6])+sign(h[i,10])))
                if direction == 0:
                    direction = sign(h[i,7])
                if direction == 0:
                    direction = sign((bid[i]+ask[i])*.5-h[i,8])
                if direction:
                    pending = 1; source = i; pending_side = direction
                    pending_risk = r; pending_target = h[i,1]; pending_mode = 1
                    pending_reason = 82; arm_side = 0
            elif phase_entries < per_phase and budget:
                mid = (bid[i]+ask[i])*.5
                desired = 0
                if current_mode == 1:
                    direction = sign(h[i,7])
                    supported = direction*h[i,6] > 0. and direction*h[i,11] >= 0.
                    if supported and direction*(mid-h[i,0]) <= .25*r and direction*(mid-h[i,1]) >= -.25*r:
                        desired = direction
                else:
                    displacement = mid-h[i,1]
                    if abs(displacement) >= max(.75*r,h[i,2]):
                        desired = -sign(displacement)
                if arm_side and (arm_mode != current_mode or
                                 (current_mode == 1 and arm_side*h[i,7] <= 0.)):
                    arm_side = 0
                if not arm_side and desired:
                    arm_side = desired; arm_mode = current_mode; arm_risk = r
                    arm_extreme = mid; arm_target = h[i,1]; arm_row = i
                elif arm_side:
                    if arm_side > 0:
                        arm_extreme = min(arm_extreme,mid)
                    else:
                        arm_extreme = max(arm_extreme,mid)
                    bounce = arm_side*(mid-arm_extreme)
                    short_known = market[i,11] == 1. and np.isfinite(market[i,5]) and np.isfinite(market[i,7])
                    opposed = short_known and arm_side*market[i,5] < -.25 and arm_side*market[i,7] < -.25
                    reward = arm_side*(arm_target-mid)
                    permitted = arm_mode == 1 or reward >= .75*arm_risk
                    if i > arm_row and bounce >= .25*arm_risk and not opposed and permitted:
                        pending = 1; source = i; pending_side = arm_side
                        pending_risk = arm_risk; pending_target = arm_target; pending_mode = arm_mode
                        pending_reason = 80 if arm_mode == 1 else 81
                        arm_side = 0
        liquidation = 0.
        if held:
            mark = last_bid if held > 0 else last_ask
            liquidation = held*(mark-entry_price)*quantity*multiplier-int(quantity*fee_per_contract)
        equity = realized+liquidation
        peak = max(peak,equity); maxdd = max(maxdd,peak-equity)
        curve[i] = np.array([equity,held*quantity,realized,maxdd,current_mode])
        assert oc < len(orders)-2 and tc < len(trades)-1
    assert held == 0 and pending != 2
    return orders[:oc], trades[:tc], curve
