"""利確後だけ再参加した全20結果の会計と親組黒字判定を独立照合する。"""

import argparse
import json
import math
import pickle
import sys

import numpy as np

from support import ROOT, WORK, module, digest, save
from phase2_checks import PHASE, load


def decisions(ready,ledger,config):
    """
    機能: 保存した決済脚の料金後合計から、黒字だけの再参加許可を再計算する。
    引数: ready/ledger/config (dict)。
    返り値: dictの判定数と早期許可数。
    """
    events=ledger['profit_reentry_events']
    cycles=ledger['cycles']
    assert len(events)==len(cycles)
    expected_positive={}
    for event,cycle in zip(events,cycles):
        row,cid,yen,allowed,when=event[:5]
        assert row==cycle[2] and cid==cycle[0]
        net=math.fsum(t['収支'] for t in ledger['net_trades'] if t['組']==int(cid))
        assert abs(net-yen)<1e-5
        assert bool(allowed)==bool(net>1e-7)
        if allowed:
            assert when==ready['time_s'][int(row)]+config['cooldown_seconds']
            expected_positive[int(row)]=event
        else:
            assert math.isnan(when)
    reset=ledger['reentry_events']
    for row,reflected,when,cid,_,_ in reset:
        assert int(row) in expected_positive
        assert reflected==row+1
        assert expected_positive[int(row)][1]==cid and expected_positive[int(row)][4]==when
    assert len(reset)==sum(row<len(ready['last'])-1 for row in expected_positive)
    link={int(p[0]):p for p in ledger['entry_preparations']}
    for prior,current in zip(cycles[:-1],cycles[1:]):
        close,prepared,entered=int(prior[2]),int(link[int(current[0])][3]),int(current[1])
        assert close<prepared<entered
        if close in expected_positive:
            assert ready['time_s'][prepared]>=expected_positive[close][4]
        else:
            # 元の実玉5分休止より早く赤字から再参加することも拒否する。
            assert ready['time_s'][prepared]>=ready['time_s'][close]+300.
    return dict(親組判定数=len(events),黒字早期許可数=len(expected_positive),翌行反映数=len(reset))


def main():
    """
    機能: 追加10条件×2モデル×60口座の全会計と再参加許可を監査する。
    引数: --partial (bool) は保存済みだけを検査する。
    返り値: None。新しい売買再生は行わない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--partial',action='store_true');args=parser.parse_args()
    strategy,_,prepare=load()
    legacy_path=ROOT/'work/wave_v85/audit'
    sys.path.insert(0,str(legacy_path))
    module('original',legacy_path/'original.py')
    account=module('wave86_p2_old_audit_accounts',legacy_path/'accounts.py')
    independent=module('wave86_p2_independent_fifo',ROOT/'work/wave_v67/audit/independent_accounting.py')
    fixed=json.loads((PHASE/'事前固定.json').read_text(encoding='utf-8'))
    for name,expected in fixed['code_SHA256'].items():
        assert digest(ROOT/name)==expected,name
    inputs,_,_=prepare.load_inputs(verify=False)
    reports=[]
    totals=dict(口座数=0,注文数=0,決済脚数=0,親組判定数=0,黒字早期許可数=0,翌行反映数=0)
    for model in fixed['models']:
        for config in fixed['catalog']:
            path=PHASE/model/'results'/(config['id']+'.json')
            if args.partial and not path.exists():
                continue
            packet=json.loads(path.read_text(encoding='utf-8'))
            ledger_path=PHASE/model/'ledgers'/(config['id']+'.pkl')
            assert digest(ledger_path)==packet['ledger_SHA256']
            ledgers=pickle.loads(ledger_path.read_bytes())
            assert len(ledgers)==len(packet['rows'])==60
            rows=[]
            for actual in packet['rows']:
                key=actual['session'],actual['symbol']
                ready,ledger=inputs[key],ledgers[key]
                old_format=dict(ledger,config=ledger['settings'],trades=ledger['net_trades'],fees=np.asarray(ledger['fees']).tolist())
                row,_,raw=independent.measure(ready,old_format,model)
                np.testing.assert_array_equal(np.asarray(raw).reshape(-1,11),ledger['trades'])
                traced=account.trace(ready,ledger,row)
                account.ratios(row);account.equal(row,actual)
                account.time_windows(ready,ledger,traced,strategy.old.old,'U')
                counts=decisions(ready,ledger,config)
                for k,v in counts.items():totals[k]+=v
                totals['口座数']+=1;totals['注文数']+=len(ledger['orders']);totals['決済脚数']+=len(ledger['trades'])
                rows.append(row)
            periods={p:{s:account.aggregate(independent,rows,s,fixed[p]) for s in ('TOPIX','NK225')} for p in ('前16','後14','全30')}
            account.equal(periods,packet['periods'])
            reports.append(dict(条件=config['id'],モデル=model,会計と親組判定一致=True,結果SHA256=digest(path),台帳SHA256=packet['ledger_SHA256']))
            print(model,config['id'],'P独立会計一致',flush=True)
    if not args.partial:
        assert len(reports)==20 and totals['口座数']==1200
    for name,expected in fixed['code_SHA256'].items():
        assert digest(ROOT/name)==expected,name
    save('利確後再参加の全会計と親組判定.json' if not args.partial else '利確後再参加の一部会計.json',
        dict(全合格=True,条件数=len(reports),**totals,条件別=reports,親会計呼出=False,
             監査器SHA256=digest(__import__('pathlib').Path(__file__))))


if __name__=='__main__':
    main()
