"""固定入口平均の改修を人工価格で検査し、旧分岐同値と因果順を確認する。"""

import copy
import unittest
import numpy as np
import core_overlay143 as original
import core_overlay_v2_143 as revised
from test_core_overlay143 import fixture, change, orders, mirror, check


class FixedAnchorProperties(unittest.TestCase):
    """売買成績を測らず、固定境界と現在方向の役割を機械的に検査する。"""

    def test_old_modes_are_unchanged(self):
        """
        機能: 新旧エンジンの旧十二条件が全注文・選択記録で一致することを確認する。
        引数: self(FixedAnchorProperties)は試験状態。
        返り値: None。
        """
        d, h = fixture()
        change(d, 5, 10, 111., own120=.3, ofi=.2)
        change(d, 10, 100, 98., peer120=-.3)
        d['features'][:, 26] = -.2
        b = orders(d, [(0, 7, 1, 3, 1, 1), (25, 7, 1, 2, 1, 2),
                       (80, 7, -1, 3, 0, 1), (80, 7, -1, 2, 0, 2)])
        for c in original.configurations():
            x, xt = original.replay(d, b, h, c)
            y, yt = revised.replay(d, b, h, c)
            np.testing.assert_array_equal(x, y)
            np.testing.assert_array_equal(xt, yt)

    def test_moving_average_cross_is_not_fixed_failure(self):
        """
        機能: 動く平均だけを逆側に跨いでも、固定入口平均を破らなければ旧玉を維持する。
        引数: self(FixedAnchorProperties)は試験状態。
        返り値: None。
        """
        d, h = fixture()
        change(d, 10, 80, 105., peer120=-.3)
        h[10:, 1] = 108.
        d['features'][:, 28:30] = -1.
        b = orders(d, [(0, 1, 1, 5, 1, 1), (90, 1, -1, 5, 0, 1)])
        old, _ = original.replay(d, b, h, original.configurations()[3])
        self.assertEqual(int(old[-1, 1]), 25)
        for c in revised.configurations():
            o, _ = revised.replay(d, b, h, c)
            np.testing.assert_array_equal(o, b)

    def test_current_medium_and_ofi_are_separate_requirements(self):
        """
        機能: 固定境界破綻だけでは発動せず、自己20分・OFI・相手20分を各条件どおり分離する。
        引数: self(FixedAnchorProperties)は試験状態。
        返り値: None。
        """
        d, h = fixture()
        change(d, 10, 80, 98., ofi=.2)
        d['features'][:, 28] = 1.
        d['features'][:, 29] = 1.
        b = orders(d, [(0, 1, 1, 5, 1, 1), (90, 1, -1, 5, 0, 1)])
        c = revised.configurations()
        o, _ = revised.replay(d, b, h, c[0])
        np.testing.assert_array_equal(o, b)
        d['features'][:, 28] = -1.
        o, _ = revised.replay(d, b, h, c[0])
        self.assertEqual(int(o[-1, 1]), 25)
        for policy in c[1:3]:
            o, _ = revised.replay(d, b, h, policy)
            np.testing.assert_array_equal(o, b)
        d['features'][:, 24] = -.2
        d['features'][:, 29] = -1.
        for policy in c[1:3]:
            o, _ = revised.replay(d, b, h, policy)
            self.assertEqual(int(o[-1, 1]), 25)
            check(d, o)

    def test_anchor_is_fixed_at_notification_and_unknown_stays_unknown(self):
        """
        機能: 初回通知と約定の間のMA更新を取り込まず、初回未知を後から既知へ置換しない。
        引数: self(FixedAnchorProperties)は試験状態。
        返り値: None。
        """
        d, h = fixture()
        h[1:, 1] = 108.
        change(d, 10, 80, 105.)
        d['features'][:, 28:30] = -1.
        b = orders(d, [(0, 1, 1, 5, 1, 1), (90, 1, -1, 5, 0, 1)])
        o, _ = revised.replay(d, b, h, revised.configurations()[0])
        np.testing.assert_array_equal(o, b)
        context = revised.parent_context(d, b, h, o)[0]
        self.assertEqual(context['fixed_ma20'], 100.)
        self.assertEqual(context['entry_signed_distance_r'], .05)
        h[0, 1] = np.nan
        change(d, 10, 80, 90.)
        b = orders(d, [(0, 1, 1, 5, 1, 1), (90, 1, -1, 5, 0, 1)])
        o, _ = revised.replay(d, b, h, revised.configurations()[0])
        np.testing.assert_array_equal(o, b)
        self.assertIsNone(revised.parent_context(d, b, h, o)[0]['fixed_ma20'])

    def test_reservations_and_partial_projection_remain_causal(self):
        """
        機能: 新固定条件でも元の発注済み追加を約定後に返済し、半減後は比例返済する。
        引数: self(FixedAnchorProperties)は試験状態。
        返り値: None。
        """
        d, h = fixture()
        change(d, 10, 80, 98.)
        d['features'][:, 28:30] = -1.
        b = orders(d, [(0, 1, 1, 3, 1, 1), (25, 1, 1, 2, 1, 2),
                       (90, 1, -1, 3, 0, 1), (90, 1, -1, 2, 0, 2)])
        o, _ = revised.replay(d, b, h, revised.configurations()[0])
        self.assertEqual(list(o[:, 0].astype(int)), [1, 26, 27, 27])
        check(d, o)
        d, h = fixture()
        h[:, 1] = 110.
        change(d, 5, 10, 111., own120=.3, ofi=.2)
        change(d, 10, 100, 107.)
        d['features'][:, 28:30] = -1.
        b = orders(d, [(0, 1, 1, 10, 1, 1), (50, 1, -1, 4, 0, 1), (90, 1, -1, 6, 0, 1)])
        o, _ = revised.replay(d, b, h, revised.configurations()[3])
        self.assertEqual(list(o[:, 4].astype(int)), [10, 5, 2, 3])
        check(d, o)

    def test_unknown_medium_resets_confirmation_and_unknown_peer_is_not_support(self):
        """
        機能: 現在20分方向が未知なら十五秒確認を切り、相手未知で二市場破綻を捏造しない。
        引数: self(FixedAnchorProperties)は試験状態。
        返り値: None。
        """
        d, h = fixture()
        change(d, 10, 100, 98.)
        d['features'][:, 28] = -1.
        d['features'][20, 28] = np.nan
        d['features'][:, 29] = np.nan
        b = orders(d, [(0, 1, 1, 5, 1, 1), (100, 1, -1, 5, 0, 1)])
        o, _ = revised.replay(d, b, h, revised.configurations()[0])
        self.assertEqual(int(o[-1, 1]), 36)
        check(d, o)
        p, _ = revised.replay(d, b, h, revised.configurations()[2])
        np.testing.assert_array_equal(p, b)

    def test_all_new_modes_mirror_prefix_and_future_independence(self):
        """
        機能: 新六条件すべての上下対称・途中打切り・未来変更不変・会計を確認する。
        引数: self(FixedAnchorProperties)は試験状態。
        返り値: None。
        """
        d, h = fixture()
        change(d, 10, 80, 93., peer120=-.3)
        d['features'][:, 28:30] = -1.
        b = orders(d, [(0, 1, 1, 5, 1, 1), (90, 1, -1, 5, 0, 1)])
        m, mh, mb = mirror(d, h, b)
        prefix = copy.deepcopy(d)
        for category in ('ready', 'quotes'):
            for key, value in prefix[category].items():
                if isinstance(value, np.ndarray):
                    prefix[category][key] = value[:60].copy()
        prefix['features'] = prefix['features'][:60].copy()
        future = copy.deepcopy(d)
        change(future, 60, 120, 175., own120=3., peer120=3.)
        future['features'][60:, 28:30] *= -1.
        fh = h.copy()
        fh[60:, 1] += 70.
        fb = orders(future, [(0, 1, 1, 5, 1, 1), (90, 1, -1, 5, 0, 1)])
        for c in revised.configurations():
            o, t = revised.replay(d, b, h, c)
            mo, mt = revised.replay(m, mb, mh, c)
            expected = o.copy()
            expected[:, 3] *= -1.
            expected[:, 5] = 200. - expected[:, 5]
            np.testing.assert_allclose(mo, expected)
            expected_t = t.copy()
            expected_t[:, 3] *= -1.
            np.testing.assert_allclose(mt, expected_t)
            p, pt = revised.replay(prefix, b, h[:60], c)
            np.testing.assert_allclose(p, o[o[:, 0] < 60])
            np.testing.assert_allclose(pt, t[t[:, 0] < 60])
            f, ft = revised.replay(future, fb, fh, c)
            np.testing.assert_allclose(f[f[:, 0] < 60], o[o[:, 0] < 60])
            np.testing.assert_allclose(ft[ft[:, 0] < 60], t[t[:, 0] < 60])
            check(d, o)


if __name__ == '__main__':
    unittest.main()
