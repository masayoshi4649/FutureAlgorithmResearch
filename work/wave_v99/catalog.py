"""現在方向の観測源だけを替え、四時計政策と二入口・二出口で34条件を比較する。"""

from copy import deepcopy
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYMBOLS = ('TOPIX', 'NK225')
PRIMARY = 'L1_C1_A7_X3'
CONTROL = 'L0_C1_A7_X3'
LANES = ('L0', 'L1')
POLICIES = ('C0', 'C1', 'C2', 'C3')
ENTRIES = (1, 7)
EXITS = (1, 3)

spec = importlib.util.spec_from_file_location('不変98待機条件の読取99', HERE.parent / 'wave_v98/catalog.py')
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
PREVIOUS = {value['id']: value for value in previous.catalog()}


def catalog() -> list[dict]:
    """
    機能: 現在方向支持の旧気配中値と独立取引価格を一軸比較へ組み合わせる。
    引数: なし。
    返り値: list[dict]。候補、時計政策、待機幅、出口と数量を保持した34条件。
    """
    values = []
    for lane in LANES:
        for policy in POLICIES:
            for entry in ENTRIES:
                for exit_index in EXITS:
                    clock_id = f'{policy}_A{entry}_X{exit_index}'
                    value = deepcopy(PREVIOUS[clock_id])
                    value.update(id=f'{lane}_{clock_id}', previous_clock_id=clock_id,
                                 entry_support_lane=lane)
                    values.append(value)
    for exit_index in EXITS:
        ident = f'A0_X{exit_index}'
        value = deepcopy(PREVIOUS[ident])
        value.update(previous_clock_id=ident, entry_support_lane='L0')
        values.append(value)
    assert len(values) == len({value['id'] for value in values}) == 34
    assert all(value['trend_budget'] == 8 and value['range_budget'] == 0
               and value['trend_source'] == 'P0' and value['entry_width_bp'] == 10.
               and value['loss_reentry_kind'] == 'none' for value in values)
    return values


def references(ident: str) -> list[str]:
    """
    機能: 観測源・時計政策・入口・出口を一つずつ替えた比較先を返す。
    引数: ident(str)は今回の条件ID。
    返り値: list[str]。元候補と同じ約定規則を持つ有限対照のID。
    """
    if ident.startswith('A0_'):
        return ['A0_X3' if ident.endswith('X1') else 'A0_X1']
    lane, policy, entry, exit_name = ident.split('_')
    answers = [('L0' if lane == 'L1' else 'L1')+f'_{policy}_{entry}_{exit_name}']
    if policy == 'C1':
        answers.append(f'{lane}_C0_{entry}_{exit_name}')
    elif policy in ('C2', 'C3'):
        answers.append(f'{lane}_C1_{entry}_{exit_name}')
    answers.append(f'A0_{exit_name}')
    if entry == 'A7':
        answers.append(f'{lane}_{policy}_A1_{exit_name}')
    answers.append(f'{lane}_{policy}_{entry}_'+('X3' if exit_name == 'X1' else 'X1'))
    return list(dict.fromkeys(answers))


def labels() -> dict[str, str]:
    """
    機能: 現在方向の観測源と旧の入口出口条件を短い日本語名にする。
    引数: なし。
    返り値: dict[str,str]。全34条件の表示名。
    """
    old_labels = previous.labels()
    return {value['id']: ('独立取引価格で再確認／' if value['entry_support_lane'] == 'L1'
                         else '旧気配中値で再確認／' if value['entry_wait_kind'] else '')
                        +old_labels[value['previous_clock_id']] for value in catalog()}
