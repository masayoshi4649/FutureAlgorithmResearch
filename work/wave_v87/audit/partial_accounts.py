"""部分確保八条件の保存会計を、FIFO・枠・親組床から独立に照合する。"""

import argparse
import hashlib
import pickle
import sys
import numpy as np
from diagnose import ROOT,HERE,read,save
from boundaries import module

partial=module('監査87部分共通',HERE/'partial_checks.py')
ROUND=ROOT/'work/wave_v87/round2'


def digest(path):
    """
    機能: 保存結果の不変を示す内容指紋を得る。
    引数: path (Path)。
    返り値: str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def events(ready,ledger,config):
    """
    機能: 部分返済の正数量・共用枠・根拠順と料金込み床を保存注文から確認する。
    引数: ready/ledger/config (dict)。
    返り値: dictの照合件数。
    """
    q0=5 if ready['symbol']=='TOPIX' else 10
    limit=int(np.floor(q0*config['narrow_fraction']+1e-9))
    narrow=ledger['orders'][ledger['orders'][:,6]==73]
    floors=ledger['orders'][ledger['orders'][:,6]==74]
    ev=ledger['partial_events']
    assert len(narrow)==sum(ev[:,2]==2) and len(floors)==sum(ev[:,2]==4)
    assert np.all((narrow[:,4]>0)&(narrow[:,4]<=limit))
    assert len(set(narrow[:,2]))==len(narrow)
    for o in narrow:
        selected=ledger['slot_events'][(ledger['slot_events'][:,0]==o[0])&(ledger['slot_events'][:,2]==o[2])&(ledger['slot_events'][:,9]==73)]
        assert np.all(selected[:,3]<=limit) and np.sum(selected[:,8])==o[4]
    if not config['protect_after_narrow']:
        assert len(floors)==0 and not np.any(ev[:,2]==3)
    if limit==0:
        assert len(ev)==0
    updates=partial.floor_rules(ledger,ready)
    return dict(狭い実部分返済数=len(narrow),親組床全返済数=len(floors),料金込み床更新数=updates)


def main():
    """
    機能: 全八条件・両約定モデルの保存注文と集計を独立会計へ通す。
    引数: --partial (bool) は保存済みだけ、--resume (bool) は指紋不変の既検算を再利用する。
    返り値: None。戦略の再生は行わない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--partial',action='store_true');parser.add_argument('--resume',action='store_true');args=parser.parse_args()
    strategy,_=partial.load()
    folder=ROOT/'work/wave_v85/audit';sys.path.insert(0,str(folder))
    module('original',folder/'original.py')
    account=module('監査87部分独立会計',folder/'accounts.py')
    fifo=module('監査87部分独立FIFO',ROOT/'work/wave_v67/audit/independent_accounting.py')
    prepare=module('監査87部分入力準備',ROOT/'work/wave_v85/prepare.py')
    fixed=read(ROUND/'事前固定.json')
    for name,value in fixed['code_SHA256'].items():assert digest(ROOT/name)==value,name
    inputs,_,_=prepare.load_inputs(verify=False)
    reports=[];totals=dict(口座数=0,注文数=0,決済脚数=0,狭い実部分返済数=0,親組床全返済数=0,料金込み床更新数=0)
    if args.resume and (HERE/'部分確保の途中独立会計.json').exists():
        prior=read(HERE/'部分確保の途中独立会計.json');assert prior['全合格']
        reports=prior['条件別'];totals={k:prior[k] for k in totals}
    for model in fixed['models']:
        for config in fixed['catalog']:
            path=ROUND/model/'results'/f"{config['id']}.json"
            if args.partial and not path.exists():continue
            packet=read(path);lp=ROUND/model/'ledgers'/f"{config['id']}.pkl"
            assert digest(lp)==packet['ledger_SHA256']
            completed=next((v for v in reports if v['モデル']==model and v['条件']==config['id']),None)
            if completed:
                assert digest(path)==completed['結果SHA256'] and digest(lp)==completed['台帳SHA256'];continue
            ledgers=pickle.loads(lp.read_bytes());rows=[]
            for actual in packet['rows']:
                key=actual['session'],actual['symbol'];ready=inputs[key];ledger=ledgers[key]
                old=dict(ledger,config=ledger['settings'],trades=ledger['net_trades'],fees=np.asarray(ledger['fees']).tolist())
                row,_,raw=fifo.measure(ready,old,model)
                np.testing.assert_array_equal(np.asarray(raw).reshape(-1,11),ledger['trades'])
                traced=account.trace(ready,ledger,row);account.ratios(row);account.equal(row,actual)
                account.time_windows(ready,ledger,traced,strategy.old.old,'U')
                for k,v in events(ready,ledger,config).items():totals[k]+=v
                totals['口座数']+=1;totals['注文数']+=len(ledger['orders']);totals['決済脚数']+=len(ledger['trades'])
                rows.append(row)
            periods={p:{s:account.aggregate(fifo,rows,s,fixed[p]) for s in ('TOPIX','NK225')} for p in ('前16','後14','全30')}
            account.equal(periods,packet['periods'])
            reports.append(dict(モデル=model,条件=config['id'],結果SHA256=digest(path),台帳SHA256=digest(lp),全合格=True))
            print(model,config['id'],'部分返済会計一致',flush=True)
    if not args.partial:assert len(reports)==16 and totals['口座数']==960
    for name,value in fixed['code_SHA256'].items():assert digest(ROOT/name)==value,name
    save('全8部分確保条件の独立会計.json' if not args.partial else '部分確保の途中独立会計.json',
        dict(全合格=True,条件数=len(reports),**totals,条件別=reports,親会計関数呼出=False,監査器SHA256=digest(__import__('pathlib').Path(__file__))))


if __name__=='__main__':
    main()
