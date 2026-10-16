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


def raw_config(previous: dict, quantity: int = 1, symbol: str | None = None) -> dict:
    """
    機能: 固定1枚の出口を保ち、旧候補後の入口待機・支持再判定を無効にする。
    引数: previous(dict)は旧G0_Q1_X1、quantity(int)は実腿枚数、symbol(str|None)は配分時の商品。
    返り値: dict。入口差だけを持つ接続案。旧strategy.playは通さない。
    """
    assert previous['trend_initial_quantity'] == 1 and previous['trend_growth_mode'] == 0
    assert previous['trend_hold_seconds'] == 1800. and previous['selection'] == 'fixed'
    result = deepcopy(previous)
    result.update(entry_wait_kind=0, entry_clock_policy='C0', entry_price_cap_multiple=None,
                  entry_bbo_confirm=False, entry_support_lane='raw103', entry_source='raw103')
    assert isinstance(quantity, int) and quantity > 0
    if quantity != 1:
        assert symbol in ('TOPIX', 'NK225')
        scale, cap = (1, 10) if symbol == 'TOPIX' else (2, 20)
        assert quantity <= cap and quantity % scale == 0
        result.update(trend_budget=quantity // scale, trend_initial_quantity=None)
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


def raw_entry_diagnostics(record: dict, output: dict, decisions: list[dict] | None = None) -> list[dict]:
    """
    機能: 実新規注文から、正しいraw判断行・実枚数・次気配fillと元episodeを記録する。
    引数: record/output(dict)、decisions(list[dict]|None)はstate側の当時候補記録。
    返り値: list[dict]。旧45列quantityの枠診断を実注文枚数として使わない。
    """
    metadata = {value['row']: value for value in (decisions or [])}
    parents = {int(value[0]): value for value in output['entry_parent_diagnostics']}
    rows = []
    for order in output['orders']:
        if order[7] != 1 or order[3] != 0:
            continue
        row, decision_row, parent = int(order[0]), int(order[1]), int(order[2])
        old = parents.get(parent)
        rows.append(dict(parent_id=parent, decision_row=decision_row,
            decision_raw_seq=int(record['seq'][decision_row]), decision_time=float(order[10]),
            fill_row=row, fill_raw_seq=int(record['seq'][row]), fill_time=float(order[11]),
            side=int(order[4]), quantity=int(order[5]), fill_price=float(order[6]), fee=float(order[9]),
            order_uid=int(order[16]), episode=deepcopy(metadata.get(decision_row)),
            old_quantity_diagnostic=float(old[8]) if old is not None else None))
    return rows


def play_artificial(record: dict, signal: dict, config: dict, decisions: list[dict] | None = None) -> dict:
    """
    機能: 人工素材だけを旧Python本体で再生し、102 sourceと出口を変更しない。
    引数: record/signal/config(dict)は明示人工素材、decisions(list[dict]|None)は当時のraw候補。
    返り値: dict。人工注文と診断。正式素材に使うAPIではない。
    """
    assert record.get('人工素材') is True, '正式又は保存原板をこの人工接続へ渡せません'
    engine = module('103入口接続検査だけの読取102出口', PREVIOUS / 'engine.py')
    compiled = engine.simulate
    try:
        engine.simulate = compiled.py_func
        output = engine.execute(record, signal, config)
    finally:
        engine.simulate = compiled
    output['raw_entry_diagnostics'] = raw_entry_diagnostics(record, output, decisions)
    return output


def portfolio_artificial(record: dict, signals: dict, previous: dict,
                         allocations: tuple[int, int]) -> dict:
    """
    機能: C/Rの同一信号を各腿の実数量で別々に再生し、合算保有と全玉時価を返す。
    引数: record/signals/previous(dict)、allocations(tuple[int,int])はC/R実枚数。
    返り値: dict。2腿の実注文・料金。1枚損益の単純倍率換算はしない。
    """
    symbol = record['symbol']
    cap = 10 if symbol == 'TOPIX' else 20
    assert sum(allocations) == cap and set(signals) == {'C', 'R'}
    legs = {family: play_artificial(record, signals[family], raw_config(previous, quantity, symbol))
            for family, quantity in zip(('C', 'R'), allocations)}
    trace = legs['C']['target_trace'] + legs['R']['target_trace']
    assert np.all(trace[:, :4] <= cap), '保有又は予約の片方向合算上限を超えました'
    return dict(legs=legs, allocations=allocations, target_trace=trace,
                curve=legs['C']['curve'] + legs['R']['curve'],
                per_direction_cap=cap, fees=sum(float(leg['orders'][:, 9].sum()) for leg in legs.values()))
