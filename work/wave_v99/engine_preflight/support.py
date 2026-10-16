"""正式原本を開かず、価格待機の人工原板を両商品・買売で共通に組み立てる。"""

import importlib.util
import math
import os
from pathlib import Path
import sys

import numba
import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.dont_write_bytecode = True
os.environ['NUMBA_CACHE_DIR'] = str(WORK / 'numba_cache')
numba.config.CACHE_DIR = os.environ['NUMBA_CACHE_DIR']


def load(name: str, path: Path) -> object:
    """
    機能: 検査対象を固有名で読み込み、全キャッシュを新99内へ限定する。
    引数: name(str)、path(Path)。
    返り値: objectは読み込んだモジュール。正式入力は開かない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    os.environ['NUMBA_CACHE_DIR'] = str(WORK / 'numba_cache')
    numba.config.CACHE_DIR = os.environ['NUMBA_CACHE_DIR']
    return result


def fixture(symbol: str, side: int, profile: str = 'complete') -> tuple[dict, dict, float]:
    """
    機能: 候補受理後の進行・押し・回復を区別できる人工板と既公開相手板を作る。
    引数: symbol(str)、side(int)、profile(str)。
    返り値: tuple[dict,dict,float]は原板・共通信号・既知の場始値。
    """
    base, tick = (4000., .5) if symbol == 'TOPIX' else (50000., 10.)
    peer_base, peer_tick = (50000., 10.) if symbol == 'TOPIX' else (4000., .5)
    width = max(2, math.ceil(base * .001 / tick - 1e-10)) * tick
    peer_width = max(2, math.ceil(peer_base * .001 / peer_tick - 1e-10)) * peer_tick
    size = 1101
    times = np.arange(size, dtype=float)
    progress = np.zeros(size)
    if profile == 'complete':
        changes = ((340, 3.), (350, 2.), (360, .5), (370, 2.), (390, 3.), (400, 0.))
    elif profile == 'direct':
        changes = ((340, 2.), (350, 3.))
    else:
        assert profile == 'flat'
        changes = ()
    for row, units in changes:
        progress[row:] = units
    quote = base + (tick if side == 1 else 0.) + side * progress * width
    bid, ask = (quote - tick, quote) if side == 1 else (quote, quote + tick)
    peer_quote = peer_base + (peer_tick if side == 1 else 0.) + side * progress * peer_width
    peer_bid, peer_ask = (peer_quote - peer_tick, peer_quote) if side == 1 else (peer_quote, peer_quote + peer_tick)
    grid = np.arange(300., 1105., 5.)
    mapped = np.full(size, -1, np.int32)
    mapped[grid[grid < size].astype(int)] = np.arange(len(grid[grid < size]), dtype=np.int32)
    event = np.zeros(size, np.int8)
    event[330] = side
    source = grid.astype(int) - 1
    peer = np.column_stack((source, source + 9000, source.astype(float),
                            peer_bid[source], peer_ask[source], np.ones(len(grid))))
    record = dict(symbol=symbol, time_s=times, price=(bid + ask) * .5, bid=bid, ask=ask,
                  seq=np.arange(size, dtype=np.int64) + 1000, price_valid=np.ones(size, bool),
                  quote_valid=np.ones(size, bool), tick=tick, start=0., limit=1100., end=1200.)
    signal = dict(grid=grid, mapped=mapped, quality=np.ones(size, bool), reset=np.zeros(size, bool),
                  event=event, mode=np.zeros(len(grid), np.int8),
                  trend_width=max(2, math.ceil(base * .004 / tick - 1e-10)) * tick,
                  peer_tick=peer_tick, entry_peer_bbo=peer,
                  entry_j2_long=np.ones(len(grid), bool), entry_j2_short=np.ones(len(grid), bool),
                  wait_opposite_long=np.zeros(len(grid), bool), wait_opposite_short=np.zeros(len(grid), bool))
    return record, signal, base


def old_prepared_fixture(config: dict, profile: str = 'complete', side: int = 1) -> dict:
    """
    機能: 根の保存往復にも使える両商品の人工preparedを作る。
    引数: config(dict)は識別だけ、profile(str)、side(int)。
    返り値: dict[tuple,dict]。原本・正式損益・現在APIに依存しない。
    """
    result = {}
    for symbol in ('TOPIX', 'NK225'):
        record, signal, opening = fixture(symbol, side, profile)
        result[('2000-01-03_人工', symbol)] = dict(record=record, signal=signal, reference_open=opening)
    return result


def price_fixture(grid: np.ndarray, raw: dict) -> dict:
    """
    機能: 人工LP原系列から厳密過去・同時計先頭の現在と300秒起点を明示する。
    引数: grid(ndarray[float])、raw(dict)は時刻・原seq・LP・単点資格。
    返り値: dict。未知起点を有効化せず、人工LP源をBBO源へ貼り付けない。
    """
    times, last, sequences = raw['time_s'], raw['last'], raw['seq']
    now = np.searchsorted(times, grid - 1., side='left') - 1
    old = np.searchsorted(times, grid - 301., side='left') - 1
    for indexes in (now, old):
        known = indexes >= 0
        indexes[known] = np.searchsorted(times, times[indexes[known]], side='left')
    safe_now, safe_old = np.maximum(now, 0), np.maximum(old, 0)
    current = dict(index=now.astype(np.int32), raw_seq=sequences[safe_now].copy(),
                   time_s=times[safe_now].copy(), value=last[safe_now].copy(), valid=now >= 0)
    for field in ('time_s', 'value'):
        current[field][now < 0] = np.nan
    current['raw_seq'][now < 0] = -1
    old_time, old_value, old_seq = times[safe_old].copy(), last[safe_old].copy(), sequences[safe_old].copy()
    old_time[old < 0] = np.nan
    old_value[old < 0] = np.nan
    old_seq[old < 0] = -1
    valid = (now >= 0) & (old >= 0) & (old < now) & raw['valid'][safe_now] & raw['valid'][safe_old]
    returns = (last[safe_now] - last[safe_old]) / last[safe_old] * 10000.
    returns[~valid] = np.nan
    window = dict(now=now.astype(np.int32), old=old.astype(np.int32), old_seq=old_seq,
                  old_time_s=old_time, old_value=old_value, source_valid=valid,
                  ret_bp=returns, reset_or_invalid_cross=np.zeros(len(grid), bool),
                  actual_seconds=times[safe_now] - times[safe_old])
    window['actual_seconds'][~valid] = np.nan
    return dict(current=current, windows={300: window})


def artificial_material(key: tuple, value: dict) -> dict:
    """
    機能: 自己人工原行と明示された相手気配から、別の人工LP素材を構成する。
    引数: key(tuple[str,str])、value(dict)は旧人工preparedの1商品。
    返り値: dictは支持診断だけに使う二市場素材。正式原本、会計、APIを読まない。
    """
    session, symbol = key
    peer = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
    record, signal = value['record'], value['signal']
    grid = signal['grid']
    observed = signal['entry_peer_bbo']
    own_raw = dict(time_s=record['time_s'].copy(), last=record['price'].copy(),
                   seq=record['seq'].copy(), valid=record['price_valid'].copy())
    peer_times = record['time_s'].copy()
    peer_source = np.searchsorted(observed[:, 2], peer_times, side='right') - 1
    peer_mid = .5 * (observed[:, 3] + observed[:, 4])
    peer_last = peer_mid[np.maximum(peer_source, 0)].copy()
    peer_raw = dict(time_s=peer_times, last=peer_last,
                    seq=np.arange(len(peer_times), dtype=np.int64) + 9000,
                    valid=np.ones(len(peer_times), bool))
    raw_records = {(session, symbol): own_raw, (session, peer): peer_raw}
    own_price, peer_price = price_fixture(grid, own_raw), price_fixture(grid, peer_raw)
    source = own_price['current']['index']
    safe = np.maximum(source, 0)
    own_bbo = np.column_stack((source, record['seq'][safe], record['time_s'][safe],
                              record['bid'][safe], record['ask'][safe]))
    own_bbo[source < 0, 1] = -1.
    own_bbo[source < 0, 2:5] = np.nan
    own_valid = (source >= 0) & record['quote_valid'][safe] & np.isfinite(record['bid'][safe])
    flow = dict(source_valid=np.ones(len(grid), bool), valid=np.ones(len(grid), bool),
                missing_ofi=np.zeros(len(grid), bool), nonzero_ofi_count=np.full(len(grid), 4),
                ofi_ratio=np.zeros(len(grid)))
    markets = {}
    for market, price, bbo, valid in ((symbol, own_price, own_bbo, own_valid),
                                     (peer, peer_price, observed[:, :5], observed[:, 5] == 1)):
        markets[market] = dict(current=dict(valid=valid.copy()),
                               windows={300: dict(source_valid=price['windows'][300]['source_valid'].copy(),
                                                  ret_bp=price['windows'][300]['ret_bp'].copy())},
                               flow={15: {name: array.copy() for name, array in flow.items()}})
    observations = np.full((len(grid), 22), np.nan)
    observations[:, :5] = own_bbo
    observations[:, 5:10] = observed[:, :5]
    observations[:, 18] = own_valid
    observations[:, 19] = observed[:, 5]
    signal['loss_observations'] = observations
    return dict(trend_prices={'I3': {session: dict(grid=grid,
               markets={symbol: own_price, peer: peer_price})}},
                grids={session: dict(grid=grid, markets=markets)}, raw_last_records=raw_records)


def attach_support(prepared: dict) -> dict:
    """
    機能: 明示した人工LP原素材から支持資格と59列基準を計算して付加する。
    引数: prepared(dict)は人工入力だけ。
    返り値: dict。人工入力を更新するが、正式共有preparedは受け取らない。
    """
    strategy = load('99人工支持素材の純関数読取', WORK / 'strategy.py')
    for key, value in prepared.items():
        material = artificial_material(key, value)
        session = key[0]
        value['trend_lp_allowed'] = strategy.lp_allowed(material['trend_prices']['I3'][session],
                                                       material['grids'][session])
        value['entry_support_base'] = strategy.support_basis(key, material, value)
        value['artificial_support_material'] = material
    return prepared


def prepared_fixture(config: dict, profile: str = 'complete', side: int = 1) -> dict:
    """
    機能: 根台帳の保存往復にも使える両商品の旧人工入力と別LP支持素材を作る。
    引数: config(dict)、profile(str)、side(int)。
    返り値: dictは原素材、旧信号、LP許可、59基準を持つ人工prepared。
    """
    return attach_support(old_prepared_fixture(config, profile, side))
