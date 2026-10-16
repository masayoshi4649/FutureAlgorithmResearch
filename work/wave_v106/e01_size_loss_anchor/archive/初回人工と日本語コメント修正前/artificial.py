"""初回受理の比例損失線を、不変数量経済・次気配超過・回復勝ち喪失で検査する。"""

from decimal import Decimal
import copy

import numpy as np

import common
import catalog
import daily
import engine
import fixed_goal_interface
import fixed_loss_policy
import goal_policy
import interface
import runner
import reuse
import storage


def fixture(symbol: str, side: int=1, quantity: int=3) -> dict:
    """
    機能: 影の部分返済と後続再参加を持つ、native呼値の人工口座を作る。
    引数: symbol(str)、side/quantity(int) は商品・方向・最初の予定実枚数。
    返り値: dict は人工専用口座。大型入力や金融結果を読まない。
    """
    tick=daily.TICK[symbol];qty=catalog.QUANTITY[symbol];n=18;base=4000. if symbol=='TOPIX' else 65000.
    bid=np.full(n,base);ask=bid+tick;p=ask.copy();times=np.arange(n,dtype=float)
    first=2 if symbol=='TOPIX' else 4;second=1 if symbol=='TOPIX' else 2
    atr={1:3.,2:1.5,3:1.}[quantity] if symbol=='TOPIX' else {1:100.,2:70.,3:50.}[quantity]
    feed=np.array([[1,0,0,1,qty,p[1],0,1,0,atr],
        [4,0,0,-1,first,p[4],0,0,0,0],[6,0,0,-1,second,p[6],0,0,0,0],
        [8,0,0,-1,qty-first-second,p[8],0,0,0,0],
        [10,0,1,1,qty,p[10],0,1,0,atr],[14,0,1,-1,qty,p[14],0,0,0,0]],float)
    if side<0:
        center=2*base+tick;p=center-p;bid,ask=center-ask,center-bid;feed[:,3]*=-1;feed[:,5]=center-feed[:,5]
    quotes=dict(seq=np.arange(n,dtype=np.int64),time_s=times,bid=bid,ask=ask,quote_valid=np.ones(n,bool))
    record=dict(seq=quotes['seq'],time_s=times,price=p,start=0.,end=17.,limit=17.,tick=tick)
    features={int(o[0]):dict(known=True,reason=0,direction_votes=2,balance=1.,accepted=True) for o in feed[feed[:,7]==1]}
    return dict(symbol=symbol,record=record,quotes=quotes,feed=feed,quiet=np.zeros(n,bool),quiet_force=np.zeros(n,bool),trade_features={'60':features})


def prefix(account: dict, cut: int) -> dict:
    """
    機能: 未来limitを保持したまま、当時に観測済みの口座接頭を切り出す。
    引数: account(dict)、cut(int) は人工素材と除外開始行。
    返り値: dict は未完了接頭。未返済を場末清算しない。
    """
    result=dict(account)
    for name in ('record','quotes'):
        result[name]={k:v[:cut].copy() if isinstance(v,np.ndarray) else v for k,v in account[name].items()}
    result['feed']=account['feed'][account['feed'][:,0]<cut].copy()
    result['quiet']=account['quiet'][:cut].copy();result['quiet_force']=account['quiet_force'][:cut].copy()
    result['trade_features']={'60':{r:v for r,v in account['trade_features']['60'].items() if r<cut}}
    return result


def same(values: tuple, expected: tuple) -> int:
    """
    機能: 影・予約・UID・数量・実料を含む11配列を全要素exactへ照合する。
    引数: values/expected(tuple) は新接口と同bytes旧数量対照。
    返り値: int は一致した配列数。不一致は検査を中断する。
    """
    assert len(values)==len(expected)==11
    for actual,other in zip(values,expected):np.testing.assert_array_equal(actual,other)
    return 11


def old_goal_output(session: str, account: dict, config: dict, values: tuple) -> dict:
    """
    機能: 同bytesの旧利確アンカー政策を、新所有域だけで対照再生する。
    引数: session(str)、account/config(dict)、values(tuple) は人工専用の共有GU。
    返り値: dict は利確比例・損失固定の旧政策。旧金融や旧moduleを実行しない。
    """
    base=daily.reconstruct((session,account['symbol']),values[0],values[5],account['quotes'])
    anchor=fixed_loss_policy.observe_anchor(account,config,values)
    return fixed_loss_policy.apply(base,account['quotes'],config,anchor)


def driver_connection() -> list[str]:
    """
    機能: 登録guard、条件全字段指紋、アンカー境界保存と同親寄与を人工で接続する。
    引数: なし。正式入力又は旧金融台帳は読まない。
    返り値: list[str] は確認した実行前資格と保存会計の範囲。
    """
    configs=catalog.configs();sources=common.sources();hashes=runner.case_hashes(configs)
    spec=dict(entry=dict(conditions=configs),implementation=sources)
    fixed=dict(configs=configs,case_SHA256=hashes,source_SHA256=sources)
    prepared_plan=dict(id=catalog.TRIAL_ID,spec=spec)
    registered=[dict(id=catalog.TRIAL_ID,spec=spec)]
    runner.registry_guard(registered,fixed,prepared_plan);runner.source_scope_guard()
    for mode in ('未登録','別trial','別spec','別条件指紋','別catalog条件'):
        found=copy.deepcopy(registered);freeze=copy.deepcopy(fixed);plan=copy.deepcopy(prepared_plan)
        if mode=='未登録':found=[]
        elif mode=='別trial':found[0]['id']='人工別試行'
        elif mode=='別spec':found[0]['spec']['entry']['追加']=True
        elif mode=='別条件指紋':freeze['case_SHA256'][configs[0]['id']]='0'*64
        else:freeze['configs'][0]['profit_ticks']=99
        failed=False
        try:runner.registry_guard(found,freeze,plan)
        except AssertionError:failed=True
        assert failed,mode
    checks=['driverのtrial/spec/casehash/catalog/source照合が入力前に別条件を拒否し、新所有JITのみを使う']
    for symbol in catalog.QUANTITY:
        for side in (1,-1):
            a=fixture(symbol,side,1);config=catalog.configs()[0]
            entry=a['quotes']['ask' if side>0 else 'bid'][2]
            for row,steps in ((3,1),(4,2),(5,3)):
                if side>0:
                    a['quotes']['bid'][row]=entry+steps*daily.TICK[symbol]
                    a['quotes']['ask'][row]=a['quotes']['bid'][row]+daily.TICK[symbol]
                else:
                    a['quotes']['ask'][row]=entry-steps*daily.TICK[symbol]
                    a['quotes']['bid'][row]=a['quotes']['ask'][row]-daily.TICK[symbol]
            values=interface.execute(a,config,python=True)
            fresh=interface.account_output('人工',a,config,values)
            before=old_goal_output('人工',a,config,values)
            delta=storage.delta(before,fresh)
            assert fresh['control']['種別']=='利益目標' and delta['収支変化']==0
            diagnostic=runner.boundary(a,fresh)
            assert diagnostic['anchor']['数量']==1 and diagnostic['目標円']==config['profit_goal_yen'][symbol]/catalog.QUANTITY[symbol]
            assert diagnostic['損失停止線円']==catalog.BUDGET[symbol]/catalog.QUANTITY[symbol]
            assert diagnostic['新規数量選択予算円']==catalog.BUDGET[symbol]
            assert diagnostic['実政策初回新規']['quantity']==1
            saved=storage.stored(fresh,len(a['record']['price']))
            for name in ('equity_yen','liquidation_yen','reserved_exit_fees','long_qty','short_qty','execution_states',
                         'gate_accepted','gate_reasons','sizing_fee_curve'):
                encoded=saved[name];locations=np.searchsorted(encoded['rows'],np.arange(encoded['length']),side='right')-1
                np.testing.assert_array_equal(encoded['values'][locations],fresh[name])
            empty=fixture(symbol,side);empty['record']['limit']=2.
            output=interface.account_output('人工',empty,config,interface.execute(empty,config,python=True))
            info=runner.boundary(empty,output)
            assert info['anchor']['成立'] and info['実政策初回新規'] is None and info['目標円'] is not None
            checks.append(symbol+str(side)+':旧固定円との同親五寄与・264比較形式・疎保存と未約定アンカー境界を保持')
            configs=[c for c in catalog.configs() if c['mode']=='CONFIRM']
            one=storage.stored(interface.account_output('人工',a,configs[0],values),len(a['record']['price']))
            two=storage.stored(interface.account_output('人工',a,configs[1],values),len(a['record']['price']))
            shared=reuse.pair(one,two,len(a['record']['price']))
            for index in reuse.USED:np.testing.assert_array_equal(shared[index],values[index])
            assert all(shared[index] is None for index in (1,2,3,4))
            for c in configs:
                restored=interface.account_output('人工',a,c,shared)
                direct=interface.account_output('人工',a,c,values)
                for field in ('orders','order_uids','order_fees','equity_yen','liquidation_yen','long_qty','short_qty'):
                    np.testing.assert_array_equal(restored[field],direct[field])
                for field in ('summary','parent','control','goal_anchor','loss_anchor'):
                    assert restored[field]==direct[field]
            bad=copy.deepcopy(two);bad['execution_states']['values'][0,0]+=1
            rejected=False
            try:reuse.pair(one,bad,len(a['record']['price']))
            except AssertionError:rejected=True
            assert rejected
            ignored=dict(one,orders=np.empty((0,8)),equity_yen=np.zeros(len(a['record']['price'])))
            copied=reuse.values(ignored,len(a['record']['price']))
            for index in reuse.USED:np.testing.assert_array_equal(copied[index],shared[index])
            checks.append(symbol+str(side)+':保存GU七配列の二政策同値・復元政策exact・実政策曲線との取り違え拒否')
    return checks


# ----------------------------------------
def run(proof_name: str='初回受理の比例損失と回復勝ち喪失及び旧GU同値の人工検査.json') -> None:
    """
    機能: 利益損失の受理固定・次気配超過・回復勝ち喪失とGU不変を人工で検査する。
    引数: proof_name(str) は新しいsource束縛の人工証跡名。初回greenを上書きしない。
    返り値: None。新所有証跡だけ保存し、正式金融・大型入力は実行しない。
    """
    start=common.sources();checks=[];arrays=0
    for symbol in catalog.QUANTITY:
        for side in (1,-1):
            for quantity in (1,2,3):
                account=fixture(symbol,side,quantity)
                for config in catalog.configs():
                    values=interface.execute(account,config)
                    arrays+=same(values,fixed_goal_interface.execute(account,config))
                    arrays+=same(values,interface.execute(account,config,python=True))
                    anchor=goal_policy.observe_anchor(account,config,values)
                    assert anchor['数量']==quantity and anchor['受理行']==1
                    expected=Decimal(str(config['profit_goal_yen'][symbol]))*quantity/catalog.QUANTITY[symbol]
                    assert anchor['利益目標円']==float(expected)
                    output=interface.account_output('人工',account,config,values)
                    assert output['goal_anchor']==anchor
                    assert output['control']['損失予算']==catalog.BUDGET[symbol]*quantity/catalog.QUANTITY[symbol]
                    assert output['loss_anchor']['新規数量選択予算円']==catalog.BUDGET[symbol]
                    assert output['actual_leg_totals']['net']==output['summary']['収支']
                    for cut in (1,2,3,5,9,11,15):
                        past=prefix(account,cut);short=interface.execute(past,config,python=True)
                        known=goal_policy.observe_anchor(past,config,short)
                        if cut<=1:assert not known['成立'] and known['利益目標円'] is None
                        else:assert known==anchor
                        altered=fixture(symbol,side,quantity)
                        altered['quotes']['bid'][cut:]+=100*daily.TICK[symbol]
                        altered['quotes']['ask'][cut:]+=100*daily.TICK[symbol]
                        altered['quotes']['quote_valid'][cut:]=False
                        future=interface.execute(prefix(altered,cut),config,python=True)
                        arrays+=same(short,future)
                        assert goal_policy.observe_anchor(prefix(altered,cut),config,future)==known
                    checks.append(symbol+str(side)+'Q'+str(quantity)+config['id']+':比例目標・旧11配列・PythonJIT・七接頭')
            config=catalog.configs()[0]
            for rejection in ('q0','不明','母拒否','静観'):
                account=fixture(symbol,side,1)
                account['feed'][4,9]=1.5 if symbol=='TOPIX' else 70.
                if rejection=='q0':account['feed'][0,9]=1000.
                elif rejection=='不明':account['quotes']['quote_valid'][1]=False
                elif rejection=='母拒否':account['trade_features']['60'][1]=dict(known=False,reason=16,direction_votes=0,balance=None)
                else:account['quiet'][1:3]=True
                values=interface.execute(account,config,python=True);anchor=goal_policy.observe_anchor(account,config,values)
                assert anchor['受理行']==10 and anchor['数量']==2 and values[9][0,15]==0
                checks.append(symbol+str(side)+':'+rejection+'は固定せず次の初回受理Q2で固定')
            account=fixture(symbol,side,1);account['quiet'][2:4]=True
            account['feed'][4,9]=1. if symbol=='TOPIX' else 50.
            values=interface.execute(account,config,python=True);anchor=goal_policy.observe_anchor(account,config,values)
            assert anchor['受理行']==1 and anchor['数量']==1
            assert not np.any(values[0][values[0][:,2]==0,7]) and values[9][1,4]==3
            output=interface.account_output('人工',account,config,values)
            assert output['control']['目標']==config['profit_goal_yen'][symbol]/catalog.QUANTITY[symbol]
            assert output['control']['損失予算']==catalog.BUDGET[symbol]/catalog.QUANTITY[symbol]
            checks.append(symbol+str(side)+':受理Q1取消後Q3再参加しても利益と損失の両停止線を保持')
            account=fixture(symbol,side);account['quotes']['quote_valid'][5:12]=False
            values=interface.execute(account,config,python=True);anchor=goal_policy.observe_anchor(account,config,values)
            assert values[9][1,15]==0 and anchor['受理行']==1 and anchor['数量']==3
            checks.append(symbol+str(side)+':残玉返済予約中の後続busy拒否は目標へ再利用しない')
            for end in (1.,2.):
                account=fixture(symbol,side);account['record']['limit']=end
                values=interface.execute(account,config,python=True);anchor=goal_policy.observe_anchor(account,config,values)
                assert len(values[0])==0
                if end==1.:assert not anchor['成立']
                else:assert anchor['成立'] and anchor['受理行']==1 and anchor['数量']==3
                output=interface.account_output('人工',account,config,values)
                assert output['summary']['親数']==0 and output['summary']['利益割合'] is None
                assert output['loss_anchor']['新規数量選択予算円']==catalog.BUDGET[symbol]
                assert output['control']['損失予算']==(None if end==1. else catalog.BUDGET[symbol]*3/catalog.QUANTITY[symbol])
                checks.append(symbol+str(side)+':期限'+str(end)+'は受理前拒否と受理後未約定取消を区別')
            account=fixture(symbol,side)
            entry=account['quotes']['ask' if side>0 else 'bid'][2]
            for row,steps in ((3,1),(4,2),(5,3)):
                if side>0:
                    account['quotes']['bid'][row]=entry+steps*daily.TICK[symbol]
                    account['quotes']['ask'][row]=account['quotes']['bid'][row]+daily.TICK[symbol]
                else:
                    account['quotes']['ask'][row]=entry-steps*daily.TICK[symbol]
                    account['quotes']['bid'][row]=account['quotes']['ask'][row]-daily.TICK[symbol]
            values=interface.execute(account,config,python=True)
            for profit in (1,2):
                c=next(x for x in catalog.configs() if x['mode']=='CONFIRM' and x['profit_ticks']==profit)
                output=interface.account_output('人工',account,c,values)
                assert output['control']['種別']=='利益目標' and output['control']['判断行']==profit+3
                assert output['control']['返済行']==profit+4 and output['control']['以後新規なし']
            checks.append(symbol+str(side)+':P1/P2の費用後初到達は別行・実UID返済は次正常気配')
            account=fixture(symbol,side);entry=account['quotes']['ask' if side>0 else 'bid'][2]
            if side>0:
                account['quotes']['bid'][3]=entry-10*daily.TICK[symbol]
                account['quotes']['ask'][3]=account['quotes']['bid'][3]+daily.TICK[symbol]
            else:
                account['quotes']['ask'][3]=entry+10*daily.TICK[symbol]
                account['quotes']['bid'][3]=account['quotes']['ask'][3]-daily.TICK[symbol]
            values=interface.execute(account,config,python=True)
            for c in catalog.configs():
                output=interface.account_output('人工',account,c,values)
                assert output['control']['種別']=='損失予算' and output['control']['判断行']==3
                assert output['control']['損失予算']==catalog.BUDGET[symbol]*3/catalog.QUANTITY[symbol]
                assert output['loss_anchor']['新規数量選択予算円']==catalog.BUDGET[symbol]
            checks.append(symbol+str(side)+':全四条件の比例L2先着と、不変数量選択予算を別項目で保持')
            instant=fixture(symbol,side,1)
            if side>0:
                instant['quotes']['ask'][2]=instant['quotes']['bid'][2]+2*daily.TICK[symbol]
                instant['quotes']['bid'][3]-=2*daily.TICK[symbol]
                instant['quotes']['ask'][3]=instant['quotes']['bid'][3]+daily.TICK[symbol]
            else:
                instant['quotes']['bid'][2]=instant['quotes']['ask'][2]-2*daily.TICK[symbol]
                instant['quotes']['ask'][3]+=2*daily.TICK[symbol]
                instant['quotes']['bid'][3]=instant['quotes']['ask'][3]-daily.TICK[symbol]
            values=interface.execute(instant,config,python=True)
            output=interface.account_output('人工',instant,config,values)
            assert output['goal_anchor']['受理行']==1 and output['goal_anchor']['数量']==1
            assert output['control']['種別']=='損失予算' and output['control']['判断行']==2 and output['control']['返済行']==3
            assert -output['summary']['収支']>output['control']['損失予算']
            checks.append(symbol+str(side)+':初fillの気配差と料だけで即停止し、次正常気配で損失線を超過し得る')
            recovery=fixture(symbol,side,1);entry=recovery['quotes']['ask' if side>0 else 'bid'][2]
            for row,steps in ((3,-3),(4,-2),(5,2),(6,3)):
                if side>0:
                    recovery['quotes']['bid'][row]=entry+steps*daily.TICK[symbol]
                    recovery['quotes']['ask'][row]=recovery['quotes']['bid'][row]+daily.TICK[symbol]
                else:
                    recovery['quotes']['ask'][row]=entry-steps*daily.TICK[symbol]
                    recovery['quotes']['bid'][row]=recovery['quotes']['ask'][row]-daily.TICK[symbol]
            values=interface.execute(recovery,config,python=True)
            newer=interface.account_output('人工',recovery,config,values);older=old_goal_output('人工',recovery,config,values)
            assert newer['control']['判断行']==3 and newer['control']['返済行']==4
            assert older['control']['種別']=='利益目標' and older['control']['判断行']==5
            assert newer['summary']['収支']<0<older['summary']['収支']
            checks.append(symbol+str(side)+':狭い比例線で旧固定L2の回復勝ちを失う反証を明示')
            full=fixture(symbol,side);full['feed'][full['feed'][:,7]==1,9]=.001
            for row in (5,7,9):
                if side>0:
                    full['quotes']['bid'][row]=full['quotes']['ask'][2]
                    full['quotes']['ask'][row]=full['quotes']['bid'][row]+daily.TICK[symbol]
                else:
                    full['quotes']['ask'][row]=full['quotes']['bid'][2]
                    full['quotes']['bid'][row]=full['quotes']['ask'][row]-daily.TICK[symbol]
            for c in catalog.configs():
                values=interface.execute(full,c,python=True);new=interface.account_output('人工',full,c,values)
                old=old_goal_output('人工',full,c,values)
                assert new['goal_anchor']['数量']==catalog.QUANTITY[symbol]
                for key in ('orders','order_uids','exit_target_uids','order_fees','equity_yen','liquidation_yen','reserved_exit_fees','long_qty','short_qty','cumulative_fees'):
                    np.testing.assert_array_equal(new[key],old[key]);arrays+=1
                for key in ('summary','parent','actual_legs','control'):assert new[key]==old[key]
            checks.append(symbol+str(side)+':初回全量は旧固定円目標と注文・UID・親・実玉・全曲線exact')
    checks.extend(driver_connection())
    original=common.read(common.HERE/'複写由来.json')['origin']
    copies={'common.py':'common.py','daily.py':'daily.py','order_kernel.py':'order_kernel.py','policy.py':'policy.py',
        'engine.py':'engine.py','baseline.py':'baseline.py','data.py':'data.py','storage.py':'storage.py',
        'fixed_goal_interface.py':'fixed_goal_interface.py','fixed_loss_policy.py':'goal_policy.py'}
    for current,old in copies.items():assert common.digest(common.HERE/current)==original[old]['SHA256']
    assert common.sources()==start
    common.write(common.HERE/proof_name,dict(全合格=True,
        観点数=len(checks),確認観点=checks,配列照合数=arrays,source_SHA256=start,同bytesコピー=copies,
        実入力読取=0,原板読取=0,NPZ読取=0,正式金融=0,API=0))
    print('初回受理比例損失人工合格 '+str(len(checks))+'観点/'+str(arrays)+'配列照合',flush=True)


if __name__=='__main__':run()
