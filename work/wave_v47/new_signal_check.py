"""追加ナイトの入口も、入力を変更してから信号を再生成して確認する。"""

from __future__ import annotations

import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE))
import check_component_signals as checks
import component_signals as signals


def calculate(inputs: dict, frames: dict, root: Path) -> dict:
    """機能: キャッシュを破棄して中央の入口列を作り直す。

    引数: inputs/frames(dict)、root(Path)。返り値: 入口列(dict)。
    """
    signals.set_root(root)
    return signals.build(signals.specification(),inputs,frames)


def candle_copy(keys: list, label: str, cutoff: float | None, pivots: dict | None) -> Path:
    """機能: 追加ナイトの確定足だけを検査用領域で変形する。

    引数: keys(list)、label(str)、cutoff(float|None)、pivots(dict|None)。返り値: 複写根(Path)。
    """
    output=HERE/'new_audit_candles'/label
    for key in keys:
        assert key[0]=='2026-09-29_Night'
        frame=pd.read_csv(ROOT/'candle_1min'/key[1]/(key[0]+'.csv'))
        if cutoff is not None:
            release=pd.to_datetime(frame.time).dt.as_unit('ns').astype('int64').to_numpy(float)/1e9+120
            mask=release>=cutoff
            for col in ('open','high','low','close','volume'):
                frame[col]=frame[col].astype(float)
                frame.loc[mask,col]=frame.loc[mask,col]*1.7+7000
            frame.loc[mask,'closed']=True
            if 'volume_complete' in frame: frame.loc[mask,'volume_complete']=True
        if pivots is not None:
            pivot=pivots[key]; high,low=frame.high.copy(),frame.low.copy()
            for col in ('open','close'): frame[col]=2*pivot-frame[col]
            frame['high'],frame['low']=2*pivot-low,2*pivot-high
        target=output/'candle_1min'/key[1]/(key[0]+'.csv')
        target.parent.mkdir(parents=True,exist_ok=True)
        frame.to_csv(target,index=False,encoding='utf-8')
    return output


def main() -> None:
    """機能: 新2入力の過去不変性・反射・同秒順を全行比較する。

    引数: なし。返り値: なし(None)。売買結果や条件選択は変更しない。
    """
    inputs=pickle.loads((HERE/'new_inputs.pkl').read_bytes())
    frames=pickle.loads((HERE/'new_features_depth.pkl').read_bytes())
    assert len(inputs)==2
    keys=list(inputs)
    baseline=calculate(inputs,frames,ROOT)
    start=max(r['start'] for r in inputs.values()); end=min(r['time_s'][-1] for r in inputs.values())
    cutoff=start+(end-start)*.37
    counts={key:int(np.searchsorted(r['time_s'],cutoff,side='left')) for key,r in inputs.items()}
    sliced,sf=checks.slice_inputs(inputs,frames,counts)
    prefix=calculate(sliced,sf,ROOT)
    future_cut=start+(end-start)*.73
    altered,af,_=checks.transformed(inputs,frames,future_cut)
    future=calculate(altered,af,candle_copy(keys,'new_future',future_cut,None))
    mirrored,mf,pivots=checks.transformed(inputs,frames,None)
    reflection=calculate(mirrored,mf,candle_copy(keys,'new_reflection',None,pivots))
    rows=[]
    for key in keys:
        np.testing.assert_array_equal(prefix[key],baseline[key][:counts[key]])
        n=int(np.searchsorted(inputs[key]['time_s'],future_cut,side='left'))
        np.testing.assert_array_equal(future[key][:n],baseline[key][:n])
        np.testing.assert_array_equal(reflection[key],-baseline[key])
        same=np.flatnonzero(np.diff(inputs[key]['time_s'])==0)+1
        cut=int(same[np.argmin(abs(same-int(len(inputs[key]['last'])*.73)))])
        keep={k:len(inputs[k]['last']) for k in keys}; keep[key]=cut
        sliced,sf=checks.slice_inputs(inputs,frames,keep)
        rebuilt=calculate(sliced,sf,ROOT)
        np.testing.assert_array_equal(rebuilt[key],baseline[key][:cut])
        rows.append(dict(session=key[0],symbol=key[1],過去切断一致=True,未来変更一致=True,
                         反射一致=True,同秒順一致=True,原本行数=len(inputs[key]['last'])))
    signals.set_root(ROOT)
    # ----------------------------------------
    # 抽出器保存直後と約定価格追加後のNPZ指紋は別物なので、最終入力の証跡を追加する。
    provenance=[]
    audit=json.loads((HERE/'追加ナイト入力監査.json').read_text(encoding='utf-8'))
    for item in audit['原本監査']:
        symbol=item['銘柄']; key=next(k for k in keys if k[1]==symbol)
        path=HERE/'features'/f'約定系列_{symbol}_{key[0]}.npz'
        with np.load(path) as tape:
            np.testing.assert_array_equal(tape['last'],inputs[key]['last'])
            np.testing.assert_array_equal(tape['seq'],inputs[key]['seq'])
        provenance.append(dict(銘柄=symbol,抽出直後の中値系列SHA256=item['抽出']['約定系列NPZ_SHA256'],
            原本約定価格追加後SHA256=checks.sha(path),入力との価格行番号一致=True,
            説明='旧抽出監査のSHAは中値だけの保存直後。売買入力は原本CurrentPrice追加後であり、入力pickle指紋で既に固定済み。'))
    checks.save(HERE/'new_signal_audit.json',dict(全合格=True,入力検査=rows,約定系列指紋の区別=provenance,
        元入力監査SHA256=checks.sha(HERE/'追加ナイト入力監査.json'),現在API追加取得数=0))
    print('追加ナイト2入力：方向の切断・未来変更・反射・同秒順が一致。原本約定価格も入力一致。',flush=True)


if __name__=='__main__':
    main()
