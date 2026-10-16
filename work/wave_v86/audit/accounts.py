"""注文の独立FIFO・全観測時価・再参加時計を保存台帳から検算する。"""

import argparse
import json
import pickle
import sys

import numpy as np

from support import ROOT, WORK, components, digest, module, save


def audit_reentry(ready, ledger, config):
    """
    機能: 実返済と新準備の前後順、休止秒数、発動証跡の参照元を照合する。
    引数: ready/ledger/config (dict)。
    返り値: dictの証跡件数。
    """
    prepare = {int(v[0]): v for v in ledger['prepare_events']}
    linked = {int(v[0]): v for v in ledger['entry_preparations']}
    cycles = ledger['cycles']
    orders = ledger['orders']
    if config['reentry_mode'] == 'actual':
        for previous, current in zip(cycles[:-1],cycles[1:]):
            exit_row, entry_row = int(previous[2]), int(current[1])
            relation = linked[int(current[0])]
            prepared_row = int(relation[3])
            assert exit_row < prepared_row < entry_row
            assert prepare[int(relation[2])][1] == prepared_row
            assert ready['time_s'][prepared_row] >= ready['time_s'][exit_row] + config['cooldown_seconds']
        for event in ledger.get('reentry_events', []):
            closed, reflected, allowed, cid, _, _ = event
            assert closed < reflected
            assert allowed == ready['time_s'][int(closed)] + config['cooldown_seconds']
            cycle = cycles[cycles[:,0]==cid]
            assert len(cycle)==1 and cycle[0,2]==closed
    elif len(ledger.get('reentry_events', [])):
        raise AssertionError('旧影時計に実返済からの反映証跡があります')
    for event in ledger.get('dynamic_events', []):
        row, cid, source, direction, mfe, oldwidth, newwidth = event
        assert source <= row and mfe >= config['dynamic_activation_atr'] and newwidth <= oldwidth
        entries = orders[(orders[:,2]==cid)&(orders[:,7]==1)]
        if len(entries):
            assert source > entries[0,0]
        assert config['dynamic_trail']
    return dict(再参加反映数=len(ledger.get('reentry_events', [])), 動的幅短縮数=len(ledger.get('dynamic_events', [])))


def main():
    """
    機能: 全40結果を会計器とは別の既監査FIFO・現金在庫式で照合する。
    引数: --partial (bool) は現時点で存在する結果だけを検査する指定。
    返り値: None。新規売買再生をしない。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--partial',action='store_true')
    args=parser.parse_args()
    strategy, _, _, prepare=components()
    legacy_path=ROOT/'work/wave_v85/audit'
    sys.path.insert(0,str(legacy_path))
    original=module('original',legacy_path/'original.py')
    account=module('wave86_old_audit_accounts',legacy_path/'accounts.py')
    independent=module('wave86_independent_fifo',ROOT/'work/wave_v67/audit/independent_accounting.py')
    fixed=json.loads((WORK/'事前固定.json').read_text(encoding='utf-8'))
    for name, expected in fixed['code_SHA256'].items():
        assert digest(ROOT/name)==expected,name
    inputs, _, _=prepare.load_inputs(verify=False)
    reports=[]
    totals=dict(口座数=0,注文数=0,決済脚数=0,組数=0,再参加反映数=0,動的幅短縮数=0)
    for model in fixed['models']:
        for config in fixed['catalog']:
            path=WORK/model/'results'/(config['id']+'.json')
            if args.partial and not path.exists():
                continue
            packet=json.loads(path.read_text(encoding='utf-8'))
            ledger_path=WORK/model/'ledgers'/(config['id']+'.pkl')
            assert digest(ledger_path)==packet['ledger_SHA256']
            ledgers=pickle.loads(ledger_path.read_bytes())
            assert len(ledgers)==len(packet['rows'])==60
            rows=[]
            for actual in packet['rows']:
                key=actual['session'],actual['symbol']
                ready, ledger=inputs[key],ledgers[key]
                old_format=dict(ledger,config=ledger['settings'],trades=ledger['net_trades'],
                                fees=np.asarray(ledger['fees']).tolist())
                row, details, raw=independent.measure(ready,old_format,model)
                np.testing.assert_array_equal(np.asarray(raw).reshape(-1,11),ledger['trades'])
                traced=account.trace(ready,ledger,row)
                account.ratios(row)
                account.equal(row,actual)
                account.time_windows(ready,ledger,traced,strategy.old,'U')
                counts=audit_reentry(ready,ledger,config)
                for k,v in counts.items():
                    totals[k]+=v
                totals['口座数']+=1
                totals['注文数']+=len(ledger['orders'])
                totals['決済脚数']+=len(ledger['trades'])
                totals['組数']+=len(ledger['cycles'])
                rows.append(row)
            periods={p:{s:account.aggregate(independent,rows,s,fixed[p]) for s in ('TOPIX','NK225')}
                     for p in ('前16','後14','全30')}
            account.equal(periods,packet['periods'])
            reports.append(dict(モデル=model,条件=config['id'],口座数=60,全行時価と全会計一致=True,
                結果SHA256=digest(path),台帳SHA256=packet['ledger_SHA256']))
            print(model,config['id'],'独立会計一致',flush=True)
    if not args.partial:
        assert len(reports)==40 and totals['口座数']==2400
    for name, expected in fixed['code_SHA256'].items():
        assert digest(ROOT/name)==expected,name
    save('全条件の独立会計と再参加時計.json' if not args.partial else '一部保存結果の独立会計.json',
         dict(全合格=True,条件数=len(reports),**totals,条件別=reports,親会計呼出=False,
              監査器SHA256=digest(__import__('pathlib').Path(__file__))))


if __name__=='__main__':
    main()
