"""既存の低頻度手法を維持し、まだ参加していない場に一度だけ別建玉を持つ。"""

import numpy as np
from numba import njit


@njit(cache=True)
def direction(h, mid, style):
    """
    機能: 当時の二市場方向を単位混合なしで合議する。
    引数: h(ndarray)、mid(float)、style(int)は公開履歴、中値、方向方式。
    返り値: intは買い1・売り−1・同値0。売買反転で符号も反転する。
    """
    score = np.sign(h[7])+np.sign(h[11])+.5*(np.sign(h[6])+np.sign(h[10]))
    if style == 1:
        score = np.sign(mid-h[8])+np.sign(h[13])
        if score == 0.:
            score = np.sign(h[7])+np.sign(h[11])
    if score == 0.:
        score = h[7]
    if score == 0.:
        score = mid-h[8]
    return 1 if score > 0. else (-1 if score < 0. else 0)


@njit(cache=True)
def simulate(times, bid, ask, qok, atr, history, phase, core_starts, activation, end,
             tick, quantity, multiplier, fee_per_contract, style):
    """
    機能: 指定時刻以降、主手法が未参加なら最大一取引だけを因果的に追加する。
    引数: times等(ndarray)は原行順の過去特徴、core_starts(ndarray[int])はその行で
          約定した主手法新規数、activation/end/tick(float)は予定時刻と刻み、
          quantity(int)、multiplier/fee_per_contract(float)、style(int)は会計と方向方式。
    返り値: tuple[ndarray,...]は注文、完結親、清算時価曲線。
            将来の主手法取引を見て取消したり、終日無取引だった場を選別したりしない。
    """
    n = len(times)
    orders = np.zeros((2,12)); trades = np.zeros((1,17)); curve = np.zeros((n,5))
    held = 0; entry = 0.; row = -1; fee_in = 0.; risk = 0.
    floor = -np.inf; mfe = 0.; mae = 0.; entry_phase = -1
    pending = 0; source = -1; pending_side = 0; pending_risk = 0.; reason = 0
    core_entered = False; attempted = False; oc = 0; tc = 0
    realized = 0.; peak = 0.; dd = 0.; mark_bid = np.nan; mark_ask = np.nan
    for i in range(n):
        t = times[i]
        if core_starts[i] > 0:
            core_entered = True
        good = qok[i] and np.isfinite(bid[i]) and np.isfinite(ask[i]) and ask[i] > bid[i] > 0.
        terminal = t >= end
        if terminal:
            if pending == 1:
                pending = 0
            if held and pending != 2:
                pending = 2; source = i; reason = 93
        # ----------------------------------------
        # 後から主手法が参加しても、既に発注した追加注文は取り消さない。
        if good:
            mark_bid, mark_ask = bid[i], ask[i]
            if pending and i > source:
                fee = int(quantity*fee_per_contract)
                if pending == 1 and not terminal:
                    held = pending_side; entry = ask[i] if held > 0 else bid[i]
                    row = i; risk = pending_risk; floor = -risk
                    mfe = 0.; mae = 0.; fee_in = fee; realized -= fee
                    entry_phase = int(phase[i])
                    orders[oc] = np.array([i,source,0,held,quantity,entry,82+style,
                                          1,fee,t,times[source],phase[i]]); oc += 1
                    pending = 0
                elif pending == 2 and held:
                    fill = bid[i] if held > 0 else ask[i]
                    movement = held*(fill-entry)
                    mfe = max(mfe,movement); mae = min(mae,movement)
                    gross = movement*quantity*multiplier
                    realized += gross-fee
                    orders[oc] = np.array([i,source,0,-held,quantity,fill,reason,
                                          0,fee,t,times[source],phase[i]]); oc += 1
                    trades[tc] = np.array([0,row,i,held,quantity,entry,fill,gross,
                        fee+fee_in,gross-fee-fee_in,risk,mfe,mae,entry_phase,1,82+style,reason]); tc += 1
                    held = 0; pending = 0
        if held and good and not pending and not terminal:
            mark = bid[i] if held > 0 else ask[i]
            gain = held*(mark-entry)
            mfe = max(mfe,gain); mae = min(mae,gain)
            if mfe >= 1.5*risk:
                floor = max(floor,mfe-risk)
            if gain <= floor:
                pending = 2; source = i; reason = 32 if floor < 0. else 70
        # ----------------------------------------
        # 時間切れの強制反復をせず、一度参加したらこの担当部分を終了する。
        known = np.isfinite(history[i]).all() and np.isfinite(atr[i]) and atr[i] > 0.
        if not attempted and not core_entered and not held and not pending and good and known:
            if activation <= t < end-600.:
                r = max(atr[i],.5*(history[i,3]-history[i,4]),8.*tick)
                mid = (bid[i]+ask[i])*.5
                side = direction(history[i],mid,style)
                if side and ask[i]-bid[i] <= .5*r:
                    pending = 1; source = i; pending_side = side; pending_risk = r
                    attempted = True
        liquidation = 0.
        if held:
            mark = mark_bid if held > 0 else mark_ask
            liquidation = held*(mark-entry)*quantity*multiplier-int(quantity*fee_per_contract)
        equity = realized+liquidation
        peak = max(peak,equity); dd = max(dd,peak-equity)
        curve[i] = np.array([equity,held*quantity,realized,dd,1 if held else 0])
    assert held == 0 and pending != 2
    return orders[:oc],trades[:tc],curve
