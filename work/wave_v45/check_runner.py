"""実相場を再生せず、順行ゲートと既存注文・厳格会計の接続を反証する。"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

import numpy as np

import runner
import adaptive_statistics_selftest as fixtures

HERE, ROOT = runner.HERE, runner.ROOT


def inspect(spec: dict, ready: dict, columns: tuple, config: dict, actual: tuple) -> tuple:
    """機能: 元厳格監査・全表示統計・影と実の初回新規を照合する。

    引数: spec/ready/config(dict)、columns/actual(tuple)。返り値: 統計・時価曲線(tuple)。
    """
    result, effective, _ = actual
    row, curves, proof, basic = runner.audit.inspect(spec, ready, result, config, effective)
    assert all(proof[name] is True for name in runner.PROOF_FLAGS)
    assert proof['原本行数'] == len(ready['last'])
    other = runner.old.session_row(spec['id'], ready, result, config, effective[1], basic, curves)
    runner.audit.statistics.equal(row, other, '人工全統計')
    runner.initial_identity(ready, result)
    assert all(effective[i] is columns[i] for i in (0,3,4,5,6,7,8,9))
    np.testing.assert_array_equal(effective[2], columns[2])
    return row, curves


def wiring(specs: list[dict]) -> dict:
    """機能: 10列委譲と悪化品質の独立取得、旧六対照の完全な条件対応を検査する。

    引数: specs(list[dict])。返り値: 接続件数・旧条件対応(dict)。
    """
    key = ('2026-09-21_Day','TOPIX')
    ready, columns, _ = fixtures.artificial(specs[0], key[1])
    prior = {s['id']:s for s in runner.read(HERE.parent/'wave_v38/探索条件の固定.json')['conditions']}
    legacy = []
    for spec in specs:
        with patch.object(runner.old,'columns',return_value=columns) as call:
            actual = runner.columns_for(spec,key)
        assert actual is columns and call.call_args.args == (spec,key)
        separate_quality = ~columns[5]
        with patch.object(runner.legacy,'INPUTS',{key:ready}), patch.object(
                runner.old.inputs,'publication_valid',return_value=separate_quality) as quality:
            valid = runner.quality_for(spec,key)
        if spec['policy']['kind'] == 'dynamic':
            assert valid is separate_quality
            assert quality.call_args.args == (spec['policy']['bad_id'],key,spec['bad_scale'])
        else:
            assert not valid.any() and quality.call_count == 0
        identifier = runner.legacy_id(spec)
        if identifier:
            older = prior[identifier]
            for field in older:
                if field not in ('id','role','primary','variant_id'):
                    assert spec[field] == older[field], (identifier,field)
            legacy.append(dict(id=spec['id'],旧ID=identifier))
    assert len(legacy) == len({r['旧ID'] for r in legacy}) == 6
    return dict(全条件入力接続数=len(specs),旧恒等条件対応=legacy)


def active_gate_fixture(spec: dict, symbol: str, tie: bool = False) -> tuple:
    """機能: 初回ATR二倍以上の順行・悪化・回復・部分利確を持つ人工経路を作る。

    引数: spec(dict)、symbol(str)、tie(bool)。返り値: 原本・10列・設定・悪化品質(tuple)。
    数値は検査だけの人工価格で、実相場や保存損益を参照しない。
    """
    ready, columns, config = fixtures.artificial(spec, symbol)
    ready['last'] = np.array([100,101,103,105,107,108,109,108,107,108,109,111,
        112,111,110,111,112,113,111,109,108,106,103,100,100,100.],float)
    if tie:
        ready['time_s'][9] = ready['time_s'][8]
    columns = list(columns)
    columns[1] = np.full(len(ready['last']),-1,np.int8)
    columns[3] = np.ones(len(ready['last']),np.int8)
    return ready, tuple(columns), config, np.ones(len(ready['last']),bool)


def reject_damage(spec: dict, ready: dict, columns: tuple, config: dict,
                  actual: tuple, valid: np.ndarray) -> int:
    """機能: 口座・ゲート記録・初回新規・必要統計の破損を拒否する。

    引数: spec/ready/config(dict)、columns/actual(tuple)、valid(bool ndarray)。返り値: 拒否数(int)。
    """
    rejection = 0
    for field, index in (('orders',(0,4)),('control_curve',(2,2)),('slot_curve',(2,0))):
        changed = deepcopy(actual); changed[0][field][index] += 1
        try:
            inspect(spec,ready,columns,config,changed)
        except (AssertionError,ValueError,IndexError):
            rejection += 1
        else:
            raise AssertionError('口座破損を受理:'+field)
    changed = deepcopy(actual); changed[0]['orders'][0,5] += 1
    try:
        runner.initial_identity(ready,changed[0])
    except AssertionError:
        rejection += 1
    else:
        raise AssertionError('初回価格破損を受理')
    for field in actual[2]:
        changed = deepcopy(actual)
        value = changed[2][field]
        if value.dtype == np.bool_:
            value[1] = ~value[1]
        else:
            value[1] = 99
        try:
            runner.gate_prefix(actual,changed,len(ready['last']))
        except AssertionError:
            rejection += 1
        else:
            raise AssertionError('ゲート証拠破損を受理:'+field)
    row, _ = inspect(spec,ready,columns,config,actual)
    for name in row:
        changed = dict(row); del changed[name]
        try:
            runner.audit.statistics.equal(row,changed,'統計必須項目')
        except AssertionError:
            rejection += 1
        else:
            raise AssertionError('必要統計欠落を受理:'+name)
    return rejection



def delegation() -> dict:
    """機能: 旧因果成果の前提となる経済・入力関数の完全な直接委譲を確認する。

    引数: なし。返り値: 関数名と元実装指紋(dict)。旧関数の複写ではなく同じ関数実体を使う。
    """
    names = ('columns_for','quality_for','play','gate_prefix','causal_check',
             'initial_identity','gate_record','legacy_id')
    for name in names:
        assert getattr(runner,name) is getattr(runner.legacy,name),name
    assert runner.engine is runner.legacy.engine and runner.audit is runner.legacy.audit
    assert runner.gate is runner.legacy.gate
    return dict(全同関数=True,関数=list(names),旧runnerSHA256=runner.digest(runner.PRIOR/'runner.py'),
                旧ゲートSHA256=runner.digest(Path(runner.gate.__file__)),
                旧注文器SHA256=runner.digest(Path(runner.engine.__file__)),
                旧厳格監査SHA256=runner.digest(Path(runner.audit.__file__)))


def inheritance_check(specs: list[dict]) -> dict:
    """機能: 人工八資料で十一引継ぎと改竄拒否を調べ、売買再生を禁止する。

    引数: specs(list[dict])。返り値: 件数と破損拒否数(dict)。実相場の成果を複写しない。
    """
    count = rejected = 0
    original_specs = {s['id']:s for s in runner.design.previous()['conditions']}
    with tempfile.TemporaryDirectory(prefix='引継ぎ人工_',dir=HERE) as directory:
        current = Path(directory)/'current'; previous = Path(directory)/'previous'
        current.mkdir(); previous.mkdir()
        fixed_path = current/'探索条件の固定.json'
        fixed_path.write_text('{}',encoding='utf-8')
        for spec in specs:
            if runner.design.reused_id(spec) is None:
                continue
            identifier = spec['id']; original = original_specs[identifier]
            old_sha = '1'*64
            with patch.object(runner,'HERE',Path(directory)):
                paths = []
                payloads = {}
                for folder,suffix in runner.ARTIFACTS:
                    payload = dict(id=identifier,spec=original,探索固定SHA256=old_sha,
                        全26全行独立会計一致=True,all_symbols={'TOPIX':{'net_yen':-37}},
                        symbols={'NK225':{'net_yen':71}}) if folder=='summaries' else [
                        dict(session=f'人工{i}',symbol=symbol,確認列=i) for i in range(13) for symbol in ('TOPIX','NK225')]
                    path = previous/folder/(identifier+suffix)
                    runner.save(path,payload); paths.append(path); payloads[folder] = payload
                record = dict(id=identifier,全合格=True,全入力数=26,因果入力数=4,
                    全原本行会計数=780,旧単一窓一致入力数=26 if runner.legacy_id(spec) else 0,
                    探索固定SHA256=old_sha,
                    出力SHA256={p.relative_to(ROOT).as_posix():runner.digest(p) for p in paths})
                record_path = previous/'completed'/(identifier+'.json'); runner.save(record_path,record)
                sources = dict(record['出力SHA256']); sources[record_path.relative_to(ROOT).as_posix()] = runner.digest(record_path)
                proof = dict(全合格=True,探索固定SHA256=old_sha,出力SHA256=sources)
                runner.save(previous/'完備監査.json',proof)
            source = dict(spec=original,completed=record_path.relative_to(ROOT).as_posix(),
                          出力SHA256=sources,旧探索固定SHA256=old_sha)
            with patch.object(runner,'HERE',current),patch.object(runner,'PRIOR',previous), \
                 patch.object(runner,'FIXED',{'既知再利用':{identifier:source}}), \
                 patch.object(runner,'play',side_effect=AssertionError('引継ぎ中の売買再生')):
                result = runner.reuse(spec)
                assert result['既知成果引継ぎ'] is True and result['新売買再生'] is False
                assert result['reuse_source'] == source
                assert len(result['出力SHA256']) == 7
                for folder,suffix in runner.ARTIFACTS:
                    target = current/folder/(identifier+suffix)
                    if folder=='summaries':
                        summary = runner.read(target)
                        assert summary['spec']==spec and summary['探索固定SHA256']==runner.digest(fixed_path)
                        assert {k:v for k,v in summary.items() if k not in ('spec','探索固定SHA256')} == {
                            k:v for k,v in payloads[folder].items() if k not in ('spec','探索固定SHA256')}
                    else:
                        assert target.read_bytes() == (previous/folder/(identifier+suffix)).read_bytes()
                # ----------------------------------------
                # ID・経済条件・資料欠落・原資料改竄・完備からの切断を別々に拒否する。
                mutations=[]
                wrong = deepcopy(spec); wrong['gate_threshold_atr']+=.01; mutations.append((wrong,source))
                wrong = deepcopy(source); wrong['spec']['min_delay_seconds']+=1; mutations.append((spec,wrong))
                wrong = deepcopy(source); del wrong['出力SHA256'][next(iter(wrong['出力SHA256']))]; mutations.append((spec,wrong))
                wrong = deepcopy(source); wrong['旧探索固定SHA256']='2'*64; mutations.append((spec,wrong))
                wrong = deepcopy(source); wrong['出力SHA256'][next(iter(wrong['出力SHA256']))]='3'*64; mutations.append((spec,wrong))
                wrong = deepcopy(source); wrong['completed']='work/wave_v44/completed/別条件.json'; mutations.append((spec,wrong))
                for changed_spec,changed_source in mutations:
                    with patch.object(runner,'FIXED',{'既知再利用':{identifier:changed_source}}):
                        try: runner.reuse(changed_spec)
                        except (AssertionError,ValueError,KeyError): rejected+=1
                        else: raise AssertionError('破損した既知資料を受理')
                prior_proof = previous/'完備監査.json'
                damaged = deepcopy(proof); damaged['出力SHA256'][source['completed']]='4'*64
                prior_proof.write_text(json.dumps(damaged,ensure_ascii=False),encoding='utf-8')
                try: runner.reuse(spec)
                except AssertionError: rejected+=1
                else: raise AssertionError('旧完備との切断を受理')
            count+=1
    assert count == 11 and rejected == 77
    return dict(全合格=True,既知条件数=count,六成果バイト同一=True,
                要約変更は二欄のみ=True,売買再生呼出なし=True,破損拒否数=rejected,実相場資料複写=False)


def run() -> dict:
    """機能: 全153条件×両市場×活動/無活動と、到達後の追加境界を検査する。

    引数: なし。返り値: 人工だけの監査証跡(dict)。実入力・新実損益へ接続しない。
    """
    runner.audit.cash.close = runner.audit.close
    specs = runner.design.catalog()+runner.design.supplementary()
    assert len(specs) == len({s['id'] for s in specs}) == 153
    paths = {Path(__file__),HERE/'runner.py',HERE/'design.py',HERE.parent/'wave_v44/profit_gate.py',
             HERE.parent/'wave_v38/探索条件の固定.json',HERE.parent/'wave_v37/partial_design_fixed.json'}
    for value in tuple(sys.modules.values()):
        source = getattr(value,'__file__',None)
        if source:
            path = Path(source).resolve()
            if path.is_relative_to(ROOT/'work') and path.suffix == '.py':
                paths.add(path)
    before = {p.relative_to(ROOT).as_posix():runner.digest(p) for p in sorted(paths)}
    connections = wiring(specs)
    delegated = delegation()
    inherited = inheritance_check(specs)
    count = period_count = legacy_count = 0; records = []
    for spec in specs:
        modes = {False:([],{}),True:([],{})}
        for symbol in runner.old.SYMBOLS:
            for inactive in (False,True):
                ready, columns, config = fixtures.artificial(spec,symbol,inactive)
                valid = columns[5].copy()
                actual = runner.play(spec,ready,columns,config,gate_valid=valid)
                row, curves = inspect(spec,ready,columns,config,actual)
                check = runner.causal_check(spec,ready,columns,config,actual,valid)
                usage = runner.gate_record(spec,ready,columns,actual[1],actual[2],valid,actual[0])
                json.dumps(usage,ensure_ascii=False,allow_nan=False)
                assert bool(len(actual[0]['orders'])) is not inactive
                if inactive:
                    assert row['net_yen'] == row['closed_units'] == 0
                if runner.legacy_id(spec):
                    old = fixtures.play(spec,ready,columns,config)
                    assert runner.old.fingerprints(old) == runner.old.fingerprints(actual[0])
                    assert runner.old.fingerprints(old['shadow'],runner.reference.EXPECTED_SHADOW_FIELDS) == runner.old.fingerprints(actual[0]['shadow'],runner.reference.EXPECTED_SHADOW_FIELDS)
                    legacy_count += 1
                rows, series = modes[inactive]
                rows.append(row); series[(ready['session'],symbol)] = curves['equity']
                records.append(dict(id=spec['id'],symbol=symbol,無活動=inactive,
                    原版厳格監査一致=True,全統計一致=True,全初回新規一致=True,**check))
                count += 1
        for rows, series in modes.values():
            previous = runner.old.period(rows,['2026-09-21_Day'])
            for symbol in runner.old.SYMBOLS:
                current = runner.audit.statistics.period(rows,series,['2026-09-21_Day'],symbol,
                    runner.old.base.research.MULT[symbol])
                runner.audit.statistics.equal(previous[symbol],current,'人工期間全統計')
                period_count += 1
    # ----------------------------------------
    # 許可が一度も使われない例だけで接続を合格にしない。
    active = []; retained = None
    for spec in runner.design.catalog():
        if spec['id'] not in (runner.design.PRIMARY,'G150_F50_N1__L015',
                              'G150_F50_N1__INV','G150_F50_N1__AV_ALL'):
            continue
        for symbol in runner.old.SYMBOLS:
            for tie in (False,True):
                ready, columns, config, valid = active_gate_fixture(spec,symbol,tie)
                actual = runner.play(spec,ready,columns,config,gate_valid=valid)
                inspect(spec,ready,columns,config,actual)
                runner.causal_check(spec,ready,columns,config,actual,valid)
                usage = runner.gate_record(spec,ready,columns,actual[1],actual[2],valid,actual[0])
                assert usage['armed_campaigns'] > 0
                if spec['gate_mode'] != 'inverse':
                    assert usage['reductions'] > 0 and usage['restorations'] > 0
                else:
                    assert usage['reductions'] == 0
                source = actual[1][2]
                admitted = actual[1][1] != 0
                assert np.all(source[admitted] > actual[2]['arm_row'][admitted])
                json.dumps(usage,ensure_ascii=False,allow_nan=False)
                active.append(dict(id=spec['id'],symbol=symbol,同秒=tie,
                    到達組数=usage['armed_campaigns'],減量回数=usage['reductions'],復元回数=usage['restorations']))
                if retained is None:
                    retained = spec,ready,columns,config,actual,valid
    assert count == period_count == 612 and legacy_count == 24 and len(active) == 16
    rejected = reject_damage(*retained)
    assert before == {name:runner.digest(ROOT/name) for name in before}
    return dict(全合格=True,主条件数=25,補助条件数=128,全条件数=153,
        人工入力検査数=count,人工期間比較数=period_count,先頭切断検査数=count+len(active),
        未来全列改変検査数=count+len(active),上下反射検査数=count+len(active),
        許可後活動と同秒境界検査数=len(active),元旧実装人工全15配列一致数=legacy_count,
        破損欠落拒否数=rejected,原版厳格監査を無変更使用=True,
        旧実相場156同値は旧実物と引継ぎ照合=True,新実相場損益=False,旧実相場再生=False,
        現在API取得数=0,保存ライブ使用=False,**connections,
        活動境界=active,検査=records,経済関数直接委譲=delegated,既知引継ぎ検査=inherited,参照資料SHA256=before)


if __name__ == '__main__':
    with patch.object(socket,'create_connection',side_effect=AssertionError('通信禁止')), \
         patch.object(socket.socket,'connect',side_effect=AssertionError('通信禁止')):
        proof = run()
    runner.save(HERE/'check_runner.json',proof)
    print(f"人工{proof['人工入力検査数']}入力・活動境界{proof['許可後活動と同秒境界検査数']}件を検査。",flush=True)
