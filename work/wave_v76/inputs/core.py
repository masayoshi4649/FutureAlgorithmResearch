"""二市場の即時表示板と短いOFI履歴を、代理時計の厳密過去参照だけで取り出す。"""

import math

import numpy as np


SNAPSHOT_FIELDS=('best_imbalance','microprice','micro_offset_ticks','weighted_bid_qty','weighted_ask_qty',
                 'depth_imbalance','bid_weighted_distance','ask_weighted_distance')


def snapshot_values(raw: dict,tick: float) -> dict:
    """機能: 原本一行だけから最良数量偏りと距離加重10段偏りを求める。

    引数: raw(dict)、tick(float)。返り値: 八つの有限スカラーとvalid、又は欠損(dict)。
    各側の最良価格からの呼値距離に1/(1+距離)を掛ける。欠損段・価格逆転・負数量は全段無効。
    microprice=(bid*askQty+ask*bidQty)/(bidQty+askQty)の数量加重中値代理で、将来価格モデルではない。
    """
    missing={k:math.nan for k in SNAPSHOT_FIELDS}
    missing['valid']=False
    if not math.isfinite(tick) or tick<=0:
        return missing
    sides=[]
    for label,direction in (('Buy',-1),('Sell',1)):
        levels=[]
        previous=None
        for depth in range(1,11):
            item=raw.get(f'{label}{depth}') or {}
            try:
                price,quantity=float(item['Price']),float(item['Qty'])
            except (KeyError,TypeError,ValueError):
                return missing
            if not math.isfinite(price) or not math.isfinite(quantity) or price<=0 or quantity<0:
                return missing
            if previous is not None and direction*(price-previous)<=0:
                return missing
            previous=price
            levels.append((price,quantity))
        best=levels[0][0]
        total=distance_total=0.
        for price,quantity in levels:
            distance=direction*(price-best)/tick
            weighted=quantity/(1.+distance)
            total+=weighted
            distance_total+=weighted*distance
        sides.append((best,levels[0][1],total,distance_total/total if total>0 else math.nan))
    bid,bq,btotal,bdistance=sides[0]
    ask,aq,atotal,adistance=sides[1]
    if tick<=0 or not 0<bid<ask or bq<=0 or aq<=0:
        return missing
    imbalance=(bq-aq)/(bq+aq)
    micro=(bid*aq+ask*bq)/(bq+aq)
    return dict(best_imbalance=imbalance,microprice=micro,micro_offset_ticks=(micro-(bid+ask)/2.)/tick,
        weighted_bid_qty=btotal,weighted_ask_qty=atotal,depth_imbalance=(btotal-atotal)/(btotal+atotal),
        bid_weighted_distance=bdistance,ask_weighted_distance=adistance,valid=True)


def asof_indices(targets: np.ndarray,times: np.ndarray,valid: np.ndarray,reset: np.ndarray,
                 max_age: float=30.) -> tuple[np.ndarray,np.ndarray]:
    """機能: 参照期限より厳密に前の最新時計の先頭準備行だけを採用する。

    引数: targets/times(float64 ndarray)、valid/reset(bool ndarray)、max_age(float)。
    返り値: 行番号int32と期限からの古さfloat32(tuple[ndarray,ndarray])。欠測は-1/NaN。
    同時計後続や古い行への救済なし。実受信時刻がないため代理時計上の過去対応に限る。
    """
    assert targets.ndim==times.ndim==valid.ndim==reset.ndim==1 and len(times)==len(valid)==len(reset)
    assert (np.diff(times)>=0).all() and max_age>=0
    indices=np.full(len(targets),-1,dtype=np.int32)
    ages=np.full(len(targets),np.nan,dtype=np.float32)
    if not len(times):return indices,ages
    ends=np.searchsorted(times,targets,side='left')-1
    present=(ends>=0)&np.isfinite(targets)
    positions=np.flatnonzero(present)
    first=np.searchsorted(times,times[ends[present]],side='left')
    elapsed=targets[present]-times[first]
    good=valid[first]&~reset[first]&(elapsed>0)&(elapsed<=max_age)
    indices[positions[good]]=first[good].astype(np.int32)
    ages[positions[good]]=elapsed[good].astype(np.float32)
    return indices,ages


def empty_market(size: int,windows: tuple[int,...]) -> dict:
    """機能: 相手の系列が空の場合に、全参照不能の同じ構造を作る。

    引数: size(int)、windows(tuple[int,...])。返り値: 欠測入力(dict)。
    欠測を中立、既知のOFIゼロ、同一観測行と呼ばない。
    """
    index=np.full(size,-1,dtype=np.int32)
    nan=np.full(size,np.nan)
    current={k:nan.copy() for k in SNAPSHOT_FIELDS}
    current.update(index=index,age=nan.copy(),actual_age=nan.copy(),valid=np.zeros(size,bool),spread_ticks=nan.copy())
    output=dict(current=current,windows={})
    for window in windows:
        values={k:nan.copy() for k in ('ofi_ratio','ofi_sum','ofi_abs_sum','actual_seconds','mid_change_bp',
            'bid_change_ticks','ask_change_ticks','best_imbalance_change','depth_imbalance_change','old_age')}
        values.update(now=index.copy(),old=index.copy(),nonzero_ofi_count=np.zeros(size,np.int32))
        values.update({k:np.zeros(size,bool) for k in ('source_valid','valid','same_row','reset_or_invalid_cross','missing_ofi','zero_ofi_denominator')})
        output['windows'][window]=values
    return output


def market_features(grid: np.ndarray,delay: int,ready: dict,book: dict,snapshot: dict,
                    windows: tuple[int,...]=(5,15,30,60),max_age: float=30.) -> dict:
    """機能: 一市場の即時板と短期OFI・価格進行を指定判断グリッドへ接続する。

    引数: grid(ndarray)、delay(int)、ready/book/snapshot(dict)、windows(tuple[int,...])、max_age(float)。
    返り値: currentとwindowsの参照行・特徴・品質フラグ(dict)。同一始終行は無効とする。
    OFIはold行を除きnow行を含む最良OFIの和/絶対和。ゼロ分母と欠測、証拠件数を別記する。
    """
    times=ready['time_s'];tick=ready['tick']
    if not len(times):
        return empty_market(len(grid),windows)
    endpoint=book['valid']&snapshot['valid']&np.isfinite(book['bid'])&np.isfinite(book['ask'])
    endpoint&=(book['bid']>0)&(book['ask']>book['bid'])&(book['ask']-book['bid']<=2*tick+1e-9)
    now,age=asof_indices(grid-delay,times,endpoint,book['reset'],max_age)
    current=dict(index=now,age=age,actual_age=age+delay,valid=now>=0)
    safe_now=np.maximum(now,0)
    for field in SNAPSHOT_FIELDS:
        a=snapshot[field][safe_now].copy();a[now<0]=np.nan;current[field]=a
    current['spread_ticks']=(book['ask'][safe_now]-book['bid'][safe_now])/tick
    current['spread_ticks'][now<0]=np.nan
    broken=np.r_[0,np.cumsum(~book['valid']|book['reset']|~snapshot['valid'],dtype=np.int64)]
    ofi=book['best_ofi'];finite=np.isfinite(ofi)
    signed=np.r_[0.,np.cumsum(np.where(finite,ofi,0.))]
    absolute=np.r_[0.,np.cumsum(np.where(finite,np.abs(ofi),0.))]
    unknown=np.r_[0,np.cumsum(~finite,dtype=np.int64)]
    events=np.r_[0,np.cumsum(finite&(np.abs(ofi)>0),dtype=np.int64)]
    output=dict(current=current,windows={})
    for window in windows:
        old,old_age=asof_indices(grid-delay-window,times,endpoint,book['reset'],max_age)
        available=(now>=0)&(old>=0)
        safe_old=np.maximum(old,0)
        same=available&(now==old)
        crossing=available&((broken[safe_now+1]-broken[safe_old+1])>0)
        source_valid=available&(old<now)&~crossing
        denominator=absolute[safe_now+1]-absolute[safe_old+1]
        numerator=signed[safe_now+1]-signed[safe_old+1]
        missing_ofi=source_valid&((unknown[safe_now+1]-unknown[safe_old+1])>0)
        zero_denominator=source_valid&(denominator<=0)
        valid=source_valid&~missing_ofi&~zero_denominator
        ratio=np.full(len(grid),np.nan)
        ratio[valid]=numerator[valid]/denominator[valid]
        count=np.zeros(len(grid),dtype=np.int32)
        count[source_valid]=(events[safe_now[source_valid]+1]-events[safe_old[source_valid]+1]).astype(np.int32)
        values=dict(now=now,old=old,old_age=old_age,source_valid=source_valid,valid=valid,same_row=same,
            reset_or_invalid_cross=crossing,missing_ofi=missing_ofi,zero_ofi_denominator=zero_denominator,
            nonzero_ofi_count=count,ofi_ratio=ratio,ofi_sum=numerator,ofi_abs_sum=denominator,
            actual_seconds=times[safe_now]-times[safe_old],mid_change_bp=(book['mid'][safe_now]/book['mid'][safe_old]-1.)*10000.,
            bid_change_ticks=(book['bid'][safe_now]-book['bid'][safe_old])/tick,
            ask_change_ticks=(book['ask'][safe_now]-book['ask'][safe_old])/tick,
            best_imbalance_change=snapshot['best_imbalance'][safe_now]-snapshot['best_imbalance'][safe_old],
            depth_imbalance_change=snapshot['depth_imbalance'][safe_now]-snapshot['depth_imbalance'][safe_old])
        for field in ('actual_seconds','mid_change_bp','bid_change_ticks','ask_change_ticks','best_imbalance_change','depth_imbalance_change','ofi_sum','ofi_abs_sum'):
            values[field][~source_valid]=np.nan
        output['windows'][window]=values
    return output


def session_features(ready: dict,books: dict,snapshots: dict,session: str,delay: int) -> dict:
    """機能: 場末の保有判断まで共通5秒グリッドで双方の板特徴を作る。

    引数: ready/books/snapshots(dict)、session(str)、delay(int)。返り値: gridとmarkets(dict)。
    start+300からlimit-60を含む。新規禁止limit-300以後の判定用途は算法側が分ける。
    """
    r=ready[(session,'TOPIX')]
    grid=np.arange(r['start']+300.,r['limit']-60.+1e-6,5.,dtype=np.float64)
    return dict(grid=grid,markets={s:market_features(grid,delay,ready[(session,s)],books[(session,s)],snapshots[(session,s)])
        for s in ('TOPIX','NK225')})
