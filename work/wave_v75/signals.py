"""二市場の共通進行・追随・失敗・相対価格・板圧力から共同イベントを作る。"""

from __future__ import annotations

import math
from pathlib import Path

import numba
import numpy as np

from inputs.core import asof_indices


HERE=Path(__file__).resolve().parent
numba.config.CACHE_DIR=str(HERE/'numba_cache')
SYMBOLS=('TOPIX','NK225')
FAMILIES=('共通方向','先行に追随','先行失敗','相対価格の戻り','両板の圧力先行','片側の吸収失敗','自動選択')
PULSE_COLUMNS=('共通判断行','自発注判断行','方向','自参照行','相手参照行')


def empty_features(size: int) -> dict:
    """機能: 一市場が欠ける場合に、参照不能な特徴を作る。

    引数: size(int)。返り値: 無効maskと未定義値を持つ特徴(dict)。
    """
    out={name:np.full(size,-1,dtype=np.int32) for name in ('now','old','short')}
    out.update({name:np.full(size,np.nan) for name in ('mid','ret','short_ret','flow','fast_flow')})
    out['valid']=np.zeros(size,dtype=bool)
    out['confirmation']=np.zeros(size,dtype=np.int8)
    return out


def features(grid: np.ndarray, delay: int, window: int, max_age: int, ready: dict, book: dict) -> dict:
    """機能: 各予定判断時刻より前に知られる一市場の価格・板フローを作る。

    引数: grid(ndarray)、delay/window/max_age(int)、ready/book(dict)。
    返り値: 参照行、百分率変化、短期両気配方向、OFI比と有効性(dict)。
    """
    times=ready['time_s']
    if not len(times):
        return empty_features(len(grid))
    endpoint=np.asarray(book['valid'] & np.isfinite(book['bid']) & np.isfinite(book['ask'])
        & (book['bid']>0) & (book['ask']>book['bid'])
        & (book['ask']-book['bid']<=2*ready['tick']+1e-9),dtype=bool)
    points={name:asof_indices(grid-delay-lag,times,endpoint,book['reset'],max_age)[0]
            for name,lag in (('now',0),('old',window),('short',15))}
    now,old,short=points['now'],points['old'],points['short']
    valid=(now>=0)&(old>=0)&(short>=0)&(old<now)&(short<now)
    safe_now=np.maximum(now,0)
    safe_old=np.maximum(old,0)
    safe_short=np.maximum(short,0)
    broken=np.cumsum(np.asarray(book['reset'] | ~book['valid'],dtype=np.int64))
    valid &= broken[safe_now]==broken[safe_old]
    valid &= broken[safe_now]==broken[safe_short]
    ofi=book['best_ofi']
    unknown=np.cumsum(~np.isfinite(ofi))
    signed=np.cumsum(np.nan_to_num(ofi,nan=0.))
    absolute=np.cumsum(np.abs(np.nan_to_num(ofi,nan=0.)))
    flow=np.zeros(len(grid))
    fast_flow=np.zeros(len(grid))
    for origin,target in ((safe_old,flow),(safe_short,fast_flow)):
        denominator=absolute[safe_now]-absolute[origin]
        known=(unknown[safe_now]==unknown[origin])&(denominator>0)
        target[known]=(signed[safe_now[known]]-signed[origin[known]])/denominator[known]
        valid &= unknown[safe_now]==unknown[origin]
    mid=book['mid'][safe_now]
    ret=(mid/book['mid'][safe_old]-1.)*10000.
    short_ret=(mid/book['mid'][safe_short]-1.)*10000.
    bid_delta=(book['bid'][safe_now]-book['bid'][safe_short])/ready['tick']
    ask_delta=(book['ask'][safe_now]-book['ask'][safe_short])/ready['tick']
    confirmation=np.where((bid_delta>=1.-1e-8)&(ask_delta>=1.-1e-8),1,
                   np.where((bid_delta<=-1.+1e-8)&(ask_delta<=-1.+1e-8),-1,0)).astype(np.int8)
    for array in (mid,ret,short_ret,flow,fast_flow):
        array[~valid]=np.nan
    confirmation[~valid]=0
    return dict(**points,valid=valid,mid=mid,ret=ret,short_ret=short_ret,
                confirmation=confirmation,flow=flow,fast_flow=fast_flow)


def relative_state(own: dict, peer: dict, window: int, paired: bool, threshold: float) -> np.ndarray:
    """機能: 過去だけの平均と分散から、相対的な偏りが縮み始めた方向を求める。

    引数: own/peer(dict)、window(int)、paired(bool)、threshold(float)。
    返り値: 平均方向へ戻り始めた売買方向(ndarray[int8])。
    単独対照は自価格だけの平均回帰で、相手フィルターの完全除去とは異なる。
    """
    length=max(16,window*4//15)
    joint_valid=own['valid']&peer['valid']
    x=np.log(own['mid'])
    y=np.log(peer['mid'])
    spread=x-y if paired else x
    states=np.zeros(len(x),dtype=np.int8)
    for i in range(length,len(x)):
        if not joint_valid[i-length:i+1].all():
            continue
        prior=spread[i-length:i]
        scale=float(np.std(prior,ddof=1))
        if scale<=1e-12:
            continue
        center=float(np.mean(prior))
        z=(spread[i]-center)/scale
        old_z=(spread[i-1]-center)/scale
        if abs(z)<threshold or z*old_z<=0 or abs(z)>=abs(old_z):
            continue
        side=-1 if z>0 else 1
        if own['confirmation'][i]!=side:
            continue
        if paired:
            dx=np.diff(x[i-length:i])
            dy=np.diff(y[i-length:i])
            denominator=float(np.std(dx)*np.std(dy))
            if denominator<=1e-20:
                continue
            correlation=float(np.mean((dx-dx.mean())*(dy-dy.mean()))/denominator)
            if correlation<.3:
                continue
        states[i]=side
    return states


def conditions(own: dict, peer: dict, window: int, level: int, paired: bool) -> tuple[np.ndarray,np.ndarray]:
    """機能: 二市場の関係を七つの事前仮説へ分け、共同状態を機械判定する。

    引数: own/peer(dict)、window/level(int)、paired(bool)。
    返り値: 七状態と共同観測有効性(tuple[ndarray,ndarray])。
    単独対照も同じ共同観測時点を使うが、相手の価格・OFI内容で売買方向を選ばない。
    """
    theta=3. if level==0 else 6.
    pressure=.10 if level==0 else .20
    joint_valid=own['valid']&peer['valid']
    n=len(joint_valid)
    result=np.zeros((7,n),dtype=np.int8)
    ret,short,flow,confirm=own['ret'],own['short_ret'],own['flow'],own['confirmation']
    pr,ps,pf=peer['ret'],peer['short_ret'],peer['flow']
    for d in (-1,1):
        own_progress=confirm==d
        own_failure=confirm==-d
        tests=[
            (d*ret>=theta)&own_progress,
            (np.abs(ret)<=theta/2)&own_progress,
            (d*ret>=theta)&own_failure,
            np.zeros(n,dtype=bool),
            (d*flow>=pressure)&(np.abs(ret)<theta)&own_progress,
            (d*flow>=pressure)&(np.abs(ret)<theta/2)&own_failure&(d*own['fast_flow']<0)
        ]
        if paired:
            tests[0] &= (d*pr>=theta)&(d*ps>=0)
            tests[1] &= (d*pr>=theta)&(d*ps>=0)
            tests[2] &= (d*pr<theta/2)&(d*ps<=0)
            tests[4] &= (d*pf>=pressure)&(np.abs(pr)<theta)&(d*ps>=0)
            tests[5] &= (d*pf>=pressure)&(d*pr>=theta)
        for family in (0,1,2,4,5):
            result[family,tests[family]&joint_valid]=d if family in (0,1,4) else -d
    result[3]=relative_state(own,peer,window,paired,1.5 if level==0 else 2.5)
    # ----------------------------------------
    # 自動選択は事前に決めた共通進行→先行追随→相対戻りの優先順で選ぶ。
    result[6]=np.where(result[0]!=0,result[0],np.where(result[1]!=0,result[1],result[3]))
    return result,joint_valid


def event_pulses(grid: np.ndarray, state: np.ndarray, valid: np.ndarray, neutral_seconds: float=60., spacing: float=600.) -> np.ndarray:
    """機能: 有効な中立による再準備と最低発火間隔で、継続状態から新規イベントを区切る。

    引数: grid/state/valid(ndarray)、neutral_seconds/spacing(float)。
    返り値: 一回限りの新規イベント方向(ndarray[int8])。
    初回は準備済み。欠測は中立に含めず、発火後は有効中立が連続60秒必要。
    """
    out=np.zeros(len(grid),dtype=np.int8)
    armed=True
    neutral_start=-1.
    previous_time=-1.
    last_fire=-1e30
    for i,stamp in enumerate(grid):
        if previous_time>=0 and stamp-previous_time>15.+1e-7:
            neutral_start=-1.
        previous_time=stamp
        if not valid[i]:
            neutral_start=-1.
            continue
        if state[i]==0:
            if neutral_start<0:
                neutral_start=stamp
            if stamp-neutral_start>=neutral_seconds:
                armed=True
        else:
            neutral_start=-1.
            if armed and stamp-last_fire>=spacing:
                out[i]=state[i]
                last_fire=stamp
                armed=False
    return out


def map_pulses(grid: np.ndarray, pulse: np.ndarray, own: dict, peer: dict, ready: dict, book: dict) -> np.ndarray:
    """機能: 共通時刻の発火を、その時刻以降の最初の自市場行へ写像する。

    引数: grid/pulse(ndarray)、own/peer/ready/book(dict)。
    返り値: 共通行・発注判断行・方向・両参照行の五列(ndarray[float])。
    不適切な自市場行又は10秒を超える遅れは棄却し、後から補完しない。
    """
    rows=[]
    if not len(ready['time_s']):
        return np.empty((0,5),dtype=np.float64)
    previous=-1
    for i in np.flatnonzero(pulse):
        target=int(np.searchsorted(ready['time_s'],grid[i],side='left'))
        if target>=len(ready['time_s']):
            continue
        if ready['time_s'][target]-grid[i]>10. or ready['time_s'][target]>=ready['limit']-300.:
            continue
        good=(book['valid'][target] and not book['reset'][target]
            and book['ask'][target]-book['bid'][target]<=2*ready['tick']+1e-9)
        if not good:
            continue
        assert target>previous
        previous=target
        rows.append([i,target,int(pulse[i]),int(own['now'][i]),int(peer['now'][i])])
    return np.asarray(rows,dtype=np.float64).reshape((-1,5))


def build(ready: dict, books: dict, sync: dict, delay: int, max_age: int) -> dict:
    """機能: 全場で同じ七仮説・二窓・二強度・共同対照を計算し、疎な新規根拠を保存する。

    引数: ready/books/sync(dict)、delay/max_age(int)。返り値: 条件入口キーごとの口座候補(dict)。
    売買損益や未来の結果を読み込まない。
    """
    output={}
    for session in sorted(sync):
        grid=sync[session]['grid']
        for window in (60,300):
            stats={s:(features(grid,delay,window,max_age,ready[(session,s)],books[(session,s)])
                      if (session,s) in ready and (session,s) in books else empty_features(len(grid))) for s in SYMBOLS}
            for symbol in SYMBOLS:
                peer='NK225' if symbol=='TOPIX' else 'TOPIX'
                key=session,symbol
                if key not in ready or key not in books:
                    continue
                for level in (0,1):
                    for paired in (True,False):
                        states,valid=conditions(stats[symbol],stats[peer],window,level,paired)
                        for family in range(7):
                            signal_key=f'{"J" if paired else "S"}{family+1}_W{window}_L{level}'
                            pulse=event_pulses(grid,states[family],valid)
                            mapped=map_pulses(grid,pulse,stats[symbol],stats[peer],ready[key],books[key])
                            output.setdefault(signal_key,{})[key]=dict(candidates=mapped,
                                states=states[family],valid=valid,pulse=pulse,
                                own_source=stats[symbol]['now'],peer_source=stats[peer]['now'])
    return output
