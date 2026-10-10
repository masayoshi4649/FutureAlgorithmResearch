"""全口座で銘柄名・単位変換・未来切断に対する入口の不変性を調べる。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE=Path(__file__).resolve().parent
TASK=HERE.parent
sys.path.insert(0,str(TASK))
from features import load_inputs_only
from signals import events,decisions,POLICIES,GATES


def main() -> None:
    """機能: 全四十六口座の共通計算と、十二政策の未来不変性を監査する。

    引数: なし。返り値: なし(None)。成績による候補選択は行わない。
    """
    frames=pickle.loads((TASK/'特徴.pkl').read_bytes())
    inputs=load_inputs_only()
    saved=pickle.loads((TASK/'判断.pkl').read_bytes())
    invariance=[]
    futures=[]
    for key,f in frames.items():
        tick=inputs[key]['tick']
        original=events(f,tick)
        renamed=f.copy();renamed['symbol']='NK225' if key[1]=='TOPIX' else 'TOPIX'
        named_events=events(renamed,tick)
        scaled=f.copy()
        for name in ('prior20_high','prior20_low','last','close','high','low'):
            scaled[name]=scaled[name]*4+1000.
        scaled['atr5']*=4
        scaled_events=events(scaled,tick*4)
        for policy,_ in POLICIES:
            for gate,_ in GATES:
                expected=decisions(original,policy,gate)
                np.testing.assert_array_equal(expected,saved[key,policy,gate])
                np.testing.assert_array_equal(decisions(named_events,policy,gate),expected)
                converted=decisions(scaled_events,policy,gate)
                for column in (0,1,5,8):np.testing.assert_array_equal(converted[:,column],expected[:,column])
                for column in (2,4,6):np.testing.assert_allclose(converted[:,column],expected[:,column]*4+1000,atol=1e-8,rtol=0)
                for column in (3,7):np.testing.assert_allclose(converted[:,column],expected[:,column]*4,atol=1e-8,rtol=0)
                invariance.append(dict(セッション=key[0],銘柄=key[1],政策=policy,確認=gate,判断数=len(expected)))
        for fraction in (.35,.7):
            cut=int(len(f)*fraction)
            last_index=f.ready_index.iloc[cut-1]
            partial=events(f.iloc[:cut],tick)
            changed=f.copy()
            for name in ('close','last','high','low','prior20_high','prior20_low'):
                changed.loc[changed.index[cut:],name]*=1.7
            for name in ('minute_supply_norm','minute_volume','past20_supply_abs_median','past20_volume_median'):
                changed.loc[changed.index[cut:],name]*=11.
            future=events(changed,tick)
            for policy,_ in POLICIES:
                for gate,_ in GATES:
                    full=saved[key,policy,gate]
                    expected=full[full[:,0]<=last_index]
                    np.testing.assert_array_equal(decisions(partial,policy,gate),expected)
                    modified=decisions(future,policy,gate)
                    np.testing.assert_array_equal(modified[modified[:,0]<=last_index],expected)
                    futures.append(dict(セッション=key[0],銘柄=key[1],政策=policy,確認=gate,比率=fraction,一致判断数=len(expected)))
    out=dict(合格=True,銘柄名と価格単位変換=invariance,未来切断と改変=futures,
             コードSHA256=hashlib.sha256((TASK/'signals.py').read_bytes()).hexdigest())
    (HERE/'入口の独立監査.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
    print('入口独立監査合格',len(invariance),'未来比較',len(futures),flush=True)


if __name__=='__main__':
    main()
