"""原本と確定分足だけから中心乖離と補充・圧力の観測材料を用意する。"""

import numpy as np
import pandas as pd
from numba import njit


@njit(cache=True)
def rolling_observations(times,mid,ofi,buy,sell,valid,reset,event_i,event_side,event_price,bid,ask):
    """機能: 公開時点までの30秒圧力と補充を更新し、未来行を参照しない。

    引数: 全て原本順配列(ndarray)。返り値: 30秒OFI・執行偏り・補充確認・直前価格・分類済数量の6列(ndarray)。
    秒は最終約定時計の代理であり実受信時計ではない。補充は同一主体を意味しない。
    """
    n=len(times)
    out=np.zeros((n,6))
    j=0
    total_ofi=total_buy=total_sell=0.
    ep=0
    last_buy_time=last_sell_time=-1e30
    last_buy_price=last_sell_price=0.
    for i in range(n):
        if reset[i] or not valid[i]:
            total_ofi=total_buy=total_sell=0.
            j=i
            last_buy_time=last_sell_time=-1e30
        total_ofi+=ofi[i] if np.isfinite(ofi[i]) else 0.
        total_buy+=buy[i] if np.isfinite(buy[i]) else 0.
        total_sell+=sell[i] if np.isfinite(sell[i]) else 0.
        while j<i and times[j]<times[i]-30.:
            total_ofi-=ofi[j] if np.isfinite(ofi[j]) else 0.
            total_buy-=buy[j] if np.isfinite(buy[j]) else 0.
            total_sell-=sell[j] if np.isfinite(sell[j]) else 0.
            j+=1
        while ep<len(event_i) and event_i[ep]<=i:
            if event_i[ep]==i and valid[i]:
                if event_side[ep]>0 and event_price[ep]==bid[i]:
                    last_buy_time=times[i]
                    last_buy_price=event_price[ep]
                elif event_side[ep]<0 and event_price[ep]==ask[i]:
                    last_sell_time=times[i]
                    last_sell_price=event_price[ep]
            ep+=1
        out[i,0]=total_ofi
        out[i,1]=total_buy-total_sell
        out[i,2]=times[i]-last_buy_time<=30. and bid[i]>=last_buy_price
        out[i,3]=times[i]-last_sell_time<=30. and ask[i]<=last_sell_price
        out[i,4]=mid[j]
        out[i,5]=total_buy+total_sell
    return out


def build(ready: dict,quotes: dict,tick_data: dict,events: np.ndarray) -> dict:
    """機能: 確定1分終値の平均と効率を次分最初の原本行から公開する。

    引数: ready/quotes/tick_data(dict)、events(ndarray)。返り値: 原本長の因果材料(dict)。
    5分平均は5本中4本以上、直前足実観測が必要。15分効率は16本中13本以上を要求する。
    """
    times=ready['time_s']
    mid=quotes['mid']
    bucket=np.floor(times/60).astype(np.int64)
    change=np.flatnonzero(np.r_[False,bucket[1:]!=bucket[:-1]])
    endpoints=np.r_[change-1,len(mid)-1]
    full=np.arange(bucket[0],bucket[-1]+1)
    observed=pd.Series(mid[endpoints],index=bucket[endpoints])
    close=observed.reindex(full).ffill()
    seen=pd.Series(np.isin(full,observed.index),index=full)
    center=close.rolling(5,min_periods=5).mean()
    ready5=seen&seen.rolling(5,min_periods=5).sum().ge(4)
    variation=close.diff().abs().rolling(15,min_periods=15).sum()
    er=(close-close.shift(15)).abs()/variation.replace(0,np.nan)
    er=er.mask(variation.eq(0),0.)
    er=er.where(seen&seen.rolling(16,min_periods=16).sum().ge(13))
    source=bucket-1-full[0]
    good=(source>=0)&(source<len(full))
    safe=np.clip(source,0,len(full)-1)
    mean=center.to_numpy()[safe]
    mean[~good|~ready5.to_numpy()[safe]]=np.nan
    efficiency=er.to_numpy()[safe]
    efficiency[~good]=np.nan
    np.testing.assert_array_equal(times,tick_data['time_s'])
    np.testing.assert_array_equal(ready['seq'],tick_data['seq'])
    obs=rolling_observations(times,mid,tick_data['best_ofi'],tick_data['exec_buy_qty'],tick_data['exec_sell_qty'],
        tick_data['valid'],tick_data['reset'],events['i'],events['side'],events['price'],quotes['bid'],quotes['ask'])
    decision=np.r_[False,np.floor(times[1:]/10)!=np.floor(times[:-1]/10)]
    return dict(center=mean,efficiency=efficiency,observations=obs,decision=decision,valid=tick_data['valid'])


def signals(material: dict,mid: np.ndarray,width: float,gate: int=0) -> np.ndarray:
    """機能: 中心から1.5幅離れた側へ戻りを狙う候補を公開時点だけで作る。

    引数: material(dict)、mid(ndarray)、width(float)、gate(int:0なし1低効率2補充圧力3両方)。
    返り値: 各原本行の方向、未成立0(ndarray)。条件不明は許可しない。
    """
    deviation=material['center']-mid
    side=np.where(deviation>=1.5*width,1,np.where(deviation<=-1.5*width,-1,0)).astype(np.int8)
    allowed=material['decision']&material['valid']
    if gate in (1,3):
        allowed&=material['efficiency']<=.3
    if gate in (2,3):
        obs=material['observations']
        refill=np.where(side>0,obs[:,2],obs[:,3])>0
        allowed&=refill&(side*obs[:,0]>0)&(side*obs[:,1]>=0)&(obs[:,5]>0)&(side*(mid-obs[:,4])>=0)
    return np.where(allowed,side,0).astype(np.int8)
