"""元GUの実建玉会計へ未使用枠の順行追加と料金込み床を挿入する。"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1]/'wave_v85/engine.py'


def replace_once(text, old, new):
    """
    機能: 読取専用の旧コードの一箇所だけを新領域用に置換する。
    引数: text/old/new(str)。
    返り値: str。
    """
    assert text.count(old) == 1, (old,text.count(old))
    return text.replace(old,new,1)


def build():
    """
    機能: 元GU不変対照を含む、初回配分・追加・床の実装を生成する。
    引数: なし。
    返り値: str の生成先。
    """
    text = SOURCE.read_text(encoding='utf-8')
    text = replace_once(text,'import exit_shadow_integrated as shadow_engine',
        'import exit_shadow_integrated as shadow_engine\nfrom wave86_shadow import rounded')
    text = replace_once(text,'quiet=None, quiet_force=None, quiet_not_before=None):',
        'quiet=None, quiet_force=None, quiet_not_before=None, initial_qty=0, add_mode=0, add_step=0., floor_mode=0, tick=1.):')
    text = replace_once(text,'    n = len(price)','''    n = len(price)
    initial = q0 if initial_qty == 0 else int(initial_qty)
    slots = q0 if initial == q0 and add_mode == 0 else cap
    if initial < 1 or initial > cap: raise ValueError('初回数量が不正です')
    if add_mode not in (0,1,2) or floor_mode not in (0,1,2): raise ValueError('追加又は床の種類が不正です')
    if add_mode and add_step <= 0: raise ValueError('追加段差が不正です')
    opened = 0; add_stage = 1; add_pending = False; add_row = -1; add_level = np.nan; add_market = False; add_qty = 0
    addition_stopped = False; added_once = False
    last_valid_price = np.nan
    allocation_floor = np.nan; allocation_floor_row = -1; allocation_floor_market = False; allocation_budget = 0.
    allocation_events = np.zeros((100000,14)); allocation_count = 0
    allocation_curve = np.full((n,10),np.nan) if detail else np.full((1,10),np.nan)''')
    # ----------------------------------------
    # 初回q0は影の基準。物理枠数と実初回数量を別にして元の時計を維持する。
    text = text.replace('range(q0)', 'range(slots)')
    text = text.replace('np.zeros(q0,', 'np.zeros(slots,').replace('np.full(q0,', 'np.full(slots,')
    text = text.replace('np.zeros((n, q0)', 'np.zeros((n, slots)').replace('np.zeros((1, q0)', 'np.zeros((1, slots)')
    text = replace_once(text,'    split_count = q0 // 2','    split_count = initial // 2')
    text = replace_once(text,'        p = price[i]; t = time[i]; old_oc = oc',
        '        p = price[i]; t = time[i]; old_oc = oc\n        added_now = False')
    text = replace_once(text,'        acted = False; reason = 0; fill = 0.; closed_now = False',
        '        acted = False; reason = 0; fill = 0.; closed_now = False\n        original_distance = 1e100; original_scheduled = False')
    text = replace_once(text,'        plan_row = -1; source = i-1;',
        '        previous_valid_price = last_valid_price; last_valid_price = p\n        plan_row = -1; source = i-1;')
    text = replace_once(text,'                    best = 1e100; prior = price[i-1]',
        '                    best = 1e100; prior = previous_valid_price if np.isfinite(allocation_floor) else price[i-1]')
    text = replace_once(text,'                    original_reason = int(plan[18]); original_fill = p; source = int(plan[19])',
        '                    original_reason = int(plan[18]); original_fill = p; source = int(plan[19]); original_scheduled = True')
    text = replace_once(text,'                            best = distance',
        '                            best = distance; original_distance = distance')
    text = replace_once(text,'is_entry = True; d = pd; a = plan[24]; risk = q0*a; planned_qty = q0',
        'is_entry = True; d = pd; a = plan[24]; risk = initial*a; planned_qty = initial')
    text = replace_once(text,'                    alive[:] = True; restorable[:] = False; slot_leg[:] = -1',
        '                    alive[:] = False; alive[:initial] = True; restorable[:] = False; slot_leg[:] = -1')
    text = replace_once(text,'                    selected[:] = True\n                    guard_peak',
        '                    selected[:] = False; selected[:initial] = True\n                    guard_peak')
    text = replace_once(text,'                    actual_anchor = fill; early_peak = 0.; early_action = 0',
        '''                    actual_anchor = fill; early_peak = 0.; early_action = 0
                    opened = initial; split_count = opened//2; add_stage = 1; add_pending = False; add_row = -1
                    addition_stopped = False; added_once = False
                    allocation_floor = np.nan; allocation_floor_row = -1; allocation_floor_market = False
                    allocation_budget = initial*.75*a''')
    # ----------------------------------------
    # 旧出口と追加床の価格線は既発注順に比較。予定時刻による全返済は優先する。
    text = replace_once(text,'        if not is_entry and original_reason:\n            planned_qty = planned_qty-split_count if original_reason == 7 else 0.', '''        if not is_entry and not closed and np.isfinite(allocation_floor) and i>allocation_floor_row and not original_scheduled and original_reason!=71:
            if allocation_floor_market or -d*(p-allocation_floor)>=-1e-8:
                distance=0. if allocation_floor_market else max(0.,-d*(allocation_floor-previous_valid_price))
                if not original_reason or distance<original_distance-1e-9:
                    original_reason=76; original_fill=p if observed_fill or allocation_floor_market else allocation_floor; source=allocation_floor_row
        if not is_entry and original_reason:
            if original_reason==7:
                split_count=opened//2
                if add_mode and not addition_stopped:
                    allocation_events[allocation_count]=np.array([i,campaign,6.,source,d,0.,original_fill,opened,initial,allocation_budget,campaign_fees,0.,7.,add_stage]); allocation_count+=1
                addition_stopped=True
            planned_qty = planned_qty-split_count if original_reason == 7 else 0.
        if add_pending and (original_reason and not is_entry or closed or quiet[i] or quiet_force[i] or t>=end-cutoff*60):
            allocation_events[allocation_count]=np.array([i,campaign,5.,add_row,d,add_qty,add_level,opened,initial,allocation_budget,0.,0.,original_reason,add_stage]); allocation_count+=1
            add_pending=False''')
    text = replace_once(text,'                realized += gain; cash += move; reductions += 1',
        '''                realized += gain; cash += move; reductions += 1
                if done>0:
                    if add_mode and not addition_stopped:
                        allocation_events[allocation_count]=np.array([i,campaign,6.,source,d,done,fill,opened,initial,allocation_budget,campaign_fees,0.,reason,add_stage]); allocation_count+=1
                    addition_stopped=True
                    if add_pending:
                        allocation_events[allocation_count]=np.array([i,campaign,5.,add_row,d,add_qty,add_level,opened,initial,allocation_budget,0.,0.,reason,add_stage]); allocation_count+=1
                        add_pending=False''')
    # ----------------------------------------
    # 新規枠だけを開き、初回建値・ATR・親組の期限・MFE根拠は変更しない。
    text = replace_once(text,'        for fee_order in range(old_oc, oc):', '''        if add_pending and not closed and not acted and not original_reason and not pending and not budget and not guard_pending and not early_action and i>add_row:
            if add_market or d*(p-add_level)>=-1e-8:
                fill=p if observed_fill or add_market else add_level
                qty=min(add_qty,cap-opened)
                if qty<=0 or opened+qty>slots: raise ValueError('追加枠が不正です')
                leg=used; pos[used]=np.array([d,fill,qty,0.,i]); used+=1
                orders[oc]=np.array([i,add_row,campaign,d,qty,fill,75.,1.]); oc+=1
                cash-=d*qty*fill
                for slot in range(opened,opened+qty):
                    if slot_leg[slot]>=0 or alive[slot]: raise ValueError('使用済み枠へ追加しようとしました')
                    alive[slot]=True; restorable[slot]=False; slot_leg[slot]=leg
                    slot_events[sc]=np.array([i,add_row,campaign,slot+1,6.,leg,d,fill,1.,75.,plan_row]); sc+=1
                opened+=qty; split_count=opened//2
                allocation_events[allocation_count]=np.array([i,campaign,2.,add_row,d,qty,fill,opened,initial,allocation_budget,0.,0.,75.,add_stage]); allocation_count+=1
                add_pending=False; add_stage+=1; added_once=True; added_now=True; acted=True; reason=75
        for fee_order in range(old_oc, oc):''')
    text = replace_once(text,'        # ----------------------------------------\n        # 買い・売り別の連敗停止。', '''        # ----------------------------------------
        # 実約定後だけ全建値と実払料金で床を更新し、次観測へ公開する。
        if not closed:
            if added_once and floor_mode and inv[0]>0 and abs(inv[2])>0:
                expected_fee=0.
                for leg in range(used):
                    if pos[leg,2]>0: expected_fee+=np.floor(pos[leg,2]*losspar[12]+1e-8)/losspar[13]
                floor_profit=-allocation_budget if floor_mode==1 else 0.
                raw_level=(floor_profit+base+campaign_fees+expected_fee-realized+inv[3])/inv[2]
                level=rounded(raw_level,tick,d)
                if not np.isfinite(allocation_floor) or d*(level-allocation_floor)>1e-9:
                    allocation_floor=level; allocation_floor_row=i
                    allocation_events[allocation_count]=np.array([i,campaign,3.,i,d,inv[0],level,opened,initial,allocation_budget,campaign_fees,expected_fee,floor_mode,add_stage]); allocation_count+=1
                allocation_floor_market=-d*(p-allocation_floor)>=-1e-8
            if add_mode and not add_pending and not addition_stopped and opened<cap and not pending and not budget and not early_action and not guard_pending and not quiet[i] and not quiet_force[i] and t<end-cutoff*60:
                level=rounded(actual_anchor+d*add_stage*add_step*a,tick,d)
                add_level=level; add_row=i; add_qty=cap-opened if add_mode==1 else min(initial,cap-opened)
                add_market=d*(p-level)>=-1e-8; add_pending=True
                allocation_events[allocation_count]=np.array([i,campaign,1.,i,d,add_qty,level,opened,initial,allocation_budget,campaign_fees,0.,floor_mode,add_stage]); allocation_count+=1
        if reason==76 and closed_now:
            allocation_events[allocation_count]=np.array([i,campaign,4.,source,0.,0.,fill,opened,initial,allocation_budget,campaign_fees,0.,76.,add_stage]); allocation_count+=1
        if allocation_count>=len(allocation_events)-5: raise ValueError('追加証跡の上限です')
        if detail:
            allocation_curve[i]=np.array([opened,add_stage,int(add_pending),add_row,add_level,int(addition_stopped),allocation_floor,allocation_floor_row,allocation_budget,int(added_once)])
        # ----------------------------------------
        # 買い・売り別の連敗停止。''')
    # 枠容量のガードも実物理上限へ合わせる。無効対照では旧値と同一。
    text = text.replace('tc+q0 >=','tc+slots >=').replace('oc+q0+1 >=','oc+slots+1 >=')
    text = text.replace('sc+2*q0 >=','sc+2*slots >=')
    text = replace_once(text,'block_events[:xc], time_events[:qc])',
        'block_events[:xc], time_events[:qc], allocation_events[:allocation_count], allocation_curve)')
    path = HERE/'engine.py'
    path.write_text(text,encoding='utf-8')
    return str(path)


if __name__ == '__main__':
    print(build())
