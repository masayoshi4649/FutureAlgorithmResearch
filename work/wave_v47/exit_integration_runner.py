"""旧13場だけで、同じ初回と再新規時計を維持した12方式を全件検査する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np

import exit_integration as integration
import integration_accounting_audit as audit

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
DESTINATION=HERE/'exit_integration'
FIXED=HERE/'exit_integration_fixed.json'
reference=integration.reference
read=reference.read
digest=reference.digest
verify=reference.verify
PANEL={}


def save(path: Path, value: object) -> None:
    """機能: 旧成果を上書きせず、今回の有限JSONを原子的に保存する。

    引数: path(Path)、value(object)。返り値: なし。圧縮時刻は固定する。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf8')
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_bytes(gzip.compress(raw,mtime=0) if path.suffix=='.gz' else raw)
    tmp.replace(path)


def freeze() -> dict:
    """機能: 12方式・実装・独立人工監査・旧入力を経済再生より先に固定する。

    引数: なし。返り値: 固定記録(dict)。既存の異なる固定は拒否する。
    """
    synthetic=read(HERE/'check_exit_integration.json')
    independent=read(HERE/'integration_accounting_fixed.json')
    assert synthetic['全合格'] and synthetic['人工入力数']==48
    assert independent['全合格'] and independent['人工入力数']==48
    verify(synthetic['参照資料SHA256']);verify(independent['SHA256'])
    refs=dict(reference.read(HERE.parent/'wave_v44/探索条件の固定.json')['参照資料SHA256'])
    refs.update(independent['SHA256']);refs.update(synthetic['参照資料SHA256'])
    names=['exit_integration_runner.py','exit_integration.py','exit_shadow_integrated.py','exit_partial_integrated.py',
        'exit_integrated_build.json','check_exit_integration.py','check_exit_integration.json',
        'integration_accounting_fixed.json','check_exit_integration_independent.json',
        'exit_fixed.json','exit_campaign_results.json.gz','check_exit_results.json']
    sources=[HERE/name for name in names]
    sources.append(HERE.parent/'wave_v44/探索条件の固定.json')
    sources.extend(HERE.parent/'wave_v45/ledgers'/(s+'.json.gz') for s in
        ('A0__V000','G000_F25_N1__V000','G150_F50_N1__V000'))
    refs.update({p.relative_to(ROOT).as_posix():digest(p) for p in sources})
    verify(refs)
    value=dict(conditions=integration.catalog(),規則={
        '期間':'既知13セッション26入力のみ。新9月29日ナイトは未読。',
        '影':'旧A0の運転は独立。元fresh準備行だけ、短縮影へ新規準備を許可。',
        '減量ゲート':'順行1.5ATRは通常影の当行までの計画で判定する。',
        '出口':'E00は元幅3、E10/E11は3ATR順行後に幅1.5/.75へ短縮。既設線を緩めない。',
        '因果検査':'全312入力でprefix37%、同時刻近傍73%以降未来改変、売買反射。影から毎回再生成。',
        '旧一致':'E00のA0/C01/F50は旧保存15配列指紋。復元なしE00は旧修正版再生との全配列。',
        '独立出口一致':'無調整E00/E10/E11の全組返済は同一初回の既出口実験と一致。',
        '口座':'実口座は初回同期の単一口座。独立実験の重複建玉を合算しない。',
        '採否':'12条件を全件表示。新Nightの結果を旧方式選定に使用しない。'},
        参照資料SHA256=refs)
    if FIXED.exists():assert read(FIXED)==value,'固定条件の書換えは禁止'
    else:save(FIXED,value)
    print('同期統合12条件を旧入力だけに固定しました。',flush=True)
    return value


def initialize() -> None:
    """機能: 旧26入力と凍結した独立出口の保存結果を読む。

    引数: なし。返り値: なし。新Nightを含むv47別入力へ接続しない。
    """
    global PANEL
    integration.initialize()
    PANEL={(r['id'],r['session'],r['symbol'],int(r['campaign'])):r
        for r in read(HERE/'exit_campaign_results.json.gz') if r['id'] in ('E00','E10','E11')}
    assert len(PANEL)==306


def panel_check(spec: dict, key: tuple, result: dict) -> int:
    """機能: 無調整の全返済脚を、独立した元組内出口実験へ対応させる。

    引数: spec/result(dict)、key(tuple)。返り値: 完全一致した組数(int)。
    初回台帳も比較する。脚番号だけを組内0へ正規化し、価格・数量・理由は変えない。
    """
    if spec['quantity_id']!='A0':return 0
    count=0
    for cycle in result['cycles']:
        cid=int(cycle[0]);expected=PANEL[(spec['exit_id'],*key,cid)]
        trades=result['trades'][result['trades'][:,0]==cid].copy()
        trades[:,1]=0
        orders=result['orders'][result['orders'][:,2]==cid]
        np.testing.assert_array_equal(trades,np.asarray(expected['trades'],float).reshape(-1,11))
        np.testing.assert_array_equal(orders,np.asarray(expected['orders'],float).reshape(-1,8))
        assert int(cycle[2])==expected['exit_row']
        assert abs(float(cycle[3])*reference.old.base.research.MULT[key[1]]-expected['net_yen'])<1e-6
        count+=1
    assert count==sum(k[0]==spec['exit_id'] and k[1:3]==key for k in PANEL)
    return count


def evaluate(spec: dict) -> dict:
    """機能: 26入力を再生し、独立全行会計・旧同値・全入力因果と期間値を保存する。

    引数: spec(dict)。返り値: 完了と指紋(dict)。失敗した条件を除外しない。
    """
    identifier=spec['id'];started=time.perf_counter()
    rows=[];series={};ledgers=[];proofs=[];causality=[];usages=[];waves=[]
    old_ledger={}
    if spec['exit_id']=='E00' and spec['reference_id']:
        old_ledger={(r['session'],r['symbol']):r for r in read(
            HERE.parent/'wave_v45/ledgers'/(spec['reference_id']+'.json.gz'))}
    for key,ready in sorted(integration.INPUTS.items()):
        columns=integration.columns_for(spec,key);valid=integration.quality_for(spec,key)
        config=integration.config_for(spec,ready)
        actual=integration.play(spec,ready,columns,config,gate_valid=valid)
        result,effective,evidence=actual
        identity=integration.initial_identity(result)
        row,curves,proof,basic=audit.inspect(spec,ready,result,config,effective)
        assert all(proof[name] is True for name in reference.PROOF_FLAGS)
        assert proof['原本行数']==len(ready['last'])
        other=reference.old.session_row(identifier,ready,result,config,effective[1],basic,curves)
        audit.statistics.equal(row,other,'二経路の全統計')
        fingerprints=reference.old.fingerprints(result)
        legacy=False
        if old_ledger:
            assert fingerprints==old_ledger[key]['result_fingerprints'],(identifier,key,'旧保存全15配列')
            legacy=True
        elif spec['exit_id']=='E00':
            old=reference.play(spec,ready,columns,dict(config,tighten_atr=0.,tight_width=1.),gate_valid=valid)
            for field in integration.FIELDS:np.testing.assert_array_equal(result[field],old[0][field],err_msg=field)
            del old;legacy=True
        panel_count=panel_check(spec,key,result)
        rows.append(row);series[key]=curves['equity']
        usage=reference.gate_record(spec,ready,columns,effective,evidence,valid,
            dict(result,shadow=result['shadow']['scheduler']))
        usages.append(usage)
        ledgers.append(dict(session=key[0],symbol=key[1],config=config,
            **{field:result[field].tolist() for field in integration.STORED},
            result_fingerprints=fingerprints,
            shadow_fingerprints=reference.old.fingerprints(result['shadow'],reference.reference.EXPECTED_SHADOW_FIELDS),
            scheduler_fingerprints=reference.old.fingerprints(result['shadow']['scheduler'],reference.reference.EXPECTED_SHADOW_FIELDS),
            shadow_cycles=result['shadow']['cycles'].tolist(),shadow_orders=result['shadow']['orders'].tolist(),
            scheduler_cycles=result['shadow']['scheduler']['cycles'].tolist(),scheduler_orders=result['shadow']['scheduler']['orders'].tolist(),
            scheduler_prepare_events=result['shadow']['scheduler']['prepare_events'].tolist(),
            prepare_allow_SHA256=hashlib.sha256(result['shadow']['schedule_prepare_allow'].tobytes()).hexdigest(),
            gate_fingerprints=usage['fingerprints'],arm_events=usage['arm_events']))
        proofs.append(dict(session=key[0],symbol=key[1],**proof,**identity,
            全統計一致=True,E00旧完全一致=legacy,独立出口一致組数=panel_count,
            時価SHA256=hashlib.sha256(curves['equity'].tobytes()).hexdigest()))
        causality.append(dict(session=key[0],symbol=key[1],
            **integration.causal_check(spec,ready,columns,config,actual,valid)))
        for wave in reference.old.FIXED['指定波']:
            if wave['session']!=key[0]:continue
            records=reference.old.base.wave_metrics.order_records(ready,columns[0],result,integration.engine.REASONS)
            waves.append(reference.old.base.wave_metrics.episode_metrics(
                dict(id=identifier,manager=reference.old.FIXED['manager']),wave,ready,columns[0],result,records,config['point_value']))
        del result,actual,curves,evidence,effective
    assert len(rows)==len(ledgers)==len(proofs)==len(causality)==26 and len(waves)==8
    periods={}
    for label,names in [('all_symbols',reference.old.FIXED['全セッション']),
                        ('symbols',reference.old.FIXED['後半7セッション']),
                        ('first_symbols',reference.old.FIXED['全セッション'][:6])]:
        periods[label]={s:audit.statistics.period(rows,series,names,s,reference.old.base.research.MULT[s]) for s in reference.old.SYMBOLS}
        audit.statistics.equal(periods[label],reference.old.period(rows,names),'期間独立統計')
    summary=dict(id=identifier,spec=spec,**periods,wave_passes=sum(r['正方向ネット20分目安達成'] for r in waves),
        全26全行独立会計一致=True,全初回同期=True,全因果入力数=26,
        E00旧一致入力数=26 if spec['exit_id']=='E00' else 0,
        独立出口一致組数=sum(r['独立出口一致組数'] for r in proofs),
        全原本行会計数=sum(len(r['last']) for r in integration.INPUTS.values()),
        固定SHA256=digest(FIXED),新Night使用=False)
    paths=[]
    for folder,payload,suffix in [('sessions',rows,'.json.gz'),('ledgers',ledgers,'.json.gz'),
        ('audits',proofs,'.json.gz'),('causality',causality,'.json'),('gate_use',usages,'.json'),
        ('waves',waves,'.json.gz'),('summaries',summary,'.json')]:
        path=DESTINATION/folder/(identifier+suffix);save(path,payload);paths.append(path)
    done=dict(id=identifier,全合格=True,全入力数=26,因果入力数=26,
        全原本行会計数=summary['全原本行会計数'],E00旧一致入力数=summary['E00旧一致入力数'],
        独立出口一致組数=summary['独立出口一致組数'],固定SHA256=digest(FIXED),
        出力SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in paths},経過秒=time.perf_counter()-started)
    save(DESTINATION/'completed'/(identifier+'.json'),done)
    return done


def complete() -> dict:
    """機能: 12条件すべての実体・指紋・監査数を結合し、完備だけを宣言する。

    引数: なし。返り値: 完備記録(dict)。経済の好悪を合否条件へ加えない。
    """
    fixed=read(FIXED);verify(fixed['参照資料SHA256'])
    done=[read(DESTINATION/'completed'/(s['id']+'.json')) for s in fixed['conditions']]
    values=[read(DESTINATION/'summaries'/(s['id']+'.json')) for s in fixed['conditions']]
    assert len(done)==len({r['id'] for r in done})==12
    for spec,d,v in zip(fixed['conditions'],done,values):
        assert d['全合格'] and d['id']==spec['id']==v['id'] and v['spec']==spec
        assert d['固定SHA256']==v['固定SHA256']==digest(FIXED)
        assert d['全入力数']==d['因果入力数']==26
        verify(d['出力SHA256'])
    assert sum(d['E00旧一致入力数'] for d in done)==104
    assert sum(d['独立出口一致組数'] for d in done)==306
    save(HERE/'exit_integration_results.json',dict(conditions=values,固定SHA256=digest(FIXED),既知13のみ=True))
    outputs={k:v for d in done for k,v in d['出力SHA256'].items()}
    sources=[DESTINATION/'completed'/(s['id']+'.json') for s in fixed['conditions']]+[HERE/'exit_integration_results.json',FIXED]
    outputs.update({p.relative_to(ROOT).as_posix():digest(p) for p in sources})
    verify(fixed['参照資料SHA256']);verify(outputs)
    result=dict(全合格=True,全条件数=12,全入力数=312,全因果入力数=312,
        E00旧一致入力数=104,独立出口一致組数=306,指定波数=96,
        全原本行会計数=sum(d['全原本行会計数'] for d in done),
        新Night使用=False,API取得数=0,固定SHA256=digest(FIXED),
        参照資料SHA256=fixed['参照資料SHA256'],出力SHA256=outputs)
    save(HERE/'exit_integration_complete.json',result)
    print('同期統合12条件・312入力が全会計と因果検査を通過。',flush=True)
    return result


def main() -> None:
    """機能: 事前固定・再開可能な全条件実行・完備結合を順に行う。

    引数: CLI prepare/complete(bool)、workers(int)。返り値: なし。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--complete',action='store_true');parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args()
    if args.prepare:freeze();return
    if args.complete:complete();return
    fixed=read(FIXED);assert fixed['conditions']==integration.catalog();verify(fixed['参照資料SHA256'])
    pending=[]
    for spec in fixed['conditions']:
        target=DESTINATION/'completed'/(spec['id']+'.json')
        if target.exists():
            done=read(target);assert done['全合格'] and done['固定SHA256']==digest(FIXED);verify(done['出力SHA256'])
        else:pending.append(spec)
    with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize) as pool:
        futures={pool.submit(evaluate,s):s['id'] for s in pending}
        for number,future in enumerate(as_completed(futures),1):
            future.result();print(f'{number}/{len(pending)} {futures[future]} 完了',flush=True)
    complete()


if __name__=='__main__':main()
