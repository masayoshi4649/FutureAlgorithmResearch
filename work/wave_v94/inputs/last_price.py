"""原本のLastPriceだけから、板の執行系列とは独立した過去価格素材を作る。"""

from datetime import datetime
import importlib.util
import math
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode=True
_SPEC=importlib.util.spec_from_file_location('価格分離94の局所読取',Path(__file__).parent/'core.py')
CORE=importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name]=CORE
_SPEC.loader.exec_module(CORE)
RESET_REASONS={1:'場内の初回保存行',2:'原本行の不連続',4:'前の時計欠測',8:'前の場外観測'}


def number(value: object) -> float:
    """機能: 有限正価格だけを数値化し、欠測や不正をNaNへ区別する。

    引数: value(object)。
    返り値: floatは正常価格、又は不正を表すNaN。
    """
    if isinstance(value,bool):return math.nan
    try:result=float(value)
    except (TypeError,ValueError,OverflowError):return math.nan
    return result if math.isfinite(result) and result>0 else math.nan


def clock(value: object) -> float:
    """機能: timezone付きの原本代理時計を読み、未観測時計を補完しない。

    引数: value(object)。
    返り値: floatはUTCのepoch秒、又は不正を表すNaN。
    """
    if not isinstance(value,str) or not value:return math.nan
    try:
        stamp=datetime.fromisoformat(value)
        if stamp.tzinfo is None or stamp.utcoffset() is None:return math.nan
        result=stamp.timestamp()
    except (TypeError,ValueError,OverflowError,OSError):return math.nan
    return result if math.isfinite(result) else math.nan


def extract_last_prices(rows: object,start: float,end: float) -> dict:
    """機能: 保存順の原本行を読み、場内LastPriceと断裂だけを独立保存する。

    引数: rows(Iterable[tuple[int,dict]])は原seqとJSON、start/end(float)は場内上下限。
    返り値: dictはseq/time_s/last/valid/reset/reset_reasonと取得診断。
    正常時計で価格不正なら時刻付きNaNを保持。時計欠測は次保存行の断裂にする。
    板価格・板数量・累積出来高を一切参照せず、執行気配を作らない。
    """
    assert math.isfinite(start) and math.isfinite(end) and start<end
    sequences=[];times=[];prices=[];resets=[]
    previous_raw_seq=previous_saved_seq=None
    previous_clock=-math.inf
    pending_reason=0
    count=missing_clock=outside=invalid_price=0
    for seq,raw in rows:
        assert isinstance(seq,(int,np.integer)) and seq>=0 and isinstance(raw,dict)
        assert previous_raw_seq is None or seq>previous_raw_seq, '原本保存順を並べ替えません'
        if previous_raw_seq is not None and seq!=previous_raw_seq+1:pending_reason|=2
        previous_raw_seq=int(seq)
        count+=1
        stamp=clock(raw.get('CurrentPriceTime'))
        if not math.isfinite(stamp):
            missing_clock+=1;pending_reason|=4
            continue
        assert stamp>=previous_clock, '代理時計逆行をソート又は補完しません'
        previous_clock=stamp
        if not start<=stamp<end:
            outside+=1;pending_reason|=8
            continue
        reason=pending_reason
        if previous_saved_seq is None:reason|=1
        elif seq!=previous_saved_seq+1:reason|=2
        price=number(raw.get('CurrentPrice'))
        invalid_price+=not math.isfinite(price)
        sequences.append(seq);times.append(stamp);prices.append(price);resets.append(reason)
        previous_saved_seq=int(seq);pending_reason=0
    reason_array=np.asarray(resets,dtype=np.uint8)
    last=np.asarray(prices,dtype=np.float64)
    return dict(seq=np.asarray(sequences,dtype=np.int64),time_s=np.asarray(times,dtype=np.float64),
                last=last,valid=np.isfinite(last)&(last>0),reset=reason_array!=0,
                reset_reason=reason_array,source_kind='原本CurrentPriceのみ',start=start,end=end,
                diagnostic=dict(読取原本行=count,保存時計行=len(times),時計欠測=missing_clock,
                                場外=outside,価格不正=int(invalid_price),板参照=0,損益計算=0))


def last_price_features(grid: np.ndarray,delay: int,record: dict,max_age: float=30.) -> dict:
    """機能: 独立LastPriceの同時計先頭・厳密過去窓と直前高安を求める。

    引数: grid(ndarray[float])、delay(int)、record(dict)、max_age(float)。
    返り値: dictはcurrent/windows/ranges。価格以外のQ・OFI・執行旗は作らない。
    現在源はLP系列内indexと原seqを別記し、retained板の行と同一視しない。
    """
    times=record['time_s'];prices=record['last'];seq=record['seq'];valid=record['valid'];reset=record['reset']
    n=len(times);size=len(grid)
    assert all(len(record[k])==n for k in ('last','seq','valid','reset','reset_reason'))
    assert np.isfinite(times).all() and (np.diff(times)>=0).all() and (np.diff(seq)>0).all()
    assert grid.ndim==1 and np.isfinite(grid).all() and (np.diff(grid)>=0).all()
    assert delay>=0 and max_age>=0
    endpoint=valid&np.isfinite(prices)&(prices>0)
    now,age=CORE.LEGACY.asof_indices(grid-delay,times,endpoint,reset,max_age)
    if not n:
        nan=np.full(size,np.nan);indices=np.full(size,-1,np.int32)
        current=dict(index=indices,raw_seq=np.full(size,-1,np.int64),time_s=nan.copy(),
                     age=nan.copy(),actual_age=nan.copy(),valid=np.zeros(size,bool),
                     value=nan.copy(),last=nan.copy())
        windows={};ranges={}
        for window in CORE.WINDOWS:
            values={k:nan.copy() for k in ('old_age','actual_seconds','ret_bp','displacement','total_variation','efficiency')}
            values.update(old=indices.copy(),now=indices.copy(),old_seq=np.full(size,-1,np.int64),now_seq=np.full(size,-1,np.int64),
                          source_valid=np.zeros(size,bool),same_row=np.zeros(size,bool),reset_or_invalid_cross=np.zeros(size,bool),
                          zero_variation=np.zeros(size,bool),unique_observations=np.zeros(size,np.int32))
            windows[window]=values
            if window in CORE.RANGES:
                bounds={k:nan.copy() for k in ('high','low','width','position','first_time','last_time','high_distance_points','low_distance_points')}
                bounds.update(old=indices.copy(),now=indices.copy(),source_valid=np.zeros(size,bool),position_valid=np.zeros(size,bool),unique_observations=np.zeros(size,np.int32))
                ranges[window]=bounds
        return dict(source_kind=record['source_kind'],current=current,windows=windows,ranges=ranges)
    safe_now=np.maximum(now,0)
    value=prices[safe_now].copy();value[now<0]=np.nan
    raw_seq=seq[safe_now].copy();raw_seq[now<0]=-1
    source_time=times[safe_now].copy();source_time[now<0]=np.nan
    current=dict(index=now,raw_seq=raw_seq,time_s=source_time,age=age,actual_age=age+delay,
                 valid=now>=0,value=value,last=value.copy())
    first=np.flatnonzero(np.r_[True,np.diff(times)!=0]);first_prices=prices[first]
    changes=np.abs(np.diff(first_prices));tv=np.r_[0.,np.cumsum(np.where(np.isfinite(changes),changes,0.))]
    now_position=np.searchsorted(first,safe_now,side='left')
    broken=np.r_[0,np.cumsum(~endpoint|reset,dtype=np.int64)]
    output=dict(source_kind=record['source_kind'],current=current,windows={},ranges={})
    for window in CORE.WINDOWS:
        old,old_age=CORE.LEGACY.asof_indices(grid-delay-window,times,endpoint,reset,max_age)
        safe_old=np.maximum(old,0);old_position=np.searchsorted(first,safe_old,side='left')
        available=(now>=0)&(old>=0);same=available&(old==now)
        crossed=available&((broken[safe_now+1]-broken[safe_old+1])>0)
        usable=available&(old<now)&~crossed
        displacement=prices[safe_now]-prices[safe_old];variation=tv[now_position]-tv[old_position]
        efficiency=np.full(size,np.nan);good=usable&(variation>0)
        efficiency[good]=np.abs(displacement[good])/variation[good]
        assert np.all(efficiency[good]<=1+1e-9)
        old_seq=seq[safe_old].copy();old_seq[old<0]=-1
        values=dict(old=old,now=now,old_seq=old_seq,now_seq=raw_seq.copy(),old_age=old_age,
                    source_valid=usable,same_row=same,reset_or_invalid_cross=crossed,
                    zero_variation=usable&(variation<=0),unique_observations=(now_position-old_position+1).astype(np.int32),
                    actual_seconds=times[safe_now]-times[safe_old],ret_bp=displacement/prices[safe_old]*10000.,
                    displacement=displacement,total_variation=variation,efficiency=efficiency)
        for field in ('actual_seconds','ret_bp','displacement','total_variation'):values[field][~usable]=np.nan
        values['unique_observations'][~usable]=0
        output['windows'][window]=values
        if window in CORE.RANGES:
            high,low=CORE.extrema(first_prices,old_position,now_position)
            count=(now_position-old_position).astype(np.int32)
            range_valid=usable&(count>=2)&np.isfinite(high)&np.isfinite(low)
            width=high-low;position=np.full(size,np.nan);position_valid=range_valid&(width>0)
            position[position_valid]=(prices[safe_now][position_valid]-low[position_valid])/width[position_valid]
            bounds=dict(old=old,now=now,source_valid=range_valid,position_valid=position_valid,
                        unique_observations=count,high=high,low=low,width=width,position=position,
                        high_distance_points=prices[safe_now]-high,low_distance_points=prices[safe_now]-low,
                        first_time=times[safe_old],last_time=times[first[np.maximum(now_position-1,0)]])
            for field in ('high','low','width','high_distance_points','low_distance_points','first_time','last_time'):bounds[field][~range_valid]=np.nan
            bounds['unique_observations'][~range_valid]=0
            output['ranges'][window]=bounds
    return output
