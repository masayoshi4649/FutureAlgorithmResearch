"""保存された旧台帳及び新増玉診断を、全原行へ展開し列と指紋を確認する。"""

import numpy as np

import compare_utils as checks
import financial


def verify(output: dict, ledger: dict, prepared: dict) -> dict:
    """
    機能: 根ledgerの疎保存と全新配列を実際に復元し、出力と元入力指紋を照合する。
    引数: output/ledger/prepared(dict)は本体出力・再読込済み保存・元入力。
    返り値: dict。復元列と保存配列件数。これは保存一致でありlatent全列の数理証明ではない。
    """
    rows = len(prepared['record']['time_s'])
    assert ledger['input_rows'] == rows
    states = [
        ('target_trace','trace_changes','target_trace_SHA256',6),
        ('range_state_trace','range_state_changes','range_state_SHA256',25),
        ('risk_state_trace','risk_state_changes','risk_state_SHA256',40),
        ('price_source_trace','price_source_changes','price_source_SHA256',22),
        ('trend_exit_state_trace','trend_exit_state_changes','trend_exit_state_SHA256',23),
        ('watch_state_trace','watch_state_changes','watch_state_SHA256',50),
        ('entry_policy_state_trace','entry_policy_state_changes','entry_policy_state_SHA256',40),
        ('entry_cap_state_trace','entry_cap_state_changes','entry_cap_state_SHA256',20),
        ('growth_state_trace','growth_state_changes','growth_state_SHA256',70),
        ('growth_gate_state_trace','growth_gate_state_changes','growth_gate_state_SHA256',19),
    ]
    recovered = 0
    for name,sparse,fingerprint,width in states:
        dense = financial.expand(np.asarray(ledger[sparse]),rows)
        assert dense.shape == (rows,width)
        checks.exact(dense,output[name],name+'/保存復元')
        assert checks.array_sha(dense) == ledger[fingerprint],name+'/復元SHA'
        recovered += width
    arrays = ['orders','trades','events','stats','slots','range_parent_diagnostics',
              'loss_reentry_events','trend_parent_diagnostics','entry_parent_diagnostics',
              'entry_wait_events','entry_policy_events','entry_cap_parent_diagnostics',
              'entry_support_state_trace','growth_events','growth_cohorts','growth_parent_diagnostics']
    for name in arrays:
        checks.exact(ledger[name],output[name],name+'/実保存全配列')
    for name in ('growth_state_columns','growth_event_columns','growth_event_codes','growth_cohort_columns',
                 'growth_parent_columns','growth_gate_state_columns','entry_support_columns','entry_support_input_SHA256'):
        assert ledger[name] == output[name],name+'/列定義又は指紋'
    assert ledger['entry_support_state_rows'] == len(output['entry_support_state_trace'])
    assert ledger['entry_support_state_SHA256'] == checks.array_sha(output['entry_support_state_trace'])
    for name in ('curve','source_curve'):
        assert ledger[name+'_SHA256'] == checks.array_sha(output[name]),name
    for name,field in [('event','trend_event_SHA256'),('loss_observations','loss_observations_SHA256'),
                       ('execution_lp_index','execution_lp_index_SHA256')]:
        assert ledger[field] == checks.array_sha(prepared['signal'][name]),field
    for name,expected in ledger['wait_input_SHA256'].items():
        assert expected == checks.array_sha(prepared['signal'][name]),name
    return dict(口座=1,疎復元列=recovered,保存全配列=len(arrays),旧growth状態復元列=70,新追加門番復元列=19)
