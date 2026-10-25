"""旧Nの同値を保ちながら、Qの二段階数量・注文別費用を人工価格で確認する。"""

import unittest
import numpy as np
import supplemental141 as original
import supplemental141_v2 as revised
import test_supplemental141 as prior_tests


# 旧5試験を数値条件を変えずv2へ接続し、元ファイルは変更しない。
prior_tests.s = revised
SupplementalProperties = prior_tests.SupplementalProperties


class QuantityProperties(unittest.TestCase):
    """旧関数との同値と数量による円会計の変化を確認する。"""

    def test_exact_native_quantity_mapping(self):
        """
        機能: 元10枚からの縮小とmini半減を、広い人工R範囲で元の式へ照合する。
        引数: self(QuantityProperties)は検査状態。
        返り値: None。最低1・最大5と境界丸めを検査する。
        """
        values = np.r_[np.linspace(1., 1500., 201), [119.99, 120., 120.01, 149.99, 150., 150.01]]
        for risk in values:
            native = max(1, min(10, int(10.*12.*10./risk)))
            expected = max(1, native//2)
            actual = revised.legacy_quantity(5, risk, 10., 12.)
            self.assertEqual(actual, expected)
            self.assertTrue(1 <= actual <= 5)

    def test_fixed_n_is_bytewise_same_orders(self):
        """
        機能: v2に残したN01～N03が旧版Nと同じ注文・診断を作ることを確認する。
        引数: self(QuantityProperties)は検査状態。
        返り値: None。数量方式追加が旧Nへ漏れた場合は失敗。
        """
        for mode in (1, 2, 3):
            data = prior_tests.fixture()
            data[3][3:, 4:8] = -.1
            c = prior_tests.config(mode)
            for core in (data[4], prior_tests.core_orders(data)):
                old, old_notes = original.replay(*data[:4], core, c)
                new, new_notes = revised.replay(*data[:4], core, c)
                np.testing.assert_array_equal(old, new)
                self.assertEqual(old_notes, new_notes)

    def test_q_quantity_and_fee_follow_new_risk(self):
        """
        機能: Qが新規判断Rの枚数で建て返済し、各注文の費用を切り捨てることを確認する。
        引数: self(QuantityProperties)は検査状態。
        返り値: None。旧枚数や旧手数料の流用があれば失敗。
        """
        for mode in (1, 2, 3):
            for risk in (100., 130., 180., 300., 800.):
                data = prior_tests.fixture()
                data[0]['tick'] = 10.
                data[0]['atr'][:] = risk
                c = revised.configurations()[mode+2].copy()
                c.update(activation_after_us_seconds=0., entry_cutoff_seconds=0.)
                orders, notes = revised.replay(*data, c)
                expected = max(1, max(1, min(10, int(1200./risk)))//2)
                self.assertEqual(len(orders), 2)
                self.assertTrue(np.all(orders[:, 4] == expected))
                self.assertTrue(np.all(orders[:, 9] == expected*385//10))
                self.assertEqual(sum(row['枚数'] for row in notes if row['種類'] == 3), expected)
                cash = np.sum(-orders[:, 3]*orders[:, 4]*orders[:, 5]*100.-orders[:, 9])
                gross = (orders[1, 5]-orders[0, 5])*expected*100.
                self.assertAlmostEqual(cash, gross-2*(expected*385//10), places=7)


if __name__ == '__main__':
    unittest.main(verbosity=2)
