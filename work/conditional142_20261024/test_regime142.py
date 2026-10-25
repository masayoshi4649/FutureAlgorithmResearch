"""中期支持維持・押し待ち・失敗後回復の状態を人工入力だけで検査する。"""

import json
from pathlib import Path
import unittest
import numpy as np
import regime_selector142 as s
import regime_trader142 as t
import test_patrol142 as previous


def fixture(pullback=False):
    """
    機能: 二市場の中期支持があり、任意で準備後の押し再進行を持つ人工系列を作る。
    引数: pullback(bool)は押し経路を入れるか。
    返り値: dictは48列特徴と気配・時計。
    """
    d=previous.fixture();a=np.column_stack((d['features'],np.full((len(d['features']),12),np.nan)))
    a[:,[28,29]]=1.
    a[:,36],a[:,37],a[:,38],a[:,39],a[:,40],a[:,41]=99.5,98.,110.,95.,3.,.5
    a[:,42:48]=a[:,36:42]
    d['features']=a
    if pullback:
        values=np.full(len(a),104.5);values[:5]=[100.,106.,103.,104.5,104.5]
        d['quotes']['bid'],d['quotes']['ask']=values-.5,values+.5
        a[:,10]=values
    return d


def config(policy=1,wide=False):
    """
    機能: 三機構と二保険幅の設定を取得する。
    引数: policy(int)は1～3、wide(bool)は広め。
    返り値: dictは設定複製。
    """
    return t.configurations()[(policy-1)*2+int(wide)].copy()


def mirror(d):
    """
    機能: 48列の価格・上下帯・方向を鏡像化し、標準偏差・効率を保つ。
    引数: d(dict)は人工入力。
    返り値: dictは中心100の鏡像。
    """
    out=previous.mirror(d);a,b=d['features'],out['features']
    for col in (36,37,42,43):b[:,col]=200.-a[:,col]
    for high,low in ((38,39),(44,45)):b[:,high],b[:,low]=200.-a[:,low],200.-a[:,high]
    return out


class RegimeProperties(unittest.TestCase):
    """利益改善を主張せず、状態機械の因果性と会計を検査する。"""

    def test_support_position_hysteresis(self):
        """
        機能: 新規と退出の価格境界を分け、短期逆行を中期崩れと同一視しない。
        引数: self(RegimeProperties)は試験状態。
        返り値: None。
        """
        a=fixture()['features'][0].copy()
        self.assertEqual(s.supported_side(a),1)
        a[[12,13,20,21]]=-10.
        self.assertEqual(s.management(a,1,1,1),(0,30))
        a[10],a[19]=97.,97.
        self.assertEqual(s.management(a,1,1,1),(0,30))
        a[36]=97.5
        self.assertEqual(s.management(a,1,1,1),(1,31))
        a[10]=97.001
        self.assertEqual(s.management(a,1,1,1),(0,30))

    def test_first_entry_and_pullback(self):
        """
        機能: 状態参加と押し再進行参加を異なる判断時刻として検査する。
        引数: self(RegimeProperties)は試験状態。
        返り値: None。
        """
        for policy in (1,2,3):
            for wide in (False,True):
                d=fixture(True);orders,curve,trace=t.replay(d,config(policy,wide))
                self.assertEqual(tuple(orders[0,:2]),(5.,4.) if policy==2 else (2.,1.))
                self.assertEqual(orders[0,4],2.)
                self.assertEqual(previous.audit(orders,curve,d),2)
                self.assertFalse(np.any(orders[:,6]==1449))
        d=fixture();orders,curve,_=t.replay(d,config(2))
        self.assertEqual(len(orders),0)
        previous.audit(orders,curve,d)

    def test_short_reverse_keeps_position(self):
        """
        機能: 中期支持位置を保つ間は120秒符号だけで返済せず、元停止も維持する。
        引数: self(RegimeProperties)は試験状態。
        返り値: None。
        """
        d=fixture();d['features'][20:,[12,13,20,21,3,14]]=-10.
        orders,curve,_=t.replay(d,config())
        self.assertEqual(len(orders),2);self.assertEqual(orders[-1,6],93.)
        d['quotes']['bid'][40:],d['quotes']['ask'][40:]=89.5,90.5
        d['features'][40:,10]=90.
        orders,curve,_=t.replay(d,config())
        first_close=orders[(orders[:,2]==0)&(orders[:,7]==0)][0]
        self.assertEqual(tuple(first_close[:2]),(41.,40.));self.assertEqual(first_close[6],32.)
        previous.audit(orders,curve,d)

    def test_actual_support_loss_waits_ten_seconds(self):
        """
        機能: 二市場価格と短平均の支持喪失が10秒続いてから返済を予約する。
        引数: self(RegimeProperties)は試験状態。
        返り値: None。
        """
        d=fixture();a=d['features']
        a[20:,[10,19]]=96.5;a[20:,36]=97.5
        d['quotes']['bid'][20:],d['quotes']['ask'][20:]=96.,97.
        orders,curve,_=t.replay(d,config())
        self.assertEqual(tuple(orders[-1,:2]),(23.,22.));self.assertEqual(orders[-1,6],1451.)
        previous.audit(orders,curve,d)
        d['quotes']['quote_valid'][21]=False
        orders,curve,_=t.replay(d,config())
        self.assertEqual(tuple(orders[-1,:2]),(25.,24.))
        previous.audit(orders,curve,d)

    def test_completed_loss_requires_new_pullback(self):
        """
        機能: 完結損失後だけ同方向再参加を止め、出口後の新しい押し再進行で解除する。
        引数: self(RegimeProperties)は試験状態。
        返り値: None。
        """
        d=fixture();a=d['features'];mid=np.full(len(a),100.)
        mid[20],mid[21],mid[22:40],mid[40],mid[41:]=90.,91.,101.,98.,99.5
        a[:,10]=mid;d['quotes']['bid'],d['quotes']['ask']=mid-.5,mid+.5
        a[20:,36],a[20:,37]=85.,80.
        orders,curve,_=t.replay(d,config(3))
        first_close=orders[(orders[:,2]==0)&(orders[:,7]==0)][0]
        second_new=orders[(orders[:,2]==1)&(orders[:,7]==1)][0]
        self.assertEqual(tuple(first_close[:2]),(21.,20.))
        self.assertEqual(tuple(second_new[:2]),(43.,42.))
        self.assertFalse(np.any((orders[:,7]==1)&(orders[:,0]>21)&(orders[:,0]<43)))
        previous.audit(orders,curve,d)
        immediate,ic,_=t.replay(d,config(1))
        self.assertLess(immediate[(immediate[:,2]==1)&(immediate[:,7]==1)][0,0],second_new[0])
        previous.audit(immediate,ic,d)

    def test_missing_resets_setup(self):
        """
        機能: 準備途中の欠測・時計飛び・支持崩れを越えて古い押しを再利用しない。
        引数: self(RegimeProperties)は試験状態。
        返り値: None。
        """
        for failure in ('missing','gap','support'):
            d=fixture(True)
            if failure=='missing':d['features'][3,42]=np.nan
            elif failure=='gap':d['ready']['time_s'][3:]+=20.
            else:d['features'][3,37]=110.
            orders,curve,_=t.replay(d,config(2))
            self.assertEqual(len(orders),0)
            previous.audit(orders,curve,d)

    def test_all_policies_mirror_and_future(self):
        """
        機能: 6条件の売買方向・状態・費用・未来改変前の判断が対称であることを確認する。
        引数: self(RegimeProperties)は試験状態。
        返り値: None。
        """
        for c in t.configurations():
            d=fixture(True);reflected=mirror(d)
            orders,curve,trace=t.replay(d,c);opposite,oc,ot=t.replay(reflected,c)
            np.testing.assert_array_equal(orders[:,[0,1,2,4,6,7,8,9]],opposite[:,[0,1,2,4,6,7,8,9]])
            np.testing.assert_array_equal(orders[:,3],-opposite[:,3])
            np.testing.assert_allclose(orders[:,5],200.-opposite[:,5],rtol=0,atol=1e-8)
            np.testing.assert_allclose(curve,oc,rtol=0,atol=1e-8)
            changed=dict(d,quotes=dict(d['quotes']),features=d['features'].copy())
            for name in ('bid','ask'):
                changed['quotes'][name]=d['quotes'][name].copy();changed['quotes'][name][100:]=reflected['quotes'][name][100:]
            changed['features'][100:]=reflected['features'][100:]
            future,fc,ft=t.replay(changed,c)
            np.testing.assert_array_equal(orders[orders[:,0]<100],future[future[:,0]<100])
            np.testing.assert_array_equal(trace[trace[:,0]<100],ft[ft[:,0]<100])
            previous.audit(orders,curve,d);previous.audit(opposite,oc,reflected);previous.audit(future,fc,changed)


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RegimeProperties))
    Path(__file__).with_name('中期状態の人工検査142.json').write_text(json.dumps(
        dict(実データ金融再生=False,人工試験=result.testsRun,失敗=len(result.failures),例外=len(result.errors),合格=result.wasSuccessful()),
        ensure_ascii=False,indent=2),encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
