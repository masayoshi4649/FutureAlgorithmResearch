"""十場を再標本単位とし、予兆と同時点の固定方向対照を一緒に再加算する。"""

from __future__ import annotations

from fractions import Fraction
from numbers import Integral
import math

import numpy as np


SEED=118
REPETITIONS=10000
FIELDS=('n','favorable','adverse','unresolved','always_long_favorable','always_short_favorable')


def validate(clusters: list[dict]) -> np.ndarray:
    """
    機能: 各場の同じ予兆母数と、対称±10ptの先着内訳を検査する。
    引数: clusters(list[dict]) はsessionとFIELDSの六件数を持つ十場。
    返り値: ndarray[int64,10,6] は件数。未決は順先/逆先へ足さない。
    """
    assert len(clusters)==10 and len({row['session'] for row in clusters})==10
    values=[]
    for row in clusters:
        for name in FIELDS:
            assert isinstance(row[name],Integral) and not isinstance(row[name],(bool,np.bool_)) and row[name]>=0
        n,win,loss,unresolved,long,short=[int(row[name]) for name in FIELDS]
        assert n==win+loss+unresolved and long+short==win+loss
        values.append([n,win,loss,unresolved,long,short])
    data=np.array(values,np.int64)
    assert np.array_equal(data.astype(object),np.array(values,dtype=object))
    assert sum(int(v) for v in data[:,0])<=np.iinfo(np.int64).max//10
    return data


def interval(values: np.ndarray) -> dict:
    """
    機能: 有限再標本値の百分位区間と未定義再標本数を保存する。
    引数: values(ndarray[float]) は再標本ごとの比率又は差。
    返り値: dict。95%区間はpercentileの記述で、探索補正済み信頼保証ではない。
    """
    assert values.ndim==1 and not np.isinf(values).any()
    finite=values[np.isfinite(values)]
    if len(finite):
        lower,median,upper=np.quantile(finite,[.025,.5,.975],method='linear').tolist()
    else:lower=median=upper=None
    return dict(valid_resamples=len(finite),undefined_resamples=len(values)-len(finite),
        percentile_2_5=lower,percentile_50=median,percentile_97_5=upper,
        method='十場等確率・復元抽出・比率は分子合計/分母合計。線形分位点。')


def analyse(clusters: list[dict]) -> dict:
    """
    機能: 十場をpairedに一万回再抽出し、順先率と固定方向との差を記述する。
    引数: clusters(list[dict]) は同一候補・risk10だけの場別件数。
    返り値: dict は観測値・bootstrap区間・一場除外感度。40独立試行の検定ではない。
    """
    data=validate(clusters);total=data.sum(axis=0)
    n,win,loss,unresolved,long,short=[int(v) for v in total]
    assert n>0
    reference=4 if long>=short else 5
    names=('favorable_rate_all','always_long_rate_all','always_short_rate_all',
        'difference_from_always_long','difference_from_always_short',
        'difference_from_original_best_fixed','difference_from_resampled_best_fixed')
    generator=np.random.default_rng(SEED)
    positions=generator.integers(0,10,size=(REPETITIONS,10))
    sampled=data[positions].sum(axis=1)
    denominator=sampled[:,0];valid=denominator>0
    rates=np.full((REPETITIONS,3),np.nan)
    for target,column in enumerate((1,4,5)):
        np.divide(sampled[:,column],denominator,out=rates[:,target],where=valid)
    fixed_column=1 if reference==4 else 2
    values=(rates[:,0],rates[:,1],rates[:,2],rates[:,0]-rates[:,1],rates[:,0]-rates[:,2],
        rates[:,0]-rates[:,fixed_column],rates[:,0]-np.maximum(rates[:,1],rates[:,2]))
    observed=dict(n=n,favorable=win,adverse=loss,unresolved=unresolved,
        favorable_rate_all=float(Fraction(win,n)),
        favorable_rate_resolved=float(Fraction(win,win+loss)) if win+loss else None,
        resolution_rate=float(Fraction(win+loss,n)),always_long_favorable=long,always_short_favorable=short,
        always_long_rate_all=float(Fraction(long,n)),always_short_rate_all=float(Fraction(short,n)),
        original_best_fixed='買い' if reference==4 else '売り',
        difference_from_original_best_fixed=float(Fraction(win-max(long,short),n)),
        active_sessions=int(np.count_nonzero(data[:,0])),no_signal_sessions=int(np.count_nonzero(data[:,0]==0)),
        maximum_session_n=int(data[:,0].max()),maximum_session_n_share=float(Fraction(int(data[:,0].max()),n)))
    removed=[]
    for i,row in enumerate(clusters):
        remaining=total-data[i];dn,dw,_,_,dl,ds=[int(v) for v in remaining]
        removed.append(dict(removed_session=row['session'],n=dn,favorable=dw,
            favorable_rate_all=float(Fraction(dw,dn)) if dn else None,
            difference_from_original_best_fixed=float(Fraction(dw-int(remaining[reference]),dn)) if dn else None,
            difference_from_remaining_best_fixed=float(Fraction(dw-max(dl,ds),dn)) if dn else None))
    return dict(seed=SEED,repetitions=REPETITIONS,sessions=[r['session'] for r in clusters],observed=observed,
        bootstrap={name:interval(array) for name,array in zip(names,values)},leave_one_session_out=removed,
        selection_adjustment=False,
        留保='同じ十場を再利用する記述的な場cluster bootstrap。場内の相関を残すが、十場間の独立性・少数clusterでの被覆・44条件と三逆行幅探索後選択を保証/補正しない。p値・未来的中率・実取引利益ではない。')


def artificial() -> dict:
    """
    機能: 再標本分母・空場・同時点対照・未知・一場依存を純人工で確認する。
    引数: なし。
    返り値: dict は算術検査の件数。実結果本文を読む関数ではない。
    """
    uniform=[dict(session=f'合成{i}',n=4,favorable=3,adverse=1,unresolved=0,
        always_long_favorable=2,always_short_favorable=2) for i in range(10)]
    a=analyse(uniform)
    assert a['observed']['favorable_rate_all']==.75
    assert a['bootstrap']['favorable_rate_all']['percentile_2_5']==.75
    assert a['bootstrap']['difference_from_original_best_fixed']['percentile_97_5']==.25
    assert analyse(uniform)==a
    sparse=[dict(session=f'薄い{i}',n=0,favorable=0,adverse=0,unresolved=0,
        always_long_favorable=0,always_short_favorable=0) for i in range(10)]
    sparse[0].update(n=4,favorable=1,adverse=1,unresolved=2,always_long_favorable=1,always_short_favorable=1)
    b=analyse(sparse)
    assert b['bootstrap']['favorable_rate_all']['undefined_resamples']>0
    assert b['observed']['favorable_rate_all']==.25 and b['observed']['favorable_rate_resolved']==.5
    assert b['leave_one_session_out'][0]['favorable_rate_all'] is None
    incomplete=deepcopy_rows(uniform);incomplete[0]['always_long_favorable']=3
    try:analyse(incomplete)
    except AssertionError:pass
    else:raise AssertionError('対称幅対照の分母不整合を受理')
    invalid=deepcopy_rows(uniform);invalid[0]['n']=True
    try:analyse(invalid)
    except AssertionError:pass
    else:raise AssertionError('bool件数を受理')
    return dict(全合格=True,seed=SEED,repetitions=REPETITIONS,実本文=0,金融=0,
        条件='十場一様素材、同seed再現、活動一場のみ、全nと解決分母差、対照不整合/bool拒否。')


def deepcopy_rows(rows: list[dict]) -> list[dict]:
    """
    機能: 人工の辞書列を一段ずつ複製する。
    引数: rows(list[dict]) はスカラー件数だけの素材。
    返り値: list[dict]。
    """
    return [dict(row) for row in rows]
