"""保存通知改修の因果性・予約尊重・減枚会計を人工価格だけで検査する。"""

import copy
import unittest
import numpy as np
import core_overlay143 as engine


def fixture(n=120):
    """
    機能: 実市場と無関係な一定価格の原行・公開平均を作る。
    引数: n(int)は原行数。
    返り値: tuple[dict,ndarray]は売買入力と十五列公開履歴。
    """
    times = np.arange(n, dtype=float)
    mid = np.full(n, 100.)
    a = np.zeros((n, 30))
    a[:, 9] = a[:, 18] = 10.
    a[:, 10] = a[:, 19] = mid
    a[:, 12:14] = .1
    a[:, 20:22] = .1
    a[:, 22] = times - 1.
    a[:, 24] = a[:, 26] = .2
    h = np.zeros((n, 15))
    h[:, :2] = 100.
    d = dict(ready=dict(time_s=times, atr=np.full(n, 10.), tick=1., seq=np.arange(n),
                        symbol='NK225', session='人工_Day', start=0., limit=float(n)),
             quotes=dict(bid=mid - .5, ask=mid + .5, quote_valid=np.ones(n, bool)), features=a)
    return d, h


def change(d, begin, end, mid, own120=-.3, peer120=.1, ofi=-.2):
    """
    機能: 指定区間だけの人工価格と当時方向を変更する。
    引数: d(dict)、begin/end(int)、mid/own120/peer120/ofi(float)は入力と変更値。
    返り値: None。渡された人工入力を変更する。
    """
    d['quotes']['bid'][begin:end] = mid - .5
    d['quotes']['ask'][begin:end] = mid + .5
    a = d['features']
    a[begin:end, 10] = mid
    a[begin:end, 12] = own120
    a[begin:end, 13] = own120
    a[begin:end, 21] = peer120
    a[begin:end, 24] = ofi


def orders(d, events):
    """
    機能: 人工通知を次正常気配約定の共通十列へ変換する。
    引数: d(dict)、events(list[tuple])は入力と判断行・親・方向・数量・新規・UID。
    返り値: ndarrayは十列注文。費用は注文単位で切り捨てる。
    """
    normal = np.flatnonzero(d['quotes']['quote_valid'])
    result = []
    for decision, parent, side, qty, new, uid in events:
        fill = int(normal[np.searchsorted(normal, decision, side='right')])
        px = d['quotes']['ask' if side > 0 else 'bid'][fill]
        result.append([fill, decision, parent, side, qty, px, 81, new, uid, qty * 385 // 10])
    return np.array(result, dtype=float).reshape(-1, 10)


def mirror(d, h, base):
    """
    機能: 価格中心100の上下反転で売買方向と全方向特徴を交換する。
    引数: d(dict)、h/base(ndarray)は人工入力・公開履歴・保存注文。
    返り値: tuple[dict,ndarray,ndarray]は鏡像入力。
    """
    m = copy.deepcopy(d)
    m['quotes']['bid'] = 200. - d['quotes']['ask']
    m['quotes']['ask'] = 200. - d['quotes']['bid']
    a = m['features']
    a[:, [10, 19]] = 200. - a[:, [10, 19]]
    a[:, [12, 13, 20, 21, 24, 25, 26, 27, 28, 29]] *= -1.
    g = h.copy()
    g[:, :2] = 200. - g[:, :2]
    b = base.copy()
    b[:, 3] *= -1.
    b[:, 5] = 200. - b[:, 5]
    return m, g, b


def check(d, actual):
    """
    機能: 次正常原行・方向別気配・UID残枚数・料金・全返済を独立検査する。
    引数: d(dict)、actual(ndarray)は人工入力と出力注文。
    返り値: None。不一致はassertで停止する。
    """
    holding = {}
    normal = np.flatnonzero(d['quotes']['quote_valid'])
    for row in actual:
        fill, decision, parent, side, qty, px, _, new, uid, fee = row
        assert int(fill) == normal[np.searchsorted(normal, decision, side='right')]
        assert px == d['quotes']['ask' if side > 0 else 'bid'][int(fill)]
        assert fee == int(qty) * 385 // 10
        key = parent, uid
        holding[key] = holding.get(key, 0) + int(qty) * (1 if new else -1)
        assert 0 <= holding[key] <= 10
        assert sum(holding.values()) <= 10
    assert all(v == 0 for v in holding.values())


class OverlayProperties(unittest.TestCase):
    """金融成績を測らず、実装の因果性と注文会計だけを確かめる。"""

    def test_reference_and_whole_parent_gate(self):
        """
        機能: O00完全同値と初回拒否後の追加・返済全体の不採用を確認する。
        引数: self(OverlayProperties)は試験状態。
        返り値: None。
        """
        d, h = fixture()
        change(d, 0, 20, 100., own120=-.4)
        b = orders(d, [(0, 3, 1, 3, 1, 11), (25, 3, 1, 2, 1, 12),
                       (80, 3, -1, 3, 0, 11), (80, 3, -1, 2, 0, 12)])
        c = engine.configurations()
        o, _ = engine.replay(d, b, h, c[0])
        np.testing.assert_array_equal(o, b)
        o, log = engine.replay(d, b, h, c[1])
        self.assertEqual(len(o), 0)
        self.assertEqual(int(log[0, 5]), 14301)
        o, _ = engine.replay(d, b, h, c[2])
        np.testing.assert_array_equal(o, b)

    def test_own_failure_and_peer_disagreement(self):
        """
        機能: 自己だけの失敗認定と二市場条件の違いを確認する。
        引数: self(OverlayProperties)は試験状態。
        返り値: None。
        """
        d, h = fixture()
        change(d, 10, 80, 98.)
        b = orders(d, [(0, 1, 1, 5, 1, 1), (90, 1, -1, 5, 0, 1)])
        o, _ = engine.replay(d, b, h, engine.configurations()[3])
        self.assertEqual(int(o[-1, 1]), 25)
        self.assertEqual(int(o[-1, 0]), 26)
        check(d, o)
        p, _ = engine.replay(d, b, h, engine.configurations()[4])
        np.testing.assert_array_equal(p, b)

    def test_issued_add_fills_then_overlay_closes(self):
        """
        機能: 逆流十五秒成立と同じ行の元追加を取消さず、その約定後に返済する。
        引数: self(OverlayProperties)は試験状態。
        返り値: None。
        """
        d, h = fixture()
        change(d, 10, 80, 98.)
        b = orders(d, [(0, 1, 1, 3, 1, 1), (25, 1, 1, 2, 1, 2),
                       (80, 1, -1, 3, 0, 1), (80, 1, -1, 2, 0, 2)])
        o, log = engine.replay(d, b, h, engine.configurations()[3])
        self.assertEqual(list(o[:, 0].astype(int)), [1, 26, 27, 27])
        self.assertEqual(list(o[o[:, 7] == 0, 4].astype(int)), [3, 2])
        self.assertEqual(int(log[log[:, 2] == 2][0, 10]), 1)
        check(d, o)

    def test_native_close_priority_and_later_add_block(self):
        """
        機能: 元の部分返済を先行させ、独自返済判断後の未発注追加だけを見送る。
        引数: self(OverlayProperties)は試験状態。
        返り値: None。
        """
        d, h = fixture()
        change(d, 10, 80, 98.)
        b = orders(d, [(0, 1, 1, 5, 1, 1), (25, 1, -1, 2, 0, 1),
                       (30, 1, 1, 2, 1, 2), (90, 1, -1, 3, 0, 1),
                       (90, 1, -1, 2, 0, 2)])
        o, log = engine.replay(d, b, h, engine.configurations()[3])
        self.assertEqual(list(o[:, 0].astype(int)), [1, 26, 27])
        self.assertEqual(list(o[:, 4].astype(int)), [5, 2, 3])
        self.assertEqual(sum(log[:, 2] == 4), 1)
        check(d, o)

    def test_half_then_native_proportional_partial(self):
        """
        機能: 利益後半減と元の部分返済をUID残枚数比で整合させる。
        引数: self(OverlayProperties)は試験状態。
        返り値: None。
        """
        d, h = fixture()
        change(d, 5, 10, 111., own120=.3, ofi=.2)
        change(d, 10, 100, 107.)
        h[10:, 1] = 110.
        b = orders(d, [(0, 1, 1, 10, 1, 1), (50, 1, -1, 4, 0, 1),
                       (90, 1, -1, 6, 0, 1)])
        o, _ = engine.replay(d, b, h, engine.configurations()[6])
        self.assertEqual(list(o[:, 4].astype(int)), [10, 5, 2, 3])
        self.assertEqual(list(o[:, 0].astype(int)), [1, 26, 51, 91])
        check(d, o)

    def test_half_then_strengthened_failure_closes(self):
        """
        機能: 半減後に建値を割る反証が強まった場合、残玉を全て返済できる。
        引数: self(OverlayProperties)は試験状態。
        返り値: None。
        """
        d, h = fixture()
        change(d, 5, 10, 111., own120=.3, ofi=.2)
        change(d, 10, 40, 107.)
        change(d, 40, 90, 99.)
        h[10:, 1] = 110.
        b = orders(d, [(0, 1, 1, 5, 1, 1), (90, 1, -1, 5, 0, 1)])
        o, _ = engine.replay(d, b, h, engine.configurations()[6])
        self.assertEqual(list(o[:, 4].astype(int)), [5, 2, 3])
        self.assertEqual(list(o[:, 0].astype(int)), [1, 26, 41])
        check(d, o)

    def test_missing_gap_and_stale_peer_reset(self):
        """
        機能: 気配無効・時計空白・相手時刻不足では逆流持続を捏造しない。
        引数: self(OverlayProperties)は試験状態。
        返り値: None。
        """
        d, h = fixture()
        change(d, 10, 80, 98., peer120=-.3)
        d['features'][:, 26] = -.2
        d['quotes']['quote_valid'][20] = False
        d['ready']['time_s'][30:] += 30.
        d['features'][:, 22] = d['ready']['time_s'] - 1.
        b = orders(d, [(0, 1, 1, 5, 1, 1), (90, 1, -1, 5, 0, 1)])
        o, _ = engine.replay(d, b, h, engine.configurations()[3])
        self.assertEqual(int(o[-1, 1]), 45)
        d['features'][10:80, 22] -= 60.
        o, _ = engine.replay(d, b, h, engine.configurations()[4])
        np.testing.assert_array_equal(o, b)

    def test_all_policies_prefix_future_and_mirror(self):
        """
        機能: 全条件で未来変更不変・入力途中打切り不変・上下鏡像・費用会計を確認する。
        引数: self(OverlayProperties)は試験状態。
        返り値: None。
        """
        d, h = fixture()
        change(d, 5, 10, 111., own120=.3, ofi=.2)
        change(d, 10, 80, 98., peer120=-.3)
        d['features'][10:80, 26] = -.2
        b = orders(d, [(0, 1, 1, 5, 1, 1), (90, 1, -1, 5, 0, 1)])
        m, mh, mb = mirror(d, h, b)
        future = copy.deepcopy(d)
        change(future, 60, 120, 75., own120=-3., peer120=-3.)
        fb = orders(future, [(0, 1, 1, 5, 1, 1), (90, 1, -1, 5, 0, 1)])
        prefix = copy.deepcopy(d)
        for category in ('ready', 'quotes'):
            for key, value in prefix[category].items():
                if isinstance(value, np.ndarray):
                    prefix[category][key] = value[:60].copy()
        prefix['features'] = prefix['features'][:60].copy()
        for cfg in engine.configurations():
            o, t = engine.replay(d, b, h, cfg)
            mo, mt = engine.replay(m, mb, mh, cfg)
            expected = o.copy()
            expected[:, 3] *= -1.
            expected[:, 5] = 200. - expected[:, 5]
            np.testing.assert_allclose(mo, expected)
            tm = t.copy()
            tm[:, 3] *= -1.
            np.testing.assert_allclose(mt, tm)
            p, pt = engine.replay(prefix, b, h[:60], cfg)
            np.testing.assert_allclose(p, o[o[:, 0] < 60])
            np.testing.assert_allclose(pt, t[t[:, 0] < 60])
            f, ft = engine.replay(future, fb, h, cfg)
            np.testing.assert_allclose(f[f[:, 0] < 60], o[o[:, 0] < 60])
            np.testing.assert_allclose(ft[ft[:, 0] < 60], t[t[:, 0] < 60])
            check(d, o)

    def test_price_normalizer_is_published_atr(self):
        """
        機能: 四十分帯の幅が変わっても同じ120秒値幅の入口判定が変わらない。
        引数: self(OverlayProperties)は試験状態。
        返り値: None。
        """
        d, h = fixture()
        d['features'][:, 9] = 100.
        d['features'][:, 13] = -.03
        b = orders(d, [(0, 1, 1, 5, 1, 1), (90, 1, -1, 5, 0, 1)])
        o, _ = engine.replay(d, b, h, engine.configurations()[1])
        self.assertEqual(len(o), 0)


if __name__ == '__main__':
    unittest.main()
