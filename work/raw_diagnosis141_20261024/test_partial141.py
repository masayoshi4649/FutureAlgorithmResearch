"""部分返済の枚数・注文順・残玉管理を人工入力だけで独立検査する。"""

import json
from pathlib import Path
import unittest
import numpy as np
import active141 as previous
import active141_v3 as revised


def fixture(initial=2, maximum=5, additions=True):
    """
    機能: 反発新規、順行追撃、短期逆行、再順行、最後の逆行を人工生成する。
    引数: initial/maximum(int)は初回と上限、additions(bool)は追撃経路の有無。
    返り値: dictはsimulateへ渡す完全な人工入力。
    """
    n = 130
    times = np.arange(n, dtype=float)*5.
    mid = np.full(n, 103.)
    mid[0] = 100.
    if additions:
        mid[7:] = 109.
        mid[13:] = 114.
        mid[19:] = 119.
        mid[40:] = 130.
    mid[80:] = 90.
    a = np.zeros((n,28))
    a[:,0],a[:,1],a[:,2],a[:,9] = 110.,100.,.1,10.
    a[:,10] = mid
    a[:,[12,13,20,21,24,26]] = .2
    a[24:40,[12,13,20,21,24,26]] = -.2
    return dict(times=times,bid=mid-.5,ask=mid+.5,good=np.ones(n,dtype=bool),a=a,
                start=0.,end=600.,us_open=np.nan,tick=1.,multiplier=100.,fee=385,
                mode=4,initial=initial,maximum=maximum,add_step=.5,stop=1.,activation=100.,
                trail=.75,hold=0.,cooldown=120.,ttl=1200.,use_peer=True,
                budget_ticks=1000.,loss_pause=900.,loss_limit=2,quiet_seconds=0.,
                entry_end=300.,delay=0.,entry_guard=0,add_guard=0,exit_guard=1,
                flow_guard=0,evidence_hold=15.)


def audit(orders, equity, data):
    """
    機能: 全注文の次正常行約定・枚数・注文別費用・終端実損益を独立計算する。
    引数: orders/equity(ndarray)は出力、data(dict)は人工入力。
    返り値: None。不整合があればAssertionError。
    """
    held = {}
    cash = 0.
    for row in orders:
        fill,decision,parent,side,qty,price,reason,new,uid,fee = row
        fill,decision,qty,uid,parent = map(int,(fill,decision,qty,uid,parent))
        after = np.flatnonzero(data['good'] & (np.arange(len(data['times']))>decision)
                              & (data['times']>=data['times'][decision]+data['delay']))
        assert len(after) and fill==after[0], (fill,decision,after[:1])
        assert fee==qty*data['fee']//10
        assert price==(data['ask'][fill] if side>0 else data['bid'][fill])
        key = (parent,uid)
        held[key] = held.get(key,0)+(qty if new else -qty)
        assert held[key]>=0 and sum(held.values())<=data['maximum']
        cash -= side*qty*price*data['multiplier']+fee
    assert all(q==0 for q in held.values())
    np.testing.assert_allclose(equity[-1],cash,atol=1e-8,rtol=0.)


class PartialProperties(unittest.TestCase):
    """実市場の利益検証をせず、新状態と旧仕様の同値を検査する。"""

    def test_old_exact(self):
        """
        機能: 半減を無効にした場合に旧版の全注文と時価が完全一致することを検査する。
        引数: self(PartialProperties)は検査状態。
        返り値: None。
        """
        for guard in (0,1,2):
            for addition in (False,True):
                for qty in (1,2,3,5):
                    d = fixture(qty,5,addition)
                    d['exit_guard'] = guard
                    old = previous.simulate(**d)
                    new = revised.simulate(**d,partial_exit=False)
                    self.assertGreater(len(old[0]),0)
                    for x,y in zip(old,new):
                        np.testing.assert_array_equal(x,y)

    def test_half_and_once(self):
        """
        機能: 1枚は維持、2～5枚は一度だけ切捨て半減し残玉を元停止で返済する。
        引数: self(PartialProperties)は検査状態。
        返り値: None。
        """
        for qty in (1,2,3,4,5):
            d = fixture(qty,qty,False)
            orders,equity = revised.simulate(**d,partial_exit=True)
            half = orders[orders[:,6]==1415]
            self.assertEqual(int(half[:,4].sum()),qty//2 if qty>=2 else 0)
            self.assertLessEqual(len(set(half[:,0])),1)
            remaining = orders[(orders[:,7]==0)&(orders[:,6]!=1415)]
            self.assertEqual(int(remaining[:,4].sum()),qty-qty//2 if qty>=2 else 1)
            self.assertTrue(np.all(remaining[:,6]==32))
            audit(orders,equity,d)

    def test_latest_first_and_no_add(self):
        """
        機能: 追加3枚の後に最新2玉を半減し、再順行しても追撃せず残玉を返済する。
        引数: self(PartialProperties)は検査状態。
        返り値: None。
        """
        d = fixture()
        orders,equity = revised.simulate(**d,partial_exit=True)
        new = orders[orders[:,7]==1]
        self.assertEqual(list(new[:,8]),[0.,1.,2.,3.])
        half = orders[orders[:,6]==1415]
        self.assertEqual(list(half[:,8]),[3.,2.])
        self.assertEqual(list(half[:,4]),[1.,1.])
        self.assertFalse(np.any((orders[:,7]==1)&(orders[:,0]>half[0,0])))
        full = orders[(orders[:,7]==0)&(orders[:,6]!=1415)]
        self.assertEqual(list(full[:,8]),[0.,1.])
        self.assertEqual(list(full[:,4]),[2.,1.])
        audit(orders,equity,d)

    def test_trail_and_terminal(self):
        """
        機能: 半減後も初回建値基準の追尾を保持し、場末では残玉を必ず返済する。
        引数: self(PartialProperties)は検査状態。
        返り値: None。
        """
        for terminal in (False,True):
            d = fixture(4,4,False)
            d['activation'] = 2.
            if terminal:
                d['bid'][80:],d['ask'][80:] = 102.5,103.5
            else:
                d['bid'][40:80],d['ask'][40:80] = 129.5,130.5
                d['bid'][80:],d['ask'][80:] = 119.5,120.5
            orders,equity = revised.simulate(**d,partial_exit=True)
            self.assertEqual(int(orders[orders[:,6]==1415,4].sum()),2)
            rest = orders[(orders[:,7]==0)&(orders[:,6]!=1415)]
            self.assertTrue(np.all(rest[:,6]==(93 if terminal else 70)))
            audit(orders,equity,d)

    def test_invalid_gap_and_next_quote(self):
        """
        機能: 無効板で逆行持続を取り消し、発注後は次正常板まで半減約定を待つ。
        引数: self(PartialProperties)は検査状態。
        返り値: None。
        """
        d = fixture(4,4,False)
        d['good'][26] = False
        d['good'][31:34] = False
        orders,equity = revised.simulate(**d,partial_exit=True)
        half = orders[orders[:,6]==1415]
        self.assertEqual(list(half[0,:2]),[34.,30.])
        audit(orders,equity,d)
        d = fixture(4,4,False)
        d['times'][26:] += 20.
        orders,equity = revised.simulate(**d,partial_exit=True)
        half = orders[orders[:,6]==1415]
        self.assertEqual(list(half[0,:2]),[30.,29.])
        audit(orders,equity,d)

    def test_mirror_future_and_stop_priority(self):
        """
        機能: 上下対称・未来変更以前の同値・停止条件の優先を確認する。
        引数: self(PartialProperties)は検査状態。
        返り値: None。
        """
        d = fixture()
        orders,equity = revised.simulate(**d,partial_exit=True)
        m = {k:v.copy() if isinstance(v,np.ndarray) else v for k,v in d.items()}
        m['bid'],m['ask'] = 300.-d['ask'],300.-d['bid']
        m['a'][:,0],m['a'][:,1] = 300.-d['a'][:,1],300.-d['a'][:,0]
        for col in (5,6,7,10,17,19):
            m['a'][:,col] = 300.-d['a'][:,col]
        m['a'][:,[3,4,12,13,14,15,20,21,24,25,26,27]] *= -1.
        reflected,me = revised.simulate(**m,partial_exit=True)
        np.testing.assert_array_equal(orders[:,[0,1,2,4,6,7,8,9]],reflected[:,[0,1,2,4,6,7,8,9]])
        np.testing.assert_array_equal(orders[:,3],-reflected[:,3])
        np.testing.assert_allclose(orders[:,5],300.-reflected[:,5])
        np.testing.assert_allclose(equity,me,atol=1e-8,rtol=0.)
        changed = {k:v.copy() if isinstance(v,np.ndarray) else v for k,v in d.items()}
        changed['bid'][60:],changed['ask'][60:] = 200.,201.
        changed['a'][60:] = np.nan
        future,_ = revised.simulate(**changed,partial_exit=True)
        np.testing.assert_array_equal(orders[orders[:,0]<60],future[future[:,0]<60])
        d = fixture(4,4,False)
        d['bid'][27:],d['ask'][27:] = 89.5,90.5
        stopped,se = revised.simulate(**d,partial_exit=True)
        self.assertFalse(np.any(stopped[:,6]==1415))
        self.assertEqual(int(stopped[stopped[:,6]==32,4].sum()),4)
        audit(stopped,se,d)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PartialProperties)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    record = {'対象':'active141_v3.py','実データ金融再生':False,
              '人工試験数':result.testsRun,'失敗数':len(result.failures),'例外数':len(result.errors),
              '合格':result.wasSuccessful(),'旧版同値の組数':24}
    Path(__file__).with_name('部分返済の独立人工検査141.json').write_text(
        json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
