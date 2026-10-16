"""十六条件の尺度と五入口を、独立端点oracle・全feed数量変化・接頭で確認する。"""

from pathlib import Path
import ast
import copy
import hashlib
import json
import os
import sys

import numpy as np
import numba

import generic_exit_check_v2 as generic
from cash_distance_oracle import fee


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=HERE.parent/'engine'
os.environ['NUMBA_CACHE_DIR']=str(HERE/'cross16_jit')
numba.config.CACHE_DIR=str(HERE/'cross16_jit')
import catalog
import entry_policy
import interface


def endpoint(own: dict, peer: dict|None, row: int, side: int, entry: str) -> dict:
    """
    機能: ソート探索を使わず、資格を満たす端点を列挙して十秒応答を独立判定する。
    引数: own/peer(dict/None)、row/side(int)、entry(str)は確認済み価格列と候補。
    返り値: dictは既知性・採否・端点。peerの同clock全行を除外する。
    """
    source=own if entry=='SELF10' else peer;clock=float(own['time'][row])
    qualified=[i for i in range(len(source['time'])) if source['normal'][i]]
    starts=[i for i in qualified if source['time'][i]<=clock-10]
    ends=[i for i in qualified if source['time'][i]<clock]
    start=max(starts) if starts else None;end=row if entry=='SELF10' else (max(ends) if ends else None)
    if start is None or end is None or start>=end or not source['normal'][end]:return dict(known=False,accepted=False)
    start_age=clock-10-source['time'][start];end_age=clock-source['time'][end]
    if not (0<=start_age<=15 and 0<=end_age<=15) or entry=='PEER10' and end_age<=0:return dict(known=False,accepted=False)
    db=(source['bid'][end]-source['bid'][start])/source['tick'];da=(source['ask'][end]-source['ask'][start])/source['tick']
    return dict(known=True,accepted=side*db>=1 and side*da>=1,start_row=start,end_row=end,
        start_raw_seq=int(source['seq'][start]),end_raw_seq=int(source['seq'][end]),start_age=float(start_age),end_age=float(end_age),
        bid_change_ticks=float(db),ask_change_ticks=float(da))


def quote_account(symbol: str, times: np.ndarray) -> dict:
    """
    機能: 同clockの複数原行を持つ人工normal口座を作る。
    引数: symbol(str)、times(ndarray)は商品と価格代理時計。
    返り値: dictは価格口座。実市場・現在APIを使わない。
    """
    tick=.5 if symbol=='TOPIX' else 10.;base=100. if symbol=='TOPIX' else 1000.;n=len(times)
    quotes=dict(time_s=times.copy(),seq=np.arange(100,100+n,dtype=np.int64),bid=np.full(n,base),ask=np.full(n,base+tick),quote_valid=np.ones(n,bool))
    return dict(symbol=symbol,quotes=quotes,record=dict(time_s=quotes['time_s'],seq=quotes['seq'],price=(quotes['bid']+quotes['ask'])/2,
        tick=tick,start=-100.,limit=float(times[-1])+1))


def feed_fixture(symbol: str, side: int, cut: int=70) -> tuple:
    """
    機能: 弱い初回を拒否すると後続qが変わる、二親全feed人工を作る。
    引数: symbol(str)、side/cut(int)は商品・方向・接頭長。
    返り値: tupleは自己とpeer人工。元paper返済を削除しない。
    """
    n=70;tick=.5 if symbol=='TOPIX' else 10.;base=100. if symbol=='TOPIX' else 1000.;full=catalog.QUANTITY[symbol]
    times=np.arange(n,dtype=float);own=quote_account(symbol,times);own['record']['start']=0.;own['record']['limit']=66.
    own['quotes']['bid'][20:36]+=side*tick;own['quotes']['ask'][20:36]+=side*tick
    atr1,atr2=(3.,1.) if symbol=='TOPIX' else (130.,70.)
    rows=[]
    for parent,entry,close,atr in ((0,20,35,atr1),(1,40,60,atr2)):
        rows.extend([[entry,0,parent,side,full,base+tick/2,0,1,0,atr],[close,0,parent,-side,full,base+tick/2,0,0,0,0]])
    own.update(feed=np.asarray(rows,float),quiet=np.zeros(n,bool),quiet_force=np.zeros(n,bool),
        trade_features={'60':{20:dict(known=True,reason=0,direction_votes=3,balance=1/3),40:dict(known=True,reason=0,direction_votes=4,balance=.75)}})
    peer_symbol='NK225' if symbol=='TOPIX' else 'TOPIX';peer=quote_account(peer_symbol,times);peer['record']['start']=0.;peer['record']['limit']=66.
    peer_tick=peer['record']['tick'];peer['quotes']['bid'][35:]+=side*peer_tick;peer['quotes']['ask'][35:]+=side*peer_tick
    # 同clockの将来peer大逆行は、自己40行のPEER10に入れてはならない。
    peer['quotes']['bid'][40]-=side*20*peer_tick;peer['quotes']['ask'][40]-=side*20*peer_tick
    for account in (own,peer):
        for group in ('quotes','record'):
            account[group]={k:v[:cut].copy() if isinstance(v,np.ndarray) else v for k,v in account[group].items()}
        account['record']['price']=(account['quotes']['bid']+account['quotes']['ask'])/2
    own['feed']=own['feed'][own['feed'][:,0]<cut];own['quiet']=own['quiet'][:cut];own['quiet_force']=own['quiet_force'][:cut]
    return own,peer


def lines_expected(ctx: dict, config: dict) -> dict:
    """
    機能: 初回公開q・ATR・気配差・注文別料から純円目標を独立に計算する。
    引数: ctx/config(dict)は人工共通文脈と十六条件。
    返り値: dictは固定円線。今の清算額へ料金を再課金しない。
    """
    anchor=ctx['anchor'];symbol=ctx['key'][1]
    if anchor is None:return dict(target_yen=None,hard_loss_yen=None,arm_yen=None,drawdown_yen=None,floor_yen=None)
    q=anchor['quantity'];multiplier=1000 if symbol=='TOPIX' else 10;tick=.5 if symbol=='TOPIX' else 10.
    risk=q*anchor['published_atr']*multiplier;cost=q*anchor['published_spread']*multiplier+2*fee(q,symbol);p1=q*tick*multiplier
    hard=catalog.BUDGET[symbol] if config['hard_basis']=='BUDGET' else config['hard_multiple']*risk+cost
    if config['exit_kind']=='fixed':
        target=p1-2*fee(q,symbol) if config['target_basis']=='TICK_NET' else p1 if config['target_basis']=='P1' else config['target_multiple']*risk
        return dict(target_yen=target,hard_loss_yen=hard,arm_yen=None,drawdown_yen=None,floor_yen=None)
    arm=p1 if config['arm_basis']=='P1' else config['arm_multiple']*risk
    return dict(target_yen=None,hard_loss_yen=hard,arm_yen=arm,drawdown_yen=config['draw_multiple']*risk,floor_yen=0.)


# ----------------------------------------
def main() -> None:
    """
    機能: 十六尺度・端点時計資格・五入口全feed・数量差・未来接頭を非金融で確認する。
    引数: なし。所有人工に束縛した経済16源を対象とする。
    返り値: Noneは自所有準備証跡。登録driver/金融計画は別に監査する。
    """
    owner=SOURCE/'十六対照と実行前拒否及び表示会計の人工検査.json'
    raw=owner.read_bytes();proof=json.loads(raw.decode('utf-8'));sources=proof['source_SHA256']
    assert hashlib.sha256(raw).hexdigest()=='0bcefa429002e7b60781440cea6eb5c5b7089b69237507f53812546cbcb24f28'
    assert proof['全合格'] and len(sources)==20 and all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==sha for p,sha in sources.items())
    scope=HERE/'十六条件の尺度端点と全feed独立人工範囲固定_v2.json';target=HERE/'十六条件の純円尺度と五入口価格時計及び全feed数量の独立人工_v2.json'
    assert not scope.exists() and not target.exists()
    scope.write_text(json.dumps(dict(source_SHA256=sources,正式結果=0,実入力=0,金融=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    configs=catalog.configs();assert len(configs)==16 and len({c['id'] for c in configs})==16
    assert len([c for c in configs if c['id'].startswith('E01_CROSS_A')])==10
    assert len([c for c in configs if c['id'].startswith('E01_CROSS_B')])==4
    assert len([c for c in configs if c['id'].startswith('E01_CROSS_C')])==2
    assert catalog.entry_ids()==('CONFIRM25','CONFIRM50','CONFIRM75','SELF10','PEER10')
    scales=0;arrays=0;truths=0;endpoints=0;feed_cases=0;quantity_changes=[]
    for symbol in ('TOPIX','NK225'):
        for side in (1,-1):
            for cancel in (False,True):
                a,one,two=generic.fixture(symbol,side,cancel);ctx=generic.context.prepare(a,one,two)
                for config in configs:
                    expected=lines_expected(ctx,config);actual=interface.calibrate(ctx,config)
                    for key,value in expected.items():assert actual[key]==value
                    assert actual['quantity_selection_budget_yen']==catalog.BUDGET[symbol] and actual['anchor']==ctx['anchor']
                    output=interface.apply(ctx,config,python=True)
                    arm=np.inf if config['exit_kind']=='fixed' else expected['arm_yen']
                    draw=1. if config['exit_kind']=='fixed' else expected['drawdown_yen']
                    decision,reason,trace=generic.scan_oracle(ctx['base']['liquidation_yen'],ctx['normal'],2,arm,draw,0.,expected['hard_loss_yen'],expected['target_yen'])
                    orders,uids,targets,pending=generic.close_oracle(ctx,decision);assert not pending
                    if config['exit_kind']=='fixed' and decision>=0:orders[(orders[:,0]>decision)&(orders[:,6]==96),6]=94 if reason==2 else 95
                    for key,value in (('orders',orders),('order_uids',uids),('exit_target_uids',targets)):
                        np.testing.assert_array_equal(output[key],value);arrays+=1
                    own_book,_=generic.book(orders,uids,ctx['quotes'],symbol)
                    for i,key in ((0,'cumulative_fees'),(1,'reserved_exit_fees'),(2,'equity_yen'),(3,'liquidation_yen')):
                        np.testing.assert_allclose(output[key],own_book[:,i],rtol=1e-12,atol=1e-6);arrays+=1
                    assert output['summary']['費用']==sum(fee(int(o[4]),symbol) for o in orders)
                    assert output['goal_anchor']['数量']==ctx['anchor']['quantity'] and output['goal_anchor']['受理行']==2
                    scales+=1
    # known/票数/厳密閾値の包含。実取引集合の包含とは扱わない。
    for known in (False,True):
        for votes in (0,1,2,3):
            for balance in (-1.,.0,np.nextafter(.25,-np.inf),.25,np.nextafter(.25,np.inf),np.nextafter(.5,-np.inf),.5,np.nextafter(.5,np.inf),np.nextafter(.75,-np.inf),.75,np.nextafter(.75,np.inf),1.):
                accepted=[]
                for threshold in (.25,.5,.75):
                    value=dict(known=known,reason=16,direction_votes=votes,balance=balance)
                    got,_=entry_policy.vote(value,threshold);assert got==(known and votes>=2 and balance>=threshold);accepted.append(got);truths+=1
                assert accepted[2]<=accepted[1]<=accepted[0]
    # 同clockpeer除外、最後normal端点、未知/欠測・左右対称を直接列挙oracleへ照合する。
    times=np.array([0,10,15,15,20,25,25,25,30,50],float)
    for symbol in ('TOPIX','NK225'):
        for side in (1,-1):
            own=quote_account(symbol,times);peer=quote_account('NK225' if symbol=='TOPIX' else 'TOPIX',times)
            for account,position in ((own,7),(peer,4)):
                tick=account['record']['tick'];account['quotes']['bid'][position]+=side*tick;account['quotes']['ask'][position]+=side*tick
            for variant in ('通常','自己当行未知','参照最新未知','相手最新未知','相手全未知','未来同clock逆転','片BBOだけ進行'):
                a,b=copy.deepcopy(own),copy.deepcopy(peer)
                if variant=='自己当行未知':a['quotes']['quote_valid'][7]=False
                elif variant=='参照最新未知':a['quotes']['quote_valid'][3]=False;b['quotes']['quote_valid'][3]=False
                elif variant=='相手最新未知':b['quotes']['quote_valid'][4]=False
                elif variant=='相手全未知':b['quotes']['quote_valid'][:]=False
                elif variant=='未来同clock逆転':
                    b['quotes']['bid'][5:]-=side*10*b['record']['tick'];b['quotes']['ask'][5:]-=side*10*b['record']['tick']
                elif variant=='片BBOだけ進行':
                    a['quotes']['ask']+=a['record']['tick'];b['quotes']['ask']+=b['record']['tick']
                    a['quotes']['ask'][7]-=side*a['record']['tick'];b['quotes']['ask'][4]-=side*b['record']['tick']
                own_clock=entry_policy.clock_account(a);peer_clock=entry_policy.clock_account(b)
                for entry in ('SELF10','PEER10'):
                    expected=endpoint(own_clock,peer_clock,7,side,entry);got=entry_policy.response(own_clock,peer_clock,7,side,entry)
                    for key,value in expected.items():assert got[key]==value,(variant,entry,key)
                    if got['known']:
                        assert got['start_price_time_s']<=got['candidate_price_time_s']-10
                        if entry=='PEER10':assert got['end_price_time_s']<got['candidate_price_time_s']
                        else:assert got['end_row']==7
                    endpoints+=1
    # 全feedを機械再生。拒否した親を消して旧損益を引く方法ではない。
    for symbol in ('TOPIX','NK225'):
        for side in (1,-1):
            account,peer=feed_fixture(symbol,side);original=account['feed'].copy();executions={}
            for entry in catalog.entry_ids():
                run=interface.execute(account,entry,peer,python=True);native=interface.execute(account,entry,peer)
                for left,right in zip(run['values'],native['values']):np.testing.assert_array_equal(left,right);arrays+=1
                np.testing.assert_array_equal(account['feed'],original);arrays+=1
                executions[entry]=run
                for cut in (20,21,36,41,62):
                    a,b=feed_fixture(symbol,side,cut);short=interface.execute(a,entry,b,python=True)
                    for index in (7,10):np.testing.assert_array_equal(short['values'][index],run['values'][index][:cut]);arrays+=1
                    for index in (0,9):
                        np.testing.assert_array_equal(short['values'][index],run['values'][index][run['values'][index][:,0]<cut]);arrays+=1
                    altered=copy.deepcopy(peer);altered['quotes']['bid'][cut:]+=100.;altered['quotes']['ask'][cut:]+=100.
                    future=interface.execute(a,entry,altered,python=True)
                    for left,right in zip(short['values'],future['values']):np.testing.assert_array_equal(left,right);arrays+=1
                feed_cases+=1
            baseline=executions['CONFIRM25']['values'];strong=executions['CONFIRM50']['values']
            for entry,run in executions.items():np.testing.assert_array_equal(run['values'][7][:,:2],baseline[7][:,:2]);arrays+=1
            old_second=baseline[9][baseline[9][:,1]==1][0];new_second=strong[9][strong[9][:,1]==1][0]
            assert baseline[9][0,15]==1 and strong[9][0,15]==0 and new_second[15]==1
            if symbol=='TOPIX':assert old_second[4]==2 and new_second[4]==3
            quantity_changes.append(dict(商品=symbol,方向=side,旧二親目q=int(old_second[4]),初親拒否後q=int(new_second[4]),
                影二列同値=True,元feed保持=True,損益を削除代用していない=True))
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==sha for p,sha in sources.items())
    result=dict(全合格=True,source_SHA256=sources,所有十六人工_SHA256=hashlib.sha256(raw).hexdigest(),
        独立source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),尺度条件=scales,配列照合=arrays,
        票真偽表=truths,価格端点条件=endpoints,全feed条件=feed_cases,拒否後の数量差=quantity_changes,
        初回束縛停止='旧16源artifactのcross_artificial.pyはdriver人工追補前の指紋だったため実行前に停止。初版源保持し、正式20源artifactへ変更。経済源差0、金融及び実資料読取0。',
        留保=['SELF10は自己BBO両側、PEER10は自己旧票と相手BBO両側。PEER10で自己BBO順行も同時必須とはしない。',
              'peer同clockは全て除外し、端点は最後normal、age<=15。十秒の基準であって全raw区間の正常性又は真の受信時計保証ではない。',
              'A04は初受理qの1観測呼値粗利−予定往復料を場net目標へ固定。実料を清算額へ二重課金せず、各親で1呼値利益を保証しない。',
              'maskの包含と実取引の包含は異なる。初親拒否で後続実qが変わる人工を全feedで確認。',
              '同既知33の診断後の16条件。未知検証又は両商品安定収益の達成はまだ測定していない。'],
        正式結果=0,実入力=0,原板=0,NPZ=0,packet=0,ledger=0,金融=0,API=0,旧source及び旧JIT変更=0)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,尺度=scales,配列=arrays,票=truths,端点=endpoints,全feed=feed_cases,
        SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':main()
