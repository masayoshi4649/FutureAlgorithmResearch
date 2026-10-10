"""ティック入口からIFD・IFD-OCOとトレーリング返済を原本順で再生する。"""

import math

import numpy as np
from numba import njit

ORDER_COLUMNS = ('約定行','判断行','組','売買方向','枚数','価格','理由','新規')
TRADE_COLUMNS = ('組','新規行','返済行','建玉方向','枚数','建値','返済値','新規料金','返済料金','料金前損益','収支')
REASONS = {1:'当初逆指値',2:'トレーリング返済',3:'保有期限',4:'場内返済',10:'新規逆指値',11:'新規トレール'}


@njit(cache=True)
def simulate(times, bid, ask, signal, reset, tick, start, limit, quantity, value, fee_unit,
             entry_type, entry_width, initial_stop, activation, trail_width, hold_seconds,
             parent_ttl=120., cooldown=30.):
    """機能: 前観測の条件成立を次有効原本行で執行し、全建玉の円時価を計算する。

    引数: times/bid/ask/signal/reset(ndarray)、tick/start/limit/value/fee_unit(float)、
    quantity/entry_type(int)、各価格幅・時間(float)。entry_typeは0逆指値、1トレール。
    返り値: 注文(ndarray8列)、決済(ndarray11列)、料金後清算時価(ndarray)、検査統計(ndarray)。
    子の逆指値・追跡開始価格は親予約時点の絶対価格。新規実約定後の次観測から監視する。
    """
    n = len(times)
    capacity = max(16, np.count_nonzero(signal)*2+8)
    orders = np.zeros((capacity,8))
    trades = np.zeros((capacity//2+8,11))
    curve = np.zeros(n)
    oi = ti = 0
    cash = 0.
    fee = math.floor(quantity*fee_unit+1e-8)
    side = 0
    entry_price = 0.
    entry_i = -1
    cid = -1
    parent_side = 0
    parent_row = -1
    parent_anchor = 0.
    parent_extreme = 0.
    parent_started = False
    pending = 0
    pending_row = -1
    pending_reason = 0
    child_stop = child_activation = 0.
    child_started = False
    child_extreme = 0.
    last_exit = -1e30
    last_bid = last_ask = 0.
    canceled = submitted = parent_triggers = 0
    for i in range(n):
        qok = (np.isfinite(bid[i]) and np.isfinite(ask[i]) and bid[i]>0 and ask[i]>=bid[i])
        if qok:
            last_bid,last_ask = bid[i],ask[i]
        # ----------------------------------------
        # 確定した発注は価格の戻りでは取消さない。無効気配なら次の有効観測まで待つ。
        if pending != 0 and i>pending_row and qok:
            if pending == 1:
                if times[i]>=limit-300.:
                    canceled += 1
                    side = 0
                else:
                    side = parent_side
                    cid += 1
                    entry_price = ask[i] if side==1 else bid[i]
                    entry_i = i
                    cash -= side*quantity*entry_price*value+fee
                    orders[oi] = np.array([i,pending_row,cid,side,quantity,entry_price,pending_reason,1.])
                    oi += 1
                    # 子の価格は親予約時の値を維持。実建値から再計算しない。
                    child_stop = parent_anchor-side*initial_stop*tick
                    child_activation = parent_anchor+side*activation*tick
                    child_started = False
                    child_extreme = 0.
                parent_side = 0
            else:
                out = bid[i] if side==1 else ask[i]
                gross = side*(out-entry_price)*quantity*value
                net = gross-2*fee
                cash += side*quantity*out*value-fee
                orders[oi] = np.array([i,pending_row,cid,-side,quantity,out,pending_reason,0.])
                oi += 1
                trades[ti] = np.array([cid,entry_i,i,side,quantity,entry_price,out,fee,fee,gross,net])
                ti += 1
                side = 0
                last_exit = times[i]
            pending = 0
        # ----------------------------------------
        # 子は約定行に遡らず、次PUSHの気配から追跡を開始する。
        if side != 0 and pending==0 and i>entry_i:
            reason = 0
            if times[i]>=limit-60.:
                reason = 4
            elif times[i]-times[entry_i]>=hold_seconds:
                reason = 3
            elif qok:
                close_quote = bid[i] if side==1 else ask[i]
                if initial_stop>0 and side*(close_quote-child_stop)<=0:
                    reason = 1
                else:
                    if not child_started and (activation==0 or side*(close_quote-child_activation)>=0):
                        child_started = True
                        child_extreme = close_quote
                    if child_started:
                        if side*(close_quote-child_extreme)>0:
                            child_extreme = close_quote
                        if side*(close_quote-child_extreme)<=-trail_width*tick:
                            reason = 2
            if reason != 0:
                pending,pending_row,pending_reason = 2,i,reason
        # ----------------------------------------
        # 未成立の親予約は期限・場末・品質リセットで取り消す。
        if side==0 and pending==0 and parent_side!=0:
            if times[i]-times[parent_row]>=parent_ttl or times[i]>=limit-300. or reset[i]:
                parent_side = 0
                canceled += 1
            elif qok and i>parent_row:
                quote = ask[i] if parent_side==1 else bid[i]
                trigger = False
                if entry_type==0:
                    trigger = parent_side*(quote-parent_anchor)>=0
                else:
                    if not parent_started:
                        parent_started = True
                        parent_extreme = quote
                    if parent_side*(quote-parent_extreme)<0:
                        parent_extreme = quote
                    trigger = parent_side*(quote-parent_extreme)>=entry_width*tick
                if trigger:
                    pending,pending_row,pending_reason = 1,i,10+entry_type
                    parent_triggers += 1
        # ----------------------------------------
        # 同じ観測で親を作って成立させない。予約中・保有中の別信号は重ねない。
        if side==0 and pending==0 and parent_side==0 and qok and not reset[i] and signal[i]!=0:
            if times[i]>=start+300. and times[i]<limit-300. and times[i]-last_exit>=cooldown:
                parent_side = int(signal[i])
                parent_row = i
                parent_anchor = ask[i] if parent_side==1 else bid[i]
                parent_started = False
                submitted += 1
        curve[i] = cash
        if side!=0:
            liquidation = last_bid if side==1 else last_ask
            curve[i] += side*quantity*liquidation*value
    return orders[:oi],trades[:ti],curve,np.array([side,pending,parent_side,submitted,parent_triggers,canceled])
