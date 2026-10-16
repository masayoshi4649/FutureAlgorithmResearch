"""新源完成前の純参照。paper状態と実UID/親の初実fill尺度を別帳簿で処理する。"""

from copy import deepcopy
from decimal import Decimal


def dec(value: object) -> Decimal:
    """
    機能: 人工の価格・率・円額を独立10進算術へ変換する。
    引数: value(object) は人工数値。
    返り値: Decimal は計算値。新経済 source は import しない。
    """
    return Decimal(str(value))


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 実成立注文の片道料金を有理数から切捨てる。
    引数: quantity(int) は実枚数、symbol(str) は商品。
    返り値: int は片道料。失効予約には徴収しない。
    """
    return quantity*209//5 if symbol=='TOPIX' else quantity*11


def fixture(symbol: str, side: int=1, kind: str='独立親と再参加') -> dict:
    """
    機能: 長出口busy・paper継続・予約取消・q0・少量partialと価格急変を持つ純小feedを作る。
    引数: symbol(str)、side(int)、kind(str) は人工商品・方向・反例名。
    返り値: dict は24行とshadow5/10の元feed。実市場資料を使わない。
    """
    assert symbol in ('TOPIX','NK225') and side in (-1,1)
    base,tick,mult,cap=(4000.,.5,1000,10) if symbol=='TOPIX' else (70000.,10.,10,20)
    full=cap//2;n=24
    changes=[0,0,0,4,11,12,16,22,20,15,14.5,14.5,14.5,14.5,100,100,100,100,100,100,100,100,100,100]
    scale=1. if symbol=='TOPIX' else 20.
    rows=[dict(row=i,time=float(i),bid=base+change*scale,ask=base+change*scale+tick,last=base+change*scale,
               normal=True,quiet=False,quiet_force=False) for i,change in enumerate(changes)]
    feed=[dict(row=1,cid=0,side=1,quantity=full,new=True,atr=1. if symbol=='TOPIX' else 20.,balance=1.,known=True,votes=4),
          dict(row=4,cid=0,side=-1,quantity=2 if symbol=='TOPIX' else 4,new=False),
          dict(row=5,cid=0,side=-1,quantity=3 if symbol=='TOPIX' else 6,new=False),
          dict(row=8,cid=1,side=1,quantity=full,new=True,atr=1. if symbol=='TOPIX' else 20.,balance=1.,known=True,votes=4),
          dict(row=10,cid=1,side=-1,quantity=full,new=False),
          dict(row=14,cid=2,side=1,quantity=full,new=True,atr=1. if symbol=='TOPIX' else 20.,balance=1.,known=True,votes=4),
          dict(row=18,cid=2,side=-1,quantity=full,new=False)]
    if kind=='paper継続中targetclose':
        feed=[feed[0],dict(row=18,cid=0,side=-1,quantity=full,new=False)]
    elif kind in ('paper先取消','paper同行firstnormal'):
        feed=[feed[0],dict(row=2,cid=0,side=-1,quantity=full,new=False)]+feed[3:]
        if kind=='paper先取消':rows[2]['normal']=False
    elif kind=='少量partial':
        feed[0]['atr']=15. if symbol=='TOPIX' else 550.
    elif kind=='q0後別親':
        feed[0]['atr']=10000.
    elif kind=='第一FAK失効':
        rows[2]['bid']+=tick*3;rows[2]['ask']+=tick*3
    elif kind=='追尾後の返済gap':
        rows[10].update(bid=base-50*scale,ask=base-50*scale+tick,last=base-50*scale)
    elif kind=='場損失後停止':
        rows[3].update(bid=base-6*scale,ask=base-6*scale+tick,last=base-6*scale)
        rows[4].update(bid=base-7*scale,ask=base-7*scale+tick,last=base-7*scale)
        rows[8].update(bid=base,ask=base+tick,last=base)
        rows[9].update(bid=base,ask=base+tick,last=base)
        rows[10].update(bid=base-6*scale,ask=base-6*scale+tick,last=base-6*scale)
        rows[11].update(bid=base-7*scale,ask=base-7*scale+tick,last=base-7*scale)
    elif kind=='partial予約後quiet':
        rows[5]['quiet']=True
    elif kind not in ('独立親と再参加',):raise AssertionError(kind)
    if side==-1:
        center=2*base+tick
        for r in rows:
            r['bid'],r['ask']=center-r['ask'],center-r['bid'];r['last']=center-r['last']
        for o in feed:o['side']=-o['side']
    feed.sort(key=lambda o:o['row'])
    return dict(symbol=symbol,tick=tick,multiplier=mult,cap=cap,shadow_full=full,rows=rows,feed=feed,end=22.,kind=kind,
                base_balance=.5 if symbol=='TOPIX' else .25,strong_balance=.75 if symbol=='TOPIX' else 1.,人工素材=True)


def run(source: dict, quantity_mode: str, exit_mode: str, guards: bool=True) -> dict:
    """
    機能: 実新規予約・実親名目・独立清算・partial/stop・影feedと完結親を逐次処理する。
    引数: source(dict)、quantity_mode/exit_mode(str)、guards(bool) は純人工・数量・退出・損失線有無。
    返り値: dict は実注文・親・影/実状態・公開資格・清算曲線。原GUもguardsONなら変更済み対照である。
    """
    assert source['人工素材'] and quantity_mode in ('HALF','FULL','RISK') and exit_mode in ('GU','TARGET','TRAIL','PARTIAL')
    symbol=source['symbol'];mult=source['multiplier'];cap=source['cap'];tick=dec(source['tick'])
    scene_basis=dec(source['rows'][0]['last'])*cap*mult;scene_stop=scene_basis*dec(.0025)
    paper_cid=-1;paper_qty=0;paper_initial=0;paper_closed=0
    actual=None;pending=None;queue=[];uid=0;cash=dec(0);paid=0;pointer=0;stopped=False;force_source=None
    markbid=dec(0);markask=dec(0);orders=[];parents=[];states=[];curve=[];publications=[];decisions=[]

    def liquidation() -> Decimal:
        """
        機能: 全実親残玉を当時返済側気配で清算し、支払料と残料を一度だけ差し引く。
        引数: なし。現在のcash/実残玉/価格だけを参照する。
        返り値: Decimal は場の費用後清算net。
        """
        gross=cash*mult-paid
        if actual is not None and actual['remaining']:
            q=actual['remaining'];gross+=actual['side']*q*(markbid if actual['side']==1 else markask)*mult-fee(q,symbol)
        return gross

    def fill(row: int, source_row: int, parent: int, side: int, quantity: int, new: bool, reason: str) -> None:
        """
        機能: 成立実注文だけを価格cashと料金へ追加し、実残零でpaperphaseと無関係に親を完結する。
        引数: row/source_row/parent/side/quantity(int)、new(bool)、reason(str) は実注文。
        返り値: None。将来のpaper終結を実親の完結条件に使わない。
        """
        nonlocal actual,uid,cash,paid
        assert source_row<row and quantity>0
        price=markask if side==1 else markbid
        previous=liquidation()
        if new:
            assert actual is None or actual['remaining']==0
            actual=dict(uid=uid,paper_parent=parent,side=side,initial_quantity=quantity,remaining=quantity,
                entry_price=price,entry_row=row,baseline_net=previous,nominal=price*quantity*mult,
                armed=False,highwater=None,partial_used=False,gu_closed=0,fee=0)
            uid+=1
        else:
            assert actual is not None and parent==actual['paper_parent'] and side==-actual['side'] and quantity<=actual['remaining']
            actual['remaining']-=quantity
        cost=fee(quantity,symbol);paid+=cost;cash-=side*quantity*price;actual['fee']+=cost
        orders.append(dict(row=row,source=source_row,paper_parent=parent,uid=actual['uid'] if new else -1,
            target_uid=-1 if new else actual['uid'],side=side,quantity=quantity,price=float(price),new=new,reason=reason,fee=cost))
        if not new and actual['remaining']==0:
            net=liquidation()-actual['baseline_net']
            parents.append(dict(uid=actual['uid'],paper_parent=actual['paper_parent'],side=actual['side'],quantity=actual['initial_quantity'],
                entry_row=actual['entry_row'],exit_row=row,nominal=float(actual['nominal']),net=float(net),fee=actual['fee']))

    for r in source['rows']:
        i=r['row'];scheduled=r['quiet'] or r['quiet_force'] or r['time']>=source['end'];good=r['normal']
        if scheduled:
            pending=None;queue=[]
            if force_source is None:force_source=max(0,i-1)
        blocked=scheduled or force_source is not None
        if good:
            markbid,markask=dec(r['bid']),dec(r['ask'])
            if blocked:
                if actual is not None and actual['remaining']:
                    fill(i,force_source,actual['paper_parent'],-actual['side'],actual['remaining'],False,'予定終了')
                force_source=None
            else:
                for request in queue:
                    fill(i,request['source'],actual['paper_parent'],-actual['side'],request['quantity'],False,request['reason'])
                queue=[]
                if pending is not None:
                    price=markask if pending['side']==1 else markbid
                    if pending['side']*(price-pending['price_cap'])<=0:
                        fill(i,pending['source'],pending['parent'],pending['side'],pending['quantity'],True,'一回FAK')
                    pending=None
                if guards and not stopped and liquidation()<=-scene_stop:
                    stopped=True;pending=None
                    if actual is not None and actual['remaining']:
                        queue=[dict(source=i,quantity=actual['remaining'],reason='場損失')]
                        decisions.append(dict(row=i,reason='場損失',liquidation=float(liquidation())))
                elif actual is not None and actual['remaining']:
                    local=liquidation()-actual['baseline_net'];nominal=actual['nominal'];reason=None
                    if guards and local<=-nominal*dec(.00125):reason='親損失'
                    elif exit_mode=='TARGET' and local>=nominal*dec(.005):reason='親純目標'
                    elif exit_mode in ('TRAIL','PARTIAL'):
                        if not actual['armed'] and local>=nominal*dec(.00375):actual['armed']=True;actual['highwater']=local
                        if actual['armed']:
                            actual['highwater']=max(actual['highwater'],local)
                            line=max(nominal*dec(.0025),actual['highwater']-nominal*dec(.00125))
                            if local<=line:reason='親利益追尾'
                        if reason is None and exit_mode=='PARTIAL' and not actual['partial_used'] and actual['initial_quantity']>=4 and local>=nominal*dec(.0025):
                            q=actual['initial_quantity']//4;actual['partial_used']=True
                            assert 0<q<actual['remaining'];queue=[dict(source=i,quantity=q,reason='四分の一')]
                    if reason is not None:
                        queue=[dict(source=i,quantity=actual['remaining'],reason=reason)]
                        decisions.append(dict(row=i,reason=reason,local_net=float(local),nominal=float(nominal),uid=actual['uid']))
        while pointer<len(source['feed']) and source['feed'][pointer]['row']==i:
            order=source['feed'][pointer];pointer+=1
            if order['new']:
                assert paper_qty==0
                paper_cid=order['cid'];paper_initial=order['quantity'];paper_closed=0;paper_qty=order['side']*paper_initial
                known=order['known'] and order['votes']>=2;gate=known and order['balance']>=source['base_balance']
                allowance=int(known and order['balance']>=source['strong_balance'])
                spread=markask-markbid if good else None
                budget=dec(r['last'])*cap*mult*dec(.00125)
                q=source['shadow_full'] if quantity_mode=='HALF' else cap if quantity_mode=='FULL' else 0
                if quantity_mode=='RISK' and good:
                    for candidate in range(1,cap+1):
                        if candidate*(dec(order['atr'])+spread)*mult+2*fee(candidate,symbol)<=budget:q=candidate
                busy=actual is not None and actual['remaining']>0 or pending is not None or bool(queue)
                accepted=good and gate and q>0 and not busy and not stopped and not blocked
                publications.append(dict(row=i,paper_parent=paper_cid,quantity=q,accepted=accepted,busy=busy,gate=gate,allowance=allowance,budget=float(budget)))
                if accepted:
                    price=markask if order['side']==1 else markbid
                    pending=dict(source=i,parent=paper_cid,side=order['side'],quantity=q,price_cap=price+order['side']*allowance*tick)
            else:
                assert order['cid']==paper_cid and order['side']*paper_qty<0 and order['quantity']<=abs(paper_qty)
                paper_qty+=order['side']*order['quantity'];paper_closed+=order['quantity']
                if pending is not None:pending=None
                elif exit_mode=='GU' and actual is not None and actual['remaining'] and actual['paper_parent']==paper_cid and all(v['reason']=='元paper返済' for v in queue) and not blocked:
                    target=actual['initial_quantity'] if paper_qty==0 else actual['initial_quantity']*paper_closed//paper_initial
                    count=target-actual['gu_closed']
                    if count:
                        actual['gu_closed']=target;queue.append(dict(source=i,quantity=count,reason='元paper返済'))
        local=None if actual is None or actual['remaining']==0 else liquidation()-actual['baseline_net']
        states.append(dict(row=i,paper_cid=paper_cid,paper_quantity=paper_qty,real_uid=None if actual is None else actual['uid'],
            real_parent=None if actual is None else actual['paper_parent'],real_quantity=0 if actual is None else actual['remaining'],
            nominal=None if actual is None else float(actual['nominal']),local_net=None if local is None else float(local),
            pending_entry=pending is not None,pending_exit=sum(v['quantity'] for v in queue),stopped=stopped))
        curve.append(dict(row=i,paid=paid,liquidation=float(liquidation()),scene_basis=float(scene_basis),scene_stop=float(scene_stop)))
        assert (actual is None or 0<=actual['remaining']<=cap)
    assert pointer==len(source['feed'])
    return dict(orders=orders,parents=parents,states=states,curve=curve,publications=publications,decisions=decisions,exit=exit_mode,quantity=quantity_mode,guards=guards)
