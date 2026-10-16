"""増玉後の停止余裕と停止線据置を分けて確かめる20条件の結果前定義。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
SYMBOLS = ('TOPIX', 'NK225')
PRIMARY = 'B1_T1_Q1_X1'
CONTROL = 'G0_QFULL_X1'
SMALL_CONTROL = 'G0_Q1_X1'
MULTIPLES = (('B05', .5), ('B1', 1.), ('B2', 2.))
EXITS = (1, 3)
sys.dont_write_bytecode = True

spec = importlib.util.spec_from_file_location('101固定数量定義だけを読む102', HERE.parent / 'wave_v101/catalog.py')
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
PREVIOUS = {value['id']: value for value in previous.catalog()}


def catalog() -> list[dict]:
    """
    機能: 初回1枚を保ち、3余裕幅と2線政策と2出口及び旧8対照を定義する。
    引数: なし。
    返り値: list[dict]。全20条件。新しい金額損益を見て条件を変更しない。
    """
    values = []
    for name, multiple in MULTIPLES:
        for preserve in (False, True):
            for exit_index in EXITS:
                old_id = f'G1_Q1_X{exit_index}'
                value = deepcopy(PREVIOUS[old_id])
                value.update(id=f'{name}_T{int(preserve)}_Q1_X{exit_index}',
                             previous_growth_id=old_id,
                             trend_growth_cushion_basis='initial_width',
                             trend_growth_cushion_initial_multiple=multiple,
                             trend_growth_preserve_stop=preserve)
                values.append(value)
    for prefix in ('G0_Q1', 'G1_Q1', 'G2_Q1', 'G0_QFULL'):
        for exit_index in EXITS:
            old_id = f'{prefix}_X{exit_index}'
            value = deepcopy(PREVIOUS[old_id])
            value['previous_growth_id'] = old_id
            values.append(value)
    assert len(values) == len({value['id'] for value in values}) == 20
    assert all(value['trend_budget'] == 8 and value['range_budget'] == 0
               and value['entry_price_cap_multiple'] == 1.
               and value['entry_support_lane'] == 'L1' and value['entry_clock_policy'] == 'C1'
               and value['entry_wait_kind'] == 1 for value in values)
    assert all(value['trend_initial_quantity'] == 1 for value in values[:12])
    return values


def references(ident: str) -> list[str]:
    """
    機能: 同じ初回枚数の固定、旧増玉、線政策、余裕幅及び出口の対照を返す。
    引数: ident(str)は今回の識別番号。
    返り値: list[str]。同時変更の比較と一軸比較を区別できる対照。
    """
    if ident.startswith('B'):
        basis, policy, quantity, exit_name = ident.split('_')
        other_basis = 'B1' if basis != 'B1' else 'B05'
        other_policy = 'T1' if policy == 'T0' else 'T0'
        values = [f'G0_Q1_{exit_name}', f'G1_Q1_{exit_name}',
                  f'{basis}_{other_policy}_{quantity}_{exit_name}',
                  f'{other_basis}_{policy}_{quantity}_{exit_name}',
                  f'{basis}_{policy}_{quantity}_'+('X3' if exit_name == 'X1' else 'X1')]
    else:
        mode, quantity, exit_name = ident.split('_')
        values = [f'G0_Q1_{exit_name}', f'G1_Q1_{exit_name}', f'G0_QFULL_{exit_name}',
                  f'{mode}_{quantity}_'+('X3' if exit_name == 'X1' else 'X1')]
    return list(dict.fromkeys(value for value in values if value != ident))


def labels() -> dict[str, str]:
    """
    機能: 入口を同じにした停止余裕と線政策を短い日本語にする。
    引数: なし。
    返り値: dict[str,str]。手法名。採用又は収益の成功を意味しない。
    """
    result = {}
    for value in catalog():
        initial, mode = value['trend_initial_quantity'], value['trend_growth_mode']
        if value['id'].startswith('B'):
            buffer = value['trend_growth_cushion_initial_multiple']
            action = f'停止余裕{buffer:g}S・'+('追加で線を寄せない' if value['trend_growth_preserve_stop'] else '予算維持の線更新可')
        else:
            action = '固定枚数' if mode == 0 else f'旧の停止余裕{mode}呼値'
        begin = '旧8/16枚' if initial is None else f'初回{initial}枚'
        exit_name = '通常30分' if value['trend_hold_seconds'] else '費用床・通常期限なし'
        result[value['id']] = f'{begin}／{action}／{exit_name}'
    return result
