"""登録前に一度だけ、00141の売買層へ独立判断関数を接続する。"""

from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
source = (ROOT/'work/raw_diagnosis141_20261024/active141_v3.py').read_text(encoding='utf-8')
source = source.replace('import early139\n', 'import early139\nfrom entry_selector142 import choose_entry, allow_add\nfrom management_selector142 import select_from_features\n')
source = source.replace('partial_exit=False):', 'partial_exit=False, entry_policy=0, management_policy=0, add_policy=0):')
source = source.replace('    partial_done = False\n    for i in range(n):', '''    partial_done = False
    selected_guard = entry_guard
    failed_by_side = np.zeros(2, np.int64)
    trace = np.zeros((max(1024,n//2), 9))
    trace_count = 0
    previous_action = -1
    for i in range(n):''')
source = source.replace('                    partial_done = False\n', '                    partial_done = False\n                    previous_action = -1\n')
source = source.replace('                    lost = lost+1 if campaign_cash < 0. else 0\n', '''                    lost = lost+1 if campaign_cash < 0. else 0
                    side_index = 1 if side > 0 else 0
                    failed_by_side[side_index] = failed_by_side[side_index]+1 if campaign_cash < 0. else 0
''')
source = source.replace('if exit_guard and adverse:', 'if (exit_guard or management_policy) and adverse:')
source = source.replace('''                        if not partial_exit:
                            pending, source, reason = 2, i, 1411 if exit_guard == 1 else 1412
                        elif not partial_done and total>=2:
                            pending, source, reason = 4, i, 1415''', '''                        if management_policy:
                            failed_same = failed_by_side[1 if side > 0 else 0]
                            action, decision_reason = select_from_features(management_policy, side, total,
                                gain/risk, best/risk, floor/risk, partial_done, failed_same, a[i], True)
                            if action != previous_action:
                                trace[trace_count] = np.array([i,2,side,action,decision_reason,parent,gain/risk,best/risk,failed_same])
                                trace_count += 1
                                previous_action = action
                            if action == 2:
                                pending, source, reason = 2, i, 1420+management_policy
                            elif action == 1 and not partial_done and total >= 2:
                                pending, source, reason = 4, i, 1430+management_policy
                        elif not partial_exit:
                            pending, source, reason = 2, i, 1411 if exit_guard == 1 else 1412
                        elif not partial_done and total>=2:
                            pending, source, reason = 4, i, 1415''')
source = source.replace('''                else:
                    adverse_since = -np.inf
        if total''', '''                else:
                    adverse_since = -np.inf
                    previous_action = -1
        if total''')
source = source.replace('''                if add_guard in (1, 2):''', '''                if add_guard in (1, 2) or add_policy:''')
source = source.replace('''                if loss_to_stop+new_risk <= budget and ask[i]-bid[i] <= .25*risk:''', '''                if add_policy and not allow_add(add_policy,a[i],side,floor):
                    budget = -1.
                if loss_to_stop+new_risk <= budget and ask[i]-bid[i] <= .25*risk:''')
source = source.replace('''                    since = -np.inf
            if arm:''', '''                    since = -np.inf
                    selected_guard = entry_guard
                    if entry_policy and chosen == 4:
                        failed_same = failed_by_side[1 if arm > 0 else 0]
                        selected_guard, decision_reason = choose_entry(entry_policy,a[i],arm,failed_same)
                        trace[trace_count] = np.array([i,1,arm,selected_guard,decision_reason,parent+1,0.,0.,failed_same])
                        trace_count += 1
            if arm:''')
source = source.replace('if entry_guard == 2:', 'if selected_guard == 2:')
source = source.replace('if entry_guard == 1 and', 'if selected_guard == 1 and')
source = source.replace('return out[:count], equity', 'return out[:count], equity, trace[:trace_count]')
source = source.replace("c.get('exit_guard',0),c.get('flow_guard',0),c.get('evidence_hold',15.),c.get('partial_exit',False))", "c.get('exit_guard',0),c.get('flow_guard',0),c.get('evidence_hold',15.),c.get('partial_exit',False),\n                    c.get('entry_policy',0),c.get('management_policy',0),c.get('add_policy',0))")
source = source.replace('全原板の損失診断から、反転確認・追撃予算・途中退出を分離して検証する。', '独立判断層の指示に従って約定・保有・追撃・返済を行う売買層。')
source = source.replace('tuple[ndarray,ndarray]は十列約定と清算時価。', 'tuple[ndarray,ndarray,ndarray]は十列約定・清算時価・判断履歴。')
source = source.replace('tuple[ndarray,ndarray]は全注文と清算時価。', 'tuple[ndarray,ndarray,ndarray]は全注文・清算時価・判断履歴。')
destination=HERE/'active_trader142.py'
assert not destination.exists()
destination.write_text(source,encoding='utf-8')
print('売買層の接続を作成しました。')
