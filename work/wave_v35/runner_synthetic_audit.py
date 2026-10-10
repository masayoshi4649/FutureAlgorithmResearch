"""条件付き短縮の活動量と同じ新規の退出差を人工台帳で検算する。"""

from copy import deepcopy

import numpy as np
import conditional_runner as runner


def fixture() -> tuple[dict, dict]:
    """機能: 悪化しても短縮しない行と、早い退出・同じ退出を含む経路を作る。

    引数: なし。返り値: 実結果と影記録 (tuple[dict,dict])。
    """
    c = np.full((15, len(runner.engine.CONDITIONAL_COLUMNS)), np.nan)
    ix = {name: i for i, name in enumerate(runner.engine.CONDITIONAL_COLUMNS)}
    for name in ('direction', 'deterioration_direction', 'shortening_enabled'):
        c[:, ix[name]] = 0
    held = [2, 3, 4, 10, 11]
    c[held, ix['direction']] = 1
    c[held, ix['initial_atr']] = 5
    c[held, ix['current_atr']] = 5
    c[[3, 4], ix['deterioration_direction']] = -1
    c[[3, 4], ix['shortening_enabled']] = 1
    c[3, ix['current_atr']] = 2
    c[4, ix['current_atr']] = 6
    c[3, ix['fixed_candidate']], c[3, ix['short_candidate']] = 100, 103
    c[4, ix['fixed_candidate']], c[4, ix['short_candidate']] = 110, 110
    events = np.zeros((2, len(runner.engine.TRAIL_EVENT_COLUMNS)))
    events[:, runner.engine.TRAIL_EVENT_COLUMNS.index('advance_kind')] = [3, 1]
    prepared = [[0, 1, 1, 100, 5, 900, 2], [1, 9, 1, 100, 5, 1200, 2]]
    linked = [[0, 2, 0, 1], [1, 10, 1, 9]]
    opened = [[2, 1, 0, 1, 2, 100, 0, 1], [10, 9, 1, 1, 2, 100, 0, 1]]
    shadow = {'prepare_events': prepared, 'entry_preparations': linked, 'orders': opened,
        'cycles': [[0, 2, 7, 6, 10, 5, 2, 2, 1, 2], [1, 10, 12, -2, 10, 5, 2, 2, 1, 1]],
        'trades': [[0, 0, 1, 2, 100, 103, 2, 7, 0, 2, 6], [1, 0, 1, 2, 100, 99, 10, 12, 0, 1, -2]]}
    actual = {name: np.array(deepcopy(shadow[name]), dtype=float) for name in shadow}
    actual['cycles'][0, 2:4] = [5, 4]
    actual['trades'][0, [5, 7, 10]] = [102, 5, 4]
    actual.update(conditional_curve=c, trail_events=events)
    return actual, shadow


def main() -> None:
    """機能: 条件回数と実際の注文変更を区別し、壊れた対応を拒否する。

    引数: なし。返り値: なし (None)。実相場を再生しない。
    """
    actual, shadow = fixture()
    times = np.arange(15, dtype=float)
    counts, pairs = runner.control_metrics(actual, shadow, {'point_value': 10.}, times)
    expected = [5, 2, 2, 1, 1, 1, 1, 1, 2, 1, 1, 1, -20., -.2, 5., 2., 2.]
    assert counts == dict(zip(runner.CONTROL_FIELDS, expected))
    assert pairs[0]['changed_repayments'] and not pairs[1]['changed_repayments']
    rejected = 0
    for kind in ('future_exit', 'different_prepare', 'different_open', 'different_risk'):
        bad = deepcopy(actual)
        if kind == 'future_exit':
            bad['cycles'][0, 2] = 8
        elif kind == 'different_prepare':
            bad['prepare_events'][0, 3] += 1
        elif kind == 'different_open':
            bad['orders'][0, 5] += 1
        else:
            bad['cycles'][0, 4] += 1
        try:
            runner.control_metrics(bad, shadow, {'point_value': 10.}, times)
        except AssertionError:
            rejected += 1
    assert rejected == 4
    serialized = deepcopy(actual)
    serialized['stats'] = np.zeros(11)
    serialized['trail_events'][0, [3, 5]] = np.nan
    stored = runner.stored_result(serialized)
    assert stored['trail_events'][0][3] is None and stored['trail_events'][0][5] is None
    assert np.array_equal(np.asarray(stored['trail_events'], dtype=float), serialized['trail_events'], equal_nan=True)
    for column, bad_value in ((0, np.nan), (3, np.inf)):
        broken = deepcopy(serialized)
        broken['trail_events'][0, column] = bad_value
        try:
            runner.stored_result(broken)
        except AssertionError:
            pass
        else:
            raise AssertionError('仕様外の非有限値を保存した')
    runner.save(runner.HERE / 'runner_synthetic_audit.json', {
        '監査完了': True, '悪化と注文変化を分離': True, '同じ新規の退出差一致': True,
        '破損拒否数': rejected, '実相場再生': False,
        '追跡未設定2列のnull往復': True, '仕様外の非有限値拒否': True,
        '実装SHA256': runner.digest(runner.HERE / 'conditional_runner.py'),
        '検査SHA256': runner.digest(runner.HERE / 'runner_synthetic_audit.py')})
    print('短縮活動量と退出差、4破損拒否を確認。')


if __name__ == '__main__':
    main()
