"""全注文を別の会計で再構成し、一定幅トレーリングと未来不変を監査する。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
TASK = HERE.parent/'exit'
OLD = HERE.parent.parent/'wave_v57'
sys.path.insert(0,str(TASK))
from engine import execute, drive


def same(a: object, b: object, tolerance: float=1e-6) -> None:
    """機能: 浮動小数の演算誤差内の一致を検査する。

    引数: a/b(object)、tolerance(float)。返り値: なし(None)。
    """
    np.testing.assert_allclose(a,b,rtol=0,atol=tolerance)


def fall(curve: np.ndarray) -> float:
    """機能: 初期残高ゼロから時価残高の最大下落を求める。

    引数: curve(ndarray)。返り値: 最大下落(float)。
    """
    return float(np.max(np.maximum.accumulate(np.r_[0.,curve])[1:]-curve,initial=0))


def audit_account(ready: dict, frame: dict, signals: np.ndarray, account: dict, mode: str) -> dict:
    """機能: 原本と各建玉から独立した会計・追跡条件・幅単位を再構成する。

    引数: ready/frame/account(dict)、signals(ndarray)。返り値: 独立曲線(dict)。
    """
    price, time, seq = frame['mid'], ready['time_s'], ready['seq']
    qty, value = (5,1000) if ready['symbol']=='TOPIX' else (10,10)
    holdings=np.zeros(len(price),int)
    realized=np.zeros(len(price));floating=np.zeros(len(price))
    w_realized=np.zeros(len(price));w_floating=np.zeros(len(price))
    assert len(account['orders'])==len(account['trades'])*2==len(account['width_groups'])*2
    previous_exit=-np.inf
    for cycle,(leg,group) in enumerate(zip(account['trades'],account['width_groups'])):
        opening,closing=account['orders'][cycle*2:cycle*2+2]
        for order in (opening,closing):
            decision,fill=np.searchsorted(seq,[order[2],order[3]])
            assert seq[decision]==order[2] and seq[fill]==order[3] and fill==decision+1
            assert order[0]==time[decision] and order[1]==time[fill] and order[7]==price[fill]
            assert order[6]==qty
        assert opening[4]==1 and closing[4]==2 and opening[5]==-closing[5]
        assert opening[11]==qty and closing[11]==0 and opening[9]==0
        assert opening[0]>=previous_exit+60. and opening[0]<ready['limit']-300.
        previous_exit=closing[1]
        begin,end=np.searchsorted(seq,[leg[11],leg[12]])
        assert begin==group[3] and end==group[4] and end>begin and time[end]<ready['limit']+300.
        assert leg[0]==time[begin] and leg[1]==time[end] and leg[4]==price[begin] and leg[5]==price[end]
        assert leg[9]==group[0]==opening[10]==closing[10]==cycle
        assert leg[2]==group[5]==opening[5] and leg[3]==qty and leg[4]==group[6]
        di=np.searchsorted(seq,opening[2]); si=np.searchsorted(signals[:,0],di)
        signal=signals[si]
        assert signal[0]==di and signal[1]==leg[2]
        width=float(signal[2]); same(width,leg[8]);same(width,group[1]);same(width,opening[12]);same(width,closing[12])
        assert width>=2*ready['tick']
        same(width/ready['tick'],round(width/ready['tick']))
        pnl=leg[2]*qty*(leg[5]-leg[4])*value
        same(pnl,leg[6]);same(pnl,closing[8]);same(group[2],pnl/(width*qty*value))
        path=leg[2]*(price[begin:end+1]-leg[4])
        midpath=leg[2]*(frame['mid'][begin:end+1]-frame['mid'][begin])
        mfe=max(0.,float(midpath.max()))/width;mae=max(0.,float(-midpath.min()))/width
        same(leg[14],mfe);same(group[7],mfe);same(group[8],mae)
        same(leg[15],(time[end]-time[begin])/60.)
        # ----------------------------------------
        # 最後の返済約定行を除いた区間で、最初の返済成立位置を直接求める。
        observed=frame['mid'][begin:end]
        best=np.maximum.accumulate(observed) if leg[2]>0 else np.minimum.accumulate(observed)
        trail=best-leg[2]*width
        active=(np.ones(len(best),bool) if mode in ('A','C') else np.zeros(len(best),bool)
                if mode=='B' else leg[2]*(best-price[begin])>=width)
        wall_used=(mode!='C')&((~active)|(leg[2]*(signal[3]-trail)>=0))
        stop=np.where(wall_used,signal[3],trail)
        reached=(leg[2]*(observed-stop)<=0.) | (time[begin:end]>=ready['limit'])
        matches=np.flatnonzero(reached)
        assert len(matches) and int(matches[0])==len(observed)-1
        assert closing[2]==seq[end-1] and closing[0]==time[end-1]
        reason=2 if time[end-1]>=ready['limit'] else (3 if wall_used[-1] else 1)
        assert closing[9]==leg[7]==reason
        assert not holdings[begin:end].any()
        holdings[begin:end]=int(leg[2]*qty)
        floating[begin:end]=path[:-1]*qty*value
        w_floating[begin:end]=path[:-1]/width
        realized[end]+=pnl;w_realized[end]+=group[2]
    curves=dict(curve=np.cumsum(realized)+floating,w_curve=np.cumsum(w_realized)+w_floating)
    assert holdings[-1]==0 and np.max(abs(holdings),initial=0)<=qty
    same(curves['curve'][-1],account['net']);same(curves['w_curve'][-1],account['w_net'])
    same(fall(curves['curve']),account['drawdown']);same(fall(curves['w_curve']),account['w_drawdown'])
    pnl=np.asarray([t[6] for t in account['trades']]); ws=np.asarray([g[2] for g in account['width_groups']])
    same(account['profit'],np.maximum(pnl,0).sum());same(account['loss'],-np.minimum(pnl,0).sum())
    same(account['w_profit'],np.maximum(ws,0).sum());same(account['w_loss'],-np.minimum(ws,0).sum())
    assert account['cycles']==len(pnl) and account['wins']==(pnl>0).sum() and account['losses']==(pnl<0).sum()
    assert account['win_qty']==(pnl>0).sum()*qty and account['loss_qty']==(pnl<0).sum()*qty and account['flat_qty']==(pnl==0).sum()*qty
    previous=0.;cash=np.cumsum(realized)
    for interval in account['intervals']:
        left=datetime.fromisoformat(interval['開始']).timestamp()
        right=datetime.fromisoformat(interval['終了未満']).timestamp()
        j=np.searchsorted(time,right,side='left')-1
        equity=curves['curve'][j] if j>=0 else 0.
        chosen=[t for t in account['trades'] if left<=t[1]<right]
        gains=sum(max(t[6],0.) for t in chosen); losses=sum(max(-t[6],0.) for t in chosen)
        same(interval['利益円'],gains);same(interval['損失円'],losses)
        same(interval['確定収支円'],gains-losses)
        same(interval['時価収支円'],equity-previous)
        same(interval['終了含み円'],equity-(cash[j] if j>=0 else 0.))
        assert interval['利益返済枚数']==sum(t[3] for t in chosen if t[6]>0)
        assert interval['損失返済枚数']==sum(t[3] for t in chosen if t[6]<0)
        previous=equity
    same(sum(r['時価収支円'] for r in account['intervals']),account['net'])
    # ----------------------------------------
    # 各候補を、採用・保有中・締切・返済後休止へ独立に分類する。
    indices=signals[:,0].astype(int)
    labels=np.zeros(len(indices),int)
    exits=[]
    for j in range(account['cycles']):
        opening,closing=account['orders'][2*j:2*j+2]
        begin,end=np.searchsorted(seq,[opening[2],closing[3]])
        labels[(indices>begin)&(indices<end)]=2
        labels[indices==begin]=1
        exits.append(end)
    pending=labels==0
    labels[pending&(time[indices]>=ready['limit']-300.)]=3
    if exits:
        last_exit=np.searchsorted(exits,indices,side='right')-1
        valid=last_exit>=0
        exit_times=np.zeros(len(indices))
        exit_times[valid]=time[np.array(exits)[last_exit[valid]]]
        labels[(labels==0)&valid&(time[indices]<exit_times+60.)]=4
    assert np.all(labels>0)
    expect=dict(consumed=len(indices),accepted=int((labels==1).sum()),occupied=int((labels==2).sum()),
                cutoff=int((labels==3).sum()),cooldown=int((labels==4).sum()),unreached=0)
    assert account['candidate_audit']==expect and account['candidate_count']==len(indices)
    return curves


def optional(actual: object, expected: object) -> None:
    """機能: 未定義比率をゼロ扱いせず照合する。

    引数: actual/expected(object)。返り値: なし(None)。
    """
    if expected is None:
        assert actual is None
    else:
        same(actual,expected)


def audit_summary(accounts: list, expected: dict, curves: dict) -> None:
    """機能: 各期間の損益・枚数・平均比率・幅評価・最大下落を独立集計する。

    引数: accounts(list)、expected/curves(dict)。返り値: なし(None)。
    """
    for name in ('profit','loss','net','win_qty','loss_qty','flat_qty','cycles','wins','losses','w_net'):
        same(expected[name],sum(a[name] for a in accounts))
    groups=np.asarray([g for a in accounts for g in a['width_groups']],float).reshape(-1,9)
    legs=np.asarray([t for a in accounts for t in a['trades']],float).reshape(-1,16)
    ws=groups[:,2]; gains=ws[ws>0]; losses=-ws[ws<0]
    optional(expected['pf'],expected['profit']/expected['loss'] if expected['loss'] else None)
    optional(expected['win_rate'],expected['wins']/expected['cycles'] if expected['cycles'] else None)
    perwin=expected['profit']/expected['win_qty'] if expected['win_qty'] else None
    perloss=expected['loss']/expected['loss_qty'] if expected['loss_qty'] else None
    optional(expected['win_per_lot'],perwin);optional(expected['loss_per_lot'],perloss)
    optional(expected['payoff'],perwin/perloss if perloss and perwin is not None else None)
    assert expected['active_sessions']==sum(a['cycles']>0 for a in accounts)
    assert expected['positive_sessions']==sum(a['net']>0 for a in accounts)
    assert expected['negative_sessions']==sum(a['net']<0 for a in accounts)
    same(expected['without_best'],expected['net']-max([a['net'] for a in accounts],default=0))
    optional(expected['w_mean'],float(ws.mean()) if len(ws) else None)
    optional(expected['median_hold_minutes'],float(np.median(legs[:,15])) if len(legs) else None)
    optional(expected['mean_mfe_width'],float(groups[:,7].mean()) if len(groups) else None)
    optional(expected['mean_hold_minutes'],float(np.mean(legs[:,15])) if len(legs) else None)
    peak=balance=decline=0.
    for account in sorted(accounts,key=lambda x:x['session']):
        path=balance+curves[account['session'],account['symbol']]['curve']
        highs=np.maximum.accumulate(np.r_[peak,path])[1:]
        decline=max(decline,float(np.max(highs-path,initial=0)))
        peak=max(peak,float(np.max(path,initial=peak)))
        balance+=account['net']
    same(expected['drawdown'],decline)
    assert expected['candidate_count']==sum(a['candidate_count'] for a in accounts)
    for name,value in expected['candidate_audit'].items():
        assert value==sum(a['candidate_audit'][name] for a in accounts)
    for name,code in [('中値トレーリング',1),('場内返済',2),('補充壁の保護線割れ',3)]:
        amounts=legs[legs[:,7]==code,6];row=expected['reasons'][name]
        assert row['cycles']==len(amounts)
        same(row['net'],amounts.sum());same(row['profit'],amounts[amounts>0].sum());same(row['loss'],-amounts[amounts<0].sum())


def main() -> None:
    """機能: 全552口座を検算し、一部原本の途中切断と未来価格改変も実施する。

    引数: なし。返り値: なし(None)。保存した成績とコードを変更しない。
    """
    result=json.loads((TASK/'出口対照結果.json').read_text(encoding='utf-8'))
    inputs=pickle.loads((OLD.parent/'wave_v55/clean_inputs.pkl').read_bytes())
    frames=pickle.loads((OLD/'features.pkl').read_bytes())
    signals=pickle.loads((OLD/'判断.pkl').read_bytes())
    original=json.loads((OLD/'売買結果.json').read_text(encoding='utf8'))
    old_accounts={(m['id'],a['session'],a['symbol']):a for m in original['methods'] for a in m['accounts']}
    all_accounts={(m['family'],m['mode'],a['session'],a['symbol']):a for m in result['methods'] for a in m['accounts']}
    keys=sorted(inputs);selected={keys[i] for i in (0,1,22,23,44,45)}
    counts=dict(口座=0,注文=0,返済組=0,区間=0,未来比較=0,A元中値一致=0,入口集合分解=0)
    for method in result['methods']:
        curves={}
        for account in method['accounts']:
            key=account['session'],account['symbol'];ready=inputs[key];ds=signals[key,method['source_id']]
            frame=frames[key]
            curves[key]=audit_account(ready,frame,ds,account,method['mode'])
            qty,value=(5,1000) if key[1]=='TOPIX' else (10,10)
            assert account['source_signal_sha256']==hashlib.sha256(ds.tobytes()).hexdigest()
            if method['mode']=='A':
                baseline=old_accounts[method['source_id'],*key]
                expected=np.asarray(baseline['orders'],float).reshape(-1,13).copy()
                expected[:,7]=frame['mid'][np.searchsorted(ready['seq'],expected[:,3])]
                for i in range(0,len(expected),2):
                    expected[i+1,8]=expected[i,5]*(expected[i+1,7]-expected[i,7])*qty*value
                np.testing.assert_array_equal(np.asarray(account['orders']).reshape(-1,13),expected)
                for field in ('profit','loss','net','win_qty','loss_qty','flat_qty','cycles','wins','losses'):
                    same(account[field],baseline['sensitivity']['中値'][field])
                counts['A元中値一致']+=1
            baseline=all_accounts[method['family'],'A',*key]
            compare=[]
            for source in (baseline,account):
                compare.append({(int(source['orders'][i*2][2]),int(source['orders'][i*2][5])):t[6]
                                for i,t in enumerate(source['trades'])})
            old,new=compare;common=old.keys()&new.keys();added=new.keys()-old.keys();removed=old.keys()-new.keys()
            expected=dict(common_entries=len(common),added_entries=len(added),removed_entries=len(removed),
                          common_baseline_net=sum(old[k] for k in common),common_variant_net=sum(new[k] for k in common),
                          added_variant_net=sum(new[k] for k in added),removed_baseline_net=sum(old[k] for k in removed))
            expected['common_delta']=expected['common_variant_net']-expected['common_baseline_net']
            expected['total_delta']=account['net']-baseline['net']
            assert account['entry_comparison']==expected
            assert expected['total_delta']==expected['common_delta']+expected['added_variant_net']-expected['removed_baseline_net']
            counts['入口集合分解']+=1
            counts['口座']+=1;counts['注文']+=len(account['orders']);counts['返済組']+=account['cycles'];counts['区間']+=len(account['intervals'])
            if key in selected:
                qty,value=(5,1000) if key[1]=='TOPIX' else (10,10)
                for ratio in (.35,.70):
                    cut=int(len(ready['seq'])*ratio)
                    part={k:v[:cut] if isinstance(v,np.ndarray) else v for k,v in ready.items()}
                    known=[o for o in account['orders'] if o[3]<=ready['seq'][cut-1]]
                    partial=execute(part,{k:v[:cut] for k,v in frame.items()},ds[ds[:,0]<cut],qty,value,method['mode'],finish=False)
                    assert partial['orders']==known
                    for col in ('curve','w_curve'):
                        same(partial[col],curves[key][col][:cut])
                    changed=dict(ready,last=ready['last'].copy(),atr=np.full(len(ready['seq']),1e100))
                    changed['last'][cut:]*=1.6
                    changed_frame={k:v.copy() for k,v in frame.items()}
                    for col in ('mid','ask','bid'):
                        changed_frame[col][cut:]*=1.6
                    altered=execute(changed,changed_frame,ds,qty,value,method['mode'],finish=False)
                    assert [o for o in altered['orders'] if o[3]<=ready['seq'][cut-1]]==known
                    for col in ('curve','w_curve'):
                        same(altered[col][:cut],curves[key][col][:cut])
                    counts['未来比較']+=2
        for symbol in ('TOPIX','NK225'):
            accounts=[a for a in method['accounts'] if a['symbol']==symbol]
            audit_summary(accounts,method['summary'][symbol],curves)
            for label,sessions in [('前10場',result['sessions'][:10]),('次9場',result['sessions'][10:19]),('後4場',result['sessions'][19:])]:
                audit_summary([a for a in accounts if a['session'] in sessions],method['periods'][symbol][label],curves)
        print(method['id'],'会計合格',flush=True)
    report=dict(合格=True,条件数=len(result['methods']),件数=counts,
                検査='原本の次行中値約定、A/B/C/D別の最初の保護線到達、候補見送り理由、数量、現金と含み、MFE/MAE、幅単位、期間・30分、途中切断、未来改変、A元評価一致、入口集合分解',
                コードSHA256={name:hashlib.sha256((TASK/name).read_bytes()).hexdigest() for name in ['engine.py','run.py','check_engine.py']})
    (HERE/'出口対照の独立会計監査.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
