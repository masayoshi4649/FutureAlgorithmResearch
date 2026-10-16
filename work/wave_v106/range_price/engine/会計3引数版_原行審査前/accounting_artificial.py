"""待機指値を市場の初quoteへ誤分類しない会計人工。"""

from pathlib import Path

import numpy as np

import artificial
import common
import accounting

HERE=Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 商品/買売/C/R/市場指値の完結会計と、指値遅延の不正例を検算する。
    引数: なし。
    返り値: None。正式金融や原本を再生しない。
    """
    target=HERE/'市場と初指値到達及び全行会計の人工検査.json';assert not target.exists()
    paths=[HERE/n for n in ('accounting.py','accounting_artificial.py','artificial.py','core.py')]+[HERE.parent/'interface.py']
    paths+=[common.ROOT/'work/wave_v102/accounting.py']
    before={str(p.relative_to(common.ROOT)):common.digest(p) for p in paths};checks={}
    for symbol in ('TOPIX','NK225'):
        q=5 if symbol=='TOPIX' else 10
        for side in (1,-1):
            for family,mode in ((1,1),(2,1),(2,2)):
                p,c,cfg=artificial.fixture(symbol,side,family,mode)
                if family==2:
                    if mode==2:artificial.clearing(p,350,side,c['entry_limit_prices'][330]-side*p['record']['tick'])
                    artificial.clearing(p,400,side,c['target_prices'][330])
                out=artificial.play(p,c,cfg,q);row=accounting.inspect(('人工',symbol),p['record'],out)
                assert abs(row['net']-out['trades'][:,11].sum())<1e-5 and row['独立全行会計検算']
                label='C市場全行会計' if family==1 else 'R市場全行会計' if mode==1 else 'R初指値到達全行会計'
                checks[label]=checks.get(label,0)+1
                if family==2 and mode==2:
                    order=out['orders'][0];normal=np.flatnonzero(accounting.quote_valid(p['record']))
                    assert accounting.first_fill(p['record'],order,normal)==350 and order[0]==350 and normal[np.searchsorted(normal,330,side='right')]==331
                    wrong=order.copy();wrong[0]=351
                    assert accounting.first_fill(p['record'],wrong,normal)!=wrong[0]
                    checks['初normalと初reachを分離し遅れた架空fillを拒否']=checks.get('初normalと初reachを分離し遅れた架空fillを拒否',0)+1
    assert before=={p:common.digest(common.ROOT/p) for p in before}
    common.save(target,dict(全合格=True,人工専用=True,検査件数=checks,source_SHA256=before,開始終端source一致=True,
        正式input読取=0,新金融再生=0,原板読取=0,API取得=0))
    print('R指値専用会計人工 '+str(sum(checks.values()))+'件',flush=True)


if __name__=='__main__':main()
