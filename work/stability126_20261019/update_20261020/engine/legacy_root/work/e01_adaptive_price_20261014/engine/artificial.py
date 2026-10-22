"""未来maskを使わない一回FAK、旧市場同値、全feed再参加と実料を小合成だけで検査する。"""

import copy
from decimal import Decimal,ROUND_FLOOR
import numpy as np

import common
import catalog
import daily
import entry_policy
import interface
import runner
import sizing_engine
import constant_engine
import parent_diagnostics


def fixture(symbol: str, side: int=1, quantity: int=3) -> dict:
    """
    機能: 二紙上親と部分返済を持つnativeラージ気配の小合成口座を作る。
    引数: symbol(str)、side/quantity(int) は商品・方向・最初の予定実枚数。
    返り値: dict は人工専用口座。原板・実input・実台帳は読まない。
    """
    tick=daily.TICK[symbol];virtual=catalog.QUANTITY[symbol];count=48;price=4000. if symbol=='TOPIX' else 65000.
    bid=np.full(count,price);ask=bid+tick;last=ask.copy();clock=np.arange(count,dtype=float)
    atr=.001 if quantity==virtual else ({1:3.,2:1.5,3:1.}[quantity] if symbol=='TOPIX' else {1:100.,2:70.,3:50.}[quantity])
    first=2 if symbol=='TOPIX' else 4;second=1 if symbol=='TOPIX' else 2
    feed=np.array([[12,0,0,1,virtual,last[12],0,1,0,atr],
        [16,0,0,-1,first,last[16],0,0,0,0],[18,0,0,-1,second,last[18],0,0,0,0],
        [20,0,0,-1,virtual-first-second,last[20],0,0,0,0],
        [25,0,1,1,virtual,last[25],0,1,0,atr],[35,0,1,-1,virtual,last[35],0,0,0,0]],float)
    if side<0:
        center=2*price+tick;last=center-last;bid,ask=center-ask,center-bid;feed[:,3]*=-1;feed[:,5]=center-feed[:,5]
    quotes=dict(seq=np.arange(3000,3000+count,dtype=np.int64),time_s=clock,bid=bid,ask=ask,quote_valid=np.ones(count,bool))
    record=dict(seq=quotes['seq'],time_s=clock,price=last,start=0.,end=47.,limit=47.,tick=tick)
    features={int(o[0]):dict(known=True,reason=0,direction_votes=4,balance=1.) for o in feed[feed[:,7]==1]}
    return dict(symbol=symbol,record=record,quotes=quotes,feed=feed,quiet=np.zeros(count,bool),quiet_force=np.zeros(count,bool),trade_features={'60':features})


def prefix(account: dict, cut: int) -> dict:
    """
    機能: 当時までの口座と公開feedへ切り、未来正常quoteを執行用に補わない。
    引数: account(dict)、cut(int) は小合成と未来開始行。
    返り値: dict は未完成接頭。limitは元の未来期限を保持する。
    """
    result=copy.deepcopy(account)
    for section in ('record','quotes'):
        for name,value in result[section].items():
            if isinstance(value,np.ndarray):result[section][name]=value[:cut]
    for name in ('quiet','quiet_force'):result[name]=result[name][:cut]
    result['feed']=result['feed'][result['feed'][:,0]<cut]
    result['trade_features']['60']={r:v for r,v in result['trade_features']['60'].items() if r<cut}
    return result


def simulate(account: dict, allowances: np.ndarray, constant: int|None=None, python: bool=True, fak: bool=True) -> tuple:
    """
    機能: 同bytes固定許容対照又は公開配列許容を小合成に接続する。
    引数: account(dict)、allowances(ndarray)、constant(int|None)、python/fak(bool) は人工入力と執行対照。
    返り値: tuple は旧十一配列とFAK十九列。正式input/旧台帳を読まない。
    """
    r,q=account['record'],account['quotes'];symbol=account['symbol'];num,den=catalog.FEE_RATIO[symbol]
    gate=entry_policy.mask(account,'G50');module=sizing_engine if constant is None else constant_engine
    fn=module.simulate.py_func if python else module.simulate
    last=allowances if constant is None else constant
    return fn(r['time_s'],r['price'],q['bid'],q['ask'],q['quote_valid'],account['feed'],account['quiet'],account['quiet_force'],
        r['limit'],catalog.CAP[symbol],r['tick'],0.,True,gate['accepted'],True,catalog.BUDGET[symbol],1.,catalog.VALUE[symbol],num,den,fak,last)


def driver_checks() -> list[str]:
    """
    機能: 八政策の登録拒否・初受理持越し・二固定許容比較と実親小診断を結合する。
    引数: なし。
    返り値: list[str] は人工のみの接続観点。原input/旧台帳/金融は未読。
    """
    configs=catalog.configs();source=common.sources();hashes=runner.case_hashes(configs)
    spec=dict(entry=dict(conditions=configs),implementation=source)
    fixed=dict(configs=configs,case_SHA256=hashes,source_SHA256=source)
    prepared=dict(id=catalog.TRIAL_ID,spec=spec);found=[copy.deepcopy(prepared)]
    runner.registry_guard(found,fixed,prepared);runner.source_scope_guard()
    for kind in ('未登録','別trial','別spec','別条件','別casehash','別source'):
        f=copy.deepcopy(found);x=copy.deepcopy(fixed);p=copy.deepcopy(prepared)
        if kind=='未登録':f=[]
        elif kind=='別trial':f[0]['id']='人工別試行'
        elif kind=='別spec':f[0]['spec']['entry']['追加']=True
        elif kind=='別条件':x['configs'][0]['strong_balance_threshold']=.8
        elif kind=='別casehash':x['case_SHA256'][configs[0]['id']]='0'*64
        else:x['source_SHA256'][next(iter(source))]='0'*64
        rejected=False
        try:runner.registry_guard(f,x,p)
        except AssertionError:rejected=True
        assert rejected,kind
    checks=['六登録拒否と新所有JIT・八条件全項目指紋'];fake_records={}
    for symbol in catalog.QUANTITY:
        for side in (1,-1):
            a=fixture(symbol,side,1);tick=a['record']['tick']
            a['quotes']['bid'][13]+=side*2*tick;a['quotes']['ask'][13]+=side*2*tick
            a['feed'][a['feed'][:,0]==25,9]=.5 if symbol=='TOPIX' else 40.
            for gate_id,execution_id in catalog.new_gu_routes():
                observed=interface.execute(a,gate_id,execution_id,python=True);ctx=interface.prepared('人工_Day',a,observed['values'])
                for config in (c for c in configs if c['entry_id']==gate_id and c['execution_id']==execution_id):
                    fresh=interface.apply(ctx,config,observed['gate'],python=True,fak_events=observed['fak_events'])
                    d=runner.fak_diagnosis(a,fresh);assert fresh['goal_anchor']['数量']==1 and d['carryover_after_unfilled_initial']
                    assert d['first_actual']['source_row']==25 and fresh['goal_anchor']['受理行']==12
                    assert d['GU全試行']['試行失効']==1 and d['GU全試行']['試行約定']==1
                    entries=parent_diagnostics.project(a,fresh);assert len(entries)==len(fresh['parent'])
                    for item,parent in zip(entries,fresh['parent']):
                        assert item['published_adverse_ticks']==1 and item['published_balance']==1.
                        assert item['published_direction_votes']==4 and item['net_yen']==parent['収支']
                        assert item['entry']['raw_seq']==a['record']['seq'][item['entry']['row']]
                        assert item['parent_worst_fee_liquidation_yen'] is not None and not item['overlapping_parent_ids']
                    for tolerance in (0,1):
                        old=simulate(a,np.full(len(a['record']['price']),tolerance,np.int8),constant=tolerance)
                        oldctx=interface.prepared('人工_Day',a,old[:11]);baseline=interface.apply(oldctx,config,fak_events=old[11])
                        difference=runner.ledger_storage.delta(baseline,fresh)
                        assert np.isclose(difference['収支変化'],fresh['summary']['収支']-baseline['summary']['収支'])
                        runner.baseline_exact(baseline,interface.apply(oldctx,config),len(a['record']['price']))
                        old_projection=parent_diagnostics.project(a,baseline)
                        assert len(old_projection)==len(baseline['parent'])
                        assert all(item['published_adverse_ticks']==tolerance for item in old_projection)
                fake_records.setdefault('人工_Day',{}).setdefault(symbol,{})[gate_id+'|'+execution_id]=runner.activity(a,observed['values'],observed['gate'],observed['fak_events'])
            checks.append(symbol+str(side)+':八政策/両端比較・取消初回保持・後q/ATR不追従・実親票/清算小射影')
    aggregate=runner.activity_summary(fake_records)
    assert aggregate['G50|ADAPT75']['TOPIX']['Day']['sessions']==1
    assert aggregate['G50|ADAPT100']['TOPIX']['全33']['paper_candidates']==2
    return checks


def run() -> None:
    """
    機能: 公開強支持閾値・定数旧十二同値・未来配列反例・影/料金/接頭を人工検査する。
    引数: なし。
    返り値: None。根の正式固定/登録/金融を行わず、新所有証跡だけ保存する。
    """
    source=common.sources();checks=driver_checks();arrays=0;truth=0
    assert len(catalog.configs())==8 and len(catalog.new_gu_routes())==4
    for threshold,min_votes in catalog.GATES.values():
        for known in (False,True):
            for n in (0,1,2,3,4,5):
                for balance in (-1.,0.,np.nextafter(threshold,-np.inf),threshold,np.nextafter(threshold,np.inf),1.):
                    v=dict(known=known,reason=4,direction_votes=n,balance=balance)
                    assert entry_policy.vote(v,threshold,min_votes)[0]==(known and n>=2 and balance>=threshold);truth+=1
    for strong in catalog.STRONG.values():
        for known in (False,True):
            for n in (0,1,2,3,4,5):
                for balance in (-1.,0.,np.nextafter(strong,-np.inf),strong,np.nextafter(strong,np.inf),1.):
                    a=fixture('TOPIX');a['trade_features']['60'][12]=dict(known=known,reason=4,direction_votes=n,balance=balance)
                    allow=entry_policy.allowances(a,strong)
                    assert allow[12]==int(known and n>=2 and balance>=strong);truth+=1
                    assert np.count_nonzero(allow)==int(allow[12])+int(allow[25])
    for symbol in catalog.QUANTITY:
        for side in (1,-1):
            for quantity in (1,2,3,catalog.QUANTITY[symbol]):
                for tolerance in (0,1):
                    for adverse in (-1,0,1,2):
                        a=fixture(symbol,side,quantity);tick=a['record']['tick'];n=len(a['record']['price'])
                        a['quotes']['bid'][13]+=side*adverse*tick;a['quotes']['ask'][13]+=side*adverse*tick
                        allow=np.full(n,tolerance,np.int8)
                        old=simulate(a,allow,constant=tolerance);fresh=simulate(a,allow);compiled=simulate(a,allow,python=False)
                        for x,y,z in zip(old,fresh,compiled):
                            np.testing.assert_array_equal(x,y);np.testing.assert_array_equal(x,z);arrays+=2
                        first=fresh[0][(fresh[0][:,2]==0)&(fresh[0][:,7]==1)]
                        assert len(first)==int(adverse<=tolerance)
                        attempts=fresh[11][(fresh[11][:,1]==2)&(fresh[11][:,2]==0)]
                        assert len(attempts)==1 and attempts[0,0]==13 and attempts[0,9]==tolerance
                        for cut in (12,13,14,17,22,26,36):
                            p=simulate(prefix(a,cut),allow[:cut])
                            for slot in (2,7,10):np.testing.assert_array_equal(p[slot],fresh[slot][:cut]);arrays+=1
                            for slot in (0,6,8,9,11):
                                np.testing.assert_array_equal(p[slot],fresh[slot][fresh[slot][:,0]<cut]);arrays+=1
                        base=daily.reconstruct(('人工',symbol),fresh[0],fresh[5],a['quotes'])
                        charge=Decimal('41.8' if symbol=='TOPIX' else '11')
                        expected=sum(int((Decimal(int(o[4]))*charge).to_integral_value(rounding=ROUND_FLOOR)) for o in fresh[0])
                        assert base['summary']['費用']==expected
                        checks.append(symbol+str(side)+'Q'+str(quantity)+'/固定'+str(tolerance)+'/不利'+str(adverse)+':旧十二/PythonJIT exact・一回失効・料金・七接頭')
            a=fixture(symbol,side,1);n=len(a['record']['price']);tick=a['record']['tick']
            for published in (0,1):
                for row in (13,14,16):
                    a=fixture(symbol,side,1)
                    if row>13:a['quotes']['quote_valid'][13:row]=False
                    a['quotes']['bid'][row]+=side*tick;a['quotes']['ask'][row]+=side*tick
                    allow=np.zeros(n,np.int8);allow[12]=published;allow[25]=1
                    fresh=simulate(a,allow);different=allow.copy();different[13:25]=1-published
                    future=simulate(a,different)
                    for slot in (2,7,10):np.testing.assert_array_equal(future[slot][:25],fresh[slot][:25]);arrays+=1
                    for slot in (0,6,8,9,11):np.testing.assert_array_equal(future[slot][future[slot][:,0]<25],fresh[slot][fresh[slot][:,0]<25]);arrays+=1
                    attempts=fresh[11][(fresh[11][:,1]==2)&(fresh[11][:,2]==0)]
                    assert len(attempts)==1 and attempts[0,13]==published and attempts[0,9]==published
                checks.append(symbol+str(side)+':公開許容'+str(published)+'固定・試行/待機中未来配列で再選択しない')
            for execution in catalog.STRONG:
                a=fixture(symbol,side,1);a['trade_features']['60'][12]['balance']=.5;a['trade_features']['60'][25]['balance']=1.
                a['quotes']['bid'][13]+=side*tick;a['quotes']['ask'][13]+=side*tick
                out=interface.execute(a,'G50',execution,python=True)
                assert out['allowance_ticks'][12]==0 and out['allowance_ticks'][25]==1
                assert not np.any(out['values'][0][:,2]==0) and np.any(out['values'][0][:,2]==1)
                assert out['values'][5][out['values'][0][:,7]==1][0]==0
                for reason in ('quiet','期限','paper'):
                    b=fixture(symbol,side,1);b['quotes']['quote_valid'][13:16]=False
                    if reason=='quiet':b['quiet_force'][16]=True
                    elif reason=='期限':b['record']['limit']=16.
                    else:b['feed'][b['feed'][:,0]==16,0]=15
                    o=interface.execute(b,'G50',execution,python=True)
                    assert not np.any((o['fak_events'][:,2]==0)&(o['fak_events'][:,1]==2))
                # 価格上限と幅拡大は別。arrival spreadを公開maskへ遡及しない。
                b=fixture(symbol,side,1);b['quotes']['bid' if side>0 else 'ask'][13]-=side*tick
                o=interface.execute(b,'G50',execution,python=True)
                assert np.any((o['values'][0][:,2]==0)&(o['values'][0][:,7]==1))
            market=simulate(a,np.zeros(n,np.int8),fak=False)
            oldmarket=simulate(a,np.zeros(n,np.int8),constant=0,fak=False)
            for x,y in zip(market,oldmarket):np.testing.assert_array_equal(x,y);arrays+=1
            checks.append(symbol+str(side)+':混合公開許容/実UID再参加・既知取消優先・幅拡大反証・市場OFF旧同値')
    assert common.sources()==source
    common.write('公開支持の許容固定と八政策接続の人工検査_v2.json',dict(全合格=True,source_SHA256=source,条件数=8,
        観点=len(checks),確認観点=checks,配列照合=arrays,独立真偽表=truth,金融=0,実input=0,旧台帳=0,原板=0,NPZ=0,API=0))
    print('適応許容人工合格 '+str(len(checks))+'観点/'+str(arrays)+'配列/'+str(truth)+'真偽表',flush=True)


if __name__=='__main__':run()
