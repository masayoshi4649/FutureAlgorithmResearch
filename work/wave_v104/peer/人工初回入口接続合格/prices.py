"""結果前の相手BBO観測窓を、時計だけで選ぶ基準と不明資格へ分ける。"""

import numpy as np


NEUTRAL = 0
UP = 1
DOWN = -1
AMBIGUOUS = 2
UNKNOWN = 3
STATUS_NAMES = {0: 'NEUTRAL', 1: 'UP', -1: 'DOWN', 2: 'AMBIGUOUS', 3: 'UNKNOWN'}
UNKNOWN_REASONS = {1: '過去基準なし', 2: '現在公表源の資格又はBBO不明',
    4: '過去基準の資格又はBBO不明', 8: '基準clockの年齢超過',
    16: '途中rawprice reset又は不正quote又は原seq断裂', 32: '途中公表clock間隔超過'}


def classify(bid_delta: np.ndarray, ask_delta: np.ndarray, known: np.ndarray,
             ambiguous: np.ndarray, threshold: int) -> np.ndarray:
    """
    機能: 正常両気配の同方向進行を、neutral/unknown/spread曖昧と分ける。
    引数: bid_delta/ask_delta(ndarray[float])、known/ambiguous(ndarray[bool])、threshold(int)は呼値数。
    返り値: ndarray[int8]は0/+1/-1/2/3。不明を反対なしへ補完しない。
    """
    assert threshold in (1, 2)
    result = np.full(len(bid_delta), UNKNOWN, np.int8)
    valid = known & ~ambiguous
    result[valid] = NEUTRAL
    result[valid & (bid_delta >= threshold) & (ask_delta >= threshold)] = UP
    result[valid & (bid_delta <= -threshold) & (ask_delta <= -threshold)] = DOWN
    result[known & ambiguous] = AMBIGUOUS
    return result


def build(raw: dict, item: dict, public: dict, policy: dict) -> dict:
    """
    機能: W3/10/30の公表窓とW10閾値2を、保存原行だけで計算する準備部品。
    引数: raw/item/public(dict)、policy(dict)は根が別途確定するspreadと間隔数値。
    返り値: dictは公表源別の基準・測定・不明理由。金融又は正式cacheロードを行わない。
    """
    tick = float(item['tick'])
    assert np.isfinite(tick) and tick > 0
    assert policy['max_public_gap_seconds'] == policy['baseline_extra_age_seconds'] == 15.
    assert policy['spread_max_ticks'] > 0 and policy['spread_increment_ticks'] >= 0
    rows, times = public['rows'], public['times']
    count, n = len(rows), len(raw['raw_seq'])
    bad = (~raw['bbo_valid'] | ~np.isfinite(raw['price_time_s']) | (raw['price_reset_reason'] != 0))
    if n > 1:
        bad[1:] |= raw['raw_seq'][1:] != raw['raw_seq'][:-1]+1
        bad[1:] |= raw['price_time_s'][1:] < raw['price_time_s'][:-1]
    raw_bad_prefix = np.r_[0, np.cumsum(bad.astype(np.int64))]
    public_gap = np.zeros(count, bool)
    if count > 1:
        public_gap[1:] = np.diff(times) > policy['max_public_gap_seconds']
    gap_prefix = np.r_[0, np.cumsum(public_gap.astype(np.int64))]
    values = {}
    for window in (3, 10, 30):
        indexes = np.searchsorted(times, times-float(window), side='right')-1
        available = indexes >= 0
        reference_rows = np.full(count, -1, np.int64)
        reference_rows[available] = rows[indexes[available]]
        reference_seq = np.full(count, -1, np.int64)
        reference_seq[available] = raw['raw_seq'][reference_rows[available]]
        reference_time, delta_bid, delta_ask = (np.full(count, np.nan) for _ in range(3))
        reference_spread, current_spread = (np.full(count, np.nan) for _ in range(2))
        reference_time[available] = raw['price_time_s'][reference_rows[available]]
        current_spread[:] = (raw['ask'][rows]-raw['bid'][rows])/tick
        if np.any(available):
            ref = reference_rows[available]
            delta_bid[available] = (raw['bid'][rows[available]]-raw['bid'][ref])/tick
            delta_ask[available] = (raw['ask'][rows[available]]-raw['ask'][ref])/tick
            reference_spread[available] = (raw['ask'][ref]-raw['bid'][ref])/tick
        reasons = np.zeros(count, np.uint16)
        reasons[~available] |= 1
        reasons[~(raw['qualified'][rows] & raw['bbo_valid'][rows])] |= 2
        good_reference = np.zeros(count, bool)
        good_reference[available] = raw['qualified'][reference_rows[available]] & raw['bbo_valid'][reference_rows[available]]
        reasons[available & ~good_reference] |= 4
        reasons[available & ((times-reference_time) > window+policy['baseline_extra_age_seconds'])] |= 8
        if np.any(available):
            positions = np.flatnonzero(available)
            ref = reference_rows[available]
            reasons[positions[(raw_bad_prefix[rows[available]+1]-raw_bad_prefix[ref]) > 0]] |= 16
            reasons[positions[(gap_prefix[positions+1]-gap_prefix[indexes[available]+1]) > 0]] |= 32
        known = reasons == 0
        ambiguous_spread = current_spread > np.maximum(policy['spread_max_ticks'], reference_spread+policy['spread_increment_ticks'])
        ambiguous_sign = ((delta_bid > 0) & (delta_ask < 0)) | ((delta_bid < 0) & (delta_ask > 0))
        ambiguous = known & (ambiguous_spread | ambiguous_sign)
        values[str(window)] = dict(window_seconds=window, public_rows=rows,
            source_raw_seq=public['raw_seq'], source_time_s=times,
            reference_public_index=indexes, reference_raw_row=reference_rows,
            reference_raw_seq=reference_seq, reference_time_s=reference_time,
            bid_change_ticks=delta_bid, ask_change_ticks=delta_ask,
            current_spread_ticks=current_spread, reference_spread_ticks=reference_spread,
            unknown_reason=reasons, ambiguous=ambiguous,
            ambiguous_spread=known & ambiguous_spread, ambiguous_sign=known & ambiguous_sign,
            direction_t1=classify(delta_bid, delta_ask, known, ambiguous, 1))
        if window == 10:
            values[str(window)]['direction_t2'] = classify(delta_bid, delta_ask, known, ambiguous, 2)
    return dict(public=public, windows=values, policy=dict(policy), status_names=STATUS_NAMES,
                unknown_reasons=UNKNOWN_REASONS)


def gate_spec(gate: str) -> dict:
    """
    機能: 根指定の8gateから相手支持窓と閾値だけを取得する。
    引数: gate(str)はOWN/N3/N10/N30/P3/P10/P30/P10T2。
    返り値: dictはuse_peer/window/threshold/mode。OWN/Nを支持ありと呼ばない。
    """
    assert gate in ('OWN', 'N3', 'N10', 'N30', 'P3', 'P10', 'P30', 'P10T2')
    if gate == 'OWN':
        return dict(use_peer=False, window=None, threshold=None, mode='OWN')
    window = 10 if gate == 'P10T2' else int(gate[1:])
    return dict(use_peer=True, window=window, threshold=2 if gate == 'P10T2' else 1,
                mode='NOT_OPPOSE' if gate.startswith('N') else 'SUPPORT')
