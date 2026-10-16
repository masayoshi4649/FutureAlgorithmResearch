"""短命な状態分類に依存する待機と、利益を失う出口を一軸ずつ比較する。"""

PRIMARY = 'P_G82_HUNL'
SYMBOLS = ('TOPIX', 'NK225')


def condition(ident: str, selection: str = 'fixed', trend: int = 8,
              reversal: int = 2, **changes: object) -> dict:
    """
    機能: 旧注文モデルを保持したまま、一つの比較条件を指定する。
    引数: ident/selection(str)、trend/reversal(int、TOPIX枚数)、changes(dict)。
    返り値: dict。NK225の数量はTOPIX指定の2倍。
    """
    result = dict(id=ident, selection=selection, trend_budget=trend,
                  range_budget=reversal, high_er=.4, low_er=.2, confirm_seconds=10.,
                  cancel_pending=False, exit_opposite_range=False, width_ticks=8,
                  trend_width_fraction=.004, trend_hold_seconds=1800.,
                  target_widths=3., stop_widths=1., improve_limit=True,
                  activate_anchor=False, persistent_arm=False, ungated_trend=False,
                  arm_direction_kind='common', range_width_mode='ticks',
                  range_width_fraction=.001, range_profit_mode='target',
                  profit_activate_widths=1., profit_trail_widths=.5,
                  reverse_kind='none', reverse_sources='none', reverse_confirm_seconds=10.)
    result.update(changes)
    assert selection in ('fixed', 'gated_fixed', 'regime')
    assert 0 <= trend <= 10 and 0 <= reversal <= 10
    assert selection == 'regime' or trend+reversal <= 10
    return result


def integrated(ident: str, selection: str = 'gated_fixed', **changes: object) -> dict:
    """
    機能: 待機保持・公平幅・利益保護・弱い撤退証拠の統合を指定する。
    引数: ident/selection(str)、changes(dict)。
    返り値: dict。全枠排他と固定8:2配分を混同しない。
    """
    values = dict(persistent_arm=True, ungated_trend=True, cancel_pending=True,
                  range_width_mode='opening_fraction', range_profit_mode='trail',
                  reverse_kind='common', reverse_sources='both')
    values.update(changes)
    return condition(ident, selection, 10 if selection == 'regime' else 8,
                     10 if selection == 'regime' else 2, **values)


def catalog() -> list[dict]:
    """
    機能: 六対照、単独部品、統合と部品除去の38条件を損益前に列挙する。
    引数: なし。
    返り値: list[dict]。結果を見て主又は条件を差替えない。
    """
    result = [condition(ident, trend=trend, reversal=reversal)
              for ident, trend, reversal in
              [('J10', 10, 0), ('J8', 8, 0), ('O10', 0, 10), ('O2', 0, 2), ('M82', 8, 2)]]
    result.append(condition('B_QA', 'regime', 10, 10, activate_anchor=True, cancel_pending=True))
    # ----------------------------------------
    # 価格逆行出口は既検証。両源へ広げる前にJ2単独との違いを別条件で確認する。
    for base, trend, reversal, sources in [('J8', 8, 0, 'trend'), ('M82', 8, 2, 'both')]:
        for seconds in (0., 10., 15.):
            result.append(condition(f'{base}_XC{int(seconds):02}', trend=trend, reversal=reversal,
                                    reverse_kind='common', reverse_sources=sources,
                                    reverse_confirm_seconds=seconds))
    for kind, suffix in [('quotes', 'XQ15'), ('either', 'XOR15')]:
        result.append(condition(f'M82_{suffix}', reverse_kind=kind, reverse_sources='both',
                                reverse_confirm_seconds=15.))
    for selection, prefix, trend, reversal in [('regime', 'A_D', 10, 10),
                                               ('gated_fixed', 'A_G82', 8, 2)]:
        for direction, suffix in [('common', ''), ('trend300', '_B300')]:
            result.append(condition(prefix+suffix, selection, trend, reversal,
                                    persistent_arm=True, cancel_pending=True,
                                    arm_direction_kind=direction))
    for fraction, suffix in [(.0005, 'F05'), (.001, 'F10'), (.0015, 'F15')]:
        result.append(condition(f'O10_{suffix}', trend=0, reversal=10,
                                range_width_mode='opening_fraction', range_width_fraction=fraction))
    result.append(condition('M82_F10', range_width_mode='opening_fraction'))
    # ----------------------------------------
    # 元J2の確認と、新たな高ER・共通条件の持続は別。往復の確認時間を変えない。
    result.append(condition('B_QA_T0', 'regime', 10, 10, activate_anchor=True,
                            cancel_pending=True, trend_mode_confirm_seconds=0.))
    result.append(condition('B_QA_TNONE', 'regime', 10, 10, activate_anchor=True,
                            cancel_pending=True, ungated_trend=True))
    result.append(condition('O10_TR', trend=0, reversal=10, range_profit_mode='trail'))
    result.append(condition('M82_TR', range_profit_mode='trail'))
    result += [integrated('P_G82'), integrated('P_D', 'regime'),
               integrated('P_G82_OMITX', reverse_kind='none', reverse_sources='none'),
               integrated('P_G82_OMITTRAIL', range_profit_mode='target'),
               integrated('P_G82_OMITF', range_width_mode='ticks'),
               integrated('P_G82_OMITARM', persistent_arm=False, activate_anchor=True),
               integrated('P_G82_B300', arm_direction_kind='trend300')]
    result += [condition('J8_HUNL', trend=8, reversal=0, trend_hold_seconds=1e30),
               condition('M82_HUNL', trend_hold_seconds=1e30),
               integrated('P_G82_HUNL', trend_hold_seconds=1e30),
               integrated('P_G82_XOR10', reverse_kind='either'),
               integrated('P_G82_XR', reverse_sources='range')]
    assert len(result) == len({c['id'] for c in result}) == 38
    assert PRIMARY in {c['id'] for c in result}
    return result
