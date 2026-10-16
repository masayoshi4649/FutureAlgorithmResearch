"""新源をimportせず、公開FAK・数量・影・実料の小feed期待値を独立に作る。"""

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import hashlib
import json
import traceback


HERE=Path(__file__).resolve().parent


def d(value: float | int) -> Decimal:
    """
    機能: 小人工の価格・円額を10進算術へ変換する。
    引数: value(float|int) は人工数値。
    返り値: Decimal は独立計算値。新金融源のfloat判定を複写しない。
    """
    return Decimal(str(value))


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 実成立注文の片道料を整数有理数からfloorする。
    引数: quantity(int) は実枚数、symbol(str) は人工商品。
    返り値: int は注文料。未成立注文へ料を付けない。
    """
    return quantity*209//5 if symbol=='TOPIX' else quantity*11


def fixture(symbol: str, side: int=1, kind: str='再参加数量') -> dict:
    """
    機能: 一親一新規・別紙上親への再参加と同列取消を含む小人工を作る。
    引数: symbol(str) はTOPIX/NK225、side(int) は±1、kind(str) は人工名。
    返り値: dict は14正常候補行と完全な紙上feed。実データは参照しない。
    """
    assert symbol in ('TOPIX','NK225') and side in (-1,1)
    base=4110. if symbol=='TOPIX' else 68700.
    tick=.5 if symbol=='TOPIX' else 10.
    full=5 if symbol=='TOPIX' else 10
    first_atr=.9 if symbol=='TOPIX' else 40.
    second_atr=.6 if symbol=='TOPIX' else 30.
    count=14
    rows=[dict(row=i,time=float(i),bid=base,ask=base+tick,normal=True,quiet=False,quiet_force=False) for i in range(count)]
    rows[2].update(bid=base+tick,ask=base+2*tick)
    for i in range(3,count):
        rows[i].update(bid=base+tick,ask=base+2*tick)
    feed=[dict(row=1,cid=0,side=1,quantity=full,new=True,reason=1,atr=first_atr),
          dict(row=4,cid=0,side=-1,quantity=full,new=False,reason=2,atr=first_atr),
          dict(row=6,cid=1,side=1,quantity=full,new=True,reason=1,atr=second_atr),
          dict(row=9,cid=1,side=-1,quantity=full,new=False,reason=2,atr=second_atr)]
    if kind!='再参加数量':
        rows[2].update(bid=base,ask=base+tick)
    if kind=='静観と第一正常が同列':
        rows[2]['quiet']=True
    elif kind=='紙上全返済と第一正常が同列':
        feed[1]['row']=2
    elif kind=='紙上全返済だけが先着':
        rows[2]['normal']=False
        feed[1]['row']=2
    elif kind in ('累積部分返済','部分返済待機の重複防止'):
        chunks=(2,1,2) if symbol=='TOPIX' else (2,2,6)
        start=2 if kind=='累積部分返済' else 3
        feed=[feed[0]]+[dict(row=start+j,cid=0,side=-1,quantity=q,new=False,reason=2,atr=first_atr) for j,q in enumerate(chunks)]+feed[2:]
        if kind=='部分返済待機の重複防止':
            rows[4]['normal']=rows[5]['normal']=False
    elif kind=='価格内の拡幅':
        rows[2].update(bid=base-tick,ask=base+tick)
    elif kind=='第一正常の前に不正気配':
        rows[2]['normal']=False
        rows[3].update(bid=base+tick,ask=base+2*tick)
    elif kind=='期限と第一正常が同列':
        # 期限以後の後候補も保存feedに残し、旧通り拒否する。
        pass
    elif kind not in ('再参加数量','通常同値'):
        raise AssertionError(kind)
    if side==-1:
        mirror=2*base+tick
        for row in rows:
            row['bid'],row['ask']=mirror-row['ask'],mirror-row['bid']
        for order in feed:
            order['side']=-order['side']
    feed.sort(key=lambda o:o['row'])
    return dict(symbol=symbol,tick=tick,full_quantity=full,side=side,rows=rows,feed=feed,
                end=2. if kind=='期限と第一正常が同列' else 12.,kind=kind,
                gate={1:True,6:True},人工素材=True)


def run(value: dict, mode: str='FAK0', sizing: bool=True, adverse_by_publication: dict|None=None) -> dict:
    """
    機能: 紙上の影・予約・一回FAK・実UID・返済待ち・floor料を互いに独立した帳簿で逐次処理する。
    引数: value(dict) は純小人工、mode(str) は市場/FAK0/FAK1、sizing(bool) は数量選択の有無、adverse_by_publication(dict|None) は公開行だけで選ぶ許容0/1。
    返り値: dict は期待注文・受理・状態・当時清算。新sourceやJITは使わない。
    """
    assert value['人工素材'] and mode in ('市場','FAK0','FAK1')
    symbol=value['symbol'];multiplier=1000 if symbol=='TOPIX' else 10
    budget=5000 if symbol=='TOPIX' else 2000
    full=value['full_quantity'];tick=value['tick']
    pointer=0;vcid=-1;vcore=0;virtual_initial=0;actual_initial=0;reserved_closed=0
    actual=None;pending=None;queue=[];orders=[];uid_counter=0;cash=d(0);paid=0
    markbid=d(0);markask=d(0);force_source=None;force_reason=None;anchor=None
    accepts=[];states=[];fee_curve=[];attempts=[]

    def liquidation() -> tuple[Decimal,int,Decimal]:
        """
        機能: 当時の実残玉だけを返済側気配で清算し前実現と全支払料を含める。
        引数: なし。外側の現在帳簿のみを読む。
        返り値: tuple[Decimal,int,Decimal] は清算net・残返済料・費用控除前時価。
        """
        mark=cash
        reserve=0
        if actual is not None and actual['remaining']:
            mark+=actual['side']*actual['remaining']*(markbid if actual['side']>0 else markask)
            reserve=fee(actual['remaining'],symbol)
        return mark*multiplier-paid-reserve,reserve,mark*multiplier

    def execute(row: int, source: int, cid: int, side: int, quantity: int, price: Decimal, new: bool, reason: int) -> None:
        """
        機能: 成立した実注文だけを追加し、UID・価格cash・料・残枚数を更新する。
        引数: row/source/cid/side/quantity/reason(int)、price(Decimal)、new(bool) は当行の実注文。
        返り値: None。未来の返済や元paper取引損益を引用しない。
        """
        nonlocal actual,cash,paid,uid_counter
        assert source<row and quantity>0
        uid=-1
        if new:
            assert actual is None or actual['remaining']==0
            uid=uid_counter;uid_counter+=1
            actual=dict(cid=cid,side=side,quantity=quantity,remaining=quantity,uid=uid)
        else:
            assert actual is not None and actual['cid']==cid and actual['side']==-side
            assert quantity<=actual['remaining']
            actual['remaining']-=quantity
        cost=fee(quantity,symbol);paid+=cost;cash-=side*quantity*price
        orders.append(dict(row=row,source=source,cid=cid,side=side,quantity=quantity,price=float(price),
                           new=new,reason=reason,uid=uid,fee=cost))

    for row in value['rows']:
        i=row['row'];scheduled=row['quiet'] or row['quiet_force'] or row['time']>=value['end']
        if scheduled:
            force_source=max(0,i-1) if force_source is None else force_source
            force_reason=93 if row['time']>=value['end'] else 92
            queue=[];pending=None
        good=row['normal'];blocked=scheduled or force_source is not None
        if good:
            markbid=d(row['bid']);markask=d(row['ask'])
            if blocked:
                if actual is not None and actual['remaining']:
                    side=-actual['side'];price=markask if side>0 else markbid
                    execute(i,force_source,actual['cid'],side,actual['remaining'],price,False,force_reason)
                queue=[];pending=None;force_source=None;force_reason=None
            else:
                for item in queue:
                    price=markask if item['side']>0 else markbid
                    execute(i,item['source'],item['cid'],item['side'],item['quantity'],price,False,91)
                queue=[]
                if pending is not None:
                    price=markask if pending['side']>0 else markbid
                    allowed=mode=='市場' or pending['side']*(price-pending['cap'])<=0
                    attempts.append(dict(row=i,cid=pending['cid'],publication=pending['source'],
                        limit=float(pending['cap']),observed_price=float(price),filled=allowed))
                    if allowed:
                        execute(i,pending['source'],pending['cid'],pending['side'],pending['quantity'],price,True,90)
                    pending=None
        while pointer<len(value['feed']) and value['feed'][pointer]['row']==i:
            order=value['feed'][pointer];pointer+=1
            if order['new']:
                assert vcore==0
                vcid=order['cid'];virtual_initial=order['quantity'];reserved_closed=0
                liquid,reserve,_=liquidation();available=max(d(0),d(budget)+liquid)
                spread=d(row['ask'])-d(row['bid']) if good else None
                per=(d(order['atr'])+spread)*multiplier if spread is not None else None
                q=virtual_initial if not sizing else 0
                if sizing and good:
                    for candidate in range(1,virtual_initial+1):
                        if candidate*per+2*fee(candidate,symbol)<=available:
                            q=candidate
                busy=(actual is not None and actual['remaining']>0) or bool(queue)
                accepted=not blocked and not busy and value['gate'].get(i,True) and q>0
                actual_initial=q
                event=dict(row=i,cid=vcid,side=order['side'],virtual_quantity=virtual_initial,selected_quantity=q,
                    published_atr=order['atr'],published_spread=None if spread is None else float(spread),
                    liquidation=float(liquid),available=float(available),paid=paid,reserve=reserve,
                    accepted=accepted,busy=busy,blocked=blocked,gate=value['gate'].get(i,True))
                accepts.append(event)
                if accepted:
                    price=markask if order['side']>0 else markbid
                    adverse=1 if mode=='FAK1' else 0
                    if adverse_by_publication is not None:
                        adverse=adverse_by_publication.get(i,0)
                        assert adverse in (0,1)
                    limit=price+order['side']*d(tick)*adverse
                    pending=dict(cid=vcid,side=order['side'],quantity=q,source=i,cap=limit)
                    if anchor is None:
                        anchor=deepcopy(event)
                vcore=order['side']*virtual_initial
            else:
                assert order['cid']==vcid and order['side']*vcore<0 and order['quantity']<=abs(vcore)
                vcore+=order['side']*order['quantity']
                if pending is not None:
                    pending=None
                elif actual is not None and actual['cid']==vcid and actual['remaining']>0 and not blocked:
                    cumulative=virtual_initial-abs(vcore)
                    target=actual_initial if vcore==0 else actual_initial*cumulative//virtual_initial
                    quantity=target-reserved_closed
                    assert quantity>=0
                    if quantity:
                        queue.append(dict(source=i,cid=vcid,side=order['side'],quantity=quantity))
                        reserved_closed+=quantity
        liquid,reserve,marked=liquidation()
        actual_quantity=actual['remaining'] if actual is not None else 0
        states.append(dict(row=i,virtual_cid=vcid,vcore=vcore,held_long=actual_quantity if actual and actual['side']>0 else 0,
            held_short=actual_quantity if actual and actual['side']<0 else 0,pending=pending is not None,
            queued=len(queue),reserved_virtual_closed=reserved_closed,
            real_cid=actual['cid'] if actual is not None else -1))
        fee_curve.append(dict(row=i,paid=paid,reserved_exit_fee=reserve,equity=float(marked-paid),
                              liquidation=float(liquid),available=float(max(d(0),d(budget)+liquid))))
    assert pointer==len(value['feed'])
    return dict(orders=orders,accepts=accepts,states=states,fee_curve=fee_curve,attempts=attempts,
                anchor=anchor,uid_count=uid_counter,mode=mode,fixture_kind=value['kind'])


def selfcheck() -> None:
    """
    機能: source完成前の独立参照だけで同列順位・予約失効・部分floor・後参加数量を固定する。
    引数: なし。
    返り値: None。純人工の期待値を所有領域へ保存し正式源合格とは呼ばない。
    """
    target=HERE/'新源完成前のFAK影数量UIDと同列順位の純参照.json'
    assert not target.exists()
    cases=[]
    kinds=('再参加数量','通常同値','静観と第一正常が同列','紙上全返済と第一正常が同列',
           '紙上全返済だけが先着','累積部分返済','部分返済待機の重複防止','価格内の拡幅',
           '第一正常の前に不正気配','期限と第一正常が同列')
    comparisons=0
    for symbol in ('TOPIX','NK225'):
        for side in (1,-1):
            for kind in kinds:
                material=fixture(symbol,side,kind)
                outcomes={m:run(material,m) for m in ('市場','FAK0','FAK1')}
                virtual=[(r['virtual_cid'],r['vcore']) for r in outcomes['市場']['states']]
                for mode,result in outcomes.items():
                    assert virtual==[(r['virtual_cid'],r['vcore']) for r in result['states']]
                    assert result['anchor']['row']==1 and result['anchor']['selected_quantity']==3
                    assert sum(o['fee'] for o in result['orders'])==result['fee_curve'][-1]['paid']
                    for cid in (0,1):
                        own=[o for o in result['orders'] if o['cid']==cid]
                        assert sum(o['quantity'] for o in own if o['new'])==sum(o['quantity'] for o in own if not o['new'])
                    if kind in ('静観と第一正常が同列','紙上全返済だけが先着','期限と第一正常が同列'):
                        assert not any(o['cid']==0 for o in result['orders'])
                    if kind=='紙上全返済と第一正常が同列':
                        own=[o for o in result['orders'] if o['cid']==0]
                        assert [o['row'] for o in own]==[2,3]
                    if kind=='価格内の拡幅':
                        assert result['attempts'][0]['filled'] and result['orders'][0]['row']==2
                    if kind=='再参加数量':
                        quantities=[a['selected_quantity'] for a in result['accepts']]
                        if mode=='FAK0':
                            assert quantities==[3,4] and not any(o['cid']==0 for o in result['orders'])
                        else:
                            assert quantities==([3,2] if symbol=='TOPIX' else [3,3])
                    if kind in ('累積部分返済','部分返済待機の重複防止'):
                        own=[o for o in result['orders'] if o['cid']==0 and not o['new']]
                        assert [o['quantity'] for o in own]==([1,2] if symbol=='TOPIX' else [1,2])
                        assert sum(o['quantity'] for o in own)==3
                        assert sum(o['fee'] for o in result['orders'] if o['cid']==0)==(249 if symbol=='TOPIX' else 66)
                    cut=5
                    altered=deepcopy(material)
                    for row in altered['rows']:
                        if row['row']>cut:
                            row['bid']+=material['tick']*50
                            row['ask']+=material['tick']*50
                    future=run(altered,mode)
                    for field in ('states','fee_curve'):
                        assert result[field][:cut+1]==future[field][:cut+1]
                    assert result['anchor']==future['anchor']
                    assert [o for o in result['orders'] if o['row']<=cut]==[o for o in future['orders'] if o['row']<=cut]
                    comparisons+=1
                    cases.append(dict(symbol=symbol,side=side,kind=kind,mode=mode,
                        expected_orders=result['orders'],anchor=result['anchor'],
                        accepted_quantities=[r['selected_quantity'] for r in result['accepts']],
                        uid_count=result['uid_count'],paid=result['fee_curve'][-1]['paid'],future_suffix_before5不変=True))
    assert comparisons==120
    result=dict(全合格=True,状態='新源import前の純参照のみ。正式engine/政策の監査合格ではない。',
        純小feed=40,三執行比較=120,期待値=cases,
        検査した順序='旧凍結数量engineのscheduled→正常予約fill/queue→当行paperを基準にした。静観/期限はpendingfill前、paper取消は同行firstgood fill後。',
        注記=['新源は作業中でまだimport/hash束縛しない。owner完成通知後だけ正式源と比較する。',
            '参照の第一正常失効と成立の区別は注文到達の物理証明ではない。未観測mini/micro部分成立・板厚みは補完しない。',
            '公開予約が消えても初受理q尺度は保持。影vcoreは市場/FAK0/FAK1で全行同じ。',
            '少数票の門は別の公開mask部品。参照では当行gateだけを与え未来quoteを渡さない。'],
        source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        新源import=0,旧source又は共有編集=0,金融=0,入力=0,台帳=0,原板=0,NPZ=0,API=0)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,比較=comparisons,SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    try:
        selfcheck()
    except Exception:
        failed=HERE/'新源完成前のFAK純参照False.json'
        assert not failed.exists()
        failed.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),
            source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            新源import=0,金融=0,入力=0,台帳=0,API=0,自動再実行=False),
            ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
