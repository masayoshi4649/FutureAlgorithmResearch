"""元proxyと反対のmarket売買を、実データなしで予約・個別料・全行会計へ接続する。"""

from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
import math
from pathlib import Path
import traceback

import numpy as np

import catalog
import engine

HERE=Path(__file__).resolve().parent
ART=HERE/'数量公開からmarket全量と半分追尾へ接続する人工検査.json'


def sources() -> dict:
    """
    機能: 新私有三源の開始終端指紋を求める。
    引数: なし。
    返り値: dict[str,str] はSHA256。旧入力や他金融sourceへ依存しない。
    """
    return {n:hashlib.sha256((HERE/n).read_bytes()).hexdigest() for n in ('catalog.py','engine.py','artificial.py')}


def fixture(symbol: str,side: int=1) -> tuple:
    """
    機能: 旧115と同じ実売買方向になるよう、元proxyだけを反対へした原rowを合成する。
    引数: symbol(str)、side(int) は商品と期待する実売買鏡映側。元proxyは-side。
    返り値: tuple はarrays/signal/time_policy/start/end/tick。
    """
    tick=.5 if symbol=='TOPIX' else 10.;base=4000. if symbol=='TOPIX' else 70000.
    movement=np.array([0,0,0,3,5,6,4,3,0,0,-2,-3,0,0,0,0.],float)
    bid=base+movement*tick;ask=bid+tick
    if side<0:bid,ask=2*base+tick-ask,2*base+tick-bid
    times=np.array([0,1,2,3,4,5,6,7,8,9,10,11,400,401,700,701.])
    arrays=dict(raw_seq=np.arange(16,dtype=np.int64),price_time_s=times,bid=bid,ask=ask,
        bid_qty=np.full(16,20. if side<0 else 10.),ask_qty=np.full(16,10. if side<0 else 20.),best_quantity_valid=np.ones(16,bool))
    fields=['type','episode','pub_i','d','opposite_q0','opposite_min_q','bid_q_at_public','ask_q_at_public']
    events=[]
    for episode,row in enumerate((1,8,12,14)):
        for typ in (0,1):events.append([typ,episode,row,-side,10.,10.,arrays['bid_qty'][row],arrays['ask_qty'][row]])
    signal=dict(events=np.asarray(events,float),fields=fields,price_valid_mask=np.ones(16,bool))
    policy=dict(entry_start_s=0.,entry_end_s=400.,force_start_s=700.,quiet_windows=np.empty((0,2)))
    return arrays,signal,policy,0.,1000.,tick


def safe(value: object) -> object:
    """
    機能: 入出力統合の保存構造をJSON原始型へ写す。
    引数: value(object) は合成結果。
    返り値: object は非有限観測だけNoneの保存形。採否計算を変更しない。
    """
    if isinstance(value,np.ndarray):return safe(value.tolist())
    if isinstance(value,np.generic):return safe(value.item())
    if isinstance(value,float):return value if math.isfinite(value) else None
    if isinstance(value,dict):return {str(k):safe(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [safe(v) for v in value]
    return value


def decimal_fee(q: int,symbol: str) -> Decimal:
    """
    機能: 各実注文のfloor料を独立Decimal演算で計算する。
    引数: q(int)、symbol(str) は実約定量と商品。
    返り値: Decimal は円料金。半分返済を全量料へ合算しない。
    """
    return (Decimal(q)*Decimal('41.8' if symbol=='TOPIX' else '11')).to_integral_value(rounding=ROUND_FLOOR)


def audit(a: dict,s: dict,out: dict,symbol: str) -> int:
    """
    機能: 注文だけから全rowのcash・残量・純清算・親と実脚を独立再構成する。
    引数: a/s/out(dict)、symbol(str) は合成原列・信号・実出力・商品。
    返り値: int は比較数。MFEを仮想約定へ使用しない。
    """
    orders=out['orders'];curve=out['curve'];m=Decimal(str(catalog.VALUE[symbol]));cash=Decimal(0);paid=Decimal(0)
    book={};parents={};legs=[];checks=0
    for row in range(len(a['raw_seq'])):
        for index,o in enumerate(orders):
            if int(o[0])!=row:continue
            at,source,cid,uid,target,side,q,new,reason=map(int,(o[0],o[1],o[2],o[3],o[4],o[5],o[6],o[8],o[9]))
            price=Decimal(str(o[7]));cost=decimal_fee(q,symbol)
            assert source<at and out['execution_normal_mask'][row];checks+=2
            assert o[10]==cost and o[11]==a['raw_seq'][at] and o[12]==a['raw_seq'][source];checks+=3
            assert price==Decimal(str(a['ask'][row] if side>0 else a['bid'][row]));checks+=1
            cash-=Decimal(side*q)*price*m+cost;paid+=cost
            if new:
                assert at==source+1 and a['raw_seq'][at]==a['raw_seq'][source]+1 and uid not in book and target==-1;checks+=4
                assert not any(b['remaining'] for b in book.values());checks+=1
                accepted=out['publication_events'][(out['publication_events'][:,5]==1)&(out['publication_events'][:,6]==cid)]
                assert len(accepted)==1 and accepted[0,0]==source and accepted[0,4]==side;checks+=3
                event=s['events'][int(accepted[0,1])];proxy=int(event[s['fields'].index('d')])
                assert side==-proxy and side==proxy*out['config']['direction_multiplier'];checks+=2
                book[uid]=dict(parent=cid,side=side,quantity=q,remaining=q,price=price,fee=cost,entry_row=at)
                parents[cid]=dict(gross=Decimal(0),fee=cost)
            else:
                b=book[target];assert uid==-1 and side==-b['side'] and 0<q<=b['remaining'];checks+=3
                gross=Decimal(b['side']*q)*(price-b['price'])*m
                entry_alloc=b['fee']*q/b['quantity'];net=gross-entry_alloc-cost
                legs.append(float(net));b['remaining']-=q;parents[cid]['gross']+=gross;parents[cid]['fee']+=cost
        active=[b for b in book.values() if b['remaining']]
        assert len(active)<=1;checks+=1
        quantity=sum(b['remaining'] for b in active);assert curve[row,2]==quantity;checks+=1
        assert math.isclose(curve[row,0],float(cash),abs_tol=1e-6) and curve[row,6]==paid;checks+=2
        if not active:expected=cash
        elif s['price_valid_mask'][row]:
            b=active[0];quote=Decimal(str(a['bid'][row] if b['side']>0 else a['ask'][row]))
            expected=cash+Decimal(b['side']*b['remaining'])*quote*m-decimal_fee(b['remaining'],symbol)
        else:expected=None
        if expected is None:assert math.isnan(curve[row,1]);checks+=1
        else:assert math.isclose(curve[row,1],float(expected),abs_tol=1e-6);checks+=1
        assert 0<=curve[row,4]<=quantity;checks+=1
    np.testing.assert_allclose(out['actual_order_legs'][:,11],legs,atol=1e-6,rtol=0);checks+=1
    for p in out['parent']:
        expected=parents[p['parent']];assert p['fee_yen']==expected['fee'];checks+=1
        assert math.isclose(p['gross_yen'],float(expected['gross']),abs_tol=1e-6);checks+=1
        assert math.isclose(p['net_yen'],float(expected['gross']-expected['fee']),abs_tol=1e-6);checks+=1
    return checks


def play(data: tuple,config: dict,symbol: str,finish: bool=True,python: bool=False) -> tuple[dict,int]:
    """
    機能: readonly入力でcoreを実行し、独立会計とJSON統合を検査する。
    引数: data(tuple)、config(dict)、symbol(str)、finish/python(bool)。
    返り値: tuple[dict,int] は出力と比較数。Python対照でも源を書き換えない。
    """
    a,s,t,start,end,tick=data
    readonly={k:v.copy() for k,v in a.items()}
    for v in readonly.values():v.setflags(write=False)
    original=engine._run
    try:
        if python:engine._run=original.py_func
        out=engine.simulate(readonly,s,symbol,start,end,tick,t,config,finish)
    finally:
        engine._run=original
    checks=audit(a,s,out,symbol)
    for k in a:np.testing.assert_array_equal(a[k],readonly[k]);checks+=1
    json.loads(json.dumps(safe(out),ensure_ascii=False,allow_nan=False));checks+=1
    return out,checks


def proxy_quantity_cases(cfgs: list[dict]) -> tuple[int,int]:
    """
    機能: C審査が反転後の実方向でなく元proxy方向の数量を使うことを反例で検査する。
    引数: cfgs(list[dict]) は十二条件。A/Bの条件と四出口を同時変更しない。
    返り値: tuple[int,int] は比較数と追加合成口座数。保存事象の方向を二度反転しない。
    """
    checks=0;accounts=0
    for symbol in catalog.CAP:
        for side in (1,-1):
            for config in cfgs:
                a,s,t,start,end,tick=fixture(symbol,side)
                a['bid_qty'][:],a['ask_qty'][:]=a['ask_qty'].copy(),a['bid_qty'].copy()
                for event in s['events']:
                    row=int(event[2]);event[6]=a['bid_qty'][row];event[7]=a['ask_qty'][row]
                out,n=play((a,s,t,start,end,tick),config,symbol);checks+=n;accounts+=1
                if config['entry_mode']==2:
                    assert out['counts']['candidate_evaluations']==0 and len(out['orders'])==len(out['parent'])==0;checks+=3
                else:
                    assert out['counts']['actual_entries']>0 and np.all(out['orders'][out['orders'][:,8]==1,5]==side);checks+=2
            # ----------------------------------------
            # 元proxy同側と反対側が同量の等号はCで受理する。actual側への付替えはしない。
            a,s,t,start,end,tick=fixture(symbol,side);a['bid_qty'][:]=10.;a['ask_qty'][:]=10.
            s['events'][:,6:8]=10.
            out,n=play((a,s,t,start,end,tick),cfgs[-1],symbol);checks+=n;accounts+=1
            assert out['counts']['actual_entries']>0 and np.all(out['orders'][out['orders'][:,8]==1,5]==side);checks+=2
    return checks,accounts


def half_hand_amounts(cfgs: list[dict]) -> int:
    """
    機能: 買売鏡映の初親を、2T判断後の半分4T約定と残2T約定で手計算する。
    引数: cfgs(list[dict]) はE4を含む十二条件。
    返り値: int は比較数。全量料と二つの半分料を別々にfloorする。
    """
    checks=0
    for symbol in catalog.CAP:
        for side in (1,-1):
            out,n=play(fixture(symbol,side),cfgs[-1],symbol);checks+=n
            q=catalog.CAP[symbol];orders=out['orders'][out['orders'][:,2]==0]
            assert orders[:,0].tolist()==[2.,4.,7.] and orders[:,1].tolist()==[1.,3.,6.];checks+=2
            assert orders[:,6].tolist()==[q,q//2,q//2] and orders[:,9].tolist()==[90.,143.,142.];checks+=2
            expected_gross=Decimal(3)*Decimal(str(.5 if symbol=='TOPIX' else 10.))*q*Decimal(str(catalog.VALUE[symbol]))
            expected_fee=decimal_fee(q,symbol)+2*decimal_fee(q//2,symbol)
            parent=out['parent'][0]
            assert parent['gross_yen']==expected_gross and parent['fee_yen']==expected_fee;checks+=2
            assert parent['net_yen']==expected_gross-expected_fee;checks+=1
            assert parent['net_yen']==(14164 if symbol=='TOPIX' else 5560);checks+=1
    return checks


def main() -> None:
    """
    機能: 十二条件・鏡映・半分予約・unknown・拡幅・prefix等を実入力なしで固定する。
    引数: なし。
    返り値: None。原NPZ/保存結果/金融/APIは0で、失敗を保全する。
    """
    assert not ART.exists() and not (HERE/'人工False.json').exists()
    source=sources();checks=0;accounts=0;prefixes=0
    try:
        cfgs=json.loads(json.dumps(catalog.configs(),allow_nan=False));assert cfgs==catalog.configs() and len(cfgs)==12;checks+=2
        assert all(c['direction_multiplier']==-1 and c['id'].startswith('QREVERSE_') for c in cfgs);checks+=1
        for symbol in catalog.CAP:
            for side in (1,-1):
                data=fixture(symbol,side)
                for c in cfgs:
                    jit,n=play(data,c,symbol);checks+=n;accounts+=1
                    py,n=play(data,c,symbol,python=True);checks+=n
                    for key in ('orders','actual_order_legs','parents','publication_events','execution_events','control_events','curve'):
                        np.testing.assert_array_equal(jit[key],py[key]);checks+=1
                    assert jit['completed'];checks+=1
                    assert np.all(jit['orders'][:,0]>jit['orders'][:,1]);checks+=1
                    if c['exit_mode']==3:assert np.any(jit['orders'][:,9]==143);checks+=1
        n,extra=proxy_quantity_cases(cfgs);checks+=n
        checks+=half_hand_amounts(cfgs)
        config=cfgs[-1]
        for symbol in catalog.CAP:
            base=fixture(symbol);out,n=play(base,config,symbol);checks+=n
            for cut in (1,2,3,4,5,7,10,15):
                a,s,t,start,end,tick=base
                small={k:v[:cut].copy() for k,v in a.items()};sig=dict(s,events=s['events'][s['events'][:,2]<cut].copy(),price_valid_mask=s['price_valid_mask'][:cut].copy())
                short,n=play((small,sig,t,start,end,tick),config,symbol,finish=False);checks+=n;prefixes+=1
                for key,col in (('orders',0),('publication_events',0),('execution_events',0),('control_events',0)):
                    np.testing.assert_array_equal(short[key],out[key][out[key][:,col]<cut]);checks+=1
                np.testing.assert_array_equal(short['curve'],out['curve'][:cut]);checks+=1
            # ----------------------------------------
            # 発注済みarrival拡幅を有利に取消さず、実fill後のstop→さらに次rowとする。
            a,s,t,start,end,tick=fixture(symbol);a['ask'][2]=a['bid'][2]+4*tick
            wide,n=play((a,s,t,start,end,tick),config,symbol);checks+=n
            assert wide['orders'][0,0]==2 and wide['orders'][0,8]==1 and wide['orders'][0,7]==a['ask'][2];checks+=3
            assert wide['orders'][1,0]==3 and wide['orders'][1,9]==141;checks+=2
            # ----------------------------------------
            # next raw不正は新規だけ取消、保持の評価・返済予約はphaseを分ける。
            a,s,t,start,end,tick=fixture(symbol);s['price_valid_mask'][2]=False
            unknown,n=play((a,s,t,start,end,tick),config,symbol);checks+=n
            assert unknown['counts']['next_raw_unknown_cancels']==1 and not np.any(unknown['orders'][:,0]==2);checks+=2
            a,s,t,start,end,tick=fixture(symbol);a['best_quantity_valid'][4]=False
            delayed,n=play((a,s,t,start,end,tick),config,symbol);checks+=n
            half=delayed['orders'][delayed['orders'][:,9]==143]
            assert len(half)==1 and half[0,0]==5 and half[0,1]==3;checks+=2
            # ----------------------------------------
            # half予約保持＋quiet残量予約は別注文。quiet判断同rowへ残量を先送りしない。
            a,s,t,start,end,tick=fixture(symbol);t['quiet_windows']=np.array([[4.,7.]])
            forced,n=play((a,s,t,start,end,tick),config,symbol);checks+=n
            first=forced['orders'][forced['orders'][:,2]==0]
            assert len(first)==3 and first[1,9]==143 and first[1,0]==4 and first[2,9]==92 and first[2,0]==5;checks+=5
            assert first[1,6]+first[2,6]==catalog.CAP[symbol];checks+=1
            # ----------------------------------------
            # entry_endは既受理を取消さず、quietはfill前に取消。
            a,s,t,start,end,tick=fixture(symbol);a['price_time_s'][1]=399.;a['price_time_s'][2]=400.
            late,n=play((a,s,t,start,end,tick),config,symbol);checks+=n
            assert late['orders'][0,0]==2;checks+=1
            a,s,t,start,end,tick=fixture(symbol);t['quiet_windows']=np.array([[2.,3.]])
            cancel,n=play((a,s,t,start,end,tick),config,symbol);checks+=n
            assert cancel['counts']['scheduled_pending_cancels']==1 and not np.any(cancel['orders'][:,0]==2);checks+=2
            # ----------------------------------------
            # force中に正常quoteが来なければ過去価格へ戻らず未完了を返す。
            a,s,t,start,end,tick=fixture(symbol);a['bid'][3:]=a['bid'][2];a['ask'][3:]=a['ask'][2]
            a['best_quantity_valid'][14:]=False
            incomplete,n=play((a,s,t,start,end,tick),config,symbol);checks+=n
            assert not incomplete['completed'] and incomplete['final_state']['held_quantity']>0;checks+=2
            # ----------------------------------------
            # 将来BBOを変更しても既観測prefixの注文/判断を変えない。
            a,s,t,start,end,tick=fixture(symbol);a['bid'][7:]+=100*tick;a['ask'][7:]+=100*tick
            s['events'][s['events'][:,2]>=7,3]*=-1
            future,n=play((a,s,t,start,end,tick),config,symbol);checks+=n
            np.testing.assert_array_equal(future['orders'][future['orders'][:,0]<7],out['orders'][out['orders'][:,0]<7]);checks+=1
            np.testing.assert_array_equal(future['curve'][:7],out['curve'][:7]);checks+=1
        assert source==sources()
        proof=dict(全合格=True,source_SHA256=source,比較数=checks,基本口座=accounts,接頭=prefixes,元proxy数量審査追加口座=extra,
            実NPZ=0,元保存結果=0,金融=0,原板=0,API=0,
            仕様='C審査は元proxy d。受理候補の実sideだけ-d。公開だけspread審査。market arrival拡幅を負担。判断後nextnormal返済。half予約とforce残量は別注文。',
            手計算='E4初親は全量実新規→半量4T→残半量2T。TOP gross15000/料836/net14164、NK gross6000/料440/net5560。買売鏡映で同じ。',
            金額='完結親net主、実脚netの勝負枚数を区別。CurrentPriceTime模型で真受信時刻未保存。')
        ART.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,比較数=checks,基本口座=accounts,接頭=prefixes,source_SHA256=source,
            artifact_SHA256=hashlib.sha256(ART.read_bytes()).hexdigest()),ensure_ascii=False))
    except BaseException:
        (HERE/'人工False.json').write_text(json.dumps(dict(全合格=False,source_SHA256=source,比較数=checks,
            原因=traceback.format_exc(),実入力=0,金融=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__=='__main__':
    main()
