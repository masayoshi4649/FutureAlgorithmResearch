"""全974条件を別会計・枠・分岐・成熟注文・期間統計へ結び、好成績の選別をしない。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import numpy as np

import adaptive_runner as runner
import adaptive_cash_reconstruction as cash
import adaptive_independent_statistics as statistics
import adaptive_slot_diagnostic as slots


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
    fixed = runner.read(HERE/'adaptive_accounting_fixed.json')
    for relative, sha in fixed['参照SHA256'].items(): assert runner.digest(ROOT/relative) == sha, relative
    runner.initialize()
    cash.close = close


def inspect(spec: dict, ready: dict, result: dict, config: dict, columns: tuple) -> tuple:
    """機能: 一入力の注文会計・全行枠・公開予約・表示統計を別式で再構成する。

    引数: spec/ready/result/config (dict)、columns (tuple[ndarray])。
    返り値: 独立指標・独立曲線・枠証跡・基本会計 (tuple)。
    """
    assert len(columns) == 10
    state,bad,bad_source,good,good_source,valid,branch,branch_source,branch_valid,choice = columns
    basic, curves = cash.reconstruct(ready, result, ready['symbol'])
    proof = slots.audit(ready, result, config, spec['policy'], bad, bad_source, good, good_source, valid, curves,
        state=state, budget_enabled=spec['budget_enabled'], min_delay_seconds=spec['min_delay_seconds'],
        observed_fill=spec['observed_fill'], branch_direction=branch, branch_source=branch_source,
        branch_valid=branch_valid, branch_mode=spec['branch_mode'], branch_choice=choice, branch_seed=spec['branch_seed'])
    row = statistics.session(spec['id'], ready, result, config, basic, curves, columns, spec)
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
        columns=runner.columns(spec,key)
        state,bad,bad_source,good,good_source,valid,branch,branch_source,branch_valid,choice=columns
        config=runner.base.managers.make_config(runner.FIXED['manager'],key[1],ready)
        original=runner.shadow(spec,key,state,config)
        result=runner.engine.run(ready,state,config,bad,bad_source,good,good_source,spec['policy'],
            observed_fill=spec['observed_fill'],detail=True,shadow=original,good_valid=valid,
            budget_enabled=spec['budget_enabled'],min_delay_seconds=spec['min_delay_seconds'],
            branch_direction=branch,branch_source=branch_source,branch_valid=branch_valid,
            branch_mode=spec['branch_mode'],branch_choice=choice,branch_seed=spec['branch_seed'])
        row,curves,proof,basic=inspect(spec,ready,result,config,columns)
        statistics.equal(saved['sessions'][key],row,'全session必須統計')
        stored=saved['ledgers'][key]
        assert stored['config']==config
        assert stored['result_fingerprints']==runner.fingerprints(result)
        assert stored['shadow_fingerprints']==runner.fingerprints(original,runner.engine.FIELDS+('plans','execution_plans','prepare_events','entry_preparations'))
        for name in runner.STORED:
            values=np.asarray(stored[name],dtype=float).reshape(result[name].shape)
            assert np.array_equal(values,result[name],equal_nan=True),(identifier,key,name)
        shadow_equal=spec['policy']['kind']=='baseline' and (not spec['budget_enabled'] or spec['min_delay_seconds']==0.)
        expected=dict(session=key[0],symbol=key[1],**{k:v for k,v in basic.items() if k not in ('session','symbol')},
            全行会計一致=True,元A0一致=shadow_equal,影の全配列同値を要求=shadow_equal,
            独立時価SHA256=hashlib.sha256(curves['equity'].tobytes()).hexdigest())
        statistics.equal(saved['accounting'][key],expected,'主の独立会計表示')
        if shadow_equal:
            for name in runner.engine.FIELDS:
                assert np.array_equal(result[name],original[name],equal_nan=True)
        ledger_hash.update(str(key).encode('utf-8')); ledger_hash.update(result['trades'].tobytes())
        rows.append(row); series[key]=curves['equity']
        assert proof['原本行数'] == len(ready['last'])
        evidence.append(dict(session=key[0],symbol=key[1],**proof,
            全保存数値一致=True,全台帳配列一致=True,分岐集計独立一致=True,全組R超過独立一致=True,
            影の全配列同値を要求=shadow_equal))
    assert ledger_hash.hexdigest()==summary['ledger_hash']
    periods={}
    for period,names in (('all_symbols',runner.FIXED['全セッション']),('symbols',runner.FIXED['後半7セッション'])):
        periods[period]={s:statistics.period(rows,series,names,s,runner.base.research.MULT[s]) for s in runner.SYMBOLS}
        statistics.equal(summary[period],periods[period],period+'全必須統計')
    assert before=={p.relative_to(ROOT).as_posix():runner.digest(p) for p in paths.values()}
    fixed_sha=runner.digest(HERE/'adaptive_accounting_fixed.json')
    result=dict(id=identifier,spec=spec,sessions=rows,検査=evidence,**periods,
        経済監査合格=True,状態契約合格=all(p['状態契約合格'] for p in evidence),全監査合格=all(p['状態契約合格'] for p in evidence),状態不一致行数=sum(p['状態不一致行数'] for p in evidence),既知残存型に限定=all(p['既知残存型に限定'] for p in evidence),全入力数=26,全原本行会計数=sum(len(r['last']) for r in runner.INPUTS.values()),
        保存資料SHA256=before,監査固定SHA256=fixed_sha,診断固定SHA256=runner.digest(HERE/'adaptive_accounting_diagnostic_fixed.json'),探索固定SHA256=runner.digest(HERE/'探索条件の固定.json'),
        経過秒=time.perf_counter()-started)
    runner.save(base/'adaptive_accounting_diagnostic_details'/(identifier+'.json.gz'),result)
    return dict(id=identifier,経済監査合格=True,状態契約合格=all(p['状態契約合格'] for p in evidence),全監査合格=all(p['状態契約合格'] for p in evidence),状態不一致行数=sum(p['状態不一致行数'] for p in evidence),既知残存型に限定=all(p['既知残存型に限定'] for p in evidence),全入力数=26,全原本行会計数=result['全原本行会計数'],
        実体SHA256=runner.digest(base/'adaptive_accounting_diagnostic_details'/(identifier+'.json.gz')),監査固定SHA256=fixed_sha,診断固定SHA256=runner.digest(HERE/'adaptive_accounting_diagnostic_fixed.json'))

