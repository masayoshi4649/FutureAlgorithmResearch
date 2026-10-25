"""初回方向固定の因果性・待機競合・旧6条件同値を人工データで検査する。"""

import copy
import unittest
import numpy as np
import supplemental141_v2 as previous
import supplemental141_v3 as revised
import test_supplemental141 as base_tests
import test_supplemental141_v2 as quantity_tests


base_tests.s = revised
quantity_tests.revised = revised
SupplementalProperties = base_tests.SupplementalProperties
QuantityProperties = quantity_tests.QuantityProperties


def config(method):
    """
    機能: 人工時計用に開始と終了直前の制限だけを短縮する。
    引数: method(str)はQ04/Q05/Q06等の固定ID。
    返り値: dictは人工用設定。実市場設定を変更しない。
    """
    c = next(c for c in revised.configurations() if c['id'] == method).copy()
    c.update(activation_after_us_seconds=0., entry_cutoff_seconds=0.)
    return c


class FixedDirectionProperties(unittest.TestCase):
    """売買有効性ではなく、新状態の機械的整合と因果順を確認する。"""

    def test_old_six_exact(self):
        """
        機能: 旧6条件の設定・注文・診断がv2と完全一致することを確認する。
        引数: self(FixedDirectionProperties)は検査状態。
        返り値: None。
        """
        self.assertEqual(previous.configurations(), revised.configurations()[:6])
        for method in previous.configurations():
            for risk in (10., 20., 35.):
                for delayed in (False, True):
                    data = base_tests.fixture()
                    data[0]['atr'][:] = risk
                    data[3][3:, 4:8] = -.1
                    if delayed:
                        data[2][:4, 6] = -1.
                    c = config(method['id'])
                    for core in (data[4], base_tests.core_orders(data, 3, 4, 9, 10)):
                        a, an = previous.replay(*data[:4], core, c)
                        b, bn = revised.replay(*data[:4], core, c)
                        np.testing.assert_array_equal(a, b)
                        self.assertEqual(an, bn)

    def test_keep_first_direction_and_reprice(self):
        """
        機能: 待機中の票変更に便乗せず、初回方向の支持時に新R・新価格で入る。
        引数: self(FixedDirectionProperties)は検査状態。
        返り値: None。
        """
        for method in ('Q04', 'Q05', 'Q06'):
            data = base_tests.fixture()
            data[2][:6, 6] = -1.
            data[2][:6, 10] = -1.
            data[2][2:, 8] = 1010.
            data[2][2:, 13] = -1.
            data[0]['atr'][6:] = 20.
            orders, notes = revised.replay(*data, config(method))
            self.assertEqual(tuple(orders[0, :2]), (7., 6.))
            self.assertEqual(orders[0, 3], 1.)
            self.assertEqual(orders[0, 5], data[1]['ask'][7])
            self.assertEqual(orders[0, 4], 3.)
            fixed = [n for n in notes if n['種類'] == 7]
            self.assertEqual(len(fixed), 1)
            self.assertEqual(fixed[0]['原行'], 0)
            self.assertEqual(fixed[0]['方向'], 1)
            entered = next(n for n in notes if n['種類'] == 3)
            self.assertEqual(entered['値1'], 20.)

    def test_prepare_eligibility_and_core_priority(self):
        """
        機能: 開始前や過大気配差では票を固定せず、待機中の主担当新規を優先する。
        引数: self(FixedDirectionProperties)は検査状態。
        返り値: None。
        """
        for method in ('Q04', 'Q05', 'Q06'):
            data = base_tests.fixture()
            data[2][:2, 8] = 1010.
            data[2][:2, 13] = -1.
            data[1]['ask'][:2] += 20.
            orders, notes = revised.replay(*data, config(method))
            fixed = next(n for n in notes if n['種類'] == 7)
            self.assertEqual(fixed['原行'], 2)
            self.assertEqual(orders[0, 3], 1.)
            c = config(method)
            c['activation_after_us_seconds'] = 10.
            orders, notes = revised.replay(*data, c)
            self.assertEqual(next(n for n in notes if n['種類'] == 7)['原行'], 2)
            waiting = base_tests.fixture()
            waiting[2][:6, 6] = -1.
            original = base_tests.core_orders(waiting, 3, 4, 9, 10)
            orders, notes = revised.replay(*waiting[:4], original, config(method))
            np.testing.assert_array_equal(orders, original)
            self.assertTrue(any(n['種類'] == 7 for n in notes))
            self.assertFalse(any(n['種類'] == 3 for n in notes))

    def test_zero_support_and_adverse_exit(self):
        """
        機能: Q06の一市場同値許可・両市場同値禁止とQ05だけの逆行返済を確認する。
        引数: self(FixedDirectionProperties)は検査状態。
        返り値: None。
        """
        data = base_tests.fixture()
        data[2][:, 10] = 0.
        for method in ('Q04', 'Q05'):
            self.assertEqual(len(revised.replay(*data, config(method))[0]), 0)
        orders, _ = revised.replay(*data, config('Q06'))
        self.assertEqual(tuple(orders[0, :2]), (1., 0.))
        data[2][:, 6] = 0.
        self.assertEqual(len(revised.replay(*data, config('Q06'))[0]), 0)
        data = base_tests.fixture()
        data[3][3:, 4:8] = -.1
        for method in ('Q04', 'Q05', 'Q06'):
            orders, _ = revised.replay(*data, config(method))
            self.assertEqual(orders[-1, 6], 1413. if method == 'Q05' else 93.)
            if method == 'Q05':
                self.assertEqual(tuple(orders[-1, :2]), (7., 6.))

    def test_mirror_future_fee_and_flat(self):
        """
        機能: 新3条件の上下対称・未知後半変更・自己次行執行・数量費用と場末返済を確認する。
        引数: self(FixedDirectionProperties)は検査状態。
        返り値: None。
        """
        for method in ('Q04', 'Q05', 'Q06'):
            data = base_tests.fixture()
            data[2][:3, 6] = -1.
            data[3][7:, 4:8] = -.1
            data[0]['atr'][:] = 20.
            mirror = copy.deepcopy(data)
            mirror[1]['bid'], mirror[1]['ask'] = 2000.-data[1]['ask'], 2000.-data[1]['bid']
            for col in (0, 1, 8):
                mirror[2][:, col] = 2000.-data[2][:, col]
            mirror[2][:, 3], mirror[2][:, 4] = 2000.-data[2][:, 4], 2000.-data[2][:, 3]
            for col in (6, 7, 10, 11, 13):
                mirror[2][:, col] *= -1.
            mirror[3][:, 4:8] *= -1.
            a, _ = revised.replay(*data, config(method))
            b, _ = revised.replay(*mirror, config(method))
            np.testing.assert_allclose(a[:, [0, 1, 2, 4, 6, 7, 8, 9]], b[:, [0, 1, 2, 4, 6, 7, 8, 9]])
            np.testing.assert_allclose(a[:, 3], -b[:, 3])
            np.testing.assert_allclose(a[:, 5], 2000.-b[:, 5])
            future = copy.deepcopy(data)
            future[1]['bid'][10:] += 2.
            future[1]['ask'][10:] += 2.
            x, _ = revised.replay(*future, config(method))
            np.testing.assert_array_equal(a[a[:, 0] < 10], x[x[:, 0] < 10])
            self.assertTrue(np.all(a[:, 0] == a[:, 1]+1))
            self.assertTrue(np.all(a[:, 4] == 3.))
            self.assertTrue(np.all(a[:, 9] == 115.))
            self.assertEqual(a[a[:, 7] == 1, 4].sum(), a[a[:, 7] == 0, 4].sum())


if __name__ == '__main__':
    unittest.main(verbosity=2)
