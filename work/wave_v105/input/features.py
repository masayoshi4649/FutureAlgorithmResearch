"""既存104の公表窓を利用し、候補当時の進行効率と逆行幅だけを測る。"""

import numpy as np


WINDOWS = (10, 30)


def nullable(value: float) -> float | None:
    """
    機能: 不明な観測値をNoneとして保存し、数値0と区別する。
    引数: value(float)は有限値又はNaN。
    返り値: float|Noneは有限な数値又は不明。
    """
    return float(value) if np.isfinite(value) else None


def endpoint(raw: dict, public: dict, candidate_time: float,
             candidate_row: int | None, strictpast: bool) -> tuple[int, float | None, bool]:
    """
    機能: 当時のfirst-newmax先頭を選び、自己と相手の公表終点を区別する。
    引数: raw/public(dict)、candidate_time(float)、candidate_row(int|None)、strictpast(bool)。
    返り値: tuple[int,float|None,bool]は公表番号、年齢、15秒以内資格。自己は同時計を許す。
    """
    if not np.isfinite(candidate_time):
        return -1, None, False
    position = int(np.searchsorted(public['times'], candidate_time,
        side='left' if strictpast else 'right')-1)
    if candidate_row is not None:
        position = min(position, int(np.searchsorted(public['rows'], candidate_row, side='right')-1))
    if position < 0:
        return -1, None, False
    row = int(public['rows'][position])
    age = float(candidate_time-raw['price_time_s'][row])
    fresh = (0. < age <= 15.) if strictpast else (0. <= age <= 15.)
    return position, age, bool(fresh)


def quote(raw: dict, row: int, tick: float) -> dict:
    """
    機能: 指定された原行の価格時計・気配・旧執行資格を別々に保存する。
    引数: raw(dict)、row(int)、tick(float)は元原行入力と呼値。
    返り値: dictはBBOと原seq。後続の正常行への探索又は補完はしない。
    """
    assert 0 <= row < len(raw['raw_seq'])
    bid, ask = float(raw['bid'][row]), float(raw['ask'][row])
    finite = np.isfinite(bid) and np.isfinite(ask) and 0 < bid < ask
    return dict(raw_row=row, raw_seq=int(raw['raw_seq'][row]),
        price_time_s=nullable(raw['price_time_s'][row]), bid=nullable(bid), ask=nullable(ask),
        midpoint=nullable((bid+ask)/2.) if finite else None,
        spread_ticks=(ask-bid)/tick if finite else None,
        bbo_valid=bool(raw['bbo_valid'][row]), qualified=bool(raw['qualified'][row]))


def path_measure(raw: dict, feature: dict, tick: float, side: int,
                 position: int, age: float | None, fresh: bool, window: int) -> dict:
    """
    機能: 104の既存基準と不明理由を引き継ぎ、公表中値の過去経路を測る。
    引数: raw/feature(dict)、tick(float)、side/position/window(int)、age(float|None)、fresh(bool)。
    返り値: dictはD/TV/eta/Nと公表系譜。不明や曖昧を既知支持として救済しない。
    """
    assert side in (-1, 1) and window in WINDOWS
    public = feature['public']
    result = dict(window_seconds=window, known=False, observed_known=False, count=0,
        directional_net_ticks=None, total_variation_ticks=None, efficiency=None,
        max_adverse_ticks=None, retreat_from_best_ticks=None, zero_variation=False,
        public_index=None, public_endpoint=None, baseline=None, best=None,
        age_seconds=age, legacy_unknown_reason=None, selection_unknown_reason=0,
        ambiguous_spread=False, ambiguous_sign=False, ambiguous=False, path_source=None)
    if position < 0:
        result['selection_unknown_reason'] = 1
        return result
    row = int(public['rows'][position])
    values = feature['windows'][str(window)]
    baseline_index = int(values['reference_public_index'][position])
    reason = int(values['unknown_reason'][position])
    result.update(public_index=position, public_endpoint=quote(raw, row, tick),
        legacy_unknown_reason=reason, selection_unknown_reason=0 if fresh else 2,
        ambiguous_spread=bool(values['ambiguous_spread'][position]),
        ambiguous_sign=bool(values['ambiguous_sign'][position]),
        ambiguous=bool(values['ambiguous'][position]))
    if baseline_index >= 0:
        baseline_row = int(public['rows'][baseline_index])
        result['baseline'] = dict(public_index=baseline_index, **quote(raw, baseline_row, tick))
        result['count'] = position-baseline_index+1
        source_rows = public['rows'][baseline_index:position+1]
        result['path_source'] = dict(raw_rows=source_rows.copy(),
            raw_seq=raw['raw_seq'][source_rows].copy(), price_time_s=raw['price_time_s'][source_rows].copy(),
            midpoint=((raw['bid'][source_rows]+raw['ask'][source_rows])/2.).copy())
    if reason or not fresh:
        return result
    assert baseline_index >= 0
    rows = public['rows'][baseline_index:position+1]
    midpoint = (raw['bid'][rows]+raw['ask'][rows])/2.
    assert np.all(np.isfinite(midpoint)) and np.all(raw['bbo_valid'][rows])
    directed = side*midpoint
    variation = float(np.sum(np.abs(np.diff(midpoint)))/tick)
    net = float((directed[-1]-directed[0])/tick)
    running_best = np.maximum.accumulate(directed)
    maximum_adverse = float(np.max(running_best-directed)/tick)
    best_offset = int(np.argmax(directed))
    best_index = baseline_index+best_offset
    result.update(observed_known=True, known=not result['ambiguous'],
        directional_net_ticks=net, total_variation_ticks=variation,
        efficiency=net/variation if variation > 0. else None,
        max_adverse_ticks=maximum_adverse,
        retreat_from_best_ticks=float((running_best[-1]-directed[-1])/tick),
        zero_variation=variation == 0., duration_seconds=float(public['times'][position]-public['times'][baseline_index]),
        best=dict(public_index=best_index, **quote(raw, int(public['rows'][best_index]), tick)))
    return result


def normal_path_measure(packet: dict, symbol: str, candidate: dict,
                        public_measure: dict) -> dict:
    """
    機能: 同じ公開基準から実候補までの全当時normal更新を、同時計も省かず測る。
    引数: packet(dict)、symbol(str)、candidate/public_measure(dict)は候補と自己公表窓。
    返り値: dictは別経路のD/TV/eta/N。公開窓を上書きせず不正中間原行を跨がない。
    """
    raw, record = packet['raw'][symbol], packet['normal'][symbol]['record']
    side, row, tick = int(candidate['side']), int(candidate['raw_row']), float(record['tick'])
    result = dict(window_seconds=public_measure['window_seconds'], known=False,
        observed_known=False, count=0, directional_net_ticks=None, total_variation_ticks=None,
        efficiency=None, max_adverse_ticks=None, retreat_from_best_ticks=None,
        zero_variation=False, baseline=public_measure['baseline'], public_endpoint=public_measure['public_endpoint'],
        endpoint=quote(raw, row, tick), best=None, legacy_unknown_reason=public_measure['legacy_unknown_reason'],
        selection_unknown_reason=public_measure['selection_unknown_reason'], tail_unknown=False,
        ambiguous=public_measure['ambiguous'], ambiguous_spread=public_measure['ambiguous_spread'],
        ambiguous_sign=public_measure['ambiguous_sign'], path_source=None,
        source='同じ公開基準から実候補までの全normal更新')
    if public_measure['baseline'] is None or candidate['normal_row'] is None:
        result['tail_unknown'] = True
        return result
    baseline_row = int(public_measure['baseline']['raw_row'])
    begin = int(raw['normal_execution_row'][baseline_row])
    finish = int(candidate['normal_row'])
    assert begin >= 0 and finish >= begin
    result['count'] = finish-begin+1
    indexes = np.arange(begin, finish+1, dtype=np.int64)
    result['path_source'] = dict(normal_rows=indexes, raw_rows=raw['execution_to_raw_index'][indexes].copy(),
        raw_seq=record['seq'][indexes].copy(), price_time_s=record['time_s'][indexes].copy(),
        midpoint=((record['bid'][indexes]+record['ask'][indexes])/2.).copy())
    interval = slice(baseline_row, row+1)
    seq, stamps = raw['raw_seq'][interval], raw['price_time_s'][interval]
    bad = (not np.all(raw['bbo_valid'][interval]) or
        not np.all(np.isfinite(stamps)) or np.any(raw['price_reset_reason'][interval] != 0) or
        np.any(np.diff(seq) != 1) or np.any(np.diff(stamps) < 0))
    result['tail_unknown'] = bool(bad)
    if not public_measure['observed_known'] or bad:
        return result
    midpoint = (record['bid'][indexes]+record['ask'][indexes])/2.
    assert np.all(record['quote_valid'][indexes]) and np.all(np.isfinite(midpoint))
    directed = side*midpoint
    best_values = np.maximum.accumulate(directed)
    variation = float(np.sum(np.abs(np.diff(midpoint)))/tick)
    net = float((directed[-1]-directed[0])/tick)
    best_normal = begin+int(np.argmax(directed))
    best_raw = int(raw['execution_to_raw_index'][best_normal])
    result.update(observed_known=True, known=not result['ambiguous'],
        directional_net_ticks=net, total_variation_ticks=variation,
        efficiency=net/variation if variation > 0. else None,
        max_adverse_ticks=float(np.max(best_values-directed)/tick),
        retreat_from_best_ticks=float((best_values[-1]-directed[-1])/tick),
        zero_variation=variation == 0., best=dict(normal_row=best_normal, **quote(raw, best_raw, tick)),
        duration_seconds=float(record['time_s'][finish]-record['time_s'][begin]),
        normal_begin=begin, normal_end=finish)
    return result


def candidate_features(packet: dict, symbol: str, candidate: dict) -> dict:
    """
    機能: 自己と厳密過去相手の10/30秒経路を、実候補行のBBOと分離して保存する。
    引数: packet(dict)は既存104入口packet、symbol(str)、candidate(dict)は保存済み候補。
    返り値: dictは採否を変更しない当時数値と支持系譜。未来高安・利益を参照しない。
    """
    other = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
    raw, row, side = packet['raw'][symbol], int(candidate['raw_row']), int(candidate['side'])
    tick = float(packet['items'][symbol]['tick'])
    assert side in (-1, 1) and tick > 0
    assert int(candidate['raw_seq']) == int(raw['raw_seq'][row])
    stamp = float(raw['price_time_s'][row])
    assert candidate['price_time_s'] == stamp and raw['qualified'][row] and not raw['entry_reset'][row]
    current = quote(raw, row, tick)
    support = float(candidate['support_price'])
    current.update(support_price=support, planned_entry_price=None, liquidation_price=None,
        entry_to_support_ticks=None, liquidation_to_support_ticks=None)
    if current['bbo_valid'] and current['midpoint'] is not None:
        planned = current['ask'] if side == 1 else current['bid']
        liquidation = current['bid'] if side == 1 else current['ask']
        current.update(planned_entry_price=planned, liquidation_price=liquidation,
            entry_to_support_ticks=side*(planned-support)/tick,
            liquidation_to_support_ticks=side*(liquidation-support)/tick)
    result = dict(entry_id=candidate['entry_id'], symbol=symbol, row=candidate['normal_row'],
        raw_row=row, raw_seq=int(raw['raw_seq'][row]), price_time_s=stamp,
        side=side, accepted_104=bool(candidate['accepted']), current=current,
        own={}, own_normal={}, peer={}, selected_support_roots=candidate['selected_support_roots'],
        self_lineages=candidate['self_lineages'])
    for role, market, strictpast in (('own', symbol, False), ('peer', other, True)):
        source, feature = packet['raw'][market], packet['peer_features'][market]
        position, age, fresh = endpoint(source, feature['public'], stamp,
            row if role == 'own' else None, strictpast)
        for window in WINDOWS:
            measured = path_measure(source, feature, float(packet['items'][market]['tick']),
                side, position, age, fresh, window)
            measured.update(symbol=market, strictpast=strictpast,
                candidate_from_best_signed_ticks=None, candidate_retreat_from_best_ticks=None)
            if role == 'own' and measured['best'] is not None and current['midpoint'] is not None:
                difference = side*(measured['best']['midpoint']-current['midpoint'])/tick
                measured.update(candidate_from_best_signed_ticks=difference,
                    candidate_retreat_from_best_ticks=max(0., difference))
            result[role][str(window)] = measured
    for window in WINDOWS:
        result['own_normal'][str(window)] = normal_path_measure(packet, symbol, candidate, result['own'][str(window)])
    return result
