"""新しい積極参加の時系列・上下対称・会計を人工価格で確認する。"""

import copy
import unittest
from datetime import datetime
import numpy as np
import active140 as a


def packet():
    """
    機能: 往復と伸長を含む二市場の原行を作る。
    引数: なし。
    返り値: dictは同時刻の異市場を含む人工一場。金銭的証拠には数えない。
    """
    start = datetime.fromisoformat('2026-10-01T08:45:00+09:00').timestamp()
    t = start + np.arange(0., 9001., 5.)
    wave = np.interp(t-start,[0,1200,1800,2400,3000,3600,4200,4800,6000,7500,9000],
                     [0,10,18,12,30,26,35,12,0,35,0])
    out = dict(session='2026-10-01_Day',inputs={},quotes={})
    for symbol,scale,base in [('NK225',20.,65000.),('TOPIX',1.,4000.)]:
        key = out['session'],symbol
        price = base + scale*wave
        out['inputs'][key] = dict(session=key[0],symbol=symbol,time_s=t.copy(),last=price,atr=np.full(len(t),4.*scale),
            start=start,limit=t[-1]-60.,tick=.5*scale,us_open=start+14*3600.)
        out['quotes'][key] = dict(bid=price-.25*scale,ask=price+.25*scale,quote_valid=np.ones(len(t),bool))
    return out


class Properties(unittest.TestCase):
    """人工の未来改変と売買反転を確認する。"""

    def test_symmetry_and_prefix(self):
        """
        機能: 全入口機構で上下反転対称と未来改変前の注文不変を確認する。
        引数: self(Properties)は検証状態。
        返り値: None。未来参照・非対称・約定遡及・数量超過なら失敗する。
        """
        raw=packet();original=a.prepare(raw,10)
        mirrored=copy.deepcopy(raw);changed=copy.deepcopy(raw)
        cut=1000
        for key,r in raw['inputs'].items():
            level=2*r['last'][0]
            mirrored['inputs'][key]['last']=level-r['last']
            q=raw['quotes'][key]
            mirrored['quotes'][key]['bid']=level-q['ask']
            mirrored['quotes'][key]['ask']=level-q['bid']
            for name in ('last','atr'):
                changed['inputs'][key][name][cut:]*=1.02
            for name in ('bid','ask'):
                changed['quotes'][key][name][cut:]*=1.02
        inverse=a.prepare(mirrored,10);future=a.prepare(changed,10)
        checked=0
        for c in a.configurations()[:12]:
            c=dict(c,budget_ticks=200.)
            for symbol in original:
                orders,curve=a.replay(original[symbol],c)
                reversed_orders,_=a.replay(inverse[symbol],c)
                other,_=a.replay(future[symbol],c)
                np.testing.assert_allclose(orders[:,[0,1,2,4,6,7,8,9]],reversed_orders[:,[0,1,2,4,6,7,8,9]])
                np.testing.assert_allclose(orders[:,3],-reversed_orders[:,3])
                np.testing.assert_allclose(orders[orders[:,0]<cut],other[other[:,0]<cut])
                self.assertTrue(np.all(orders[:,0]>orders[:,1]))
                quantity={}
                for row in orders:
                    key=(int(row[2]),int(row[8]))
                    quantity[key]=quantity.get(key,0)+(int(row[4]) if row[7] else -int(row[4]))
                    self.assertGreaterEqual(quantity[key],0)
                self.assertTrue(all(x==0 for x in quantity.values()))
                checked+=len(orders)
        self.assertGreater(checked,20)

    def test_peer_same_timestamp(self):
        """
        機能: 相手市場の同時刻改変が当行特徴へ入らないことを確認する。
        引数: self(Properties)は検証状態。
        返り値: None。厳密過去の接続に違反すると失敗する。
        """
        raw=packet();original=a.prepare(raw,10)
        changed=copy.deepcopy(raw);ix=700
        for name in ('bid','ask'):
            changed['quotes'][(raw['session'],'TOPIX')][name][ix:]+=100.
        newer=a.prepare(changed,10)
        np.testing.assert_allclose(original['NK225']['features'][:ix+1],newer['NK225']['features'][:ix+1],equal_nan=True)


if __name__=='__main__':
    unittest.main()
