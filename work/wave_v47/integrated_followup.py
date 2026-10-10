"""統合方式の入口時間幅と追加ナイトを、選抜へ流用せず固定再生する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
from copy import deepcopy
from pathlib import Path
import sys

import numpy as np

import replay_parts as replay
import exit_integration as integration
import integration_accounting_audit as audit

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
INPUTS={}


def catalog(stage: str) -> list[dict]:
    """機能: 中央12方式又は主窓±20%だけの24方式を返す。

    引数: stage(str:clock/new)。返り値: 全仕様(list[dict])。
    """
    specs=[]
    for original in integration.catalog():
        for scale in ((.8,1.2) if stage=='clock' else (1.,)):
            spec=deepcopy(original)
            spec.update(id=original['id']+(f'__M{round(scale*100):03d}' if stage=='clock' else ''),
                primary=False if stage=='clock' else original['primary'],main_scale=scale,
                entry_component=f'M{round(scale*100):03d}_S100_P1_C1_D100')
            specs.append(spec)
    return specs


def initialize(stage: str) -> None:
    """機能: 各プロセスに旧入力又は保存済み追加入力を用意する。

    引数: stage(str)。返り値: なし(None)。外部通信は旧初期化で拒否する。
    """
    global INPUTS
    if stage=='clock':
        integration.initialize();INPUTS=integration.INPUTS
    else:
        replay.initialize('new');INPUTS=replay.INPUTS


def inspect_case(spec: dict,key: tuple,columns: tuple,valid: np.ndarray,causal: bool) -> tuple:
    """機能: 統合注文を独立会計・枠監査と因果再生成へ通す。

    引数: spec(dict)、key(tuple)、columns(tuple)、valid(ndarray)、causal(bool)。返り値: 集計・台帳・証拠・時価(tuple)。
    """
    ready=INPUTS[key];config=integration.config_for(spec,ready)
    actual=integration.play(spec,ready,columns,config,gate_valid=valid)
    result,effective,evidence=actual
    row,curves,proof,basic=audit.inspect(spec,ready,result,config,effective)
    assert all(proof[f] is True for f in integration.reference.PROOF_FLAGS)
    identity=integration.initial_identity(result)
    other=integration.reference.old.session_row(spec['id'],ready,result,config,effective[1],basic,curves)
    audit.statistics.equal(row,other,'統合別経路統計')
    if causal:proof['因果']=integration.causal_check(spec,ready,columns,config,actual,valid)
    ledger=dict(session=key[0],symbol=key[1],config=config,
        **{field:result[field].tolist() for field in integration.STORED},
        result_fingerprints=integration.reference.old.fingerprints(result),
        shadow_fingerprints=integration.reference.old.fingerprints(result['shadow'],integration.reference.reference.EXPECTED_SHADOW_FIELDS),
        scheduler_fingerprints=integration.reference.old.fingerprints(result['shadow']['scheduler'],integration.reference.reference.EXPECTED_SHADOW_FIELDS),
        shadow_cycles=result['shadow']['cycles'].tolist(),shadow_orders=result['shadow']['orders'].tolist(),
        scheduler_cycles=result['shadow']['scheduler']['cycles'].tolist(),
        scheduler_orders=result['shadow']['scheduler']['orders'].tolist())
    proof.update(session=key[0],symbol=key[1],**identity)
    if key[0]==replay.NEW_SESSION:
        from datetime import datetime
        cutoff=datetime.fromisoformat('2026-09-29T21:00:00+09:00').timestamp()
        index=int(np.searchsorted(ready['time_s'],cutoff,side='left'))-1
        equity=curves['equity']*config['point_value']
        row.update(既知21時直前時価円=float(equity[index]),追加21時以降時価差分円=float(equity[-1]-equity[index]))
    return row,ledger,proof,curves['equity']


def evaluate(spec: dict,stage: str) -> dict:
    """機能: 一統合仕様の全指定入力を検算して保存する。

    引数: spec(dict)、stage(str)。返り値: 完了記録(dict)。
    """
    rows=[];ledgers=[];proofs=[];series={};calibration=[]
    if stage=='clock':
        with np.load(HERE/'component_entries'/(spec['entry_component']+'.npz')) as source:
            states={key:source['|'.join(key)] for key in INPUTS}
    else:
        original=replay.previous.read(HERE/'exit_integration/ledgers'/(spec['id']+'.json.gz'))
        original={(r['session'],r['symbol']):r for r in original}
        for symbol in ('TOPIX','NK225'):
            key=('2026-09-29_Day',symbol)
            columns,valid=replay.new_columns(spec,key)
            for own,prior in zip(columns,integration.columns_for(spec,key)):
                np.testing.assert_array_equal(own,prior)
            np.testing.assert_array_equal(valid,integration.quality_for(spec,key))
            row,ledger,proof,curve=inspect_case(spec,key,columns,valid,False)
            for field in ('result_fingerprints','shadow_fingerprints','scheduler_fingerprints'):
                assert ledger[field]==original[key][field],(spec['id'],key,field)
            calibration.append(dict(session=key[0],symbol=symbol,旧10列品質一致=True,旧統合15指紋一致=True,影二系統20指紋一致=True))
    for key,ready in sorted(INPUTS.items()):
        if stage=='new' and key[0]!=replay.NEW_SESSION:continue
        if stage=='clock':
            columns=integration.columns_for(spec,key);columns=(states[key],*columns[1:])
            valid=integration.quality_for(spec,key)
        else:columns,valid=replay.new_columns(spec,key)
        row,ledger,proof,curve=inspect_case(spec,key,columns,valid,stage=='new' or key[0]=='2026-09-24_Night')
        rows.append(row);ledgers.append(ledger);proofs.append(proof);series[key]=curve
    assert len(rows)==(26 if stage=='clock' else 2)
    expected_keys=set(INPUTS) if stage=='clock' else {(replay.NEW_SESSION,s) for s in ('TOPIX','NK225')}
    assert {(r['session'],r['symbol']) for r in rows}==expected_keys
    summary=dict(id=spec['id'],spec=spec,全合格=True,stage=stage,旧統合照合=calibration)
    periods=[('all_symbols',integration.reference.old.FIXED['全セッション']),
             ('symbols',integration.reference.old.FIXED['後半7セッション'])] if stage=='clock' else [('new_symbols',[replay.NEW_SESSION])]
    for label,names in periods:
        summary[label]={s:audit.statistics.period(rows,series,names,s,integration.reference.old.base.research.MULT[s]) for s in ('TOPIX','NK225')}
    base=HERE/'integration_followup'/stage
    paths=[]
    for folder,value,suffix in [('sessions',rows,'.json.gz'),('ledgers',ledgers,'.json.gz'),
        ('audits',proofs,'.json.gz'),('summaries',summary,'.json')]:
        target=base/folder/(spec['id']+suffix);replay.save(target,value);paths.append(target)
    done=dict(id=spec['id'],全合格=True,入力数=len(rows),因果検査数=sum('因果' in p for p in proofs),旧照合数=len(calibration),
        固定SHA256=replay.previous.digest(HERE/'統合追試の固定.json'),出力SHA256={p.relative_to(ROOT).as_posix():replay.previous.digest(p) for p in paths})
    assert done['因果検査数']==2 and done['旧照合数']==(0 if stage=='clock' else 2)
    replay.save(base/'completed'/(spec['id']+'.json'),done)
    return done


def freeze() -> dict:
    """機能: 時間幅24条件と追加ナイト中央12条件の仕様を事前固定する。

    引数: なし。返り値: 固定書(dict)。追加ナイトの既知範囲を明記する。
    """
    for name in ('check_exit_integration.json','check_exit_integration_independent.json'):
        assert replay.previous.read(HERE/name)['全合格']
    sources=[Path(__file__),Path(integration.__file__),Path(audit.__file__),
        HERE/'exit_partial_integrated.py',HERE/'exit_shadow_integrated.py',HERE/'integration_shadow_oracle.py',
        HERE/'integration_slot_audit.py',HERE/'component_entries/M080_S100_P1_C1_D100.npz',
        HERE/'component_entries/M120_S100_P1_C1_D100.npz',HERE/'new_inputs.pkl',HERE/'new_features_depth.pkl',
        HERE/'inputs.pkl',HERE/'features_depth.pkl',HERE/'replay_parts.py',HERE/'component_signals.py',
        HERE.parent/'wave_v35/deterioration_signals.py',HERE/'exit_integration_fixed.json',
        HERE.parent/'wave_v23/inputs.pkl',HERE/'new_signal_audit.json']
    dependencies=replay.previous.read(HERE/'exit_integration_fixed.json')['参照資料SHA256']
    replay.previous.verify(dependencies)
    references=dict(dependencies)
    references.update({p.relative_to(ROOT).as_posix():replay.previous.digest(p) for p in sources})
    for module in tuple(sys.modules.values()):
        filename=getattr(module,'__file__',None)
        if filename:
            p=Path(filename).resolve()
            if p.suffix=='.py' and p.is_relative_to(ROOT/'work'):
                name=p.relative_to(ROOT).as_posix();actual=replay.previous.digest(p)
                if name in references:assert references[name]==actual,name
                references[name]=actual
    fixed=dict(旧時間幅=catalog('clock'),追加ナイト=catalog('new'),原本追加取得数=0,
        条件選定='出口E10代表/E11強短縮対照/E00基準を旧13の同初回診断で選択。途中4方式・入口主窓3点を全表示。',
        新ナイト位置付け='既存5方式の新Night損益はroot既読。部品の設計・実装担当は未読で旧13から仕様を固定。完全未見検証とは呼ばない。',
        新ナイト選抜禁止=True,追加探索='新Night結果を見て出口幅・ゲート・数量・時刻を変更しない。',
        参照SHA256=references)
    path=HERE/'統合追試の固定.json'
    if path.exists():assert replay.previous.read(path)==fixed
    else:replay.save(path,fixed)
    return fixed


def main() -> None:
    """機能: 固定した旧時間幅又は新ナイトを全件再生する。

    引数: stage(str)、workers(int)。返り値: なし(None)。
    """
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('clock','new'));parser.add_argument('--workers',type=int,default=2)
    args=parser.parse_args();fixed=freeze()
    replay.previous.verify(fixed['参照SHA256'])
    if args.stage=='new':
        assert replay.previous.read(HERE/'exit_integration_complete.json')['全合格']
        assert replay.previous.read(HERE/'integration_followup/clock/complete.json')['全合格']
        calibration_sources={}
        for spec in integration.catalog():
            path=HERE/'exit_integration/completed'/(spec['id']+'.json')
            record=replay.previous.read(path)
            assert record['全合格'] and record['id']==spec['id'] and record['全入力数']==record['因果入力数']==26
            assert record['固定SHA256']==replay.previous.digest(HERE/'exit_integration_fixed.json')
            replay.previous.verify(record['出力SHA256'])
            calibration_sources.update(record['出力SHA256']);calibration_sources[path.relative_to(ROOT).as_posix()]=replay.previous.digest(path)
        calibration_fixed=HERE/'統合追加ナイトの照合元固定.json'
        if calibration_fixed.exists():assert replay.previous.read(calibration_fixed)==calibration_sources
        else:replay.save(calibration_fixed,calibration_sources)
    specs=fixed['旧時間幅' if args.stage=='clock' else '追加ナイト']
    with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize,initargs=(args.stage,)) as pool:
        tasks={pool.submit(evaluate,s,args.stage):s['id'] for s in specs};completed=[]
        for i,future in enumerate(as_completed(tasks),1):
            completed.append(future.result());print(f'統合追試 {args.stage} {i}/{len(specs)} {tasks[future]} 完了',flush=True)
    assert len(completed)==len(specs) and {r['id'] for r in completed}=={s['id'] for s in specs}
    expected_inputs=26 if args.stage=='clock' else 2
    outputs={}
    for record in completed:
        assert record['全合格'] and record['入力数']==expected_inputs and record['因果検査数']==2
        assert record['旧照合数']==(0 if args.stage=='clock' else 2)
        assert record['固定SHA256']==replay.previous.digest(HERE/'統合追試の固定.json')
        replay.previous.verify(record['出力SHA256']);outputs.update(record['出力SHA256'])
    replay.previous.verify(fixed['参照SHA256'])
    if args.stage=='new':replay.previous.verify(calibration_sources)
    replay.save(HERE/'integration_followup'/args.stage/'complete.json',dict(全合格=True,条件数=len(specs),
        入力数=sum(r['入力数'] for r in completed),完了=completed,出力SHA256=outputs,
        固定SHA256=replay.previous.digest(HERE/'統合追試の固定.json')))


if __name__=='__main__':main()
