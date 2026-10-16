"""最良気配の価格経路と、完全深板に基づく旧Q・OFIの資格を分離する。"""

from collections import deque
import importlib.util
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[3]
_SPEC=importlib.util.spec_from_file_location('完全板入力94内の厳密コピー',Path(__file__).parent/'strict_board.py')
LEGACY=importlib.util.module_from_spec(_SPEC);sys.modules[_SPEC.name]=LEGACY;_SPEC.loader.exec_module(LEGACY)
WINDOWS=(30,60,180,300,600)
RANGES=(60,180)


def price_masks(ready: dict,book: dict) -> dict:
    """機能: 最良気配と最良数量及び原行連続から、価格だけの資格を導出する。

    引数: ready(dict、seq/time_s/tick)、book(dict、bid/ask/bid_qty/ask_qty/reset/reset_reason)。
    返り値: valid/reset/reset_reason/mid等の生行別配列(dict)。
    初回・原行gap・時計逆行を無視しない。時計をソート又は補完しない。
    旧bit1の深板不正直後は初回と分ける。旧深板・出来高resetを価格resetへ転用しない。
    """
    times=np.asarray(ready['time_s']);seq=np.asarray(ready['seq']);tick=float(ready['tick'])
    n=len(times)
    assert times.ndim==seq.ndim==1 and len(seq)==n
    assert np.isfinite(times).all() and np.isfinite(tick) and tick>0
    assert np.issubdtype(seq.dtype,np.integer) and (seq>=0).all()
    assert (np.diff(seq)>0).all(), '原行番号の重複・逆行は正常化しません'
    assert (np.diff(times)>=0).all(), '代理時計逆行はソートせず入力を拒否します'
    for field in ('bid','ask','bid_qty','ask_qty'):
        assert np.asarray(book[field]).ndim==1 and len(book[field])==n, field
    for field in ('seq','time_s'):
        if field in book:np.testing.assert_array_equal(book[field],ready[field])
    reason=np.asarray(book.get('reset_reason',np.zeros(n,np.uint8)),dtype=np.int64)
    assert len(reason)==n
    assert ((reason>=0)&((reason&~31)==0)).all(), '未定義reset理由を無視しません'
    if 'reset' in book:assert np.array_equal(np.asarray(book['reset'],dtype=bool),reason!=0)
    bid=np.asarray(book['bid']);ask=np.asarray(book['ask'])
    bqty=np.asarray(book['bid_qty']);aqty=np.asarray(book['ask_qty'])
    path_valid=(np.isfinite(bid)&np.isfinite(ask)&(bid>0)&(ask>bid)
                &np.isfinite(bqty)&np.isfinite(aqty)&(bqty>0)&(aqty>0))
    endpoint_valid=path_valid&(ask-bid<=2*tick+1e-9)
    price_reason=np.zeros(n,np.uint8)
    if n:price_reason[0]=1
    if n>1:price_reason[1:]|=np.where(np.diff(seq)!=1,2,0).astype(np.uint8)
    # 原比較が既に時計・原行の破綻を記録した場合も保守的に保持する。
    price_reason|=(reason&(2|8)).astype(np.uint8)
    mid=(bid+ask)/2.
    mid[~path_valid]=np.nan
    return dict(valid=path_valid,path_valid=path_valid,endpoint_valid=endpoint_valid,
                reset=price_reason!=0,reset_reason=price_reason,mid=mid,
                first=np.r_[True,np.zeros(max(0,n-1),bool)] if n else np.zeros(0,bool),
                sequence_gap=(price_reason&2)!=0,clock_reverse=(price_reason&8)!=0,
                best_price_or_quantity_invalid=~path_valid,
                spread_endpoint_invalid=path_valid&~endpoint_valid)


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


def price_features(grid: np.ndarray,delay: int,ready: dict,book: dict,max_age: float=30.) -> dict:
    """機能: 最良気配価格の窓・高安だけを、元Q/Fを参照せず独立生成する。

    引数: grid(float配列)、delay(int)、ready/book(dict)、max_age(float)。
    返り値: current/windows/ranges/price_quality(dict)。Q/F・損益は生成しない。
    総変動は同時計先頭の中値だけ、レンジは採用現在先頭を排除する。
    """
    times=ready['time_s'];tick=ready['tick'];n=len(times)
    assert n>0
    assert grid.ndim==1 and np.isfinite(grid).all() and (np.diff(grid)>=0).all()
    assert delay>=0 and max_age>=0
    quality=price_masks(ready,book)
    endpoint=quality['endpoint_valid']
    now,age=LEGACY.asof_indices(grid-delay,times,endpoint,quality['reset'],max_age)
    safe_now=np.maximum(now,0)
    raw_seq=ready['seq'][safe_now].copy();raw_seq[now<0]=-1
    source_time=times[safe_now].copy();source_time[now<0]=np.nan
    current=dict(index=now,age=age,actual_age=age+delay,valid=now>=0,
                 raw_seq=raw_seq,time_s=source_time)
    for field in ('mid','bid','ask','last'):
        source=quality['mid'] if field=='mid' else book[field] if field in book else ready[field]
        a=source[safe_now].copy();a[now<0]=np.nan;current[field]=a
    current['last_valid']=current['valid']&np.isfinite(current['last'])&(current['last']>0)
    current['spread_ticks']=(current['ask']-current['bid'])/tick
    first=np.flatnonzero(np.r_[True,np.diff(times)!=0])
    first_prices=quality['mid'][first]
    changes=np.abs(np.diff(first_prices))
    # 不正行に接する差は未観測。窓はbrokenで必ず拒否し、後続正常窓へNaNを感染させない。
    increments=np.where(np.isfinite(changes),changes,0.)
    tv=np.r_[0.,np.cumsum(increments)]
    now_position=np.searchsorted(first,safe_now,side='left')
    broken=np.r_[0,np.cumsum(~quality['path_valid']|quality['reset'],dtype=np.int64)]
    output=dict(current=current,windows={},ranges={},price_quality=quality)
    for window in WINDOWS:
        old,old_age=LEGACY.asof_indices(grid-delay-window,times,endpoint,quality['reset'],max_age)
        safe_old=np.maximum(old,0);old_position=np.searchsorted(first,safe_old,side='left')
        available=(now>=0)&(old>=0);same=available&(old==now)
        crossed=available&((broken[safe_now+1]-broken[safe_old+1])>0)
        valid=available&(old<now)&~crossed
        displacement=quality['mid'][safe_now]-quality['mid'][safe_old]
        variation=tv[now_position]-tv[old_position]
        efficiency=np.full(len(grid),np.nan);good=valid&(variation>0)
        efficiency[good]=np.abs(displacement[good])/variation[good]
        assert np.all(efficiency[good]<=1+1e-9)
        values=dict(old=old,now=now,old_age=old_age,source_valid=valid,same_row=same,
            reset_or_invalid_cross=crossed,zero_variation=valid&(variation<=0),
            unique_observations=(now_position-old_position+1).astype(np.int32),
            actual_seconds=times[safe_now]-times[safe_old],ret_bp=displacement/quality['mid'][safe_old]*10000.,
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
            position[position_valid]=(quality['mid'][safe_now][position_valid]-low[position_valid])/width[position_valid]
            bounds=dict(old=old,now=now,source_valid=range_valid,position_valid=position_valid,
                unique_observations=count,high=high,low=low,width=width,position=position,
                high_distance_ticks=(quality['mid'][safe_now]-high)/tick,
                low_distance_ticks=(quality['mid'][safe_now]-low)/tick,
                first_time=times[safe_old],last_time=times[first[np.maximum(now_position-1,0)]])
            for field in ('high','low','width','high_distance_ticks','low_distance_ticks','first_time','last_time'):
                bounds[field][~range_valid]=np.nan
            bounds['unique_observations'][~range_valid]=0
            output['ranges'][window]=bounds
    return output


def market_features(grid: np.ndarray,delay: int,ready: dict,book: dict,snapshot: dict,
                    max_age: float=30.) -> dict:
    """機能: 独立価格素材へ旧完全板のQ/Fを別indexのまま添える。

    引数: grid(ndarray[float])、delay(int)、ready/book/snapshot(dict)、max_age(float)。
    返り値: dictは価格current/windows/ranges、旧q_current/flow及びprice_quality。
    Qは価格と同じ源のときだけcurrent.q_valid=True。他の行の数量を貼り合わせない。
    """
    assert len(book['valid'])==len(snapshot['valid'])==len(ready['time_s'])
    output=price_features(grid,delay,ready,book,max_age)
    legacy=LEGACY.market_features(grid,delay,ready,book,snapshot,windows=(15,30),max_age=max_age)
    current=output['current'];q_current=legacy['current'];now=current['index'];safe_now=np.maximum(now,0)
    q_same=(now>=0)&q_current['valid']&(now==q_current['index'])
    current.update(q_valid=q_same,q_index=q_current['index'].copy(),q_same_source=q_same.copy())
    for field in ('best_imbalance','depth_imbalance'):
        values=snapshot[field][safe_now].copy();values[~q_same]=np.nan;current[field]=values
    output.update(q_current=q_current,flow=legacy['windows'])
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
