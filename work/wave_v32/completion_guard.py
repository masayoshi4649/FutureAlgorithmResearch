"""全148の台帳・影口座・独立判定・独立監査を結合し、欠けた検証を完了にしない。"""

from __future__ import annotations

from datetime import datetime
import argparse
import hashlib
import json
import math
from pathlib import Path
import pickle
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import numpy as np
import run_verified
import selection_assessment
import selection_judgment
import selection_runner as runner

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SYMBOLS = ('TOPIX', 'NK225')


def finite(value: object) -> None:
    """機能: JSON内の非有限数を拒否し、未定義価格のNoneは区別する。

    引数: value (object)。返り値: なし (None)。
    """
    if isinstance(value, dict):
        for item in value.values():
            finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            finite(item)
    elif isinstance(value, float):
        assert math.isfinite(value), '非有限数を含む'


def close(actual: object, expected: object, label: str) -> None:
    """機能: 全項目・型を照合し、演算順の小さな丸め差だけ許容する。

    引数: actual/expected (object)、label (str)。返り値: なし (None)。
    """
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and set(actual) == set(expected), label + 'キー不一致'
        for key in expected:
            close(actual[key], expected[key], label + '/' + str(key))
    elif isinstance(expected, (list, tuple)):
        assert isinstance(actual, (list, tuple)) and len(actual) == len(expected), label + '件数不一致'
        for i, value in enumerate(expected):
            close(actual[i], value, label + '/' + str(i))
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert isinstance(actual, (int, float)) and not isinstance(actual, bool)
        assert math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-6), label + '数値不一致'
    else:
        assert actual == expected, label + '値不一致'


def keyed(rows: list[dict], fields: tuple[str, ...], label: str) -> dict:
    """機能: 重複を拒否して全明細を複合キーへ変換する。

    引数: rows (list[dict])、fields (tuple[str,...])、label (str)。返り値: 明細対応 (dict)。
    """
    values = {tuple(row[f] for f in fields): row for row in rows}
    assert len(values) == len(rows), label + '重複'
    return values


def verify_summary(candidate: dict, rows: list[dict], fixed: dict, inputs: dict) -> None:
    """機能: 一方式26区間の集合・会計尺度・全13と共通7の再集計を照合する。

    引数: candidate/fixed/inputs (dict)、rows (list[dict])。返り値: なし (None)。
    """
    finite([candidate, rows])
    assert len(rows) == 26 and set(keyed(rows, ('session', 'symbol'), 'session')) == set(inputs)
    assert all(row['id'] == candidate['id'] for row in rows)
    for row in rows:
        assert row['gross_profit_yen'] >= 0 and row['gross_loss_yen'] >= 0 and row['drawdown_yen'] >= 0
        close(row['net_yen'], row['gross_profit_yen'] - row['gross_loss_yen'], '全玉利益損失')
        close(row['net_yen'], row['cycle_profit_yen'] - row['cycle_loss_yen'], '全売買組')
        assert row['closed_units'] == row['profit_units'] + row['loss_units'] + row['zero_units']
        quantity = 5 if row['symbol'] == 'TOPIX' else 10
        assert row['closed_units'] == row['opening_orders'] * quantity and row['cycles'] == row['opening_orders']
        assert 0 <= row['max_long'] <= quantity * 2 and 0 <= row['max_short'] <= quantity * 2
        selection = row['selection']
        assert set(selection['branch_opening_orders']) == {'T', 'R'}
        assert sum(selection['branch_opening_orders'].values()) == row['opening_orders']
        assert sum(selection['branch_closed_units'].values()) == row['closed_units']
        for field, original in (('branch_net_yen', 'net_yen'), ('branch_profit_yen', 'gross_profit_yen'), ('branch_loss_yen', 'gross_loss_yen')):
            close(sum(selection[field].values()), row[original], '枝合計/' + field)
    close(candidate['all_symbols'], runner.periods(rows, fixed['全セッション']), '全13期間再集計')
    close(candidate['symbols'], runner.periods(rows, fixed['共通評価7セッション']), '主7期間再集計')


def verify_ledger(candidate: dict, rows: list[dict], records: list[dict], inputs: dict, fixed: dict) -> dict:
    """機能: 保存全玉台帳から金額・枚数・参加・実入口枝を再構成する。

    引数: candidate/inputs/fixed (dict)、rows/records (list[dict])。
    返り値: 台帳件数 (dict)。注文器を再実行しない。
    """
    finite(records)
    indexed = keyed(rows, ('session', 'symbol'), 'session')
    ledgers = keyed(records, ('session', 'symbol'), '台帳')
    assert len(records) == 26 and set(ledgers) == set(inputs)
    fingerprint = hashlib.sha256()
    trade_count = order_count = 0
    event_columns = {name: i for i, name in enumerate(runner.engine_selector.EVENT_COLUMNS)}
    for key, ready in inputs.items():
        item, row = ledgers[key], indexed[key]
        config = runner.managers.make_config(fixed['manager'], key[1], ready)
        assert item['config'] == config
        arrays = {'trades': np.asarray(item['trades'], float).reshape(-1, 11),
                  'orders': np.asarray(item['orders'], float).reshape(-1, 8),
                  'cycles': np.asarray(item['cycles'], float).reshape(-1, 10),
                  'stats': np.asarray(item['stats'], float)}
        repeated = runner.research.summarize(arrays, config, key[1], key[0], candidate['id'])
        repeated['two_largest_cycle_profits'] = sorted([float(v) * config['point_value'] for v in arrays['cycles'][:, 3] if v > 0], reverse=True)[:2]
        repeated.update(runner.previous.participation(arrays, ready))
        assert set(repeated) <= set(row)
        for field, value in repeated.items():
            close(row[field], value, '台帳再集計/' + field)
        fingerprint.update(str(key).encode())
        fingerprint.update(arrays['trades'].tobytes())
        events = np.asarray(item['selection_events'], float).reshape(-1, len(event_columns))
        assert not np.isinf(events).any()
        event_counts = {name: int(np.sum(events[:, event_columns['event']] == code)) for code, name in runner.engine_selector.EVENT_NAMES.items()}
        assert event_counts == row['selection']['event_counts']
        openings = events[events[:, event_columns['event']] == 7]
        assert len(openings) == row['opening_orders']
        origins = {int(event[event_columns['campaign']]): int(event[event_columns['entry_source_id']]) for event in openings}
        assert len(origins) == len(openings) and set(origins.values()) <= {1, 2}
        for number, branch in ((1, 'T'), (2, 'R')):
            branch_trades = arrays['trades'][np.array([origins[int(trade[0])] == number for trade in arrays['trades']], bool)]
            pnl = branch_trades[:, 10] * config['point_value']
            actual = {'branch_opening_orders': sum(v == number for v in origins.values()),
                      'branch_net_yen': float(pnl.sum()), 'branch_profit_yen': float(pnl[pnl > 1e-6].sum()),
                      'branch_loss_yen': float(-pnl[pnl < -1e-6].sum()), 'branch_closed_units': int(branch_trades[:, 3].sum())}
            for field, value in actual.items():
                close(row['selection'][field][branch], value, '所有台帳からの実入口/' + field)
        trade_count += len(arrays['trades'])
        order_count += len(arrays['orders'])
    assert fingerprint.hexdigest() == candidate['ledger_hash']
    return {'全入力数': 26, '返済脚数': trade_count, '全注文数': order_count, '台帳指紋と全項目再集計一致': True}


def verify_judgment(candidates: list[dict], details: dict, fixed: dict, reported: dict) -> dict:
    """機能: 最大勝ち組を別経路で計算し、主A/Bと全反証の判定を独立照合する。

    引数: candidates (list[dict])、details/fixed/reported (dict)。返り値: 独立判定証跡 (dict)。
    """
    independent = selection_assessment.assess(candidates, details, fixed)
    rebuilt = selection_judgment.judge(candidates)
    close(reported, rebuilt, '主判定実装の再計算')
    assert reported['全条件数'] == 148
    own = {row['id']: row for row in independent['結果']}
    assert len(reported['全対応比較']) == 148 and {r['id'] for r in reported['全対応比較']} == set(own)
    for row in reported['全対応比較']:
        check = own[row['id']]
        assert bool(row['最低目安未達']) == (not check['一次目安通過'])
        assert bool(row['T比の工学目標未達銘柄']) == (not check['Tへの工学目標通過'])
    assert {r['id'] for r in reported['主判定']} == {'S002', 'S003'} and len(reported['主判定']) == 2
    for row in reported['主判定']:
        check = own[row['id']]
        assert row['一次目安と追加価値の条件を充足'] == check['主方式の目安合格']
        assert bool(row['選択の稼働不足']) == (not check['選択実稼働確認'])
        assert set(row['両市場で支配する対照']) == {k for k, v in check['固定対照との関係'].items() if v == '対照がPareto支配'}
        assert set(row['4値が同一の対照']) == {k for k, v in check['固定対照との関係'].items() if v == '全4値同等'}
        assert row['乱数対照']['対照数'] == 64 and row['乱数対照']['正式p値ではない'] is True and row['乱数対照']['最良seed採用'] is False
    return {'全148判定一致': True, '主A_B独立判定一致': True,
            '主の目安合格ID': independent['主の目安合格ID'], '最大1勝ち組の別経路一致': True}


def verify_waves(report: dict, definitions: list[dict], identifiers: set) -> dict:
    """機能: 全148×8の指定波が欠けず、20分目安と要約が整合するか確かめる。

    引数: report (dict)、definitions (list[dict])、identifiers (set[str])。
    返り値: 波完備監査 (dict)。波は主評価採否に追加しない。
    """
    rows = report['結果']
    waves = {r['id']: r for r in definitions}
    assert set(waves) == {'W01', 'W02', 'W03', 'W04'} and len(definitions) == 4
    expected = {(name, wave, symbol) for name in identifiers for wave in waves for symbol in SYMBOLS}
    assert len(rows) == 1184 and set(keyed(rows, ('method', 'wave', 'symbol'), '波')) == expected
    assert len(report['手法']) == 148 and {r['id'] for r in report['手法']} == identifiers
    summary = keyed(report['方法別要約'], ('method',), '波要約')
    assert set(summary) == {(name,) for name in identifiers}
    for row in rows:
        wave = waves[row['wave']]
        assert (row['session'], row['開始'], row['終了'], row['波方向']) == (wave['session'], wave['start'], wave['end'], wave['side'])
        minutes = (datetime.fromisoformat(wave['end']) - datetime.fromisoformat(wave['start'])).total_seconds() / 60
        close(row['区間分'], minutes, '波の固定分数')
        assert 0 <= row['正方向ネット保有分'] <= minutes + 1e-8
        assert row['正方向ネット20分目安達成'] == (row['正方向ネット保有分'] >= 20)
    for identifier in identifiers:
        selected = [r for r in rows if r['method'] == identifier]
        assert summary[identifier,]['対象区間数'] == 8
        assert summary[identifier,]['目安達成区間数'] == sum(r['正方向ネット20分目安達成'] for r in selected)
    return {'全148方式の指定波1184完備': True, '20分判定と要約再集計一致': True}


def collect_main(load, check) -> dict:
    """機能: 主再生全148・入口と要求・固定影口座を選別せず検査する。

    引数: load/check (callable) は指紋付き読取りと指紋照合。
    返り値: 後続監査に使う全資料と主検査結果 (dict)。
    """
    fixed = load(HERE / '探索条件の固定.json')
    protocol = load(HERE / 'selection_fixed.json')
    with (HERE.parent / 'wave_v23/inputs.pkl').open('rb') as source:
        inputs = pickle.load(source)
    evidence = load(HERE / '主再生の起動証跡.json')['実行'][-1]
    assert evidence['完了'] is True and evidence['実行可能'] is True
    check(HERE / '探索条件の固定.json', evidence['探索固定SHA256'])
    check(HERE / '主再生の完了.json', evidence['主再生の完了SHA256'])
    complete = load(HERE / '主再生の完了.json')
    assert complete['全条件数'] == 148 and complete['全入力数'] == 3848
    assert complete['現在データ使用'] is False and complete['API取得数'] == 0 and complete['既存結果の再利用'] is False
    assert complete['探索固定SHA256'] == runner.digest(HERE / '探索条件の固定.json')
    candidates = load(HERE / '全条件の期間集計.json.gz')
    index = keyed(candidates, ('id',), '全候補')
    specs = {s['id']: s for s in fixed['conditions']}
    assert len(candidates) == 148 and set(index) == {(name,) for name in specs}
    assert fixed['conditions'] == protocol['条件']
    for folder, suffix in (('summaries', '.json'), ('sessions', '.json.gz'), ('ledgers', '.json.gz'),
                           ('requests', '.npz'), ('requests', '.json.gz')):
        assert {p.name for p in (HERE / folder).glob('*' + suffix)} == {name + suffix for name in specs}, folder + '全対象の不足又は余分な資料'
    causal = load(HERE / 'selector_causality_before_pnl.json')
    entries_hash = load(HERE / 'entries_hash.json')
    assert entries_hash == causal['入口配列SHA256']
    check(HERE / 'entries.npz')
    with np.load(HERE / 'entries.npz') as archive:
        assert set(archive.files) == {f'{b}|{k[0]}|{k[1]}' for b in ('T', 'R') for k in inputs}
        entries = {b: {k: archive[f'{b}|{k[0]}|{k[1]}'] for k in inputs} for b in ('T', 'R')}
    for branch, values in entries.items():
        assert runner.array_hash(values) == entries_hash[branch]
        assert all(v.dtype == np.int8 and len(v) == len(inputs[k]['seq']) and np.isin(v, [-1, 0, 1]).all() for k, v in values.items())
    delayed_hashes = {0: entries_hash}
    for seconds in (1, 5, 15):
        delayed_hashes[seconds] = {}
        for branch, values in entries.items():
            delayed = {}
            for key, ready in inputs.items():
                times = ready['time_s']
                source_index = np.searchsorted(times, times - seconds, side='right') - 1
                valid = source_index >= 0
                assert np.all(source_index[valid] < np.flatnonzero(valid))
                output = np.zeros(len(times), np.int8)
                output[valid] = values[key][source_index[valid]]
                delayed[key] = output
            delayed_hashes[seconds][branch] = runner.array_hash(delayed)
    details, trade_count, order_count = {}, 0, 0
    for candidate in candidates:
        name = candidate['id']
        assert candidate == load(HERE / 'summaries' / (name + '.json'))
        assert candidate['spec'] == specs[name] and candidate['既存結果の再利用'] is False
        assert candidate['探索固定SHA256'] == evidence['探索固定SHA256']
        rows = load(HERE / 'sessions' / (name + '.json.gz'))
        details[name] = rows
        verify_summary(candidate, rows, fixed, inputs)
        ledger = verify_ledger(candidate, rows, load(HERE / 'ledgers' / (name + '.json.gz')), inputs, fixed)
        trade_count += ledger['返済脚数']
        order_count += ledger['全注文数']
        check(HERE / 'requests' / (name + '.npz'))
        with np.load(HERE / 'requests' / (name + '.npz')) as archive:
            assert set(archive.files) == {'|'.join(key) for key in inputs}
            requests = {key: archive['|'.join(key)] for key in inputs}
        assert all(v.dtype == np.int8 and len(v) == len(inputs[k]['seq']) and np.isin(v, [1, 2]).all() for k, v in requests.items())
        assert runner.array_hash(requests) == candidate['request_hash']
        assert candidate['entries_hash'] == delayed_hashes[specs[name]['delay_seconds']]
        logs = load(HERE / 'requests' / (name + '.json.gz'))
        finite(logs)
        assert {r['session'] for r in logs} == set(fixed['全セッション'])
    shadow = load(HERE / 'shadow_rows.json')
    assert len(shadow) == 52 and set(keyed(shadow, ('session', 'symbol', 'branch'), '影口座')) == {(*key, b) for key in inputs for b in ('T', 'R')}
    fixed_rows = {b: keyed(details[name], ('session', 'symbol'), '影口座元') for name, b in (('S000', 'T'), ('S001', 'R'))}
    for row in shadow:
        key = row['session'], row['symbol']
        assert row['complete'] is True and row['completed_at'] == inputs[key]['time_s'][-1] > inputs[key]['limit']
        close(row['net_yen'], fixed_rows[row['branch']][key]['net_yen'], '影口座元台帳収支')
    old_rows = next(r['rows'] for r in load(HERE.parent / 'wave_v31/sessions/H019.json.gz') if r['id'] == 'H019__L000__V000')
    old = keyed(old_rows, ('session', 'symbol'), '旧固定T')
    for row in details['S000']:
        for name, value in old[row['session'], row['symbol']].items():
            if name != 'id':
                close(row[name], value, '旧固定T/' + name)
    old_summary = next(r for r in load(HERE.parent / 'wave_v31/summaries/H019.json')['candidates'] if r['id'] == 'H019__L000__V000')
    assert index['S000',]['ledger_hash'] == old_summary['ledger_hash']
    judgments = verify_judgment(candidates, details, fixed, load(HERE / '選択の判定.json'))
    return {'fixed': fixed, 'protocol': protocol, 'inputs': inputs, 'candidates': candidates, 'details': details,
            '主監査': {'全条件数': 148, '全入力数': 3848, '共通主評価入力数': 2072,
                      '旧固定T一致入力数': 26, '影口座元台帳一致数': 52,
                      '全返済脚数': trade_count, '全注文数': order_count,
                      '入口と要求の全指紋一致': True, '全13と主7の全数値再集計一致': True},
            '独立判定': judgments}


# ----------------------------------------
def subset_equal(actual: dict, expected: dict, label: str) -> None:
    """機能: 必須項目の欠落を拒否して全保存値を比較する。

    引数: actual/expected (dict)、label (str)。返り値: なし (None)。
    """
    assert set(expected) <= set(actual), label + '必須項目欠落'
    for name, value in expected.items():
        close(actual[name], value, label + '/' + name)


def verify_accounting_record(record: dict, candidate: dict, main_rows: list[dict], inputs: dict) -> None:
    """機能: 一方式の独立会計に26入力・全保存項目・未来検査が揃うことを確認する。

    引数: record/candidate/inputs (dict)、main_rows (list[dict])。返り値: なし (None)。
    """
    assert record['id'] == candidate['id'] and record['全入力数'] == len(inputs)
    assert record['原本行会計数'] == sum(len(v['last']) for v in inputs.values())
    for name in ('prefix検査数', '未来価格ATR両入口要求改変数', '買売反射数'):
        assert record[name] == len(inputs)
    for name in ('全要求再生成一致', '保存全数値一致', '独立参加時間一致', '全台帳配列一致'):
        assert record[name] is True
    for target, source in (('台帳SHA256', 'ledger_hash'), ('要求SHA256', 'request_hash'), ('入口SHA256', 'entries_hash')):
        assert record[target] == candidate[source]
    independent = keyed(record['sessions'], ('session', 'symbol'), '独立会計')
    assert set(independent) == set(inputs)
    for row in main_rows:
        key = row['session'], row['symbol']
        observed = independent[key]
        subset_equal(observed, {k: v for k, v in row.items() if k != 'selection'}, '独立会計保存全項目')
        assert observed['検算した観測行数'] == len(inputs[key]['last'])
        for name in ('prefix検査合格', '未来改変合格', '買売反射合格', '全台帳配列一致', '選択曲線SHA一致'):
            assert observed[name] is True
    for period in ('all_symbols', 'symbols'):
        for symbol in SYMBOLS:
            subset_equal(record[period][symbol], {k: v for k, v in candidate[period][symbol].items() if k != 'selection'}, '独立期間集計')


def collect_accounting(context: dict, load, check) -> dict:
    """機能: 全148の独立会計実体・件数・元資料指紋を結合する。

    引数: context (dict)、load/check (callable)。返り値: 会計監査概要 (dict)。
    """
    fixed = load(HERE / 'selector_accounting_fixed.json')
    report = load(HERE / 'selector_accounting_audit.json')
    assert report['全監査合格'] is True and report['対象条件数'] == 148 and report['全入力数'] == 3848
    assert report['監査規則'] == fixed
    assert report['合成検査'] == load(HERE / 'selector_accounting_selftest.json')
    assert report['合成検査']['合成合格'] is True and report['合成検査']['合成組合せ数'] == 6
    assert report['影口座監査'] == load(HERE / 'selector_shadow_accounting.json')
    shadow = report['影口座監査']
    assert shadow['影口座元台帳一致'] is True and shadow['照合行数'] == 52
    assert set(keyed(shadow['rows'], ('session', 'symbol', 'branch'), '影口座独立会計')) == {
        (*key, branch) for key in context['inputs'] for branch in ('T', 'R')}
    assert all(r['元約定損益一致'] is True and r['完了と最終残玉一致'] is True for r in shadow['rows'])
    candidates = {r['id']: r for r in context['candidates']}
    assert fixed['対象条件ID'] == sorted(candidates) and fixed['対象条件数'] == 148 and fixed['対象入力数'] == 26
    assert {p.name for p in (HERE / 'selector_accounting_details').glob('*.json.gz')} == {name + '.json.gz' for name in candidates}
    check(HERE / '探索条件の固定.json', report['探索固定SHA256'])
    assert fixed['探索固定SHA256'] == report['探索固定SHA256']
    for name, expected in fixed['参照SHA256'].items():
        check(ROOT / name, expected)
    causal = load(HERE / 'selector_causality_before_pnl.json')
    assert report['原本78SHA256'] == causal['原本78SHA256']
    assert report['参照SHA256'] == context['fixed']['SHA256']
    assert report['事前因果監査参照SHA256'] == causal['参照SHA256']
    for group in ('原本78SHA256', '参照SHA256', '事前因果監査参照SHA256', '保存入力SHA256'):
        for name, expected in report[group].items():
            check(ROOT / name, expected)
    summaries = keyed(report['条件'], ('id',), '独立会計全条件')
    assert set(summaries) == {(name,) for name in candidates}
    for identifier, candidate in candidates.items():
        record = load(HERE / 'selector_accounting_details' / (identifier + '.json.gz'))
        verify_accounting_record(record, candidate, context['details'][identifier], context['inputs'])
        close(summaries[identifier,], {k: v for k, v in record.items() if k not in ('sessions', '保存資料SHA256')}, '会計明細と全体要約')
        for name, expected in record['保存資料SHA256'].items():
            check(ROOT / name, expected)
    raw_count = sum(len(v['last']) for v in context['inputs'].values())
    assert report['一条件原本行数'] == raw_count and report['全原本行会計数'] == raw_count * 148
    for name in ('prefix検査数', '未来価格ATR両入口要求改変数', '買売反射数'):
        assert report[name] == 3848
    for name in ('全要求再生成一致', '影口座元台帳一致', '全入口事前監査一致', '保存全数値と全台帳SHA一致', '独立参加時間一致'):
        assert report[name] is True
    assert report['旧固定T一致区間数'] == 26 and report['API取得数'] == 0
    for name in ('現在データ使用', '成績による対象選別', 'ルール変更'):
        assert report[name] is False
    return {'全入力数': 3848, '全原本行会計数': raw_count * 148, 'prefix検査数': 3848,
            '未来変更検査数': 3848, '上下反射検査数': 3848, '全保存項目と独立会計一致': True}


def verify_participation_row(row: dict, main: dict, ready: dict) -> None:
    """機能: 参加時間・所有条件・注文数を独立資料と主台帳の間で検算する。

    引数: row/main/ready (dict)。返り値: なし (None)。
    """
    close(row['selection'], main['selection'], '全選択明細')
    for name in ('long_unit_minutes', 'short_unit_minutes', 'opening_orders', 'first_entry_min'):
        close(row[name], main[name], '全参加項目/' + name)
    assert row['観測行数'] == len(ready['last'])
    duration = (min(float(ready['time_s'][-1]), float(ready['limit'])) - float(ready['start'])) / 60
    # 開始直後に観測がない期間は集計対象にしない。
    duration -= max(0., (float(ready['time_s'][0]) - float(ready['start'])) / 60)
    close(row['観測分'], duration, '観測時間')
    close(row['held_minutes'] + row['flat_minutes'], duration, '保有と未保有')
    for name in ('actual_entry_source_minutes', 'position_owner_minutes', 'pending_owner_minutes', 'position_source_minutes'):
        close(sum(row[name].values()), duration, name)
        assert all(v >= -1e-7 for v in row[name].values())
    for name in ('request_minutes', 'applied_minutes'):
        close(sum(row['selection'][name].values()), duration, name)
    for name in ('全行所有一致', '取消順序一致', '5分休止一致', '場内全返済'):
        assert row['所有監査'][name] is True
    events = row['selection']['event_counts']
    close(row['所有監査']['所有検査新規数'], events['新規約定'], '所有新規数')
    close(row['所有監査']['完全返済数'], events['完全返済'], '所有完了数')
    close(row['所有監査']['新規準備数'], events['新規準備'] + events['切替後再準備'], '所有準備数')
    close(row['所有監査']['取消要求確認数'], events['取消確認'], '所有取消数')


def participation_totals(rows: list[dict], context: dict) -> tuple[list, list, list]:
    """機能: 所有明細を期間と場間境界へ再集計し、初期6→主評価7の変更も数える。

    引数: rows (list[dict])、context (dict)。返り値: 全期間・主7・境界 (tuple)。
    """
    full, evaluation, boundaries = [], [], []
    dicts = ('actual_entry_source_minutes', 'position_owner_minutes', 'pending_owner_minutes', 'position_source_minutes')
    numbers = ('long_unit_minutes', 'short_unit_minutes', '場内買い枚数分', '場内売り枚数分', 'held_minutes', 'flat_minutes', 'opening_orders', '観測分')
    fixed = context['fixed']
    for candidate in context['candidates']:
        for symbol in SYMBOLS:
            history = sorted((r for r in rows if r['id'] == candidate['id'] and r['symbol'] == symbol), key=lambda r: r['session'])
            assert len(history) == 13
            local_boundaries = []
            for before, after in zip(history, history[1:]):
                local_boundaries.append({'id': candidate['id'], 'symbol': symbol, '前session': before['session'], '次session': after['session'],
                    '前最終applied': before['selection']['last_applied_id'], '次初回applied': after['selection']['first_applied_id'],
                    '適用変更': before['selection']['last_applied_id'] != after['selection']['first_applied_id'],
                    '主評価へ算入': after['session'] in fixed['共通評価7セッション']})
            boundaries.extend(local_boundaries)
            for label, sessions, target, source in (('全13区間', fixed['全セッション'], full, 'all_symbols'),
                                                     ('共通評価7区間', fixed['共通評価7セッション'], evaluation, 'symbols')):
                members = [r for r in history if r['session'] in sessions]
                selection = {}
                for name in members[0]['selection']:
                    if name not in ('first_applied_id', 'last_applied_id'):
                        selection[name] = {k: sum(r['selection'][name][k] for r in members) for k in members[0]['selection'][name]}
                selection['between_session_applied_switches'] = sum(r['適用変更'] for r in local_boundaries if r['次session'] in sessions)
                selection['within_session_applied_switches'] = selection['event_counts']['適用変更']
                close(selection, candidate[source][symbol]['selection'], '期間選択独立再集計')
                target.append({'id': candidate['id'], 'symbol': symbol, '区間': label, 'selection': selection,
                    **{name: sum(r[name] for r in members) for name in numbers},
                    **{name: {k: sum(r[name][k] for r in members) for k in members[0][name]} for name in dicts}})
    return full, evaluation, boundaries


def collect_participation(context: dict, load, check) -> dict:
    """機能: 全148の所有・参加・全1184波・期間境界を一意集合で検算する。

    引数: context (dict)、load/check (callable)。返り値: 波と参加の検査結果 (dict)。
    """
    fixed = load(HERE / 'episode_audit_fixed.json')
    design = load(HERE / 'selection_participation_fixed.json')
    assert fixed['規則'] == design and fixed['手法'] == context['fixed']['conditions']
    assert fixed['全条件数'] == 148 and fixed['全入力数'] == 3848 and fixed['全指定波数'] == 1184
    check(HERE / 'selection_participation_fixed.json', fixed['計測設計SHA256'])
    check(HERE / '探索条件の固定.json', design['探索固定SHA256'])
    for group in (fixed['参照コードSHA256'], design['参照SHA256']):
        for name, expected in group.items():
            check(ROOT / name, expected)
    tests = load(HERE / 'selection_ownership_test.json')
    assert tests['全合格'] is True and tests['正常経路一致'] is True and tests['破損拒否件数'] == 6
    assert len(tests['検査']) == 6 and all(r['拒否'] is True for r in tests['検査'])
    assert tests['API取得数'] == 0 and tests['実相場再生'] is False
    check(HERE / 'episode_audit.py', tests['監査実装SHA256'])
    report = load(HERE / 'participation.json')
    ownership = load(HERE / 'selection_ownership_audit.json')
    waves = load(HERE / 'episode_audit.json')
    for value in (report, ownership, waves):
        check(HERE / 'episode_audit_fixed.json', value['計測固定SHA256'])
    assert waves['固定仕様'] == fixed and waves['手法'] == fixed['手法']
    assert waves['全入力数'] == 3848 and waves['API取得数'] == 0 and waves['現在保存物使用'] is False
    ids = {r['id'] for r in context['candidates']}
    assert {p.name for p in (HERE / 'selection_participation_details').glob('*.json.gz')} == {name + '.json.gz' for name in ids}
    participants, episodes, boundaries = [], [], 0
    for candidate in context['candidates']:
        identifier = candidate['id']
        detail = load(HERE / 'selection_participation_details' / (identifier + '.json.gz'))
        assert detail['id'] == identifier and detail['spec'] == candidate['spec']
        assert detail['計測固定SHA256'] == report['計測固定SHA256']
        for name, expected in detail['保存資料SHA256'].items():
            check(HERE / name, expected)
        rows = keyed(detail['参加'], ('session', 'symbol'), '独立所有')
        assert set(rows) == set(context['inputs'])
        main = keyed(context['details'][identifier], ('session', 'symbol'), '主参加')
        for key, row in rows.items():
            assert row['id'] == identifier
            verify_participation_row(row, main[key], context['inputs'][key])
        participants.extend(detail['参加'])
        episodes.extend(detail['波'])
        assert detail['境界独立検算']['全約定からの独立会計一致'] is True
        assert detail['境界独立検算']['比較境界数'] == 16
        boundaries += 16
    close(keyed(report['セッション'], ('id', 'session', 'symbol'), '参加全体'),
          keyed(participants, ('id', 'session', 'symbol'), '参加実体'), '全参加集合')
    close(keyed(waves['結果'], ('method', 'wave', 'symbol'), '波全体'),
          keyed(episodes, ('method', 'wave', 'symbol'), '波実体'), '全波集合')
    verify_waves(waves, fixed['対象'], ids)
    all_period, evaluation, between = participation_totals(participants, context)
    close(report['全期間'], all_period, '参加全期間再集計')
    close(report['評価期間'], evaluation, '参加共通7再集計')
    close(report['セッション境界'], between, '参加場間境界')
    assert len(all_period) == len(evaluation) == 296 and len(between) == 3552
    assert waves['境界損益の独立検算'] == {'全約定からの独立会計一致': True, '比較境界数': boundaries}
    for name in ('全合格', '主selection全一致', '所有不変全一致', '取消順序全一致', '期間境界全一致'):
        assert ownership[name] is True
    assert ownership['全条件数'] == 148 and ownership['全入力数'] == 3848 and ownership['境界比較数'] == 3552
    assert ownership['全行所有数'] == 148 * sum(len(v['last']) for v in context['inputs'].values())
    for name in ('所有検査新規数', '取消要求確認数', '新規準備数', '完全返済数'):
        assert ownership[name] == sum(r['所有監査'][name] for r in participants)
    assert ownership['API取得数'] == 0 and ownership['現在保存物使用'] is False
    return {'全参加入力数': 3848, '全指定波数': 1184, '全波境界数': boundaries, '全期間境界数': 3552,
            '所有と選択時間と全枝損益一致': True, '全指定波は初期6区間': True}


class ChartExtractor(HTMLParser):
    """機能: 図JSONとリンクを抽出し、重複した要素IDを拒否する。

    引数: feedへHTML (str)。返り値: data/links (str/list[str])。
    """

    def __init__(self) -> None:
        """機能: HTML抽出状態を初期化する。

        引数: なし。返り値: なし (None)。
        """
        super().__init__()
        self.active, self.data, self.links, self.ids = False, '', [], set()

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """機能: 図JSON開始とリンクを記録する。

        引数: tag (str)、attrs (list)。返り値: なし (None)。
        """
        values = dict(attrs)
        if values.get('id'):
            assert values['id'] not in self.ids, 'HTML要素ID重複'
            self.ids.add(values['id'])
        if tag == 'script' and values.get('id') == 'chart-data':
            self.active = True
        if tag == 'a' and values.get('href'):
            self.links.append(values['href'])

    def handle_endtag(self, tag: str) -> None:
        """機能: 図JSONの終端を認識する。

        引数: tag (str)。返り値: なし (None)。
        """
        if tag == 'script':
            self.active = False

    def handle_data(self, value: str) -> None:
        """機能: 図JSONを蓄積する。

        引数: value (str)。返り値: なし (None)。
        """
        if self.active:
            self.data += value


def collect_charts(context: dict, load, check) -> dict:
    """機能: 主6方式の全156図・全返済・状態帯を保存台帳とHTMLへ結び付ける。

    引数: context (dict)、load/check (callable)。返り値: 図の監査結果 (dict)。
    """
    fixed = load(HERE / 'chart_fixed.json')
    audit = load(HERE / 'chart_audit.json')
    data_audit = load(HERE / 'chart_data_audit.json')
    ids = [r['id'] for r in context['fixed']['conditions'] if r['role'] == 'primary']
    assert ids == fixed['手法'] == audit['手法'] and len(ids) == 6
    assert audit['全図示数'] == data_audit['全図示数'] == fixed['全図示数'] == 156
    for name in ('全収支一致', '全返済一致', '全新規一致', '状態帯一致'):
        assert audit[name] is True
    for name in ('全返済一致', '全新規一致', '三帯一致', 'ローカルリンク全有効'):
        assert data_audit[name] is True
    for value in (audit, data_audit):
        assert value['API取得数'] == 0 and value['現在保存物使用'] is False
    check(HERE / 'chart_fixed.json', audit['固定SHA256'])
    check(HERE / 'chart_fixed.json', data_audit['chart_fixed_SHA256'])
    for name, expected in fixed['SHA256'].items():
        check(ROOT / name, expected)
    for name, expected in audit['台帳元SHA256'].items():
        check(HERE / name, expected)
    html = ROOT / 'アルゴリズム調査/00027_順張りと反転の機械的選択/５分足と売買.html'
    check(html, data_audit['HTML_SHA256'])
    check(HERE / 'chart_data_audit.py')
    parser = ChartExtractor()
    parser.feed(html.read_text(encoding='utf-8'))
    payload = json.loads(parser.data)
    finite(payload)
    keys = {name + '|' + '|'.join(key) for name in ids for key in context['inputs']}
    assert set(payload['trades']) == set(payload['states']) == keys
    chart_rows = keyed(audit['保存済み収支との比較'], ('id', 'session', 'symbol'), '全図比較')
    assert set(chart_rows) == {(name, *key) for name in ids for key in context['inputs']}
    trades = orders = 0
    for name in ids:
        detail = load(HERE / 'selection_participation_details' / (name + '.json.gz'))
        diagrams = keyed(detail['図示用'], ('session', 'symbol'), '全図実体')
        assert set(diagrams) == set(context['inputs'])
        main_rows = keyed(context['details'][name], ('session', 'symbol'), '図主集計')
        for key, row in diagrams.items():
            saved = payload['trades'][name + '|' + '|'.join(key)]
            assert len(saved) == len(row['全返済'])
            for actual, expected in zip(saved, row['全返済']):
                first, last = (datetime.fromisoformat(expected[n]).timestamp() for n in ('新規時刻', '返済時刻'))
                close(actual[:7], [first, last, expected['direction'], expected['枚数'], expected['新規価格'], expected['返済価格'], expected['損益円']], 'HTML全返済')
                assert actual[7] == runner.engine_selector.REASONS[expected['返済理由番号']]
                labels = {1: 'T', 2: 'R'}
                assert actual[8] == '所有' + labels[expected['所有ID']] + '／入口' + labels[expected['実入口源ID']]
                assert actual[9:] == [expected['新規行'], expected['返済行']]
            close(payload['states'][name + '|' + '|'.join(key)], row['状態'], 'HTML三帯')
            record = chart_rows[(name, *key)]
            assert record['保存値一致'] is True and record['返済件数'] == len(saved)
            close(record['収支円'], main_rows[key]['net_yen'], '図収支')
            close(record['新規件数'], main_rows[key]['opening_orders'], '図新規数')
            trades += len(saved)
            orders += record['新規件数']
    assert trades == data_audit['全返済件数'] and orders == data_audit['全新規件数']
    for href in parser.links:
        assert not href.startswith(('http:', 'https:'))
        target = href.split('#', 1)[0]
        assert not target or (html.parent / target).exists()
    return {'全図示数': 156, '全返済数': trades, '全新規数': orders, '全図と台帳と三帯一致': True}


# ----------------------------------------
def freeze() -> dict:
    """機能: 完備ガードの実装・拒否検査を固定し、採否ルールを変えないことを記録する。

    引数: なし。返り値: 固定内容 (dict)。
    """
    value = {'実装SHA256': runner.digest(Path(__file__)),
             '拒否検査実装SHA256': runner.digest(HERE / 'completion_guard_test.py'),
             '拒否検査SHA256': runner.digest(HERE / 'completion_guard_test.json'),
             '探索固定SHA256': runner.digest(HERE / '探索条件の固定.json'),
             '全条件数': 148, '全入力数': 3848, '全指定波数': 1184, '全図示数': 156,
             '採否閾値変更': False, '成績による対象選別': False,
             '範囲': '全主台帳・影口座・独立会計・所有参加・全波・主6全図・独立採否判定の完全性と指紋。未知収益を保証しない。'}
    path = HERE / 'completion_guard_fixed.json'
    if path.exists():
        assert runner.read(path) == value, '完備ガード固定後の変更'
    else:
        runner.save(path, value)
    return value


def collect() -> dict:
    """機能: 全検査を実行し、全資料の前後指紋が同一の場合のみ完了証跡を返す。

    引数: なし。返り値: 完備監査 (dict)。売買再生・外部通信はしない。
    """
    source = run_verified.verify_sources()
    hashes = dict(source['参照資料SHA256'])

    def check(path: Path, expected: str | None = None) -> str:
        """機能: 指紋を保存し、期待値と読取り途中の変更を拒否する。

        引数: path (Path)、expected (str|None)。返り値: SHA256 (str)。
        """
        path = path.resolve()
        key = str(path)
        actual = runner.digest(path)
        assert expected is None or actual == expected, '指紋不一致: ' + key
        assert key not in hashes or hashes[key] == actual, '監査中の変更: ' + key
        hashes[key] = actual
        return actual

    def load(path: Path):
        """機能: 指紋を束ねて有限JSONを読む。

        引数: path (Path)。返り値: JSON内容 (object)。
        """
        check(path)
        value = runner.read(path)
        finite(value)
        return value

    context = collect_main(load, check)
    accounting = collect_accounting(context, load, check)
    participation = collect_participation(context, load, check)
    charts = collect_charts(context, load, check)
    fixed = load(HERE / 'completion_guard_fixed.json')
    check(Path(__file__), fixed['実装SHA256'])
    check(HERE / 'completion_guard_test.py', fixed['拒否検査実装SHA256'])
    test = load(HERE / 'completion_guard_test.json')
    assert test['全検査合格'] is True and test['採否閾値変更'] is False
    check(HERE / 'completion_guard_test.json', fixed['拒否検査SHA256'])
    for name, expected in hashes.items():
        assert runner.digest(Path(name)) == expected, '監査前後で資料変更: ' + name
    return {'検証完了': True, '全条件数': 148, '全入力数': 3848, '全指定波数': 1184, '全図示数': 156,
            '主監査': context['主監査'], '独立会計': accounting, '所有参加と指定波': participation,
            '図解': charts, '独立選択判定': context['独立判定'], 'ガード実装SHA256': fixed['実装SHA256'],
            'ガード固定SHA256': runner.digest(HERE / 'completion_guard_fixed.json'),
            '参照資料SHA256': hashes, 'API取得数': 0, '現在保存物使用': False,
            '採否条件変更': False, '診断最良による主方式差替': False,
            '検証の意味': '実装・記録・全件比較の完了。選択追加の合格又は未知期間の利益保証とは別。',
            '確認時刻': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()}


def main() -> None:
    """機能: ガードを固定し、全資料が揃った場合だけ完了JSONを保存する。

    引数: --prepare (bool) は固定のみ。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    freeze()
    if args.prepare:
        print('全148完備ガードを固定。採否条件変更なし。', flush=True)
        return
    result = collect()
    runner.save(HERE / '検証完備の監査.json', result)
    print({k: result[k] for k in ('検証完了', '全条件数', '全入力数', '全指定波数', '全図示数')}, flush=True)


if __name__ == '__main__':
    main()
