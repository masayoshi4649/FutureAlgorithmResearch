"""異なる戦略の親を相殺せず、商品ごとに手数料後の利益と損失を集計する。"""

from datetime import date, timedelta
import math

import numpy as np


def fraction(profit: float, loss: float) -> float | None:
    """
    機能: 金額利益の割合を計算し、無取引を勝ちに数えない。
    引数: profit/loss(float、非負の利益・損失額)。
    返り値: float | None。金額変動がなければNone。
    """
    return profit / (profit + loss) if profit + loss > 0 else None


def trade_totals(trades: np.ndarray) -> dict:
    """
    機能: 一つの源又は商品で、完結した親の金額と決済枚数を計算する。
    引数: trades(ndarray、エンジン公開順の16列)。
    返り値: dict。利益は親の費用後netが正、損失は負の場合の絶対額。
    """
    net = trades[:, 11]
    wins, losses = net > 1e-5, net < -1e-5
    profit, loss = float(net[wins].sum()), float(-net[losses].sum())
    nw, nl = int(wins.sum()), int(losses.sum())
    average_win = profit / nw if nw else None
    average_loss = loss / nl if nl else None
    return dict(profit=profit, loss=loss, net=profit-loss,
                gross=float(trades[:, 10].sum()),
                fees=float((trades[:, 8]+trades[:, 9]).sum()),
                campaigns=len(trades), winning_campaigns=nw, losing_campaigns=nl,
                flat_campaigns=len(trades)-nw-nl,
                winning_lots=int(trades[wins, 5].sum()),
                losing_lots=int(trades[losses, 5].sum()),
                flat_lots=int(trades[~(wins | losses), 5].sum()),
                lots=int(trades[:, 5].sum()), profit_share=fraction(profit, loss),
                average_win=average_win, average_loss=average_loss,
                payoff=average_win/average_loss if average_win is not None
                    and average_loss is not None and average_loss > 0 else None)


def path_totals(curve: np.ndarray) -> dict:
    """
    機能: 全原板行の清算時価から日中の最大下落を算出する。
    引数: curve(ndarray[float]、当該セッション開始時を0とする清算時価)。
    返り値: dict。含み損と残玉返済手数料を含む最大下落・頂点・底点。
    """
    values = np.concatenate((np.zeros(1), curve))
    return dict(equity_peak=float(values.max()), equity_trough=float(values.min()),
                equity_drawdown=float((np.maximum.accumulate(values)-values).max()))


def account(key: tuple[str, str], output: dict) -> dict:
    """
    機能: 一商品一セッションの費用後会計と源別寄与を検算する。
    引数: key(tuple[str,str]、セッションと商品)、output(dict、機械的再生結果)。
    返り値: dict。源別の金額利益率を混同せず、全親の合計と整合させる。
    """
    orders, trades, curve = output['orders'], output['trades'], output['curve']
    totals = trade_totals(trades)
    assert len(orders) == 2*len(trades), '終端に未決済親が残っています'
    assert math.isclose(float(orders[:, 9].sum()), totals['fees'], abs_tol=1e-5)
    assert math.isclose(float(curve[-1]), totals['net'], abs_tol=1e-4)
    assert np.allclose(output['source_curve'].sum(axis=1), curve, atol=1e-4, rtol=0)
    assert not np.any(output['target_trace'][-1]), '終端の予約又は保有が残っています'
    row = dict(session=key[0], symbol=key[1], **totals, **path_totals(curve))
    # ----------------------------------------
    # 同じ日で源を相殺した損益から勝率を作らず、完結親のnetを保持する。
    row['sources'] = {}
    for source, name in [(0, 'J2'), (1, 'O06')]:
        selected = trades[trades[:, 1] == source]
        row['sources'][name] = dict(**trade_totals(selected),
                                  **path_totals(output['source_curve'][:, source]))
    row['directions'] = {name: trade_totals(trades[trades[:, 4] == side])
                         for side, name in [(1, '買い'), (-1, '売り')]}
    row['maximums'] = {name: int(output['target_trace'][:, i].max(initial=0))
                       for i, name in enumerate(output['trace_columns'])}
    for i, name in enumerate(output['trace_columns'][:4]):
        row['maximums'][name] = int(output['stats'][i])
    row['stats'] = {name: float(output['stats'][i])
                    for i, name in enumerate(output['stat_columns'])}
    row['event_counts'] = {str(int(code)): int(np.sum(output['events'][:, 3] == code))
                           for code in np.unique(output['events'][:, 3])}
    return row


def sum_totals(rows: list[dict]) -> dict:
    """
    機能: 同一商品の親別利益・損失を足し、平均勝負額と割合を再計算する。
    引数: rows(list[dict]、同商品・指定期間の会計)。
    返り値: dict。別商品を混ぜた円額比較は行わない。
    """
    additive = ('profit', 'loss', 'net', 'gross', 'fees', 'campaigns',
                'winning_campaigns', 'losing_campaigns', 'flat_campaigns',
                'winning_lots', 'losing_lots', 'flat_lots', 'lots')
    result = {field: sum(r[field] for r in rows) for field in additive}
    result['profit_share'] = fraction(result['profit'], result['loss'])
    nw, nl = result['winning_campaigns'], result['losing_campaigns']
    result['average_win'] = result['profit']/nw if nw else None
    result['average_loss'] = result['loss']/nl if nl else None
    result['payoff'] = result['average_win']/result['average_loss'] if nw and nl else None
    return result


def aggregate(rows: list[dict], symbol: str, sessions: list[str]) -> dict:
    """
    機能: 時系列を保ち、日夜・日別・週別と最大利益日を除く安定性を算出する。
    引数: rows(list[dict])、symbol(str)、sessions(list[str]、指定順の期間)。
    返り値: dict。無取引場は黒字数へ含めず、全行時価の期間下落を算出する。
    """
    selected = [r for key in sessions for r in rows
                if r['symbol'] == symbol and r['session'] == key]
    assert len(selected) == len(sessions)
    result = sum_totals(selected)
    cash, peak, drawdown = 0., 0., 0.
    for r in selected:
        drawdown = max(drawdown, r['equity_drawdown'], peak-cash-r['equity_trough'])
        peak = max(peak, cash+r['equity_peak'])
        cash += r['net']
    result.update(equity_drawdown=drawdown, positive_sessions=sum(r['net']>1e-5 for r in selected),
                  losing_sessions=sum(r['net'] < -1e-5 for r in selected),
                  no_trade_sessions=sum(r['campaigns']==0 for r in selected),
                  active_sessions=sum(r['campaigns']>0 for r in selected),
                  session_count=len(selected), worst_session=min((r['net'] for r in selected), default=0.),
                  all_sessions_profitable=all(r['net']>1e-5 for r in selected))
    result['positive_session_rate'] = result['positive_sessions']/result['active_sessions'] \
        if result['active_sessions'] else None
    # ----------------------------------------
    # 日別・週別の差額は親別G/Lの合計と区別する。最大日除外も源別相殺はしない。
    days, weeks = {}, {}
    for r in selected:
        day = date.fromisoformat(r['session'][:10])
        for mapping, label in [(days, str(day)), (weeks, str(day-timedelta(days=day.weekday())))]:
            mapping.setdefault(label, []).append(r)
    result['days'] = {key: sum_totals(value) for key, value in days.items()}
    result['weeks'] = {key: sum_totals(value) for key, value in weeks.items()}
    best = max(result['days'], key=lambda d: result['days'][d]['net'], default=None)
    others = [r for r in selected if r['session'][:10] != best]
    result['best_day'] = best
    result['without_best_day'] = sum_totals(others)
    result['sources'] = {name: sum_totals([r['sources'][name] for r in selected])
                         for name in ('J2', 'O06')}
    result['directions'] = {name: sum_totals([r['directions'][name] for r in selected])
                            for name in ('買い', '売り')}
    result['maximums'] = {name: max((r['maximums'][name] for r in selected), default=0)
                           for name in (selected[0]['maximums'] if selected else [])}
    return result
