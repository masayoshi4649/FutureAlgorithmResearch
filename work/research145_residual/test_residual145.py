"""人工価格だけでH04同値、切替、利益保護、未来非参照を確認する。"""

import copy
from pathlib import Path
import sys
import unittest
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT/'work/research145_engine'), str(ROOT/'work/nikkei143_20261024')]
import residual145 as engine
import source145
from test_profit_residual143 import sample, native, crop
from test_core_overlay143 import fixture, change, mirror


def zero(base):
    """人工源の費用列を0へ揃える。

    引数: base(ndarray)は人工注文。
    返り値: ndarrayは独立コピー。
    """
    result=base.copy();result[:,9]=0.;return result


def check(data, actual):
    """約定価格・順序・数量・全返済を独立検査する。

    引数: data(dict)、actual(ndarray)は人工入力と約定。
    返り値: None。不整合はassertで停止。
    """
    held={};normal=np.flatnonzero(data['quotes']['quote_valid'])
    for row in actual:
        fill,decision,parent,side,qty,price,reason,new,uid,fee=row
        assert int(fill)==normal[np.searchsorted(normal,decision,side='right')]
        assert price==data['quotes']['ask' if side>0 else 'bid'][int(fill)]
        assert fee==0. and qty>0 and qty==int(qty)
        key=(parent,uid)
        held[key]=held.get(key,0)+int(qty)*(1 if new else -1)
        assert min(held.values())>=0 and sum(held.values())<=5
    assert sum(held.values())==0


class Properties(unittest.TestCase):
    """金融再生前に不変条件を検査する。"""

    def test_original_h04_exact(self):
        """費用0 H04の全約定・診断が無変更対照と同じことを確認する。

        引数: self(Properties)。返り値: None。
        """
        for n in (120,160):
            data,_,base=sample(n);base=zero(base)
            expected,et=source145.replay_residual(data,base,source145.residual.configurations()[4])
            got,gt=engine.replay(data,base,engine.configurations()[0])
            np.testing.assert_array_equal(got,expected)
            np.testing.assert_array_equal(gt,et)
            check(data,got)

    def test_reverse_wait_uses_current_quote_and_source_survival(self):
        """反対源通知時に残玉を返し、待機後の現在価格・方向で新規判断する。

        引数: self(Properties)。返り値: None。
        """
        data,_,_=sample(240);data['ready']['limit']=220.
        change(data,40,240,108.,own120=-.2)
        change(data,80,140,104.,own120=-.2)
        base=zero(native(data,[(0,1,1,3,1,11),(30,1,-1,3,0,11),
            (40,2,-1,2,1,21),(180,2,1,2,0,21)]))
        for wait in (0.,60.,300.,900.):
            cfg=dict(engine.configurations()[6],reentry_wait=wait)
            got,trace=engine.replay(data,base,cfg)
            check(data,got)
            closed=got[(got[:,2]==1)&(got[:,6]==14501)]
            self.assertEqual(closed[:,0].tolist(),[41.])
            opened=got[(got[:,2]==2)&(got[:,7]==1)]
            self.assertEqual(opened[:,0].tolist(),[42.+wait] if wait<100 else [])
            if len(opened):self.assertEqual(opened[0,6],14520.)

    def test_wrong_momentum_waits_and_does_not_force_entry(self):
        """待機満了だけで再参加せず30秒・120秒の方向を確認する。

        引数: self(Properties)。返り値: None。
        """
        data,_,_=sample(150)
        base=zero(native(data,[(0,1,1,3,1,11),(30,1,-1,3,0,11),
            (40,2,-1,2,1,21),(90,2,1,2,0,21)]))
        data['features'][40:80,12:14]=1.
        data['features'][80:,12:14]=-.1
        got,_=engine.replay(data,base,engine.configurations()[6])
        self.assertEqual(got[(got[:,2]==2)&(got[:,7]==1),0].tolist(),[81.])
        check(data,got)

    def test_partial_profit_starts_after_fill_and_frees_next_parent(self):
        """部分利確の実約定後に利益を保護し、元親追加を拒否して次親を許可する。

        引数: self(Properties)。返り値: None。
        """
        data,_=fixture(180);data['ready']['limit']=170.
        change(data,10,35,120.)
        change(data,35,180,108.)
        base=zero(native(data,[(0,1,1,5,1,11),(20,1,-1,2,0,11),
            (80,1,-1,3,0,11),(100,2,-1,2,1,21),(130,2,1,2,0,21)],[20,7,2,20,1]))
        for cfg in engine.configurations()[12:15]:
            got,_=engine.replay(data,base,cfg)
            self.assertEqual(got[(got[:,2]==1)&(got[:,6]>=14530),0].tolist(),[36.])
            self.assertEqual(got[(got[:,2]==2)&(got[:,7]==1),0].tolist(),[101.])
            check(data,got)

    def test_partial_support_requires_continuity(self):
        """部分利確価格の逆側と120秒逆行は15秒連続で確認する。

        引数: self(Properties)。返り値: None。
        """
        data,_=fixture(140);data['ready']['limit']=130.
        change(data,10,35,120.)
        change(data,35,140,108.)
        base=zero(native(data,[(0,1,1,5,1,11),(20,1,-1,2,0,11),(100,1,-1,3,0,11)],[20,7,2]))
        got,_=engine.replay(data,base,engine.configurations()[15])
        self.assertEqual(got[got[:,6]==14533,0].tolist(),[51.])
        check(data,got)

    def test_prefix_future_and_mirror(self):
        """全条件を未来改変・途中打切り・上下反転で検査する。

        引数: self(Properties)。返り値: None。
        """
        data,h,_=sample(150);data['ready']['limit']=140.
        base=zero(native(data,[(0,1,1,3,1,11),(20,1,-1,1,0,11),(30,1,-1,2,0,11),
            (50,2,-1,2,1,21),(110,2,1,2,0,21)],[20,7,2,20,1]))
        data['features'][40:,12:14]=-.2
        md,_,mb=mirror(data,h,base)
        future=copy.deepcopy(data);change(future,70,150,105.)
        fb=base.copy()
        for k,row in enumerate(fb):
            fb[k,5]=future['quotes']['ask' if row[3]>0 else 'bid'][int(row[0])]
        for cfg in engine.configurations():
            actual,trace=engine.replay(data,base,cfg)
            mo,mt=engine.replay(md,mb,cfg)
            expected=actual.copy();expected[:,3]*=-1.;expected[:,5]=200.-expected[:,5]
            np.testing.assert_allclose(mo,expected)
            for length in (15,21,22,30,31,32,51,52,70,111):
                clipped=crop(data,length);clipped['features']=data['features'][:length]
                part,pt=engine.replay(clipped,base,cfg)
                np.testing.assert_allclose(part,actual[actual[:,0]<length])
            fo,_=engine.replay(future,fb,cfg)
            np.testing.assert_allclose(fo[fo[:,0]<70],actual[actual[:,0]<70])
            check(data,actual)

    def test_quote_gap_and_pending_orders_are_preserved(self):
        """独自全返済は欠測後の次正常気配まで残し、同原行の返済を作らない。

        引数: self(Properties)。返り値: None。
        """
        data,_=fixture(140);data['ready']['limit']=130.
        change(data,10,35,120.);change(data,35,140,108.)
        data['quotes']['quote_valid'][36:42]=False
        base=zero(native(data,[(0,1,1,5,1,11),(20,1,-1,2,0,11),(100,1,-1,3,0,11)],[20,7,2]))
        got,_=engine.replay(data,base,engine.configurations()[12])
        final=got[got[:,6]==14531][0]
        self.assertEqual((final[1],final[0],final[4]),(35.,42.,3.))
        check(data,got)

    def test_nonpositive_remaining_peak_is_not_a_profit_floor(self):
        """最初の利益玉を部分決済しても残玉が赤字ならゼロを既得利益と扱わない。

        引数: self(Properties)。返り値: None。
        """
        data,_=fixture(140);data['ready']['limit']=130.
        change(data,5,10,120.);change(data,10,140,105.)
        base=zero(native(data,[(0,1,1,2,1,11),(5,1,1,3,1,12),(20,1,-1,2,0,11),
            (100,1,-1,3,0,12)],[20,20,7,1]))
        for cfg in engine.configurations()[12:]:
            got,_=engine.replay(data,base,cfg)
            self.assertFalse(np.any(got[:,6]>=14530))
            check(data,got)

    def test_same_direction_replacement_is_explicit(self):
        """反対専用と同方向許可の切替を混同しない。

        引数: self(Properties)。返り値: None。
        """
        data,_,_=sample(150);data['ready']['limit']=140.
        data['features'][:,12:14]=.2
        base=zero(native(data,[(0,1,1,3,1,11),(30,1,-1,3,0,11),
            (40,2,1,2,1,21),(90,2,-1,2,0,21)]))
        refused,_=engine.replay(data,base,engine.configurations()[6])
        accepted,_=engine.replay(data,base,engine.configurations()[10])
        self.assertFalse(np.any(refused[:,2]==2))
        self.assertEqual(accepted[(accepted[:,2]==2)&(accepted[:,7]==1),0].tolist(),[42.])
        check(data,refused);check(data,accepted)

    def test_invalid_quote_breaks_support_duration(self):
        """支持破綻の15秒確認を異常板の前後でつながない。

        引数: self(Properties)。返り値: None。
        """
        data,_=fixture(140);data['ready']['limit']=130.
        change(data,10,35,120.);change(data,35,140,108.)
        data['quotes']['quote_valid'][42]=False
        base=zero(native(data,[(0,1,1,5,1,11),(20,1,-1,2,0,11),(100,1,-1,3,0,11)],[20,7,2]))
        got,_=engine.replay(data,base,engine.configurations()[15])
        self.assertEqual(got[got[:,6]==14533,0].tolist(),[59.])
        check(data,got)


if __name__=='__main__':
    unittest.main()
