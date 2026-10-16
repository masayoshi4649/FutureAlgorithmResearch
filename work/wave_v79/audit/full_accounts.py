"""防止18案・3遅延の全会計を独立計算し、基準と固定した診断集合を照合する。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util
import json
import sys

import numpy as np

from account_parts import HERE, ROOT, row_account, aggregate, same_fields
from independent_account import save


sys.dont_write_bytecode=True
sys.path.insert(0,str(HERE.parent))
spec=importlib.util.spec_from_file_location('防止策79の独立検算接続',HERE.parent/'experiment.py')
study=importlib.util.module_from_spec(spec);sys.modules[spec.name]=study;spec.loader.exec_module(study)


def scopes(fixed: dict, symbol: str) -> dict:
    """機能: 基準で固定した損失集合とその補集合を独立列挙する。

    引数: fixed(dict)、symbol(str)。返り値: 期間辞書(dict)。
    """
    worst=fixed['商品別赤字上位3'][symbol];union=set(sum(fixed['商品別赤字上位3'].values(),[]))
    return {'全30':fixed['全30'],'赤字上位3':worst,'残り27':[s for s in fixed['全30'] if s not in worst],
        '対象外25':[s for s in fixed['全30'] if s not in union], '前16':fixed['全30'][:16],'後14':fixed['全30'][16:]}


def audit_one(job: tuple, materials: dict, fixed: dict) -> dict:
    """機能: 一設定の全注文と清算時価、商品別六期間を独立会計する。

    引数: job(tuple)、materials/fixed(dict)。返り値: 検査計数(dict)。
    """
    delay,config=job;area=study.output_base(delay);ident=config['id']
    packet=study.load(area/'results'/f'{ident}.json');path=area/'ledgers'/f'{ident}.pkl';ledgers=study.load(path)
    assert packet['config']==dict(config,delay=delay) and packet['ledger_SHA256']==study.digest(path)
    ready=materials[delay][0];assert set(ledgers)==set(ready)
    saved={(r['session'],r['symbol']):r for r in packet['rows']};assert set(saved)==set(ready)
    counts=dict(口座数=0,全注文数=0,全決済数=0,比較項目数=0,期間会計数=0,基準完全一致口座数=0,判断約定最大秒=0.);rows=[]
    if ident=='E0_X0':
        oldbase=ROOT/'work/wave_v78' if delay==5 else ROOT/f'work/wave_v78/sensitivity/delay{delay}'
        old=study.load(oldbase/'ledgers/J2_F0_B0_H0_R0.pkl')
    for key in sorted(ready):
        args=study.arguments(config,key,*materials[delay]);ledger=ledgers[key]
        row=row_account(key,args,ledger,ready[key]);rows.append(row)
        counts['比較項目数']+=same_fields(row,saved[key],(delay,ident,key))
        counts['口座数']+=1;counts['全注文数']+=len(ledger['orders']);counts['全決済数']+=row['trades']
        counts['判断約定最大秒']=max(counts['判断約定最大秒'],row['判断約定最大秒'])
        assert len(ledger['events'])==0,'新防止策に数量変更・休止・延長・保護は含めない'
        if ident=='E0_X0':
            for name in ('orders','trades','stats','events'):np.testing.assert_array_equal(ledger[name],old[key][name])
            assert ledger['curve_hash']==old[key]['curve_hash'];counts['基準完全一致口座数']+=1
    for symbol in ('TOPIX','NK225'):
        for period,sessions in scopes(fixed,symbol).items():
            actual=aggregate(rows,symbol,sessions)
            counts['比較項目数']+=same_fields(actual,packet['periods'][period][symbol],(delay,ident,period,symbol));counts['期間会計数']+=1
    return counts


def main() -> None:
    """機能: 54条件・3240口座を独立計算し、基準完全一致と各期間の損益を検査する。

    引数: なし。返り値: なし(None)。新設定・候補選定・損益探索は行わない。
    """
    fixed=study.load(HERE.parent/'事前固定.json');assert len(fixed['条件'])==18
    assert all(study.digest(ROOT/p)==h for p,h in fixed['SHA256'].items())
    baseline=study.load(ROOT/'work/wave_v78/results/J2_F0_B0_H0_R0.json')
    for symbol in ('TOPIX','NK225'):
        worst=sorted((r for r in baseline['rows'] if r['symbol']==symbol),key=lambda r:(r['net'],r['session']))[:3]
        assert [r['session'] for r in worst]==fixed['商品別赤字上位3'][symbol]
        assert len(scopes(fixed,symbol)['残り27'])==27 and len(scopes(fixed,symbol)['対象外25'])==25
    for name in ('engine.py','accounting.py','signals.py'):
        assert study.digest(HERE.parent/name)==study.digest(ROOT/'work/wave_v78'/name)
    materials={d:study.material(d) for d in (5,1,15)};jobs=[]
    for delay in (5,1,15):
        assert {p.stem for p in (study.output_base(delay)/'results').glob('*.json')}=={c['id'] for c in fixed['条件']}
        jobs.extend((delay,c) for c in fixed['条件'])
    totals=dict(口座数=0,全注文数=0,全決済数=0,比較項目数=0,期間会計数=0,基準完全一致口座数=0,判断約定最大秒=0.)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(audit_one,job,materials,fixed) for job in jobs]
        for index,future in enumerate(as_completed(futures),1):
            counts=future.result()
            for key,value in counts.items():totals[key]=max(totals[key],value) if key.endswith('最大秒') else totals[key]+value
            if index%6==0 or index==len(jobs):print(f'防止案の独立全会計 {index}/{len(jobs)}',flush=True)
    assert all(study.digest(ROOT/p)==h for p,h in fixed['SHA256'].items())
    proof=dict(合格=True,設定数=18,遅延数=3,条件数=54,**totals,全行清算時価照合数=totals['口座数'],
        対象集合は基準で固定=True,商品別残27と共通残25を分離=True,全30は既知=True,
        固定SHA256=study.digest(HERE.parent/'事前固定.json'),
        実装SHA256={name:study.digest(HERE.parent/name) for name in ('experiment.py','prevention.py','engine.py','accounting.py')},
        独立監査の対象='全明細の費用後利益損失・全玉清算時価・最大下落・注文上限・次有効気配・場別と全期間・基準全配列。',
        新設定損益探索=0,API取得=0,実注文=0)
    save(HERE/'全18防止策と3遅延の独立会計監査.json',proof)
    print(json.dumps(proof,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
