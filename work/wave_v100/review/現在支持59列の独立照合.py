"""公開された支持診断を原LP・旧BBOと別式の支持条件へ対応させる。"""

import hashlib

import numpy as np

import 共通独立読取 as R

COLUMNS = ['grid_index', 'grid_time', 'support_lane', 'legacy_long_allowed', 'legacy_short_allowed',
    'lp_long_allowed', 'lp_short_allowed', 'selected_long_allowed', 'selected_short_allowed',
    'entry_kind', 'clock_policy'] + [prefix + '_' + name for prefix in ('own', 'peer') for name in (
    'lp_current_index', 'lp_current_raw_seq', 'lp_current_time', 'lp_current_value', 'lp_current_valid',
    'lp_old300_index', 'lp_old300_raw_seq', 'lp_old300_time', 'lp_old300_value', 'lp_old300_endpoint_valid',
    'lp300_source_valid', 'lp300_ret_bp', 'lp300_reset_or_invalid_cross', 'lp300_actual_seconds',
    'legacy_mid300_source_valid', 'legacy_mid300_ret_bp', 'execution_bbo_index', 'execution_bbo_raw_seq',
    'execution_bbo_time', 'execution_bid', 'execution_ask', 'execution_current_valid',
    'ofi15_sufficient', 'ofi15_ratio')]


def indexed(raw: dict, source: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    機能: 独立LPindexを原seq・clock・値と単点資格へ直接対応させる。
    引数: raw(dict)、source(ndarray[int])。
    返り値: tuple[ndarray,...]はseq、clock、LP値、単点資格。未知源のsafe0を観測へ借用しない。
    """
    assert np.all((source >= -1) & (source < len(raw['seq'])))
    known, safe = source >= 0, np.maximum(source, 0)
    seq = np.full(len(source), -1, np.int64)
    stamp = np.full(len(source), np.nan)
    value = stamp.copy()
    seq[known] = raw['seq'][safe[known]]
    stamp[known] = raw['time_s'][safe[known]]
    value[known] = raw['last'][safe[known]]
    valid = known & raw['valid'][safe] & np.isfinite(value) & (value > 0) & np.isfinite(stamp)
    return seq, stamp, value, valid


def lp_allowed(price: dict, execution: dict, side: int) -> np.ndarray:
    """
    機能: 両LP現在・窓と旧執行及び十分な逆OFIから現在支持を別式で算出する。
    引数: price/execution(dict)、side(int:1/-1)。
    返り値: ndarray[bool]。未知OFIを支持や追加の拒否条件へ代用しない。
    """
    result, progress = np.ones(len(price['grid']), bool), []
    for symbol in R.SYMBOLS:
        market, old = price['markets'][symbol], execution['markets'][symbol]
        current, window, flow = market['current'], market['windows'][300], old['flow'][15]
        signed = side * window['ret_bp']
        result &= (old['current']['valid'] & current['valid'] & np.isfinite(current['value'])
            & (current['value'] > 0) & window['source_valid'] & np.isfinite(signed) & (signed > 0))
        sufficient = (flow['source_valid'] & flow['valid'] & ~flow['missing_ofi']
            & (flow['nonzero_ofi_count'] >= 3) & np.isfinite(flow['ofi_ratio']))
        result &= ~(sufficient & (side * flow['ofi_ratio'] <= -.1))
        progress.append(signed)
    return result & (np.minimum(*progress) >= .25 * np.maximum(*progress))


def base_matrix(key: tuple, material: dict) -> np.ndarray:
    """
    機能: 支持59の選択前源列を原LPと旧BBOの別座標で独立構成する。
    引数: key(tuple[str,str])、material(dict)。
    返り値: ndarray[float]。現在LP源と旧300秒起点の採用indexは固定入力を所与とする。
    """
    session, symbol = key
    peer = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
    price, execution = material['trend_prices']['I3'][session], material['grids'][session]
    grid = price['grid']
    assert np.array_equal(grid, execution['grid'])
    old_gate = material['entries'][session]['entries']['J2']
    long, short = lp_allowed(price, execution, 1), lp_allowed(price, execution, -1)
    result = np.full((len(grid), 59), np.nan)
    result[:, :9] = np.column_stack((np.arange(len(grid)), grid, np.zeros(len(grid)),
        old_gate['long_allowed'], old_gate['short_allowed'], long, short,
        old_gate['long_allowed'], old_gate['short_allowed']))
    for j, name in enumerate((symbol, peer)):
        raw = material['raw_last_records'][session, name]
        market, old = price['markets'][name], execution['markets'][name]
        current, window = market['current'], market['windows'][300]
        now, origin = current['index'], window['old']
        seq, stamp, value, endpoint = indexed(raw, now)
        prior_seq, prior_time, prior_value, prior_endpoint = indexed(raw, origin)
        known, prior_known = now >= 0, origin >= 0
        np.testing.assert_array_equal(current['raw_seq'], seq)
        np.testing.assert_array_equal(current['time_s'], stamp)
        np.testing.assert_array_equal(current['value'], value)
        np.testing.assert_array_equal(current['valid'], known)
        assert np.all(endpoint[known]) and np.all(stamp[known] < grid[known])
        np.testing.assert_array_equal(window['old_seq'], prior_seq)
        np.testing.assert_array_equal(window['old_time_s'], prior_time)
        np.testing.assert_array_equal(window['old_value'], prior_value)
        available = known & prior_known
        broken = np.r_[0, np.cumsum(~raw['valid'] | raw['reset'], dtype=np.int64)]
        crossed = available & (broken[np.maximum(now, 0) + 1] - broken[np.maximum(origin, 0) + 1] > 0)
        valid = available & (origin < now) & ~crossed
        with np.errstate(invalid='ignore', divide='ignore'):
            ret = (value - prior_value) / prior_value * 10000.
        elapsed = stamp - prior_time
        ret[~valid] = np.nan; elapsed[~valid] = np.nan
        np.testing.assert_array_equal(window['source_valid'], valid)
        np.testing.assert_array_equal(window['ret_bp'], ret)
        np.testing.assert_array_equal(window['reset_or_invalid_cross'], crossed)
        np.testing.assert_array_equal(window['actual_seconds'], elapsed)
        bbo = old['current']
        source, record = bbo['index'], material['prices'][session, name]
        known_bbo, safe = source >= 0, np.maximum(source, 0)
        sequence = np.full(len(source), -1, np.int64)
        bbo_time = np.full(len(source), np.nan)
        sequence[known_bbo] = record['seq'][safe[known_bbo]]
        bbo_time[known_bbo] = record['time_s'][safe[known_bbo]]
        bid, ask = bbo['bid'], bbo['ask']
        np.testing.assert_array_equal(bid[known_bbo], record['bid'][safe[known_bbo]])
        np.testing.assert_array_equal(ask[known_bbo], record['ask'][safe[known_bbo]])
        flow = old['flow'][15]
        sufficient = (flow['source_valid'] & flow['valid'] & ~flow['missing_ofi']
            & (flow['nonzero_ofi_count'] >= 3) & np.isfinite(flow['ofi_ratio']))
        result[:, 11+j*24:35+j*24] = np.column_stack((now, seq, stamp, value, known,
            origin, prior_seq, prior_time, prior_value, prior_endpoint, valid, ret, crossed, elapsed,
            old['windows'][300]['source_valid'], old['windows'][300]['ret_bp'],
            source, sequence, bbo_time, bid, ask, bbo['valid'], sufficient, flow['ofi_ratio']))
    result[np.isinf(result)] = np.nan
    return result


def check(key: tuple, ledger: dict, config: dict, material: dict, base: np.ndarray) -> dict:
    """
    機能: 公表支持59と買売の実入力指紋を、設定lane及び原価格から独立照合する。
    引数: key(tuple[str,str])、ledger/config/material(dict)、base(ndarray[float])。
    返り値: dict。59源の対応を40政策状態の全行再現へ拡張して主張しない。
    """
    trace = ledger['entry_support_state_trace']
    assert ledger['entry_support_columns'] == COLUMNS and trace.shape[1] == 59
    mapped = R.published_grid(material['prices'][key], material['grids'][key[0]]['grid'])
    public = np.unique(mapped[mapped >= 0])
    lane = 0 if config['entry_support_lane'] == 'L0' else 1
    expected = base[public].copy()
    expected[:, 2] = lane
    expected[:, 7:9] = expected[:, 3:5] if lane == 0 else expected[:, 5:7]
    expected[:, 9] = config['entry_wait_kind']
    expected[:, 10] = int(config['entry_clock_policy'][1])
    np.testing.assert_array_equal(trace, expected)
    assert ledger['entry_support_state_rows'] == len(trace)
    assert ledger['entry_support_state_SHA256'] == hashlib.sha256(trace.tobytes()).hexdigest()
    input_hash = {}
    for name, column in (('entry_j2_long', 3 if lane == 0 else 5), ('entry_j2_short', 4 if lane == 0 else 6)):
        full = base[:, column].astype(bool)
        input_hash[name] = hashlib.sha256(full.tobytes()).hexdigest()
    assert ledger['entry_support_input_SHA256'] == input_hash
    return dict(公表格子=len(public), 支持59原源照合=True, 実渡し買売2列SHA一致=True,
        lane=config['entry_support_lane'], 全grid入力SHAは公表59と別範囲=True,
        scope='固定入力のLP採用indexを原LPへ戻し窓の断裂・変位と支持を別式で再計算。旧BBOを原保持板へ対応。asof源採用全過程と政策40全行は別監査。')
