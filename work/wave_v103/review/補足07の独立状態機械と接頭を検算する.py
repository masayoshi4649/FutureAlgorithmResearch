"""補足07の観測記録を仕様oracleへ加え、旧境界Falseを残したまま現sourceを人工検算する。"""

from copy import deepcopy
import json
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def oracle07(raw: dict, config: dict, tick: float, helpers: object) -> dict:
    """
    機能: 補足01〜07を独立な名称付き辞書状態機械で原行順に判定する。
    引数: raw/config(dict)、tick(float)、helpers(object)は人工、入口条件、呼値、独立価格参照部品。
    返り値: dictはready、固定基準seq、段階。engineの配列状態、simulate及びlogは参照しない。
    """
    family, n = config['family'], len(raw['raw_seq'])
    ready = np.zeros((n, 2), bool)
    anchors = np.full((n, 2), -1, np.int64)
    phases = np.full((n, 2), -1, np.int8)
    signs, states = helpers.proxy_oracle(raw), {1: None, -1: None}
    for row in range(n):
        for intent in (1, -1):
            out_side = intent if family == 'C' else -intent
            col = 0 if out_side == 1 else 1
            state = states[intent]
            if not raw['独立正常資格'][row]:
                states[intent] = None
                continue
            if state is None:
                state = helpers.seed_state(raw, row, intent)
                states[intent] = state
            else:
                b, a = raw['bid'][row], raw['ask'][row]
                opposite_q = helpers.observed_quantity(raw, row, state['p'], intent == -1)
                support_p = state['p'] if family == 'C' else state['r']
                support_q = helpers.observed_quantity(raw, row, support_p, out_side == 1)
                if family == 'C':
                    moved = (b >= state['p'] and a >= state['ask'] + tick) if intent == 1 else (a <= state['p'] and b <= state['bid'] - tick)
                else:
                    moved = (b <= state['bid'] - tick and a <= state['ask'] - tick) if intent == 1 else (b >= state['bid'] + tick and a >= state['ask'] + tick)
                original_reached = (b >= state['p']) if intent == 1 else (a <= state['p'])
                expired = (raw['price_time_s'][row] - state['stamp'] >= 120
                           or row - state['anchor'] >= 5000)
                reset = expired or opposite_q is None or support_q is None
                reset |= family == 'R' and original_reached
                reset |= state['saw_move'] and not moved
                if reset:
                    state = helpers.seed_state(raw, row, intent)
                    states[intent] = state
                elif state['phase'] == '活動待ち':
                    decrease = max(0., state['previous_q'] - opposite_q)
                    aligned = (signs[row] == intent and raw['volume_delta'][row] > 0
                               and abs(raw['last'][row] - state['p']) <= tick)
                    if config['use_supply'] and (not config['use_volume'] or aligned):
                        state['decreased'] += decrease
                    if config['use_volume'] and aligned and (not config['use_supply'] or decrease > 0):
                        state['initial_volume'] += raw['volume_delta'][row]
                    state['previous_q'] = opposite_q
                    supply_ok = not config['use_supply'] or state['decreased'] >= .5 * state['q0']
                    volume_ok = not config['use_volume'] or state['initial_volume'] >= config['strength'] * state['q0']
                    if supply_ok and volume_ok:
                        state['phase'] = '回復待ち' if family == 'R' else '移動待ち'
                        if family == 'C' and moved:
                            state['saw_move'] = True
                elif state['phase'] == '回復待ち':
                    recovered = opposite_q > state['previous_q'] and opposite_q >= .8 * state['q0']
                    state['previous_q'] = opposite_q
                    if not config['use_supply'] or recovered:
                        state['phase'] = '移動待ち'
                        if moved:
                            state['saw_move'] = True
                elif state['phase'] == '移動待ち':
                    if moved:
                        state['saw_move'] = True
                        denominator = state['q0'] if family == 'C' else state['own_q0']
                        if not config['use_supply'] or support_q >= .5 * denominator:
                            state['phase'] = '移動後待ち'
                            state['post_volume'] = 0.
                else:
                    denominator = state['q0'] if family == 'C' else state['own_q0']
                    supported = not config['use_supply'] or support_q >= .5 * denominator
                    progress = out_side * (raw['last'][row] - support_p)
                    if (config['use_volume'] and signs[row] == out_side and raw['volume_delta'][row] > 0
                            and 0 <= progress <= 2 * tick):
                        state['post_volume'] += raw['volume_delta'][row]
                    state['ready'] = bool(supported and (not config['use_volume']
                                          or state['post_volume'] >= config['strength'] * state['q0']))
                    if state['ready']:
                        state['first_ready'] = True
            phase_names = {'活動待ち': 0, '回復待ち': 1,
                           '移動待ち': 1 if family == 'C' else 2,
                           '移動後待ち': (3 if state['first_ready'] else 2) if family == 'C'
                                         else (4 if state['first_ready'] else 3)}
            anchors[row, col] = raw['raw_seq'][state['anchor']]
            phases[row, col] = phase_names[state['phase']]
            ready[row, col] = state['ready']
    return dict(ready=ready, anchor_raw_seq=anchors, phases=phases)


# ----------------------------------------

def main() -> None:
    """
    機能: 全14入口の既人工と旧112境界を別oracle及び接頭未来変更で検算する。
    引数: なし。
    返り値: None。新review JSONだけを保存し、旧False・旧oracle・金融・原本を変更しない。
    """
    import importlib.util
    path = HERE / '定着反転と二市場判断を独立人工で比較する.py'
    spec = importlib.util.spec_from_file_location('補足07の独立人工部品', path)
    review = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(review)
    boundary = review.load_module('補足07の旧境界部品', HERE / '準備回復行での先行移動を忘れる反例を検査する.py')
    states_path = HERE.parent / 'engine' / 'states.py'
    states = review.load_module('補足07の人工検査対象', states_path)
    catalog = review.load_module('補足07の条件読取', HERE.parent / 'catalog.py')
    before = review.digest(states_path)
    for name in ('fixed_quantity', 'seed', 'log_event'):
        setattr(states, name, getattr(states, name).py_func)
    configs = [config for config in catalog.catalog() if config['kind'] == 'single']
    matrices = [(label, rows, configs, None) for label, rows in review.scenarios()]
    for family in ('C', 'R'):
        for broken in (False, True):
            rows, observed, next_row = boundary.examples(review.market_row, family, broken)
            matrices.append((family + ('直後崩れ' if broken else '維持'), rows,
                             [config for config in configs if config['family'] == family],
                             dict(family=family, broken=broken, observed=observed, boundary=next_row)))
    compared, state_rows, prefix_count, prefix_arrays = 0, 0, 0, 0
    boundary_checks = []
    for label, rows, selected, edge in matrices:
        for symbol, tick in (('TOPIX', .5), ('NK225', 10.)):
            for reflection in (False, True):
                raw = review.raw_fixture(rows, tick, reflection)
                for config in selected:
                    expected = oracle07(raw, config, tick, review)
                    actual = states.run(raw, dict(tick=tick), config, python=True)
                    for name in expected:
                        np.testing.assert_array_equal(expected[name], actual[name], err_msg=f'{label}/{symbol}/{reflection}/{config["id"]}/{name}')
                    compared += 1
                    state_rows += len(rows) * 2
                    if edge is not None:
                        intent = -1 if reflection else 1
                        direction = intent if edge['family'] == 'C' else -intent
                        col = 0 if direction == 1 else 1
                        observed, next_row = edge['observed'], edge['boundary']
                        events = actual['events']
                        intended = events[events[:, 1] == intent]
                        observed_events = intended[(intended[:, 0] == observed) & (intended[:, 3] == 9)]
                        move_same_row = intended[(intended[:, 0] == observed) & (intended[:, 3] == 4)]
                        assert len(observed_events) == 1 and len(move_same_row) == 0
                        assert int(observed_events[0, 9]) == -1 and observed_events[0, 21] == 0
                        if edge['broken']:
                            resets = intended[(intended[:, 0] == next_row) & (intended[:, 3] == 8)]
                            assert len(resets) == 1 and int(resets[0, 4]) == 4
                            assert int(actual['anchor_raw_seq'][next_row, col]) == next_row
                            assert not bool(actual['ready'][-1, col])
                        else:
                            passed = intended[(intended[:, 0] == next_row) & (intended[:, 3] == 4)]
                            assert len(passed) == 1 and bool(actual['ready'][-1, col])
                            assert int(passed[0, 9]) == next_row and passed[0, 21] == 0
                        boundary_checks.append(dict(入口=config['id'], 商品=symbol, 売買反射=reflection,
                            崩れ=edge['broken'], 観測行=observed, 移動段階通過は次行=True,
                            崩れなら当該行再基準=True, 最終ready=bool(actual['ready'][-1, col])))
                    for cut in sorted({2, 3, len(rows) - 1}):
                        prefix_raw = review.raw_fixture(rows[:cut], tick, reflection)
                        prefix = states.run(prefix_raw, dict(tick=tick), config, python=True)
                        modified_rows = [deepcopy(row) for row in rows]
                        for row in modified_rows[cut:]:
                            row.update(bid=row['bid'] + 20, ask=row['ask'] + 20,
                                       bidq=2000, askq=3000, volume=9000, last=row['last'] + 20)
                        changed_raw = review.raw_fixture(modified_rows, tick, reflection)
                        changed = states.run(changed_raw, dict(tick=tick), config, python=True)
                        for name in ('ready', 'anchor_raw_seq', 'phases', 'qualified', 'volume_direction_proxy'):
                            np.testing.assert_array_equal(prefix[name], actual[name][:cut])
                            np.testing.assert_array_equal(prefix[name], changed[name][:cut])
                            prefix_arrays += 2
                        prefix_count += 1
    assert review.digest(states_path) == before
    old_path = HERE / 'C準備とR回復行の先行移動を忘れる独立人工反例.json'
    old = json.loads(old_path.read_text(encoding='utf-8'))
    assert old['全合格'] is False and old['反例再現'] is True
    assert old['価格破れで旧活動再使用件数'] == 56
    engine_proof = HERE.parent / 'engine' / '独立状態と厳密過去接続及び実配分の人工検査_補足07確定.json'
    proof = json.loads(engine_proof.read_text(encoding='utf-8'))
    source_fields = [value for key, value in proof.items() if 'SHA' in key]
    result = dict(全合格=True,
        scope='補足07の観測記録を独立辞書oracleへ反映。現Python本体の人工状態と接頭/未来変更を比較。実prefix及び金融を含まない。',
        入口条件数=14, 商品呼値数=2, 売買反射数=2, 一致人工ケース数=compared,
        比較状態行数=state_rows, 補足07境界件数=len(boundary_checks),
        旧崩れ56件の持越し消失=sum(case['崩れ'] for case in boundary_checks),
        維持56件で別行段階通過=sum(not case['崩れ'] for case in boundary_checks),
        境界=boundary_checks, 人工接頭数=prefix_count, 人工未来変更数=prefix_count,
        過去一致配列数=prefix_arrays, 旧False保持=True,
        engine公式人工を独立数理の代わりに使った=False,
        engine公式人工SHA項目数=len(source_fields),
        SHA256={str(file.relative_to(ROOT)): review.digest(file) for file in (
            Path(__file__), states_path, HERE.parent / 'catalog.py',
            HERE / '定着反転と二市場判断を独立人工で比較する.py',
            HERE / '準備回復行での先行移動を忘れる反例を検査する.py', old_path,
            engine_proof, HERE.parent / '数値設計補足07.json')},
        正式原本読取=0, 正式全64派生=0, 金融再生=0, 現在API取得=0, 実注文=0,
        本体source変更=0, JIT実行=0)
    destination = HERE / '補足07入口の独立oracleと旧56反例消失及び接頭不変.json'
    assert not destination.exists(), '完成資料は上書きしません'
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 一致人工ケース数=compared, 境界件数=len(boundary_checks),
                         旧56反例消失=56, 維持別行=56, 接頭数=prefix_count, SHA256=review.digest(destination)), ensure_ascii=False))


if __name__ == '__main__':
    main()
