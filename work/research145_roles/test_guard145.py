"""40分確認ドテンの限定変更と情報公開の因果性を人工経路で検査する。"""

from copy import deepcopy
import unittest
import numpy as np

import addon_guard145 as guard
import trader_guard145 as changed
import trader145 as original
from config145 import configurations
from test145 import fixture, mirror
from run145 import check_orders


def flip_fixture():
    """
    機能: 買いの返済後に短期下向きが続き、旧確認ドテンが発生する人工資料を作る。
    引数: なし。
    返り値: tuple[dict,dict]は資料と設定。通常帯突破は転換区間で発生させない。
    """
    data, config = fixture()
    for key, value in ((3, -20.), (4, -50.), (6, 1500.), (12, -.1), (13, -.1), (30, 1500.),
                       (0, 2000.), (1, 500.)):
        data['features'][180:, key] = value
    data['features'][100:, 0] = 2000.
    data['features'][100:, 1] = 500.
    return data, config


def flips(rows):
    """
    機能: 新規約定のうち確認ドテンだけを抜き出す。
    引数: rows(ndarray)は十列約定。
    返り値: ndarrayは理由14513の新規行。
    """
    return rows[(rows[:, 7] == 1) & (rows[:, 6] == 14513)]


class Tests(unittest.TestCase):
    """限定変更・上下対称・連続支持・未来不使用を検査する。"""

    def test_v10_unchanged_and_wait_preserved(self):
        """
        機能: 追加制約0が元V10と完全一致し、候補の待機60秒等を変更していないと確認する。
        引数: self(Tests)。返り値: None。
        """
        base = configurations()[10]
        for data, config in (fixture(), flip_fixture()):
            for fee in (0, 385):
                expected = original.replay(data, config, base, fee)
                got = changed.replay(data, config, dict(base, flip_guard40=0), fee)
                for left, right in zip(expected, got):
                    np.testing.assert_array_equal(left, right)
        for item in guard.configurations():
            for key, value in base.items():
                if key not in ('id', 'name'):
                    self.assertEqual(item[key], value)
            self.assertEqual(item['reentry_wait'], 60.)

    def test_direction_and_mean_are_separate(self):
        """
        機能: V16は40分差の逆向きを拒否し、V17だけが平均の反対側も拒否すると確認する。
        引数: self(Tests)。返り値: None。
        """
        data, config = flip_fixture()
        before = original.replay(data, config, configurations()[10])[0]
        self.assertGreater(len(flips(before)), 0)
        for candidate in guard.configurations():
            accepted = changed.replay(data, config, candidate)[0]
            np.testing.assert_array_equal(accepted, before)
        data['features'][180:, 4] = 50.
        for candidate in guard.configurations():
            self.assertEqual(len(flips(changed.replay(data, config, candidate)[0])), 0)
        data['features'][180:, 4] = -50.
        data['features'][180:, 6] = 500.
        self.assertGreater(len(flips(changed.replay(data, config, guard.configurations()[0])[0])), 0)
        self.assertEqual(len(flips(changed.replay(data, config, guard.configurations()[1])[0])), 0)

    def test_zero_missing_and_symmetry(self):
        """
        機能: 0差・平均上・欠測を支持と扱わず、買い売りを対称に判定する。
        引数: self(Tests)。返り値: None。
        """
        data, config = flip_fixture()
        feature = data['features'][200].copy()
        for level in (1, 2):
            self.assertTrue(changed.allow_flip40(feature, -1, level))
            for value in (0., 1., np.nan):
                item = feature.copy(); item[4] = value
                self.assertFalse(changed.allow_flip40(item, -1, level))
        for value in (feature[10], feature[10]-1, np.nan):
            item = feature.copy(); item[6] = value
            self.assertFalse(changed.allow_flip40(item, -1, 2))
        for candidate in guard.configurations():
            rows = changed.replay(data, config, candidate)[0]
            reversed_rows = changed.replay(mirror(data), config, candidate)[0]
            np.testing.assert_array_equal(rows[:, [0,1,2,4,6,7,8,9]], reversed_rows[:, [0,1,2,4,6,7,8,9]])
            np.testing.assert_array_equal(rows[:, 3], -reversed_rows[:, 3])
            np.testing.assert_allclose(rows[:, 5], 4000.-reversed_rows[:, 5], atol=1e-10)
            check_orders(rows, data, 3)

    def test_interrupted_confirmation_restarts(self):
        """
        機能: 追加条件不一致・欠測・不正気配を跨いで15秒支持を累積しないと確認する。
        引数: self(Tests)。返り値: None。
        """
        for candidate in guard.configurations():
            source, config = flip_fixture()
            first = flips(changed.replay(source, config, candidate)[0])[0]
            gap = int(first[1])-7
            for kind in ('方向不一致', '方向欠測', '平均欠測', '不正気配'):
                data = deepcopy(source)
                if kind == '方向不一致': data['features'][gap, 4] = 50.
                elif kind == '方向欠測': data['features'][gap, 4] = np.nan
                elif kind == '平均欠測': data['features'][gap, 6] = np.nan
                else: data['quotes']['quote_valid'][gap] = False
                following = flips(changed.replay(data, config, candidate)[0])
                self.assertGreater(len(following), 0, kind)
                self.assertGreaterEqual(following[0, 1], gap+16, kind)

    def test_original_entry_is_not_restricted(self):
        """
        機能: 確認ドテンを伴わない通常入口が平均40分条件で制限されないと確認する。
        引数: self(Tests)。返り値: None。
        """
        data, config = fixture()
        data['features'][:, 6] = 2000.
        before = original.replay(data, config, configurations()[10])[0]
        self.assertGreater(np.sum(before[:, 7] == 1), 0)
        self.assertEqual(len(flips(before)), 0)
        for candidate in guard.configurations():
            np.testing.assert_array_equal(changed.replay(data, config, candidate)[0], before)

    def test_order_prefix(self):
        """
        機能: 未来の原価格・特徴を除いても既発生の新規返済が変わらないと確認する。
        引数: self(Tests)。返り値: None。
        """
        data, config = flip_fixture()
        for length in (150, 250, 500):
            prefix = deepcopy(data)
            for key in ('time_s', 'atr'): prefix['ready'][key] = data['ready'][key][:length].copy()
            prefix['quotes'] = {k:v[:length].copy() for k,v in data['quotes'].items()}
            prefix['features'] = data['features'][:length].copy()
            for candidate in guard.configurations():
                full = changed.replay(data, config, candidate)[0]
                actual = changed.replay(prefix, config, candidate)[0]
                np.testing.assert_array_equal(actual, full[full[:, 0] < length])

    def test_public_mean_causality(self):
        """
        機能: 40分差・平均が確定から60秒後だけ公開され、未来の切除で変わらないと確認する。
        引数: self(Tests)。返り値: None。
        """
        times = np.arange(6000, dtype=float)
        price = 1000.+times
        actual = original.history(times, price, 0., 40)
        self.assertTrue(np.isnan(actual[2519, 6]))
        self.assertEqual(actual[2520, 4], 2400.)
        self.assertEqual(actual[2520, 6], np.mean(1000.+np.arange(119, 2460, 60)))
        changed_price = price.copy(); changed_price[4000:] = 999999.
        mutated = original.history(times, changed_price, 0., 40)
        np.testing.assert_array_equal(actual[:4000], mutated[:4000])
        prefix = original.history(times[:4000], price[:4000], 0., 40)
        np.testing.assert_array_equal(prefix, actual[:4000])


if __name__ == '__main__':
    unittest.main()
