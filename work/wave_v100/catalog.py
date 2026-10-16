"""現在支持と二入口二出口を固定し、元候補から不利な判断価格の幅を34対照で比べる。"""

from copy import deepcopy
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYMBOLS = ('TOPIX', 'NK225')
PRIMARY = 'P1_L1_C1_A1_X1'
CONTROL = 'P0_L1_C1_A1_X1'
CAPS = (('P0', None), ('P05', .5), ('P1', 1.), ('P2', 2.))
LANES = ('L0', 'L1')
ENTRIES = (1, 7)
EXITS = (1, 3)

spec = importlib.util.spec_from_file_location('不変99現在支持条件の読取100', HERE.parent / 'wave_v99/catalog.py')
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
PREVIOUS = {value['id']: value for value in previous.catalog()}


def catalog() -> list[dict]:
    """
    機能: 判断価格の不利幅だけを制限し、旧候補と支持・時計・出口・数量を保持する。
    引数: なし。
    返り値: list[dict]。新売買実装前の有限34条件。
    """
    values = []
    for cap_name, multiple in CAPS:
        for lane in LANES:
            for entry in ENTRIES:
                for exit_index in EXITS:
                    support_id = f'{lane}_C1_A{entry}_X{exit_index}'
                    value = deepcopy(PREVIOUS[support_id])
                    value.update(id=f'{cap_name}_{support_id}', previous_support_id=support_id,
                                 entry_price_cap_name=cap_name, entry_price_cap_multiple=multiple)
                    values.append(value)
    for exit_index in EXITS:
        ident = f'A0_X{exit_index}'
        value = deepcopy(PREVIOUS[ident])
        value.update(previous_support_id=ident, entry_price_cap_name='P0', entry_price_cap_multiple=None)
        values.append(value)
    assert len(values) == len({value['id'] for value in values}) == 34
    assert all(value['trend_budget'] == 8 and value['range_budget'] == 0
               and value['trend_source'] == 'P0' and value['entry_width_bp'] == 10.
               and value['loss_reentry_kind'] == 'none' for value in values)
    assert all(value['entry_clock_policy'] == ('C1' if value['entry_wait_kind'] else 'C0')
               for value in values)
    return values


def references(ident: str) -> list[str]:
    """
    機能: 判断価格上限、支持源、入口、出口だけを替える対照を返す。
    引数: ident(str)は今回の条件ID。
    返り値: list[str]。事前固定する有限比較先。
    """
    if ident.startswith('A0_'):
        return ['A0_X3' if ident.endswith('X1') else 'A0_X1']
    cap, lane, clock, entry, exit_name = ident.split('_')
    answers = [('P0' if cap != 'P0' else 'P1')+f'_{lane}_{clock}_{entry}_{exit_name}',
               cap+('_L0_' if lane == 'L1' else '_L1_')+f'{clock}_{entry}_{exit_name}',
               f'A0_{exit_name}']
    if entry == 'A7':
        answers.append(f'{cap}_{lane}_{clock}_A1_{exit_name}')
    answers.append(f'{cap}_{lane}_{clock}_{entry}_'+('X3' if exit_name == 'X1' else 'X1'))
    return list(dict.fromkeys(answers))


def labels() -> dict[str, str]:
    """
    機能: 元候補からの判断価格制限と旧条件を日本語で表示する。
    引数: なし。
    返り値: dict[str,str]。全34条件の表示名。
    """
    old_labels = previous.labels()
    names = dict(P0='判断価格の制限なし', P05='元候補から半Wまで', P1='元候補から1Wまで', P2='元候補から2Wまで')
    return {value['id']: (names[value['entry_price_cap_name']]+'／' if value['entry_wait_kind'] else '')
            +old_labels[value['previous_support_id']] for value in catalog()}
