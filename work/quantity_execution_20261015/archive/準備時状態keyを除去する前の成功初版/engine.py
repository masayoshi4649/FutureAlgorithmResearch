"""外部IOを持たない、数量公開後のmarket全量・部分返済と実料金の逐次機械。"""

import numpy as np
from numba import njit

import catalog

ORDER_FIELDS=['row','source_row','parent','uid','target_uid','side','q','price','new','reason','fee','raw_seq','source_raw_seq']
LEG_FIELDS=['parent','uid','side','q','entry_row','exit_row','entry_price','exit_price','gross_yen','entry_fee_allocated','exit_fee','net_yen']
PARENT_FIELDS=['parent','uid','publication_row','entry_row','exit_row','side','quantity','gross_yen','fee_yen','net_yen',
    'entry_price','entry_raw_seq','exit_raw_seq','signal_event_index','unknown_price_rows','unknown_quantity_rows',
    'peak_gross_ticks','worst_gross_ticks','peak_liquidation_net_yen','worst_liquidation_net_yen']
PUBLICATION_FIELDS=['row','signal_event_index','signal_type','episode','side','accepted','parent','reason','public_spread','public_quote','q','raw_seq']
EXECUTION_FIELDS=['row','kind','parent','source_row','side','q','price','reason','remaining_quantity','raw_seq','source_raw_seq']
CONTROL_FIELDS=['row','parent','reason','added_reserved_quantity','held_quantity','previous_reserved_quantity','gross_ticks','peak_ticks','liquidation_net_yen','line','raw_seq']
CURVE_FIELDS=['cash_yen','liquidation_net_yen','held_quantity','side','reserved_quantity','reserved_exit_fee_yen','paid_fee_yen',
    'parent','parent_local_net_yen','gross_ticks','peak_gross_ticks','trail_armed','session_loss_line_yen','session_profit_line_yen','price_known','execution_normal']
COUNT_FIELDS=['candidate_evaluations','accepted_reservations','actual_entries','next_raw_unknown_cancels','next_raw_seq_cancels',
    'scheduled_pending_cancels','busy_rejections','public_spread_rejections','public_data_rejections','time_rejections',
    'session_rejections','holding_price_unknown_rows','holding_quantity_unknown_rows','half_orders','exit_orders','session_stop_events']
REASONS={90:'次rawの成行新規',92:'米国開始静観',93:'場末返済',94:'実保有又は予約busy',95:'新規時間外',
    96:'公開データ資格不達',97:'公開spreadが2T以上',98:'直後rawのデータ資格不達',99:'直後rawのseq不連続',
    140:'固定gross利確',141:'初期gross損切り',142:'gross追尾',143:'gross2Tで半分返済',161:'場純損失停止',162:'場純利益停止'}


@njit(cache=False)
def _append(a,count,value):
    """
    機能: 私有診断・注文bufferを必要時だけ拡張し、順序を保持して追記する。
    引数: a(ndarray)、count(int)、value(ndarray) は二次元bufferと新行。
    返り値: tuple[ndarray,int] は新bufferと件数。外部保存は行わない。
    """
    if count==len(a):
        new=np.empty((max(8,len(a)*2),a.shape[1]),np.float64);new[:count]=a;a=new
    a[count]=value
    return a,count+1


@njit(cache=False)
def _fee(q,num,den):
    """
    機能: 一回の実注文料を整数比のfloorで計算する。
    引数: q/num/den(int) は約定量と片道料金。
    返り値: int は円料。注文の分割をまとめ直さない。
    """
    return q*num//den


@njit(cache=False)
def _run(seq,pt,bid,ask,price_known,execution_normal,candidates,entry_start,entry_end,force_start,quiet_windows,
         cap,tick,mult,num,den,exit_mode,loss_fraction,profit_fraction):
    """
    機能: 公開・翌raw新規・既返済・場制御・親制御を実順に逐次運転する。
    引数: 原配列/資格/候補/静観窓(ndarray)、時間/呼値/倍率/率(float)、容量/料金/出口mode(int)。
    返り値: tuple は注文・実脚・完結親・公開・執行・制御・曲線・件数・最終状態。
    """
    n=len(seq);orders=np.empty((64,13));legs=np.empty((64,12));parents=np.empty((64,20))
    pubs=np.empty((64,12));executions=np.empty((64,11));controls=np.empty((64,11));curve=np.full((n,16),np.nan)
    oc=0;lc=0;pc=0;pubc=0;ec=0;cc=0;pointer=0;counts=np.zeros(16,np.int64)
    # ----------------------------------------
    # 返済予約は元のhalfと未充当残を別注文のまま保持する。二予約で全残量を覆う。
    queue=np.zeros((4,3));qn=0;reserved=0;held=0;side=0;cid=-1;uid=-1;next_cid=0;next_uid=0
    pending=False;pending_row=-1;pending_cid=-1;pending_side=0;pending_event=-1
    cash=0.;paid=0.;entry_price=0.;entry_row=-1;entry_pub=-1;entry_event=-1;entry_cost=0;parent_base=0.
    parent_gross=0.;parent_exit_cost=0;parent_unknown=0;parent_qty_unknown=0
    peak=-np.inf;worst=np.inf;best_net=-np.inf;worst_net=np.inf;trail=False;partial_requested=False
    loss_line=np.nan;profit_line=np.nan;session_block=False;session_reason=0;force_latched=False;force_observed=False
    for row in range(n):
        known=bool(price_known[row]);normal=bool(execution_normal[row]);time=pt[row]
        if known and not np.isfinite(loss_line):
            nominal=(bid[row]+ask[row])*.5*cap*mult;loss_line=nominal*loss_fraction;profit_line=nominal*profit_fraction
        quiet=False
        if np.isfinite(time):
            for w in range(len(quiet_windows)):
                if quiet_windows[w,0]<=time<quiet_windows[w,1]:quiet=True
            if time>=force_start:force_latched=True;force_observed=True
        timer_reason=93 if force_latched else 92 if quiet else 0
        # ----------------------------------------
        # 当行timerは当行に約定せず、既予約は先に実行する。新規予約はtimerでfill前取消。
        if timer_reason and held>reserved:
            amount=held-reserved;assert qn<4
            queue[qn]=np.array([row,amount,timer_reason]);qn+=1
            controls,cc=_append(controls,cc,np.array([row,cid,timer_reason,amount,held,reserved,np.nan,peak,np.nan,np.nan,seq[row]],np.float64))
            reserved+=amount
        if pending and (timer_reason or session_block):
            reason=timer_reason if timer_reason else session_reason
            executions,ec=_append(executions,ec,np.array([row,3,pending_cid,pending_row,pending_side,0,np.nan,reason,held,seq[row],seq[pending_row]],np.float64))
            pending=False;counts[5]+=1
        if normal:
            while qn>0 and int(queue[0,0])<row:
                source=int(queue[0,0]);amount=int(queue[0,1]);reason=int(queue[0,2]);assert 0<amount<=held
                price=bid[row] if side>0 else ask[row];cost=_fee(amount,num,den)
                orders,oc=_append(orders,oc,np.array([row,source,cid,-1,uid,-side,amount,price,0,reason,cost,seq[row],seq[source]],np.float64))
                gross=side*(price-entry_price)*amount*mult;entry_alloc=entry_cost*amount/cap
                legs,lc=_append(legs,lc,np.array([cid,uid,side,amount,entry_row,row,entry_price,price,gross,entry_alloc,cost,gross-entry_alloc-cost],np.float64))
                cash+=side*amount*price*mult-cost;paid+=cost;parent_gross+=gross;parent_exit_cost+=cost
                held-=amount;reserved-=amount;counts[14]+=1
                if reason==143:counts[13]+=1
                executions,ec=_append(executions,ec,np.array([row,2,cid,source,-side,amount,price,reason,held,seq[row],seq[source]],np.float64))
                qn-=1
                for k in range(qn):queue[k]=queue[k+1]
                if held==0:
                    assert reserved==0 and qn==0
                    final_ticks=side*(price-entry_price)/tick;peak=max(peak,final_ticks);worst=min(worst,final_ticks)
                    net=cash-parent_base;best_net=max(best_net,net);worst_net=min(worst_net,net)
                    assert abs(net-(parent_gross-entry_cost-parent_exit_cost))<1e-5
                    parents,pc=_append(parents,pc,np.array([cid,uid,entry_pub,entry_row,row,side,cap,parent_gross,entry_cost+parent_exit_cost,net,
                        entry_price,seq[entry_row],seq[row],entry_event,parent_unknown,parent_qty_unknown,peak,worst,best_net,worst_net],np.float64))
                    side=0;cid=-1;uid=-1;trail=False;partial_requested=False
        # ----------------------------------------
        # 受理済新規は直後rawの一回だけ。不明行を飛ばして後の正常行で約定しない。
        if pending:
            assert pending_row<row and held==0
            reason=0
            if row!=pending_row+1 or seq[row]!=seq[pending_row]+1:reason=99;counts[4]+=1
            elif not normal:reason=98;counts[3]+=1
            if reason:
                executions,ec=_append(executions,ec,np.array([row,3,pending_cid,pending_row,pending_side,0,np.nan,reason,0,seq[row],seq[pending_row]],np.float64))
            else:
                side=pending_side;held=cap;cid=pending_cid;uid=next_uid;next_uid+=1
                entry_price=ask[row] if side>0 else bid[row];entry_row=row;entry_pub=pending_row;entry_event=pending_event
                parent_base=cash;entry_cost=_fee(cap,num,den);parent_gross=0.;parent_exit_cost=0;parent_unknown=0;parent_qty_unknown=0
                peak=-np.inf;worst=np.inf;best_net=-np.inf;worst_net=np.inf;trail=False;partial_requested=False
                cash-=side*cap*entry_price*mult+entry_cost;paid+=entry_cost;counts[2]+=1
                orders,oc=_append(orders,oc,np.array([row,pending_row,cid,uid,-1,side,cap,entry_price,1,90,entry_cost,seq[row],seq[pending_row]],np.float64))
                executions,ec=_append(executions,ec,np.array([row,1,cid,pending_row,side,cap,entry_price,90,held,seq[row],seq[pending_row]],np.float64))
            pending=False
        reserve_fee=_fee(held,num,den) if held else 0
        liquidation=cash if held==0 else np.nan
        local=0. if held==0 else np.nan;gross_ticks=np.nan
        if held>0:
            if not known:parent_unknown+=1;counts[11]+=1
            if known and not normal:parent_qty_unknown+=1;counts[12]+=1
            if known:
                quote=bid[row] if side>0 else ask[row]
                liquidation=cash+side*held*quote*mult-reserve_fee;local=liquidation-parent_base
                gross_ticks=side*(quote-entry_price)/tick;peak=max(peak,gross_ticks);worst=min(worst,gross_ticks)
                best_net=max(best_net,local);worst_net=min(worst_net,local)
        # ----------------------------------------
        # 場停止は純清算、親の利確/損切り/追尾は初回実entryに対するgross値幅。
        if known and np.isfinite(loss_line) and not session_block:
            if liquidation<=-loss_line:session_block=True;session_reason=161
            elif liquidation>=profit_line:session_block=True;session_reason=162
            if session_block:
                counts[15]+=1
                amount=held-reserved;line=loss_line if session_reason==161 else profit_line
                controls,cc=_append(controls,cc,np.array([row,cid,session_reason,amount,held,reserved,gross_ticks,peak,liquidation,line,seq[row]],np.float64))
                if amount>0:
                    assert qn<4;queue[qn]=np.array([row,amount,session_reason]);qn+=1;reserved+=amount
                if pending:
                    executions,ec=_append(executions,ec,np.array([row,3,pending_cid,pending_row,pending_side,0,np.nan,session_reason,held,seq[row],seq[pending_row]],np.float64))
                    pending=False;counts[5]+=1
        if held>reserved and known and not timer_reason and not session_block:
            reason=0;line=0.;amount=held-reserved
            if gross_ticks<=-2.:reason=141;line=-2.
            elif exit_mode==0 and gross_ticks>=2.:reason=140;line=2.
            elif exit_mode==1 and gross_ticks>=4.:reason=140;line=4.
            elif exit_mode==2:
                if gross_ticks>=3.:trail=True
                if trail:
                    line=max(2.,peak-1.)
                    if gross_ticks<=line:reason=142
            elif exit_mode==3:
                if not partial_requested and gross_ticks>=2.:
                    reason=143;line=2.;amount=cap//2;partial_requested=True;trail=True
                elif trail:
                    line=max(1.,peak-1.)
                    if gross_ticks<=line:reason=142
            if reason:
                assert 0<amount<=held-reserved and qn<4
                controls,cc=_append(controls,cc,np.array([row,cid,reason,amount,held,reserved,gross_ticks,peak,liquidation,line,seq[row]],np.float64))
                queue[qn]=np.array([row,amount,reason]);qn+=1;reserved+=amount
        # ----------------------------------------
        # 当行候補は一回消費。busy/予定窓/公開spread拒否を将来のquoteで変更しない。
        while pointer<len(candidates) and int(candidates[pointer,0])==row:
            c=candidates[pointer];pointer+=1;counts[0]+=1
            d=int(c[2]);reason=0
            if session_block:reason=session_reason;counts[10]+=1
            elif timer_reason:reason=timer_reason;counts[9]+=1
            elif held>0 or pending or reserved>0:reason=94;counts[6]+=1
            elif not(np.isfinite(time) and entry_start<=time<entry_end):reason=95;counts[9]+=1
            elif not normal:reason=96;counts[8]+=1
            elif ask[row]-bid[row]>=2*tick:reason=97;counts[7]+=1
            accepted=reason==0;pub_cid=next_cid if accepted else -1
            quote=ask[row] if d>0 else bid[row]
            pubs,pubc=_append(pubs,pubc,np.array([row,c[1],c[3],c[4],d,int(accepted),pub_cid,reason,ask[row]-bid[row],quote,cap,seq[row]],np.float64))
            if accepted:
                pending=True;pending_row=row;pending_cid=next_cid;next_cid+=1;pending_side=d;pending_event=int(c[1]);counts[1]+=1
        reserved_check=0.
        for k in range(qn):reserved_check+=queue[k,1]
        assert reserved<=held and reserved_check==reserved
        curve[row]=np.array([cash,liquidation,held,side,reserved,reserve_fee,paid,cid,local,gross_ticks,
            peak if held else np.nan,int(trail),loss_line,profit_line,int(known),int(normal)],np.float64)
    assert pointer==len(candidates)
    final=np.array([held,int(pending),reserved,qn,int(force_observed),int(session_block),cash,paid],np.float64)
    return orders[:oc],legs[:lc],parents[:pc],pubs[:pubc],executions[:ec],controls[:cc],curve,counts,final


def simulate(arrays: dict, signal: dict, symbol: str, start: float, end: float, tick: float,
             time_policy: dict, config: dict, finish: bool=True) -> dict:
    """
    機能: 114保存の公開事象を三入口で選び、実約定・個別料・完結親へ因果接続する。
    引数: arrays/signal/time_policy/config(dict)、symbol(str)、start/end/tick(float)、finish(bool)。
    返り値: dict は各配列/fields・完結親/脚/主会計・mask・完了状態。未完了を全場損益と呼ばない。
    """
    assert symbol in catalog.CAP and config in catalog.configs()
    assert np.isfinite(start) and np.isfinite(end) and start<end and np.isfinite(tick) and tick>0
    n=len(arrays['raw_seq']);assert n>0
    for name in ('raw_seq','price_time_s','bid','ask','bid_qty','ask_qty','best_quantity_valid'):
        assert arrays[name].shape==(n,)
    assert np.issubdtype(arrays['raw_seq'].dtype,np.integer)
    assert np.all((arrays['raw_seq']>=0)&(arrays['raw_seq']<2**53))
    known=np.asarray(signal['price_valid_mask']);assert known.shape==(n,) and known.dtype==bool
    b,a,t=arrays['bid'],arrays['ask'],arrays['price_time_s']
    assert np.all(~known|(np.isfinite(b)&np.isfinite(a)&(b>0)&(a>b)&np.isfinite(t)&(t>=start)&(t<end)))
    quantity=arrays['best_quantity_valid']&np.isfinite(arrays['bid_qty'])&np.isfinite(arrays['ask_qty'])&(arrays['bid_qty']>0)&(arrays['ask_qty']>0)
    normal=known&quantity
    events=np.asarray(signal['events']);names=signal['fields'];assert events.ndim==2 and events.shape[1]==len(names)
    assert len(names)==len(set(names)) and np.all(np.isfinite(events))
    j={k:names.index(k) for k in ('type','episode','pub_i','d','opposite_q0','opposite_min_q','bid_q_at_public','ask_q_at_public')}
    mode=config['entry_mode'];chosen=[]
    for index,event in enumerate(events):
        typ=int(event[j['type']]);d=int(event[j['d']]);row=int(event[j['pub_i']])
        assert typ==event[j['type']] and d==event[j['d']] and row==event[j['pub_i']]
        assert typ in (0,1) and d in (-1,1) and 0<=row<n and event[j['opposite_q0']]>0
        accepted=(typ==0) if mode==0 else typ==1 and event[j['opposite_min_q']]>=event[j['opposite_q0']]
        if accepted and mode==2:
            own=event[j['bid_q_at_public']] if d>0 else event[j['ask_q_at_public']]
            opposite=event[j['ask_q_at_public']] if d>0 else event[j['bid_q_at_public']]
            accepted=own>=opposite
        if accepted:chosen.append((row,index,d,typ,event[j['episode']]))
    candidates=np.asarray(chosen,float).reshape((-1,5))
    assert not len(candidates) or np.all(np.diff(candidates[:,0])>0),'同一入口種類の当行候補を重複しない'
    quiet=np.asarray(time_policy['quiet_windows'],float).reshape((-1,2))
    assert np.all(np.isfinite(quiet)) and np.all(quiet[:,0]<quiet[:,1])
    entry_start=float(time_policy['entry_start_s']);entry_end=float(time_policy['entry_end_s']);force=float(time_policy['force_start_s'])
    assert start<=entry_start<entry_end==end-600. and force==end-300.
    num,den=catalog.FEE_RATIO[symbol]
    values=_run(arrays['raw_seq'],t,b,a,known,normal,candidates,entry_start,entry_end,force,quiet,
        catalog.CAP[symbol],tick,catalog.VALUE[symbol],num,den,config['exit_mode'],config['session_loss_fraction'],config['session_profit_fraction'])
    orders,legs,parents,pubs,execution,controls,curve,counts,final=values
    assert np.all(np.isfinite(orders)) and np.all(np.isfinite(legs)) and np.all(np.isfinite(parents))
    assert np.all(orders[:,0]>orders[:,1]),'判断当行の約定を禁止'
    assert not len(orders) or np.all(orders[orders[:,8]==1,6]==catalog.CAP[symbol])
    parent_records=[]
    for p in parents:
        out=dict(zip(PARENT_FIELDS,p.tolist()))
        for k in ('parent','uid','publication_row','entry_row','exit_row','side','quantity','entry_raw_seq','exit_raw_seq','signal_event_index','unknown_price_rows','unknown_quantity_rows'):
            out[k]=int(out[k])
        out.update(親=out['parent'],方向=out['side'],枚数=out['quantity'],粗損益=out['gross_yen'],費用=out['fee_yen'],収支=out['net_yen'])
        parent_records.append(out)
    leg_records=[dict(zip(LEG_FIELDS,p.tolist())) for p in legs]
    pnl=parents[:,9];profit=float(np.maximum(pnl,0).sum());loss=float(-np.minimum(pnl,0).sum())
    completed=bool(finish and final[0]==final[1]==final[2]==final[3]==0 and final[4]==1)
    if completed:
        assert abs(float(pnl.sum())-final[6])<1e-5 and abs(float(legs[:,11].sum())-final[6])<1e-5
        assert abs(float(orders[:,10].sum())-final[7])<1e-5
        assert len(parents)==int(np.sum(orders[:,8]==1))
    summary=dict(symbol=symbol,利益=profit,損失=loss,収支=float(pnl.sum()),親数=len(parents),
        勝ち親=int(np.sum(pnl>0)),負け親=int(np.sum(pnl<0)),零親=int(np.sum(pnl==0)),
        利益割合=profit/(profit+loss) if profit+loss else None,費用=int(final[7]),新規枚数=int(np.sum(orders[orders[:,8]==1,6])),
        勝ち枚数=int(np.sum(legs[legs[:,11]>0,3])),負け枚数=int(np.sum(legs[legs[:,11]<0,3])),零枚数=int(np.sum(legs[legs[:,11]==0,3])),
        親勝ち枚数=int(np.sum(parents[parents[:,9]>0,6])),親負け枚数=int(np.sum(parents[parents[:,9]<0,6])),
        最大買枚数=int(np.max(np.where(curve[:,3]>0,curve[:,2],0))),最大売枚数=int(np.max(np.where(curve[:,3]<0,curve[:,2],0))),
        全会計合格=completed,未完結保有枚数=int(final[0]),新規予約残=bool(final[1]))
    return dict(config=config,orders=orders,order_fields=list(ORDER_FIELDS),actual_order_legs=legs,leg_fields=list(LEG_FIELDS),
        parents=parents,parent_fields=list(PARENT_FIELDS),parent=parent_records,actual_legs=leg_records,summary=summary,
        publication_events=pubs,publication_fields=list(PUBLICATION_FIELDS),execution_events=execution,execution_fields=list(EXECUTION_FIELDS),
        control_events=controls,control_fields=list(CONTROL_FIELDS),curve=curve,curve_fields=list(CURVE_FIELDS),
        counts={k:int(counts[i]) for i,k in enumerate(COUNT_FIELDS)},completed=completed,finish=finish,
        final_state=dict(zip(('held_quantity','pending_new','reserved_quantity','exit_queue_count','force_observed','session_block','cash_yen','paid_fee_yen'),final.tolist())),
        price_valid_mask=known,execution_normal_mask=normal,reason_labels=dict(REASONS),
        definition='実parent netが主金額、勝負枚数は実返済脚net。未知価格の保有評価はNaNで未測。gross値幅は初回実entry基準。')
