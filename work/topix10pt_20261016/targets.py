"""公開時の現在Lastを固定し、後続の採用済み観測価格で十ptの先着を採点する。"""

from __future__ import annotations

import numpy as np
from numba import njit


SIDES=np.array([1,-1],dtype=np.int8)
ADVERSE_POINTS=np.array([2.5,5.,10.],dtype=np.float64)
FAVORABLE_POINTS=10.
CODE_NAMES={1:'順方向10pt先着',-1:'指定逆行幅先着',0:'観測窓末未解決',
    2:'原EOF未解決',-2:'公開基準なし'}

# ----------------------------------------


@njit(cache=False)
def _tree(values):
    """
    機能: 採用済み単一価格の最大・最小木を構築する。
    引数: values(ndarray[float64,M]) は有限正Last。
    返り値: tuple[ndarray,ndarray,int] は最大木・最小木・葉数。
    """
    size=1
    while size<len(values):size*=2
    maximum=np.full(size*2,-np.inf,np.float64)
    minimum=np.full(size*2,np.inf,np.float64)
    for i in range(len(values)):
        maximum[size+i]=values[i];minimum[size+i]=values[i]
    for i in range(size-1,0,-1):
        maximum[i]=max(maximum[i*2],maximum[i*2+1])
        minimum[i]=min(minimum[i*2],minimum[i*2+1])
    return maximum,minimum,size


@njit(cache=False)
def _first(maximum,minimum,node,lo,hi,left,right,level,above):
    """
    機能: 指定区間の閾値を等号付きで満たす最初の価格位置を探す。
    引数: maximum/minimum(ndarray)、node/lo/hi/left/right(int)、level(float)、above(bool)。
    返り値: int は採用済み価格列の位置又は未到達−1。
    """
    if right<=lo or hi<=left:return -1
    if above:
        if maximum[node]<level:return -1
    elif minimum[node]>level:return -1
    if hi-lo==1:return lo
    middle=(lo+hi)//2
    found=_first(maximum,minimum,node*2,lo,middle,left,right,level,above)
    if found>=0:return found
    return _first(maximum,minimum,node*2+1,middle,hi,left,right,level,above)


@njit(cache=False)
def _range(maximum,minimum,left,right,size):
    """
    機能: 空でない半開価格区間の最大と最小を得る。
    引数: maximum/minimum(ndarray)、left/right/size(int)。
    返り値: tuple[float,float] は最大と最小。
    """
    high=-np.inf;low=np.inf;left+=size;right+=size
    while left<right:
        if left&1:
            high=max(high,maximum[left]);low=min(low,minimum[left]);left+=1
        if right&1:
            right-=1;high=max(high,maximum[right]);low=min(low,minimum[right])
        left//=2;right//=2
    return high,low


@njit(cache=False)
def _calculate(anchors,pub,raw_rows,last,times,window_complete):
    """
    機能: 全基準の両方向三逆行幅、純future極値、共通±10終端を計算する。
    引数: anchors/last/times(ndarray[float64])、pub/raw_rows(ndarray[int64])、window_complete(bool)。
    返り値: tuple はラベル・終端原行・MFE/MAE・十pt初到達・到達直前MAE・共通終端。
    """
    count=len(anchors);m=len(last);maximum,minimum,size=_tree(last)
    labels=np.full((count,2,3),-2,np.int8)
    terminal=np.full((count,2,3),-1,np.int64)
    mfe=np.full((count,2),np.nan,np.float64);mae=np.full((count,2),np.nan,np.float64)
    first_ten=np.full((count,2),-1,np.int64)
    first_time=np.full((count,2),np.nan,np.float64)
    before_mae=np.full((count,2),np.nan,np.float64)
    lock=np.full(count,-1,np.int64)
    pending=0 if window_complete else 2
    for i in range(count):
        if pub[i]<0:continue
        anchor=anchors[i]
        left=np.searchsorted(raw_rows,pub[i],side='right')
        end_row=raw_rows[m-1] if left<m else pub[i]
        upper=_first(maximum,minimum,1,0,size,left,m,anchor+10.,True) if left<m else -1
        lower=_first(maximum,minimum,1,0,size,left,m,anchor-10.,False) if left<m else -1
        common=upper if lower<0 else lower if upper<0 else min(upper,lower)
        lock[i]=raw_rows[common] if common>=0 else end_row
        if left<m:
            high,low=_range(maximum,minimum,left,m,size)
            mfe[i,0]=high-anchor;mae[i,0]=low-anchor
            mfe[i,1]=anchor-low;mae[i,1]=anchor-high
        for side_index in range(2):
            side=1 if side_index==0 else -1
            plus=upper if side>0 else lower
            if plus>=0:
                first_ten[i,side_index]=raw_rows[plus];first_time[i,side_index]=times[plus]
                if left<plus:
                    high,low=_range(maximum,minimum,left,plus,size)
                    before_mae[i,side_index]=(low-anchor) if side>0 else (anchor-high)
            for j in range(3):
                distance=2.5 if j==0 else 5. if j==1 else 10.
                minus=_first(maximum,minimum,1,0,size,left,m,anchor-side*distance,side<0) if left<m else -1
                assert plus<0 or minus<0 or plus!=minus
                if plus>=0 and (minus<0 or plus<minus):
                    labels[i,side_index,j]=1;terminal[i,side_index,j]=raw_rows[plus]
                elif minus>=0:
                    labels[i,side_index,j]=-1;terminal[i,side_index,j]=raw_rows[minus]
                else:
                    labels[i,side_index,j]=pending;terminal[i,side_index,j]=end_row
    return labels,terminal,mfe,mae,first_ten,first_time,before_mae,lock

# ----------------------------------------


def measure(bars: dict,prices: dict,window_complete: bool) -> dict:
    """
    機能: 確定足公開時Lastを固定し、採用済み後続Lastの十pt対逆行先着を採点する。
    引数: bars(dict) はanchor/t_s(float64[N])とpub_raw_row(int64[N])。
          prices(dict) はraw_row_index(int64[M])とlast/price_time_s(float64[M])。
          window_complete(bool) は窓終了の観測が存在するかを示す。
    返り値: dict は両方向三逆行幅のラベル、原行終端、純future極値、十pt初到達と直前MAE。
    原配列・公開基準を変更せず、OHLC未来値・BBO・金融・外部IOを使用しない。
    """
    assert isinstance(bars,dict) and isinstance(prices,dict)
    assert isinstance(window_complete,(bool,np.bool_))
    for name in ('anchor','pub_raw_row','t_s'):assert isinstance(bars[name],np.ndarray) and bars[name].ndim==1
    n=len(bars['anchor'])
    assert bars['anchor'].shape==bars['pub_raw_row'].shape==bars['t_s'].shape==(n,)
    assert bars['anchor'].dtype==bars['t_s'].dtype==np.float64 and bars['pub_raw_row'].dtype==np.int64
    assert np.isfinite(bars['t_s']).all() and np.all(np.diff(bars['t_s'])>0)
    anchor=bars['anchor'];pub=bars['pub_raw_row']
    assert np.all(pub>=-1) and np.array_equal(np.isnan(anchor),pub==-1)
    known=pub>=0
    assert np.isfinite(anchor[known]).all() and np.all(anchor[known]>0)
    assert np.all(np.diff(pub[known])>=0)
    for name in ('raw_row_index','last','price_time_s'):assert isinstance(prices[name],np.ndarray) and prices[name].ndim==1
    raw=prices['raw_row_index'];last=prices['last'];times=prices['price_time_s'];m=len(raw)
    assert raw.dtype==np.int64 and last.dtype==times.dtype==np.float64
    assert raw.shape==last.shape==times.shape==(m,)
    assert np.all(raw>=0) and np.all(raw[1:]>raw[:-1])
    assert np.isfinite(last).all() and np.all(last>0) and np.isfinite(times).all()
    assert np.all(times[1:]>=times[:-1])
    positions=np.searchsorted(raw,pub[known],side='left')
    assert np.all(positions<m)
    assert np.array_equal(raw[positions],pub[known]) and np.array_equal(last[positions],anchor[known])
    assert np.all(times[positions]>=bars['t_s'][known])
    assert np.isfinite(anchor[known]+10.).all() and np.isfinite(anchor[known]-10.).all()
    assert np.all(anchor[known]+2.5>anchor[known]) and np.all(anchor[known]-2.5<anchor[known])
    values=_calculate(anchor,pub,raw,last,times,bool(window_complete))
    names=('labels','terminal_raw_row','mfe','mae','first_10_raw_row','first_10_time_s','mae_before_first_10','common_lock_end')
    result=dict(zip(names,values))
    assert np.all(result['common_lock_end'][known]>=pub[known])
    return dict(**result,sides=SIDES.copy(),adverse_points=ADVERSE_POINTS.copy(),favorable_points=FAVORABLE_POINTS,
        code_names=dict(CODE_NAMES),window_complete=bool(window_complete),
        counts=dict(基準数=n,公開基準あり=int(known.sum()),公開基準なし=int((~known).sum()),採用済み価格数=m),
        極値の定義='MFE=max/MAE=minのsigned純future観測値。到達後も観測終端まで。0丸めなし、空はNaN。',
        到達前の定義='mae_before_first_10は十pt到達行を除く未来観測の最小signed値。未到達又は先行観測空はNaN。',
        共通終端の定義='公開後±10ptのどちらか初到達まで。未到達は未来最終原行又は公開行。三逆行幅で同じ予兆群を選ぶ診断用。',
        留保='採用済み観測価格の先着で、完全約定テープではない。原行間の不正/古いLastは入力側で除外。取引勝率・実注文・損益・再参加頻度ではない。')
