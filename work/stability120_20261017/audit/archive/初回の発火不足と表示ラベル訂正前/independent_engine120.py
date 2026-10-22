"""段階追尾・在庫管理を人工経路と独立会計だけで敵対的に検査する。"""

from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np


HERE=Path(__file__).resolve().parent
SOURCE=HERE.parent/'engine120.py'
EXPECTED='aaa2f4ed234f49c4f00b6dcfff7d66db6dd23c684ed0d6dbee15aebea27e4c16'
CHECKS=Counter()


def check(value: bool,label: str) -> None:
    """
    機能: 意味別の独立期待を確認する。
    引数: value(bool)、label(str)は判定と内容。
    返り値: None。失敗時は市場へ進めず例外とする。
    """
    assert value,label
    CHECKS[label]+=1


def near(actual: object,expected: object,label: str) -> None:
    """
    機能: 会計値と独立手計算を有限精度で照合する。
    引数: actual/expected(object)、label(str)は比較対象と内容。
    返り値: None。不一致なら停止する。
    """
    check(np.allclose(actual,expected,rtol=1e-10,atol=1e-7,equal_nan=True),label)


def material(mids: object,mode: int=0,cap: int=2,fee: float=41.8,multiplier: float=1000.,trail: float=1.,
             close: float|None=None,cut: int|None=None,rows: np.ndarray|None=None,times: np.ndarray|None=None) -> tuple:
    """
    機能: 実在市場と無関係の対称気配・原row・場内期限を構成する。
    引数: mids(object)、mode/cap(int)、費用・倍率・幅・時刻及び任意原row配列。
    返り値: tupleは核心へ渡す全引数。cutは未来を含めず先頭だけへ切る。
    """
    mid=np.asarray(mids,float);n=len(mid)
    rr=np.arange(n,dtype=np.int64)*3+10 if rows is None else np.asarray(rows,np.int64)
    tt=np.arange(n,dtype=float) if times is None else np.asarray(times,float)
    finish=float(n-3) if close is None else float(close)
    used=n if cut is None else cut
    return (rr[:used],tt[:used],mid[:used],mid[:used]-.1,mid[:used]+.1,cap,multiplier,fee,1.,.01,mode,trail,0.,finish-2.,finish,float(n+10))


def accounting(args: tuple,result: tuple) -> dict:
    """
    機能: 実注文だけからUID現金・両方向在庫・全正常行清算時価・玉会計を独立計算する。
    引数: args(tuple)は人工観測、result(tuple)は核心の注文・玉・曲線・集計。
    返り値: dictは原row別状態。戦略の新規/返済条件は再実装しない。
    """
    rows,times,last,bid,ask,cap,multiplier,fee,_,_,mode,_,start,_,close,end=args
    orders,lots,curve,summary=result;fee_one=int(math.floor(fee+1e-9))
    check(orders.ndim==2 and orders.shape[1]==18 and lots.ndim==2 and lots.shape[1]==19 and curve.ndim==2 and curve.shape[1]==8,'注文18・玉19・曲線8列')
    check(np.all(orders[:,4]>orders[:,3]) and np.all(orders[:,6]>=orders[:,5]),'同row約定禁止と時計先後')
    check(np.all(orders[:,11]==1.) and np.all(orders[:,8]==fee_one),'一枚別注文と毎注文切捨て')
    check(np.all(np.isin(orders[:,1],[1.,2.])) and np.all(np.isin(orders[:,2],[-1.,1.])),'注文種別と売買方向')
    check(np.all(np.diff(orders[:,4])>=0),'注文fill原row順')
    state={};cash=0.;realized=0.;paid=0.;peak=0.;maxdd=0.;minimum=0.;snapshots={};certificates=[];last_clock=-math.inf;rejected=0
    for i,raw in enumerate(rows):
        now=times[i]
        if not math.isfinite(now) or now<start or now>end or now<last_clock or not (math.isfinite(bid[i]) and math.isfinite(ask[i]) and 0<bid[i]<=ask[i]):
            rejected+=1;continue
        last_clock=now
        own=orders[orders[:,4]==raw]
        for order in own:
            uid,kind,side=int(order[0]),int(order[1]),int(order[2])
            near(order[[6,7,13,14,15]],[now,ask[i] if side==1 else bid[i],last[i],bid[i],ask[i]],'订单价格来自该原row BBO')
            matches=np.flatnonzero(rows==int(order[3]));check(len(matches)==1,'判断原row存在且唯一')
            decision=int(matches[0]);near(order[5],times[decision],'判断time对应原row')
            if kind==1:
                check(uid not in state,'新UID不重复')
                state[uid]={'side':side,'entry':order[7],'fee':fee_one,'entry_order':order.copy(),'open':True,'mfe':side*((bid[i] if side==1 else ask[i])-order[7])*multiplier-2*fee_one,'mae':side*((bid[i] if side==1 else ask[i])-order[7])*multiplier-2*fee_one}
                cash-=fee_one
            else:
                check(uid in state and state[uid]['open'] and side==-state[uid]['side'],'返済は実在UIDの反対注文')
                item=state[uid];gross=item['side']*(order[7]-item['entry'])*multiplier;net=gross-2*fee_one
                near(order[16],net,'返済注文netは両道料後')
                item['open']=False;cash+=gross-fee_one;realized+=net
                item['mfe']=max(item['mfe'],net);item['mae']=min(item['mae'],net)
                certificates.append((uid,order.copy(),gross,net,item.copy()))
            paid+=fee_one
        active=[(uid,item) for uid,item in state.items() if item['open']]
        long=sum(item['side']==1 for _,item in active);short=sum(item['side']==-1 for _,item in active)
        check(long<=cap and short<=cap,'各方向の実保有上限')
        if mode in (1,2):check(long*short==0,'NET/FLIPは対向を実保有で重ねない')
        equity=cash
        for uid,item in active:
            gross=item['side']*((bid[i] if item['side']==1 else ask[i])-item['entry'])*multiplier
            net=gross-2*fee_one;item['mfe']=max(item['mfe'],net);item['mae']=min(item['mae'],net)
            equity+=gross-fee_one
        peak=max(peak,equity);maxdd=max(maxdd,peak-equity);minimum=min(minimum,equity)
        snapshots[int(raw)]={'row':int(raw),'time':now,'cash':cash,'equity':equity,'realized':realized,'long':long,'short':short,'drawdown':peak-equity,'active':{uid:dict(item) for uid,item in active}}
    for point in curve:
        saved=snapshots[int(point[0])]
        near(point[1:],[saved[k] for k in ('time','equity','cash','realized','long','short','drawdown')],'公开curve包含全部在庫と清算料')
    check(len(lots)==len(certificates),'決済玉の件数')
    for lot,(uid,exit_order,gross,net,item) in zip(lots,certificates):
        entry=item['entry_order']
        expected=[uid,item['side'],entry[10],entry[3],entry[4],entry[6],entry[7],exit_order[3],exit_order[4],exit_order[6],exit_order[7],gross,2*fee_one,net,exit_order[9],item['mfe'],item['mae'],entry[13],exit_order[13]]
        near(lot,expected,'UID両価格・費用・net・MFE/MAE')
    if snapshots:
        final=list(snapshots.values())[-1];held=final['long']+final['short']
        near(summary[[0,1,2,3,4,5,6,7,8,9,10,11,12,13,15,17,18,19]],[final['equity'],cash,sum(max(0.,c[3]) for c in certificates),sum(max(0.,-c[3]) for c in certificates),paid,len(certificates),sum(c[3]>0 for c in certificates),sum(c[3]<0 for c in certificates),held,max(p['long'] for p in snapshots.values()),max(p['short'] for p in snapshots.values()),maxdd,minimum,len(state),rejected,held*fee_one,final['equity'],final['time']],'全会計summary独立一致')
        near(cash,realized-held*fee_one,'現金は実現netから残入口料を控除')
        if held==0:near(summary[0],summary[2]-summary[3],'全玉精算時はP/Lと現金一致')
    return snapshots


def main() -> None:
    """
    機能: 全八mode・費用・将来置換・在庫精算を人工だけで検査する。
    引数: なし。
    返り値: None。証跡又はFalseを自所有auditへ保存する。
    """
    source_bytes=SOURCE.read_bytes();check(hashlib.sha256(source_bytes).hexdigest()==EXPECTED,'監査開始SHA')
    spec=importlib.util.spec_from_file_location('engine120',SOURCE);engine=importlib.util.module_from_spec(spec);sys.modules['engine120']=engine;spec.loader.exec_module(engine)
    wave=np.r_[np.arange(100.,112.),np.arange(110.,88.,-1.),np.arange(90.,112.),np.arange(110.,88.,-1.),np.arange(90.,105.),np.full(7,104.)]
    cases=[]
    for mode in range(8):
        for fee,mult in ((41.8,1000.),(11.,10.)):
            args=material(wave,mode=mode,fee=fee,multiplier=mult)
            result=engine.replay(*args);snap=accounting(args,result)
            check(result[3][8]==0,'場末後quoteありの実全玉返済')
            if mode==6:
                entries=result[0][result[0][:,1]==1.]
                check(len(entries)<=2*args[5] and len(set((v[2],v[10]) for v in entries))==len(entries),'再利用なしは方向rung各一回')
            cases.append({'mode':mode,'fee':fee,'entries':int(result[3][13]),'closed':int(result[3][5]),'reasons':sorted(set(result[1][:,14].astype(int).tolist()))})
    # ----------------------------------------
    # 極値追尾、固定比較、次気配gapと利益判断後の実損を具体例で確認する。
    path=[100.,90.,93.,94.,100.,101.,99.5,99.,99.,99.,99.,99.]
    args=material(path,close=9.);normal=engine.replay(*args);accounting(args,normal)
    fixed=engine.replay(*material(path,mode=5,close=9.))
    check(np.any(normal[0][:,2]==1.) and not np.any((fixed[0][:,1]==1.)&(fixed[0][:,2]==1.)),'極値安値から反発して買う対照と固定基準を区別')
    grouped=engine.replay(*material(path,mode=7,close=9.));accounting(material(path,mode=7,close=9.),grouped)
    check(np.any((grouped[1][:,14]==7.)&(grouped[1][:,13]<0.)),'全玉返済対照は同方向の損失玉も実返済')
    gap=path.copy();gap[7]=80.;gapped=engine.replay(*material(gap,close=9.));accounting(material(gap,close=9.),gapped)
    check(np.any((gapped[1][:,14]==1.)&(gapped[1][:,13]<0.)),'利益玉追尾の判断後gap損失を隠さない')
    sameclock_args=material(path,times=np.zeros(len(path)),close=50.)
    sameclock=engine.replay(*sameclock_args);accounting(sameclock_args,sameclock)
    check(len(sameclock[0])>0 and np.all(sameclock[0][:,5]==sameclock[0][:,6]),'同clockの後原row約定を許容する契約')
    eof_args=material(path,cut=6,close=50.);eof=engine.replay(*eof_args);accounting(eof_args,eof)
    check(eof[3][8]>0 and not np.any(eof[0][:,9]==9.),'EOF保有を架空の場末返済へしない')
    # ----------------------------------------
    # 準備金と個別停止の決定当行を、保存注文から独立に照合する。
    recycle_args=material(wave,mode=3);recycle=engine.replay(*recycle_args);snap=accounting(recycle_args,recycle)
    for order in recycle[0][(recycle[0][:,1]==2.)&(recycle[0][:,9]==4.)]:
        s=snap[int(order[3])];item=s['active'][int(order[0])];mid=(recycle_args[3][np.flatnonzero(recycle_args[0]==order[3])[0]]+recycle_args[4][np.flatnonzero(recycle_args[0]==order[3])[0]])/2
        net=item['side']*((mid-.1 if item['side']==1 else mid+.1)-item['entry'])*recycle_args[6]-2*math.floor(recycle_args[7]+1e-9)
        check(net<0 and s['realized']>=-2*net-1e-7,'RECYCLEは決定当時の実現net半分以内')
    hard_args=material(wave,mode=4);hard=engine.replay(*hard_args);snap=accounting(hard_args,hard)
    for order in hard[0][(hard[0][:,1]==2.)&(hard[0][:,9]==5.)]:
        s=snap[int(order[3])];item=s['active'][int(order[0])];k=int(np.flatnonzero(hard_args[0]==order[3])[0]);xp=hard_args[3][k] if item['side']==1 else hard_args[4][k]
        net=item['side']*(xp-item['entry'])*hard_args[6]-2*math.floor(hard_args[7]+1e-9)
        check(net<=-3*hard[3][16]*hard_args[6]+1e-7,'HARDは決定当行の個別損失で予約')
    # ----------------------------------------
    # 末尾を書き換えても完成済み原rowの注文・玉・公開資産を変えない。
    for mode in range(8):
        prefix_args=material(wave,mode=mode,cut=40);prefix=engine.replay(*prefix_args)
        changed=wave.copy();changed[40:]=150.+np.arange(len(changed)-40)*(-1 if mode%2 else 1)
        full=engine.replay(*material(changed,mode=mode))
        last_raw=prefix_args[0][-1]
        near(prefix[0],full[0][full[0][:,4]<=last_raw],'未来置換で前半全注文不変')
        near(prefix[1],full[1][full[1][:,8]<=last_raw],'未来置換で前半全決済玉不変')
        # EOFの追加curve行は実観測済み点の再掲。定期公開行だけ同じ原rowで比較する。
        for p in prefix[2][:-1]:
            target=full[2][full[2][:,0]==p[0]]
            check(len(target)>=1,'前半の定期資産公開原rowを維持');near(p,target[0],'未来置換で前半公開資産不変')
    check(hashlib.sha256(SOURCE.read_bytes()).hexdigest()==EXPECTED,'監査終了SHA不変')
    result={'passed':True,'engine_SHA256':EXPECTED,'checks':dict(CHECKS),'total_checks':sum(CHECKS.values()),'cases':cases,'market_reads':0,'NPZ_reads':0,'old_result_reads':0,'registry_changes':0,'formal_financial_replay':0,'source_changes':0,'留保':'価格時計とLarge BBOを仮想注文へ写す人工検査。実際の待ち順位や約定量は証明しない。'}
    target=HERE/'段階追尾全八管理の独立会計と原row因果性の人工監査.json';assert not target.exists()
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'passed':True,'checks':sum(CHECKS.values()),'SHA256':hashlib.sha256(target.read_bytes()).hexdigest(),'cases':cases},ensure_ascii=False))


if __name__=='__main__':
    try:main()
    except BaseException as exc:
        path=HERE/'人工False.json'
        if not path.exists():path.write_text(json.dumps({'passed':False,'engine_SHA256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'checks':dict(CHECKS),'error_type':type(exc).__name__,'error':str(exc),'market_reads':0,'NPZ_reads':0,'formal_financial_replay':0},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
