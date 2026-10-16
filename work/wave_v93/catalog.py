"""予定停止距離・中心利確・構造失敗後の再参加を16対照で固定する。"""

from copy import deepcopy
import importlib.util
from pathlib import Path

SYMBOLS = ('TOPIX', 'NK225')
PRIMARY = 'C11'
OLD = Path(__file__).resolve().parent.parent / 'wave_v92'
spec = importlib.util.spec_from_file_location('旧回復条件92の読取93', OLD / 'catalog.py')
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
BASES = {value['id']: value for value in previous.catalog()}


def condition(ident: str, base: str = 'R_B25_C', **changes: object) -> dict:
    """
    機能: 旧実績のある対照に、初期無効の追加部品を明示的に付ける。
    引数: ident(str)、base(str)、changes(dict[str,object])。
    返り値: dict。TOPIX指定数量を基に日経は2倍で実行する条件。
    """
    config = deepcopy(BASES[base])
    config.update(id=ident, range_entry_max_risk_widths=0.,
                  range_entry_min_center_ratio=0., range_target_kind='widths',
                  range_center_target_offset=0., range_failure_reentry_kind='legacy',
                  failure_center_fraction=.25)
    config.update(changes)
    return config


def clone(ident: str, source: dict, **changes: object) -> dict:
    """
    機能: 一つの対照から変更軸だけを替え、暗黙の条件差を避ける。
    引数: ident(str)、source(dict)、changes(dict[str,object])。
    返り値: dict。独立した条件の複製。
    """
    config = deepcopy(source)
    config.update(id=ident, **changes)
    return config


def catalog() -> list[dict]:
    """
    機能: 基本12対照と独立配分4対照を、損益のない仕様として返す。
    引数: なし。
    返り値: list[dict]。主は結果を見る前にC11へ固定する。
    """
    c00 = condition('C00')
    c01 = condition('C01', base='R_B25_C_ESTOP')
    c02 = clone('C02', c01, range_stop_kind='width_or_witness')
    c03 = clone('C03', c01, range_entry_max_risk_widths=.5)
    c04 = clone('C04', c01, range_entry_max_risk_widths=1.)
    c05 = clone('C05', c02, range_entry_min_center_ratio=2.)
    c06 = clone('C06', c05, range_target_kind='center')
    c07 = clone('C07', c05, range_target_kind='center_plus', range_center_target_offset=.5)
    c08 = clone('C08', c02, range_failure_reentry_kind='return_self')
    c09 = clone('C09', c02, range_failure_reentry_kind='return_both')
    c10 = clone('C10', c02, range_failure_reentry_kind='prepare_reset')
    c11 = clone('C11', c06, range_failure_reentry_kind='return_both')
    s00 = condition('S00', base='J8')
    s01 = condition('S01', base='J10')
    s02 = clone('S02', c11, range_budget=2)
    s03 = clone('S03', s02, trend_budget=8, ungated_trend=True)
    values = [c00, c01, c02, c03, c04, c05, c06, c07, c08, c09, c10, c11, s00, s01, s02, s03]
    assert len(values) == 16 and len({value['id'] for value in values}) == 16
    assert all(value['trend_budget'] + value['range_budget'] <= 10 for value in values)
    return values


def references(ident: str) -> list[str]:
    """
    機能: 各変更を評価するための因果対照と数量対照を定義する。
    引数: ident(str)。条件ID。
    返り値: list[str]。S03は追加と置換と源単独を別々に比較する。
    """
    mapping = dict(C00=[], C01=['C00'], C02=['C01', 'C00'], C03=['C01'], C04=['C01'],
                   C05=['C02'], C06=['C05'], C07=['C05', 'C06'], C08=['C02'], C09=['C02'],
                   C10=['C02'], C11=['C06', 'C09', 'C00'], S00=[], S01=['S00'],
                   S02=['C11'], S03=['S00', 'S01', 'S02'])
    return mapping[ident]


def labels() -> dict[str, str]:
    """
    機能: 条件IDを簡単な日本語で識別できるようにする。
    引数: なし。
    返り値: dict[str,str]。説明用の手法名。
    """
    return dict(C00='回復確認・固定幅停止の旧対照', C01='回復確認・極値停止の旧対照',
                C02='固定幅又は極値で停止', C03='停止距離0.5幅以内で新規',
                C04='停止距離1幅以内で新規', C05='中心利益と停止損失の予定比2以上で新規',
                C06='予定比確認・中心で返済', C07='予定比確認・中心の0.5幅先で返済',
                C08='極値失敗後は自己中心帰還を待つ', C09='極値失敗後は双方中心帰還を待つ',
                C10='極値失敗後は全窓更新と新準備を待つ', C11='予定比・中心利確・双方帰還を統合',
                S00='追従8枚単独', S01='追従10枚単独', S02='統合反発2枚単独',
                S03='追従8枚と統合反発2枚の同時運転')
