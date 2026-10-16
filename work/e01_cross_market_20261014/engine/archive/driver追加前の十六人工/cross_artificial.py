"""十六対照の円尺度・五入口・全feed・予約・接頭を実入力未読で検査する。"""

import copy
from decimal import Decimal,ROUND_FLOOR
import hashlib
import numpy as np

import common
import artificial
import base_policy
import catalog
import daily
import entry_policy
import interface
import reuse
import sizing_engine
import sizing_baseline
import storage


def fixture(symbol: str, side: int=1, quantity: int=3) -> dict:
    """
    機能: 二紙上親の再参加と部分返済を持つnative気配の人工口座を作る。
    引数: symbol(str)、side/quantity(int) は商品・意図方向・最初の予定実枚数。
    返り値: dict は人工のみの口座。大型入力・実台帳・原板は読まない。
    """
    tick=daily.TICK[symbol];qty=catalog.QUANTITY[symbol];n=48;base=4000. if symbol=='TOPIX' else 65000.
    bid=np.full(n,base);ask=bid+tick;p=ask.copy();times=np.arange(n,dtype=float)
    atr=.001 if quantity==qty else ({1:3.,2:1.5,3:1.}[quantity] if symbol=='TOPIX' else {1:100.,2:70.,3:50.}[quantity])
    first=2 if symbol=='TOPIX' else 4;second=1 if symbol=='TOPIX' else 2
    feed=np.array([[12,0,0,1,qty,p[12],0,1,0,atr],
        [16,0,0,-1,first,p[16],0,0,0,0],[18,0,0,-1,second,p[18],0,0,0,0],
        [20,0,0,-1,qty-first-second,p[20],0,0,0,0],
        [25,0,1,1,qty,p[25],0,1,0,atr],[35,0,1,-1,qty,p[35],0,0,0,0]],float)
    if side<0:
        center=2*base+tick;p=center-p;bid,ask=center-ask,center-bid;feed[:,3]*=-1;feed[:,5]=center-feed[:,5]
    quotes=dict(seq=np.arange(3000,3000+n,dtype=np.int64),time_s=times,bid=bid,ask=ask,quote_valid=np.ones(n,bool))
    record=dict(seq=quotes['seq'],time_s=times,price=p,start=0.,end=47.,limit=47.,tick=tick)
    features={int(o[0]):dict(known=True,reason=0,direction_votes=4,balance=.5) for o in feed[feed[:,7]==1]}
    return dict(symbol=symbol,record=record,quotes=quotes,feed=feed,quiet=np.zeros(n,bool),quiet_force=np.zeros(n,bool),trade_features={'60':features})


def prefix(account: dict, cut: int) -> dict:
    """
    機能: 時計limitを保持し、当時行までのfeedと票だけへ同じ位置で切断する。
    引数: account(dict)、cut(int) は人工口座と未来開始行。
    返り値: dict は未完成口座。将来正常行を執行用に補わない。
    """
    result=copy.deepcopy(account)
    for section in ('record','quotes'):
        for key,value in result[section].items():
            if isinstance(value,np.ndarray):result[section][key]=value[:cut]
    for key in ('quiet','quiet_force'):result[key]=result[key][:cut]
    result['feed']=result['feed'][result['feed'][:,0]<cut]
    result['trade_features']['60']={k:v for k,v in result['trade_features']['60'].items() if k<cut}
    return result


def response_checks() -> list[str]:
    """
    機能: 自己当行・相手strictpast・最後normal・age及び未来行不使用を人工確認する。
    引数: なし。
    返り値: list[str] は価格模型の資格確認。raw中間経路や物理受信時刻は保証しない。
    """
    checks=[]
    for symbol in catalog.QUANTITY:
        for side in (1,-1):
            own=fixture(symbol,side,1);other='NK225' if symbol=='TOPIX' else 'TOPIX';peer=fixture(other,side,1)
            for a in (own,peer):
                tick=a['record']['tick'];a['quotes']['bid'][3:]+=side*tick;a['quotes']['ask'][3:]+=side*tick
            own['quotes']['quote_valid'][2]=False;peer['quotes']['quote_valid'][2]=False
            own['quotes']['quote_valid'][11]=False;peer['quotes']['quote_valid'][11]=False
            prices=entry_policy.clock_account(own);op=entry_policy.clock_account(peer)
            s=entry_policy.response(prices,None,12,side,'SELF10');p=entry_policy.response(prices,op,12,side,'PEER10')
            assert s['accepted'] and s['start_row']==1 and s['end_row']==12
            assert p['accepted'] and p['start_row']==1 and p['end_row']==10
            assert p['end_price_time_s']<s['candidate_price_time_s']
            # 同時計の後続自己quote及び相手当時計以後の価格は選択できない。
            changed=copy.deepcopy(own);changed['quotes']['time_s'][13]=12.;changed['record']['time_s'][13]=12.
            changed['quotes']['bid'][13]+=side*10000;changed['quotes']['ask'][13]+=side*10000
            assert entry_policy.response(entry_policy.clock_account(changed),None,12,side,'SELF10')==s
            future=copy.deepcopy(peer);future['quotes']['bid'][12:]+=side*10000;future['quotes']['ask'][12:]+=side*10000
            assert entry_policy.response(prices,entry_policy.clock_account(future),12,side,'PEER10')==p
            invalid=copy.deepcopy(own);invalid['quotes']['quote_valid'][12]=False
            assert not entry_policy.response(entry_policy.clock_account(invalid),None,12,side,'SELF10')['known']
            for route in ('SELF10','PEER10'):
                gate=entry_policy.mask(own,route,peer);assert gate['accepted'][12]
            checks.append(symbol+str(side)+':最後normal端点・自己公開当行・相手strictpast・未知当行拒否・同clock未来排除')
    own=fixture('TOPIX',1,1);peer=fixture('NK225',1,1)
    own['quotes']['time_s']*=20.;own['record']['time_s']=own['quotes']['time_s'];own['record']['limit']=own['quotes']['time_s'][-1]
    s=entry_policy.response(entry_policy.clock_account(own),None,12,1,'SELF10');assert s['known']
    own['quotes']['time_s']*=2.;own['record']['time_s']=own['quotes']['time_s'];own['record']['limit']=own['quotes']['time_s'][-1]
    assert not entry_policy.response(entry_policy.clock_account(own),None,12,1,'SELF10')['known']
    checks.append('比較基準ageは十五秒以内を境界包含し、超過はUNKNOWNで価格方向へ補完しない')
    return checks


def run() -> None:
    """
    機能: 十六数学・全feed入口・基準同値・費用・予約・未来不変を非金融で閉じる。
    引数: なし。
    返り値: None。source開始終端を束縛した人工証跡のみ保存する。
    """
    source=common.sources();checks=response_checks();arrays=0;truth=0
    configs=catalog.configs();assert len(configs)==len({c['id'] for c in configs})==16
    assert set(c['entry_id'] for c in configs)==set(catalog.entry_ids())
    for threshold in (.25,.5,.75):
        for known in (False,True):
            for count in (0,1,2,3):
                for balance in (-1.,0.,np.nextafter(threshold,-np.inf),threshold,np.nextafter(threshold,np.inf),1.):
                    value=dict(known=known,reason=1,direction_votes=count,balance=balance)
                    assert entry_policy.vote(value,threshold)[0]==(known and count>=2 and balance>=threshold);truth+=1
    for symbol in catalog.QUANTITY:
        for side in (1,-1):
            for qty in (1,2,3,catalog.QUANTITY[symbol]):
                a,l=artificial.fixture(symbol,side,qty);ctx=context_for(a,l)
                for config in configs:
                    b=interface.calibrate(ctx,config);q=Decimal(qty);atr=Decimal(str(ctx['anchor']['published_atr']));m=Decimal(str(daily.VALUE[symbol]))
                    r=q*atr*m;cost=q*Decimal(str(ctx['anchor']['published_spread']))*m+2*daily.fee(qty,symbol)
                    expected=Decimal(str(catalog.BUDGET[symbol])) if config['hard_basis']=='BUDGET' else Decimal(str(config['hard_multiple']))*r+cost
                    assert b['hard_loss_yen']==float(expected)
                    if config['exit_kind']=='fixed':
                        target=q*Decimal(str(daily.TICK[symbol]))*m
                        if config['target_basis']=='ATR':target=Decimal(str(config['target_multiple']))*r
                        if config['target_basis']=='TICK_NET':target-=2*daily.fee(qty,symbol)
                        assert b['target_yen']==float(target)
                    actual=interface.apply(ctx,config,python=False);oracle=interface.apply(ctx,config,python=True)
                    for field in ('orders','order_uids','order_fees','equity_yen','liquidation_yen','reserved_exit_fees'):
                        np.testing.assert_array_equal(actual[field],oracle[field]);arrays+=1
                    for cut in (2,3,4,7,9):
                        pa,pl=artificial.prefix(a,l,cut);pc=context_for(pa,pl,False);p=interface.apply(pc,config,python=True)
                        compare=actual['orders'][:,0]<cut
                        np.testing.assert_array_equal(p['orders'],actual['orders'][compare]);arrays+=1
                        np.testing.assert_array_equal(p['equity_yen'],actual['equity_yen'][:cut]);arrays+=1
                    checks.append(config['id']+'/'+symbol+str(side)+'Q'+str(qty)+':独立Decimal線・PythonJIT実会計・五接頭')
            a=fixture(symbol,side,3);gate=entry_policy.mask(a,'CONFIRM25');old=base_policy.mask(a['feed'],48,a['trade_features']['60'],'CONFIRM')
            np.testing.assert_array_equal(gate['accepted'],old[0]);arrays+=1
            values=interface.execute(a,'CONFIRM25',python=True)['values']
            assert values[9][0,4]==3
            ctx=interface.prepared('人工',a,values);baseline=interface.baseline(ctx)
            unit=daily.TICK[symbol]*daily.QUANTITY[symbol]*daily.VALUE[symbol]
            reference=daily.apply_policy(ctx['base'],ctx['quotes'],dict(profit_ticks=3/daily.QUANTITY[symbol],loss_ticks=2))
            for field in ('orders','order_uids','order_fees','equity_yen','liquidation_yen'):
                np.testing.assert_array_equal(baseline[field],reference[field]);arrays+=1
            assert baseline['summary']==reference['summary'] and baseline['control']==reference['control']
            charge=Decimal('41.8' if symbol=='TOPIX' else '11')
            assert ctx['base']['summary']['費用']==sum(int((Decimal(int(o[4]))*charge).to_integral_value(rounding=ROUND_FLOOR)) for o in values[0])
            reject=copy.deepcopy(a);reject['trade_features']['60'][12]['balance']=.5;reject['trade_features']['60'][25]['balance']=.75
            result=interface.execute(reject,'CONFIRM75',python=True)
            assert not np.any(result['values'][0][:,2]==0) and np.any(result['values'][0][:,2]==1)
            assert not result['gate']['accepted'][12] and result['gate']['accepted'][25]
            np.testing.assert_array_equal(reject['feed'],a['feed']);arrays+=1
            # サイズoffの九経済配列は、不変旧執行数学とexactである。
            r,q=a['record'],a['quotes'];num,den=catalog.FEE_RATIO[symbol]
            off=sizing_engine.simulate.py_func(r['time_s'],r['price'],q['bid'],q['ask'],q['quote_valid'],a['feed'],a['quiet'],a['quiet_force'],r['limit'],catalog.CAP[symbol],r['tick'],0.,True,gate['accepted'],False,catalog.BUDGET[symbol],1.,catalog.VALUE[symbol],num,den)
            old=sizing_baseline.simulate.py_func(r['time_s'],r['price'],q['bid'],q['ask'],q['quote_valid'],a['feed'],a['quiet'],a['quiet_force'],r['limit'],catalog.CAP[symbol],r['tick'],0.,True,gate['accepted'])
            for x,y in zip(off[:9],old):np.testing.assert_array_equal(x,y);arrays+=1
            for cut in (13,14,18,22,26,36):
                pa=prefix(a,cut);p=interface.execute(pa,'CONFIRM25',python=True)['values']
                for slot in (2,7,10):np.testing.assert_array_equal(p[slot],values[slot][:cut]);arrays+=1
                np.testing.assert_array_equal(p[0],values[0][values[0][:,0]<cut]);arrays+=1
            checks.append(symbol+str(side)+':元mask/旧P1同値・拒否後次paper親再参加・shadow非削除・実料・サイズoff九配列・全feed接頭')
    for current,old in (('sizing_engine.py','engine.py'),('order_kernel.py','order_kernel.py'),('sizing_baseline.py','baseline.py'),('base_policy.py','policy.py'),('daily.py','daily.py')):
        before=common.ROOT/'work/wave_v106/e01_size_goal_anchor'/old
        assert (common.HERE/current).read_bytes()==before.read_bytes()
    assert common.sources()==source
    common.write('十六対照の尺度と五入口及び全feed実玉接頭の人工検査.json',dict(全合格=True,
        条件数=16,観点=len(checks),確認観点=checks,配列照合=arrays,独立真偽表=truth,
        source_SHA256=source,金融=0,実入力=0,実台帳=0,原板=0,NPZ=0,API=0))
    print('十六対照人工合格 '+str(len(checks))+'観点/'+str(arrays)+'配列/'+str(truth)+'真偽表',flush=True)


def context_for(account: dict, ledger: dict, finish: bool=True) -> dict:
    """
    機能: 人工保存GUの七配列を同一人工文脈へ接続する。
    引数: account/ledger(dict)、finish(bool) は人工口座・同GU・完成範囲。
    返り値: dict は使用外をNoneとした共通文脈。実資料は読まない。
    """
    count=len(account['record']['price']);return interface.prepared('人工',account,reuse.values(ledger,count),finish)


if __name__=='__main__':run()
