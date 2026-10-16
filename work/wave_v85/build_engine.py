"""監査済みの元E01数量器を保持し、利益保護と方向別の再開待ちだけを追加する。"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def replace_once(source, old, new):
    """
    機能: 既知の実装位置だけを一度置換する。
    引数: source/old/new(str)。
    返り値: str。位置が一意でなければ生成を中止する。
    """
    assert source.count(old) == 1, old[:100]
    return source.replace(old, new, 1)


def build():
    """
    機能: 旧ファイルを変更せず、今回専用の追加制御器を生成する。
    引数: なし。
    返り値: None。
    """
    source = (ROOT / 'work/wave_v68/loss_engine.py').read_text(encoding='utf-8')
    source = source[:source.index('\ndef run(ready:')]
    source = source.replace('"""元A0の前行有効計画を並行使用し、同一組の数量減量・復元だけを行う。"""',
                            '"""E01の注文順を維持し、実組利益保護・方向別再開待ちを追加する。"""')
    source = replace_once(source, 'raw_valid, ema_direction, ema_source):',
                          'raw_valid, ema_direction, ema_source, ema_peer_source, ema_valid, quiet=None, quiet_force=None, quiet_not_before=None):')
    source = replace_once(source, 'losspar(ndarray)は早期制御・休止・料金の固定変数。raw_bad/source/validとEMA列は公開済み根拠。',
        'losspar(ndarray)は早期制御・料金と利益保護・方向停止の固定変数。\n'
        '    raw_bad/source/validとEMA列は公開済み根拠。追加EMA列は相手公開元行と両市場の有限値・鮮度。\n'
        '    quiet/quiet_force/quiet_not_beforeは事前予定から作る静観・返済・新準備時刻(ndarray又はNone)。\n'
        '    追加の返り値は利益保護曲線、保護イベント、方向停止イベント、時間イベント(ndarray)。')
    source = replace_once(source, '    n = len(price)\n    pos =', '''    n = len(price)
    if quiet is None: quiet = np.zeros(n, np.bool_)
    if quiet_force is None: quiet_force = np.zeros(n, np.bool_)
    if quiet_not_before is None: quiet_not_before = np.full(n, -np.inf)
    time_events = np.zeros((12000, 7)); qc = 0; last_quiet_prepare = -1
    pos =''')
    source = replace_once(source, '    risk_events = np.zeros((12000, 10)); rc = 0', '''    risk_events = np.zeros((12000, 10)); rc = 0
    guard_peak = 0.; guard_floor = -np.inf; guard_pending = False; guard_row = -1
    guard_curve = np.zeros((n, 8)) if detail else np.zeros((1, 8))
    guard_events = np.zeros((36000, 10)); gc = 0
    block_events = np.zeros((24000, 8)); xc = 0
    direction_losses = np.zeros(2, np.int64)
    blocked = np.zeros(2, np.bool_); reset_seen = np.zeros(2, np.bool_)
    block_row = np.full(2, -1, np.int64)
    reset_own = np.full(2, -1, np.int64); reset_peer = np.full(2, -1, np.int64)''')
    source = replace_once(source, '            continue\n        plan_row = -1;',
                          '            if detail and i: guard_curve[i] = guard_curve[i-1]\n            continue\n        plan_row = -1;')
    source = replace_once(source, 'and t >= pause_until:\n                pd = int(plan[21])',
        'and t >= pause_until and not blocked[0 if plan[21]>0 else 1] and not quiet[i] and not quiet_force[i] and time[int(plan[29])] >= quiet_not_before[i]:\n                pd = int(plan[21])')
    source = replace_once(source, '                    actual_anchor = fill; early_peak = 0.; early_action = 0',
        '                    guard_peak = 0.; guard_floor = -np.inf; guard_pending = False; guard_row = -1\n'
        '                    actual_anchor = fill; early_peak = 0.; early_action = 0')
    source = replace_once(source, '        if not is_entry and original_reason:\n', '''        # ----------------------------------------
        # 時刻予定は価格観測より前から既知。寄付き回避は元の部分返済より全返済を優先する。
        if i and np.isfinite(execution_plans[i,33]):
            plan = execution_plans[i]
            if int(plan[21]) and int(plan[28]) != last_quiet_prepare and (quiet[i] or time[int(plan[29])] < quiet_not_before[i]):
                last_quiet_prepare = int(plan[28])
                time_events[qc] = np.array([i,int(plan[1])+1,2.,int(plan[29]),0.,quiet_not_before[i]-1800.,quiet_not_before[i]]); qc += 1
        if not closed and not is_entry and quiet_force[i]:
            original_reason = 71; original_fill = p; source = i-1
            time_events[qc] = np.array([i,campaign,1.,source,shadow_engine.inventory(pos,used)[0],quiet_not_before[i]-1800.,quiet_not_before[i]]); qc += 1
        if qc >= len(time_events)-3:
            raise ValueError('時間回避の証跡上限です')
        if not is_entry and original_reason:
''')
    source = replace_once(source, '            else:\n                closed_now = True\n        elif not is_entry', '''                if guard_pending:
                    guard_events[gc] = np.array([i,campaign,4.,guard_row,0.,guard_peak,guard_floor,0.,d,7.]); gc += 1
            else:
                if guard_pending:
                    guard_events[gc] = np.array([i,campaign,5.,guard_row,0.,guard_peak,guard_floor,0.,d,reason]); gc += 1
                closed_now = True
        elif not is_entry''')
    source = replace_once(source, '        elif not is_entry and not closed and early_action and i > early_row:', '''        elif not is_entry and not closed and guard_pending and i > guard_row:
            fill = p; reason = 70; source = guard_row; selected[:] = True
            for slot in range(q0):
                if alive[slot]:
                    slot_events[sc] = np.array([i,source,campaign,slot+1,5.,slot_leg[slot],d,fill,1. if slot_leg[slot]>=0 else 0.,reason,plan_row]); sc += 1
            tc, oc, gain, move, done = close_slots(pos,used,slot_leg,selected,fill,i,source,reason,campaign,trades,tc,orders,oc)
            realized += gain; cash += move; acted = True; closed_now = True
            guard_events[gc] = np.array([i,campaign,3.,source,0.,guard_peak,guard_floor,done,d,reason]); gc += 1
        elif not is_entry and not closed and early_action and i > early_row:''')
    source = replace_once(source, '            net_campaign = realized-base-campaign_fees\n            loss_streak', '''            net_campaign = realized-base-campaign_fees
            ix = 0 if d > 0 else 1
            direction_losses[ix] = direction_losses[ix]+1 if net_campaign < 0 else 0
            if losspar[18] > 0 and direction_losses[ix] >= 2:
                blocked[ix] = True; reset_seen[ix] = False; block_row[ix] = i
                block_events[xc] = np.array([i,campaign,1.,d,direction_losses[ix],i,ema_source[i],ema_peer_source[i]]); xc += 1
            guard_pending = False
            loss_streak''')
    source = replace_once(source, '            early_peak = max(early_peak, d*(p-actual_anchor)/a)', '''            early_peak = max(early_peak, d*(p-actual_anchor)/a)
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
                    guard_events[gc] = np.array([i,campaign,2.,i,net_liquidation,guard_peak,guard_floor,inv[0],d,70.]); gc += 1''')
    source = source.replace('not pending and not budget and not early_action:',
                            'not pending and not budget and not early_action and not guard_pending:')
    source = replace_once(source, '        if detail:\n            branch_curve[i]', '''        # ----------------------------------------
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
            branch_curve[i]''')
    source = replace_once(source, 'branch_events[:brc], branch_curve, risk_events[:rc])',
                          'branch_events[:brc], branch_curve, risk_events[:rc], guard_curve, guard_events[:gc], block_events[:xc], time_events[:qc])')
    (HERE / 'engine.py').write_text(source, encoding='utf-8')
    print('旧数量器を保持して今回の2制御を生成しました。')


if __name__ == '__main__':
    build()
