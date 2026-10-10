"""両銘柄の代理時計を、厳密な過去参照と同時計先頭行で同期する。"""

import numpy as np


def asof_indices(targets: np.ndarray, times: np.ndarray, valid: np.ndarray,
                 reset: np.ndarray, max_age: float = 10.) -> tuple[np.ndarray, np.ndarray]:
    """機能: 各参照期限より厳密に前の最新時刻の先頭有効観測を選ぶ。

    引数: targets/times(float64 ndarray)、valid/reset(bool ndarray)、max_age(float)。
    返り値: 採用行int32と期限からの古さfloat32(tuple[ndarray,ndarray])。
    無効行、リセット行、期限と同時計、古すぎる観測を採用せず、より古い行への救済も行わない。
    同時計先頭は保存された有効準備系列の先頭であり、実受信の共通順序を保証しない。
    """
    targets=np.asarray(targets,dtype=np.float64)
    times=np.asarray(times,dtype=np.float64)
    valid=np.asarray(valid,dtype=np.bool_)
    reset=np.asarray(reset,dtype=np.bool_)
    assert targets.ndim==times.ndim==valid.ndim==reset.ndim==1
    assert len(times)==len(valid)==len(reset) and max_age>=0
    assert np.isfinite(times).all() and (np.diff(times)>=0).all()
    indices=np.full(len(targets),-1,dtype=np.int32)
    age=np.full(len(targets),np.nan,dtype=np.float32)
    if not len(times):
        return indices,age
    ends=np.searchsorted(times,targets,side='left')-1
    present=(ends>=0)&np.isfinite(targets)
    positions=np.flatnonzero(present)
    first=np.searchsorted(times,times[ends[present]],side='left')
    elapsed=targets[present]-times[first]
    good=valid[first]&~reset[first]&(elapsed>0)&(elapsed<=max_age)
    indices[positions[good]]=first[good].astype(np.int32)
    age[positions[good]]=elapsed[good].astype(np.float32)
    return indices,age


def session_sync(ready: dict, features: dict, session: str,
                 delays: tuple[int,...]=(1,5,15,60), step: float=15., max_age: float=10.) -> dict:
    """機能: 一つの保存場に共通判断グリッドと両銘柄の過去観測行を作る。

    引数: ready/features(dict)、session(str)、delays(tuple[int,...])、step/max_age(float)。
    返り値: grid、indices、observation_age、actual_age、両市場の採用マスク(dict)。
    開始5分後以上、安全撤収目安5分前未満とする。参照窓内のリセット判定は算法側が別に行う。
    """
    symbols=('TOPIX','NK225')
    start=ready[(session,symbols[0])]['start']
    limit=ready[(session,symbols[0])]['limit']
    assert all(ready[(session,s)]['start']==start and ready[(session,s)]['limit']==limit for s in symbols)
    grid=np.arange(start+300.,limit-300.,step,dtype=np.float64)
    output=dict(grid=grid,indices={},observation_age={},actual_age={},both_available={})
    for delay in delays:
        output['indices'][delay]={}
        output['observation_age'][delay]={}
        output['actual_age'][delay]={}
        for symbol in symbols:
            r,f=ready[(session,symbol)],features[(session,symbol)]
            index,age=asof_indices(grid-delay,r['time_s'],f['valid'],f['reset'],max_age)
            output['indices'][delay][symbol]=index
            output['observation_age'][delay][symbol]=age
            output['actual_age'][delay][symbol]=age+delay
        output['both_available'][delay]=(output['indices'][delay]['TOPIX']>=0)&(output['indices'][delay]['NK225']>=0)
    return output
