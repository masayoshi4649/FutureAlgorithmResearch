"""全427条件を別会計・枠・予約・期間統計へ結び、好成績の選別をしない。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import numpy as np

import partial_runner as runner
import partial_cash_reconstruction as cash
import partial_independent_statistics as statistics
import partial_slot_audit as slots


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def close(a: object, b: object, label: str) -> None:
    """機能: 独立会計の頻繁な数値比較を同じ絶対誤差で行う。

    引数: a/b (object)、label (str)。返り値: なし (None)。
    """
    left, right = np.asarray(a), np.asarray(b)
    assert left.shape == right.shape and np.isfinite(left).all() and np.isfinite(right).all(), label
    assert np.all(np.abs(left-right) <= 1e-6), label


def initialize() -> None:
    """機能: 凍結資料を検査して既知入力だけを各プロセスへ設定する。

    引数: なし。返り値: なし (None)。
    """
    fixed = runner.read(HERE/'partial_accounting_fixed.json')
    for relative, sha in fixed['参照SHA256'].items(): assert runner.digest(ROOT/relative) == sha, relative
    runner.initialize()
    cash.close = close


def inspect(identifier: str, ready: dict, result: dict, config: dict, policy: dict,
            bad: np.ndarray, bad_source: np.ndarray, good: np.ndarray, good_source: np.ndarray,
            valid: np.ndarray) -> tuple:
    """機能: 一入力の注文会計・全行枠・公開予約・表示統計を別式で再構成する。

    引数: identifier (str)、ready/result/config/policy (dict)、方向/根拠/valid (ndarray)。
    返り値: 独立指標・独立曲線・枠証跡・基本会計 (tuple)。
    """
    basic, curves = cash.reconstruct(ready, result, ready['symbol'])
    proof = slots.audit(ready, result, config, policy, bad, bad_source, good, good_source, valid, curves)
    row = statistics.session(identifier, ready, result, config, basic, curves, bad)
    return row, curves, proof, basic


def evaluate(spec: dict, destination: str = '') -> dict:
    """機能: 全26入力を再生成し、全保存台帳・必須統計・期間時価へ接続する。

    引数: spec (dict)、destination (str)。返り値: 一条件の独立証跡 (dict)。
    """
    identifier = spec['id']; started = time.perf_counter()
    base = HERE/destination
    paths = {folder:base/folder/(identifier+suffix) for folder,suffix in (
        ('sessions','.json.gz'),('ledgers','.json.gz'),('waves','.json.gz'),('accounting','.json.gz'),('summaries','.json'))}
    before = {p.relative_to(ROOT).as_posix():runner.digest(p) for p in paths.values()}
    summary = runner.read(paths['summaries'])
    assert summary['id'] == identifier and summary['spec'] == spec
    assert summary['探索固定SHA256'] == runner.digest(HERE/'探索条件の固定.json')
    saved = {}
    for folder in ('sessions','ledgers','accounting'):
        values=runner.read(paths[folder]); assert len(values)==26
        mapped={(v['session'],v['symbol']):v for v in values}
        assert len(mapped)==26 and set(mapped)==set(runner.INPUTS)
        saved[folder]=mapped
    rows, evidence, series = [], [], {}
    ledger_hash=hashlib.sha256()
    for key, ready in sorted(runner.INPUTS.items()):
        state,bad,bad_source,good,good_source,valid=runner.columns(spec,key)
        config=runner.base.managers.make_config(runner.FIXED['manager'],key[1],ready)
        original=runner.shadow(spec,key,state,config)
        result=runner.engine.run(ready,state,config,bad,bad_source,good,good_source,spec['policy'],
            observed_fill=spec['observed_fill'],detail=True,shadow=original,good_valid=valid)
        row,curves,proof,basic=inspect(identifier,ready,result,config,spec['policy'],bad,bad_source,good,good_source,valid)
        statistics.equal(saved['sessions'][key],row,'全session必須統計')
        stored=saved['ledgers'][key]
        assert stored['config']==config
        assert stored['result_fingerprints']==runner.fingerprints(result)
        assert stored['shadow_fingerprints']==runner.fingerprints(original,runner.engine.FIELDS+('plans','prepare_events','entry_preparations'))
        for name in runner.STORED:
            values=np.asarray(stored[name],dtype=float).reshape(result[name].shape)
            assert np.array_equal(values,result[name],equal_nan=True),(identifier,key,name)
        expected=dict(session=key[0],symbol=key[1],**{k:v for k,v in basic.items() if k not in ('session','symbol')},
            全行会計一致=True,元A0一致=spec['policy']['kind']=='baseline',
            独立時価SHA256=hashlib.sha256(curves['equity'].tobytes()).hexdigest())
        statistics.equal(saved['accounting'][key],expected,'主の独立会計表示')
        if spec['policy']['kind']=='baseline':
            for name in runner.engine.FIELDS:
                assert np.array_equal(result[name],original[name],equal_nan=True)
        ledger_hash.update(str(key).encode('utf-8')); ledger_hash.update(result['trades'].tobytes())
        rows.append(row); series[key]=curves['equity']
        evidence.append(dict(session=key[0],symbol=key[1],**proof,全保存数値一致=True,全台帳配列一致=True))
    assert ledger_hash.hexdigest()==summary['ledger_hash']
    periods={}
    for period,names in (('all_symbols',runner.FIXED['全セッション']),('symbols',runner.FIXED['後半7セッション'])):
        periods[period]={s:statistics.period(rows,series,names,s,runner.base.research.MULT[s]) for s in runner.SYMBOLS}
        statistics.equal(summary[period],periods[period],period+'全必須統計')
    assert before=={p.relative_to(ROOT).as_posix():runner.digest(p) for p in paths.values()}
    fixed_sha=runner.digest(HERE/'partial_accounting_fixed.json')
    result=dict(id=identifier,spec=spec,sessions=rows,検査=evidence,**periods,
        全監査合格=True,全入力数=26,全原本行会計数=sum(len(r['last']) for r in runner.INPUTS.values()),
        保存資料SHA256=before,監査固定SHA256=fixed_sha,探索固定SHA256=runner.digest(HERE/'探索条件の固定.json'),
        経過秒=time.perf_counter()-started)
    runner.save(base/'partial_accounting_details'/(identifier+'.json.gz'),result)
    return dict(id=identifier,全監査合格=True,全入力数=26,全原本行会計数=result['全原本行会計数'],
        実体SHA256=runner.digest(base/'partial_accounting_details'/(identifier+'.json.gz')),監査固定SHA256=fixed_sha)


def selftest() -> dict:
    """機能: 人工価格全309管理と破損反例で会計・枠・全統計を結果前に検査する。

    引数: なし。返り値: 合成証跡 (dict)。新実データは読まない。
    """
    import partial_engine_audit as fixtures
    cash.close=close
    count=0; rejection=0
    retained=None
    for policy in runner.design.policies():
        rows=[]; series={}
        for symbol in runner.SYMBOLS:
            args=list(deepcopy(fixtures.fixture([100,101,103,100,103,104,100,99,101,104,100,98,95],(2,6,10),(4,8))))
            ready=args[0];ready.update(symbol=symbol,session='2026-09-21_Day')
            args[2]=fixtures.helpers.config(symbol,ready)
            valid=np.ones(len(ready['last']),bool)
            for inactive in (False,True):
                current=deepcopy(args)
                if inactive: current[1][:]=0
                result=fixtures.play(tuple(current),policy,good_valid=valid)
                row,curves,proof,basic=inspect(policy['id'],ready,result,current[2],policy,*current[3:],valid)
                saved=runner.session_row(policy['id'],ready,result,current[2],current[3],basic,curves)
                statistics.equal(saved,row,'人工session')
                if not inactive: rows.append(row);series[(ready['session'],symbol)]=curves['equity']
                if policy['id']==runner.design.PRIMARY_POLICY and symbol=='TOPIX' and not inactive:
                    retained=(current,policy,result,valid,curves,row)
                count+=1
        expected=runner.period(rows,['2026-09-21_Day'])
        for symbol in runner.SYMBOLS:
            statistics.equal(expected[symbol],statistics.period(rows,series,['2026-09-21_Day'],symbol,
                runner.base.research.MULT[symbol]),'人工period')
    assert retained is not None
    args,policy,result,valid,curves,row=retained
    changes=[('slot_curve',(2,0),0),('control_curve',(2,5),99.),
        ('slot_events',(0,3),99.),('orders',(0,4),99.),('adjustment_events',(0,5),0.)]
    for field,index,value in changes:
        changed=deepcopy(result); changed[field][index]=value
        try: inspect(policy['id'],args[0],changed,args[2],policy,*args[3:],valid)
        except (AssertionError,IndexError,KeyError,ValueError): rejection+=1
        else: raise AssertionError('破損受理:'+field)
    for field in row:
        changed=deepcopy(row);del changed[field]
        try: statistics.equal(changed,row,'必須統計欠落')
        except AssertionError: rejection+=1
        else: raise AssertionError('欠落受理:'+field)
    return dict(全合格=True,人工入力検査数=count,破損欠落拒否数=rejection,
        全309管理両銘柄活動無取引=True,新実データ損益=False,API取得数=0,現在保存物使用=False)


def prepare() -> dict:
    """機能: 全427の対象・監査経路・人工検査・実装を新損益前に固定する。

    引数: なし。返り値: 固定資料 (dict)。
    """
    path=HERE/'partial_accounting_fixed.json'
    if path.exists():
        fixed=runner.read(path)
        for relative,sha in fixed['参照SHA256'].items():assert runner.digest(ROOT/relative)==sha,relative
        return fixed
    test=selftest();runner.save(HERE/'partial_accounting_selftest.json',test)
    paths={HERE/name for name in ('partial_accounting_audit.py','partial_slot_audit.py',
        'partial_independent_statistics.py','partial_cash_reconstruction.py','partial_accounting_selftest.json',
        'partial_accounting_oracles.py','partial_accounting_oracles.json','partial_runner.py',
        'engine_partial_restore.py','engine_shadow_plan.py','partial_design.py','partial_inputs.py',
        'partial_input_fixed.json','partial_engine_audit.py')}
    originals=runner.read(HERE/'partial_input_causality.json')['原本78SHA256']
    for relative,sha in originals.items():assert runner.digest(ROOT/relative)==sha
    fixed=dict(主対象=runner.design.catalog(),補助対象=runner.design.supplementary(),
        主条件数=363,補助条件数=64,全条件数=427,全入力数=427*26,
        規則='全条件全26。別注文会計、枠状態と退役、予約有無の全行検算、新根拠と次行、予算保持、同約定両建て時価、全session/period必須統計、保存全配列SHA。成績で除外しない。',
        因果性の分担='別partial_causality_auditで代表1730入力のprefix/future/reflection。本文の全会計427×26と区別する。',
        人工検査=test,原本78SHA256=originals,
        参照SHA256={p.relative_to(ROOT).as_posix():runner.digest(p) for p in sorted(paths)},
        新実データ損益=False,API取得数=0,現在保存物使用=False)
    runner.save(path,fixed)
    return fixed


def main() -> None:
    """機能: 結果前固定又は完成済み主・補助全件の独立会計を実行する。

    引数: --prepare/--supplementary (bool)、--workers (int)。返り値: なし (None)。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--supplementary',action='store_true');parser.add_argument('--workers',type=int,default=8)
    args=parser.parse_args()
    fixed=prepare()
    if args.prepare:print('全427の独立会計を結果前固定。人工入力',fixed['人工検査']['人工入力検査数'],flush=True);return
    initialize();destination='supplementary' if args.supplementary else ''
    specs=fixed['補助対象'] if args.supplementary else fixed['主対象']
    before={relative:runner.digest(ROOT/relative) for relative in fixed['参照SHA256']}
    records=[]
    with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize) as executor:
        futures={executor.submit(evaluate,spec,destination):spec['id'] for spec in specs}
        for future in as_completed(futures):
            records.append(future.result())
            if len(records)%12==0 or len(records)==len(specs):print('独立会計',len(records),'/',len(specs),flush=True)
    assert before=={relative:runner.digest(ROOT/relative) for relative in before}
    for relative,sha in fixed['原本78SHA256'].items():assert runner.digest(ROOT/relative)==sha
    result=dict(全監査合格=True,対象条件数=len(specs),全入力数=len(specs)*26,
        全原本行会計数=sum(r['全原本行会計数'] for r in records),条件=sorted(records,key=lambda r:r['id']),
        全枠会計一致=True,全予約と新根拠一致=True,同約定両建て全行一致=True,全予算予約一致=True,
        全保存統計一致=True,全台帳配列一致=True,元終了以前=True,
        監査固定SHA256=runner.digest(HERE/'partial_accounting_fixed.json'),
        探索固定SHA256=runner.digest(HERE/'探索条件の固定.json'),参照SHA256=before,
        原本78SHA256=fixed['原本78SHA256'],API取得数=0,現在保存物使用=False)
    runner.save(HERE/destination/'partial_accounting_audit.json',result)
    print('独立会計の全件完了',len(specs),flush=True)


if __name__=='__main__':main()
