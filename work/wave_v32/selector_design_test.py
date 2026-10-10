"""148条件の範囲と、数値境界の固定判定を人工値だけで確認する。"""

from copy import deepcopy
import json
import math
from pathlib import Path

import selector_design as design
import selection_assessment as assessment

HERE = Path(__file__).resolve().parent


def main() -> None:
    """機能: 全ID・単軸変形・境界値・同等/支配を損益参照なしで検査する。

    引数: なし。返り値: なし (None)。
    """
    catalog = design.catalog()
    index = {row['id']: row for row in catalog}
    assert len(index) == len(catalog) == 148
    primary = [row['id'] for row in catalog if row['role'] == 'primary']
    assert primary == [f'S{i:03}' for i in range(6)]
    expected_counts = {'er_window': 2, 'history_window': 2, 'score_gap': 2, 'lag': 6, 'observed': 2, 'random_request': 128}
    assert {key: sum(r['variation'] == key for r in catalog) for key in expected_counts} == expected_counts
    changed_field = {'er_window': 'er_window', 'history_window': 'history_window', 'score_gap': 'score_gap',
                     'lag': 'delay_seconds', 'observed': 'fill_model', 'random_request': 'random_seed'}
    for row in catalog:
        if row['role'] == 'primary':
            continue
        base = index[row['base_selector']]
        changed = {key for key in row if row[key] != base[key]}
        assert changed == {'id', 'name', 'role', 'variation', changed_field[row['variation']]}
    for base in ('S002', 'S003'):
        seeds = [r['random_seed'] for r in catalog if r['base_selector'] == base and r['variation'] == 'random_request']
        assert sorted(seeds) == list(range(64))
    sample = {'net_yen': 100., 'money_ratio': 1.1, 'average_unit_payoff': 1.1, 'active_sessions': 7,
              'drawdown_yen': 20., 'selection': {'branch_opening_orders': {'T': 3, 'R': 4},
                                              'within_session_applied_switches': 1, 'between_session_applied_switches': 0}}
    reference = {'net_yen': 100., 'drawdown_yen': 25.}
    rows = [{'session': str(i), 'net_yen': 100. / 7, 'opening_orders': 1, 'two_largest_cycle_profits': [100.]} for i in range(7)]
    base = assessment.symbol_checks(sample, reference, rows, 'A')
    assert base['一次目安通過'] and base['工学目標通過'] and base['選択実稼働確認']
    tested = []
    for key, value, criterion in (
        ('net_yen', 0., '黒字'), ('money_ratio', None, 'PF1.10以上'),
        ('money_ratio', math.nextafter(1.1, -math.inf), 'PF1.10以上'),
        ('average_unit_payoff', None, '1枚平均利益損失比1.10以上')):
        item = deepcopy(sample)
        item[key] = value
        assert not assessment.symbol_checks(item, reference, rows, 'A')['一次目安'][criterion]
        tested.append(criterion + '境界拒否')
    item = deepcopy(sample)
    item['drawdown_yen'] = math.nextafter(20., math.inf)
    assert not assessment.symbol_checks(item, reference, rows, 'A')['工学目標通過']
    tested.append('DD80%超の最小浮動差も拒否')
    item = deepcopy(sample)
    item['selection']['within_session_applied_switches'] = 0
    item['selection']['between_session_applied_switches'] = 1
    assert not assessment.symbol_checks(item, reference, rows, 'A')['選択実稼働確認']
    assert assessment.symbol_checks(item, reference, rows, 'B')['選択実稼働確認']
    tested.append('A初期化とB場間切替の区別')
    large = deepcopy(rows)
    large[0]['two_largest_cycle_profits'] = [101.]
    assert not assessment.symbol_checks(sample, reference, large, 'A')['一次目安']['最大1勝ち組除外後非負']
    tested.append('部分返済でなく組利益を除外')
    pair = {s: {'net_yen': 100., 'drawdown_yen': 20.} for s in assessment.SYMBOLS}
    assert assessment.relation(pair, pair) == '全4値同等'
    better = deepcopy(pair)
    better['TOPIX']['net_yen'] += 1
    assert assessment.relation(pair, better) == '対照がPareto支配'
    better['NK225']['drawdown_yen'] += 1
    assert assessment.relation(pair, better) == '支配なし'
    result = {'合成全合格': True, '全条件数': 148, '主6と単独反証142': True, '要求乱数全128一意': True,
              '境界検査': tested, '4値同等とPareto支配を区別': True, '新損益参照': False, '売買再生実行': False,
              '設計実装SHA256': design.digest(HERE / 'selector_design.py'),
              '独立判定実装SHA256': design.digest(HERE / 'selection_assessment.py')}
    (HERE / 'selector_design_test.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
