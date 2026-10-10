"""実相場の新収支を使わず、出口単体の会計と次行・反射・旧基準を検査する。"""

from copy import deepcopy
import gzip
import hashlib
import importlib
import json
from pathlib import Path
import sys

import numpy as np

import exit_design as design
import engine_exit_campaign as engine

HERE=Path(__file__).resolve().parent


def digest(path: Path) -> str:
    """機能: 検査したファイルの指紋を返す。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(path: int=0, qty: int=5, side: int=1) -> tuple:
    """機能: 部分利確・反落・未到達・元終了後悪化を含む人工価格を作る。

    引数: path/qty/side(int)。返り値: readyと共通初回(tuple[dict,dict])。
    """
    values=[
        [0,0,5,15,20,25,35,45,40,30,15,0,-10,-20],
        [0,0,1,-5,-10,-15,-20,40,50,40,20,0,-10,-20],
        [0,0,15,19,25,19,30,35,19,18,17,15,10,-20],
        [0,0,40,39,38,37,36,35,34,33,32,10,-10,-20],
    ][path]
    p=1000+side*np.array(values,float);n=len(p)
    ready=dict(time_s=np.arange(n,dtype=float)*60,last=p,seq=np.arange(n,dtype=np.int64),tick=1.,limit=660.,session_close=1200.)
    entry=dict(row=1,decision_row=0,side=side,qty=qty,price=1000.,initial_atr=10.,initial_risk=10.*qty,campaign=0)
    return ready,entry


def account(ready: dict, entry: dict, result: dict) -> None:
    """機能: 注文台帳から現金・数量・時価を独立再構成する。

    引数: ready/entry/result(dict)。返り値: なし。一致しなければ例外。
    """
    n=len(ready['last']);cash=np.zeros(n);qty=np.zeros(n);real=np.zeros(n)
    for r in result['orders']:
        i=int(r[0]);assert int(r[1])<i
        cash[i]-=r[3]*r[4]*r[5];qty[i]+=r[3]*r[4]
    for r in result['trades']:
        assert r[10]==r[2]*r[3]*(r[5]-r[4])
        real[int(r[7])]+=r[10]
    cash=np.cumsum(cash);qty=np.cumsum(qty);real=np.cumsum(real)
    eq=cash+qty*ready['last'];curve=result['curve']
    np.testing.assert_allclose(curve[:,0],eq,rtol=0,atol=1e-8)
    np.testing.assert_allclose(curve[:,1],real,rtol=0,atol=1e-8)
    np.testing.assert_allclose(curve[:,5],cash,rtol=0,atol=1e-8)
    np.testing.assert_array_equal(curve[:,6],qty)
    assert np.max(np.abs(qty))<=entry['qty']
    if result['closed']:assert qty[-1]==0 and abs(eq[-1]-real[-1])<1e-8


def legacy_check() -> int:
    """機能: 人工原本だけで旧影の各初回と全返済を再現する。

    引数: なし。返り値: 全経済台帳が一致した人工組数(int)。
    """
    oldpath=HERE.parent/'wave_v38';sys.path.insert(0,str(oldpath))
    old=importlib.import_module('engine_shadow_plan');sys.path.pop(0)
    assert Path(old.__file__).resolve()==(oldpath/'engine_shadow_plan.py').resolve()
    saved=json.loads(gzip.decompress((HERE.parent/'wave_v45/ledgers/A0__V000.json.gz').read_bytes()))
    configs={r['symbol']:r['config'] for r in saved}
    count=0
    for symbol,config in configs.items():
        for side in (-1,1):
            for k in range(4):
                ready,entry=fixture(k,config['initial_qty'],side)
                n=90;t=np.arange(n,dtype=float)*60
                delta=np.tile(np.array([0.,5.,15.,20.,30.,50.,60.,45.,20.,-20.,0.,10.]),8)[:n]
                ready.update(time_s=t,last=1000+side*delta,atr=np.full(n,10.),seq=np.arange(n,dtype=np.int64),
                             start=0.,limit=4800.,session_close=5400.,us_open=1e20)
                ready['last'][:20]=1000
                if k==1:ready['last']=2000-ready['last']
                if k==2:ready['last'][27:]=ready['last'][27]
                if k==3:ready['time_s'][25]=ready['time_s'][24]
                state=np.full(n,side,np.int8)
                r=old.run(ready,state,config,detail=True)
                for cyc in r['cycles']:
                    cid=int(cyc[0]);order=r['orders'][(r['orders'][:,2]==cid)&(r['orders'][:,7]==1)][0]
                    e=dict(row=int(order[0]),decision_row=int(order[1]),side=int(order[3]),qty=int(order[4]),price=float(order[5]),
                           initial_atr=float(cyc[5]),initial_risk=float(cyc[4]),campaign=cid)
                    got=engine.run(ready,e,design.catalog()[0]);account(ready,e,got)
                    want=r['orders'][r['orders'][:,2]==cid]
                    np.testing.assert_array_equal(got['orders'],want)
                    want_t=r['trades'][r['trades'][:,0]==cid].copy();want_t[:,1]=0
                    np.testing.assert_array_equal(got['trades'],want_t)
                    np.testing.assert_array_equal(got['cycles'],cyc[None,:]);count+=1
    return count


def main() -> dict:
    """機能: 13条件の人工・未来不変・反射と必須境界を検査し保存する。

    引数: なし。返り値: 件数と実装指紋(dict)。
    """
    cases=prefix=future=mirror=0
    for spec in design.catalog():
        for path in range(4):
            for qty in (5,10):
                for side in (-1,1):
                    ready,e=fixture(path,qty,side);r=engine.run(ready,e,spec);account(ready,e,r);cases+=1
                    for cut in (5,9):
                        small={k:(v[:cut].copy() if isinstance(v,np.ndarray) else v) for k,v in ready.items()}
                        z=engine.run(small,e,spec,require_complete=False)
                        for key,col in [('orders',0),('trades',7)]:
                            np.testing.assert_array_equal(z[key],r[key][r[key][:,col]<cut])
                        for key in ('curve','plans'):np.testing.assert_array_equal(z[key],r[key][:cut])
                        prefix+=1
                        changed=deepcopy(ready);changed['last'][cut:]=900+np.arange(len(ready['last'])-cut)
                        z=engine.run(changed,e,spec,require_complete=False)
                        for key in ('curve','plans'):np.testing.assert_array_equal(z[key][:cut],r[key][:cut])
                        future+=1
                    m=deepcopy(ready);m['last']=2000-m['last'];me={**e,'side':-side,'price':2000-e['price']}
                    z=engine.run(m,me,spec);account(m,me,z)
                    np.testing.assert_array_equal(z['trades'][:,[3,6,7,9,10]],r['trades'][:,[3,6,7,9,10]])
                    np.testing.assert_allclose(z['curve'][:,0],r['curve'][:,0],rtol=0,atol=1e-8);mirror+=1
    # ----------------------------------------
    # 元方式の終了後を切り捨てず、同秒でも新設線は次行だけで返済する。
    ready,e=fixture(0);base=engine.run(ready,e,design.catalog()[0]);later=engine.run(ready,e,design.catalog()[2])
    assert later['trades'][-1,7]>base['trades'][-1,7]
    ready,e=fixture(3);ready['time_s'][2:5]=120.
    r=engine.run(ready,e,design.catalog()[5]);assert (r['orders'][1:,0]>r['orders'][1:,1]).all()
    shortened={k:(v[:3] if isinstance(v,np.ndarray) else v) for k,v in ready.items()}
    rejected=0
    for args in [(shortened,e,design.catalog()[0]),(ready,{**e,'exit_row':7},design.catalog()[0]),
                 (ready,{**e,'decision_row':e['row']},design.catalog()[0])]:
        try:engine.run(*args)
        except ValueError:rejected+=1
        else:raise AssertionError('不正な打切り又は未来欄を受理')
    same=legacy_check()
    proof=dict(全合格=True,人工条件入力数=cases,prefix検査数=prefix,未来改変検査数=future,売買反射数=mirror,
               旧A0人工組一致数=same,不正拒否数=rejected,新実相場収支計算=False,
               参照資料SHA256={p.name:digest(p) for p in [HERE/'exit_design.py',HERE/'engine_exit_campaign.py',Path(__file__)]})
    (HERE/'check_exit_campaign.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(proof,ensure_ascii=False));return proof


if __name__=='__main__':main()
