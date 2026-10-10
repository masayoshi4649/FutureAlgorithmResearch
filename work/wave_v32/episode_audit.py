"""全148条件の所有者・参加・指定波を主再生と独立に再集計する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import hashlib
import importlib.util
from pathlib import Path
import pickle
import socket
import sys
import urllib.request

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import selection_runner as runner
import selection_participation_design as design

specification = importlib.util.spec_from_file_location('v32_fixed_wave_metrics', HERE.parent / 'wave_v30/episode_audit.py')
metrics = importlib.util.module_from_spec(specification)
sys.modules[specification.name] = metrics
specification.loader.exec_module(metrics)
engine = runner.engine_selector
S = {name: index for index, name in enumerate(engine.SELECTION_COLUMNS)}
E = {name: index for index, name in enumerate(engine.EVENT_COLUMNS)}
INPUTS, ENTRIES, FIXED = {}, {}, {}


def deny_network() -> None:
    """機能: 親・子プロセスからの外部通信を拒否する。

    引数: なし。返り値: なし (None)。
    """
    socket.socket.connect = metrics.reject_network
    socket.create_connection = metrics.reject_network
    urllib.request.OpenerDirector.open = metrics.reject_network


def freeze() -> dict:
    """機能: 結果前に決めた対象へ実装指紋を結合する。

    引数: なし。返り値: 計測の固定仕様 (dict)。
    """
    rules = design.prepare()
    assert list(metrics.EPISODES) == rules['指定波']
    record = {'規則': rules, '対象': rules['指定波'], '目安分': 20,
              '手法': rules['条件'], '全条件数': 148, '全入力数': 3848, '全指定波数': 1184,
              '計測設計SHA256': runner.digest(HERE / 'selection_participation_fixed.json'),
              '参照コードSHA256': {p.relative_to(ROOT).as_posix(): runner.digest(p) for p in [
                  Path(__file__), HERE / 'engine_selector.py', HERE / 'selection_runner.py',
                  HERE.parent / 'wave_v30/episode_audit.py']}}
    destination = HERE / 'episode_audit_fixed.json'
    if destination.exists():
        assert runner.read(destination) == record
    else:
        runner.save(destination, record)
    return record


def worker_init() -> None:
    """機能: 既知の保存入力と固定両入口を子プロセスへ読む。

    引数: なし。返り値: なし (None)。
    """
    global INPUTS, ENTRIES, FIXED
    deny_network()
    INPUTS = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    FIXED = runner.read(HERE / '探索条件の固定.json')
    with np.load(HERE / 'entries.npz') as archive:
        ENTRIES = {branch: {key: archive[f'{branch}|{key[0]}|{key[1]}'] for key in INPUTS} for branch in ('T', 'R')}


def equal(actual: object, expected: object, path: str = '') -> None:
    """機能: 辞書とリストの全保存項目を型に応じて比較する。

    引数: actual/expected (object)、path (str)。返り値: なし (None)。円と分の許容差1e-6。
    """
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and set(actual) == set(expected), path
        for key in expected:
            equal(actual[key], expected[key], path + '/' + key)
    elif isinstance(expected, list):
        assert len(actual) == len(expected), path
        for index, value in enumerate(expected):
            equal(actual[index], value, path + '/' + str(index))
    elif expected is None or isinstance(expected, (str, bool)):
        assert actual == expected, path
    else:
        np.testing.assert_allclose(actual, expected, atol=1e-6, rtol=0, err_msg=path)


def selected_events(result: dict, code: int) -> np.ndarray:
    """機能: ある種類の所有イベントを抽出する。

    引数: result (dict)、code (int)。返り値: 該当イベント (ndarray)。
    """
    values = result['selection_events']
    return values[values[:, E['event']] == code]


def owner_audit(ready: dict, states: np.ndarray, requests: np.ndarray, result: dict, spec: dict) -> tuple[np.ndarray, np.ndarray, dict]:
    """機能: 約定前の未約定と全注文から建玉所有を独立再構成し、取消・待機を確認する。

    引数: ready/result/spec (dict)、states/requests (ndarray)。返り値: 所有列・実源列・検査件数 (tuple)。
    売買の全金銭集計・未来改変は別担当の全会計監査で検査する。
    """
    curve, events, orders = result['selection_curve'], result['selection_events'], result['orders']
    n, times = len(requests), ready['time_s']
    np.testing.assert_array_equal(curve[:, S['request_id']], requests)
    assert curve.shape == (n, len(S))
    if len(events) > 1:
        assert np.all(events[1:, E['row']] >= events[:-1, E['row']])
        same = events[1:, E['row']] == events[:-1, E['row']]
        assert np.all(events[1:, E['phase']][same] >= events[:-1, E['phase']][same])
    quantity = np.zeros(n)
    long, short = np.zeros(n), np.zeros(n)
    for order in orders:
        row, source, side, qty, opening = int(order[0]), int(order[1]), int(order[3]), int(order[4]), bool(order[7])
        assert 0 <= source < row < n
        quantity[row] += qty if opening else -qty
        held_side = side if opening else -side
        (long if held_side == 1 else short)[row] += qty if opening else -qty
    quantity, long, short = np.cumsum(quantity), np.cumsum(long), np.cumsum(short)
    np.testing.assert_array_equal(quantity, result['curve'][:, 2] + result['curve'][:, 3])
    np.testing.assert_array_equal(long, result['curve'][:, 2])
    np.testing.assert_array_equal(short, result['curve'][:, 3])
    assert quantity[-1] == 0
    close_row = int(np.searchsorted(times, ready['limit'], side='left')) + 1
    assert not quantity[close_row:].any()
    owners, sources = np.zeros(n, dtype=np.int8), np.zeros(n, dtype=np.int8)
    opening = orders[orders[:, 7] == 1]
    closes = np.flatnonzero((quantity == 0) & np.r_[False, quantity[:-1] > 0])
    assert len(opening) == len(closes)
    for order, close in zip(opening, closes):
        row = int(order[0])
        assert row < close and times[row] < ready['limit'] - 300
        prior = curve[row - 1]
        owner = int(prior[S['pending_owner_id']])
        source = spec['source_override'] or owner
        assert owner in (1, 2) and prior[S['cancel_wait']] == 0
        assert prior[S['pending_direction']] == order[3]
        assert prior[S['pending_source_row']] == order[1]
        assert prior[S['pending_entry_source_id']] == source
        owners[row:close], sources[row:close] = owner, source
        np.testing.assert_array_equal(curve[row:close, S['position_atr']], np.full(close - row, prior[S['pending_atr']]))
        np.testing.assert_array_equal(curve[row:close, S['applied_id']], np.full(close - row, owner))
    np.testing.assert_array_equal(owners, curve[:, S['position_owner_id']])
    np.testing.assert_array_equal(sources, curve[:, S['position_entry_source_id']])
    effective = np.where(quantity > 0, sources, spec['source_override'] or curve[:, S['applied_id']]).astype(int)
    np.testing.assert_array_equal(effective, curve[:, S['entry_source_id']])
    np.testing.assert_array_equal(states[np.arange(n), effective - 1], curve[:, S['entry_direction']])
    pending = curve[:, S['pending_direction']] != 0
    np.testing.assert_array_equal(curve[pending, S['pending_owner_id']], curve[pending, S['applied_id']])
    assert np.all(curve[~pending, S['pending_owner_id']] == 0)
    changes = np.flatnonzero(np.r_[False, curve[1:, S['applied_id']] != curve[:-1, S['applied_id']]])
    assert np.all(quantity[changes] == 0)
    cancellation = selected_events(result, 2)
    acknowledgments = selected_events(result, 3)
    for event in cancellation:
        row = int(event[E['row']])
        assert row + 1 < n and quantity[row] == 0
        assert curve[row, S['cancel_wait']] == 1 and curve[row, S['cancel_source_row']] == row
        hit = acknowledgments[acknowledgments[:, E['source_row']] == row]
        assert len(hit) == 1 and hit[0, E['row']] == row + 1 and hit[0, E['phase']] == 0
        assert hit[0, E['new_id']] == requests[row]
        assert not np.any(opening[:, 0] == row + 1)
        np.testing.assert_array_equal(curve[row, [S[x] for x in ('pending_owner_id', 'pending_entry_source_id', 'pending_level', 'pending_atr', 'pending_expiry', 'pending_source_row')]],
                                      curve[row - 1, [S[x] for x in ('pending_owner_id', 'pending_entry_source_id', 'pending_level', 'pending_atr', 'pending_expiry', 'pending_source_row')]])
    assert len(cancellation) == len(acknowledgments)
    preparations = events[np.isin(events[:, E['event']], (5, 12))]
    for event in preparations:
        row = int(event[E['row']])
        assert event[E['source_row']] == row and quantity[row] == 0
        assert times[row] >= ready['start'] + 1200 and times[row] < ready['limit'] - 300
        old = closes[closes <= row]
        if len(old):
            assert times[row] >= times[old[-1]] + 300 - 1e-8
        assert curve[row, S['pending_owner_id']] == event[E['pending_owner_id']]
        assert curve[row, S['pending_atr']] == ready['atr'][row]
    for order in selected_events(result, 7):
        row = int(order[E['row']])
        assert order[E['position_owner_id']] == owners[row]
        assert order[E['entry_source_id']] == sources[row]
    return owners, sources, {'所有検査新規数': len(opening), '取消要求確認数': len(cancellation),
                            '新規準備数': len(preparations), '完全返済数': len(closes), '全行所有一致': True,
                            '取消順序一致': True, '5分休止一致': True, '場内全返済': True}


def summarize(ready: dict, result: dict, owners: np.ndarray, sources: np.ndarray, multiplier: float) -> tuple[dict, dict]:
    """機能: 主selection指標と追加の所有・実入口源・保有時間を別実装で積分する。

    引数: ready/result (dict)、owners/sources (ndarray)、multiplier (float)。返り値: 主互換集計・追加計測 (tuple)。
    """
    times, curve, sc, events = ready['time_s'], result['curve'], result['selection_curve'], result['selection_events']
    measure = lambda values: metrics.integrate(times, values, ready['start'], ready['limit'])
    selection = {field: {} for field in ('request_minutes', 'applied_minutes', 'branch_opening_orders', 'branch_net_yen',
                                        'branch_profit_yen', 'branch_loss_yen', 'branch_closed_units')}
    selection['event_counts'] = {name: int(np.count_nonzero(events[:, E['event']] == code)) for code, name in engine.EVENT_NAMES.items()}
    selection['first_applied_id'] = int(sc[0, S['applied_id']])
    selection['last_applied_id'] = int(sc[-1, S['applied_id']])
    opening = result['orders'][result['orders'][:, 7] == 1]
    trades = result['trades']
    trade_sources = sources[trades[:, 6].astype(int)]
    pnl = trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4]) * multiplier
    for number, name in ((1, 'T'), (2, 'R')):
        selection['request_minutes'][name] = measure(sc[:, S['request_id']] == number)
        selection['applied_minutes'][name] = measure(sc[:, S['applied_id']] == number)
        selection['branch_opening_orders'][name] = int(np.count_nonzero(sources[opening[:, 0].astype(int)] == number))
        selected = trade_sources == number
        values = pnl[selected]
        selection['branch_net_yen'][name] = float(values.sum())
        selection['branch_profit_yen'][name] = float(values[values > 1e-6].sum())
        selection['branch_loss_yen'][name] = float(-values[values < -1e-6].sum())
        selection['branch_closed_units'][name] = int(trades[selected, 3].sum())
    extra = {
        'actual_entry_source_minutes': {name: measure(sc[:, S['entry_source_id']] == number) for number, name in ((1, 'T'), (2, 'R'))},
        'position_owner_minutes': {name: measure(owners == number) for number, name in ((0, 'なし'), (1, 'T'), (2, 'R'))},
        'pending_owner_minutes': {name: measure(sc[:, S['pending_owner_id']] == number) for number, name in ((0, 'なし'), (1, 'T'), (2, 'R'))},
        'position_source_minutes': {name: measure(sources == number) for number, name in ((0, 'なし'), (1, 'T'), (2, 'R'))},
        'long_unit_minutes': metrics.integrate(times, curve[:, 2], times[0], times[-1]),
        'short_unit_minutes': metrics.integrate(times, curve[:, 3], times[0], times[-1]),
        '場内買い枚数分': measure(curve[:, 2]), '場内売り枚数分': measure(curve[:, 3]),
        'held_minutes': measure(owners != 0), 'flat_minutes': measure(owners == 0),
        'opening_orders': len(opening),
        'first_entry_min': None if not len(opening) else float((times[int(opening[0, 0])] - ready['start']) / 60),
        '観測分': measure(np.ones(len(times))),
    }
    for field in ('actual_entry_source_minutes', 'position_owner_minutes', 'pending_owner_minutes', 'position_source_minutes'):
        np.testing.assert_allclose(sum(extra[field].values()), extra['観測分'], atol=1e-8, rtol=0)
    np.testing.assert_allclose(extra['held_minutes'] + extra['flat_minutes'], extra['観測分'], atol=1e-8, rtol=0)
    return selection, extra


def process_condition(spec: dict) -> dict:
    """機能: 一条件26入力を再生し、所有・主selection・波・主6の図材料を全て保存する。

    引数: spec (dict)。返り値: 一条件の全計測 (dict)。結果で対象を減らさない。
    """
    identifier = spec['id']
    with np.load(HERE / 'requests' / (identifier + '.npz')) as archive:
        requests = {key: archive['|'.join(key)] for key in INPUTS}
    entries = {branch: runner.selector_signals.delay_columns(INPUTS, values, spec['delay_seconds'], initial=0)
               if spec['delay_seconds'] else values for branch, values in ENTRIES.items()}
    expected = {(row['session'], row['symbol']): row for row in runner.read(HERE / 'sessions' / (identifier + '.json.gz'))}
    ledgers = {(row['session'], row['symbol']): row for row in runner.read(HERE / 'ledgers' / (identifier + '.json.gz'))}
    paths = [HERE / folder / (identifier + suffix) for folder, suffix in (('requests', '.npz'), ('sessions', '.json.gz'), ('ledgers', '.json.gz'), ('summaries', '.json'))]
    hashes = {str(path.relative_to(HERE)): runner.digest(path) for path in paths}
    rows, waves, chart, boundary_ledgers = [], [], [], []
    for key, ready in INPUTS.items():
        cfg = runner.managers.make_config(FIXED['manager'], key[1], ready)
        states = np.column_stack([entries[branch][key] for branch in ('T', 'R')]).astype(np.int8)
        result = engine.run(ready, states, requests[key], cfg, detail=True,
                            source_override=spec['source_override'], observed_fill=spec['fill_model'] == 'observed')
        stored = ledgers[key]
        for field, width in (('trades', 11), ('orders', 8), ('cycles', 10), ('selection_events', len(E))):
            np.testing.assert_array_equal(result[field], np.asarray(stored[field], dtype=float).reshape(-1, width))
        assert hashlib.sha256(result['selection_curve'].tobytes()).hexdigest() == stored['selection_curve_SHA256']
        owners, sources, audit = owner_audit(ready, states, requests[key], result, spec)
        selection, extra = summarize(ready, result, owners, sources, cfg['point_value'])
        equal(selection, expected[key]['selection'], identifier + str(key))
        for field in ('long_unit_minutes', 'short_unit_minutes', 'opening_orders', 'first_entry_min'):
            equal(extra[field], expected[key][field], field)
        rows.append({'id': identifier, 'session': key[0], 'symbol': key[1], 'selection': selection,
                     **extra, '所有監査': audit, '観測行数': len(ready['last'])})
        state = result['selection_curve'][:, S['entry_direction']].astype(np.int8)
        if key[0] in {row['session'] for row in metrics.EPISODES}:
            orders = metrics.order_records(ready, state, result, engine.REASONS)
            boundary_ledgers.append({'method': identifier, 'session': key[0], 'symbol': key[1], '全約定': orders})
            for wave in metrics.EPISODES:
                if wave['session'] == key[0]:
                    measured = metrics.episode_metrics(dict(spec, manager=FIXED['manager']), wave, ready, state, result, orders, cfg['point_value'])
                    measured['評価区分'] = '初期6区間の目的参考'
                    waves.append(measured)
        if spec['role'] == 'primary':
            columns = [S[name] for name in ('request_id', 'applied_id', 'entry_source_id')]
            bands = result['selection_curve'][:, columns]
            changes = np.flatnonzero(np.r_[True, np.any(bands[1:] != bands[:-1], axis=1)])
            trades = metrics.trade_records(ready, result, cfg['point_value'])
            for trade in trades:
                entry = trade['新規行']
                trade['所有ID'] = int(owners[entry])
                trade['実入口源ID'] = int(sources[entry])
            chart.append({'method': identifier, 'session': key[0], 'symbol': key[1], '全返済': trades,
                          '全約定': result['orders'].tolist(),
                          '状態': [[float(ready['time_s'][i]), *map(int, bands[i])] for i in changes]})
    boundary = metrics.accounting_checks(waves, boundary_ledgers)
    assert len(rows) == 26 and len(waves) == 8
    for name, expected_hash in hashes.items():
        assert runner.digest(HERE / name) == expected_hash
    return {'id': identifier, 'spec': spec, '参加': rows, '波': waves, '図示用': chart,
            '境界独立検算': boundary, '保存資料SHA256': hashes,
            '計測固定SHA256': runner.digest(HERE / 'episode_audit_fixed.json')}


def aggregate(rows: list[dict], fixed: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """機能: 全期間と評価7区間を独立に集計し、第6→第7を含む適用変更を比較する。

    引数: rows (list[dict])、fixed (dict)。返り値: 全期間・評価期間・セッション境界 (tuple)。
    """
    all_period, evaluation, boundaries = [], [], []
    dictionary_fields = ('request_minutes', 'applied_minutes', 'branch_opening_orders', 'branch_net_yen',
                         'branch_profit_yen', 'branch_loss_yen', 'branch_closed_units', 'event_counts')
    extra_dictionaries = ('actual_entry_source_minutes', 'position_owner_minutes', 'pending_owner_minutes', 'position_source_minutes')
    extra_fields = ('long_unit_minutes', 'short_unit_minutes', '場内買い枚数分', '場内売り枚数分', 'held_minutes', 'flat_minutes', 'opening_orders', '観測分')
    for spec in fixed['conditions']:
        summary = runner.read(HERE / 'summaries' / (spec['id'] + '.json'))
        for symbol in ('TOPIX', 'NK225'):
            history = sorted([row for row in rows if row['id'] == spec['id'] and row['symbol'] == symbol], key=lambda r: r['session'])
            assert len(history) == 13
            for previous, current in zip(history, history[1:]):
                boundaries.append({'id': spec['id'], 'symbol': symbol, '前session': previous['session'], '次session': current['session'],
                                   '前最終applied': previous['selection']['last_applied_id'], '次初回applied': current['selection']['first_applied_id'],
                                   '適用変更': previous['selection']['last_applied_id'] != current['selection']['first_applied_id'],
                                   '主評価へ算入': current['session'] in fixed['共通評価7セッション']})
            for label, sessions, destination, saved_key in (('全13区間', fixed['全セッション'], all_period, 'all_symbols'),
                                                            ('共通評価7区間', fixed['共通評価7セッション'], evaluation, 'symbols')):
                members = [row for row in history if row['session'] in sessions]
                selection = {field: {key: sum(row['selection'][field][key] for row in members) for key in members[0]['selection'][field]}
                             for field in dictionary_fields}
                selection['between_session_applied_switches'] = sum(a['selection']['last_applied_id'] != b['selection']['first_applied_id']
                    for a, b in zip(history, history[1:]) if b['session'] in sessions)
                selection['within_session_applied_switches'] = selection['event_counts']['適用変更']
                equal(selection, summary[saved_key][symbol]['selection'], spec['id'] + symbol + label)
                destination.append({'id': spec['id'], 'symbol': symbol, '区間': label, 'selection': selection,
                    **{field: sum(row[field] for row in members) for field in extra_fields},
                    **{field: {key: sum(row[field][key] for row in members) for key in members[0][field]} for field in extra_dictionaries}})
    return all_period, evaluation, boundaries


def main() -> None:
    """機能: 固定済み全対象を再生し、所有参加・波と図示材料の完備を確認する。

    引数: --prepare (bool)、--workers (int)。返り値: なし (None)。現在相場は使用しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    deny_network()
    frozen = freeze()
    if args.prepare:
        print('全148の所有参加3848・波1184・主6図156の実装を固定。再生なし。', flush=True)
        return
    assert runner.read(HERE / '主再生の完了.json')['全条件数'] == 148
    fixed = runner.read(HERE / '探索条件の固定.json')
    destination = HERE / 'selection_participation_details'
    destination.mkdir(exist_ok=True)
    results, pending = [], []
    for spec in fixed['conditions']:
        path = destination / (spec['id'] + '.json.gz')
        if path.exists():
            value = runner.read(path)
            assert value['計測固定SHA256'] == runner.digest(HERE / 'episode_audit_fixed.json')
            for name, fingerprint in value['保存資料SHA256'].items():
                assert runner.digest(HERE / name) == fingerprint
            results.append(value)
        else:
            pending.append(spec)
    with ProcessPoolExecutor(max_workers=args.workers, initializer=worker_init) as pool:
        jobs = [pool.submit(process_condition, spec) for spec in pending]
        for future in as_completed(jobs):
            value = future.result()
            runner.save(destination / (value['id'] + '.json.gz'), value)
            results.append(value)
            print(str(len(results)) + '/148 所有・参加・波一致 ' + value['id'], flush=True)
    results.sort(key=lambda row: row['id'])
    rows = [row for value in results for row in value['参加']]
    waves = [row for value in results for row in value['波']]
    assert len(rows) == 3848 and len(waves) == 1184
    all_period, evaluation, boundaries = aggregate(rows, fixed)
    counts = {key: sum(row['所有監査'][key] for row in rows) for key in ('所有検査新規数', '取消要求確認数', '新規準備数', '完全返済数')}
    runner.save(HERE / 'participation.json', {'セッション': rows, '全期間': all_period, '評価期間': evaluation,
                'セッション境界': boundaries, '計測固定SHA256': runner.digest(HERE / 'episode_audit_fixed.json')})
    runner.save(HERE / 'episode_audit.json', {'固定仕様': frozen, '手法': fixed['conditions'], '結果': waves,
        '方法別要約': [{'method': spec['id'], '対象区間数': 8, '目安達成区間数': sum(row['正方向ネット20分目安達成'] for row in waves if row['method'] == spec['id']),
                        '位置付け': '全て初期6区間、主評価7区間の合格数ではない'} for spec in fixed['conditions']],
        '境界損益の独立検算': {'全約定からの独立会計一致': True, '比較境界数': sum(v['境界独立検算']['比較境界数'] for v in results)},
        '全入力数': 3848, '計測固定SHA256': runner.digest(HERE / 'episode_audit_fixed.json'), 'API取得数': 0, '現在保存物使用': False})
    runner.save(HERE / 'selection_ownership_audit.json', {'全合格': True, '全条件数': 148, '全入力数': 3848,
        '全行所有数': sum(row['観測行数'] for row in rows), '主selection全一致': True, '所有不変全一致': True,
        '取消順序全一致': True, '期間境界全一致': True, '境界比較数': len(boundaries), **counts,
        'API取得数': 0, '現在保存物使用': False, '計測固定SHA256': runner.digest(HERE / 'episode_audit_fixed.json')})
    assert freeze() == frozen
    (HERE / 'selection_ownership_audit.md').write_text(
        '# 選択所有・参加・指定波の独立監査\n\n全148条件・3,848入力で所有者、取消順序、5分待機、主selection集計と期間境界が一致。'
        '建玉の実入口源から枝別の全返済損益を再計算し、要求時間と保有時間を分けた。\n\n'
        '全1,184指定波の境界評価は全注文から独立に確認。4指定波は全て初期6区間にあり、主評価7区間の成績・未知検証とは数えない。'
        '詳細は [参加](participation.json)、[指定波](episode_audit.json)、[所有監査](selection_ownership_audit.json)。API取得0、現在保存物使用0。\n', encoding='utf-8')
    print('全148の所有参加3848・指定波1184・期間境界を完了。', flush=True)


if __name__ == '__main__':
    main()
