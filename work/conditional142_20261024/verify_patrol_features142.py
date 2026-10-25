"""巡回特徴を独立した人工資料で照合し、未来参照と市場接続を検査する。"""

import copy
import json
import unittest
from pathlib import Path
import numpy as np
from patrol_features142 import prepare, rolling_range


def fixture():
    """
    機能: 同時計の別原行を含む二市場の人工資料を作る。
    引数: なし。
    返り値: dictは価格・原気配・公開幅を持つ入力。
    """
    out = {}
    t = np.repeat(np.arange(0., 1000., 2.), 2)
    for symbol, center, tick in (('NK225', 65000., 10.), ('TOPIX', 4000., .5)):
        price = center+tick*np.sin(t/30.)+np.arange(len(t))*.01*tick
        a = np.full((len(t),30),np.nan)
        a[:,10], a[:,11] = price, 2.*tick
        a[:,24:28] = .1
        out[symbol] = dict(ready=dict(time_s=t.copy(),atr=np.full(len(t),3.*tick),tick=tick),
            quotes=dict(bid=price-tick/2,ask=price+tick/2,quote_valid=np.ones(len(t),bool)),features=a)
    return out


class FeatureAudit(unittest.TestCase):
    """金融状態を持たず、特徴量の原行境界と対称性だけを調べる。"""

    def test_range_bruteforce(self):
        """
        機能: 同秒・欠測・無効板を含む窓高安を総当たりの過去参照と照合する。
        引数: self(FeatureAudit)は検査状態。
        返り値: None。
        """
        rng = np.random.default_rng(14201)
        t = np.cumsum(rng.integers(0,5,500)).astype(float)
        p = 100.+np.cumsum(rng.normal(size=len(t)))
        good = rng.random(len(t)) > .2
        p[rng.random(len(t)) < .1] = np.nan
        for width in (1.,30.,300.):
            expected = []
            for i in range(len(t)):
                ix = (t[:i+1] >= t[i]-width)&good[:i+1]&np.isfinite(p[:i+1])
                values = p[:i+1][ix]
                expected.append(values.max()-values.min() if len(values) else np.nan)
            np.testing.assert_allclose(rolling_range(t,p,good,width),expected,equal_nan=True)

    def test_same_clock_peer_and_stale(self):
        """
        機能: 相手の同時計全行を除外し、15秒より古い相手資料を未知にする。
        引数: self(FeatureAudit)は検査状態。
        返り値: None。
        """
        base = fixture()
        result = prepare({},base)
        a = result['NK225']['features']
        self.assertTrue(np.isnan(a[:2,22]).all())
        self.assertEqual(a[2,22],0.)
        self.assertEqual(a[3,22],0.)
        self.assertEqual(a[2,19],base['TOPIX']['features'][1,10])
        self.assertEqual(a[3,19],base['TOPIX']['features'][1,10])
        short = copy.deepcopy(base)
        for k in short['TOPIX']['ready']:
            if isinstance(short['TOPIX']['ready'][k],np.ndarray):short['TOPIX']['ready'][k]=short['TOPIX']['ready'][k][:2]
        for k in short['TOPIX']['quotes']:short['TOPIX']['quotes'][k]=short['TOPIX']['quotes'][k][:2]
        short['TOPIX']['features']=short['TOPIX']['features'][:2]
        stale = prepare({},short)['NK225']['features']
        self.assertTrue(np.isnan(stale[20,[14,18,19,20,21,22,31,33,35]]).all())

    def test_future_prefix_and_immutable(self):
        """
        機能: 未知後半の価格・幅・気配変更が過去特徴へ届かず、元入力も不変と確認する。
        引数: self(FeatureAudit)は検査状態。
        返り値: None。
        """
        base = fixture()
        before = copy.deepcopy(base)
        first = prepare({},base)
        changed = copy.deepcopy(base)
        for item in changed.values():
            item['features'][600:,10] += 10000.
            item['features'][600:,11] += 100.
            item['quotes']['bid'][600:] += 10000.
            item['quotes']['ask'][600:] += 10005.
            item['ready']['atr'][600:] += 100.
        after = prepare({},changed)
        for symbol in base:
            np.testing.assert_allclose(first[symbol]['features'][:600],after[symbol]['features'][:600],equal_nan=True)
            np.testing.assert_array_equal(base[symbol]['features'],before[symbol]['features'])
            for group in ('ready','quotes'):
                for key,value in base[symbol][group].items():
                    np.testing.assert_equal(value,before[symbol][group][key])

    def test_mirror(self):
        """
        機能: 上下反転で方向量だけ反転し、レンジ・気配差・幅・時計は不変と確認する。
        引数: self(FeatureAudit)は検査状態。
        返り値: None。
        """
        base = fixture()
        mirror = copy.deepcopy(base)
        for symbol,axis in (('NK225',130000.),('TOPIX',8000.)):
            mirror[symbol]['features'][:,10] = axis-base[symbol]['features'][:,10]
            mirror[symbol]['features'][:,24:28] *= -1.
            mirror[symbol]['quotes']['bid'] = axis-base[symbol]['quotes']['ask']
            mirror[symbol]['quotes']['ask'] = axis-base[symbol]['quotes']['bid']
        a,b = prepare({},base),prepare({},mirror)
        for symbol,axis,peer_axis in (('NK225',130000.,8000.),('TOPIX',8000.,130000.)):
            x,y=a[symbol]['features'],b[symbol]['features']
            np.testing.assert_allclose(x[:,[3,12,13,14,20,21]],-y[:,[3,12,13,14,20,21]],equal_nan=True,atol=1.e-9)
            np.testing.assert_allclose(x[:,[9,18,22,30,31,32,33,34,35]],y[:,[9,18,22,30,31,32,33,34,35]],equal_nan=True,atol=1.e-9)
            np.testing.assert_allclose(x[:,10],axis-y[:,10],equal_nan=True)
            np.testing.assert_allclose(x[:,19],peer_axis-y[:,19],equal_nan=True)


if __name__ == '__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(FeatureAudit))
    value=dict(financial_replays=0,tests=result.testsRun,passed=result.wasSuccessful(),failures=len(result.failures),errors=len(result.errors))
    Path(__file__).with_name('巡回特徴の独立人工検査142.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
