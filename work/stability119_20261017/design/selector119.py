"""当時の全玉清算時価と保有方向だけから、六つの前向き配分信号を作る。"""

from __future__ import annotations

import numpy as np


HORIZONS=(20,60,120)
METHODS=('single','distinct_family_consensus')


def _inputs(
    equity: np.ndarray,
    position: np.ndarray,
    width: np.ndarray,
    families: list[str],
    fee_roundtrip: float,
) -> tuple[np.ndarray,np.ndarray,np.ndarray,list[str],float]:
    """
    機能: 公開一分列の寸法と契約を検査し、入力を改変しない観測用配列を返す。
    引数: equity(float[B,N])、position(int8[B,N])、width(float[N])、
        families(list[str])は実在する戦略家族、fee_roundtrip(float)は同数量の往復料金。
    返り値: tupleは検査済み資産・方向・幅・家族・料金。NaNは後段で共通gapとする。
    """
    e=np.asarray(equity,dtype=np.float64)
    p=np.asarray(position)
    w=np.asarray(width,dtype=np.float64)
    if e.ndim!=2 or e.shape[0]<1:
        raise ValueError('資産は教師一つ以上の二次元配列にしてください。')
    if p.shape!=e.shape or p.dtype!=np.dtype(np.int8):
        raise ValueError('方向は資産と同形のint8配列にしてください。')
    if not np.isin(p,(-1,0,1)).all():
        raise ValueError('方向は売り−1・中立0・買い1だけを使用します。')
    if w.shape!=(e.shape[1],):
        raise ValueError('幅は公開一分列と同じ長さの一次元配列にしてください。')
    if not isinstance(families,list) or len(families)!=e.shape[0]:
        raise ValueError('家族名は教師数と一致する文字列リストにしてください。')
    if any(not isinstance(v,str) or not v.strip() for v in families):
        raise ValueError('空又は文字列以外の家族名は使えません。')
    f=float(fee_roundtrip)
    if not np.isfinite(f) or f<0:
        raise ValueError('往復料金は有限の非負金額にしてください。')
    return e,p,w,list(families),f


def _window_scores(equity: np.ndarray,good: np.ndarray,horizon: int) -> tuple[np.ndarray,np.ndarray]:
    """
    機能: 直近H分の資産差から、その窓内の最大時価下落の半分を引く。
    引数: equity(float[B,N])、good(bool[N])は共通正常列、horizon(int)は分数。
    返り値: tuple[float[B,N],bool[N]]は得点とH+1正常観測の準備完了列。
        価格時計の飛びは入力のNaN列として示す必要があり、圧縮列からは検出しない。
    """
    b,n=equity.shape
    scores=np.full((b,n),np.nan,dtype=np.float64)
    ready=np.zeros(n,dtype=np.bool_)
    consecutive=0
    for t in range(n):
        consecutive=consecutive+1 if good[t] else 0
        if consecutive<horizon+1:
            continue
        values=equity[:,t-horizon:t+1]
        with np.errstate(over='ignore',invalid='ignore'):
            drawdown=np.max(np.maximum.accumulate(values,axis=1)-values,axis=1)
            score=values[:,-1]-values[:,0]-.5*drawdown
        scores[:,t]=score
        ready[t]=bool(np.isfinite(score).all())
    return scores,ready


def _direction(scores: np.ndarray,position: np.ndarray,families: list[str],fee: float,method: str) -> tuple[int,bool]:
    """
    機能: 料金足切り後の最高得点、又は異家族の上位二教師から当時方向を決める。
    引数: scores(float[B])、position(int8[B])、families(list[str])、fee(float)、method(str)。
    返り値: tuple[int,bool]は方向と比較成立。順位同点は固定された教師の入力順で解く。
        最高得点教師が中立のとき、保有中の別教師へ後から差し替えない。
    """
    order=sorted(range(len(scores)),key=lambda i:(-float(scores[i]),i))
    selected=[]
    used=set()
    required=1 if method=='single' else 2
    for i in order:
        if not np.isfinite(scores[i]) or scores[i]<=2*fee:
            continue
        if method!='single' and families[i] in used:
            continue
        selected.append(i)
        used.add(families[i])
        if len(selected)==required:
            break
    if len(selected)!=required:
        return 0,False
    if required==1:
        return int(position[selected[0]]),True
    left,right=(int(position[i]) for i in selected)
    return (left if left==right else 0),True


def build_selectors(
    equity: np.ndarray,
    position: np.ndarray,
    width: np.ndarray,
    families: list[str],
    fee_roundtrip: float,
) -> dict:
    """
    機能: 全玉清算時価を含む教師から六条件の新規方向と反対確認退出述語を作る純関数。
    引数: equity(float[B,N])は各公開一分時点で既知の直前BBOによる、返済料差引後の
        教師清算資産。position(int8[B,N])は同時点の符号。width(float[N])は根で固定した
        20分幅。families(list[str])、fee_roundtrip(float)は同商品・同数量の比較条件。
    返り値: dictはspecs(list[dict])、entry(int8[6,N])、exit_long/exit_short(bool[6,N])、
        width(float[6,N])、valid(bool[6,N])。実注文や実保有を作らず教師のstopを継承しない。

    入力の各列は欠落を詰めない一分格子を表す。NaN又は非有限の教師資産、非有限又は
    非正の幅は全教師共通のgapであり、全窓の準備と連続確認を切る。最初のH列は無信号。
    validは履歴・料金足切り・必要家族数が揃うこと。中立や二教師不一致でもvalidの
    場合があるが、新規も退出も出さず連続確認を切る。新規は同方向2列、退出は3列。
    退出述語はその方向の実保有がある場合だけ利用する責任を呼出側へ委ねる。
    """
    e,p,w,fam,fee=_inputs(equity,position,width,families,fee_roundtrip)
    n=e.shape[1]
    specs=[]
    entry=np.zeros((6,n),dtype=np.int8)
    exit_long=np.zeros((6,n),dtype=np.bool_)
    exit_short=np.zeros((6,n),dtype=np.bool_)
    valid=np.zeros((6,n),dtype=np.bool_)
    widths=np.broadcast_to(w,(6,n)).copy()
    good=np.isfinite(e).all(axis=0)&np.isfinite(w)&(w>0)
    # ----------------------------------------
    # 同じHの得点を二つの選択方式で共有し、未来列や完了後の勝敗は参照しない。
    for h in HORIZONS:
        score,ready=_window_scores(e,good,h)
        for method in METHODS:
            k=len(specs)
            specs.append(dict(id=f'S119_H{h:03d}_{method}',horizon_minutes=h,method=method,
                score='直近H分の清算資産差−0.5×同じ窓の最大時価下落',
                fee_hurdle_multiplier=2.,entry_confirm_bars=2,opposite_exit_confirm_bars=3,
                width_source='根で固定した現在の20分幅。教師の停止線は使わない。',
                warmup_observations=h+1,tie_rule='得点降順、同点は固定教師入力順',
                gap_rule='どれかの資産又は共通幅が不正なら共通gap。H履歴と連続確認を切る。',
                clock_contract='欠落列をNaNで保持した一分格子。真の板受信時計とは限らない。',
                未検証='完了勝敗選別との収益差・未知場安定性は未検証。実市場読取なし。'))
            previous=0
            streak=0
            for t in range(n):
                direction=0
                if ready[t]:
                    direction,valid[k,t]=_direction(score[:,t],p[:,t],fam,fee,method)
                if not valid[k,t] or direction==0:
                    previous=0
                    streak=0
                    continue
                streak=streak+1 if direction==previous else 1
                previous=direction
                if streak>=2:
                    entry[k,t]=direction
                if streak>=3:
                    exit_long[k,t]=direction<0
                    exit_short[k,t]=direction>0
    return dict(specs=specs,entry=entry,exit_long=exit_long,exit_short=exit_short,width=widths,valid=valid)
