"""全反転台帳を注文ごとに独立会計し、元成行台帳との恒等式も照合する。"""

import argparse
from context import *
from independent import account,compare,aggregate


def run(stage: str, expected: int) -> dict:
    """機能: 保存済み段階の全口座と期間集計を再計算する。

    引数: stage(str)、expected(int)。返り値: 監査結果(dict)。
    """
    fixed = load(WORK/'事前固定.json')
    paths = sorted((WORK/stage/'results').glob('*.json'))
    assert len(paths)==expected,(len(paths),expected)
    material = research.previous.material()
    old_paths = {p['config']['id']:ROOT/p['path'] for p in fixed['parents']}
    totals = dict(条件数=0,口座数=0,注文数=0,決済数=0,会計照合項目=0,期間照合数=0,
                  成行恒等式口座数=0,成行恒等式決済数=0,元前半完全一致口座数=0,全再生一致口座数=0)
    hashes={};identities={}
    for path in paths:
        packet = load(path); c=packet['config']; delay=c['latency']
        ledgerpath = WORK/stage/'ledgers'/f'{c["id"]}.pkl'
        assert digest(ledgerpath)==packet['ledger_SHA256']
        saved=load(ledgerpath);bykey={(r['session'],r['symbol']):r for r in packet['rows']}
        assert set(saved)==set(bykey)
        parent=None
        if stage=='first' or (c['polarity']==1 and delay==5):
            p=old_paths[c['parent_id']]
            parent=load(p.parent.parent/'ledgers'/f'{c["parent_id"]}.pkl')
        elif c['polarity']==-1 and c['entry_mode']==0 and stage.startswith('final/'):
            parent=load(WORK/stage/'ledgers'/f'F__{c["parent_id"]}.pkl')
        rows=[];durations={};ids=[]
        for key in sorted(saved):
            args=research.arguments(c,key,material,delay)
            if stage=='quality3':
                rerun=engine.simulate(*args)
                for part,name in [(0,'orders'),(1,'trades'),(3,'stats'),(4,'events')]:
                    np.testing.assert_array_equal(rerun[part],saved[key][name])
                assert hashlib.sha256(rerun[2].tobytes()).hexdigest()==saved[key]['curve_hash']
                totals['全再生一致口座数']+=1
            actual,curve=account(key,args,saved[key])
            totals['会計照合項目']+=compare(actual,bykey[key]);rows.append(actual)
            t=saved[key]['trades'];durations[key]=args[0][t[:,2].astype(int)]-args[0][t[:,1].astype(int)]
            if c['polarity']==-1 and c['entry_mode']==0 and parent is not None:
                if stage=='first':
                    forward_args=research.arguments(dict(c,polarity=1),key,material,delay)
                else:
                    forward_args=list(args)
                    for i in (7,26,32,33):forward_args[i]=-forward_args[i]
                report=mirrored(parent[key],saved[key],forward_args)
                ids.append(dict(session=key[0],symbol=key[1],**report))
                totals['成行恒等式口座数']+=1;totals['成行恒等式決済数']+=len(t)
            if c['polarity']==1 and delay==5 and key in parent:
                for name in ['orders','trades','stats','events']:
                    np.testing.assert_array_equal(parent[key][name],saved[key][name])
                assert parent[key]['curve_hash']==saved[key]['curve_hash']
                totals['元前半完全一致口座数']+=1
            totals['口座数']+=1;totals['注文数']+=len(saved[key]['orders']);totals['決済数']+=len(t)
        target=[s for s in fixed['全30'] if any(r['session']==s for r in rows)]
        for name,sessions in [('対象',target),('前16',fixed['前16']),('後14',fixed['後14'])]:
            for symbol in ['TOPIX','NK225']:
                actual=aggregate(rows,symbol,sessions)
                pieces=[v for k,v in durations.items() if k[1]==symbol and k[0] in sessions]
                holds=np.concatenate(pieces) if pieces else np.zeros(0)
                actual.update(hold_median=float(np.median(holds)) if len(holds) else None,
                              hold_max=float(holds.max()) if len(holds) else None)
                totals['会計照合項目']+=compare(actual,packet['periods'][name][symbol]);totals['期間照合数']+=1
        hashes[path.name]=digest(path);identities[c['id']]=ids;totals['条件数']+=1
        if totals['条件数']%16==0 or totals['条件数']==len(paths):
            print(f'独立会計 {stage} {totals["条件数"]}/{len(paths)}、{totals["口座数"]}口座',flush=True)
    result=dict(合格=True,段階=stage,**totals,全行清算時価SHA一致口座数=totals['口座数'],
        事前固定SHA256=digest(WORK/'事前固定.json'),結果SHA256=hashes,
        旧エンジンSHA256=digest(OLD/'engine.py'),主会計SHA256=digest(OLD/'accounting.py'),
        成行恒等式の各口座=identities)
    save(stage.replace('/','_')+'の全口座独立会計監査.json',result)
    return {k:v for k,v in result.items() if k not in ['結果SHA256','成行恒等式の各口座']}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--stage',required=True);parser.add_argument('--count',type=int,required=True)
    args=parser.parse_args();print(json.dumps(run(args.stage,args.count),ensure_ascii=False))
