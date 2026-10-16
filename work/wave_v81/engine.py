"""時間で保有を区切らず、観測した方向状態だけで新規・返済する。"""

import math
import numpy as np
from numba import njit

REASONS = {4: '場内清算', 6: '共同支持の消失', 7: '一市場の反対', 8: '二市場の反対一致', 10: '方向検知の新規'}


@njit(cache=True)
def should_exit(side, own, peer, own_valid, peer_valid, mode, solo):
    """機能: 中立と欠測を区別し、現在判別できる方向から返済を判断する。

    引数: side/own/peer/mode/solo(int)、own_valid/peer_valid(bool)。
    返り値: 返済理由番号(int)、0は継続。時間・損益を条件に用いない。
    """
    if solo:
        if own_valid and own != side:
            return 6
    elif mode == 0:
        if own_valid and peer_valid and (own != side or peer != side):
            return 6
    elif mode == 1:
        if (own_valid and own == -side) or (peer_valid and peer == -side):
            return 7
    elif own_valid and peer_valid and own == -side and peer == -side:
        return 8
    return 0


@njit(cache=True, nogil=True)
def simulate(times, bid, ask, quality, reset, mapped, grid, states, source_own, source_peer, reference_bid, reference_ask,
             tick, start, limit, quantity, value, fee_unit, latency, entry_mode, unused_target, unused_stop, unused_hold,
             unused_trail, unused_cooldown, unused_repair, peer_states, valid_own, valid_peer, exit_mode, solo, repair,
             exit_own_states, exit_peer_states, exit_valid_own, exit_valid_peer):
    """機能: 全原板を順に読み、方向が分かる行で発注判断を行う。

    引数: 原本・参照・方向配列(ndarray)、tick/start/limit/quantity/value/fee_unit/latency(float)、
        entry_mode(int:0成行/1不利1呼値上限)、exit_mode(int:0支持消失/1片方反対/2双方反対)、solo/repair(int)、
        exit_own_states/exit_peer_states/exit_valid_own/exit_valid_peer(ndarray)。初回は入口と同じ状態を用いる。
        unused接頭辞の引数は旧会計との列互換用で、常に0。売買判断に使用しない。
    返り値: 注文18列・決済12列・全行清算時価・残状態9列・イベント9列(tuple)。
    利確目標、保有期限、固定休止は設けない。場内清算だけは終了60秒前に返済を送る。
    発注済み成行は消さず、新規約定直後も最新状態で返済判断する。
    """
    n = len(times)
    capacity = max(1024, n + 32)
    orders = np.zeros((capacity, 18)); trades = np.zeros((capacity // 2 + 64, 12))
    curve = np.zeros(n); events = np.zeros((2 * capacity + 64, 9))
    oi = ti = ei = 0; side = pending_side = 0; pending_entry = pending_exit = False
    cid = -1; entry_i = decision_i = exit_decision_i = -1; entry_grid = exit_grid = -1
    decision_time = arrival = exit_decision_time = exit_arrival = 0.
    entry = price_limit = cash = last_bid = last_ask = 0.
    exit_reason = maxlong = maxshort = cancelled = gapfills = 0
    last_closed_side = 0; rearmed = True
    for i in range(n):
        assert oi + 2 < len(orders) and ti + 1 < len(trades) and ei + 4 < len(events), '配列容量超過'
        stamp = times[i]
        qok = np.isfinite(bid[i]) and np.isfinite(ask[i]) and bid[i] > 0 and ask[i] >= bid[i]
        g = int(mapped[i])
        own = int(states[g]); peer = int(peer_states[g]); vo = bool(valid_own[g]); vp = bool(valid_peer[g])
        joint = own if vo and own != 0 and (solo or (vp and peer == own)) else 0
        # ----------------------------------------
        # 時計による唯一の返済は場内清算。価格観測がなくても予定時刻で送ったものとする。
        if side and not pending_exit and stamp >= limit - 60.:
            due = max(times[entry_i], limit - 60.)
            pending_exit = True; exit_decision_i = i - 1; exit_decision_time = due; exit_arrival = due + latency
            exit_reason = 4; exit_grid = -1
            events[ei] = np.array([i - 1, cid, 24., due, side, last_bid if side == 1 else last_ask, exit_arrival, 4., -1.]); ei += 1
        if qok:
            last_bid = bid[i]; last_ask = ask[i]
        # ----------------------------------------
        # 到達済み注文を処理する。返済済みの方向を後から書き換えない。
        if pending_exit and i > exit_decision_i and stamp >= exit_arrival and qok:
            price = bid[i] if side == 1 else ask[i]
            fee = math.floor(quantity * fee_unit + 1e-8)
            gross = side * (price - entry) * quantity * value; net = gross - 2 * fee
            sg = grid[exit_grid] if exit_grid >= 0 else -1.
            sa = source_own[exit_grid] if exit_grid >= 0 else -1
            sb = source_peer[exit_grid] if exit_grid >= 0 else -1
            orders[oi] = np.array([i, exit_decision_i, cid, -side, quantity, price, exit_reason, 0., fee, -1., exit_decision_time, exit_arrival, stamp, i, 0., sg, sa, sb]); oi += 1
            trades[ti] = np.array([cid, entry_i, i, side, quantity, entry, price, fee, fee, gross, net, 0.]); ti += 1
            cash += side * quantity * price * value - fee
            gapfills += int(stamp - exit_arrival > 5.)
            events[ei] = np.array([i, cid, 29., stamp, side, price, exit_arrival, net, sg]); ei += 1
            last_closed_side = side; rearmed = False
            side = 0; pending_exit = False
        if pending_entry and i > decision_i and stamp >= arrival and qok:
            price = ask[i] if pending_side == 1 else bid[i]
            fill = entry_mode == 0 or pending_side * (price - price_limit) <= 1e-8
            if fill:
                side = pending_side; entry_i = i; entry = price; cid += 1
                fee = math.floor(quantity * fee_unit + 1e-8)
                cash -= side * quantity * entry * value + fee
                sg = grid[entry_grid]; sa = source_own[entry_grid]; sb = source_peer[entry_grid]
                orders[oi] = np.array([i, decision_i, cid, side, quantity, price, 10., 1., fee, 0., decision_time, arrival, stamp, i, entry_mode, sg, sa, sb]); oi += 1
                maxlong = max(maxlong, quantity if side == 1 else 0); maxshort = max(maxshort, quantity if side == -1 else 0)
                gapfills += int(stamp - arrival > 5.)
                events[ei] = np.array([i, cid, 28., stamp, side, price, arrival, 0., sg]); ei += 1
            else:
                cancelled += 1
                events[ei] = np.array([i, cid, 21., stamp, pending_side, price_limit, arrival, 0., grid[entry_grid]]); ei += 1
            pending_entry = False
        # ----------------------------------------
        # 途中判断は方向状態のみ。約定した行でも、根拠が消えていれば直ちに返済を判断する。
        if side and not pending_exit:
            reason = 4 if stamp >= limit - 60. else should_exit(side, exit_own_states[g], exit_peer_states[g], exit_valid_own[g], exit_valid_peer[g], exit_mode, solo)
            if reason:
                pending_exit = True; exit_decision_i = i; exit_decision_time = stamp; exit_arrival = stamp + latency
                exit_reason = reason; exit_grid = g
                events[ei] = np.array([i, cid, 24., stamp, side, bid[i] if side == 1 else ask[i], exit_arrival, reason, grid[g]]); ei += 1
        # ----------------------------------------
        # 再入口にも現在の支持を要求する。固定秒数の休止はしない。
        if vo and (solo or vp) and (own != last_closed_side or (not solo and peer != last_closed_side)):
            rearmed = True
        allowed = joint != 0 and (repair != 1 or rearmed or joint != last_closed_side)
        if side == 0 and not pending_entry and not pending_exit and allowed and quality[i] and not reset[i] and qok and stamp >= start and stamp < limit - 120.:
            pending_entry = True; pending_side = joint; decision_i = i; decision_time = stamp; arrival = stamp + latency; entry_grid = g
            price_limit = ask[i] + tick if joint == 1 else bid[i] - tick
            events[ei] = np.array([i, cid, 20., stamp, joint, price_limit, arrival, 0., grid[g]]); ei += 1
        curve[i] = cash
        if side:
            fee = math.floor(quantity * fee_unit + 1e-8)
            curve[i] += side * quantity * (last_bid if side == 1 else last_ask) * value - fee
    return orders[:oi], trades[:ti], curve, np.array([side, int(pending_entry), int(pending_exit), 0, maxlong, maxshort, cancelled, ti, gapfills]), events[:ei]
