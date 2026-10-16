"""20数量配分条件の実建玉群・追加予約・固定予算を根の保存経路で検算する。"""

import hashlib
import importlib.util
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'engine_preflight'))
import catalog
import research
import strategy

spec = importlib.util.spec_from_file_location('101明示人工増玉素材の読取', HERE / 'engine_preflight/selfcheck.py')
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


def restore(changes: np.ndarray, rows: int) -> np.ndarray:
    """
    機能: 変化行形式から全原行の状態を独立復元する。
    引数: changes(ndarray[float])は先頭行番号と状態、rows(int)は原行数。
    返り値: ndarray[float]。全原行へ展開した状態。
    """
    result = np.empty((rows, changes.shape[1]-1))
    for index, row in enumerate(changes):
        end = int(changes[index+1, 0]) if index+1 < len(changes) else rows
        result[int(row[0]):end] = row[1:]
    return result


def main() -> None:
    """
    機能: 全20人工40口座を根run_oneで保存し、政策・待機・親・全8期間を再読込する。
    引数: なし。
    返り値: None。正式損益を作らず、新work内の人工保存だけを行う。
    """
    session = '2000-01-03_人工'
    prepared = {}
    for symbol in catalog.SYMBOLS:
        prepared.update(support.prepared_fixture(catalog.catalog()[0], symbol, 1))
    for value in prepared.values():
        signal = value['signal']
        candidates = [[int(signal['mapped'][i]), int(i), int(signal['event'][i]), -1, -1]
                      for i in np.flatnonzero(signal['event'])]
        value['trend_candidate_state'] = {'candidates': np.asarray(candidates, float).reshape(-1, 5),
                                          '種類': '固定した人工eventのmetadata。実J8候補の抽出ではない。'}
        signal['execution_lp_index'] = np.full(len(value['record']['time_s']), -1, np.int64)
    serial = 1
    base = HERE / f'root_preflight/人工保存往復_{serial:05d}'
    while base.exists():
        serial += 1
        base = HERE / f'root_preflight/人工保存往復_{serial:05d}'
    count = 0
    for config in catalog.catalog():
        research.run_one(config, [session], base, prepared)
        saved_all = research.read(base / 'ledgers' / (config['id']+'.pkl'))
        rows = research.read(base / 'results' / (config['id']+'.json'))['rows']
        for symbol in catalog.SYMBOLS:
            key = session, symbol
            output = strategy.play(config, key, prepared)
            saved = saved_all[key]
            assert len(output['trades']) >= 1, config['id']
            for name in ('watch_state', 'trend_exit_state', 'entry_policy_state', 'entry_cap_state', 'growth_state'):
                trace = restore(saved[name+'_changes'], len(output['curve']))
                np.testing.assert_array_equal(trace, output[name+'_trace'])
                assert hashlib.sha256(trace.tobytes()).hexdigest() == saved[name+'_SHA256']
            for name in ('orders', 'trades', 'entry_parent_diagnostics', 'entry_wait_events',
                         'trend_parent_diagnostics', 'entry_policy_events', 'entry_cap_parent_diagnostics',
                         'growth_events', 'growth_cohorts', 'growth_parent_diagnostics'):
                np.testing.assert_array_equal(saved[name], output[name])
            for name in ('growth_state_columns', 'growth_event_columns', 'growth_event_codes',
                         'growth_cohort_columns', 'growth_parent_columns'):
                assert saved[name] == output[name]
            assert saved['entry_cap_state_columns'] == output['entry_cap_state_columns']
            assert saved['entry_cap_parent_columns'] == output['entry_cap_parent_columns']
            assert saved['entry_policy_state_columns'] == output['entry_policy_state_columns']
            assert saved['entry_policy_event_columns'] == output['entry_policy_event_columns']
            assert saved['entry_policy_event_codes'] == output['entry_policy_event_codes']
            np.testing.assert_array_equal(saved['entry_support_state_trace'], output['entry_support_state_trace'])
            assert saved['entry_support_state_rows'] == len(output['entry_support_state_trace'])
            assert saved['entry_support_columns'] == output['entry_support_columns']
            assert saved['entry_support_input_SHA256'] == output['entry_support_input_SHA256']
            assert saved['entry_support_state_SHA256'] == hashlib.sha256(
                output['entry_support_state_trace'].tobytes()).hexdigest()
            for name in ('全31', '前16', '後15', '旧30', '後14', '追加1', 'デイ', 'ナイト'):
                values = research.accounting.aggregate(rows, symbol, [session])
                assert values['session_count'] == 1
                stable = research.stability(rows, config, prepared, [session])[symbol]
                assert stable['session_count'] == 1
                count += 1
    paths = [HERE / name for name in ('根台帳の保存往復を確かめる.py', 'engine.py', 'strategy.py',
                                      'catalog.py', 'accounting.py', 'research.py', 'engine_preflight/support.py', 'engine_preflight/selfcheck.py')]
    research.save(HERE / 'root_preflight/全20人工の根台帳と実建玉群及び固定予算追加状態の保存往復.json', dict(
        全合格=True, 人工条件数=20, 人工口座数=40, 全8商品期間=count,
        保存先=str(base.relative_to(research.ROOT)), 新支持源及び待機出口及び固定予算追加診断一致=True,
        期間の範囲='全8期間へ同じ明示人工1場を入力。実際の日夜分類や収益性能の証明ではない。',
        正式新損益実行=0, API取得=0, 実注文=0,
        SHA256={str(path.relative_to(research.ROOT)): research.data.digest(path) for path in paths}))
    print('根の全20人工40口座の実建玉群・固定予算追加状態と全8期間終端が一致しました。', flush=True)


if __name__ == '__main__':
    main()
