"""第二巡の押戻り入口と第一巡互換の人工検査。"""

import json
from pathlib import Path
import unittest
import numpy as np
import engine_round2
import tests as original
from accounting import account

HERE = Path(__file__).resolve().parent
CONFIGS = json.loads((HERE / 'configs_round2.json').read_text(encoding='utf-8'))
EXTRA = dict(pullback_points=0., rebound_points=0., pullback_expiry_seconds=900.)
original.BASE = dict(original.BASE, **EXTRA)
original.CONFIGS = [dict(c, **EXTRA) for c in original.CONFIGS]
original.simulate = engine_round2.simulate
original.prepare = engine_round2.prepare


class RoundTwoChecks(unittest.TestCase):
    """押戻り入口の因果性と対称性を確認する。"""

    def test_押戻りなしの一直線では新規しない(self):
        """機能: 直線上昇を押戻りと誤認しない。

        引数: self(RoundTwoChecks)。返り値: None。
        """
        data = original.artificial(60000. + np.arange(1800) * .4)
        for config in CONFIGS[5:]:
            self.assertEqual(len(engine_round2.simulate(data, config)['orders']), 0)

    def test_追加全条件で上下反転と未来改変(self):
        """機能: 同じ人工往復で反転対称・未来不使用・枚数を検査する。

        引数: self(RoundTwoChecks)。返り値: None。
        """
        t = np.arange(4800)
        prices = 60000. + .15 * t + 90. * np.sin(t/75.)
        data = original.artificial(prices, cutoff=4700.)
        inverse = original.artificial(120000. - prices, cutoff=4700.)
        total = 0
        for config in CONFIGS:
            a = engine_round2.simulate(data, config)['orders']
            b = engine_round2.simulate(inverse, config)['orders']
            np.testing.assert_array_equal(a[:, [0, 1, 2, 4, 6, 7, 8, 9]], b[:, [0, 1, 2, 4, 6, 7, 8, 9]])
            np.testing.assert_array_equal(a[:, 3], -b[:, 3])
            account(a, data)
            short = engine_round2.simulate(original.crop(data, 2600), config)['orders']
            np.testing.assert_array_equal(a[a[:, 0] < 2600], short)
            if config['pullback_points']:
                total += len(a)
        self.assertGreater(total, 0)


if __name__ == '__main__':
    suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(original.EngineChecks),
                               unittest.defaultTestLoader.loadTestsFromTestCase(RoundTwoChecks)])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
