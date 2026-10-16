"""保存原本や金融を読まず、v2訂正及び入口状態の未来不変を独立人工で確かめる。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def load(name: str, path: Path) -> object:
    """
    機能: 新入口又は訂正の読取部品だけを固有名で読み込む。
    引数: name(str)、path(Path)はモジュール名と位置。
    返り値: objectは部品。正式派生及び金融関数は呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


# ----------------------------------------

def compare_prefix(left: dict, right: dict, count: int) -> int:
    """
    機能: 独立入力又は状態の過去配列を欠測込みで全件比較する。
    引数: left/right(dict)、count(int)は二入力と過去行数。
    返り値: intは一致した配列数。執行逆map空配列だけは全体を比較する。
    """
    assert left.keys() == right.keys()
    for name in left:
        a, b = (left[name], right[name]) if name == 'execution_to_raw_index' else (left[name][:count], right[name][:count])
        np.testing.assert_array_equal(a, b)
    return len(left)


def state_part(packet: dict) -> dict:
    """
    機能: 原行に対応する入口状態の比較列を選ぶ。
    引数: packet(dict)は人工入口の結果。
    返り値: dict[str,ndarray]は準備完了、基準、段階、正常資格、方向代理。
    """
    return {name: packet[name] for name in ('ready', 'anchor_raw_seq', 'phases',
                                           'qualified', 'volume_direction_proxy')}


def main() -> None:
    """
    機能: v2の最小訂正と旧42配列保持、人工原行状態の接頭及び未来変更不変を検算する。
    引数: なし。
    返り値: None。新review JSONだけを保存し、全64派生・原本読取・金融は行わない。
    """
    destination = HERE / 'v2二列訂正と入口接頭未来不変の独立人工.json'
    assert not destination.exists(), '完成検査を上書きしません'
    clock_review = load('独立入力人工の部品再使用', HERE / '入力時計と方向代理の独立人工を検算する.py')
    state_review = load('独立入口人工の部品再使用', HERE / '定着反転と二市場判断を独立人工で比較する.py')
    core = load('独立103未訂正core読取', HERE.parent / 'input' / 'core.py')
    correction = load('独立103訂正source読取', HERE.parent / 'input_v2' / 'correction.py')
    states = load('独立103未来不変検査対象', HERE.parent / 'engine' / 'states.py')
    catalog = load('独立103未来不変条件読取', HERE.parent / 'catalog.py')
    for name in ('fixed_quantity', 'seed', 'log_event'):
        setattr(states, name, getattr(states, name).py_func)
    correction_cases, unchanged_checks, corrected_rows = [], 0, 0
    for label, pt, vt in (
            ('正常', [0, 10, 20, 30], [0, 10, 20, 30]),
            ('価格だけ逆行', [0, 10, 5, 20], [0, 0, 0, 0]),
            ('出来高だけ逆行', [0, 10, 20, 30], [0, 10, 5, 30]),
            ('旧人工と同じ複合異常', [0, 10, 5, 30], [0, 10, 20, 30]),
            ('連続価格逆行', [0, 20, 10, 15, 20, 30], [0, 0, 0, 0, 0, 0]),
            ('一行', [0], [0])):
        rows = clock_review.fixture(pt, vt)
        original, _ = core.extract_rows(rows, clock_review.START, clock_review.END)
        before = {name: value.copy() for name, value in original.items()}
        actual, diagnosis = correction.correct_arrays(original)
        expected = clock_review.oracle_usable(pt, vt, [row['TradingVolume'] for _, row in rows])
        np.testing.assert_array_equal(actual['volume_delta_usable'], expected)
        np.testing.assert_array_equal(actual['volume_delta'],
                                      np.where(expected, original['volume_delta_observed'], np.nan))
        for name in original:
            np.testing.assert_array_equal(original[name], before[name])
            if name not in ('volume_delta_usable', 'volume_delta'):
                np.testing.assert_array_equal(actual[name], original[name])
                unchanged_checks += 1
        corrected_rows += diagnosis['usable変更行数']
        prefix_original, _ = core.extract_rows(rows[:2], clock_review.START, clock_review.END)
        prefix, _ = correction.correct_arrays(prefix_original)
        compare_prefix(prefix, actual, min(2, len(rows)))
        correction_cases.append(dict(検査=label, 一致=True, 期待=expected,
                                     変更行数=diagnosis['usable変更行数'], 入力変更なし=True, 不変配列数=42))
    empty, _ = core.extract_rows([], clock_review.START, clock_review.END)
    corrected_empty, _ = correction.correct_arrays(empty)
    assert len(corrected_empty['raw_seq']) == 0 and len(corrected_empty) == 44
    schema = correction.schema()
    assert schema['version'] == 2 and set(schema['columns']) == set(empty)
    assert schema['訂正']['変更列'] == ['volume_delta_usable', 'volume_delta']
    assert schema['訂正']['不変列数'] == 42 and schema['訂正']['raw再読取'] == 0
    # ----------------------------------------
    # 完全未来、切断未来、変更未来の三つで過去状態を比較する。
    prefixes, suffixes, compared_arrays = 0, 0, 0
    configs = [config for config in catalog.catalog() if config['kind'] == 'single']
    for label, rows in state_review.scenarios():
        for tick in (.5, 10.):
            for reflected in (False, True):
                full_raw = state_review.raw_fixture(rows, tick, reflected)
                for config in configs:
                    full = state_part(states.run(full_raw, dict(tick=tick), config, python=True))
                    for cut in sorted({2, 3, len(rows) - 1}):
                        prefix_raw = state_review.raw_fixture(rows[:cut], tick, reflected)
                        prefix = state_part(states.run(prefix_raw, dict(tick=tick), config, python=True))
                        compared_arrays += compare_prefix(prefix, full, cut)
                        prefixes += 1
                        changed = [deepcopy(row) for row in rows]
                        for row in changed[cut:]:
                            row.update(bid=row['bid'] + 20, ask=row['ask'] + 20,
                                       bidq=2000, askq=3000, volume=9000, last=row['last'] + 20)
                        altered_raw = state_review.raw_fixture(changed, tick, reflected)
                        altered = state_part(states.run(altered_raw, dict(tick=tick), config, python=True))
                        compared_arrays += compare_prefix(prefix, altered, cut)
                        suffixes += 1
    supplement06 = HERE.parent / '数値設計補足06.json'
    assert supplement06.exists()
    result = dict(全合格=True,
                  scope='v1源配列を人工生成してv2訂正を独立数理と照合。入口本体の人工接頭/未来変更一致。全64派生及び実金融は範囲外。',
                  訂正ケース=correction_cases, 訂正人工usable変更行数=corrected_rows,
                  不変配列検査数=unchanged_checks, 空人工44配列=True, schema44列及び最小二列訂正=True,
                  入口人工接頭数=prefixes, 入口人工未来変更数=suffixes, 過去一致配列数=compared_arrays,
                  補足04から06の未解決5点='全て確定。固定own分母、直前比正回復、全valid-ready競合、省略門の次別行、移動段階後の当該支持回復ready。',
                  SHA256={str(path.relative_to(ROOT)): state_review.digest(path) for path in (
                      Path(__file__), HERE.parent / 'engine' / 'states.py',
                      HERE.parent / 'input_v2' / 'correction.py', HERE.parent / 'input_v2' / 'data.py',
                      HERE / '入力時計と方向代理の独立人工を検算する.py',
                      HERE / '定着反転と二市場判断を独立人工で比較する.py',
                      *[HERE.parent / f'数値設計補足{index:02d}.json' for index in range(4, 7)])},
                  生原本再読取=0, 正式全64派生=0, 金融再生=0, 現在API取得=0, 実注文=0,
                  source変更=0, JIT実行=0)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 訂正ケース数=len(correction_cases), 不変配列検査数=unchanged_checks,
                          接頭数=prefixes, 未来変更数=suffixes, SHA256=state_review.digest(destination)), ensure_ascii=False))


if __name__ == '__main__':
    main()
