"""価格経路を作った人工試験。実データの成績探索を行わない。"""

import json
from pathlib import Path
import unittest
import numpy as np
import source145 as src
import trader145 as trader
from config145 import configurations


def fixture():
    """
    機能: 突破、順行、押し戻り、再進行、最後の返済を含む人工観測を作る。
    引数: なし。
    返り値: tuple[dict,dict]は一場資料と共通入口設定。
    """
    t = np.arange(5005, dtype=float)
    mid = np.interp(t, [0, 9, 10, 20, 50, 80, 120, 180, 200, 260, 5004],
                    [1000, 1000, 1100, 1100, 1200, 1120, 1170, 1270, 1160, 1300, 1300])
    a = np.ones((len(t), 31))
    a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4] = 1000, 900, .4, 20, 50
    a[:, 5], a[:, 6], a[:, 7], a[:, 8] = 1000, 950, 1000, t
    a[:, 9], a[:, 10], a[:, 11], a[:, 12], a[:, 13] = 100, mid, 20, .1, .1
    a[:, 14], a[:, 15], a[:, 16], a[:, 17], a[:, 18] = 20, 50, .4, 1000, 100
    a[:, 19], a[:, 20], a[:, 21], a[:, 22], a[:, 23] = mid, .1, .1, t-1, t-1
    a[:, 30] = 1000
    data = dict(ready=dict(symbol='NK225', session='人工_Day', time_s=t, start=0., limit=5000.,
                          tick=10., atr=np.full(len(t), 40.)),
                quotes=dict(bid=mid-5, ask=mid+5, quote_valid=np.ones(len(t), bool)), features=a)
    config = dict(mode=0, initial=2, maximum=3, add_step=.5, stop=1., activation=1.25,
                  trail=.75, hold=0., cooldown=120., ttl=1200., peer=True,
                  budget_ticks=40., loss_pause=900., loss_limit=2, quiet_seconds=900.)
    return data, config


def mirror(data):
    """
    機能: 売買方向だけの偏りを検査するため人工価格と方向特徴を上下鏡像にする。
    引数: data(dict)。
    返り値: dictは2000を中心とした対称資料。
    """
    d = dict(ready=dict(data['ready']), quotes={k:v.copy() for k,v in data['quotes'].items()}, features=data['features'].copy())
    a = d['features']
    old = data['features']
    a[:, 0], a[:, 1] = 4000-old[:, 1], 4000-old[:, 0]
    for k in (5, 6, 7, 10, 17, 19, 30):
        a[:, k] = 4000-old[:, k]
    for k in (3, 4, 12, 13, 14, 15, 20, 21, 24, 26, 28, 29):
        a[:, k] = -old[:, k]
    d['quotes']['bid'], d['quotes']['ask'] = 4000-data['quotes']['ask'], 4000-data['quotes']['bid']
    return d


class Tests(unittest.TestCase):
    """新しい利益回転・再参加の会計と因果順を検査する。"""

    def test_original_equal(self):
        """
        機能: 新管理を選ばないV00が既存追加担当と完全一致することを確認する。
        引数: self(Tests)。返り値: None。
        """
        d, c = fixture()
        for fee in (0, 385):
            expected = src.replay_active(d, c, fee)
            got = trader.replay(d, c, configurations()[0], fee)[0]
            np.testing.assert_array_equal(got, expected)

    def test_all_variants(self):
        """
        機能: 全16条件の次原行約定、上限、全返済、鏡像対称を検査する。
        引数: self(Tests)。返り値: None。
        """
        d, c = fixture()
        m = mirror(d)
        for config in configurations():
            rows = trader.replay(d, c, config)[0]
            rev = trader.replay(m, c, config)[0]
            self.assertTrue(np.all(rows[:, 0] > rows[:, 1]), config['id'])
            held = np.cumsum(np.where(rows[:, 7] > 0, rows[:, 4], -rows[:, 4]))
            self.assertTrue(np.all((held >= 0) & (held <= 3)))
            self.assertEqual(held[-1], 0)
            self.assertTrue(np.all(rows[:, 9] == 0))
            self.assertEqual(rows.shape, rev.shape, config['id'])
            np.testing.assert_array_equal(rows[:, [0,1,2,4,6,7,8,9]], rev[:, [0,1,2,4,6,7,8,9]], err_msg=config['id'])
            np.testing.assert_array_equal(rows[:, 3], -rev[:, 3])
            np.testing.assert_allclose(rows[:, 5], 4000-rev[:, 5], atol=1e-10)

    def test_rotation_needs_new_pullback(self):
        """
        機能: 先に部分利確し、再取得まで価格変化と確認時間を待つことを検査する。
        引数: self(Tests)。返り値: None。
        """
        d, c = fixture()
        rows = trader.replay(d, c, configurations()[5])[0]
        rotations = rows[(rows[:, 7] == 1) & (rows[:, 6] == 14511)]
        self.assertGreater(len(rotations), 0)
        for row in rotations:
            preceding = rows[(rows[:, 0] < row[1]) & (rows[:, 6] == 14510)]
            self.assertGreater(len(preceding), 0)
            prior = preceding[-1]
            self.assertGreater(row[1]-prior[0], 15)
            self.assertLessEqual(row[5], prior[5])

    def test_prefix_causality(self):
        """
        機能: 未来価格を消しても、それ以前の全約定が変わらないことを確認する。
        引数: self(Tests)。返り値: None。
        """
        d, c = fixture()
        partial = dict(ready=dict(d['ready']), quotes={k:v[:150].copy() for k,v in d['quotes'].items()}, features=d['features'][:150].copy())
        partial['ready']['time_s'] = d['ready']['time_s'][:150]
        partial['ready']['atr'] = d['ready']['atr'][:150]
        for config in configurations():
            full = trader.replay(d, c, config)[0]
            prefix = trader.replay(partial, c, config)[0]
            np.testing.assert_array_equal(prefix, full[full[:, 0] < 150], err_msg=config['id'])

    def test_flip_waits_until_flat_and_confirmation(self):
        """
        機能: 返済確定後の逆方向確認からのみ反対の新親が発生することを検査する。
        引数: self(Tests)。返り値: None。
        """
        d, c = fixture()
        d['features'][180:, 3] = -20.
        d['features'][180:, 4] = -50.
        d['features'][180:, 12] = -.1
        d['features'][180:, 13] = -.1
        d['features'][180:, 30] = 1500.
        variant = dict(configurations()[10], reentry_wait=0.)
        rows = trader.replay(d, c, variant)[0]
        flips = rows[(rows[:, 7] == 1) & (rows[:, 6] == 14513)]
        self.assertGreater(len(flips), 0)
        for row in flips:
            self.assertEqual(row[3], -1)
            self.assertGreaterEqual(row[1], 195)
            previous = rows[rows[:, 0] < row[0]]
            self.assertEqual(np.sum(np.where(previous[:, 7] > 0, previous[:, 4], -previous[:, 4])), 0)

    def test_invalid_quote_interrupts_rotation_confirmation(self):
        """
        機能: 確認中の不正気配を経過時間へ加算せず、15秒を数え直すことを確認する。
        引数: self(Tests)。返り値: None。
        """
        d, c = fixture()
        rows = trader.replay(d, c, configurations()[5])[0]
        first = rows[(rows[:, 7] == 1) & (rows[:, 6] == 14511)][0]
        gap = int(first[1])-7
        d['quotes']['quote_valid'][gap] = False
        rows = trader.replay(d, c, configurations()[5])[0]
        first_after = rows[(rows[:, 7] == 1) & (rows[:, 6] == 14511)][0]
        self.assertGreaterEqual(first_after[1], gap+16)

    def test_missing_feature_interrupts_reentry_confirmation(self):
        """
        機能: 方向特徴の欠測を跨いだ確認ドテンを禁止する。
        引数: self(Tests)。返り値: None。
        """
        d, c = fixture()
        for k, value in ((3,-20.), (4,-50.), (12,-.1), (13,-.1), (30,1500.)):
            d['features'][180:,k] = value
        variant = dict(configurations()[10], reentry_wait=0.)
        rows = trader.replay(d, c, variant)[0]
        first = rows[(rows[:, 7] == 1) & (rows[:, 6] == 14513)][0]
        gap = int(first[1])-7
        d['features'][gap,13] = np.nan
        rows = trader.replay(d, c, variant)[0]
        first_after = rows[(rows[:, 7] == 1) & (rows[:, 6] == 14513)][0]
        self.assertGreaterEqual(first_after[1], gap+16)


if __name__ == '__main__':
    unittest.main()
