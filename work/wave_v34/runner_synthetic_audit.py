"""部分返済・前組利益・利益未経験組を用いて返却計測を検算する。"""

import numpy as np
import scheduler_runner as runner


def main() -> None:
    """機能: 金銭の経路から独立に決めた期待値と集計を照合する。

    引数: なし。返り値: なし (None)。売買再生・成績探索は行わない。
    """
    # 前組の確定益100は今回の含み益へ混ぜない。部分返済後も同じ組。
    curve = np.zeros((10, 8))
    curve[:, 0] = [100, 90, 160, 130, 140, 140, 138, 136, 125, 125]
    curve[:, 1] = [100, 100, 100, 120, 140, 140, 140, 140, 125, 125]
    result = {'curve': curve, 'cycles': np.array([
        [0, 1, 4, 40, 50, 10, 5, 5, 1, 2],
        [1, 6, 8, -15, 50, 10, 5, 5, -1, 1]], dtype=float)}
    rows = runner.retracements(result, {'time_s': np.arange(10.) * 60}, 10.)
    assert rows[0]['peak_yen'] == 600 and rows[0]['final_yen'] == 400
    assert rows[0]['retracement_yen'] == 200 and rows[0]['retracement_r'] == .4
    assert rows[0]['positive_peak'] is True and rows[0]['holding_minutes'] == 3
    assert rows[1]['peak_yen'] == 0 and rows[1]['final_yen'] == -150
    assert rows[1]['retracement_yen'] == 150 and rows[1]['positive_peak'] is False
    total = runner.retracement_totals(rows)
    np.testing.assert_allclose([total['all']['sum_yen'], total['all']['sum_r'],
                               total['all']['mean_r'], total['all']['median_r']], [350, .7, .35, .35])
    assert total['all']['cycles'] == 2 and total['positive_peak']['cycles'] == 1
    assert total['positive_peak']['sum_yen'] == 200
    empty = runner.retracement_totals([])
    assert empty['all']['mean_r'] is None and empty['all']['sum_yen'] == 0
    # ----------------------------------------
    # 影の新設だけを選び、未参加理由を保有・休止・既設・その他へ排他的に分ける。
    events = [[n, row, 1, 102, 4, 900, 5] for n, row in enumerate((1, 3, 5, 7, 9))]
    shadow = {'prepare_events': events, 'entry_preparations': [[0, 2, 0, 1], [1, 4, 1, 3]]}
    actual = {'prepare_events': np.array(events[:1], dtype=float),
              'entry_preparations': np.array([[0, 2, 0, 1]], dtype=float),
              'curve': np.zeros((10, 8)), 'cycles': np.array([[0, 2, 4]], dtype=float),
              'atr_curve': np.full((10, 12), np.nan)}
    actual['curve'][3, 2] = 5
    actual['atr_curve'][7, 9] = 4
    ready = {'time_s': np.array([0, 60, 120, 180, 240, 300, 360, 600, 660, 720], dtype=float)}
    counts = runner.gate_metrics(actual, shadow, ready, True)
    assert counts == dict(zip(runner.GATE_FIELDS, [5, 1, 1, 0, 4, 2, 1, 1, 0, 1, 1, 1, 1]))
    mask = runner.prepare_mask(shadow, 10)
    assert mask.dtype == np.bool_ and np.flatnonzero(mask).tolist() == [1, 3, 5, 7, 9]
    assert not mask[2] and not mask[4], '影の約定行を許可にしない'
    broken_rejected = 0
    for field, column in (('prepare_events', 3), ('entry_preparations', 1)):
        broken = dict(actual)
        broken[field] = actual[field].copy()
        broken[field][0, column] += 1
        try:
            runner.gate_metrics(broken, shadow, ready, True)
        except AssertionError:
            broken_rejected += 1
    try:
        runner.prepare_mask({'prepare_events': events + events[:1]}, 10)
    except AssertionError:
        broken_rejected += 1
    assert broken_rejected == 3
    runner.save(runner.HERE / 'runner_synthetic_audit.json', {
        '監査完了': True, '部分返済と前組の実現益を区別': True,
        '含み利益なし損失組を隠さない': True, '取引数平均中央値': True, '空集合': True,
        '準備行のみ許可': True, '見送り4理由排他': True, '破損拒否数': broken_rejected,
        '実装SHA256': runner.digest(runner.HERE / 'scheduler_runner.py'),
        '検査SHA256': runner.digest(runner.HERE / 'runner_synthetic_audit.py')})
    print('返却計測の独立経路3例を確認')


if __name__ == '__main__':
    main()
