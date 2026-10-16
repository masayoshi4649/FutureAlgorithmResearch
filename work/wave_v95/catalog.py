"""追従入口の価格と観測資格、損失後の反対方向再参加を38条件へ分離する。"""

from copy import deepcopy
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYMBOLS = ('TOPIX', 'NK225')
PRIMARY = 'P3_R3_N'
spec = importlib.util.spec_from_file_location('確定追従94の条件読取95', HERE.parent / 'wave_v94/catalog.py')
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
BASE = next(value for value in previous.catalog() if value['id'] == 'J8')
KINDS = ('none', 'ban_opposite', 'fresh_quotes', 'fresh_price_quotes', 'sustained_price_quotes')
TRIGGERS = {'N': 'any_net_negative', 'S': 'stop_net_negative'}


def condition(ident: str, source: str, kind: str, trigger: str, quantity: int = 8) -> dict:
    """
    機能: 旧追従の執行・出口を維持し、入口源と損失後の再参加部品だけを指定する。
    引数: ident/source/kind/trigger(str)、quantity(int)はTOPIX基準数量。
    返り値: dictは独立した売買条件。日経数量はTOPIXの2倍。
    """
    value = deepcopy(BASE)
    value.update(id=ident, trend_budget=quantity, trend_source=source,
                 loss_reentry_kind=kind, loss_reentry_trigger=trigger, loss_confirm_seconds=10.)
    return value


def catalog() -> list[dict]:
    """
    機能: 4入口源と9再参加条件の36対照、及び数量だけ異なる2対照を返す。
    引数: なし。
    返り値: list[dict]は38条件。主は正式損益前にP3_R3_Nとする。
    """
    values = []
    for source in ('P0', 'P1', 'P2', 'P3'):
        values.append(condition(f'{source}_R0', source, 'none', TRIGGERS['N']))
        for mode in range(1, 5):
            for trigger, name in TRIGGERS.items():
                values.append(condition(f'{source}_R{mode}_{trigger}', source, KINDS[mode], name))
    values.append(condition('J10', 'P0', 'none', TRIGGERS['N'], 10))
    values.append(condition('P3_R3_N_Q4', 'P3', 'fresh_price_quotes', TRIGGERS['N'], 4))
    assert len(values) == 38 and len({value['id'] for value in values}) == 38
    assert all(value['range_budget'] == 0 and 0 < value['trend_budget'] <= 10 for value in values)
    assert all(value['selection'] == 'fixed' and not value['ungated_trend'] for value in values)
    return values


def references(ident: str) -> list[str]:
    """
    機能: 価格・候補・観測資格・再参加・数量の変更をそれぞれ対応対照へ結ぶ。
    引数: ident(str)は条件ID。
    返り値: list[str]は一軸対照又は数量対照。
    """
    if ident == 'J10':
        return ['P0_R0']
    if ident == 'P3_R3_N_Q4':
        return [PRIMARY]
    parts = ident.split('_')
    source, mode = parts[:2]
    answers = []
    if source != 'P0':
        answers.append('_'.join((f'P{int(source[1]) - 1}', *parts[1:])))
    if mode != 'R0':
        lower = int(mode[1]) - 1
        answers.append(f'{source}_R0' if lower == 0 else f'{source}_R{lower}_{parts[2]}')
        if parts[2] == 'S':
            answers.append(f'{source}_{mode}_N')
    return answers


def labels() -> dict[str, str]:
    """
    機能: 各入口素材と損失後の確認を日本語で短く識別する。
    引数: なし。
    返り値: dict[str,str]は表示用の手法名。
    """
    sources = {'P0': '旧候補・旧許可', 'P1': '旧候補・約定価格許可',
               'P2': '約定価格候補・旧観測資格', 'P3': '独立約定価格候補'}
    modes = {'none': '旧再参加', 'ban_opposite': '損失後の反対禁止',
             'fresh_quotes': '損失後の両気配再進行', 'fresh_price_quotes': '損失後の両価格・気配再進行',
             'sustained_price_quotes': '両価格・気配再進行を10秒確認'}
    values = {}
    for config in catalog():
        text = sources[config['trend_source']] + '・' + modes[config['loss_reentry_kind']]
        if config['loss_reentry_kind'] != 'none':
            text += '（全純損失）' if config['loss_reentry_trigger'] == 'any_net_negative' else '（停止の純損失）'
        if config['id'] == 'J10':
            text = '旧追従10枚・日経20枚の数量対照'
        elif config['id'] == 'P3_R3_N_Q4':
            text += '・4枚／8枚の数量対照'
        values[config['id']] = text
    return values
