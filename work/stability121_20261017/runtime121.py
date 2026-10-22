"""固定した人工経路で通常版と高速版の全配列を実測前に照合する。"""

import hashlib
from pathlib import Path
import numpy as np
import engine121 as E
from catalog121 import specifications


def verify() -> dict:
    """
    機能: 非空の人工往復で全条件のUID・現金・通常高速の一致を確認する。
    引数: なし。市場と無関係な固定乱数百二十行を用いる。
    返り値: dictは合否と件数。未合格なら例外で金融前に止める。
    """
    rng=np.random.default_rng(20261017121)
    prices=(4000.+np.cumsum(rng.integers(-15,16,120))*.5).astype(float)
    rows=np.arange(len(prices),dtype=np.int64)
    times=rows.astype(float)
    cases=[]
    for cap in (2,10):
        for spec in specifications():
            args=(rows,times,prices,prices,prices+.5,cap,1000.,41.8,.5,1.,2,spec['trail'],
                spec['spacing'],spec['reset_after_profit'],0.,100.,110.,120.)
            fast=E.replay(*args)
            plain=E.replay.py_func(*args)
            assert all(np.array_equal(a,b,equal_nan=True) for a,b in zip(fast,plain)),(cap,spec['id'])
            o,l,c,s=fast
            entry=o[o[:,1]==1];exit_=o[o[:,1]==2]
            assert len(entry)>0 and len(entry)==len(exit_)==len(l)
            assert len(set(entry[:,0]))==len(entry) and set(entry[:,0])==set(exit_[:,0])
            assert s[8]==0 and s[9]<=cap and s[10]<=cap
            assert s[0]==s[1]==sum(l[:,13])==s[2]-s[3]
            cases.append(dict(cap=cap,method=spec['id'],entries=len(entry),net=float(s[0])))
    return dict(passed=True,cases=cases,comparisons=len(cases),financial_accounts=0,
        engine_sha256=hashlib.sha256(Path(E.__file__).read_bytes()).hexdigest())
