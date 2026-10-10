"""全162条件と固定感度の注文を独立再計算し、前半選定を再現する。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from account_parts import HERE, ROOT, row_account, aggregate, same_fields
from independent_account import save


sys.path.insert(0,str(HERE.parent))
spec=importlib.util.spec_from_file_location('wave78_independent_study',HERE.parent/'study.py')
study=importlib.util.module_from_spec(spec);sys.modules[spec.name]=study;spec.loader.exec_module(study)


def audit_one(job: tuple, materials: dict, fixed: dict) -> tuple:
    """機能: 一条件の全60口座・全曲線と期間指標を別会計へ照合する。

    引数: job(tuple)、materials/fixed(dict)。返り値: 識別、独立前半会計、件数(tuple)。
    """
    delay,config,area=job;ident=config['id'];path=area/'ledgers'/f'{ident}.pkl'
    packet=study.load(area/'results'/f'{ident}.json');ledgers=study.load(path)
    assert packet['config']==dict(config,delay=delay)
    assert packet['ledger_SHA256']==study.digest(path)
    ready=materials[delay][0];assert set(ledgers)==set(ready)
    saved={(r['session'],r['symbol']):r for r in packet['rows']};assert set(saved)==set(ready)
    rows=[];front=hashlib.sha256();counts=dict(口座数=0,全注文数=0,全決済数=0,比較項目数=0,期間会計数=0,判断約定最大秒=0.)
    for key in sorted(ready):
        args=study.arguments(config,key,*materials[delay])
        row=row_account(key,args,ledgers[key],ready[key]);rows.append(row)
        counts['比較項目数']+=same_fields(row,saved[key],(delay,ident,key))
        counts['口座数']+=1;counts['全注文数']+=len(ledgers[key]['orders']);counts['全決済数']+=row['trades']
        counts['判断約定最大秒']=max(counts['判断約定最大秒'],row['判断約定最大秒'])
        if key[0] in fixed['前16']:
            front.update(str(key).encode('utf8'));front.update(ledgers[key]['orders'].tobytes())
    assert front.hexdigest()==packet['front_orders_SHA256']
    periods={}
    for period in ('前16','後14','全30','後13','追加1既知'):
        periods[period]={}
        for symbol in ('TOPIX','NK225'):
            actual=aggregate(rows,symbol,fixed[period]);periods[period][symbol]=actual
            counts['比較項目数']+=same_fields(actual,packet['periods'][period][symbol],(delay,ident,period,symbol))
            counts['期間会計数']+=1
    return (delay,ident),dict(config=config,periods=periods),counts


def selection_score(value: dict) -> tuple:
    """機能: 前半だけの金額比率・黒字活動場率・IDを独立に順位付けする。

    引数: value(dict)。返り値: 昇順順位(tuple)。
    """
    own=list(value['periods']['前16'].values())
    loss=[r['loss']/(r['profit']+r['loss']) if r['profit']+r['loss'] else 1. for r in own]
    red=[1-r['winning_sessions']/r['active_sessions'] if r['active_sessions'] else 1. for r in own]
    return max(loss),max(red),sum(loss),value['config']['id']


def main() -> None:
    """機能: 固定済み全会計を6並列で検算し、代表の後半差替えがないことを確認する。

    引数: なし。返り値: なし(None)。エンジンによる新規損益探索は実行しない。
    """
    fixed=study.load(HERE.parent/'事前固定.json');selected=study.load(HERE.parent/'前半選定.json')
    assert len(fixed['条件'])==162 and all(study.digest(ROOT/p)==h for p,h in fixed['SHA256'].items())
    catalog={c['id']:c for c in fixed['条件']};materials={d:study.material(d) for d in (5,1,15)}
    jobs=[]
    for delay,ids in ((5,list(catalog)),(1,selected['感度対象']),(15,selected['感度対象'])):
        area=study.base_path(delay)
        assert {p.stem for p in (area/'results').glob('*.json')}==set(ids)
        jobs.extend((delay,catalog[ident],area) for ident in ids)
    totals=dict(口座数=0,全注文数=0,全決済数=0,比較項目数=0,期間会計数=0,判断約定最大秒=0.);independent={}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(audit_one,job,materials,fixed) for job in jobs]
        for index,future in enumerate(as_completed(futures),1):
            key,value,counts=future.result();independent[key]=value
            for field,number in counts.items():
                totals[field]=max(totals[field],number) if field.endswith('最大秒') else totals[field]+number
            if index%12==0 or index==len(jobs):print(f'独立全会計 {index}/{len(jobs)}',flush=True)
    picks=[]
    for entry in ('J0','J1','J2'):
        pool=[v for (delay,_),v in independent.items() if delay==5 and v['config']['entry']==entry]
        active=[v for v in pool if all(r['trades']>=20 and r['active_sessions']>=8 for r in v['periods']['前16'].values())]
        positive=[v for v in active if all(r['net']>0 for r in v['periods']['前16'].values())]
        good=[v for v in positive if all(r['payoff'] is not None and r['payoff']>1 for r in v['periods']['前16'].values())]
        level=0 if good else 1 if positive else 2 if active else 3
        best=min(good or positive or active or pool,key=selection_score)
        chosen=next(r for r in selected['代表'] if r['entry']==entry)
        assert chosen['id']==best['config']['id'] and chosen['level']==level
        assert tuple(chosen['score'])==selection_score(best)
        picks.append(dict(id=chosen['id'],level=level,score=selection_score(best)))
    primary=min(picks,key=lambda r:(r['level'],*r['score']))['id'];assert primary==selected['主候補']
    assert all(study.digest(ROOT/p)==h for p,h in fixed['SHA256'].items())
    proof=dict(合格=True,主条件数=162,感度条件数=len(jobs)-162,条件数=len(jobs),**totals,
        全行清算時価照合数=totals['口座数'],前半独立選定=picks,主候補=primary,
        前半だけで選定=True,全30場は既知=True,全明細損失を計上=True,
        engine_SHA256=study.digest(HERE.parent/'engine.py'),固定SHA256=study.digest(HERE.parent/'事前固定.json'),
        選定SHA256=study.digest(HERE.parent/'前半選定.json'),
        限界='保存気配を用いた次行約定と整数手数料の独立検算。ミニ自身の流動性と真の受信時計は保証しない。',
        新損益探索=0,API取得=0,実注文=0)
    save(HERE/'全162条件と固定感度の独立会計監査.json',proof)
    print(json.dumps(proof,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
