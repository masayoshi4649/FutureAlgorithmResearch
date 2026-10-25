"""短い準備で利用できる価格差と、当時までの活動幅を構成する。"""

import numpy as np
from numba import njit
from run142 import first


@njit(cache=True)
def rolling_range(times, price, valid, seconds):
    """
    機能: 原行順を保ち、現在行までの窓内高安幅を単調キューで計算する。
    引数: times/price/valid(ndarray)、seconds(float)は窓幅。時刻は非減少。
    返り値: ndarrayは現在原行までの幅。同時計の後続原行は含まない。
    """
    n=len(times);out=np.full(n,np.nan);hi=np.zeros(n,np.int64);lo=np.zeros(n,np.int64)
    hs=he=ls=le=0
    for i in range(n):
        while hs<he and times[hi[hs]]<times[i]-seconds:hs+=1
        while ls<le and times[lo[ls]]<times[i]-seconds:ls+=1
        if valid[i] and np.isfinite(price[i]):
            while he>hs and price[hi[he-1]]<=price[i]:he-=1
            while le>ls and price[lo[le-1]]>=price[i]:le-=1
            hi[he]=i;he+=1;lo[le]=i;le+=1
        if hs<he and ls<le:out[i]=price[hi[hs]]-price[lo[ls]]
    return out


def prepare(packet,base):
    """
    機能: 40分準備を必須としない巡回担当用36列を因果的に作成する。
    引数: packet(dict)は原資料、base(dict)は第一巡の30列特徴。
    返り値: dictは市場別資料。元の入力と第一巡特徴を変更しない。

    0～29列の意味は基本維持。ただし5分差は原行300秒差、Rはmax(公開ATR,2短ATR,8呼値)。
    30/31列は自他300秒高安幅、32/33は自他気配差、34/35は自他呼値。
    中期未確定はNaNのままとし、短期一致だけの入口と中期支持の継続を区別する。
    """
    result={}
    for symbol,item in base.items():
        ready=item['ready'];q=item['quotes'];a=item['features'].copy();t=ready['time_s']
        assert np.all(np.diff(t)>=0.)
        short=np.where(np.isfinite(a[:,11]),2.*a[:,11],0.)
        published=np.where(np.isfinite(ready['atr']),ready['atr'],0.)
        risk=np.maximum(np.maximum(short,published),8.*ready['tick'])
        a[:,9]=risk
        change=first.original.early139._changes
        for column,seconds in ((12,30.),(13,120.)):
            a[:,column]=change(t,a[:,10],risk,seconds)[0]
        a[:,3]=change(t,a[:,10],risk,300.)[0]*risk
        span=rolling_range(t,a[:,10],q['quote_valid'],300.)
        a=np.column_stack((a,span,np.full(len(t),np.nan),q['ask']-q['bid'],np.full(len(t),np.nan),np.full(len(t),ready['tick']),np.full(len(t),np.nan)))
        result[symbol]=dict(item,features=a)
    for symbol,item in result.items():
        peer=result['TOPIX' if symbol=='NK225' else 'NK225'];t=item['ready']['time_s'];pt=peer['ready']['time_s']
        index=np.searchsorted(pt,t,side='left')-1;safe=np.maximum(0,index)
        valid=(index>=0)&(t-pt[safe]<=15.)
        a=item['features'];b=peer['features']
        for target,source in ((14,3),(18,9),(19,10),(20,12),(21,13),(31,30),(33,32),(35,34)):
            a[:,target]=np.nan;a[valid,target]=b[safe[valid],source]
        a[:,22]=np.nan;a[valid,22]=pt[safe[valid]]
    return result
