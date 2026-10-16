"""旧候補後の待機入口を、幅尺度を独立させた36対照へ固定する。"""

from copy import deepcopy
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYMBOLS = ('TOPIX', 'NK225')
PRIMARY = 'A7_X3'
CONTROL = 'A0_X3'
spec = importlib.util.spec_from_file_location('旧出口36の読取97', HERE.parent / 'wave_v96/catalog.py')
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
PREVIOUS = {value['id']: value for value in previous.catalog()}
EXITS = ('S40_M0_H30', 'S10_M0_H30', 'S20_M2_H30', 'S10_M1_UNL')
ENTRY_LABELS = ('旧候補から即時', '両気配の再進行を待つ', '1幅順行を待つ',
                '1幅順行と両気配再進行', '2幅順行と両気配再進行',
                '半幅追尾新規と両気配再進行', '半幅の押し後に半幅回復',
                '1幅の押し後に半幅回復', '1幅の押し後に1幅回復')


def catalog() -> list[dict]:
    """
    機能: 同じ旧候補からの9入口と既検証4出口を組み合わせる。
    引数: なし。
    返り値: list[dict]。待機幅Wは始値10bpで、初期停止Sとは独立する。
    """
    values = []
    for entry in range(9):
        for exit_index, ident in enumerate(EXITS):
            value = deepcopy(PREVIOUS[ident])
            value.update(id=f'A{entry}_X{exit_index}', entry_wait_kind=entry,
                         entry_wait_seconds=300., entry_width_bp=10.,
                         entry_bbo_confirm=entry in (1, 3, 4, 5, 6, 7, 8),
                         entry_advance_widths=1. if entry in (2, 3) else 2. if entry == 4 else 0.,
                         entry_pullback_widths=.5 if entry == 6 else 1. if entry in (7, 8) else 0.,
                         entry_recovery_widths=.5 if entry in (5, 6, 7) else 1. if entry == 8 else 0.)
            values.append(value)
    assert len(values) == len({value['id'] for value in values}) == 36
    assert all(value['trend_budget'] == 8 and value['range_budget'] == 0
               and value['trend_source'] == 'P0' and value['loss_reentry_kind'] == 'none'
               and value['entry_width_bp'] == 10 for value in values)
    return values


def references(ident: str) -> list[str]:
    """
    機能: 入口又は出口の一軸対照を返し、入口の幅と停止の幅を混同しない。
    引数: ident(str)は条件ID。
    返り値: list[str]。同じ出口の即時・価格だけ・押し条件等の対照。
    """
    entry, exit_name = ident.split('_')
    e = int(entry[1:])
    answers = []
    if e:
        answers.append(f'A0_{exit_name}')
    extra = {3: (2, 1), 4: (3,), 6: (5,), 7: (6,), 8: (7,)}.get(e, ())
    answers += [f'A{other}_{exit_name}' for other in extra]
    if exit_name != 'X0':
        answers.append(f'{entry}_X0')
    return list(dict.fromkeys(answers))


def labels() -> dict[str, str]:
    """
    機能: 入口の待機機構と出口を短い日本語へ変換する。
    引数: なし。
    返り値: dict[str,str]。表示する各手法の名前。
    """
    exits = ('初期0.4%・30分', '初期0.1%・30分',
             '初期0.2%・半利益保護・30分', '初期0.1%・建値保護・期限なし')
    return {value['id']: ENTRY_LABELS[value['entry_wait_kind']]+'／'
            + exits[int(value['id'].split('_')[1][1:])] for value in catalog()}
