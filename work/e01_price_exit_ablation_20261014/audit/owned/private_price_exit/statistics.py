"""完結実親の金額/容量を全場、前後、上位三除外で別集計する。"""

import numpy as np
import catalog
import daily
import ledger_storage


def economic(rows: list[dict], parents: list[dict], symbol: str) -> dict:
    """
    機能: 損失/無取引込み平均場netと参考親平均・容量/同時保有を定義別に集計する。
    引数: rows/parents(list[dict])、symbol(str) は同商品範囲の場/完結親小資料。
    返り値: dict は経済尺度。無親の平均又はNK未指定円床はNone。
    """
    net=sum(r['収支'] for r in rows);count=len(parents);mean=net/count if count else None
    session_mean=net/len(rows) if rows else None
    assert count==sum(r['親数'] for r in rows) and np.isclose(net,sum(p['net_yen'] for p in parents),atol=1e-5)
    initial=float(np.mean([p['entry_quantity'] for p in parents])) if parents else None
    maximum=max([0]+[max(r['最大買枚数'],r['最大売枚数']) for r in rows]);cap=catalog.CAP[symbol]
    floor=100000. if symbol=='TOPIX' else None
    by_session=[]
    for row in rows:
        group=[p for p in parents if p['session']==row['session']]
        by_session.append(dict(session=row['session'],net_yen=row['収支'],parent_count=len(group),
            mean_parent_net_yen=row['収支']/len(group) if group else None,
            mean_initial_quantity=float(np.mean([p['entry_quantity'] for p in group])) if group else None,
            maximum_same_direction_quantity=max(row['最大買枚数'],row['最大売枚数']),
            net_capacity_points=row['収支']/(cap*catalog.VALUE[symbol]),
            worst_parent_liquidation_yen=min([0.]+[p['worst_parent_liquidation_yen'] for p in group]) if group else None))
    return dict(session_count=len(rows),mean_session_net_yen=session_mean,parent_count=count,mean_parent_net_yen=mean,mean_initial_quantity=initial,
        maximum_same_direction_quantity=maximum,mean_initial_capacity_ratio=initial/cap if initial is not None else None,
        net_capacity_points=net/(cap*catalog.VALUE[symbol]),target_floor_yen=floor,
        target_floor_specified=floor is not None,target_mean_success=None if floor is None else session_mean is not None and session_mean>=floor,
        by_session=by_session,definition='主目標は損失/無取引を含む全場net/場数。全完結親平均は負/零親を含む参考。容量ptは純換算、必要生値幅ではない。')


def stability(rows: list[dict], economy: dict) -> dict:
    """
    機能: 旧65/赤字20/最大赤字補填と新全場平均収支床を別判定する。
    引数: rows(list[dict])、economy(dict) は同商品/同期間の小会計。
    返り値: dict は活動/無取引と各達否。NKの円床未指定を達成へ補完しない。
    """
    pos=[r['収支'] for r in rows if r['収支']>0];neg=[r['収支'] for r in rows if r['収支']<0]
    active=sum(r['親数']>0 for r in rows);gain=sum(r['利益'] for r in rows);loss=sum(r['損失'] for r in rows)
    share=gain/(gain+loss) if gain+loss else None;mean=float(np.mean(pos)) if pos else None
    worst=max([0.]+[-v for v in neg]);red=len(neg)/len(rows) if rows else None
    old=share is not None and mean is not None and share>=.65 and red is not None and red<=.2 and worst<=mean
    return dict(session_count=len(rows),active_sessions=active,positive_sessions=len(pos),losing_sessions=len(neg),
        no_trade_sessions=len(rows)-active,flat_active_sessions=active-len(pos)-len(neg),red_full_rate=red,
        red_active_rate=len(neg)/active if active else None,profit_share=share,mean_positive_session_net_yen=mean,
        worst_negative_session_abs_yen=worst,target65=share is not None and share>=.65,
        target_red20=red is not None and red<=.2,target_worst_mean=mean is not None and worst<=mean,
        all_targets=old,target_mean_session_net=economy['target_mean_success'],
        all_economic_targets=old and (economy['target_mean_success'] if economy['target_floor_specified'] else True),
        monetary_floor_applies=economy['target_floor_specified'])


def periods(rows: list[dict], parents: list[dict], profiles: list[dict], sessions: list[str], symbol: str) -> dict:
    """
    機能: 商品別の全33/前16/後17/正net上位三場除外を同じ親定義で検算する。
    引数: rows/parents/profiles(list[dict])、sessions(list[str])、symbol(str) は保存場/親/射影。
    返り値: dict は期間別の会計/経済/安定性と除外場。
    """
    own=[r for r in rows if r['symbol']==symbol];pp=[p for p in parents if p['symbol']==symbol];pf=[p for p in profiles if p['symbol']==symbol]
    assert len(own)==len(sessions) and {r['session'] for r in own}==set(sessions)
    top=sorted((r for r in own if r['収支']>0),key=lambda r:(-r['収支'],r['session']))[:3];excluded={r['session'] for r in top}
    scopes={'全33':sessions,'前16':sessions[:16],'後17':sessions[16:],'上位3正収支場除外':[s for s in sessions if s not in excluded]};out={}
    for name,scope in scopes.items():
        rr=[r for r in own if r['session'] in scope];ps=[p for p in pp if p['session'] in scope];pr=[p for p in pf if p['session'] in scope]
        aggregate=ledger_storage.aggregate(rr,ps,scope);econ=economic(rr,pr,symbol)
        for key in ('利益','損失','収支'):assert np.isclose(aggregate[key],sum(r[key] for r in rr),atol=1e-5)
        out[name]=dict(aggregate=aggregate,economic=econ,stability=stability(rr,econ),sessions=scope)
    out['除外場']=[r['session'] for r in top];return out
