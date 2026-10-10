"""金額・実効R・計画Rを返済組から別計算し、全口座を独立監査する。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE=Path(__file__).resolve().parent
TASK=HERE.parent
sys.path.insert(0,str(TASK))
from features import load_inputs_only
from engine import execute


def same(a: float, b: float) -> None:
    """機能: 浮動小数の演算誤差内で同じか検査する。

    引数: a/b(float)。返り値: なし(None)。
    """
    assert np.isclose(a,b,rtol=0,atol=1e-6),(a,b)


def dd(curve: np.ndarray) -> float:
    """機能: 初期残高ゼロからの時価最大下落を計算する。

    引数: curve(ndarray)。返り値: 最大下落(float)。
    """
    return float(np.max(np.maximum.accumulate(np.r_[0.,curve])[1:]-curve,initial=0))


def account_audit(ready: dict, ds: np.ndarray, account: dict) -> dict:
    """機能: 注文時の反証線と各返済から、金額と二種類のR曲線を再構成する。

    引数: ready/account(dict)、ds(ndarray)。返り値: 独立曲線(dict)。
    """
    price,time,seq=ready['last'],ready['time_s'],ready['seq']
    qty,value=(5,1000) if ready['symbol']=='TOPIX' else (10,10)
    holding=np.zeros(len(price),int)
    realized,floating=np.zeros(len(price)),np.zeros(len(price))
    r_realized,r_floating=np.zeros(len(price)),np.zeros(len(price))
    p_realized,p_floating=np.zeros(len(price)),np.zeros(len(price))
    assert len(account['orders'])==len(account['trades'])*2==len(account['risk_groups'])*2
    previous_exit=-np.inf
    total_gap=0
    for i,(leg,g) in enumerate(zip(account['trades'],account['risk_groups'])):
        opening,closing=account['orders'][i*2:i*2+2]
        for o in (opening,closing):
            decision,fill=np.searchsorted(seq,[o[2],o[3]])
            assert seq[decision]==o[2] and seq[fill]==o[3] and fill==decision+1
            assert o[0]==time[decision] and o[1]==time[fill] and o[7]==price[fill]
            assert o[6]==qty
        assert opening[4]==1 and closing[4]==2 and opening[5]==-closing[5]
        assert opening[11]==qty and closing[11]==0
        assert opening[0]>=previous_exit+60 and opening[0]<ready['limit']-300
        previous_exit=closing[1]
        begin,end=np.searchsorted(seq,[leg[11],leg[12]])
        assert begin==g[5] and end==g[6] and end>begin and time[end]<ready['limit']+300
        assert leg[0]==time[begin] and leg[1]==time[end] and leg[4]==price[begin] and leg[5]==price[end]
        assert leg[9]==g[0]==opening[10]==closing[10]
        di=np.searchsorted(seq,opening[2]);si=np.searchsorted(ds[:,0],di)
        signal=ds[si]
        assert signal[0]==di and signal[1]==leg[2] and signal[5]==g[1] and signal[8]==g[2]
        real_r=leg[2]*(leg[4]-signal[2])
        plan_r=signal[7]
        gap=real_r<=0
        risk=plan_r if gap else real_r
        same(g[3],risk);same(g[9],plan_r)
        assert g[10]==int(gap)
        total_gap+=int(gap)
        if gap:
            assert closing[9]==6 and closing[2]==opening[3]
        pnl=leg[2]*qty*(leg[5]-leg[4])*value
        same(pnl,leg[6]);same(pnl,closing[8]);same(g[4],pnl/(risk*qty*value))
        same(leg[14],max(0.,float(np.max(leg[2]*(price[begin:end+1]-leg[4]))))/leg[8])
        assert not holding[begin:end].any()
        holding[begin:end]=int(leg[2]*qty)
        path=leg[2]*(price[begin:end]-leg[4])
        floating[begin:end]=path*qty*value
        r_floating[begin:end]=path/risk
        p_floating[begin:end]=path/plan_r
        realized[end]+=pnl
        r_realized[end]+=g[4]
        p_realized[end]+=pnl/(plan_r*qty*value)
    curves=dict(curve=np.cumsum(realized)+floating,r_curve=np.cumsum(r_realized)+r_floating,
                planned_curve=np.cumsum(p_realized)+p_floating)
    assert holding[-1]==0 and np.max(abs(holding),initial=0)<=qty
    for name,field in [('curve','net'),('r_curve','r_net'),('planned_curve','planned_r_net')]:
        same(curves[name][-1],account[field])
    assert total_gap==account['gap_entries']
    rs=np.asarray([g[4] for g in account['risk_groups']])
    same(account['r_profit'],np.maximum(rs,0).sum())
    same(account['r_loss'],-np.minimum(rs,0).sum())
    same(dd(curves['curve']),account['drawdown']);same(dd(curves['r_curve']),account['r_drawdown'])
    pnl=np.asarray([t[6] for t in account['trades']])
    same(account['profit'],np.maximum(pnl,0).sum());same(account['loss'],-np.minimum(pnl,0).sum())
    assert account['cycles']==len(pnl) and account['wins']==(pnl>0).sum() and account['losses']==(pnl<0).sum()
    assert account['win_qty']==(pnl>0).sum()*qty and account['loss_qty']==(pnl<0).sum()*qty and account['flat_qty']==(pnl==0).sum()*qty
    previous=0.;cash=np.cumsum(realized)
    for interval in account['intervals']:
        right=datetime.fromisoformat(interval['終了未満']).timestamp()
        j=np.searchsorted(time,right,side='left')-1
        equity=curves['curve'][j] if j>=0 else 0.
        same(interval['時価収支円'],equity-previous)
        same(interval['終了含み円'],equity-(cash[j] if j>=0 else 0.))
        previous=equity
    same(sum(r['時価収支円'] for r in account['intervals']),account['net'])
    return curves


def summary_audit(accounts: list, expected: dict, curves: dict) -> None:
    """機能: 金額とRの期間集計・最大利益除外・平均・下落を独立照合する。

    引数: accounts(list)、expected/curves(dict)。返り値: なし(None)。
    """
    for name in ('profit','loss','net','win_qty','loss_qty','flat_qty','cycles','wins','losses','r_net','r_profit','r_loss','planned_r_net','gap_entries'):
        same(expected[name],sum(a[name] for a in accounts))
    rs=np.asarray([g[4] for a in accounts for g in a['risk_groups']])
    plans=np.asarray([g[4]*g[3]/g[9] for a in accounts for g in a['risk_groups']])
    wins,losses=rs[rs>0],-rs[rs<0]
    ratios={
        'r_pf':float(wins.sum()/losses.sum()) if losses.sum() else None,
        'r_payoff':float(wins.mean()/losses.mean()) if len(wins) and len(losses) else None,
        'pf':expected['profit']/expected['loss'] if expected['loss'] else None,
        'payoff':(expected['profit']/expected['win_qty'])/(expected['loss']/expected['loss_qty'])
                  if expected['win_qty'] and expected['loss_qty'] and expected['loss'] else None,
    }
    for name,value in ratios.items():
        assert expected[name] is None if value is None else np.isclose(expected[name],value,rtol=0,atol=1e-8)
    assert expected['active_sessions']==sum(a['cycles']>0 for a in accounts)
    assert expected['positive_sessions']==sum(a['net']>0 for a in accounts)
    assert expected['negative_sessions']==sum(a['net']<0 for a in accounts)
    for name,value in [('r_mean',rs.mean() if len(rs) else None),('planned_r_mean',plans.mean() if len(plans) else None),
                       ('r_median',np.median(rs) if len(rs) else None),('r_worst',rs.min() if len(rs) else None)]:
        assert expected[name] is None if value is None else np.isclose(expected[name],value,rtol=0,atol=1e-8)
    same(expected['without_best'],expected['net']-max([a['net'] for a in accounts],default=0))
    same(expected['r_without_best_session'],rs.sum()-max([a['r_net'] for a in accounts],default=0))
    same(expected['r_without_best_trade'],rs.sum()-rs.max(initial=0))
    for col,name in [('curve','drawdown'),('r_curve','r_drawdown')]:
        peak=balance=fall=0.
        for a in sorted(accounts,key=lambda x:x['session']):
            path=balance+curves[a['session'],a['symbol']][col]
            highs=np.maximum.accumulate(np.r_[peak,path])[1:]
            fall=max(fall,float(np.max(highs-path,initial=0)))
            peak=max(peak,float(np.max(path,initial=peak)))
            balance+=a['net' if col=='curve' else 'r_net']
        same(expected[name],fall)
    common=expected['net']>0 and expected['r_net']>0 and expected['planned_r_net']>0 and expected['without_best']>0 and expected['r_without_best_session']>0 and expected['cycles']>=30 and expected['active_sessions']>=8
    assert expected['common_pass']==bool(common)


def main() -> None:
    """機能: 全十四条件の六百四十四口座と途中の三曲線を監査する。

    引数: なし。返り値: なし(None)。既存売買を変更しない。
    """
    result=json.loads((TASK/'売買結果.json').read_text(encoding='utf8'))
    inputs=load_inputs_only()
    signals=pickle.loads((TASK/'判断.pkl').read_bytes())
    keys=sorted(inputs);chosen={keys[i] for i in (0,1,22,23,44,45)}
    accounting=[];future=[]
    for method in result['methods']:
        curves={}
        for a in method['accounts']:
            key=a['session'],a['symbol'];ready=inputs[key]
            ds=signals[key,method['policy'],method['gate']]
            curves[key]=account_audit(ready,ds,a)
            accounting.append(dict(手法=method['id'],セッション=key[0],銘柄=key[1],注文数=len(a['orders']),組数=a['cycles'],区間数=len(a['intervals']),異常約定=a['gap_entries']))
            if key in chosen:
                qty,value=(5,1000) if key[1]=='TOPIX' else (10,10)
                for fraction in (.35,.7):
                    cut=int(len(ready['seq'])*fraction)
                    part={k:v[:cut] if isinstance(v,np.ndarray) and len(v)==len(ready['seq']) else v for k,v in ready.items()}
                    known=[o for o in a['orders'] if o[3]<=ready['seq'][cut-1]]
                    partial=execute(part,ds[ds[:,0]<cut],method['exit']=='T',qty,value,finish=False)
                    assert partial['orders']==known
                    for col in ('curve','r_curve','planned_curve'):
                        np.testing.assert_allclose(partial[col],curves[key][col][:cut],atol=1e-6,rtol=0)
                    changed=ready.copy();changed['last']=ready['last'].copy();changed['last'][cut:]*=1.6
                    altered=execute(changed,ds,method['exit']=='T',qty,value,finish=False)
                    assert [o for o in altered['orders'] if o[3]<=ready['seq'][cut-1]]==known
                    for col in ('curve','r_curve','planned_curve'):
                        np.testing.assert_allclose(altered[col][:cut],curves[key][col][:cut],atol=1e-6,rtol=0)
                    future.append(dict(手法=method['id'],セッション=key[0],銘柄=key[1],比率=fraction,一致注文数=len(known)))
        for symbol in ('TOPIX','NK225'):
            accounts=[a for a in method['accounts'] if a['symbol']==symbol]
            summary_audit(accounts,method['summary'][symbol],curves)
            for label,ss in [('前10場',result['sessions'][:10]),('次9場',result['sessions'][10:19]),('後4場',result['sessions'][19:])]:
                summary_audit([a for a in accounts if a['session'] in ss],method['periods'][symbol][label],curves)
            for monday,summary in method['weeks'][symbol].items():
                day=datetime.fromisoformat(monday).date()
                summary_audit([a for a in accounts if 0<=(datetime.fromisoformat(a['session'][:10]).date()-day).days<7],summary,curves)
    output=dict(合格=True,条件数=len(result['methods']),口座数=len(accounting),
                合計={n:sum(a[n] for a in accounting) for n in ('注文数','組数','区間数','異常約定')},
                会計=accounting,未来切断と改変=future,
                コードSHA256={n:hashlib.sha256((TASK/n).read_bytes()).hexdigest() for n in ('signals.py','engine.py','backtest.py')})
    (HERE/'金額と固定Rの独立監査.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    print('全会計合格',len(accounting),'未来比較',len(future),output['合計'],flush=True)


if __name__=='__main__':
    main()
