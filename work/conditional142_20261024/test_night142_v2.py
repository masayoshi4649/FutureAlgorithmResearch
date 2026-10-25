"""初回縮小の選択・旧条件同値・費用を人工データで検査する。"""

import copy
import unittest
import numpy as np
import night_trader142 as old
import night_trader142_v2 as revised
import night_selector142_v2 as revised_selector
import test_night142 as previous


previous.trader = revised
previous.selector = revised_selector
NightSelectorProperties = previous.NightSelectorProperties


class InitialSizeProperties(unittest.TestCase):
    """実データの金融再生は行わず、数量選択の機械的整合だけを検査する。"""

    def test_old_five_exact(self):
        """
        機能: 既存5条件の設定と全注文・診断を保持することを確認する。
        引数: self(InitialSizeProperties)は試験状態。
        返り値: None。
        """
        self.assertEqual(old.configurations(), revised.configurations()[:5])
        for c in old.configurations():
            d, raw = previous.data()
            d[3][3:, 4:8] = -.1
            raw[3:] *= -1.
            d[2][6:, 7] = -2.
            d[2][6:, 11] = -2.
            c = dict(c, activation_after_us_seconds=0., entry_cutoff_seconds=0.)
            a, an = old.replay(*d, c, extra=raw)
            b, bn = revised.replay(*d, c, extra=raw)
            np.testing.assert_array_equal(a, b)
            self.assertEqual(an, bn)

    def test_quantity_fee_and_missing(self):
        """
        機能: 初回だけの切捨て半減、最低1枚、費用、欠測時に縮小しない仕様を確認する。
        引数: self(InitialSizeProperties)は試験状態。
        返り値: None。
        """
        for c in revised.configurations()[5:]:
            c = dict(c, activation_after_us_seconds=0., entry_cutoff_seconds=0.)
            for risk in (10., 20., 100.):
                for unknown in ('なし','相手時計','相手OFI','片側支持'):
                    d, raw = previous.data()
                    d[0]['atr'][:] = risk
                    d[3][:, 5] = -.2
                    d[3][:, 7] = -.2
                    raw[:, 0] = -.1
                    raw[:, 2] = -.1
                    if unknown == '相手時計': d[3][:, 11] = 0.
                    if unknown == '相手OFI': raw[:, 2] = np.nan
                    if unknown == '片側支持': d[3][:, 7] = .2
                    orders, notes = revised.replay(*d, c, extra=raw)
                    native = max(1, min(10, int(120./risk)))
                    before = max(1, native//2)
                    expected = max(1, before//2) if unknown == 'なし' else before
                    self.assertTrue(np.all(orders[:, 4] == expected))
                    self.assertTrue(np.all(orders[:, 9] == expected*385//10))
                    decision = [n for n in notes if n['種類'] == 10]
                    self.assertEqual(len(decision), 1)
                    self.assertEqual(decision[0]['値1'], before)
                    self.assertEqual(decision[0]['値2'], 1. if unknown == 'なし' else 0.)
                    cash = np.sum(-orders[:, 3]*orders[:, 4]*orders[:, 5]*100.-orders[:, 9])
                    gross = (orders[-1, 5]-orders[0, 5])*expected*100.
                    self.assertAlmostEqual(cash, gross-2*(expected*385//10), places=7)

    def test_mirror_prefix_and_no_reduction_after_entry(self):
        """
        機能: 売買反転・未知後半変更に不変で、保有後の逆行では枚数を再計算しないことを確認する。
        引数: self(InitialSizeProperties)は試験状態。
        返り値: None。
        """
        for c in revised.configurations()[5:]:
            c = dict(c, activation_after_us_seconds=0., entry_cutoff_seconds=0.)
            d, raw = previous.data()
            d[3][:, 5:8:2] = -.2
            raw[:, [0,2]] = -.1
            a, _ = revised.replay(*d, c, extra=raw)
            mirror = copy.deepcopy(d)
            mirror[1]['bid'], mirror[1]['ask'] = 2000.-d[1]['ask'], 2000.-d[1]['bid']
            for col in (0,1,8): mirror[2][:, col] = 2000.-d[2][:, col]
            mirror[2][:, 3], mirror[2][:, 4] = 2000.-d[2][:, 4], 2000.-d[2][:, 3]
            for col in (6,7,10,11,13): mirror[2][:, col] *= -1.
            mirror[3][:, 4:8] *= -1.
            b, _ = revised.replay(*mirror, c, extra=-raw)
            np.testing.assert_array_equal(a[:, [0,1,2,4,6,7,8,9]], b[:, [0,1,2,4,6,7,8,9]])
            np.testing.assert_allclose(a[:, 3], -b[:, 3])
            np.testing.assert_allclose(a[:, 5], 2000.-b[:, 5])
            future = copy.deepcopy(d)
            future[3][10:, 4:8] *= -1.
            future_raw = raw.copy()
            future_raw[10:] *= -1.
            x, _ = revised.replay(*future, c, extra=future_raw)
            np.testing.assert_array_equal(a[a[:,0] < 10], x[x[:,0] < 10])
            d, raw = previous.data()
            d[3][3:, 5:8:2] = -.2
            raw[3:, [0,2]] = -.1
            orders, notes = revised.replay(*d, c, extra=raw)
            self.assertTrue(np.all(orders[:,4] == 5.))
            self.assertEqual(sum(n['種類'] == 10 for n in notes), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
