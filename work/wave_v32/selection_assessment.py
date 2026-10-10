"""固定した一次目安・工学目標・実切替を個別判定し、反証を候補へ昇格しない。"""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path

import selector_design as design

HERE = Path(__file__).resolve().parent
SYMBOLS = ('TOPIX', 'NK225')
CONTROLS = ('S001', 'S004', 'S005')


def relation(candidate: dict, control: dict) -> str:
    """機能: 両市場の収支とDDの4値だけで支配・同等・非支配を判定する。

    引数: candidate/control (dict[str,dict])。返り値: 判定名 (str)。
    """
    pairs = [(control[s]['net_yen'], candidate[s]['net_yen']) for s in SYMBOLS]
    pairs += [(-control[s]['drawdown_yen'], -candidate[s]['drawdown_yen']) for s in SYMBOLS]
    assert all(math.isfinite(v) for pair in pairs for v in pair)
    if all(a == b for a, b in pairs):
        return '全4値同等'
    if all(a >= b for a, b in pairs) and any(a > b for a, b in pairs):
        return '対照がPareto支配'
    return '支配なし'


def symbol_checks(values: dict, reference: dict, rows: list[dict], kind: str) -> dict:
    """機能: 一銘柄の主評価7区間を同じ固定閾値で判定する。

    引数: values/reference (dict)、rows (list[dict])、kind (str)。
    返り値: 一次・工学・活動と除外収支 (dict)。
    """
    assert len(rows) == 7 and len({r['session'] for r in rows}) == 7
    net = values['net_yen']
    assert math.isfinite(net) and math.isfinite(values['drawdown_yen']) and values['drawdown_yen'] >= 0
    largest_cycle = max([0.] + [v for row in rows for v in row['two_largest_cycle_profits'] if v > 0])
    largest_session = max([0.] + [row['net_yen'] for row in rows])
    active = sum(row['opening_orders'] > 0 for row in rows)
    assert active == values['active_sessions']
    primary = {'黒字': net > 0, 'PF1.10以上': values['money_ratio'] is not None and values['money_ratio'] >= 1.1,
               '1枚平均利益損失比1.10以上': values['average_unit_payoff'] is not None and values['average_unit_payoff'] >= 1.1,
               '4区間以上稼働': active >= 4,
               '最大1勝ち組除外後非負': net - largest_cycle >= 0,
               '最大1黒字区間除外後非負': net - largest_session >= 0}
    engineering = {'T収支75%以上': net >= .75 * reference['net_yen'],
                   'T最大下落80%以下': values['drawdown_yen'] <= .8 * reference['drawdown_yen']}
    selection = values['selection']
    branch = selection['branch_opening_orders']
    switches = selection['within_session_applied_switches']
    if kind == 'B':
        switches += selection['between_session_applied_switches']
    activity = {'T枝新規あり': branch['T'] > 0, 'R枝新規あり': branch['R'] > 0, '実適用切替あり': switches > 0}
    return {'一次目安': primary, '一次目安通過': all(primary.values()),
            '工学目標': engineering, '工学目標通過': all(engineering.values()),
            '選択実稼働': activity, '選択実稼働確認': all(activity.values()),
            '実適用切替数': switches, '両枝新規数': deepcopy(branch),
            '最大1勝ち組円': largest_cycle, '最大1黒字セッション円': largest_session,
            '最大1勝ち組除外後収支円': net - largest_cycle,
            '最大1黒字セッション除外後収支円': net - largest_session}


def assess(summaries: list[dict], details: dict, fixed: dict) -> dict:
    """機能: 主6と反証142を全件判定し、A/B主だけの候補と留保を保存可能にする。

    引数: summaries (list[dict])、details/fixed (dict)。
    返り値: 順位選抜をしない全件判定結果 (dict)。売買再生を行わない。
    """
    expected = {s['id']: s for s in design.catalog()}
    values = {r['id']: r for r in summaries}
    assert len(summaries) == len(values) == 148 and set(values) == set(details) == set(expected)
    periods = fixed['主評価7'] if '主評価7' in fixed else fixed['共通評価7セッション']
    assert len(periods) == 7 and len(set(periods)) == 7
    baseline = values['S000']['symbols']
    results = []
    for name in sorted(values):
        summary, spec = values[name], expected[name]
        assert summary['spec'] == spec
        rows = details[name]
        assert len(rows) == 26 and len({(r['session'], r['symbol']) for r in rows}) == 26
        symbols = {symbol: symbol_checks(summary['symbols'][symbol], baseline[symbol],
                                         [r for r in rows if r['session'] in periods and r['symbol'] == symbol],
                                         spec['selector_kind']) for symbol in SYMBOLS}
        primary = all(r['一次目安通過'] for r in symbols.values())
        engineering = all(r['工学目標通過'] for r in symbols.values())
        activity = all(r['選択実稼働確認'] for r in symbols.values())
        comparisons = {control: relation(summary['symbols'], values[control]['symbols']) for control in CONTROLS}
        dominated = any(value != '支配なし' for value in comparisons.values())
        main_selector = name in ('S002', 'S003')
        qualified = main_selector and primary and engineering and activity and not dominated
        results.append({'id': name, 'role': spec['role'], 'base_selector': spec['base_selector'],
                        '銘柄別': symbols, '一次目安通過': primary, 'Tへの工学目標通過': engineering,
                        '選択実稼働確認': activity, '固定対照との関係': comparisons,
                        '比較上の追加価値未確認': dominated,
                        '主方式の目安合格': qualified, '候補への昇格対象': main_selector})
    indexed = {r['id']: r for r in results}
    for name in ('S002', 'S003'):
        adversarial = [row for row in results if row['role'] == 'adversarial' and row['base_selector'] == name]
        indexed[name]['反証全件'] = [r['id'] for r in adversarial]
        indexed[name]['一次目安が維持されない反証'] = [r['id'] for r in adversarial if not r['一次目安通過']]
        indexed[name]['工学目標が維持されない反証'] = [r['id'] for r in adversarial if not r['Tへの工学目標通過']]
        indexed[name]['表現'] = ('主の目安合格。全反証の留保と併記し未知利益の確証とはしない。'
                               if indexed[name]['主方式の目安合格'] else '今回の選択追加の目安未達。固定手法や全アルゴリズムの無価値を意味しない。')
    return {'全件判定完了': True, '全条件数': 148, '主比較数': 6, '反証数': 142,
            '主評価7': periods, '結果': results,
            '主の目安合格ID': [name for name in ('S002', 'S003') if indexed[name]['主方式の目安合格']],
            '順位選抜': False, '反証最良の昇格': False,
            '反証留保': '全件差と同じ目安の維持を提示する。乱数順位は正式p値ではなく、追加の合格率閾値は設けない。',
            'Bの取消対照比較': 'A取消対照に支配されても追加価値未確認まで。B予測力の不存在証明とは呼ばない。'}


def freeze() -> dict:
    """機能: 判定実装を事前仕様へ結合し、売買前に固定する。

    引数: なし。返り値: 実装固定記録 (dict)。
    """
    fixed = {'実装SHA256': design.digest(Path(__file__)),
             '事前規則SHA256': design.digest(HERE / 'selection_fixed.json'),
             '候補対象': ['S002', 'S003'], '新閾値追加': False,
             'Aの実切替': '主評価中の適用変更イベント。毎セッションTへの初期化だけは含めない。',
             'Bの実切替': '場初の適用変更行と、第6終了→第7開始も含む主評価セッション開始での前適用IDからの変更。'}
    path = HERE / 'selection_assessment_fixed.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8')) == fixed
    else:
        path.write_text(json.dumps(fixed, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return fixed


if __name__ == '__main__':
    freeze()
    print('全148の同じ尺度・主A/Bだけの個別判定を固定。損益再生なし。', flush=True)
