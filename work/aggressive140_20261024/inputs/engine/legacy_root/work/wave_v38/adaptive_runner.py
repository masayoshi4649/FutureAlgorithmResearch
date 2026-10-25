"""復元方式の選択・数量・予算を分けた固定条件を再生する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / 'wave_v33'))
import atr_runner as base
sys.path.insert(0, str(HERE))
import adaptive_design as design
import engine_partial_restore as engine
assert Path(engine.__file__).resolve().parent == HERE
assert Path(engine.shadow_engine.__file__).resolve().parent == HERE
import branch_inputs_runtime as inputs
import adaptive_cash_reconstruction as accounting
assert Path(engine.__file__).resolve().parent == HERE
assert Path(engine.shadow_engine.__file__).resolve().parent == HERE

INPUTS, FIXED, SHADOWS = {}, {}, {}
SHADOW_GROUP = None
SYMBOLS = ('TOPIX', 'NK225')
FIELDS = engine.FIELDS + ('prepare_events', 'entry_preparations', 'control_curve',
    'slot_curve', 'slot_events', 'adjustment_events', 'budget_events', 'branch_events', 'branch_curve')
STORED = ('trades', 'cycles', 'orders', 'stats', 'prepare_events', 'entry_preparations',
    'slot_events', 'adjustment_events', 'budget_events', 'branch_events')
EXTRA_SUMS = ('long_unit_minutes', 'short_unit_minutes', 'opening_orders', 'reductions',
    'restorations', 'reduced_units', 'restored_units', 'adjustment_cancellations',
    'budget_requests', 'budget_completions', 'budget_deferrals', 'budget_excess_yen',
    'contradictory_restore_decisions', 'initial_actual_risk_yen', 'initial_shadow_risk_yen',
    'signal_choices','timer_choices','branch_missing','branch_neutral','branch_favorable','branch_adverse',
    'cycle_risk_excess_yen','cycle_risk_excess_count')


def digest(path: Path) -> str:
    """機能: 保存内容をSHA256へ固定する。

    引数: path (Path)。返り値: 指紋 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> object:
    """機能: 通常又は圧縮したJSONを読む。

    引数: path (Path)。返り値: 保存内容 (object)。
    """
    payload = path.read_bytes()
    return json.loads(gzip.decompress(payload) if path.suffix == '.gz' else payload)


def save(path: Path, value: object) -> None:
    """機能: 有限JSONを同じ圧縮形式で原子的に保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(gzip.compress(payload, mtime=0) if path.suffix == '.gz' else payload)
    temporary.replace(path)


def reject_network(*args: object, **kwargs: object) -> None:
    """機能: 保存データ再生中の外部取得を拒否する。

    引数: args/kwargs (object)。返り値: なし (None)。常に例外。
    """
    raise RuntimeError('保存データの再生から現在データを取得しません')


def initialize() -> None:
    """機能: 固定入力を各処理へ読み、影のキャッシュを空にする。

    引数: なし。返り値: なし (None)。
    """
    global INPUTS, FIXED, SHADOW_GROUP
    socket.socket.connect = reject_network
    socket.create_connection = reject_network
    INPUTS = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    FIXED = read(HERE / '探索条件の固定.json')
    inputs.initialize(INPUTS)
    SHADOWS.clear(); SHADOW_GROUP = None
    assert len(INPUTS) == 26 and len(FIXED['conditions']) == len(design.catalog())


def columns(spec: dict, key: tuple) -> tuple:
    """機能: 入口・悪化・回復・公開品質を凍結した列へ接続する。

    引数: spec (dict)、key (tuple)。返り値: 入口と悪化・復元・分岐の10配列 (tuple)。
    """
    ready = INPUTS[key]
    state = inputs.entry(spec['signal_id'], spec['entry_scale'], key)
    policy = spec['policy']
    if policy['kind'] != 'dynamic':
        zero = np.zeros(len(state), np.int8)
        source = np.full(len(state), -1, np.int64)
        valid=np.zeros(len(state),bool)
        return state,zero,source,zero,source,valid,zero,source,valid,zero
    bad, bad_source, _ = inputs.directions(policy['bad_id'], key, spec['bad_scale'],spec['bad_seed'],'bad')
    good, good_source, _ = inputs.directions(policy['good_id'], key, spec['good_scale'],spec['good_seed'],'good')
    valid = inputs.publication_valid(policy['good_id'], key, spec['good_scale'])
    branch,branch_source,_=inputs.condition('B01',key,spec['branch_scale'])
    branch_valid=inputs.publication_valid('B01',key,spec['branch_scale'])
    choice=inputs.branch_choice(key,spec['branch_seed'],spec['branch_scale']) if spec['branch_seed'] is not None else np.zeros(len(state),np.int8)
    assert len(ready['last']) == len(good)
    return state,bad,bad_source,good,good_source,valid,branch,branch_source,branch_valid,choice


def shadow(spec: dict, key: tuple, state: np.ndarray, config: dict) -> dict:
    """機能: 同じ入口・約定の影のみ再利用し、入口切替時に全旧影を捨てる。

    引数: spec/config (dict)、key (tuple)、state (ndarray)。返り値: 独立影 (dict)。
    """
    global SHADOW_GROUP
    group = spec['signal_id'], spec['entry_scale'], spec['observed_fill'],spec['min_delay_seconds']
    if group != SHADOW_GROUP:
        SHADOWS.clear(); SHADOW_GROUP = group
    if key not in SHADOWS:
        SHADOWS[key] = engine.make_shadow(INPUTS[key], state, config, spec['observed_fill'],spec['min_delay_seconds'])
    return SHADOWS[key]


def fingerprints(result: dict, fields: tuple = FIELDS) -> dict:
    """機能: 全配列の形状・型・内容を台帳へ結びつける。

    引数: result (dict)、fields (tuple)。返り値: 指紋 (dict)。
    """
    return {name: dict(shape=list(result[name].shape), dtype=result[name].dtype.str,
        SHA256=hashlib.sha256(result[name].tobytes()).hexdigest()) for name in fields}


def session_row(identifier: str, ready: dict, result: dict, config: dict, bad: np.ndarray,
                basic: dict, curves: dict) -> dict:
    """機能: 全決済・元組・減量復元・予算超過・保有量を集計する。

    引数: identifier (str)、ready/result/config/basic/curves (dict)、bad (ndarray)。
    返り値: 一セッションの集計 (dict)。Rは元q0基準と実初回数量基準を分ける。
    """
    row = base.research.summarize(result, config, ready['symbol'], ready['session'], identifier)
    for field in basic.keys() & row.keys():
        if isinstance(basic[field], (int, float)):
            assert abs(basic[field] - row[field]) <= 1e-6, (identifier, field)
    factor = config['point_value']
    cycles, orders, adjustments, budgets = (result[k] for k in ('cycles', 'orders', 'adjustment_events', 'budget_events'))
    reduce = adjustments[(adjustments[:, 2] == 2) & (adjustments[:, 3] == -1)]
    restore = adjustments[(adjustments[:, 2] == 2) & (adjustments[:, 3] == 1)]
    restore_decisions = adjustments[(adjustments[:, 2] == 1) & (adjustments[:, 3] == 1)]
    complete = budgets[budgets[:, 2] == 2]
    durations = np.diff(ready['time_s'], append=ready['time_s'][-1]) / 60.
    actual_risk = 0.
    for cycle in cycles:
        opening = orders[(orders[:, 2] == cycle[0]) & (orders[:, 6] == 20) & (orders[:, 7] == 1)]
        assert len(opening) == 1
        actual_risk += opening[0, 4] * cycle[5] * factor
    cycle_sides = {int(c[0]): int(c[8]) for c in cycles}
    branches=result['branch_events']
    excess=np.maximum(0.,-cycles[:,3]-cycles[:,4])*factor
    row.update(two_largest_cycle_profits=sorted([float(v) * factor for v in cycles[:, 3] if v > 0], reverse=True)[:2],
        long_unit_minutes=float(np.sum(curves['long'] * durations)),
        short_unit_minutes=float(np.sum(curves['short'] * durations)),
        opening_orders=int(np.sum(orders[:, 7] == 1)),
        retracements=base.retracements(result, ready, factor),
        reductions=len(reduce), restorations=len(restore),
        reduced_units=int(reduce[:, 6].sum()), restored_units=int(restore[:, 6].sum()),
        adjustment_cancellations=int(np.sum(adjustments[:, 2] == 3)),
        budget_requests=int(np.sum(budgets[:, 2] == 1)), budget_completions=len(complete),
        budget_deferrals=int(np.sum(budgets[:, 2] == 3)),
        budget_excess_yen=float(complete[:, 6].sum() * factor),
        maximum_budget_excess_yen=max([0.] + (complete[:, 6] * factor).tolist()),
        maximum_budget_latency_seconds=max([0.] + complete[:, 7].tolist()),
        contradictory_restore_decisions=sum(int(bad[int(a[0])] == -cycle_sides[int(a[1])]) for a in restore_decisions),
        initial_actual_risk_yen=float(actual_risk), initial_shadow_risk_yen=float(cycles[:, 4].sum() * factor),
        signal_choices=int(np.sum(branches[:,3]==1)),timer_choices=int(np.sum(branches[:,3]==2)),
        branch_missing=int(np.sum(branches[:,7]==0)),branch_neutral=int(np.sum(branches[:,7]==1)),
        branch_favorable=int(np.sum(branches[:,7]==2)),branch_adverse=int(np.sum(branches[:,7]==3)),
        cycle_risk_excess_yen=float(excess.sum()),cycle_risk_excess_count=int(np.sum(excess>1e-6)),
        maximum_cycle_risk_excess_yen=float(max([0.]+excess.tolist())))
    return row


def period(rows: list[dict], sessions: list[str]) -> dict:
    """機能: 銘柄内の金額・数量・操作回数を期間集計する。

    引数: rows (list[dict])、sessions (list[str])。返り値: 銘柄別集計 (dict)。
    """
    output = {}
    for symbol in SYMBOLS:
        part = [r for r in rows if r['symbol'] == symbol and r['session'] in sessions]
        assert len(part) == len(sessions)
        value = base.research.aggregate(part)
        for name in EXTRA_SUMS: value[name] = sum(r[name] for r in part)
        for name in ('maximum_budget_excess_yen', 'maximum_budget_latency_seconds','maximum_cycle_risk_excess_yen'):
            value[name] = max(r[name] for r in part)
        value['average_cycle_payoff'] = base.research.ratio(value['cycle_profit_yen'] / value['cycle_wins'],
            value['cycle_loss_yen'] / value['cycle_losses']) if value['cycle_wins'] and value['cycle_losses'] else None
        value['retracement'] = base.retracement_totals([r for item in part for r in item['retracements']])
        output[symbol] = value
    return output


def evaluate(spec: dict, destination: str = '') -> dict:
    """機能: 一条件を全26入力で再生し、全行別会計と指定8波を保存する。

    引数: spec (dict)、destination (str)。返り値: 期間成績 (dict)。
    """
    identifier, started = spec['id'], time.perf_counter()
    assert destination in ('', 'supplementary')
    rows, ledgers, waves, checks = [], [], [], []
    ledger_hash = hashlib.sha256()
    for key, ready in sorted(INPUTS.items()):
        state,bad,bad_source,good,good_source,valid,branch,branch_source,branch_valid,choice = columns(spec, key)
        config = base.managers.make_config(FIXED['manager'], key[1], ready)
        original = shadow(spec, key, state, config)
        result = engine.run(ready, state, config, bad, bad_source, good, good_source, spec['policy'],
            observed_fill=spec['observed_fill'], detail=True, shadow=original, good_valid=valid,
            budget_enabled=spec['budget_enabled'],min_delay_seconds=spec['min_delay_seconds'],
            branch_direction=branch,branch_source=branch_source,branch_valid=branch_valid,
            branch_mode=spec['branch_mode'],branch_choice=choice,branch_seed=spec['branch_seed'])
        independent, curves = accounting.reconstruct(ready, result, key[1])
        baseline = spec['policy']['kind'] == 'baseline'
        shadow_equal = baseline and (not spec['budget_enabled'] or spec['min_delay_seconds']==0.)
        if shadow_equal:
            for field in engine.FIELDS:
                assert np.array_equal(result[field], original[field], equal_nan=True), ('A0差', key, field)
        row = session_row(identifier, ready, result, config, bad, independent, curves)
        rows.append(row)
        ledger_hash.update(str(key).encode('utf-8')); ledger_hash.update(result['trades'].tobytes())
        ledgers.append(dict(session=key[0], symbol=key[1], config=config,
            **{field: result[field].tolist() for field in STORED}, result_fingerprints=fingerprints(result),
            shadow_fingerprints=fingerprints(original, engine.FIELDS + ('plans','execution_plans','prepare_events','entry_preparations'))))
        checks.append(dict(session=key[0], symbol=key[1], **{k: v for k, v in independent.items() if k not in ('symbol', 'session')},
            全行会計一致=True, 元A0一致=shadow_equal, 影の全配列同値を要求=shadow_equal,
            独立時価SHA256=hashlib.sha256(curves['equity'].tobytes()).hexdigest()))
        for wave in FIXED['指定波']:
            if wave['session'] == key[0]:
                records = base.wave_metrics.order_records(ready, state, result, engine.REASONS)
                waves.append(base.wave_metrics.episode_metrics(dict(id=identifier, manager=FIXED['manager']),
                    wave, ready, state, result, records, config['point_value']))
    assert len(rows) == len(ledgers) == len(checks) == 26 and len(waves) == 8
    value = dict(id=identifier, spec=spec, all_symbols=period(rows, FIXED['全セッション']),
        symbols=period(rows, FIXED['後半7セッション']), ledger_hash=ledger_hash.hexdigest(),
        wave_passes=sum(r['正方向ネット20分目安達成'] for r in waves), 全26全行独立会計一致=True,
        経過秒=time.perf_counter()-started, 探索固定SHA256=digest(HERE/'探索条件の固定.json'))
    for folder, payload, suffix in (('sessions', rows, '.json.gz'), ('ledgers', ledgers, '.json.gz'),
        ('waves', waves, '.json.gz'), ('accounting', checks, '.json.gz'), ('summaries', value, '.json')):
        save(HERE/destination/folder/(identifier+suffix), payload)
    return value


def runtime_files() -> set[Path]:
    """機能: 実装依存と正式な結果前監査を固定対象に集める。

    引数: なし。返り値: ファイル集合 (set[Path])。
    """
    names = ('adaptive_design.py','adaptive_design_fixed.json','branch_inputs.py','branch_inputs_runtime.py','branch_input_fixed.json','branch_input_runtime_fixed.json',
        'engine_partial_restore.py','engine_shadow_plan.py','adaptive_cash_reconstruction.py',
        'adaptive_assessment.py','adaptive_assessment_fixed.json','adaptive_runner.py')
    paths = {HERE/name for name in names}
    paths.update((HERE.parent/'wave_v23/inputs.pkl', HERE.parent/'wave_v35/探索条件の固定.json'))
    for module in tuple(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if name:
            path = Path(name).resolve()
            if path.is_relative_to(ROOT/'work') and path.suffix == '.py': paths.add(path)
    return paths


def prepare() -> dict:
    """機能: 結果前の条件・入力・実装を固定し、以後の変更を拒否する。

    引数: なし。返り値: 固定記録 (dict)。
    """
    path = HERE/'探索条件の固定.json'
    if path.exists():
        fixed = read(path)
        assert fixed['conditions'] == design.catalog() and fixed['supplementary_conditions'] == design.supplementary()
        for relative, sha in fixed['SHA256'].items(): assert digest(ROOT/relative) == sha, relative
        return fixed
    material = read(HERE/'branch_input_runtime_fixed.json')
    assert material['全入力監査合格']
    paths = runtime_files()
    for relative, sha in material['SHA256'].items():
        assert digest(ROOT/relative) == sha, relative
        paths.add(ROOT/relative)
    originals = read(HERE.parent/'wave_v35/input_causality_before_pnl.json')['原本78SHA256']
    for relative, sha in originals.items():
        assert digest(ROOT/relative) == sha, relative
        paths.add(ROOT/relative)
    original_inputs = pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    sessions = sorted({key[0] for key in original_inputs})
    assert len(original_inputs) == 26 and len(sessions) == 13
    fixed = dict(固定日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), conditions=design.catalog(),
        supplementary_conditions=design.supplementary(), manager=read(HERE.parent/'wave_v35/探索条件の固定.json')['manager'],
        全セッション=sessions, 後半7セッション=sessions[6:], 指定波=list(base.wave_metrics.EPISODES),
        全条件数=len(design.catalog()),補助条件数=len(design.supplementary()),主仮説=design.PRIMARY_ID,
        データ='全13既知。現在API・保存ライブを使わない。',
        SHA256={p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths)})
    save(path, fixed)
    return fixed


def main() -> None:
    """機能: 起動前監査の指紋を検査して固定条件を再生する。

    引数: --prepare/--supplementary (bool)、--workers (int)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--supplementary', action='store_true')
    parser.add_argument('--workers', type=int, default=6)
    args = parser.parse_args()
    socket.socket.connect = reject_network; socket.create_connection = reject_network
    fixed = prepare()
    if args.prepare:
        print(f'主{fixed["全条件数"]}・補助{fixed["補助条件数"]}を固定。新損益なし。', flush=True)
        return
    audit = read(HERE/'起動前監査.json')
    assert audit['実行可能'] and audit['探索固定SHA256'] == digest(HERE/'探索条件の固定.json')
    for relative, sha in audit['SHA256'].items(): assert digest(ROOT/relative) == sha, relative
    specs = fixed['supplementary_conditions'] if args.supplementary else fixed['conditions']
    destination = 'supplementary' if args.supplementary else ''
    if args.supplementary: assert read(HERE/'主再生の完了.json')['全条件数'] == len(fixed['conditions'])
    started, results = time.perf_counter(), []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize) as pool:
        futures = {pool.submit(evaluate, spec, destination): spec['id'] for spec in specs}
        for future in as_completed(futures):
            value = future.result(); results.append(value)
            print(f"{len(results)}/{len(specs)} {value['id']} 全行会計一致", flush=True)
    assert len(results) == len(specs) and {r['id'] for r in results} == {s['id'] for s in specs}
    prepare()
    save(HERE/destination/'全条件の期間集計.json.gz', sorted(results, key=lambda r: r['id']))
    save(HERE/destination/'主再生の完了.json', dict(全条件数=len(specs), 全入力数=len(specs)*26, 全指定波数=len(specs)*8,
        全行独立会計=True, 経過秒=time.perf_counter()-started, API取得数=0, 現在保存物使用=False,
        探索固定SHA256=digest(HERE/'探索条件の固定.json')))


if __name__ == '__main__':
    main()
