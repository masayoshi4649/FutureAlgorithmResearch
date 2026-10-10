"""中値の価格イベントと表示補充から、反転・再開・突破の仮説を順番に判定する。"""

from __future__ import annotations

import numpy as np
from numba import njit


SIGNAL_META = [
    dict(id='T1L0', family='中値往復の反転', strength='標準', impulse=4, confirmation=2,
         description='中値が4呼値進み、両気配を伴って2呼値戻ったら、戻る方向を候補にする。'),
    dict(id='T1L1', family='中値往復の反転', strength='強め', impulse=8, confirmation=4,
         description='中値が8呼値進み、両気配を伴って4呼値戻ったら、戻る方向を候補にする。'),
    dict(id='T2L0', family='押し戻し後の再開', strength='標準', impulse=4, confirmation=2,
         description='4呼値の伸びの途中で2呼値押し、局所極値から2呼値戻って元の極値に近づいたら、元方向を候補にする。'),
    dict(id='T2L1', family='押し戻し後の再開', strength='強め', impulse=8, confirmation=4,
         description='8呼値の伸びの途中で4呼値押し、局所極値から4呼値戻って元の極値に近づいたら、元方向を候補にする。'),
    dict(id='T3L0', family='表示補充後の反転', strength='標準', impulse=2, confirmation=2, refill_ratio=.5,
         description='近くの板が最良量の0.5倍以上回復し、直前の2呼値以上の進行が止まり、両気配を伴って2呼値戻ったら反転候補にする。'),
    dict(id='T3L1', family='表示補充後の反転', strength='強め', impulse=4, confirmation=4, refill_ratio=1.,
         description='近くの板が最良量の1倍以上回復し、直前の4呼値以上の進行が止まり、両気配を伴って4呼値戻ったら反転候補にする。'),
    dict(id='T4L0', family='表示補充価格の突破', strength='標準', confirmation=2, refill_ratio=.5,
         description='近くの補充価格を2呼値越え、両気配も2呼値進み、直近16中値イベント区間のOFIが同方向なら継続候補にする。'),
    dict(id='T4L1', family='表示補充価格の突破', strength='強め', confirmation=4, refill_ratio=1.,
         description='近くの補充価格を4呼値越え、両気配も4呼値進み、直近16中値イベント区間のOFIが同方向なら継続候補にする。'),
]


@njit(cache=True)
def candidate_signals(bid, ask, bq, aq, best_ofi, valid, reset, time_s,
                      events_i, events_side, events_qty, events_bestqty, events_price,
                      tick, start):
    """機能: 原本順に一度ずつ処理し、中値が変わった行だけで8種類の候補を作る。

    引数: bid/ask/bq/aq/best_ofi/time_s(ndarray[float])、valid/reset(ndarray[bool])、
    events_i/side/qty/bestqty/price(ndarray)、tick/start(float)。
    返り値: 8系列×原本行の候補方向(ndarray[int8])。1は買い、-1は売り、0は候補なし。
    表示補充は真の約定吸収・注文取消を識別した証拠ではない。同行の観測後に判断する。
    """
    n = len(bid)
    output = np.zeros((8, n), dtype=np.int8)
    # ----------------------------------------
    # 反転と再開は同じ呼値尺度を用いるが、独立した状態を持つ。
    direction = np.zeros((2, 2), dtype=np.int8)
    low = np.zeros((2, 2))
    high = np.zeros((2, 2))
    low_time = np.zeros((2, 2))
    high_time = np.zeros((2, 2))
    origin = np.zeros((2, 2))
    origin_time = np.zeros((2, 2))
    extreme = np.zeros((2, 2))
    extreme_bid = np.zeros((2, 2))
    extreme_ask = np.zeros((2, 2))
    pull_active = np.zeros(2, dtype=np.bool_)
    pull_extreme = np.zeros(2)
    pull_bid = np.zeros(2)
    pull_ask = np.zeros(2)
    resume_used = np.zeros(2, dtype=np.bool_)
    # ----------------------------------------
    # 価格イベントの履歴を保存する。原本行数をティック数として使わない。
    ring_mid = np.zeros(17)
    ring_time = np.zeros(17)
    ring_ofi = np.zeros(17)
    event_count = 0
    cumulative_ofi = 0.
    # ----------------------------------------
    # 補充の最初の適格完了を基準として固定し、同価格の後続補充で時刻を延長しない。
    active = np.zeros((2, 2, 2), dtype=np.bool_)
    refill_price = np.zeros((2, 2, 2))
    refill_mid = np.zeros((2, 2, 2))
    refill_bid = np.zeros((2, 2, 2))
    refill_ask = np.zeros((2, 2, 2))
    refill_time = np.zeros((2, 2, 2))
    refill_max = np.zeros((2, 2, 2))
    pointer = 0
    previous_mid = np.nan
    previous_time = np.nan
    seeded = False
    epsilon = max(1e-10, tick * 1e-7)
    for i in range(n):
        stamp = time_s[i]
        mid = (bid[i] + ask[i]) / 2.
        quality = (valid[i] and np.isfinite(mid) and tick > 0. and bq[i] > 0. and aq[i] > 0.
                   and ask[i] > bid[i] and ask[i] - bid[i] <= 2. * tick + epsilon)
        broken = (reset[i] or not quality or (np.isfinite(previous_time)
                  and (stamp < previous_time or stamp - previous_time > 120.)))
        if broken:
            direction[:, :] = 0
            pull_active[:] = False
            resume_used[:] = False
            active[:, :, :] = False
            event_count = 0
            cumulative_ofi = 0.
            previous_mid = np.nan
            seeded = False
        # 無効な行の補充イベントは消費だけを行い、状態へ残さない。
        if not quality or broken:
            while pointer < len(events_i) and events_i[pointer] <= i:
                pointer += 1
            previous_time = stamp
            continue
        if not seeded:
            for family in range(2):
                for level in range(2):
                    low[family, level] = high[family, level] = mid
                    low_time[family, level] = high_time[family, level] = stamp
            previous_mid = mid
            seeded = True
        changed = abs(mid - previous_mid) > epsilon
        if np.isfinite(best_ofi[i]):
            cumulative_ofi += best_ofi[i]
        incoming = np.nan
        if event_count >= 8:
            back = (event_count - 8) % 17
            if stamp - ring_time[back] <= 120.:
                incoming = (mid - ring_mid[back]) / tick
        recent_ofi = 0.
        has_ofi_window = False
        if event_count >= 16:
            back = (event_count - 16) % 17
            if stamp - ring_time[back] <= 120.:
                recent_ofi = cumulative_ofi - ring_ofi[back]
                has_ofi_window = True
        for family in range(2):
            for level in range(2):
                for side_index in range(2):
                    if active[family, level, side_index] and stamp - refill_time[family, level, side_index] > 120.:
                        active[family, level, side_index] = False
        while pointer < len(events_i) and events_i[pointer] <= i:
            if events_i[pointer] == i and events_bestqty[pointer] > 0.:
                side = int(events_side[pointer])
                side_index = 0 if side == 1 else 1
                at_price = events_price[pointer]
                best = bid[i] if side == 1 else ask[i]
                ratio = events_qty[pointer] / events_bestqty[pointer]
                if abs(best - at_price) <= 2. * tick + epsilon:
                    for level in range(2):
                        strength = .5 if level == 0 else 1.
                        confirmation = 2. if level == 0 else 4.
                        if ratio + 1e-10 < strength:
                            continue
                        for family in range(2):
                            incoming_valid = family == 1 or (np.isfinite(incoming) and -side * incoming >= confirmation - 1e-7)
                            if incoming_valid and not active[family, level, side_index]:
                                active[family, level, side_index] = True
                                refill_price[family, level, side_index] = at_price
                                refill_mid[family, level, side_index] = mid
                                refill_bid[family, level, side_index] = bid[i]
                                refill_ask[family, level, side_index] = ask[i]
                                refill_time[family, level, side_index] = stamp
                                refill_max[family, level, side_index] = 0.
            pointer += 1
        # 中値が動かない板数量更新でも前進の最大値を更新するが、候補は発火しない。
        for level in range(2):
            for side_index in range(2):
                side = 1 if side_index == 0 else -1
                if active[0, level, side_index]:
                    progress = -side * (mid - refill_mid[0, level, side_index]) / tick
                    refill_max[0, level, side_index] = max(refill_max[0, level, side_index], progress)
                    if refill_max[0, level, side_index] > 1. + 1e-7:
                        active[0, level, side_index] = False
                if active[1, level, side_index]:
                    # 補充価格から離れて反対へ8呼値以上進んだエピソードは破棄する。
                    if side * (mid - refill_price[1, level, side_index]) > 8. * tick + epsilon:
                        active[1, level, side_index] = False
        if not changed:
            previous_time = stamp
            continue
        ready = stamp - start >= 300.
        for family in range(2):
            for level in range(2):
                impulse = (4. if level == 0 else 8.) * tick
                confirmation = (2. if level == 0 else 4.) * tick
                d = int(direction[family, level])
                if d != 0 and stamp - origin_time[family, level] > 120.:
                    d = 0
                    direction[family, level] = 0
                    low[family, level] = high[family, level] = mid
                    low_time[family, level] = high_time[family, level] = stamp
                    if family == 1:
                        pull_active[level] = False
                        resume_used[level] = False
                if d == 0:
                    if stamp - low_time[family, level] > 120.:
                        low[family, level], low_time[family, level] = mid, stamp
                    if stamp - high_time[family, level] > 120.:
                        high[family, level], high_time[family, level] = mid, stamp
                    if mid < low[family, level]:
                        low[family, level], low_time[family, level] = mid, stamp
                    if mid > high[family, level]:
                        high[family, level], high_time[family, level] = mid, stamp
                    if mid - low[family, level] >= impulse - epsilon:
                        d = 1
                        origin[family, level], origin_time[family, level] = low[family, level], low_time[family, level]
                    elif high[family, level] - mid >= impulse - epsilon:
                        d = -1
                        origin[family, level], origin_time[family, level] = high[family, level], high_time[family, level]
                    if d != 0:
                        direction[family, level] = d
                        extreme[family, level] = mid
                        extreme_bid[family, level], extreme_ask[family, level] = bid[i], ask[i]
                    continue
                advance = d * (mid - extreme[family, level])
                if advance > epsilon:
                    if family == 1 and pull_active[level]:
                        rebound = d * (mid - pull_extreme[level])
                        both_rebound = (d * (bid[i] - pull_bid[level]) > epsilon and d * (ask[i] - pull_ask[level]) > epsilon)
                        if ready and rebound >= confirmation - epsilon and both_rebound:
                            output[2 + level, i] = d
                    extreme[family, level] = mid
                    extreme_bid[family, level], extreme_ask[family, level] = bid[i], ask[i]
                    if family == 1:
                        pull_active[level] = False
                        resume_used[level] = False
                    continue
                pull = d * (extreme[family, level] - mid)
                previous_leg = d * (extreme[family, level] - origin[family, level])
                if family == 0:
                    both_return = (-d * (bid[i] - extreme_bid[family, level]) > epsilon
                                   and -d * (ask[i] - extreme_ask[family, level]) > epsilon)
                    if pull >= confirmation - epsilon and both_return:
                        if ready and previous_leg >= impulse - epsilon:
                            output[level, i] = -d
                        origin[family, level] = extreme[family, level]
                        origin_time[family, level] = stamp
                        direction[family, level] = -d
                        extreme[family, level] = mid
                        extreme_bid[family, level], extreme_ask[family, level] = bid[i], ask[i]
                else:
                    if pull >= impulse - epsilon:
                        origin[family, level] = extreme[family, level]
                        origin_time[family, level] = stamp
                        direction[family, level] = -d
                        extreme[family, level] = mid
                        extreme_bid[family, level], extreme_ask[family, level] = bid[i], ask[i]
                        pull_active[level] = False
                        resume_used[level] = False
                        continue
                    if previous_leg >= impulse - epsilon and pull >= confirmation - epsilon and not resume_used[level]:
                        if not pull_active[level]:
                            pull_active[level] = True
                            pull_extreme[level] = mid
                            pull_bid[level], pull_ask[level] = bid[i], ask[i]
                        elif d * (mid - pull_extreme[level]) < -epsilon:
                            pull_extreme[level] = mid
                            pull_bid[level], pull_ask[level] = bid[i], ask[i]
                    if pull_active[level]:
                        rebound = d * (mid - pull_extreme[level])
                        both_rebound = (d * (bid[i] - pull_bid[level]) > epsilon and d * (ask[i] - pull_ask[level]) > epsilon)
                        if rebound >= confirmation - epsilon and pull <= confirmation + epsilon and both_rebound:
                            if ready:
                                output[2 + level, i] = d
                            pull_active[level] = False
                            resume_used[level] = True
        for level in range(2):
            confirmation = (2. if level == 0 else 4.) * tick
            reversal = 0
            breakout = 0
            for side_index in range(2):
                side = 1 if side_index == 0 else -1
                if active[0, level, side_index]:
                    movement = side * (mid - refill_mid[0, level, side_index])
                    both_return = (side * (bid[i] - refill_bid[0, level, side_index]) > epsilon
                                   and side * (ask[i] - refill_ask[0, level, side_index]) > epsilon)
                    if movement >= confirmation - epsilon and both_return:
                        if ready:
                            reversal += side
                        active[0, level, side_index] = False
                if active[1, level, side_index]:
                    d = -side
                    quote = bid[i] if d == 1 else ask[i]
                    beyond = d * (quote - refill_price[1, level, side_index])
                    both_advance = (d * (bid[i] - refill_bid[1, level, side_index]) >= confirmation - epsilon
                                    and d * (ask[i] - refill_ask[1, level, side_index]) >= confirmation - epsilon)
                    if beyond >= confirmation - epsilon and both_advance and has_ofi_window and d * recent_ofi > 0.:
                        if ready:
                            breakout += d
                        active[1, level, side_index] = False
            # 同じ行で上下両候補なら見送る。
            output[4 + level, i] = 1 if reversal > 0 else -1 if reversal < 0 else 0
            output[6 + level, i] = 1 if breakout > 0 else -1 if breakout < 0 else 0
        ring_slot = event_count % 17
        ring_mid[ring_slot], ring_time[ring_slot] = mid, stamp
        ring_ofi[ring_slot] = cumulative_ofi
        event_count += 1
        previous_mid = mid
        previous_time = stamp
    return output


def arguments_from(feature: dict, events: np.ndarray, tick: float, start: float) -> tuple:
    """機能: 監査済み板特徴と補充完了配列を、入口関数の引数へ並べる。

    引数: feature(dict)、events(ndarray構造体)、tick/start(float)。
    返り値: candidate_signalsへ位置指定で渡せる引数(tuple)。ATRや約定値を追加しない。
    """
    return (feature['bid'], feature['ask'], feature['bid_qty'], feature['ask_qty'],
            feature['best_ofi'], feature['valid'], feature['reset'], feature['time_s'],
            events['i'], events['side'], events['qty'], events['bestqty'], events['price'],
            tick, start)
