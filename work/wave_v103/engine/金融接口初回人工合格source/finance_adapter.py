"""保存済み活動を同一原行の旧執行へ写し、固定出口と実数量料金を保持する。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location('103金融接続専用adapter', Path(__file__).resolve().parent / 'adapter.py')
adapter = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = adapter
_spec.loader.exec_module(adapter)


RESET_FIELDS = ('price_reset_reason', 'depth_reset_reason', 'lp_reset_reason', 'volume_reset_reason')


def connect(account: dict, case_id: str, record: dict, reference_signal: dict,
            previous_config: dict, reference_open: float, quantity: int = 1) -> tuple[dict, dict, list]:
    """
    機能: 活動cacheの同じraw原行だけをnormalへ写し、旧入口の二重判定を省く。
    引数: account(dict)は活動口座、case_id(str)、record/reference_signal/previous_config(dict)は一度準備済み旧素材、reference_open(float)、quantity(int)。
    返り値: tuple[dict,dict,list]。新信号、同出口の設定、normal判断とraw由来のcopy。
    baseの読取・旧prepare・未来有効行検索・金融再生はこの関数で行わない。
    """
    assert case_id in account['pulses']
    source, pulse = account['source'], account['pulses'][case_id]
    assert record['symbol'] == account['item']['symbol']
    mapping = source['execution_to_raw_index']
    raw_seq, raw_to_normal = source['raw_seq'], source['normal_execution_row']
    n, m = len(raw_seq), len(record['seq'])
    assert mapping.shape == (m,) and np.issubdtype(mapping.dtype, np.integer)
    assert np.all((mapping >= 0) & (mapping < n)) and np.all(np.diff(mapping) > 0)
    assert raw_to_normal.shape == (n,) and np.array_equal(raw_to_normal[mapping], np.arange(m))
    assert np.array_equal(np.flatnonzero(raw_to_normal >= 0), mapping)
    assert np.array_equal(record['seq'], raw_seq[mapping])
    assert np.array_equal(record['time_s'], source['price_time_s'][mapping])
    for name in ('seq', 'time_s', 'price', 'bid', 'ask'):
        np.testing.assert_array_equal(record[name], account['normal_record'][name], err_msg=name)
    for name in ('start', 'end', 'limit', 'tick'):
        assert record[name] == account['normal_record'][name] == account['item'][name]
    event = pulse['event']
    assert event.dtype == np.int8 and event.shape == (n,) and np.isin(event, (-1, 0, 1)).all()
    expected = event[mapping]
    assert np.array_equal(pulse['normal_event'], expected), '非対応raw候補を別のnormal原行へ移しています'
    assert pulse['normal_event'].dtype == np.int8
    quality = source['qualified'][mapping].copy()
    assert quality.dtype == np.bool_ and quality.shape == (m,)
    reset = np.zeros(m, bool)
    for name in RESET_FIELDS:
        assert source[name].shape == (n,)
        reset |= source[name][mapping] != 0
    settings = adapter.raw_config(previous_config, quantity, record['symbol'])
    signal = adapter.signal_for_raw(record, reference_signal, expected, quality, reset, reference_open, settings)

    # ----------------------------------------
    # 台帳のrowは旧executeへ渡すnormal行。元raw行と段階lineageは別欄で保存する。
    decisions, seen = [], set()
    for original in pulse['normal_decisions']:
        raw_row, normal_row = int(original['row']), int(original['normal_row'])
        assert 0 <= raw_row < n and 0 <= normal_row < m
        assert mapping[normal_row] == raw_row and raw_to_normal[raw_row] == normal_row
        assert int(original['raw_seq']) == int(raw_seq[raw_row])
        assert int(original['side']) == int(event[raw_row]) != 0
        assert normal_row not in seen
        row = deepcopy(original)
        row.update(row=normal_row, raw_row=raw_row, normal_row=normal_row,
                   raw_seq=int(raw_seq[raw_row]), price_time=float(source['price_time_s'][raw_row]))
        decisions.append(row)
        seen.add(normal_row)
    assert seen == set(np.flatnonzero(expected)), 'normal pulseと当時判断台帳が一致しません'
    return signal, settings, decisions


def enrich_diagnostics(account: dict, record: dict, output: dict, decisions: list) -> None:
    """
    機能: 物理新規の実枚数を保持し、判断/約定のnormal行とraw行を分離記録する。
    引数: account/record/output(dict)、decisions(list[dict])は同一原行投影の判断。
    返り値: None。outputへ診断だけ追加し、物理注文・親・玉・料金を変更しない。
    """
    mapping = account['source']['execution_to_raw_index']
    rows = adapter.raw_entry_diagnostics(record, output, decisions)
    for row in rows:
        decision, fill = row['decision_row'], row['fill_row']
        row.update(decision_normal_row=decision, decision_raw_row=int(mapping[decision]),
                   fill_normal_row=fill, fill_raw_row=int(mapping[fill]))
        assert row['episode'] is not None and row['episode']['raw_row'] == row['decision_raw_row']
        assert row['episode']['normal_row'] == decision
    output['raw_entry_diagnostics'] = rows
    pulse = account['pulses'][output['entry_case_id']]
    output['projection_diagnostics'] = dict(raw_pulses=int(np.count_nonzero(pulse['event'])),
        normal_pulses=int(np.count_nonzero(pulse['normal_event'])),
        non_normal_pulses=int(np.count_nonzero(pulse['event'])) - int(np.count_nonzero(pulse['normal_event'])),
        actual_entries=len(rows), consumed_without_entry=len(decisions) - len(rows),
        definition='raw同原行のみを投影。保有中・受付外・不明・cutで消費された候補の未来補充なし。')


def replay_single(account: dict, case_id: str, record: dict, reference_signal: dict,
                  previous_config: dict, reference_open: float, quantity: int = 1,
                  python: bool = False) -> dict:
    """
    機能: 保存済み入口を実数量の旧固定出口へ渡し、当時lineage付き実注文を返す。
    引数: account(dict)、case_id(str)、record/reference_signal/previous_config(dict)は準備済み素材、reference_open(float)、quantity(int)、python(bool)は人工限定。
    返り値: dict。物理注文・親・玉・全玉時価・raw診断。API注文やbase再読取を行わない。
    正式呼出しは根の金融事前固定後に行う。Python対照は明示人工だけ許容する。
    """
    signal, settings, decisions = connect(account, case_id, record, reference_signal, previous_config, reference_open, quantity)
    if python:
        assert record.get('人工素材') is True, 'Python人工再生へ正式口座を渡せません'
        output = adapter.play_artificial(record, signal, settings, decisions)
    else:
        engine = adapter.module('103新入口の読取102固定出口', adapter.PREVIOUS / 'engine.py')
        output = engine.execute(record, signal, settings)
    output['entry_case_id'] = case_id
    enrich_diagnostics(account, record, output, decisions)
    return output


def replay_portfolio(account: dict, record: dict, reference_signal: dict, previous_config: dict,
                     reference_open: float, allocations: tuple[int, int], python: bool = False) -> dict:
    """
    機能: C1/R1の既存候補を各実腿枚数で再生し、同原行の金融口座を合算する。
    引数: account/record/reference_signal/previous_config(dict)は一度準備済み素材、reference_open(float)、allocations(tuple[int,int])、python(bool)は人工限定。
    返り値: dict。別腿の物理注文・親・玉と実注文別料金を保持する合算口座。
    入力候補は1枚出力から作らず、活動cacheの同じC/R候補を各腿へ渡す。
    """
    cap = 10 if record['symbol'] == 'TOPIX' else 20
    assert sum(allocations) == cap and len(allocations) == 2
    legs = {family: replay_single(account, family + '1', record, reference_signal,
                                 previous_config, reference_open, quantity, python)
            for family, quantity in zip(('C', 'R'), allocations)}
    return adapter.join_portfolio_outputs(legs, allocations, record['symbol'])
