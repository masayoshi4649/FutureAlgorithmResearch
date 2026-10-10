"""実相場を読まず、二つの時計と相手公開の因果性を人工経路で検算する。"""

from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path

import numpy as np

import price_clock as target

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def ready(price: list|np.ndarray, times: list|np.ndarray|None = None,
          atr: list|np.ndarray|None = None) -> dict:
    """機能: 原本順と同秒更新を持てる人工入力を作る。

    引数: price/times/atr(list|ndarray|None)。返り値: 入力辞書(dict)。
    """
    price=np.asarray(price,dtype=float);n=len(price)
    return dict(last=price,time_s=np.arange(n,dtype=float)*10 if times is None else np.asarray(times,float),
        atr=np.full(n,2.) if atr is None else np.asarray(atr,float),seq=np.arange(n,dtype=np.int64)*3,
        tick=.01,start=0.)


def prefix(source: dict, count: int) -> dict:
    """機能: 人工原本を同じ行境界で切断する。

    引数: source(dict)、count(int)。返り値: 切断入力(dict)。
    """
    return {k:v[:count].copy() if isinstance(v,np.ndarray) else v for k,v in source.items()}


def equal(left: dict, right: dict, count: int|None = None) -> None:
    """機能: 特徴・品質・全参照行を省略せず厳密比較する。

    引数: left/right(dict)、count(int|None)。返り値: なし(None)。
    """
    assert set(left)==set(right)
    for key,value in left.items():np.testing.assert_array_equal(value[:count],right[key],err_msg=key)


def main() -> None:
    """機能: 人工式・切断・未来改変・反射・公開順を検査し、未採択証拠を保存する。

    引数: なし。返り値: なし(None)。保存原本と売買結果を読まない。
    """
    configs=[replace(target.candidate(s),warmup_seconds=0.,warmup_distance=0.,
                     maximum_slope_age_seconds=10000.) for s in (.5,1.,2.,4.)]
    sample=np.arange(75,dtype=float)
    paths=[ready(100+sample*.12),ready(120-sample*.12),ready(np.round(100+np.sin(sample)*2,2)),
           ready(np.full(75,100.)),ready(np.r_[np.full(20,100.),np.full(55,160.)]),
           ready(100+sample*.1,times=np.floor(sample/3)*10),
           ready(100+sample*.1,atr=np.r_[np.full(4,np.nan),np.full(20,2.),np.nan,np.full(50,4.)]),
           ready(np.r_[np.full(20,100.),np.nan,np.arange(54)*.1+101.]),
           ready(100+sample*.1,times=np.r_[sample[:30]*10,sample[30:]*10+120])]
    counts=dict(先頭切断=0,未来変更=0,上下反射=0,公開切断=0,公開未来=0,相手過去参照=0)
    for case in paths:
        original={k:v.copy() if isinstance(v,np.ndarray) else v for k,v in case.items()}
        for config in configs:
            for clock in ('distance','physical'):
                for slope in ('native','physical'):
                    base=target.model(case,config,clock=clock,slope_clock=slope)
                    for cut in (2,11,24,39,60):
                        cut_result=target.model(prefix(case,cut),config,clock=clock,slope_clock=slope)
                        equal(base,cut_result,cut);counts['先頭切断']+=1
                        changed=prefix(case,len(case['last']))
                        changed['last'][cut:]=1500.-changed['last'][cut:]
                        changed['atr'][cut:]*=7.;changed['seq'][cut:]+=100
                        future=target.model(changed,config,clock=clock,slope_clock=slope)
                        equal(base,{k:v[:cut] for k,v in future.items()},cut);counts['未来変更']+=1
                        before=target.completed_groups(case,base)
                        stopped=target.completed_groups(prefix(case,cut),cut_result)
                        keep=before['release_row']<cut
                        equal({k:v[keep] for k,v in before.items()},stopped);counts['公開切断']+=1
                        after=target.completed_groups(changed,future)
                        equal({k:v[keep] for k,v in before.items()},{k:v[after['release_row']<cut] for k,v in after.items()})
                        counts['公開未来']+=1
                    flipped=prefix(case,len(case['last']));flipped['last']=1000.-flipped['last']
                    reflected=target.model(flipped,config,clock=clock,slope_clock=slope)
                    for name,value in base.items():
                        expected=1000.-value if name in ('fast','slow') else -value if name in ('gap','slope','direction','fast_offset','slow_offset') else value
                        np.testing.assert_allclose(reflected[name],expected,rtol=0,atol=1e-10,equal_nan=True,err_msg=name)
                    counts['上下反射']+=1
        for k,v in original.items():np.testing.assert_array_equal(case[k],v)
    # ----------------------------------------
    # 直前ATR、初期化、同秒順を手計算式と照合する。
    simple=ready([100,100,104,104,106],times=[0,1,1,2,3],atr=[2,2,100,2,2])
    result=target.model(simple,configs[1]);assert not result['valid'][0] and result['valid'][1]
    assert result['used_atr'][2]==2 and result['used_atr'][3]==100
    assert result['u'][1]==0 and result['u'][2]==2 and result['u'][3]==2 and result['u'][4]==3
    np.testing.assert_allclose(result['fast'][2],100+(1-math.exp(-2))*4,rtol=0,atol=1e-13)
    np.testing.assert_allclose(result['slow'][2],100+(1-math.exp(-.5))*4,rtol=0,atol=1e-13)
    assert result['fast'][3]==result['fast'][2]
    physical=target.model(simple,configs[1],clock='physical')
    assert physical['fast'][2]==100 and physical['u'][2]==2
    # ----------------------------------------
    # 未来ATRによる遡及補完、欠測の跨ぎ、観測穴の価格飛びを拒否する。
    missing=target.model(ready([100,101,102,103,104,105],atr=[np.nan,2,2,np.nan,2,2]),configs[1])
    np.testing.assert_array_equal(missing['valid'],[False,False,True,False,False,True])
    assert missing['u'][2]==missing['u'][5]==0
    hole=target.model(ready([100,100,102,140,142],times=[0,1,2,100,101]),configs[1])
    assert hole['u'][3]==0 and hole['fast'][3]==140 and hole['u'][4]==1
    # ----------------------------------------
    # 規定速度の人工入力だけでは係数と平均が一致する。速度推定は実施しない。
    times=np.arange(60,dtype=float)*10
    prices=100+2*times/100.
    both=target.compare(ready(prices,times),replace(configs[1],tau_unit=100.))
    for key in ('fast','slow','gap','seed_weight_slow'):
        np.testing.assert_allclose(both['distance'][key],both['physical'][key],rtol=0,atol=1e-11,equal_nan=True)
    # ----------------------------------------
    # 同時刻群末尾を次異時刻まで公開しない。終端群も先行公開しない。
    tied=ready([100,101,102,103,104],times=[0,0,0,10,10])
    states=dict(direction=np.array([1,-1,1,-1,-1],np.int8),valid=np.ones(5,bool))
    events=target.completed_groups(tied,states)
    np.testing.assert_array_equal(events['release_row'],[3]);np.testing.assert_array_equal(events['source_row'],[2])
    assert events['release_time'][0]==10 and events['source_time'][0]==0
    for count in (1,2,3):assert not len(target.completed_groups(prefix(tied,count),{k:v[:count] for k,v in states.items()})['release_row'])
    past=target.peer_asof(np.array([0,69,70,190,191],float),events)
    np.testing.assert_array_equal(past['direction'],[0,0,1,1,0])
    assert past['source_row'][2]==2 and past['release_row'][2]==3
    reflected_events=dict(events,direction=-events['direction'])
    mirror=target.peer_asof(np.array([0,69,70,190,191],float),reflected_events)
    np.testing.assert_array_equal(mirror['direction'],-past['direction']);counts['相手過去参照']=8
    # ----------------------------------------
    # 非有限・逆行等は契約の異常として拒否する。
    invalid=[]
    for label,mutation in [('時刻逆行',lambda d:d['time_s'].__setitem__(2,-1)),
                           ('seq重複',lambda d:d['seq'].__setitem__(2,3)),
                           ('非正呼値',lambda d:d.update(tick=0)),
                           ('非整合価格',lambda d:d['last'].__setitem__(2,104.003)),
                           ('配列長違い',lambda d:d.update(atr=np.ones(2)))]:
        broken=prefix(simple,len(simple['last']));mutation(broken)
        try:target.model(broken)
        except ValueError:invalid.append(label)
        else:raise AssertionError('不正入力を拒否できない: '+label)
    sources=[Path(__file__),HERE/'price_clock.py',HERE/'小数距離の境界反例.json',HERE/'price_clock_float_before_boundary.py.txt']
    proof=dict(全合格=True,未確定設計の人工検査=True,新売買再生=False,実相場入力読取=False,
        新実相場損益読取=False,速度校正=False,API取得数=0,人工経路数=len(paths),時計2種類=True,
        検査数=counts,手計算と境界検査=['直前ATR','同秒原本順','欠測補完なし','穴の距離除外',
            '同じ規定速度の平均一致','群完了前は相手非公開','追加60秒と120秒鮮度'],不正入力拒否=invalid,
        暫定中央設定=asdict(target.Config()),
        参照資料SHA256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    (HERE/'check_price_clock.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,検査数=counts,新売買再生=False),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
