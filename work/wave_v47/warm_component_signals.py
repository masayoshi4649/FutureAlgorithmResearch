"""建玉と方向状態は毎場初期化し、EMAと傾きだけ過去の確定足で暖機する。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import component_signals as RESET


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SESSIONS=tuple(f'2026-09-{day:02d}_{kind}' for day in (21,22,23,24,25,28,29)
               for kind in ('Day','Night') if not (day==29 and kind=='Night'))
_HISTORY: dict={}
_MAIN: dict={}


def catalog() -> list[dict]:
    """機能: 主方向3窓×相手有無×短期有無の12仕様を返す。

    引数: なし。返り値: 暖機IDと完全対応する毎場初期化仕様 (list[dict])。
    """
    result=[]
    for scale in RESET.SCALES:
        for peer in (False,True):
            for short in (False,True):
                reset=RESET.specification(main_scale=scale,peer_confirm=peer,short_confirm=short)
                result.append(dict(id='W_'+reset['id'],reset=reset))
    return result


def set_root(path: Path | str) -> None:
    """機能: 現場と過去場の足参照根を一緒に変更してキャッシュを破棄する。

    引数: path (Path|str)。返り値: なし (None)。
    """
    global ROOT
    ROOT=Path(path).resolve()
    _HISTORY.clear()
    _MAIN.clear()
    RESET.set_root(ROOT)


def past_closes(ready: dict) -> np.ndarray:
    """機能: 当該場より前の保存済みセッションの公開確定終値だけを連結する。

    引数: ready (dict)。返り値: 時系列順の過去終値 (ndarray[float64])。
    現在場と後続場を読まず、セッションの空白時間による減衰は加えない。
    """
    session=ready['session']
    if session not in SESSIONS:
        raise ValueError('固定した旧13セッションだけを対象にします')
    key=(str(ROOT),session,ready['symbol'],float(ready['start']))
    if key not in _HISTORY:
        values=[]
        for earlier in SESSIONS[:SESSIONS.index(session)]:
            frame=pd.read_csv(ROOT/'candle_1min'/ready['symbol']/(earlier+'.csv'))
            release=pd.to_datetime(frame.time).dt.as_unit('ns').astype('int64').to_numpy(float)/1e9+120
            valid=frame.closed.astype(str).str.lower().eq('true').to_numpy(copy=True)
            valid&=release<float(ready['start'])
            chosen=frame.loc[valid,'close'].to_numpy(float)
            if not np.isfinite(chosen).all() or (chosen<=0).any():
                raise ValueError('過去確定終値が不正です')
            values.append(chosen)
        _HISTORY[key]=np.concatenate(values) if values else np.array([],dtype=float)
    return _HISTORY[key]


def main_model(ready: dict, params: dict) -> dict:
    """機能: 過去終値でEMAを暖機し、当場ATRで新しい主方向を判定する。

    引数: ready/params (dict)。返り値: 当場の公開時刻と主方向 (dict)。
    持ち越すのはEMA計算と傾き差分用の価格履歴だけ。方向保持状態とATRは持ち越さない。
    """
    key=(str(ROOT),id(ready),id(ready['atr']),len(ready['seq']),int(ready['seq'][-1]),
         float(ready['time_s'][-1]),params['clock_multiplier'])
    if key not in _MAIN:
        hierarchy=RESET.HIERARCHY
        bars=hierarchy.LEGACY._bars(ready)
        history=past_closes(ready)
        combined=pd.Series(np.r_[history,np.asarray(bars['close'],float)])
        scale=params['clock_multiplier']
        fast,slow,slope_bars=[hierarchy._size(value*scale) for value in (15,60,3)]
        short=combined.ewm(span=fast,adjust=False,min_periods=fast).mean()
        long=combined.ewm(span=slow,adjust=False,min_periods=slow).mean()
        begin=len(history)
        atr=np.asarray(bars['atr'],float)
        measure=(short-long).to_numpy(float)[begin:]/atr
        slope=long.diff(slope_bars).to_numpy(float)[begin:]/atr
        arm=np.zeros(len(atr),dtype=np.int8)
        arm[(measure>.15)&(slope>.02)]=1
        arm[(measure<-.15)&(slope<-.02)]=-1
        valid=np.isfinite(atr)&(atr>0)
        arm[~valid]=0
        measure[~valid]=np.nan
        direction=hierarchy._persistent(arm,measure,0.,False)
        _MAIN[key]=dict(time_s=np.asarray(bars['time_s']),direction=direction,ready_ref=ready,
                        past_count=begin,fast=fast,slow=slow,slope_bars=slope_bars)
    return _MAIN[key]


def build(spec: dict, inputs: dict, features: dict) -> dict:
    """機能: 暖機した主方向へ従来の相手・短期条件を接続する。

    引数: spec (dict)、inputs/features (dict)。返り値: 原本行の入口列 (dict[tuple,ndarray[int8]])。
    ATR・開始20分・相手60秒・短期30秒・短期TTL120秒を元通りに保つ。
    """
    fixed={value['id']:value for value in catalog()}
    if fixed.get(spec.get('id'))!=spec:
        raise ValueError('固定12仕様と一致しません')
    reset=spec['reset']
    params=RESET.legacy_spec(reset)['params']
    hierarchy=RESET.HIERARCHY
    if not inputs or not set(inputs)<=set(features):
        raise ValueError('入力又は公開特徴が不足しています')
    models={key:main_model(ready,params) for key,ready in inputs.items()}
    output={}
    for key,ready in inputs.items():
        main=hierarchy._allowed(key,ready['time_s'],models,params)
        main[(ready['time_s']<ready['start']+1200)|~np.isfinite(ready['atr'])|(ready['atr']<=0)]=0
        if not reset['short_confirm']:
            output[key]=main
            continue
        # ----------------------------------------
        # 短期条件を新しい主方向へ接続し、旧公開順と保持規則を保つ。
        short=RESET.short_model(ready,features[key],1.)
        allowed=hierarchy._allowed(key,short['time_s'],models,params)
        allowed[short['time_s']<ready['start']+1200]=0
        direction,_,_=hierarchy._entry_filter(ready['seq'],ready['time_s'],main,short['seq'],
            short['time_s'],allowed,short['short'],np.zeros(len(short['seq'])),1,1.)
        assert direction.shape==ready['seq'].shape and direction.dtype==np.int8
        assert np.isin(direction,[-1,0,1]).all()
        output[key]=direction
    return output
