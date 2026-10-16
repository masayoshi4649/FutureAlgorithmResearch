"""104の同一原行候補を、最小B/T又は不変旧Oへ接続する。"""

from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import sys

import numba
import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.dont_write_bytecode = True


def module(name: str, path: Path) -> object:
    """
    機能: 104専用cacheで新執行と旧経済同値snapshotを読取接続する。
    引数: name(str)、path(Path)は固有名とsource。
    返り値: object。旧source・旧cacheへ書き込まない。
    """
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec)
        sys.modules[name] = value
        spec.loader.exec_module(value)
    os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'jit')
    numba.config.CACHE_DIR = str(HERE / 'jit')
    return sys.modules[name]


def connect(prepared_value: dict, normal_case: dict, exit_id: str, quantity: int = 1) -> tuple[dict, dict]:
    """
    機能: 事前normal投影と当時支持価格を、旧共通recordの同一原行へ結ぶ。
    引数: prepared_value(dict)はrecord/signal/reference_open、normal_case(dict)、exit_id(str)、quantity(int)。
    返り値: tuple[dict,dict]は新signalと根の出口設定。候補生成・base読取をしない。
    """
    record, old = prepared_value['record'], prepared_value['signal']
    n = len(record['seq'])
    for name in ('event', 'support_price', 'entry_quality', 'entry_reset'):
        assert normal_case[name].shape == (n,)
    assert normal_case['event'].dtype == np.int8
    assert np.isin(normal_case['event'], (-1, 0, 1)).all()
    assert normal_case['entry_quality'].dtype == normal_case['entry_reset'].dtype == np.bool_
    mapping = normal_case['execution_to_raw_index']
    assert mapping.shape == (n,) and np.issubdtype(mapping.dtype, np.integer)
    decisions = normal_case['decisions']
    assert {int(row['row']) for row in decisions} == set(np.flatnonzero(normal_case['event']))
    for row in decisions:
        normal = int(row['row'])
        assert int(row['normal_row']) == normal and int(row['raw_row']) == int(mapping[normal])
        assert int(row['raw_seq']) == int(record['seq'][normal])
        assert int(row['side']) == int(normal_case['event'][normal])
        assert np.isfinite(normal_case['support_price'][normal]) and normal_case['support_price'][normal] > 0
        assert float(row['support_price']) == float(normal_case['support_price'][normal])
    catalog = module('104最小執行の根条件', HERE.parent / 'catalog.py')
    config = dict(catalog.exit_config(exit_id), quantity=quantity)
    signal = dict(event=normal_case['event'], support_price=normal_case['support_price'],
        entry_quality=normal_case['entry_quality'], entry_reset=normal_case['entry_reset'],
        decisions=decisions, execution_to_raw_index=mapping,
        reference_open=float(prepared_value['reference_open']), trend_width=float(old['trend_width']))
    return signal, config


def play(prepared_value: dict, normal_case: dict, exit_id: str, quantity: int = 1,
         finish: bool = True, python: bool = False) -> dict:
    """
    機能: 同じ入口と実量を、旧O又は新しい支持境界B/Tで再生する。
    引数: prepared_value/normal_case(dict)、exit_id(str)、quantity(int)、finish(bool)、python(bool)は人工限定。
    返り値: dict。旧会計へ渡せる物理注文・親・玉・全行時価と仮説判断。
    """
    signal, config = connect(prepared_value, normal_case, exit_id, quantity)
    if exit_id == 'O':
        old = module('104専用の不変103金融snapshot', HERE / 'old_finance_snapshot.py')
        old_adapter = old.adapter
        record = prepared_value['record']
        settings = old_adapter.raw_config(old_adapter.reference_config(), quantity, record['symbol'])
        old_signal = old_adapter.signal_for_raw(record, prepared_value['signal'], signal['event'],
            signal['entry_quality'], signal['entry_reset'], signal['reference_open'], settings)
        assert np.array_equal(old_signal['event'], signal['event'])
        assert np.array_equal(old_signal['quality'], signal['entry_quality'])
        assert np.array_equal(old_signal['reset'], signal['entry_reset'])
        engine = old_adapter.module('103新入口の読取102固定出口', old_adapter.PREVIOUS / 'engine.py')
        # ----------------------------------------
        # 旧helperの既存cacheが保持するcanonical名にも、同一sourceの読取objectを結ぶ。
        sys.modules.setdefault('103入口接続検査だけの読取102出口', engine)
        sys.modules.setdefault('停止余裕と線据置を分ける執行102', engine)
        if python:
            assert record.get('人工素材') is True
            compiled = engine.simulate
            try:
                engine.simulate = compiled.py_func
                result = engine.execute(record, old_signal, settings, finish=finish)
            finally:
                engine.simulate = compiled
        else:
            result = engine.execute(record, old_signal, settings, finish=finish)
        diagnostics = old_adapter.raw_entry_diagnostics(record, result, signal['decisions'])
        for row in diagnostics:
            decision, fill = row['decision_row'], row['fill_row']
            row.update(decision_normal_row=decision, decision_raw_row=int(signal['execution_to_raw_index'][decision]),
                       fill_normal_row=fill, fill_raw_row=int(signal['execution_to_raw_index'][fill]))
        result['raw_entry_diagnostics'] = diagnostics
        result['entry_case_id'] = normal_case['entry_id']
        module('104専用の不変103金融snapshot', HERE / 'old_finance_snapshot.py')
        result.update(exit_id='O', fixed_support_context=normal_case['support_price'],
            entry_contract='O/B/Tの同normal event/entry_quality/entry_resetを直接旧執行へ渡す。旧qualifiedから再生成しない。')
        return result
    engine = module('104の支持境界と利益追尾執行', HERE / 'core.py')
    result = engine.execute(prepared_value['record'], signal, config, finish=finish, python=python)
    result['entry_id'] = normal_case['entry_id']
    return result


def join(legs: dict, allocations: tuple[int, int], symbol: str) -> dict:
    """
    機能: C/Rの実数量腿を、衝突しない親/UID/玉と同原行時価で合算する。
    引数: legs(dict[str,dict])、allocations(tuple[int,int])、symbol(str)。
    返り値: dict。実注文別の料金と片方向held/pending枠を保存した口座。
    """
    adapter = module('104の不変103配分snapshot', HERE / 'adapter.py')
    return adapter.join_portfolio_outputs(legs, allocations, symbol)
