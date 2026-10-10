"""新しい対照損益を読まず、全件完備検査の正常系と破損拒否を確認する。"""

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

import completion_guard as guard

HERE = Path(__file__).resolve().parent


def fixture() -> tuple:
    """機能: 旧一方式の明細を複製し、構造だけ420条件の合成材料を作る。

    引数: なし。返り値: 全件検査に必要な引数 (tuple)。新損益は参照しない。
    """
    fixed = guard.runner.read(HERE / '探索条件の固定.json')
    old_rows = guard.runner.read(HERE.parent / 'wave_v30/sessions/H003.json.gz')[0]['rows']
    inputs = {(r['session'], r['symbol']): {'last': list(range(10))} for r in old_rows}
    details, old_details, old_candidates, summaries, candidates = {}, {}, {}, {}, []
    for signal in fixed['signals']:
        name = signal['id']
        summary = {'signal': signal, '既存結果の再利用': False, 'candidates': [], '旧管理の全数値と台帳一致': []}
        for management in fixed['managers']:
            base_id = name + '__' + management['id']
            base_rows = [dict(row, id=base_id) for row in old_rows]
            old_details[base_id] = {(r['session'], r['symbol']): r for r in base_rows}
            original = guard.runner.diagnostics(base_rows)
            old_candidates[base_id] = {'symbols': original, 'ledger_hash': 'a' * 64}
            summary['旧管理の全数値と台帳一致'].append(base_id)
            for variant in fixed['variants']:
                identifier = base_id + '__' + variant['id']
                rows = [dict(row, id=identifier, long_unit_minutes=float(row['cycles']), short_unit_minutes=0.,
                             opening_orders=row['cycles'], first_entry_min=0. if row['cycles'] else None) for row in base_rows]
                values = deepcopy(original)
                for symbol in guard.SYMBOLS:
                    values[symbol].update({field: sum(r[field] for r in rows if r['symbol'] == symbol) for field in guard.PARTICIPATION_FIELDS})
                candidate = dict(id=identifier, base_id=base_id, signal_id=name, manager_id=management['id'],
                                 variant_id=variant['id'], signal_family=signal['family'], manager_family=management['family'],
                                 symbols=values, failures=guard.runner.failures(values), ledger_hash='a' * 64)
                details[identifier] = rows
                candidates.append(candidate)
                summary['candidates'].append(candidate)
        summaries[name] = summary
    return fixed, inputs, candidates, summaries, details, old_candidates, old_details


def rejection(name: str, function, output: list) -> None:
    """機能: 不正材料が拒否されたことを確認して記録する。

    引数: name (str)、function (callable)、output (list)。返り値: なし (None)。
    """
    try:
        function()
    except (AssertionError, KeyError):
        output.append(name)
    else:
        raise AssertionError('不正材料を許容: ' + name)


def main() -> None:
    """機能: 全件正常系と欠損・重複・偽要約・会計不整合を合成検査する。

    引数: なし。返り値: なし (None)。新損益読取り・エンジン再生なし。
    """
    args = fixture()
    fixed, inputs, candidates, summaries, details, old_candidates, old_details = args
    normal = guard.verify_main(*args)
    rejected = []
    for name, change in (
        ('候補不足', lambda a: a[2].pop()),
        ('候補重複', lambda a: a[2].__setitem__(1, a[2][0])),
        ('区間不足', lambda a: next(iter(a[4].values())).pop()),
        ('収支不整合', lambda a: next(iter(a[4].values()))[0].update(net_yen=123456789)),
        ('決済枚数不整合', lambda a: next(iter(a[4].values()))[0].update(closed_units=99999)),
        ('V000台帳不一致', lambda a: next(iter(a[5].values())).update(ledger_hash='b' * 64)),
        ('旧一致要約重複', lambda a: next(iter(a[3].values()))['旧管理の全数値と台帳一致'].__setitem__(1, next(iter(a[3].values()))['旧管理の全数値と台帳一致'][0]))):
        broken = deepcopy(args)
        change(broken)
        rejection(name, lambda: guard.verify_main(*broken), rejected)
    episode_fixed = guard.runner.read(HERE / 'episode_audit_fixed.json')
    catalog = {r['id']: r for r in candidates}
    rows, wave_summaries = [], []
    for name in catalog:
        for wave in episode_fixed['規則']['対象波']:
            duration = (datetime.fromisoformat(wave['end']) - datetime.fromisoformat(wave['start'])).total_seconds() / 60
            for symbol in guard.SYMBOLS:
                rows.append(dict(method=name, wave=wave['id'], session=wave['session'], symbol=symbol,
                                 開始=wave['start'], 終了=wave['end'], 波方向=wave['side'], 区間分=duration,
                                 正方向ネット保有分=0., 正方向ネット20分目安達成=False))
        wave_summaries.append(dict(method=name, 対象区間数=8, 目安達成区間数=0))
    waves = {'手法': [{'id': name} for name in catalog], '結果': rows, '方法別要約': wave_summaries}
    guard.verify_waves(waves, episode_fixed, catalog)
    for name, change in (
        ('波不足', lambda a: a['結果'].pop()),
        ('波重複', lambda a: a['結果'].__setitem__(1, a['結果'][0])),
        ('波合格偽装', lambda a: a['結果'][0].update(正方向ネット20分目安達成=True)),
        ('波要約偽装', lambda a: a['方法別要約'][0].update(目安達成区間数=8))):
        broken = deepcopy(waves)
        change(broken)
        rejection(name, lambda: guard.verify_waves(broken, episode_fixed, catalog), rejected)
    values = []
    for signal in fixed['signals']:
        records = []
        for candidate in candidates:
            if candidate['signal_id'] != signal['id']:
                continue
            records.append(dict(id=candidate['id'], 全入力数=26, 原本行会計数=260,
                                prefix検査数=26, 未来価格ATR両入力改変数=26, 買売反射数=26,
                                独立参加時間一致=True, 保存全数値一致=True, 台帳SHA256=candidate['ledger_hash'],
                                V000旧一致=candidate['variant_id'] == 'V000', sessions=details[candidate['id']], symbols=candidate['symbols']))
        values.append({'全35条件': records})
    accounting = dict(全監査合格=True, 対象条件数=420, 全入力数=10920, V000旧一致条件数=84,
                      全方向保存列一致=True, 独立参加時間一致=True, 保存全数値と全台帳SHA一致=True,
                      現在データ使用=False, 成績による対象選別=False, ルール変更=False, API取得数=0,
                      条件=[{k: v for k, v in row.items() if k != 'sessions'} for value in values for row in value['全35条件']],
                      全原本行会計数=109200, prefix検査数=10920, 未来価格ATR両入力改変数=10920, 買売反射数=10920)
    guard.verify_accounting(accounting, values, catalog, details, inputs)
    for name, change in (
        ('会計偽合格', lambda a: a[0].update(全監査合格=False)),
        ('会計要約偽装', lambda a: a[0].update(全原本行会計数=1)),
        ('会計実体不足', lambda a: a[1][0]['全35条件'].pop()),
        ('会計実体重複', lambda a: a[1][0]['全35条件'].__setitem__(1, a[1][0]['全35条件'][0])),
        ('会計明細の必須項目欠落', lambda a: a[1][0]['全35条件'][0]['sessions'][0].pop('gross_profit_yen'))):
        broken = deepcopy((accounting, values))
        change(broken)
        rejection(name, lambda: guard.verify_accounting(*broken, catalog, details, inputs), rejected)
    import episode_audit
    participant_values = []
    for signal in fixed['signals']:
        names = [name for name in catalog if name.startswith(signal['id'] + '__')]
        participant_rows = []
        for name in names:
            for main_row in details[name]:
                held = min(1., main_row['long_unit_minutes'])
                row = {key: main_row[key] for key in ('id', 'session', 'symbol', *guard.PARTICIPATION_FIELDS, 'first_entry_min')}
                row.update({'観測分': 100., '買い枚数分': main_row['long_unit_minutes'], '売り枚数分': 0.,
                            '買い保有分': held, '売り保有分': 0., '保有分': held, '無建玉分': 100. - held,
                            '初回新規待ち分': 100. - held, '返済後再開待ち分': 0., '最終返済後待ち分': 0.,
                            '新規注文数': main_row['opening_orders'], '新規枚数': main_row['closed_units'], '返済枚数': main_row['closed_units'],
                            '場末後等の区間外買い枚数分': 0., '場末後等の区間外売り枚数分': 0.,
                            '方向の時間': {key: {'買い分': 0., '売り分': 0., '中立分': 100.} for key in ('入口', '両市場C', '自己S')},
                            '損益': {key: value for key, value in main_row.items() if key not in (*guard.PARTICIPATION_FIELDS, 'first_entry_min')}})
                participant_rows.append(row)
        participant_values.append({'signal': signal, '手法': [{'id': name} for name in names], '参加': participant_rows})
    participants = episode_audit.aggregate_participation(participant_values)
    participants.update(現在保存物使用=False, API取得数=0)
    guard.verify_participation(participants, participant_values, catalog, details, inputs)
    for name, change in (
        ('参加不足', lambda a: a['セッション'].pop()),
        ('参加重複', lambda a: a['セッション'].__setitem__(1, a['セッション'][0])),
        ('参加時間偽装', lambda a: a['セッション'][0].update(long_unit_minutes=9876543)),
        ('参加対応差偽装', lambda a: a['対照差'][0].update(収支差円=9876543))):
        broken = deepcopy(participants)
        change(broken)
        rejection(name, lambda: guard.verify_participation(broken, participant_values, catalog, details, inputs), rejected)
    chart_methods = sorted(name for name in catalog if name.startswith('H019__'))
    chart_fixed = {'手法': chart_methods, '全入力図数': 910}
    chart = {'手法': chart_methods, '採用候補の図示': False, '結果前固定の例示': True, '外部通信': 0, '現在保存物使用': False,
             '保存済み収支との比較': [{'手法': name, 'session': row['session'], 'symbol': row['symbol'], '保存値一致': True, '収支円': row['net_yen']}
                                      for name in chart_methods for row in details[name]]}
    guard.verify_chart(chart, chart_fixed, catalog, details, inputs)
    broken = deepcopy(chart)
    broken['保存済み収支との比較'].pop()
    rejection('図示不足', lambda: guard.verify_chart(broken, chart_fixed, catalog, details, inputs), rejected)
    output = {'合成検査全合格': True, '全420主結果正常系': normal, '波3360正常系': True,
              '会計420実体正常系': True, '参加10920と対応差1008正常系': True, '図示910正常系': True,
              '不正材料拒否': rejected, '新対照の損益読取': False,
              'エンジン再生': False, '旧一方式複製': 'v30 H003 L000の旧26行を各IDへ複製した合成材料。'}
    guard.runner.save(HERE / 'completion_guard_test.json', output)
    print(json.dumps(output, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
