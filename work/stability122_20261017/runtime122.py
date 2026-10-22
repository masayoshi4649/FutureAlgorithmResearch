"""途中返済停止・六分窓・全玉代理会計を人工入力で確かめる。"""

import hashlib
from pathlib import Path
import numpy as np
import engine122 as E


def verify() -> dict:
    """
    機能: 追尾停止と通常清算・代理清算のUID及び料金を人工で確認する。
    引数: なし。市場から独立した固定百二十行を用いる。
    返り値: dictは確認件数と指紋。失敗は例外として金融前に止める。
    """
    rng=np.random.default_rng(20261017122)
    p=4000.+np.cumsum(rng.integers(-15,16,120))*.5
    q=dict(row=np.arange(120,dtype=np.int64),time=np.arange(120,dtype=float),last=p,bid=p,ask=p+.5)
    cases=[]
    for cap in (2,10):
        setting=dict(cap=cap,multiplier=1000.,fee=41.8,observed_tick=.5,
            session_start=0.,entry_end=85.,close_time=100.,session_end=130.)
        args=(q['row'],q['time'],q['last'],q['bid'],q['ask'],cap,1000.,41.8,.5,1.,2,
              float('inf'),3.,False,0.,85.,float('inf'),130.)
        fast=E.BASE.replay(*args);plain=E.BASE.replay.py_func(*args)
        assert all(np.array_equal(a,b,equal_nan=True) for a,b in zip(fast,plain))
        early=E.evaluate(q,setting,'EARLY');end=E.evaluate(q,setting,'CLOSE_PROXY')
        assert len(early[0])>0 and len(end[0])>0
        assert np.array_equal(early[0][early[0][:,1]==1],end[0])
        assert not len(end[1]) and np.all(early[1][:,14]==9)
        assert early[3]['unclosed']==end[3]['unclosed']==0
        assert len(end[4])==len(end[0])==end[3]['closed_lots']
        assert all(end[3][k]==early[3][k] for k in ('entries','max_long','max_short'))
        assert end[3]['net']==sum(end[4][:,12])==end[3]['profit']-end[3]['loss']
        cases.append(dict(cap=cap,entries=len(end[0]),early_net=early[3]['net'],proxy_net=end[3]['net']))
    setting.update(session_end=500.)
    missing=E.evaluate(q,setting,'CLOSE_PROXY')
    assert missing[3]['net'] is None and not missing[5]['measured'] and missing[3]['unclosed']>0
    return dict(passed=True,cases=cases,missing_window_rejected=True,financial_accounts=0,
        engine_sha256=hashlib.sha256(Path(E.__file__).read_bytes()).hexdigest(),
        base_engine_sha256=hashlib.sha256(Path(E.BASE.__file__).read_bytes()).hexdigest())
