"""基準価格による方向制限、追跡注文、連敗後の休止を原本順で再生する。"""

import math
import numpy as np
from numba import njit


ORDER_COLUMNS = ('約定行','判断行','取引番号','売買方向','枚数','価格','理由','新規')
TRADE_COLUMNS = ('取引番号','新規行','返済行','方向','枚数','建値','返済値','新規料金','返済料金','料金前損益','収支')
PAUSE_COLUMNS = ('行','開始0終了1','休止方式','再開方向','連敗数')
REASONS = {1:'初期損切り',2:'トレーリング返済',3:'60分返済判断',4:'場内全返済',5:'基準方向の反転',10:'方向確認の新規',11:'追跡極値からの反発新規'}


@njit(cache=True)
def historical_rows(times, reset, seconds):
    """機能: 指定秒数以前の最新観測を、リセットを跨がず求める。

    引数: times(ndarray[float])、reset(ndarray[bool])、seconds(float)。
    返り値: 過去行番号、未準備は-1(ndarray[int64])。
    """
    out = np.full(len(times), -1, dtype=np.int64)
    first = pointer = 0
    for i in range(len(times)):
        if reset[i] or (i > 0 and times[i] < times[i-1]):
            first = pointer = i
        target = times[i]-seconds
        while pointer+1 < i and times[pointer+1] <= target:
            pointer += 1
        if pointer >= first and pointer < i and times[pointer] <= target:
            out[i] = pointer
    return out


@njit(cache=True)
def make_direction(last, lag60, open_price, open_known, previous_price, previous_known, mode, band, inverse):
    """機能: 当時までに利用可能な基準と現在値から新規の許可方向を作る。

    引数: last(ndarray[float])、lag60(ndarray[int64])、価格(float)、既知開始行(int)、
    mode(int:0始値/1前場終値/2両方一致/3過去60秒)、band(float)、inverse(bool)。
    返り値: 買い1、売り-1、待機0の方向(ndarray[int8])。
    """
    out = np.zeros(len(last), dtype=np.int8)
    for i in range(len(last)):
        if i < open_known or not np.isfinite(last[i]) or last[i] <= 0:
            continue
        a = b = 0
        if np.isfinite(open_price) and open_price > 0:
            gap = last[i]-open_price
            if gap > open_price*band:
                a = 1
            elif gap < -open_price*band:
                a = -1
        if i >= previous_known and np.isfinite(previous_price) and previous_price > 0:
            gap = last[i]-previous_price
            if gap > previous_price*band:
                b = 1
            elif gap < -previous_price*band:
                b = -1
        d = a if mode == 0 else b if mode == 1 else a if mode == 2 and a == b else 0
        if mode == 3 and lag60[i] >= 0:
            ref = last[lag60[i]]
            if np.isfinite(ref) and ref > 0:
                gap = last[i]-ref
                d = 1 if gap > ref*band else -1 if gap < -ref*band else 0
        out[i] = -d if inverse else d
    return out


@njit(cache=True, nogil=True)
def simulate(times, bid, ask, quality, reset, direction, lag30, tick, start, limit,
             quantity, value, fee_unit, width, entry_width, entry_type, pause_mode,
             exit_on_reverse, hold_seconds=3600., cooldown=30., convergence_seconds=30.):
    """機能: 方向制限と追跡返済、損失回数による休止を次観測約定で再生する。

    引数: 時刻/気配(ndarray[float])、品質/reset(ndarray[bool])、direction(ndarray[int8])、
    lag30(ndarray[int64])、tick/start/limit/value/fee_unit/width/entry_width/各秒数(float)、
    quantity/entry_type/pause_mode(int)、exit_on_reverse(bool)。休止は0なし、1二敗10分、
    2二敗30分、3二敗収束、4二敗10分かつ収束、5三敗30分。
    返り値: 注文8列、決済11列、手数料後清算時価、休止5列、終端統計(tuple[ndarray,...])。
    保存末尾だから返済する処理はなく、場の予定時刻だけで返済を判断する。
    """
    n = len(times)
    capacity = max(64, int((limit-start)/max(1., cooldown))*2+32)
    orders = np.zeros((capacity, 8))
    trades = np.zeros((capacity//2+8, 11))
    pauses = np.zeros((capacity, 5))
    curve = np.zeros(n)
    oi = ti = pi = 0
    fee = math.floor(quantity*fee_unit+1e-8)
    cash = 0.
    side = pending = pending_side = 0
    pending_row = pending_reason = -1
    entry_i = cid = -1
    entry_price = peak = 0.
    parent_side = 0
    parent_i = -1
    parent_extreme = 0.
    last_exit = -1e30
    streak = 0
    paused = False
    pause_until = 0.
    pause_side = 0
    adverse_extreme = adverse_time = 0.
    pause_count = resume_count = 0
    last_bid = last_ask = 0.
    for i in range(n):
        stamp = times[i]
        qok = np.isfinite(bid[i]) and np.isfinite(ask[i]) and bid[i] > 0 and ask[i] >= bid[i]
        if qok:
            last_bid, last_ask = bid[i], ask[i]
        # ----------------------------------------
        # 前の原本行で確定した注文を、次の有効気配で執行する。
        if pending != 0 and i > pending_row and qok:
            if pending == 1:
                if stamp < limit-300.:
                    side = pending_side
                    entry_i = i
                    cid += 1
                    entry_price = ask[i] if side == 1 else bid[i]
                    peak = entry_price
                    cash -= side*quantity*entry_price*value+fee
                    orders[oi] = np.array([i,pending_row,cid,side,quantity,entry_price,pending_reason,1.])
                    oi += 1
            else:
                price = bid[i] if side == 1 else ask[i]
                gross = side*(price-entry_price)*quantity*value
                net = gross-2*fee
                cash += side*quantity*price*value-fee
                orders[oi] = np.array([i,pending_row,cid,-side,quantity,price,pending_reason,0.])
                oi += 1
                trades[ti] = np.array([cid,entry_i,i,side,quantity,entry_price,price,fee,fee,gross,net])
                ti += 1
                if net < 0:
                    streak += 1
                elif net > 0:
                    streak = 0
                threshold = 3 if pause_mode == 5 else 2
                if pause_mode != 0 and streak >= threshold:
                    paused = True
                    pause_count += 1
                    pause_until = stamp+(600. if pause_mode in (1,4) else 1800. if pause_mode in (2,5) else 0.)
                    pause_side = 0
                    adverse_time = stamp
                    pauses[pi] = np.array([i,0,pause_mode,side,streak])
                    pi += 1
                side = 0
                last_exit = stamp
            pending = 0
        # ----------------------------------------
        # 全量の実建値を基準に最初からトレールし、逆向き基準と場末も判定する。
        if side != 0 and pending == 0 and i > entry_i:
            reason = 0
            if stamp >= limit-60.:
                reason = 4
            elif stamp-times[entry_i] >= hold_seconds:
                reason = 3
            elif qok:
                quote = bid[i] if side == 1 else ask[i]
                if side*(quote-peak) > 0:
                    peak = quote
                if side*(quote-peak) <= -width+tick*1e-8:
                    reason = 1 if abs(peak-entry_price) < tick*1e-8 else 2
                elif exit_on_reverse and direction[i] == -side:
                    reason = 5
            if reason:
                pending, pending_row, pending_reason = 2, i, reason
        # ----------------------------------------
        # 休止後の逆向き極値が30秒更新されず、価格と両気配が戻った場合だけ再開する。
        if paused and side == 0 and pending == 0:
            d = int(direction[i])
            can_resume = False
            if pause_mode in (1,2,5):
                can_resume = stamp >= pause_until
            elif qok and quality[i] and not reset[i] and d != 0:
                mid = (bid[i]+ask[i])/2.
                if d != pause_side:
                    pause_side = d
                    adverse_extreme, adverse_time = mid, stamp
                elif d*(mid-adverse_extreme) < -tick*1e-8:
                    adverse_extreme, adverse_time = mid, stamp
                j = lag30[i]
                returned = (j >= 0 and d*(bid[i]-bid[j]) >= tick-tick*1e-8
                            and d*(ask[i]-ask[j]) >= tick-tick*1e-8)
                can_resume = (stamp >= pause_until and stamp-adverse_time >= convergence_seconds
                              and d*(mid-adverse_extreme) >= entry_width-tick*1e-8 and returned)
            elif reset[i] or not quality[i] or d == 0:
                pause_side = 0
                adverse_time = stamp
            if can_resume:
                pauses[pi] = np.array([i,1,pause_mode,d,streak])
                pi += 1
                paused = False
                streak = 0
                resume_count += 1
        # ----------------------------------------
        # 未成立の新規トレールは方向変更・120秒期限・品質切断で取り消す。
        if side == 0 and pending == 0 and parent_side != 0:
            if (paused or direction[i] != parent_side or reset[i] or not quality[i] or not qok
                    or stamp-times[parent_i] >= 120. or stamp >= limit-300.):
                parent_side = 0
            elif qok and quality[i] and i > parent_i:
                quote = ask[i] if parent_side == 1 else bid[i]
                if parent_side*(quote-parent_extreme) < 0:
                    parent_extreme = quote
                if parent_side*(quote-parent_extreme) >= entry_width-tick*1e-8:
                    pending, pending_row, pending_reason, pending_side = 1, i, 11, parent_side
                    parent_side = 0
        if (side == 0 and pending == 0 and parent_side == 0 and not paused and qok and quality[i]
                and not reset[i] and direction[i] != 0 and stamp >= start+300. and stamp < limit-300.
                and stamp-last_exit >= cooldown):
            if entry_type == 0:
                pending, pending_row, pending_reason, pending_side = 1, i, 10, int(direction[i])
            else:
                parent_side, parent_i = int(direction[i]), i
                parent_extreme = ask[i] if parent_side == 1 else bid[i]
        curve[i] = cash
        if side != 0:
            quote = last_bid if side == 1 else last_ask
            curve[i] += side*quantity*quote*value-fee
    stats = np.array([side,pending,parent_side,int(paused),streak,pause_count,resume_count])
    return orders[:oi],trades[:ti],curve,pauses[:pi],stats
