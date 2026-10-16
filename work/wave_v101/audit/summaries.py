"""独立再構成済みの親とcohortを、相殺前金額と全期間安定性へ集計する。"""

from datetime import date, timedelta
import math
import numpy as np

import compare_utils as checks
import financial
import math_oracle


def totals(net: np.ndarray, gross: np.ndarray, fees: np.ndarray,
           quantities: np.ndarray, cohort: bool = False) -> dict:
    """
    機能: 親又はcohort単位の費用後金額を相殺せず分類する。
    引数: net/gross/fees/quantities(ndarray)、cohort(bool)は建玉群集計。
    返り値: dict。金額・枚数・平均勝負とpayoff。取引なしは利益割合None。
    """
    positive,negative = net > 1e-5,net < -1e-5
    profit,loss = float(net[positive].sum()),float(-net[negative].sum())
    nw,nl = int(positive.sum()),int(negative.sum())
    aw,al = profit/nw if nw else None,loss/nl if nl else None
    name = 'cohorts' if cohort else 'campaigns'
    result = dict(profit=profit,loss=loss,net=profit-loss,gross=float(gross.sum()),fees=float(fees.sum()),
        winning_lots=int(quantities[positive].sum()),losing_lots=int(quantities[negative].sum()),
        flat_lots=int(quantities[~(positive|negative)].sum()),lots=int(quantities.sum()),
        profit_share=profit/(profit+loss) if profit+loss else None,average_win=aw,average_loss=al,
        payoff=aw/al if aw is not None and al is not None and al > 0 else None)
    result[name] = len(net)
    result['winning_'+name] = nw
    result['losing_'+name] = nl
    result['flat_'+name] = len(net)-nw-nl
    return result


def parent_totals(trades: np.ndarray) -> dict:
    """
    機能: 独立親16列から相殺前の金額と最終決済枚数を集計する。
    引数: trades(ndarray[float])は検算済み親。
    返り値: dict。親の利益損失。
    """
    return totals(trades[:,11],trades[:,10],trades[:,8]+trades[:,9],trades[:,5])


def cohort_totals(cohorts: np.ndarray, columns: list[str]) -> dict:
    """
    機能: 独立実注文会計で照合済みcohortの相殺前金額を集計する。
    引数: cohorts(ndarray[float])、columns(list[str])。
    返り値: dict。費用の親内配分でGP/GLを相殺しない。
    """
    index = {name:i for i,name in enumerate(columns)}
    return totals(cohorts[:,index['net']],cohorts[:,index['gross']],
                  cohorts[:,index['entry_fee']]+cohorts[:,index['exit_fee_share']],
                  cohorts[:,index['quantity']],cohort=True)


def path(curve: np.ndarray) -> dict:
    """
    機能: 原板全行の清算時価から頂点・底点・最大下落を独立計算する。
    引数: curve(ndarray[float])は残玉返済費用込み。
    返り値: dict。初期時価0も含む。
    """
    values = np.r_[0.,curve]
    return dict(equity_peak=float(values.max()),equity_trough=float(values.min()),
                equity_drawdown=float((np.maximum.accumulate(values)-values).max()))


def row(key: tuple[str,str], record: dict, config: dict, output: dict) -> dict:
    """
    機能: 全注文検算の完了親・全原板時価から一場の独立会計を作る。
    引数: key(tuple[str,str])、record/config/output(dict)。
    返り値: dict。最大占有/旧イベント統計の保存値は別に物理保有・現金と照合する。
    """
    finance = financial.verify_account(record,config,output)
    trades,curve = finance['trades'],finance['curve']
    cohorts,columns = np.asarray(output['growth_cohorts']),output['growth_cohort_columns']
    index = {name:i for i,name in enumerate(columns)}
    trace,stats,events = np.asarray(output['target_trace']),np.asarray(output['stats']),np.asarray(output['events'])
    checks.exact(stats[0],np.maximum(finance['positions'],0).sum(axis=1).max(initial=0),'最大実買保有')
    checks.exact(stats[1],np.maximum(-finance['positions'],0).sum(axis=1).max(initial=0),'最大実売保有')
    checks.exact(stats[8],np.abs(finance['positions']).sum(axis=1).max(initial=0),'最大実保有合計')
    checks.exact(stats[4:8],trace[-1,[0,1,4,5]],'終端保有/予約')
    checks.money(stats[15],finance['cash'][-1].sum(),'実注文現金と終端cash')
    result = dict(session=key[0],symbol=key[1],**parent_totals(trades),**path(curve))
    result['cohorts'] = cohort_totals(cohorts,columns)
    checks.money(result['cohorts']['net'],result['net'],'親とcohort合計')
    result['order_count'] = len(output['orders'])
    result['entry_order_count'] = int((output['orders'][:,7] == 1).sum())
    result['adding_order_count'] = result['entry_order_count']-len(trades)
    result['cohort_directions'] = {name:cohort_totals(cohorts[cohorts[:,index['side']] == side],columns)
                                   for name,side in [('買い',1),('売り',-1)]}
    result['sources'] = {name:dict(**parent_totals(trades[trades[:,1] == source]),
                                  **path(finance['source_curve'][:,source]))
                         for source,name in enumerate(('J2','O06'))}
    result['directions'] = {name:parent_totals(trades[trades[:,4] == side]) for name,side in [('買い',1),('売り',-1)]}
    result['maximums'] = {name:int(trace[:,i].max(initial=0)) for i,name in enumerate(output['trace_columns'])}
    for i,name in enumerate(output['trace_columns'][:4]):
        result['maximums'][name] = int(stats[i])
    result['stats'] = {name:float(stats[i]) for i,name in enumerate(output['stat_columns'])}
    result['event_counts'] = {str(int(code)):int((events[:,3] == code).sum()) for code in np.unique(events[:,3])}
    return result


def add_totals(rows: list[dict], cohort: bool = False) -> dict:
    """
    機能: 同商品同集計単位の会計を足し、平均と利益割合を再計算する。
    引数: rows(list[dict])、cohort(bool)は建玉群集計。
    返り値: dict。商品間の円金額を混ぜない。
    """
    name = 'cohorts' if cohort else 'campaigns'
    fields = ['profit','loss','net','gross','fees',name,'winning_'+name,'losing_'+name,'flat_'+name,
              'winning_lots','losing_lots','flat_lots','lots']
    result = {field:sum(item[field] for item in rows) for field in fields}
    profit,loss = result['profit'],result['loss']
    result['profit_share'] = profit/(profit+loss) if profit+loss else None
    nw,nl = result['winning_'+name],result['losing_'+name]
    result['average_win'] = profit/nw if nw else None
    result['average_loss'] = loss/nl if nl else None
    result['payoff'] = result['average_win']/result['average_loss'] if nw and nl else None
    return result


def aggregate(rows: list[dict], symbol: str, sessions: list[str]) -> dict:
    """
    機能: 日・週・場順を守り、親/cohort・源/方向・最大日除外と期間下落を独立算定する。
    引数: rows(list[dict])、symbol(str)、sessions(list[str])は評価順。
    返り値: dict。根のaggregateを正答生成に呼ばない。
    """
    selected = [r for session in sessions for r in rows if r['session'] == session and r['symbol'] == symbol]
    assert len(selected) == len(sessions)
    result = add_totals(selected)
    result['cohorts'] = add_totals([r['cohorts'] for r in selected],True)
    result['cohort_directions'] = {name:add_totals([r['cohort_directions'][name] for r in selected],True) for name in ('買い','売り')}
    for field in ('order_count','entry_order_count','adding_order_count'):
        result[field] = sum(r[field] for r in selected)
    cash,peak,drawdown = 0.,0.,0.
    for item in selected:
        drawdown = max(drawdown,item['equity_drawdown'],peak-cash-item['equity_trough'])
        peak = max(peak,cash+item['equity_peak'])
        cash += item['net']
    positive = sum(r['net'] > 1e-5 for r in selected)
    active = sum(r['campaigns'] > 0 for r in selected)
    result.update(equity_drawdown=drawdown,positive_sessions=positive,
        losing_sessions=sum(r['net'] < -1e-5 for r in selected),no_trade_sessions=len(selected)-active,
        active_sessions=active,session_count=len(selected),worst_session=min((r['net'] for r in selected),default=0.),
        all_sessions_profitable=all(r['net'] > 1e-5 for r in selected),positive_session_rate=positive/active if active else None)
    days,weeks = {},{}
    for item in selected:
        day = date.fromisoformat(item['session'][:10])
        for mapping,key in ((days,str(day)),(weeks,str(day-timedelta(days=day.weekday())))):
            mapping.setdefault(key,[]).append(item)
    result['days'] = {name:add_totals(items) for name,items in days.items()}
    result['weeks'] = {name:add_totals(items) for name,items in weeks.items()}
    for mapping,groups in ((result['days'],days),(result['weeks'],weeks)):
        for label,items in groups.items():
            mapping[label]['cohorts'] = add_totals([item['cohorts'] for item in items],True)
    best = max(result['days'],key=lambda name:result['days'][name]['net'],default=None)
    others = [item for item in selected if item['session'][:10] != best]
    result['best_day'] = best
    result['without_best_day'] = add_totals(others)
    result['without_best_day']['cohorts'] = add_totals([r['cohorts'] for r in others],True)
    result['sources'] = {name:add_totals([r['sources'][name] for r in selected]) for name in ('J2','O06')}
    result['directions'] = {name:add_totals([r['directions'][name] for r in selected]) for name in ('買い','売り')}
    result['maximums'] = {name:max((r['maximums'][name] for r in selected),default=0)
                          for name in (selected[0]['maximums'] if selected else [])}
    return result


def stability(rows: list[dict], config: dict, prices: dict, sessions: list[str]) -> dict:
    """
    機能: 共通ユーザー上限・共通評価場数で下方偏差と黒字率を独立計算する。
    引数: rows(list[dict])、config/prices(dict)、sessions(list[str])。
    返り値: dict。初回数量/設定上限/実ピークを分離し、無取引を黒字にしない。
    """
    result = {}
    for symbol in ('TOPIX','NK225'):
        selected = [r for r in rows if r['symbol'] == symbol and r['session'] in sessions]
        active = [r for r in selected if r['campaigns'] > 0]
        red = [r for r in active if r['net'] < -1e-5]
        v,cap,maximum = (1000.,10,8) if symbol == 'TOPIX' else (10.,20,16)
        initial = math_oracle.quantity_for(config,symbol)
        units = {r['session']:cap*v*float(prices[r['session'],symbol]['price'][0])*.001 for r in selected}
        normalized = np.asarray([r['net']/units[r['session']] for r in active],float)
        negatives = [min(value,0.)**2 for value in normalized]
        red_units = [-r['net']/units[r['session']] for r in red]
        nets = np.asarray([r['net'] for r in selected],float)
        result[symbol] = dict(configured_quantity=initial,comparison_cap=cap,
            maximum_configured_quantity=maximum if config['trend_growth_mode'] else initial,
            actual_peak_quantity=max((max(r['maximums']['held_long'],r['maximums']['held_short']) for r in selected),default=0),
            session_count=len(selected),active_sessions=len(active),no_trade_sessions=len(selected)-len(active),losing_sessions=len(red),
            positive_session_rate=sum(r['net'] > 1e-5 for r in active)/len(active) if active else None,
            mean_losing_session_yen=sum(-r['net'] for r in red)/len(red) if red else 0.,
            worst_session_loss_yen=max([-r['net'] for r in red],default=0.),
            downside_rms_units=math.sqrt(sum(negatives)/len(selected)) if selected else None,
            active_downside_rms_units=math.sqrt(sum(negatives)/len(active)) if active else None,
            mean_losing_session_units=sum(red_units)/len(red_units) if red else 0.,
            worst_session_loss_units=max(red_units,default=0.),
            active_net_q25_units=float(np.quantile(normalized,.25)) if active else None,
            active_net_median_units=float(np.median(normalized)) if active else None,
            session_net_q25_yen=float(np.quantile(nets,.25)) if selected else None,
            session_net_median_yen=float(np.median(nets)) if selected else None,
            worst_intraday_drawdown_units=max([r['equity_drawdown']/units[r['session']] for r in selected],default=0.),
            comparison_units_yen=units,
            definition='全条件共通上限10/20枚×倍率×当該場最初の正常価格0.1%。主RMS分母は共通全評価場数。無取引は活動黒字率の勝ちへ含めない。')
    return result
