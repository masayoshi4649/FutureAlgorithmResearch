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
import sizing_engine_legacy


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


def legacy(account: dict, gate: dict, python: bool=True) -> tuple:
    """
    機能: 同bytes私有の旧数量engineだけを人工市場対照として呼ぶ。
    引数: account/gate(dict)、python(bool) は人工口座と同mask。
    返り値: tuple は旧十一配列。旧所有領域のmodule/JITはimportしない。
    """
    r,q=account['record'],account['quotes'];symbol=account['symbol'];num,den=catalog.FEE_RATIO[symbol]
    fn=sizing_engine_legacy.simulate.py_func if python else sizing_engine_legacy.simulate
    return fn(r['time_s'],r['price'],q['bid'],q['ask'],q['quote_valid'],account['feed'],account['quiet'],account['quiet_force'],
        r['limit'],catalog.CAP[symbol],r['tick'],0.,True,gate['accepted'],True,catalog.BUDGET[symbol],1.,catalog.VALUE[symbol],num,den)


def run(proof_name: str='一回FAKと全feed再参加及び旧市場同値の人工検査.json') -> None:
    """
    機能: FAK境界・待機・失効・影・費用・接頭と旧市場を人工だけで検査する。
    引数: proof_name(str) は新source束縛の未保存証跡名。
    返り値: None。正式input・GU・金融・APIを実行しない。
    """
    source=common.sources();checks=driver_checks();arrays=0;truth=0
    assert len(catalog.configs())==18 and len(catalog.new_gu_routes())==9
    for gate,(threshold,count) in catalog.GATES.items():
        for known in (False,True):
            for n in (0,1,2,3,4,5):
                for balance in (-1.,0.,np.nextafter(threshold,-np.inf),threshold,np.nextafter(threshold,np.inf),1.):
                    value=dict(known=known,reason=4,direction_votes=n,balance=balance)
                    assert entry_policy.vote(value,threshold,count)[0]==(known and n>=count and balance>=threshold);truth+=1
    for symbol in catalog.QUANTITY:
        for side in (1,-1):
            for quantity in (1,2,3,catalog.QUANTITY[symbol]):
                a=fixture(symbol,side,quantity)
                for gate in catalog.entry_ids():
                    fresh=interface.execute(a,gate,'MARKET',python=True);old=legacy(a,fresh['gate'])
                    for x,y in zip(fresh['values'],old):np.testing.assert_array_equal(x,y);arrays+=1
                    assert fresh['fak_events'].shape==(0,19)
                    compiled=interface.execute(a,gate,'MARKET',python=False)
                    for x,y in zip(compiled['values'],old):np.testing.assert_array_equal(x,y);arrays+=1
                    assert compiled['fak_events'].shape==(0,19)
                checks.append(symbol+str(side)+'Q'+str(quantity)+':MARKET旧十一配列exact、PythonJIT、FAK証跡空')
                for tolerance in (0,1):
                    for adverse in (-1,0,1,2):
                        a=fixture(symbol,side,quantity);q=a['quotes'];tick=a['record']['tick']
                        q['bid'][13]+=side*adverse*tick;q['ask'][13]+=side*adverse*tick
                        route='FAK'+str(tolerance);fresh=interface.execute(a,'G50',route,python=True)
                        compiled=interface.execute(a,'G50',route,python=False)
                        for x,y in zip(fresh['values'],compiled['values']):np.testing.assert_array_equal(x,y);arrays+=1
                        np.testing.assert_array_equal(fresh['fak_events'],compiled['fak_events']);arrays+=1
                        actual=fresh['values'][0];first=actual[(actual[:,2]==0)&(actual[:,7]==1)]
                        assert len(first)==int(adverse<=tolerance)
                        attempts=fresh['fak_events'][(fresh['fak_events'][:,1]==2)&(fresh['fak_events'][:,2]==0)]
                        assert len(attempts)==1 and attempts[0,0]==13 and attempts[0,13]==int(adverse<=tolerance)
                        public=fresh['fak_events'][(fresh['fak_events'][:,1]==1)&(fresh['fak_events'][:,2]==0)][0]
                        cap=a['quotes']['ask' if side>0 else 'bid'][12]+side*tolerance*tick
                        assert public[6]==cap and fresh['gate']['accepted'][12]
                        if len(first):assert first[0,0]==13 and first[0,5]==q['ask' if side>0 else 'bid'][13]
                        else:
                            assert not np.any(actual[:,2]==0) and np.any(actual[:,2]==1)
                            # 次の有利quoteでも旧pendingを復活させず、影部分feedは全て残る。
                            assert not fresh['values'][7][14,5] and fresh['values'][7][14,6]
                            assert fresh['values'][9][0,15]==1 and fresh['values'][9][0,4]==quantity
                            assert fresh['values'][5][actual[:,7]==1][0]==0
                        base=daily.reconstruct(('人工',symbol),actual,fresh['values'][5],q)
                        charge=Decimal('41.8' if symbol=='TOPIX' else '11')
                        expected=sum(int((Decimal(int(o[4]))*charge).to_integral_value(rounding=ROUND_FLOOR)) for o in actual)
                        assert base['summary']['費用']==expected
                        for cut in (12,13,14,17,22,26,36):
                            p=interface.execute(prefix(a,cut),'G50',route,python=True)
                            for slot in (2,7,10):np.testing.assert_array_equal(p['values'][slot],fresh['values'][slot][:cut]);arrays+=1
                            np.testing.assert_array_equal(p['values'][0],actual[actual[:,0]<cut]);arrays+=1
                            np.testing.assert_array_equal(p['fak_events'],fresh['fak_events'][fresh['fak_events'][:,0]<cut]);arrays+=1
                        checks.append(symbol+str(side)+'Q'+str(quantity)+'/'+route+'/不利'+str(adverse)+':等号対称・当行禁止・一回失効・影後参加・実料・七接頭')
            a=fixture(symbol,side,1);a['quotes']['quote_valid'][13:16]=False
            fresh=interface.execute(a,'G50','FAK0',python=True);attempts=fresh['fak_events'][fresh['fak_events'][:,1]==2]
            assert attempts[0,0]==16
            assert np.any(fresh['values'][0][:,0]==16),'初goodとpaper撤回同行は実fillが先'
            cut=interface.execute(prefix(a,15),'G50','FAK0',python=True)
            assert not len(cut['values'][0]) and cut['values'][7][-1,5]==1 and not np.any(cut['fak_events'][:,1]==2)
            for reason in ('quiet','期限','paper'):
                b=copy.deepcopy(a)
                if reason=='quiet':b['quiet_force'][16]=True
                elif reason=='期限':b['record']['limit']=16.
                else:
                    b['feed'][b['feed'][:,0]==16,0]=15
                out=interface.execute(b,'G50','FAK0',python=True)
                assert not np.any(out['values'][0][:,2]==0)
                assert not np.any((out['fak_events'][:,2]==0)&(out['fak_events'][:,1]==2))
            # capはspread自体を守らない。買ask同じでbidだけ下がればFAK0でも約定する。
            b=fixture(symbol,side,1)
            b['quotes']['bid' if side>0 else 'ask'][13]-=side*b['record']['tick']
            spread=interface.execute(b,'G50','FAK0',python=True)
            assert np.any((spread['values'][0][:,2]==0)&(spread['values'][0][:,7]==1))
            # 公開不明をfuture firstgoodで救済せず、q0は実予約を作らない。
            unknown=fixture(symbol,side,1);unknown['quotes']['quote_valid'][12]=False
            out=interface.execute(unknown,'G50','FAK0',python=True)
            assert out['values'][9][0,4]==out['values'][9][0,15]==0 and not np.any(out['values'][0][:,2]==0)
            checks.append(symbol+str(side)+':無効quoteは試行無し・未着pending保持・旧取消優先・広spread反証・公開不明非救済')
    assert common.sources()==source
    common.write(proof_name,dict(全合格=True,source_SHA256=source,条件数=18,観点=len(checks),確認観点=checks,
        配列照合=arrays,独立真偽表=truth,金融=0,実input=0,旧GU台帳=0,原板=0,NPZ=0,API=0))
    print('一回FAK人工合格 '+str(len(checks))+'観点/'+str(arrays)+'配列/'+str(truth)+'真偽表',flush=True)


def driver_checks() -> list[str]:
    """
    機能: 十八政策・六保存対照・登録前拒否と一次FAK診断を小合成で結合する。
    引数: なし。
    返り値: list[str] はsource・表示・初受理持越しを確認した範囲。実input/旧台帳0。
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
        elif kind=='別条件':x['configs'][0]['adverse_ticks']=5
        elif kind=='別casehash':x['case_SHA256'][configs[0]['id']]='0'*64
        else:x['source_SHA256'][next(iter(source))]='0'*64
        rejected=False
        try:runner.registry_guard(f,x,p)
        except AssertionError:rejected=True
        assert rejected,kind
    checks=['六登録拒否と新所有JITを実input前に確認'];fake_records={}
    for symbol in catalog.QUANTITY:
        for side in (1,-1):
            a=fixture(symbol,side,1);a['quotes']['bid'][13]+=side*2*a['record']['tick'];a['quotes']['ask'][13]+=side*2*a['record']['tick']
            a['feed'][a['feed'][:,0]==25,9]=.5 if symbol=='TOPIX' else 40.
            outputs={}
            for route,execution in catalog.new_gu_routes():
                observed=interface.execute(a,route,execution,python=True);ctx=interface.prepared('人工',a,observed['values'])
                for config in (c for c in configs if c['entry_id']==route and c['execution_id']==execution):
                    fresh=interface.apply(ctx,config,observed['gate'],python=True,fak_events=observed['fak_events'])
                    d=runner.fak_diagnosis(a,fresh);assert fresh['goal_anchor']['数量']==1
                    if execution!='MARKET':
                        assert d['carryover_after_unfilled_initial'] and d['first_actual']['source_row']==25
                        assert fresh['goal_anchor']['受理行']==12 and d['first_actual']['published_ATR']==a['feed'][4,9]
                        assert d['GU全試行']['試行失効']==1 and d['GU全試行']['試行約定']==1
                    outputs[config['id']]=fresh
                stats=runner.activity(a,observed['values'],observed['gate'],observed['fak_events'])
                assert stats['paper_candidates']==stats['known_votes']==2
                fake_records.setdefault('人工_Day',{}).setdefault(symbol,{})[route+'|'+execution]=stats
            assert len(outputs)==18
            for gate in ('G25','G50','G75'):
                observed=interface.execute(a,gate,'MARKET',python=True);ctx=interface.prepared('人工',a,observed['values'])
                for target in ('P1','ATR25'):
                    old=interface.market_reference(ctx,gate,target);runner.baseline_exact(old,interface.market_reference(ctx,gate,target),len(a['record']['price']))
            checks.append(symbol+str(side)+':十八出口接続・六保存同値接口・初受理未約定から後q/ATRへ旧目標持越し・全GUと政策接頭区別')
    aggregate=runner.activity_summary(fake_records)
    assert aggregate['G50|FAK0']['TOPIX']['Day']['sessions']==1 and aggregate['G50|FAK0']['TOPIX']['全33']['paper_candidates']==2
    return checks


if __name__=='__main__':run()
