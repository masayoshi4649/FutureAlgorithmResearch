"""夜間複合判別の経路選択・未知値・因果順・会計を人工データで検査する。"""

import copy
import sys
import unittest
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/'raw_diagnosis141_20261024'))
import supplemental141_v3 as original
import test_supplemental141 as fixtures
import night_selector142 as selector
import night_trader142 as trader


def data():
    """
    機能: 価格・短期・中期・原板が買いで一致する人工入力を作る。
    引数: なし。
    返り値: tuple[tuple,ndarray]は売買側6引数用資料と4列原板特徴。
    """
    d = fixtures.fixture()
    d[2][:, 0] = 1000.5
    d[0]['seq'] = np.arange(len(d[2]))+100
    raw = np.tile([.1, .2, .1, .2], (len(d[2]), 1))
    return d, raw


def config(mode):
    """
    機能: セレクター番号に対応する人工用の開始時刻設定を作る。
    引数: mode(int)は1～5。
    返り値: dictは人工用設定。
    """
    c = trader.configurations()[mode-1].copy()
    c.update(activation_after_us_seconds=0., entry_cutoff_seconds=0.)
    return c


class NightSelectorProperties(unittest.TestCase):
    """機構上の整合性だけを検査し、実市場での優位性を意味しない。"""

    def test_routes_and_unknown_board(self):
        """
        機能: 旧方向一致・直近転換・混在の3経路と原板未知を確認する。
        引数: self(NightSelectorProperties)は検査状態。
        返り値: None。
        """
        d, raw = data()
        h, m = d[2][0].copy(), d[3][0].copy()
        for mode in (1, 2, 3):
            self.assertEqual(selector.entry_policy(h, m, 1001., 10., 1., raw[0], mode)[:2], (1, 1))
            h2 = h.copy()
            h2[8], h2[13] = 1010., -1.
            self.assertEqual(selector.entry_policy(h2, m, 1001., 10., 1., raw[0], mode)[:2], (3, 1))
            mixed = h.copy()
            mixed[11] = -2.
            self.assertEqual(selector.entry_policy(mixed, m, 1001., 10., 1., raw[0], mode)[:2], (2, 1))
        unknown = np.full(4, np.nan)
        self.assertEqual(selector.entry_policy(h, m, 1001., 10., 1., unknown, 3)[:2], (2, 1))
        self.assertFalse(selector.entry_ready(h, m, 1001., unknown, 3, 2, 1)[0])

    def test_immediate_rebuttal_and_exit_ablation(self):
        """
        機能: 待機なし対照は強い逆方向一致だけを置換し、退出差以外を共通に保つ。
        引数: self(NightSelectorProperties)は検査状態。
        返り値: None。
        """
        d, raw = data()
        h, m = d[2][0].copy(), d[3][0].copy()
        for mode in (4, 5):
            h[8], h[13] = 1010., -1.
            self.assertEqual(selector.entry_policy(h, m, 1001., 10., 1., raw[0], mode), (4, 1, 29))
            mixed = h.copy()
            mixed[11] = -2.
            self.assertEqual(selector.entry_policy(mixed, m, 1001., 10., 1., raw[0], mode), (1, -1, 19))
            stale = m.copy()
            stale[11] = 0.
            self.assertEqual(selector.entry_policy(h, stale, 1001., 10., 1., raw[0], mode), (1, -1, 19))
            d, raw = data()
            d[3][3:, 4:8] = -.1
            d[2][3:, 7] = -2.
            d[2][3:, 11] = -2.
            orders, _ = trader.replay(*d, config(mode), extra=raw)
            self.assertEqual(tuple(orders[0, :2]), (1., 0.))
            self.assertEqual(orders[-1, 6], 1434. if mode == 4 else 93.)

    def test_short_pullback_and_medium_failure(self):
        """
        機能: 短期だけの逆行を維持し、中期否定・平均位置喪失・板裏付けを分ける。
        引数: self(NightSelectorProperties)は検査状態。
        返り値: None。
        """
        d, raw = data()
        h, m = d[2][0].copy(), d[3][0].copy()
        m[4:8] = -.1
        raw[:] *= -1.
        for mode in (1, 2, 3):
            self.assertFalse(selector.exit_policy(h, m, 1, 1001., 10., 1000.8, raw[0], mode)[0])
        h[6], h[10] = -1., -1.
        self.assertFalse(selector.exit_policy(h, m, 1, 1001., 10., 999., raw[0], 1)[0])
        self.assertTrue(selector.exit_policy(h, m, 1, 1001., 10., 999., raw[0], 2)[0])
        self.assertTrue(selector.exit_policy(h, m, 1, 1001., 10., 999., raw[0], 3)[0])
        h[7], h[11] = -2., -2.
        self.assertTrue(selector.exit_policy(h, m, 1, 1001., 10., 999., raw[0], 1)[0])
        self.assertFalse(selector.exit_policy(h, m, 1, 1001., 10., 999., np.full(4, np.nan), 3)[0])

    def test_mode_zero_matches_all_nine(self):
        """
        機能: セレクター無効時は旧9条件の全注文・診断が完全同値であることを確認する。
        引数: self(NightSelectorProperties)は検査状態。
        返り値: None。
        """
        self.assertEqual(original.configurations(), trader.legacy_configurations())
        for old in original.configurations():
            for delay in (0, 3):
                d, raw = data()
                d[2][:delay, 6] = -1.
                d[3][5:, 4:8] = -.1
                c = dict(old, activation_after_us_seconds=0., entry_cutoff_seconds=0.)
                for core in (d[4], fixtures.core_orders(d, 3, 4, 9, 10)):
                    a, an = original.replay(*d[:4], core, c)
                    b, bn = trader.replay(*d[:4], core, c, extra=raw)
                    np.testing.assert_array_equal(a, b)
                    self.assertEqual(an, bn)

    def test_trace_core_priority_and_wait(self):
        """
        機能: 選択時刻・原seq・経路を記録し、支持待ち中は主担当を優先する。
        引数: self(NightSelectorProperties)は検査状態。
        返り値: None。
        """
        for mode in (1, 2, 3):
            d, raw = data()
            d[2][:3, 11] = -2.
            d[2][:3, 6] = -1.
            orders, notes = trader.replay(*d, config(mode), extra=raw)
            selected = [n for n in notes if n['種類'] == 8]
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0]['値1'], 2.)
            self.assertEqual(selected[0]['原seq'], 100)
            self.assertEqual(selected[0]['価格時計'], 0.)
            self.assertEqual(tuple(orders[0, :2]), (4., 3.))
            core = fixtures.core_orders(d, 2, 3, 9, 10)
            orders, _ = trader.replay(*d[:4], core, config(mode), extra=raw)
            np.testing.assert_array_equal(orders, core)

    def test_exit_clock_and_gap(self):
        """
        機能: 中期否定成立から15秒を測り、時計空白と原板未知で継続をリセットする。
        引数: self(NightSelectorProperties)は検査状態。
        返り値: None。
        """
        for mode in (1, 2, 3):
            d, raw = data()
            d[3][3:, 4:8] = -.1
            d[2][6:, 7] = -2.
            d[2][6:, 11] = -2.
            raw[3:] *= -1.
            orders, _ = trader.replay(*d, config(mode), extra=raw)
            self.assertEqual(tuple(orders[-1, :2]), (10., 9.))
            self.assertEqual(orders[-1, 6], 1430.+mode)
            gap = copy.deepcopy(d)
            gap[0]['time_s'][8:] += 30.
            gap[0]['limit'] += 30.
            orders, _ = trader.replay(*gap, config(mode), extra=raw)
            self.assertEqual(tuple(orders[-1, :2]), (12., 11.))
        d, raw = data()
        d[3][3:, 4:8] = -.1
        d[2][3:, 7] = -2.
        d[2][3:, 11] = -2.
        raw[3:] *= -1.
        raw[5] = np.nan
        orders, _ = trader.replay(*d, config(3), extra=raw)
        self.assertEqual(tuple(orders[-1, :2]), (10., 9.))

    def test_mirror_future_fee_shape_and_terminal(self):
        """
        機能: 上下対称・未来原板改変・28/30列接続・旧数量費用・次原行約定・場末予約を確認する。
        引数: self(NightSelectorProperties)は検査状態。
        返り値: None。
        """
        for mode in (1, 2, 3, 4, 5):
            d, raw = data()
            d[0]['atr'][:] = 20.
            mirror = copy.deepcopy(d)
            mirror[1]['bid'], mirror[1]['ask'] = 2000.-d[1]['ask'], 2000.-d[1]['bid']
            for col in (0, 1, 8):
                mirror[2][:, col] = 2000.-d[2][:, col]
            mirror[2][:, 3], mirror[2][:, 4] = 2000.-d[2][:, 4], 2000.-d[2][:, 3]
            for col in (6, 7, 10, 11, 13):
                mirror[2][:, col] *= -1.
            mirror[3][:, 4:8] *= -1.
            a, _ = trader.replay(*d, config(mode), extra=raw)
            b, _ = trader.replay(*mirror, config(mode), extra=-raw)
            np.testing.assert_allclose(a[:, [0, 1, 2, 4, 6, 7, 8, 9]], b[:, [0, 1, 2, 4, 6, 7, 8, 9]])
            np.testing.assert_allclose(a[:, 3], -b[:, 3])
            np.testing.assert_allclose(a[:, 5], 2000.-b[:, 5])
            expanded = np.column_stack((np.zeros((len(raw), 24)), raw))
            x, _ = trader.replay(*d, config(mode), extra=expanded)
            np.testing.assert_array_equal(a, x)
            thirty = np.column_stack((expanded, np.full((len(raw), 2), 12345.)))
            x, _ = trader.replay(*d, config(mode), extra=thirty)
            np.testing.assert_array_equal(a, x)
            future = copy.deepcopy(d)
            future[1]['bid'][10:] += 5.
            future[1]['ask'][10:] += 5.
            future_raw = raw.copy()
            future_raw[10:] *= -1.
            x, _ = trader.replay(*future, config(mode), extra=future_raw)
            np.testing.assert_array_equal(a[a[:, 0] < 10], x[x[:, 0] < 10])
            self.assertTrue(np.all(a[:, 0] == a[:, 1]+1))
            self.assertTrue(np.all(a[:, 4] == 3.))
            self.assertTrue(np.all(a[:, 9] == 115.))
            self.assertEqual(np.sum(a[:, 3]*a[:, 4]), 0.)
            d[0]['limit'] = 5.
            orders, _ = trader.replay(*d, config(mode), extra=raw)
            self.assertEqual(tuple(orders[:, 0]), (1., 2.))
            self.assertEqual(orders[-1, 6], 93.)


if __name__ == '__main__':
    unittest.main(verbosity=2)
