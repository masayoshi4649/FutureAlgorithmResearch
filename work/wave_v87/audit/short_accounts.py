"""最新支持十条件の保存会計と、新規注文に使った直前公開許可を独立照合する。"""

import argparse
import hashlib
import pickle
import sys
import numpy as np
from diagnose import ROOT,HERE,read,save
from boundaries import module

ROUND=ROOT/'work/wave_v87/round3'


def digest(path):
    """
    機能: 保存結果と固定ソースの指紋を取得する。
    引数: path(Path)。
    返り値: str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entries(ready,ledger,config,short):
    """
    機能: 新規約定の直前に公開された支持が条件を満たし、未来元行を使わないことを確認する。
    引数: ready/ledger/config/short(dict)。
    返り値: intの確認新規数。今行の支持低下で旧注文を後付け取消しない。
    """
    mode=config['support_mode'];events=ledger['support_events'];count=0
    for order in ledger['orders'][ledger['orders'][:,7]==1]:
        row=int(order[0]);previous=row-1;side=int(order[3])
        history=events[events[:,0]<row];assert len(history)
        e=history[-1];extreme=int(e[2])
        assert e[1]==side and e[3]==1 and 0<=extreme<=previous
        assert order[1]<row
        if mode:
            assert short['self_valid'][previous] and side*short['self_value'][previous]>.05
        if mode in (2,4):assert short['self_source_seq'][previous]>ready['seq'][extreme]
        if mode in (3,4):assert short['peer_valid'][previous] and side*short['peer_value'][previous]>.05
        if mode==4:assert short['peer_source_time'][previous]>ready['time_s'][extreme]
        count+=1
    return count


def main():
    """
    機能: 全十条件・両約定モデルの保存注文を独立FIFO会計へ通し、支持公開根拠も再検査する。
    引数: --partial(bool)は保存済みのみ、--resume(bool)は指紋一致した既確認を再利用する。
    返り値: None。戦略損益を再生しない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--partial',action='store_true');parser.add_argument('--resume',action='store_true');args=parser.parse_args()
    strategy=module('監査87支持会計戦略',ROUND/'strategy.py')
    folder=ROOT/'work/wave_v85/audit';sys.path.insert(0,str(folder))
    module('original',folder/'original.py')
    account=module('監査87支持独立会計',folder/'accounts.py')
    fifo=module('監査87支持独立FIFO',ROOT/'work/wave_v67/audit/independent_accounting.py')
    prepare=module('監査87支持入力準備',ROOT/'work/wave_v85/prepare.py')
    fixed=read(ROUND/'事前固定.json')
    for name,value in fixed['code_SHA256'].items():assert digest(ROOT/name)==value,name
    inputs,_,_=prepare.load_inputs(verify=False)
    shorts=pickle.loads((ROUND/'prepared/short.pkl').read_bytes())['expanded']
    reports=[];totals=dict(口座数=0,注文数=0,決済脚数=0,新規公開根拠照合数=0)
    if args.resume and (HERE/'支持条件の途中独立会計.json').exists():
        prior=read(HERE/'支持条件の途中独立会計.json');assert prior['全合格']
        reports=prior['条件別'];totals={k:prior[k] for k in totals}
    for model in fixed['models']:
        for config in fixed['catalog']:
            path=ROUND/model/'results'/f"{config['id']}.json"
            if args.partial and not path.exists():continue
            packet=read(path);lp=ROUND/model/'ledgers'/f"{config['id']}.pkl"
            assert packet['config']==config and packet['model']==model
            assert packet['run']['code_SHA256']==fixed['code_SHA256']
            assert packet['run']['input_SHA256']==fixed['input_SHA256']
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
                totals['新規公開根拠照合数']+=entries(ready,ledger,config,shorts[key])
                totals['口座数']+=1;totals['注文数']+=len(ledger['orders']);totals['決済脚数']+=len(ledger['trades'])
                rows.append(row)
            periods={p:{s:account.aggregate(fifo,rows,s,fixed[p]) for s in ('TOPIX','NK225')} for p in ('前16','後14','全30')}
            account.equal(periods,packet['periods'])
            reports.append(dict(モデル=model,条件=config['id'],結果SHA256=digest(path),台帳SHA256=digest(lp),全合格=True))
            print(model,config['id'],'会計・直前支持一致',flush=True)
    if not args.partial:assert len(reports)==20 and totals['口座数']==1200
    for name,value in fixed['code_SHA256'].items():assert digest(ROOT/name)==value,name
    save('支持条件の途中独立会計.json' if args.partial else '全10支持条件の独立会計と直前公開根拠.json',dict(全合格=True,条件数=len(reports),
        **totals,条件別=reports,親会計関数呼出=False,監査器SHA256=digest(__import__('pathlib').Path(__file__))))


if __name__=='__main__':
    main()
