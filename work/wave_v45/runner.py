"""既知十一条件を指紋で引き継ぎ、同じ経済実装で新しい五十パーセント反証を再生する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRIOR = HERE.parent/'wave_v44'


def module(name: str, path: Path) -> object:
    """機能: 明示した実装を通常のモジュール登録手順で読む。

    引数: name(str)、path(Path)。返り値: モジュール(object)。
    """
    specification = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(specification)
    sys.modules[name] = value
    specification.loader.exec_module(value)
    assert Path(value.__file__).resolve() == path.resolve()
    return value


legacy = module('f50_previous_runner', PRIOR/'runner.py')
design = module('f50_refutation_design', HERE/'design.py')
reference, audit, old, engine, causal, gate = (
    legacy.reference, legacy.audit, legacy.old, legacy.engine, legacy.causal, legacy.gate)
assert Path(gate.__file__).resolve() == PRIOR/'profit_gate.py'
assert Path(engine.__file__).resolve() == HERE.parent/'wave_v41/engine_partial_restore_corrected.py'
assert Path(audit.__file__).resolve() == HERE.parent/'wave_v38/adaptive_accounting_audit.py'
INPUTS, FIXED = {}, {}
FIELDS, STORED = legacy.FIELDS, legacy.STORED
PROOF_FLAGS, REPRESENTATIVE = legacy.PROOF_FLAGS, legacy.REPRESENTATIVE
ARTIFACTS = (('sessions', '.json.gz'), ('ledgers', '.json.gz'), ('audits', '.json.gz'),
             ('waves', '.json.gz'), ('causality', '.json'), ('gate_use', '.json'), ('summaries', '.json'))

# ----------------------------------------
# 経済計算・入力・因果検査は旧関数そのものを使う。関数のグローバル入力も旧初期化で設定する。
digest, read, verify = legacy.digest, legacy.read, legacy.verify
columns_for, quality_for, play = legacy.columns_for, legacy.quality_for, legacy.play
gate_prefix, causal_check = legacy.gate_prefix, legacy.causal_check
initial_identity, gate_record, legacy_id = legacy.initial_identity, legacy.gate_record, legacy.legacy_id


def save(path: Path, value: object) -> None:
    """機能: 新作業領域だけへ有限JSONを原子的に保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。旧成果は書き換えない。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == '.gz' else raw)
    temporary.replace(path)


def initialize() -> None:
    """機能: 旧入力を通信拒否状態で初期化し、新旧の参照を同じ辞書へ結ぶ。

    引数: なし。返り値: なし(None)。新しい損益はこの処理では計算しない。
    """
    global INPUTS, FIXED
    legacy.initialize()
    INPUTS = legacy.INPUTS
    FIXED = read(HERE/'探索条件の固定.json')
    assert INPUTS is old.INPUTS
    assert Path(gate.__file__).resolve() == PRIOR/'profit_gate.py'
    assert Path(audit.slots.__file__).resolve() == HERE.parent/'wave_v38/adaptive_slot_audit.py'


def reuse(spec: dict) -> dict:
    """機能: 固定した旧八資料を検証し、七成果を新領域へ引き継ぐ。

    引数: spec(dict)。返り値: 引継ぎ完了記録(dict)。
    六成果はバイト完全一致、要約は主案・役割を含むspecと探索指紋だけを更新する。
    """
    started = time.perf_counter()
    identifier = design.reused_id(spec)
    assert identifier is not None and spec['role'] != 'supplementary'
    source = FIXED['既知再利用'][identifier]
    assert set(source) == {'spec','completed','出力SHA256','旧探索固定SHA256'}
    assert set(spec) == set(source['spec'])
    assert design.economic(spec) == design.economic(source['spec'])
    assert type(spec['primary']) is bool and isinstance(spec['role'], str)
    source_paths = {(PRIOR/folder/(identifier+suffix)).relative_to(ROOT).as_posix()
                    for folder,suffix in ARTIFACTS}
    old_record_path = PRIOR/'completed'/(identifier+'.json')
    assert source['completed'] == old_record_path.relative_to(ROOT).as_posix()
    assert set(source['出力SHA256']) == source_paths | {source['completed']}
    verify(source['出力SHA256'])
    old_record = read(old_record_path)
    assert old_record['id'] == identifier and old_record['全合格'] is True
    assert (old_record['全入力数'], old_record['因果入力数']) == (26,4)
    assert old_record['探索固定SHA256'] == source['旧探索固定SHA256']
    assert old_record['出力SHA256'] == {name:source['出力SHA256'][name] for name in source_paths}
    proof = read(PRIOR/'完備監査.json')
    assert proof['全合格'] is True and proof['探索固定SHA256'] == source['旧探索固定SHA256']
    assert all(proof['出力SHA256'][name] == value for name,value in source['出力SHA256'].items())
    paths = []
    for folder,suffix in ARTIFACTS:
        prior_path = PRIOR/folder/(identifier+suffix)
        target = HERE/folder/(identifier+suffix)
        if folder == 'summaries':
            previous = read(prior_path)
            assert previous['id'] == identifier and previous['spec'] == source['spec']
            assert previous['探索固定SHA256'] == source['旧探索固定SHA256']
            current = deepcopy(previous)
            current['spec'] = deepcopy(spec)
            current['探索固定SHA256'] = digest(HERE/'探索条件の固定.json')
            save(target,current)
            restored = read(target)
            assert {k:v for k,v in previous.items() if k not in ('spec','探索固定SHA256')} == {
                k:v for k,v in restored.items() if k not in ('spec','探索固定SHA256')}
        else:
            raw = prior_path.read_bytes()
            assert hashlib.sha256(raw).hexdigest() == source['出力SHA256'][prior_path.relative_to(ROOT).as_posix()]
            assert target.resolve().is_relative_to(HERE)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix+'.tmp')
            temporary.write_bytes(raw)
            temporary.replace(target)
            assert digest(target) == digest(prior_path)
        paths.append(target)
    verify(source['出力SHA256'])
    done = dict(id=identifier, 全合格=True, 全入力数=26, 因果入力数=4,
        全原本行会計数=old_record['全原本行会計数'],旧単一窓一致入力数=old_record['旧単一窓一致入力数'],
        探索固定SHA256=digest(HERE/'探索条件の固定.json'),
        出力SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in paths},
        経過秒=time.perf_counter()-started,既知成果引継ぎ=True,新売買再生=False,reuse_source=deepcopy(source))
    save(HERE/'completed'/(identifier+'.json'),done)
    return done


def evaluate(spec: dict) -> dict:
    """機能: 一条件の26入力を全行会計へ通し、期間集計と元単一窓同値を保存する。

    引数: spec(dict)。返り値: 条件完了記録(dict)。
    """
    if design.reused_id(spec) is not None:
        return reuse(spec)
    identifier, started = spec['id'], time.perf_counter()
    destination = HERE/'supplementary' if spec['role'] == 'supplementary' else HERE
    rows, series, ledgers, proofs, waves, causality = [], {}, [], [], [], []
    prior_id = legacy_id(spec)
    prior = {(r['session'],r['symbol']):r for r in read(HERE.parent/'wave_v38/ledgers'/(prior_id+'.json.gz'))} if prior_id else {}
    gate_use = []
    for key, ready in sorted(INPUTS.items()):
        columns = columns_for(spec, key)
        config = old.base.managers.make_config(old.FIXED['manager'], key[1], ready)
        valid = quality_for(spec, key)
        result, effective, evidence = play(spec, ready, columns, config, gate_valid=valid)
        row, curves, proof, basic = audit.inspect(spec, ready, result, config, effective)
        for flag in PROOF_FLAGS:
            assert proof[flag] is True, (identifier, key, flag)
        assert proof['原本行数'] == len(ready['last'])
        other_row = old.session_row(identifier, ready, result, config, effective[1], basic, curves)
        audit.statistics.equal(other_row, row, '別経路の全統計')
        fingerprints = old.fingerprints(result)
        if prior_id:
            assert fingerprints == prior[key]['result_fingerprints'], (identifier, key, '旧単一窓全15指紋')
        rows.append(row)
        series[key] = curves['equity']
        usage = gate_record(spec, ready, columns, effective, evidence, valid, result)
        assert usage['全源行維持']
        gate_use.append(usage)
        ledgers.append(dict(session=key[0], symbol=key[1], config=config,
            **{field:result[field].tolist() for field in STORED}, result_fingerprints=fingerprints,
            shadow_fingerprints=old.fingerprints(result['shadow'], reference.EXPECTED_SHADOW_FIELDS),
            shadow_cycles=result['shadow']['cycles'].tolist(), shadow_orders=result['shadow']['orders'].tolist(),
            gate_fingerprints=usage['fingerprints'], arm_events=usage['arm_events']))
        proofs.append(dict(session=key[0], symbol=key[1], **proof, 全統計一致=True,
            時価SHA256=hashlib.sha256(curves['equity'].tobytes()).hexdigest(), 旧単一窓一致=prior_id is not None))
        if key[0] in REPRESENTATIVE:
            causality.append(dict(session=key[0], symbol=key[1], **causal_check(spec, ready, columns, config, (result,effective,evidence), valid)))
        for wave in old.FIXED['指定波']:
            if wave['session'] == key[0]:
                records = old.base.wave_metrics.order_records(ready, columns[0], result, engine.REASONS)
                waves.append(old.base.wave_metrics.episode_metrics(dict(id=identifier, manager=old.FIXED['manager']),
                    wave, ready, columns[0], result, records, config['point_value']))
    assert len(rows) == len(ledgers) == len(proofs) == 26 and len(waves) == 8 and len(causality) == 4
    periods = {}
    for period, names in (('all_symbols', old.FIXED['全セッション']), ('symbols', old.FIXED['後半7セッション'])):
        periods[period] = {s:audit.statistics.period(rows, series, names, s, old.base.research.MULT[s]) for s in old.SYMBOLS}
        audit.statistics.equal(old.period(rows, names), periods[period], '期間全統計')
    value = dict(id=identifier, spec=spec, **periods, wave_passes=sum(r['正方向ネット20分目安達成'] for r in waves),
        全26全行独立会計一致=True, 探索固定SHA256=digest(HERE/'探索条件の固定.json'),
        全原本行会計数=sum(len(r['last']) for r in INPUTS.values()), 旧単一窓一致入力数=26 if prior_id else 0)
    paths = []
    for folder, payload, suffix in (('sessions', rows, '.json.gz'), ('ledgers', ledgers, '.json.gz'),
        ('audits', proofs, '.json.gz'), ('waves', waves, '.json.gz'), ('causality', causality, '.json'),
        ('gate_use', gate_use, '.json'), ('summaries', value, '.json')):
        path = destination/folder/(identifier+suffix)
        save(path, payload)
        paths.append(path)
    done = dict(id=identifier, 全合格=True, 全入力数=26, 因果入力数=4,
        全原本行会計数=value['全原本行会計数'], 旧単一窓一致入力数=value['旧単一窓一致入力数'],
        探索固定SHA256=digest(HERE/'探索条件の固定.json'),
        出力SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in paths}, 経過秒=time.perf_counter()-started,
        既知成果引継ぎ=False,新売買再生=True)
    save(destination/'completed'/(identifier+'.json'), done)
    return done

def main() -> None:
    """機能: 全主・補助を事前固定した後、既知引継ぎと新規再生を分離して全件保存する。

    引数: コマンドラインworkers(int)、supplementary(bool)。返り値: なし(None)。
    保存完了済みの条件も勝手に間引かず、指定範囲を全て同じ規則で比較する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--supplementary', action='store_true')
    args = parser.parse_args()
    fixed = read(HERE/'探索条件の固定.json')
    assert fixed['conditions'] == design.catalog()
    assert fixed['supplementary'] == design.supplementary()
    verify(fixed['参照資料SHA256'])
    specs = design.supplementary() if args.supplementary else design.catalog()
    assert len(specs) == len({s['id'] for s in specs}) == (128 if args.supplementary else 25)
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize) as pool:
        futures = {pool.submit(evaluate, spec):spec['id'] for spec in specs}
        completed = []
        for future in as_completed(futures):
            completed.append(future.result())
            print(f"{len(completed)}/{len(futures)} {futures[future]} 完了", flush=True)
    assert {v['id'] for v in completed} == {s['id'] for s in specs}
    verify(fixed['参照資料SHA256'])
    for record in completed:
        verify(record['出力SHA256'])
    destination = HERE/'supplementary' if args.supplementary else HERE
    save(destination/'主再生の完了.json', dict(全合格=True, 全条件数=len(completed),
        全入力数=sum(r['全入力数'] for r in completed), 因果入力数=sum(r['因果入力数'] for r in completed),
        全原本行会計数=sum(r['全原本行会計数'] for r in completed),
        旧単一窓一致入力数=sum(r['旧単一窓一致入力数'] for r in completed),
        探索固定SHA256=digest(HERE/'探索条件の固定.json'), records=sorted(completed, key=lambda x:x['id']),
        既知引継条件数=sum(r['既知成果引継ぎ'] for r in completed),
        新規再生条件数=sum(r['新売買再生'] for r in completed),
        既知引継入力数=sum(r['全入力数'] for r in completed if r['既知成果引継ぎ']),
        新規再生入力数=sum(r['全入力数'] for r in completed if r['新売買再生']),
        既知引継因果入力数=sum(r['因果入力数'] for r in completed if r['既知成果引継ぎ']),
        新規因果入力数=sum(r['因果入力数'] for r in completed if r['新売買再生']),
        現在API取得数=0, 保存ライブ使用=False, 全体目標達成=False))


if __name__ == '__main__':
    main()
