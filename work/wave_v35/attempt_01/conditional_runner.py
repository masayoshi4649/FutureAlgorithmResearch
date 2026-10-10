"""最初6区間だけで追跡方式を選択し、後7区間へ固定して再生する。"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE.parent / 'wave_v34'
sys.path.insert(0, str(OLD))
import scheduler_runner as previous
sys.path.insert(0, str(HERE))
import conditional_design as design
import conditional_assessment as assessment
import engine_conditional as engine
import conditional_inputs as input_api

read, digest = previous.read, previous.digest
research, managers, wave_metrics = previous.research, previous.managers, previous.wave_metrics
retracements, retracement_totals = previous.retracements, previous.retracement_totals
SYMBOLS = ('TOPIX', 'NK225')
INPUTS, FIXED, SHADOWS, PHASE = {}, {}, {}, ''
RESULT_FIELDS = (*previous.RESULT_FIELDS, *previous.EVENT_FIELDS, 'conditional_curve', 'trail_events')
STORED_FIELDS = ('trades', 'orders', 'cycles', 'stats', 'prepare_events', 'entry_preparations', 'trail_events')
CONTROL_FIELDS = ('held_rows', 'adverse_rows', 'shortening_enabled_rows', 'contracted_atr_rows',
    'stricter_candidate_rows', 'fixed_advance_events', 'additional_advance_events',
    'conditional_advance_events', 'campaigns', 'earlier_exits', 'equal_exit_rows',
    'changed_repayments', 'exit_difference_yen', 'exit_difference_r',
    'held_seconds', 'adverse_seconds', 'shortening_enabled_seconds')


def save(path: Path, value: object) -> None:
    """機能: 内容が同じなら圧縮ファイルも同じになるよう保存する。

    引数: path (Path)、value (JSON化できるobject)。返り値: なし (None)。
    """
    temporary = path.with_suffix(path.suffix + '.tmp')
    data = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    temporary.write_bytes(gzip.compress(data, mtime=0) if path.suffix == '.gz' else data)
    temporary.replace(path)


def fingerprints(result: dict) -> dict:
    """機能: 全数値結果の内容と形状を指紋へ結ぶ。

    引数: result (dict)。返り値: 配列ごとの形とSHA256 (dict)。
    """
    return {name: {'shape': list(result[name].shape),
                   'SHA256': hashlib.sha256(result[name].tobytes()).hexdigest()} for name in RESULT_FIELDS}


def control_metrics(result: dict, shadow: dict, config: dict, time_s: np.ndarray) -> tuple[dict, list]:
    """機能: 悪化・幅縮小・注文変化と同じ新規からの退出差を分離する。

    引数: result/shadow/config (dict)、time_s (ndarray[float]) は原本秒列。
    返り値: 計数・次行までの保有秒数と全組対応明細 (tuple[dict,list])。
    """
    c = result['conditional_curve']
    ix = {name: i for i, name in enumerate(engine.CONDITIONAL_COLUMNS)}
    held = c[:, ix['direction']] != 0
    adverse = held & (c[:, ix['deterioration_direction']] == -c[:, ix['direction']])
    enabled = held & (c[:, ix['shortening_enabled']] == 1)
    durations = np.diff(time_s, append=time_s[-1])
    assert len(durations) == len(c) and np.all(durations >= 0)
    contracted = enabled & (c[:, ix['current_atr']] < c[:, ix['initial_atr']])
    strict = np.isfinite(c[:, ix['short_candidate']]) & (
        c[:, ix['direction']] * (c[:, ix['short_candidate']] - c[:, ix['fixed_candidate']]) > 1e-8)
    kinds = result['trail_events'][:, engine.TRAIL_EVENT_COLUMNS.index('advance_kind')]
    # ----------------------------------------
    # 新設準備・全新規が同じで、実が影より遅く全返済しないことを全組で要求する。
    for name in ('prepare_events', 'entry_preparations'):
        assert result[name].tolist() == shadow[name], '新規機会不一致: ' + name
    actual_opens = [r for r in result['orders'].tolist() if r[7] == 1]
    shadow_opens = [r for r in shadow['orders'] if r[7] == 1]
    assert actual_opens == shadow_opens
    assert len(result['cycles']) == len(shadow['cycles'])
    factor, pairs = config['point_value'], []
    for actual, virtual in zip(result['cycles'], shadow['cycles'], strict=True):
        assert actual[0] == virtual[0] and actual[1] == virtual[1] and actual[2] <= virtual[2]
        assert actual[4] == virtual[4] and actual[5] == virtual[5] and actual[8] == virtual[8]
        campaign = int(actual[0])
        actual_legs = [r[2:] for r in result['trades'].tolist() if int(r[0]) == campaign]
        virtual_legs = [r[2:] for r in shadow['trades'] if int(r[0]) == campaign]
        delta = float(actual[3] - virtual[3])
        pairs.append({'campaign': campaign, 'entry_row': int(actual[1]), 'shadow_exit_row': int(virtual[2]),
            'actual_exit_row': int(actual[2]), 'shadow_yen': virtual[3] * factor,
            'actual_yen': actual[3] * factor, 'difference_yen': delta * factor,
            'difference_r': delta / virtual[4], 'changed_repayments': actual_legs != virtual_legs})
    value = {'held_rows': int(held.sum()), 'adverse_rows': int(adverse.sum()),
        'shortening_enabled_rows': int(enabled.sum()), 'contracted_atr_rows': int(contracted.sum()),
        'stricter_candidate_rows': int(strict.sum()), 'fixed_advance_events': int(np.sum(kinds == 1)),
        'additional_advance_events': int(np.sum(kinds >= 2)), 'conditional_advance_events': int(np.sum(kinds == 3)),
        'campaigns': len(pairs), 'earlier_exits': sum(r['actual_exit_row'] < r['shadow_exit_row'] for r in pairs),
        'equal_exit_rows': sum(r['actual_exit_row'] == r['shadow_exit_row'] for r in pairs),
        'changed_repayments': sum(r['changed_repayments'] for r in pairs),
        'exit_difference_yen': sum(r['difference_yen'] for r in pairs),
        'exit_difference_r': sum(r['difference_r'] for r in pairs),
        'held_seconds': float(durations[held].sum()),
        'adverse_seconds': float(durations[adverse].sum()),
        'shortening_enabled_seconds': float(durations[enabled].sum())}
    assert set(value) == set(CONTROL_FIELDS)
    return value, pairs


def periods(rows: list[dict], sessions: list[str]) -> dict:
    """機能: 従来の金額・枚数・参加量と条件付き短縮の作用を銘柄別に合算する。

    引数: rows (list[dict])、sessions (list[str])。返り値: 銘柄別集計 (dict)。
    """
    values = previous.prior.periods(rows, sessions)
    for symbol in SYMBOLS:
        part = [r for r in rows if r['symbol'] == symbol and r['session'] in sessions]
        values[symbol]['control'] = {field: sum(r['control'][field] for r in part) for field in CONTROL_FIELDS}
    return values


def prepare() -> dict:
    """機能: 全条件・選択・入力・実装を新しい損益の前に固定する。

    引数: なし。返り値: 固定記録 (dict)。既存の固定内容と異なれば停止する。
    """
    path = HERE / '探索条件の固定.json'
    if path.exists():
        fixed = read(path)
        assert fixed['conditions'] == design.catalog()
        for name, expected in fixed['SHA256'].items():
            assert digest(ROOT / name) == expected, '固定後変更: ' + name
        return fixed
    old = read(OLD / '探索条件の固定.json')
    specs = design.catalog()
    assert len(specs) == len({r['id'] for r in specs}) == 840
    files = [ROOT / name for name in old['SHA256']]
    files += [OLD / '探索条件の固定.json', OLD / '完備監査.json'] + list(OLD.glob('*.py'))
    files += [HERE / name for name in ('conditional_runner.py', 'conditional_design.py',
        'conditional_assessment.py', 'engine_conditional.py', 'runner_synthetic_audit.py',
        'conditional_design_fixed.json', 'conditional_assessment_fixed.json',
        'supplementary_diagnostics.py', 'supplementary_design_fixed.json')]
    input_fixed = read(HERE / 'conditional_input_fixed.json')
    files += [HERE / 'conditional_input_fixed.json'] + [ROOT / name for name in input_fixed['SHA256']]
    sessions = old['全セッション']
    fixed = {'固定日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), 'conditions': specs,
        'manager': old['manager'], '全条件数': 840, '主条件数': 168, '診断数': 672,
        '全セッション': sessions, '選択用6セッション': sessions[:6], '共通評価7セッション': sessions[6:],
        '指定波': old['指定波'], '段階': '最初6全条件→選択固定→後7全条件。運用の最初6は固定A0。',
        'データ': '全13は既知。現在API・保存ライブ不使用。未知検証とは呼ばない。',
        'SHA256': {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(set(files))}}
    save(path, fixed)
    for phase in ('training', 'evaluation', ''):
        for folder in ('sessions', 'ledgers', 'waves', 'summaries'):
            (HERE / phase / folder).mkdir(parents=True, exist_ok=True)
    return fixed


def worker_init(phase: str) -> None:
    """機能: 指定段階の入力だけを再生対象へ読み込む。

    引数: phase (str) はtraining又はevaluation。返り値: なし (None)。
    """
    global INPUTS, FIXED, SHADOWS, PHASE
    previous.prior.deny_network()
    FIXED = read(HERE / '探索条件の固定.json')
    selected = FIXED['選択用6セッション'] if phase == 'training' else FIXED['共通評価7セッション']
    all_inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    INPUTS = {key: value for key, value in all_inputs.items() if key[0] in selected}
    assert len(INPUTS) == (12 if phase == 'training' else 14)
    input_api.initialize(INPUTS)
    SHADOWS, PHASE = {}, phase


def columns(spec: dict, key: tuple, ready: dict) -> tuple:
    """機能: 入口時計と悪化条件を別々の過去入力から用意する。

    引数: spec/ready (dict)、key (tuple)。返り値: 入口・悪化方向・根拠行 (tuple[ndarray,...])。
    """
    state = input_api.entry(spec['signal_id'], spec['entry_clock_scale'], key)
    direction, source = input_api.deterioration(spec['condition_id'], key, spec['random_seed'])
    if spec.get('reverse_deterioration', False):
        direction = -direction
    return state, direction, source


def shadow_record(ready: dict, state: np.ndarray, config: dict, observed: bool) -> dict:
    """機能: 実の短縮条件や損益に依存しないA0の仮想記録を作る。

    引数: ready/config (dict)、state (ndarray)、observed (bool)。返り値: 仮想台帳 (dict)。
    """
    result = engine.run(ready, state, config, detail=True, width_mode=0, observed_fill=observed)
    return {**{field: result[field].tolist() for field in STORED_FIELDS}, 'result_fingerprints': fingerprints(result)}


def evaluate(spec: dict, destination: str = '') -> dict:
    """機能: 一条件の一段階を再生し、全玉と全新規の一致証跡を保存する。

    引数: spec (dict)、destination (str) は補助診断用の保存先。返り値: 段階の集計 (dict)。
    """
    started, rows, ledgers, waves = time.perf_counter(), [], [], []
    for key, ready in INPUTS.items():
        state, deterioration, source = columns(spec, key, ready)
        config = managers.make_config(FIXED['manager'], key[1], ready)
        cache = (spec['signal_id'], spec['entry_clock_scale'], spec['observed_fill'], key)
        if cache not in SHADOWS:
            SHADOWS[cache] = shadow_record(ready, state, config, spec['observed_fill'])
        shadow = SHADOWS[cache]
        allow = previous.prepare_mask(shadow, len(state))
        result = engine.run(ready, state, config, detail=True, width_mode=spec['width_mode'],
            observed_fill=spec['observed_fill'], deterioration=deterioration,
            deterioration_source=source, prepare_allow=allow)
        hashes = fingerprints(result)
        if spec['width_mode'] == 0:
            assert hashes == shadow['result_fingerprints'], '固定A0の恒等性違反'
        row = research.summarize(result, config, key[1], key[0], spec['id'])
        row['two_largest_cycle_profits'] = sorted([float(v) * config['point_value'] for v in result['cycles'][:, 3] if v > 0], reverse=True)[:2]
        row.update(previous.prior.previous.participation(result, ready))
        row['retracements'] = retracements(result, ready, config['point_value'])
        row['control'], row['exit_pairs'] = control_metrics(result, shadow, config, ready['time_s'])
        row['completed_at'] = float(ready['time_s'][-1])
        row['complete'] = bool(result['stats'][9] == 0 and len(result['cycles']) == len(result['entry_preparations']))
        assert row['complete'] is True
        rows.append(row)
        ledgers.append({'session': key[0], 'symbol': key[1], 'config': config,
            **{field: result[field].tolist() for field in STORED_FIELDS},
            'curve_SHA256': hashes['curve']['SHA256'], 'result_fingerprints': hashes, 'shadow': shadow,
            'prepare_allow_SHA256': hashlib.sha256(allow.tobytes()).hexdigest(),
            'deterioration_SHA256': hashlib.sha256(deterioration.tobytes()).hexdigest(),
            'deterioration_source_SHA256': hashlib.sha256(source.tobytes()).hexdigest()})
        for wave in FIXED['指定波']:
            if wave['session'] == key[0]:
                orders = wave_metrics.order_records(ready, state, result, engine.REASONS)
                waves.append(wave_metrics.episode_metrics({'id': spec['id'], 'manager': FIXED['manager']},
                    wave, ready, state, result, orders, config['point_value']))
    assert len(rows) == (12 if PHASE == 'training' else 14)
    assert len(waves) == (8 if PHASE == 'training' else 0)
    summary = {'id': spec['id'], 'phase': PHASE, 'spec': spec,
        'symbols': periods(rows, sorted({r['session'] for r in rows})), '経過秒': time.perf_counter() - started,
        '探索固定SHA256': digest(HERE / '探索条件の固定.json')}
    for folder, value, extension in (('sessions', rows, '.json.gz'), ('ledgers', ledgers, '.json.gz'),
                                    ('waves', waves, '.json.gz'), ('summaries', summary, '.json')):
        save(HERE / destination / PHASE / folder / (spec['id'] + extension), value)
    return summary


def run_phase(fixed: dict, phase: str, workers: int) -> None:
    """機能: 同じ全840条件の指定段階を一括実行する。

    引数: fixed (dict)、phase (str)、workers (int)。返り値: なし (None)。
    """
    with ProcessPoolExecutor(max_workers=workers, initializer=worker_init, initargs=(phase,)) as pool:
        futures = [pool.submit(evaluate, spec) for spec in fixed['conditions']]
        for count, future in enumerate(as_completed(futures), 1):
            result = future.result()
            print(f"{phase} {count}/840 {result['id']}", flush=True)


def freeze_selection(fixed: dict) -> dict:
    """機能: 初期6専用の資料だけから方式を決め、後半開始前へ固定する。

    引数: fixed (dict)。返り値: 選択記録 (dict)。後半7の損益を読まない。
    """
    inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    cutoff = min(r['start'] for key, r in inputs.items() if key[0] in fixed['共通評価7セッション'])
    paths = [HERE / 'training/sessions' / (spec['id'] + '.json.gz') for spec in fixed['conditions'] if spec['variant_id'] == 'V000']
    training = {p.name.removesuffix('.json.gz'): read(p) for p in paths}
    result = assessment.select_training(training, cutoff)
    payload = {'選択': result, 'cutoff': float(cutoff),
        '選択用SHA256': {p.relative_to(ROOT).as_posix(): digest(p) for p in paths},
        '探索固定SHA256': digest(HERE / '探索条件の固定.json'),
        '選択実装SHA256': digest(HERE / 'conditional_assessment.py'),
        '確定日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), '後7再生前': True}
    path = HERE / '選択固定.json'
    if path.exists():
        existing = read(path)
        assert {k: v for k, v in existing.items() if k != '確定日時'} == {
            k: v for k, v in payload.items() if k != '確定日時'}, '既存の方式選択と不一致'
        return existing
    save(path, payload)
    return payload


def combine(spec: dict, fixed: dict, destination: str = '') -> dict:
    """機能: 選択用6と後7を結合し、研究用固定条件の13成績を作る。

    引数: spec/fixed (dict)、destination (str)。返り値: 研究用集計 (dict)。自動運用の13成績とは別物。
    """
    groups = {}
    for folder in ('sessions', 'ledgers', 'waves'):
        rows = read(HERE / destination / 'training' / folder / (spec['id'] + '.json.gz')) + read(HERE / destination / 'evaluation' / folder / (spec['id'] + '.json.gz'))
        groups[folder] = rows
        save(HERE / destination / folder / (spec['id'] + '.json.gz'), rows)
    rows = groups['sessions']
    assert len(rows) == 26 and len(groups['waves']) == 8
    ledger_hash = hashlib.sha256()
    for ledger in groups['ledgers']:
        ledger_hash.update(str((ledger['session'], ledger['symbol'])).encode('utf-8'))
        ledger_hash.update(np.array(ledger['trades'], dtype=float).reshape(-1, 11).tobytes())
    summary = {'id': spec['id'], 'spec': spec, 'all_symbols': periods(rows, fixed['全セッション']),
        'symbols': periods(rows, fixed['共通評価7セッション']),
        'training_symbols': periods(rows, fixed['選択用6セッション']), 'ledger_hash': ledger_hash.hexdigest(),
        'wave_passes': sum(r['正方向ネット20分目安達成'] for r in groups['waves']),
        '全新規一致': True, '全返済が影以前': True,
        '探索固定SHA256': digest(HERE / '探索条件の固定.json')}
    save(HERE / destination / 'summaries' / (spec['id'] + '.json'), summary)
    return summary


def main() -> None:
    """機能: 事前監査後、初期6→選択固定→後7の順に全840を実行する。

    引数: --prepare (bool)、--workers (int)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    previous.prior.deny_network()
    fixed = prepare()
    if args.prepare:
        print('主168＋診断672の二段階再生を結果前固定。', flush=True)
        return
    startup = read(HERE / '起動前監査.json')
    assert startup['実行可能'] is True and startup['探索固定SHA256'] == digest(HERE / '探索条件の固定.json')
    for name, expected in startup['SHA256'].items():
        assert digest(ROOT / name) == expected
    started = time.perf_counter()
    run_phase(fixed, 'training', args.workers)
    selected = freeze_selection(fixed)
    selection_hash = digest(HERE / '選択固定.json')
    print('最初6だけの方式選択を固定。後7の再生へ進む。', flush=True)
    run_phase(fixed, 'evaluation', args.workers)
    assert selection_hash == digest(HERE / '選択固定.json')
    result = [combine(spec, fixed) for spec in fixed['conditions']]
    prepare()
    save(HERE / '全条件の期間集計.json.gz', result)
    save(HERE / '主再生の完了.json', {'全条件数': 840, '全入力数': 21840, '全波数': 6720,
        '前6入力数': 10080, '後7入力数': 11760, '選択固定SHA256': selection_hash,
        '経過秒': time.perf_counter() - started, 'API取得数': 0, '現在保存物使用': False,
        '探索固定SHA256': digest(HERE / '探索条件の固定.json')})


if __name__ == '__main__':
    main()
