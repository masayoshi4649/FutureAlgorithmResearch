"""旧974条件を変更せず、状態一行修正版と元の厳格監査を独立成果へ接続する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback

import numpy as np


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OLD=HERE.parent/'wave_v38'
sys.path.insert(0,str(OLD))
import adaptive_accounting_audit as audit
runner=audit.runner
sys.path.insert(0,str(HERE))
import engine_partial_restore_corrected as corrected

assert Path(audit.__file__).resolve()==OLD/'adaptive_accounting_audit.py'
assert Path(audit.slots.__file__).resolve()==OLD/'adaptive_slot_audit.py'
assert Path(runner.engine.__file__).resolve()==OLD/'engine_partial_restore.py'
assert Path(corrected.__file__).resolve()==HERE/'engine_partial_restore_corrected.py'
assert corrected.shadow_engine is runner.engine.shadow_engine
assert Path(corrected.shadow_engine.__file__).resolve()==OLD/'engine_shadow_plan.py'

BAD_ID='H019__B00_T120_F25_N3__R1__L015'
BASE_ID='H019__A0__R1__V000'
BAD_KEY=('2026-09-24_Night','NK225')
EXPECTED_ROWS=list(range(46748,46760))
PILOT=(BAD_ID,BASE_ID)
FIXED_PATH=HERE/'状態修正の固定.json'
PROGRESS_PATH=HERE/'状態修正の進捗.json'
STOP_PATH=None
EXPECTED_SHADOW_FIELDS=runner.engine.FIELDS+('plans','execution_plans','prepare_events','entry_preparations')
PROOF_FLAGS=('全枠会計一致','全予約と新根拠一致','元終了以前','同約定両建て全行一致',
    '全予算予約一致','全分岐独立一致','全伝達遅延一致')


def digest(path: Path) -> str:
    """機能: 原本を変更せず、巨大ファイルも逐次読取で指紋化する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):value.update(block)
    return value.hexdigest()


def read(path: Path) -> object:
    """機能: 通常又は圧縮JSONを読み取る。

    引数: path(Path)。返り値: 内容(object)。
    """
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def save(path: Path, value: object) -> None:
    """機能: 今回の領域だけへ有限JSONを原子的に保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。旧結果への保存を拒否する。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_bytes(gzip.compress(raw,mtime=0) if path.suffix=='.gz' else raw)
    temporary.replace(path)


def verify_references(references: dict) -> None:
    """機能: 参照した原本・凍結・実装の全指紋を再照合する。

    引数: references(dict[str,str])。返り値: なし(None)、不一致は停止する。
    """
    def check(item: tuple) -> None:
        """機能: 一ファイルのパスと指紋を照合する。

        引数: item(tuple[str,str])。返り値: なし(None)。
        """
        relative,sha=item;path=(ROOT/relative).resolve()
        assert path.is_relative_to(ROOT) and digest(path)==sha,relative
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(check,references.items()))


def specifications() -> tuple[list[dict],set[str]]:
    """機能: 旧探索・旧原監査・旧設計の全974条件が同一か検査する。

    引数: なし。返り値: 全条件、補助ID集合(tuple)。好成績による選抜はしない。
    """
    frozen=read(OLD/'探索条件の固定.json');original=read(OLD/'adaptive_accounting_fixed.json')
    main,supp=frozen['conditions'],frozen['supplementary_conditions']
    assert len(main)==206 and len(supp)==768
    assert main==original['主対象']==runner.design.catalog()
    assert supp==original['補助対象']==runner.design.supplementary()
    specs=main+supp
    assert len({spec['id'] for spec in specs})==974
    assert set(PILOT)<={spec['id'] for spec in main}
    for destination,number in (('',206),('supplementary',768)):
        complete=read(OLD/destination/'主再生の完了.json')
        assert complete['全条件数']==number and complete['全入力数']==26*number
        assert complete['探索固定SHA256']==digest(OLD/'探索条件の固定.json')
    return specs,{spec['id'] for spec in supp}


def prepare() -> dict:
    """機能: 一行差分と全974対象を今回の修正検証へ固定する。

    引数: なし。返り値: 今回の固定記録(dict)。探索の再選抜や旧資料変更はしない。
    """
    specs,supplementary=specifications();change=read(HERE/'状態修正の差分.json')
    old=(OLD/'engine_partial_restore.py').read_bytes()
    new=(HERE/'engine_partial_restore_corrected.py').read_bytes()
    nl=b'\r\n' if b'\r\n' in old else b'\n'
    addition=b'                    phase = 2 if np.any(restorable) else 0'+nl
    assert new.count(addition)==1 and new.replace(addition,b'',1)==old
    assert change['元SHA256']==digest(OLD/'engine_partial_restore.py')
    assert change['修正版SHA256']==digest(HERE/'engine_partial_restore_corrected.py')
    probe=read(OLD/'adaptive_phase_revision_probe.json')
    assert probe['id']==BAD_ID and (probe['session'],probe['symbol'])==BAD_KEY
    assert probe['不一致行']==EXPECTED_ROWS and probe['不一致行数']==12
    original=read(OLD/'adaptive_accounting_fixed.json')
    reference={}
    for group in (read(OLD/'探索条件の固定.json')['SHA256'],original['参照SHA256'],original['原本78SHA256']):
        for relative,sha in group.items():
            assert relative not in reference or reference[relative]==sha,relative
            reference[relative]=sha
    extra=(OLD/'探索条件の固定.json',OLD/'adaptive_accounting_fixed.json',
        OLD/'adaptive_phase_revision_probe.json',OLD/'主再生の完了.json',OLD/'supplementary/主再生の完了.json',
        OLD/'経済完備監査.json',HERE/'状態修正の差分.json',HERE/'engine_partial_restore_corrected.py',Path(__file__))
    for path in extra:reference[path.relative_to(ROOT).as_posix()]=digest(path)
    value=dict(条件=specs,全条件数=974,主条件数=206,補助条件数=768,全入力数=25324,先行対象=list(PILOT),
        既知状態差=dict(id=BAD_ID,session=BAD_KEY[0],symbol=BAD_KEY[1],rows=EXPECTED_ROWS,old=1,new=0),
        一行修正のみ=True,採否条件変更=False,影注文器変更=False,
        原監査='wave_v38/adaptive_accounting_audit.inspectとadaptive_slot_auditを無変更で使用。診断版は使わない。',
        比較='旧再生の全15配列指紋が旧保存値に一致。修正版のphase以外は旧保存指紋とバイト一致。phaseは既知12行のみ。',
        参照資料SHA256=reference,API取得数=0,現在保存物使用=False)
    if FIXED_PATH.exists():assert read(FIXED_PATH)==value,'固定後に実装又は対象が変化しています'
    else:save(FIXED_PATH,value)
    verify_references(reference)
    return value


def initialize(stop: str) -> None:
    """機能: 各処理で旧凍結入力と元の厳格監査を初期化する。

    引数: stop(str)は同じ実行の停止証跡パス。返り値: なし(None)。
    """
    global STOP_PATH
    STOP_PATH=Path(stop)
    audit.initialize()
    assert len(runner.INPUTS)==26
    assert Path(audit.slots.__file__).resolve()==OLD/'adaptive_slot_audit.py'
    fixed=read(FIXED_PATH)
    for path in (Path(__file__),HERE/'engine_partial_restore_corrected.py'):
        assert digest(path)==fixed['参照資料SHA256'][path.relative_to(ROOT).as_posix()]


def play(engine: object, spec: dict, ready: dict, columns: tuple, config: dict, shadow: dict) -> dict:
    """機能: 同一入力と同一指紋の影を、旧版又は一行修正版へ渡す。

    引数: engine(module)、spec/ready/config/shadow(dict)、columns(tuple)。返り値: 全結果(dict)。
    """
    state,bad,bad_source,good,good_source,valid,branch,branch_source,branch_valid,choice=columns
    assert shadow['input_sha256']==engine.input_digest(ready,state,config,spec['observed_fill'],spec['min_delay_seconds'])
    return engine.run(ready,state,config,bad,bad_source,good,good_source,spec['policy'],
        observed_fill=spec['observed_fill'],detail=True,shadow=shadow,good_valid=valid,
        budget_enabled=spec['budget_enabled'],min_delay_seconds=spec['min_delay_seconds'],
        branch_direction=branch,branch_source=branch_source,branch_valid=branch_valid,
        branch_mode=spec['branch_mode'],branch_choice=choice,branch_seed=spec['branch_seed'])


def evaluate(spec: dict, supplementary: bool) -> dict:
    """機能: 一条件の全26で旧保存同値・限定状態修正・元厳格監査を確認する。

    引数: spec(dict)、supplementary(bool)。返り値: 今回の条件別証跡への参照(dict)。
    phase以外の差又は既知12行以外の状態差を検知したら保存して停止する。
    """
    started=time.perf_counter();identifier=spec['id'];base=OLD/('supplementary' if supplementary else '')
    paths={name:base/name/(identifier+suffix) for name,suffix in (
        ('ledgers','.json.gz'),('sessions','.json.gz'),('accounting','.json.gz'),('summaries','.json'))}
    before={path.relative_to(ROOT).as_posix():digest(path) for path in paths.values()}
    saved={name:{(row['session'],row['symbol']):row for row in read(path)}
           for name,path in paths.items() if name!='summaries'}
    summary=read(paths['summaries'])
    assert summary['id']==identifier and summary['spec']==spec
    assert summary['探索固定SHA256']==digest(OLD/'探索条件の固定.json')
    for part in saved.values():assert len(part)==26 and set(part)==set(runner.INPUTS)
    rows=[];proofs=[];series={};differences=[];ledger_sha=hashlib.sha256()
    for key,ready in sorted(runner.INPUTS.items()):
        assert STOP_PATH is None or not STOP_PATH.exists(),'他条件の不一致により停止'
        columns=runner.columns(spec,key)
        config=runner.base.managers.make_config(runner.FIXED['manager'],key[1],ready)
        shadow=runner.shadow(spec,key,columns[0],config)
        shadow_before=runner.fingerprints(shadow,EXPECTED_SHADOW_FIELDS)
        old=play(runner.engine,spec,ready,columns,config,shadow)
        stored=saved['ledgers'][key]
        assert stored['config']==config and stored['result_fingerprints']==runner.fingerprints(old),(identifier,key,'旧全指紋')
        assert stored['shadow_fingerprints']==shadow_before,(identifier,key,'影全指紋')
        new=play(corrected,spec,ready,columns,config,shadow)
        new_fingerprints=runner.fingerprints(new)
        for field in runner.FIELDS:
            if field!='control_curve':
                assert new_fingerprints[field]==stored['result_fingerprints'][field],(identifier,key,field,'経済又は証跡差')
        for field in runner.STORED:
            actual=np.asarray(stored[field],dtype=float).reshape(new[field].shape)
            assert np.array_equal(actual,new[field],equal_nan=True),(identifier,key,field)
        old_control,new_control=old['control_curve'],new['control_curve']
        assert old_control.shape==new_control.shape and old_control.dtype==new_control.dtype
        nonphase=[i for i in range(20) if i!=2]
        assert np.ascontiguousarray(old_control[:,nonphase]).tobytes()==np.ascontiguousarray(new_control[:,nonphase]).tobytes(),(identifier,key,'phase以外の管理列')
        changed=np.flatnonzero(old_control[:,2]!=new_control[:,2]).tolist()
        expected=EXPECTED_ROWS if identifier==BAD_ID and key==BAD_KEY else []
        if changed!=expected:
            save(HERE/'unexpected_phase'/f'{identifier}__{key[0]}__{key[1]}.json',
                dict(id=identifier,session=key[0],symbol=key[1],expected=expected,actual=changed,
                     old=old_control[changed,2].tolist(),new=new_control[changed,2].tolist()))
            raise AssertionError((identifier,key,'既知範囲外の状態差',changed,expected))
        if changed:
            assert np.all(old_control[changed,2]==1) and np.all(new_control[changed,2]==0)
            assert np.all(new_control[changed,8]==0) and np.all(new_control[changed,13]==1)
            # ----------------------------------------
            # 元監査の失敗を実際に再現し、修正版だけが同じ検査を通ることを確かめる。
            try:audit.inspect(spec,ready,old,config,columns)
            except AssertionError as error:assert '全行の減量状態' in str(error),str(error)
            else:raise AssertionError('旧版で既知状態不適合を再現できません')
            differences.extend(dict(session=key[0],symbol=key[1],row=i,seq=int(ready['seq'][i]),
                time_s=float(ready['time_s'][i]),old=1,new=0) for i in changed)
        row,curves,proof,basic=audit.inspect(spec,ready,new,config,columns)
        for flag in PROOF_FLAGS:assert proof[flag] is True,(identifier,key,flag)
        assert proof['原本行数']==len(ready['last'])
        audit.statistics.equal(saved['sessions'][key],row,'旧session全統計と修正版')
        shadow_equal=spec['policy']['kind']=='baseline' and (not spec['budget_enabled'] or spec['min_delay_seconds']==0.)
        if shadow_equal:
            for field in runner.engine.FIELDS:assert np.array_equal(new[field],shadow[field],equal_nan=True)
        expected_account=dict(session=key[0],symbol=key[1],**{k:v for k,v in basic.items() if k not in ('session','symbol')},
            全行会計一致=True,元A0一致=shadow_equal,影の全配列同値を要求=shadow_equal,
            独立時価SHA256=hashlib.sha256(curves['equity'].tobytes()).hexdigest())
        audit.statistics.equal(saved['accounting'][key],expected_account,'旧口座検算と修正版')
        assert runner.fingerprints(shadow,EXPECTED_SHADOW_FIELDS)==shadow_before,'共有影が変更されました'
        ledger_sha.update(str(key).encode('utf-8'));ledger_sha.update(new['trades'].tobytes())
        rows.append(row);series[key]=curves['equity']
        proofs.append(dict(session=key[0],symbol=key[1],**proof,旧保存全指紋一致=True,
            修正後状態契約合格=True,phase以外全配列完全一致=True,状態変更行数=len(changed),
            修正版全指紋=new_fingerprints,影入力SHA256=shadow['input_sha256'],影全指紋=shadow_before))
        del old,new,curves
    assert ledger_sha.hexdigest()==summary['ledger_hash']
    periods={}
    for period,names in (('all_symbols',runner.FIXED['全セッション']),('symbols',runner.FIXED['後半7セッション'])):
        periods[period]={s:audit.statistics.period(rows,series,names,s,runner.base.research.MULT[s]) for s in runner.SYMBOLS}
        audit.statistics.equal(summary[period],periods[period],'旧全期間と修正版:'+period)
    assert before=={path.relative_to(ROOT).as_posix():digest(path) for path in paths.values()}
    assert len(differences)==(12 if identifier==BAD_ID else 0)
    detail=dict(id=identifier,spec=spec,補助条件=supplementary,全合格=True,全入力数=26,
        原版状態監査合格=True,経済全配列完全一致=True,全保存統計一致=True,影不変=True,
        状態変更行数=len(differences),状態変更全行=differences,検査=proofs,sessions=rows,**periods,
        全原本行会計数=sum(len(r['last']) for r in runner.INPUTS.values()),
        旧成果SHA256=before,固定SHA256=digest(FIXED_PATH),経過秒=time.perf_counter()-started,
        旧成果変更=False,新条件探索=False,API取得数=0,現在保存物使用=False)
    target=HERE/'state_fix_details'/(identifier+'.json.gz');save(target,detail)
    return dict(id=identifier,補助条件=supplementary,全合格=True,全入力数=26,状態変更行数=len(differences),
        全原本行会計数=detail['全原本行会計数'],実体=target.relative_to(ROOT).as_posix(),実体SHA256=digest(target))


def reusable(record: dict, spec: dict, supplementary: bool) -> bool:
    """機能: 中断前の条件証拠を指紋・全26集合・元資料へ再結合する。

    引数: record/spec(dict)、supplementary(bool)。返り値: 再利用可能か(bool)。不整合は停止。
    """
    path=ROOT/record['実体'];assert path.resolve().is_relative_to(HERE/'state_fix_details')
    assert record['id']==spec['id'] and record['実体SHA256']==digest(path)
    value=read(path);assert value['id']==spec['id'] and value['spec']==spec
    assert value['補助条件']==supplementary and value['固定SHA256']==digest(FIXED_PATH)
    for flag in ('全合格','原版状態監査合格','経済全配列完全一致','全保存統計一致','影不変'):assert value[flag] is True
    expected={(session,symbol) for session in runner.read(OLD/'探索条件の固定.json')['全セッション'] for symbol in runner.SYMBOLS}
    assert len(value['検査'])==26 and {(row['session'],row['symbol']) for row in value['検査']}==expected
    assert len(value['sessions'])==26 and {(row['session'],row['symbol']) for row in value['sessions']}==expected
    assert value['状態変更行数']==record['状態変更行数']==(12 if spec['id']==BAD_ID else 0)
    for row in value['検査']:
        for flag in PROOF_FLAGS+('旧保存全指紋一致','修正後状態契約合格','phase以外全配列完全一致'):assert row[flag] is True
    verify_references(value['旧成果SHA256'])
    return True


def main() -> None:
    """機能: 先行52又は全25324入力を条件単位で中断再開して検証する。

    引数: --prepare/--pilot/--all(bool)、--workers(int)。返り値: なし(None)。全件は明示指示時だけ開始。
    """
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare',action='store_true');mode.add_argument('--pilot',action='store_true');mode.add_argument('--all',action='store_true')
    parser.add_argument('--workers',type=int,default=1);args=parser.parse_args()
    assert 1<=args.workers<=32
    frozen=prepare();specs,supplementary=specifications()
    if args.prepare:print('状態一行修正と旧974対象を固定・指紋一致',flush=True);return
    if args.all:
        pilot=read(HERE/'状態修正の先行検査.json')
        assert pilot['全合格'] and pilot['固定SHA256']==digest(FIXED_PATH) and pilot['状態変更行数']==12
    chosen=[spec for spec in specs if args.all or spec['id'] in PILOT]
    chosen_ids={spec['id'] for spec in chosen};assert len(chosen)==(974 if args.all else 2)
    progress=read(PROGRESS_PATH) if PROGRESS_PATH.exists() else dict(固定SHA256=digest(FIXED_PATH),結果=[])
    assert progress['固定SHA256']==digest(FIXED_PATH)
    prior={record['id']:record for record in progress['結果']}
    assert len(prior)==len(progress['結果']) and set(prior)<={spec['id'] for spec in specs}
    missing=[];records=[]
    for spec in chosen:
        if spec['id'] in prior and reusable(prior[spec['id']],spec,spec['id'] in supplementary):records.append(prior[spec['id']])
        else:missing.append(spec)
    stop=HERE/f'state_fix_stop_{time.time_ns()}.json';began=time.perf_counter()
    print(json.dumps(dict(対象=len(chosen),再利用=len(records),再生=len(missing)),ensure_ascii=False),flush=True)
    def finish(record: dict) -> None:
        """機能: 一条件完了を中断再開用の正本へ保存する。

        引数: record(dict)。返り値: なし(None)。
        """
        records.append(record);prior[record['id']]=record
        save(PROGRESS_PATH,dict(固定SHA256=digest(FIXED_PATH),結果=[prior[k] for k in sorted(prior)]))
        print(f'{len(records)}/{len(chosen)} {record["id"]} 原監査合格・状態差{record["状態変更行数"]}',flush=True)
    try:
        if args.workers==1:
            initialize(str(stop))
            for spec in missing:finish(evaluate(spec,spec['id'] in supplementary))
        else:
            with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize,initargs=(str(stop),)) as pool:
                futures={pool.submit(evaluate,spec,spec['id'] in supplementary):spec['id'] for spec in missing}
                try:
                    for future in as_completed(futures):finish(future.result())
                except BaseException:
                    save(stop,dict(停止=True,例外=traceback.format_exc()))
                    for future in futures:future.cancel()
                    raise
        assert {record['id'] for record in records}==chosen_ids and sum(r['状態変更行数'] for r in records)==12
        verify_references(frozen['参照資料SHA256'])
        for record in records:assert digest(ROOT/record['実体'])==record['実体SHA256']
        result=dict(全合格=True,修正後実装状態契約合格=True,経済全配列完全一致=True,全保存統計一致=True,
            原版監査を無変更で使用=True,全条件数=len(records),主条件数=sum(not r['補助条件'] for r in records),
            補助条件数=sum(r['補助条件'] for r in records),全入力数=sum(r['全入力数'] for r in records),
            全原本行会計数=sum(r['全原本行会計数'] for r in records),状態変更条件数=1,状態変更行数=12,
            既知12行だけ修正=True,結果=sorted(records,key=lambda r:r['id']),固定SHA256=digest(FIXED_PATH),
            参照資料SHA256=frozen['参照資料SHA256'],経過秒=time.perf_counter()-began,
            採否変更=False,旧成果変更=False,新条件探索=False,API取得数=0,現在保存物使用=False)
        target=HERE/('状態修正の全再生.json' if args.all else '状態修正の先行検査.json');save(target,result)
        print(json.dumps({k:v for k,v in result.items() if k not in ('結果','参照資料SHA256')},ensure_ascii=False),flush=True)
    except BaseException:
        failure=dict(全合格=False,対象ID=sorted(chosen_ids),完了ID=[r['id'] for r in records],
            例外=traceback.format_exc(),固定SHA256=digest(FIXED_PATH),旧成果変更=False)
        save(HERE/'状態修正の失敗.json',failure)
        raise


if __name__=='__main__':main()
