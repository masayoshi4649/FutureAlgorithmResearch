"""既存の独立明細会計へ、日別・連敗・期間別の安定性を追加する。"""

from datetime import date,timedelta
import importlib.util
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('前回の全玉会計78',HERE.parent/'wave_v77/accounting.py')
BASE=importlib.util.module_from_spec(spec);spec.loader.exec_module(BASE)


def account(key: tuple,args: tuple,out: tuple) -> dict:
    """機能: 原本順の全決済と管理イベントを会計する。

    引数: key(tuple)、args/out(tuple)。返り値: 一場一商品会計(dict)。
    """
    a=BASE.account(key,args,out)
    for code,name in [(20,'extensions'),(21,'protections'),(22,'pauses'),(23,'rearms'),(24,'skipped')]:a[name]=int((out[4][:,2]==code).sum())
    losses=[bool(t[10]<0) for t in out[1]];streak=longest=leading=0
    for i,lost in enumerate(losses):
        streak=streak+1 if lost else 0;longest=max(longest,streak)
        if lost and leading==i:leading+=1
    a.update(max_consecutive_trade_losses=longest,leading_trade_losses=leading,trailing_trade_losses=streak)
    return a


def aggregate(rows: list[dict],symbol: str,sessions: list[str]) -> dict:
    """機能: 同商品内で金額比率と日・週・連続赤字を混同せず集計する。

    引数: rows(list[dict])、symbol(str)、sessions(list[str])。返り値: 期間会計(dict)。
    """
    a=BASE.aggregate(rows,symbol,sessions);rs=sorted([r for r in rows if r['symbol']==symbol and r['session'] in sessions],key=lambda r:sessions.index(r['session']))
    for name in ('extensions','protections','pauses','rearms','skipped'):a[name]=sum(r[name] for r in rs)
    a['session_count']=len(rs);a['losing_sessions']=sum(r['net']<0 for r in rs);a['no_trade_sessions']=sum(r['trades']==0 for r in rs)
    a['flat_active_sessions']=sum(r['trades']>0 and r['net']==0 for r in rs)
    a['positive_session_rate']=a['winning_sessions']/a['active_sessions'] if a['active_sessions'] else None
    a['all_sessions_profitable']=bool(rs and all(r['net']>0 for r in rs))
    a['worst_session']=min((r['net'] for r in rs),default=0.)
    streak=longest=0
    for r in rs:
        if r['net']<0:streak+=1;longest=max(longest,streak)
        elif r['trades']>0:streak=0
    a['consecutive_losing_sessions']=longest
    streak=longest=0
    for r in rs:
        longest=max(longest,r['max_consecutive_trade_losses'],streak+r['leading_trade_losses'])
        streak=streak+r['trades'] if r['leading_trade_losses']==r['trades'] else r['trailing_trade_losses']
    a['max_consecutive_trade_losses']=longest
    days={};weeks={}
    for r in rs:
        d=date.fromisoformat(r['session'][:10]);week=str(d-timedelta(days=d.weekday()));key=str(d)
        for group,label in ((days,key),(weeks,week)):
            if label not in group:group[label]=dict(profit=0.,loss=0.,net=0.,trades=0)
            for field in ('profit','loss','net','trades'):group[label][field]+=r[field]
    a['days']=days;a['weeks']=weeks;a['worst_day']=min((v['net'] for v in days.values()),default=0.)
    a['positive_days']=sum(v['net']>0 for v in days.values());a['active_days']=sum(v['trades']>0 for v in days.values())
    best=max(days,key=lambda d:days[d]['net'],default=None);a['best_day']=best
    p=a['profit']-(days[best]['profit'] if best else 0.);l=a['loss']-(days[best]['loss'] if best else 0.)
    a['without_best_day_net']=p-l;a['without_best_day_profit_share']=p/(p+l) if p+l else None
    a['day_sessions_net']=sum(r['net'] for r in rs if r['session'].endswith('_Day'))
    a['night_sessions_net']=sum(r['net'] for r in rs if r['session'].endswith('_Night'))
    a['positive_weeks']=sum(v['net']>0 for v in weeks.values());a['week_count']=len(weeks)
    return a
