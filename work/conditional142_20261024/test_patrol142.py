"""巡回参加の判断・約定・再参加を人工入力だけで検査する。"""

import json
import unittest
from pathlib import Path
import numpy as np
import patrol_selector142 as s
import patrol_trader142 as t


def fixture():
    """
    機能: 中期未公開だが二市場短期支持と十分なレンジがある人工入力を作る。
    引数: なし。
    返り値: dictはready・quotes・36列特徴。
    """
    n=421;times=np.arange(n,dtype=float)*5.;mid=np.full(n,100.)
    a=np.full((n,36),np.nan)
    a[:,9],a[:,18],a[:,10],a[:,19]=10.,10.,mid,mid
    a[:,[12,20]]=.1;a[:,[13,21]]=.2;a[:,[24,26]]=.1
    a[:,[3,14]]=2.;a[:,[30,31]]=12.;a[:,[32,33,34,35]]=1.
    return dict(ready=dict(time_s=times,start=0.,limit=2000.,us_open=600.,symbol='NK225',session='人工_Day'),
                quotes=dict(bid=mid-.5,ask=mid+.5,quote_valid=np.ones(n,bool)),features=a)


def config(policy=1,wide=False):
    """
    機能: 固定12条件から指定の政策と幅を取得する。
    引数: policy(int)は1～6、wide(bool)は広め幅。
    返り値: dictは設定の複製。
    """
    return t.configurations()[(policy-1)*2+int(wide)].copy()


def mirror(data):
    """
    機能: 人工入力の方向と価格・板圧力を上下反転する。
    引数: data(dict)は元入力。
    返り値: dictは中心100の鏡像。時計・R・レンジ・気配幅・呼値は維持する。
    """
    d=dict(data,quotes=dict(data['quotes']),features=data['features'].copy())
    d['quotes']['bid']=200.-data['quotes']['ask'];d['quotes']['ask']=200.-data['quotes']['bid']
    a,b=data['features'],d['features']
    b[:,0],b[:,1]=200.-a[:,1],200.-a[:,0]
    for c in (5,6,7,10,17,19):b[:,c]=200.-a[:,c]
    for c in (3,4,12,13,14,15,20,21,24,25,26,27,28,29):b[:,c]=-a[:,c]
    return d


def audit(orders,curve,data):
    """
    機能: 全注文の数量・次正常板・方向・費用・最終現金を独立計算する。
    引数: orders/curve(ndarray)、data(dict)は出力と入力。
    返り値: intは最大保有枚数。終端残玉があれば失敗する。
    """
    q=data['quotes'];normal=np.flatnonzero(q['quote_valid'])
    fee,mult=(385,100.) if data['ready']['symbol']=='NK225' else (418,1000.)
    tickets={};total=maximum=0;cash=0.
    for o in orders:
        row,source,parent,side,qty=map(int,o[:5]);new,uid,cost=map(int,o[7:])
        assert row==normal[np.searchsorted(normal,source,side='right')]
        assert cost==qty*fee//10 and o[5]==(q['ask'][row] if side>0 else q['bid'][row])
        key=parent,uid
        if new:
            assert key not in tickets;tickets[key]=[side,qty];total+=qty
        else:
            assert tickets[key][0]==-side and tickets[key][1]>=qty
            tickets[key][1]-=qty;total-=qty
        assert 0<=total<=5
        maximum=max(maximum,total);cash-=side*qty*o[5]*mult+cost
    assert total==0 and all(qty==0 for side,qty in tickets.values())
    np.testing.assert_allclose(curve[-1],cash,rtol=0,atol=1e-8)
    return maximum


class PatrolProperties(unittest.TestCase):
    """参加率や利益の有効性を採点せず、仕様と因果順を検査する。"""

    def test_early_entry_without_medium(self):
        """
        機能: 中期NaNでも短期合議で参加し、時刻だけを理由に途中返済しない。
        引数: self(PatrolProperties)は試験状態。
        返り値: None。
        """
        for c in t.configurations():
            d=fixture();orders,curve,trace=t.replay(d,c)
            self.assertEqual(tuple(orders[0,:2]),(2.,1.))
            self.assertEqual(orders[0,4],2.)
            self.assertEqual(orders[-1,6],93.)
            self.assertEqual(len(orders),2)
            audit(orders,curve,d)

    def test_activity_and_flow(self):
        """
        機能: 無方向の狭い値幅と未知の原板を有効な支持へ読み替えない。
        引数: self(PatrolProperties)は試験状態。
        返り値: None。
        """
        x=fixture()['features'][0].copy()
        x[30]=3.999
        self.assertEqual(s.signal(x,1)[0],0)
        x[30]=4.
        self.assertEqual(s.signal(x,1)[0],1)
        x[24]=np.nan
        self.assertEqual(s.signal(x,4)[0],0)
        x[[28,29]]=-1.
        self.assertEqual(s.signal(x,6)[0],0)
        x[[24,26]]=.1;x[[13,21]]=.2
        self.assertEqual(s.signal(x,6),(1,2,21,15.))

    def test_medium_hold_and_reversal(self):
        """
        機能: 中期合意中は短期だけの逆行を維持し、5分も崩れた場合にだけ撤退する。
        引数: self(PatrolProperties)は試験状態。
        返り値: None。
        """
        d=fixture();a=d['features'];a[:,[28,29]]=1.
        a[20:,[12,13,20,21]]=-.2
        a[40:,[3,14]]=-2.
        orders,curve,trace=t.replay(d,config(2))
        first_close=orders[(orders[:,2]==0)&(orders[:,7]==0)][0]
        self.assertEqual(tuple(first_close[:2]),(43.,42.))
        self.assertTrue(any(row[4]==32 for row in trace))
        audit(orders,curve,d)

    def test_reverse_after_close_not_same_fill(self):
        """
        機能: 反転案だけは返済完了後すぐ再予約し、新規約定は必ず後の正常原行になる。
        引数: self(PatrolProperties)は試験状態。
        返り値: None。
        """
        d=fixture();d['features'][20:,[12,13,20,21,24,26]]=-.2
        old,oc,_=t.replay(d,config(1));new,nc,_=t.replay(d,config(3))
        closing=new[(new[:,2]==0)&(new[:,7]==0)][0]
        entry=new[(new[:,2]==1)&(new[:,7]==1)][0]
        self.assertEqual(tuple(closing[:2]),(23.,22.))
        self.assertEqual(tuple(entry[:2]),(24.,23.))
        self.assertEqual(entry[3],-1.)
        self.assertGreater(old[(old[:,2]==1)&(old[:,7]==1)][0,0],entry[0])
        audit(old,oc,d);audit(new,nc,d)

    def test_inactivity_requires_continuation(self):
        """
        機能: 小さいレンジを一度見ただけで退出せず300秒継続を待ち、無効板で数え直す。
        引数: self(PatrolProperties)は試験状態。
        返り値: None。
        """
        d=fixture();d['features'][20:,[30,31]]=1.
        orders,curve,_=t.replay(d,config())
        self.assertEqual(tuple(orders[-1,:2]),(81.,80.))
        self.assertEqual(orders[-1,6],1470.)
        audit(orders,curve,d)
        d['quotes']['quote_valid'][60]=False
        orders,curve,_=t.replay(d,config())
        self.assertEqual(tuple(orders[-1,:2]),(122.,121.))
        audit(orders,curve,d)

    def test_reverse_cooldown_exception_has_direction(self):
        """
        機能: 反転返済の約定待ち中に元方向へ戻っても、同方向の冷却を免除しない。
        引数: self(PatrolProperties)は試験状態。
        返り値: None。
        """
        d=fixture();d['features'][20:40,[12,13,20,21,24,26]]=-.2
        d['quotes']['quote_valid'][23:50]=False
        orders,curve,_=t.replay(d,config(3))
        close=orders[(orders[:,2]==0)&(orders[:,7]==0)][0]
        entry=orders[(orders[:,2]==1)&(orders[:,7]==1)][0]
        self.assertEqual(tuple(close[:2]),(50.,22.))
        self.assertEqual(tuple(entry[:2]),(57.,56.))
        self.assertEqual(entry[3],1.)
        audit(orders,curve,d)

    def test_frozen_risk_and_stop_priority(self):
        """
        機能: 初回判断Rを保険幅へ固定し、中期反転と同時でも元停止を先に発注する。
        引数: self(PatrolProperties)は試験状態。
        返り値: None。
        """
        d=fixture();d['features'][20:,9]=100.
        d['quotes']['bid'][20:],d['quotes']['ask'][20:]=89.5,90.5
        d['features'][20:,[12,13,20,21]]=-.2
        c=config(3);c['exit_hold']=0.
        orders,curve,_=t.replay(d,c)
        close=orders[(orders[:,2]==0)&(orders[:,7]==0)][0]
        self.assertEqual(tuple(close[:2]),(21.,20.));self.assertEqual(close[6],32.)
        audit(orders,curve,d)

    def test_additions_caps_fees_and_terminal_pending(self):
        """
        機能: 中期支持時の初回3枚と保護後追加、次正常板待ち、場末予約を検査する。
        引数: self(PatrolProperties)は試験状態。
        返り値: None。
        """
        for symbol in ('NK225','TOPIX'):
            d=fixture();d['ready']['symbol']=symbol;d['features'][:,[28,29]]=1.
            d['quotes']['bid'][20:]=129.5;d['quotes']['ask'][20:]=130.5
            orders,curve,_=t.replay(d,config(5))
            self.assertEqual(orders[0,4],3.)
            self.assertEqual(audit(orders,curve,d),5)
            self.assertTrue(np.any(orders[:,6]==1449))
        d=fixture();d['quotes']['quote_valid'][2:401]=False
        c=config();orders,curve,_=t.replay(d,c)
        self.assertEqual(tuple(orders[0,:2]),(401.,1.))
        self.assertEqual(tuple(orders[-1,:2]),(402.,401.))
        self.assertEqual(orders[-1,6],93.);audit(orders,curve,d)

    def test_all_profiles_mirror_future_and_quiet(self):
        """
        機能: 12政策の上下対称・未来改変前同値と米国前後の任意静観を確認する。
        引数: self(PatrolProperties)は試験状態。
        返り値: None。
        """
        for c in t.configurations():
            d=fixture();d['features'][:,[28,29]]=1.
            d['quotes']['bid'][20:80]=np.linspace(100.,130.,60)-.5
            d['quotes']['ask'][20:80]=d['quotes']['bid'][20:80]+1.
            d['quotes']['bid'][80:]=119.5;d['quotes']['ask'][80:]=120.5
            d['features'][150:,[12,13,20,21,24,26,28,29,3,14]]=-.2
            opposite=mirror(d)
            orders,curve,trace=t.replay(d,c);reflected,rcurve,rtrace=t.replay(opposite,c)
            np.testing.assert_array_equal(orders[:,[0,1,2,4,6,7,8,9]],reflected[:,[0,1,2,4,6,7,8,9]])
            np.testing.assert_array_equal(orders[:,3],-reflected[:,3])
            np.testing.assert_allclose(orders[:,5],200.-reflected[:,5],atol=1e-10,rtol=0.)
            np.testing.assert_allclose(curve,rcurve,atol=1e-8,rtol=0.)
            changed=dict(d,quotes=dict(d['quotes']),features=d['features'].copy())
            for name in ('bid','ask'):
                changed['quotes'][name]=d['quotes'][name].copy();changed['quotes'][name][100:]=opposite['quotes'][name][100:]
            changed['features'][100:]=opposite['features'][100:]
            future,fc,ft=t.replay(changed,c)
            np.testing.assert_array_equal(orders[orders[:,0]<100],future[future[:,0]<100])
            np.testing.assert_array_equal(trace[trace[:,0]<100],ft[ft[:,0]<100])
            audit(orders,curve,d);audit(reflected,rcurve,opposite);audit(future,fc,changed)
        d=fixture();d['ready']['session']='人工_Night';c=config();c['quiet_seconds']=60.
        orders,curve,_=t.replay(d,c)
        self.assertTrue(np.any(orders[:,6]==94.))
        new=orders[orders[:,7]==1]
        self.assertFalse(np.any((new[:,1]*5.>=540.)&(new[:,1]*5.<660.)))
        audit(orders,curve,d)


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PatrolProperties))
    Path(__file__).with_name('巡回参加の人工検査142.json').write_text(json.dumps(
        dict(実データ金融再生=False,人工試験=result.testsRun,失敗=len(result.failures),例外=len(result.errors),合格=result.wasSuccessful()),
        ensure_ascii=False,indent=2),encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
