"""現在支持の二列差替えと公開59源を、正式損益なしの人工で検査する。"""

import copy
import hashlib
import json
import math
from pathlib import Path
import pickle

import numpy as np

from support import HERE, ROOT, WORK, attach_support, load, prepared_fixture


OLD_NAMES = ('orders', 'trades', 'curve', 'source_curve', 'target_trace', 'events', 'stats', 'slots',
    'range_state_trace', 'risk_state_trace', 'range_parent_diagnostics', 'price_source_trace',
    'loss_reentry_events', 'trend_exit_state_trace', 'trend_parent_diagnostics', 'watch_state_trace',
    'entry_parent_diagnostics', 'entry_wait_events', 'entry_policy_state_trace', 'entry_policy_events')


def run(strategy: object, config: dict, prepared: dict, python: bool = False) -> dict:
    """
    機能: 人工だけで支持の輸送と共有準備不変、実約定との親対応を確認する。
    引数: strategy(object)、config/prepared(dict)、python(bool)。
    返り値: dictは1商品の人工出力。正式口座は実行しない。
    """
    key = next(iter(prepared))
    before = pickle.dumps(prepared, protocol=5)
    compiled = strategy.ENGINE.simulate
    try:
        if python:
            strategy.ENGINE.simulate = compiled.py_func
        result = strategy.play(config, key, prepared)
    finally:
        strategy.ENGINE.simulate = compiled
    assert before == pickle.dumps(prepared, protocol=5)
    value = prepared[key]
    signal = value['signal']
    seen = np.unique(signal['mapped'][signal['mapped'] >= 0])
    trace = result['entry_support_state_trace']
    assert trace.shape == (len(seen), 59) and len(result['entry_support_columns']) == 59
    np.testing.assert_array_equal(trace[:, 0], seen)
    np.testing.assert_array_equal(trace[:, 1], signal['grid'][seen])
    chosen = {1: signal['entry_j2_long'], -1: signal['entry_j2_short']} if config['entry_support_lane'] == 'L0' else value['trend_lp_allowed']
    for side, column, name in ((1, 7, 'entry_j2_long'), (-1, 8, 'entry_j2_short')):
        np.testing.assert_array_equal(trace[:, column], chosen[side][seen])
        assert result['entry_support_input_SHA256'][name] == hashlib.sha256(chosen[side].tobytes()).hexdigest()
    for parent in result['entry_parent_diagnostics']:
        entries = result['orders'][(result['orders'][:, 2] == parent[0]) & (result['orders'][:, 7] == 1)]
        if parent[41] == 1:
            assert len(entries) == 1 and entries[0, 0] == parent[37] > parent[28]
    return result


def refresh(strategy: object, key: tuple, value: dict) -> None:
    """
    機能: 改変した明示人工素材から許可と診断を再計算して整合させる。
    引数: strategy(object)、key(tuple)、value(dict)は人工準備だけ。
    返り値: None。未知資格を直接onesで埋めず、正式共有素材は受け取らない。
    """
    material = value['artificial_support_material']
    value['trend_lp_allowed'] = strategy.lp_allowed(material['trend_prices']['I3'][key[0]], material['grids'][key[0]])
    value['entry_support_base'] = strategy.support_basis(key, material, value)


def old_output(engine: object, config: dict, value: dict) -> dict:
    """
    機能: 同じ人工入力へ98の旧幅を渡し、L0経済20配列を少数照合する。
    引数: engine(object)は不変98、config/value(dict)は人工条件と準備。
    返り値: dictは人工の旧出力。旧strategyのキャッシュ設定は実行しない。
    """
    signal = dict(value['signal'])
    opening, tick = value['reference_open'], value['record']['tick']
    signal['trend_initial_stop_width'] = max(2, math.ceil(opening * config['trend_initial_stop_bp'] / 10000. / tick - 1e-10)) * tick
    width = max(2, math.ceil(opening * config['entry_width_bp'] / 10000. / tick - 1e-10)) * tick
    signal['entry_wait_width'] = width
    for suffix, field in (('advance', 'entry_advance_widths'), ('pullback', 'entry_pullback_widths'),
                          ('recovery', 'entry_recovery_widths')):
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
    機能: 全34人工、支持の正負・硬反対・C3再準備及びPython/JITを検査する。
    引数: なし。
    返り値: None。コード指紋付き人工証跡のみ保存し、正式99損益は計算しない。
    """
    strategy = load('99現在支持の人工自己検査', WORK / 'strategy.py')
    catalog = load('99全34人工の条件読取', WORK / 'catalog.py')
    configs = {config['id']: config for config in catalog.catalog()}
    examples = []
    for side in (1, -1):
        for config in configs.values():
            both = prepared_fixture(config, side=side)
            for key, value in both.items():
                output = run(strategy, config, {key: value})
                assert len(output['trades']) >= 1, (config['id'], key)
                examples.append(dict(条件=config['id'], 商品=key[1], 方向=side,
                                     予約数=len(output['entry_parent_diagnostics'])))
    print('全34×両商品×買売の136人工と59源輸送が合格', flush=True)

    # ----------------------------------------
    # 観測源の正負と旧取消の優先は、入口価格を未来から選別せずに固定する。
    checks = []
    for symbol, side in (('TOPIX', 1), ('NK225', -1)):
        positive_config = configs['L1_C1_A1_X3']
        key = ('2000-01-03_人工', symbol)
        original = prepared_fixture(positive_config, side=side)[key]
        positive = copy.deepcopy(original)
        positive['signal']['entry_j2_long'][:] = False
        positive['signal']['entry_j2_short'][:] = False
        for market in positive['artificial_support_material']['grids'][key[0]]['markets'].values():
            market['windows'][300]['source_valid'][:] = False
            market['windows'][300]['ret_bp'][:] = np.nan
        refresh(strategy, key, positive)
        yes = run(strategy, positive_config, {key: positive}, python=True)
        no = run(strategy, configs['L0_C1_A1_X3'], {key: positive}, python=True)
        assert len(yes['entry_parent_diagnostics']) > 0 and not len(no['entry_parent_diagnostics'])

        unknown = copy.deepcopy(positive)
        for market in unknown['artificial_support_material']['trend_prices']['I3'][key[0]]['markets'].values():
            market['windows'][300]['source_valid'][:] = False
            market['windows'][300]['ret_bp'][:] = np.nan
        refresh(strategy, key, unknown)
        failed = run(strategy, positive_config, {key: unknown}, python=True)
        assert not len(failed['entry_parent_diagnostics'])
        trace = failed['entry_support_state_trace']
        assert (trace[:, 20] == 1).any() and (trace[:, 21] == 0).all(), '単点と窓の資格を混同しました'

        reverse = copy.deepcopy(original)
        for market in reverse['artificial_support_material']['grids'][key[0]]['markets'].values():
            market['flow'][15]['ofi_ratio'][:] = -.2 * side
        refresh(strategy, key, reverse)
        reverse_output = run(strategy, positive_config, {key: reverse}, python=True)
        assert not len(reverse_output['entry_parent_diagnostics'])

        opposite = copy.deepcopy(original)
        mask = opposite['signal']['grid'] >= 345.
        opposite['signal']['wait_opposite_long' if side == 1 else 'wait_opposite_short'][mask] = True
        for market in opposite['artificial_support_material']['grids'][key[0]]['markets'].values():
            market['windows'][300]['source_valid'][mask] = True
            market['windows'][300]['ret_bp'][mask] = -3. * side
        refresh(strategy, key, opposite)
        conflict = run(strategy, positive_config, {key: opposite}, python=True)
        assert not len(conflict['entry_parent_diagnostics'])
        assert ((conflict['entry_wait_events'][:, 1] == 3) & (conflict['entry_wait_events'][:, 2] == 6)).any()
        checks.append(dict(商品=symbol, 旧mid不明LP既知で新規=True, 双方窓不明で不参加=True,
                           起点有効と窓無効を分離=True, 逆OFIで不参加=True, 硬い反対が先=True))

    # ----------------------------------------
    # 同じC3再準備が、選択した現在支持列を使うことを少数gap人工で確認する。
    gap_module = load('98固定gap人工の読取99', WORK.parent / 'wave_v98/engine_preflight/selfcheck.py')
    gap = attach_support(gap_module.gap_fixture('TOPIX', 1, 7))
    key = next(iter(gap))
    value = gap[key]
    for market in value['artificial_support_material']['trend_prices']['I3'][key[0]]['markets'].values():
        market['windows'][300]['source_valid'][value['signal']['grid'] < 360.] = False
    refresh(strategy, key, value)
    old = run(strategy, configs['L0_C3_A7_X3'], copy.deepcopy(gap), python=True)
    new = run(strategy, configs['L1_C3_A7_X3'], copy.deepcopy(gap), python=True)
    old_reprepare = old['entry_policy_events'][old['entry_policy_events'][:, 1] == 4][:, 0].astype(int).tolist()
    new_reprepare = new['entry_policy_events'][new['entry_policy_events'][:, 1] == 4][:, 0].astype(int).tolist()
    assert old_reprepare == [343] and new_reprepare == [348], (old_reprepare, new_reprepare)

    # ----------------------------------------
    # 経済本体は98と同じbytes、実行形も全20経済・政策と公開59源で同値にする。
    assert (WORK / 'engine.py').read_bytes() == (WORK.parent / 'wave_v98/engine.py').read_bytes()
    jit_count = 0
    for ident in ('L0_C1_A7_X3', 'L1_C1_A7_X3', 'L1_C3_A7_X3', 'A0_X3'):
        for symbol, side in (('TOPIX', 1), ('NK225', -1)):
            config = configs[ident]
            key = ('2000-01-03_人工', symbol)
            value = prepared_fixture(config, side=side)[key]
            expected = run(strategy, config, {key: copy.deepcopy(value)}, python=True)
            actual = run(strategy, config, {key: copy.deepcopy(value)})
            for name in OLD_NAMES + ('entry_support_state_trace',):
                np.testing.assert_array_equal(expected[name], actual[name])
            assert expected['entry_support_input_SHA256'] == actual['entry_support_input_SHA256']
            jit_count += 1
    empty = copy.deepcopy(value)
    empty['signal']['mapped'][:] = -1
    empty_result = run(strategy, config, {key: empty}, python=True)
    assert empty_result['entry_support_state_trace'].shape == (0, 59)
    print('支持の正負/C3再準備とPythonJIT8×21配列が合格', flush=True)
    old_engine = load('98不変経済20の人工読取99', WORK.parent / 'wave_v98/engine.py')
    nulls = 0
    for ident in ('L0_C1_A1_X1', 'L0_C3_A7_X3', 'A0_X1', 'A0_X3'):
        config = configs[ident]
        data = prepared_fixture(config)
        key = ('2000-01-03_人工', 'TOPIX')
        actual = run(strategy, config, {key: copy.deepcopy(data[key])}, python=True)
        expected = old_output(old_engine, config, data[key])
        for name in OLD_NAMES:
            np.testing.assert_array_equal(actual[name], expected[name])
        nulls += 1
    paths = [Path(__file__), HERE / 'support.py', WORK / 'engine.py', WORK / 'strategy.py', WORK / 'catalog.py',
             WORK.parent / 'wave_v98/engine.py', WORK.parent / 'wave_v98/engine_preflight/selfcheck.py']
    proof = dict(全合格=True, 全34両商品買売人工=len(examples), 支持正負=checks,
                 C3再準備=dict(旧支持=old_reprepare, 独立LP支持=new_reprepare),
                 PythonJIT人工=jit_count, PythonJIT配列照合=jit_count * 21, 公表なし診断shape=[0, 59],
                 旧20配列の少数人工null=nulls,
                 経済本体98byte一致=True, 共有prepared変更=0, 実支持配列全格子SHA一致=True,
                 旧1116対照は監査担当=True, 正式99損益実行=0, API取得=0, 実注文=0, 検査例=examples,
                 SHA256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths})
    (HERE / '全34人工と独立LP支持正負及びPythonJITと59源の自己検査.json').write_text(
        json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in proof.items() if key not in ('SHA256', '検査例')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
