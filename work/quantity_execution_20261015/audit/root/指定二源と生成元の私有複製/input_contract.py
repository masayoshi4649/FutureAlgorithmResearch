"""数量公開と元44列の系譜を照合し、価格資格を数量資格から分離する。"""

import numpy as np

FIELDS = [
    'type', 'episode', 'start_i', 'pub_i', 'd', 'bid', 'ask', 'bid_q0', 'ask_q0',
    'bid_q_at_public', 'ask_q_at_public', 'min_bid_q', 'min_ask_q', 'opposite_q0',
    'opposite_q_at_public', 'opposite_min_q', 'quantity_ratio', 'minimum_quantity_ratio',
    'quantity_group', 'total_volume', 'npositive', 'first_positive_i', 'fresh_price_time',
    'volume_after_price', 'volume_clock_known', 'first_positive_fresh_price_time',
    'first_positive_volume_after_price', 'first_positive_volume_clock_known',
    'start_raw_seq', 'pub_raw_seq', 'pub_price_time_s']

# ----------------------------------------


def validate(arrays: dict, schema: dict) -> None:
    """
    機能: 44列の型・形・原順・正常行の順逆写像を生成元の契約で検査する。
    引数: arrays(dict[str,ndarray])、schema(dict) は原列と固定型定義。
    返り値: None。値を直さず、原入力配列を読取専用へ固定する。
    """
    assert set(arrays) == set(schema) and len(arrays) == 44
    n, m = len(arrays['raw_seq']), len(arrays['execution_to_raw_index'])
    assert n > 0
    for name, wanted in schema.items():
        shape = tuple(n if size == 'N' else m if size == 'M' else size for size in wanted['shape'])
        assert str(arrays[name].dtype) == wanted['dtype'] and arrays[name].shape == shape, name
        arrays[name].flags.writeable = False
    assert np.all(np.diff(arrays['raw_seq']) > 0)
    mapping, inverse = arrays['execution_to_raw_index'], arrays['normal_execution_row']
    assert np.all((mapping >= 0) & (mapping < n)) and np.all(np.diff(mapping) > 0)
    assert np.all(inverse >= -1)
    np.testing.assert_array_equal(mapping, np.flatnonzero(inverse >= 0))
    np.testing.assert_array_equal(inverse[mapping], np.arange(m, dtype=np.int32))


def price_valid(arrays: dict, start: float, end: float) -> np.ndarray:
    """
    機能: 00114と同じ自身原順・価格時計・両気配による価格資格を独立に構成する。
    引数: arrays(dict[str,ndarray])、start/end(float) は元列と排他的観測窓。
    返り値: ndarray[bool] は価格資格。数量・出来高・真の受信時刻を代入しない。
    """
    pt, bid, ask, seq = (arrays[name] for name in ('price_time_s', 'bid', 'ask', 'raw_seq'))
    valid = np.isfinite(pt) & (pt >= start) & (pt < end)
    valid &= np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask > bid)
    valid &= (arrays['price_reset_reason'] & 8) == 0
    valid[1:] &= (seq[1:] == seq[:-1] + 1) & np.isfinite(pt[:-1]) & (pt[1:] >= pt[:-1])
    valid.flags.writeable = False
    return valid


def signal(arrays: dict, events: np.ndarray, fields: list[str], start: float, end: float) -> dict:
    """
    機能: 保存公開の原seq・時刻・数量・気配を同じ原行へ結び、結果ラベルを渡さない。
    引数: arrays(dict)、events(ndarray)、fields(list[str])、start/end(float) は原列と公開featureだけ。
    返り値: dict はevents/fields/price_valid_mask。先着結果・未来極値は含まない。
    """
    assert fields == FIELDS
    assert events.dtype == np.float64 and events.ndim == 2 and events.shape[1] == len(fields) and np.isfinite(events).all()
    col = {name: events[:, index] for index, name in enumerate(fields)}
    n = len(arrays['raw_seq'])
    pub, first, initial = (col[name].astype(np.int64) for name in ('pub_i', 'first_positive_i', 'start_i'))
    for name, integer in (('pub_i', pub), ('first_positive_i', first), ('start_i', initial)):
        np.testing.assert_array_equal(col[name], integer)
    assert np.all((initial >= 0) & (initial < first) & (first <= pub) & (pub < n))
    assert np.all(np.diff(pub) >= 0)
    assert np.all(np.isin(col['type'], [0, 1])) and np.all(np.isin(col['d'], [-1, 1]))
    for saved, original, indexes in (
        ('pub_raw_seq', 'raw_seq', pub), ('start_raw_seq', 'raw_seq', initial),
        ('pub_price_time_s', 'price_time_s', pub), ('bid', 'bid', pub), ('ask', 'ask', pub),
        ('bid_q0', 'bid_qty', initial), ('ask_q0', 'ask_qty', initial),
        ('bid_q_at_public', 'bid_qty', pub), ('ask_q_at_public', 'ask_qty', pub)):
        np.testing.assert_array_equal(col[saved], arrays[original][indexes])
    known = price_valid(arrays, start, end)
    assert np.all(known[pub])
    events.flags.writeable = False
    return dict(events=events, fields=list(fields), price_valid_mask=known)
