"""原版合格の証拠と、状態不適合を残す全経済診断の証拠を別出力へ結合する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path

import numpy as np
import adaptive_accounting_diagnostic_core as core

runner=core.runner
HERE=core.HERE
ROOT=core.ROOT


def selftest() -> dict:
    """機能: 状態差を合格へ隠さないことと、他の破損が従来通り停止することを確かめる。

    引数: なし。返り値: 人工検査の証跡 (dict)。新しい実相場は再生しない。
    """
    core.initialize()
    control=np.zeros((4,20));expected=np.zeros(4);budget=np.zeros(4,bool);times=np.arange(4,dtype=float)
    proof=core.slots.phase_diagnostic(control,expected,budget,times)
    assert proof['状態契約合格'] and proof['状態不一致行数']==0
    count=1;reject=0
    for actual,target in ((1,0),(3,2)):
        c=control.copy();e=expected.copy();b=budget.copy()
        c[1,2]=actual;e[1]=target;c[1,13]=1;b[1]=True
        result=core.slots.phase_diagnostic(c,e,b,times)
        assert not result['状態契約合格'] and result['既知残存型に限定'] and result['状態不一致行数']==1
        count+=1
        for changed in ('予算なし','予約残存','異なるphase'):
            cc=c.copy();bb=b.copy()
            if changed=='予算なし':bb[1]=False
            if changed=='予約残存':cc[1,8]=-1
            if changed=='異なるphase':cc[1,2]=4
            result=core.slots.phase_diagnostic(cc,e,bb,times)
            assert not result['状態契約合格'] and not result['既知残存型に限定']
            count+=1
    for value in (np.nan,np.inf):
        c=control.copy();c[1,2]=value
        try:core.slots.phase_diagnostic(c,expected,budget,times)
        except AssertionError:reject+=1
        else:raise AssertionError('非有限状態の受理')
    import adaptive_statistics_selftest as fixture
    spec=next(s for s in runner.FIXED['conditions'] if s['primary'])
    ready,columns,config=fixture.artificial(spec,'TOPIX',False)
    result=fixture.play(spec,ready,columns,config)
    row,curves,proof,basic=core.inspect(spec,ready,result,config,columns)
    assert proof['状態契約合格'];count+=1
    abnormal=deepcopy(result);abnormal['control_curve'][0,2]=4
    row,curves,proof,basic=core.inspect(spec,ready,abnormal,config,columns)
    assert not proof['状態契約合格'] and not proof['既知残存型に限定'];count+=1
    for name,index in (('orders',(0,4)),('slot_curve',(2,0)),('control_curve',(2,5))):
        bad=deepcopy(result);bad[name][index]+=99
        try:core.inspect(spec,ready,bad,config,columns)
        except (AssertionError,IndexError,KeyError,ValueError):reject+=1
        else:raise AssertionError('phase以外の破損受理:'+name)
    return dict(全合格=True,状態分離の人工数=count,非状態破損又は非有限拒否数=reject,
        原状態差を合格化しない=True,未知状態差も全列挙=True,経済破損は停止=True,
        新実相場損益=False,API取得数=0,現在保存物使用=False)


def prepare() -> dict:
    """機能: 診断用の最小差分と原版参照を結果後の診断仕様として固定する。

    引数: なし。返り値: 診断固定 (dict)。探索前固定と偽らない。
    """
    path=HERE/'adaptive_accounting_diagnostic_fixed.json'
    if path.exists():
        fixed=runner.read(path)
        for relative,sha in fixed['参照SHA256'].items():assert runner.digest(ROOT/relative)==sha,relative
        return fixed
    build=runner.read(HERE/'adaptive_phase_diagnostic_build.json')
    assert build['全合格'] and build['逆置換AST一致'] and build['原assert全文全順序一致']
    assert build['全口座会計の逆置換全文AST一致']
    for relative,sha in build['参照SHA256'].items():assert runner.digest(ROOT/relative)==sha,relative
    test=selftest();runner.save(HERE/'adaptive_accounting_diagnostic_selftest.json',test)
    original=runner.read(HERE/'adaptive_accounting_fixed.json')
    refs=dict(original['参照SHA256']);refs.update(build['参照SHA256'])
    for name in ('adaptive_accounting_diagnostic.py','adaptive_accounting_diagnostic_selftest.json',
            'adaptive_phase_diagnostic_build.json','adaptive_accounting_fixed.json'):
        p=HERE/name;refs[p.relative_to(ROOT).as_posix()]=runner.digest(p)
    fixed=dict(診断専用=True,既知状態不適合の後の固定=True,探索前固定ではない=True,
        主対象=original['主対象'],補助対象=original['補助対象'],主条件数=206,補助条件数=768,
        原監査固定SHA256=runner.digest(HERE/'adaptive_accounting_fixed.json'),
        規則='phase比較だけ全不一致行を記録し状態契約不合格を維持。他の全会計・注文・全統計assertは不変。原版成功証拠は状態も全一致として結合。',
        人工検査=test,参照SHA256=refs,採否規則変更=False,売買コード変更=False,
        API取得数=0,現在保存物使用=False)
    runner.save(path,fixed);return fixed


def original_certificate(spec: dict, destination: str) -> dict | None:
    """機能: 変更前監査で全26が通過した実体を、現在の保存資料へ厳密に結ぶ。

    引数: spec (dict)、destination (str)。返り値: 原版合格証拠又は不存在 (dict|None)。
    """
    base=HERE/destination;path=base/'adaptive_accounting_details'/(spec['id']+'.json.gz')
    if not path.exists():return None
    detail=runner.read(path);expected=set(runner.INPUTS)
    assert detail['spec']==spec and detail['id']==spec['id'] and detail['全監査合格'] is True
    assert detail['全入力数']==26 and detail['全原本行会計数']==sum(len(r['last']) for r in runner.INPUTS.values())
    assert detail['監査固定SHA256']==runner.digest(HERE/'adaptive_accounting_fixed.json')
    assert detail['探索固定SHA256']==runner.digest(HERE/'探索条件の固定.json')
    assert len(detail['検査'])==26 and {(r['session'],r['symbol']) for r in detail['検査']}==expected
    assert len(detail['sessions'])==26 and {(r['session'],r['symbol']) for r in detail['sessions']}==expected
    flags=('全枠会計一致','全予約と新根拠一致','元終了以前','同約定両建て全行一致','全予算予約一致',
        '全分岐独立一致','全伝達遅延一致','全保存数値一致','全台帳配列一致','分岐集計独立一致','全組R超過独立一致')
    for proof in detail['検査']:
        for flag in flags:assert proof[flag] is True,flag
        assert proof['原本行数']==len(runner.INPUTS[(proof['session'],proof['symbol'])]['last'])
    required={(base/folder/(spec['id']+suffix)).relative_to(ROOT).as_posix() for folder,suffix in (
        ('sessions','.json.gz'),('ledgers','.json.gz'),('waves','.json.gz'),('accounting','.json.gz'),('summaries','.json'))}
    assert set(detail['保存資料SHA256'])==required
    for relative,sha in detail['保存資料SHA256'].items():assert runner.digest(ROOT/relative)==sha,relative
    saved=runner.read(base/'summaries'/(spec['id']+'.json'))
    for field in ('all_symbols','symbols'):core.statistics.equal(detail[field],saved[field],field)
    core.statistics.equal(detail['sessions'],runner.read(base/'sessions'/(spec['id']+'.json.gz')),'原版合格明細')
    return dict(id=spec['id'],経済監査合格=True,状態契約合格=True,全監査合格=True,状態不一致行数=0,
        既知残存型に限定=True,全入力数=26,全原本行会計数=detail['全原本行会計数'],
        証拠種別='原版全検査合格',実体=path.relative_to(ROOT).as_posix(),実体SHA256=runner.digest(path),
        原版phase比較も全行一致=True,監査固定SHA256=detail['監査固定SHA256'])


def main() -> None:
    """機能: 原版成功と未保存条件の診断を結び、経済・状態の合否を別に保存する。

    引数: --prepare/--supplementary (bool)、--workers (int)。返り値: なし (None)。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--supplementary',action='store_true');parser.add_argument('--workers',type=int,default=8)
    args=parser.parse_args();fixed=prepare()
    if args.prepare:print('診断版固定・状態不合格と経済合格を分離',flush=True);return
    core.initialize();destination='supplementary' if args.supplementary else '';base=HERE/destination
    specs=fixed['補助対象'] if args.supplementary else fixed['主対象']
    complete=runner.read(base/'主再生の完了.json')
    assert complete['全条件数']==len(specs) and complete['全入力数']==len(specs)*26
    assert complete['探索固定SHA256']==runner.digest(HERE/'探索条件の固定.json')
    if not args.supplementary:
        ended=runner.read(HERE/'adaptive_accounting_failed_run.json')
        assert ended['監査プロセス終了'] and ended['終了コード']==1
    references={relative:runner.digest(ROOT/relative) for relative in fixed['参照SHA256']}
    records=[];missing=[]
    for spec in specs:
        original=original_certificate(spec,destination)
        if original is None:missing.append(spec)
        else:records.append(original)
    reused=len(records)
    with ProcessPoolExecutor(max_workers=args.workers,initializer=core.initialize) as executor:
        jobs={executor.submit(core.evaluate,spec,destination):spec['id'] for spec in missing}
        for future in as_completed(jobs):
            item=future.result();path=base/'adaptive_accounting_diagnostic_details'/(item['id']+'.json.gz')
            item.update(証拠種別='診断版全経済検査',実体=path.relative_to(ROOT).as_posix())
            records.append(item)
            if (len(records)-reused)%12==0 or len(records)==len(specs):
                print('診断会計',len(records),'/',len(specs),'原版再利用',reused,flush=True)
    assert len(records)==len(specs) and {r['id'] for r in records}=={s['id'] for s in specs}
    assert all(r['経済監査合格'] for r in records)
    for row in records:
        assert runner.digest(ROOT/row['実体'])==row['実体SHA256']
        references[row['実体']]=row['実体SHA256']
    assert all(runner.digest(ROOT/path)==sha for path,sha in references.items())
    result=dict(全範囲診断完了=True,経済全合格=True,状態全合格=all(r['状態契約合格'] for r in records),
        全監査合格=all(r['状態契約合格'] for r in records),対象条件数=len(specs),全入力数=len(specs)*26,
        全原本行会計数=sum(r['全原本行会計数'] for r in records),
        原版成功条件数=reused,診断版条件数=len(missing),状態不適合条件数=sum(not r['状態契約合格'] for r in records),
        状態不一致行数=sum(r['状態不一致行数'] for r in records),既知残存型に限定=all(r['既知残存型に限定'] for r in records),
        条件=sorted(records,key=lambda r:r['id']),診断固定SHA256=runner.digest(HERE/'adaptive_accounting_diagnostic_fixed.json'),
        監査固定SHA256=runner.digest(HERE/'adaptive_accounting_fixed.json'),探索固定SHA256=runner.digest(HERE/'探索条件の固定.json'),
        参照SHA256=references,診断専用=True,完全合格又は実運用可能を意味しない=True,
        API取得数=0,現在保存物使用=False)
    runner.save(base/'adaptive_accounting_diagnostic.json',result)
    print('経済全合格',result['経済全合格'],'状態全合格',result['状態全合格'],'不一致行数',result['状態不一致行数'],flush=True)


if __name__=='__main__':
    main()
