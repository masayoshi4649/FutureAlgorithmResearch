"""鮮度診断の全件資料を照合する。新候補の採否や利益順位は決めない。"""

from __future__ import annotations

from datetime import datetime
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo

import numpy as np
import lag_runner as runner
import run_verified

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / 'wave_v30'
SYMBOLS = ('TOPIX', 'NK225')
PARTICIPATION_FIELDS = ('long_unit_minutes', 'short_unit_minutes', 'opening_orders')


def finite(value: object) -> None:
    """機能: 保存された数値のNaNと無限大を拒否する。

    引数: value (object)。返り値: なし (None)。
    """
    if isinstance(value, dict):
        for item in value.values():
            finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            finite(item)
    elif isinstance(value, float):
        assert math.isfinite(value), '非有限値が含まれる'


def unique(rows: list[dict], key: str, label: str) -> dict:
    """機能: 指定識別子の一意性を検査して対応辞書を作る。

    引数: rows (list[dict])、key/label (str)。返り値: 対応辞書 (dict)。
    """
    values = {row[key]: row for row in rows}
    assert len(values) == len(rows), label + 'の重複'
    return values


def verify_main(fixed: dict, inputs: dict, candidates: list[dict], summaries: dict,
                details: dict, old_candidates: dict, old_details: dict) -> dict:
    """機能: 全420の明細を再集計し、V000全84が元結果と一致するか検査する。

    引数: fixed/inputs/summaries/details/old_candidates/old_details (dict)、candidates (list[dict])。
    返り値: 主結果の検査件数 (dict)。新しい売買再生はしない。
    """
    finite([fixed, candidates, summaries, details])
    signals = unique(fixed['signals'], 'id', '入口')
    managers = unique(fixed['managers'], 'id', '管理')
    variants = unique(fixed['variants'], 'id', '変形')
    assert len(signals) == 12 and len(managers) == 7 and len(variants) == 5
    assert set(variants) == {'V000', 'V030', 'V060', 'W030', 'W060'}
    assert fixed['全組合せ数'] == 420 and len(inputs) == 26
    expected = {s + '__' + m + '__' + v for s in signals for m in managers for v in variants}
    all_candidates = unique(candidates, 'id', '全候補')
    assert set(all_candidates) == set(details) == expected and len(expected) == 420
    assert set(summaries) == set(signals)
    same = 0
    for signal_id, signal in signals.items():
        summary = summaries[signal_id]
        assert summary['signal'] == signal and summary['既存結果の再利用'] is False
        part = unique(summary['candidates'], 'id', '入口別候補')
        assert set(part) == {signal_id + '__' + m + '__' + v for m in managers for v in variants}
        assert set(summary['旧管理の全数値と台帳一致']) == {signal_id + '__' + m for m in managers}
        assert len(summary['旧管理の全数値と台帳一致']) == 7
        for identifier, candidate in part.items():
            assert candidate == all_candidates[identifier]
            s, m, v = identifier.split('__')
            base_id = s + '__' + m
            assert (candidate['base_id'], candidate['signal_id'], candidate['manager_id'], candidate['variant_id']) == (base_id, s, m, v)
            assert candidate['signal_family'] == signal['family'] and candidate['manager_family'] == managers[m]['family']
            rows = details[identifier]
            assert len(rows) == 26 and {(r['session'], r['symbol']) for r in rows} == set(inputs)
            for row in rows:
                assert row['id'] == identifier
                assert row['gross_profit_yen'] >= 0 and row['gross_loss_yen'] >= 0 and row['drawdown_yen'] >= 0
                assert abs(row['net_yen'] - row['gross_profit_yen'] + row['gross_loss_yen']) < 1e-6
                assert abs(row['net_yen'] - row['cycle_profit_yen'] + row['cycle_loss_yen']) < 1e-6
                assert row['closed_units'] == row['profit_units'] + row['loss_units'] + row['zero_units']
                assert all(row[field] >= 0 for field in PARTICIPATION_FIELDS)
                quantity = 5 if row['symbol'] == 'TOPIX' else 10
                assert row['closed_units'] == row['opening_orders'] * quantity
                assert row['cycles'] == row['opening_orders']
                assert (row['first_entry_min'] is None) == (row['opening_orders'] == 0)
                assert 0 <= row['max_long'] <= quantity * 2 and 0 <= row['max_short'] <= quantity * 2
                if v == 'V000':
                    prior = old_details[base_id][row['session'], row['symbol']]
                    stripped = {key: value for key, value in row.items() if key not in ('id', 'first_entry_min', *PARTICIPATION_FIELDS)}
                    assert stripped == {key: value for key, value in prior.items() if key != 'id'}
            repeated = runner.diagnostics(rows)
            for symbol in SYMBOLS:
                for field in PARTICIPATION_FIELDS:
                    repeated[symbol][field] = sum(row[field] for row in rows if row['symbol'] == symbol)
            close(candidate['symbols'], repeated, '主結果の明細再集計')
            assert candidate['failures'] == runner.failures(repeated)
            if v == 'V000':
                assert candidate['ledger_hash'] == old_candidates[base_id]['ledger_hash']
                for symbol in SYMBOLS:
                    assert {key: value for key, value in repeated[symbol].items() if key not in PARTICIPATION_FIELDS} == old_candidates[base_id]['symbols'][symbol]
                same += 1
    assert same == 84
    return {'全手法数': 420, '全入力数': 10920, 'V000旧台帳と全数値一致数': 84,
            '全明細再集計一致': True, '全玉収支と枚数整合': True}


def verify_waves(report: dict, fixed: dict, catalog: dict) -> dict:
    """機能: 全420×8の波明細・固定区間・20分目安と要約を検算する。

    引数: report/fixed/catalog (dict)。返り値: 全件波監査 (dict)。
    """
    finite(report)
    methods = unique(report['手法'], 'id', '波対象')
    summaries = unique(report['方法別要約'], 'method', '波要約')
    assert set(methods) == set(summaries) == set(catalog) and len(catalog) == 420
    definitions = unique(fixed['規則']['対象波'], 'id', '波定義')
    assert set(definitions) == {'W01', 'W02', 'W03', 'W04'}
    rows = report['結果']
    assert len(rows) == 3360 and {r['method'] for r in rows} == set(catalog)
    for identifier in catalog:
        selected = [row for row in rows if row['method'] == identifier]
        assert len(selected) == 8 and {(r['wave'], r['symbol']) for r in selected} == {(w, s) for w in definitions for s in SYMBOLS}
        for row in selected:
            definition = definitions[row['wave']]
            assert (row['session'], row['開始'], row['終了'], row['波方向']) == (definition['session'], definition['start'], definition['end'], definition['side'])
            duration = (datetime.fromisoformat(definition['end']) - datetime.fromisoformat(definition['start'])).total_seconds() / 60
            assert abs(row['区間分'] - duration) < 1e-9
            assert 0 <= row['正方向ネット保有分'] <= duration + 1e-8
            assert type(row['正方向ネット20分目安達成']) is bool
            assert row['正方向ネット20分目安達成'] == (row['正方向ネット保有分'] >= 20.)
        summary = summaries[identifier]
        assert summary['対象区間数'] == 8 and summary['目安達成区間数'] == sum(r['正方向ネット20分目安達成'] for r in selected)
    return {'指定波明細数': 3360, '指定波全420件完備': True, '波判定再計算一致': True}


def close(actual: object, expected: object, label: str) -> None:
    """機能: 数値の積分順差だけを許容し、保存内容を再帰照合する。

    引数: actual/expected (object)、label (str)。返り値: なし (None)。
    """
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and set(actual) == set(expected), label + 'のキー不一致'
        for key in expected:
            close(actual[key], expected[key], label + '/' + str(key))
    elif isinstance(expected, (list, tuple)):
        assert isinstance(actual, (list, tuple)) and len(actual) == len(expected), label + 'の件数不一致'
        for i, value in enumerate(expected):
            close(actual[i], value, label + '/' + str(i))
    elif isinstance(expected, (float, int)) and not isinstance(expected, bool):
        assert isinstance(actual, (float, int)) and not isinstance(actual, bool)
        assert math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-6), label + 'の数値不一致'
    else:
        assert actual == expected, label + 'の値不一致'


def verify_participation(report: dict, values: list[dict], catalog: dict, details: dict, inputs: dict) -> dict:
    """機能: 参加量の全明細と全期間・週・対照差の要約を再集計する。

    引数: report/catalog/details/inputs (dict)、values (list[dict])。
    返り値: 全件参加監査 (dict)。原本売買の再生はしない。
    """
    import episode_audit
    finite(report)
    sessions = report['セッション']
    expected = {(name, *key) for name in catalog for key in inputs}
    assert len(sessions) == 10920 and {(r['id'], r['session'], r['symbol']) for r in sessions} == expected
    main = {name: {(r['session'], r['symbol']): r for r in rows} for name, rows in details.items()}
    for row in sessions:
        saved = main[row['id']][row['session'], row['symbol']]
        for name in (*PARTICIPATION_FIELDS, 'first_entry_min'):
            close(row[name], saved[name], '独立参加/' + name)
        for name, value in row['損益'].items():
            close(value, saved[name], '参加元損益/' + name)
        assert all(row[field] >= -1e-8 for field in episode_audit.PARTICIPATION_FIELDS)
        close(row['保有分'] + row['無建玉分'], row['観測分'], '保有と無建玉')
        close(row['初回新規待ち分'] + row['返済後再開待ち分'] + row['最終返済後待ち分'], row['無建玉分'], '無建玉の分解')
        for name in ('入口', '両市場C', '自己S'):
            close(sum(row['方向の時間'][name].values()), row['観測分'], '方向時間合計')
        for en, jp, delta in (('long_unit_minutes', '買い枚数分', '場末後等の区間外買い枚数分'),
                              ('short_unit_minutes', '売り枚数分', '場末後等の区間外売り枚数分')):
            close(row[en], row[jp] + row[delta], '全観測と場内積分')
        assert row['返済枚数'] == saved['closed_units']
    repeated = episode_audit.aggregate_participation(values)
    for key in ('セッション', '週別', '全期間', '対照差', '等重み集計'):
        close(report[key], repeated[key], '参加再集計/' + key)
    assert len(report['全期間']) == 840 and len(report['週別']) == 1680
    assert len(report['対照差']) == 1008 and len(report['等重み集計']) == 84
    assert report['現在保存物使用'] is False and report['API取得数'] == 0
    return {'参加明細数': 10920, '全期間参加数': 840, '開始週集計数': 1680,
            '対応差数': 1008, '等重み要約数': 84, '参加再集計一致': True}


def verify_accounting(report: dict, values: list[dict], catalog: dict, details: dict, inputs: dict) -> dict:
    """機能: 独立会計監査の全420実体と要約・台帳指紋を検算する。

    引数: report/catalog/details/inputs (dict)、values (list[dict])。
    返り値: 全会計監査の件数 (dict)。
    """
    finite(report)
    assert report['全監査合格'] is True and report['対象条件数'] == 420 and report['全入力数'] == 10920
    assert report['V000旧一致条件数'] == 84
    for name in ('全方向保存列一致', '独立参加時間一致', '保存全数値と全台帳SHA一致'):
        assert report[name] is True
    for name in ('現在データ使用', '成績による対象選別', 'ルール変更'):
        assert report[name] is False
    assert report['API取得数'] == 0
    summary = unique(report['条件'], 'id', '独立会計要約')
    full = unique([r for value in values for r in value['全35条件']], 'id', '独立会計全実体')
    assert set(summary) == set(full) == set(catalog) and len(full) == 420
    totals = {'原本行会計数': 0, 'prefix検査数': 0, '未来価格ATR両入力改変数': 0, '買売反射数': 0}
    for name, row in full.items():
        close(summary[name], {k: v for k, v in row.items() if k != 'sessions'}, '会計要約と実体')
        assert row['全入力数'] == 26 and row['保存全数値一致'] is True and row['独立参加時間一致'] is True
        assert row['原本行会計数'] == sum(len(ready['last']) for ready in inputs.values())
        assert row['台帳SHA256'] == catalog[name]['ledger_hash']
        assert row['V000旧一致'] == name.endswith('__V000')
        for field in totals:
            totals[field] += row[field]
        assert all(row[field] == 26 for field in ('prefix検査数', '未来価格ATR両入力改変数', '買売反射数'))
        close(row['symbols'], catalog[name]['symbols'], '独立会計期間集計')
        sessions = row['sessions']
        assert len(sessions) == 26 and {(r['session'], r['symbol']) for r in sessions} == set(inputs)
        main = {(r['session'], r['symbol']): r for r in details[name]}
        for session in sessions:
            expected = main[session['session'], session['symbol']]
            assert set(expected) <= set(session), '独立会計sessionの保存必須項目不足'
            for field, value in expected.items():
                close(session[field], value, '独立会計session/' + field)
    assert totals['原本行会計数'] == report['全原本行会計数']
    for field in ('prefix検査数', '未来価格ATR両入力改変数', '買売反射数'):
        assert totals[field] == report[field] == 10920
    return {'独立会計条件数': 420, '独立会計入力数': 10920,
            '独立会計原本行数': report['全原本行会計数'], '独立会計全実体と要約一致': True}


def verify_chart(report: dict, fixed: dict, catalog: dict, details: dict, inputs: dict) -> dict:
    """機能: 事前固定H019全35条件の910図が欠けず、主収支と一致するか調べる。

    引数: report/fixed/catalog/details/inputs (dict)。返り値: 図示の件数 (dict)。
    """
    methods = {name for name in catalog if name.startswith('H019__')}
    assert len(methods) == 35 and set(report['手法']) == set(fixed['手法']) == methods
    assert len(report['手法']) == 35 and fixed['全入力図数'] == 910
    assert report['採用候補の図示'] is False and report['結果前固定の例示'] is True
    assert report['外部通信'] == 0 and report['現在保存物使用'] is False
    rows = report['保存済み収支との比較']
    assert len(rows) == 910 and {(r['手法'], r['session'], r['symbol']) for r in rows} == {(name, *key) for name in methods for key in inputs}
    main = {name: {(r['session'], r['symbol']): r for r in details[name]} for name in methods}
    for row in rows:
        assert row['保存値一致'] is True
        close(row['収支円'], main[row['手法']][row['session'], row['symbol']]['net_yen'], '図示収支')
    return {'図示条件数': 35, '全図示数': 910, '図示と主結果一致': True}


def collect() -> dict:
    """機能: 主結果・方向・波・参加・独立会計の全資料を読み完備を検算する。

    引数: なし。返り値: 各監査と参照指紋を含む完備証跡 (dict)。
    """
    evidence = run_verified.verify_sources()
    hashes = dict(evidence['参照資料SHA256'])

    def load(path: Path):
        """機能: 資料を指紋付きで読み、監査中の変更を検出可能にする。

        引数: path (Path)。返り値: JSON資料 (dict|list)。
        """
        hashes[path.resolve().as_posix()] = runner.digest(path)
        return runner.read(path)

    fixed = load(HERE / '探索条件の固定.json')
    with (HERE.parent / 'wave_v23/inputs.pkl').open('rb') as source:
        inputs = pickle.load(source)
    launch = load(HERE / '主再生の起動証跡.json')['実行'][-1]
    assert launch['完了'] is True and launch['開始前検査合格'] is True and launch['起動実行'] is True
    assert launch['探索固定SHA256'] == runner.digest(HERE / '探索条件の固定.json')
    assert launch['主再生の完了SHA256'] == runner.digest(HERE / '主再生の完了.json')
    complete = load(HERE / '主再生の完了.json')
    assert complete['全条件数'] == 420 and complete['全入力数'] == 10920 and complete['V000旧84一致'] is True
    assert all(complete[k] is False for k in ('現在データ使用', '新候補選抜', '既存結果の再利用'))
    assert complete['API取得数'] == 0
    candidates = load(HERE / '全条件の期間集計.json.gz')
    catalog = unique(candidates, 'id', '全候補')
    summaries, details, old_candidates, old_details = {}, {}, {}, {}
    for signal in fixed['signals']:
        name = signal['id']
        summaries[name] = load(HERE / 'summaries' / (name + '.json'))
        assert summaries[name]['探索固定SHA256'] == evidence['探索固定SHA256']
        grouped = unique(load(HERE / 'sessions' / (name + '.json.gz')), 'id', '入口別session')
        details.update({key: row['rows'] for key, row in grouped.items()})
        old_candidates.update(unique(load(BASE / 'summaries' / (name + '.json'))['candidates'], 'id', '旧候補'))
        old_details.update({row['id']: {(r['session'], r['symbol']): r for r in row['rows']}
                            for row in load(BASE / 'sessions' / (name + '.json.gz'))})
    main = verify_main(fixed, inputs, candidates, summaries, details, old_candidates, old_details)
    causal = load(HERE / 'lag_causality_before_pnl.json')
    audited = {(r['signal'], r['session'], r['symbol']): r for r in causal['各入力']}
    for signal in fixed['signals']:
        name = signal['id']
        for variant in fixed['variants']:
            arrays = []
            for folder in ('directions', 'contexts', 'contexts_own'):
                path = HERE / folder / (name + '__' + variant['id'] + '.npz')
                hashes[path.resolve().as_posix()] = runner.digest(path)
                with np.load(path) as archive:
                    assert set(archive.files) == {'|'.join(key) for key in inputs}
                    values = {key: archive['|'.join(key)] for key in inputs}
                assert all(a.dtype == np.int8 and len(a) == len(inputs[k]['seq']) and np.isin(a, [-1, 0, 1]).all() for k, a in values.items())
                arrays.append(values)
            assert [runner.array_digest(a) for a in arrays] == summaries[name]['array_hashes'][variant['id']]
            for key in inputs:
                value = hashlib.sha256()
                for lane in arrays:
                    array = lane[key]
                    value.update(str((array.shape, array.dtype)).encode())
                    value.update(array.tobytes())
                assert value.hexdigest() == audited[name, *key]['各変形SHA256'][variant['id']]
    episode_fixed = load(HERE / 'episode_audit_fixed.json')
    episode = load(HERE / 'episode_audit.json')
    assert episode['計測固定SHA256'] == runner.digest(HERE / 'episode_audit_fixed.json')
    assert episode['固定仕様'] == episode_fixed and episode['全入力数'] == 10920
    assert episode['境界損益の独立検算'] == {'全約定からの独立会計一致': True, '比較境界数': 6720}
    assert episode['現在保存物使用'] is False and episode['API取得数'] == 0
    assert episode['ルール変更'] is False and episode['参照コード不変'] is True
    assert episode['参照コードSHA256'] == episode_fixed['参照コードSHA256']
    assert episode['手法'] == episode_fixed['対象仕様']
    waves = verify_waves(episode, episode_fixed, catalog)
    for name, expected in episode_fixed['参照コードSHA256'].items():
        path = HERE.parent / name
        assert runner.digest(path) == expected
        hashes[path.resolve().as_posix()] = expected
    participant_values = [load(HERE / 'episode_participation_details' / (s['id'] + '.json.gz')) for s in fixed['signals']]
    for value in participant_values:
        assert value['計測固定SHA256'] == runner.digest(HERE / 'episode_audit_fixed.json')
        for name, expected in value['保存方向SHA256'].items():
            path = HERE / name
            assert runner.digest(path) == expected
            hashes[path.resolve().as_posix()] = expected
    assert episode['結果'] == [row for value in participant_values for row in value['波']]
    participants = load(HERE / 'participation.json')
    participation = verify_participation(participants, participant_values, catalog, details, inputs)
    accounting_fixed = load(HERE / 'lag_accounting_fixed.json')
    accounting = load(HERE / 'lag_accounting_audit.json')
    assert accounting['監査規則'] == accounting_fixed
    assert accounting['原本78SHA256'] == causal['原本78SHA256'] and accounting['探索固定SHA256'] == fixed['SHA256']
    for path, field in ((HERE / 'lag_accounting_audit.py', 'コードSHA256'),
                        (BASE / 'all_accounting_audit.py', '会計helperSHA256'),
                        (HERE / 'lag_causality_audit.py', '遅延独立helperSHA256'),
                        (HERE / '探索条件の固定.json', '探索固定SHA256')):
        assert runner.digest(path) == accounting_fixed[field]
        hashes[path.resolve().as_posix()] = accounting_fixed[field]
    accounting_values = [load(HERE / 'lag_accounting_details' / (s['id'] + '.json.gz')) for s in fixed['signals']]
    for value in accounting_values:
        for name, expected in value['保存資料SHA256'].items():
            path = Path(name)
            assert runner.digest(path) == expected
            hashes[path.resolve().as_posix()] = expected
    audited_accounting = verify_accounting(accounting, accounting_values, catalog, details, inputs)
    assert episode['全行独立会計数'] == accounting['全原本行会計数']
    chart_fixed = load(HERE / 'chart_fixed.json')
    chart = load(HERE / 'chart_audit.json')
    assert chart['固定SHA256'] == runner.digest(HERE / 'chart_fixed.json')
    assert chart['台帳元SHA256'] == runner.digest(HERE / 'episode_participation_details/H019.json.gz')
    for name, expected in chart_fixed['SHA256'].items():
        path = HERE.parents[1] / name
        assert runner.digest(path) == expected
        hashes[path.resolve().as_posix()] = expected
    chart_result = verify_chart(chart, chart_fixed, catalog, details, inputs)
    chart_data = load(HERE / 'chart_data_audit.json')
    assert chart_data['全図示数'] == 910 and chart_data['図示条件数'] == 35
    assert chart_data['全返済と三帯一致'] is True and chart_data['全リンク有効'] is True
    assert chart_data['API取得数'] == 0 and chart_data['固定SHA256'] == chart['固定SHA256']
    chart_html = HERE.parents[1] / 'アルゴリズム調査/00026_方向情報の鮮度と保有継続/５分足と売買.html'
    assert runner.digest(chart_html) == chart_data['HTML_SHA256']
    hashes[chart_html.resolve().as_posix()] = chart_data['HTML_SHA256']
    chart_result['全返済数'] = chart_data['全返済数']
    for name, expected in hashes.items():
        assert runner.digest(Path(name)) == expected, '監査中の資料変更: ' + name
    return {'診断完了': True, '全条件数': 420, '全入力数': 10920, '指定波区間数': 3360,
            '主結果': main, '指定波': waves, '参加': participation, '会計': audited_accounting, '図示': chart_result,
            '方向保存180ファイルの構造監査指紋一致': True, '参照資料SHA256': hashes,
            '新候補選抜': False, '成績選別': False, '現在データ使用': False, 'API取得数': 0,
            '解釈': '完全性と再集計の監査。未知利益、純粋な鮮度の因果効果、遅延方式の採用は主張しない。'}


def main() -> None:
    """機能: 完備ガードを固定し、全資料が揃った場合だけ完了JSONを保存する。

    引数: --prepare (bool)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    fixed = {'規則': '選別なし全420/10920入力/3360波/独立会計/参加1008対応差/旧84再現/固定35条件910図の全明細と集計を照合。採否の閾値なし。',
             'ガード実装SHA256': runner.digest(Path(__file__)),
             '合成検査SHA256': runner.digest(HERE / 'completion_guard_test.json'),
             '元診断固定SHA256': runner.digest(HERE / 'freshness_diagnostic_fixed.json'),
             '採用規則追加': False}
    path = HERE / 'completion_guard_fixed.json'
    if path.exists():
        assert runner.read(path) == fixed
    else:
        runner.save(path, fixed)
    if args.prepare:
        print('全420の完備ガードを固定。損益未読・売買再生なし。', flush=True)
        return
    result = collect()
    result.update({'確認日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
                   'ガード実装SHA256': fixed['ガード実装SHA256'],
                   'ガード固定SHA256': runner.digest(path)})
    runner.save(HERE / '診断完備の監査.json', result)
    print({k: result[k] for k in ('診断完了', '全条件数', '全入力数', '指定波区間数')}, flush=True)


if __name__ == '__main__':
    main()
