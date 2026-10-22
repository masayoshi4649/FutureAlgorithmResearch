"""元A0の前行有効計画を並行使用し、同一組の数量減量・復元だけを行う。"""

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
             branch_source, branch_valid, branch_choice, branch_mode, branch_seed):
    """機能: 前行影計画と現在価格から約定を独立判定し、数量枠を管理する。

    引数: 原本・影計画・方向・根拠(ndarray)、数量・方針(int)、閾値(float)、約定・詳細(bool)。
    返り値: 旧6結果と枠・調整・予算・管理状態の証跡 (tuple[ndarray,...])。
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
    for i in range(n):
        if (used+1 >= len(pos) or tc+q0 >= len(trades) or oc+q0+1 >= len(orders)
                or cc+1 >= len(cycles) or sc+2*q0 >= len(slot_events)
                or ac+3 >= len(adjustment) or bc+3 >= len(budgets)):
            raise ValueError('数量調整台帳の保存上限に達しました')
        p = price[i]; t = time[i]
        if not np.isfinite(p) or p <= 0:
            if detail and i:
                control[i] = control[i-1]; slot_curve[i] = slot_curve[i-1]; branch_curve[i]=branch_curve[i-1]
                if closed and atr_curve[i, 0] != 0:
                    atr_curve[i, 0] = 0.; atr_curve[i, 1:9] = np.nan; atr_curve[i, 5] = 0.; atr_curve[i, 10] = -1.
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
            elif int(plan[21]) and not bool(plan[30]) and t < plan[23] and t < end-cutoff*60:
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
            fill = original_fill; reason = original_reason
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
            else:
                closed_now = True
        elif not is_entry and not closed and budget and i>budget_row and t>=budget_time+min_delay_seconds-1e-9:
            fill = p; reason = 32; source = budget_row; selected[:] = True
            for slot in range(q0):
                if alive[slot]:
                    slot_events[sc] = np.array([i, source, campaign, slot+1, 5., slot_leg[slot], d,
                                               fill, 1. if slot_leg[slot] >= 0 else 0., reason, plan_row]); sc += 1
            tc, oc, gain, move, done = close_slots(pos, used, slot_leg, selected, fill, i, source, reason, campaign, trades, tc, orders, oc)
            realized += gain; cash += move; acted = True; closed_now = True
        elif not is_entry and not closed and pending and not budget and i>pending_row and t>=time[pending_row]+min_delay_seconds-1e-9:
            fill = p; reason = 30 if pending < 0 else 31; source = pending_row
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
            if budget_enabled and e <= -risk and not budget:
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
            if kind == 3 and not acted and not pending and not budget:
                evidence = -1
                if phase == 0 and reductions < maximum and bad[i] == -d and bad_source[i] > barrier:
                    pending = -1; evidence = bad_source[i]
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
        if detail:
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
            control, slot_curve, slot_events[:sc], adjustment[:ac], budgets[:bc], branch_events[:brc], branch_curve)


def run(ready: dict, state: np.ndarray, config: dict, bad: np.ndarray, bad_source: np.ndarray,
        good: np.ndarray, good_source: np.ndarray, policy: dict, observed_fill: bool = False,
        detail: bool = True, shadow: dict | None = None, *, good_valid: np.ndarray | None = None, budget_enabled: bool=True,
        branch_direction: np.ndarray | None=None, branch_source: np.ndarray | None=None,
        branch_valid: np.ndarray | None=None, branch_mode: str="fixed",
        branch_choice: np.ndarray | None=None, branch_seed: int | None=None,
        min_delay_seconds: float=0.) -> dict:
    """機能: 同じ元A0組の数量操作を、前行条件と新情報だけで再生する。

    引数: ready/config/policy/任意shadow(dict)、方向(ndarray[int8])、source(ndarray[int64])、約定・詳細(bool)。
    good_valid(ndarray[bool]|None)は時計復元の新しい有効自市場公開行。方向0でも真になり得る。
    budget_enabled(bool)は追加実損益R退出のみの有効性。min_delay_seconds(float)は注文伝達の秒数。
    branch_direction/source/valid(ndarray|None)は選択用B01の公開方向・ready行・品質。
    branch_mode(str)はfixed/adverse_signal/reverse/random、choice(int8列|None)は0時計/1信号。
    branch_seed(int|None)は入力側の固定乱数種の記録。engine側では乱数を生成しない。
    返り値: 旧6結果、準備2、旧証跡、branch_events/curve、独立影(dict)。損益は価格×枚数。
    shadowは全利用入力SHAが同一の場合だけ再利用可。監査では毎回影から再生成する。
    """
    n = len(ready['last'])
    if not isinstance(observed_fill, (bool, np.bool_)) or not isinstance(detail, (bool, np.bool_)):
        raise ValueError('約定モデルと詳細指定は真偽値が必要です')
    for name, value in (('state', state), ('bad', bad), ('good', good)):
        if not isinstance(value, np.ndarray) or value.dtype != np.int8 or value.shape != (n,) or not np.isin(value, (-1, 0, 1)).all():
            raise ValueError(name+'は原本行対応のint8方向列が必要です')
    for name, value, direction in (('bad_source', bad_source, bad), ('good_source', good_source, good)):
        if not isinstance(value, np.ndarray) or value.dtype != np.int64 or value.shape != (n,) or np.any(value < -1) or np.any(value > np.arange(n)) or np.any((direction != 0) & (value < 0)):
            raise ValueError(name+'は過去又は当行の根拠行が必要です')
    branch_modes={'fixed':0,'adverse_signal':1,'reverse':2,'random':3}
    if branch_mode not in branch_modes:raise ValueError('復元分岐方式が不正です')
    if not isinstance(budget_enabled,(bool,np.bool_)):raise ValueError('追加R退出は真偽値です')
    if isinstance(min_delay_seconds,(bool,np.bool_)) or min_delay_seconds not in (0.,1.,5.,15.):
        raise ValueError('注文伝達遅延は0/1/5/15秒です')
    supplied=(branch_direction,branch_source,branch_valid)
    if branch_mode!='fixed' and any(value is None for value in supplied):
        raise ValueError('復元分岐にはB01方向・source・有効性が必要です')
    if branch_direction is None:branch_direction=np.zeros(n,np.int8)
    if branch_source is None:branch_source=np.full(n,-1,np.int64)
    if branch_valid is None:branch_valid=np.zeros(n,np.bool_)
    for value,dtype in ((branch_direction,np.int8),(branch_source,np.int64),(branch_valid,np.bool_)):
        if not isinstance(value,np.ndarray) or value.dtype!=dtype or value.shape!=(n,):
            raise ValueError('復元分岐列の型・長さが不正です')
    if not np.isin(branch_direction,(-1,0,1)).all() or (branch_source< -1).any() or (branch_source>np.arange(n)).any():
        raise ValueError('復元分岐列に未来source又は不正方向があります')
    if (branch_valid & (branch_source<0)).any():raise ValueError('有効分岐に公開sourceが必要です')
    if branch_mode=='random' and (type(branch_seed) is not int or not 0<=branch_seed<64 or branch_choice is None):
        raise ValueError('乱数分岐には固定seedと入力選択列が必要です')
    if branch_choice is None:branch_choice=np.zeros(n,np.int8)
    if not isinstance(branch_choice,np.ndarray) or branch_choice.dtype!=np.int8 or branch_choice.shape!=(n,) or not np.isin(branch_choice,(0,1)).all():
        raise ValueError('乱数分岐選択列はint8の0/1です')
    if branch_mode!='fixed' and policy['kind']!='dynamic':raise ValueError('復元分岐は動的数量だけに指定できます')
    modes = {'baseline': 0, 'static_core': 1, 'static_split': 2, 'dynamic': 3}
    restores = {'none': 0, 'signal': 1, 'timer': 2}
    if policy['kind'] not in modes or policy['restore_mode'] not in restores:
        raise ValueError('未定義の数量方針です')
    if policy['kind'] != 'baseline' and policy['reduce_fraction'] not in (.25, .5):
        raise ValueError('減量割合は25%又は50%です')
    if policy['kind'] == 'dynamic' and policy['max_reductions'] not in (1, 3):
        raise ValueError('減量回数は1又は3です')
    if policy['kind'] != 'dynamic' and (policy['max_reductions'] != 0 or policy['restore_mode'] != 'none'):
        raise ValueError('固定数量対照では復元と反復を設定できません')
    if policy['kind'] == 'dynamic' and policy['restore_mode'] == 'none' and policy['max_reductions'] != 1:
        raise ValueError('減量のみの対照は1回に限ります')
    if policy.get('restore_seconds', 120.) not in (96.,120.,144.):
        raise ValueError('時計復元は96/120/144秒です')
    if good_valid is None:
        if policy['restore_mode'] == 'timer' or branch_mode!='fixed': raise ValueError('時計又は分岐復元には有効公開列が必要です')
        good_valid = np.zeros(n, dtype=np.bool_)
    if not isinstance(good_valid, np.ndarray) or good_valid.dtype != np.bool_ or good_valid.shape != (n,):
        raise ValueError('有効公開列は原本行対応boolが必要です')
    if shadow is None:
        shadow = make_shadow(ready, state, config, observed_fill, min_delay_seconds)
    elif shadow.get('input_sha256') != input_digest(ready, state, config, observed_fill, min_delay_seconds):
        raise ValueError('影キャッシュの入力又は約定モデルが違います')
    if shadow['plans'].shape != (n, len(PLAN_COLUMNS)) or shadow['execution_plans'].shape != (n,len(PLAN_COLUMNS)):
        raise ValueError('影の計画列が不正です')
    execution=shadow['execution_plans'];present=np.isfinite(execution[:,33])
    references=execution[present,33];rows=np.flatnonzero(present)
    if (references!=np.floor(references)).any() or (references<0).any() or (references>=rows).any():
        raise ValueError('有効注文計画に未来又は不正な公開行があります')
    indices=references.astype(np.int64)
    if (ready['time_s'][indices]+min_delay_seconds>ready['time_s'][rows]+1e-9).any():
        raise ValueError('未成熟の注文計画があります')
    values = simulate(ready['time_s'], ready['last'], shadow['plans'], shadow['execution_plans'], shadow['atr_curve'], bad, bad_source,
        good, good_source, good_valid, ready['limit'], config['entry_cutoff_min'], int(config['initial_qty']),
        int(config['audit_cap']), modes[policy['kind']], policy['reduce_fraction'], restores[policy['restore_mode']],
        int(policy['max_reductions']), policy.get('restore_seconds', 120.), observed_fill, detail, bool(budget_enabled), float(min_delay_seconds), branch_direction, branch_source,
        branch_valid, branch_choice, branch_modes[branch_mode], -1 if branch_seed is None else branch_seed)
    result = dict(zip(FIELDS+('control_curve', 'slot_curve', 'slot_events', 'adjustment_events', 'budget_events', 'branch_events', 'branch_curve'), values))
    result['prepare_events'] = shadow['prepare_events']
    result['entry_preparations'] = shadow['entry_preparations']
    result['shadow'] = shadow
    return result
