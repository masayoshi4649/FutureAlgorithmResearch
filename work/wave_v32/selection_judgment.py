"""固定した目安と全対照を適用し、選択の追加価値と黒字候補を混同しない。"""

from __future__ import annotations

import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import selection_runner as runner


def minimum(symbols: dict) -> list[str]:
    """機能: 結果前に定めた共通7区間の最低目安へ照合する。

    引数: symbols (dict)。返り値: 未達理由 (list[str])。
    """
    reasons = []
    for symbol, row in symbols.items():
        checks = {'黒字なし': row['net_yen'] > 0,
                  '利益損失比1.10未確認': row['money_ratio'] is not None and row['money_ratio'] >= 1.1,
                  '平均1枚の勝ち負け比1.10未確認': row['average_unit_payoff'] is not None and row['average_unit_payoff'] >= 1.1,
                  '稼働4区間未満': row['active_sessions'] >= 4,
                  '最大1黒字区間除外で赤字': row['best_removed_net'] >= 0,
                  '最大1勝ち組除外で赤字': row['best_trade_removed_net'] >= 0}
        reasons += [symbol + '：' + name for name, value in checks.items() if not value]
    return reasons


def joint_score(candidate: dict) -> float:
    """機能: 円額を市場間で加算せず、弱い市場の収支／最大下落を示す。

    引数: candidate (dict)。返り値: 比較用値 (float)。採用や正式p値には使わない。
    """
    return min(row['net_yen'] / max(1., row['drawdown_yen']) for row in candidate['symbols'].values())


def judge(candidates: list[dict]) -> dict:
    """機能: 全148の反証と、主A/Bだけの固定判定を保存用にまとめる。

    引数: candidates (list[dict])。返り値: 判定と全対照 (dict)。
    """
    fixed = runner.read(HERE / '探索条件の固定.json')
    by_id = {row['id']: row for row in candidates}
    assert set(by_id) == {row['id'] for row in fixed['conditions']}
    base = by_id['S000']['symbols']
    comparisons, primary = [], []
    for candidate in candidates:
        identifier, spec = candidate['id'], candidate['spec']
        original = by_id[spec['base_selector']]['symbols']
        differences = {symbol: {name: row[name] - original[symbol][name]
                                for name in ('net_yen', 'drawdown_yen', 'closed_units', 'opening_orders',
                                             'long_unit_minutes', 'short_unit_minutes')}
                       for symbol, row in candidate['symbols'].items()}
        reasons = minimum(candidate['symbols'])
        engineering = [symbol for symbol, row in candidate['symbols'].items()
                       if not (row['net_yen'] >= .75 * base[symbol]['net_yen'] and row['drawdown_yen'] <= .8 * base[symbol]['drawdown_yen'])]
        comparisons.append({'id': identifier, 'primary_id': spec['base_selector'], 'variation': spec['variation'],
                            '最低目安未達': reasons, 'T比の工学目標未達銘柄': engineering, '主との差': differences})
        if identifier not in ('S002', 'S003'):
            continue
        inactive = []
        for symbol, row in candidate['symbols'].items():
            selected = row['selection']
            if any(selected['branch_opening_orders'][branch] == 0 for branch in ('T', 'R')):
                inactive.append(symbol + '：両枝の新規が揃わない')
            count = selected['within_session_applied_switches']
            if identifier == 'S003':
                count += selected['between_session_applied_switches']
            if count == 0:
                inactive.append(symbol + '：実適用の切替なし')
        dominated, identical = [], []
        for other_id in ('S001', 'S004', 'S005'):
            weak, strict = True, False
            for symbol, row in candidate['symbols'].items():
                other = by_id[other_id]['symbols'][symbol]
                weak &= other['net_yen'] >= row['net_yen'] and other['drawdown_yen'] <= row['drawdown_yen']
                strict |= other['net_yen'] > row['net_yen'] or other['drawdown_yen'] < row['drawdown_yen']
            if weak:
                (dominated if strict else identical).append(other_id)
        main_score = joint_score(candidate)
        randoms = [c for c in candidates if c['spec']['base_selector'] == identifier and c['spec']['variation'] == 'random_request']
        assert len(randoms) == 64
        random_scores = [joint_score(c) for c in randoms]
        primary.append({'id': identifier, '最低目安未達': reasons, 'T比の工学目標未達銘柄': engineering,
                        '選択の稼働不足': inactive, '両市場で支配する対照': dominated, '4値が同一の対照': identical,
                        '一次目安と追加価値の条件を充足': not (reasons or engineering or inactive or dominated or identical),
                        '乱数対照': {'指標': '両銘柄の収支÷含み込み最大下落の小さい方。下落0の分母は1円。',
                                     '主の値': main_score, '対照数': 64,
                                     '主以上の対照数': sum(value >= main_score for value in random_scores),
                                     '主より大きい対照数': sum(value > main_score for value in random_scores),
                                     '対照の最小': min(random_scores), '対照の最大': max(random_scores),
                                     '正式p値ではない': True, '最良seed採用': False}})
    return {'対象': '既知13区間中、共通の後半7区間。未知検証ではない。', '全条件数': 148,
            '主判定': primary, '全対応比較': comparisons,
            '反証の合格率で新しい閾値を設けたか': False,
            '解釈': '選択追加の目安と黒字の有無は別。工学目標未達は全アルゴリズム無効の意味ではない。'
                    '対照に劣る場合も予測不可能の証明とはせず、この比較の追加価値未確認とする。',
            '現在データ使用': False, 'API取得数': 0}


def main() -> None:
    """機能: 全保存結果へ固定判定を適用し、最良反証への差替を行わない。

    引数: なし。返り値: なし (None)。
    """
    candidates = runner.read(HERE / '全条件の期間集計.json.gz')
    result = judge(candidates)
    runner.save(HERE / '選択の判定.json', result)
    print(json.dumps({'全条件数': 148, '主判定': result['主判定']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
