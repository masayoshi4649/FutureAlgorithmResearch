"""実測と同じプロセスで、通常実行と高速実行の建玉保存を先に照合する。"""

import hashlib
from pathlib import Path

import numpy as np

import engine120e as E


def verify() -> dict:
    """
    機能: 元の反例とカバー維持の三管理を、市場読取前にPythonとJITで突き合わせる。
    引数: なし。乱数seed固定の完全人工50行のみ使用する。
    返り値: dictは合格と比較数。違いが一つでもあれば金融開始前に停止する。
    """
    rg=np.random.default_rng(20261017)
    x=(65000+np.cumsum(rg.integers(-4,5,50))*10).astype(float)
    rows=np.arange(50,dtype=np.int64)
    times=np.arange(50,dtype=float)
    counts=[]
    for cap in (2,20):
        for mode in range(3):
            args=(rows,times,x,x-10,x+10,cap,10.,11.,10.,.000125,mode,1.,0.,40.,45.,51.)
            fast=E.replay(*args)
            plain=E.replay.py_func(*args)
            assert all(np.array_equal(a,b,equal_nan=True) for a,b in zip(fast,plain)),(cap,mode)
            o,l,c,s=fast
            entry=o[o[:,1]==1]
            closed=o[o[:,1]==2]
            assert len(entry)==s[13] and len(closed)==s[5]
            assert len(entry)==len(closed)+s[8]
            assert len(np.unique(entry[:,0]))==len(entry)
            assert len(np.unique(closed[:,0]))==len(closed)
            assert set(entry[:,0])==set(closed[:,0])  # この人工経路は場末に全返済済み
            assert np.isclose(s[1],s[2]-s[3]) and s[8]==0
            counts.append(dict(cap=cap,mode=mode,entries=int(s[13]),closed=int(s[5]),net=s[0]))
    return dict(passed=True,comparisons=len(counts),cases=counts,original_market_reads=0,
        financial_accounts=0,engine_sha256=hashlib.sha256(Path(E.__file__).read_bytes()).hexdigest(),
        内容='同一プロセスの全三管理・二上限でPython/JIT全配列同値、UIDと費用後現金の保存を確認。')
