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
    機能: 検査対象を固有名で読み込み、全キャッシュを新97内へ限定する。
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


def prepared_fixture(config: dict, profile: str = 'complete', side: int = 1) -> dict:
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
