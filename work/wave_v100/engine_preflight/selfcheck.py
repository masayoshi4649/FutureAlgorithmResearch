"""正式原本と損益を読まず、判断価格上限の保持・再入域・実約定超過を検査する。"""

import copy
import hashlib
import json
import math
from pathlib import Path
import pickle

import numpy as np

from support import HERE, ROOT, WORK, attach_support, load, old_prepared_fixture


OLD_NAMES = ('orders', 'trades', 'curve', 'source_curve', 'target_trace', 'events', 'stats', 'slots',
    'range_state_trace', 'risk_state_trace', 'range_parent_diagnostics', 'price_source_trace',
    'loss_reentry_events', 'trend_exit_state_trace', 'trend_parent_diagnostics', 'watch_state_trace',
    'entry_parent_diagnostics', 'entry_wait_events', 'entry_policy_state_trace', 'entry_policy_events')


def fixture(config: dict, symbol: str, side: int,
            changes: tuple = ((340, 3.), (350, 2.), (360, .5), (370, 1.), (380, -.25), (386, -.5), (390, .25), (410, 3.), (450, 0.)),
            opening: float | None = None) -> dict:
    """
    機能: 両BBOと独立LPを明示した人工で、上限外から内への再入域を作る。
    引数: config(dict)、symbol(str)、side(int)、changes(tuple[tuple[int,float]])、opening(float|None)。
    返り値: dict[tuple,dict]は1商品の人工prepared。正式素材を参照しない。
    """
    prepared = old_prepared_fixture(config, side=side)
    key = ('2000-01-03_人工', symbol)
    value = prepared[key]
    record, signal = value['record'], value['signal']
    base = float(value['reference_open'] if opening is None else opening)
    tick = record['tick']
    width = max(2, math.ceil(base * .001 / tick - 1e-10)) * tick
    value['reference_open'] = base
    signal['trend_width'] = max(2, math.ceil(base * .004 / tick - 1e-10)) * tick
    progress = np.zeros(len(record['time_s']))
    for row, multiple in changes:
        progress[row:] = multiple
    quote = base + (tick if side == 1 else 0.) + side * progress * width
    record['bid'] = quote - tick if side == 1 else quote.copy()
    record['ask'] = quote.copy() if side == 1 else quote + tick
    record['price'] = .5 * (record['bid'] + record['ask'])
    peer_base, peer_tick = (50000., 10.) if symbol == 'TOPIX' else (4000., .5)
    peer_width = max(2, math.ceil(peer_base * .001 / peer_tick - 1e-10)) * peer_tick
    peer_quote = peer_base + (peer_tick if side == 1 else 0.) + side * progress * peer_width
    indexes = signal['entry_peer_bbo'][:, 0].astype(int)
    signal['entry_peer_bbo'][:, 3] = (peer_quote - peer_tick if side == 1 else peer_quote)[indexes]
    signal['entry_peer_bbo'][:, 4] = (peer_quote if side == 1 else peer_quote + peer_tick)[indexes]
    return attach_support({key: value})


def run(strategy: object, config: dict, prepared: dict, python: bool = False) -> dict:
    """
    機能: 人工だけを実行し、上限診断の形と共有preparedの不変を確認する。
    引数: strategy(object)、config/prepared(dict)、python(bool)。
    返り値: dictは人工出力。Python/JIT切替は検査中だけで元へ復元する。
    """
    before = pickle.dumps(prepared, protocol=5)
    key = next(iter(prepared))
    compiled = strategy.ENGINE.simulate
    try:
        if python:
            strategy.ENGINE.simulate = compiled.py_func
        result = strategy.play(config, key, prepared)
    finally:
        strategy.ENGINE.simulate = compiled
    assert before == pickle.dumps(prepared, protocol=5)
    assert result['entry_cap_state_trace'].shape == (len(prepared[key]['record']['time_s']), 20)
    assert result['entry_cap_parent_diagnostics'].shape == (len(result['entry_parent_diagnostics']), 21)
    assert len(result['entry_cap_state_columns']) == 20 and len(result['entry_cap_parent_columns']) == 21
    for parent, cap_parent in zip(result['entry_parent_diagnostics'], result['entry_cap_parent_diagnostics']):
        np.testing.assert_array_equal(cap_parent[[0, 1, 2, 3, 4, 5, 6, 10, 11, 12, 15, 16, 17, 20]],
                                      parent[[0, 1, 4, 7, 8, 5, 9, 28, 30, 31, 37, 39, 40, 41]])
        if config['entry_price_cap_multiple'] is not None:
            assert cap_parent[9] == config['entry_price_cap_multiple'] * parent[9]
            assert cap_parent[14] == 1.
    return result


def old_output(engine: object, config: dict, value: dict) -> dict:
    """
    機能: 旧99の20出力を同じ人工信号へ接続し、無制限枝だけを照合する。
    引数: engine(object)は読取の99、config/value(dict)は人工だけ。
    返り値: dictは旧人工出力。旧キャッシュへ保存する経路を使わない。
    """
    signal = dict(value['signal'])
    if config['entry_support_lane'] == 'L1':
        signal['entry_j2_long'] = value['trend_lp_allowed'][1]
        signal['entry_j2_short'] = value['trend_lp_allowed'][-1]
    opening, tick = value['reference_open'], value['record']['tick']
    signal['trend_initial_stop_width'] = max(2, math.ceil(opening * config['trend_initial_stop_bp'] / 10000. / tick - 1e-10)) * tick
    width = max(2, math.ceil(opening * config['entry_width_bp'] / 10000. / tick - 1e-10)) * tick
    signal['entry_wait_width'] = width
    for suffix, field in (('advance', 'entry_advance_widths'), ('pullback', 'entry_pullback_widths'), ('recovery', 'entry_recovery_widths')):
        multiple = config[field]
        signal['entry_' + suffix + '_width'] = 0. if multiple == 0 else max(1, math.ceil(width * multiple / tick - 1e-10)) * tick
    compiled = engine.simulate
    try:
        engine.simulate = compiled.py_func
        return engine.execute(value['record'], signal, config)
    finally:
        engine.simulate = compiled


def main() -> None:
    """
    機能: 34条件の買売人工、境界、元TTL、実fill超過と少数旧nullを検査する。
    引数: なし。
    返り値: None。金融結果を一つも読まず証跡JSONだけ保存する。
    """
    strategy = load('100自己検査の判断価格上限', WORK / 'strategy.py')
    catalog = load('100自己検査の有限34条件', WORK / 'catalog.py')
    configs = {value['id']: value for value in catalog.catalog()}
    counts = dict(全34買売人工=0, 上限等号=0, 半呼値上限を拡大しない=0, 上限外保持と再入域=0,
                  元TTL等号取消=0, 未知quote取消=0, 予約後上限外fill=0, 旧20少数null=0, PythonJIT=0)
    for config in configs.values():
        for symbol in catalog.SYMBOLS:
            for side in (1, -1):
                result = run(strategy, config, fixture(config, symbol, side), python=True)
                assert len(result['trades']) >= 1, (config['id'], symbol, side)
                counts['全34買売人工'] += 1
    print('全34×両商品買売136人工が合格', flush=True)

    # ----------------------------------------
    # 等号・上限外での待機保持は候補固定で検査し、局所peakへ基準を替えない。
    for symbol in catalog.SYMBOLS:
        for side in (1, -1):
            config = configs['P05_L0_C1_A1_X1']
            data = fixture(config, symbol, side, changes=((340, .5), (410, 3.), (450, 0.)))
            result = run(strategy, config, data, python=True)
            parent = result['entry_cap_parent_diagnostics'][0]
            assert parent[13] == parent[9] and parent[14] == 1.
            counts['上限等号'] += 1
            data = fixture(config, symbol, side)
            result = run(strategy, config, data, python=True)
            trace = result['entry_cap_state_trace']
            blocked = np.flatnonzero(trace[:, 15] == 1.)
            assert len(blocked) and np.all(trace[blocked, 3] == 1.)
            np.testing.assert_array_equal(trace[blocked, 6], np.full(len(blocked), trace[330, 6]))
            assert np.all(trace[blocked, 16] == 630.)
            assert result['entry_parent_diagnostics'][0, 28] > blocked[0]
            counts['上限外保持と再入域'] += 1
            data = fixture(config, symbol, side, changes=((340, 3.),))
            result = run(strategy, config, data, python=True)
            assert not len(result['entry_parent_diagnostics'])
            assert ((result['entry_wait_events'][:, 0] == 630.) & (result['entry_wait_events'][:, 1] == 3.)
                    & (result['entry_wait_events'][:, 2] == 2.)).any()
            counts['元TTL等号取消'] += 1
            data = fixture(config, symbol, side, changes=((340, .5),))
            key = next(iter(data))
            data[key]['record']['quote_valid'][340] = False
            result = run(strategy, config, data, python=True)
            assert not len(result['entry_parent_diagnostics'])
            assert ((result['entry_wait_events'][:, 0] == 340.) & (result['entry_wait_events'][:, 2] == 5.)).any()
            counts['未知quote取消'] += 1
            data = fixture(config, symbol, side, changes=((340, .5), (346, 3.), (347, .5), (450, 0.)))
            result = run(strategy, config, data, python=True)
            parent = result['entry_cap_parent_diagnostics'][0]
            assert parent[10] == 345. and parent[15] == 346.
            assert parent[14] == 1. and parent[19] > 0 and len(result['trades']) >= 1
            counts['予約後上限外fill'] += 1
    for side in (1, -1):
        config = configs['P05_L0_C1_A1_X1']
        result = run(strategy, config, fixture(config, 'TOPIX', side,
                     changes=((340, 5./9.), (360, 4./9.), (450, 0.)), opening=4500.), python=True)
        trace = result['entry_cap_state_trace']
        assert trace[345, 2] == 2.25 and trace[345, 11] == 2.5 and trace[345, 15] == 1.
        assert result['entry_cap_parent_diagnostics'][0, 10] == 360.
        counts['半呼値上限を拡大しない'] += 1
    print('買売境界/再入域/元TTL/未知/次fill超過が合格', flush=True)

    # ----------------------------------------
    # 無制限の経済は旧99へ接続し、実行器だけを切り替えた全配列も同値にする。
    old_engine = load('99不変経済の少数人工読取100', WORK.parent / 'wave_v99/engine.py')
    for ident in ('P0_L0_C1_A1_X1', 'P0_L1_C1_A7_X3', 'A0_X1', 'A0_X3'):
        config = configs[ident]
        data = fixture(config, 'TOPIX', 1)
        value = next(iter(data.values()))
        actual = run(strategy, config, data, python=True)
        expected = old_output(old_engine, config, value)
        for name in OLD_NAMES:
            np.testing.assert_array_equal(actual[name], expected[name], err_msg=ident+'/'+name)
        counts['旧20少数null'] += 1
    for ident in ('P1_L1_C1_A1_X1', 'P05_L0_C1_A7_X3', 'P0_L1_C1_A7_X3', 'A0_X3'):
        for symbol, side in (('TOPIX', 1), ('NK225', -1)):
            config = configs[ident]
            data = fixture(config, symbol, side)
            expected = run(strategy, config, copy.deepcopy(data), python=True)
            actual = run(strategy, config, copy.deepcopy(data))
            for name in OLD_NAMES + ('entry_support_state_trace', 'entry_cap_state_trace', 'entry_cap_parent_diagnostics'):
                np.testing.assert_array_equal(actual[name], expected[name], err_msg=ident+'/'+name)
            assert actual['entry_support_input_SHA256'] == expected['entry_support_input_SHA256']
            counts['PythonJIT'] += 1
    paths = [Path(__file__), HERE / 'support.py', WORK / 'engine.py', WORK / 'strategy.py', WORK / 'catalog.py',
             WORK.parent / 'wave_v99/engine.py', WORK.parent / 'wave_v99/strategy.py']
    proof = dict(全合格=True, 検査件数=counts, PythonJIT配列照合=counts['PythonJIT']*23,
        共有prepared変更=0, 旧620対照は監査担当=True, 数学上限の不利拡大丸め=False,
        cap外実約定を未来選別せず診断だけ=True, 正式100損益実行=0, API取得=0, 実注文=0,
        SHA256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths})
    destination = HERE / '全34人工と判断上限及び元TTLと約定超過とPythonJITの自己検査.json'
    destination.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in proof.items() if key != 'SHA256'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
