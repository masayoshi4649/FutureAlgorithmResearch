"""仮想の新規準備時刻で実売買の参加を制御し、退出と再入場を分けて比較する。"""

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
OLD = HERE.parent / 'wave_v33'
sys.path.insert(0, str(OLD))
import atr_runner as prior
sys.path.insert(0, str(HERE))
import scheduler_design as design
import engine_scheduler as engine

save, read, digest = prior.save, prior.read, prior.digest
research, managers, wave_metrics = prior.research, prior.managers, prior.wave_metrics
retracements, retracement_totals = prior.retracements, prior.retracement_totals
INPUTS, ENTRIES, FIXED, SHADOWS = {}, {}, {}, {}
SYMBOLS = ('TOPIX', 'NK225')
RESULT_FIELDS = ('trades', 'orders', 'cycles', 'stats', 'curve', 'atr_curve')
EVENT_FIELDS = ('prepare_events', 'entry_preparations')
GATE_FIELDS = ('shadow_preparations', 'actual_preparations', 'shared_preparations',
               'extra_preparations', 'skipped_shadow_preparations',
               'shadow_opening_orders', 'actual_opening_orders',
               'matched_openings', 'unmatched_openings', 'skipped_holding',
               'skipped_cooldown', 'skipped_pending', 'skipped_other')


def fingerprints(result: dict) -> dict:
    """機能: 各数値配列の形と内容を固定する。

    引数: result (dict)。返り値: 全6結果の指紋 (dict)。
    """
    return {field: {'shape': list(result[field].shape),
                    'SHA256': hashlib.sha256(result[field].tobytes()).hexdigest()}
            for field in RESULT_FIELDS}


def prepare() -> dict:
    """機能: 格子・実装・既知入力を新結果の前に固定する。

    引数: なし。返り値: 固定記録 (dict)。固定後の変更は拒否する。
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
    old = read(OLD / '探索条件の固定.json')
    specs = design.catalog()
    assert len(specs) == len({row['id'] for row in specs}) == 192
    files = [ROOT / name for name in old['SHA256']]
    files += [HERE / name for name in ('scheduler_runner.py', 'scheduler_design.py',
        'scheduler_assessment.py', 'engine_scheduler.py', 'scheduler_input_audit.py',
        'runner_synthetic_audit.py', 'scheduler_design_fixed.json', 'scheduler_assessment_fixed.json')]
    files += [OLD / '探索条件の固定.json', OLD / '完備監査.json']
    files += list(OLD.glob('*.py'))
    for spec in specs:
        name = spec['signal_id'] + '__' + spec['atr_mode_id'] + '__' + spec['variant_id']
        files += [OLD / 'sessions' / (name + '.json.gz'), OLD / 'ledgers' / (name + '.json.gz'),
                  OLD / 'summaries' / (name + '.json')]
    fixed = {'固定日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
        'conditions': specs, 'manager': old['manager'], '全条件数': 192, '主条件数': 48, '診断数': 144,
        '全セッション': old['全セッション'], '共通評価7セッション': old['共通評価7セッション'],
        '指定波': old['指定波'], '採用対象': 'H019__AT__SHADOW__V000のみ。他入口・診断最良への差替なし。',
        'データ': '既知13。未知検証ではない。現在API・保存ライブの再利用なし。',
        '仮想運転': '同じ入口遅延・約定モデルのA0通常。実売買から影響されず新規準備行だけを公開。',
        'SHA256': {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(set(files))}}
    save(path, fixed)
    return fixed


def worker_init() -> None:
    """機能: 保存入力と旧12入口を各実行処理へ読み込む。

    引数: なし。返り値: なし (None)。外部通信を禁止する。
    """
    global INPUTS, ENTRIES, FIXED, SHADOWS
    prior.deny_network()
    INPUTS = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    ENTRIES = prior.input_audit.load_entries(INPUTS)
    FIXED = read(HERE / '探索条件の固定.json')
    SHADOWS = {}


def columns(spec: dict, key: tuple, ready: dict) -> tuple:
    """機能: 入口と追跡ATRの遅延を独立に作る。

    引数: spec/ready (dict)、key (tuple)。返り値: 入口と追跡ATR (tuple[ndarray,ndarray])。
    """
    state, _ = prior.input_audit.make_entry(ready, ENTRIES[spec['signal_id']][key], spec['entry_delay_seconds'])
    tracking, _ = prior.input_audit.make_tracking_atr(ready, spec['trail_atr_delay_seconds'])
    return state, tracking


def shadow_record(ready: dict, state: np.ndarray, config: dict, observed_fill: bool) -> dict:
    """機能: 実側と独立した固定A0の運転と準備履歴を作る。

    引数: ready/config (dict)、state (ndarray)、observed_fill (bool)。返り値: 影の小容量記録 (dict)。
    全未来を先に読み取る条件は使わず、一行ずつの準備イベントだけを公開する。
    """
    result = engine.run(ready, state, config, detail=True, width_mode=0, observed_fill=observed_fill)
    return {**{field: result[field].tolist() for field in (*EVENT_FIELDS, 'trades', 'orders', 'cycles', 'stats')},
            'result_fingerprints': fingerprints(result)}


def prepare_mask(shadow: dict, count: int) -> np.ndarray:
    """機能: 影の新設行だけを許可する。

    引数: shadow (dict)、count (int)。返り値: 行対応の許可列 (ndarray[bool])。
    約定行や将来の返済行では許可しない。
    """
    mask = np.zeros(count, dtype=np.bool_)
    for event in shadow['prepare_events']:
        row = int(event[1])
        assert 0 <= row < count and not mask[row]
        mask[row] = True
    return mask


def gate_metrics(result: dict, shadow: dict, ready: dict, gated: bool) -> dict:
    """機能: 影の準備に参加した実注文と見送った機会を数える。

    引数: result/shadow/ready (dict)、gated (bool)。返り値: 準備・新規件数 (dict)。
    一致は行だけでなく方向・水準・A0・期限・枚数が等しい場合に限る。
    """
    source = {int(event[1]): event for event in shadow['prepare_events']}
    actual = {int(event[1]): event for event in result['prepare_events']}
    assert len(source) == len(shadow['prepare_events']) and len(actual) == len(result['prepare_events'])
    shared = {row for row, event in actual.items() if row in source and np.array_equal(event[1:], source[row][1:])}
    source_entries = {int(event[3]): event for event in shadow['entry_preparations']}
    matched = 0
    for event in result['entry_preparations']:
        fill_row, prep_row = int(event[1]), int(event[3])
        if prep_row in shared and prep_row in source_entries and int(source_entries[prep_row][1]) == fill_row:
            matched += 1
    if gated:
        assert len(shared) == len(actual), '影に存在しない新設'
        assert matched == len(result['entry_preparations']), '影の準備又は約定にない実新規'
    reasons = {field: 0 for field in ('skipped_holding', 'skipped_cooldown', 'skipped_pending', 'skipped_other')}
    exits = result['cycles'][:, 2].astype(int)
    for row in sorted(set(source) - shared):
        prior_exits = exits[exits <= row]
        if sum(result['curve'][row, 2:4]) > .5:
            reasons['skipped_holding'] += 1
        elif len(prior_exits) and ready['time_s'][row] < ready['time_s'][prior_exits[-1]] + 300:
            reasons['skipped_cooldown'] += 1
        elif np.isfinite(result['atr_curve'][row, 9]):
            reasons['skipped_pending'] += 1
        else:
            reasons['skipped_other'] += 1
    return {'shadow_preparations': len(source), 'actual_preparations': len(actual),
            'shared_preparations': len(shared), 'extra_preparations': len(actual) - len(shared),
            'skipped_shadow_preparations': len(source) - len(shared),
            'shadow_opening_orders': len(shadow['entry_preparations']),
            'actual_opening_orders': len(result['entry_preparations']),
            'matched_openings': matched, 'unmatched_openings': len(result['entry_preparations']) - matched,
            **reasons}


def periods(rows: list[dict], sessions: list[str]) -> dict:
    """機能: 従来の金額・枚数・返却指標と新規制御件数を合算する。

    引数: rows (list[dict])、sessions (list[str])。返り値: 銘柄別期間集計 (dict)。
    """
    output = prior.periods(rows, sessions)
    for symbol in SYMBOLS:
        part = [r for r in rows if r['symbol'] == symbol and r['session'] in sessions]
        output[symbol]['gate'] = {field: sum(r['gate'][field] for r in part) for field in GATE_FIELDS}
    return output


def evaluate(spec: dict) -> dict:
    """機能: 1条件を全26入力で再生し、影と実の台帳を保存する。

    引数: spec (dict)。返り値: 13区間・後7区間の集計 (dict)。
    """
    identifier, started = spec['id'], time.perf_counter()
    rows, ledgers, waves, ledger_hash = [], [], [], hashlib.sha256()
    old_id = spec['signal_id'] + '__' + spec['atr_mode_id'] + '__' + spec['variant_id']
    old_ledgers = {(r['session'], r['symbol']): r for r in read(OLD / 'ledgers' / (old_id + '.json.gz'))}
    old_rows = {(r['session'], r['symbol']): r for r in read(OLD / 'sessions' / (old_id + '.json.gz'))}
    for key, ready in INPUTS.items():
        state, tracking = columns(spec, key, ready)
        config = managers.make_config(FIXED['manager'], key[1], ready)
        cache_key = (spec['signal_id'], spec['entry_delay_seconds'], spec['observed_fill'], key)
        if cache_key not in SHADOWS:
            SHADOWS[cache_key] = shadow_record(ready, state, config, spec['observed_fill'])
        shadow = SHADOWS[cache_key]
        allow = prepare_mask(shadow, len(state)) if spec['gated'] else None
        result = engine.run(ready, state, config, detail=True, width_mode=spec['dynamic_trail_atr'],
            observed_fill=spec['observed_fill'], trail_atr=tracking, prepare_allow=allow)
        result_hashes = fingerprints(result)
        # ----------------------------------------
        # 通常は前回の成績を厳密に再現し、固定A0の制御は仮想側と同値にする。
        if not spec['gated']:
            expected = old_ledgers[key]
            for field in ('trades', 'orders', 'cycles', 'stats'):
                assert result[field].tolist() == expected[field], (identifier, key, field)
            assert result_hashes['curve']['SHA256'] == expected['curve_SHA256']
        if spec['gated'] and not spec['dynamic_trail_atr']:
            for field in ('trades', 'orders', 'cycles', 'stats', 'curve'):
                assert result_hashes[field] == shadow['result_fingerprints'][field], (identifier, key, field)
            for field in EVENT_FIELDS:
                assert result[field].tolist() == shadow[field]
        # ----------------------------------------
        row = research.summarize(result, config, key[1], key[0], identifier)
        row['two_largest_cycle_profits'] = sorted([float(v) * config['point_value'] for v in result['cycles'][:, 3] if v > 0], reverse=True)[:2]
        row.update(prior.previous.participation(result, ready))
        row['retracements'] = retracements(result, ready, config['point_value'])
        if not spec['gated']:
            for field, value in old_rows[key].items():
                if field != 'id':
                    assert row[field] == value, (identifier, key, field)
        row['gate'] = gate_metrics(result, shadow, ready, spec['gated'])
        rows.append(row)
        ledger_hash.update(str(key).encode('utf-8'))
        ledger_hash.update(result['trades'].tobytes())
        ledgers.append({'session': key[0], 'symbol': key[1], 'config': config,
            **{field: result[field].tolist() for field in ('trades', 'orders', 'cycles', 'stats', *EVENT_FIELDS)},
            'curve_SHA256': result_hashes['curve']['SHA256'], 'result_fingerprints': result_hashes, 'shadow': shadow,
            'prepare_allow_SHA256': hashlib.sha256(prepare_mask(shadow, len(state)).tobytes()).hexdigest() if spec['gated'] else None})
        for wave in FIXED['指定波']:
            if wave['session'] == key[0]:
                orders = wave_metrics.order_records(ready, state, result, engine.REASONS)
                waves.append(wave_metrics.episode_metrics({'id': identifier, 'manager': FIXED['manager']},
                    wave, ready, state, result, orders, config['point_value']))
    assert len(rows) == 26 and len(waves) == 8
    summary = {'id': identifier, 'spec': spec, 'symbols': periods(rows, FIXED['共通評価7セッション']),
        'all_symbols': periods(rows, FIXED['全セッション']), 'ledger_hash': ledger_hash.hexdigest(),
        'wave_passes': sum(r['正方向ネット20分目安達成'] for r in waves),
        '旧通常再現': not spec['gated'], '固定制御同値': spec['gated'] and not spec['dynamic_trail_atr'],
        '経過秒': time.perf_counter() - started, '探索固定SHA256': digest(HERE / '探索条件の固定.json')}
    for folder, value, extension in (('sessions', rows, '.json.gz'), ('ledgers', ledgers, '.json.gz'),
                                    ('waves', waves, '.json.gz'), ('summaries', summary, '.json')):
        save(HERE / folder / (identifier + extension), value)
    return summary


def main() -> None:
    """機能: 事前監査を要求し固定192条件を再生する。

    引数: --prepare (bool)、--workers (int)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    prior.deny_network()
    fixed = prepare()
    if args.prepare:
        print('48主条件＋144診断を結果前固定。売買再生なし。', flush=True)
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
            results.append(future.result())
            print(f"{len(results)}/192 {results[-1]['id']}", flush=True)
    assert len(results) == len({row['id'] for row in results}) == 192
    prepare()
    save(HERE / '全条件の期間集計.json.gz', sorted(results, key=lambda r: r['id']))
    save(HERE / '主再生の完了.json', {'全条件数': 192, '全入力数': 4992, '全波数': 1536,
        '経過秒': time.perf_counter() - started, 'API取得数': 0, '現在保存物使用': False,
        '旧通常96一致': sum(r['旧通常再現'] for r in results) == 96,
        '固定制御48同値': sum(r['固定制御同値'] for r in results) == 48,
        '探索固定SHA256': digest(HERE / '探索条件の固定.json')})


if __name__ == '__main__':
    main()
