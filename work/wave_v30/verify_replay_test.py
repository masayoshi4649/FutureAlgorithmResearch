"""主探索の再利用ガードを、壊れた保存物に相当する合成材料だけで反証する。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

import numpy as np
import verify_replay as verify
import select_verified_test as ledger_fixture


def fixture() -> dict:
    """機能: 12入口×7管理×26入力の整合した架空資料を生成する。

    引数: なし。返り値: 検算用資料 (dict)。実成績は読まない。
    """
    signals, own = verify.runner.context_split_design.signals()
    managers = verify.runner.context_split_design.catalog()
    fixed = {'signals': signals, 'own_signals': own, 'managers': managers, '全組合せ数': 84}
    inputs = {(r['session'], r['symbol']): {'seq': np.arange(4)} for r in ledger_fixture.rows('架空')}
    summaries, sessions, arrays, candidates = {}, {}, {}, []
    for signal in signals:
        identifier = signal['id']
        arrays[identifier] = {source: {key: np.ones(4, dtype=np.int8) for key in inputs}
                              for source in ('entry', 'main', 'own')}
        current, details = [], []
        for manager in managers:
            name = identifier + '__' + manager['id']
            rows = ledger_fixture.rows(name)
            symbols = verify.runner.diagnostics(rows)
            candidate = {'id': name, 'signal_id': identifier, 'manager_id': manager['id'],
                         'signal_family': signal['family'], 'manager_family': manager['family'],
                         'symbols': symbols, 'failures': verify.runner.failures(symbols), 'ledger_hash': 'a' * 64}
            current.append(candidate)
            details.append({'id': name, 'rows': rows})
            candidates.append(candidate)
        hashes = {source: verify.array_hash(values, inputs) for source, values in arrays[identifier].items()}
        summaries[identifier] = {'signal': signal, 'state_hash': hashes['entry'], 'context_hash': hashes['main'],
                                'own_context_hash': hashes['own'], 'elapsed_seconds': 1., 'candidates': current}
        sessions[identifier] = details
    candidates.sort(key=lambda row: row['id'])
    before = {'日時': '合成', '全条件数': 84, '最低基準通過数': sum(not c['failures'] for c in candidates),
              '方向系列の一意数': 1, '売買台帳の一意数': 1, '中期撤回系列の一意数': 1,
              '自己撤回系列の一意数': 1, '反証候補': deepcopy(candidates), '未知検証ではない': True}
    return dict(fixed=fixed, inputs=inputs, summaries=summaries, sessions=sessions,
                arrays=arrays, all_candidates=deepcopy(candidates), before=before)


def main() -> None:
    """機能: 不足・改変・偽集計を拒否し、来歴不一致ではrunnerが呼ばれないことを確認する。

    引数: なし。返り値: なし (None)。合成検査記録だけ保存する。
    """
    original = fixture()
    valid = verify.verify_materials(**deepcopy(original))
    rejected = []
    names = ('入口不足', '管理不足', '管理重複', '区間不足', '区間重複', '収支矛盾', '期間集計偽造',
             '上限超過', '枚数合算矛盾', '組利益不整合', '保存方向指紋不一致', 'C_S恒等式不一致',
             '方向集合の余分', '全期間候補不足', '全件要約偽造', '非有限集計')
    for name in names:
        bundle = deepcopy(original)
        signal = bundle['fixed']['signals'][0]['id']
        summary = bundle['summaries'][signal]
        details = bundle['sessions'][signal]
        row = details[0]['rows'][0]
        if name == '入口不足':
            del bundle['summaries'][signal]
        elif name == '管理不足':
            details.pop()
        elif name == '管理重複':
            details.append(deepcopy(details[0]))
        elif name == '区間不足':
            details[0]['rows'].pop()
        elif name == '区間重複':
            details[0]['rows'][-1] = deepcopy(details[0]['rows'][0])
        elif name == '収支矛盾':
            row['net_yen'] += 1.
        elif name == '期間集計偽造':
            summary['candidates'][0]['symbols']['TOPIX']['net_yen'] += 1.
        elif name == '上限超過':
            row['max_long'] = 21
        elif name == '枚数合算矛盾':
            row['closed_units'] += 1
        elif name == '組利益不整合':
            row['two_largest_cycle_profits'] = [row['cycle_profit_yen'] + 1.]
        elif name == '保存方向指紋不一致':
            summary['state_hash'] = 'b' * 64
        elif name == 'C_S恒等式不一致':
            for values in bundle['arrays'][signal]['own'].values():
                values[:] = -1
            summary['own_context_hash'] = verify.array_hash(bundle['arrays'][signal]['own'], bundle['inputs'])
        elif name == '方向集合の余分':
            bundle['arrays'][signal]['entry'][('架空追加', 'TOPIX')] = np.ones(4, dtype=np.int8)
        elif name == '全期間候補不足':
            bundle['all_candidates'].pop()
        elif name == '全件要約偽造':
            bundle['before']['全条件数'] = 83
        elif name == '非有限集計':
            row['gross_profit_yen'] = float('nan')
        try:
            verify.verify_materials(**bundle)
        except (AssertionError, ValueError, KeyError, TypeError):
            rejected.append(name)
        else:
            raise AssertionError('破損を受理: ' + name)

    # ----------------------------------------
    # 整合した偽造資料で再集計を通過しても、登録したバイト指紋が違えば起動しない。
    with tempfile.TemporaryDirectory(prefix='v30_再利用合成_') as folder:
        manifest = Path(folder) / 'manifest.json'
        manifest.write_text(json.dumps({'検査コードSHA256': verify.digest(Path(verify.__file__)),
                             'ファイルSHA256': {'合成成果': '既存指紋'}, '意味内容SHA256': {'合成成果': '意味'}},
                             ensure_ascii=False), encoding='utf-8')
        with patch.object(verify, 'MANIFEST', manifest), \
             patch.object(verify, 'collect', return_value=(valid, {'合成成果': '変更指紋'}, {'合成成果': '意味'})), \
             patch.object(verify.subprocess, 'run') as called:
            try:
                verify.run(1, replay=True)
            except AssertionError:
                pass
            else:
                raise AssertionError('指紋変更後の再実行を許可した')
            called.assert_not_called()
    result = {'合成正常資料': valid, '合成破損拒否': rejected, '拒否数': len(rejected),
              '指紋改変時はrunner未起動': True, '現在データ使用': False, '売買再生': False,
              '監査コードSHA256': verify.digest(Path(verify.__file__))}
    Path(__file__).with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'合成破損{len(rejected)}件を拒否。SHA改変時のrunner未起動を確認。', flush=True)


if __name__ == '__main__':
    main()
