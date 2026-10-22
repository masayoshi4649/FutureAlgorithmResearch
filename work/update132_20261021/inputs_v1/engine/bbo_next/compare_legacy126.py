"""追加部品が介入しない人工経路で旧次行約定核との一致を確認する。"""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np

import bbo_order_kernel126
import core126

sys.modules['order_kernel'] = bbo_order_kernel126
import source_engine


HERE = Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 固定乱数の人工気配を新旧核へ同入力で渡し、実注文・現金・時価を照合する。
    引数: なし。
    返り値: None。実市場と原版金融を使わない開発者照合JSONを保存する。
    """
    rng = np.random.default_rng(126106)
    checks = []
    oldrun = getattr(source_engine.simulate,'py_func',source_engine.simulate)
    newrun = getattr(core126.simulate,'py_func',core126.simulate)
    for quantity in (5,10):
        for side in (1,-1):
            for seed in range(25):
                n = 20
                time = np.arange(n,dtype=float)*301.
                last = 100.+np.cumsum(rng.choice(np.array([-1.,0.,1.]),size=n))
                bid = last-.5; ask = last+.5
                good = rng.random(n) > .25
                good[0] = good[-1] = True
                feed = np.array([[1,0,0,side,quantity,last[1],20.,1.,0.,1000.],
                    [5,4,0,-side,quantity//2,last[5],7.,0.,0.,0.],
                    [10,9,0,-side,quantity-quantity//2,last[10],9.,0.,0.,0.]],float)
                quiet = np.zeros(n,dtype=bool)
                old = oldrun(time,last,bid,ask,good,feed,quiet,quiet,time[-1]+1000.,quantity*2,1.,0.,True)
                market = np.full((n,12),np.nan); market[:,11] = 0.
                new = newrun(time,last,bid,ask,good,feed,time[-1]+1000.,quantity*2,market,np.array([0.,.5,0.,0.]))
                np.testing.assert_array_equal(old[0][:,:6],new[0][:,:6])
                for columns in (list(range(9)),[10]):
                    np.testing.assert_array_equal(old[1][:,columns],new[1][:,columns])
                np.testing.assert_array_equal(old[2],new[2])
                np.testing.assert_array_equal(old[3],new[3])
                np.testing.assert_array_equal(old[4][:,:9],new[4][:,:9])
                np.testing.assert_array_equal(old[5],new[5])
                checks.append(dict(quantity=quantity,side=side,seed=seed,passed=True))
    proof = dict(passed=True,count=len(checks),checks=checks,market_reads=0,financial_runs=0,
        scope='開発者による非介入時の旧次行約定核照合。元返済理由名91を原理由へ保持する列だけ比較対象外。',
        source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (HERE/'core126.py',HERE/'source_engine.py',HERE/'bbo_order_kernel126.py',Path(__file__))})
    target = HERE/'旧次行核と非介入人工百経路の同値.json'
    assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,count=len(checks),market_reads=0,financial_runs=0),ensure_ascii=False))


if __name__ == '__main__':
    main()
