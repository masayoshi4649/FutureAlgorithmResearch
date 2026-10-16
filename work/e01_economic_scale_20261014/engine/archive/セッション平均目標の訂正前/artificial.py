"""十四規模条件と影/実親分離を、旧source不変更の小合成で検査する。"""

import copy
from decimal import Decimal,ROUND_FLOOR
import numpy as np
import common
import catalog
import core
import daily
import interface
import entry_policy
import legacy_engine


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


def run() -> None:
    """
    機能: 14条件、requested枚数、親完結/紙上分離、fee、予約、部分、prefixを人工で検査する。
    引数: なし。
    返り値: None。金融/登録/実input無しの署名済み証跡を保存する。
    """
    source=common.sources();configs=catalog.configs();assert len(configs)==14
    checks=[];arrays=0;accounts=0
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
    assert common.sources()==source
    common.write('十四容量と実親分離及び局所清算の人工検査.json',dict(全合格=True,source_SHA256=source,条件数=14,
        人工口座=accounts,配列照合=arrays,観点=len(checks),確認観点=checks,金融=0,実input=0,旧台帳=0,原板=0,NPZ=0,API=0))
    print('規模十四人工合格 '+str(accounts)+'口座/'+str(arrays)+'配列',flush=True)


if __name__=='__main__':run()
