"""毎セッションの損失抑制を、両銘柄別に評価する。"""

import math

import numpy as np

import common


def summarize(rows: list[dict], symbol: str, sessions: list[str]) -> dict:
    """
    機能: 同一銘柄の収支と安定性を計算する。
    引数: rows(list[dict])、symbol(str)、sessions(list[str])は会計と対象範囲。
    返り値: dictは利益損失・活動・赤字頻度・最大勝ち除外等。
    """
    selected = [row for row in rows if row['symbol'] == symbol and row['session'] in sessions]
    assert len(selected) == len(sessions) == len(set(sessions))
    assert {row['session'] for row in selected} == set(sessions)
    assert all(math.isfinite(row['budget_unit']) and row['budget_unit'] > 0
               and math.isfinite(row['net']) for row in selected)
    old = common.module('105の不変会計', common.ROOT/'work/wave_v102/accounting.py')
    total = old.sum_totals(selected)
    active = [row for row in selected if row['campaigns'] > 0]
    losses = [row for row in active if row['net'] < -1e-5]
    units = np.array([row['net']/row['budget_unit'] for row in selected])
    best = max(selected, key=lambda row: (row['net'], row['session']))
    total.update(active_sessions=len(active), losing_sessions=len(losses),
        positive_sessions=sum(row['net'] > 1e-5 for row in active),
        no_trade_sessions=len(selected)-len(active),
        losing_active_rate=len(losses)/len(active) if active else None,
        worst_session_loss=max([0.]+[-row['net'] for row in selected]),
        downside_rms=float(np.sqrt(np.mean(np.minimum(units, 0.)**2))),
        worst_normalized_loss=float(max(0., -units.min())),
        best_session=best['session'], without_best_net=total['net']-best['net'],
        largest_session_drawdown=max(row['equity_drawdown'] for row in selected))
    return total


def assess(cases: dict, sessions: list[str], baseline_id: str) -> dict:
    """
    機能: 最大利益より赤字頻度と損失を優先し、最低活動も満たす候補を判定する。
    引数: cases(dict)は全条件会計、sessions(list[str])、baseline_id(str)は同数量の共通基準。
    返り値: dictは両銘柄の基準達否。既知データの探索結果と明示する。
    """
    minimum_active = math.ceil(len(sessions)/2)
    scores = {ident: {symbol: summarize(value['rows'], symbol, sessions)
        for symbol in ('TOPIX', 'NK225')} for ident,value in cases.items()}
    judged = {}
    for ident, products in scores.items():
        reasons, qualified = [], True
        for symbol, value in products.items():
            if value['active_sessions'] < minimum_active or value['campaigns'] < 20:
                qualified = False
                reasons.append(symbol+'：活動不足')
            payoff_ok = ((value['loss'] == 0 and value['profit'] > 0)
                         or (value['payoff'] is not None and value['payoff'] > 1))
            if value['net'] <= 0 or not payoff_ok:
                qualified = False
                reasons.append(symbol+'：合計黒字・平均損小利大を未達')
            if value['profit_share'] is None or value['profit_share'] < .8:
                reasons.append(symbol+'：金額利益80%を未達')
            if value['without_best_net'] <= 0:
                reasons.append(symbol+'：最大勝ち除外後が黒字ではない')
            reference = scores[baseline_id][symbol]
            for metric in ('losing_active_rate', 'downside_rms', 'worst_normalized_loss'):
                if reference[metric] is None:
                    reasons.append(symbol+'：基準の活動不足で'+metric+'を比較できない')
                elif value[metric] is None or value[metric] > reference[metric]+1e-10:
                    reasons.append(symbol+'：'+metric+'が基準より悪化')
        judged[ident] = dict(symbols=products, eligible=qualified,
            adopted=qualified and not reasons, reasons=reasons,
            all_sessions_positive=all(value['positive_sessions'] == len(sessions) for value in products.values()))
    ranking = sorted([ident for ident,item in judged.items() if item['eligible']], key=lambda ident: (
        max(v['losing_active_rate'] for v in scores[ident].values()),
        max(v['downside_rms'] for v in scores[ident].values()),
        max(v['worst_normalized_loss'] for v in scores[ident].values()),
        -min(v['profit_share'] for v in scores[ident].values()), ident))
    return dict(results=judged, ranking=ranking,
        adopted=[ident for ident in ranking if judged[ident]['adopted']],
        minimum_active=minimum_active, baseline=baseline_id,
        判定範囲='全場は既知の探索対象。前後分割や最大勝ち除外は頑健性の点検で、未知性能の証明ではない。')
