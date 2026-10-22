"""元Last影の公開通知と実BBO約定を分離する、手数料零の次原行運転。"""

import numpy as np
from numba import njit

from bbo_order_kernel126 import execute


@njit(cache=True)
def repay(orders, trades, uids, slots, inventory, counters, parent,
          row, source, cid, bid, ask, qty, reason):
    """
    機能: 保有する実玉の指定枚数だけを当行正常BBOで返済する。
    引数: 会計配列(ndarray)、row/source/cid/qty/reason(int)、bid/ask(float)。
    返り値: intは返済枚数。紙上数量だけを根拠に実玉を過剰返済しない。
    """
    longqty = int(inventory[:, 0].sum()); shortqty = int(inventory[:, 1].sum())
    assert not (longqty and shortqty)
    held = longqty if longqty else shortqty
    take = min(held, qty)
    if take:
        side = -1 if longqty else 1
        fill = ask if side > 0 else bid
        execute(orders, trades, uids, slots, inventory, counters, parent,
                row, source, cid, side, take, fill, 0, 0, reason)
    return take


@njit(cache=True)
def simulate(times, prices, bid, ask, qok, feed, end, cap, market, policy, current_atr, history, exit_rule):
    """
    機能: 原Last影の通知を順に処理し、実玉の新規・返済を次の正常原行で行う。
    引数: times/prices/bid/ask/qok/feed/market/policy(ndarray)、end(float)、cap(int)。
    返り値: tuple[ndarray,...]は実注文・FIFO決済・時価・統計・親・UID・状態・三部品証跡。
    """
    n = len(times)
    capacity = max(128, len(feed)*8+32)
    if len(feed): capacity = max(capacity, int(feed[:, 2].max())+2)
    orders = np.zeros((capacity, 8)); trades = np.zeros((capacity*max(2, cap), 11))
    uids = np.full(capacity, -1, np.int64); slots = np.zeros((capacity, 7))
    inventory = np.zeros((3, 2), np.int64); counters = np.zeros(9)
    parent = np.zeros((capacity, 11)); parent[:, :3] = -1.
    curve = np.zeros((n, 8)); states = np.zeros((n, 14))
    events = np.zeros((capacity*12, 14)); ec = 0
    exitqueue = np.zeros(capacity, np.int64); queued = 0
    pointer = 0; virtual_cid = -1; vcore = 0; real_cid = -1
    pending = False; cancelled = False; filled = False
    entry_source = -1; entry_side = 0; entry_qty = 0; atr = 0.
    force_source = -1; force_reason = 0
    markbid = np.nan; markask = np.nan; markrow = -1
    peak = 0.; dd = 0.; session_r = 0.; session_stop = False
    guard_peak = 0.; guard_floor = -np.inf; real_entry_row = -1
    risk_fraction = 1.
    rearm_block = np.zeros(2, np.bool_); rearm_close = np.full(2, -np.inf)
    anchor_ready = np.zeros(2, np.bool_); anchor_row = np.full(2, -1, np.int64)
    anchor_time = np.full(2, np.nan); anchor_peer_time = np.full(2, np.nan)
    anchor_own = np.full(2, np.nan); anchor_peer = np.full(2, np.nan)
    anchor_own_atr = np.full(2, np.nan); anchor_peer_atr = np.full(2, np.nan)
    for i in range(n):
        t = times[i]
        good = bool(qok[i] and np.isfinite(bid[i]) and np.isfinite(ask[i]) and 0 < bid[i] < ask[i])
        scheduled = t >= end
        if scheduled:
            if force_source < 0: force_source = max(0, i-1)
            force_reason = 93
            queued = 0
            if pending:
                pending = False; cancelled = True
                events[ec] = np.array([i,8.,virtual_cid,entry_source,entry_side,entry_qty,0.,0.,0.,0.,0.,0.,0.,93.]); ec += 1
        held_before = int(inventory.sum())
        blocked = scheduled or session_stop or force_source >= 0
        # ----------------------------------------
        # 予約済みの注文を最初に処理する。当行後半の情報で遡及取消しない。
        if good:
            markbid = bid[i]; markask = ask[i]; markrow = i
            paper_first = queued > 0 and force_reason in (32, 70, 73)
            if paper_first:
                for q in range(queued):
                    o = feed[exitqueue[q]]
                    assert int(o[0]) < i and int(o[2]) == real_cid
                    done = repay(orders,trades,uids,slots,inventory,counters,parent,
                        i,int(o[0]),real_cid,bid[i],ask[i],int(o[4]),int(o[6]))
                    events[ec] = np.array([i,3.,real_cid,o[0],o[3],done,0.,0.,0.,0.,0.,0.,0.,o[6]]); ec += 1
                queued = 0
            if blocked and not paper_first:
                if inventory.sum():
                    assert force_source >= 0 and force_source < i
                    done = repay(orders,trades,uids,slots,inventory,counters,parent,
                        i,force_source,real_cid,bid[i],ask[i],int(inventory.sum()),force_reason)
                    events[ec] = np.array([i,4.,real_cid,force_source,0.,done,0.,0.,0.,0.,0.,0.,0.,force_reason]); ec += 1
                queued = 0; pending = False; force_source = -1; force_reason = 0
            elif not blocked:
                for q in range(queued):
                    o = feed[exitqueue[q]]
                    assert int(o[0]) < i and int(o[2]) == real_cid
                    done = repay(orders,trades,uids,slots,inventory,counters,parent,
                        i,int(o[0]),real_cid,bid[i],ask[i],int(o[4]),int(o[6]))
                    events[ec] = np.array([i,3.,real_cid,o[0],o[3],done,0.,0.,0.,0.,0.,0.,0.,o[6]]); ec += 1
                queued = 0
                if pending:
                    assert entry_source < i and not filled and not cancelled and inventory.sum() == 0
                    real_cid = virtual_cid
                    fill = ask[i] if entry_side > 0 else bid[i]
                    execute(orders,trades,uids,slots,inventory,counters,parent,
                        i,entry_source,real_cid,entry_side,entry_qty,fill,1,0,90)
                    pending = False; filled = True; real_entry_row = i
                    guard_peak = 0.; guard_floor = -np.inf
                    risk_fraction = 1.
                    if session_r == 0.: session_r = entry_qty*atr
                    events[ec] = np.array([i,2.,real_cid,entry_source,entry_side,entry_qty,fill,entry_qty*atr,0.,0.,0.,0.,0.,90.]); ec += 1
        # ----------------------------------------
        # 実組の全量返済だけで損失後制限を更新する。紙上の勝敗は使わない。
        if held_before > 0 and inventory.sum() == 0:
            net_campaign = parent[real_cid,7]
            side = int(parent[real_cid,5]); ix = 0 if side > 0 else 1
            if policy[2] > 0. and net_campaign < 0.:
                rearm_block[ix] = True; rearm_close[ix] = t
                anchor_ready[ix] = False; anchor_row[ix] = -1
                events[ec] = np.array([i,11.,real_cid,i,side,net_campaign,0.,0.,0.,0.,0.,0.,0.,0.]); ec += 1
            force_source = -1; force_reason = 0
        # ----------------------------------------
        # 当行までの原Last影通知だけを読む。実約定待ちの玉は解消済みと数えない。
        while pointer < len(feed) and int(feed[pointer,0]) == i:
            o = feed[pointer]; feed_index = pointer; pointer += 1
            cid = int(o[2]); side = int(o[3]); qty = int(o[4]); new = int(o[7]); reason = int(o[6])
            assert int(o[8]) == 0 and reason != 32
            if new:
                assert vcore == 0 and o[9] > 0. and qty <= cap
                virtual_cid = cid; entry_source = i; entry_side = side; entry_qty = qty; atr = o[9]
                busy = inventory.sum() > 0 or queued > 0
                ix = 0 if side > 0 else 1
                cancelled = blocked or busy or rearm_block[ix]; filled = False; pending = not cancelled
                parent[cid,0] = i; parent[cid,3] = qty*atr; parent[cid,4] = atr; parent[cid,5] = side
                vcore += side*qty
                events[ec] = np.array([i,1.,cid,i,side,qty,o[5],qty*atr,int(pending),int(cancelled),int(busy),int(rearm_block[ix]),0.,reason]); ec += 1
            else:
                assert cid == virtual_cid and side*entry_side < 0 and qty <= abs(vcore)
                vcore += side*qty
                if pending:
                    pending = False; cancelled = True
                    events[ec] = np.array([i,8.,cid,entry_source,side,qty,0.,0.,0.,0.,0.,0.,0.,reason]); ec += 1
                elif real_cid == cid and inventory.sum() > 0 and not scheduled:
                    exitqueue[queued] = feed_index; queued += 1
            events[ec] = np.array([i,6.,cid,i,side,qty,o[5],vcore,int(pending),inventory.sum(),0.,0.,0.,reason]); ec += 1
        assert pointer >= len(feed) or int(feed[pointer,0]) > i
        longqty = int(inventory[:,0].sum()); shortqty = int(inventory[:,1].sum())
        assert 0 <= longqty <= cap and 0 <= shortqty <= cap and not (longqty and shortqty)
        assert not inventory.sum() or (np.isfinite(markbid) and markask > markbid > 0.)
        liquidation = longqty*markbid-shortqty*markask if inventory.sum() else 0.
        equity = counters[3]+liquidation
        peak = max(peak,equity); dd = max(dd,peak-equity)
        # ----------------------------------------
        # 新しい実予算・利益床は当行後に設定し、次の正常原行以降で返済する。
        if good and inventory.sum() and force_source < 0:
            side = 1 if longqty else -1
            entry_price = 0.
            for ticket in range(int(counters[2])):
                if int(slots[ticket,6]) == real_cid:
                    entry_price = slots[ticket,2]
                    break
            mark = bid[i] if side > 0 else ask[i]
            campaign_equity = parent[real_cid,7]+side*int(inventory.sum())*(mark-entry_price)
            risk = parent[real_cid,3]
            guard_peak = max(guard_peak,campaign_equity)
            opposition = i > real_entry_row and market[i,8] > times[real_entry_row] and market[i,11] == 1.
            opposition = opposition and side*market[i,4] < -.05 and side*market[i,5] < -.1 and side*market[i,6] < -.05 and side*market[i,7] < -.1
            if policy[0] > 0. and guard_peak >= policy[0]*risk and opposition:
                next_floor = max(guard_floor,policy[1]*guard_peak)
                if next_floor > guard_floor:
                    guard_floor = next_floor
                    events[ec] = np.array([i,12.,real_cid,i,side,campaign_equity,guard_peak,guard_floor,risk,0.,0.,0.,0.,0.]); ec += 1
            # ----------------------------------------
            # 日中の値幅収縮／中期失敗を、当行までの資料だけで判断する。
            effective_risk = risk
            if exit_rule in (1, 3):
                if np.isfinite(current_atr[i]) and current_atr[i] > 0.:
                    risk_fraction = min(risk_fraction, max(policy[4], min(1., current_atr[i] / atr)))
                effective_risk = risk * risk_fraction
            if exit_rule in (2, 3) and guard_peak >= policy[5] * risk:
                failed = np.isfinite(history[i, 1]) and np.isfinite(history[i, 10])
                failed = failed and np.isfinite(history[i,7]) and np.isfinite(history[i,11])
                failed = failed and side * history[i,7] < 0. and side * history[i,11] < 0.
                if failed:
                    guard_floor = max(guard_floor, .5 * guard_peak)
            reason = 0
            if campaign_equity <= -effective_risk: reason = 32
            elif exit_rule in (2, 3) and np.isfinite(guard_floor) and campaign_equity <= guard_floor: reason = 70
            elif policy[0] > 0. and np.isfinite(guard_floor) and campaign_equity <= guard_floor: reason = 70
            if reason:
                force_source = i; force_reason = reason
                boundary = -effective_risk if reason == 32 else guard_floor
                events[ec] = np.array([i,9.,real_cid,i,side,campaign_equity,risk,boundary,0.,0.,0.,0.,0.,reason]); ec += 1
        if good and policy[3] > 0. and session_r > 0. and not session_stop and equity <= -policy[3]*session_r:
            session_stop = True; pending = False
            if inventory.sum() and force_source < 0:
                force_source = i; force_reason = 73
            events[ec] = np.array([i,10.,real_cid,i,0.,equity,session_r,policy[3],0.,0.,0.,0.,0.,73.]); ec += 1
        # ----------------------------------------
        # 損失後アンカーと解除は現在行の新規通知へ遡って適用しない。
        if policy[2] > 0. and market[i,11] == 1.:
            for ix in range(2):
                if not rearm_block[ix]: continue
                side = 1. if ix == 0 else -1.
                if not anchor_ready[ix] and t > rearm_close[ix] and market[i,8] > rearm_close[ix]:
                    anchor_ready[ix] = True; anchor_row[ix] = i
                    anchor_time[ix] = t; anchor_peer_time[ix] = market[i,8]
                    anchor_own[ix] = market[i,0]; anchor_peer[ix] = market[i,1]
                    anchor_own_atr[ix] = market[i,2]; anchor_peer_atr[ix] = market[i,3]
                    events[ec] = np.array([i,13.,real_cid,i,side,anchor_own[ix],anchor_peer[ix],anchor_own_atr[ix],anchor_peer_atr[ix],0.,0.,0.,0.,0.]); ec += 1
                if anchor_ready[ix]:
                    own = side*(market[i,0]-anchor_own[ix])/anchor_own_atr[ix]
                    peer = side*(market[i,1]-anchor_peer[ix])/anchor_peer_atr[ix]
                    window = market[i,9] >= anchor_time[ix] and market[i,10] >= anchor_peer_time[ix]
                    supported = side*market[i,4] > .05 and side*market[i,6] > .05
                    if window and supported and own >= policy[2] and peer >= policy[2]:
                        rearm_block[ix] = False
                        events[ec] = np.array([i,14.,real_cid,anchor_row[ix],side,own,peer,policy[2],0.,0.,0.,0.,0.,0.]); ec += 1
        curve[i] = np.array([equity,counters[4],longqty,shortqty,dd,counters[3],longqty-shortqty,real_cid])
        states[i] = np.array([virtual_cid,vcore,real_cid,longqty,shortqty,int(pending),int(cancelled),int(filled),queued,markrow,int(session_stop),session_r,int(rearm_block[0]),int(rearm_block[1])])
        assert ec < len(events)-32
    oc = int(counters[0]); tc = int(counters[1]); cycles = np.zeros((capacity,10)); cc = 0
    for cid in range(capacity):
        if parent[cid,6] == 0.: continue
        residual = 0
        for ticket in range(int(counters[2])):
            if int(slots[ticket,6]) == cid: residual += int(slots[ticket,0])
        if residual: continue
        cycles[cc] = np.array([cid,parent[cid,1],parent[cid,2],parent[cid,7],parent[cid,3],parent[cid,4],parent[cid,8],parent[cid,9],parent[cid,5],parent[cid,10]]); cc += 1
    assert pointer == len(feed)
    stats = np.array([counters[4],dd,counters[5],counters[6],counters[7],counters[8],0.,min(0.,curve[:,0].min()),max(0.,curve[:,0].max()),inventory.sum(),0.])
    return orders[:oc],trades[:tc],curve,stats,cycles[:cc],uids[:oc],events[:ec],states,parent
