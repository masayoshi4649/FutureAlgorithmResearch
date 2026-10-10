"""元の入口を固定した早期保護比較の会計と固定範囲を独立確認する。"""

from __future__ import annotations

import argparse
import pickle

import numpy as np

from gate_result_check import period_check
from independent_audit import ROOT, SOURCES, account, read, same, save, sha


EARLY = ROOT / 'work/wave_v49/early'
BASE = 'F50_NONE__E11'


def initial(orders: list) -> np.ndarray:
    """機能: 初回新規だけを抽出する。

    引数: orders (list)。返り値: 初回注文配列 (ndarray)。
    """
    data = np.asarray(orders)
    return data[(data[:, 7] == 1) & (data[:, 6] == 20)]


def check(expected_count: int | None) -> dict:
    """機能: 早期保護全条件の価格数量会計と元入口・時計を照合する。

    引数: expected_count (int|None) は要求方式数。返り値: 独立監査の証跡 (dict)。
    """
    inputs = pickle.loads((ROOT / 'work/wave_v47/inputs.pkl').read_bytes())
    for folder in SOURCES[2:]:
        inputs.update(pickle.loads((folder / 'new_inputs.pkl').read_bytes()))
    originals = []
    for folder in SOURCES:
        originals.extend(read(folder / 'ledgers' / (BASE + '.json.gz')))
    old = {(r['session'], r['symbol']): r for r in originals}
    assert len(old) == len(inputs) == 32
    fixed = {r['id']: r for r in read(EARLY / '条件の事前固定.json')['条件']}
    files = sorted((EARLY / 'summaries').glob('*.json'))
    if expected_count is not None:
        assert len(files) == expected_count, len(files)
    checks, fingerprints = [], {}
    baseline_count = initial_count = 0
    for path in files:
        summary = read(path)
        variant = summary['variant']
        assert variant == fixed[variant['id']]
        identifier = variant['id']
        rows = read(EARLY / 'sessions' / (identifier + '.json.gz'))
        ledgers = read(EARLY / 'ledgers' / (identifier + '.json.gz'))
        assert len(rows) == len(ledgers) == 32
        keyed = {(r['session'], r['symbol']): r for r in rows}
        for ledger in ledgers:
            key = ledger['session'], ledger['symbol']
            row, ready, original = keyed[key], inputs[key], old[key]
            proof = account(ledger, row, ready)
            expected_config = dict(original['config'], **variant['changes'])
            assert ledger['config'] == expected_config
            assert ledger['scheduler_fingerprints'] == original['scheduler_fingerprints']
            np.testing.assert_array_equal(initial(ledger['orders']), initial(original['orders']))
            np.testing.assert_array_equal(ledger['prepare_events'], original['prepare_events'])
            np.testing.assert_array_equal(ledger['entry_preparations'], original['entry_preparations'])
            assert len(ledger['cycles']) == len(original['cycles'])
            for cycle, reference in zip(ledger['cycles'], original['cycles']):
                np.testing.assert_array_equal(np.asarray(cycle)[[0, 1, 4, 5, 8]], np.asarray(reference)[[0, 1, 4, 5, 8]])
                same(cycle[4], ledger['config']['initial_qty'] * cycle[5], '固定実R分母')
            initial_count += len(ledger['entry_preparations'])
            if identifier == 'E00':
                for name in ('result_fingerprints', 'shadow_fingerprints', 'scheduler_fingerprints'):
                    assert ledger[name] == original[name]
                baseline_count += 1
            checks.append(dict(条件=identifier, **proof, 初回完全一致=True, 元時計全指紋一致=True,
                               変更設定限定=True, リスク分母一定=True))
        period_check(summary, rows)
        for source in (path, EARLY/'sessions'/(identifier+'.json.gz'), EARLY/'ledgers'/(identifier+'.json.gz')):
            fingerprints[source.relative_to(ROOT).as_posix()] = sha(source)
    output = dict(全合格=True, 方式数=len(files), 口座数=len(checks), 固定初回件数=initial_count,
                  基準全指紋一致口座数=baseline_count, 全口座独立会計一致=True,
                  全行時価と期間合計一致=True, 初回と通常影時計完全固定=True,
                  結果=checks, 参照SHA256=fingerprints,
                  限定='今回の独立監査は会計・固定範囲の照合。実装担当のNight全条件因果検査は別資料。')
    save('早期保護比較の独立監査.json', output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected', type=int)
    args = parser.parse_args()
    output = check(args.expected)
    print({k:v for k,v in output.items() if k not in ('結果', '参照SHA256')})
