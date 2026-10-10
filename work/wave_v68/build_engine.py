"""既存の枠注文器へ、実建玉の早期損失制御と料金後休止だけを追加する。"""

from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main() -> None:
    """機能: 既存器の該当箇所を検査し、新領域へ追加制御器を生成する。

    引数: なし。返り値: なし(None)。
    """
    source = (ROOT / 'work/wave_v67/engine_partial.py').read_text(encoding='utf8')
    edits = [
        ('branch_source, branch_valid, branch_choice, branch_mode, branch_seed):',
         'branch_source, branch_valid, branch_choice, branch_mode, branch_seed, losspar, raw_bad, raw_source, raw_valid, ema_direction, ema_source):'),
        ('    last_exit = -1e20; inv = np.zeros(6)\n',
         '''    last_exit = -1e20; inv = np.zeros(6)
    early_peak = 0.; early_action = 0; early_row = -1; early_evidence = -1
    reduce_reason = 30; actual_anchor = 0.; campaign_fees = 0.
    loss_streak = 0; cumulative_r = 0.; pause_until = -1e20
    risk_events = np.zeros((12000, 10)); rc = 0
'''),
        ('        p = price[i]; t = time[i]\n', '        p = price[i]; t = time[i]; old_oc = oc\n'),
        ("            elif int(plan[21]) and not bool(plan[30]) and t < plan[23] and t < end-cutoff*60:\n",
         "            elif int(plan[21]) and not bool(plan[30]) and t < plan[23] and t < end-cutoff*60 and t >= pause_until:\n"),
        ('                    selected[:] = True\n                    if kind == 1:',
         '''                    selected[:] = True
                    actual_anchor = fill; early_peak = 0.; early_action = 0
                    early_row = -1; early_evidence = -1; reduce_reason = 30; campaign_fees = 0.
                    if kind == 1:'''),
        ('        elif not is_entry and not closed and pending and not budget and i>pending_row',
         '''        elif not is_entry and not closed and early_action and i > early_row:
            fill = p; reason = early_action; source = early_row; selected[:] = True
            for slot in range(q0):
                if alive[slot]:
                    slot_events[sc] = np.array([i, source, campaign, slot+1, 5., slot_leg[slot], d, fill, 1. if slot_leg[slot]>=0 else 0., reason, plan_row]); sc += 1
            tc, oc, gain, move, done = close_slots(pos, used, slot_leg, selected, fill, i, source, reason, campaign, trades, tc, orders, oc)
            realized += gain; cash += move; acted = True; closed_now = True
            risk_events[rc] = np.array([i, campaign, 2., early_action, source, early_evidence, done, early_peak, loss_streak, cumulative_r]); rc += 1
            early_action = 0
        elif not is_entry and not closed and pending and not budget and i>pending_row'''),
        ('            fill = p; reason = 30 if pending < 0 else 31; source = pending_row',
         '            fill = p; reason = reduce_reason if pending < 0 else 31; source = pending_row'),
        ('            fill = original_fill; reason = original_reason\n',
         '            fill = original_fill; reason = original_reason; early_action = 0\n'),
        ('        inv = shadow_engine.inventory(pos, used)\n        equity = realized+inv[2]*p-inv[3]\n',
         '''        for fee_order in range(old_oc, oc):
            campaign_fees += np.floor(orders[fee_order,4] * losspar[12] + 1e-8) / losspar[13]
        inv = shadow_engine.inventory(pos, used)
        equity = realized+inv[2]*p-inv[3]
'''),
        ('        if closed_now:\n            cycles[cc]',
         '''        if closed_now:
            net_campaign = realized-base-campaign_fees
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
            cycles[cc]'''),
        ('            if budget_enabled and e <= -risk and not budget:',
         '            if budget_enabled and e-(campaign_fees if losspar[8]<1. else 0.) <= -risk*losspar[8] and not budget:'),
        ('            if kind == 3 and not acted and not pending and not budget:\n',
         '''            early_peak = max(early_peak, d*(p-actual_anchor)/a)
            # ----------------------------------------
            # 当行までの進捗と新しい公開根拠だけで、次行用の損失制御を予約する。
            if not acted and not pending and not budget and not early_action:
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
            if kind == 3 and not acted and not pending and not budget and not early_action:
'''),
        ('                    pending = -1; evidence = bad_source[i]\n',
         '                    pending = -1; evidence = bad_source[i]; reduce_reason = 30\n'),
        ('adjustment[:ac], budgets[:bc], branch_events[:brc], branch_curve)',
         'adjustment[:ac], budgets[:bc], branch_events[:brc], branch_curve, risk_events[:rc])')
    ]
    # 関数runは旧署名を保持するが今回呼ばない。追加引数付きsimulateを窓口から直接呼ぶ。
    for old, new in edits:
        assert source.count(old) == 1, (old[:80], source.count(old))
        source = source.replace(old, new, 1)
    source = source.replace('"""元A0の前行有効計画を並行使用し、同一組の数量減量・復元だけを行う。"""',
        '"""元E01の枠会計に、実建玉の初期失敗と料金後連敗による損失制御を追加する。"""', 1)
    source = source.replace('    返り値: 旧6結果と枠・調整・予算・管理状態の証跡 (tuple[ndarray,...])。',
        '    losspar(ndarray)は早期制御・休止・料金の固定変数。raw_bad/source/validとEMA列は公開済み根拠。\n    返り値: 旧6結果と枠・調整・予算・管理状態・損失制御証跡 (tuple[ndarray,...])。', 1)
    (HERE / 'loss_engine.py').write_text(source, encoding='utf8')
    (HERE / 'loss_shadow.py').write_bytes((ROOT / 'work/wave_v67/engine_shadow.py').read_bytes())
    print('損失制御用エンジンを新領域へ生成しました')


if __name__ == '__main__':
    main()
