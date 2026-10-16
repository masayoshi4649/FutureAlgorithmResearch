"""初回を小さくし、全玉損失予算を固定して段階的に増やす20条件の結果前定義。"""

from copy import deepcopy
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYMBOLS = ('TOPIX', 'NK225')
PRIMARY = 'G1_Q1_X1'
CONTROL = 'G0_QFULL_X1'
SMALL_CONTROL = 'G0_Q1_X1'
INITIALS = (1, 2, 4)
GROWTH = (0, 1, 2)
EXITS = (1, 3)

spec = importlib.util.spec_from_file_location('100固定条件だけを読む101', HERE.parent / 'wave_v100/catalog.py')
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
PREVIOUS = {value['id']: value for value in previous.catalog()}


def catalog() -> list[dict]:
    """
    機能: 初回1/2/4枚の固定又は予算固定の増玉と、不変の全量二対照を定義する。
    引数: なし。
    返り値: list[dict]。初回枚数は両商品で同じ絶対枚数。最大は既存8/16枚。
    """
    values = []
    for initial in INITIALS:
        for growth in GROWTH:
            for exit_index in EXITS:
                old_id = f'P1_L1_C1_A1_X{exit_index}'
                value = deepcopy(PREVIOUS[old_id])
                value.update(id=f'G{growth}_Q{initial}_X{exit_index}',
                             previous_price_cap_id=old_id, trend_initial_quantity=initial,
                             trend_growth_mode=growth, trend_growth_cushion_ticks=growth,
                             trend_growth_risk_budget='初回全玉の初期停止損失と往復費用に固定')
                values.append(value)
    for exit_index in EXITS:
        old_id = f'P1_L1_C1_A1_X{exit_index}'
        value = deepcopy(PREVIOUS[old_id])
        value.update(id=f'G0_QFULL_X{exit_index}', previous_price_cap_id=old_id,
                     trend_initial_quantity=None, trend_growth_mode=0,
                     trend_growth_cushion_ticks=0,
                     trend_growth_risk_budget='既存全量の停止条件をそのまま保持')
        values.append(value)
    assert len(values) == len({value['id'] for value in values}) == 20
    assert all(value['entry_price_cap_multiple'] == 1. and value['entry_support_lane'] == 'L1'
               and value['entry_clock_policy'] == 'C1' and value['entry_wait_kind'] == 1
               and value['trend_budget'] == 8 and value['range_budget'] == 0 for value in values)
    return values


def references(ident: str) -> list[str]:
    """
    機能: 同じ初回枚数で増玉しない対照と既存全量及び出口対照を返す。
    引数: ident(str)は今回の識別番号。
    返り値: list[str]。数量縮小だけの効果と条件付き配分を区別する。
    """
    mode, initial, exit_name = ident.split('_')
    values = [f'G0_{initial}_{exit_name}', f'G0_QFULL_{exit_name}',
              f'{mode}_{initial}_'+('X3' if exit_name == 'X1' else 'X1')]
    return list(dict.fromkeys(value for value in values if value != ident))


def labels() -> dict[str, str]:
    """
    機能: まだ実装していない数量配分案を短い日本語で表示する。
    引数: なし。
    返り値: dict[str,str]。手法名を収益達成の保証に使わない。
    """
    answers = {}
    for value in catalog():
        initial, mode = value['trend_initial_quantity'], value['trend_growth_mode']
        begin = '既存の8/16枚固定' if initial is None else f'初回{initial}枚'
        action = '増玉なし' if mode == 0 else f'利益を確認して倍増・全玉損失予算固定・停止線まで{mode}呼値の余裕'
        answers[value['id']] = begin+'／'+action+'／'+('通常30分' if value['trend_hold_seconds'] else '費用床・通常期限なし')
    return answers
