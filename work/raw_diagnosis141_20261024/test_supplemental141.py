"""補完改修の方向・未来参照・予約競合・途中返済を人工価格で検査する。"""

import copy
import unittest
import numpy as np
import supplemental141 as s


def fixture():
    """
    機能: 価格時計・気配・公開履歴を揃えた人工夜間を作る。
    引数: なし。
    返り値: tuple[dict,dict,ndarray,ndarray,ndarray]は入力と空の保存主担当。
    """
    t = np.arange(0., 101., 5.)
    p = 1001.+np.sin(t/30.)
    ready = dict(session='人工_Night', symbol='NK225', time_s=t, atr=np.full(len(t), 10.),
                 us_open=0., limit=90., tick=1.)
    q = dict(bid=p-.1, ask=p+.1, quote_valid=np.ones(len(t), bool))
    h = np.tile([1000., 1000., 5., 1005., 995., .3, 1., 2., 1000., 0., 1., 2., .3, 1., 0.], (len(t), 1))
    market = np.zeros((len(t), 12))
    market[:, 11] = 1.
    market[:, 4:8] = .1
    return ready, q, h, market, np.empty((0, 10))


def config(mode):
    """
    機能: 開始待機だけ短縮した人工検査設定を作る。
    引数: mode(int)は1/2/3。
    返り値: dictは実市場計画と区別した人工設定。
    """
    c = s.configurations()[mode-1].copy()
    c.update(activation_after_us_seconds=0., entry_cutoff_seconds=0.)
    return c


def core_orders(data, source=0, fill=1, close_source=9, close_fill=10):
    """
    機能: 指定行に判断・約定を持つ保存主担当の人工通知を作る。
    引数: data(tuple)、各行(int)は入力と通知位置。
    返り値: ndarray[m,10]は5枚一親の新規・全返済。
    """
    q = data[1]
    return np.array([[fill, source, 123, 1, 5, q['ask'][fill], 11, 1, 0, 192],
                     [close_fill, close_source, 123, -1, 5, q['bid'][close_fill], 12, 0, 0, 192]], dtype=float)


class SupplementalProperties(unittest.TestCase):
    """売買核の機械的整合だけを検査する。実データ有効性の証拠ではない。"""

    def test_direction_and_wait(self):
        """
        機能: 始値基準と短期逆行を区別し、待機後は新価格で次行新規することを確認する。
        引数: self(SupplementalProperties)は検査状態。
        返り値: None。
        """
        d = fixture()
        d[2][:3, 6] = -1.
        d[2][:3, 10] = -1.
        o, notes = s.replay(*d, config(1))
        self.assertEqual(tuple(o[0, :2]), (4., 3.))
        self.assertEqual(o[0, 5], d[1]['ask'][4])
        self.assertEqual(o[0, 3], 1.)
        self.assertTrue(any(note['種類'] == 6 for note in notes))
        other = fixture()
        other[2][:, 8] = 1010.
        other[2][:, 13] = -1.
        a, _ = s.replay(*other, config(1))
        b, _ = s.replay(*other, config(2))
        self.assertEqual(len(a), 0)
        self.assertEqual(len(b), 2)
        self.assertEqual(b[0, 3], 1.)

    def test_core_first_and_reserved_extra(self):
        """
        機能: 同時判断では主担当を先に予約し、補完が先なら主担当親全体を見送る。
        引数: self(SupplementalProperties)は検査状態。
        返り値: None。
        """
        d = fixture()
        original = core_orders(d)
        o, _ = s.replay(*d[:4], original, config(1))
        np.testing.assert_array_equal(o, original)
        late = core_orders(d, 5, 6, 12, 13)
        o, notes = s.replay(*d[:4], late, config(1))
        self.assertEqual(len(o), 2)
        self.assertTrue(np.all(o[:, 2] == s.EXTRA_PARENT))
        self.assertTrue(any(note['種類'] == 2 for note in notes))
        moved = late.copy()
        moved[-1, 0:2] = [15, 14]
        moved[-1, 5] = d[1]['bid'][15]
        x, _ = s.replay(*d[:4], moved, config(1))
        np.testing.assert_array_equal(o, x)

    def test_adverse_confirmation_and_gap(self):
        """
        機能: N3だけ15秒継続後に返済し、価格時計空白で継続をリセットする。
        引数: self(SupplementalProperties)は検査状態。
        返り値: None。
        """
        d = fixture()
        d[3][3:, 4:8] = -.1
        a, _ = s.replay(*d, config(2))
        b, _ = s.replay(*d, config(3))
        self.assertEqual(b[-1, 6], 1413.)
        self.assertEqual(tuple(b[-1, :2]), (7., 6.))
        self.assertEqual(a[-1, 6], 93.)
        gap = copy.deepcopy(d)
        gap[0]['time_s'][6:] += 30.
        gap[0]['limit'] += 30.
        o, _ = s.replay(*gap, config(3))
        self.assertEqual(tuple(o[-1, :2]), (10., 9.))
        unknown = copy.deepcopy(d)
        unknown[3][5, 6] = np.nan
        o, _ = s.replay(*unknown, config(3))
        self.assertEqual(tuple(o[-1, :2]), (10., 9.))

    def test_mirror_future_fee_and_flat(self):
        """
        機能: 上下反転・未来改変・全注文の費用と自己次原行・全返済を確認する。
        引数: self(SupplementalProperties)は検査状態。
        返り値: None。
        """
        for mode in (1, 2, 3):
            d = fixture()
            d[3][3:, 4:8] = -.1
            mirror = copy.deepcopy(d)
            mirror[1]['bid'], mirror[1]['ask'] = 2000.-d[1]['ask'], 2000.-d[1]['bid']
            h = mirror[2]
            for col in (0, 1, 8):
                h[:, col] = 2000.-d[2][:, col]
            h[:, 3], h[:, 4] = 2000.-d[2][:, 4], 2000.-d[2][:, 3]
            for col in (6, 7, 10, 11, 13):
                h[:, col] *= -1.
            mirror[3][:, 4:8] *= -1.
            a, _ = s.replay(*d, config(mode))
            b, _ = s.replay(*mirror, config(mode))
            np.testing.assert_allclose(a[:, [0, 1, 2, 4, 6, 7, 8, 9]], b[:, [0, 1, 2, 4, 6, 7, 8, 9]])
            np.testing.assert_allclose(a[:, 3], -b[:, 3])
            np.testing.assert_allclose(a[:, 5], 2000.-b[:, 5])
            future = copy.deepcopy(d)
            future[1]['bid'][10:] += 5.
            future[1]['ask'][10:] += 5.
            x, _ = s.replay(*future, config(mode))
            np.testing.assert_allclose(a[a[:, 0] < 10], x[x[:, 0] < 10])
            self.assertTrue(np.all(a[:, 0] == a[:, 1]+1))
            self.assertTrue(np.all(a[:, 9] == 192.))
            self.assertEqual(a[a[:, 7] == 1, 4].sum(), a[a[:, 7] == 0, 4].sum())

    def test_terminal_pending_and_missing_close(self):
        """
        機能: 新規判断後に場末へ跨いでも約定を消さず返済し、終端不足は失敗にする。
        引数: self(SupplementalProperties)は検査状態。
        返り値: None。
        """
        d = fixture()
        d[0]['limit'] = 5.
        o, _ = s.replay(*d, config(1))
        self.assertEqual(tuple(o[:, 0]), (1., 2.))
        self.assertEqual(o[-1, 6], 93.)
        short = copy.deepcopy(d)
        short[0]['time_s'] = short[0]['time_s'][:2]
        short[0]['atr'] = short[0]['atr'][:2]
        for key in short[1]:
            short[1][key] = short[1][key][:2]
        with self.assertRaises(AssertionError):
            s.replay(short[0], short[1], short[2][:2], short[3][:2], short[4], config(1))


if __name__ == '__main__':
    unittest.main(verbosity=2)
