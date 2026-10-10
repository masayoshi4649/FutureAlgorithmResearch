"""銘柄別・売買サイクル別に損小利大と未完了建玉を評価する共通指標。"""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np

MULTIPLIERS = {'NK225': 1000., 'TOPIX': 10000.}


def from_raw(raw: np.ndarray, method: str, symbol: str, session: str, cap: int,
             time_s: np.ndarray | None = None, incomplete_cycle_ids: Iterable[int] | None = None) -> list[dict]:
    """機能: 既存22列の全脚を、全返済まで一つの売買サイクルとして束ねる。

    引数: raw (ndarray): exact_engineの22列、method/symbol/session (str)、cap (int): 設定上限。
    time_s (ndarray|None): 原本価格系列の時刻。
    incomplete_cycle_ids (Iterable[int]|None): グリッド再配置等で継続中の中心番号。
    返り値: list[dict]: 完了・未完了サイクル。
    """
    raw = np.asarray(raw, dtype=float)
    if raw.size == 0:
        return []
    if raw.ndim != 2 or raw.shape[1] != 22 or cap <= 0 or int(cap) != cap:
        raise ValueError('rawは22列、設定枚数上限は正数で指定してください')
    if symbol not in MULTIPLIERS:
        raise ValueError('ペア等の別単位はサイクル辞書を直接渡してください')
    result = []
    incomplete_cycle_ids = set([] if incomplete_cycle_ids is None else incomplete_cycle_ids)
    for cycle_id in np.unique(raw[:, 0]).astype(int):
        rows = raw[raw[:, 0] == cycle_id]
        points = rows[:, 2]*(rows[:, 9]-rows[:, 8])
        if not np.all(np.isfinite(points)) or not np.all(rows[:, 7] > 0):
            raise ValueError('サイクルの損益と固定ATRが有効ではありません')
        if not np.allclose(points, rows[:, 15], rtol=1e-9, atol=1e-7):
            raise ValueError('価格差から求めた脚損益と保存損益が一致しません')
        closed = rows[:, 14] == 1
        if len(np.unique(rows[:, [1, 5]], axis=0)) != len(rows):
            raise ValueError('同じサイクルの脚番号と新規行位置が重複しています')
        row = dict(method=method, symbol=symbol, session=session, cycle_id=int(cycle_id),
                   complete=bool(closed.all() and cycle_id not in incomplete_cycle_ids),
                   legs=len(rows), closed_legs=int(closed.sum()),
                   open_legs=int((~closed).sum()), cap=int(cap),
                   entry_order=int(rows[:, 5].min()), exit_order=int(rows[:, 6].max()),
                   entry_seq=int(rows[:, 20].min()), exit_seq=int(rows[:, 21].max()))
        for name, selected in [('net', np.ones(len(rows), dtype=bool)), ('closed', closed), ('open', ~closed)]:
            row[f'{name}_points'] = float(points[selected].sum())
            row[f'{name}_yen'] = float(points[selected].sum()*MULTIPLIERS[symbol])
            row[f'{name}_atr'] = float((points[selected]/rows[selected, 7]).sum())
        if time_s is not None:
            row['entry_time_s'] = float(time_s[row['entry_order']])
            row['exit_time_s'] = float(time_s[row['exit_order']])
            row['holding_minutes'] = (row['exit_time_s']-row['entry_time_s'])/60
        result.append(row)
    return result


def unit_value(cycle: dict, kind: str, unit: str) -> float:
    """機能: 同一サイクルの評価単位を明示して取得する。

    引数: cycle (dict)、kind (str): net/closed/open、unit (str): yen/points/atr/atr_cap/points_cap/r。
    返り値: float: 指定単位の値。ATR換算を初期損失額Rとは呼ばない。
    """
    if unit.endswith('_cap'):
        return float(cycle[f'{kind}_{unit[:-4]}'])/float(cycle['cap'])
    if unit not in ['yen', 'points', 'atr', 'r']:
        raise ValueError(f'未知の損益単位: {unit}')
    return float(cycle[f'{kind}_{unit}'])


def maximum_loss_run(values: Iterable[float]) -> int:
    """機能: 時系列の負の損益が連続した最大回数を数える。

    引数: values (Iterable[float])。返り値: int: 最大連敗。損益ゼロは連敗を区切る。
    """
    current = maximum = 0
    for value in values:
        current = current+1 if value < 0 else 0
        maximum = max(maximum, current)
    return maximum


def distribution(values: Iterable[float]) -> dict:
    """機能: 完了サイクルだけの平均勝敗・PF・裾の損失を求める。

    引数: values (Iterable[float]): 順序付きサイクル損益。
    返り値: dict: 比率・平均・尾部・連敗。負け０のPFはNoneとし、∞を順位へ渡さない。
    """
    values = np.asarray(list(values), dtype=float)
    if np.any(~np.isfinite(values)):
        raise ValueError('損益は有限値で指定してください')
    winners, losers = values[values > 0], -values[values < 0]
    wins, losses, count = len(winners), len(losers), len(values)
    gross_profit, gross_loss = float(winners.sum()), float(losers.sum())
    avg_win = float(winners.mean()) if wins else None
    avg_loss = float(losers.mean()) if losses else None
    payoff = avg_win/avg_loss if wins and losses else None
    cumulative = np.r_[0., np.cumsum(values)]
    drawdown = float((np.maximum.accumulate(cumulative)-cumulative).max())
    tail_n = max(1, math.ceil(.1*count)) if count else 0
    return dict(count=count, wins=wins, losses=losses, flats=int((values == 0).sum()),
                net=float(values.sum()), gross_profit=gross_profit, gross_loss=gross_loss,
                avg_win=avg_win, avg_loss=avg_loss, payoff_ratio=payoff,
                profit_factor=gross_profit/gross_loss if losses else None,
                pf_status='未取引' if not count else '損失未観測' if not losses else '算出可能',
                win_rate=wins/count if count else None,
                nonflat_win_rate=wins/(wins+losses) if wins+losses else None,
                breakeven_win_rate=1/(1+payoff) if payoff is not None else None,
                expectancy=float(values.mean()) if count else None,
                median_cycle=float(np.median(values)) if count else None,
                worst_cycle=float(values.min()) if count else None,
                best_cycle=float(values.max()) if count else None,
                max_win=float(winners.max()) if wins else None,
                max_loss=float(losers.max()) if losses else None,
                tail10_mean=float(np.sort(values)[:tail_n].mean()) if count else None,
                tail10_count=tail_n,
                loss_q90=float(np.quantile(losers, .9)) if losses else None,
                loss_q95=float(np.quantile(losers, .95)) if losses else None,
                max_loss_streak=maximum_loss_run(values),
                closed_cycle_drawdown=drawdown,
                net_without_best_cycle=float(values.sum()-values.max()) if count else None)


def leave_one_out(cycles: list[dict], sessions: list[str], unit: str) -> dict:
    """機能: 各セッションを一つずつ外したPF・平均勝敗比の最悪値を求める。

    引数: cycles (list[dict]): 完了サイクル、sessions (list[str])、unit (str)。
    返り値: dict: 各除外結果と最悪比率。未定義比率があれば順位用得点を０とする。
    """
    rows = []
    for omitted in sessions:
        values = np.asarray([unit_value(c, 'net', unit) for c in cycles if c['session'] != omitted], dtype=float)
        winners, losers = values[values > 0], -values[values < 0]
        pf = float(winners.sum()/losers.sum()) if len(losers) else None
        payoff = float(winners.mean()/losers.mean()) if len(winners) and len(losers) else None
        rows.append(dict(omitted=omitted, count=len(values), wins=len(winners), losses=len(losers),
                         net=float(values.sum()), profit_factor=pf, payoff_ratio=payoff))
    valid_pf = len(rows) > 1 and all(r['profit_factor'] is not None for r in rows)
    valid_payoff = len(rows) > 1 and all(r['payoff_ratio'] is not None for r in rows)
    minimum_pf = min(r['profit_factor'] for r in rows) if valid_pf else None
    minimum_payoff = min(r['payoff_ratio'] for r in rows) if valid_payoff else None
    score = min(5., max(0., minimum_pf), max(0., minimum_payoff)) if valid_pf and valid_payoff else 0.
    return dict(leave_one_out=rows, loo_min_pf=minimum_pf, loo_min_payoff=minimum_payoff,
                loo_ratio_score=score, loo_ratio_evaluable=valid_pf and valid_payoff,
                loo_undefined_count=sum(r['profit_factor'] is None or r['payoff_ratio'] is None for r in rows))


def summarize(cycles: list[dict], sessions: list[str] | None = None, unit: str = 'yen') -> dict:
    """機能: 同一銘柄・同一方式の完了サイクルを主に、未完了とセッション安定性を分けて集計する。

    引数: cycles (list[dict])、sessions (list[str]|None): 無取引期間も含む評価対象、unit (str): 評価単位。
    返り値: dict: 完了PF・平均勝敗、未完了全建玉評価、セッション指標。
    """
    identities = {(row['method'], row['symbol']) for row in cycles}
    if len(identities) > 1:
        raise ValueError('銘柄や方式を混ぜて平均勝敗・PFを比較できません')
    sessions = list(sessions) if sessions is not None else sorted({row['session'] for row in cycles})
    if len(sessions) != len(set(sessions)) or any(row['session'] not in sessions for row in cycles):
        raise ValueError('対象セッションが重複、または対象外サイクルがあります')
    positions = {session:index for index, session in enumerate(sessions)}
    ordered = sorted(cycles, key=lambda row:(positions[row['session']], row['entry_order'], row['cycle_id']))
    completed = [row for row in ordered if row['complete']]
    incomplete = [row for row in ordered if not row['complete']]
    values = [unit_value(row, 'net', unit) for row in completed]
    result = distribution(values)
    session_rows = []
    for session in sessions:
        rows = [row for row in ordered if row['session'] == session]
        complete_rows = [row for row in rows if row['complete']]
        marks = [unit_value(row, 'net', unit) for row in rows]
        complete_values = [unit_value(row, 'net', unit) for row in complete_rows]
        session_rows.append(dict(session=session, complete_cycles=len(complete_rows),
            incomplete_cycles=len(rows)-len(complete_rows), complete_net=float(sum(complete_values)),
            net=float(sum(marks)), loss_streak=maximum_loss_run(complete_values)))
    session_values = np.asarray([row['net'] for row in session_rows], dtype=float)
    complete_session_values = np.asarray([row['complete_net'] for row in session_rows], dtype=float)
    result.update(unit=unit, complete_cycles=len(completed), incomplete_cycles=len(incomplete),
        total_cycles=len(ordered), total_legs=sum(row['legs'] for row in ordered),
        closed_legs=sum(row['closed_legs'] for row in ordered), open_legs=sum(row['open_legs'] for row in ordered),
        complete_net=result['net'], incomplete_net=sum(unit_value(row, 'net', unit) for row in incomplete),
        incomplete_closed_net=sum(unit_value(row, 'closed', unit) for row in incomplete),
        incomplete_open_net=sum(unit_value(row, 'open', unit) for row in incomplete),
        all_closed_net=sum(unit_value(row, 'closed', unit) for row in ordered),
        all_open_net=sum(unit_value(row, 'open', unit) for row in ordered),
        all_net=sum(unit_value(row, 'net', unit) for row in ordered),
        session_count=len(sessions), traded_sessions=sum(row['complete_cycles']+row['incomplete_cycles'] > 0 for row in session_rows),
        complete_traded_sessions=sum(row['complete_cycles'] > 0 for row in session_rows),
        positive_sessions=int((session_values > 0).sum()), negative_sessions=int((session_values < 0).sum()),
        flat_sessions=int((session_values == 0).sum()),
        session_mean=float(session_values.mean()) if len(sessions) else None,
        session_median=float(np.median(session_values)) if len(sessions) else None,
        session_worst=float(session_values.min()) if len(sessions) else None,
        session_best=float(session_values.max()) if len(sessions) else None,
        net_without_best_session=float(session_values.sum()-session_values.max()) if len(sessions) else None,
        completed_net_without_best_session=float(complete_session_values.sum()-complete_session_values.max()) if len(sessions) else None,
        positive_leave_one_session_out=int(np.sum(session_values.sum()-session_values > 0)) if len(sessions) > 1 else None,
        max_session_loss_streak=maximum_loss_run(session_values), sessions=session_rows,
        ratio_sample_ok=len(completed) >= 10 and result['wins'] >= 3 and result['losses'] >= 3,
        ratio_note='PFと平均勝敗は全脚返済済みサイクルだけ。未完了サイクルの既返済利益を勝ちへ加えない。',
        drawdown_note='closed_cycle_drawdownは完了サイクル確定損益の段階的下落。含み損を含む原本全行DDとは別。')
    if ordered:
        result['method'], result['symbol'] = next(iter(identities))
    result.update(leave_one_out(completed, sessions, unit))
    return result
