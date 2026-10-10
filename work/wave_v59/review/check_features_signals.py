"""未来値を使わない確定足と入口を、独立した少量人工経路で検査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import features
import signals


def synthetic(seconds: int = 60) -> tuple:
    """機能: 一部の空白足と未完成の最後足を持つ原本代理を作る。

    引数: seconds(int) は足幅。
    返り値: 価格入力・気配・独立集計用の元行一覧(tuple)。
    """
    rows = []
    for bar in range(71):
        if bar in (13,29,30,47):
            continue
        for offset, move in ((1,-1.),(seconds//2,2.),(seconds-1,0.)):
            price = 20000. + 7.*np.sin(bar/2) + bar*.2 + move
            rows.append((bar*seconds+offset,price))
    times,mids = np.array(rows).T
    seq = np.arange(len(times))*2+5
    ready = dict(time_s=times,seq=seq,last=mids+4,start=0.,limit=seconds*72.,
                 tick=1.,session='合成',symbol='同一規則')
    quotes = dict(time_s=times,seq=seq,mid=mids,bid=mids-.5,ask=mids+.5)
    return ready,quotes,rows


def independently_check(ready: dict, quotes: dict, setting: dict, frame: pd.DataFrame) -> int:
    """機能: 公開以前の元行だけから各足と主要指標を再計算する。

    引数: ready/quotes/setting(dict)、frame(pd.DataFrame)。
    返り値: 独立検算した公開行数(int)。
    """
    sec,short,long=setting['seconds'],setting['short'],setting['long']
    times,mids=ready['time_s'],quotes['mid']
    for row in frame.itertuples(index=False):
        i=int(row.ready_index)
        assert row.seq==ready['seq'][i]
        assert i>0 and int(times[i]//sec)>int(times[i-1]//sec)
        latest=int(times[i]//sec)-1
        closes,highs,lows,observed=[],[],[],[]
        source=-1
        for bar in range(latest+1):
            ids=np.flatnonzero((times[:i]>=bar*sec)&(times[:i]<(bar+1)*sec))
            yes=len(ids)>0
            observed.append(yes)
            if yes:
                source=int(ids[-1])
                closes.append(mids[source]);highs.append(max(mids[ids]));lows.append(min(mids[ids]))
            else:
                closes.append(closes[-1]);highs.append(closes[-1]);lows.append(closes[-1])
        assert row.close==closes[-1] and row.source_last_seq==ready['seq'][source]
        assert bool(row.observed)==observed[-1]
        if len(closes)>=long:
            np.testing.assert_allclose(row.sma_long,np.mean(closes[-long:]),rtol=0,atol=1e-9)
            np.testing.assert_allclose(row.sma_short,np.mean(closes[-short:]),rtol=0,atol=1e-9)
            np.testing.assert_allclose(row.std_long,np.std(closes[-long:]),rtol=0,atol=1e-8)
            assert row.observed_count_long==sum(observed[-long:])
        if len(closes)>long:
            assert row.prior_box_high==max(highs[-long-1:-1])
            assert row.prior_box_low==min(lows[-long-1:-1])
            denom=sum(abs(np.diff(closes[-long-1:])))
            expected=abs(closes[-1]-closes[-long-1])/denom if denom else 0.
            np.testing.assert_allclose(row.er,expected,rtol=0,atol=1e-12)
        if not observed[-1] or (len(observed)>1 and not observed[-2]):
            assert not row.can_trade
    return len(frame)


def transform(frame: pd.DataFrame, factor: float) -> pd.DataFrame:
    """機能: 価格の単位だけを変え、同一判定になるか確かめる表を作る。

    引数: frame(pd.DataFrame)、factor(float) は正の倍率。
    返り値: 価格列だけを換算した特徴表(pd.DataFrame)。
    """
    result=frame.copy()
    for column in frame.columns:
        if column in ('close','high','low','bid','ask','mid','last','prior_box_high','prior_box_low',
                      'session_open','session_open_mid','prior_move') or column.startswith(('sma_','std_','gap','close_lag')):
            result[column]=result[column]*factor
    return result


def entry_boundaries() -> int:
    """機能: 交差の等値、補完足、箱品質による見送りを人工表で確認する。

    引数: なし。
    返り値: 合格した人工入口検査数(int)。
    """
    ready,quotes,_=synthetic()
    base=features.build_features(ready,quotes,features.SETTINGS[0]).iloc[[-1]].copy()
    defaults=dict(can_trade=True,ready_index=10,mid=96.,close=96.,close_lag1=94.,
                  sma_short=99.,sma_short_lag1=98.,sma_long=100.,sma_long_lag1=100.,sma_long_lag3=100.,
                  std_long=3.,std_long_lag1=3.,gap=-1.,gap_lag1=-2.,gap_lag2=-2.,
                  prior_box_low=90.,prior_box_high=110.,er=.2,prior_move=-6.,
                  latest_three_observed=True,prior_move_start_observed=True,prior_box_observed_fraction=1.)
    for key,value in defaults.items():
        base[key]=value
    specs=[
        ('M1',dict(gap_lag1=0.,gap=1.),1),
        ('M1',dict(gap_lag1=-1.,gap=0.),0),
        ('M1',dict(gap_lag1=1.,gap=2.),0),
        ('M1',dict(gap_lag1=0.,gap=-1.),-1),
        ('M1',dict(gap_lag1=0.,gap=1.,can_trade=False),0),
        ('M2',dict(gap_lag1=3.,gap_lag2=-3.,gap=4.,sma_short=104.,close=105.),1),
        ('M2',dict(gap_lag1=3.,gap_lag2=-3.,gap=3.,sma_short=104.,close=105.),0),
        ('M2',dict(gap_lag1=3.,gap_lag2=-3.,gap=4.,sma_short=104.,close=105.,latest_three_observed=False),0),
        ('S3',{},1),
        ('S3',dict(prior_move_start_observed=False),0),
        ('S3',dict(prior_box_observed_fraction=.79),0),
        ('S1',dict(close_lag1=92.,close=94.,mid=94.),1),
        ('S1',dict(close_lag1=92.,close=94.,mid=111.01),0),
        ('S2',dict(close_lag1=92.),1),
        ('S2',dict(close_lag1=92.,std_long=0.),0),
        ('A1',dict(close_lag1=92.,close=94.,mid=94.),1),
        ('A1',dict(close_lag1=92.,close=94.,mid=94.,prior_box_observed_fraction=.79,gap_lag1=0.,gap=1.),0),
        ('A1',dict(er=.6,gap_lag1=0.,gap=1.),1),
        ('A1',dict(er=.45,gap_lag1=0.,gap=1.),0),
    ]
    for family,changes,side in specs:
        one=base.copy()
        for key,value in changes.items():
            one[key]=value
        rows=signals.candidates(one,20000.,1.)[family]
        assert len(rows)==(1 if side else 0),(family,changes,rows)
        if side:
            assert rows[0,1]==side
    return len(specs)


def main() -> None:
    """機能: 独立足計算、未来切断、単位変更、銘柄名変更の検査を保存する。

    引数: なし。
    返り値: なし(None)。追加2場と売買結果は開かない。
    """
    bar_checks=prefix_checks=scale_checks=0
    for setting in features.SETTINGS:
        ready,quotes,_=synthetic(setting['seconds'])
        full=features.build_features(ready,quotes,setting)
        bar_checks+=independently_check(ready,quotes,setting,full)
        for size in (1,38,len(ready['seq'])//2,len(ready['seq'])-1):
            part,partq=features.cut_inputs(ready,quotes,size)
            actual=features.build_features(part,partq,setting)
            pd.testing.assert_frame_equal(actual,full[full.ready_index<size].reset_index(drop=True),check_exact=True)
            mutated={k:v.copy() for k,v in quotes.items()}
            for k in ('mid','bid','ask'):
                mutated[k][size:]+=999.
            changed=features.build_features(ready,mutated,setting)
            pd.testing.assert_frame_equal(actual,changed[changed.ready_index<size].reset_index(drop=True),check_exact=True)
            prefix_checks+=1
        renamed=dict(ready,symbol='変更した銘柄名',session='別の場名')
        pd.testing.assert_frame_equal(full,features.build_features(renamed,quotes,setting),check_exact=True)
    # ----------------------------------------
    # 旧23場だけの全特徴で倍率変更。結果一覧や新2場のファイルは読まない。
    data=pickle.loads((HERE.parent/'features.pkl').read_bytes())
    quotes=pickle.loads((HERE.parent/'quotes.pkl').read_bytes())
    ready=pickle.loads((HERE.parent/'inputs.pkl').read_bytes())
    assert len(data)==46
    for key,settings in data.items():
        for setting_id,frame in settings.items():
            opening=float(quotes[key]['mid'][0]);tick=float(ready[key]['tick'])
            original=signals.candidates(frame,opening,tick)
            scaled=signals.candidates(transform(frame,2.),opening*2.,tick*2.)
            for family in signals.FAMILIES:
                expected=original[family].copy()
                expected[:,2:5]*=2.
                np.testing.assert_allclose(scaled[family],expected,rtol=0,atol=1e-9,equal_nan=True)
                scale_checks+=1
    boundaries=entry_boundaries()
    evidence={'合格':True,'独立確定足検算行数':bar_checks,'人工経路切断と未来改変':prefix_checks,
              '交差と品質境界の人工入口検査':boundaries,
              '銘柄名変更':4,'価格単位変更比較数':scale_checks,'旧口座数':46,
              '追加2場読取':False,'売買結果参照':False,
              'ソースSHA256':{name:hashlib.sha256((HERE.parent/name).read_bytes()).hexdigest()
                              for name in ('features.py','signals.py')}}
    (HERE/'特徴と入口の独立監査.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False))


if __name__=='__main__':
    main()
