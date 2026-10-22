"""実市場を使わず、次原行BBOの実注文会計と三部品を独立に反証する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

import numba
import numpy as np


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
ENGINE=HERE.parents[1]/'engine'
BBO=ENGINE/'bbo_next'
sys.dont_write_bytecode=True
numba.config.CACHE_DIR=str(HERE/'jit')
sys.path[:0]=[str(BBO),str(ENGINE),str(HERE.parents[1]/'design')]
import core126 as core
import policy_bbo126 as interface
from catalog126 import catalog

CHECKS=[]
CASES=[]


def check(name: str, condition: bool) -> None:
    """
    機能: 独立期待値との一致を記録し、不一致では停止する。
    引数: name(str)は検査名、condition(bool)は比較結果。
    返り値: None。
    """
    assert condition,name
    CHECKS.append(name)


def same(name: str, first: object, second: object) -> None:
    """
    機能: 配列同値を確認して記録する。
    引数: name(str)、first/second(object)は比較値。
    返り値: None。
    """
    np.testing.assert_array_equal(first,second,err_msg=name)
    check(name,True)


def fixture(bids: list[float], definitions: list[tuple], quantity: int,
            *, good: list[bool] | None=None, end_row: int | None=None,
            atr: float=4.) -> tuple:
    """
    機能: Last紙上通知とBBO価格を互いに独立な固定人工値で構成する。
    引数: bids(list[float])、definitions(list[tuple])は(cid,entry,exit,side)、quantity(int)、
        good(list[bool]|None)、end_row(int|None)、atr(float)は合成設定。
    返り値: tupleはready,quotes,market,paperの四辞書又は配列。
    """
    bid=np.asarray(bids,float);ask=bid+1.;n=len(bid)
    times=np.arange(n,dtype=float)*301.
    price=(bid+ask)/2.
    symbol='TOPIX' if quantity==5 else 'NK225'
    ready=dict(symbol=symbol,seq=np.arange(n,dtype=np.int64)*3+7,time_s=times,
               last=price,atr=np.full(n,atr),limit=times[-1]+1000. if end_row is None else times[end_row])
    quotes=dict(seq=ready['seq'].copy(),time_s=times.copy(),bid=bid,ask=ask,
                quote_valid=np.ones(n,bool) if good is None else np.array(good,bool))
    market=np.full((n,12),np.nan);market[:,11]=0.
    rows=[];parents=[]
    for cid,entry,exit_row,side in definitions:
        rows.extend([[entry,entry-1,cid,side,quantity,price[entry],20,1],
                     [exit_row,exit_row-1,cid,-side,quantity,price[exit_row],9,0]])
        parents.append([cid,entry,exit_row,-12345,atr*quantity,atr,999999,123456,side,9])
    paper=dict(orders=np.array(sorted(rows,key=lambda x:x[0]),float).reshape((-1,8)),
               cycles=np.array(parents,float).reshape((-1,10)))
    return ready,quotes,market,paper


def market_known(ready: dict, market: np.ndarray) -> np.ndarray:
    """
    機能: 当時両市場が既知で新しい合成市場状態を作る。
    引数: ready(dict)、market(ndarray)は合成元。
    返り値: ndarrayは別配列の十二状態列。
    """
    out=market.copy();t=ready['time_s']
    out[:,0]=100.;out[:,1]=100.;out[:,2:4]=4.
    out[:,4:8]=.2;out[:,8]=t-1.;out[:,9]=t-30.;out[:,10]=t-31.;out[:,11]=1.
    return out


def run(value: tuple, config: dict) -> dict:
    """
    機能: 人工入力だけをBBO公開APIへ渡す。
    引数: value(tuple)は人工四値、config(dict)は全十六固定条件の一つ。
    返り値: dictは経済的人工の結果。
    """
    ready,quotes,market,paper=value
    result=interface.play(config,ready,quotes,market,paper,use_python=True)
    assert all(np.isfinite(result[field]).all() for field in interface.FIELDS), '経済又は診断出力の非有限値'
    audit(value,result)
    CASES.append(dict(id=config['id'],quantity=5 if ready['symbol']=='TOPIX' else 10,
                      orders=len(result['orders']),trades=len(result['trades']),
                      unclosed=int(result['stats'][9])))
    return result


def audit(value: tuple, result: dict) -> None:
    """
    機能: 実注文だけから現金・FIFO玉・返済・全行BBO清算を独立再構築する。
    引数: value(tuple)、result(dict)は固定人工入力と被監査値。
    返り値: None。被監査の内部会計関数を期待値生成に使わない。
    """
    ready,q,market,paper=value
    orders,trades,curve,stats=result['orders'],result['trades'],result['curve'],result['stats']
    positions=[];cash=0.;realized=0.;expected_trades=[];markbid=np.nan;markask=np.nan
    maxlong=0;maxshort=0;peak=0.;dd=0.;uids=set()
    for i in range(len(ready['time_s'])):
        good=bool(q['quote_valid'][i] and np.isfinite(q['bid'][i]) and np.isfinite(q['ask'][i]) and 0<q['bid'][i]<q['ask'][i])
        if good:markbid=q['bid'][i];markask=q['ask'][i]
        indices=np.flatnonzero(orders[:,0]==i)
        for oi in indices:
            o=orders[oi];row,source,cid,side,qty=map(int,o[:5]);price=o[5]
            assert source<row and good
            assert price==(q['ask'][i] if side>0 else q['bid'][i])
            cash-=side*qty*price
            if o[7]==1:
                uid=int(result['order_uids'][oi]);assert uid>=0 and uid not in uids;uids.add(uid)
                positions.append(dict(qty=qty,side=side,cid=cid,price=price,row=row,uid=uid))
            else:
                left=qty
                for p in positions:
                    if left==0:break
                    if p['qty']==0 or p['cid']!=cid or p['side']!=-side:continue
                    take=min(p['qty'],left);gain=p['side']*take*(price-p['price'])
                    expected_trades.append([cid,p['uid'],p['side'],take,p['price'],price,p['row'],row,0,o[6],gain])
                    realized+=gain;p['qty']-=take;left-=take
                assert left==0
        longqty=sum(p['qty'] for p in positions if p['side']>0)
        shortqty=sum(p['qty'] for p in positions if p['side']<0)
        assert not(longqty and shortqty)
        maxlong=max(maxlong,longqty);maxshort=max(maxshort,shortqty)
        liquidation=longqty*markbid-shortqty*markask if longqty or shortqty else 0.
        equity=cash+liquidation;peak=max(peak,equity);dd=max(dd,peak-equity)
        np.testing.assert_allclose(curve[i,:7],np.array([equity,realized,longqty,shortqty,dd,cash,longqty-shortqty]),atol=1e-8,rtol=0.)
    expected=np.array(expected_trades,float).reshape((-1,11))
    np.testing.assert_allclose(trades,expected,atol=1e-8,rtol=0.)
    np.testing.assert_allclose(stats[[0,1,2,3,9]],[realized,dd,maxlong,maxshort,longqty+shortqty],atol=1e-8,rtol=0.)
    if not longqty and not shortqty:
        assert abs(cash-realized)<1e-8 and abs(result['cycles'][:,3].sum()-realized)<1e-8
    CHECKS.append('独立FIFOと現金及び全行BBO清算_'+str(len(CASES)))


def mirror(value: tuple) -> tuple:
    """
    機能: 固定200を中心に売買・BBO・市場方向を上下反射する。
    引数: value(tuple)は合成四値。
    返り値: tupleは経済的に対称な別入力。
    """
    r,q,m,p=deepcopy(value)
    r['last']=200.-r['last'];q['bid'],q['ask']=200.-q['ask'],200.-q['bid']
    m[:,:2]=200.-m[:,:2];m[:,4:8]*=-1.
    p['orders'][:,3]*=-1.;p['orders'][:,5]=200.-p['orders'][:,5]
    p['cycles'][:,8]*=-1.
    return r,q,m,p


def mirrored_check(value: tuple, config: dict, result: dict) -> None:
    """
    機能: 上下反射が収支・数量・注文時刻を変えないことを独立確認する。
    引数: value(tuple)、config/result(dict)は元人工と固定条件・元結果。
    返り値: None。
    """
    reflected=run(mirror(value),config)
    for field in ('curve','stats'):
        columns=[0,1,4] if field=='curve' else [0,1,9]
        same('上下反射収支_'+config['id']+'_'+field,result[field][:,columns] if field=='curve' else result[field][columns],
             reflected[field][:,columns] if field=='curve' else reflected[field][columns])
    same('上下反射の発注元行_'+config['id'],result['orders'][:,:3],reflected['orders'][:,:3])
    same('上下反射の注文方向_'+config['id'],result['orders'][:,3],-reflected['orders'][:,3])


def timing_checks(configs: dict) -> None:
    """
    機能: 次正常原行・撤回・既予約優先・実予算・場末欠測を反証する。
    引数: configs(dict)は固定条件の対応。
    返り値: None。
    """
    config=configs['E01']
    for qty in (5,10):
        base=fixture([100,100,100,101,102,103,104],[(0,1,5,1)],qty)
        r=run(base,config)
        same('新規返済は各次行_'+str(qty),r['orders'][:,0],np.array([2.,6.]))
        same('買ask売bid_'+str(qty),r['orders'][:,5],np.array([101.,104.]))
        delayed=fixture([100]*7,[(0,1,2,1)],qty,good=[True,True,False,True,True,True,True])
        dr=run(delayed,config);check('正常待ち中に影撤回で取消_'+str(qty),len(dr['orders'])==0)
        racing=fixture([100]*7,[(0,1,2,1)],qty)
        rr=run(racing,config);same('既予約新規を当行影返済で遡及取消しない_'+str(qty),rr['orders'][:,0],np.array([2.,3.]))
        invalid=fixture([100]*8,[(0,1,6,1)],qty)
        invalid[1]['bid'][2]=102.;invalid[1]['ask'][2]=101.
        ir=run(invalid,config);check('crossed BBOはvalidTrueでも発注しない_'+str(qty),ir['orders'][0,0]==3.)
        budget=fixture([110,110,110,105,106,108,109],[(0,1,5,1)],qty)
        br=run(budget,config)
        check('実建値111から1ATR4の逆行で次行予算返済_'+str(qty),br['orders'][-1,0]==4. and br['orders'][-1,5]==106. and br['orders'][-1,6]==32.)
        same('実建値予算は紙上entry価格依存でない_'+str(qty),br['trades'][:,10],np.array([-5.*qty]))
        queued=fixture([100,100,100,96,95,94,93,92],[(0,1,3,1)],qty)
        queued[3]['orders'][1,4]=qty//2
        queued[3]['orders']=np.vstack([queued[3]['orders'],[5,4,0,-1,qty-qty//2,94.5,9,0]])
        qr=run(queued,config)
        same('部分返済予約を先行し予算残玉は次行_'+str(qty),qr['orders'][:,0],np.array([2.,4.,5.]))
        same('部分返済と予算返済の数量保存_'+str(qty),qr['orders'][:,4],np.array([qty,qty//2,qty-qty//2]))
        terminal=fixture([100]*8,[(0,1,5,1)],qty,good=[True,True,True,True,False,False,False,False],end_row=6)
        tr=run(terminal,config)
        check('場末正常気配無しで架空返済しない_'+str(qty),len(tr['orders'])==1 and tr['stats'][9]==qty)
        try:interface.normalized_summary(tr,terminal[0])
        except AssertionError:check('未返済を完成損益として通さない_'+str(qty),True)
        else:raise AssertionError('未返済が成功扱い')


def mechanism_cases(qty: int) -> dict:
    """
    機能: P/A/Lの有効枝と反例を経済結果とは独立な固定合成経路で用意する。
    引数: qty(int)は5又は10。
    返り値: dict[str,tuple]は三つの人工経路。
    """
    p=fixture([100,100,100,110,114,108,107,106,105,104,104,104,104],[(0,1,10,1)],qty)
    p[2][:]=market_known(p[0],p[2]);p[2][:,4:8]=0.;p[2][4,4:8]=[-.2,-.3,-.2,-.3]
    a=fixture([100,100,100,100,99,99,100,100,100,101,101,101,101,101,101,101,103,103,104,104,104],
              [(0,1,4,1),(1,6,8,1),(2,9,11,1),(3,14,18,1)],qty)
    a[2][:]=market_known(a[0],a[2]);a[2][9:,0:2]=101.5
    a[2][9:,9]=a[0]['time_s'][6];a[2][9:,10]=a[0]['time_s'][6]-1.
    l=fixture([100,100,100,97,96,96,96,96,96,96,96,96,96,97,97,97,97],
              [(0,1,5,1),(1,7,9,1),(2,11,15,1)],qty)
    return dict(P=p,A=a,L=l)


def mechanisms(configs: dict) -> None:
    """
    機能: 全16条件・両数量・上下反射で全会計を検算し、P/A/L各効果を独立確認する。
    引数: configs(dict)は全固定条件。
    返り値: None。
    """
    for qty in (5,10):
        cases=mechanism_cases(qty)
        for label,value in cases.items():
            for config in configs.values():
                result=run(value,config);mirrored_check(value,config,result)
        p=run(cases['P'],configs['P01'])
        check('P両市場反対後に利益床予約_'+str(qty),p['orders'][-1,0]==7. and p['orders'][-1,6]==70.)
        noopp=deepcopy(cases['P']);noopp[2][:,4:8]=0.
        nr=run(noopp,configs['P01']);check('P利益額のみでは床を起動しない_'+str(qty),not np.any(nr['execution_events'][:,1]==12.))
        stale=deepcopy(cases['P']);stale[2][:,8]=stale[0]['time_s'][2]
        sr=run(stale,configs['P01']);check('P新規後更新前の相手を使わない_'+str(qty),not np.any(sr['execution_events'][:,1]==12.))
        a=run(cases['A'],configs['A01']);ev=a['execution_events']
        check('A実赤字だけで同方向を止める_'+str(qty),np.any(ev[:,1]==11.))
        release=ev[ev[:,1]==14.];check('A新しい両アンカー進行で解除_'+str(qty),len(release)>0 and release[0,0]==9.)
        same('A解除当行候補は遡及新規しない_'+str(qty),a['orders'][a['orders'][:,7]==1.,0],np.array([2.,15.]))
        l=run(cases['L'],configs['L01']);check('L初回固定riskの場損失で停止_'+str(qty),np.any(l['execution_events'][:,1]==10.))
        check('L停止後の紙上親を実新規しない_'+str(qty),not np.any((l['orders'][:,2]==2)&(l['orders'][:,7]==1)))


def future_checks(configs: dict) -> None:
    """
    機能: 未来PL・終了情報・未来価格が過去注文に影響しないことを確認する。
    引数: configs(dict)は固定条件。
    返り値: None。
    """
    base=mechanism_cases(5)['A']
    for config in configs.values():
        first=run(base,config)
        changed=deepcopy(base)
        for col in (1,2,3,4,6,7,8,9):changed[3]['cycles'][:,col]=np.arange(len(changed[3]['cycles']))*1e12+999999.
        np.testing.assert_array_equal(interface.make_feed(base[3]),interface.make_feed(changed[3]))
        other=run(changed,config)
        for field in ('orders','trades','curve','stats'):
            same('未来親終了PL極値を利用しない_'+config['id']+'_'+field,first[field],other[field])
        cut=10;modified=deepcopy(base)
        modified[1]['bid'][cut:]+=10.;modified[1]['ask'][cut:]+=10.
        modified[0]['last'][cut:]+=5000.;modified[2][cut:,:2]+=3000.
        altered=run(modified,config)
        same('未来価格改変で過去時価不変_'+config['id'],first['curve'][:cut],altered['curve'][:cut])
        same('未来価格改変で過去注文不変_'+config['id'],first['orders'][first['orders'][:,0]<cut],altered['orders'][altered['orders'][:,0]<cut])
    bad=deepcopy(base[3]);bad['orders'][0,6]=32.
    try:interface.make_feed(bad)
    except AssertionError:check('紙上へ実予算32が混入したfeed拒否',True)
    else:raise AssertionError('実予算を含む紙上feedを通過')


def execute() -> None:
    """
    機能: BBO別段階の独立純人工だけを実行し、適用源指紋を保存する。
    引数: なし。
    返り値: None。実市場本文・追加金融・APIは使用しない。
    """
    configs={v['id']:v for v in catalog()}
    expected={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (BBO/'core126.py',BBO/'bbo_order_kernel126.py',BBO/'policy_bbo126.py',ENGINE/'policy126.py',HERE.parents[1]/'design/catalog126.py')}
    timing_checks(configs);mechanisms(configs);future_checks(configs)
    assert all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in expected.items())
    result=dict(passed=True,checks=CHECKS,count=len(CHECKS),cases=CASES,case_count=len(CASES),sources=expected,
        producer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        market_reads=0,financial_replays=0,API=0,real_orders=0,
        contract='固定人工のみ。被監査の会計核を期待値へ流用せず、実注文からFIFOと全行BBO清算を再構築。実商品の約定実績ではない。')
    path=HERE/'次正常原行と実会計及び三部品の独立純人工.json';assert not path.exists()
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,checks=len(CHECKS),cases=len(CASES),market_reads=0,financial_replays=0),ensure_ascii=False))


if __name__=='__main__':
    try:execute()
    except Exception as error:
        path=HERE/('純人工停止_'+str(time.time_ns())+'.json')
        path.write_text(json.dumps(dict(passed=False,error=repr(error),checks=CHECKS,cases=CASES,
            market_reads=0,financial_replays=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
