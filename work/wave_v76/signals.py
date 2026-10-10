"""両市場の即時板偏り・短期フローと、更新を伴う持続確認を計算する。"""

from pathlib import Path

import numba
import numpy as np
from numba import njit


HERE=Path(__file__).resolve().parent
numba.config.CACHE_DIR=str(HERE/'numba_cache')
FAMILIES={1:'最良板の一致',2:'距離加重板の一致',3:'注文増減の一致',4:'注文増減と板厚の一致',
          5:'短期価格進行の一致',6:'従来J1入口と短期の保有判断'}


def definitions() -> list[dict]:
    """機能: 瞬時板四条件と短期窓十二条件を事前列挙する。

    引数: なし。返り値: 十六入口の定義(list[dict])。
    """
    output=[]
    for code,family in [('Q',1),('D',2)]:
        for threshold in (.10,.25):
            output.append(dict(id=f'{code}{int(threshold*100)}',family=family,kind=code,window=0,threshold=threshold))
    for code,family in [('F',3),('FD',4),('P',5)]:
        for window in (5,15,30,60):
            output.append(dict(id=f'{code}{window}',family=family,kind=code,window=window,threshold=1. if code=='P' else .10))
    assert len(output)==16
    return output


def market_state(definition: dict,market: dict) -> tuple:
    """機能: 一市場の強い入口方向と緩い保有支持を分けて判定する。

    引数: definition/market(dict)。返り値: 強方向、弱支持、有効性、参照行(tuple[ndarray,...])。
    最良数量の偏りとmicropriceは同値なので重複計数しない。OFIは非ゼロ三イベント以上が必要。
    """
    c=market['current'];kind=definition['kind'];threshold=definition['threshold']
    size=len(c['valid']);strong=np.zeros(size,dtype=np.int8);weak=strong.copy()
    valid=c['valid'].copy()
    if kind in ('Q','D'):
        values=c['best_imbalance' if kind=='Q' else 'depth_imbalance']
        valid &= np.isfinite(values)
        for d in (-1,1):
            strong[valid&(d*values>=threshold)]=d
            weak[valid&(d*values>=threshold/2)]=d
    else:
        w=market['windows'][definition['window']]
        if kind=='P':
            valid &= w['source_valid']
            for d in (-1,1):
                strong[valid&(d*w['bid_change_ticks']>=1.-1e-8)&(d*w['ask_change_ticks']>=1.-1e-8)]=d
                weak[valid&(d*w['mid_change_bp']>0)]=d
        else:
            valid &= w['source_valid']&~w['missing_ofi']
            evidence=w['valid']&(w['nonzero_ofi_count']>=3)
            for d in (-1,1):
                high=valid&evidence&(d*w['ofi_ratio']>=threshold)
                low=valid&evidence&(d*w['ofi_ratio']>=threshold/2)
                if kind=='FD':
                    high &= d*c['depth_imbalance']>=threshold
                    low &= d*c['depth_imbalance']>=threshold/2
                strong[high]=d;weak[low]=d
    return strong,weak,valid,c['index']


@njit(cache=True)
def confirmation(grid,condition,valid,source_a,source_b,seconds):
    """機能: 条件の連続時間と、確認開始後の両側参照行更新を判定する。

    引数: grid(float配列)、条件/有効性(bool配列)、参照行(int配列)、seconds(float)。
    返り値: 確認完了(bool配列)。0秒だけは瞬時判定、欠測や格子欠落は確認を破棄する。
    """
    out=np.zeros(len(grid),dtype=np.bool_);start=-1;previous=-1e30
    for i in range(len(grid)):
        gap=grid[i]-previous>5.+1e-8;previous=grid[i]
        if not valid[i] or not condition[i]:start=-1;continue
        if start<0 or gap:start=i
        if seconds==0:
            out[i]=True
        elif grid[i]-grid[start]>=seconds and source_a[i]>source_a[start] and source_b[i]>source_b[start]:
            out[i]=True
    return out


@njit(cache=True)
def pulses(grid,strong,valid,confirmed):
    """機能: 確認された合意の立上がりを、最短60秒の新規イベントに変換する。

    引数: grid(float配列)、strong/confirmed(int配列)、valid(bool配列)。返り値: 売買方向(int8配列)。
    合意なし（中立又は不一致）が有効格子で10秒続けば再準備する。反対方向成立も別イベント。
    """
    out=np.zeros(len(grid),dtype=np.int8)
    emitted=0;neutral=-1.;last=-1e30;previous=-1e30
    for i in range(len(grid)):
        gap=grid[i]-previous>5.+1e-8;previous=grid[i]
        if gap:neutral=-1.
        if not valid[i]:neutral=-1.;continue
        if strong[i]==0:
            if neutral<0:neutral=grid[i]
            if grid[i]-neutral>=10.:emitted=0
        else:neutral=-1.
        d=confirmed[i]
        if d!=0 and d!=emitted and grid[i]-last>=60.:
            out[i]=d;emitted=d;last=grid[i]
    return out


def joint(definition: dict,session: dict) -> dict:
    """機能: 両市場の合意・中立・不一致・欠測と、入口/保有確認を作る。

    引数: definition/session(dict)。返り値: 合意状態と全持続確認(dict)。
    欠測は中立にせず、相手と不一致でも直ちに反対方向とは扱わない。
    """
    grid=session['grid']
    a,wa,va,sa=market_state(definition,session['markets']['TOPIX'])
    b,wb,vb,sb=market_state(definition,session['markets']['NK225'])
    valid=va&vb
    strong=np.where(valid&(a==b),a,0).astype(np.int8)
    support_long=valid&(wa==1)&(wb==1);support_short=valid&(wa==-1)&(wb==-1)
    out=dict(grid=grid,strong=strong,valid=valid,own_strong=a,peer_strong=b,own_weak=wa,peer_weak=wb,source_top=sa,source_nk=sb,
        disagreement=valid&(a*b==-1),support_long=support_long,support_short=support_short,entry={},management={})
    for seconds in (0,10):
        yes=confirmation(grid,strong==1,valid,sa,sb,float(seconds))
        no=confirmation(grid,strong==-1,valid,sa,sb,float(seconds))
        confirmed=yes.astype(np.int8)-no.astype(np.int8)
        out['entry'][seconds]=pulses(grid,strong,valid,confirmed)
    for seconds in (15,30):
        out['management'][seconds]=dict(
            loss_long=confirmation(grid,~support_long,valid,sa,sb,float(seconds)),
            loss_short=confirmation(grid,~support_short,valid,sa,sb,float(seconds)),
            opposite_long=confirmation(grid,strong==-1,valid,sa,sb,float(seconds)),
            opposite_short=confirmation(grid,strong==1,valid,sa,sb,float(seconds)))
    return out


def mapping(grid: np.ndarray,ready: dict) -> np.ndarray:
    """機能: 共通格子を以後10秒以内の最初の自原本行に対応付ける。

    引数: grid(ndarray)、ready(dict)。返り値: 各原本行で更新する格子番号(int32配列)。
    同じ原本行に複数の格子が届く場合は最新だけを使い、古い新規イベントを後から執行しない。
    """
    times=ready['time_s'];out=np.full(len(times),-1,dtype=np.int32)
    if not len(times):return out
    rows=np.searchsorted(times,grid,side='left')
    for g,i in enumerate(rows):
        if i<len(times) and times[i]-grid[g]<=10.:out[i]=g
    return out


def build(grids: dict) -> dict:
    """機能: 各場の十六条件について、共通状態を損益なしに準備する。

    引数: grids(dict[session,dict])。返り値: 条件ID→場→状態(dict)。
    """
    return {d['id']:{session:joint(d,value) for session,value in grids.items()} for d in definitions()}
