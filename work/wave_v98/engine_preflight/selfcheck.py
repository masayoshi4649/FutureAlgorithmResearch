"""人工板だけで価格時計政策、旧18台帳、Python/JIT及び予約の対応を検査する。"""

import copy
import hashlib
import json
import math
from pathlib import Path
import pickle

import numpy as np

from support import HERE, ROOT, WORK, fixture, load


OLD_NAMES = ('orders', 'trades', 'curve', 'source_curve', 'target_trace', 'events', 'stats', 'slots',
    'range_state_trace', 'risk_state_trace', 'range_parent_diagnostics', 'price_source_trace',
    'loss_reentry_events', 'trend_exit_state_trace', 'trend_parent_diagnostics', 'watch_state_trace',
    'entry_parent_diagnostics', 'entry_wait_events')
NEW_NAMES = ('entry_policy_state_trace', 'entry_policy_events')


def gap_fixture(symbol: str, side: int, entry: int) -> dict:
    """
    機能: gap行の発注とgap後の再準備を区別する、保存時計だけの人工系列を作る。
    引数: symbol(str)、side(int)、entry(int:3又は7)。
    返り値: dictは1商品の人工prepared。正式原本・実損益は参照しない。
    """
    record, signal, opening = fixture(symbol, side, 'flat')
    times = record['time_s'].copy()
    times[340:] += 12.
    record['time_s'] = times
    width = max(2, math.ceil(opening * .001 / record['tick'] - 1e-10)) * record['tick']
    peer_base, peer_tick = (50000., 10.) if symbol == 'TOPIX' else (4000., .5)
    peer_width = max(2, math.ceil(peer_base * .001 / peer_tick - 1e-10)) * peer_tick
    steps = ((340., 2.), (370., 3.), (400., 0.)) if entry == 3 else (
        (335., 3.), (337., 2.), (338., 1.), (352., 2.), (365., 4.),
        (367., 3.), (368., 2.5), (380., 3.5), (400., 0.))

    # ----------------------------------------
    # 自己原行と相手公開源はそれぞれの価格時計で観測した価格だけを使う。
    own_progress = np.zeros(len(times))
    peer_clock = signal['entry_peer_bbo'][:, 2]
    peer_progress = np.zeros(len(peer_clock))
    for stamp, units in steps:
        own_progress[times >= stamp] = units
        peer_progress[peer_clock >= stamp] = units
    quote = opening + (record['tick'] if side == 1 else 0.) + side * width * own_progress
    record['bid'] = quote - record['tick'] if side == 1 else quote
    record['ask'] = quote if side == 1 else quote + record['tick']
    record['price'] = (record['bid'] + record['ask']) * .5
    peer_quote = peer_base + (peer_tick if side == 1 else 0.) + side * peer_width * peer_progress
    signal['entry_peer_bbo'][:, 3] = peer_quote - peer_tick if side == 1 else peer_quote
    signal['entry_peer_bbo'][:, 4] = peer_quote if side == 1 else peer_quote + peer_tick
    mapped = np.full(len(times), -1, np.int32)
    previous = -1
    for row, stamp in enumerate(times):
        index = int(np.searchsorted(signal['grid'], stamp, side='right') - 1)
        if index >= 0 and index != previous:
            mapped[row] = index
            previous = index
    signal['mapped'] = mapped
    return {('2000-01-03_人工', symbol): dict(record=record, signal=signal, reference_open=opening)}


def run(strategy: object, config: dict, prepared: dict, python: bool) -> dict:
    """
    機能: 人工入力を変えずに実装を実行し、旧及び追加診断と実約定を検査する。
    引数: strategy(object)、config/prepared(dict)、python(bool)。
    返り値: dictは人工出力。新正式期間の損益は生成しない。
    """
    before = pickle.dumps(prepared, protocol=5)
    compiled = strategy.ENGINE.simulate
    try:
        if python:
            strategy.ENGINE.simulate = compiled.py_func
        output = strategy.play(config, next(iter(prepared)), prepared)
    finally:
        strategy.ENGINE.simulate = compiled
    assert before == pickle.dumps(prepared, protocol=5), '共有preparedを変更しました'
    assert output['entry_policy_state_trace'].shape[1] == len(output['entry_policy_state_columns']) == 40
    assert output['entry_policy_events'].shape[1] == len(output['entry_policy_event_columns']) == 50
    for parent in output['entry_parent_diagnostics']:
        entries = output['orders'][(output['orders'][:, 2] == parent[0]) & (output['orders'][:, 7] == 1)]
        if parent[41] == 1:
            assert len(entries) == 1 and entries[0, 0] == parent[37] > parent[28]
            assert entries[0, 11] == parent[39] and entries[0, 6] == parent[40]
    assert np.all(output['target_trace'][:, 2:4] <= (10 if next(iter(prepared))[1] == 'TOPIX' else 20))
    return output


def old_output(old: object, config: dict, prepared: dict) -> dict:
    """
    機能: 旧97の執行へ同じ人工幅を渡し、時計対照の旧18列を照合可能にする。
    引数: old(object)、config/prepared(dict)。
    返り値: dictは旧97人工出力。旧strategyのキャッシュ設定を実行しない。
    """
    value = prepared[next(iter(prepared))]
    record, signal, opening = value['record'], dict(value['signal']), value['reference_open']
    tick = record['tick']
    signal['trend_initial_stop_width'] = max(2, math.ceil(opening * config['trend_initial_stop_bp'] / 10000. / tick - 1e-10)) * tick
    width = max(2, math.ceil(opening * config['entry_width_bp'] / 10000. / tick - 1e-10)) * tick
    signal['entry_wait_width'] = width
    for suffix, field in (('advance', 'entry_advance_widths'), ('pullback', 'entry_pullback_widths'),
                          ('recovery', 'entry_recovery_widths')):
        multiple = config[field]
        signal['entry_' + suffix + '_width'] = 0. if multiple == 0 else max(1, math.ceil(width * multiple / tick - 1e-10)) * tick
    compiled = old.simulate
    try:
        old.simulate = compiled.py_func
        return old.execute(record, signal, config)
    finally:
        old.simulate = compiled


def main() -> None:
    """
    機能: 少数人工で政策差とPython/JITの全20配列、C0旧18列を検算する。
    引数: なし。
    返り値: None。現コードSHAを証跡へ保存し、正式98損益・APIは実行しない。
    """
    strategy = load('価格時計政策の人工自己検査98', WORK / 'strategy.py')
    catalog = load('価格時計34条件の人工読取98', WORK / 'catalog.py')
    configs = {value['id']: value for value in catalog.catalog()}
    old = load('旧97執行の人工null読取98', WORK.parent / 'wave_v97/engine.py')
    cases = []
    null_count = 0
    for symbol, side in (('TOPIX', 1), ('NK225', -1)):
        for entry in (3, 7):
            fixture_data = gap_fixture(symbol, side, entry)
            for policy in range(4):
                config = configs[f'C{policy}_A{entry}_X3']
                output = run(strategy, config, copy.deepcopy(fixture_data), python=True)
                decisions = output['entry_parent_diagnostics'][:, 28].astype(int).tolist()
                if policy == 0:
                    expected = old_output(old, config, fixture_data)
                    for name in OLD_NAMES:
                        np.testing.assert_array_equal(output[name], expected[name])
                    assert not decisions
                    null_count += 1
                elif policy in (1, 2):
                    assert decisions == [340], (config['id'], decisions)
                    assert output['entry_wait_events'][output['entry_wait_events'][:, 1] == 8][0, 0] == 340
                    assert output['watch_state_trace'][340, 48] == 0, 'gapを取消旗へ残しました'
                else:
                    assert decisions == [363 if entry == 3 else 368], (config['id'], decisions)
                    events = output['entry_policy_events']
                    reprepare = events[events[:, 1] == 4]
                    assert len(reprepare) == 1 and reprepare[0, 0] == 343
                    assert reprepare[0, 44] == 1., '押しarmを再開始しませんでした'
                    trace = output['watch_state_trace']
                    np.testing.assert_array_equal(trace[340:343, 13:17], trace[339, 13:17][None, :].repeat(3, axis=0))
                    assert trace[343, 7] == trace[330, 7] and trace[343, 8] == trace[330, 8]
                    assert trace[343, 13] == trace[343, 14] and trace[343, 15] == 343
                    assert output['target_trace'][341, 4] == (8 if symbol == 'TOPIX' else 16)
                cases.append(dict(条件=config['id'], 商品=symbol, 方向=side, 予約行=decisions))
    print('gap政策の16人工とC0旧18列の4対照が合格', flush=True)

    # ----------------------------------------
    # 位相後という共通時計を除く意味の差と、未知基準の同行発注禁止を確認する。
    watch = np.full(32, np.nan)
    observation = np.array([10., 110., 100., 4000., 4000.5, 20., 220., 95., 50000., 50010.])
    strategy.ENGINE.entry_watch_start(watch, 1, 1, 10, 110, 100., 4000.5, 4., 4., 0., 0., 300., 3, observation, True, 0)
    advanced = observation + np.array([1., 1., 0., .5, .5, 1., 1., 1., 10., 10.])
    assert strategy.ENGINE.entry_pair_valid(advanced, True, True)
    assert strategy.ENGINE.entry_bbo_status(watch, advanced, True, .5, 10., 1) == (False, False)
    assert strategy.ENGINE.entry_bbo_status(watch, advanced, True, .5, 10., 2) == (True, True)
    assert not (advanced[7] > watch[16] and advanced[7] <= advanced[2])
    stagnant = advanced.copy()
    stagnant[[3, 4, 8, 9]] = observation[[3, 4, 8, 9]]
    assert strategy.ENGINE.entry_bbo_status(watch, stagnant, True, .5, 10., 2) == (True, False)

    # ----------------------------------------
    # JITは全20配列をPythonと一致させ、旧対照・追加診断を同時に検算する。
    jit_count = 0
    for symbol, side in (('TOPIX', 1), ('NK225', -1)):
        data = gap_fixture(symbol, side, 7)
        for policy in range(4):
            config = configs[f'C{policy}_A7_X3']
            expected = run(strategy, config, copy.deepcopy(data), python=True)
            actual = run(strategy, config, copy.deepcopy(data), python=False)
            for name in OLD_NAMES + NEW_NAMES:
                np.testing.assert_array_equal(expected[name], actual[name])
            jit_count += 1
    print('Python/JITの8人工×20配列が合格', flush=True)
    paths = [Path(__file__), HERE / 'support.py', WORK / 'engine.py', WORK / 'strategy.py',
             WORK / 'catalog.py', WORK.parent / 'wave_v97/engine.py']
    proof = dict(全合格=True, 人工政策経路=len(cases), C0旧18配列人工null=null_count,
        PythonJIT人工=jit_count, PythonJIT配列照合=jit_count * 20, 源時計同値非同値の人工=True,
        C1gap同行成立=True, C3gap期間幾何不更新=True, C3再準備同行不成立=True,
        共有prepared変更=0, 正式98損益実行=0, API取得=0, 実注文=0, 検査=cases,
        SHA256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths})
    (HERE / 'gap四政策の少数人工と旧18列及びPythonJITの自己検査.json').write_text(
        json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in proof.items() if key not in ('SHA256', '検査')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
