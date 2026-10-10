"""全売買口座を返済脚から再構成し、分割・区間・数量・未来不変性を監査する。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(TASK))
from features import load_inputs_only
from engine import execute


def close(a: float, b: float) -> None:
    """機能: 金額の端数演算差のみを許して一致を検査する。

    引数: a/b(float)。返り値: なし(None)。
    """
    assert np.isclose(a,b,rtol=0,atol=1e-6), (a,b)


def audit_account(ready: dict, result: dict) -> tuple:
    """機能: 返済脚を分離して含み損益・数量・原本約定を独立再計算する。

    引数: ready/result(dict)。返り値: 再計算時価曲線と件数(tuple)。
    同一組の分割脚の保有時間重複は許し、異なる組の重複は許さない。
    """
    value, initial, cap = (1000.,5,10) if ready['symbol']=='TOPIX' else (10.,10,20)
    prices, times, seqs = ready['last'], ready['time_s'], ready['seq']
    floating, realized = np.zeros(len(prices)),np.zeros(len(prices))
    holding = np.zeros(len(prices),int)
    by_cycle, entries, remaining = {},{},{}
    dq = np.zeros(len(prices),int)
    for o in result['orders']:
        d,f = int(np.searchsorted(seqs,o[2])),int(np.searchsorted(seqs,o[3]))
        assert seqs[d]==o[2] and seqs[f]==o[3] and f==d+1
        assert times[d]==o[0] and times[f]==o[1] and prices[f]==o[7]
        cid=int(o[10])
        assert int(o[6])==o[6] and o[6]>0
        if o[4]==1:
            assert cid not in entries and o[6]==initial and o[11]==initial
            assert times[d]<ready['limit']-300
            entries[cid]=o
            remaining[cid]=initial
        else:
            assert cid in entries and o[5]==-entries[cid][5]
            remaining[cid]-=o[6]
            assert 0<=remaining[cid]<=initial and o[11]==remaining[cid]
            close(o[8], entries[cid][5]*o[6]*(o[7]-entries[cid][7])*value)
        dq[f]+=int(o[5]*o[6])
    assert not any(remaining.values())
    previous_end=-1
    for cid,entry in entries.items():
        legs=[t for t in result['trades'] if t[9]==cid]
        assert 1<=len(legs)<=2 and sum(t[3] for t in legs)==initial
        assert legs[0][11]>previous_end
        previous_end=legs[-1][12]
        if len(legs)==2:
            assert legs[0][3]==initial//2 and legs[1][3]==initial-initial//2
        by_cycle[cid]=sum(t[6] for t in legs)
    for t in result['trades']:
        start,end=int(np.searchsorted(seqs,t[11])),int(np.searchsorted(seqs,t[12]))
        assert seqs[start]==t[11] and seqs[end]==t[12] and end>start
        assert times[start]==t[0] and times[end]==t[1] and times[end]<ready['limit']+300
        assert prices[start]==t[4] and prices[end]==t[5]
        close(t[6],t[2]*t[3]*(t[5]-t[4])*value)
        close(t[14],max(0.,float(np.max(t[2]*(prices[start:end+1]-t[4]))))/t[8])
        close(t[15],(t[1]-t[0])/60.)
        holding[start:end]+=int(t[2]*t[3])
        floating[start:end]+=t[2]*t[3]*(prices[start:end]-t[4])*value
        realized[end]+=t[6]
    np.testing.assert_array_equal(holding,np.cumsum(dq))
    assert holding[-1]==0 and np.max(abs(holding),initial=0)<=min(initial,cap)
    curve=np.cumsum(realized)+floating
    close(curve[-1],result['net'])
    close(result['profit'],sum(max(t[6],0.) for t in result['trades']))
    close(result['loss'],-sum(min(t[6],0.) for t in result['trades']))
    for name,test in [('win_qty',lambda p:p>0),('loss_qty',lambda p:p<0),('flat_qty',lambda p:p==0)]:
        assert result[name]==sum(t[3] for t in result['trades'] if test(t[6]))
    assert result['group_nets']==list(by_cycle.values())
    assert result['cycles']==len(by_cycle) and result['repayment_legs']==len(result['trades'])
    assert result['wins']==sum(p>0 for p in by_cycle.values()) and result['losses']==sum(p<0 for p in by_cycle.values())
    dd=float(np.max(np.maximum.accumulate(np.r_[0.,curve])[1:]-curve,initial=0.))
    close(dd,result['drawdown'])
    previous=0.
    realized_path=np.cumsum(realized)
    for interval in result['intervals']:
        left=datetime.fromisoformat(interval['開始']).timestamp()
        right=datetime.fromisoformat(interval['終了未満']).timestamp()
        i=int(np.searchsorted(times,right,side='left'))-1
        equity=curve[i] if i>=0 else 0.
        accumulated=realized_path[i] if i>=0 else 0.
        selected=[t for t in result['trades'] if left<=t[1]<right]
        close(interval['時価収支円'],equity-previous)
        close(interval['終了含み円'],equity-accumulated)
        close(interval['利益円'],sum(max(t[6],0.) for t in selected))
        close(interval['損失円'],-sum(min(t[6],0.) for t in selected))
        assert interval['評価原本行']==int(seqs[i])
        previous=equity
    close(sum(i['時価収支円'] for i in result['intervals']),result['net'])
    return curve, dict(注文数=len(result['orders']),組数=len(entries),返済脚数=len(result['trades']),区間数=len(result['intervals']))


def audit_summary(accounts: list, expected: dict, curves: dict) -> None:
    """機能: 全期間・週・期間別の組数と枚数、金額、最大下落を検査する。

    引数: accounts(list)、expected/curves(dict)。返り値: なし(None)。
    """
    for name in ('profit','loss','net','win_qty','loss_qty','flat_qty','cycles','wins','losses'):
        close(expected[name],sum(a[name] for a in accounts))
    ratios={'pf':('profit','loss'),'win_rate':('wins','cycles'),'win_per_lot':('profit','win_qty'),'loss_per_lot':('loss','loss_qty')}
    for name,(top,bottom) in ratios.items():
        value=expected[top]/expected[bottom] if expected[bottom] else None
        assert expected[name] is None if value is None else np.isclose(expected[name],value)
    assert expected['positive_sessions']==sum(a['net']>0 for a in accounts)
    assert expected['negative_sessions']==sum(a['net']<0 for a in accounts)
    assert expected['active_sessions']==sum(a['cycles']>0 for a in accounts)
    close(expected['without_best'],expected['net']-max([a['net'] for a in accounts],default=0))
    peak=balance=dd=0.
    for account in sorted(accounts,key=lambda a:a['session']):
        curve=curves[account['session'],account['symbol']]+balance
        high=np.maximum.accumulate(np.r_[peak,curve])[1:]
        dd=max(dd,float(np.max(high-curve,initial=0)))
        peak=max(peak,float(np.max(curve,initial=peak)))
        balance+=account['net']
    close(expected['drawdown'],dd)


def main() -> None:
    """機能: 全2300口座会計と六口座五十条件の未来不変性を保存する。

    引数: なし。返り値: なし(None)。利益順位は表示せず監査のみ行う。
    """
    result=json.loads((TASK/'売買結果.json').read_text(encoding='utf8'))
    inputs=load_inputs_only()
    decisions=pickle.loads((TASK/'判断.pkl').read_bytes())
    accounts_audit=[]
    prefix=[]
    keys=sorted(inputs)
    chosen={keys[i] for i in (0,1,22,23,44,45)}
    for method in result['methods']:
        curves={}
        for account in method['accounts']:
            key=account['session'],account['symbol']
            ready=inputs[key]
            curves[key], counts=audit_account(ready,account)
            accounts_audit.append(dict(手法=method['id'],セッション=key[0],銘柄=key[1],**counts))
            if key in chosen:
                ds=decisions[key,method['family'],method['confirmation']]
                for fraction in (.35,.7):
                    cut=int(len(ready['seq'])*fraction)
                    partial={k:v[:cut] if isinstance(v,np.ndarray) and len(v)==len(ready['seq']) else v for k,v in ready.items()}
                    known=[o for o in account['orders'] if o[3]<=ready['seq'][cut-1]]
                    actual=execute(partial,ds[ds[:,0]<cut],method['advanced'],finish=False)
                    assert actual['orders']==known
                    changed=ready.copy()
                    changed['last']=ready['last'].copy()
                    changed['last'][cut:]*=1.6
                    other=execute(changed,ds,method['advanced'],finish=False)
                    assert [o for o in other['orders'] if o[3]<=ready['seq'][cut-1]]==known
                    prefix.append(dict(手法=method['id'],セッション=key[0],銘柄=key[1],切断比率=fraction,一致注文数=len(known)))
        for symbol in ('TOPIX','NK225'):
            selected=[a for a in method['accounts'] if a['symbol']==symbol]
            audit_summary(selected,method['summary'][symbol],curves)
            for label,ss in [('前10場',result['sessions'][:10]),('次9場',result['sessions'][10:19]),('後4場',result['sessions'][19:])]:
                audit_summary([a for a in selected if a['session'] in ss],method['periods'][symbol][label],curves)
            for monday,expected in method['weeks'][symbol].items():
                start=datetime.fromisoformat(monday).date()
                audit_summary([a for a in selected if 0<=(datetime.fromisoformat(a['session'][:10]).date()-start).days<7],expected,curves)
    output=dict(合格=True,条件数=len(result['methods']),口座数=len(accounts_audit),
                合計={name:sum(a[name] for a in accounts_audit) for name in ('注文数','組数','返済脚数','区間数')},
                会計=accounts_audit,未来切断と改変=prefix,
                コードSHA256={name:hashlib.sha256((TASK/name).read_bytes()).hexdigest() for name in ('engine.py','signals.py','backtest.py')})
    (HERE/'売買会計の独立検査.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    print('会計合格',len(accounts_audit),'未来検査',len(prefix),'件数',output['合計'],flush=True)


if __name__=='__main__':
    main()
