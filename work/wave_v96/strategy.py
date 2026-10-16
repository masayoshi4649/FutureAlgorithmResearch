"""旧J8の入口を固定し、初期停止幅と利益保護を新しい執行コピーへ渡す。"""

import importlib.util
import math
import os
from pathlib import Path
import sys

import numba
import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
SYMBOLS = ('TOPIX', 'NK225')
CACHE = str(HERE / 'numba_cache')
os.environ['NUMBA_CACHE_DIR'] = CACHE
numba.config.CACHE_DIR = CACHE


def module(name: str, path: Path) -> object:
    """
    機能: 固有名で読取モジュールを接続し、旧領域へのキャッシュ保存を防ぐ。
    引数: name(str)、path(Path)。
    返り値: objectは読取実装。バイトコードとNumbaキャッシュは新96だけに限定する。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    try:
        spec.loader.exec_module(value)
    finally:
        os.environ['NUMBA_CACHE_DIR'] = CACHE
        numba.config.CACHE_DIR = CACHE
    return value


ENGINE = module('不変J8入口の初期停止と利益保護執行96', HERE / 'engine.py')
LEGACY = module('不変J8の94読取96', HERE.parent / 'wave_v94/strategy.py')


def event_pulses(grid: np.ndarray, state: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """
    機能: 旧75と同じ有効中立60秒・発火間隔600秒で一度だけ候補を作る。
    引数: grid(ndarray[float])、state(ndarray[int])、valid(ndarray[bool])。
    返り値: ndarray[int8]の発火方向。欠測は中立へ代用せず、発火機会は消費する。
    """
    out = np.zeros(len(grid), np.int8)
    armed, neutral_start, previous, last_fire = True, -1., -1., -1e30
    for i, stamp in enumerate(grid):
        if previous >= 0 and stamp - previous > 15. + 1e-7:
            neutral_start = -1.
        previous = stamp
        if not valid[i]:
            neutral_start = -1.
            continue
        if state[i] == 0:
            if neutral_start < 0:
                neutral_start = stamp
            if stamp - neutral_start >= 60.:
                armed = True
        else:
            neutral_start = -1.
            if armed and stamp - last_fire >= 600.:
                out[i], last_fire, armed = state[i], stamp, False
    return out


def quote_valid(current: dict) -> np.ndarray:
    """
    機能: 旧完全板資格を維持した現在の買売気配を判定する。
    引数: current(dict)は旧執行格子。
    返り値: ndarray[bool]。LPが正常でも旧板・数量の不明は救済しない。
    """
    return (current['valid'] & current.get('q_valid', current['valid'])
            & np.isfinite(current['bid']) & np.isfinite(current['ask'])
            & (current['bid'] > 0) & (current['ask'] > current['bid']))


def lp_allowed(price: dict, execution: dict) -> dict[int, np.ndarray]:
    """
    機能: LPの5分進行比と旧15秒OFIの十分な逆証拠からJ2許可を作る。
    引数: price(dict)はI3価格格子、execution(dict)は旧執行及びOFI格子。
    返り値: dict[int,ndarray[bool]]の買売許可。未知OFIを支持へ有効化しない。
    """
    assert np.array_equal(price['grid'], execution['grid'])
    result = {}
    for side in (-1, 1):
        yes = np.ones(len(price['grid']), bool)
        returns = []
        for symbol in SYMBOLS:
            market = price['markets'][symbol]
            current, window = market['current'], market['windows'][300]
            progress = side * window['ret_bp']
            yes &= (execution['markets'][symbol]['current']['valid'] & current['valid']
                    & np.isfinite(current['value']) & (current['value'] > 0)
                    & window['source_valid'] & np.isfinite(progress) & (progress > 0))
            returns.append(progress)
            flow = execution['markets'][symbol]['flow'][15]
            sufficient = (flow['source_valid'] & flow['valid'] & ~flow['missing_ofi']
                          & (flow['nonzero_ofi_count'] >= 3) & np.isfinite(flow['ofi_ratio']))
            yes &= ~(sufficient & (side * flow['ofi_ratio'] <= -.1))
        yes &= np.minimum(returns[0], returns[1]) >= .25 * np.maximum(returns[0], returns[1])
        result[side] = yes
    return result


def lp_candidates(key: tuple[str, str], material: dict, source: str, signal: dict) -> dict:
    """
    機能: 新LP候補を15秒格子で作り、最初の旧執行原行だけへ写像する。
    引数: key(tuple[str,str])、material(dict)、source(str:P2/P3)、signal(dict)。
    返り値: dictのstate/valid/pulse/candidatesと独立LP源。却下した発火を後で補完しない。
    """
    session, symbol = key
    peer = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
    price = material['trend_prices']['I3'][session]
    old = material['legacy'][key]
    positions, grid = price['candidate_positions'], price['candidate_grid']
    assert np.array_equal(price['grid'][positions], grid)
    assert len(old['valid']) == len(grid)
    own, other = price['markets'][symbol], price['markets'][peer]
    valid = np.ones(len(grid), bool)
    for market in (own, other):
        current = market['current']
        valid &= current['valid'][positions] & np.isfinite(current['value'][positions])
        for seconds in (15, 300):
            window = market['windows'][seconds]
            valid &= window['source_valid'][positions] & np.isfinite(window['ratio_ret_bp'][positions])
    quotes = material['grids'][session]['markets'][symbol]['flow'][15]
    valid &= (quotes['source_valid'][positions] & np.isfinite(quotes['bid_change_ticks'][positions])
              & np.isfinite(quotes['ask_change_ticks'][positions]))
    if source == 'P2':
        valid &= old['valid']
    assert source in ('P2', 'P3')
    state = np.zeros(len(grid), np.int8)
    for side in (-1, 1):
        eligible = (valid & (side * own['windows'][300]['ratio_ret_bp'][positions] >= 3.)
                    & (side * other['windows'][300]['ratio_ret_bp'][positions] >= 3.)
                    & (side * other['windows'][15]['ratio_ret_bp'][positions] >= 0)
                    & (side * quotes['bid_change_ticks'][positions] >= 1. - 1e-8)
                    & (side * quotes['ask_change_ticks'][positions] >= 1. - 1e-8))
        state[eligible] = side
    pulse = event_pulses(grid, state, valid)
    record = material['prices'][key]
    rows, previous = [], -1
    for g in np.flatnonzero(pulse):
        target = int(np.searchsorted(record['time_s'], grid[g], side='left'))
        if (target >= len(record['time_s']) or record['time_s'][target] - grid[g] > 10.
                or record['time_s'][target] >= record['limit'] - 300.):
            continue
        good = (signal['quality'][target] and not signal['reset'][target]
                and record['ask'][target] - record['bid'][target] <= 2 * record['tick'] + 1e-9)
        if not good:
            continue
        assert target > previous
        previous = target
        rows.append([g, target, int(pulse[g]), int(own['current']['index'][positions[g]]),
                     int(other['current']['index'][positions[g]])])
    return dict(states=state, valid=valid, pulse=pulse,
                candidates=np.asarray(rows, np.float64).reshape((-1, 5)),
                own_source=own['current']['index'][positions], peer_source=other['current']['index'][positions])


def loss_observations(key: tuple[str, str], material: dict) -> np.ndarray:
    """
    機能: 損失後反転用の四源をI3価格と旧執行BBOから別々に組み立てる。
    引数: key(tuple[str,str])、material(dict)。
    返り値: ndarray[float64]の22列。独立LPindex・原seq・旧執行indexは別資格で保持する。
    """
    session, symbol = key
    peer = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
    price, execution = material['trend_prices']['I3'][session], material['grids'][session]
    assert np.array_equal(price['grid'], execution['grid'])
    result = np.full((len(price['grid']), 22), np.nan)
    for j, market_symbol in enumerate((symbol, peer)):
        current = execution['markets'][market_symbol]['current']
        record = material['prices'][(session, market_symbol)]
        source, offset = current['index'], j * 5
        good = source >= 0
        result[:, offset] = source
        result[:, offset + 1] = -1
        result[good, offset + 1] = record['seq'][source[good]]
        result[good, offset + 2] = record['time_s'][source[good]]
        result[:, offset + 3] = current['bid']
        result[:, offset + 4] = current['ask']
        result[:, 18 + j] = quote_valid(current)
        lp, offset = price['markets'][market_symbol]['current'], 10 + j * 4
        for column, name in enumerate(('index', 'raw_seq', 'time_s', 'value')):
            result[:, offset + column] = lp[name]
        result[:, 20 + j] = lp['valid']
    return result


def prepare(material: dict, config: dict) -> dict:
    """
    機能: 旧J8の全入口と状態を保持し、全条件共通の場始値だけ添える。
    引数: material/config(dict)。
    返り値: dict[tuple,dict]の共通原板・信号・候補診断。初期停止幅は共有信号へ埋めない。
    """
    source = config.get('trend_source', 'P0')
    assert source == 'P0' and config.get('loss_reentry_kind', 'none') == 'none'
    assert int(config['trend_budget']) == 8 and not config.get('ungated_trend', False)
    assert config['selection'] == 'fixed' and int(config['range_budget']) == 0
    base = dict(config, price_lane='I0')
    result = LEGACY.prepare(material, base)
    allowed = {session: lp_allowed(price, material['grids'][session])
               for session, price in material['trend_prices']['I3'].items()}
    for key, value in result.items():
        signal, record = value['signal'], value['record']
        session = key[0]
        candidates = material['legacy'][key] if source in ('P0', 'P1') else lp_candidates(key, material, source, signal)
        if source != 'P0':
            event = np.zeros(len(record['time_s']), np.int8)
            for candidate in candidates['candidates']:
                i, side = int(candidate[1]), int(candidate[2])
                g = int(signal['mapped'][i])
                if g >= 0 and allowed[session][side][g]:
                    event[i] = side
            signal['event'] = event
        signal['loss_observations'] = loss_observations(key, material)
        signal['execution_lp_index'] = material['execution_lp_index'][key]
        value['trend_candidate_state'] = candidates
        value['trend_lp_allowed'] = allowed[session]
        reference = material['metadata']['references']['|'.join(key)]['ref_open']
        assert reference['known_from_i'] == 0
        value['reference_open'] = float(reference['value'])
        assert np.isfinite(value['reference_open']) and value['reference_open'] > 0
    return result


def play(config: dict, key: tuple[str, str], prepared: dict, finish: bool = True) -> dict:
    """
    機能: 共通の旧入口を変更せず、当該条件の初期停止幅を浅い信号コピーへ設定する。
    引数: config(dict)、key(tuple[str,str])、prepared(dict)、finish(bool)。
    返り値: dictは旧台帳と利益保護の別診断。共有preparedを変更せず並列実行できる。
    """
    value = prepared[key]
    initial_bp = float(config.get('trend_initial_stop_bp', 40.))
    assert np.isfinite(initial_bp) and initial_bp > 0
    tick = float(value['record']['tick'])
    initial_width = max(2, math.ceil(value['reference_open'] * initial_bp / 10000. / tick - 1e-10)) * tick
    if initial_bp == 40.:
        assert initial_width == value['signal']['trend_width'], '40bp初期線は旧D追尾幅との経済nullが必要です'
    signal = dict(value['signal'], trend_initial_stop_width=initial_width)
    return ENGINE.execute(value['record'], signal, config, finish=finish)
