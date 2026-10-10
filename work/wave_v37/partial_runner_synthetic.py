"""結果保存・金額枚数集計を人工価格だけで検査する。"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import numpy as np

import partial_runner as runner
import partial_engine_audit as fixtures


def main() -> None:
    """機能: 全管理×両銘柄の人工会計・集計・保存と無取引を確認する。

    引数: なし。返り値: なし (None)。保存データの新損益は計算しない。
    """
    checks, symbols = [], ('TOPIX', 'NK225')
    policies = runner.design.policies()
    cash_source = (runner.HERE.parent/'wave_v35/accounting_reconstruction_vectorized.py').read_text(encoding='utf-8')
    actual_source = (runner.HERE/'partial_cash_reconstruction.py').read_text(encoding='utf-8')
    assert actual_source.split('from __future__', 1)[1].replace('(20, 21, 22, 23, 31)', '(20, 21, 22, 23)') == cash_source.split('from __future__', 1)[1]
    for policy in policies:
        rows, series = [], {}
        for symbol in symbols:
            args = list(deepcopy(fixtures.fixture([100, 101, 103, 100, 103, 104, 100, 99, 101, 104, 100, 98, 95], (2, 6, 10), (4, 8))))
            ready = args[0]
            ready.update(symbol=symbol, session='2026-09-21_Day')
            args[2] = fixtures.helpers.config(symbol, ready)
            for inactive in (False, True):
                current = deepcopy(args)
                if inactive: current[1][:] = 0
                result = fixtures.play(tuple(current), policy, good_valid=np.ones(len(current[1]), bool))
                basic, curves = runner.accounting.reconstruct(ready, result, symbol)
                row = runner.session_row(policy['id'], ready, result, current[2], current[3], basic, curves)
                factor = current[2]['point_value']
                trades = result['trades']
                gains = trades[:, 2]*trades[:, 3]*(trades[:, 5]-trades[:, 4])*factor
                assert abs(sum(gains)-row['net_yen']) < 1e-6
                assert row['closed_units'] == row['profit_units']+row['loss_units']+row['zero_units']
                assert row['reductions'] == sum(result['orders'][:, 6] == 30)
                assert row['restorations'] == sum(result['orders'][:, 6] == 31)
                assert row['initial_actual_risk_yen'] <= row['initial_shadow_risk_yen']
                payload = dict(row=row, ledger={name: result[name].tolist() for name in runner.STORED},
                    fingerprints=runner.fingerprints(result))
                assert json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False)) == payload
                if not inactive:
                    rows.append(row); series[symbol] = curves['equity']*factor
                else:
                    assert not row['closed_units'] and not row['net_yen'] and not row['cycles']
                checks.append(dict(policy=policy['id'], symbol=symbol, inactive=inactive, 合格=True))
        period = runner.period(rows, ['2026-09-21_Day'])
        for symbol in symbols:
            values = np.r_[0., series[symbol]]
            dd = np.max(np.maximum.accumulate(values)-values)
            assert abs(period[symbol]['drawdown_yen']-dd) < 1e-6
    target = runner.HERE/'partial_runner_synthetic.json'
    runner.save(target, dict(全合格=True, 人工再生数=len(checks), 旧会計との差='復元新規理由31の許可だけ',
        新実データ損益=False, 検査=checks,
        SHA256={p.name: runner.digest(p) for p in (Path(__file__), runner.HERE/'partial_runner.py',
            runner.HERE/'partial_cash_reconstruction.py', runner.HERE/'engine_partial_restore.py')}))
    print(f'人工{len(checks)}条件の会計・枚数・保存一致。新実データ損益なし。', flush=True)


if __name__ == '__main__':
    main()
