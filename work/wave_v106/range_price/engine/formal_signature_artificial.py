"""選択後のwritable資格とcached readonly静観列を含む実接口型を人工比較する。"""

from pathlib import Path

import numpy as np

import artificial
import common

HERE=Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 正式loader/selectionと同じ読書資格の市場/指値をPythonとJITで比較する。
    引数: なし。
    返り値: None。正式金融や入力cacheを開始しない。
    """
    target=HERE/'選択後writable資格とreadonly静観のJIT人工検査.json';assert not target.exists()
    paths=[HERE/n for n in ('core.py','common.py','artificial.py','formal_signature_artificial.py')]+[HERE.parent/'interface.py']
    before={str(p.relative_to(common.ROOT)):common.digest(p) for p in paths};checks=[]
    for symbol in ('TOPIX','NK225'):
        q=5 if symbol=='TOPIX' else 10
        for side in (1,-1):
            for mode in (1,2):
                p,c,cfg=artificial.fixture(symbol,side,2,mode)
                if mode==2:artificial.clearing(p,350,side,c['entry_limit_prices'][330]-side*p['record']['tick'])
                artificial.clearing(p,400,side,c['target_prices'][330])
                common.immutable(p)
                for name in ('execution_to_raw_index','quiet','quiet_start_s'):c[name].flags.writeable=False
                assert c['entry_quality'].flags.writeable and c['entry_reset'].flags.writeable
                python=artificial.play(p,c,cfg,q,python=True);native=artificial.play(p,c,cfg,q,python=False)
                for name in ('orders','trades','growth_cohorts','events','curve','source_curve','target_trace','judgments','control_events','candidate_controls'):
                    np.testing.assert_array_equal(python[name],native[name])
                checks.append(dict(symbol=symbol,side=side,mode=mode,一致=True))
    assert before=={p:common.digest(common.ROOT/p) for p in before}
    common.save(target,dict(全合格=True,人工専用=True,検査数=len(checks),検査=checks,source_SHA256=before,
        開始終端source一致=True,正式input読取=0,新金融再生=0,原板読取=0,API取得=0))
    print('正式selection型JIT人工 '+str(len(checks))+'件',flush=True)


if __name__=='__main__':main()
