"""管理選択を人工状態で検査する。原板再生や損益の最適化は行わない。"""

import json
from pathlib import Path
import unittest
import numpy as np
import management_selector142 as m


def fixture():
    """
    機能: 二市場の短期逆行だけ成立し、長期方向は未一致の人工建玉を作る。
    引数: なし。
    返り値: ndarray[20]は書換可能な単一時点状態。
    """
    x = np.zeros(m.SNAPSHOT_SIZE)
    x[m.SIDE],x[m.QUANTITY],x[m.FLOOR_R] = 1.,4.,-1.
    x[m.OWN30_R],x[m.PEER30_R],x[m.OWN120_R],x[m.PEER120_R] = -.1,-.1,-.2,-.2
    x[m.SHORT_CONFIRMED] = 1.
    return x


def set_pairs(x, fast=0., medium=0., slow=0., flow=0.):
    """
    機能: 二市場の各期間方向とOFIを左右同じ値へ設定する。
    引数: x(ndarray)は人工状態、fast/medium/slow/flow(float)は指定値。
    返り値: ndarrayは同じ人工状態。
    """
    x[[m.OWN5_R,m.PEER5_R]] = fast
    x[[m.OWN20_R,m.PEER20_R]] = medium
    x[[m.OWN40_R,m.PEER40_R]] = slow
    x[[m.OWN_OFI,m.PEER_OFI]] = flow
    return x


class SelectorProperties(unittest.TestCase):
    """機械的整合を調べ、有効性の証拠とは区別する。"""

    def test_m01_horizons(self):
        """
        機能: 長短一致の逆行・長い支持・混在で全返済/維持/半減を区別する。
        引数: self(SelectorProperties)は試験状態。
        返り値: None。
        """
        x = fixture()
        self.assertEqual(m.choose_action(1,x),(m.HALF,103))
        set_pairs(x,fast=-1.,medium=-1.,slow=-1.)
        self.assertEqual(m.choose_action(1,x),(m.CLOSE,101))
        set_pairs(x,fast=-1.,medium=1.,slow=1.)
        self.assertEqual(m.choose_action(1,x),(m.HOLD,102))
        x[m.PEER40_R] = 0.
        self.assertEqual(m.choose_action(1,x),(m.HOLD,102))
        x[m.OWN40_R] = 0.
        self.assertEqual(m.choose_action(1,x),(m.HALF,103))

    def test_m02_flow_confirmation(self):
        """
        機能: OFI単独で全返済せず、価格との反証又は支持の一致を必要とする。
        引数: self(SelectorProperties)は試験状態。
        返り値: None。
        """
        x = set_pairs(fixture(),fast=1.,medium=1.,slow=1.,flow=-.1)
        self.assertEqual(m.choose_action(2,x),(m.HALF,203))
        set_pairs(x,fast=-1.,medium=-1.,slow=1.,flow=-.1)
        self.assertEqual(m.choose_action(2,x),(m.CLOSE,201))
        x[m.PEER_OFI] = np.nan
        self.assertEqual(m.choose_action(2,x),(m.HALF,203))
        set_pairs(x,medium=1.,slow=1.,flow=.1)
        self.assertEqual(m.choose_action(2,x),(m.HOLD,202))

    def test_m03_progress_and_loss(self):
        """
        機能: 初期失敗、利益消失、利益吐出し、まだ維持する状態の境界を検査する。
        引数: self(SelectorProperties)は試験状態。
        返り値: None。
        """
        x = set_pairs(fixture(),fast=-1.,medium=-1.)
        x[m.GAIN_R] = -.5
        self.assertEqual(m.choose_action(3,x),(m.CLOSE,301))
        x[m.GAIN_R] = -.499
        self.assertEqual(m.choose_action(3,x),(m.HALF,303))
        x[m.BEST_R],x[m.GAIN_R] = .75,0.
        self.assertEqual(m.choose_action(3,x),(m.CLOSE,301))
        x[m.GAIN_R] = .5
        self.assertEqual(m.choose_action(3,x),(m.HALF,302))
        x[m.GAIN_R] = .501
        self.assertEqual(m.choose_action(3,x),(m.HOLD,304))
        x[m.BEST_R],x[m.GAIN_R] = .749,.1
        self.assertEqual(m.choose_action(3,x),(m.HOLD,304))

    def test_m04_failure_and_stop_buffer(self):
        """
        機能: 長い支持だけでなく既往失敗と元停止までの余裕を管理へ使う。
        引数: self(SelectorProperties)は試験状態。
        返り値: None。
        """
        x = set_pairs(fixture(),fast=-1.,medium=-1.,slow=-1.,flow=.1)
        self.assertEqual(m.choose_action(4,x),(m.CLOSE,401))
        x[m.GAIN_R] = .2
        self.assertEqual(m.choose_action(4,x),(m.HALF,403))
        x[m.FAILED_SAME] = 2.
        self.assertEqual(m.choose_action(4,x),(m.CLOSE,401))
        set_pairs(x,medium=1.,slow=1.,flow=.1)
        x[m.FAILED_SAME] = 0.
        self.assertEqual(m.choose_action(4,x),(m.HOLD,402))
        x[m.FLOOR_R] = 0.
        self.assertEqual(m.choose_action(4,x),(m.HALF,403))
        x[m.GAIN_R] = .251
        self.assertEqual(m.choose_action(4,x),(m.HOLD,402))
        x[m.PEER_OFI] = np.nan
        self.assertEqual(m.choose_action(4,x),(m.HALF,403))

    def test_one_reduction_then_stronger_full_exit(self):
        """
        機能: 同じ親の再半減を禁止し、後で反証が強まれば残玉を全返済できる。
        引数: self(SelectorProperties)は試験状態。
        返り値: None。
        """
        for policy in (1,2,3,4):
            x = set_pairs(fixture(),fast=-1.)
            x[m.GAIN_R] = -.1
            self.assertEqual(m.choose_action(policy,x)[0],m.HALF)
            x[m.PARTIAL_DONE] = 1.
            self.assertEqual(m.choose_action(policy,x),(m.HOLD,20))
            x[m.PARTIAL_DONE],x[m.QUANTITY] = 0.,1.
            self.assertEqual(m.choose_action(policy,x),(m.HOLD,21))
            set_pairs(x,fast=-1.,medium=-1.,slow=-1.,flow=-.1)
            x[m.GAIN_R],x[m.PARTIAL_DONE] = -.7,1.
            self.assertEqual(m.choose_action(policy,x)[0],m.CLOSE)

    def test_short_confirmation_and_missing(self):
        """
        機能: 継続未確認・短期欠測・現在支持の反転では管理提案を出さない。
        引数: self(SelectorProperties)は試験状態。
        返り値: None。
        """
        for policy in (1,2,3,4):
            for col,value,reason in ((m.SHORT_CONFIRMED,0.,10),(m.OWN30_R,-.099,10),
                                     (m.PEER120_R,0.,10),(m.OWN120_R,np.nan,11),
                                     (m.GAIN_R,np.nan,11),(m.FAILED_SAME,np.nan,11),
                                     (m.QUANTITY,0.,12)):
                x = set_pairs(fixture(),fast=-1.,medium=-1.,slow=-1.,flow=-1.)
                x[col] = value
                self.assertEqual(m.choose_action(policy,x),(m.HOLD,reason))

    def test_wrapper_and_immutable_input(self):
        """
        機能: 30列特徴の正しいR換算と、入力を変更しない選択を検査する。
        引数: self(SelectorProperties)は試験状態。
        返り値: None。
        """
        a = np.arange(30,dtype=float)
        a[9],a[18] = 10.,2.
        a[[12,13,20,21]] = -.2
        before = a.copy()
        x = m.snapshot_from_features(1,4,.5,.8,-1.,False,0,a,True)
        np.testing.assert_allclose(x[[m.OWN5_R,m.OWN20_R,m.OWN40_R]],a[[3,28,4]]/10.)
        np.testing.assert_allclose(x[[m.PEER5_R,m.PEER20_R,m.PEER40_R]],a[[14,29,15]]/2.)
        self.assertEqual(x[m.OWN_OFI],a[24])
        self.assertEqual(x[m.PEER_OFI],a[26])
        for policy in (1,2,3,4):
            expected=m.choose_action(policy,x)
            self.assertEqual(m.select_from_features(policy,1,4,.5,.8,-1.,False,0,a,True),expected)
        np.testing.assert_array_equal(a,before)
        a[9] = 0.
        unknown = m.snapshot_from_features(1,4,.5,.8,-1.,False,0,a)
        self.assertTrue(np.isnan(unknown[[m.OWN5_R,m.OWN20_R,m.OWN40_R]]).all())

    def test_mirror_and_market_swap(self):
        """
        機能: 500人工状態で買売反転と市場の左右交換に選択が偏らないことを確認する。
        引数: self(SelectorProperties)は試験状態。
        返り値: None。
        """
        rng = np.random.default_rng(142)
        for unused in range(500):
            x = fixture()
            x[m.OWN5_R:m.SHORT_CONFIRMED] = rng.normal(size=m.SHORT_CONFIRMED-m.OWN5_R)
            x[[m.OWN30_R,m.PEER30_R,m.OWN120_R,m.PEER120_R]] = -.2
            x[m.GAIN_R] = rng.uniform(-1.,2.)
            x[m.BEST_R] = max(0.,x[m.GAIN_R])+rng.uniform(0.,1.)
            x[m.FLOOR_R] = -1.
            x[m.FAILED_SAME] = rng.integers(0,4)
            reflected = x.copy()
            reflected[m.SIDE] *= -1.
            reflected[m.OWN5_R:m.SHORT_CONFIRMED] *= -1.
            swapped = x.copy()
            for left,right in ((m.OWN5_R,m.PEER5_R),(m.OWN20_R,m.PEER20_R),(m.OWN40_R,m.PEER40_R),
                               (m.OWN30_R,m.PEER30_R),(m.OWN120_R,m.PEER120_R),(m.OWN_OFI,m.PEER_OFI)):
                swapped[left],swapped[right]=x[right],x[left]
            before=x.copy()
            for policy in (1,2,3,4):
                selected=m.choose_action(policy,x)
                self.assertEqual(selected,m.choose_action(policy,reflected))
                self.assertEqual(selected,m.choose_action(policy,swapped))
            np.testing.assert_array_equal(x,before)


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SelectorProperties))
    Path(__file__).with_name('管理選択の人工検査142.json').write_text(json.dumps(
        dict(実データ金融再生=False,人工試験=result.testsRun,失敗=len(result.failures),例外=len(result.errors),
             合格=result.wasSuccessful(),上下反転と市場交換の人工状態数=500),ensure_ascii=False,indent=2),encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
