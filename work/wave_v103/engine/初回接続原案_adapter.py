"""新しいraw入口だけを、読取102の固定1枚・同じ出口へ接続する案。"""

from copy import deepcopy
import importlib.util
import math
import os
from pathlib import Path
import sys

import numba
import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PREVIOUS = ROOT / 'work/wave_v102'
sys.dont_write_bytecode = True
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'jit')
numba.config.CACHE_DIR = str(HERE / 'jit')


def module(name: str, path: Path) -> object:
    """
    機能: 旧出口と条件を読取専用で接続し、旧領域へキャッシュを書かない。
    引数: name(str)は固有名、path(Path)は既存source。
    返り値: object。読取モジュール。入力読取と正式再生は呼び出さない。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'jit')
    numba.config.CACHE_DIR = str(HERE / 'jit')
    return value


def reference_config() -> dict:
    """
    機能: 102の固定1枚30分対照を、そのまま参照設定として読む。
    引数: なし。
    返り値: dict。旧G0_Q1_X1のcopy。新条件を旧領域へ保存しない。
    """
    old = module('103の読取固定1枚対照条件', PREVIOUS / 'catalog.py')
    values = {value['id']: value for value in old.catalog()}
    return deepcopy(values['G0_Q1_X1'])


def raw_config(previous: dict) -> dict:
    """
    機能: 固定1枚の出口を保ち、旧候補後の入口待機・支持再判定を無効にする。
    引数: previous(dict)は旧G0_Q1_X1。
    返り値: dict。入口差だけを持つ接続案。旧strategy.playは通さない。
    """
    assert previous['trend_initial_quantity'] == 1 and previous['trend_growth_mode'] == 0
    assert previous['trend_hold_seconds'] == 1800. and previous['selection'] == 'fixed'
    result = deepcopy(previous)
    result.update(entry_wait_kind=0, entry_clock_policy='C0', entry_price_cap_multiple=None,
                  entry_bbo_confirm=False, entry_support_lane='raw103', entry_source='raw103')
    return result


def signal_for_raw(record: dict, previous: dict, event: np.ndarray, quality: np.ndarray,
                   reset: np.ndarray, reference_open: float, config: dict) -> dict:
    """
    機能: 当時既知のraw入口pulseと資格だけを浅い信号copyへ接続する。
    引数: record/previous/config(dict)、event(ndarray[int8])、quality/reset(ndarray[bool])、reference_open(float)。
    返り値: dict。旧D出口を保持し、Sを旧と同じ保存始値・呼値式で作る。
    pulseは判断行に置く。quote不明のpulseを未来検索で正常行へ移さない。
    """
    size = len(record['time_s'])
    assert event.shape == quality.shape == reset.shape == (size,)
    assert event.dtype == np.int8 and quality.dtype == reset.dtype == np.bool_
    assert np.isin(event, (-1, 0, 1)).all()
    assert math.isfinite(reference_open) and reference_open > 0
    tick = float(record['tick'])
    initial = max(2, math.ceil(reference_open * config['trend_initial_stop_bp'] / 10000. / tick - 1e-10)) * tick
    return dict(previous, event=event.copy(), quality=quality.copy(), reset=reset.copy(),
                trend_initial_stop_width=initial)


def play_artificial(record: dict, signal: dict, config: dict) -> dict:
    """
    機能: 人工素材だけを旧Python本体で再生し、102 sourceと出口を変更しない。
    引数: record/signal/config(dict)は明示人工素材。
    返り値: dict。人工注文と診断。正式素材に使うAPIではない。
    """
    assert record.get('人工素材') is True, '正式又は保存原板をこの人工接続へ渡せません'
    engine = module('103入口接続検査だけの読取102出口', PREVIOUS / 'engine.py')
    compiled = engine.simulate
    try:
        engine.simulate = compiled.py_func
        return engine.execute(record, signal, config)
    finally:
        engine.simulate = compiled
