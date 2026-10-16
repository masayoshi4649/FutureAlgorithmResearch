"""場終端のflatを仮定せず、固定単一位置の物理注文だけから接頭会計を独立検算する。"""

import numpy as np


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 注文ごとの税込料金を十進整数で切り捨てる。
    引数: quantity(int)、symbol(str)は実約定数量と商品。
    返り値: intはTOPIXmini41.8円/NKmicro11円の片道料金。
    """
    assert quantity>0 and symbol in ('TOPIX','NK225')
    return quantity*418//10 if symbol=='TOPIX' else quantity*11


def valid_quote(record: dict) -> np.ndarray:
    """
    機能: 元normal執行と同じ有限時計/気配/quote_validを判定する。
    引数: record(dict)は正常執行入力。
    返り値: ndarray[bool]はqok。量/出来高の資格と区別する。
    """
    b,a,t=record['bid'],record['ask'],record['time_s']
    return record['quote_valid']&np.isfinite(t)&np.isfinite(b)&np.isfinite(a)&(b>0)&(a>b)


def pending_state(events: np.ndarray, n: int) -> tuple:
    """
    機能: 予約/約定/取消の当時イベントから、未約定と返済予約数量を復元する。
    引数: events(ndarray[float])、n(int)は疎イベントと正常行数。
    返り値: tuple[ndarray,ndarray,ndarray]は方向別新規予約と返済予約。未約定に経済損益を付けない。
    """
    long,short,exit_pending=(np.zeros(n,np.int64) for _ in range(3))
    phase,parent,side,q=0,0,0,0;last=-1
    for e in events:
        row,p,code,d,size=(int(e[k]) for k in (0,1,3,4,5))
        assert last<=row<n and d in (-1,1);last=row
        if code==9:continue
        if code==1:
            assert phase==0;phase,parent,side,q=1,p,d,size
            (long if d==1 else short)[row]+=q
        elif code==4:
            assert phase==1 and (p,d,size)==(parent,side,q)
            (long if d==1 else short)[row]-=q;phase=2
        elif code==6:
            assert phase==1 and (p,d,size)==(parent,side,q)
            (long if d==1 else short)[row]-=q;phase=0
        elif code==2:
            assert phase in (2,3) and (p,d,size)==(parent,side,q)
            if phase==2:exit_pending[row]+=q
            phase=3
        elif code==5:
            assert phase==3 and (p,d,size)==(parent,side,q)
            exit_pending[row]-=q;phase=0
        else:raise AssertionError(('不明物理イベント',code))
    values=tuple(np.cumsum(v) for v in (long,short,exit_pending))
    assert all(np.all(v>=0) for v in values)
    return values


def verify_fills(record: dict, output: dict, normal: dict, config: dict) -> dict:
    """
    機能: 当時候補と同原行の次quote/初指値到達、料金、取消後復活なしを独立確認する。
    引数: record/output/normal/config(dict)は正常入力、物理台帳、当時選択と固定3政策。
    返り値: dictは商品規則別の照合件数。既存全flat会計は呼ばない。
    """
    qok=valid_quote(record);rows=np.flatnonzero(qok);n=len(qok);symbol=record['symbol'];times=record['time_s']
    mapping=normal['execution_to_raw_index'];assert mapping.shape==(n,) and np.all(np.diff(mapping)>0)
    decisions={int(v['row']):v for v in normal['decisions']}
    diagnostics={int(v['parent_id']):v for v in output['raw_entry_diagnostics']}
    cancellations={int(e[1]):int(e[0]) for e in output['events'] if int(e[3])==6}
    counts={'C_next':0,'R_market_next':0,'R_limit_first':0,'exit_next':0}
    seen=set();previous=-1
    for o in output['orders']:
        at,d,parent,action,qty,source,uid=(int(o[k]) for k in (0,1,2,4,5,3,16))
        assert 0<=at<n and at> d and at>=previous and qok[at];previous=at
        assert uid not in seen and uid>0;seen.add(uid)
        assert qty==config['quantity'][symbol] and action in (-1,1) and source in (0,1)
        assert o[9]==fee(qty,symbol)
        price=float(record['ask'][at] if action==1 else record['bid'][at]);assert o[6]==price
        assert o[11]==times[at] and o[10]<=times[at]
        available=rows[(rows>d)&(rows<=at)]
        if o[7]:
            assert 0<=d<n and qok[d] and o[10]==times[d]
            assert normal['event'][d]==action and normal['entry_families'][d]==source+1
            assert record['start']+config['start_offset']<=times[d]<record['limit']-config['cut_offset']
            assert times[at]<record['limit']-config['cut_offset']
            assert not normal['quiet'][d] and not np.any(normal['quiet'][d+1:at+1])
            assert not np.any(np.isfinite(normal['quiet_start_s'][d+1:at+1]))
            assert parent not in cancellations or cancellations[parent]>at
            meta=decisions[d];diag=diagnostics[parent]
            assert meta['raw_row']==mapping[d] and meta['raw_seq']==int(record['seq'][d]) and meta['normal_row']==d
            assert diag['decision_raw_row']==mapping[d] and diag['fill_raw_row']==mapping[at]
            assert diag['decision_raw_seq']==int(record['seq'][d]) and diag['fill_raw_seq']==int(record['seq'][at])
            assert meta['side']==action and meta['support_price']==normal['support_price'][d]
            if source==0:
                assert normal['entry_quality'][d] and not normal['entry_reset'][d]
                assert normal['entry_modes'][d]==1;counts['C_next']+=1
                for root in meta['selected_support_roots']:
                    assert int(root['anchor_raw_seq'])<=int(record['seq'][d])
            else:
                before=rows[(rows>d)&(rows<at)];stop=normal['entry_stop_prices'][d];eps=record['tick']*1e-8
                clearing=record['bid'][before] if action==1 else record['ask'][before]
                assert not np.any(action*(clearing-stop)<=eps)
                assert not np.any(normal['range_pending_trend'][d+1:at])
                assert not meta['selected_support_roots'] and meta['stop_price']==stop
                mode=int(normal['entry_modes'][d]);assert mode in (1,2)
                if mode==2:
                    limit=float(normal['entry_limit_prices'][d]);assert o[12]==limit and int(o[14])==12
                    reached=record['ask'][available]<=limit+eps if action==1 else record['bid'][available]>=limit-eps
                    available=available[reached];counts['R_limit_first']+=1
                else:assert int(o[14])==11;counts['R_market_next']+=1
        else:
            available=available[times[available]>=o[10]];counts['exit_next']+=1
        assert len(available)>0 and int(available[0])==at,'判断後初quote又は初指値到達でない約定'
    return counts


def inspect(record: dict, output: dict, normal: dict, config: dict) -> dict:
    """
    機能: 物理注文のcash/保有/残UID料から全行curveを独立復元し、実現と未決済を分ける。
    引数: record/output/normal/config(dict)は同一正常入力、接頭台帳、候補と固定政策。
    返り値: dictは独立partial会計。単一玉・追加なし・全量約定/返済の仕様だけに適用する。
    """
    checks=verify_fills(record,output,normal,config);symbol=record['symbol'];n=len(record['seq']);assert n>0
    multiplier=1000. if symbol=='TOPIX' else 10.;cap=config['caps'][symbol]
    cash,long,short,reserve=(np.zeros(n) for _ in range(4));entries,exits={},{}
    for o in output['orders']:
        at,parent,action,q,side=(int(o[k]) for k in (0,2,4,5,15));entry=bool(o[7]);charge=fee(q,symbol)
        cash[at]-=action*q*o[6]*multiplier+charge
        (long if side==1 else short)[at]+=q if entry else -q
        reserve[at]+=charge if entry else -charge
        if entry:
            assert parent not in entries and not any(p not in exits for p in entries),'単一位置/追加なしの違反'
            assert side==action;entries[parent]=o
        else:
            assert parent in entries and parent not in exits and action==-side
            original=entries[parent];assert q==int(original[5]) and side==int(original[15])
            assert at>int(original[0]);exits[parent]=o
    cash,long,short,reserve=(np.cumsum(v) for v in (cash,long,short,reserve))
    assert np.all(long>=0) and np.all(short>=0) and np.all(reserve>=0)
    assert np.all((long<=cap)&(short<=cap)) and not np.any((long>0)&(short>0))
    qok=valid_quote(record);last=np.maximum.accumulate(np.where(qok,np.arange(n),-1));held=(long+short)>0
    assert np.all(last[held]>=0);curve=cash.copy();selected=last[held]
    curve[held]+=(long[held]*record['bid'][selected]-short[held]*record['ask'][selected])*multiplier-reserve[held]
    np.testing.assert_allclose(curve,output['curve'],atol=1e-4,rtol=0)
    pl,ps,pe=pending_state(output['events'],n)
    trace=np.column_stack((long,short,long+pl,short+ps,pl+ps,pe)).astype(np.int32)
    np.testing.assert_array_equal(trace,output['target_trace'])
    assert trace[:,:4].max(initial=0)<=cap and not np.any((long+pl>0)&(short+ps>0))
    trades={int(t[0]):t for t in output['trades']};assert set(trades)==set(exits)
    nets=[]
    for parent,closing in exits.items():
        opening=entries[parent];t=trades[parent];side=int(opening[15]);q=int(opening[5])
        gross=side*q*(closing[6]-opening[6])*multiplier;net=gross-opening[9]-closing[9]
        expected=[parent,int(opening[3]),int(opening[0]),int(closing[0]),side,q,opening[6],closing[6],opening[9],closing[9],gross,net,
            int(opening[8]),int(closing[8]),int(opening[13]),int(opening[1])]
        np.testing.assert_allclose(t,np.array(expected),atol=1e-4,rtol=0);nets.append(net)
    realized=float(sum(nets));open_positions=[]
    for parent,opening in entries.items():
        if parent in exits:continue
        side,q=int(opening[15]),int(opening[5]);at=int(last[-1]);assert at>=0
        quote=float(record['bid'][at] if side==1 else record['ask'][at]);closing_fee=fee(q,symbol)
        mark=side*q*(quote-opening[6])*multiplier-opening[9]-closing_fee
        open_positions.append(dict(parent_id=parent,entry_uid=int(opening[16]),source=int(opening[3]),side=side,quantity=q,
            entry_price=float(opening[6]),entry_fee=float(opening[9]),remaining_exit_fee=closing_fee,
            clearing_row=at,clearing_raw_seq=int(record['seq'][at]),clearing_price=quote,open_mark_net=float(mark)))
    open_mark=float(sum(p['open_mark_net'] for p in open_positions))
    assert abs(curve[-1]-(realized+open_mark))<1e-4
    net=np.asarray(nets,float);win=net>1e-5;lose=net<-1e-5;profit=float(net[win].sum());loss=float(-net[lose].sum())
    q=config['quantity'][symbol];paid=float(output['orders'][:,9].sum())
    return dict(symbol=symbol,realized_profit=profit,realized_loss=loss,realized_net=realized,
        closed_campaigns=len(nets),winning_campaigns=int(win.sum()),losing_campaigns=int(lose.sum()),flat_campaigns=int((~win&~lose).sum()),
        winning_lots=int(win.sum())*q,losing_lots=int(lose.sum())*q,flat_lots=int((~win&~lose).sum())*q,
        profit_share=profit/(profit+loss) if profit+loss>0 else None,
        open_mark_net=open_mark,actual_liquidation_value=float(curve[-1]),open_positions=open_positions,
        held_long=int(long[-1]),held_short=int(short[-1]),pending_entry=int((pl+ps)[-1]),pending_exit=int(pe[-1]),
        total_paid_fees=paid,reserved_exit_fees=float(reserve[-1]),last_normal_row=n-1,last_raw_seq=int(record['seq'][-1]),
        last_price_clock=float(record['time_s'][-1]),clearing_quote_row=int(last[-1]),quote_invalid_at_end=bool(not qok[-1]),
        order_count=len(output['orders']),max_held=int((long+short).max(initial=0)),max_occupied=int((long+pl+short+ps).max(initial=0)),
        equity_min=float(min(0.,curve.min())),equity_max=float(max(0.,curve.max())),
        equity_drawdown=float((np.maximum.accumulate(np.r_[0.,curve])-np.r_[0.,curve]).max()),
        closed_trade_verification=True,all_row_order_equity_verification=True,realized_plus_open_verification=True,
        pending_zero_exposure_verification=True,execution_checks=checks,finish=False,
        measurement='取得済み接頭の当時正常ラージ気配による返済料込み清算代理。実際の返済/その後の値段/全Night収支ではない。')
