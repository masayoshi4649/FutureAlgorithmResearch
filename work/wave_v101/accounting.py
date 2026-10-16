"""実際の増玉と全量返済の費用を保存し、親と建玉群の利益損失を分けて集計する。"""

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


# ----------------------------------------


def cohort_totals(cohorts: np.ndarray, columns: list[str]) -> dict:
    """
    機能: 実約定した各建玉群の費用後損益を相殺前に集計する。
    引数: cohorts (ndarray[float])、columns (list[str]) は建玉群と列定義。
    返り値: dict。親内で利益と損失を相殺した割合とは別の金額と枚数。
    """
    positions = {name: i for i, name in enumerate(columns)}
    net = cohorts[:, positions['net']]
    quantities = cohorts[:, positions['quantity']]
    assert np.isfinite(net).all() and np.isfinite(quantities).all()
    wins, losses = net > 1e-5, net < -1e-5
    profit, loss = float(net[wins].sum()), float(-net[losses].sum())
    nw, nl = int(wins.sum()), int(losses.sum())
    average_win = profit / nw if nw else None
    average_loss = loss / nl if nl else None
    return dict(profit=profit, loss=loss, net=profit-loss,
                gross=float(cohorts[:, positions['gross']].sum()),
                fees=float((cohorts[:, positions['entry_fee']] +
                            cohorts[:, positions['exit_fee_share']]).sum()),
                cohorts=len(cohorts), winning_cohorts=nw, losing_cohorts=nl,
                flat_cohorts=len(cohorts)-nw-nl,
                winning_lots=int(quantities[wins].sum()),
                losing_lots=int(quantities[losses].sum()),
                flat_lots=int(quantities[~(wins | losses)].sum()),
                lots=int(quantities.sum()), profit_share=fraction(profit, loss),
                average_win=average_win, average_loss=average_loss,
                payoff=average_win/average_loss if average_win is not None
                    and average_loss is not None and average_loss > 0 else None)


def verify_campaigns(key: tuple[str, str], output: dict) -> None:
    """
    機能: 複数新規と一括返済の注文・親・建玉群を独立に突き合わせる。
    引数: key (tuple[str,str])、output (dict) は商品と正式終端の再生結果。
    返り値: None。数量・実料金・現金損益の不一致があれば停止する。
    """
    orders, trades = output['orders'], output['trades']
    cohorts, columns = output['growth_cohorts'], output['growth_cohort_columns']
    positions = {name: i for i, name in enumerate(columns)}
    multiplier = 1000. if key[1] == 'TOPIX' else 10.
    fee_unit = 41.8 if key[1] == 'TOPIX' else 11.
    assert np.all(orders[:, 5] > 0) and np.all(orders[:, 5] == np.floor(orders[:, 5]))
    assert np.array_equal(orders[:, 9], np.floor(orders[:, 5] * fee_unit + 1e-8))
    assert len(orders) == len(cohorts) + len(trades), '実新規数と全量返済数が一致しません'
    assert len(set(trades[:, 0])) == len(trades), '追加を別の親に数えています'
    assert set(orders[:, 2]) == set(trades[:, 0]) == set(cohorts[:, positions['parent_id']])
    for parent in trades:
        ident, side, quantity = parent[0], parent[4], parent[5]
        entries = orders[(orders[:, 2] == ident) & (orders[:, 7] == 1)]
        exits = orders[(orders[:, 2] == ident) & (orders[:, 7] == 0)]
        selected = cohorts[cohorts[:, positions['parent_id']] == ident]
        assert len(exits) == 1 and len(entries) == len(selected)
        assert len(set(selected[:, positions['cohort_id']])) == len(selected)
        for cohort in selected:
            matching = entries[entries[:, 0] == cohort[positions['entry_row']]]
            assert len(matching) == 1
            assert matching[0, 5] == cohort[positions['quantity']]
            assert matching[0, 6] == cohort[positions['entry_price']]
            assert matching[0, 9] == cohort[positions['entry_fee']]
        assert entries[:, 5].sum() == exits[0, 5] == quantity
        assert np.all(entries[:, 4] == side) and exits[0, 4] == -side
        assert selected[:, positions['quantity']].sum() == quantity
        assert np.all(selected[:, positions['side']] == side)
        weighted = float(np.dot(entries[:, 5], entries[:, 6]) / quantity)
        assert math.isclose(weighted, parent[6], abs_tol=1e-8)
        assert entries[:, 9].sum() == parent[8] == selected[:, positions['entry_fee']].sum()
        assert exits[0, 9] == parent[9] == selected[:, positions['exit_fee_share']].sum()
        allocation = np.array([int(parent[9]) * int(cohort[positions['quantity']]) // int(quantity)
                               for cohort in selected], dtype=np.int64)
        remainder = int(parent[9]) - int(allocation.sum())
        priority = sorted(range(len(selected)), key=lambda i: (
            -(int(parent[9]) * int(selected[i, positions['quantity']]) % int(quantity)),
            int(selected[i, positions['cohort_id']])))
        for i in priority[:remainder]:
            allocation[i] += 1
        assert np.array_equal(allocation, selected[:, positions['exit_fee_share']])
        assert np.all(selected[:, positions['exit_row']] == parent[3])
        assert np.all(selected[:, positions['exit_price']] == parent[7])
        gross = side * float(np.dot(entries[:, 5], exits[0, 6]-entries[:, 6])) * multiplier
        assert math.isclose(gross, parent[10], abs_tol=1e-4)
        assert math.isclose(gross, float(selected[:, positions['gross']].sum()), abs_tol=1e-4)
        cash = -float(np.sum(orders[orders[:, 2] == ident, 4] *
                             orders[orders[:, 2] == ident, 5] *
                             orders[orders[:, 2] == ident, 6])) * multiplier
        cash -= float(orders[orders[:, 2] == ident, 9].sum())
        assert math.isclose(cash, parent[11], abs_tol=1e-4)
        assert math.isclose(cash, float(selected[:, positions['net']].sum()), abs_tol=1e-4)


def account(key: tuple[str, str], output: dict) -> dict:
    """
    機能: 一商品一セッションの費用後会計と源別寄与を検算する。
    引数: key(tuple[str,str]、セッションと商品)、output(dict、機械的再生結果)。
    返り値: dict。源別の金額利益率を混同せず、全親の合計と整合させる。
    """
    orders, trades, curve = output['orders'], output['trades'], output['curve']
    totals = trade_totals(trades)
    verify_campaigns(key, output)
    assert math.isclose(float(orders[:, 9].sum()), totals['fees'], abs_tol=1e-5)
    assert math.isclose(float(curve[-1]), totals['net'], abs_tol=1e-4)
    assert np.allclose(output['source_curve'].sum(axis=1), curve, atol=1e-4, rtol=0)
    assert not np.any(output['target_trace'][-1]), '終端の予約又は保有が残っています'
    row = dict(session=key[0], symbol=key[1], **totals, **path_totals(curve))
    cohorts, columns = output['growth_cohorts'], output['growth_cohort_columns']
    positions = {name: i for i, name in enumerate(columns)}
    row['cohorts'] = cohort_totals(cohorts, columns)
    assert math.isclose(row['cohorts']['net'], row['net'], abs_tol=1e-4)
    assert row['cohorts']['fees'] == row['fees'] and row['cohorts']['lots'] == row['lots']
    row['order_count'] = len(orders)
    row['entry_order_count'] = int(np.sum(orders[:, 7] == 1))
    row['adding_order_count'] = row['entry_order_count'] - row['campaigns']
    row['cohort_directions'] = {name: cohort_totals(cohorts[cohorts[:, positions['side']] == side], columns)
                              for side, name in [(1, '買い'), (-1, '売り')]}
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


# ----------------------------------------


def sum_cohort_totals(rows: list[dict]) -> dict:
    """
    機能: 実建玉群の相殺前利益・損失・費用・枚数を期間で足す。
    引数: rows (list[dict])。同じ商品の建玉群会計。
    返り値: dict。期間の建玉群平均と金額利益割合を再計算した会計。
    """
    additive = ('profit', 'loss', 'net', 'gross', 'fees', 'cohorts',
                'winning_cohorts', 'losing_cohorts', 'flat_cohorts',
                'winning_lots', 'losing_lots', 'flat_lots', 'lots')
    result = {field: sum(row[field] for row in rows) for field in additive}
    result['profit_share'] = fraction(result['profit'], result['loss'])
    nw, nl = result['winning_cohorts'], result['losing_cohorts']
    result['average_win'] = result['profit'] / nw if nw else None
    result['average_loss'] = result['loss'] / nl if nl else None
    result['payoff'] = result['average_win'] / result['average_loss'] if nw and nl else None
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
    result['cohorts'] = sum_cohort_totals([row['cohorts'] for row in selected])
    result['cohort_directions'] = {
        name: sum_cohort_totals([row['cohort_directions'][name] for row in selected])
        for name in ('買い', '売り')}
    for field in ('order_count', 'entry_order_count', 'adding_order_count'):
        result[field] = sum(row[field] for row in selected)
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
    for mapping, groups in ((result['days'], days), (result['weeks'], weeks)):
        for label, values in groups.items():
            mapping[label]['cohorts'] = sum_cohort_totals([row['cohorts'] for row in values])
    best = max(result['days'], key=lambda d: result['days'][d]['net'], default=None)
    others = [r for r in selected if r['session'][:10] != best]
    result['best_day'] = best
    result['without_best_day'] = sum_totals(others)
    result['without_best_day']['cohorts'] = sum_cohort_totals([row['cohorts'] for row in others])
    result['sources'] = {name: sum_totals([r['sources'][name] for r in selected])
                         for name in ('J2', 'O06')}
    result['directions'] = {name: sum_totals([r['directions'][name] for r in selected])
                            for name in ('買い', '売り')}
    result['maximums'] = {name: max((r['maximums'][name] for r in selected), default=0)
                           for name in (selected[0]['maximums'] if selected else [])}
    return result
