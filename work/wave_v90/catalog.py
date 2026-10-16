"""異なる二戦略の同時配分と現在状態による選択を、損益を見る前に列挙する。"""

PRIMARY = 'D_C'
SYMBOLS = ('TOPIX', 'NK225')


def condition(ident: str, selection: str, trend: int, reversal: int,
              cancel: bool = False, exit_opposite: bool = False,
              **changes: object) -> dict:
    """
    機能: 同一の注文幅・数量尺度による一つの比較条件を作る。
    引数: ident/selection(str)、trend/reversal(int、TOPIX枚数)、
        cancel/exit_opposite(bool)、changes(dictの追加指定)。
    返り値: dict。NK225の枠はTOPIX指定の2倍で使用する。
    """
    result = dict(id=ident, selection=selection, trend_budget=trend,
                  range_budget=reversal, high_er=.4, low_er=.2,
                  confirm_seconds=10., cancel_pending=cancel,
                  exit_opposite_range=exit_opposite, width_ticks=8,
                  trend_width_fraction=.004, trend_hold_seconds=1800.,
                  target_widths=3., stop_widths=1.)
    result.update(changes)
    assert 0 <= trend <= 10 and 0 <= reversal <= 10
    assert selection in ('fixed', 'gated_fixed', 'regime')
    assert selection == 'regime' or trend + reversal <= 10
    assert 0 <= result['low_er'] < result['high_er'] <= 1
    return result


def catalog() -> list[dict]:
    """
    機能: 理論指定の主、単独、固定併用、状態選択、取消と撤回の27条件を返す。
    引数: なし。
    返り値: list[dict]。結果に応じて条件又は主を追加・差替えしない。
    """
    output = [condition(ident, 'fixed', trend, reversal)
              for ident, trend, reversal in
              [('J10', 10, 0), ('O10', 0, 10), ('J8', 8, 0),
               ('O2', 0, 2), ('M82', 8, 2), ('M64', 6, 4), ('M55', 5, 5)]]
    # ----------------------------------------
    # 排他的な全枠選択と、源別の固定枠を維持する選択を別に比較する。
    for prefix, selection, trend, reversal in [
            ('D', 'regime', 10, 10), ('G82', 'gated_fixed', 8, 2)]:
        for suffix, cancel, exit_opposite in [
                ('E', False, False), ('C', True, False), ('X', True, True)]:
            output.append(condition(f'{prefix}_{suffix}', selection, trend,
                                    reversal, cancel, exit_opposite))
        for suffix, changes in [('H30', dict(high_er=.3)),
                                ('H50', dict(high_er=.5)),
                                ('L10', dict(low_er=.1)),
                                ('L30', dict(low_er=.3)),
                                ('S00', dict(confirm_seconds=0.)),
                                ('S15', dict(confirm_seconds=15.))]:
            output.append(condition(f'{prefix}_C_{suffix}', selection, trend,
                                    reversal, True, False, **changes))
    output.append(condition('J_HIGH', 'gated_fixed', 10, 0))
    output.append(condition('O_LOW', 'gated_fixed', 0, 10, True))
    assert len(output) == 27
    assert len({c['id'] for c in output}) == 27
    assert PRIMARY in {c['id'] for c in output}
    return output
