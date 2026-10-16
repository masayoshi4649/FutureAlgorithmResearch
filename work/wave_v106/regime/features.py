"""価格を間引いて良く見せず、事前固定した6公表点から当時5分状態を測る。"""

import math

import numpy as np


def publications(raw: dict) -> dict:
    """
    機能: 旧104と同じ新最大価格時計の最初の原行を公表源にする。
    引数: raw(dict)は保存原行と価格時計。
    返り値: dictはrows/times/raw_seq。同clockの不正先頭を後半へ差し替えない。
    """
    indexes,maximum=[],-np.inf
    for row,stamp in enumerate(raw['price_time_s']):
        if np.isfinite(stamp) and stamp>maximum:
            maximum=stamp;indexes.append(row)
    rows=np.asarray(indexes,np.int64)
    return dict(rows=rows,times=raw['price_time_s'][rows].copy(),raw_seq=raw['raw_seq'][rows].copy())


def context(raw: dict, public: dict | None=None) -> dict:
    """
    機能: 時計断裂と公表gapだけを累積し、観測外の非normal BBOとは区別する。
    引数: raw(dict)、public(dict|None)は原行と既first公表。
    返り値: dictは公表と不正prefix。資格で公表点を先に間引かない。
    """
    pub=publications(raw) if public is None else public
    seq,stamps=raw['raw_seq'],raw['price_time_s']
    bad=(~np.isfinite(stamps))|(raw['price_reset_reason']!=0)
    if len(stamps)>1:
        bad[1:]|=(~np.isfinite(stamps[:-1]))|(np.diff(stamps)<0)|(np.diff(seq)!=1)
    gaps=np.r_[False,np.diff(pub['times'])>15.]
    return dict(public=pub,bad_prefix=np.r_[0,np.cumsum(bad.astype(np.int64))],
        gap_prefix=np.r_[0,np.cumsum(gaps.astype(np.int64))])


def sample(raw: dict, ctx: dict, stamp: float, tick: float,
           candidate_row: int | None=None, strictpast: bool=False) -> dict:
    """
    機能: 300/240/180/120/60秒前と現在の6点を当時以前から選ぶ。
    引数: raw/ctx(dict)、stamp/tick(float)、candidate_row(int|None)、strictpast(bool)は自己行上限と相手厳密過去。
    返り値: dictはknown/理由と6点系譜、ER/return/span/H/L。未来点で不明を救済しない。
    """
    result=dict(known=False,reason=0,rows=[],raw_seq=[],times=[],midpoint=[],ages=[],
        ER=None,return_bp=None,span_ticks=None,high=None,low=None,centre=None,TV=None)
    if not np.isfinite(stamp):result['reason']=1;return result
    pub=ctx['public'];times,rows=pub['times'],pub['rows']
    offsets=np.array([300.,240.,180.,120.,60.,0.]);requested=stamp-offsets
    positions=np.searchsorted(times,requested,side='right')-1
    if strictpast:positions[-1]=np.searchsorted(times,stamp,side='left')-1
    if candidate_row is not None:
        maximum=int(np.searchsorted(rows,candidate_row,side='right')-1);positions=np.minimum(positions,maximum)
    if np.any(positions<0):result['reason']=1;return result
    selected=rows[positions];observed=times[positions];ages=requested-observed
    result.update(rows=selected.tolist(),raw_seq=raw['raw_seq'][selected].tolist(),times=observed.tolist(),ages=ages.tolist())
    if np.any((ages<0)|(ages>15.)) or (strictpast and observed[-1]>=stamp):result['reason']|=2
    bid,ask=raw['bid'][selected],raw['ask'][selected]
    good=raw['qualified'][selected]&raw['bbo_valid'][selected]&np.isfinite(bid)&np.isfinite(ask)&(bid>0)&(ask>bid)
    if not np.all(good):result['reason']|=4
    first,last=int(selected[0]),int(selected[-1])
    # ----------------------------------------
    # 自己の公表終点から実候補行までの時計断裂も含める。未観測BBOだけでは窓を破棄しない。
    endpoint=last if candidate_row is None else candidate_row
    if ctx['bad_prefix'][endpoint+1]-ctx['bad_prefix'][first]>0:result['reason']|=8
    if ctx['gap_prefix'][positions[-1]+1]-ctx['gap_prefix'][positions[0]+1]>0:result['reason']|=16
    if result['reason']:return result
    mids=(bid+ask)/2.;net=float(mids[-1]-mids[0]);tv=float(np.abs(np.diff(mids)).sum())
    high,low=float(mids.max()),float(mids.min())
    result.update(known=True,midpoint=mids.tolist(),ER=abs(net)/tv if tv>0 else None,
        return_bp=net/mids[0]*10000.,span_ticks=(high-low)/tick,high=high,low=low,centre=(high+low)/2.,TV=tv)
    return result


def classify(pair: dict, threshold_bp: float, range_er: float) -> str:
    """
    機能: 共通RANGEを先に決め、それ以外の双方同方向進行をTRENDへ分ける。
    引数: pair(dict)はown/peerの6点測定、threshold_bp/range_er(float)は固定水準。
    返り値: strはUNKNOWN/RANGE/TREND_UP/TREND_DOWN/NEUTRAL。余地不足でもCへ救済しない。
    """
    own,peer=pair['own'],pair['peer']
    if not own['known'] or not peer['known']:return 'UNKNOWN'
    if all(v['ER'] is not None and v['ER']<=range_er and v['span_ticks']>=4 for v in (own,peer)):return 'RANGE'
    if own['return_bp']>=threshold_bp and peer['return_bp']>=threshold_bp:return 'TREND_UP'
    if own['return_bp']<=-threshold_bp and peer['return_bp']<=-threshold_bp:return 'TREND_DOWN'
    return 'NEUTRAL'


def range_order(prepared: dict, case: dict, row: int, measure: dict, quantity: int) -> dict:
    """
    機能: 当時中心とask/bidで、Rの費用後利益余地対予定損失を審査する。
    引数: prepared/case/measure(dict)、row/quantity(int)は同原行入口と実枚数。
    返り値: dictは許可/拒否理由、固定targetと予定net利益/損失。次quoteの実収支上限ではない。
    """
    record=prepared['record'];side=int(case['event'][row]);assert side in (-1,1)
    tick=float(record['tick']);symbol=record['symbol'];m,unit=(1000.,41.8) if symbol=='TOPIX' else (10.,11.)
    centre=float(measure['centre']);E=float(record['ask'][row] if side==1 else record['bid'][row])
    support=float(case['support_price'][row]);S=max(2,math.ceil(prepared['reference_open']*.001/tick-1e-10))*tick
    L0=max(support-4*tick,E-S) if side==1 else min(support+4*tick,E+S)
    fees=2*math.floor(quantity*unit+1e-8)
    target=(math.ceil(centre/tick-1e-10) if side==1 else math.floor(centre/tick+1e-10))*tick
    profit=side*(centre-E)*quantity*m-fees
    loss=side*(E-L0)*quantity*m+fees
    allowed=side*(centre-E)>0 and loss>0 and profit>=1.25*loss
    reason='許可' if allowed else '中心の反対側' if side*(centre-E)<=0 else '予定初期損失が非正' if loss<=0 else '費用後中心余地が1.25倍未満'
    return dict(allowed=bool(allowed),reason=reason,target=float(target),centre=centre,planned_entry=E,
        planned_stop=L0,planned_net_profit=profit,planned_net_loss=loss,exact_roundtrip_fees=fees)
