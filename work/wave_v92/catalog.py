"""回復を確認する入口と、利確後の中心帰還を少数の独立軸で比較する。"""

import importlib.util
from pathlib import Path

SYMBOLS = ('TOPIX', 'NK225')
PRIMARY = 'R_B25_C_ESTOP'
OLD = Path(__file__).resolve().parent.parent / 'wave_v91'
spec = importlib.util.spec_from_file_location('既存条件91の読取92', OLD / 'catalog.py')
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)


def condition(ident: str, **changes: object) -> dict:
    """
    機能: 旧固定配分と注文模型を残し、新しい部品を初期状態では無効にする。
    引数: ident(str)、changes(dict、事前に指定する条件差)。
    返り値: dict。数量はTOPIX指定で、NK225は各2倍。
    """
    config = previous.condition(ident)
    config.update(range_entry_kind='limit', recovery_confirmation='none',
                  recovery_fraction=.25, watch_clear_common='any',
                  range_stop_kind='width', range_reentry_kind='legacy',
                  center_fraction=.25, center_after='profit', center_release=False)
    config.update(changes)
    return config


def recovery(ident: str, **changes: object) -> dict:
    """
    機能: 低ERで準備した逸脱に対し、確認後の次有効気配成行を指定する。
    引数: ident(str)、changes(dict)。
    返り値: dict。元指値との取得価格差を、回復確認の効果へ混ぜない。
    """
    values = dict(selection='gated_fixed', trend_budget=0, range_budget=10,
                  persistent_arm=True, cancel_pending=True,
                  range_width_mode='opening_fraction', range_entry_kind='recovery_market')
    values.update(changes)
    return condition(ident, **values)


def center(ident: str, **changes: object) -> dict:
    """
    機能: 初回入口と出口を変えず、黒字全返済後の再参加だけを変更する。
    引数: ident(str)、changes(dict)。
    返り値: dict。初回の中心は従来通りLastPrice、反発幅は始値割合。
    """
    values = dict(trend_budget=0, range_budget=10, range_width_mode='opening_fraction',
                  range_profit_mode='trail', range_reentry_kind='keep')
    values.update(changes)
    return condition(ident, **values)


def catalog() -> list[dict]:
    """
    機能: 8対照、回復10、出口1、極値停止2、中心8、統合2、配分2、幅3の36条件を固定する。
    引数: なし。
    返り値: list[dict]。入口・停止・再参加を一軸比較し、主を結果で差替えない。
    """
    result = [condition(ident, trend_budget=trend, range_budget=reversal)
              for ident, trend, reversal in
              [('J10', 10, 0), ('J8', 8, 0), ('O10', 0, 10), ('O2', 0, 2), ('M82', 8, 2)]]
    result += [condition('O10_TR', trend_budget=0, range_budget=10, range_profit_mode='trail'),
               condition('A_O', selection='gated_fixed', trend_budget=0, range_budget=10,
                         persistent_arm=True, cancel_pending=True, range_width_mode='opening_fraction'),
               center('O10_F10_TR', range_reentry_kind='legacy')]
    # ----------------------------------------
    # 同執行の確認なし、自己回復、双方回復を先に比較し、解除条件の差を別列へ置く。
    result.append(recovery('R0'))
    result.append(recovery('R0_C', watch_clear_common='adverse'))
    for confirmation, prefix in [('self', 'S'), ('both', 'B')]:
        for fraction, suffix in [(.25, '25'), (.5, '50')]:
            result.append(recovery(f'R_{prefix}{suffix}', recovery_confirmation=confirmation,
                                   recovery_fraction=fraction))
    for confirmation, prefix in [('self', 'S'), ('both', 'B')]:
        for fraction, suffix in [(.25, '25'), (.5, '50')]:
            result.append(recovery(f'R_{prefix}{suffix}_C', recovery_confirmation=confirmation,
                                   recovery_fraction=fraction, watch_clear_common='adverse'))
    for confirmation, prefix in [('self', 'S'), ('both', 'B')]:
        result.append(recovery(f'R_{prefix}25_C_ESTOP', recovery_confirmation=confirmation,
                               watch_clear_common='adverse', range_stop_kind='witness_extreme'))
    result.append(recovery('R_B25_C_TR', recovery_confirmation='both',
                           watch_clear_common='adverse', range_profit_mode='trail'))
    # ----------------------------------------
    # 利確後の中心保持と帰還条件を分け、損切り後の経路は黒字限定の列で維持する。
    result.append(center('K0'))
    for kind, prefix in [('return_self', 'S'), ('return_both', 'B')]:
        for fraction, suffix in [(.25, '25'), (.5, '50')]:
            result.append(center(f'K{prefix}{suffix}', range_reentry_kind=kind,
                                 center_fraction=fraction))
    result.append(center('KS25_ALL', range_reentry_kind='return_self', center_after='all'))
    for kind, prefix in [('return_self', 'S'), ('return_both', 'B')]:
        result.append(center(f'K{prefix}25_REL', range_reentry_kind=kind, center_release=True))
    for kind, prefix in [('return_self', 'S'), ('return_both', 'B')]:
        result.append(recovery(f'I_B25_C_K{prefix}25', recovery_confirmation='both',
                               watch_clear_common='adverse', range_profit_mode='trail',
                               range_reentry_kind=kind))
    result += [recovery('M_RB25_C', trend_budget=8, range_budget=2, ungated_trend=True,
                        recovery_confirmation='both', watch_clear_common='adverse'),
               center('M_KS25', trend_budget=8, range_budget=2, range_reentry_kind='return_self')]
    result += [center('O10_F15_TR', range_reentry_kind='legacy', range_width_fraction=.0015),
               recovery('R_B25_C_W15', recovery_confirmation='both', watch_clear_common='adverse',
                        range_width_fraction=.0015),
               center('KS25_W15', range_reentry_kind='return_self', range_width_fraction=.0015)]
    assert len(result) == len({item['id'] for item in result}) == 36
    assert PRIMARY in {item['id'] for item in result}
    for config in result:
        assert config['trend_budget'] + config['range_budget'] <= 10
    return result
