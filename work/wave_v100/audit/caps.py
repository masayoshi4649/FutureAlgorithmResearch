"""元候補からの判断価格上限と、判断後の実約定超過を別々に独立構成する。"""

import math

import numpy as np

import common
import watch


STATE_COLUMNS = ['enabled', 'multiple', 'cap_width', 'watch_active', 'candidate_id',
    'candidate_time', 'candidate_quote', 'width', 'side', 'current_entry_quote', 'quote_valid',
    'adverse_width', 'cap_pass', 'old_trigger', 'selected_trigger', 'cap_blocked', 'deadline',
    'row_time', 'parent_id', 'cancel_flags']
PARENT_COLUMNS = ['parent_id', 'candidate_id', 'candidate_time', 'side', 'quantity',
    'candidate_quote', 'width', 'enabled', 'multiple', 'cap_width', 'trigger_row', 'trigger_time',
    'trigger_quote', 'trigger_adverse_width', 'trigger_inside_cap', 'fill_row', 'fill_time',
    'fill_price', 'fill_adverse_width', 'fill_cap_excess', 'market_outcome']


def parents(entries: np.ndarray, config: dict) -> np.ndarray:
    """
    機能: 旧入口45列の確認済み候補・判断・実fillから新21列を独立算定する。
    引数: entries(ndarray[float])、config(dict)は固定条件。
    返り値: ndarray[float]。判断後のfillを入口oracleへ渡さず、超過は事後診断だけ。
    """
    multiple = config['entry_price_cap_multiple']
    enabled = multiple is not None
    result = np.full((len(entries), 21), np.nan)
    for row, entry in enumerate(entries):
        side, candidate, width = entry[7], entry[5], entry[9]
        limit = multiple * width if enabled else math.nan
        decision = side * (entry[31] - candidate)
        fill = side * (entry[40] - candidate) if math.isfinite(entry[40]) else math.nan
        excess = max(0., fill - limit) if enabled and math.isfinite(fill) else math.nan
        result[row] = [entry[0], entry[1], entry[4], side, entry[8], candidate, width,
            enabled, multiple if enabled else math.nan, limit, entry[28], entry[30], entry[31],
            decision, math.isfinite(decision) and (not enabled or decision <= limit),
            entry[37], entry[39], entry[40], fill, excess, entry[41]]
    return result


def verify(record: dict, config: dict, reference: float, expected: dict, actual: dict,
           vector: object) -> None:
    """
    機能: 生原板と独立watch更新からcap全20列と判断・実fillの21列を照合する。
    引数: record/config/expected/actual(dict)、reference(float)、vector(Callable)は独立watch列化。
    返り値: None。未保有の順行を利益と見なさず、実約定超過を判断拒否へ逆流させない。
    """
    size = len(record['time_s'])
    multiple, kind = config['entry_price_cap_multiple'], config['entry_wait_kind']
    enabled = multiple is not None
    width = watch.waiting_widths(reference, record['tick'], config)[0]
    limit = multiple * width if enabled else math.nan
    geometry = np.full((size, 32), np.nan)
    geometry[:, :4], geometry[:, 31] = 0., kind
    previous, begin = None, 0
    decisions = {}
    for row, state, decision in expected['schedule']['changes']:
        if previous is not None:
            geometry[begin:row] = previous
        previous, begin = vector(state, record), row
        if isinstance(decision, dict):
            decisions[row] = decision
    if previous is not None:
        geometry[begin:] = previous
    qok = record['quote_valid'] & np.isfinite(record['bid']) & np.isfinite(record['ask'])
    qok &= (record['bid'] > 0) & (record['ask'] > record['bid'])
    output = np.full((size, 20), np.nan)
    output[:, 0], output[:, 1], output[:, 2] = enabled, multiple if enabled else math.nan, limit
    output[:, 3:9] = np.column_stack((geometry[:, 0], geometry[:, 3], geometry[:, 6],
        geometry[:, 7], np.full(size, width), geometry[:, 2]))
    output[:, 10], output[:, 12:16] = 0., 0.
    output[:, 16], output[:, 17] = geometry[:, 8], record['time_s']
    output[:, 18] = expected['trend_exit_state_trace'][:, 0]
    output[:, 19] = 0.
    for row in range(size):
        if geometry[row, 3] > 0 and math.isfinite(geometry[row, 7]):
            side, candidate = int(geometry[row, 2]), geometry[row, 7]
            quote = record['ask'][row] if side == 1 else record['bid'][row]
            valid = bool(qok[row] and math.isfinite(quote) and quote > 0 and candidate > 0)
            adverse = side * (quote - candidate) if valid else math.nan
            output[row, 9:13] = [quote, valid, adverse, valid and (not enabled or adverse <= limit)]
        else:
            output[row, 4] = 0.
        if row in decisions:
            decision = decisions[row]
            output[row, 13] = decision.get('uncapped_trigger', False)
            output[row, 14] = decision['trigger']
            output[row, 15] = decision.get('cap_rejected', False)
            flag_bits = {'新規cut': 1, 'TTL': 2, '自己gap': 4, 'reset': 8, '自己BBO': 16, '両300逆方向': 32}
            output[row, 19] = sum(flag_bits[name] for name in decision['cancel_flags'])
    common.exact(actual['entry_cap_state_trace'], output, '独立cap全20列')
    common.exact(actual['entry_cap_parent_diagnostics'], parents(actual['entry_parent_diagnostics'], config), '独立cap親21列')
    if 'entry_cap_state_columns' in actual:
        assert actual['entry_cap_state_columns'] == STATE_COLUMNS
        assert actual['entry_cap_parent_columns'] == PARENT_COLUMNS
