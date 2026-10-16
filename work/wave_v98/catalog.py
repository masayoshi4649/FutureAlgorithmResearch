"""価格時計の取消政策を、同じ四入口と二出口の34対照へ固定する。"""

from copy import deepcopy
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYMBOLS = ('TOPIX', 'NK225')
PRIMARY = 'C1_A7_X3'
CONTROL = 'C0_A7_X3'
POLICIES = ('C0', 'C1', 'C2', 'C3')
ENTRIES = (1, 3, 5, 7)
EXITS = (1, 3)

spec = importlib.util.spec_from_file_location('不変97待機条件の読取98', HERE.parent / 'wave_v97/catalog.py')
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
PREVIOUS = {value['id']: value for value in previous.catalog()}


def catalog() -> list[dict]:
    """
    機能: 旧待機の取消・源確認・gap後再準備を独立な政策として組み合わせる。
    引数: なし。
    返り値: list[dict]。入口幅や出口は97の既定値から変更しない34条件。
    """
    values = []
    for policy in POLICIES:
        for entry in ENTRIES:
            for exit_index in EXITS:
                previous_id = f'A{entry}_X{exit_index}'
                value = deepcopy(PREVIOUS[previous_id])
                value.update(id=f'{policy}_{previous_id}', previous_id=previous_id,
                             entry_clock_policy=policy)
                values.append(value)
    for exit_index in EXITS:
        previous_id = f'A0_X{exit_index}'
        value = deepcopy(PREVIOUS[previous_id])
        value.update(previous_id=previous_id, entry_clock_policy='C0')
        values.append(value)
    assert len(values) == len({value['id'] for value in values}) == 34
    assert all(value['trend_budget'] == 8 and value['range_budget'] == 0
               and value['trend_source'] == 'P0' and value['entry_width_bp'] == 10.
               and value['loss_reentry_kind'] == 'none' for value in values)
    return values


def references(ident: str) -> list[str]:
    """
    機能: 同じ入口出口で政策だけ変える対照と同じ政策の即時対照を示す。
    引数: ident(str)は34条件内のID。
    返り値: list[str]。政策一軸、入口一軸及び既定出口間の比較ID。
    """
    if ident.startswith('A0_'):
        return ['A0_X3' if ident.endswith('X1') else 'A0_X1']
    policy, entry, exit_name = ident.split('_')
    answers = []
    if policy == 'C1':
        answers.append(f'C0_{entry}_{exit_name}')
    elif policy in ('C2', 'C3'):
        answers.append(f'C1_{entry}_{exit_name}')
    answers.append(f'A0_{exit_name}')
    for other in {'A3': ('A1',), 'A5': ('A1',), 'A7': ('A5',)}.get(entry, ()):
        answers.append(f'{policy}_{other}_{exit_name}')
    answers.append(f'{policy}_{entry}_'+('X3' if exit_name == 'X1' else 'X1'))
    return list(dict.fromkeys(answers))


def labels() -> dict[str, str]:
    """
    機能: 政策、入口機構及び出口を短い日本語へ変換する。
    引数: なし。
    返り値: dict[str,str]。各手法の日本語表示名。
    """
    old_labels = previous.labels()
    policy_labels = dict(C0='旧の価格間隔取消', C1='価格間隔だけでは取消しない',
                         C2='各市場の源から再進行', C3='価格間隔後に再準備')
    return {value['id']: (policy_labels[value['entry_clock_policy']]+'／'
             if value['entry_wait_kind'] else '')+old_labels[value['previous_id']]
            for value in catalog()}
