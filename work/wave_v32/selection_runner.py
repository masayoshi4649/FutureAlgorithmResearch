"""順張り・価格反転の選択を、同じ注文器と同じ評価区間で比較する。"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import argparse
import hashlib
from pathlib import Path
import pickle
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE.parent / 'wave_v23'
sys.path.insert(0, str(HERE.parent / 'wave_v31'))
import lag_runner as previous
sys.path.insert(0, str(HERE))
import selector_design
import selector_signals
import engine_selector

save, read, digest = previous.save, previous.read, previous.digest
research, managers = previous.research, previous.managers
SYMBOLS = ('TOPIX', 'NK225')
INPUTS, ENTRIES, SHADOW, FIXED = {}, {}, [], {}


def array_hash(values: dict) -> str:
    """機能: キー順と配列内容を含む指紋を作る。

    引数: values (dict)。返り値: SHA256 (str)。
    """
    result = hashlib.sha256()
    for key in sorted(values):
        result.update(str(key).encode('utf-8'))
        result.update(np.asarray(values[key]).tobytes())
    return result.hexdigest()


def prepare() -> dict:
    """機能: 新規損益の前に、全条件と入力・実装を固定する。

    引数: なし。返り値: 固定記録 (dict)。旧資料や現在保存物は変更しない。
    """
    for folder in ('requests', 'sessions', 'summaries', 'ledgers'):
        (HERE / folder).mkdir(exist_ok=True)
    path = HERE / '探索条件の固定.json'
    if path.exists():
        fixed = read(path)
        for name, expected in fixed['SHA256'].items():
            assert digest(ROOT / name) == expected, '固定後変更: ' + name
        assert fixed['conditions'] == selector_design.catalog()
        return fixed
    old_fixed = read(HERE.parent / 'wave_v31/探索条件の固定.json')
    management = next(m for m in old_fixed['managers'] if m['id'] == 'L000')
    inputs = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    sessions = sorted({k[0] for k in inputs})
    assert len(inputs) == 26 and len(sessions) == 13
    conditions = selector_design.catalog()
    assert len(conditions) == 148 and len({r['id'] for r in conditions}) == 148
    files = [HERE / name for name in ('selection_runner.py', 'selection_judgment.py', 'engine_selector.py', 'selector_signals.py',
                                       'selector_design.py', 'selection_fixed.json')]
    files += [OLD / 'inputs.pkl', OLD / 'features_depth.pkl']
    for folder in ('wave_v23', 'wave_v25', 'wave_v27', 'wave_v28', 'wave_v29', 'wave_v30', 'wave_v31'):
        files += list((HERE.parent / folder).glob('*.py'))
    for folder, suffix in (('book', 'jsonl'), ('candle_1min', 'csv'), ('candle_5min', 'csv')):
        for session, symbol in inputs:
            files.append(ROOT / folder / symbol / (session + '.' + suffix))
    files += [HERE.parent / 'wave_v27/hierarchy_design_fixed.json',
              HERE.parent / 'wave_v25/d016_price_control_fixed.json',
              HERE.parent / 'wave_v25/探索条件の固定.json',
              HERE.parent / 'wave_v31/探索条件の固定.json',
              HERE.parent / 'wave_v31/sessions/H019.json.gz',
              HERE.parent / 'wave_v31/summaries/H019.json']
    files += list((HERE.parent / 'wave_v27/directions').glob('H019.npz'))
    for file in files:
        assert file.is_file(), file
    fixed = {'固定日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), 'conditions': conditions,
             'manager': management, '全条件数': 148, '主比較数': 6, '反証数': 142,
             '全セッション': sessions, '初期6セッション': sessions[:6], '共通評価7セッション': sessions[6:],
             '対象': '既知13セッション。T/Rもこの期間を知って選んだ部品であり未知検証ではない。',
             '費用': '0・指定価格約定を主比較。観測価格約定は別の反証。',
             '現在データ': '現在APIと保存ライブの再読取・再生を禁止。',
             '再計算': '既存の新損益を使い回さず、固定T/Rの影口座から全148を毎回再計算。',
             'SHA256': {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(set(files))}}
    save(path, fixed)
    return fixed


def worker_init() -> None:
    """機能: 各実行器へ固定入力・両入口・過去用影口座を読み込む。

    引数: なし。返り値: なし (None)。
    """
    global INPUTS, ENTRIES, SHADOW, FIXED
    INPUTS = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    FIXED = read(HERE / '探索条件の固定.json')
    SHADOW = read(HERE / 'shadow_rows.json')
    ENTRIES = {}
    with np.load(HERE / 'entries.npz') as source:
        for branch in ('T', 'R'):
            ENTRIES[branch] = {key: source[f'{branch}|{key[0]}|{key[1]}'] for key in INPUTS}


def request_columns(spec: dict) -> tuple[dict, list]:
    """機能: 固定規則だけで全セッションの要求IDを生成する。

    引数: spec (dict)。返り値: 原本行要求列・因果判定ログ (tuple[dict,list])。
    """
    primary = spec['base_selector']
    if spec['random_seed'] is not None:
        values, logs = selector_signals.random_requests(INPUTS, spec['selector_kind'], spec['random_seed'])
    elif spec['selector_kind'] == 'fixed':
        branch = spec['fixed_request']
        values = {key: np.full(len(r['seq']), branch, dtype=np.int8) for key, r in INPUTS.items()}
        logs = [{'session': session, 'timestamp': float(min(r['start'] for key, r in INPUTS.items() if key[0] == session)),
                 'request': branch, 'reason': '固定方式'} for session in FIXED['全セッション']]
    elif spec['selector_kind'] == 'B':
        values, logs = selector_signals.build_past_requests(INPUTS, SHADOW, window=spec['history_window'], gap=spec['score_gap'])
    else:
        values, logs = selector_signals.build_state_requests(INPUTS, window=spec['er_window'])
    if spec['delay_seconds']:
        values = selector_signals.delay_columns(INPUTS, values, spec['delay_seconds'], initial=1)
    return values, logs


def selection_summary(result: dict, ready: dict, multiplier: float) -> dict:
    """機能: 要求・適用・実入口の時間と損益を分けて集計する。

    引数: result/ready (dict)、multiplier (float)。返り値: 選択と参加の指標 (dict)。
    """
    columns = {name: i for i, name in enumerate(engine_selector.SELECTION_COLUMNS)}
    event_columns = {name: i for i, name in enumerate(engine_selector.EVENT_COLUMNS)}
    curve, events, times = result['selection_curve'], result['selection_events'], ready['time_s']
    after = np.r_[times[1:], times[-1]]
    durations = np.maximum(0., np.minimum(after, ready['limit']) - np.maximum(times, ready['start'])) / 60.
    output = {'request_minutes': {}, 'applied_minutes': {}, 'branch_opening_orders': {},
              'branch_net_yen': {}, 'branch_profit_yen': {}, 'branch_loss_yen': {}, 'branch_closed_units': {},
              'event_counts': {name: int(np.sum(events[:, event_columns['event']] == code)) for code, name in engine_selector.EVENT_NAMES.items()},
              'first_applied_id': int(curve[0, columns['applied_id']]),
              'last_applied_id': int(curve[-1, columns['applied_id']])}
    entry_orders = result['orders'][result['orders'][:, 7] == 1]
    for number, branch in ((1, 'T'), (2, 'R')):
        output['request_minutes'][branch] = float(durations[curve[:, columns['request_id']] == number].sum())
        output['applied_minutes'][branch] = float(durations[curve[:, columns['applied_id']] == number].sum())
        output['branch_opening_orders'][branch] = int(sum(curve[int(r[0]), columns['position_entry_source_id']] == number for r in entry_orders))
        trades = result['trades']
        subset = trades[np.array([curve[int(r[6]), columns['position_entry_source_id']] == number for r in trades], dtype=bool)]
        profits = subset[:, 10] * multiplier
        output['branch_net_yen'][branch] = float(profits.sum())
        output['branch_profit_yen'][branch] = float(profits[profits > 1e-6].sum())
        output['branch_loss_yen'][branch] = float(-profits[profits < -1e-6].sum())
        output['branch_closed_units'][branch] = int(subset[:, 3].sum())
    assert sum(output['branch_opening_orders'].values()) == len(entry_orders)
    np.testing.assert_allclose(sum(output['branch_net_yen'].values()), result['stats'][0] * multiplier, atol=1e-6, rtol=0)
    assert sum(output['branch_closed_units'].values()) == int(result['trades'][:, 3].sum())
    return output


def periods(rows: list[dict], sessions: list[str]) -> dict:
    """機能: 共通対象区間の全損益を銘柄内で集計する。

    引数: rows (list[dict])、sessions (list[str])。返り値: 銘柄別集計 (dict)。
    """
    output = {}
    for symbol in SYMBOLS:
        part = [r for r in rows if r['symbol'] == symbol and r['session'] in sessions]
        value = research.aggregate(part)
        for field in ('long_unit_minutes', 'short_unit_minutes', 'opening_orders'):
            value[field] = sum(r[field] for r in part)
        selection = {}
        for field in ('request_minutes', 'applied_minutes', 'branch_opening_orders', 'branch_net_yen',
                      'branch_profit_yen', 'branch_loss_yen', 'branch_closed_units', 'event_counts'):
            selection[field] = {key: sum(r['selection'][field][key] for r in part) for key in part[0]['selection'][field]}
        history = sorted([r for r in rows if r['symbol'] == symbol], key=lambda r: r['session'])
        selection['between_session_applied_switches'] = sum(a['selection']['last_applied_id'] != b['selection']['first_applied_id']
                    for a, b in zip(history, history[1:]) if b['session'] in sessions)
        selection['within_session_applied_switches'] = selection['event_counts']['適用変更']
        value['selection'] = selection
        output[symbol] = value
    return output


def evaluate(spec: dict) -> dict:
    """機能: 一つの選択規則を全26入力で順送りし、全注文を保存する。

    引数: spec (dict)。返り値: 全期間・共通評価期間の集計 (dict)。
    """
    started, identifier = time.perf_counter(), spec['id']
    requests, logs = request_columns(spec)
    delay = spec['delay_seconds']
    entries = {branch: selector_signals.delay_columns(INPUTS, values, delay, initial=0) if delay else values
               for branch, values in ENTRIES.items()}
    np.savez_compressed(HERE / 'requests' / (identifier + '.npz'), **{f'{k[0]}|{k[1]}': v for k, v in requests.items()})
    save(HERE / 'requests' / (identifier + '.json.gz'), logs)
    override = spec['source_override']
    observed = spec['fill_model'] == 'observed'
    rows, ledgers, ledger_hash = [], [], hashlib.sha256()
    for key, ready in INPUTS.items():
        states = np.column_stack([entries[b][key] for b in ('T', 'R')]).astype(np.int8)
        config = managers.make_config(FIXED['manager'], key[1], ready)
        result = engine_selector.run(ready, states, requests[key], config, detail=False,
                                     source_override=override, observed_fill=observed)
        row = research.summarize(result, config, key[1], key[0], identifier)
        row['two_largest_cycle_profits'] = sorted([float(v) * config['point_value'] for v in result['cycles'][:, 3] if v > 0], reverse=True)[:2]
        row.update(previous.participation(result, ready))
        row['selection'] = selection_summary(result, ready, config['point_value'])
        rows.append(row)
        if identifier == 'S000':
            reference = next(r for part in read(HERE.parent / 'wave_v31/sessions/H019.json.gz') if part['id'] == 'H019__L000__V000'
                             for r in part['rows'] if r['session'] == key[0] and r['symbol'] == key[1])
            for field, target in reference.items():
                if field != 'id':
                    assert row[field] == target, ('旧T再現', key, field)
        ledger_hash.update(str(key).encode('utf-8'))
        ledger_hash.update(result['trades'].tobytes())
        assert not np.isinf(result['selection_events']).any()
        events = result['selection_events'].astype(object)
        events[np.isnan(result['selection_events'])] = None
        ledgers.append({'session': key[0], 'symbol': key[1], 'config': config,
                        'trades': result['trades'].tolist(), 'orders': result['orders'].tolist(),
                        'cycles': result['cycles'].tolist(), 'stats': result['stats'].tolist(),
                        'selection_events': events.tolist(),
                        'selection_curve_SHA256': hashlib.sha256(result['selection_curve'].tobytes()).hexdigest()})
    all_period = periods(rows, FIXED['全セッション'])
    evaluation = periods(rows, FIXED['共通評価7セッション'])
    save(HERE / 'sessions' / (identifier + '.json.gz'), rows)
    save(HERE / 'ledgers' / (identifier + '.json.gz'), ledgers)
    summary = {'id': identifier, 'spec': spec, 'all_symbols': all_period, 'symbols': evaluation,
               'ledger_hash': ledger_hash.hexdigest(), 'request_hash': array_hash(requests),
               'entries_hash': {branch: array_hash(values) for branch, values in entries.items()},
               '探索固定SHA256': digest(HERE / '探索条件の固定.json'),
               '経過秒': time.perf_counter() - started, '既存結果の再利用': False}
    save(HERE / 'summaries' / (identifier + '.json'), summary)
    return summary


def main() -> None:
    """機能: 固定・構造検査の後、影口座から全148条件を再計算する。

    引数: --prepare (bool)、--workers (int)。返り値: なし (None)。
    """
    global INPUTS, ENTRIES, SHADOW, FIXED
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    FIXED = prepare()
    if args.prepare:
        print('全148条件の実装・対象を固定。売買再生なし。', flush=True)
        return
    assert read(HERE / '起動前監査.json')['実行可能'] is True
    INPUTS = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    features = pickle.loads((OLD / 'features_depth.pkl').read_bytes())
    ENTRIES = selector_signals.build_entries(INPUTS, features)
    np.savez_compressed(HERE / 'entries.npz', **{f'{branch}|{k[0]}|{k[1]}': values for branch, rows in ENTRIES.items() for k, values in rows.items()})
    save(HERE / 'entries_hash.json', {branch: array_hash(rows) for branch, rows in ENTRIES.items()})
    started, results = time.perf_counter(), []
    for spec in FIXED['conditions'][:2]:
        results.append(evaluate(spec))
        print(spec['id'] + ' 固定影口座完了', flush=True)
    SHADOW = []
    for identifier, branch in (('S000', 'T'), ('S001', 'R')):
        rows = read(HERE / 'sessions' / (identifier + '.json.gz'))
        for row in rows:
            ready = INPUTS[(row['session'], row['symbol'])]
            assert ready['time_s'][-1] > ready['limit']
            SHADOW.append({'session': row['session'], 'symbol': row['symbol'], 'branch': branch,
                           'net_yen': row['net_yen'], 'completed_at': float(ready['time_s'][-1]), 'complete': True})
    save(HERE / 'shadow_rows.json', SHADOW)
    with ProcessPoolExecutor(max_workers=args.workers, initializer=worker_init) as pool:
        pending = [pool.submit(evaluate, spec) for spec in FIXED['conditions'][2:]]
        for future in as_completed(pending):
            value = future.result()
            results.append(value)
            print(f"{len(results)}/148 {value['id']} 完了", flush=True)
    assert len(results) == 148 and len({r['id'] for r in results}) == 148
    prepare()
    save(HERE / '全条件の期間集計.json.gz', sorted(results, key=lambda r: r['id']))
    save(HERE / '主再生の完了.json', {'全条件数': 148, '全入力数': 3848, '経過秒': time.perf_counter() - started,
         '現在データ使用': False, 'API取得数': 0, '既存結果の再利用': False,
         '探索固定SHA256': digest(HERE / '探索条件の固定.json')})
    print('全148条件を完了。採用判定は独立監査後。', flush=True)


if __name__ == '__main__':
    main()
