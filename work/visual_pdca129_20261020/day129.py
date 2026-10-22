"""D17互換の次原行運転へ、二市場の新規根拠撤回と同影内の再参加を追加する。"""

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
def simulate(times, prices, bid, ask, qok, feed, end, cap, market, policy, current_atr, history,
             exit_rule, withdrawal_width=0., allow_reentry=False):
    """
    機能: D17の通知と返済を維持し、二市場が新規基準から逆行したら撤退する。
    引数: 原核の配列と時刻・上限、withdrawal_width(float)は各初期ATR比、
          allow_reentry(bool)は同影につき一度だけ再参加を許可するか。
    返り値: tuple[ndarray,...]は旧9配列と実親・影親・参加回数・判断行の対応表。
            幅0かつ再参加なしでは旧9配列が元核と同値。費用は呼出側で加算する。
    """
    n = len(times)
    capacity = max(128, len(feed)*8+32)
    if len(feed): capacity = max(capacity, int(feed[:, 2].max())+2)
    if withdrawal_width > 0. and allow_reentry:
        capacity *= 2
    orders = np.zeros((capacity, 8)); trades = np.zeros((capacity*max(2, cap), 11))
    uids = np.full(capacity, -1, np.int64); slots = np.zeros((capacity, 7))
    inventory = np.zeros((3, 2), np.int64); counters = np.zeros(9)
    parent = np.zeros((capacity, 11)); parent[:, :3] = -1.
    curve = np.zeros((n, 8)); states = np.zeros((n, 14))
    events = np.zeros((capacity*12, 14)); ec = 0
    exitqueue = np.zeros(capacity, np.int64); queued = 0
    exitqueue_qty = np.zeros(capacity, np.int64)
    pointer = 0; virtual_cid = -1; vcore = 0; real_cid = -1
    pending_cid = -1; real_shadow_cid = -1; paper_basis_qty = 0
    next_real_cid = 0
    links = np.zeros((capacity,4)); link_count = 0
    attempt = 0; shadow_qty = 0; shadow_atr = 0.; reentry_used = False
    entry_anchor_known = False
    entry_anchor_own = 0.; entry_anchor_peer = 0.; entry_peer_atr = 0.
    entry_peer_time = 0.
    retry_waiting = False; retry_anchor_known = False
    retry_own = 0.; retry_peer = 0.; retry_time = 0.; retry_peer_time = 0.
    retry_own_atr = 0.; retry_peer_atr = 0.
    retry_close_time = -np.inf
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
        completed_reason = 0
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
            paper_first = queued > 0 and force_reason in (32, 70, 73, 75)
            if paper_first:
                for q in range(queued):
                    o = feed[exitqueue[q]]
                    assert int(o[0]) < i and int(o[2]) == real_shadow_cid
                    done = repay(orders,trades,uids,slots,inventory,counters,parent,
                        i,int(o[0]),real_cid,bid[i],ask[i],exitqueue_qty[q],int(o[6]))
                    if done and inventory.sum() == 0: completed_reason = int(o[6])
                    events[ec] = np.array([i,3.,real_cid,o[0],o[3],done,0.,0.,0.,0.,0.,0.,0.,o[6]]); ec += 1
                queued = 0
            if blocked and not paper_first:
                if inventory.sum():
                    assert force_source >= 0 and force_source < i
                    done = repay(orders,trades,uids,slots,inventory,counters,parent,
                        i,force_source,real_cid,bid[i],ask[i],int(inventory.sum()),force_reason)
                    if done and inventory.sum() == 0: completed_reason = force_reason
                    events[ec] = np.array([i,4.,real_cid,force_source,0.,done,0.,0.,0.,0.,0.,0.,0.,force_reason]); ec += 1
                queued = 0; pending = False; force_source = -1; force_reason = 0
            elif not blocked:
                for q in range(queued):
                    o = feed[exitqueue[q]]
                    assert int(o[0]) < i and int(o[2]) == real_shadow_cid
                    done = repay(orders,trades,uids,slots,inventory,counters,parent,
                        i,int(o[0]),real_cid,bid[i],ask[i],exitqueue_qty[q],int(o[6]))
                    if done and inventory.sum() == 0: completed_reason = int(o[6])
                    events[ec] = np.array([i,3.,real_cid,o[0],o[3],done,0.,0.,0.,0.,0.,0.,0.,o[6]]); ec += 1
                queued = 0
                if pending:
                    assert entry_source < i and not filled and not cancelled and inventory.sum() == 0
                    real_cid = pending_cid
                    real_shadow_cid = virtual_cid
                    fill = ask[i] if entry_side > 0 else bid[i]
                    execute(orders,trades,uids,slots,inventory,counters,parent,
                        i,entry_source,real_cid,entry_side,entry_qty,fill,1,0,90)
                    pending = False; filled = True; real_entry_row = i
                    guard_peak = 0.; guard_floor = -np.inf
                    risk_fraction = 1.
                    entry_anchor_known = market[i,11] == 1. and np.isfinite(market[i,:4]).all()
                    entry_anchor_known = entry_anchor_known and market[i,2] > 0. and market[i,3] > 0.
                    entry_anchor_known = entry_anchor_known and np.isfinite(market[i,8])
                    if entry_anchor_known:
                        entry_anchor_own = market[i,0]; entry_anchor_peer = market[i,1]
                        entry_peer_atr = market[i,3]; entry_peer_time = market[i,8]
                    links[link_count] = np.array([real_cid,virtual_cid,attempt,entry_source])
                    link_count += 1
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
            if completed_reason == 75 and allow_reentry and not reentry_used and entry_anchor_known:
                retry_waiting = True; retry_anchor_known = False
                retry_own_atr = atr; retry_peer_atr = entry_peer_atr
                retry_close_time = t
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
                pending_cid = cid
                if withdrawal_width > 0.:
                    pending_cid = next_real_cid; next_real_cid += 1
                paper_basis_qty = qty
                shadow_qty = qty; shadow_atr = atr; attempt = 0; reentry_used = False
                retry_waiting = False; retry_anchor_known = False
                busy = inventory.sum() > 0 or queued > 0
                ix = 0 if side > 0 else 1
                cancelled = blocked or busy or rearm_block[ix]; filled = False; pending = not cancelled
                parent[pending_cid,0] = i; parent[pending_cid,3] = qty*atr
                parent[pending_cid,4] = atr; parent[pending_cid,5] = side
                vcore += side*qty
                events[ec] = np.array([i,1.,pending_cid,i,side,qty,o[5],qty*atr,int(pending),int(cancelled),int(busy),int(rearm_block[ix]),0.,reason]); ec += 1
            else:
                assert cid == virtual_cid and side*entry_side < 0 and qty <= abs(vcore)
                vcore += side*qty
                if pending:
                    pending = False; cancelled = True
                    events[ec] = np.array([i,8.,cid,entry_source,side,qty,0.,0.,0.,0.,0.,0.,0.,reason]); ec += 1
                elif real_shadow_cid == cid and inventory.sum() > 0 and not scheduled:
                    # 再参加時点で残っていた影枚数を分母に、残実枚数を累計整数で対応する。
                    target_remaining = int(np.floor(abs(vcore)*entry_qty/paper_basis_qty+.5))
                    available = int(inventory.sum())-int(exitqueue_qty[:queued].sum())
                    take = max(0,available-target_remaining)
                    if take:
                        exitqueue[queued] = feed_index; exitqueue_qty[queued] = take; queued += 1
                if vcore == 0:
                    retry_waiting = False; retry_anchor_known = False
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
            if not reason and withdrawal_width > 0. and entry_anchor_known:
                known = market[i,11] == 1. and np.isfinite(market[i,:2]).all()
                fresh = i > real_entry_row and market[i,8] > entry_peer_time
                if known and fresh:
                    own_failure = side*(market[i,0]-entry_anchor_own)/atr
                    peer_failure = side*(market[i,1]-entry_anchor_peer)/entry_peer_atr
                    if own_failure <= -withdrawal_width and peer_failure <= -withdrawal_width:
                        reason = 75
                        events[ec] = np.array([i,15.,real_cid,i,side,own_failure,peer_failure,
                            withdrawal_width,entry_anchor_own,entry_anchor_peer,real_shadow_cid,attempt,0.,75.]); ec += 1
            if reason:
                force_source = i; force_reason = reason
                boundary = -effective_risk if reason == 32 else (campaign_equity if reason == 75 else guard_floor)
                events[ec] = np.array([i,9.,real_cid,i,side,campaign_equity,risk,boundary,0.,0.,0.,0.,0.,reason]); ec += 1
        if good and policy[3] > 0. and session_r > 0. and not session_stop and equity <= -policy[3]*session_r:
            session_stop = True; pending = False
            if inventory.sum() and force_source < 0:
                force_source = i; force_reason = 73
            events[ec] = np.array([i,10.,real_cid,i,0.,equity,session_r,policy[3],0.,0.,0.,0.,0.,73.]); ec += 1
        # ----------------------------------------
        # 撤退後の新しい資料だけで再武装し、元影が存続中でも同方向の新規を一度だけ予約する。
        if allow_reentry and retry_waiting and not reentry_used and vcore != 0:
            idle = inventory.sum() == 0 and not pending and queued == 0 and force_source < 0
            idle = idle and not scheduled and not session_stop
            known = market[i,11] == 1. and np.isfinite(market[i,:2]).all() and np.isfinite(market[i,8])
            if idle and known:
                if not retry_anchor_known and t > retry_close_time and market[i,8] > retry_close_time:
                    retry_anchor_known = True
                    retry_own = market[i,0]; retry_peer = market[i,1]
                    retry_time = t; retry_peer_time = market[i,8]
                    events[ec] = np.array([i,16.,real_cid,i,entry_side,retry_own,retry_peer,
                        retry_own_atr,retry_peer_atr,virtual_cid,0.,0.,0.,0.]); ec += 1
                elif retry_anchor_known:
                    own = entry_side*(market[i,0]-retry_own)/retry_own_atr
                    peer = entry_side*(market[i,1]-retry_peer)/retry_peer_atr
                    window = market[i,9] >= retry_time and market[i,10] >= retry_peer_time
                    fresh = t > retry_time and market[i,8] > retry_peer_time
                    supported = entry_side*market[i,4] > .05 and entry_side*market[i,6] > .05
                    adverse = ask[i]-prices[i] if entry_side > 0 else prices[i]-bid[i]
                    budget = good and ask[i]-bid[i] <= .5*shadow_atr and adverse <= .5*shadow_atr
                    if budget and window and fresh and supported and own >= .25 and peer >= .25:
                        pending_cid = next_real_cid; next_real_cid += 1
                        assert pending_cid < capacity and shadow_qty <= cap
                        entry_source = i; entry_qty = shadow_qty; atr = shadow_atr
                        paper_basis_qty = abs(vcore); attempt = 1
                        parent[pending_cid,0] = i; parent[pending_cid,3] = entry_qty*atr
                        parent[pending_cid,4] = atr; parent[pending_cid,5] = entry_side
                        pending = True; cancelled = False; filled = False
                        retry_waiting = False; reentry_used = True
                        events[ec] = np.array([i,17.,pending_cid,i,entry_side,entry_qty,own,peer,
                            virtual_cid,paper_basis_qty,attempt,0.,0.,90.]); ec += 1
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
    return orders[:oc],trades[:tc],curve,stats,cycles[:cc],uids[:oc],events[:ec],states,parent,links[:link_count]
