"""自己の板の準備と相手の方向を分け、支持境界と利益追尾を比べる。"""

from copy import deepcopy


SYMBOLS = ('TOPIX', 'NK225')
GATES = ('OWN', 'N3', 'N10', 'N30', 'P3', 'P10', 'P30', 'P10T2')
EXITS = ('O', 'B1', 'B2', 'B4', 'T2', 'T4')
PRIMARY = 'U_P10_T2'


def entries() -> list[dict]:
    """
    機能: 共通自己候補と相手確認の19入口を結果前に定義する。
    引数: なし。
    返り値: list[dict]はC/R各8と自動単一U3。新損益は読まない。
    """
    values = [dict(id=family+'_'+gate, family=family, gate=gate)
              for family in ('C', 'R') for gate in GATES]
    values += [dict(id='U_'+gate, family='U', gate=gate) for gate in ('OWN', 'N10', 'P10')]
    assert len(values) == 19
    return deepcopy(values)


def catalog() -> list[dict]:
    """
    機能: 入口・出口・二腿実配分を121条件へまとめる。
    引数: なし。
    返り値: list[dict]は114単一、6配分、旧参照1。
    """
    values = [dict(id=entry['id']+'_'+exit_id, kind='single', entry_id=entry['id'],
                   family=entry['family'], gate=entry['gate'], exit_id=exit_id,
                   quantity=dict(TOPIX=1, NK225=1))
              for entry in entries() for exit_id in EXITS]
    # ----------------------------------------
    # 同じ一般支持を使うC/Rの実数量配分を、単一1枚とは区別する。
    for exit_id in ('B2', 'T2'):
        for quantity in (2, 5, 8):
            values.append(dict(id=f'P{quantity*10}_P10_'+exit_id, kind='portfolio',
                components=('C_P10', 'R_P10'), gate='P10', exit_id=exit_id,
                allocations=dict(TOPIX=(quantity, 10-quantity), NK225=(2*quantity, 20-2*quantity)),
                per_direction_caps=dict(TOPIX=10, NK225=20)))
    values.append(dict(id='OLD_G0', kind='previous', previous_id='OLD_G0',
                       quantity=dict(TOPIX=1, NK225=1)))
    assert len(values) == len({value['id'] for value in values}) == 121
    return deepcopy(values)


def exit_config(ident: str) -> dict:
    """
    機能: 支持線幅と価格追尾方式を共通の数値へ対応させる。
    引数: ident(str)はO/B1/B2/B4/T2/T4。
    返り値: dictは幅呼値数・旧出口か・利益追尾の有無。
    """
    assert ident in EXITS
    return dict(id=ident, old=(ident == 'O'), support_ticks=0 if ident == 'O' else int(ident[1:]),
                profit_trail=ident.startswith('T'), initial_stop_fraction=.001,
                wide_trail_fraction=.004, hold_seconds=1800. if ident == 'O' else 0.,
                cooldown_seconds=30., start_offset=300., cut_offset=300., force_offset=60.)
