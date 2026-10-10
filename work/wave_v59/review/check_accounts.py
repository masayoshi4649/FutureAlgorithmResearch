"""全口座の注文・時価・出口先着・価格感度を独立会計で点検する。"""

from __future__ import annotations

import argparse
from datetime import datetime,timedelta
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE=Path(__file__).resolve().parent
TASK=HERE.parent
sys.path.insert(0,str(TASK))
import engine


def same(a: object,b: object,tolerance: float=1e-6) -> None:
    """機能: 演算誤差内の一致を確かめる。

    引数: a/b(object)、tolerance(float)。返り値: なし(None)。
    """
    np.testing.assert_allclose(a,b,rtol=0,atol=tolerance)


def optional(a: object,b: object) -> None:
    """機能: 未定義比率と数値を区別して照合する。

    引数: a/b(object)。返り値: なし(None)。
    """
    if b is None:
        assert a is None
    else:
        same(a,b)


def dd(curve: np.ndarray) -> float:
    """機能: 初期資産ゼロを含む最大資産減少を計算する。

    引数: curve(ndarray)。返り値: 最大資産減少(float)。
    """
    return float(np.max(np.maximum.accumulate(np.r_[0.,curve])[1:]-curve,initial=0))


def statistics(pnls: np.ndarray,qty: int,view: dict) -> None:
    """機能: 返済損益から金額・枚数・平均比を別計算する。

    引数: pnls(ndarray)、qty(int)、view(dict)。返り値: なし(None)。
    """
    p=float(pnls[pnls>0].sum());l=float(-pnls[pnls<0].sum())
    same(view['profit'],p);same(view['loss'],l);same(view['net'],p-l)
    wins=int((pnls>0).sum());losses=int((pnls<0).sum());flat=int((pnls==0).sum())
    assert view['cycles']==len(pnls) and view['wins']==wins and view['losses']==losses
    assert view['win_qty']==wins*qty and view['loss_qty']==losses*qty and view['flat_qty']==flat*qty
    pw=p/(wins*qty) if wins else None;pl=l/(losses*qty) if losses else None
    optional(view['pf'],p/l if l else None)
    optional(view['win_rate'],wins/len(pnls) if len(pnls) else None)
    optional(view['win_per_lot'],pw);optional(view['loss_per_lot'],pl)
    optional(view['payoff'],pw/pl if pw is not None and pl else None)


def interval_check(intervals: list,trades: np.ndarray,curve: np.ndarray,realized: np.ndarray,times: np.ndarray) -> None:
    """機能: 30分区間の確定・含み・枚数を約定時刻から照合する。

    引数: intervals(list)、trades/curve/realized/times(ndarray)。返り値: なし(None)。
    """
    previous=0.;cash=np.cumsum(realized)
    for row in intervals:
        left=datetime.fromisoformat(row['開始']).timestamp();right=datetime.fromisoformat(row['終了未満']).timestamp()
        i=np.searchsorted(times,right,side='left')-1
        equity=curve[i] if i>=0 else 0.
        legs=trades[(trades[:,1]>=left)&(trades[:,1]<right)]
        p=legs[legs[:,6]>0,6].sum();l=-legs[legs[:,6]<0,6].sum()
        same(row['利益円'],p);same(row['損失円'],l);same(row['確定収支円'],p-l)
        same(row['時価収支円'],equity-previous);same(row['終了含み円'],equity-(cash[i] if i>=0 else 0.))
        assert row['利益返済枚数']==legs[legs[:,6]>0,3].sum()
        assert row['損失返済枚数']==legs[legs[:,6]<0,3].sum()
        previous=equity
    same(sum(r['時価収支円'] for r in intervals),trades[:,6].sum())


def account_check(ready: dict,quotes: dict,source: np.ndarray,account: dict,method: dict) -> tuple:
    """機能: 各建玉の全経路から最初の退出成立・会計・数量を再構成する。

    引数: ready/quotes/account/method(dict)、source(ndarray)。
    返り値: 中値と気配の独立時価曲線(tuple[ndarray,ndarray])。
    """
    time,seq,mid=ready['time_s'],ready['seq'],quotes['mid']
    qty,value=(5,1000.) if ready['symbol']=='TOPIX' else (10,10.)
    orders=np.asarray(account['orders'],float).reshape(-1,13)
    legs=np.asarray(account['trades'],float).reshape(-1,16)
    groups=np.asarray(account['width_groups'],float).reshape(-1,9)
    modes=np.asarray(account['trade_modes'],int).reshape(-1,2)
    assert len(orders)==len(legs)*2==len(groups)*2==len(modes)*2
    assert hashlib.sha256(source.tobytes()).hexdigest()==account['source_signal_sha256']
    holdings=np.zeros(len(mid),int)
    realized=np.zeros((2,len(mid)));floating=np.zeros_like(realized)
    wr=np.zeros_like(realized);wf=np.zeros_like(realized)
    quote_legs=legs.copy()
    fills=np.searchsorted(seq,orders[:,3])
    expected_quote=np.where(orders[:,5]>0,quotes['ask'][fills],quotes['bid'][fills])
    same(account['quote_order_prices'],expected_quote)
    prev_exit=-np.inf
    for c,(leg,group,mode) in enumerate(zip(legs,groups,modes)):
        opening,closing=orders[2*c:2*c+2]
        for order in (opening,closing):
            d,f=np.searchsorted(seq,[order[2],order[3]])
            assert seq[d]==order[2] and seq[f]==order[3] and f==d+1
            assert order[0]==time[d] and order[1]==time[f] and order[7]==mid[f] and order[6]==qty
        begin,end=np.searchsorted(seq,[leg[11],leg[12]])
        d=np.searchsorted(seq,opening[2]);signal=source[np.searchsorted(source[:,0],d)]
        assert signal[0]==d and signal[1]==leg[2] and opening[5]==leg[2]==group[5]==-closing[5]
        assert opening[4]==1 and closing[4]==2 and opening[11]==qty and closing[11]==0 and opening[9]==0
        assert opening[0]>=prev_exit+60 and opening[0]<ready['limit']-300
        prev_exit=closing[1]
        assert begin==group[3] and end==group[4] and end>begin and time[end]<ready['limit']+300
        assert leg[0]==time[begin] and leg[1]==time[end] and leg[4]==mid[begin] and leg[5]==mid[end]
        assert group[0]==leg[9]==opening[10]==closing[10]==c and leg[3]==qty and group[6]==leg[4]
        width=signal[2]
        same([leg[8],group[1],opening[12],closing[12]],[width]*4)
        same(width/ready['tick'],round(width/ready['tick']));assert width>=2*ready['tick']
        actual=3 if method['family']=='A1' and signal[5]==1 else int(method['exit_id'][1:])
        assert mode[0]==actual and mode[1]==signal[5]
        path=leg[2]*(mid[begin:end+1]-mid[begin]);pnl=path[-1]*qty*value
        same([leg[6],closing[8]],[pnl,pnl]);same(group[2],pnl/(width*qty*value))
        same([leg[14],group[7]],[max(0.,path.max())/width]*2);same(group[8],max(0.,-path.min())/width)
        same(leg[15],(time[end]-time[begin])/60.)
        # ----------------------------------------
        # 更新直後の中値ごとに出口を求め、最初の成立が保存判断行と一致するか検査する。
        observed=mid[begin:end];best=np.maximum.accumulate(observed) if leg[2]>0 else np.minimum.accumulate(observed)
        half=np.ceil(.5*width/ready['tick']-1e-10)*ready['tick']
        active=(np.ones(len(best),bool) if actual==3 else (leg[2]*(best-leg[4])>=half) if actual==2 else np.zeros(len(best),bool))
        trail=best-leg[2]*(half if actual==2 else width)
        initial=leg[4]-leg[2]*width
        use=active&(leg[2]*(trail-initial)>0)
        stop=np.where(use,trail,initial)
        target=width if actual==1 else np.ceil(1.5*width/ready['tick']-1e-10)*ready['tick']
        reason=np.zeros(len(observed),int)
        reason[(actual!=3)&(time[begin:end]-time[begin]>=600)]=4
        reason[(actual!=3)&(leg[2]*(observed-leg[4])>=target)]=2
        reason[(observed<signal[3])|(observed>signal[4])]=5
        stop_hit=leg[2]*(observed-stop)<=0
        reason[stop_hit]=np.where(use[stop_hit]|(actual==3),3,1)
        reason[time[begin:end]>=ready['limit']]=6
        reached=np.flatnonzero(reason)
        assert len(reached) and reached[0]==len(reason)-1
        assert closing[9]==leg[7]==reason[-1] and closing[2]==seq[end-1] and closing[0]==time[end-1]
        assert not holdings[begin:end].any();holdings[begin:end]=int(leg[2]*qty)
        qp=leg[2]*(expected_quote[2*c+1]-expected_quote[2*c])*qty*value
        quote_legs[c,4:7]=[expected_quote[2*c],expected_quote[2*c+1],qp]
        for j,(entryprice,net) in enumerate(((mid[begin],pnl),(expected_quote[2*c],qp))):
            realized[j,end]+=net;wr[j,end]+=net/(width*qty*value)
            floating[j,begin:end]=leg[2]*(mid[begin:end]-entryprice)*qty*value
            wf[j,begin:end]=leg[2]*(mid[begin:end]-entryprice)/width
    curves=np.cumsum(realized,axis=1)+floating;wcurves=np.cumsum(wr,axis=1)+wf
    assert holdings[-1]==0 and np.max(abs(holdings),initial=0)<=qty
    for j,(view,ls) in enumerate(((account,legs),(account['sensitivity']['売買気配'],quote_legs))):
        statistics(ls[:,6],qty,view)
        same(curves[j,-1],view['net']);same(wcurves[j,-1],view['w_net'])
        same(dd(curves[j]),view['drawdown']);same(dd(wcurves[j]),view['w_drawdown'])
        interval_check(view['intervals'],ls,curves[j],realized[j],time)
    same(account['w_profit'],groups[groups[:,2]>0,2].sum());same(account['w_loss'],-groups[groups[:,2]<0,2].sum())
    # ----------------------------------------
    # 採用・保有・締切・休止の優先を注文から別に求める。
    indices=source[:,0].astype(int);labels=np.zeros(len(source),int);exits=[]
    for c in range(len(legs)):
        opening,closing=orders[2*c:2*c+2]
        b,e=np.searchsorted(seq,[opening[2],closing[3]])
        labels[(indices>b)&(indices<e)]=2;labels[indices==b]=1;exits.append(e)
    labels[(labels==0)&(time[indices]>=ready['limit']-300)]=3
    if exits:
        which=np.searchsorted(exits,indices,side='right')-1;valid=which>=0
        et=np.zeros(len(indices));et[valid]=time[np.array(exits)[which[valid]]]
        labels[(labels==0)&valid&(time[indices]<et+60)]=4
    assert np.all(labels>0)
    expected=dict(consumed=len(source),accepted=int((labels==1).sum()),occupied=int((labels==2).sum()),
                  cutoff=int((labels==3).sum()),cooldown=int((labels==4).sum()),unreached=0)
    assert account['candidate_audit']==expected and account['candidate_count']==len(source)
    return curves


def summary_check(accounts: list,expected: dict,curves: dict) -> None:
    """機能: 各銘柄の全期間・部分期間の集計を台帳から照合する。

    引数: accounts(list)、expected/curves(dict)。返り値: なし(None)。
    """
    qty=5 if accounts[0]['symbol']=='TOPIX' else 10
    for j,view in enumerate((expected,expected['sensitivity']['売買気配'])):
        selected=[a if j==0 else a['sensitivity']['売買気配'] for a in accounts]
        for field in ('profit','loss','net','win_qty','loss_qty','flat_qty','cycles','wins','losses','w_net'):
            same(view[field],sum(a[field] for a in selected))
        assert view['positive_sessions']==sum(a['net']>0 for a in selected)
        assert view['negative_sessions']==sum(a['net']<0 for a in selected)
        assert view['active_sessions']==sum(a['cycles']>0 for a in selected)
        same(view['without_best'],view['net']-max(a['net'] for a in selected))
        optional(view['pf'],view['profit']/view['loss'] if view['loss'] else None)
        pw=view['profit']/view['win_qty'] if view['win_qty'] else None
        pl=view['loss']/view['loss_qty'] if view['loss_qty'] else None
        optional(view['payoff'],pw/pl if pw is not None and pl else None)
        balance=peak=drawdown=0.
        for a in sorted(accounts,key=lambda x:x['session']):
            path=balance+curves[a['session'],a['symbol']][j]
            highs=np.maximum.accumulate(np.r_[peak,path])[1:]
            drawdown=max(drawdown,float(np.max(highs-path,initial=0)))
            peak=max(peak,float(path.max()));balance+=(a if j==0 else a['sensitivity']['売買気配'])['net']
        same(view['drawdown'],drawdown)
    assert expected['candidate_count']==sum(a['candidate_count'] for a in accounts)
    for field,value in expected['candidate_audit'].items():
        assert value==sum(a['candidate_audit'][field] for a in accounts)
    legs=np.asarray([t for a in accounts for t in a['trades']],float).reshape(-1,16)
    optional(expected['median_hold_minutes'],float(np.median(legs[:,15])) if len(legs) else None)
    for number,name in engine.REASONS.items():
        if not number:
            continue
        chosen=legs[legs[:,7]==number,6];r=expected['reasons'][name]
        assert r['cycles']==len(chosen)
        same(r['net'],chosen.sum());same(r['profit'],chosen[chosen>0].sum());same(r['loss'],-chosen[chosen<0].sum())


def main() -> None:
    """機能: 指定段階の全会計と途中切断を検査し証跡を保存する。

    引数: CLI --stage dev/holdout(str)。返り値: なし(None)。原本は再読取しない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=('dev','holdout'),required=True)
    stage=parser.parse_args().stage
    data=TASK if stage=='dev' else TASK/'holdout'
    result=json.loads((TASK/stage/'売買結果.json').read_text(encoding='utf-8'))
    inputs=pickle.loads((data/'inputs.pkl').read_bytes());quotes=pickle.loads((data/'quotes.pkl').read_bytes())
    candidates=pickle.loads((data/'入口候補.pkl').read_bytes())
    keys=sorted(inputs);chosen=set(keys[:2]+keys[-2:])
    totals=dict(口座=0,注文=0,返済組=0,価格別区間=0,接頭辞と未来改変=0,期間集計=0)
    for m in result['methods']:
        curves={}
        for a in m['accounts']:
            key=a['session'],a['symbol'];r=inputs[key];q=quotes[key]
            source=candidates[key][m['setting_id']][m['family']]
            curves[key]=account_check(r,q,source,a,m)
            totals['口座']+=1;totals['注文']+=len(a['orders']);totals['返済組']+=len(a['trades'])
            totals['価格別区間']+=len(a['intervals'])*2
            if key in chosen:
                qty,value=(5,1000.) if key[1]=='TOPIX' else (10,10.)
                for size in (len(q['mid'])//3,len(q['mid'])*3//4):
                    cutsource=source[source[:,0]<size]
                    actual=engine.drive(r['time_s'][:size],r['seq'][:size],q['mid'][:size],cutsource,
                                        qty,value,r['tick'],r['limit'],int(m['exit_id'][1:]),m['family']=='A1',False)
                    expected=np.array([o for o in a['orders'] if o[3]<=r['seq'][size-1]]).reshape(-1,13)
                    np.testing.assert_array_equal(actual[0],expected)
                    future=q['mid'].copy();future[size:]+=100*r['tick']
                    changed=engine.drive(r['time_s'],r['seq'],future,source,qty,value,r['tick'],r['limit'],
                                         int(m['exit_id'][1:]),m['family']=='A1',False)
                    past=changed[0][changed[0][:,3]<=r['seq'][size-1]]
                    np.testing.assert_array_equal(actual[0],past)
                    totals['接頭辞と未来改変']+=1
        for symbol in ('TOPIX','NK225'):
            acc=[a for a in m['accounts'] if a['symbol']==symbol]
            summary_check(acc,m['summary'][symbol],curves);totals['期間集計']+=1
            sections=[('前10場',result['sessions'][:10]),('次9場',result['sessions'][10:19]),('後4場',result['sessions'][19:])] if stage=='dev' else [('追加2場',result['sessions'])]
            for label,sessions in sections:
                summary_check([a for a in acc if a['session'] in sessions],m['periods'][symbol][label],curves);totals['期間集計']+=1
        print(m['id'],totals['口座'],flush=True)
    evidence={'合格':True,'段階':stage,**totals,'API取得数':0,'原本再読取数':0,
              '結果SHA256':hashlib.sha256((TASK/stage/'売買結果.json').read_bytes()).hexdigest()}
    (HERE/f'{stage}_全口座の独立会計監査.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False))


if __name__=='__main__':
    main()
