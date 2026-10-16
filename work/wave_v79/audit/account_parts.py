"""統合器を再実行せず、保存注文と原本気配から全明細・全行時価を再構成する。"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys
from datetime import date, timedelta

import numpy as np

from adapters import clearing_curve, orders9
from independent_account import CAP, POINT, fee, near, reconstruct


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SUM_FIELDS = ("profit", "loss", "net", "gross", "fees", "trades", "wins", "losses", "flats", "legs", "winning_legs", "losing_legs",
    "winning_lots", "losing_lots", "flat_lots", "campaign_profit", "campaign_loss", "hold_seconds", "adds", "risk_excesses", "spread_drag")


def metrics(a: dict) -> dict:
    """機能: 金額明細比率・平均明細勝敗・組勝率を独立の分母で計算する。

    引数: a(dict)。返り値: 指標を追加したdict。
    """
    p, l = a["profit"], a["loss"]
    a["profit_share"] = p / (p+l) if p+l else None
    a["money_loss_share"] = l / (p+l) if p+l else None
    a["profit_loss_ratio"] = p / l if l else None
    a["average_win"] = p / a["winning_legs"] if a["winning_legs"] else None
    a["average_loss"] = l / a["losing_legs"] if a["losing_legs"] else None
    a["payoff"] = a["average_win"] / a["average_loss"] if a["average_win"] is not None and a["average_loss"] else None
    a["win_rate"] = a["wins"] / a["trades"] if a["trades"] else None
    a["average_net"] = a["net"] / a["trades"] if a["trades"] else None
    a["average_hold_seconds"] = a["hold_seconds"] / a["trades"] if a["trades"] else None
    cp, cl = a["campaign_profit"], a["campaign_loss"]
    a["campaign_profit_share"] = cp / (cp+cl) if cp+cl else None
    a["goal80"] = bool(p+l > 0 and p > 0 and p >= 4*l)
    return a


def same_fields(actual: dict, saved: dict, label: object) -> int:
    """機能: 元帳票の全項目を比較し、円演算誤差だけを許容する。

    引数: actual/saved(dict)、label(object)。返り値: 比較項目数(int)。
    """
    count = 0
    for field, value in saved.items():
        assert field in actual, (label, field, "独立値なし")
        expected = actual[field]
        if isinstance(value, dict):
            assert set(value) == set(expected), (label, field)
            count += same_fields(expected, value, (label, field))
        elif isinstance(value, (float, int)) and not isinstance(value, bool):
            assert abs(value-expected) < 1.e-4, (label, field, value, expected)
        else:
            assert value == expected, (label, field, value, expected)
        count += 1
    return count


def aggregate(rows: list[dict], symbol: str, sessions: list[str]) -> dict:
    """機能: 商品の全明細・組会計を場順に合算し、DDと最大黒字場除外を求める。

    引数: rows(list[dict])、symbol(str)、sessions(list[str])。返り値: 期間会計(dict)。
    """
    own = sorted((r for r in rows if r["symbol"] == symbol and r["session"] in sessions), key=lambda r: sessions.index(r["session"]))
    result = {k: sum(r[k] for r in own) for k in SUM_FIELDS}
    for k in ("max_trade_loss", "max_leg_loss", "max_long", "max_short"):
        result[k] = max((r[k] for r in own), default=0.)
    result["active_sessions"] = sum(r["trades"] > 0 for r in own)
    result["winning_sessions"] = sum(r["net"] > 0 for r in own)
    wealth = maximum = worst = 0.
    for r in own:
        worst = max(worst, r["drawdown"], maximum-(wealth+r["curve_min"]))
        maximum = max(maximum, wealth+r["curve_max"])
        wealth += r["net"]
    result["drawdown"] = worst
    result["max_session_drawdown"] = max((r["drawdown"] for r in own), default=0.)
    best = max(own, key=lambda r: r["net"], default=None)
    result["without_best_session"] = result["net"]-(best["net"] if best else 0.)
    p = result["profit"]-(best["profit"] if best else 0.)
    l = result["loss"]-(best["loss"] if best else 0.)
    result["without_best_profit_share"] = p/(p+l) if p+l else None
    result["without_best_profit_loss_ratio"] = p/l if l else None
    return metrics(result)


base_aggregate = aggregate


def aggregate(rows: list[dict], symbol: str, sessions: list[str]) -> dict:
    """機能: 前半・後半・全期の場、開始日、週、連続赤字を独立集計する。

    引数: rows(list[dict])、symbol(str)、sessions(list[str])。返り値: 期間会計(dict)。
    """
    result = base_aggregate(rows, symbol, sessions)
    own = sorted((r for r in rows if r['symbol'] == symbol and r['session'] in sessions), key=lambda r:sessions.index(r['session']))
    for name in ('extensions','protections','pauses','rearms','skipped'):
        result[name] = sum(r[name] for r in own)
    result.update(session_count=len(own), losing_sessions=sum(r['net']<0 for r in own),
        no_trade_sessions=sum(r['trades']==0 for r in own), flat_active_sessions=sum(r['trades']>0 and r['net']==0 for r in own),
        positive_session_rate=result['winning_sessions']/result['active_sessions'] if result['active_sessions'] else None,
        all_sessions_profitable=bool(own and min(r['net'] for r in own)>0), worst_session=min((r['net'] for r in own), default=0.))
    streak=longest=0
    for r in own:
        streak = streak+1 if r['net']<0 else 0 if r['trades']>0 else streak
        longest=max(longest,streak)
    result['consecutive_losing_sessions']=longest
    days={}; weeks={}
    for r in own:
        stamp=date.fromisoformat(r['session'][:10]); monday=stamp-timedelta(days=stamp.weekday())
        for destination, label in ((days,str(stamp)),(weeks,str(monday))):
            if label not in destination:destination[label]={name:0 for name in ('profit','loss','net','trades')}
            for name in ('profit','loss','net','trades'):destination[label][name]+=r[name]
    best=max(days,key=lambda label:days[label]['net'],default=None)
    profit=result['profit']-(days[best]['profit'] if best else 0.)
    loss=result['loss']-(days[best]['loss'] if best else 0.)
    result.update(days=days,weeks=weeks,worst_day=min((r['net'] for r in days.values()),default=0.),
        positive_days=sum(r['net']>0 for r in days.values()),active_days=sum(r['trades']>0 for r in days.values()),
        best_day=best,without_best_day_net=profit-loss,without_best_day_profit_share=profit/(profit+loss) if profit+loss else None,
        day_sessions_net=sum(r['net'] for r in own if r['session'].endswith('_Day')),
        night_sessions_net=sum(r['net'] for r in own if r['session'].endswith('_Night')),
        positive_weeks=sum(r['net']>0 for r in weeks.values()),week_count=len(weeks))
    sequence=[value for row in own for value in row.get('trade_nets',[])]
    losing=longest=0
    for value in sequence:
        losing=losing+1 if value<0 else 0;longest=max(longest,losing)
    result['max_consecutive_trade_losses']=longest
    return result


def row_account(key: tuple, args: tuple, ledger: dict, ready: dict) -> dict:
    """機能: 次行約定・全量・料金・明細・全曲線と新管理の計数を独立に照合する。

    引数: key(tuple)、args(tuple)、ledger/ready(dict)。返り値: 独立口座会計(dict)。
    """
    symbol=key[1]; orders=ledger['orders']; trades=ledger['trades']; events=ledger['events']
    assert np.all(ledger['stats'][:3]==0), ('末尾に建玉又は未解決注文',key)
    data=dict(time_s=args[0],seq=ready['seq'],bid=args[1],ask=args[2])
    account,raw_curve=reconstruct(data,dict(symbol=symbol,session=key[0],orders=orders9(orders)))
    curve=clearing_curve(symbol,orders,raw_curve)
    assert hashlib.sha256(curve.tobytes()).hexdigest()==ledger['curve_hash'],(key,'全行清算時価')
    expected=np.array([[d['campaign'],d['entry_row'],d['exit_row'],d['side'],d['quantity'],d['entry'],d['exit'],
        d['entry_fee'],d['exit_fee'],d['gross'],d['net'],0] for d in account['details']],dtype=float).reshape((-1,12))
    np.testing.assert_allclose(trades,expected,atol=1.e-4,rtol=0)
    opened=orders[orders[:,7]==1];closed=orders[orders[:,7]==0]
    assert len(opened)==len(closed)==len(trades)==len(set(opened[:,2]))
    assert np.all(orders[:,4]==CAP[symbol]) and np.all(opened[:,9]==0) and np.all(closed[:,9]==-1)
    assert np.all(orders[:,8]==fee(symbol,CAP[symbol]))
    assert np.array_equal(ledger['stats'][3:5],[account['max_long'],account['max_short']])
    assert ledger['stats'][5]==ledger['stats'][6]==0
    hold=0.;reasons={}
    for first,close in zip(opened,closed):
        assert first[2]==close[2] and first[3]==-close[3] and first[6]==10
        i=int(first[1]);assert args[5][i]==first[3] and args[3][i] and not args[4][i]
        assert args[15]+300.<=args[0][i]<args[16]-300.
        previous=closed[closed[:,0]<first[0]]
        assert not len(previous) or args[0][i]-args[0][int(previous[-1,0])]>=30.
        hold+=args[0][int(close[0])]-args[0][int(first[0])]
        reason=str(int(close[6]));reasons[reason]=reasons.get(reason,0)+1
    net=np.array([r['net'] for r in account['details']]); loss_streak=maximum_streak=0
    for value in net:
        loss_streak=loss_streak+1 if value<0 else 0;maximum_streak=max(maximum_streak,loss_streak)
    row=dict(session=key[0],symbol=symbol,profit=account['profit'],loss=account['loss'],net=account['net'],
        gross=account['gross'],fees=account['fees'],trades=account['campaigns'],wins=account['campaign_wins'],losses=account['campaign_losses'],
        flats=account['campaign_flats'],legs=account['trades'],winning_legs=account['wins'],losing_legs=account['losses'],
        winning_lots=account['winning_lots'],losing_lots=account['losing_lots'],flat_lots=account['flat_lots'],
        campaign_profit=account['campaign_profit'],campaign_loss=account['campaign_loss'],hold_seconds=float(hold),
        drawdown=float(np.max(np.maximum.accumulate(np.r_[0.,curve])[1:]-curve)),curve_min=min(0.,float(curve.min())),
        curve_max=max(0.,float(curve.max())),max_trade_loss=account['max_campaign_loss'],max_leg_loss=account['max_campaign_loss'],
        max_long=account['max_long'],max_short=account['max_short'],adds=0,risk_excesses=0,
        spread_drag=sum(.5*(args[2][int(o[0])]-args[1][int(o[0])])*o[4]*POINT[symbol] for o in orders),
        reasons=reasons,active_sessions=int(len(trades)>0),candidate_count=int(np.count_nonzero(args[5])),
        trade_nets=net.tolist(),max_consecutive_trade_losses=maximum_streak,
        leading_trade_losses=int(np.argmax(net>=0)) if np.any(net>=0) else len(net),trailing_trade_losses=loss_streak)
    for code,name in ((20,'extensions'),(21,'protections'),(22,'pauses'),(23,'rearms'),(24,'skipped')):
        row[name]=int(np.count_nonzero(events[:,2]==code))
    assert np.all(np.isin(events[:,2],(20,21,22,23,24)))
    assert not len(closed) or np.all(args[0][closed[:,0].astype(int)]<args[16]+300.),'返済は予定場末から5分未満'
    row['判断約定最大秒']=max((float(args[0][int(o[0])]-args[0][int(o[1])]) for o in orders),default=0.)
    return metrics(row)

