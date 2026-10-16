"""保存24結果を注文の独立会計・再参加証跡から検算する。"""

import argparse
import hashlib
import math
import pickle
import sys
import numpy as np
from boundaries import module, load
from diagnose import ROOT, HERE, read, save
event_rules=module('監査87再参加証跡',HERE/'prefix.py').event_rules

ROUND=ROOT/'work/wave_v87/round1'


def digest(path):
    """
    機能: 保存されたファイルの内容指紋を取得する。
    引数: path (Path)。
    返り値: str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decisions(ready,ledger,config):
    """
    機能: 親組の黒字後だけ60秒再参加する証跡を、注文料金後会計と照合する。
    引数: ready/ledger/config (dict)。
    返り値: dictの判定数・許可数・翌行反映数。
    """
    events=ledger['profit_reentry_events'];cycles=ledger['cycles'];positive={}
    assert len(events)==len(cycles)
    for e,c in zip(events,cycles):
        row,cid,yen,allowed,when=e[:5]
        assert row==c[2] and cid==c[0]
        net=math.fsum(t['収支'] for t in ledger['net_trades'] if t['組']==int(cid))
        assert abs(yen-net)<1e-5 and bool(allowed)==bool(net>1e-7)
        if allowed:
            assert when==ready['time_s'][int(row)]+config['cooldown_seconds']
            positive[int(row)]=e
        else:
            assert math.isnan(when)
    for row,reflected,when,cid,_,_ in ledger['reentry_events']:
        assert int(row) in positive and reflected==row+1
        assert positive[int(row)][1]==cid and positive[int(row)][4]==when
    assert len(ledger['reentry_events'])==sum(row<len(ready['last'])-1 for row in positive)
    links={int(p[0]):p for p in ledger['entry_preparations']}
    for a,b in zip(cycles[:-1],cycles[1:]):
        close,prepared,entered=int(a[2]),int(links[int(b[0])][3]),int(b[1])
        assert close<prepared<entered
        expected=positive[close][4] if close in positive else ready['time_s'][close]+300.
        assert ready['time_s'][prepared]>=expected
    return dict(親組判定数=len(events),黒字早期許可数=len(positive),翌行反映数=len(ledger['reentry_events']))


def main():
    """
    機能: 固定12条件の全保存注文から会計・時価・停止帯・再参加条件を検証する。
    引数: --partial (bool) は途中保存だけ、--resume (bool) は不変指紋の既検算分を継続する。
    返り値: None。売買再生や親の会計関数を呼ばない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--partial',action='store_true');parser.add_argument('--resume',action='store_true');args=parser.parse_args()
    strategy,_=load()
    old_path=ROOT/'work/wave_v85/audit';sys.path.insert(0,str(old_path))
    module('original',old_path/'original.py')
    account=module('監査87独立時価会計',old_path/'accounts.py')
    independent=module('監査87独立FIFO',ROOT/'work/wave_v67/audit/independent_accounting.py')
    prepare=module('監査87入力準備',ROOT/'work/wave_v85/prepare.py')
    fixed=read(ROUND/'事前固定.json')
    for name,value in fixed['code_SHA256'].items():assert digest(ROOT/name)==value,name
    inputs,_,_=prepare.load_inputs(verify=False)
    reports=[];totals=dict(口座数=0,注文数=0,決済脚数=0,親組判定数=0,黒字早期許可数=0,翌行反映数=0,追加条件証跡数=0)
    if args.resume and (HERE/'保存途中の独立会計.json').exists():
        previous=read(HERE/'保存途中の独立会計.json')
        assert previous['全合格']
        reports=previous['条件別']
        totals={k:previous[k] for k in totals}
    for model in fixed['models']:
        for config in fixed['catalog']:
            path=ROUND/model/'results'/f"{config['id']}.json"
            if args.partial and not path.exists():continue
            packet=read(path);ledger_path=ROUND/model/'ledgers'/f"{config['id']}.pkl"
            assert digest(ledger_path)==packet['ledger_SHA256']
            completed=next((r for r in reports if r['モデル']==model and r['条件']==config['id']),None)
            if completed is not None:
                assert digest(path)==completed['結果SHA256'] and packet['ledger_SHA256']==completed['台帳SHA256']
                continue
            ledgers=pickle.loads(ledger_path.read_bytes());rows=[]
            assert len(ledgers)==len(packet['rows'])==60
            for actual in packet['rows']:
                key=actual['session'],actual['symbol'];ready=inputs[key];ledger=ledgers[key]
                old_format=dict(ledger,config=ledger['settings'],trades=ledger['net_trades'],fees=np.asarray(ledger['fees']).tolist())
                row,_,raw=independent.measure(ready,old_format,model)
                np.testing.assert_array_equal(np.asarray(raw).reshape(-1,11),ledger['trades'])
                traced=account.trace(ready,ledger,row);account.ratios(row);account.equal(row,actual)
                account.time_windows(ready,ledger,traced,strategy.old.old,'U')
                for k,v in decisions(ready,ledger,config).items():totals[k]+=v
                totals['追加条件証跡数']+=event_rules(ledger,ready,config)
                totals['口座数']+=1;totals['注文数']+=len(ledger['orders']);totals['決済脚数']+=len(ledger['trades'])
                rows.append(row)
            periods={p:{s:account.aggregate(independent,rows,s,fixed[p]) for s in ('TOPIX','NK225')} for p in ('前16','後14','全30')}
            account.equal(periods,packet['periods'])
            reports.append(dict(モデル=model,条件=config['id'],全会計と再参加条件一致=True,
                結果SHA256=digest(path),台帳SHA256=packet['ledger_SHA256']))
            print(model,config['id'],'独立会計一致',flush=True)
    if not args.partial:assert len(reports)==24 and totals['口座数']==1440
    for name,value in fixed['code_SHA256'].items():assert digest(ROOT/name)==value,name
    save('全12条件の独立会計と再参加条件.json' if not args.partial else '保存途中の独立会計.json',
        dict(全合格=True,条件数=len(reports),**totals,条件別=reports,親会計関数呼出=False,
            監査器SHA256=digest(__import__('pathlib').Path(__file__))))


if __name__=='__main__':
    main()
