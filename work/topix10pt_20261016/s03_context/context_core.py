"""S03の既存予兆を四つの当時価格特性で別々に分類する純関数。"""

import numpy as np


CONDITIONS=('A','B','C','D')
STATE_NAMES={1:'true',0:'false',-1:'unknown'}


def classify(bars: dict,rows: np.ndarray,sides: np.ndarray) -> dict:
    """
    機能: 既予兆だけの当時値幅と方向性を、閾値固定の四分類へ写す。
    引数: bars(dict) はt_s/valid/open/high/low/close/anchor、rows(int64[K])、sides(int8[K])。
    返り値: dict はclasses(int8[K,4])、values(float64[K,4])と始値/20分差の対照方向・既知flag。
    採点ラベル・未来価格・損益を使わず、AND条件や最良分類を作らない。
    """
    n=len(bars['valid']);valid=bars['valid']
    assert valid.shape==(n,) and valid.dtype==bool
    for name in ('t_s','open','high','low','close','anchor'):
        assert bars[name].shape==(n,) and bars[name].dtype==np.float64
    assert np.isfinite(bars['t_s']).all() and np.all(np.diff(bars['t_s'])==60)
    assert rows.dtype==np.int64 and sides.dtype==np.int8 and rows.shape==sides.shape
    assert rows.ndim==1 and np.all(rows>=0) and np.all(rows<n) and np.all(rows[1:]>rows[:-1])
    assert np.isin(sides,(-1,1)).all()
    for name in ('open','high','low','close'):
        assert np.isfinite(bars[name][valid]).all() and np.all(bars[name][valid]>0)
    assert np.all(bars['high'][valid]>=bars['low'][valid])
    k=len(rows);classes=np.full((k,4),-1,np.int8);values=np.full((k,4),np.nan)
    control_start=np.zeros(k,np.int8);control_twenty=np.zeros(k,np.int8)
    start_known=np.zeros(k,bool);twenty_known=np.zeros(k,bool)
    first=np.full(n,np.nan);opening=np.nan
    for t in range(n):
        if np.isnan(opening) and valid[t]:opening=bars['open'][t]
        first[t]=opening
    for i,(t,d) in enumerate(zip(rows,sides)):
        for ci,window,threshold in ((0,20,10.),(1,60,20.)):
            left=int(t)-window+1
            if left>=0 and np.all(valid[left:t+1]):
                value=float(np.max(bars['high'][left:t+1])-np.min(bars['low'][left:t+1]))
                values[i,ci]=value;classes[i,ci]=int(value>=threshold)
        if t>=20 and np.all(valid[t-20:t+1]):
            change=bars['close'][t]-bars['close'][t-20]
            values[i,2]=float(d*change);classes[i,2]=int(d*change>=2.5)
            twenty_known[i]=True;control_twenty[i]=int(np.sign(change))
        anchor=bars['anchor'][t]
        if valid[t] and np.isfinite(anchor) and anchor>0 and np.isfinite(first[t]):
            change=anchor-first[t]
            values[i,3]=float(d*change);classes[i,3]=int(d*change>=2.5)
            start_known[i]=True;control_start[i]=int(np.sign(change))
    return dict(classes=classes,values=values,control_start=control_start,control_twenty=control_twenty,
        start_known=start_known,twenty_known=twenty_known)


def count(labels: np.ndarray) -> dict:
    """
    機能: 保存済み先着ラベルの分子分母を再加算する。
    引数: labels(ndarray[int8]) はS03又は同時点因果方向対照の保存ラベル。
    返り値: dict。未決と基準不可は勝敗に入れず、空率はNone。
    """
    assert labels.ndim==1 and labels.dtype==np.int8 and np.isin(labels,(-2,-1,0,1,2)).all()
    names={1:'順先',-1:'逆先',0:'窓末未決',2:'EOF未決',-2:'基準不可'}
    values={name:int(np.count_nonzero(labels==code)) for code,name in names.items()}
    n=len(labels);resolved=values['順先']+values['逆先']
    return dict(**values,n=n,resolved=resolved,全候補順先率=values['順先']/n if n else None,
        解決内順先率=values['順先']/resolved if resolved else None,解決率=resolved/n if n else None)
