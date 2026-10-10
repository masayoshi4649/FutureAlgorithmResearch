"""仮想準備による参加制御を旧固定方式と通常動的方式へ別々に比較する。"""

from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path

import scheduler_design as design

HERE = Path(__file__).resolve().parent
SYMBOLS = ('TOPIX', 'NK225')
PERIODS = ('all_symbols', 'symbols')
EPS = 1e-6


def relation(candidate: dict, reference: dict) -> str:
    """機能: 両期間×両銘柄の収支と最大下落の関係を分類する。

    引数: candidate/reference (dict)。返り値: 関係 (str)。額は合算しない。
    """
    nets = [candidate[p][s]['net_yen'] - reference[p][s]['net_yen'] for p in PERIODS for s in SYMBOLS]
    dds = [candidate[p][s]['drawdown_yen'] - reference[p][s]['drawdown_yen'] for p in PERIODS for s in SYMBOLS]
    assert all(math.isfinite(v) for v in nets + dds)
    assert all(value[p][s]['drawdown_yen'] >= 0 for value in (candidate, reference) for p in PERIODS for s in SYMBOLS)
    if all(abs(v) <= EPS for v in nets + dds):
        return '同値'
    if all(v >= -EPS for v in nets) and all(v <= EPS for v in dds):
        return '同時改善'
    if all(v <= EPS for v in nets) and all(v >= -EPS for v in dds):
        return '旧案が支配'
    if all(v <= EPS for v in dds) and any(v < -EPS for v in dds) and any(v < -EPS for v in nets):
        return 'リスク収益交換'
    if all(v >= -EPS for v in nets) and any(v > EPS for v in nets) and any(v > EPS for v in dds):
        return '収益リスク交換'
    return '混在'


def basic_checks(values: dict, rows: list[dict], primary: bool) -> dict:
    """機能: 候補基礎と最大勝ち除外を全玉で確認する。

    引数: values (dict)、rows (list[dict])、primary (bool) は後半7か。
    返り値: 各検査と除外収支 (dict)。
    """
    assert len(rows) == (7 if primary else 13) and len({r['session'] for r in rows}) == len(rows)
    net = values['net_yen']
    assert math.isfinite(net) and math.isfinite(values['gross_profit_yen']) and math.isfinite(values['gross_loss_yen'])
    ratio = values['gross_profit_yen'] / values['gross_loss_yen'] if values['gross_loss_yen'] > 0 else None
    payoff = ((values['gross_profit_yen'] / values['profit_units']) / (values['gross_loss_yen'] / values['loss_units'])
              if values['profit_units'] > 0 and values['loss_units'] > 0 and values['gross_loss_yen'] > 0 else None)
    for actual, expected in ((values['money_ratio'], ratio), (values['average_unit_payoff'], payoff)):
        assert (actual is None and expected is None) or (actual is not None and expected is not None and math.isclose(actual, expected, abs_tol=1e-10, rel_tol=1e-10))
    best_cycle = max([0.] + [r['final_yen'] for row in rows for r in row['retracements']])
    best_session = max([0.] + [r['net_yen'] for r in rows])
    active = sum(r['opening_orders'] > 0 for r in rows)
    assert active == values['active_sessions']
    checks = {'黒字': net > EPS, '総利益損失比1超': ratio is not None and ratio > 1.,
              '勝ち負け1枚平均比1超': payoff is not None and payoff > 1.}
    if primary:
        checks.update({'4区間以上稼働': active >= 4, '最大1勝ち組除外後非負': net - best_cycle >= -EPS,
                       '最大1黒字区間除外後非負': net - best_session >= -EPS})
    return {'検査': checks, '基礎確認': all(checks.values()), '最大1勝ち組円': best_cycle,
            '最大1黒字セッション円': best_session, '最大1勝ち組除外後収支円': net - best_cycle,
            '最大1黒字セッション除外後収支円': net - best_session, '稼働区間数': active}


def wave_comparison(candidate: list[dict], reference: list[dict]) -> dict:
    """機能: 正方向保有時間と20分目安の喪失を8区間全てで比較する。

    引数: candidate/reference (list[dict])。返り値: 波維持と全差 (dict)。
    """
    definitions = {r['id']: r for r in design.waves()}
    expected = {(name, s) for name in definitions for s in SYMBOLS}
    indexes = []
    for rows in (candidate, reference):
        index = {(r['wave'], r['symbol']): r for r in rows}
        assert len(rows) == len(index) == 8 and set(index) == expected
        for (name, symbol), row in index.items():
            wave = definitions[name]
            assert (row['session'], row['開始'], row['終了'], row['波方向']) == (wave['session'], wave['start'], wave['end'], wave['side'])
            assert math.isfinite(row['正方向ネット保有分']) and row['正方向ネット保有分'] >= 0
            assert row['正方向ネット20分目安達成'] == (row['正方向ネット保有分'] >= 20.)
        indexes.append(index)
    rows = []
    for key in sorted(expected):
        changed, original = indexes[0][key], indexes[1][key]
        rows.append({'wave': key[0], 'symbol': key[1], '旧保有分': original['正方向ネット保有分'],
                     '変更保有分': changed['正方向ネット保有分'],
                     '正方向保有差分': changed['正方向ネット保有分'] - original['正方向ネット保有分'],
                     '旧目安達成': original['正方向ネット20分目安達成'], '変更目安達成': changed['正方向ネット20分目安達成'],
                     '目安喪失': original['正方向ネット20分目安達成'] and not changed['正方向ネット20分目安達成']})
    return {'旧達成数': sum(r['旧目安達成'] for r in rows), '変更達成数': sum(r['変更目安達成'] for r in rows),
            '波維持': not any(r['目安喪失'] for r in rows), '全区間': rows,
            '位置付け': '初期6内の目的診断。共通後半7の未見証拠ではない。'}


# ----------------------------------------
def differences(candidate: dict, reference: dict) -> dict:
    """機能: 金額・枚数・返却・参加量を期間と銘柄別に比較する。

    引数: candidate/reference (dict)。返り値: 全4セルの対応差 (dict)。
    """
    result = {}
    numeric = ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'drawdown_yen',
        'profit_units', 'loss_units', 'zero_units', 'cycles', 'opening_orders',
        'long_unit_minutes', 'short_unit_minutes')
    for period in PERIODS:
        result[period] = {}
        for symbol in SYMBOLS:
            new, old = candidate[period][symbol], reference[period][symbol]
            row = {field: {'旧': old[field], '変更': new[field], '差': new[field] - old[field]} for field in numeric}
            row['比率'] = {field: {'旧': old[field], '変更': new[field]}
                           for field in ('money_ratio', 'average_unit_payoff')}
            row['組ピーク悪化'] = {'旧': old['retracement'], '変更': new['retracement']}
            if 'gate' in new or 'gate' in old:
                assert 'gate' in new and 'gate' in old
                assert set(new['gate']) == set(old['gate'])
                row['仮想参加'] = {field: {'旧': old['gate'][field], '変更': new['gate'][field],
                                         '差': new['gate'][field] - old['gate'][field]} for field in new['gate']}
            result[period][symbol] = row
    return result


def compare(candidate: dict, reference: dict, waves: dict) -> dict:
    """機能: 一つの比較対象に対する収支・下落・波の変化をまとめる。

    引数: candidate/reference/waves (dict)。返り値: 比較記録 (dict)。
    """
    return {'reference_id': reference['id'], '収支DD関係': relation(candidate, reference),
            '指定波': wave_comparison(waves[candidate['id']], waves[reference['id']]),
            '期間銘柄差': differences(candidate, reference)}


def assess(summaries: list[dict], details: dict, waves: dict) -> dict:
    """機能: 全192を確認して二つの基準との効果を分け、主1件だけを判定する。

    引数: summaries (list[dict])、details/waves (dict[id,list[dict]])。返り値: 全判定 (dict)。
    売買を再生せず、実装の正しさは別の全件監査を必須とする。
    """
    specs = {s['id']: s for s in design.catalog()}
    index = {r['id']: r for r in summaries}
    assert len(summaries) == len(index) == 192 and set(index) == set(details) == set(waves) == set(specs)
    expected = {(session, symbol) for session in design.SESSIONS for symbol in SYMBOLS}
    bases = {}
    for name, summary in index.items():
        assert summary['spec'] == specs[name]
        rows = details[name]
        assert len(rows) == len({(r['session'], r['symbol']) for r in rows}) == 26
        assert {(r['session'], r['symbol']) for r in rows} == expected
        assert all(r['id'] == name for r in rows)
        assert all(r['method'] == name for r in waves[name])
        wave_comparison(waves[name], waves[name])
        bases[name] = {}
        for period in PERIODS:
            sessions = design.SESSIONS if period == 'all_symbols' else design.SESSIONS[6:]
            bases[name][period] = {s: basic_checks(summary[period][s], [r for r in rows
                if r['session'] in sessions and r['symbol'] == s], period == 'symbols') for s in SYMBOLS}

    comparisons = []
    for spec in specs.values():
        candidate = index[spec['id']]
        old = compare(candidate, index[spec['reference_id']], waves)
        dynamic = compare(candidate, index[spec['dynamic_reference_id']], waves)
        qualified = all(bases[spec['id']][p][s]['基礎確認'] for p in PERIODS for s in SYMBOLS)
        comparisons.append({'id': spec['id'], 'signal_id': spec['signal_id'], 'atr_mode_id': spec['atr_mode_id'],
            'gate_id': spec['gate_id'], 'variant_id': spec['variant_id'], 'role': spec['role'],
            '採用対象': spec['adoption_target'], '候補基礎確認': qualified, '基礎検査': bases[spec['id']],
            '旧A0通常比較': old, 'At通常比較': dynamic,
            '主条件の採用目安合格': bool(spec['adoption_target'] and qualified
                and old['収支DD関係'] == '同時改善' and old['指定波']['波維持'])})
    main = next(row for row in comparisons if row['採用対象'])
    main['診断留保'] = [{'id': row['id'], '基礎未確認': not row['候補基礎確認'],
        '旧A0通常関係': row['旧A0通常比較']['収支DD関係'], 'At通常関係': row['At通常比較']['収支DD関係'],
        '旧A0波維持': row['旧A0通常比較']['指定波']['波維持']}
        for row in comparisons if row['signal_id'] == 'H019' and row['atr_mode_id'] == 'AT'
        and row['gate_id'] == 'SHADOW' and row['role'] == 'diagnostic']
    relations = ('同時改善', '同値', 'リスク収益交換', '収益リスク交換', '旧案が支配', '混在')
    groups = {variant['id']: {base: {label: sum(row['variant_id'] == variant['id'] and
        row['atr_mode_id'] == 'AT' and row['gate_id'] == 'SHADOW' and row[base]['収支DD関係'] == label
        for row in comparisons) for label in relations} for base in ('旧A0通常比較', 'At通常比較')}
        for variant in design.variants()}
    diagnostic = [{'id': spec['id'], 'base_id': spec['base_id'],
        **compare(index[spec['id']], index[spec['base_id']], waves)}
        for spec in specs.values() if spec['role'] == 'diagnostic']
    return {'全件判定完了': True, '全条件数': 192, '主条件数': 48, '診断数': 144,
        '全対応比較数': 384, '全13': list(design.SESSIONS), '共通後半7': list(design.SESSIONS[6:]),
        '全条件判定': comparisons, '全12の関係件数': groups, '全診断の主条件差': diagnostic,
        'H019主判定': main, '主条件採用目安ID': [main['id']] if main['主条件の採用目安合格'] else [],
        '実装監査は別条件': '全192の因果・会計・通常96の前回一致・A0制御48の恒等・資料完備の確認後に利用する。',
        '解釈': '旧A0比の採用目安とAt通常比の参加制御効果を分ける。後者の失敗を隠さず、採用目安へ新たな閾値を追加しない。',
        '診断留保': '診断の悪化や波喪失を残し、最良診断や別入口へ差し替えない。',
        '順位による入口再選択': False, '75_80閾値使用': False, '未知利益保証': False}


def freeze() -> dict:
    """機能: 判定実装を結果前の仕様と人工境界検査へ結合する。

    引数: なし。返り値: 固定記録 (dict)。
    """
    payload = {'実装SHA256': design.digest(Path(__file__)),
        '設計固定SHA256': design.digest(HERE / 'scheduler_design_fixed.json'),
        '人工検査SHA256': design.digest(HERE / 'scheduler_assessment_test.json'),
        '採用対象': 'H019__AT__SHADOW__V000', '全件数': 192,
        '新PnL参照': False, '診断最良昇格': False}
    path = HERE / 'scheduler_assessment_fixed.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8')) == payload
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


def main() -> None:
    """機能: 判定コードを固定するか、全192の保存値を独立判定する。

    引数: --prepare (bool)。返り値: なし (None)。売買再生を行わない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    fixed = freeze()
    if args.prepare:
        print('独立判定を結果前固定。新損益読取なし。')
        return

    def read(path: Path):
        """機能: 保存JSONを変更せず読む。

        引数: path (Path)。返り値: JSON内容 (object)。
        """
        if path.name.endswith('.gz'):
            with gzip.open(path, 'rt', encoding='utf-8') as stream:
                return json.load(stream)
        return json.loads(path.read_text(encoding='utf-8'))

    specs = design.catalog()
    summaries = [read(HERE / 'summaries' / (r['id'] + '.json')) for r in specs]
    details = {r['id']: read(HERE / 'sessions' / (r['id'] + '.json.gz')) for r in specs}
    waves = {r['id']: read(HERE / 'waves' / (r['id'] + '.json.gz')) for r in specs}
    result = assess(summaries, details, waves)
    result['独立判定固定SHA256'] = design.digest(HERE / 'scheduler_assessment_fixed.json')
    assert fixed['実装SHA256'] == design.digest(Path(__file__))
    (HERE / '独立判定.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('全192判定完了。主採用目安:', result['主条件採用目安ID'])


if __name__ == '__main__':
    main()

