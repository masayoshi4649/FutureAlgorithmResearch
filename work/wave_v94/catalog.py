"""価格素材・現在の新規資格・停止・利確を53条件に分け、配分も固定する。"""

from copy import deepcopy
import importlib.util
from pathlib import Path

SYMBOLS = ('TOPIX', 'NK225')
PRIMARY = 'I3_G1_S0_T1'
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('旧53設計の読取93', HERE.parent / 'wave_v93/catalog.py')
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
BASES = {value['id']: value for value in previous.catalog()}
PROFILES = ('I0', 'I1', 'I2', 'I3')
CONTEXTS = ('legacy', 'observable', 'confirmed_range')


def clone(ident: str, config: dict, **changes: object) -> dict:
    """
    機能: 条件を複製して、指定した変更を明示的に付ける。
    引数: ident(str)、config(dict)、changes(dict[str,object])。
    返り値: dict。独立した売買条件。
    """
    result = deepcopy(config)
    result.update(id=ident, price_lane='I0', range_entry_context='legacy')
    result.update(changes)
    return result


def catalog() -> list[dict]:
    """
    機能: 48基本対照と5個の旧基準・同数量単独・配分対照を返す。
    引数: なし。
    返り値: list[dict]。主は新損益前にI3_G1_S0_T1へ固定する。
    """
    values = []
    for profile in PROFILES:
        for gate, context in enumerate(CONTEXTS):
            for stop in range(2):
                for target in range(2):
                    ident = f'{profile}_G{gate}_S{stop}_T{target}'
                    config = clone(ident, BASES['C00'], price_lane=profile, range_entry_context=context,
                                   range_stop_kind='width' if stop == 0 else 'witness_extreme',
                                   range_target_kind='widths' if target == 0 else 'center',
                                   range_entry_max_risk_widths=0., range_entry_min_center_ratio=0.,
                                   range_failure_reentry_kind='legacy')
                    values.append(config)
    primary = next(value for value in values if value['id'] == PRIMARY)
    small = clone('R2', primary, price_lane=primary['price_lane'],
                  range_entry_context=primary['range_entry_context'], range_budget=2)
    mixture = clone('M82', small, price_lane=small['price_lane'],
                    range_entry_context=small['range_entry_context'], trend_budget=8, ungated_trend=True)
    values += [clone('OLD_C11', BASES['C11']), clone('J8', BASES['S00']),
               clone('J10', BASES['S01']), small, mixture]
    assert len(values) == 53 and len({value['id'] for value in values}) == 53
    assert all(value['trend_budget'] + value['range_budget'] <= 10 for value in values)
    assert all(value['range_entry_min_center_ratio'] == 0 and value['range_failure_reentry_kind'] == 'legacy'
               for value in values[:48])
    return values


def references(ident: str) -> list[str]:
    """
    機能: 変更軸ごとの対照を返し、複数変更から単独の効果を断定させない。
    引数: ident(str)。条件ID。
    返り値: list[str]。一軸対照又は源・数量対照。
    """
    controls = dict(OLD_C11=[], J8=[], J10=['J8'], R2=[PRIMARY], M82=['J8', 'J10', 'R2'])
    if ident in controls:
        return controls[ident]
    profile, gate, stop, target = ident.split('_')
    answer = []
    previous_profile = {'I1': 'I0', 'I2': 'I0', 'I3': 'I2'}.get(profile)
    if previous_profile:
        answer.append('_'.join((previous_profile, gate, stop, target)))
    if gate != 'G0':
        answer.append('_'.join((profile, 'G0' if gate == 'G1' else 'G1', stop, target)))
    if stop == 'S1':
        answer.append('_'.join((profile, gate, 'S0', target)))
    if target == 'T1':
        answer.append('_'.join((profile, gate, stop, 'T0')))
    return answer


def labels() -> dict[str, str]:
    """
    機能: 価格素材と新規再確認及び出口を日本語で短く識別する。
    引数: なし。
    返り値: dict[str,str]。各手法の説明用名称。
    """
    prices = dict(I0='旧中値', I1='分離中値', I2='旧源LP', I3='原本LP')
    contexts = ('旧入口', '現在可観測', '現在往復確認')
    result = {}
    for config in catalog()[:48]:
        profile, gate, stop, target = config['id'].split('_')
        result[config['id']] = '・'.join((prices[profile], contexts[int(gate[1])],
                                        '1幅停止' if stop == 'S0' else '極値停止',
                                        '3幅利確' if target == 'T0' else '中心利確'))
    result.update(OLD_C11='旧93主の完全一致対照', J8='追従8枚単独', J10='追従10枚単独',
                  R2='原本LPの現在可観測反発2枚単独', M82='追従8枚と原本LP反発2枚の同時運転')
    return result
