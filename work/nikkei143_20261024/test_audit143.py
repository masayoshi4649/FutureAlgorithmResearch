"""金融データを使わず、00143共通監査が誤会計を見逃さないことを確認する。"""

import unittest
import numpy as np
import audit143 as audit


def sample():
    """
    機能: 部分返済・逆向き別親・無効板を含む小さな人工注文を作る。
    引数: なし。
    返り値: tuple[dict,ndarray]は入力と正しい注文。
    """
    start, _, _ = audit.bounds('2026-10-23_Day')
    count = 12
    good = np.ones(count, dtype=bool)
    good[2] = False
    data = dict(ready=dict(symbol='NK225', time_s=start+np.arange(count)*60., last=np.full(count, 101.)),
        quotes=dict(bid=np.full(count, 100.), ask=np.full(count, 102.), quote_valid=good),
        features=np.tile(np.arange(48, dtype=float), (count, 1)))
    orders = np.array([[1, 0, 1, 1, 5, 102., 1, 1, 0, 192],
                       [3, 1, 1, -1, 2, 100., 2, 0, 0, 77],
                       [4, 3, 2, -1, 2, 100., 1, 1, 0, 77],
                       [5, 4, 1, -1, 3, 100., 2, 0, 0, 115],
                       [6, 5, 2, 1, 2, 102., 2, 0, 0, 77]], dtype=float)
    return data, orders


class AuditTests(unittest.TestCase):
    """正常系だけでなく、未来約定・費用・残高の反例を検知する人工試験。"""

    def test_partial_and_hedged_union(self):
        """
        機能: 部分返済の親会計と両建てを重複計上しない保有率を検証する。
        引数: self(AuditTests)。返り値: None。
        """
        data, orders = sample()
        result = audit.orders_account(orders, data, 10, '2026-10-23_Day')
        self.assertEqual(result['net'], -1938.)
        self.assertEqual(result['fees'], 538)
        self.assertEqual(result['parents'], 2)
        self.assertEqual(result['held_minutes'], 5.)
        self.assertEqual(result['hedged_minutes'], 1.)
        self.assertAlmostEqual(result['average_gross_quantity'], 20./420.)

    def test_next_normal_not_next_time(self):
        """
        機能: 正常原行を飛び越した約定を検出する。
        引数: self(AuditTests)。返り値: None。
        """
        data, orders = sample()
        orders[1, 0] = 4
        with self.assertRaises(AssertionError):
            audit.orders_account(orders, data)

    def test_no_same_row_fill(self):
        """
        機能: 判断と同じ原行での約定を検出する。
        引数: self(AuditTests)。返り値: None。
        """
        data, orders = sample()
        orders[0, 1] = 1
        with self.assertRaises(AssertionError):
            audit.orders_account(orders, data)

    def test_fee_floor(self):
        """
        機能: 5枚の192.5円を192円に切り捨てない誤りを検出する。
        引数: self(AuditTests)。返り値: None。
        """
        data, orders = sample()
        orders[0, 9] = 193
        with self.assertRaises(AssertionError):
            audit.orders_account(orders, data)

    def test_unknown_uid(self):
        """
        機能: 他の建玉を返済したように扱う誤りを検出する。
        引数: self(AuditTests)。返り値: None。
        """
        data, orders = sample()
        orders[1, 8] = 9
        with self.assertRaises(AssertionError):
            audit.orders_account(orders, data)

    def test_quantity_cap(self):
        """
        機能: 片方向上限を超える保有を検出する。
        引数: self(AuditTests)。返り値: None。
        """
        data, orders = sample()
        with self.assertRaises(AssertionError):
            audit.orders_account(orders, data, 4)

    def test_no_open_end(self):
        """
        機能: 未返済玉を損益集計から落とす誤りを検出する。
        引数: self(AuditTests)。返り値: None。
        """
        data, orders = sample()
        with self.assertRaises(AssertionError):
            audit.orders_account(orders[:-1], data)

    def test_fractional_quantity(self):
        """
        機能: 整数変換で小数枚数を黙って切り捨てることを防ぐ。
        引数: self(AuditTests)。返り値: None。
        """
        data, orders = sample()
        orders[0, 4] = 5.1
        with self.assertRaises(AssertionError):
            audit.orders_account(orders, data)

    def test_price_side(self):
        """
        機能: 買いをbidで有利に約定する誤りを検出する。
        引数: self(AuditTests)。返り値: None。
        """
        data, orders = sample()
        orders[0, 5] = 100.
        with self.assertRaises(AssertionError):
            audit.orders_account(orders, data)

    def test_mirror_and_input_unchanged(self):
        """
        機能: 鏡像後の損益同値・二度反転復元・元配列不変を確認する。
        引数: self(AuditTests)。返り値: None。
        """
        data, orders = sample()
        snapshot = data['features'].copy()
        reflected = audit.mirror_data(data, 100., 200.)
        mirror_orders = audit.mirror_orders(orders, 100.)
        audit.assert_mirror(orders, mirror_orders, 100.)
        self.assertEqual(audit.orders_account(orders, data)['net'], audit.orders_account(mirror_orders, reflected)['net'])
        restored = audit.mirror_data(reflected, 100., 200.)
        np.testing.assert_array_equal(snapshot, restored['features'])
        np.testing.assert_array_equal(snapshot, data['features'])

    def test_prefix_and_mutation_detection(self):
        """
        機能: 後半のみ変更し、過去約定の不正変更を検知する。
        引数: self(AuditTests)。返り値: None。
        """
        data, orders = sample()
        reflected = audit.mirror_data(data, 100., 200.)
        future = audit.future_data(data, reflected, 4)
        np.testing.assert_array_equal(data['features'][:4], future['features'][:4])
        np.testing.assert_array_equal(reflected['features'][4:], future['features'][4:])
        changed = orders.copy()
        changed[changed[:, 0] >= 4, 5] += 1.
        self.assertEqual(audit.assert_prefix(orders, changed, 4), 2)
        changed[0, 5] += 1.
        with self.assertRaises(AssertionError):
            audit.assert_prefix(orders, changed, 4)

    def test_history_schemas_and_feature_widths(self):
        """
        機能: 9/15列履歴と30/36/48列特徴の二度鏡像が元へ戻ることを確認する。
        引数: self(AuditTests)。返り値: None。
        """
        data, _ = sample()
        for width in (30, 36, 48):
            source = dict(data, features=data['features'][:, :width])
            reflected = audit.mirror_data(source, 100., 200.)
            restored = audit.mirror_data(reflected, 100., 200.)
            np.testing.assert_array_equal(source['features'], restored['features'])
        for width, transform in ((9, audit.mirror_history), (15, audit.mirror_history15)):
            history = np.tile(np.arange(width, dtype=float), (4, 1))
            history[0] = np.nan
            np.testing.assert_array_equal(history, transform(transform(history, 100.), 100.))

    def test_night_excludes_03_06(self):
        """
        機能: 02:50から03:10までの保有を10分だけ算入する。
        引数: self(AuditTests)。返り値: None。
        """
        start, _, end = audit.bounds('2026-10-23_Night')
        times = np.array([start, end-600., end+600.])
        orders = np.array([[1, 0, 1, 1, 1, 100., 1, 1, 0, 38],
                           [2, 1, 1, -1, 1, 101., 2, 0, 0, 38]])
        result = audit.holding(orders, times, '2026-10-23_Night')
        self.assertEqual(result['evaluation_minutes'], 600.)
        self.assertEqual(result['held_minutes'], 10.)
        self.assertEqual(result['excluded_03_06_minutes'], 10.)

    def test_unregistered_replay_denied(self):
        """
        機能: 登録ファイルがない新金融再生を拒否する。
        引数: self(AuditTests)。返り値: None。
        """
        with self.assertRaises(AssertionError):
            audit.registration(audit.HERE/'存在しない登録.json')


if __name__ == '__main__':
    unittest.main(verbosity=2)
