"""同時計先頭の過去価格から、共同方向・総変動・直前レンジの入力素材を作る。"""

from collections import deque
import importlib.util
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[3]
_SPEC=importlib.util.spec_from_file_location('即時板入力76読取',ROOT/'work/wave_v76/inputs/core.py')
LEGACY=importlib.util.module_from_spec(_SPEC);sys.modules[_SPEC.name]=LEGACY;_SPEC.loader.exec_module(LEGACY)
WINDOWS=(30,60,180,300,600)
RANGES=(60,180)


def extrema(prices: np.ndarray,left: np.ndarray,right: np.ndarray) -> tuple[np.ndarray,np.ndarray]:
    """機能: 単調に進む過去区間の高安を、現在行を含めず求める。

    引数: prices(float配列)、left/right(int配列)。返り値: 高値と安値(float配列のtuple)。
    区間はleft以上right未満。右端・左端が等しい空範囲はNaNのまま残す。
    """
    high=np.full(len(left),np.nan);low=high.copy();up=deque();down=deque();cursor=0
    for i,(start,stop) in enumerate(zip(left,right)):
        while cursor<stop:
            while up and prices[up[-1]]<=prices[cursor]:up.pop()
            while down and prices[down[-1]]>=prices[cursor]:down.pop()
            up.append(cursor);down.append(cursor);cursor+=1
        while up and up[0]<start:up.popleft()
        while down and down[0]<start:down.popleft()
        if start<stop:
            high[i]=prices[up[0]];low[i]=prices[down[0]]
    return high,low


def market_features(grid: np.ndarray,delay: int,ready: dict,book: dict,snapshot: dict,
                    max_age: float=30.) -> dict:
    """機能: 過去価格窓・価格効率・直前レンジと旧板Q/Fを共通格子へ接続する。

    引数: grid(float配列)、delay(int)、ready/book/snapshot(dict)、max_age(float)。
    返り値: current/windows/ranges/flow(dict)。新規や途中の採否、未来損益は計算しない。
    総変動は同時計先頭の中値だけ、レンジは採用現在先頭を排除する。
    """
    times=ready['time_s'];tick=ready['tick'];n=len(times)
    assert n>0 and len(book['valid'])==len(snapshot['valid'])==n
    endpoint=book['valid']&np.isfinite(book['bid'])&np.isfinite(book['ask'])
    endpoint&=(book['bid']>0)&(book['ask']>book['bid'])&(book['ask']-book['bid']<=2*tick+1e-9)
    now,age=LEGACY.asof_indices(grid-delay,times,endpoint,book['reset'],max_age)
    safe_now=np.maximum(now,0)
    current=dict(index=now,age=age,actual_age=age+delay,valid=now>=0,
                 q_valid=(now>=0)&snapshot['valid'][safe_now])
    for field in ('mid','bid','ask','last'):
        a=book[field][safe_now].copy();a[now<0]=np.nan;current[field]=a
    for field in ('best_imbalance','depth_imbalance'):
        a=snapshot[field][safe_now].copy();a[~current['q_valid']]=np.nan;current[field]=a
    current['spread_ticks']=(current['ask']-current['bid'])/tick
    first=np.flatnonzero(np.r_[True,np.diff(times)!=0])
    first_prices=book['mid'][first]
    tv=np.r_[0.,np.cumsum(np.abs(np.diff(first_prices)))]
    now_position=np.searchsorted(first,safe_now,side='left')
    broken=np.r_[0,np.cumsum(~book['valid']|book['reset'],dtype=np.int64)]
    output=dict(current=current,windows={},ranges={},flow={})
    for window in WINDOWS:
        old,old_age=LEGACY.asof_indices(grid-delay-window,times,endpoint,book['reset'],max_age)
        safe_old=np.maximum(old,0);old_position=np.searchsorted(first,safe_old,side='left')
        available=(now>=0)&(old>=0);same=available&(old==now)
        crossed=available&((broken[safe_now+1]-broken[safe_old+1])>0)
        valid=available&(old<now)&~crossed
        displacement=book['mid'][safe_now]-book['mid'][safe_old]
        variation=tv[now_position]-tv[old_position]
        efficiency=np.full(len(grid),np.nan);good=valid&(variation>0)
        efficiency[good]=np.abs(displacement[good])/variation[good]
        assert np.all(efficiency[good]<=1+1e-9)
        values=dict(old=old,now=now,old_age=old_age,source_valid=valid,same_row=same,
            reset_or_invalid_cross=crossed,zero_variation=valid&(variation<=0),
            unique_observations=(now_position-old_position+1).astype(np.int32),
            actual_seconds=times[safe_now]-times[safe_old],ret_bp=displacement/book['mid'][safe_old]*10000.,
            bid_change_ticks=(book['bid'][safe_now]-book['bid'][safe_old])/tick,
            ask_change_ticks=(book['ask'][safe_now]-book['ask'][safe_old])/tick,
            displacement=displacement,total_variation=variation,efficiency=efficiency)
        for field in ('actual_seconds','ret_bp','bid_change_ticks','ask_change_ticks','displacement','total_variation'):
            values[field][~valid]=np.nan
        values['unique_observations'][~valid]=0
        output['windows'][window]=values
        if window in RANGES:
            high,low=extrema(first_prices,old_position,now_position)
            count=(now_position-old_position).astype(np.int32)
            range_valid=valid&(count>=2)&np.isfinite(high)&np.isfinite(low)
            width=high-low;position=np.full(len(grid),np.nan);position_valid=range_valid&(width>0)
            position[position_valid]=(book['mid'][safe_now][position_valid]-low[position_valid])/width[position_valid]
            bounds=dict(old=old,now=now,source_valid=range_valid,position_valid=position_valid,
                unique_observations=count,high=high,low=low,width=width,position=position,
                high_distance_ticks=(book['mid'][safe_now]-high)/tick,
                low_distance_ticks=(book['mid'][safe_now]-low)/tick,
                first_time=times[safe_old],last_time=times[first[np.maximum(now_position-1,0)]])
            for field in ('high','low','width','high_distance_ticks','low_distance_ticks','first_time','last_time'):
                bounds[field][~range_valid]=np.nan
            bounds['unique_observations'][~range_valid]=0
            output['ranges'][window]=bounds
    legacy=LEGACY.market_features(grid,delay,ready,book,snapshot,windows=(15,30),max_age=max_age)
    output['flow']=legacy['windows']
    return output


def session_features(ready: dict,books: dict,snapshots: dict,session: str,delay: int) -> dict:
    """機能: 場末までの共通5秒格子へ二市場素材を接続する。

    引数: ready/books/snapshots(dict)、session(str)、delay(int)。返り値: gridとmarkets(dict)。
    新規はlimit−300以後禁止する設計用。保有判断に使えるよう格子はlimit−60まで含む。
    """
    r=ready[(session,'TOPIX')];grid=np.arange(r['start']+300.,r['limit']-60.+1e-6,5.)
    assert all(ready[(session,s)]['start']==r['start'] and ready[(session,s)]['limit']==r['limit'] for s in ('TOPIX','NK225'))
    return dict(grid=grid,markets={s:market_features(grid,delay,ready[(session,s)],books[(session,s)],snapshots[(session,s)])
        for s in ('TOPIX','NK225')})
