"""十四規模条件と影/実親分離を、旧source不変更の小合成で検査する。"""

import copy
import json
from decimal import Decimal,ROUND_FLOOR
import numpy as np
import common
import catalog
import core
import daily
import interface
import entry_policy
import legacy_engine
import runner
import statistics


def fixture(symbol: str, side: int=1, path: str='profit', count: int=64) -> dict:
    """
    機能: 保存paper5/10の二親と、利益/損失/追尾のnative小気配を作る。
    引数: symbol(str)、side(int)、path(str)、count(int) は商品・方向・人工経路・長さ。
    返り値: dict は完全又は切断用人工口座。実入力/板/台帳を読まない。
    """
    base=4000. if symbol=='TOPIX' else 65000.;tick=daily.TICK[symbol];v=catalog.HALF[symbol]
    bid=np.full(count,base);ask=bid+tick;times=np.arange(count,dtype=float)
    def shift(start: int, ratio: float) -> None:
        """
        機能: 指定行以降の観測気配を呼値格子上の人工値幅へ写す。
        引数: start(int)、ratio(float) は人工開始行と価格比。
        返り値: None。未来値は人工sourceへ限定する。
        """
        amount=np.ceil(base*ratio/tick)*tick;bid[start:]=base+amount;ask[start:]=bid[start:]+tick
    if path=='profit':shift(7,.007)
    elif path=='trail':shift(7,.007);shift(10,.004)
    elif path=='partial':shift(7,.003);shift(9,.007);shift(11,.004)
    elif path=='loss':shift(7,-.002)
    elif path=='flat':pass
    else:raise AssertionError(path)
    first=2 if symbol=='TOPIX' else 4;second=1 if symbol=='TOPIX' else 2;atr=3. if symbol=='TOPIX' else 50.
    last=ask.copy();feed=np.array([[5,0,0,1,v,last[5],0,1,0,atr],
        [12,0,0,-1,first,last[12],0,0,0,0],[16,0,0,-1,second,last[16],0,0,0,0],
        [20,0,0,-1,v-first-second,last[20],0,0,0,0],
        [25,0,1,1,v,last[25],0,1,0,atr],[35,0,1,-1,v,last[35],0,0,0,0]],float)
    if side<0:
        center=2*base+tick;last=center-last;bid,ask=center-ask,center-bid;feed[:,3]*=-1;feed[:,5]=center-feed[:,5]
    quotes=dict(seq=np.arange(1000,1000+count,dtype=np.int64),time_s=times,bid=bid,ask=ask,quote_valid=np.ones(count,bool))
    record=dict(price=last,seq=quotes['seq'],time_s=times,start=0.,end=float(count-1),limit=float(count-1),tick=tick)
    features={int(o[0]):dict(known=True,reason=0,direction_votes=4,balance=1.) for o in feed[feed[:,7]==1]}
    return dict(symbol=symbol,record=record,quotes=quotes,feed=feed,quiet=np.zeros(count,bool),quiet_force=np.zeros(count,bool),trade_features={'60':features})


def prefix(account: dict, cut: int) -> dict:
    """
    機能: 原期間/期限を維持して口座を当時の観測行とpaperだけに切る。
    引数: account(dict)、cut(int) は小人工と未来開始行。
    返り値: dict は未完成接頭。未来正常quoteを約定へ補わない。
    """
    out=copy.deepcopy(account)
    for section in ('record','quotes'):
        for key,value in out[section].items():
            if isinstance(value,np.ndarray):out[section][key]=value[:cut]
    out['feed']=out['feed'][out['feed'][:,0]<cut]
    for key in ('quiet','quiet_force'):out[key]=out[key][:cut]
    out['trade_features']['60']={r:v for r,v in out['trade_features']['60'].items() if r<cut}
    return out


def old_orders(account: dict) -> tuple:
    """
    機能: 私有同bytes旧coreで数量選択無しの半容量GU注文を人工対照にする。
    引数: account(dict) は小合成口座。
    返り値: tuple は旧十一配列とFAK証跡。旧module/cacheをimportしない。
    """
    r,q=account['record'],account['quotes'];s=account['symbol'];num,den=catalog.FEE_RATIO[s]
    return legacy_engine.simulate.py_func(r['time_s'],r['price'],q['bid'],q['ask'],q['quote_valid'],account['feed'],
        account['quiet'],account['quiet_force'],r['limit'],catalog.CAP[s],r['tick'],0.,True,
        np.ones(len(r['price']),bool),False,5000. if s=='TOPIX' else 2000.,1.,catalog.VALUE[s],num,den,True,np.ones(len(r['price']),np.int8))


def boundary_checks() -> int:
    """
    機能: 合成料0の正確な円境界でstop/goal/arm/partial/sceneと隣接価格を検査する。
    引数: なし。
    返り値: int は厳密境界検査数。実注文の料金は別のDecimal全行検査で保持する。
    """
    count=0
    for kind,mode,level in (('stop',0,3995.),('goal',1,4020.),('partial',3,4010.),('arm',2,4015.),('trail',2,4015.),('scene',1,3990.)):
        for position in (-1,0,1):
            a=fixture('TOPIX',1,'flat');q=a['quotes'];r=a['record']
            q['bid'][:]=3999.5;q['ask'][:]=4000.;r['price'][:]=4000.
            price=np.nextafter(level,-np.inf) if position<0 else np.nextafter(level,np.inf) if position>0 else level
            at=8 if kind=='trail' else 7
            if kind=='trail':q['bid'][7]=4020.;q['ask'][7]=4020.5
            q['bid'][at:]=price;q['ask'][at:]=price+.5
            if kind=='arm':q['bid'][8:]=4010.;q['ask'][8:]=4010.5
            values=core.simulate.py_func(r['time_s'],r['price'],q['bid'],q['ask'],q['quote_valid'],a['feed'],a['quiet'],a['quiet_force'],
                0.,r['limit'],10,.5,1000.,0,1,np.ones(len(r['price']),bool),np.zeros(len(r['price']),np.int8),10,0,mode,
                .00125,.00125,.005,.00375,.00125,.0025,.0025,.25,.0025)
            reason={'stop':141,'goal':140,'partial':144,'arm':142,'trail':142,'scene':143}[kind]
            row=8 if kind in ('arm','trail') else 7
            hits=values[4][(values[4][:,0]==row)&(values[4][:,3]==reason)]
            expected=position<=0 if kind in ('stop','trail','scene') else position>=0
            assert bool(len(hits))==expected,(kind,position,values[4])
            count+=1
    return count


def driver_checks() -> int:
    """
    機能: 登録拒否・十四case指紋・全場平均の分母と実親極値時刻を人工結合する。
    引数: なし。
    返り値: int は小結合検査数。旧金融/台帳/入力本文は読まない。
    """
    configs=catalog.configs();source=common.sources();fixed=dict(configs=configs,case_SHA256=runner.case_hashes(configs),source_SHA256=source)
    proposal=dict(id=catalog.TRIAL_ID,spec=dict(entry=dict(conditions=configs),implementation=source));found=[copy.deepcopy(proposal)]
    runner.registry_guard(found,fixed,proposal);runner.source_scope_guard();count=1
    # 保存JSONを再読込した配列型でも、元catalog/八部品/条件指紋が一致する。
    fixed=json.loads(json.dumps(fixed,ensure_ascii=False,allow_nan=False))
    proposal=json.loads(json.dumps(proposal,ensure_ascii=False,allow_nan=False))
    found=json.loads(json.dumps(found,ensure_ascii=False,allow_nan=False))
    runner.registry_guard(found,fixed,proposal);count+=1
    for kind in ('未登録','別trial','別spec','別条件','別casehash','別source'):
        f=copy.deepcopy(found);x=copy.deepcopy(fixed);p=copy.deepcopy(proposal)
        if kind=='未登録':f=[]
        elif kind=='別trial':f[0]['id']='人工別trial'
        elif kind=='別spec':f[0]['spec']['entry']['追加']=True
        elif kind=='別条件':x['configs'][0]['parent_stop_fraction']=.1
        elif kind=='別casehash':x['case_SHA256'][configs[0]['id']]='0'*64
        else:x['source_SHA256'][next(iter(source))]='0'*64
        rejected=False
        try:runner.registry_guard(f,x,p)
        except AssertionError:rejected=True
        assert rejected,kind;count+=1
    sessions=['人工'+str(i) for i in range(33)]
    for symbol in catalog.CAP:
        value=3300000.
        rows=[dict(session=s,symbol=symbol,収支=value if i==0 else 0.,利益=value if i==0 else 0.,損失=0.,親数=1 if i==0 else 0,
            最大買枚数=10 if i==0 else 0,最大売枚数=0) for i,s in enumerate(sessions)]
        profile=[dict(session=sessions[0],net_yen=value,entry_quantity=10,worst_parent_liquidation_yen=-10.)]
        econ=statistics.economic(rows,profile,symbol)
        assert econ['mean_session_net_yen']==100000. and econ['mean_parent_net_yen']==3300000.
        assert econ['target_mean_success']==(True if symbol=='TOPIX' else None)
        trimmed=statistics.economic(rows[1:],[],symbol);assert trimmed['mean_session_net_yen']==0. and trimmed['mean_parent_net_yen'] is None
        assert trimmed['mean_initial_quantity'] is None and trimmed['target_mean_success']==(False if symbol=='TOPIX' else None);count+=6
    for symbol in catalog.CAP:
        a=fixture(symbol,1,'partial');cfg=next(c for c in configs if c['quantity_mode']=='FULL' and c['exit_id']=='PARTIAL')
        output=interface.play(a,cfg,'人工',python=True);profiles=interface.parent_diagnostics(a,output)
        for p in profiles:
            assert p['first_parent_liquidation_argmin']['parent_liquidation_yen']==p['worst_parent_liquidation_yen']
            assert p['first_parent_liquidation_argmax']['parent_liquidation_yen']==p['best_parent_liquidation_yen']
            for event in p['exits']:
                assert event['source_parent_liquidation_yen']==output['economic_curve'][event['source_row'],2]
            count+=3
        packed=runner.packed_curve(output['economic_curve']);assert packed['shape'][1]==10;count+=1
    return count


def run(proof_name: str='十四容量と実親分離及び登録接口の人工検査_v3.json') -> None:
    """
    機能: 14条件、requested枚数、親完結/紙上分離、fee、予約、部分、prefixを人工で検査する。
    引数: proof_name(str) は全source追加後の新署名名。
    返り値: None。金融/登録/実input無しの署名済み証跡を保存する。
    """
    source=common.sources();configs=catalog.configs();assert len(configs)==14
    checks=[];arrays=0;accounts=0;boundaries=boundary_checks();driver=driver_checks()
    for symbol in catalog.CAP:
        for side in (1,-1):
            for path in ('flat','profit','trail','partial','loss'):
                a=fixture(symbol,side,path)
                for config in configs:
                    py=interface.play(a,config,'人工',python=True);jit=interface.play(a,config,'人工',python=False);accounts+=1
                    for key in ('orders','order_uids','economic_curve','publication_events','exit_judgments','execution_events','actual_origins'):
                        np.testing.assert_array_equal(py[key],jit[key]);arrays+=1
                    assert py['summary']==jit['summary'] and py['parent']==jit['parent']
                    new=py['orders'][py['orders'][:,7]==1]
                    if config['quantity_mode']!='RISK':assert np.all(new[:,4]==config['quantity'][symbol])
                    charge=Decimal('41.8' if symbol=='TOPIX' else '11')
                    total=sum(int((Decimal(int(o[4]))*charge).to_integral_value(rounding=ROUND_FLOOR)) for o in py['orders'])
                    assert total==py['summary']['費用']
                    profile=interface.parent_diagnostics(a,py);assert len(profile)==len(py['parent'])
                    assert sum(p['net_yen'] for p in profile)==py['summary']['収支']
                    for cut in (5,6,8,11,17,26,37):
                        pre=interface.play(prefix(a,cut),config,'人工',finish=False,python=True)
                        np.testing.assert_array_equal(pre['orders'],py['orders'][py['orders'][:,0]<cut]);arrays+=1
                        np.testing.assert_array_equal(pre['economic_curve'],py['economic_curve'][:cut]);arrays+=1
                    if config['exit_id']=='TARGET' and path=='profit':
                        first=[p for p in profile if p['parent']==0];assert len(first)==1 and first[0]['actual_completed_before_paper_exit']
                        assert py['summary']['親数']>=2,'利益終了後も次paper候補を実運転する'
                    checks.append(symbol+str(side)+'/'+path+'/'+config['id'])
            # 原GU経済同値は親/場guardをOFFにした半量だけ。新14の成功標本ではない。
            a=fixture(symbol,side,'flat');config=copy.deepcopy(configs[0]);config['parent_stop_fraction']=np.inf;config['session_stop_fraction']=np.inf
            current=interface.play(a,config,'人工',python=True);old=old_orders(a)
            np.testing.assert_array_equal(current['orders'],old[0]);np.testing.assert_array_equal(current['order_uids'],old[5]);arrays+=2
            # unknownとq0を将来の気配で救済せず、既normal第一試行不成立は一回失効。
            a=fixture(symbol,side,'flat');a['quotes']['quote_valid'][5]=False
            out=interface.play(a,configs[4],'人工',python=True)
            assert not np.any((out['orders'][:,2]==0)&(out['orders'][:,7]==1))
            a=fixture(symbol,side,'flat');tick=a['record']['tick'];a['quotes']['bid'][6]+=side*2*tick;a['quotes']['ask'][6]+=side*2*tick
            out=interface.play(a,configs[4],'人工',python=True)
            assert not np.any(out['orders'][:,2]==0)
            # 第一正常quoteと当行paper退出ではfill先、過去paper退出なら取消先。
            a=fixture(symbol,side,'flat');a['quotes']['quote_valid'][6:13]=False
            out=interface.play(a,configs[4],'人工',python=True);assert not np.any(out['orders'][:,2]==0)
            a=fixture(symbol,side,'flat');a['quotes']['quote_valid'][6:12]=False
            out=interface.play(a,configs[4],'人工',python=True);assert np.any((out['orders'][:,2]==0)&(out['orders'][:,7]==1))
            # 小risk数量では四分の一floorをゼロ注文にしない。
            for desired,atr in ((1,40. if symbol=='TOPIX' else 1200.),(2,18. if symbol=='TOPIX' else 600.),(3,13. if symbol=='TOPIX' else 400.)):
                a=fixture(symbol,side,'partial');a['feed'][0,9]=atr
                config=next(c for c in configs if c['quantity_mode']=='RISK' and c['exit_id']=='PARTIAL')
                out=interface.play(a,config,'人工',python=True);new=out['orders'][(out['orders'][:,2]==0)&(out['orders'][:,7]==1)]
                assert len(new)==1 and new[0,4]==desired
                assert not np.any((out['orders'][:,2]==0)&(out['orders'][:,6]==144))
            checks.append(symbol+str(side)+':旧GU半量OFF経済同値・公開不明・一回FAK・pendingpaper取消・小q部分floor')
    # ----------------------------------------
    # 前親cashを目標へ混ぜず、GU予約を保ち残stopだけ加える。未来値は当時へ逆流しない。
    a=fixture('TOPIX',1,'flat');cfg=next(c for c in configs if c['quantity_mode']=='FULL' and c['exit_id']=='GU')
    a['quotes']['bid'][12:]=3993.;a['quotes']['ask'][12:]=3993.5
    output=interface.play(a,cfg,'人工',python=True)
    closes=output['orders'][(output['orders'][:,0]==13)&(output['orders'][:,7]==0)]
    assert closes[:,4].tolist()==[4.,6.] and closes[:,6].tolist()==[91.,141.]
    assert [daily.fee(int(o[4]),'TOPIX') for o in closes]==[167,250]
    checks.append('GU当行4予約＋親stop残6は次normalで別注文167/250円。予約を全量一注文へ置換しない。')
    a=fixture('TOPIX',1,'flat');a['quotes']['bid'][7:]=3992.;a['quotes']['ask'][7:]=3992.5
    cfg=next(c for c in configs if c['quantity_mode']=='RISK' and c['exit_id']=='TARGET')
    output=interface.play(a,cfg,'人工',python=True);second=output['publication_events'][output['publication_events'][:,1]==1]
    assert len(second)==1 and second[0,5]==0 and second[0,15]==97
    checks.append('RISKの場損失後available枯渇で次q0。固定量と同じ活動を仮定しない。')
    for symbol in catalog.CAP:
        a=fixture(symbol,1,'partial');cfg=next(c for c in configs if c['quantity_mode']=='FULL' and c['exit_id']=='PARTIAL')
        full=interface.play(a,cfg,'人工',python=True);future=copy.deepcopy(a);cut=11
        future['quotes']['bid'][cut:]+=100.;future['quotes']['ask'][cut:]+=200.;future['record']['price'][cut:]+=500.
        future['quotes']['quote_valid'][cut:]=False
        for row,v in future['trade_features']['60'].items():
            if row>=cut:v['known']=False;v['balance']=None
        observed=interface.play(future,cfg,'人工',finish=False,python=True)
        np.testing.assert_array_equal(observed['orders'][observed['orders'][:,0]<cut],full['orders'][full['orders'][:,0]<cut])
        np.testing.assert_array_equal(observed['economic_curve'][:cut],full['economic_curve'][:cut]);arrays+=2
    assert common.sources()==source
    common.write(proof_name,dict(全合格=True,source_SHA256=source,条件数=14,
        人工口座=accounts,配列照合=arrays,厳密境界=boundaries,driver結合=driver,観点=len(checks),確認観点=checks,
        金融=0,実input=0,旧台帳=0,原板=0,NPZ=0,API=0,
        変更説明='13源/v2人工を保持。登録fixed/proposal/foundのJSON保存再読込人工を追加した最終17源。14売買係数と経済coreは不変更。'))
    print('規模十四人工合格 '+str(accounts)+'口座/'+str(arrays)+'配列',flush=True)


if __name__=='__main__':run()
