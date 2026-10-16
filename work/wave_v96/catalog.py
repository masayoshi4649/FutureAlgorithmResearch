"""入口を固定し、初期停止・順行後保護・通常期限を独立に比較する。"""

from copy import deepcopy
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYMBOLS = ('TOPIX', 'NK225')
PRIMARY = 'S10_M1_UNL'
CONTROL = 'S40_M0_H30'
spec = importlib.util.spec_from_file_location('旧J8条件の読取96', HERE.parent / 'wave_v95/catalog.py')
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
BASE = next(value for value in previous.catalog() if value['id'] == 'P0_R0')


def catalog() -> list[dict]:
    """
    機能: 初期停止3幅、利益保護3種類、通常期限2種類の18対照を返す。
    引数: なし。
    返り値: list[dict]。入口、枚数、追尾幅、再参加、執行を固定した条件。
    """
    values = []
    for stop in (10, 20, 40):
        for mode in (0, 1, 2):
            for name, seconds in (('H30', 1800.), ('UNL', 0.)):
                value = deepcopy(BASE)
                value.update(id=f'S{stop}_M{mode}_{name}', trend_initial_stop_bp=stop,
                             trend_protection_mode=mode, trend_hold_seconds=seconds)
                values.append(value)
    assert len(values) == len({value['id'] for value in values}) == 18
    assert all(value['trend_source'] == 'P0' and value['loss_reentry_kind'] == 'none'
               and value['trend_budget'] == 8 and value['range_budget'] == 0 for value in values)
    return values


def references(ident: str) -> list[str]:
    """
    機能: 初期幅・利益保護・保有期限の一軸対照を返す。
    引数: ident(str)は条件ID。
    返り値: list[str]。同じ入口と枚数で一部品だけ異なる条件。
    """
    stop, mode, hold = ident.split('_')
    answers = []
    if stop != 'S40':
        answers.append('_'.join(('S40', mode, hold)))
    if mode != 'M0':
        answers.append('_'.join((stop, 'M0', hold)))
    if hold != 'H30':
        answers.append('_'.join((stop, mode, 'H30')))
    return answers


def labels() -> dict[str, str]:
    """
    機能: 18条件の注文手法を日本語で短く識別する。
    引数: なし。
    返り値: dict[str,str]。表示用の手法名。
    """
    protections = ('追加保護なし', '順行後に費用込み建値保護', '順行後に半分の利益を保護')
    return {value['id']: f"初期停止{value['trend_initial_stop_bp']/100:.1f}%・"
            + protections[value['trend_protection_mode']] + '・'
            + ('場末まで期限なし' if value['trend_hold_seconds'] == 0 else '通常30分期限')
            for value in catalog()}
