"""原GUの枠会計へ、一部だけの狭い追尾と親組ゼロ円床を追加する。"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1]/'wave_v85/engine.py'


def replace_once(text, old, new):
    """
    機能: 期待した箇所だけを置換する。
    引数: text/old/new(str)。
    返り値: str。
    """
    assert text.count(old)==1, (old,text.count(old))
    return text.replace(old,new,1)


def build():
    """
    機能: 旧実装を不変に保ち、部分返済と全親組保護の別実装を生成する。
    引数: なし。
    返り値: str の生成先。
    """
    text=SOURCE.read_text(encoding='utf-8')
    text=replace_once(text,'import exit_shadow_integrated as shadow_engine',
        'import exit_shadow_integrated as shadow_engine\nfrom wave86_shadow import rounded')
    text=replace_once(text,'quiet=None, quiet_force=None, quiet_not_before=None):',
        'quiet=None, quiet_force=None, quiet_not_before=None, narrow_fraction=0., protect_after_narrow=False, tick=1.):')
    text=replace_once(text,'    split_count = q0 // 2','''    split_count = q0 // 2
    narrow_count = int(np.floor(q0*narrow_fraction+1e-9))
    if narrow_count < 0 or narrow_count >= q0: raise ValueError('先行枠数は全玉未満にします')
    narrow_extreme = np.nan; narrow_level = np.nan; narrow_source = -1
    narrow_done = False; narrow_market = False
    parent_floor_active = False; parent_floor = np.nan; parent_floor_source = -1; parent_floor_market = False
    partial_curve = np.full((n,8),np.nan) if detail else np.full((1,8),np.nan)
    partial_events = np.zeros((n+12000,12)); pc = 0''')
    text=replace_once(text,'        p = price[i]; t = time[i]; old_oc = oc',
        '        p = price[i]; t = time[i]; old_oc = oc\n        narrow_executed = False')
    text=replace_once(text,'                    actual_anchor = fill; early_peak = 0.; early_action = 0',
        '''                    actual_anchor = fill; early_peak = 0.; early_action = 0
                    narrow_extreme = p; narrow_level = np.nan; narrow_source = -1
                    narrow_done = False; narrow_market = False
                    parent_floor_active = False; parent_floor = np.nan; parent_floor_source = -1; parent_floor_market = False''')
    text=replace_once(text,'        if not is_entry and original_reason:\n            planned_qty = planned_qty-split_count if original_reason == 7 else 0.', '''        # ----------------------------------------
        # 原注文と既存の全返済予約を優先する。同一行で二重に注文しない。
        if not is_entry and not closed and not original_reason and not budget and not guard_pending and not early_action:
            if parent_floor_active and i>parent_floor_source and (parent_floor_market or -d*(p-parent_floor)>=-1e-8):
                original_reason=74; original_fill=p if observed_fill or parent_floor_market else parent_floor; source=parent_floor_source
            elif narrow_count>0 and not narrow_done and i>narrow_source and np.isfinite(narrow_level) and (narrow_market or -d*(p-narrow_level)>=-1e-8):
                available=False
                for slot in range(narrow_count):
                    if alive[slot] and slot_leg[slot]>=0: available=True
                if available:
                    original_reason=73; original_fill=p if observed_fill or narrow_market else narrow_level; source=narrow_source
                else:
                    narrow_done=True
        if not is_entry and original_reason:
            if original_reason==7: planned_qty-=split_count
            elif original_reason!=73: planned_qty=0.''')
    text=replace_once(text,'            if reason == 7:\n                selected[split_count:] = False',
        '            if reason == 7:\n                selected[split_count:] = False\n            elif reason == 73:\n                selected[narrow_count:] = False')
    text=text.replace('4. if reason == 7 else 5.', '4. if reason in (7,73) else 5.')
    text=replace_once(text,'            if reason == 7:\n                if not np.any(restorable):', '''            if reason == 73:
                narrow_done=True
                narrow_executed=done>0
                if pc>=len(partial_events): raise ValueError('部分追尾証跡の上限です')
                partial_events[pc]=np.array([i,campaign,2.,source,d,done,fill,narrow_extreme,a,realized-base,0.,narrow_count]); pc+=1
            elif reason == 74:
                if pc>=len(partial_events): raise ValueError('部分追尾証跡の上限です')
                partial_events[pc]=np.array([i,campaign,4.,source,d,done,fill,narrow_extreme,a,realized-base,0.,narrow_count]); pc+=1
            if reason in (7,73):
                if not np.any(restorable):''')
    text=replace_once(text,'        # ----------------------------------------\n        # 買い・売り別の連敗停止。', '''        # ----------------------------------------
        # 今見た極値から作る線は次の観測以降で有効。全返済前は別組に入らない。
        if not closed:
            if narrow_count>0 and not narrow_done:
                available=False
                for slot in range(narrow_count):
                    if alive[slot] and slot_leg[slot]>=0: available=True
                if not available:
                    narrow_done=True
                else:
                    narrow_extreme=max(narrow_extreme,p) if d>0 else min(narrow_extreme,p)
                    if d*(narrow_extreme-actual_anchor)>=.75*a-1e-9:
                        level=rounded(narrow_extreme-d*.5*a,tick,-d)
                        if not np.isfinite(narrow_level) or d*(level-narrow_level)>1e-9:
                            narrow_level=level; narrow_source=i
                            if pc>=len(partial_events): raise ValueError('部分追尾証跡の上限です')
                            partial_events[pc]=np.array([i,campaign,1.,i,d,narrow_count,level,narrow_extreme,a,realized-base,inv[0],narrow_count]); pc+=1
                        narrow_market=-d*(p-narrow_level)>=-1e-8
            if narrow_executed and protect_after_narrow:
                parent_floor_active=True
            if parent_floor_active and inv[0]>0 and abs(inv[2])>0:
                # 全親組の実現利益・支払料・残玉の見込返済料を合算したゼロ円床。
                expected_fee=np.floor(inv[0]*losspar[12]+1e-8)/losspar[13]
                zero_price=(base+campaign_fees+expected_fee-realized+inv[3])/inv[2]
                level=rounded(zero_price,tick,d)
                if not np.isfinite(parent_floor) or d*(level-parent_floor)>1e-9:
                    parent_floor=level; parent_floor_source=i
                    if pc>=len(partial_events): raise ValueError('部分追尾証跡の上限です')
                    partial_events[pc]=np.array([i,campaign,3.,i,d,inv[0],level,narrow_extreme,a,realized-base-campaign_fees,expected_fee,narrow_count]); pc+=1
                parent_floor_market=-d*(p-parent_floor)>=-1e-8
        if detail:
            partial_curve[i]=np.array([narrow_extreme,narrow_level,narrow_source,int(narrow_done),int(parent_floor_active),parent_floor,parent_floor_source,narrow_count])
        # ----------------------------------------
        # 買い・売り別の連敗停止。''')
    text=replace_once(text,'block_events[:xc], time_events[:qc])',
        'block_events[:xc], time_events[:qc], partial_events[:pc], partial_curve)')
    text=text.replace('元E01の枠会計に、実建玉の初期失敗と料金後連敗による損失制御を追加する。',
        '原GUの枠会計へ、一部狭幅追尾と実部分返済後の親組ゼロ円床を追加する。')
    path=HERE/'engine.py'
    path.write_text(text,encoding='utf-8')
    return str(path)


if __name__=='__main__':
    print(build())
