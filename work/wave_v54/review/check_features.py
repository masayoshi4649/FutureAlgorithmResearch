"""非重複の一分量・直前中央値・単位正規化を独立検査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd


HERE=Path(__file__).resolve().parent
TASK=HERE.parent
sys.path.insert(0,str(TASK))
from features import build_account,load_inputs_only,MEDIANS


def fixture(n: int=25) -> tuple:
    """機能: 各分二行が完全に公開された数量監査用の合成入力を作る。

    引数: n(int)。返り値: 確定足・公開数量・原本行(tuple)。
    """
    ready=dict(time_s=np.arange(n*2+1,dtype=float)*30,seq=np.arange(n*2+1,dtype=np.int64)+1,start=0.,symbol='TOPIX')
    base=pd.DataFrame([dict(source_bar_start=i*60.,time_s=(i+1)*60.,seq=(i+1)*2+1,ready_index=(i+1)*2,
                            close=100+i*.1,prev_close=100+(i-1)*.1,atr5=2.,symbol='TOPIX') for i in range(n)])
    cols=('source_volume_delta','exec_buy','exec_sell','exec_unknown','noexec_bid_add','noexec_bid_remove',
          'noexec_ask_add','noexec_ask_remove','quote_events','trade_events','no_trade_events','valid_events',
          'continuity_resets','volume_resets','unavailable_volume_events','depth_incomplete_events',
          'depth_disordered_events','depth_duplicate_events','depth_valid_events','supply_bid_near','supply_ask_near')
    blocks=pd.DataFrame({k:np.zeros(n*2) for k in cols})
    blocks['source_time_s']=ready['time_s'][:-1]
    blocks['source_last_seq']=ready['seq'][:-1]
    blocks['seq']=ready['seq'][1:]
    blocks['source_age']=30.
    for name in ('source_volume_delta','exec_buy','noexec_bid_add','quote_events','trade_events','valid_events','depth_valid_events'):
        blocks[name]=1.
    blocks['supply_bid_near']=10.
    blocks['supply_ask_near']=10.
    return base,blocks,ready


def main() -> None:
    """機能: 合成端点・全口座の過去中央値・未来改変を検査する。

    引数: なし。返り値: なし(None)。成績を参照せず特徴だけを照合する。
    """
    checks=[]
    base,blocks,ready=fixture()
    blocks.loc[40:41,['source_volume_delta','exec_buy']]=100000.
    f=build_account(base,blocks,ready)
    assert f.minute_volume.iloc[20]==200000 and f.past20_volume_median.iloc[20]==2
    assert f.past20_valid_count.iloc[20]==20 and f.past20_volume_median.iloc[:19].isna().all()
    assert f.minute_valid.all()
    checks.append('当分の極端な数量を過去中央値へ混ぜず、開始二十分未満を使用しない')
    invalid=blocks.copy();invalid.loc[:19,'unavailable_volume_events']=1
    g=build_account(base,invalid,ready)
    assert g.past20_valid_count.iloc[20]==10 and g.past20_volume_median.iloc[20]==2
    invalid.loc[20:21,'unavailable_volume_events']=1
    g=build_account(base,invalid,ready)
    assert g.past20_valid_count.iloc[20]==9 and np.isnan(g.past20_volume_median.iloc[20])
    missing=blocks.drop(index=41).reset_index(drop=True)
    g=build_account(base,missing,ready)
    assert not g.minute_valid.iloc[20] and np.isnan(g.relative_volume.iloc[20])
    checks.append('十有効分の準備条件を厳守し、未公開の原本行を含む分は無効')
    zero=blocks.copy()
    zero[['source_volume_delta','exec_buy','noexec_bid_add']]=0.
    g=build_account(base,zero,ready)
    assert g.minute_valid.all() and g.past20_volume_median.iloc[20]==0 and g.past20_supply_abs_median.iloc[20]==0
    assert np.isnan(g.relative_volume.iloc[20]) and np.isnan(g.known_fraction.iloc[20])
    checks.append('観測されたゼロ量と不明を区別し、ゼロ中央値で割らない')

    quantity=('source_volume_delta','exec_buy','exec_sell','exec_unknown','noexec_bid_add','noexec_bid_remove',
              'noexec_ask_add','noexec_ask_remove','supply_bid_near','supply_ask_near')
    scaled=blocks.copy()
    scaled[list(quantity)]*=7.
    g=build_account(base,scaled,ready)
    for name in ('minute_supply_norm','relative_volume','relative_depth','pressure','known_fraction'):
        np.testing.assert_allclose(g[name],f[name],equal_nan=True,atol=1e-10)
    swapped=ready.copy();swapped['symbol']='NK225'
    pd.testing.assert_frame_equal(build_account(base,blocks,swapped),f,check_exact=True)
    checks.append('数量単位を七倍しても相対指標は不変、銘柄IDを使っていない')

    features=pickle.loads((TASK/'特徴.pkl').read_bytes())
    bases=pickle.loads((TASK.parent/'wave_v53/特徴.pkl').read_bytes())
    allblocks=pickle.loads((TASK.parent/'wave_v52/measurement/features.pkl').read_bytes())
    inputs=load_inputs_only()
    rows=0
    for key,frame in features.items():
        for i,row in enumerate(frame.itertuples()):
            past=frame[(frame.source_bar_start>=row.source_bar_start-1200)&(frame.source_bar_start<row.source_bar_start)&frame.minute_valid]
            assert row.past20_valid_count==len(past)
            for output,source in MEDIANS.items():
                actual=getattr(row,output)
                if len(past)>=10 and row.time_s-inputs[key]['start']>=1200:
                    assert actual==np.median(past[source])
                else:
                    assert np.isnan(actual)
            if row.minute_valid:
                assert row.minute_observed_rows==row.minute_ready_rows and row.minute_source_last_seq<row.seq
            rows+=1
    checks.append(f'全46口座{rows}分の過去窓・有効数・中央値を別式で照合')
    futures=[]
    keys=sorted(inputs)
    for key in [keys[i] for i in (0,1,22,23,44,45)]:
        base,b=bases[key].copy(),allblocks[key].copy()
        cut=len(base)//2
        seq=base.seq.iloc[cut-1]
        b.loc[b.seq>seq,list(quantity)]*=11.
        base.loc[base.index[cut:],['close','prev_close']]*=2.
        changed=build_account(base,b,inputs[key])
        pd.testing.assert_frame_equal(changed.iloc[:cut],features[key].iloc[:cut],check_exact=True)
        futures.append(dict(セッション=key[0],銘柄=key[1],一致分数=cut))
    checks.append('六口座の未来量・価格を変更しても過去特徴は不変')
    output=dict(合格=True,項目=checks,全口座分数=rows,未来改変=futures,
                コードSHA256=hashlib.sha256((TASK/'features.py').read_bytes()).hexdigest())
    (HERE/'特徴の独立監査.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    print('特徴独立監査合格',rows,'未来改変',len(futures),flush=True)


if __name__=='__main__':
    main()
