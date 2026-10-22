"""枠イベントと入力根拠から、注文器を使わず状態・同約定両建てを検算する。"""

from __future__ import annotations

import numpy as np
import integration_shadow_oracle as shadow_oracle


def close(a: object, b: object, label: str) -> None:
    """機能: 有限値と形状を確認して会計値を絶対誤差だけで比較する。

    引数: a/b (object)、label (str)。返り値: なし (None)。
    """
    left, right = np.asarray(a), np.asarray(b)
    assert left.shape == right.shape and np.isfinite(left).all() and np.isfinite(right).all(), label
    assert np.all(np.abs(left-right) <= 1e-6), label


def audit(ready: dict, result: dict, config: dict, policy: dict, bad: np.ndarray, bad_source: np.ndarray,
          good: np.ndarray, good_source: np.ndarray, good_valid: np.ndarray, curves: dict, *,
          state: np.ndarray, budget_enabled: bool=True, min_delay_seconds: float=0., observed_fill: bool=False,
          branch_direction: np.ndarray | None=None, branch_source: np.ndarray | None=None,
          branch_valid: np.ndarray | None=None, branch_mode: str="fixed",
          branch_choice: np.ndarray | None=None, branch_seed: int | None=None) -> dict:
    """機能: 全枠・調整・予算・公開順と両建て経済同値を独立検算する。

    引数: ready/result/config/policy/curves (dict)、各方向・根拠・品質 (ndarray)。
    返り値: 検査件数と合格フラグ (dict)。影の最終台帳は答え合わせだけに使用する。
    """
    prices, times = ready['last'], ready['time_s']
    n, q0 = len(prices), int(config['initial_qty'])
    original, cycles = result['shadow'], result['cycles']
    slots, control = result['slot_curve'], result['control_curve']
    events, adjustments, budgets = (result[k] for k in ('slot_events', 'adjustment_events', 'budget_events'))
    transmitted=shadow_oracle.audit(ready,original,config,state,min_delay_seconds,observed_fill)
    raw_source=original['execution_plans'][:,33]
    effective_source=np.where(np.isfinite(raw_source),raw_source,-1).astype(np.int64)
    restore_code={'none':0,'signal':1,'timer':2}[policy['restore_mode']]
    branch_codes={'fixed':0,'adverse_signal':1,'reverse':2,'random':3}
    modes=np.full(n,restore_code,np.int64)
    expected_branch_curve=np.tile(np.asarray([restore_code,-1,-1,0.]),(n,1))
    marks={int(c[1]):np.asarray([restore_code,-1,-1,0.]) for c in cycles}
    branch_expected=[]
    directions={int(c[0]):int(c[8]) for c in cycles}
    branch_number={}
    if branch_mode!='fixed':
        for event in adjustments[(adjustments[:,2]==2)&(adjustments[:,3]==-1)]:
            row,campaign=int(event[0]),int(event[1]);d=directions[campaign]
            valid=bool(branch_valid[row]);direction_at=int(branch_direction[row]);source=int(branch_source[row])
            assert -1<=source<=row and (not valid or source>=0)
            classification=0 if not valid else 1 if direction_at==0 else 2 if direction_at==d else 3
            adverse=valid and direction_at==-d
            signal=adverse if branch_mode=='adverse_signal' else not adverse if branch_mode=='reverse' else bool(branch_choice[row])
            mode=1 if signal else 2;branch_number[campaign]=branch_number.get(campaign,0)+1
            branch_expected.append([row,campaign,branch_number[campaign],mode,direction_at,source,int(valid),classification,
                                   branch_codes[branch_mode],-1 if branch_seed is None else branch_seed])
            marks[row]=np.asarray([mode,row,source,classification])
    for row in sorted(marks):
        expected_branch_curve[row:]=marks[row]
    close(result['branch_events'],np.asarray(branch_expected,dtype=float).reshape((-1,10)),'全分岐の独立判断')
    close(result['branch_curve'],expected_branch_curve,'全行の分岐保持')
    modes=expected_branch_curve[:,0].astype(np.int64)
    assert slots.shape == (n, q0) and control.shape == (n, 20)
    assert np.isfinite(prices).all() and (prices > 0).all()
    assert np.all(np.diff(events[:, 0]) >= 0) if len(events) else True
    expected_slots = np.zeros((n, q0), np.int8)
    active = np.zeros(n, bool); direction = np.zeros(n, np.int8)
    campaign_base = np.zeros(n); risk_series = np.zeros(n)
    barrier_marks = np.full(n, -1, np.int64); reduction_marks = np.full(n, -1, np.int64)
    acted = np.zeros(n, bool); pending_before = np.zeros(n, bool); expected_budget = np.zeros(n, bool)
    reductions_count = np.zeros(n, np.int64)
    hedge_changes = np.zeros((n, 3))
    original_cycles = {int(c[0]): c for c in original['cycles']}
    assert {int(c[0]) for c in cycles} == set(original_cycles) and len(cycles) == len(original_cycles)
    original_orders = original['orders']
    original_actions = {(int(o[2]), int(o[0]), int(o[6])): float(o[5]) for o in original_orders}
    opens = result['orders'][result['orders'][:, 6] == 20]
    old_opens = original_orders[original_orders[:, 6] == 20]
    close(opens[:, [0,1,2,3,5,6,7]], old_opens[:, [0,1,2,3,5,6,7]], '元組の初回一致')
    slot_order_totals = {}
    for cycle in cycles:
        campaign, start, end = map(int, cycle[:3]); d = int(cycle[8])
        old = original_cycles[campaign]
        assert start == old[1] and end <= old[2] and d == old[8]
        a = float(original['execution_plans'][start,24]); risk = q0*a
        close(cycle[4:6], np.asarray([risk, a]), '初回ATRと元R')
        active[start:end] = True; direction[start:end+1] = d
        base = curves['realized'][start-1]
        campaign_base[start:end+1] = base; risk_series[start:end+1] = risk
        selected = np.ones(q0, bool)
        if policy['kind'] == 'static_core': selected[:int(np.floor(policy['reduce_fraction']*q0))] = False
        elif policy['kind'] == 'static_split':
            small = q0-int(np.floor(policy['reduce_fraction']*q0)); count = small//2
            selected[:] = False; selected[:count] = True; selected[q0-(small-count):] = True
        ce = events[events[:, 2] == campaign]
        assert len(ce) and int(ce[0,0]) == start
        initial = ce[ce[:, 4] == 1]
        assert set(initial[:,3].astype(int)) == set(np.flatnonzero(selected)+1)
        assert np.all(initial[:,0] == start)
        alive, held, debt = np.ones(q0, bool), np.zeros(q0, bool), np.zeros(q0, bool)
        leg = np.full(q0, -1, np.int64)
        core, cover = np.ones(q0, bool), ~selected.copy()
        entry_price = float(old_opens[old_opens[:,2] == campaign][0,5])
        hedge_changes[start,0] -= d*q0*entry_price
        hedge_changes[start,1] += d*q0
        hedge_changes[start,2] += q0
        hedge_changes[start,0] += d*int(cover.sum())*entry_price
        hedge_changes[start,1] -= d*int(cover.sum())
        hedge_changes[start,2] += int(cover.sum())
        last_row = start
        for row_value in np.unique(ce[:,0]):
            row = int(row_value)
            if row > last_row: expected_slots[last_row:row] = alive.astype(np.int8)+2*held+4*debt
            group = ce[ce[:,0] == row]
            assert len({int(e[3]) for e in group}) == len(group), '同一行枠重複'
            for ev in group:
                r, source, cid, slot, event, current_leg, side, price, quantity, reason, plan_row = ev
                j, event, current_leg, reason = int(slot)-1, int(event), int(current_leg), int(reason)
                assert r == row and cid == campaign and side == d and 0 <= source < row and 0 <= j < q0
                assert plan_row == effective_source[row] and -1 <= plan_row < row
                assert quantity in (0,1) and np.isfinite(price)
                if event == 1:
                    assert row == start and selected[j] and not held[j] and reason == 20 and quantity == 1
                    held[j] = True; leg[j] = current_leg
                elif event == 2:
                    assert alive[j] and held[j] and not debt[j] and current_leg == leg[j] and reason == 30 and quantity == 1
                    held[j] = False; debt[j] = True; leg[j] = -1
                    assert core[j] and not cover[j]
                    cover[j] = True; hedge_changes[row] += [d*price, -d, 1]
                elif event == 3:
                    assert alive[j] and debt[j] and not held[j] and current_leg >= 0 and reason == 31 and quantity == 1
                    held[j] = True; debt[j] = False; leg[j] = current_leg
                    assert core[j] and cover[j]
                    cover[j] = False; hedge_changes[row] += [-d*price, d, -1]
                else:
                    assert event in (4,5) and alive[j] and bool(quantity) == held[j] and current_leg == leg[j]
                    if event == 4: assert j < q0//2 and reason == 7
                    else: assert row == end
                    if core[j]: hedge_changes[row] += [d*price, -d, -1]; core[j] = False
                    if cover[j]: hedge_changes[row] += [-d*price, d, -1]; cover[j] = False
                    alive[j] = held[j] = debt[j] = False; leg[j] = -1
                if quantity:
                    opening = 1 if event in (1,3) else 0
                    key = (row,int(source),campaign,d if opening else -d,float(price),reason,opening)
                    slot_order_totals[key] = slot_order_totals.get(key,0)+1
                if reason not in (30,31,32):
                    assert original_actions[(campaign,row,reason)] == price, '元条件の約定価格一致'
            acted[row] = True; barrier_marks[row] = row
            expected_slots[row] = alive.astype(np.int8)+2*held+4*debt
            last_row = row
        assert last_row == end and not alive.any() and not held.any() and not debt.any()
        assert not core.any() and not cover.any()
        cb = budgets[budgets[:,1] == campaign]
        requests = cb[cb[:,2] == 1]; completions = cb[cb[:,2] == 2]
        path = curves['equity'][start:end] - base
        breaches = np.flatnonzero(path <= -risk)
        if budget_enabled and len(breaches):
            first = start+int(breaches[0])
            assert len(requests) == len(completions) == 1 and requests[0,0] == first
            assert completions[0,0] == end
            expected_budget[first:end] = True
            next_row=max(first+1,int(np.searchsorted(times,times[first]+min_delay_seconds,side='left')))
            while (campaign,next_row,7) in original_actions:next_row+=1
            original_full=[r for cid,r,reason in original_actions if cid==campaign and first<r and reason in (1,2,8,9)]
            expected_end=min([next_row]+original_full)
            assert end==expected_end,'成熟予算又は先行元全返済で終了する' 
        else: assert not len(cb)
        for event in cb:
            row, _, code, source, saved_risk, equity, excess, elapsed = event
            row, source, code = int(row), int(source), int(code)
            assert source == requests[0,0] and source <= row <= end
            close(np.asarray([saved_risk,equity,excess,elapsed]), np.asarray([risk,
                curves['equity'][row]-base,max(0., -(curves['equity'][row]-base)-risk),times[row]-times[source]]), '予算の全実現含みと超過')
            if code == 3: assert (campaign,row,7) in original_actions and row < end
        ca = adjustments[adjustments[:,1] == campaign]
        count = 0
        for reservation in ca[ca[:,2] == 1]:
            row, _, _, kind, source, evidence, qty, reason, mask, saved_count, plan_row = reservation
            row, kind, evidence, mask = int(row), int(kind), int(evidence), int(mask)
            assert source == row and plan_row == effective_source[row] and plan_row < row
            assert start < row < end and not acted[row] and not expected_budget[row]
            prior_barrier = max([start]+[int(e[0]) for e in ce if e[0] < row])
            assert prior_barrier < evidence <= row
            before = expected_slots[row]
            live = (before&1)!=0; owned = (before&2)!=0; empty = (before&4)!=0
            if kind == -1:
                assert policy['kind']=='dynamic' and not empty.any() and bad[row] == -d and bad_source[row] == evidence
                number = min(int(live.sum())-1,max(1,int(np.floor(policy['reduce_fraction']*live.sum()))))
                chosen = np.flatnonzero(live&owned)[:number]
            else:
                assert kind == 1 and modes[row]!=0 and empty.any() and good_source[row] == evidence
                previous = ca[(ca[:,0] < row)&(ca[:,2] == 2)&(ca[:,3] == -1)]
                assert len(previous) and evidence > previous[-1,0]
                if modes[row]==1: assert good[row] == d and (branch_mode=='fixed' or good_valid[row])
                else:
                    deadline = times[int(previous[-1,0])] + policy['restore_seconds']
                    assert good_valid[row] and times[row] >= deadline and times[evidence] >= deadline
                chosen = np.flatnonzero(empty)
            assert qty == len(chosen) > 0 and mask == sum(1 << int(j) for j in chosen)
            outcomes = ca[(ca[:,4] == row)&np.isin(ca[:,2],(2,3))]
            assert len(outcomes) == 1
            outcome = outcomes[0]; resolution = int(outcome[0])
            mature=max(row+1,int(np.searchsorted(times,times[row]+min_delay_seconds,side='left')))
            original_next=[r for cid,r,code in original_actions if cid==campaign and r>row and 1<=code<=14]
            budget_cancel=[int(b[0]) for b in requests if row<b[0]<mature]
            expected_resolution=min([mature]+original_next+budget_cancel)
            assert resolution==expected_resolution and outcome[3] == kind and outcome[5] == evidence and outcome[6] == qty and outcome[8] == mask
            assert saved_count==int(np.sum((ca[:,2]==2)&(ca[:,3]==-1)&(ca[:,0]<row)))
            assert outcome[9]==int(np.sum((ca[:,2]==2)&(ca[:,3]==-1)&(ca[:,0]<=resolution)))
            pending_before[row+1:resolution] = True
            if outcome[2] == 2:
                assert not any((campaign,resolution,r) in original_actions for r in range(1,15))
                count += kind == -1
                if kind == -1: reduction_marks[resolution] = resolution
            else: assert outcome[7] in (7,32) or (campaign,resolution,int(outcome[7])) in original_actions
            assert count <= policy['max_reductions']
        filled = ca[(ca[:,2] == 2)&(ca[:,3] == -1)]
        for i,event in enumerate(filled):
            begin = int(event[0]); finish = int(filled[i+1,0]) if i+1<len(filled) else end+1
            reductions_count[begin:finish] = i+1
    assert np.array_equal(slots, expected_slots), '全行の枠生存・保有・復元資格'
    # ----------------------------------------
    # 約定したイベントだけでなく、条件を満たした予約の脱落も全行で拒否する。
    barrier = np.maximum.accumulate(barrier_marks)
    latest_reduction = np.maximum.accumulate(reduction_marks)
    debt_count = ((slots&4)!=0).sum(axis=1)
    expected_decisions = np.zeros(n, np.int8)
    if policy['kind'] == 'dynamic':
        allowed = active & ~acted & ~expected_budget & ~pending_before
        reduce = allowed & (debt_count == 0) & (reductions_count < policy['max_reductions'])
        reduce &= (bad == -direction) & (bad_source > barrier)
        expected_decisions[reduce] = -1
        if np.any(modes!=0):
            restore = allowed & (debt_count > 0) & (good_source > barrier) & (good_source > latest_reduction)
            deadline=times[np.maximum(0,latest_reduction)]+policy['restore_seconds']
            signal=(modes==1)&(good==direction)
            if branch_mode!='fixed':signal &= good_valid
            timer=(modes==2)&good_valid&(times>=deadline)&(times[np.maximum(0,good_source)]>=deadline)
            restore &= signal|timer
            expected_decisions[restore] = 1
    actual_decisions = np.zeros(n,np.int8)
    decisions = adjustments[adjustments[:,2] == 1]
    assert len(set(decisions[:,0].astype(int))) == len(decisions)
    actual_decisions[decisions[:,0].astype(int)] = decisions[:,3].astype(np.int8)
    assert np.array_equal(expected_decisions, actual_decisions), '全行の予約有無・方向・脱落'
    # 全予約の保持・取消も約定ログと独立の区間で復元する。
    expected_pending=np.zeros((n,3));expected_pending[:,1:]=-1
    for reservation in decisions:
        row=int(reservation[0]);campaign=int(reservation[1])
        outcome=adjustments[(adjustments[:,1]==campaign)&(adjustments[:,4]==row)&np.isin(adjustments[:,2],(2,3))]
        finish=int(outcome[0,0]);expected_pending[row:finish]=[reservation[3],row,reservation[5]]
    close(control[:,8:11],expected_pending,'全行の調整予約保持')
    phase=np.where(active,np.where(debt_count>0,2,0),0)
    phase[expected_pending[:,0]<0]=1;phase[expected_pending[:,0]>0]=3
    close(control[:,2],phase,'全行の減量状態')
    close(control[:,15],(~active).astype(float),'全行の組終了状態')
    for order in result['orders']:
        row,source=int(order[0]),int(order[1])
        assert source<row and times[row]>=times[source]+min_delay_seconds-1e-8
        assert times[row]<ready.get('session_close',ready['limit']+600.)
    close(control[:,5], ((slots&2)!=0).sum(axis=1).astype(float), '全行実保有枚数')
    close(control[:,6], ((slots&4)!=0).sum(axis=1).astype(float), '全行復元資格枚数')
    close(control[active,7], reductions_count[active].astype(float), '実行済み減量回数')
    assert np.array_equal(control[:,13].astype(bool), expected_budget), '予算予約保持'
    order_totals = {}
    for order in result['orders']:
        row,source,cid,side,qty,price,reason,opening=order
        key=(int(row),int(source),int(cid),int(side),float(price),int(reason),int(opening))
        order_totals[key]=order_totals.get(key,0)+int(qty)
    assert slot_order_totals == order_totals, '全枠の約定と全注文の数量一致'
    hedge = np.cumsum(hedge_changes,axis=0)
    close(hedge[:,0], curves['cash'], '両建て写像の全行現金')
    close(hedge[:,1], curves['long']-curves['short'], '両建て写像の全行純数量')
    close(hedge[:,0]+hedge[:,1]*prices, curves['equity'], '両建て写像の全行時価')
    assert hedge[-1,1] == hedge[-1,2] == 0
    assert np.all((hedge[:,2]+abs(hedge[:,1]))/2 <= config['audit_cap']), '両建て片方向上限'
    return dict(影の独立公開と執行=transmitted,全分岐独立一致=True,全伝達遅延一致=True,
        全枠会計一致=True, 全予約と新根拠一致=True, 元終了以前=True,
        同約定両建て全行一致=True, 全予算予約一致=True, 元組数=len(cycles), 枠イベント数=len(events),
        調整イベント数=len(adjustments), 予算イベント数=len(budgets), 原本行数=n)
