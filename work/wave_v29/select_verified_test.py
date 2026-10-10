"""整合ガードを合成資料だけで検査する。探索結果と現在データは読まない。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import math
from pathlib import Path

import episode_audit
import protection_design
import select_verified as guard


def rows(name: str) -> list:
    """機能: 13期間×2銘柄の合成会計明細を作る。

    引数: name (str)。返り値: 検算可能な架空区間明細 (list)。
    """
    sessions = [f'2026-09-{day:02d}_{period}' for day in (21, 22, 23, 24, 25, 28) for period in ('Day', 'Night')] + ['2026-09-29_Day']
    return [dict(id=name, symbol=symbol, session=session, gross_profit_yen=10000., gross_loss_yen=1000., net_yen=9000.,
                 profit_units=5, loss_units=5, zero_units=0, closed_units=10,
                 cycles=2, cycle_wins=1, cycle_losses=1, cycle_profit_yen=10000., cycle_loss_yen=1000.,
                 net_r=1., drawdown_yen=1000., min_equity_yen=-1000., max_equity_yen=9000.,
                 max_long=5, max_short=0, longest_losing_streak=1, maximum_trade_profit=10000.,
                 two_largest_cycle_profits=[10000.]) for session in sessions for symbol in guard.SYMBOLS]


def case(name: str, category: str | None = None) -> dict:
    """機能: 架空の再生1件と再計算可能な期間集計を作る。

    引数: name (str)、category (str|None)。返り値: 合成再生 (dict)。
    """
    detail = rows(name)
    output = {'case': name, 'rows': detail, 'symbols': guard.runner.diagnostics(detail), 'ledger_hash': 'a' * 64}
    if category is not None:
        output['category'] = category
    return output


def fixture() -> dict:
    """機能: 一次・乱数・波の資料が全て内部整合する合成一候補を作る。

    引数: なし。返り値: 純粋検算関数へ渡す資料集合 (dict)。
    """
    signal = next(row for row in guard.runner.hierarchy_signals.catalog() if row['id'] == 'H019')
    management = protection_design.catalog()[0]
    identifier = signal['id'] + '__' + management['id']
    base = case('基準再現')
    candidate = {'id': identifier, 'signal_id': signal['id'], 'manager_id': management['id'],
                 'signal_family': signal['family'], 'manager_family': management['family'],
                 'ledger_hash': base['ledger_hash'], 'symbols': deepcopy(base['symbols']), 'failures': []}
    assert not guard.runner.failures(candidate['symbols'])
    cases = [base] + [case(f'両入力{value}秒遅延', 'delay') for value in (1, 5, 15)] + [case('観測価格約定', 'observed')]
    grouped = {'entry': [], 'management': [], 'clock': [], 'confirmation': [], 'loss_controls': []}
    management_variants, _ = guard.validator.management_neighbors(management)
    signal_variants = [row for row in guard.runner.hierarchy_signals.neighbor_specs(signal) if row['applied']]
    for spec in management_variants + signal_variants:
        category = spec.get('category', spec.get('diagnostic_category'))
        row = case(spec['id'], category)
        cases.append(row)
        grouped['clock' if category == 'peer' else category].append(row)
    cases.extend(case(name) for name in ('両入力を反転', '管理をG08へ交換', '片方向1枚へ保有制限',
                                        '同じ退出規則でcontextをentryへ戻す', '損失制限だけ除去', '常時買い', '常時売り',
                                        '同一入口K000へ交換', '割合保護だけ除去', '追跡短縮だけ除去'))
    full_first = {'candidate': deepcopy(candidate), 'validation_sha': '合成の実装SHA', 'cases': cases,
                  'basic_failures': [], 'first_stage_failures': [],
                  'カテゴリ判定': {name: guard.validator.group_diagnostics(name, group, base, allow_empty=name in ('entry', 'confirmation', 'loss_controls'))
                                 for name, group in grouped.items()}}
    summary_first = {key: deepcopy(value) for key, value in full_first.items() if key != 'cases'}
    results = []
    for gate in (False, True):
        for seed in range(64):
            row = case(f'乱数{gate}_{seed}')
            row.update(gated=gate, seed=seed)
            results.append(row)
    full_random = {'candidate': deepcopy(candidate), 'validation_sha': '合成の実装SHA', 'results': results,
                   'summary': guard.random_summary(results, candidate),
                   '中期撤回も同一30分乱数へ置換': True, '発火限定は入口だけに適用': True}
    random = {key: deepcopy(value) for key, value in full_random.items() if key != 'results'}
    waves = deepcopy(list(episode_audit.EPISODES))
    fixed_comparisons = ['F32__G08', 'D016__D065', 'P02__D065', 'H019__D273']
    episode_fixed = {'規則': {'対象': waves, '銘柄': list(guard.SYMBOLS), '固定比較': fixed_comparisons}}
    methods = [{'id': key} for key in fixed_comparisons]
    methods.append({'id': identifier, 'signal': dict(signal, 実装元='二入力階層'), 'manager': management})
    wave_rows, summaries = [], []
    for method in methods:
        for wave in waves:
            minutes = (datetime.fromisoformat(wave['end']) - datetime.fromisoformat(wave['start'])).total_seconds() / 60
            for symbol in guard.SYMBOLS:
                wave_rows.append({'method': method['id'], 'wave': wave['id'], 'symbol': symbol,
                                  'session': wave['session'], '開始': wave['start'], '終了': wave['end'], '波方向': wave['side'],
                                  '区間分': minutes, '正方向ネット保有分': 20., '正方向ネット20分目安達成': True})
        summaries.append({'method': method['id'], '対象区間数': 8, '目安達成区間数': 8, '正方向保有0区間': []})
    episodes = {'固定仕様': episode_fixed, '一次反証固定SHA256': '合成一次SHA',
                '手法': methods, '結果': wave_rows, '方法別要約': summaries}
    return {'specs': {'signals': [signal], 'managers': [management], '全組合せ数': 1},
            'candidates': [deepcopy(candidate)], 'planned': [deepcopy(candidate)],
            'first': [summary_first], 'adversarial': {identifier: full_first},
            'random': [random], 'random_targets': [deepcopy(candidate)], 'random_full': {identifier: full_random},
            'episodes': episodes, 'episode_fixed': episode_fixed,
            'episode_extension': {'規則': {'一次反証SHA256': '合成一次SHA', '元の波診断固定SHA256': '合成波SHA', '追加対象': [identifier]}},
            'expected_keys': {(row['session'], row['symbol']) for row in base['rows']},
            'validation_sha': '合成の実装SHA', 'first_sha': '合成一次SHA', 'episode_fixed_sha': '合成波SHA',
            'baseline': {'id': 'H019__D273', 'symbols': {symbol: {'net_yen': 100., 'drawdown_yen': 100.} for symbol in guard.SYMBOLS}}}


def main() -> None:
    """機能: 完全な合成資料だけ受理し、不足・重複・偽要約等の反例を拒否する。

    引数: なし。返り値: なし (None)。実成績を読まず、元選抜を実行しない。
    """
    original = fixture()
    valid = guard.verify_bundle(deepcopy(original))
    records = []
    mutations = ('一次不足', '一次重複', '一次実体変形不足', '一次集計偽造', '乱数不足', '乱数seed重複',
                 '乱数方式型不正', '乱数要約偽造', '乱数SHA不一致', '乱数候補内容不一致', '波重複',
                 '波要約偽造', '波20分判定偽造', '波一次SHA不一致', '非有限値', '通過ありの乱数空', '乱数予定重複',
                 '同入口K000対照不足', '同入口K000台帳不一致', '全探索K000重複')
    for name in mutations:
        bundle = deepcopy(original)
        identifier = bundle['candidates'][0]['id']
        if name == '一次不足':
            bundle['first'] = []
        elif name == '一次重複':
            bundle['first'].append(deepcopy(bundle['first'][0]))
        elif name == '一次実体変形不足':
            bundle['adversarial'][identifier]['cases'].pop()
        elif name == '一次集計偽造':
            bundle['adversarial'][identifier]['cases'][1]['symbols']['TOPIX']['net_yen'] += 1
        elif name == '乱数不足':
            bundle['random_full'][identifier]['results'].pop()
        elif name == '乱数seed重複':
            bundle['random_full'][identifier]['results'][-1]['seed'] = 62
        elif name == '乱数方式型不正':
            bundle['random_full'][identifier]['results'][0]['gated'] = 0
        elif name == '乱数要約偽造':
            bundle['random'][0]['summary'][0]['両銘柄で候補以上の収支seed数'] = 0
            bundle['random_full'][identifier]['summary'][0]['両銘柄で候補以上の収支seed数'] = 0
        elif name == '乱数SHA不一致':
            bundle['random'][0]['validation_sha'] = '別SHA'
            bundle['random_full'][identifier]['validation_sha'] = '別SHA'
        elif name == '乱数候補内容不一致':
            bundle['random'][0]['candidate']['symbols']['TOPIX']['net_yen'] += 1
        elif name == '波重複':
            bundle['episodes']['結果'][-1] = deepcopy(bundle['episodes']['結果'][-2])
        elif name == '波要約偽造':
            bundle['episodes']['方法別要約'][-1]['目安達成区間数'] = 7
        elif name == '波20分判定偽造':
            bundle['episodes']['結果'][-1]['正方向ネット保有分'] = 19.99
        elif name == '波一次SHA不一致':
            bundle['episodes']['一次反証固定SHA256'] = '別一次SHA'
        elif name == '非有限値':
            bundle['candidates'][0]['symbols']['TOPIX']['net_yen'] = math.nan
        elif name == '通過ありの乱数空':
            bundle['random'] = []
            bundle['random_targets'] = []
            bundle['random_full'] = {}
        elif name == '乱数予定重複':
            bundle['random_targets'].append(deepcopy(bundle['random_targets'][0]))
        elif name == '同入口K000対照不足':
            bundle['adversarial'][identifier]['cases'] = [row for row in bundle['adversarial'][identifier]['cases'] if row['case'] != '同一入口K000へ交換']
        elif name == '同入口K000台帳不一致':
            next(row for row in bundle['adversarial'][identifier]['cases'] if row['case'] == '同一入口K000へ交換')['ledger_hash'] = 'b' * 64
        elif name == '全探索K000重複':
            bundle['candidates'].append(deepcopy(bundle['candidates'][0]))
        try:
            guard.verify_bundle(bundle)
        except (AssertionError, ValueError, KeyError, TypeError) as error:
            records.append({'反例': name, '拒否': True, '例外種別': type(error).__name__})
        else:
            raise AssertionError('不正資料を受理: ' + name)

    # ----------------------------------------
    empty = deepcopy(original)
    identifier = empty['candidates'][0]['id']
    full = empty['adversarial'][identifier]
    observed = next(row for row in full['cases'] if row['case'] == '観測価格約定')
    for row in observed['rows']:
        row.update(gross_profit_yen=0., net_yen=-1000., cycle_profit_yen=0.,
                   max_equity_yen=0., maximum_trade_profit=0., two_largest_cycle_profits=[])
    observed['symbols'] = guard.runner.diagnostics(observed['rows'])
    full['first_stage_failures'] = ['遅延または観測約定で両銘柄黒字PF1.2を維持できない']
    empty['first'][0]['first_stage_failures'] = full['first_stage_failures'].copy()
    empty['random_targets'], empty['random'], empty['random_full'] = [], [], {}
    for field, key in (('手法', 'id'), ('方法別要約', 'method'), ('結果', 'method')):
        empty['episodes'][field] = [row for row in empty['episodes'][field] if row[key] != identifier]
    empty['episode_extension']['規則']['追加対象'] = []
    no_pass = guard.verify_bundle(empty)
    assert no_pass['一次通過数'] == no_pass['乱数候補数'] == 0
    result = {'実損益未読': True, '現在データ未読': True, '合成正常資料': valid,
              '一次通過0が確認された正当な空資料': no_pass, '拒否確認': records,
              '検査対象コードSHA256': guard.digest(Path(guard.__file__))}
    path = Path(__file__).with_suffix('.json')
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(f'合成正常2件（正当な通過0件を含む）・不正{len(records)}件の拒否を確認。新損益は未読。', flush=True)


if __name__ == '__main__':
    main()
