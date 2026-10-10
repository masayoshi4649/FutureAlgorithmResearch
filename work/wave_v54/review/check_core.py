"""境界の状態遷移と固定Rの注文管理を手作り事例で独立検査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


HERE=Path(__file__).resolve().parent
TASK=HERE.parent
sys.path.insert(0,str(TASK))
from signals import events,decisions
from engine import execute


def frame(closes: list) -> pd.DataFrame:
    """機能: 論点以外の条件を固定した確定足を用意する。

    引数: closes(list)。返り値: 公開済み特徴表(DataFrame)。
    """
    return pd.DataFrame([dict(bar_start=1200.+i*60,time_s=1260.+i*60,seq=100+i*3,source_last_seq=99+i*3,
                              ready_index=i,can_trade=True,prior20_high=100.,prior20_low=60.,atr5=10.,
                              close=p,last=p,high=p+.2,low=p-.2,past20_supply_abs_median=1.,
                              past20_volume_median=10.,past20_valid_count=20,minute_valid=True,
                              minute_supply_norm=2.,minute_volume=20.,symbol='TOPIX') for i,p in enumerate(closes)])


def prices(values: list, times: list | None=None, limit: float=3000.) -> dict:
    """機能: 次行約定を明瞭に確認できる原本価格列を作る。

    引数: values(list)、times(list|None)、limit(float)。返り値: 入力(dict)。
    """
    return dict(last=np.asarray(values,float),time_s=np.asarray(times if times is not None else range(len(values)),float),
                seq=np.arange(len(values),dtype=np.int64)+100,limit=limit,start=0.,session='合成',symbol='TOPIX')


def order(stop: float=98., risk: float=2., side: int=1) -> np.ndarray:
    """機能: 入口判断だけの指示を作る。

    引数: stop/risk(float)、side(int)。返り値: 指示(ndarray)。
    """
    return np.asarray([[0,side,stop,10.,100.,1.,80.,risk,1]],float)


def main() -> None:
    """機能: 状態・正規化・異常約定・未来不変性を検査して保存する。

    引数: なし。返り値: なし(None)。実データ損益を参照しない。
    """
    checks=[]
    f=frame([102,102.5,100])
    f.loc[1,['prior20_high','atr5','past20_supply_abs_median','past20_volume_median']]=[500.,1000.,999.,999.]
    e=events(f,.1)
    assert len(e)==1 and e[0]['kind']==1 and e[0]['end_seq']==103
    assert e[0]['line']==100 and e[0]['atr']==10 and e[0]['supply_scale']==1 and e[0]['volume_scale']==10
    assert e[0]['stop']==99 and e[0]['planned_risk']==3.5 and e[0]['supply_ok'] and e[0]['activity_ok']
    assert len(decisions(e,'S',3))==1
    checks.append('t0を一本目とし、線・ATR・板と出来高基準を開始時で固定')

    f=frame([102,98.5,100]);f.loc[1,'minute_supply_norm']=-2.
    e=events(f,.1)
    assert len(e)==1 and e[0]['kind']==-1 and e[0]['side']==-1
    assert np.isclose(e[0]['stop'],103.2) and e[0]['room']>=2*e[0]['planned_risk']
    assert len(decisions(e,'F',0))==0 and len(decisions(e,'R',3))==1
    checks.append('失敗は後続足から判定し、確認時点までの突出端と固定中央を使う')

    f=frame([102,100,102,102.5,100])
    e=events(f,.1)
    assert e[0]['end_seq']==109 and e[0]['outside_count']==2
    checks.append('外側二本は連続が必要で、中立足を挟む場合は数え直す')
    f=frame([102,102.5,100]);f.loc[1,'minute_supply_norm']=-2.
    e=events(f,.1)
    assert len(e)==1 and len(decisions(e,'S',3))==0 and len(decisions(e,'S',0))==1
    f=frame([102,102.5]);f.loc[0,['past20_supply_abs_median','past20_volume_median']]=0.
    e=events(f,.1)
    assert not e[0]['supply_ok'] and not e[0]['activity_ok']
    f=frame([102,102.5]);f.loc[1,'minute_valid']=False
    e=events(f,.1)
    assert not e[0]['supply_ok'] and not e[0]['activity_ok']
    checks.append('確認で拒否しても状態は消費し、未知・基準ゼロを支持扱いしない')

    f=frame([102]+[100]*9+[98.5]);f.loc[10,'minute_supply_norm']=-2
    e=events(f,.1)
    assert e[0]['kind']==-1 and e[0]['end_time']==e[0]['deadline']
    f=frame([102]+[100]*10+[98.5])
    e=events(f,.1)
    assert e[0]['kind']==0 and e[0]['result']=='10分で未確定'
    f=frame([102,102.5]);f.loc[1,'bar_start']+=60
    assert events(f,.1)[0]['kind']==0
    checks.append('10分境界は以内を採用、超過・足欠落は状態を破棄')

    f=frame([102,102.5,100,58,57.5,80])
    original=decisions(events(f,.1),'S',0)
    swapped=f.copy();swapped['symbol']='NK225'
    np.testing.assert_array_equal(decisions(events(swapped,.1),'S',0),original)
    transformed=f.copy()
    for name in ('prior20_high','prior20_low','close','last','high','low'):
        transformed[name]=transformed[name]*4+500
    transformed['atr5']*=4
    scaled=decisions(events(transformed,.4),'S',0)
    for col in (0,1,5,8):np.testing.assert_array_equal(scaled[:,col],original[:,col])
    for col in (2,4,6):np.testing.assert_allclose(scaled[:,col],original[:,col]*4+500)
    for col in (3,7):np.testing.assert_allclose(scaled[:,col],original[:,col]*4)
    reflected=f.copy()
    reflected['high'],reflected['low']=200-f.low,200-f.high
    reflected['prior20_high'],reflected['prior20_low']=200-f.prior20_low,200-f.prior20_high
    reflected['close'],reflected['last']=200-f.close,200-f.last
    reflected['minute_supply_norm']=-f.minute_supply_norm
    reverse=decisions(events(reflected,.1),'S',0)
    np.testing.assert_array_equal(reverse[:,1],-original[:,1])
    np.testing.assert_allclose(reverse[:,7],original[:,7])
    checks.append('銘柄名入替・価格倍率と平行移動・上下反射で判断が整合')

    x=prices([100,100,97,96]);s=order()
    z=execute(x,s,True,5,1000)
    assert z['net']==-20000 and z['r_net']==-2 and z['orders'][1][2:4]==[102.,103.]
    x=prices([100,98,97]);s=order(99,1)
    z=execute(x,s,True,5,1000)
    assert z['gap_entries']==1 and z['orders'][1][9]==6 and z['orders'][1][2:4]==[101.,102.]
    assert z['net']==-5000 and z['r_net']==-1 and z['risk_groups'][0][10]==1
    checks.append('次行約定・線越え異常約定を計画Rで記録し、さらに次行で即失敗返済')

    x=prices([100,100,104,102.5,102,101.5]);s=order()
    follow=execute(x,s,True,5,1000)
    fixed=execute(x,s,False,5,1000)
    assert follow['net']==7500 and fixed['net']==12500
    assert follow['orders'][-1][9]==2 and fixed['orders'][-1][9]==5
    for cut in range(2,len(x['seq'])):
        part={k:v[:cut] if isinstance(v,np.ndarray) else v for k,v in x.items()}
        observed=execute(part,s,True,5,1000,finish=False)
        expected=[o for o in follow['orders'] if o[3]<=x['seq'][cut-1]]
        assert observed['orders']==expected
        for name in ('curve','r_curve','planned_curve'):
            np.testing.assert_allclose(observed[name],follow[name][:cut],rtol=0,atol=1e-8)
    checks.append('追跡と固定目標を分離し、未返済を含む金額R曲線も途中切断で不変')

    x=prices([100,100,100.5,100.5],[0,1,1801,1802]);z=execute(x,order(),True,5,1000)
    assert z['orders'][-1][9]==3
    x=prices([100,100,100.5,100.5],[0,1,600,601],limit=600);z=execute(x,order(),True,5,1000)
    assert z['orders'][-1][9]==4
    checks.append('三十分期限と場内返済を次行で実行する')
    output=dict(合格=True,項目数=len(checks),項目=checks,
                コードSHA256={p:hashlib.sha256((TASK/p).read_bytes()).hexdigest() for p in ('signals.py','engine.py')})
    (HERE/'状態と固定Rの合成監査.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    print('合成監査合格',len(checks),flush=True)


if __name__=='__main__':
    main()
