"""旧26入力だけで途中判断の既知7を再利用し、既知2と未試行4を検算する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import gzip
import importlib.util
import json
from pathlib import Path
import sys
import time

import mid_design as design

HERE, ROOT = design.HERE, design.ROOT
OUT = HERE/'mid_results'
specification = importlib.util.spec_from_file_location('mid_reference_runner',HERE.parent/'wave_v44/runner.py')
reference = importlib.util.module_from_spec(specification)
sys.modules[specification.name] = reference
specification.loader.exec_module(reference)
read, digest = design.read, design.digest


def save(path: Path, value: object) -> None:
    """機能: 今回の途中判断結果だけを有限JSONで原子的に保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True,exist_ok=True)
    raw = json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_bytes(gzip.compress(raw,mtime=0) if path.suffix == '.gz' else raw)
    temp.replace(path)


def verify(references: dict) -> None:
    """機能: 凍結した参照資料の変更を拒否する。

    引数: references(dict[str,str])。返り値: なし(None)。
    """
    for name,sha in references.items():assert digest(ROOT/name) == sha,name


def prepare() -> dict:
    """機能: 13条件・実行コード・独立集計を新規再生前に固定する。

    引数: なし。返り値: 固定記録(dict)。新Nightは対象へ追加できない。
    """
    fixed = read(HERE/'mid_design_fixed.json')
    assert fixed['conditions'] == design.catalog() and fixed['origins'] == design.origins()
    verify(fixed['SHA256'])
    refs = dict(fixed['SHA256'])
    for path in (Path(__file__),HERE/'mid_design_fixed.json',HERE/'mid_analysis.py'):
        refs[path.relative_to(ROOT).as_posix()] = digest(path)
    value = dict(conditions=fixed['conditions'],origins=fixed['origins'],rules=fixed['rules'],
        comparisons=fixed['comparisons'],SHA256=refs,新規再生前=True,新Night使用=False)
    path = HERE/'mid_runtime_fixed.json'
    if path.exists():assert read(path) == value
    else:save(path,value)
    return value


def initialize() -> None:
    """機能: 旧v44が使用した凍結26入力と無変更の独立監査を初期化する。

    引数: なし。返り値: なし(None)。新しい原本を探索しない。
    """
    reference.initialize()
    expected = {(n,s) for n in design.rules()['全セッション'] for s in ('TOPIX','NK225')}
    assert set(reference.INPUTS) == expected and len(expected) == 26
    assert '2026-09-29_Night' not in {k[0] for k in reference.INPUTS}


def write_result(spec: dict, origin: dict, payloads: dict, flags: dict) -> dict:
    """機能: 条件の各実体と由来を保存し、全資料指紋を完了証拠へ束ねる。

    引数: spec/origin/payloads/flags(dict)。返り値: 条件完了記録(dict)。
    """
    paths = []
    for folder,payload in payloads.items():
        suffix = '.json' if folder in ('summaries','causality','gate_use') else '.json.gz'
        path = OUT/folder/(spec['id']+suffix);save(path,payload);paths.append(path)
    done = dict(id=spec['id'],spec=spec,origin=origin,全合格=True,全入力数=26,全波数=8,
        実行固定SHA256=digest(HERE/'mid_runtime_fixed.json'),
        出力SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in paths},**flags)
    save(OUT/'completed'/(spec['id']+'.json'),done)
    return done


def reuse(spec: dict, origin: dict) -> dict:
    """機能: 旧完備された経済結果を、元IDと証拠を保持して再利用する。

    引数: spec/origin(dict)。返り値: 旧成果継承の完了記録(dict)。売買は再生しない。
    """
    assert not origin['replay']
    base = ROOT/origin['source_dir']; prior = origin['source_id']
    summary = read(base/'summaries'/(prior+'.json'))
    assert design.economic_spec(summary['spec'],origin['source_version']) == design.economic_spec(spec,47)
    ledgers = read(base/'ledgers'/(prior+'.json.gz'))
    rows = read(base/'sessions'/(prior+'.json.gz'))
    waves = read(base/'waves'/(prior+'.json.gz'))
    if origin['kind'] == 'reuse_v41':
        anchor = {(r['session'],r['symbol']):r for r in read(HERE.parent/'wave_v44/ledgers/A0__V000.json.gz')}
        for row in ledgers:
            key = row['session'],row['symbol']
            assert row['shadow_fingerprints'] == anchor[key]['shadow_fingerprints']
            row['shadow_cycles'] = deepcopy(anchor[key]['shadow_cycles'])
            row['shadow_orders'] = deepcopy(anchor[key]['shadow_orders'])
    for row in rows:assert row['id'] == prior;row['id'] = spec['id']
    for row in waves:assert row['method'] == prior;row['method'] = spec['id']
    summary.update(id=spec['id'],spec=spec,origin=origin)
    assert len(rows) == len(ledgers) == 26 and len(waves) == 8
    payloads = dict(summaries=summary,sessions=rows,ledgers=ledgers,waves=waves)
    return write_result(spec,origin,payloads,dict(新売買再生=False,旧完備と状態修正証跡継承=True,
        参照由来証拠SHA256=digest(HERE/'mid_reuse_evidence.json')))


def evaluate(spec: dict) -> dict:
    """機能: 新6条件を全26で旧厳格会計・枠監査・因果監査に通す。

    引数: spec(dict)。返り値: 完了記録(dict)。既知v37の2条件は旧全共有配列との一致も要求する。
    """
    r = reference;identifier = spec['id'];origin = design.origins()[identifier]
    assert origin['replay']
    rows=[];series={};ledgers=[];proofs=[];waves=[];causality=[];gate_use=[]
    prior = {}
    if origin['kind'] == 'known_replay_v37':
        prior = {(x['session'],x['symbol']):x for x in read(ROOT/origin['source_dir']/'ledgers'/(origin['source_id']+'.json.gz'))}
    for key,ready in sorted(r.INPUTS.items()):
        columns = r.columns_for(spec,key)
        config = r.old.base.managers.make_config(r.old.FIXED['manager'],key[1],ready)
        valid = r.quality_for(spec,key)
        result,effective,evidence = r.play(spec,ready,columns,config,gate_valid=valid)
        row,curves,proof,basic = r.audit.inspect(spec,ready,result,config,effective)
        assert all(proof[f] is True for f in r.PROOF_FLAGS)
        assert proof['原本行数'] == len(ready['last'])
        r.audit.statistics.equal(row,r.old.session_row(identifier,ready,result,config,effective[1],basic,curves),'全統計')
        fingerprints = r.old.fingerprints(result)
        shadow_fingerprints = r.old.fingerprints(result['shadow'],r.reference.EXPECTED_SHADOW_FIELDS)
        if prior:
            for field,sha in prior[key]['result_fingerprints'].items():
                assert fingerprints[field] == sha,(identifier,key,field,'v37実配列互換不一致')
            for field,sha in prior[key]['shadow_fingerprints'].items():
                assert shadow_fingerprints[field] == sha,(identifier,key,field,'v37影配列互換不一致')
        identity = r.initial_identity(ready,result)
        rows.append(row);series[key] = curves['equity']
        usage = r.gate_record(spec,ready,columns,effective,evidence,valid,result);gate_use.append(usage)
        ledgers.append(dict(session=key[0],symbol=key[1],config=config,
            **{f:result[f].tolist() for f in r.STORED},result_fingerprints=fingerprints,
            shadow_fingerprints=shadow_fingerprints,shadow_cycles=result['shadow']['cycles'].tolist(),
            shadow_orders=result['shadow']['orders'].tolist(),gate_fingerprints=usage['fingerprints'],arm_events=usage['arm_events']))
        proofs.append(dict(session=key[0],symbol=key[1],**proof,**identity,全統計一致=True,旧37同値=bool(prior)))
        if key[0] in r.REPRESENTATIVE:
            causality.append(dict(session=key[0],symbol=key[1],**r.causal_check(spec,ready,columns,config,(result,effective,evidence),valid)))
        for wave in r.old.FIXED['指定波']:
            if wave['session'] == key[0]:
                orders = r.old.base.wave_metrics.order_records(ready,columns[0],result,r.engine.REASONS)
                waves.append(r.old.base.wave_metrics.episode_metrics(dict(id=identifier,manager=r.old.FIXED['manager']),
                    wave,ready,columns[0],result,orders,config['point_value']))
    assert len(rows) == len(ledgers) == len(proofs) == 26 and len(waves) == 8 and len(causality) == 4
    periods={}
    for period,names in (('all_symbols',r.old.FIXED['全セッション']),('symbols',r.old.FIXED['後半7セッション'])):
        periods[period]={s:r.audit.statistics.period(rows,series,names,s,r.old.base.research.MULT[s]) for s in r.old.SYMBOLS}
        r.audit.statistics.equal(r.old.period(rows,names),periods[period],'期間全統計')
    summary=dict(id=identifier,spec=spec,origin=origin,**periods,wave_passes=sum(w['正方向ネット20分目安達成'] for w in waves),
        全26全行独立会計一致=True,全原本行会計数=sum(len(v['last']) for v in r.INPUTS.values()))
    payloads=dict(summaries=summary,sessions=rows,ledgers=ledgers,audits=proofs,waves=waves,causality=causality,gate_use=gate_use)
    return write_result(spec,origin,payloads,dict(新売買再生=True,今回未試行機構=not origin['known'],
        旧37全共有配列一致入力数=26 if prior else 0,因果入力数=4))


def main() -> None:
    """機能: 固定後に再利用7と経済再生6を全件実施し、全資料SHAを再確認する。

    引数: --prepare(bool)、--workers(int)。返り値: なし(None)。欠落時は完了を書かない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--workers',type=int,default=4);args=parser.parse_args()
    if args.prepare:prepare();print('途中判断13条件の実行前固定完了');return
    fixed=read(HERE/'mid_runtime_fixed.json');verify(fixed['SHA256'])
    assert fixed['conditions'] == design.catalog() and fixed['origins'] == design.origins()
    assert not (OUT/'completed').exists(),'初回用の新領域だけで実行する'
    started=time.perf_counter();records=[]
    for spec in fixed['conditions']:
        origin=fixed['origins'][spec['id']]
        if not origin['replay']:records.append(reuse(spec,origin))
    pending=[s for s in fixed['conditions'] if fixed['origins'][s['id']]['replay']]
    with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize) as pool:
        futures={pool.submit(evaluate,s):s['id'] for s in pending}
        for future in as_completed(futures):
            try:records.append(future.result())
            except Exception as error:
                save(HERE/'mid_failure.json',dict(id=futures[future],例外=repr(error),完了扱い=False));raise
            print(f'途中判断 {len(records)}/13 完了 {futures[future]}',flush=True)
    assert len(records) == 13 and {r['id'] for r in records} == set(fixed['origins'])
    outputs={}
    for row in records:
        assert row['全合格'] and row['全入力数'] == 26
        verify(row['出力SHA256']);outputs.update(row['出力SHA256'])
        path=OUT/'completed'/(row['id']+'.json');outputs[path.relative_to(ROOT).as_posix()]=digest(path)
    verify(fixed['SHA256'])
    value=dict(全合格=True,全条件数=13,全入力数=338,再利用条件数=7,既知互換再生条件数=2,
        未試行機構条件数=4,経済再生入力数=156,因果入力数=24,全指定波数=104,
        結果=sorted(records,key=lambda r:r['id']),出力SHA256=outputs,参照資料SHA256=fixed['SHA256'],
        実行固定SHA256=digest(HERE/'mid_runtime_fixed.json'),経過秒=time.perf_counter()-started,
        新Night使用=False,現在API取得数=0,保存ライブ使用=False)
    save(HERE/'mid_complete.json',value)
    print('途中判断13条件・338口座の完了保存',flush=True)


if __name__ == '__main__':main()
