"""1枚で共通化した取引の利益・損失・枚数を銘柄別に集計する。"""

from __future__ import annotations

import numpy as np

FACTORS={'TOPIX':1000.,'NK225':10.}


def ratio(a: float,b: float) -> float | None:
    """機能: 分母0を無限大へ置き換えず未定義とする。

    引数: a/b (float)。返り値: 比率 (float|None)。
    """
    return float(a/b) if b>0 and np.isfinite(a) and np.isfinite(b) and np.isfinite(a/b) else None


def session(ready: dict,result: dict) -> dict:
    """機能: 全取引と全行曲線から一市場セッションの統計を作る。

    引数: ready/result (dict)。返り値: 金額・決済枚数・含み込み下落等 (dict)。
    """
    trades=result['trades'];pnl=trades[:,6];factor=FACTORS[ready['symbol']]
    win=pnl>0;lose=pnl<0
    return dict(session=ready['session'],symbol=ready['symbol'],
        profit_yen=float(pnl[win].sum()*factor),loss_yen=float(-pnl[lose].sum()*factor),
        net_yen=float(pnl.sum()*factor),profit_units=int(win.sum()),loss_units=int(lose.sum()),
        zero_units=int((pnl==0).sum()),trades=len(trades),net_r=float(np.sum(pnl/trades[:,5])),
        drawdown_yen=float(result['stats'][1]*factor),
        minimum_yen=float(min(0.,result['curve'][:,1].min())*factor),
        maximum_yen=float(max(0.,result['curve'][:,1].max())*factor),
        max_win_yen=float(max(0.,pnl.max())*factor) if len(pnl) else 0.,
        long_trades=int((trades[:,2]>0).sum()),short_trades=int((trades[:,2]<0).sum()),
        held_minutes=float(np.sum(ready['time_s'][trades[:,1].astype(int)]-ready['time_s'][trades[:,0].astype(int)])/60),
        candidates=int(result['stats'][2]),accepted=int(result['stats'][3]),cancelled=int(result['stats'][4]))


def aggregate(rows: list[dict]) -> dict:
    """機能: 場内完結したセッションを時系列に結び含み込みDDを保持する。

    引数: rows (list[dict]) は同一銘柄の集計行。返り値: 期間合計 (dict)。
    """
    names=('profit_yen','loss_yen','net_yen','profit_units','loss_units','zero_units','trades',
        'net_r','long_trades','short_trades','held_minutes','candidates','accepted','cancelled')
    result={k:sum(r[k] for r in rows) for k in names}
    base=peak=dd=0.
    for row in sorted(rows,key=lambda r:r['session']):
        dd=max(dd,row['drawdown_yen'],peak-(base+row['minimum_yen']))
        peak=max(peak,base+row['maximum_yen']);base+=row['net_yen']
    result.update(drawdown_yen=dd,active_sessions=sum(r['trades']>0 for r in rows),
        positive_sessions=sum(r['net_yen']>0 for r in rows),
        without_max_trade=result['net_yen']-max([0.]+[r['max_win_yen'] for r in rows]),
        without_max_session=result['net_yen']-max([0.]+[r['net_yen'] for r in rows]))
    result['profit_factor']=ratio(result['profit_yen'],result['loss_yen'])
    aw=ratio(result['profit_yen'],result['profit_units']);al=ratio(result['loss_yen'],result['loss_units'])
    result['average_payoff']=ratio(aw,al) if aw is not None and al is not None else None
    return result


def basic(value: dict) -> dict:
    """機能: 事前固定した活動量・損小利大・集中回避を判定する。

    引数: value (dict)。返り値: 各条件と全体合否 (dict)。
    """
    flags=dict(有限統計=all(np.isfinite(value[k]) for k in ('net_yen','net_r','trades','active_sessions',
        'long_trades','short_trades','without_max_trade','without_max_session')),
        決済20以上=value['trades']>=20,活動6以上=value['active_sessions']>=6,
        両方向各3以上=min(value['long_trades'],value['short_trades'])>=3,黒字=value['net_yen']>0,
        利益損失比1_2以上=value['profit_factor'] is not None and np.isfinite(value['profit_factor']) and value['profit_factor']>=1.2,
        平均利益損失比1_2以上=value['average_payoff'] is not None and np.isfinite(value['average_payoff']) and value['average_payoff']>=1.2,
        最大勝ち除外=value['without_max_trade']>=0,最大黒字場除外=value['without_max_session']>=0)
    return dict(合格=all(flags.values()),検査={k:bool(v) for k,v in flags.items()})
