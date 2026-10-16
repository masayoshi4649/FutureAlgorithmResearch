"""係数未固定の汎用出口を、基準同値・逐次保全・接頭・実料で人工検査する。"""

from decimal import Decimal,ROUND_FLOOR
import copy
import numpy as np

import common
import context
import daily
import exit_core
import exit_policy
import storage


def fixture(symbol: str, side: int, quantity: int) -> tuple[dict,dict]:
    """
    機能: native呼値の同原行気配と、一新規・部分・全返済の保存GUを人工で作る。
    引数: symbol(str)、side/quantity(int) は商品・方向・実初回枚数。
    返り値: tuple[dict,dict] は人工口座と保存形式の台帳。実データは読まない。
    """
    n=10;tick=daily.TICK[symbol];price=4000. if symbol=='TOPIX' else 65000.
    increments=np.array([0,0,0,2,3,2,2,1,1,0])*tick
    bid=price+increments;ask=bid+tick
    if side<0:
        center=2*price+tick;bid,ask=center-ask,center-bid
    quotes=dict(seq=np.arange(100,100+n,dtype=np.int64),time_s=np.arange(n,dtype=float),bid=bid,ask=ask,quote_valid=np.ones(n,bool))
    record=dict(seq=quotes['seq'],time_s=quotes['time_s'],price=(bid+ask)/2,limit=9.,tick=tick)
    entry=ask[2] if side>0 else bid[2];first=1;orders=[[2,1,0,side,quantity,entry,90,1]]
    orders.append([6,5,0,-side,first,bid[6] if side>0 else ask[6],91,0])
    if quantity>first:orders.append([8,7,0,-side,quantity-first,bid[8] if side>0 else ask[8],91,0])
    orders=np.asarray(orders,float);uids=np.array([0]+[-1]*(len(orders)-1),np.int64)
    base=daily.reconstruct(('人工',symbol),orders,uids,quotes)
    atr=tick*2 if symbol=='TOPIX' else tick*5
    if quantity==daily.QUANTITY[symbol]:atr=.001
    fee=2*daily.fee(quantity,symbol);budget=5000. if symbol=='TOPIX' else 2000.
    events=np.array([[1,0,side,daily.QUANTITY[symbol],quantity,atr,tick,(atr+tick)*daily.VALUE[symbol],0,budget,
        quantity*(atr+tick)*daily.VALUE[symbol]+fee,0,0,0,1,1]],float)
    ledger=dict(key=('人工',symbol),shadow_GU_orders=orders,shadow_GU_uids=uids,
        execution_events=np.empty((0,12)),execution_states=np.zeros((n,10)),limit_events=np.empty((0,18)),
        sizing_events=events,sizing_fee_curve=np.column_stack((base['cumulative_fees'],base['reserved_exit_fees'],
            base['equity_yen'],base['liquidation_yen'],np.maximum(0,budget+base['liquidation_yen']))))
    account=dict(symbol=symbol,record=record,quotes=quotes)
    return account,ledger


def prefix(account: dict, ledger: dict, cut: int) -> tuple[dict,dict]:
    """
    機能: 原行を同じ位置で切り、未完成GU接頭を人工で作る。
    引数: account/ledger(dict)、cut(int) は人工文脈と端点。
    返り値: tuple[dict,dict] は未来清算や未来fillを持たない保存接頭。
    """
    a=copy.deepcopy(account);l=copy.deepcopy(ledger)
    for section in ('record','quotes'):
        for name,value in a[section].items():
            if isinstance(value,np.ndarray):a[section][name]=value[:cut]
    chosen=l['shadow_GU_orders'][:,0]<cut
    l['shadow_GU_orders']=l['shadow_GU_orders'][chosen];l['shadow_GU_uids']=l['shadow_GU_uids'][chosen]
    for name in ('execution_states','sizing_fee_curve'):l[name]=l[name][:cut]
    l['sizing_events']=l['sizing_events'][l['sizing_events'][:,0]<cut]
    return a,l


def run() -> None:
    """
    機能: 正式係数を選ばず、固定/保全の契約を意味のある人工反例で確かめる。
    引数: なし。
    返り値: None。人工証跡を保存し、金融・台帳・実入力・APIを読まない。
    """
    sources=common.sources();checks=[];arrays=0
    for symbol in ('TOPIX','NK225'):
        for side in (1,-1):
            for quantity in (1,2,3,daily.QUANTITY[symbol]):
                account,ledger=fixture(symbol,side,quantity);ctx=context.prepare(account,ledger,copy.deepcopy(ledger))
                unit=daily.TICK[symbol]*daily.QUANTITY[symbol]*daily.VALUE[symbol]
                goal=unit*quantity/daily.QUANTITY[symbol];loss=2*unit
                new=exit_policy.fixed(ctx,goal,loss)
                old=daily.apply_policy(ctx['base'],ctx['quotes'],dict(profit_ticks=quantity/daily.QUANTITY[symbol],loss_ticks=2))
                for name in ('orders','order_uids','order_fees','equity_yen','liquidation_yen','reserved_exit_fees'):
                    np.testing.assert_array_equal(new[name],old[name]);arrays+=1
                for name in ('parent','summary','control'):assert new[name]==old[name]
                charge=Decimal('41.8' if symbol=='TOPIX' else '11')
                actual=sum(int((Decimal(int(o[4]))*charge).to_integral_value(rounding=ROUND_FLOOR)) for o in new['orders'])
                assert new['summary']['費用']==actual
                one=exit_policy.protection(ctx,goal/2,goal/2,0.,loss,python=False)
                two=exit_policy.protection(ctx,goal/2,goal/2,0.,loss,python=True)
                assert one['row']==two['row'] and one['reason']==two['reason']
                np.testing.assert_array_equal(one['trace'],two['trace']);arrays+=1
                np.testing.assert_array_equal(storage.expand(storage.pack(one['trace'])),one['trace']);arrays+=1
                if one['row'] is not None:
                    closed=exit_policy.close_prefix(ctx,one)
                    assert closed['long_qty'][-1]==closed['short_qty'][-1]==0
                    assert not closed['control']['返済予約']
                for cut in (1,2,3,4,6,8):
                    a,l=prefix(account,ledger,cut);part=context.prepare(a,l,copy.deepcopy(l),finish=False)
                    early=exit_policy.protection(part,goal/2,goal/2,0.,loss,python=True)
                    if early['trace'] is not None:
                        np.testing.assert_array_equal(early['trace'],one['trace'][:cut]);arrays+=1
                        assert early['row']==(one['row'] if one['row'] is not None and one['row']<cut else None)
                    completed=exit_policy.close_prefix(part,early)
                    assert completed['control']['未完成接頭']
                    if early['row'] is None and len(part['base']['orders']):assert not completed['summary']['全会計合格']
                tiny=exit_policy.fixed(ctx,goal,1.)
                assert tiny['control']['種別']=='損失予算' and tiny['control']['判断行']==2
                assert tiny['control']['返済行']==3
                checks.append(symbol+str(side)+'Q'+str(quantity)+':旧固定線exact、PythonJIT保全、疎保存、六接頭、低loss即停止')
            account,ledger=fixture(symbol,side,3);ctx=context.prepare(account,ledger,copy.deepcopy(ledger))
            after_partial=dict(row=6,reason=3);closed=exit_policy.close_prefix(ctx,after_partial)
            expected=daily.fee(3,symbol)+daily.fee(1,symbol)+daily.fee(2,symbol)
            assert closed['summary']['費用']==expected
            if symbol=='TOPIX':assert expected==249
            assert closed['orders'][-1,4]==2 and closed['orders'][-1,0]==7
            checks.append(symbol+str(side)+':発動前partialの実料・実現を保ち、残UID別料金を注文単位floor')
            a,l=prefix(account,ledger,3);part=context.prepare(a,l,copy.deepcopy(l),finish=False)
            pending=exit_policy.close_prefix(part,dict(row=2,reason=1))
            assert pending['control']['返済予約'] and pending['control']['返済行'] is None
            assert len(pending['orders'])==1 and pending['long_qty'][-1]+pending['short_qty'][-1]==3
            checks.append(symbol+str(side)+':接頭で次正常quote未観測なら未返済予約を保持し未来場末清算無し')
            rejected=False
            try:context.prepare(a,l,copy.deepcopy(l),finish=True)
            except AssertionError:rejected=True
            assert rejected
    # ----------------------------------------
    # 場の清算は現在親だけでなく、前親の実現益と注文別の実料を含む。
    for symbol in ('TOPIX','NK225'):
        for side in (1,-1):
            account,ledger=fixture(symbol,side,1);quotes=account['quotes']
            first=ledger['shadow_GU_orders'].copy()
            entry=quotes['ask' if side>0 else 'bid'][8]
            close=quotes['bid' if side>0 else 'ask'][9]
            orders=np.concatenate((first,np.array([[8,7,1,side,1,entry,90,1],[9,8,1,-side,1,close,91,0]],float)))
            uids=np.array([0,-1,1,-1],np.int64)
            base=daily.reconstruct(('人工',symbol),orders,uids,quotes)
            ledger['shadow_GU_orders']=orders;ledger['shadow_GU_uids']=uids
            event=ledger['sizing_events'][0].copy();event[0]=7;event[1]=1
            ledger['sizing_events']=np.vstack((ledger['sizing_events'],event))
            budget=5000. if symbol=='TOPIX' else 2000.
            ledger['sizing_fee_curve']=np.column_stack((base['cumulative_fees'],base['reserved_exit_fees'],
                base['equity_yen'],base['liquidation_yen'],np.maximum(0,budget+base['liquidation_yen'])))
            ctx=context.prepare(account,ledger,copy.deepcopy(ledger))
            previous=base['parent'][0]['収支'];cost=daily.TICK[symbol]*daily.VALUE[symbol]+2*daily.fee(1,symbol)
            np.testing.assert_allclose(base['liquidation_yen'][8],previous-cost,atol=1e-7);arrays+=1
            loss=200. if symbol=='TOPIX' else 50.
            assert -cost<=-loss and base['liquidation_yen'][8]>-loss
            decision=exit_policy.protection(ctx,100000.,10000.,0.,loss,python=True)
            assert decision['row'] is None or decision['row']>8
            assert ctx['anchor']['row']==1 and ctx['anchor']['parent']==0
            checks.append(symbol+str(side)+':前親の確定益を第二親の清算へ含め、現親だけの初期費用で偽停止しない')
    account,ledger=fixture('TOPIX',1,2)
    cancelled=copy.deepcopy(ledger);cancelled['shadow_GU_orders'][:,2]=1
    cancelled['shadow_GU_orders'][0,0]=3;cancelled['shadow_GU_orders'][0,1]=2
    cancelled['shadow_GU_orders'][0,5]=account['quotes']['ask'][3]
    event=cancelled['sizing_events'][0].copy();event[1]=1;event[0]=2
    cancelled['sizing_events'][0,4]=1;cancelled['sizing_events']=np.vstack((cancelled['sizing_events'],event))
    base=daily.reconstruct(('人工','TOPIX'),cancelled['shadow_GU_orders'],cancelled['shadow_GU_uids'],account['quotes'])
    cancelled['sizing_fee_curve']=np.column_stack((base['cumulative_fees'],base['reserved_exit_fees'],base['equity_yen'],base['liquidation_yen'],np.maximum(0,5000+base['liquidation_yen'])))
    ctx=context.prepare(account,cancelled,copy.deepcopy(cancelled));assert ctx['anchor']['quantity']==1 and ctx['anchor']['parent']==0
    assert ctx['base']['orders'][0,4]==2 and ctx['base']['orders'][0,2]==1
    checks.append('初受理Q1取消後に実Q2が入っても、受理q/ATR/spreadアンカーを交換しない')
    empty=copy.deepcopy(ledger);empty['shadow_GU_orders']=np.empty((0,8));empty['shadow_GU_uids']=np.empty(0,np.int64)
    empty['sizing_events']=np.empty((0,16));empty['sizing_fee_curve']=np.column_stack((np.zeros((10,4)),np.full(10,5000.)))
    ctx=context.prepare(account,empty,copy.deepcopy(empty));assert ctx['anchor'] is None
    assert exit_policy.fixed(ctx,None,5000.)['control']['目標'] is None
    assert exit_policy.protection(ctx,1.,1.,0.,5000.)['trace'] is None and storage.pack(None) is None
    checks.append('未受理None・無取引非勝ち・停止線の0補完無し')
    equity=np.array([0.,100.,200.,100.,150.,50.]);normal=np.ones(6,bool)
    full=exit_core.scan.py_func(equity,normal,1,150.,75.,0.,500.,np.nan)
    assert full[0]==3 and full[1]==3
    for cut in range(1,7):
        before=exit_core.scan.py_func(equity[:cut],normal[:cut],1,150.,75.,0.,500.,np.nan)
        future=equity.copy();future[cut:]=1000000.
        altered=exit_core.scan.py_func(future[:cut],normal[:cut],1,150.,75.,0.,500.,np.nan)
        np.testing.assert_array_equal(before[2],full[2][:cut]);np.testing.assert_array_equal(before[2],altered[2]);arrays+=2
    normal[3]=False;assert exit_core.scan.py_func(equity,normal,1,150.,75.,0.,500.,np.nan)[0]==5
    checks.append('未知quoteで新判断せず、当時高水準は不利へ緩めず、未来ピーク書換えで過去trace不変')
    assert common.sources()==sources
    assert str(common.HERE/'jit') in exit_core.scan._cache._impl._locator._cache_path
    common.write('汎用出口の基準同値と因果保全及び実UID接頭の人工検査_v2.json',dict(全合格=True,
        観点=len(checks),確認観点=checks,配列照合=arrays,source_SHA256=sources,
        正式係数固定=False,金融再生=0,実入力読取=0,実台帳読取=0,原板=0,NPZ=0,API=0))
    print('汎用出口prepared人工合格 '+str(len(checks))+'観点/'+str(arrays)+'配列照合',flush=True)


if __name__=='__main__':run()
