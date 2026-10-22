"""両市場逆行で部分返済する核の互換性と時系列順序を架空値で検査する。"""

import time
import numpy as np
from common130 import HERE, save, reference
from author_test130 import fixture
import night_exit130
import night_confirm130


def main():
    """
    機能: 旧0～3の互換、確認待機、未知、発注後の確定、上下対称を調べる。
    引数: なし。架空経路だけを生成する。
    返り値: None。証跡を保存する。実市場の金融再生は0。
    """
    checks = 0
    prices = np.array([100.5, 101.5, 102., 104.5, 105., 104., 104., 104., 104., 103., 102., 98., 98.])
    for side in (1, -1):
        for quantity in (5, 10):
            args = fixture(prices.copy(), side, quantity)
            market = args[7]
            no_confirm = night_confirm130.simulate.py_func(*args, 4)
            assert not np.any(no_confirm[0][:, 6] == 76.)
            market[7:, 4] = market[7:, 6] = -side
            yes = night_confirm130.simulate.py_func(*args, 4)
            partial = yes[0][yes[0][:, 6] == 76.]
            assert len(partial) == 1 and partial[0, 1] == 7 and partial[0, 0] == 8
            assert partial[0, 4] == quantity // 2
            market[7, 11] = 0.
            unknown = night_confirm130.simulate.py_func(*args, 4)
            assert unknown[0][unknown[0][:, 6] == 76.][0, 1] == 8
            market[7, 11] = 1.
            args[4][8] = False
            market[8:, 4] = market[8:, 6] = side
            pending = night_confirm130.simulate.py_func(*args, 4)
            partial = pending[0][pending[0][:, 6] == 76.]
            assert len(partial) == 1 and partial[0, 1] == 7 and partial[0, 0] == 9
            checks += 5
    rng = np.random.default_rng(1303)
    for retest in (0, 1):
        for quantity in (5, 10):
            for sample in range(12):
                prefix = [100.5, 101.5, 102.] if not retest else [101., 104., 100.8, 102., 102.]
                values = np.r_[prefix, 102.+rng.normal(0., 1.3, 45).cumsum()]
                direct = fixture(values.copy(), 1, quantity, retest)
                reflected = fixture(values.copy(), -1, quantity, retest)
                signs = rng.choice([-1., 0., 1.], (len(values)-6, 4))
                direct[7][6:, 4:8] = signs
                reflected[7][6:, 4:8] = -signs
                for style in range(4):
                    old = night_exit130.simulate.py_func(*direct, style)
                    new = night_confirm130.simulate.py_func(*direct, style)
                    for a, b in zip(old, new):
                        np.testing.assert_array_equal(a, b)
                        checks += 1
                result = night_confirm130.simulate.py_func(*direct, 4)
                mirror = night_confirm130.simulate.py_func(*reflected, 4)
                np.testing.assert_allclose(result[2][:, [0, 2, 3]], mirror[2][:, [0, 2, 3]], atol=1e-8)
                np.testing.assert_array_equal(result[0][:, 3], -mirror[0][:, 3])
                changed = tuple(x.copy() if isinstance(x, np.ndarray) else x for x in direct)
                changed[7][25:, :] = np.nan
                changed[1][25:] += 200.
                after = night_confirm130.simulate.py_func(*changed, 4)
                np.testing.assert_array_equal(result[2][:25], after[2][:25])
                checks += 3
                if sample == 0:
                    compiled = night_confirm130.simulate(*direct, 4)
                    for a, b in zip(result, compiled):
                        np.testing.assert_array_equal(a, b)
                        checks += 1
    save(HERE / f"両市場確認出口の作者人工_{time.time_ns()}.json",
         dict(passed=True, checks=checks, financial_replays=0, real_data_reads=0,
              sources={n: reference(HERE / n) for n in
                       ("night_confirm130.py", "run_confirm130.py", "author_confirm130.py")}))
    print("両市場確認出口人工合格", checks, flush=True)


if __name__ == "__main__":
    main()
