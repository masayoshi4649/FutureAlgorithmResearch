"""人工価格だけでペアの未来不使用・脚入替対称・非同期約定・円会計を確認する。"""

import copy
import unittest
import numpy as np
import pair140 as pair


def fixture():
    """
    機能: 共通方向と相対的な往復を持つ人工二市場を作る。
    引数: なし。
    返り値: dictは9千秒の原行。金融的な有効性の証拠には用いない。
    """
    out = dict(session='人工_Day', inputs={}, quotes={})
    for leg, symbol in enumerate(pair.SYMBOLS):
        t = np.arange(0., 9001., 5.)+.2*leg
        signed = 1. if leg == 0 else -1.
        price = 6000.*np.exp(.0000002*t+signed*.004*np.sin(t*2.*np.pi/600.))
        key = out['session'], symbol
        out['inputs'][key] = dict(session=key[0], symbol=symbol, time_s=t, start=0., limit=8900., last=price)
        out['quotes'][key] = dict(bid=price-.01, ask=price+.01, quote_valid=np.ones(len(t), dtype=bool))
    return out


def settings(mode=0):
    """
    機能: 入口・両脚約定の到達性を人工波で確保する検査専用値を作る。
    引数: mode(int)は三種類の入口。
    返り値: dictは実市場計画とは区別した人工検査設定。
    """
    c = pair.configurations()[mode].copy()
    c.update(entry_z=.8, turn_z=.01, hold_seconds=0., cooldown_seconds=20., minimum_edge_cost=0.,
             nk_min=1, nk_max=2, topix_min=1, topix_max=2, multipliers=(100., 100.), fee_tenths=(385, 418))
    return c


def parameters(config):
    """
    機能: 状態機械だけの境界検査へ既定設定を渡す。
    引数: config(dict)は人工設定。
    返り値: ndarrayは固定順の数値設定。
    """
    names = ('mode', 'entry_z', 'target_z', 'stop_z', 'turn_z', 'hold_seconds', 'cooldown_seconds',
             'freshness_seconds', 'leg_timeout_seconds', 'entry_cutoff_seconds', 'minimum_edge_cost',
             'maximum_mismatch', 'nk_min', 'nk_max', 'topix_min', 'topix_max')
    return np.array([config[k] for k in names]+list(config['multipliers'])+list(config['fee_tenths']), dtype=float)


class PairProperties(unittest.TestCase):
    """実データを読まず、手続きの妥当性だけを検証する。"""

    def test_account_and_next_individual_quote(self):
        """
        機能: 三入口の全注文について次の自己正常原行・数量・手数料・往復会計を確認する。
        引数: self(PairProperties)は検査状態。
        返り値: None。不一致なら検査失敗。
        """
        raw = fixture()
        total = 0
        for mode in range(3):
            c = settings(mode)
            result = pair.replay(raw, c)
            self.assertGreater(result['summary']['pairs'], 0)
            orders = result['orders']
            total += len(orders)
            independent = np.zeros(2)
            balances = {}
            for order in orders:
                ev, row, when, source, parent, leg, side, qty, px, fee, new = order[:11]
                leg, row, source, parent = int(leg), int(row), int(source), int(parent)
                key = raw['session'], pair.SYMBOLS[leg]
                r, q = raw['inputs'][key], raw['quotes'][key]
                good = pair._valid(q['bid'], q['ask'], q['quote_valid'])
                first = np.flatnonzero(good & (r['time_s'] > when))[0]
                self.assertEqual(row, first)
                self.assertGreater(row, source)
                self.assertEqual(px, q['ask'][row] if side > 0 else q['bid'][row])
                self.assertEqual(fee, qty*c['fee_tenths'][leg]//10)
                self.assertLessEqual(qty, 10)
                independent[leg] -= side*qty*px*c['multipliers'][leg]+fee
                k = parent, leg
                balances[k] = balances.get(k, 0)+qty*(1 if new else -1)
                self.assertGreaterEqual(balances[k], 0)
            self.assertTrue(all(v == 0 for v in balances.values()))
            np.testing.assert_allclose(independent, result['equity'][-1, 1:], atol=.001)
            self.assertAlmostEqual(independent.sum(), result['summary']['net'], places=3)
            self.assertGreater(result['summary']['single_leg_seconds'], 0.)
        self.assertGreater(total, 24)

    def test_future_and_current_timestamp_excluded(self):
        """
        機能: 未来の価格改変と当時刻の相手行が過去の特徴・注文へ侵入しないことを確認する。
        引数: self(PairProperties)は検査状態。
        返り値: None。未来参照を認める場合は失敗。
        """
        raw = fixture()
        changed = copy.deepcopy(raw)
        cut = 4500.
        for key in changed['inputs']:
            mask = changed['inputs'][key]['time_s'] >= cut
            changed['quotes'][key]['bid'][mask] *= 1.03
            changed['quotes'][key]['ask'][mask] *= 1.03
        a, b = pair.prepare(raw, 20), pair.prepare(changed, 20)
        before = a['times'] <= cut
        np.testing.assert_allclose(a['decision'][before], b['decision'][before], equal_nan=True)
        np.testing.assert_allclose(a['history'][before], b['history'][before], equal_nan=True)
        for mode in range(3):
            x = pair.replay(raw, settings(mode), a)['orders']
            y = pair.replay(changed, settings(mode), b)['orders']
            np.testing.assert_allclose(x[a['times'][x[:, 0].astype(int)] < cut],
                                       y[b['times'][y[:, 0].astype(int)] < cut], atol=1.e-8)

    def test_swapped_legs(self):
        """
        機能: 市場・数量範囲・倍率・料金を左右交換すると実質同じ売買になることを確認する。
        引数: self(PairProperties)は検査状態。
        返り値: None。比率の向きに恣意的な優遇があれば失敗。
        """
        raw = fixture()
        swapped = copy.deepcopy(raw)
        for leg, symbol in enumerate(pair.SYMBOLS):
            dest = raw['session'], symbol
            source = raw['session'], pair.SYMBOLS[1-leg]
            swapped['inputs'][dest] = copy.deepcopy(raw['inputs'][source])
            swapped['inputs'][dest]['symbol'] = symbol
            swapped['quotes'][dest] = copy.deepcopy(raw['quotes'][source])
        for mode in range(3):
            c = settings(mode)
            other = dict(c, fee_tenths=c['fee_tenths'][::-1], multipliers=c['multipliers'][::-1])
            x, y = pair.replay(raw, c), pair.replay(swapped, other)
            a, b = x['orders'].copy(), y['orders'].copy()
            b[:, 5] = 1.-b[:, 5]
            sort_a = np.lexsort((a[:, 5], a[:, 0]))
            sort_b = np.lexsort((b[:, 5], b[:, 0]))
            np.testing.assert_allclose(a[sort_a], b[sort_b], rtol=1.e-8, atol=1.e-5)
            self.assertAlmostEqual(x['summary']['net'], y['summary']['net'], places=4)

    def test_asynchronous_failure_and_terminal(self):
        """
        機能: 片脚遅延・後着新規・場末既発注を捏造取消せず返済し、終端不足を検出する。
        引数: self(PairProperties)は検査状態。
        返り値: None。原行不足の人工例だけは意図した例外を要求する。
        """
        c = settings()
        c.update(cooldown_seconds=1000., entry_cutoff_seconds=0., hold_seconds=0., entry_z=1.)
        p = parameters(c)
        t = np.arange(0., 71., 5.)
        n = len(t)
        q = np.tile([101.99, 102.01, 99.99, 100.01, 0., 0.], (n, 1))
        f = q[:, :4].copy()
        rows = np.tile(np.arange(n)[:, None], (1, 2)).astype(np.int64)
        source = rows.copy()
        h = np.tile([0., .01, .01, -.01, 0.], (n, 1))
        old = np.full(n, np.nan)
        late = rows.copy()
        late[1:5, 1] = -1
        orders, parents, eq = pair._run(t, q, f, f, late, source, h, old, 0., 60., p)
        self.assertEqual(len(parents), 1)
        self.assertEqual(parents[0, 14], 4)
        self.assertEqual(parents[0, 12], 25.)
        self.assertEqual(len(orders), 4)
        nk_close = orders[(orders[:, 5] == 0) & (orders[:, 10] == 0)][0]
        tx_new = orders[(orders[:, 5] == 1) & (orders[:, 10] == 1)][0]
        tx_close = orders[(orders[:, 5] == 1) & (orders[:, 10] == 0)][0]
        self.assertEqual(t[int(nk_close[0])], 25.)
        self.assertEqual(t[int(tx_new[0])], 25.)
        self.assertEqual(t[int(tx_close[0])], 30.)
        pair.account(orders, parents, eq)
        terminal, parents, eq = pair._run(t, q, f, f, rows, source, h, old, 0., 5., p)
        self.assertEqual(len(terminal), 4)
        self.assertTrue(np.all(terminal[terminal[:, 10] == 1, 0] == 1))
        self.assertTrue(np.all(terminal[terminal[:, 10] == 0, 0] == 2))
        self.assertEqual(parents[0, 14], 6)
        with self.assertRaises(AssertionError):
            pair._run(t[:2], q[:2], f[:2], f[:2], rows[:2], source[:2], h[:2], old[:2], 0., 5., p)

    def test_integer_notional_balance(self):
        """
        機能: 当時価格の整数総当たりが元本差を最小にし、先の価格を必要としないことを確認する。
        引数: self(PairProperties)は検査状態。
        返り値: None。数量制約や最小化の誤りで失敗。
        """
        price, mult = np.array([65000., 4000.]), np.array([100., 1000.])
        a, b, mismatch, score = pair.quantities(price, mult, 5, 10, 1, 10)
        self.assertEqual((a, b), (5, 8))
        self.assertEqual(mismatch, 500000.)
        expected = min(abs(x*6500000.-y*4000000.)/((x*6500000.+y*4000000.)*.5)
                       for x in range(5, 11) for y in range(1, 11))
        self.assertAlmostEqual(score, expected)


if __name__ == '__main__':
    unittest.main(verbosity=2)
