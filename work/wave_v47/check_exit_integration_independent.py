"""同期した出口短縮と数量調整を、旧注文器とは別の公開計画・枠会計で攻撃する。"""

from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

import exit_integration as integration
import integration_accounting_audit as audit

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
_fixture=importlib.util.spec_from_file_location('integration_validation_fixture',HERE.parent/'wave_v44/check_runner.py')
old_generic=sys.modules.get('runner')
saved_path=list(sys.path)
try:
    sys.modules['runner']=integration.reference
    sys.path.insert(0,str(HERE.parent/'wave_v33'))
    sys.path.insert(0,str(HERE.parent/'wave_v38'))
    helpers=importlib.util.module_from_spec(_fixture);_fixture.loader.exec_module(helpers)
finally:
    sys.path[:]=saved_path
    if old_generic is None:del sys.modules['runner']
    else:sys.modules['runner']=old_generic


def digest(path: Path) -> str:
    """機能: 実行した実装と参照資料を結ぶ指紋を返す。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(spec: dict, ready: dict, columns: tuple, config: dict, actual: tuple) -> dict:
    """機能: 会計・影の公開と全注文・枠・予約を独立再構成して初回同期と照合する。

    引数: spec/ready/config(dict)、columns/actual(tuple)。返り値: 全証拠(dict)。
    """
    result,effective,evidence=actual
    row,curves,proof,basic=audit.inspect(spec,ready,result,config,effective)
    assert all(proof[k] is True for k in integration.reference.PROOF_FLAGS)
    for key in ('影全会計一致','独立公開計画一致','独立準備一致','最新成熟計画一致','全行注文成立不成立一致'):
        assert proof['影の独立公開と執行'][key] is True
    original=integration.reference.old.session_row(spec['id'],ready,result,config,effective[1],basic,curves)
    audit.statistics.equal(row,original,'統計別経路')
    identity=integration.initial_identity(result)
    scheduler=result['shadow']['scheduler']
    bad,source,wanted=integration.reference.gate.gate_bad(ready,scheduler,columns[1],columns[2],
        spec['gate_threshold_atr'],mode=spec['gate_mode'],valid=np.ones(len(columns[0]),bool))
    np.testing.assert_array_equal(effective[1],bad)
    np.testing.assert_array_equal(effective[2],source)
    for key in wanted:np.testing.assert_array_equal(evidence[key],wanted[key])
    return dict(全独立監査合格=True,**identity,減量回数=row['reductions'],復元回数=row['restorations'])


def reject(spec: dict, ready: dict, columns: tuple, config: dict, actual: tuple) -> list[str]:
    """機能: 価格線・成熟元・同期許可・部分枠・予算・注文の意図的破損を拒否する。

    引数: spec/ready/config(dict)、columns/actual(tuple)。返り値: 拒否した箇所(list[str])。
    """
    rejected=[]
    for label in ('追跡線','成熟線','未公開許可','元scheduler','現金注文','部分利確枠','予算状態'):
        changed=deepcopy(actual);result=changed[0]
        if label=='追跡線':
            rows=np.flatnonzero(np.isfinite(result['shadow']['plans'][:,13]));assert len(rows)
            result['shadow']['plans'][rows[0],13]+=ready['tick']
        elif label=='成熟線':
            rows=np.flatnonzero(np.isfinite(result['shadow']['execution_plans'][:,13]));assert len(rows)
            result['shadow']['execution_plans'][rows[0],13]+=ready['tick']
        elif label=='未公開許可':result['shadow']['schedule_prepare_allow'][2]=~result['shadow']['schedule_prepare_allow'][2]
        elif label=='元scheduler':result['shadow']['scheduler']['plans'][4,13]=123456.
        elif label=='現金注文':result['orders'][0,4]+=1
        elif label=='部分利確枠':result['slot_curve'][8,0]+=1
        else:result['control_curve'][8,13]=1-result['control_curve'][8,13]
        try:inspect(spec,ready,columns,config,changed)
        except (AssertionError,ValueError,IndexError):rejected.append(label)
        else:raise AssertionError('破損を受理:'+label)
    return rejected


def run() -> dict:
    """機能: 全12人工と先読み・反射・同秒・旧E00の経済同値を確認する。

    引数: なし。返り値: 新Nightと実相場を使わない独立検査証拠(dict)。
    """
    specs=integration.catalog()
    assert len(specs)==len({s['id'] for s in specs})==12
    assert {(s['quantity_id'],s['exit_id']) for s in specs}=={(q,e) for q in ('A0','C01','F50','F50_NONE') for e in ('E00','E10','E11')}
    rows=[];negative=[];retained=None;old_matches=0
    for spec in specs:
        for symbol in ('TOPIX','NK225'):
            for tie in (False,True):
                ready,columns,config,valid=helpers.active_gate_fixture(spec,symbol,tie)
                ready['last']=np.array([100,101,103,106,108,110,113,114,116,118,117,115,
                    113,110,108,106,104,102,101,100,101,103,100,98,98,98.],float)
                config.update(tighten_atr=spec['tighten_atr'],tight_width=spec['tight_width'])
                actual=integration.play(spec,ready,columns,config,gate_valid=valid)
                proof=inspect(spec,ready,columns,config,actual)
                if spec['exit_id']=='E00':
                    prior=integration.reference.play(spec,ready,columns,config,gate_valid=valid)
                    assert integration.reference.old.fingerprints(actual[0])==integration.reference.old.fingerprints(prior[0])
                    old_matches+=1
                # ----------------------------------------
                # 新設した価格線とゲートを、現在までの入力だけから毎回再生成する。
                for cut in (10,13,20):
                    clipped=integration.reference.causal.clipped(ready,cut)
                    early=integration.play(spec,clipped,tuple(x[:cut].copy() for x in columns),config,gate_valid=valid[:cut])
                    integration.reference.gate_prefix(actual,early,cut)
                    future=integration.reference.causal.clipped(ready,len(ready['last']))
                    future['last'][cut:]+=100.
                    future['atr'][cut:]*=3.
                    altered=[x.copy() for x in columns]
                    for i in (0,1,3,6):altered[i][cut:]*=-1
                    changed=integration.play(spec,future,tuple(altered),config,gate_valid=valid)
                    integration.reference.gate_prefix(actual,changed,cut)
                center=300.
                mirrored=dict(ready,last=center-ready['last'])
                opposite=tuple(-x if i in (0,1,3,6) else x.copy() for i,x in enumerate(columns))
                reflection=integration.play(spec,mirrored,opposite,config,gate_valid=valid)
                inspect(spec,mirrored,opposite,config,reflection)
                integration.reference.causal.reflected_result(actual[0],reflection[0],center,True)
                integration.reference.causal.reflected_result(actual[0]['shadow'],reflection[0]['shadow'],center,False)
                rows.append(dict(id=spec['id'],symbol=symbol,同秒=tie,**proof,接頭部3=True,未来変更3=True,上下反射=True))
                if spec['id']=='F50__E10' and symbol=='TOPIX' and not tie:retained=spec,ready,columns,config,actual
    assert retained is not None
    negative=reject(*retained)
    files=set()
    for module in tuple(sys.modules.values()):
        source=getattr(module,'__file__',None)
        if source:
            path=Path(source).resolve()
            if path.is_relative_to(ROOT/'work') and path.suffix=='.py':files.add(path)
    files.add(Path(__file__))
    build=json.loads((HERE/'integration_audit_build.json').read_text(encoding='utf-8'))
    for name,sha in build['新旧SHA256'].items():assert digest(ROOT/name)==sha,name
    return dict(全合格=True,全条件数=12,人工入力数=len(rows),旧E00全15配列一致数=old_matches,
        接頭部検査数=len(rows)*3,未来改変検査数=len(rows)*3,上下反射検査数=len(rows),
        破損拒否数=len(negative),拒否=negative,結果=rows,監査生成SHA256=digest(HERE/'integration_audit_build.json'),
        参照資料SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in sorted(files)},
        新Night使用=False,実相場再生=False,API取得数=0)


if __name__=='__main__':
    value=run();(HERE/'check_exit_integration_independent.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"同期統合の独立人工{value['人工入力数']}・破損{value['破損拒否数']}合格",flush=True)
