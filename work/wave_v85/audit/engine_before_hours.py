"""元E01の枠会計に、実建玉の初期失敗と料金後連敗による損失制御を追加する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import numpy as np
from numba import njit

import exit_shadow_integrated as shadow_engine

PARAMS = shadow_engine.PARAMS
ATR_COLUMNS = shadow_engine.ATR_COLUMNS
PLAN_COLUMNS = shadow_engine.PLAN_COLUMNS
REASONS = dict(shadow_engine.REASONS, **{})
REASONS.update({30: '悪化による数量減量', 31: '数量復元', 32: '実組損失予算による全返済'})
CONTROL_COLUMNS = ['shadow_campaign', 'actual_campaign', 'phase', 'direction', 'shadow_qty',
                   'actual_qty', 'restorable_qty', 'reductions', 'pending_kind', 'pending_row',
                   'pending_evidence_row', 'campaign_equity', 'initial_risk', 'budget_pending',
                   'budget_source_row', 'campaign_closed', 'evidence_barrier_row',
                   'reduction_fill_row', 'shadow_plan_row', 'budget_excess']
SLOT_EVENT_COLUMNS = ['row', 'source_row', 'campaign', 'slot', 'event', 'leg', 'direction',
                      'price', 'qty', 'reason', 'shadow_plan_row']
SLOT_EVENT_NAMES = {1: '組開始新規', 2: '減量返済', 3: '復元新規', 4: '元部分利確の枠終了', 5: '組全返済'}
ADJUSTMENT_COLUMNS = ['row', 'campaign', 'event', 'kind', 'source_row', 'evidence_row',
                      'qty', 'reason', 'slot_mask', 'reductions', 'shadow_plan_row']
ADJUSTMENT_NAMES = {1: '調整予約', 2: '調整約定', 3: '元注文による調整取消', 4: '復元資格消滅'}
BUDGET_COLUMNS = ['row', 'campaign', 'event', 'source_row', 'initial_risk', 'campaign_equity',
                  'excess', 'elapsed_seconds']
BUDGET_NAMES = {1: '全返済予約', 2: '全返済完了', 3: '元部分利確による予約継続'}
FIELDS = ('trades', 'cycles', 'curve', 'orders', 'stats', 'atr_curve')
BRANCH_COLUMNS = ['row','campaign','reduction_number','restore_mode','direction','source_row','valid','classification','branch_mode','seed']
BRANCH_CURVE_COLUMNS = ['restore_mode','selection_row','source_row','classification']
BRANCH_NAMES = {0:'固定',1:'逆方向なら信号',2:'逆分岐',3:'固定乱数'}
BRANCH_CLASSIFICATION = {0:'欠測',1:'有効中立',2:'有効順方向',3:'有効逆方向'}


def input_digest(ready: dict, state: np.ndarray, config: dict, observed_fill: bool, min_delay_seconds: float=0.) -> str:
    """機能: 影の全利用入力を内容指紋へまとめる。

    引数: ready/config (dict)、state (ndarray)、observed_fill (bool)。返り値: SHA256 (str)。
    """
    h = hashlib.sha256()
    h.update(hashlib.sha256(Path(shadow_engine.__file__).read_bytes()).digest())
    h.update(bytes.fromhex(shadow_engine.dependency_sha256()))
    for name in ('time_s', 'last', 'atr', 'seq'):
        value = np.ascontiguousarray(ready[name])
        h.update(name.encode()); h.update(str((value.dtype.str, value.shape)).encode()); h.update(value.tobytes())
    value = np.ascontiguousarray(state)
    h.update(str((value.dtype.str, value.shape)).encode()); h.update(value.tobytes())
    h.update(repr(tuple(ready[k] for k in ('tick', 'start', 'limit', 'us_open'))).encode())
    h.update(json.dumps(config, sort_keys=True, separators=(',', ':'), default=float).encode())
    h.update(str(bool(observed_fill)).encode())
    h.update(repr((float(min_delay_seconds),float(ready.get('session_close',ready['limit']+600.)))).encode())
    return h.hexdigest()


def make_shadow(ready: dict, state: np.ndarray, config: dict, observed_fill: bool = False, min_delay_seconds: float=0.) -> dict:
    """機能: 実口座から独立したA0と、各行後の有効計画を生成する。

    引数: ready/config (dict)、state (ndarray)、observed_fill (bool)。返り値: 旧8結果・計画・入力指紋 (dict)。
    実際の枠注文器は影の約定行・返済行・台帳を約定判断には使わない。
    """
    result = shadow_engine.run(ready, state, config, detail=True, width_mode=0, observed_fill=observed_fill, min_delay_seconds=min_delay_seconds)
    result['input_sha256'] = input_digest(ready, state, config, observed_fill, min_delay_seconds)
    result['observed_fill'] = bool(observed_fill)
    result['min_delay_seconds'] = float(min_delay_seconds)
    return result


@njit(cache=True)
def close_slots(pos, used, slot_leg, selected, price, row, source, reason, campaign,
                trades, tc, orders, oc):
    """機能: 指定枠の現在玉を元脚順にまとめて返済し、二重返済を避ける。

    引数: 建玉・枠・台帳(ndarray)、各行・件数(int)、price(float)。
    返り値: 件数・損益・現金変化・返済枚数 (tuple)。
    """
    leg_quantities = np.zeros(used, dtype=np.int64)
    for slot in range(len(slot_leg)):
        if selected[slot] and slot_leg[slot] >= 0:
            leg_quantities[slot_leg[slot]] += 1
    gain = 0.; cash_change = 0.; count = 0
    for leg in range(used):
        qty = leg_quantities[leg]
        if not qty:
            continue
        if qty > pos[leg, 2] or tc >= len(trades) or oc >= len(orders):
            raise ValueError('枠数量又は返済台帳が不正です')
        pnl = qty * pos[leg, 0] * (price - pos[leg, 1])
        trades[tc] = np.array([campaign, leg, pos[leg, 0], qty, pos[leg, 1], price,
                              pos[leg, 4], row, 0., reason, pnl]); tc += 1
        orders[oc] = np.array([row, source, campaign, -pos[leg, 0], qty, price, reason, 0.]); oc += 1
        pos[leg, 2] -= qty; gain += pnl; cash_change += pos[leg, 0] * qty * price; count += qty
    for slot in range(len(slot_leg)):
        if selected[slot]:
            slot_leg[slot] = -1
    return tc, oc, gain, cash_change, count


@njit(cache=True)
def simulate(time, price, plans, execution_plans, shadow_atr, bad, bad_source, good, good_source, good_valid,
             end, cutoff, q0, cap, kind, fraction, restore_mode, maximum, restore_seconds,
             observed_fill, detail, budget_enabled, min_delay_seconds, branch_direction,
             branch_source, branch_valid, branch_choice, branch_mode, branch_seed, losspar, raw_bad, raw_source, raw_valid, ema_direction, ema_source, ema_peer_source, ema_valid):
    """機能: 前行影計画と現在価格から約定を独立判定し、数量枠を管理する。

    引数: 原本・影計画・方向・根拠(ndarray)、数量・方針(int)、閾値(float)、約定・詳細(bool)。
    losspar(ndarray)は早期制御・料金と利益保護・方向停止の固定変数。
    raw_bad/source/validとEMA列は公開済み根拠。追加EMA列は相手公開元行と両市場の有限値・鮮度。
    追加の返り値は利益保護曲線、保護イベント、方向停止イベント(ndarray)。
    返り値: 旧6結果と枠・調整・予算・管理状態・損失制御証跡 (tuple[ndarray,...])。
    """
    n = len(price)
    pos = np.zeros((12000, 5)); used = 0
    trades = np.zeros((24000, 11)); tc = 0
    orders = np.zeros((36000, 8)); oc = 0
    cycles = np.zeros((2000, 10)); cc = 0
    curve = np.zeros((n, 8)) if detail else np.zeros((1, 8))
    atr_curve = shadow_atr.copy() if detail else np.full((1, 12), np.nan)
    control = np.zeros((n, 20)) if detail else np.zeros((1, 20))
    slot_curve = np.zeros((n, q0), dtype=np.int8) if detail else np.zeros((1, q0), dtype=np.int8)
    slot_events = np.zeros((100000, 11)); sc = 0
    adjustment = np.zeros((24000, 11)); ac = 0
    budgets = np.zeros((6000, 8)); bc = 0
    branch_events=np.zeros((12000,10)); brc=0
    branch_curve=np.full((n,4),-1.) if detail else np.full((1,4),-1.)
    chosen_restore=restore_mode;branch_row=-1;branch_evidence=-1;branch_class=0
    alive = np.zeros(q0, dtype=np.bool_); restorable = np.zeros(q0, dtype=np.bool_)
    slot_leg = np.full(q0, -1, dtype=np.int64); pending_slots = np.zeros(q0, dtype=np.bool_)
    split_count = q0 // 2
    campaign = -1; shadow_campaign = -1; d = 0; entry_row = -1; base = 0.; a = 1.; risk = 1.
    closed = True; phase = 0; reductions = 0; barrier = -1; reduction_row = -1; reduction_time = 0.
    pending = 0; pending_row = -1; pending_evidence = -1
    budget = False; budget_row = -1; budget_time = 0.
    realized = 0.; cash = 0.; high_equity = 0.; dd = 0.; min_equity = 0.; max_equity = 0.; max_error = 0.
    maxlong = 0.; maxshort = 0.; maxgross = 0.; maxnet = 0.; cycle_max = 0.
    last_exit = -1e20; inv = np.zeros(6)
    early_peak = 0.; early_action = 0; early_row = -1; early_evidence = -1
    reduce_reason = 30; actual_anchor = 0.; campaign_fees = 0.
    loss_streak = 0; cumulative_r = 0.; pause_until = -1e20
    risk_events = np.zeros((12000, 10)); rc = 0
    guard_peak = 0.; guard_floor = -np.inf; guard_pending = False; guard_row = -1
    guard_curve = np.zeros((n, 8)) if detail else np.zeros((1, 8))
    guard_events = np.zeros((36000, 10)); gc = 0
    block_events = np.zeros((24000, 8)); xc = 0
    direction_losses = np.zeros(2, np.int64)
    blocked = np.zeros(2, np.bool_); reset_seen = np.zeros(2, np.bool_)
    block_row = np.full(2, -1, np.int64)
    reset_own = np.full(2, -1, np.int64); reset_peer = np.full(2, -1, np.int64)
    for i in range(n):
        if (used+1 >= len(pos) or tc+q0 >= len(trades) or oc+q0+1 >= len(orders)
                or cc+1 >= len(cycles) or sc+2*q0 >= len(slot_events)
                or ac+3 >= len(adjustment) or bc+3 >= len(budgets)):
            raise ValueError('数量調整台帳の保存上限に達しました')
        p = price[i]; t = time[i]; old_oc = oc
        if not np.isfinite(p) or p <= 0:
            if detail and i:
                control[i] = control[i-1]; slot_curve[i] = slot_curve[i-1]; branch_curve[i]=branch_curve[i-1]
                if closed and atr_curve[i, 0] != 0:
                    atr_curve[i, 0] = 0.; atr_curve[i, 1:9] = np.nan; atr_curve[i, 5] = 0.; atr_curve[i, 10] = -1.
            if detail and i: guard_curve[i] = guard_curve[i-1]
            continue
        plan_row = -1; source = i-1; original_reason = 0; original_fill = 0.; is_entry = False; planned_qty = 0.
        selected = np.zeros(q0, dtype=np.bool_)
        acted = False; reason = 0; fill = 0.; closed_now = False
        # ----------------------------------------
        # i行終了後の計画は参照しない。前行までの計画と現在観測だけを使う。
        if i and np.isfinite(execution_plans[i, 33]):
            plan = execution_plans[i]
            plan_row = int(plan[33]); sd = int(plan[0]); shadow_campaign = int(plan[1]); planned_qty = plan[7]
            source=i-1 if min_delay_seconds==0 else plan_row
            if sd:
                if int(plan[18]):
                    original_reason = int(plan[18]); original_fill = p; source = int(plan[19])
                else:
                    best = 1e100; prior = price[i-1]
                    for z in range(3):
                        level = plan[12+z]; side = sd if z == 2 else -sd
                        flag = bool(plan[15+z])
                        if not np.isfinite(level) or (not flag and side*(p-level) < -1e-8):
                            continue
                        distance = 0. if flag else max(0., side*(level-prior))
                        if distance < best-1e-9:
                            best = distance
                            original_reason = int(plan[20]) if z == 0 else (2 if z == 1 else 7)
                            original_fill = p if observed_fill or flag else level
            elif int(plan[21]) and not bool(plan[30]) and t < plan[23] and t < end-cutoff*60 and t >= pause_until and not blocked[0 if plan[21]>0 else 1]:
                pd = int(plan[21])
                if bool(plan[26]) or pd*(p-plan[22]) >= -1e-8:
                    is_entry = True; d = pd; a = plan[24]; risk = q0*a; planned_qty = q0
                    campaign = int(plan[1])+1; shadow_campaign = campaign; base = realized; entry_row = i
                    fill = p if observed_fill or bool(plan[26]) else plan[22]
                    source = int(plan[27]); original_reason = 20
                    closed = False; phase = 0; reductions = 0; barrier = i
                    reduction_row = -1; budget = False; budget_row = -1
                    chosen_restore=restore_mode;branch_row=-1;branch_evidence=-1;branch_class=0
                    pending = 0; pending_row = -1; pending_evidence = -1; pending_slots[:] = False
                    alive[:] = True; restorable[:] = False; slot_leg[:] = -1
                    cycle_max = 0.
                    if t < last_exit+300.-1e-8:
                        raise ValueError('元組開始で実の5分休止が終わっていません')
                    selected[:] = True
                    guard_peak = 0.; guard_floor = -np.inf; guard_pending = False; guard_row = -1
                    actual_anchor = fill; early_peak = 0.; early_action = 0
                    early_row = -1; early_evidence = -1; reduce_reason = 30; campaign_fees = 0.
                    if kind == 1:
                        count = int(np.floor(fraction*q0)); selected[:count] = False
                    elif kind == 2:
                        qs = q0-int(np.floor(fraction*q0)); k = qs//2
                        selected[:] = False; selected[:k] = True; selected[q0-(qs-k):] = True
                    qty = int(np.sum(selected)); leg = used
                    pos[used] = np.array([d, fill, qty, 0., i]); used += 1
                    orders[oc] = np.array([i, source, campaign, d, qty, fill, 20., 1.]); oc += 1
                    cash -= d*qty*fill
                    for slot in range(q0):
                        if selected[slot]:
                            slot_leg[slot] = leg
                            slot_events[sc] = np.array([i, source, campaign, slot+1, 1., leg, d, fill, 1., 20., plan_row]); sc += 1
                    acted = True; reason = 20
        if not is_entry and original_reason:
            planned_qty = planned_qty-split_count if original_reason == 7 else 0.
        # ----------------------------------------
        # 元注文を最優先。予算予約は部分利確によって消さない。
        if not is_entry and original_reason and not closed:
            fill = original_fill; reason = original_reason; early_action = 0
            if pending:
                mask = 0
                for slot in range(q0):
                    if pending_slots[slot]: mask += 1 << slot
                adjustment[ac] = np.array([i, campaign, 3., pending, pending_row, pending_evidence,
                                          np.sum(pending_slots), reason, mask, reductions, plan_row]); ac += 1
                pending = 0; pending_slots[:] = False
            barrier = i
            old_restorable = int(np.sum(restorable))
            selected[:] = True
            if reason == 7:
                selected[split_count:] = False
            for slot in range(q0):
                if selected[slot] and alive[slot]:
                    slot_events[sc] = np.array([i, source, campaign, slot+1, 4. if reason == 7 else 5.,
                        slot_leg[slot], d, fill, 1. if slot_leg[slot] >= 0 else 0., reason, plan_row]); sc += 1
                    alive[slot] = False; restorable[slot] = False
            tc, oc, gain, move, done = close_slots(pos, used, slot_leg, selected, fill, i, source, reason, campaign, trades, tc, orders, oc)
            realized += gain; cash += move; acted = True
            if reason == 7:
                if not np.any(restorable):
                    if old_restorable:
                        adjustment[ac] = np.array([i, campaign, 4., 0., source, -1., 0., 7., 0., reductions, plan_row]); ac += 1
                    phase = 0
                else:
                    phase = 2
                if budget:
                    inv = shadow_engine.inventory(pos, used)
                    e = realized-base+inv[2]*p-inv[3]
                    budgets[bc] = np.array([i, campaign, 3., budget_row, risk, e, max(0., -e-risk), t-budget_time]); bc += 1
                if guard_pending:
                    guard_events[gc] = np.array([i,campaign,4.,guard_row,0.,guard_peak,guard_floor,0.,d,7.]); gc += 1
            else:
                if guard_pending:
                    guard_events[gc] = np.array([i,campaign,5.,guard_row,0.,guard_peak,guard_floor,0.,d,reason]); gc += 1
                closed_now = True
        elif not is_entry and not closed and budget and i>budget_row and t>=budget_time+min_delay_seconds-1e-9:
            fill = p; reason = 32; source = budget_row; selected[:] = True
            for slot in range(q0):
                if alive[slot]:
                    slot_events[sc] = np.array([i, source, campaign, slot+1, 5., slot_leg[slot], d,
                                               fill, 1. if slot_leg[slot] >= 0 else 0., reason, plan_row]); sc += 1
            tc, oc, gain, move, done = close_slots(pos, used, slot_leg, selected, fill, i, source, reason, campaign, trades, tc, orders, oc)
            realized += gain; cash += move; acted = True; closed_now = True
        elif not is_entry and not closed and guard_pending and i > guard_row:
            fill = p; reason = 70; source = guard_row; selected[:] = True
            for slot in range(q0):
                if alive[slot]:
                    slot_events[sc] = np.array([i,source,campaign,slot+1,5.,slot_leg[slot],d,fill,1. if slot_leg[slot]>=0 else 0.,reason,plan_row]); sc += 1
            tc, oc, gain, move, done = close_slots(pos,used,slot_leg,selected,fill,i,source,reason,campaign,trades,tc,orders,oc)
            realized += gain; cash += move; acted = True; closed_now = True
            guard_events[gc] = np.array([i,campaign,3.,source,0.,guard_peak,guard_floor,done,d,reason]); gc += 1
        elif not is_entry and not closed and early_action and i > early_row:
            fill = p; reason = early_action; source = early_row; selected[:] = True
            for slot in range(q0):
                if alive[slot]:
                    slot_events[sc] = np.array([i, source, campaign, slot+1, 5., slot_leg[slot], d, fill, 1. if slot_leg[slot]>=0 else 0., reason, plan_row]); sc += 1
            tc, oc, gain, move, done = close_slots(pos, used, slot_leg, selected, fill, i, source, reason, campaign, trades, tc, orders, oc)
            realized += gain; cash += move; acted = True; closed_now = True
            risk_events[rc] = np.array([i, campaign, 2., early_action, source, early_evidence, done, early_peak, loss_streak, cumulative_r]); rc += 1
            early_action = 0
        elif not is_entry and not closed and pending and not budget and i>pending_row and t>=time[pending_row]+min_delay_seconds-1e-9:
            fill = p; reason = reduce_reason if pending < 0 else 31; source = pending_row
            mask = 0
            for slot in range(q0):
                if pending_slots[slot]: mask += 1 << slot
            if pending < 0:
                for slot in range(q0):
                    if pending_slots[slot]:
                        if slot_leg[slot] < 0 or not alive[slot]: raise ValueError('減量枠が生存していません')
                        slot_events[sc] = np.array([i, source, campaign, slot+1, 2., slot_leg[slot], d, fill, 1., reason, plan_row]); sc += 1
                        restorable[slot] = True
                tc, oc, gain, move, done = close_slots(pos, used, slot_leg, pending_slots, fill, i, source, reason, campaign, trades, tc, orders, oc)
                realized += gain; cash += move; reductions += 1
                reduction_row = i; reduction_time = t; phase = 2
                if branch_mode:
                    is_valid=bool(branch_valid[i]);bd=int(branch_direction[i])
                    branch_class=0 if not is_valid else (1 if bd==0 else (2 if bd==d else 3))
                    adverse=is_valid and bd==-d
                    choose_signal=adverse if branch_mode==1 else (not adverse if branch_mode==2 else bool(branch_choice[i]))
                    chosen_restore=1 if choose_signal else 2
                    branch_row=i;branch_evidence=int(branch_source[i])
                    if brc>=len(branch_events):raise ValueError('復元分岐の記録上限です')
                    branch_events[brc]=np.array([i,campaign,reductions,chosen_restore,bd,branch_evidence,
                        int(is_valid),branch_class,branch_mode,branch_seed]);brc+=1
            else:
                qty = int(np.sum(pending_slots)); leg = used
                for slot in range(q0):
                    if pending_slots[slot] and (not alive[slot] or not restorable[slot] or slot_leg[slot] >= 0):
                        raise ValueError('復元資格がありません')
                pos[used] = np.array([d, fill, qty, 0., i]); used += 1
                orders[oc] = np.array([i, source, campaign, d, qty, fill, reason, 1.]); oc += 1
                cash -= d*qty*fill
                for slot in range(q0):
                    if pending_slots[slot]:
                        slot_leg[slot] = leg; restorable[slot] = False
                        slot_events[sc] = np.array([i, source, campaign, slot+1, 3., leg, d, fill, 1., reason, plan_row]); sc += 1
                phase = 0
            adjustment[ac] = np.array([i, campaign, 2., pending, pending_row, pending_evidence,
                                      np.sum(pending_slots), reason, mask, reductions, plan_row]); ac += 1
            barrier = i; pending = 0; pending_slots[:] = False; acted = True
        for fee_order in range(old_oc, oc):
            campaign_fees += np.floor(orders[fee_order,4] * losspar[12] + 1e-8) / losspar[13]
        inv = shadow_engine.inventory(pos, used)
        equity = realized+inv[2]*p-inv[3]
        max_error = max(max_error, abs(equity-(cash+inv[2]*p)))
        high_equity = max(high_equity, equity); dd = max(dd, high_equity-equity)
        min_equity = min(min_equity, equity); max_equity = max(max_equity, equity)
        maxlong = max(maxlong, inv[4]); maxshort = max(maxshort, inv[5]); maxgross = max(maxgross, inv[0]); maxnet = max(maxnet, abs(inv[2]))
        if inv[4] > cap or inv[5] > cap: raise ValueError('片方向保有上限違反です')
        if not closed:
            cycle_max = max(cycle_max, inv[0])
        if closed_now:
            net_campaign = realized-base-campaign_fees
            ix = 0 if d > 0 else 1
            direction_losses[ix] = direction_losses[ix]+1 if net_campaign < 0 else 0
            if losspar[18] > 0 and direction_losses[ix] >= 2:
                blocked[ix] = True; reset_seen[ix] = False; block_row[ix] = i
                block_events[xc] = np.array([i,campaign,1.,d,direction_losses[ix],i,ema_source[i],ema_peer_source[i]]); xc += 1
            guard_pending = False
            loss_streak = loss_streak+1 if net_campaign < 0 else 0
            cumulative_r += net_campaign/risk
            if losspar[9] > 0 and loss_streak >= losspar[9]:
                pause_until = end if losspar[10] < 0 else t+losspar[10]
                loss_streak = 0
                risk_events[rc] = np.array([i, campaign, 3., 60., i, -1., 0., early_peak, 0., cumulative_r]); rc += 1
            if losspar[11] > 0 and cumulative_r <= -losspar[11]:
                pause_until = end
                risk_events[rc] = np.array([i, campaign, 3., 61., i, -1., 0., early_peak, loss_streak, cumulative_r]); rc += 1
            early_action = 0
            cycles[cc] = np.array([campaign, entry_row, i, realized-base, risk, a, cycle_max, cycle_max, d, reason]); cc += 1
            if budget:
                e = realized-base
                budgets[bc] = np.array([i, campaign, 2., budget_row, risk, e, max(0., -e-risk), t-budget_time]); bc += 1
            alive[:] = False; restorable[:] = False; slot_leg[:] = -1
            pending = 0; pending_slots[:] = False; budget = False; d = 0; phase = 0; closed = True; last_exit = t
        # ----------------------------------------
        # ここから現在観測による次行予約。復元でも損益・R・期限は初期化しない。
        if not closed:
            e = equity-base
            if budget_enabled and e-(campaign_fees if losspar[8]<1. else 0.) <= -risk*losspar[8] and not budget:
                budget = True; budget_row = i; budget_time = t
                budgets[bc] = np.array([i, campaign, 1., i, risk, e, max(0., -e-risk), 0.]); bc += 1
                if pending:
                    mask = 0
                    for slot in range(q0):
                        if pending_slots[slot]: mask += 1 << slot
                    adjustment[ac] = np.array([i, campaign, 3., pending, pending_row, pending_evidence,
                                              np.sum(pending_slots), 32., mask, reductions, plan_row]); ac += 1
                    pending = 0; pending_slots[:] = False
                    phase = 2 if np.any(restorable) else 0
            early_peak = max(early_peak, d*(p-actual_anchor)/a)
            # ----------------------------------------
            # 実建玉の既払料金と残玉返済料を含めて、利益の最高点を追跡する。
            close_fee = np.floor(inv[0]*losspar[12]+1e-8)/losspar[13]
            net_liquidation = e-campaign_fees-close_fee
            guard_peak = max(guard_peak,net_liquidation)
            if losspar[15] > 0 and guard_peak >= losspar[16]*risk:
                first_guard = not np.isfinite(guard_floor)
                guard_floor = max(guard_floor,losspar[17]*guard_peak)
                if first_guard:
                    guard_events[gc] = np.array([i,campaign,1.,i,net_liquidation,guard_peak,guard_floor,inv[0],d,70.]); gc += 1
                if net_liquidation <= guard_floor and not guard_pending and not budget:
                    guard_pending = True; guard_row = i; early_action = 0
                    if pending:
                        mask = 0
                        for slot in range(q0):
                            if pending_slots[slot]: mask += 1 << slot
                        adjustment[ac] = np.array([i,campaign,3.,pending,pending_row,pending_evidence,np.sum(pending_slots),70.,mask,reductions,plan_row]); ac += 1
                        pending = 0; pending_slots[:] = False
                    guard_events[gc] = np.array([i,campaign,2.,i,net_liquidation,guard_peak,guard_floor,inv[0],d,70.]); gc += 1
            # ----------------------------------------
            # 当行までの進捗と新しい公開根拠だけで、次行用の損失制御を予約する。
            if not acted and not pending and not budget and not early_action and not guard_pending:
                fresh_bad = raw_valid[i] and raw_bad[i] == -d and raw_source[i] > barrier and raw_source[i] > entry_row
                bad_failed = losspar[0] > 0 and fresh_bad and early_peak < losspar[1] and d*(p-actual_anchor)/a <= -losspar[2]
                timed_failed = losspar[3] > 0 and t-time[entry_row] >= losspar[3] and early_peak < losspar[4] and d*(p-actual_anchor)/a <= -losspar[5]
                ema_failed = losspar[6] > 0 and ema_source[i] > entry_row and ema_direction[i] != d and d*(p-actual_anchor)/a <= -losspar[7]
                action = 0; why = 0; evidence_row = i
                if bad_failed:
                    action = int(losspar[0]); why = 50; evidence_row = raw_source[i]
                elif timed_failed:
                    action = int(losspar[14]); why = 51
                elif ema_failed:
                    action = 2; why = 52; evidence_row = ema_source[i]
                if action == 1 and reductions < maximum:
                    count = min(int(np.sum(alive))-1, max(1, int(np.floor(fraction*np.sum(alive)))))
                    if count > 0:
                        pending = -1; pending_row = i; pending_evidence = evidence_row; reduce_reason = why
                        for slot in range(q0):
                            if count > 0 and alive[slot] and slot_leg[slot] >= 0:
                                pending_slots[slot] = True; count -= 1
                        phase = 1
                        risk_events[rc] = np.array([i, campaign, 1., why, i, evidence_row, np.sum(pending_slots), early_peak, loss_streak, cumulative_r]); rc += 1
                elif action == 2:
                    early_action = why; early_row = i; early_evidence = evidence_row
                    risk_events[rc] = np.array([i, campaign, 1., why, i, evidence_row, inv[0], early_peak, loss_streak, cumulative_r]); rc += 1
            if kind == 3 and not acted and not pending and not budget and not early_action and not guard_pending:
                evidence = -1
                if phase == 0 and reductions < maximum and bad[i] == -d and bad_source[i] > barrier:
                    pending = -1; evidence = bad_source[i]; reduce_reason = 30
                    count = min(int(np.sum(alive))-1, max(1, int(np.floor(fraction*np.sum(alive)))))
                    for slot in range(q0):
                        if count > 0 and alive[slot] and slot_leg[slot] >= 0:
                            pending_slots[slot] = True; count -= 1
                    phase = 1
                elif phase == 2 and chosen_restore and good_source[i] > barrier and good_source[i] > reduction_row:
                    fresh = (good[i] == d and (branch_mode==0 or good_valid[i])) if chosen_restore == 1 else (
                        good_valid[i] and t >= reduction_time+restore_seconds and time[good_source[i]] >= reduction_time+restore_seconds)
                    if fresh and np.any(restorable):
                        pending = 1; evidence = good_source[i]; pending_slots[:] = restorable; phase = 3
                if pending:
                    pending_row = i; pending_evidence = evidence; mask = 0
                    for slot in range(q0):
                        if pending_slots[slot]: mask += 1 << slot
                    adjustment[ac] = np.array([i, campaign, 1., pending, i, evidence, np.sum(pending_slots),
                                              30. if pending < 0 else 31., mask, reductions, plan_row]); ac += 1
        # ----------------------------------------
        # 買い・売り別の連敗停止。双方の停止後の新資料で失効と再成立を確認する。
        if losspar[18] > 0 and ema_valid[i]:
            for ix in range(2):
                side = 1 if ix == 0 else -1
                if blocked[ix] and ema_source[i] > block_row[ix] and ema_peer_source[i] > block_row[ix]:
                    if not reset_seen[ix] and ema_direction[i] != side:
                        reset_seen[ix] = True; reset_own[ix] = ema_source[i]; reset_peer[ix] = ema_peer_source[i]
                        block_events[xc] = np.array([i,campaign,2.,side,direction_losses[ix],block_row[ix],ema_source[i],ema_peer_source[i]]); xc += 1
                    elif reset_seen[ix] and ema_direction[i] == side and ema_source[i] > reset_own[ix] and ema_peer_source[i] > reset_peer[ix]:
                        blocked[ix] = False; reset_seen[ix] = False; direction_losses[ix] = 0
                        block_events[xc] = np.array([i,campaign,3.,side,0.,block_row[ix],ema_source[i],ema_peer_source[i]]); xc += 1
        if gc >= len(guard_events)-5 or xc >= len(block_events)-5:
            raise ValueError('利益保護又は再開待ちの証跡上限です')
        if detail:
            close_fee = np.floor(inv[0]*losspar[12]+1e-8)/losspar[13]
            net_liquidation = equity-base-campaign_fees-close_fee if campaign >= 0 else 0.
            guard_curve[i] = np.array([guard_peak,guard_floor,net_liquidation,int(guard_pending),int(blocked[0]),int(blocked[1]),direction_losses[0],direction_losses[1]])
            branch_curve[i]=np.array([chosen_restore,branch_row,branch_evidence,branch_class])
            curve[i] = np.array([equity, realized, inv[4], inv[5], dd, cash, inv[2], campaign])
            if closed and atr_curve[i, 0] != 0:
                atr_curve[i, 0] = 0.; atr_curve[i, 1:9] = np.nan; atr_curve[i, 5] = 0.; atr_curve[i, 10] = -1.
            control[i] = np.array([shadow_campaign, campaign, phase, d, planned_qty, inv[0], np.sum(restorable), reductions,
                pending, pending_row if pending else -1, pending_evidence if pending else -1,
                equity-base if campaign >= 0 else 0., risk if campaign >= 0 else 0.,
                int(budget), budget_row if budget else -1, int(closed), barrier, reduction_row, plan_row,
                max(0., -(equity-base)-risk) if campaign >= 0 else 0.])
            for slot in range(q0):
                slot_curve[i, slot] = int(alive[slot])+2*int(slot_leg[slot] >= 0)+4*int(restorable[slot])
    stats = np.array([realized, dd, maxlong, maxshort, maxgross, maxnet, max_error, min_equity, max_equity, inv[0], 0.])
    return (trades[:tc], cycles[:cc], curve, orders[:oc], stats, atr_curve,
            control, slot_curve, slot_events[:sc], adjustment[:ac], budgets[:bc], branch_events[:brc], branch_curve, risk_events[:rc], guard_curve, guard_events[:gc], block_events[:xc])

