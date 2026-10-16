"""完結実親の金額と、各場の安定性を主目標の定義で集計する。"""

from statistics import mean, median
import math
from numbers import Integral, Real


def amounts(values: list[float]) -> dict:
    """
    機能: 完結取引群の手数料後損益を相殺前の正負へ分ける。
    引数: values(list[float]) は各完結親の円損益。
    返り値: dict は利益・損失・収支と金額利益割合。無取引の割合は未知。
    """
    assert all(isinstance(v,Real) and not isinstance(v,bool) and math.isfinite(v) for v in values)
    wins = [v for v in values if v > 0]
    losses = [-v for v in values if v < 0]
    p, l = sum(wins), sum(losses)
    return dict(利益=p, 損失=l, 収支=sum(values), 親数=len(values), 勝ち親=len(wins),
                負け親=len(losses), 零親=len(values)-len(wins)-len(losses),
                利益割合=p/(p+l) if p+l else None, PF=p/l if l else None,
                平均利益=mean(wins) if wins else None,
                平均損失=mean(losses) if losses else None)


def scope(rows: list[dict], parents: list[dict], symbol: str) -> dict:
    """
    機能: 同商品・同期間の金額指標と平均的な黒字による最悪損失の補填を測る。
    引数: rows/parents(list[dict])、symbol(str) は場、完結親、商品識別。
    返り値: dict は金額・場数・目標達否。日経の円額床は未指定のまま。
    """
    assert rows
    for row in rows:
        assert all(isinstance(row[k],Real) and not isinstance(row[k],bool) and math.isfinite(row[k]) for k in ('利益','損失','収支'))
        assert row['利益']>=0 and row['損失']>=0
        assert isinstance(row['親数'],Integral) and not isinstance(row['親数'],bool) and row['親数']>=0
    sums = amounts([p['収支'] for p in parents])
    for name in ('利益', '損失', '収支'):
        assert abs(sums[name]-sum(r[name] for r in rows)) < 1e-5
    assert sums['親数'] == sum(r['親数'] for r in rows)
    positive = [float(r['収支']) for r in rows if r['収支'] > 0]
    negative = [-float(r['収支']) for r in rows if r['収支'] < 0]
    active = sum(r['親数'] > 0 for r in rows)
    positive_mean = mean(positive) if positive else None
    worst = max([0.]+negative)
    n = len(rows)
    red = len(negative)/n
    monetary65 = sums['利益割合'] is not None and sums['利益割合'] >= .65
    red20 = red <= .2
    coverage = positive_mean is not None and worst <= positive_mean
    session_mean = sums['収支']/n
    floor = 100000. if symbol == 'TOPIX' else None
    return dict(aggregate=sums, session_count=n, active_sessions=active,
                positive_sessions=len(positive), losing_sessions=len(negative),
                no_trade_sessions=n-active, flat_active_sessions=active-len(positive)-len(negative),
                red_full_rate=red, red_active_rate=len(negative)/active if active else None,
                mean_session_net_yen=session_mean, median_session_net_yen=median(r['収支'] for r in rows),
                mean_positive_session_net_yen=positive_mean, worst_negative_session_abs_yen=worst,
                target65=monetary65, target_red20=red20, target_worst_mean=coverage,
                all_stability_targets=monetary65 and red20 and coverage,
                target_floor_yen=floor, target_mean_success=session_mean >= floor if floor is not None else None,
                all_main_targets=monetary65 and red20 and coverage and (floor is None or session_mean >= floor),
                actual_quantity_cap=10 if symbol == 'TOPIX' else 20,
                net_capacity_points=sums['収支']/((10*1000.) if symbol == 'TOPIX' else (20*10.)))


def periods(rows: list[dict], parents: list[dict], sessions: list[str], symbol: str) -> dict:
    """
    機能: 全場・前後半・デイナイト・上位3黒字場除外を同じ金額定義で測る。
    引数: rows/parents(list[dict])、sessions(list[str])、symbol(str) は固定順の測定母集団。
    返り値: dict は期間別集計と除外場。除外の結果を発注判断へ使わない。
    """
    own = [r for r in rows if r['symbol'] == symbol]
    pp = [p for p in parents if p['symbol'] == symbol]
    assert len(own) == len(sessions) and {r['session'] for r in own} == set(sessions)
    top = sorted((r for r in own if r['収支'] > 0), key=lambda r: (-r['収支'],r['session']))[:3]
    excluded = {r['session'] for r in top}
    middle = len(sessions)//2
    groups = {'全場':sessions, '前半':sessions[:middle], '後半':sessions[middle:],
              'デイ':[s for s in sessions if s.endswith('_Day')],
              'ナイト':[s for s in sessions if s.endswith('_Night')],
              '上位3黒字場除外':[s for s in sessions if s not in excluded]}
    out = {}
    for name, ids in groups.items():
        rr = [r for r in own if r['session'] in ids]
        ps = [p for p in pp if p['session'] in ids]
        if rr:
            out[name] = dict(**scope(rr,ps,symbol), sessions=ids)
    out['除外場'] = [r['session'] for r in top]
    out['方向'] = {label:amounts([p['収支'] for p in pp if p['方向'] == side])
                   for label,side in (('買い',1),('売り',-1))}
    return out
