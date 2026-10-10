"""部分返済・前組利益・利益未経験組を用いて返却計測を検算する。"""

import numpy as np
import atr_runner as runner


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
    runner.save(runner.HERE / 'runner_synthetic_audit.json', {
        '監査完了': True, '部分返済と前組の実現益を区別': True,
        '含み利益なし損失組を隠さない': True, '取引数平均中央値': True, '空集合': True,
        '実装SHA256': runner.digest(runner.HERE / 'atr_runner.py'),
        '検査SHA256': runner.digest(runner.HERE / 'runner_synthetic_audit.py')})
    print('返却計測の独立経路3例を確認')


if __name__ == '__main__':
    main()
