"""価格特性の四分類を未来抜きの逐次期待と合成だけで照合する。"""

from fractions import Fraction
import hashlib
import json
from pathlib import Path

import numpy as np

import context_core as subject


HERE=Path(__file__).resolve().parent
CHECKS=0


def oracle(bars: dict,rows: np.ndarray,sides: np.ndarray) -> dict:
    """
    機能: listの過去だけを読み、独立Fraction算術で四分類と因果方向を求める。
    引数: bars(dict)、rows/sides(ndarray) は合成素材。
    返り値: dict は実装と同型の分類。未来ラベルは参照しない。
    """
    k=len(rows);classes=np.full((k,4),-1,np.int8);values=np.full((k,4),np.nan)
    ds=np.zeros(k,np.int8);dt=np.zeros(k,np.int8);ks=np.zeros(k,bool);kt=np.zeros(k,bool)
    for i,(t,d) in enumerate(zip(rows,sides)):
        for ci,w,threshold in ((0,20,10),(1,60,20)):
            points=list(range(int(t)-w+1,int(t)+1))
            if points[0]>=0 and all(bool(bars['valid'][j]) for j in points):
                width=max(Fraction(float(bars['high'][j])) for j in points)-min(Fraction(float(bars['low'][j])) for j in points)
                values[i,ci]=float(width);classes[i,ci]=int(width>=threshold)
        if t>=20 and all(bool(bars['valid'][j]) for j in range(t-20,t+1)):
            delta=Fraction(float(bars['close'][t]))-Fraction(float(bars['close'][t-20]))
            values[i,2]=float(int(d)*delta);classes[i,2]=int(int(d)*delta>=Fraction(5,2))
            kt[i]=True;dt[i]=int(delta>0)-int(delta<0)
        opening=next((Fraction(float(bars['open'][j])) for j in range(t+1) if bars['valid'][j]),None)
        if bars['valid'][t] and opening is not None and np.isfinite(bars['anchor'][t]) and bars['anchor'][t]>0:
            delta=Fraction(float(bars['anchor'][t]))-opening
            values[i,3]=float(int(d)*delta);classes[i,3]=int(int(d)*delta>=Fraction(5,2))
            ks[i]=True;ds[i]=int(delta>0)-int(delta<0)
    return dict(classes=classes,values=values,control_start=ds,control_twenty=dt,start_known=ks,twenty_known=kt)


def same(a: dict,b: dict) -> None:
    """
    機能: 分類の値・dtype・未知を逐項照合する。
    引数: a/b(dict[str,ndarray])。
    返り値: None。
    """
    global CHECKS
    assert set(a)==set(b)
    for name in a:
        assert a[name].shape==b[name].shape and a[name].dtype==b[name].dtype
        np.testing.assert_allclose(a[name],b[name],rtol=0,atol=0,equal_nan=True)
        CHECKS+=a[name].size


def fixture(n: int=90) -> dict:
    """
    機能: 欠測のない単調価格の合成足を作る。
    引数: n(int) は足数。
    返り値: dict は実データと無関係の七列。
    """
    close=100.+np.arange(n)/8
    return dict(t_s=np.arange(n,dtype=float)*60,valid=np.ones(n,bool),open=close.copy(),
        high=close+.5,low=close-.5,close=close.copy(),anchor=close+.25)


def main() -> None:
    """
    機能: 窓端・閾値・欠足・方向鏡映・接頭・ゼロ対照を検査して保存する。
    引数: なし。
    返り値: None。prepared等の実本文は読まない。
    """
    global CHECKS
    before={n:hashlib.sha256((HERE/n).read_bytes()).hexdigest() for n in ('context_core.py','artificial_context.py')}
    generator=np.random.default_rng(1184)
    for case in range(16):
        b=fixture();b['valid'][generator.choice(90,3,replace=False)]=False
        rows=np.arange(90,dtype=np.int64);sides=generator.choice(np.array([-1,1],np.int8),90)
        result=subject.classify(b,rows,sides);same(result,oracle(b,rows,sides))
        mirror={name:value.copy() for name,value in b.items()}
        for name in ('open','close','anchor'):mirror[name]=1000.-b[name]
        mirror['high']=1000.-b['low'];mirror['low']=1000.-b['high']
        reversed_result=subject.classify(mirror,rows,-sides)
        same({name:result[name] for name in ('classes','values','start_known','twenty_known')},
            {name:reversed_result[name] for name in ('classes','values','start_known','twenty_known')})
        np.testing.assert_array_equal(result['control_start'],-reversed_result['control_start'])
        np.testing.assert_array_equal(result['control_twenty'],-reversed_result['control_twenty'])
        for end in (1,19,20,21,59,60,61,90):
            prefix={name:value[:end] for name,value in b.items()}
            got=subject.classify(prefix,rows[:end],sides[:end]);wanted={name:value[:end] for name,value in result.items()}
            same(got,wanted)
    b=fixture(61);b['high'][:]=100.;b['low'][:]=100.;b['open'][:]=100.;b['close'][:]=100.;b['anchor'][:]=100.
    b['high'][19]=110.;b['high'][59]=120.
    rows=np.array([19,59],np.int64);sides=np.array([1,1],np.int8)
    r=subject.classify(b,rows,sides);assert r['classes'][0,0]==r['classes'][1,1]==1
    assert r['control_start'].tolist()==[0,0] and r['start_known'].all()
    assert r['control_twenty'][1]==0 and r['twenty_known'][1]
    b=fixture();b['valid'][0]=False
    r=subject.classify(b,np.array([20,59],np.int64),np.array([1,1],np.int8))
    assert r['classes'][0,0]!=-1 and r['classes'][0,2]==-1 and r['classes'][1,1]==-1
    b=fixture();b['valid'][10]=False
    r=subject.classify(b,np.array([70],np.int64),np.array([1],np.int8))
    assert r['start_known'][0] and r['values'][0,3]==b['anchor'][70]-100.
    b=fixture();b['anchor'][20]=102.5
    r=subject.classify(b,np.array([20],np.int64),np.array([1],np.int8))
    assert r['classes'][0,2]==r['classes'][0,3]==1 and r['values'][0,2]==r['values'][0,3]==2.5
    n=subject.count(np.array([1,-1,0,2,-2],np.int8))
    assert n['n']==5 and n['resolved']==2 and n['全候補順先率']==.2 and n['解決内順先率']==.5
    assert subject.count(np.empty(0,np.int8))['全候補順先率'] is None
    CHECKS+=12
    assert before=={n:hashlib.sha256((HERE/n).read_bytes()).hexdigest() for n in before}
    p=HERE/'四分類と窓境界及び因果二方向の純人工.json';assert not p.exists()
    value=dict(全合格=True,source_SHA256=before,比較項目=CHECKS,合成系列=16,接頭=128,
        窓='A t−19..t、B t−59..t、C t−20..tの全valid。D最初valid openを保持。',
        実prepared=0,元raw=0,元測定結果=0,金融=0,API=0)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,比較項目=CHECKS,SHA256=hashlib.sha256(p.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':main()
