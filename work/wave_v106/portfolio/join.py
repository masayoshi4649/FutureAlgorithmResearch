"""既存の偶奇namespaceと実腿合算を同じ数学で接続する。"""

from copy import deepcopy

import numpy as np


def namespace_rows(rows: np.ndarray, columns: list[str], source: int) -> np.ndarray:
    """
    機能: C/R腿の親・玉・注文識別子を、偶奇の衝突しない名前空間へ写す。
    引数: rows(ndarray)、columns(list[str])は旧列定義、source(int)はC=0/R=1。
    返り値: ndarray。原行・価格・数量・料金を変更しない独立copy。
    """
    assert source in (0, 1)
    result = rows.copy()
    positions = {name: index for index, name in enumerate(columns)}
    for name in ('parent_id', 'cohort_id', 'uid', 'order_uid'):
        if name in positions:
            values = result[:, positions[name]]
            positive = np.isfinite(values) & (values > 0)
            assert np.all(values[positive] == np.floor(values[positive]))
            assert np.all(values[positive] <= (2**53 - 2) // 2), '識別子の厳密整数範囲を超えます'
            values[positive] = 2 * values[positive] + source
    if 'source' in positions:
        result[:, positions['source']] = source
    return result


def join_portfolio_outputs(legs: dict, allocations: tuple[int, int], symbol: str) -> dict:
    """
    機能: 実腿の物理注文・親・玉を保存し、同原行の全玉時価と6列保有を合算する。
    引数: legs(dict[str,dict])はC/R実数量再生、allocations(tuple[int,int])、symbol(str)。
    返り値: dict。accounting102へ渡せる合算口座。旧内部源名J2/O06の意味はC/Rへ対応する。
    """
    assert set(legs) == {'C', 'R'} and symbol in ('TOPIX', 'NK225')
    cap = 10 if symbol == 'TOPIX' else 20
    assert sum(allocations) == cap and all(isinstance(value, int) and value > 0 for value in allocations)
    c, r = legs['C'], legs['R']
    assert c['curve'].shape == r['curve'].shape
    assert c['target_trace'].shape == r['target_trace'].shape and c['target_trace'].shape[1] == 6
    trace = c['target_trace'] + r['target_trace']
    assert np.all(trace[:, :4] <= cap), '実保有又は予約込みの片方向上限を超えました'
    source_curve = np.column_stack((c['curve'], r['curve']))
    answer = dict(legs=legs, allocations=allocations, curve=source_curve.sum(axis=1),
                  source_curve=source_curve, target_trace=trace, per_direction_cap=cap,
                  source_names={0: 'C', 1: 'R'}, old_source_names={'J2': 'C', 'O06': 'R'})
    for field, column_field in (('orders', 'order_columns'), ('trades', 'trade_columns'),
                                ('growth_cohorts', 'growth_cohort_columns'), ('events', 'event_columns')):
        assert c[column_field] == r[column_field]
        columns = c[column_field]
        parts = [namespace_rows(legs[family][field], columns, source) for source, family in enumerate(('C', 'R'))]
        joined = np.concatenate(parts)
        sort_field = 'exit_row' if field == 'trades' else ('entry_row' if field == 'growth_cohorts' else 'row')
        if len(joined):
            joined = joined[np.argsort(joined[:, columns.index(sort_field)], kind='stable')]
        answer[field], answer[column_field] = joined, columns
    assert c['trace_columns'] == r['trace_columns'] and c['stat_columns'] == r['stat_columns']
    answer['trace_columns'], answer['stat_columns'] = c['trace_columns'], c['stat_columns']
    stats = c['stats'] + r['stats']
    stats[:4] = trace[:, :4].max(axis=0, initial=0)
    stats[4:8] = trace[-1, [0, 1, 4, 5]] if len(trace) else 0.
    stats[8] = (trace[:, 0] + trace[:, 1]).max(initial=0)
    answer['stats'] = stats
    answer['fees'] = float(answer['orders'][:, answer['order_columns'].index('fee')].sum())
    answer['raw_entry_diagnostics'] = []
    for source, family in enumerate(('C', 'R')):
        for value in legs[family]['raw_entry_diagnostics']:
            row = deepcopy(value)
            row.update(parent_id=2 * row['parent_id'] + source,
                       order_uid=2 * row['order_uid'] + source, source=source, family=family)
            answer['raw_entry_diagnostics'].append(row)
    answer['identifier_mapping'] = {}
    for source, family in enumerate(('C', 'R')):
        leg = legs[family]
        answer['identifier_mapping'][family] = dict(
            parent_id={int(value): 2 * int(value) + source for value in leg['trades'][:, 0]},
            order_uid={int(value): 2 * int(value) + source for value in leg['orders'][:, 16]},
            cohort_id={int(value): 2 * int(value) + source for value in leg['growth_cohorts'][:, leg['growth_cohort_columns'].index('cohort_id')]})
    return answer

