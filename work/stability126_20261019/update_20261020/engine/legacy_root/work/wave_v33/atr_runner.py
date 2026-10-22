"""同じ入口と損失予算で、固定ATR幅と保有中ATR幅を対応比較する。"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import argparse
import hashlib
import importlib.util
from pathlib import Path
import pickle
import socket
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
import design
import input_audit
import engine_dynamic_atr as engine

save, read, digest = previous.save, previous.read, previous.digest
research, managers = previous.research, previous.managers
_spec = importlib.util.spec_from_file_location('v33_wave_metrics', HERE.parent / 'wave_v30/episode_audit.py')
wave_metrics = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = wave_metrics
_spec.loader.exec_module(wave_metrics)
INPUTS, ENTRIES, FIXED = {}, {}, {}
SYMBOLS = ('TOPIX', 'NK225')


def deny_network() -> None:
    """機能: 今回の保存データ再生から外部通信を禁止する。

    引数: なし。返り値: なし (None)。
    """
    socket.socket.connect = wave_metrics.reject_network
    socket.create_connection = wave_metrics.reject_network


def prepare() -> dict:
    """機能: 全条件・実装・入力を新損益の前に固定する。

    引数: なし。返り値: 固定記録 (dict)。既存固定との差は停止する。
    """
    for folder in ('sessions', 'summaries', 'ledgers', 'waves'):
        (HERE / folder).mkdir(exist_ok=True)
    path = HERE / '探索条件の固定.json'
    if path.exists():
        fixed = read(path)
        assert fixed['conditions'] == design.catalog()
        for name, expected in fixed['SHA256'].items():
            assert digest(ROOT / name) == expected, '固定後変更: ' + name
        return fixed
    old = read(HERE.parent / 'wave_v31/探索条件の固定.json')
    manager = next(row for row in old['managers'] if row['id'] == 'L000')
    inputs = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    sessions = sorted({key[0] for key in inputs})
    assert len(sessions) == 13 and len(inputs) == 26
    specs = design.catalog()
    assert len(specs) == len({row['id'] for row in specs}) == 96
    files = [HERE / name for name in ('atr_runner.py', 'engine_dynamic_atr.py', 'design.py', 'input_audit.py',
                                      'assessment.py', 'runner_synthetic_audit.py')]
    files += list(HERE.glob('design_fixed.json')) + list(HERE.glob('assessment_fixed.json'))
    files += [OLD / 'inputs.pkl', OLD / 'features_depth.pkl']
    for folder in ('wave_v23', 'wave_v25', 'wave_v27', 'wave_v28', 'wave_v29', 'wave_v30', 'wave_v31'):
        files += list((HERE.parent / folder).glob('*.py'))
    for key in inputs:
        for folder, extension in (('book', 'jsonl'), ('candle_1min', 'csv'), ('candle_5min', 'csv')):
            files.append(ROOT / folder / key[1] / (key[0] + '.' + extension))
    for signal in sorted({row['signal_id'] for row in specs}):
        files += [HERE.parent / 'wave_v30/directions' / (signal + '.npz'),
                  HERE.parent / 'wave_v31/sessions' / (signal + '.json.gz'),
                  HERE.parent / 'wave_v31/summaries' / (signal + '.json')]
    files += [HERE.parent / 'wave_v31/探索条件の固定.json']
    fixed = {'固定日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
             'conditions': specs, 'manager': manager, '全条件数': 96, '主条件数': 24, '診断数': 72,
             '全セッション': sessions, '共通評価7セッション': sessions[6:],
             '指定波': list(wave_metrics.EPISODES),
             '採用対象': 'H019__AT__V000のみ。他入口・診断最良への差替なし。',
             'データ': '既知13。未知検証と呼ばない。現在API・保存ライブの再利用なし。',
             'SHA256': {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(set(files))}}
    save(path, fixed)
    return fixed


def worker_init() -> None:
    """機能: 固定した入力と12種類の旧方向を子処理へ読む。

    引数: なし。返り値: なし (None)。
    """
    global INPUTS, ENTRIES, FIXED
    deny_network()
    INPUTS = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    ENTRIES = input_audit.load_entries(INPUTS)
    FIXED = read(HERE / '探索条件の固定.json')


def columns(spec: dict, key: tuple, ready: dict) -> tuple:
    """機能: 入口遅延と追跡ATR遅延を別々に構成する。

    引数: spec/ready (dict)、key (tuple)。返り値: 入口、追跡ATR列 (tuple[ndarray,ndarray])。
    """
    state, _ = input_audit.make_entry(ready, ENTRIES[spec['signal_id']][key], spec['entry_delay_seconds'])
    tracking, _ = input_audit.make_tracking_atr(ready, spec['trail_atr_delay_seconds'])
    return state, tracking


def retracements(result: dict, ready: dict, point_value: float) -> list[dict]:
    """機能: 全組の資産ピークから全返済までの悪化を測る。

    引数: result/ready (dict)、point_value (float)。返り値: 各組の計測値 (list[dict])。
    損失組も除外せず、利益が一度出た組かを別フラグにする。
    """
    rows = []
    for cycle in result['cycles']:
        number, begin, end = map(int, cycle[:3])
        base = result['curve'][begin - 1, 1] if begin else 0.
        path = result['curve'][begin:end + 1, 0] - base
        peak, final, risk = max(0., float(np.max(path))), float(cycle[3]), float(cycle[4])
        assert risk > 0
        np.testing.assert_allclose(path[-1], final, atol=1e-7, rtol=0)
        loss = max(0., peak - final)
        rows.append({'campaign': number, 'entry_row': begin, 'exit_row': end,
                     'peak_yen': peak * point_value, 'final_yen': final * point_value,
                     'retracement_yen': loss * point_value, 'risk_yen': risk * point_value,
                     'retracement_r': loss / risk, 'positive_peak': peak > 1e-8,
                     'holding_minutes': float((ready['time_s'][end] - ready['time_s'][begin]) / 60.)})
    return rows


def retracement_totals(rows: list[dict]) -> dict:
    """機能: 取引数の影響を隠さずピーク悪化を合計・平均・中央値で示す。

    引数: rows (list[dict])。返り値: 全組と利益経験組の集計 (dict)。
    """
    result = {}
    for label, part in (('all', rows), ('positive_peak', [r for r in rows if r['positive_peak']])):
        values = [r['retracement_r'] for r in part]
        yen = [r['retracement_yen'] for r in part]
        result[label] = {'cycles': len(part), 'sum_yen': sum(r['retracement_yen'] for r in part),
                         'sum_r': sum(values), 'mean_r': float(np.mean(values)) if values else None,
                         'median_r': float(np.median(values)) if values else None,
                         'mean_yen': float(np.mean(yen)) if yen else None,
                         'median_yen': float(np.median(yen)) if yen else None}
    result['holding_minutes'] = sum(r['holding_minutes'] for r in rows)
    return result


def periods(rows: list[dict], sessions: list[str]) -> dict:
    """機能: 銘柄ごとに同じ区間の金額・枚数・参加・ピーク悪化を合算する。

    引数: rows (list[dict])、sessions (list[str])。返り値: 銘柄別結果 (dict)。
    """
    output = {}
    for symbol in SYMBOLS:
        part = [row for row in rows if row['symbol'] == symbol and row['session'] in sessions]
        value = research.aggregate(part)
        for field in ('long_unit_minutes', 'short_unit_minutes', 'opening_orders'):
            value[field] = sum(row[field] for row in part)
        value['retracement'] = retracement_totals([r for row in part for r in row['retracements']])
        output[symbol] = value
    return output


def evaluate(spec: dict) -> dict:
    """機能: 一条件の全原本行を再生し損益・返却・指定波を保存する。

    引数: spec (dict)。返り値: 13区間と共通7区間の集計 (dict)。
    """
    identifier, started = spec['id'], time.perf_counter()
    rows, ledgers, waves, ledger_hash = [], [], [], hashlib.sha256()
    baseline = spec['atr_mode'] == 'initial' and spec['variant_id'] in ('V000', 'L300')
    reference = read(HERE.parent / 'wave_v31/sessions' / (spec['signal_id'] + '.json.gz')) if baseline else []
    old_rows = next((r['rows'] for r in reference if r['id'] == spec['signal_id'] + '__L000__V000'), [])
    for key, ready in INPUTS.items():
        state, tracking = columns(spec, key, ready)
        config = managers.make_config(FIXED['manager'], key[1], ready)
        result = engine.run(ready, state, config, detail=True, width_mode=spec['dynamic_trail_atr'],
                            observed_fill=spec['observed_fill'], trail_atr=tracking)
        row = research.summarize(result, config, key[1], key[0], identifier)
        row['two_largest_cycle_profits'] = sorted([float(v) * config['point_value'] for v in result['cycles'][:, 3] if v > 0], reverse=True)[:2]
        row.update(previous.participation(result, ready))
        if baseline:
            expected = next(r for r in old_rows if (r['session'], r['symbol']) == key)
            for field, value in expected.items():
                if field != 'id':
                    assert row[field] == value, (identifier, key, field)
        row['retracements'] = retracements(result, ready, config['point_value'])
        rows.append(row)
        ledger_hash.update(str(key).encode('utf-8'))
        ledger_hash.update(result['trades'].tobytes())
        ledgers.append({'session': key[0], 'symbol': key[1], 'config': config,
                        **{field: result[field].tolist() for field in ('trades', 'orders', 'cycles', 'stats')},
                        'curve_SHA256': hashlib.sha256(result['curve'].tobytes()).hexdigest()})
        for wave in FIXED['指定波']:
            if wave['session'] == key[0]:
                orders = wave_metrics.order_records(ready, state, result, engine.REASONS)
                waves.append(wave_metrics.episode_metrics({'id': identifier, 'manager': FIXED['manager']},
                            wave, ready, state, result, orders, config['point_value']))
    if baseline:
        old = read(HERE.parent / 'wave_v31/summaries' / (spec['signal_id'] + '.json'))
        expected = next(r for r in old['candidates'] if r['id'] == spec['signal_id'] + '__L000__V000')
        assert ledger_hash.hexdigest() == expected['ledger_hash']
    assert len(rows) == 26 and len(waves) == 8
    summary = {'id': identifier, 'spec': spec, 'symbols': periods(rows, FIXED['共通評価7セッション']),
               'all_symbols': periods(rows, FIXED['全セッション']), 'ledger_hash': ledger_hash.hexdigest(),
               'wave_passes': sum(r['正方向ネット20分目安達成'] for r in waves),
               '旧固定再現': baseline, '経過秒': time.perf_counter() - started,
               '探索固定SHA256': digest(HERE / '探索条件の固定.json')}
    for folder, value, extension in (('sessions', rows, '.json.gz'), ('ledgers', ledgers, '.json.gz'),
                                     ('waves', waves, '.json.gz'), ('summaries', summary, '.json')):
        save(HERE / folder / (identifier + extension), value)
    return summary


def main() -> None:
    """機能: 結果前監査を要求し、96条件を固定仕様で一括再生する。

    引数: --prepare (bool)、--workers (int)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    deny_network()
    fixed = prepare()
    if args.prepare:
        print('24主条件＋72診断を結果前固定。売買再生なし。', flush=True)
        return
    startup = read(HERE / '起動前監査.json')
    assert startup['実行可能'] is True
    assert startup['探索固定SHA256'] == digest(HERE / '探索条件の固定.json')
    for name, expected in startup['SHA256'].items():
        assert digest(ROOT / name) == expected
    started, results = time.perf_counter(), []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=worker_init) as pool:
        pending = [pool.submit(evaluate, spec) for spec in fixed['conditions']]
        for future in as_completed(pending):
            value = future.result()
            results.append(value)
            print(f"{len(results)}/96 {value['id']}", flush=True)
    assert len(results) == len({row['id'] for row in results}) == 96
    prepare()
    save(HERE / '全条件の期間集計.json.gz', sorted(results, key=lambda r: r['id']))
    save(HERE / '主再生の完了.json', {'全条件数': 96, '全入力数': 2496, '全波数': 768,
         '経過秒': time.perf_counter() - started, 'API取得数': 0, '現在保存物使用': False,
         '旧固定12一致': sum(r['旧固定再現'] for r in results) == 24,
         '探索固定SHA256': digest(HERE / '探索条件の固定.json')})


if __name__ == '__main__':
    main()
