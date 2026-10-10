"""中期の確定足と入口を、人工原本から独立計算して検査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


HERE=Path(__file__).resolve().parent
MEDIUM=HERE.parent/'medium'
sys.path.insert(0,str(MEDIUM))
import features
import signals


def fixture() -> tuple:
    """機能: 空白・同時計・終値と異なる足高安を持つ人工原本を作る。

    引数: なし。
    返り値: 入力と気配(tuple[dict,dict])。
    """
    rows=[]
    for b in range(80):
        if b in (14,32,33,49):
            continue
        p=20000+30*np.sin(b/3)+b*.5
        rows.extend([(b*300+1,p-2),(b*300+150,p+5),(b*300+299,p)])
    t,m=np.array(rows).T
    seq=np.arange(len(m),dtype=int)*3+7
    return (dict(seq=seq,time_s=t,start=0.,limit=24000.,tick=1.,symbol='試験',session='人工'),
            dict(seq=seq.copy(),time_s=t.copy(),mid=m,bid=m-.5,ask=m+.5))


def independent(ready: dict,quotes: dict,setting: dict,frame: pd.DataFrame) -> int:
    """機能: 公開以前だけを走査し、終値・平均・分散・過去高安を再計算する。

    引数: ready/quotes/setting(dict)、frame(pd.DataFrame)。
    返り値: 検査した公開行数(int)。
    """
    t,m=ready['time_s'],quotes['mid'];long=setting['long'];short=setting['short']
    for row in frame.itertuples(index=False):
        i=int(row.i);last=int(t[i]//300)-1;c=[];hi=[];lo=[];obs=[]
        assert row.seq==ready['seq'][i] and int(t[i]//300)>int(t[i-1]//300)
        for b in range(last+1):
            ids=np.flatnonzero((t[:i]>=b*300)&(t[:i]<(b+1)*300));obs.append(len(ids)>0)
            if len(ids):
                c.append(m[ids[-1]]);hi.append(max(m[ids]));lo.append(min(m[ids]))
            else:
                c.append(c[-1]);hi.append(c[-1]);lo.append(c[-1])
        assert row.close==c[-1] and row.observed==obs[-1]
        if len(c)>=long:
            np.testing.assert_allclose([row.short,row.long,row.std],[np.mean(c[-short:]),np.mean(c[-long:]),np.std(c[-long:])],rtol=0,atol=1e-8)
            assert row.observed_fraction==sum(obs[-long:])/long
        if len(c)>long:
            assert row.prior_high==max(hi[-long-1:-1]) and row.prior_low==min(lo[-long-1:-1])
            travel=sum(abs(np.diff(c[-long-1:])));er=abs(c[-1]-c[-long-1])/travel if travel else 0.
            np.testing.assert_allclose(row.er,er,rtol=0,atol=1e-12)
        if not obs[-1] or (len(obs)>1 and not obs[-2]):
            assert not row.can_trade
    return len(frame)


def main() -> None:
    """機能: 確定足独立計算・未来不変・単位倍率の証跡を保存する。

    引数: なし。
    返り値: なし(None)。実相場の損益は読まない。
    """
    ready,quotes=fixture();count=prefix=unit=0
    for setting in features.SETTINGS:
        full=features.build(ready,quotes,setting);count+=independent(ready,quotes,setting,full)
        for size in (1,40,100,len(ready['seq'])-1):
            part={k:(v[:size] if isinstance(v,np.ndarray) else v) for k,v in ready.items()}
            partq={k:v[:size] for k,v in quotes.items()}
            expected=full[full.i<size].reset_index(drop=True)
            pd.testing.assert_frame_equal(features.build(part,partq,setting),expected,check_exact=True)
            future={k:v.copy() for k,v in quotes.items()}
            for name in ('mid','bid','ask'):
                future[name][size:]+=5000
            after=features.build(ready,future,setting)
            pd.testing.assert_frame_equal(after[after.i<size].reset_index(drop=True),expected,check_exact=True)
            prefix+=1
        scaled=full.copy()
        for name in full.columns:
            if name in ('close','high','low','short','long','std','gap','prior_high','prior_low','mid') or name.startswith(('close_lag','short_lag','long_lag','std_lag','gap_lag')):
                scaled[name]*=2.
        for fraction in (.001,.002):
            original=signals.candidates(full,quotes['mid'][0],1.,fraction)
            changed=signals.candidates(scaled,quotes['mid'][0]*2,2.,fraction)
            for family,rows in original.items():
                expected=rows.copy();expected[:,2]*=2.
                np.testing.assert_array_equal(changed[family],expected);unit+=1
    assert len(signals.methods())==120 and sum(x['primary'] for x in signals.methods())==5
    evidence=dict(合格=True,独立確定足計算=count,切断と未来改変比較=prefix,価格単位変更比較=unit,
                  条件数=120,主条件数=5,損益参照=False,
                  コードSHA256={name:hashlib.sha256((MEDIUM/name).read_bytes()).hexdigest() for name in ('features.py','signals.py')})
    (HERE/'中期特徴の独立合成監査.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False))


if __name__=='__main__':
    main()
