"""旧互換と、部分返済後に残った損失を架空経路で確認する。"""

import os
import sys
import time
import numpy as np
from common130 import HERE, PREV, save, reference

os.environ["NUMBA_CACHE_DIR"] = str(HERE / "jit_artificial_author")
sys.path.insert(0, str(PREV))
import night_retest129c
import night_exit130


def fixture(prices, side, quantity=5, retest=0):
    """
    機能: 架空の方向支持と価格経路を同時に作る。
    引数: prices(ndarray)、side(int)、quantity(int)、retest(int)は価格と方向等。
    返り値: tupleは核への引数。実市場データは含まない。
    """
    n = len(prices)
    times = np.arange(n, dtype=float) * 60.
    h = np.ones((n, 15))
    h[:, 1], h[:, 3], h[:, 4], h[:, 5] = 95., 100., 90., 1.
    market = np.ones((n, 12))
    market[:, 0], market[:, 1] = prices, prices
    market[:, 2:4] = 4.
    if side < 0:
        prices = 200. - prices
        h[:, 1], h[:, 3], h[:, 4] = 105., 110., 100.
        h[:, 6:8] *= -1
        h[:, 10:12] *= -1
        market[:, 0], market[:, 1] = prices, prices
        market[:, 4:8] *= -1
    parameters = np.array([2., 1., 1., .75, 1., 300., .25, 900., .35, .25,
                           6. if retest else 3., 2., 0., 1e9])
    return (times, prices, prices-.25, prices+.25, np.ones(n, dtype=np.bool_),
            np.full(n, 4.), h, market, 0., times[-2], -10000., .5,
            quantity, 1000. if quantity == 5 else 10., 418 if quantity == 5 else 110,
            parameters, retest)


def main():
    """
    機能: 手計算、旧版同値、上下対称、未来改変による過去不変を確認する。
    引数: なし。
    返り値: None。作成者の人工検査証跡を保存する。金融再生は行わない。
    """
    checks = 0
    manual = fixture(np.array([100.5,101.5,102.,104.5,105.,104.,104.,101.,99.,98.,98.]), 1)
    orders, trades, curve = night_exit130.simulate.py_func(*manual, 2)
    assert orders[:, 4].tolist() == [5, 2, 3], orders
    assert trades[:, 8].sum() == -10917. and curve[-1, 0] == -10917.
    assert trades[:, 7].sum() == 417.
    checks += 3
    rng = np.random.default_rng(130)
    for retest in (0, 1):
        initial = [100.5,101.5,102.] if not retest else [101.,104.,100.8,102.,102.]
        for quantity in (5, 10):
            for seed in range(20):
                prices = np.r_[initial, 102. + np.cumsum(rng.normal(0., 1.2, 50))]
                direct = fixture(prices, 1, quantity, retest)
                reflected = fixture(prices, -1, quantity, retest)
                old = night_retest129c.simulate.py_func(*direct)
                new = night_exit130.simulate.py_func(*direct, 0)
                for left, right in zip(old, (new[0], new[1][:, :14], new[2])):
                    np.testing.assert_array_equal(left, right)
                    checks += 1
                for style in range(4):
                    result = night_exit130.simulate.py_func(*direct, style)
                    mirror = night_exit130.simulate.py_func(*reflected, style)
                    np.testing.assert_allclose(result[2][:, [0,2,3]], mirror[2][:, [0,2,3]], atol=1e-8)
                    np.testing.assert_array_equal(result[0][:, 3], -mirror[0][:, 3])
                    for parent in result[0][result[0][:, 7] == 1, 2]:
                        po = result[0][result[0][:, 2] == parent]
                        assert po[po[:, 7] == 1, 4].sum() == po[po[:, 7] == 0, 4].sum()
                    cut = 25
                    changed = prices.copy()
                    changed[cut:] += rng.normal(0., 50., len(changed)-cut)
                    changed_result = night_exit130.simulate.py_func(*fixture(changed, 1, quantity, retest), style)
                    np.testing.assert_array_equal(result[2][:cut], changed_result[2][:cut])
                    checks += 4
                    if seed == 0:
                        compiled = night_exit130.simulate(*direct, style)
                        for a, b in zip(result, compiled):
                            np.testing.assert_array_equal(a, b)
                            checks += 1
    save(HERE / f"作成者人工_{time.time_ns()}.json", dict(passed=True, checks=checks, financial_replays=0,
         real_data_reads=0, source=reference(HERE / "night_exit130.py"),
         author=reference(HERE / "author_test130.py"), partial_net=-10917, partial_fees=417))
    print("作成者人工合格", checks, flush=True)


if __name__ == "__main__":
    main()
