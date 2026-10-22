"""独立させた初回距離と間隔を、通常版・高速版と旧基準で人工照合する。"""

import hashlib
from pathlib import Path
import numpy as np
import engine123 as E
from catalog123 import specifications


def verify() -> dict:
    """
    機能: 全十九条件の非空新規・全UID・同値実行と代理会計を市場前に確認する。
    引数: なし。固定乱数と正負150ptの人工往復だけを使用する。
    返り値: dictは合格と確認件数。失敗時は金融前に例外で停止する。
    """
    rng=np.random.default_rng(20261017123)
    prices=np.concatenate((4000.+np.arange(81)*2.,4160.-np.arange(81)*2.,
        4000.+np.cumsum(rng.integers(-15,16,120))*.5))
    q=dict(row=np.arange(len(prices),dtype=np.int64),time=np.arange(len(prices),dtype=float),
        last=prices,bid=prices,ask=prices+.5)
    cases=[]
    for spec in specifications():
        # 実装同士の一致だけでなく、先に決めた一段目から十段目の発火線を確認する。
        for side in (1,-1):
            monotone=np.repeat(4000.+side*np.arange(401)*.5,2)
            count=len(monotone)
            fixture=E.BASE.replay(np.arange(count,dtype=np.int64),np.arange(count,dtype=float),
                monotone,monotone,monotone+.5,10,1000.,41.8,.5,1.,spec['initial'],2,
                float('inf'),spec['spacing'],False,0.,850.,float('inf'),900.)
            entry=fixture[0]
            expected=4000.+side*(spec['initial']+np.arange(10)*spec['spacing'])
            assert len(entry)==10 and np.all(entry[:,2]==side),spec['id']
            assert np.array_equal(entry[:,17],expected),(spec['id'],side,entry[:,17],expected)
        config=dict(cap=10,multiplier=1000.,fee=41.8,observed_tick=.5,unit=1.,initial=spec['initial'],mode=2,
            trail=float('inf'),spacing=spec['spacing'],reset_after_profit=False,
            session_start=0.,entry_end=260.,close_time=float('inf'),session_end=320.)
        args=[q[k] for k in ('row','time','last','bid','ask')]
        fast=E.BASE.replay(*args,**config);plain=E.BASE.replay.py_func(*args,**config)
        assert all(np.array_equal(a,b,equal_nan=True) for a,b in zip(fast,plain)),spec['id']
        o,l,c,n=fast
        assert len(o)>0 and not len(l) and np.all(o[:,1]==1)
        assert len(o)==len(set(o[:,0]))==n[13]==n[8] and n[9]<=10 and n[10]<=10
        setting={k:v for k,v in config.items() if k not in ('unit','initial','mode','trail','spacing','reset_after_profit')}
        setting['close_time']=285.
        full=E.evaluate(q,setting,'CLOSE_PROXY',spec['initial'],spec['spacing'])
        assert np.array_equal(full[0],o) and full[3]['unclosed']==0
        assert len(full[4])==len(o) and full[3]['net']==sum(full[4][:,12])
        cases.append(dict(method=spec['id'],entries=len(o),net=full[3]['net']))
    return dict(passed=True,cases=cases,comparisons=len(cases),financial_accounts=0,
        engine_sha256=hashlib.sha256(Path(E.__file__).read_bytes()).hexdigest(),
        core_sha256=hashlib.sha256(Path(E.BASE.__file__).read_bytes()).hexdigest())
