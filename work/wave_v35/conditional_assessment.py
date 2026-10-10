"""条件付き短縮を初期6だけで選び、選択policyと全対応差を独立判定する。"""

from __future__ import annotations

import argparse
import gzip
import json
import math
from statistics import median
from pathlib import Path

import conditional_design as design

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
def totals(rows: list[dict]) -> dict:
    """機能: 同銘柄の完了セッションを独立に合計し、含み込み最大下落を接続する。

    引数: rows (list[dict])。返り値: 基礎指標 (dict)。異銘柄の円額は混ぜない。
    """
    assert rows and len({r['symbol'] for r in rows}) == 1
    assert len(rows) == len({r['session'] for r in rows})
    fields = ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'net_r', 'profit_units', 'loss_units',
              'zero_units', 'cycles', 'opening_orders', 'long_unit_minutes', 'short_unit_minutes', 'closed_units')
    result = {field: sum(r[field] for r in rows) for field in fields}
    assert all(math.isfinite(v) for v in result.values())
    cash = peak = drawdown = 0.
    for row in sorted(rows, key=lambda r: r['session']):
        assert all(math.isfinite(row[f]) for f in ('drawdown_yen', 'min_equity_yen', 'max_equity_yen'))
        assert row['drawdown_yen'] >= 0
        drawdown = max(drawdown, row['drawdown_yen'], peak - cash - row['min_equity_yen'])
        peak = max(peak, cash + row['max_equity_yen'])
        cash += row['net_yen']
    profit, loss = result['gross_profit_yen'], result['gross_loss_yen']
    result['money_ratio'] = profit / loss if loss > 0 else None
    result['average_unit_payoff'] = ((profit / result['profit_units']) / (loss / result['loss_units'])
        if result['profit_units'] > 0 and result['loss_units'] > 0 and loss > 0 else None)
    result['drawdown_yen'] = drawdown
    result['active_sessions'] = sum(r['opening_orders'] > 0 for r in rows)
    result['session_count'] = len(rows)
    result['average_win_unit_yen'] = profit / result['profit_units'] if result['profit_units'] else None
    result['average_loss_unit_yen'] = loss / result['loss_units'] if result['loss_units'] else None
    result['average_closed_unit_yen'] = result['net_yen'] / result['closed_units'] if result['closed_units'] else None
    metrics = [m for row in rows for m in row['retracements']]
    result['組ピーク悪化'] = {}
    for key, part in (('全組', metrics), ('利益の出た組', [m for m in metrics if m['positive_peak']])):
        values = [m['retracement_yen'] for m in part]
        risk = [m['retracement_r'] for m in part]
        result['組ピーク悪化'][key] = {'件数': len(part), '合計円': sum(values), '合計R': sum(risk),
            '平均円': sum(values) / len(values) if values else None,
            '中央値円': median(values) if values else None,
            '平均R': sum(risk) / len(risk) if risk else None, '中央値R': median(risk) if risk else None}
    return result


def period_values(rows: list[dict]) -> dict:
    """機能: 同じ完了列の全13と共通後半7を銘柄別に集計する。

    引数: rows (list[dict])。返り値: 4セルの成績 (dict)。
    """
    return {period: {symbol: totals([r for r in rows if r['symbol'] == symbol and r['session'] in sessions])
                     for symbol in SYMBOLS}
            for period, sessions in (('all_symbols', design.SESSIONS), ('symbols', design.SESSIONS[6:]))}


def select_training(training: dict[str, list[dict]], cutoff: float) -> dict:
    """機能: 初期6だけの全168候補から、共通の返済方式を機械的に1つ選ぶ。

    引数: training (dict[id,list[dict]])、cutoff (float) は後半先頭の開始秒。
    返り値: 選択方式・全スコア・適格根拠 (dict)。後半や未完了の混入は拒否する。
    """
    specs = {s['id']: s for s in design.catalog() if s['role'] == 'primary'}
    expected = {(session, symbol) for session in design.SESSIONS[:6] for symbol in SYMBOLS}
    assert math.isfinite(cutoff) and set(training) == set(specs) and len(training) == 168
    aggregate = {}
    for name, rows in training.items():
        keys = {(r['session'], r['symbol']) for r in rows}
        assert len(rows) == len(keys) == 12 and keys == expected
        for row in rows:
            assert row['id'] == name and row['complete'] is True
            assert math.isfinite(row['completed_at']) and row['completed_at'] <= cutoff
        aggregate[name] = {symbol: totals([r for r in rows if r['symbol'] == symbol]) for symbol in SYMBOLS}
    candidates = []
    for mode in design.exit_modes():
        by_symbol = {}
        for symbol in SYMBOLS:
            pairs = []
            for signal in design.SIGNAL_IDS:
                value, base = aggregate[f"{signal}__{mode['id']}__V000"][symbol], aggregate[f'{signal}__A0__V000'][symbol]
                pairs.append({'signal_id': signal, 'net_r_delta': value['net_r'] - base['net_r'],
                    'drawdown_yen_delta': value['drawdown_yen'] - base['drawdown_yen'],
                    'net_yen': value['net_yen'], 'money_ratio': value['money_ratio'],
                    'average_unit_payoff': value['average_unit_payoff']})
            dr = median(p['net_r_delta'] for p in pairs)
            dd = median(p['drawdown_yen_delta'] for p in pairs)
            by_symbol[symbol] = {'対応12': pairs, '中央値純益差R': dr, '中央値DD差円': dd,
                '収支適格': dr >= -1e-10, 'DD適格': dd <= 1e-6}
        scores = [by_symbol[s]['中央値純益差R'] for s in SYMBOLS]
        eligible = all(by_symbol[s]['収支適格'] and by_symbol[s]['DD適格'] for s in SYMBOLS)
        candidates.append({'exit_mode_id': mode['id'], '適格': eligible, '銘柄別': by_symbol,
            '弱い銘柄の中央値差R': min(scores), '両銘柄の中央値差R平均': sum(scores) / 2})
    valid = [r for r in candidates if r['適格']]
    assert any(r['exit_mode_id'] == 'A0' for r in valid)
    ordered = sorted(valid, key=lambda r: (-round(r['弱い銘柄の中央値差R'], 12),
        -round(r['両銘柄の中央値差R平均'], 12), 0 if r['exit_mode_id'] == 'A0' else 1, r['exit_mode_id']))
    chosen = ordered[0]['exit_mode_id']
    return {'選択完了': True, 'selected_exit_mode_id': chosen, 'selected_id': f'H019__{chosen}__V000',
        '使用セッション': list(design.SESSIONS[:6]), '選択締切秒': cutoff,
        '全主条件数': 168, '全初期行数': 2016, '全14方式': candidates,
        '適格順序': [r['exit_mode_id'] for r in ordered], '固定fallback': chosen == 'A0',
        '最初6の運用': 'H019__A0__V000', '後半7の運用': f'H019__{chosen}__V000',
        '後半結果参照': False, '診断最良採用': False, '別入口採用': False}


def comparison(candidate: dict, reference: dict) -> dict:
    """機能: 4セルの全指標と差を残し、収支/DD関係を分類する。

    引数: candidate/reference (dict)。返り値: 比較記録 (dict)。
    """
    changes = {}
    for period in PERIODS:
        changes[period] = {}
        for symbol in SYMBOLS:
            new, old = candidate[period][symbol], reference[period][symbol]
            changes[period][symbol] = {'旧': old, '変更': new,
                '差': {f: new[f] - old[f] for f in ('net_yen', 'net_r', 'drawdown_yen', 'gross_profit_yen',
                    'gross_loss_yen', 'profit_units', 'loss_units', 'zero_units', 'cycles', 'opening_orders')}}
    return {'収支DD関係': relation(candidate, reference), '期間銘柄': changes}


def policy_rows(details: dict, mode: str, variant: str = 'V000') -> list[dict]:
    """機能: 初期6固定A0と後7選択方式を、遡及させず接続する。

    引数: details (dict[id,list])、mode/variant (str)。返り値: 26運用行 (list[dict])。
    """
    initial = [r for r in details[f'H019__A0__{variant}'] if r['session'] in design.SESSIONS[:6]]
    latter = [r for r in details[f'H019__{mode}__{variant}'] if r['session'] in design.SESSIONS[6:]]
    result = sorted(initial + latter, key=lambda r: (r['session'], r['symbol']))
    assert len(result) == len({(r['session'], r['symbol']) for r in result}) == 26
    return result


def assess(summaries: list[dict], details: dict, waves: dict, selection: dict) -> dict:
    """機能: 初期選択を再照合し、全840とH019の時系列運用を独立判定する。

    引数: summaries (list[dict])、details/waves/selection (dict)。返り値: 全判定 (dict)。
    選択後に最良条件へ変更せず、診断と追加乱数は採用候補へ昇格しない。
    """
    specs = {s['id']: s for s in design.catalog()}
    index = {s['id']: s for s in summaries}
    assert len(index) == len(summaries) == 840 and set(index) == set(details) == set(waves) == set(specs)
    expected = {(session, symbol) for session in design.SESSIONS for symbol in SYMBOLS}
    values = {}
    for name, spec in specs.items():
        assert index[name]['spec'] == spec
        rows = details[name]
        assert len(rows) == len({(r['session'], r['symbol']) for r in rows}) == 26
        assert {(r['session'], r['symbol']) for r in rows} == expected
        assert all(r['id'] == name and r['complete'] is True for r in rows)
        assert all(r['method'] == name for r in waves[name])
        wave_comparison(waves[name], waves[name])
        values[name] = period_values(rows)
        for period in PERIODS:
            for symbol in SYMBOLS:
                for field in ('net_yen', 'net_r', 'drawdown_yen', 'gross_profit_yen', 'gross_loss_yen',
                              'profit_units', 'loss_units', 'zero_units', 'cycles', 'opening_orders'):
                    assert math.isclose(values[name][period][symbol][field], index[name][period][symbol][field], abs_tol=1e-6, rel_tol=1e-10)
    training = {name: [r for r in details[name] if r['session'] in design.SESSIONS[:6]]
                for name, spec in specs.items() if spec['role'] == 'primary'}
    reproduced = select_training(training, selection['選択締切秒'])
    assert selection == reproduced, '初期6の選択固定と一致しない'
    chosen, chosen_id = selection['selected_exit_mode_id'], selection['selected_id']
    operated = policy_rows(details, chosen)
    policy = period_values(operated)
    fixed = values['H019__A0__V000']
    constant_min = values['H019__MIN__V000']
    checks = {p: {s: basic_checks(policy[p][s], [r for r in operated if r['symbol'] == s
        and r['session'] in (design.SESSIONS if p == 'all_symbols' else design.SESSIONS[6:])], p == 'symbols')
        for s in SYMBOLS} for p in PERIODS}
    base_ok = all(checks[p][s]['基礎確認'] for p in PERIODS for s in SYMBOLS)
    selected_waves = wave_comparison(waves[chosen_id], waves['H019__A0__V000'])
    old_relation = comparison(policy, fixed)
    min_policy = period_values(policy_rows(details, 'MIN'))
    min_relation = comparison(policy, min_policy)
    adopted = chosen != 'A0' and base_ok and old_relation['収支DD関係'] == '同時改善' and selected_waves['波維持']
    all_comparisons = []
    for name, spec in specs.items():
        all_comparisons.append({'id': name, 'signal_id': spec['signal_id'], 'exit_mode_id': spec['exit_mode_id'],
            'variant_id': spec['variant_id'], 'role': spec['role'],
            '固定A0比較': comparison(values[name], values[spec['reference_id']]),
            '常時MIN比較': comparison(values[name], values[spec['always_reference_id']]),
            '指定波': wave_comparison(waves[name], waves[spec['reference_id']]),
            '原型比較': comparison(values[name], values[spec['base_id']]) if spec['role'] == 'diagnostic' else None})
    diagnostics = []
    for variant in design.variants():
        if variant['id'] == 'V000':
            continue
        altered = period_values(policy_rows(details, chosen, variant['id']))
        variant_base = values[f"H019__A0__{variant['id']}"]
        diagnostics.append({'variant_id': variant['id'], 'selected_exit_mode_id': chosen,
            '選択の再最適化': False, '主policyとの差': comparison(altered, policy),
            '同変形固定A0との差': comparison(altered, variant_base),
            '選択条件の波': wave_comparison(waves[f"H019__{chosen}__{variant['id']}"], waves[f"H019__A0__{variant['id']}"])})
    return {'全件判定完了': True, '全条件数': 840, '主条件数': 168, '診断数': 672,
        '選択固定再計算一致': True, '選択': selection, '全対応比較': all_comparisons,
        'H019運用policy': {'全13と後7': policy, 'セッション': operated, '候補基礎': checks,
            '候補基礎確認': base_ok, '固定A0比較': old_relation, '初期A0後半MIN比較': min_relation,
            '全期間常時MIN比較': comparison(policy, constant_min),
            '選択した固定条件の波': selected_waves, 'policyの波': '初期6は固定A0。全指定波もこの範囲であり選択条件の証拠にしない。',
            '確認条件の追加価値未支持': chosen.startswith('B') and min_relation['収支DD関係'] in ('旧案が支配', '同値'),
            '主条件の採用目安合格': adopted},
        'H019診断': diagnostics, '主条件採用目安ID': [chosen_id] if adopted else [],
        '実装監査は別条件': '全840の未来/会計/全新規一致/早い返済/波/完備を満たした後に使用する。',
        '追加乱数の扱い': '選択Bの場合64seedと反転は別診断。最良を主条件へ昇格せず正式pとしない。',
        '評価の限界': '初期6だけの選択手順は因果的だが全13既知。12入口は同じ相場の相関した対応比較である。',
        '新閾値の追加': False, '75_80閾値使用': False, '未知利益保証': False}


def freeze() -> dict:
    """機能: 選択と判定の実装を事前仕様・人工反例へ固定する。

    引数: なし。返り値: 固定記録 (dict)。
    """
    payload = {'実装SHA256': design.digest(Path(__file__)),
        '設計固定SHA256': design.digest(HERE / 'conditional_design_fixed.json'),
        '人工検査SHA256': design.digest(HERE / 'conditional_assessment_test.json'),
        '全条件数': 840, '選択は初期6のみ': True, '後半混入拒否': True, '新PnL参照': False}
    path = HERE / 'conditional_assessment_fixed.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8')) == payload
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    if args.prepare:
        freeze()
        print('選択と独立判定を固定。新損益参照なし。')
    else:
        raise SystemExit('売買再生は担当runner。判定は保存資料をassessへ渡して実行する。')

