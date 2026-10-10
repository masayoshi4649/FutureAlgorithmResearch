"""保存統計を、別会計の注文・全観測行から過不足なく再構成する。"""

from __future__ import annotations

import math
import numpy as np


def equal(actual: object, expected: object, path: str = '') -> None:
    """機能: 必須項目の欠落と余分な項目も拒否して値を比較する。

    引数: actual/expected (object)、path (str)。返り値: なし (None)。
    """
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and actual.keys() == expected.keys(), (path, '項目不一致')
        for key, value in expected.items():
            equal(actual[key], value, path + '/' + key)
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), (path, '件数不一致')
        for i, value in enumerate(expected):
            equal(actual[i], value, path + '/' + str(i))
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert isinstance(actual, (int, float)) and not isinstance(actual, bool), path
        assert math.isfinite(actual) and math.isfinite(expected) and abs(actual - expected) <= 1e-6, path
    else:
        assert actual == expected, (path, actual, expected)


def session(identifier: str, ready: dict, result: dict, config: dict, basic: dict, curves: dict) -> dict:
    """機能: 注文と別会計曲線から一セッションの全表示指標を組み立てる。

    引数: identifier (str)、ready/result/config/basic/curves (dict)。返り値: 指標 (dict)。
    """
    fields = ('symbol', 'session', 'gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units',
        'loss_units', 'zero_units', 'cycles', 'cycle_wins', 'cycle_losses', 'cycle_profit_yen',
        'cycle_loss_yen', 'drawdown_yen', 'min_equity_yen', 'max_equity_yen', 'max_long', 'max_short', 'closed_units')
    output = {name: basic[name] for name in fields}
    output['id'] = identifier
    orders, trades = result['orders'], result['trades']
    factor = config['point_value']
    gains, risks, retracements = [], [], []
    streak = longest = 0
    for cycle in result['cycles']:
        number, begin, end = map(int, cycle[:3])
        opening = orders[(orders[:, 2] == number) & (orders[:, 7] == 1)]
        assert len(opening) == 1 and int(opening[0, 6]) == 20, '固定注文器は追加・反転しない'
        assert begin > 0 and opening[0, 0] == begin
        initial_atr = result['atr_curve'][begin - 1, 9]
        risk = float(opening[0, 4] * config['stop_atr'] * initial_atr)
        assert math.isfinite(risk) and risk > 0
        equal(float(cycle[4]), risk, '初回損失予算')
        equal(float(cycle[5]), float(initial_atr), '初回ATR')
        legs = trades[trades[:, 0] == number]
        gain = float(np.sum(legs[:, 2] * legs[:, 3] * (legs[:, 5] - legs[:, 4])))
        equal(float(cycle[3]), gain, '組損益')
        gains.append(gain * factor); risks.append(gain / risk)
        streak = streak + 1 if gain < 0 else 0
        longest = max(longest, streak)
        path = curves['equity'][begin:end + 1] - curves['realized'][begin - 1]
        equal(float(path[-1]), gain, '組終了時価')
        peak = max(0., float(np.max(path)))
        loss = max(0., peak - gain)
        retracements.append(dict(campaign=number, entry_row=begin, exit_row=end, peak_yen=peak * factor,
            final_yen=gain * factor, retracement_yen=loss * factor, risk_yen=risk * factor,
            retracement_r=loss / risk, positive_peak=peak > 1e-8,
            holding_minutes=float((ready['time_s'][end] - ready['time_s'][begin]) / 60.)))
    durations = np.diff(ready['time_s'], append=ready['time_s'][-1]) / 60.
    output.update(net_r=float(np.sum(risks)), reversals=0, longest_losing_streak=longest,
        maximum_trade_profit=max([0.] + gains), maximum_trade_loss=min([0.] + gains),
        two_largest_cycle_profits=sorted((v for v in gains if v > 0), reverse=True)[:2],
        long_unit_minutes=float(np.sum(curves['long'] * durations)),
        short_unit_minutes=float(np.sum(curves['short'] * durations)),
        opening_orders=int(np.sum(orders[:, 7] == 1)), retracements=retracements)
    assert result['stats'][10] == 0
    return output


def ratio(a: float, b: float) -> float | None:
    """機能: 定義できない比率をゼロに偽装せず欠損として返す。

    引数: a/b (float)。返り値: 比率又は欠損 (float|None)。
    """
    return a / b if b > 1e-8 else None


def period(rows: list[dict], series: dict, names: list[str], symbol: str, factor: float) -> dict:
    """機能: 全行時価を連結し、期間の全必須項目を独立計算する。

    引数: rows (list[dict])、series (dict)、names (list[str])、symbol (str)、factor (float)。
    返り値: 期間指標 (dict)。
    """
    selected = [r for r in rows if r['symbol'] == symbol and r['session'] in names]
    assert len(selected) == len(names) and {r['session'] for r in selected} == set(names)
    fields = ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units',
        'cycles', 'cycle_wins', 'cycle_losses', 'cycle_profit_yen', 'cycle_loss_yen', 'net_r', 'closed_units',
        'long_unit_minutes', 'short_unit_minutes', 'opening_orders')
    output = {name: sum(r[name] for r in selected) for name in fields}
    cash, joined = 0., [np.zeros(1)]
    for name in sorted(names):
        values = series[(name, symbol)] * factor
        joined.append(cash + values)
        cash += values[-1]
    curve = np.concatenate(joined)
    best = max(range(len(selected)), key=lambda i: selected[i]['net_yen'])
    trimmed = [r for i, r in enumerate(selected) if i != best]
    output.update(money_ratio=ratio(output['gross_profit_yen'], output['gross_loss_yen']),
        cycle_ratio=ratio(output['cycle_profit_yen'], output['cycle_loss_yen']),
        win_sessions=sum(r['net_yen'] > 0 for r in selected), active_sessions=sum(r['cycles'] > 0 for r in selected),
        worst_session=min(r['net_yen'] for r in selected),
        drawdown_yen=float(np.max(np.maximum.accumulate(curve) - curve)),
        best_removed_net=sum(r['net_yen'] for r in trimmed),
        best_removed_pf=ratio(sum(r['cycle_profit_yen'] for r in trimmed), sum(r['cycle_loss_yen'] for r in trimmed)),
        best_trade_removed_net=output['net_yen'] - max(r['maximum_trade_profit'] for r in selected),
        max_long=max(r['max_long'] for r in selected), max_short=max(r['max_short'] for r in selected),
        longest_losing_streak=max(r['longest_losing_streak'] for r in selected), session_count=len(selected),
        average_unit_payoff=ratio(output['gross_profit_yen'] / output['profit_units'], output['gross_loss_yen'] / output['loss_units'])
            if output['profit_units'] and output['loss_units'] else None)
    equal(float(cash), output['net_yen'], '連結時価と収支')
    all_retracements = [r for item in selected for r in item['retracements']]
    totals = {}
    for label, part in (('all', all_retracements), ('positive_peak', [r for r in all_retracements if r['positive_peak']])):
        values = [r['retracement_r'] for r in part]
        yen = [r['retracement_yen'] for r in part]
        totals[label] = dict(cycles=len(part), sum_yen=sum(yen), sum_r=sum(values),
            mean_r=float(np.mean(values)) if values else None, median_r=float(np.median(values)) if values else None,
            mean_yen=float(np.mean(yen)) if yen else None, median_yen=float(np.median(yen)) if yen else None)
    totals['holding_minutes'] = sum(r['holding_minutes'] for r in all_retracements)
    output['retracement'] = totals
    return output
