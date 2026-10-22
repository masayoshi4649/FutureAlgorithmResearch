"""純建玉の進行・回帰・撤回を正常原行の次行で実行する。"""

from __future__ import annotations

import math
import numpy as np
from numba import njit


FEATURE_COLUMNS=('closed_last','prev_closed_last','range15_high','range15_low','mean15','er15','change15','scale',
                 'peer_dir','peer_er','peer_age','peer_change15')
ORDER_COLUMNS=('order_uid','group_id','kind','side','quantity','decision_row','fill_row','decision_time','fill_time',
               'price','fee','reason','decision_last','decision_bid','decision_ask','trigger_price','realized_net',
               'position_after','average_entry_after','cash_after')
TRADE_COLUMNS=('group_id','side','quantity','entry_notional','average_entry','first_entry_row','first_entry_time',
               'exit_decision_row','exit_row','exit_time','exit_price','gross','entry_fees','exit_fee','net','mfe','mae',
               'entry_reason','exit_reason','initial_w','initial_stop','entry_orders','proxy_flag','reference_row','planned_exit_time')
CURVE_COLUMNS=('row','time','equity','cash','realized_net','long','short','drawdown')
SUMMARY_COLUMNS=('net','cash','profit','loss','fees_paid','closed_groups','wins','losses','unclosed_quantity','unclosed','position',
                 'max_long','max_short','max_drawdown','min_equity','entry_orders','entry_quantity','canceled_entries',
                 'clock_rejected','forced_groups','normal_groups','add_orders','groups_started','first_entry_time',
                 'last_time','last_equity','normal_closed_groups','proxy_closed_groups','proxy_quantity','proxy_reference_row',
                 'proxy_reference_time','normal_unclosed_before_proxy','pending_close_at_eof')
REASONS={1:'押し戻り後の再進行',2:'追跡極値から反発反落',3:'ER追従',4:'ER往復の中心回帰',5:'三十分期限の通常半容量参加',
         10:'初期損切り',11:'準備支持水準の撤回',12:'利益追尾',13:'新しい反対方向で持替え',14:'固定中心到達',
         15:'場末の通常返済',16:'終端六分以内BBOの代理精算',20:'一単位順行後の残容量追加'}


@njit(cache=False,boundscheck=True)
def _push(table,count,values):
    """
    機能: 人工・金融とも同じ動的台帳へ一行保存する。
    引数: table(float64二次元配列)、count(int)、values(float64一次元配列)。
    返り値: tuple[ndarray,int]は保存先と新しい行数。
    """
    if count==len(table):
        expanded=np.empty((max(8,count*2),table.shape[1]),np.float64)
        expanded[:count]=table
        table=expanded
    table[count]=values
    return table,count+1


@njit(cache=False,boundscheck=True)
def _peer_ok(feature,side,required,now,published,trend):
    """
    機能: 相手の時刻資格と方向を同じ固定規則で確認する。
    引数: feature(ndarray12列)、side(int)、required/trend(bool)、now/published(float)。
    返り値: boolは不要対照又は有効な相手条件の成立。
    """
    if not required:
        return True
    if not (math.isfinite(feature[8]) and math.isfinite(feature[9]) and math.isfinite(feature[10])):
        return False
    if not 0.<=feature[10]+max(0.,now-published)<=120.:
        return False
    return feature[8]==side and (not trend or feature[9]>=.4)


@njit(cache=False,boundscheck=True)
def replay(rows,times,last,bid,ask,feature_rows,features,cap,multiplier,fee,observed_tick,mode,stop_w,
           trail_start_w,trail_w,add_enabled,peer_required,session_start,entry_end,close_time,session_end):
    """
    機能: 確定足状態で入口を準備し、純建玉・全費用・実返済と代理終端を逐次会計する。
    引数: rows/feature_rows(int64一次元配列)、times/last/bid/ask(float64一次元配列)、features(float64二次元12列)。
        cap/mode(int)、multiplier/fee/observed_tick/stop_w/trail_start_w/trail_w/場内時刻(float)、add_enabled/peer_required(bool)。
    返り値: tuple[orders,closed_trades,curve,summary]は20/25/8/33列のfloat64配列。
        初回cap//2、反転前に実返済、全tick時価、通常判断の厳密に次正常原行で約定する。
        曲線は六十秒と最終行を保存。EOF代理は通常注文を作らず、未返済と区別する。
    """
    assert cap>=2 and mode>=0 and mode<=2 and multiplier>0. and fee>=0. and observed_tick>0.
    assert stop_w>0. and trail_start_w>0. and trail_w>0. and session_start<entry_end<=close_time<=session_end
    assert features.shape[1]==12 and len(feature_rows)==len(features)
    orders=np.empty((1024,20));trades=np.empty((512,25));curves=np.empty((1024,8))
    oc=tc=cc=order_id=group_id=0
    qty=side=0;average=notional=entry_fees=0.
    first_row=-1;first_time=np.nan;entry_reason=0;group_orders=0
    group_w=hard_stop=initial_stop=support=center=peak_price=held_last_extreme=0.
    group_mfe=group_mae=0.;initial_budget=0.;added=False;trail_armed=False
    cash=realized=profit=loss=fees_paid=0.
    high_equity=max_dd=min_equity=equity=0.
    entry_orders=entry_quantity=canceled=rejected=forced_groups=normal_groups=add_orders=0
    wins=losses=max_long=max_short=normal_closed=0
    first_entry=-1.
    pending=0;pending_side=pending_qty=pending_reason=0
    pending_row=-1;pending_time=pending_last=pending_bid=pending_ask=pending_trigger=0.
    pending_w=0.;pending_support=pending_center=np.nan
    reverse_side=0;reverse_w=0.
    feature=np.full(12,np.nan);fi=-1;next_fi=0;feature_time=-np.inf
    setup_side=setup_stage=0;setup_w=0.;setup_extreme=setup_pull=0.
    setup_support=setup_center=np.nan
    anchor_low=anchor_high=np.nan
    consumed_feature=-2;exit_feature=-2
    first_last=previous_last=np.nan
    last_clock=-np.inf;last_row=-1;last_time=last_bid=last_ask=last_last=np.nan
    curve_clock=-np.inf;last_decision_row=-1
    has_entry=False

    for i in range(len(rows)):
        now=times[i];raw=rows[i]
        if not (math.isfinite(now) and session_start<=now<=session_end and now>=last_clock and
                math.isfinite(last[i]) and last[i]>0. and math.isfinite(bid[i]) and math.isfinite(ask[i]) and 0.<bid[i]<=ask[i]):
            rejected+=1
            continue
        last_clock=now;last_row=raw;last_time=now;last_bid=bid[i];last_ask=ask[i];last_last=last[i]
        if not math.isfinite(first_last):
            first_last=previous_last=anchor_low=anchor_high=last[i]
        move=last[i]-previous_last;previous_last=last[i]
        fresh=False
        while next_fi<len(feature_rows) and feature_rows[next_fi]<=raw:
            feature=features[next_fi].copy();fi=next_fi;next_fi+=1
            feature_time=session_start+60.*math.floor((now-session_start)/60.)
            fresh=True

        # ----------------------------------------
        # 以前の原行で出した一注文だけを実行する。新規締切後は未約定新規を取り消す。
        just_closed=False
        if pending and raw>pending_row:
            if pending in (1,3) and (now>=entry_end or ask[i]-bid[i]+2.*fee/multiplier>.5*pending_w):
                canceled+=1;pending=0
            elif pending==1:
                assert qty==0 and pending_qty==cap//2
                group_id+=1;side=pending_side;qty=pending_qty
                average=ask[i] if side==1 else bid[i];notional=qty*average
                charge=math.floor(qty*fee+1e-9);entry_fees=charge;fees_paid+=charge;cash-=charge
                first_row=raw;first_time=now;entry_reason=pending_reason;group_orders=1
                group_w=pending_w;support=pending_support;center=pending_center
                hard_stop=average-side*stop_w*group_w
                if math.isfinite(support):
                    hard_stop=max(hard_stop,support) if side==1 else min(hard_stop,support)
                initial_stop=hard_stop
                initial_budget=max(0.,side*(average-hard_stop)*qty*multiplier)+charge+math.floor(qty*fee+1e-9)
                peak_price=bid[i] if side==1 else ask[i]
                held_last_extreme=last[i]
                initial_mark=side*(peak_price-average)*qty*multiplier-entry_fees-math.floor(qty*fee+1e-9)
                group_mfe=max(0.,initial_mark);group_mae=min(0.,initial_mark)
                added=False;trail_armed=False;has_entry=True
                if first_entry<0.:first_entry=now
                forced_groups+=int(entry_reason==5);normal_groups+=int(entry_reason!=5)
                entry_orders+=1;entry_quantity+=qty;order_id+=1
                orders,oc=_push(orders,oc,np.array([order_id,group_id,1.,side,qty,pending_row,raw,pending_time,now,average,
                    charge,pending_reason,pending_last,pending_bid,pending_ask,pending_trigger,0.,side*qty,average,cash]))
                pending=0;setup_stage=0;setup_side=0;reverse_side=0
            elif pending==3:
                assert qty>0 and pending_side==side and qty+pending_qty<=cap
                xp=ask[i] if side==1 else bid[i];charge=math.floor(pending_qty*fee+1e-9)
                notional+=pending_qty*xp;qty+=pending_qty;average=notional/qty
                entry_fees+=charge;fees_paid+=charge;cash-=charge;group_orders+=1
                required=average+side*(entry_fees+math.floor(qty*fee+1e-9)-initial_budget)/(qty*multiplier)
                hard_stop=max(hard_stop,required) if side==1 else min(hard_stop,required)
                assert side*(hard_stop-initial_stop)>=-1e-8
                added=True;add_orders+=1;entry_orders+=1;entry_quantity+=pending_qty;order_id+=1
                orders,oc=_push(orders,oc,np.array([order_id,group_id,1.,side,pending_qty,pending_row,raw,pending_time,now,xp,
                    charge,20.,pending_last,pending_bid,pending_ask,pending_trigger,0.,side*qty,average,cash]))
                pending=0
            elif pending==2:
                assert qty>0
                xp=bid[i] if side==1 else ask[i];charge=math.floor(qty*fee+1e-9)
                gross=side*(xp*qty-notional)*multiplier;net=gross-entry_fees-charge
                group_mfe=max(group_mfe,net);group_mae=min(group_mae,net)
                cash+=gross-charge;realized+=net;profit+=max(0.,net);loss+=max(0.,-net);fees_paid+=charge
                wins+=int(net>0.);losses+=int(net<0.);normal_closed+=1;order_id+=1
                orders,oc=_push(orders,oc,np.array([order_id,group_id,2.,-side,qty,pending_row,raw,pending_time,now,xp,
                    charge,pending_reason,pending_last,pending_bid,pending_ask,pending_trigger,net,0.,0.,cash]))
                trades,tc=_push(trades,tc,np.array([group_id,side,qty,notional,average,first_row,first_time,pending_row,raw,now,
                    xp,gross,entry_fees,charge,net,group_mfe,group_mae,entry_reason,pending_reason,group_w,initial_stop,group_orders,
                    0.,raw,pending_time]))
                qty=0;side=0;average=notional=entry_fees=0.;pending=0;just_closed=True
                anchor_low=anchor_high=last[i];setup_side=setup_stage=0;exit_feature=fi

        # ----------------------------------------
        # 全tickで返済側BBOと全返済料を含む時価を計算する。曲線の保存間隔とは別。
        equity=cash
        mark=0.
        if qty:
            xp=bid[i] if side==1 else ask[i]
            mark=side*(xp*qty-notional)*multiplier-entry_fees-math.floor(qty*fee+1e-9)
            equity+=mark+entry_fees
            group_mfe=max(group_mfe,mark);group_mae=min(group_mae,mark)
            peak_price=max(peak_price,xp) if side==1 else min(peak_price,xp)
            held_last_extreme=max(held_last_extreme,last[i]) if side==1 else min(held_last_extreme,last[i])
            if mark>0. and side*(peak_price-average)>=trail_start_w*group_w:trail_armed=True
        high_equity=max(high_equity,equity);min_equity=min(min_equity,equity);max_dd=max(max_dd,high_equity-equity)
        max_long=max(max_long,qty if side==1 else 0);max_short=max(max_short,qty if side==-1 else 0)
        if now>=curve_clock+60.:
            curves,cc=_push(curves,cc,np.array([raw,now,equity,cash,realized,qty if side==1 else 0,qty if side==-1 else 0,high_equity-equity]))
            curve_clock=now

        valid_state=math.isfinite(feature[5]) and math.isfinite(feature[6]) and math.isfinite(feature[7]) and feature[7]>0.
        d=1 if valid_state and feature[6]>0. else -1 if valid_state and feature[6]<0. else 0
        trend=valid_state and feature[5]>=.4 and abs(feature[6])>=feature[7] and d!=0
        trend=trend and _peer_ok(feature,d,peer_required,now,feature_time,True)
        range_state=valid_state and feature[5]<=.2 and math.isfinite(feature[2]) and math.isfinite(feature[3]) and math.isfinite(feature[4])
        if range_state and peer_required:
            range_state=math.isfinite(feature[9]) and feature[9]<=.2 and math.isfinite(feature[10]) and 0.<=feature[10]+max(0.,now-feature_time)<=120.
        if fresh:
            # 未約定の準備は新しい欠測・状態不一致で取り消す。保有済みの撤回線は動かさない。
            invalid_setup=not valid_state or (mode==0 and not trend) or (mode==2 and setup_stage==3 and not range_state)
            if invalid_setup:
                setup_side=setup_stage=0

        # ----------------------------------------
        # 初期撤回線は保有中に広げない。反対の新規は必ず旧玉の返済完了後。
        if qty and not pending:
            exit_reason=0;line=np.nan;wanted=0
            xp=bid[i] if side==1 else ask[i]
            b_reverse=mode==1 and side*(last[i]-held_last_extreme)<=-group_w and _peer_ok(feature,-side,peer_required,now,feature_time,False)
            strong_reverse=fresh and trend and d==-side
            if now>=close_time:
                exit_reason=15;line=xp
            elif side*(xp-hard_stop)<=0.:
                exit_reason=10;line=hard_stop
                if b_reverse or strong_reverse:wanted=-side
            elif math.isfinite(support) and side*(last[i]-support)<=0.:
                exit_reason=11;line=support
                if b_reverse or strong_reverse:wanted=-side
            elif b_reverse or strong_reverse:
                exit_reason=13;line=last[i];wanted=-side
            elif trail_armed and side*(peak_price-xp)>=trail_w*group_w:
                exit_reason=12;line=peak_price-side*trail_w*group_w
            elif entry_reason==4 and math.isfinite(center) and side*(last[i]-center)>=0.:
                exit_reason=14;line=center
            if exit_reason:
                pending=2;pending_side=-side;pending_qty=qty;pending_reason=exit_reason
                pending_row=raw;pending_time=now;pending_last=last[i];pending_bid=bid[i];pending_ask=ask[i];pending_trigger=line
                reverse_side=wanted;reverse_w=feature[7] if valid_state else group_w
                last_decision_row=raw
            elif (add_enabled and not added and qty<cap and now<entry_end and side*(xp-average)>=group_w
                  and ask[i]-bid[i]+2.*fee/multiplier<=.5*group_w):
                allow=mode==1 or (trend and d==side)
                if allow:
                    extra=cap-qty;price_guess=ask[i] if side==1 else bid[i]
                    total_price=(notional+extra*price_guess)/cap
                    total_fees=entry_fees+math.floor(extra*fee+1e-9)+math.floor(cap*fee+1e-9)
                    required=total_price+side*(total_fees-initial_budget)/(cap*multiplier)
                    possible=max(hard_stop,required) if side==1 else min(hard_stop,required)
                    if side*(xp-possible)>=observed_tick:
                        pending=3;pending_side=side;pending_qty=extra;pending_reason=20;pending_w=group_w
                        pending_row=raw;pending_time=now;pending_last=last[i];pending_bid=bid[i];pending_ask=ask[i];pending_trigger=average+side*group_w
                        last_decision_row=raw

        # ----------------------------------------
        # 平坦時だけ新しい入口を準備する。利確後は新しい分か新しい極値から再準備。
        if qty or pending or now>=entry_end or raw==last_decision_row:
            continue
        desired=0;reason=0;prepared_w=feature[7] if valid_state else 8.*observed_tick
        prepared_support=prepared_center=np.nan;trigger_price=last[i]
        if just_closed and reverse_side:
            desired=reverse_side;prepared_w=reverse_w;reason=2 if mode==1 else 1 if mode==0 else 3
            reverse_side=0
        elif not has_entry and now>=session_start+1800.:
            desired=1 if last[i]>first_last else -1 if last[i]<first_last else 0
            if desired==0 and math.isfinite(feature[0]) and math.isfinite(feature[1]):
                desired=1 if feature[0]>feature[1] else -1 if feature[0]<feature[1] else 0
            if desired==0:desired=1
            reason=5;setup_side=setup_stage=0
        elif mode==1:
            anchor_low=min(anchor_low,last[i]);anchor_high=max(anchor_high,last[i])
            if valid_state:
                if move>0. and last[i]>=anchor_low+prepared_w and _peer_ok(feature,1,peer_required,now,feature_time,False):
                    desired=1;reason=2;trigger_price=anchor_low+prepared_w;prepared_support=anchor_low-observed_tick
                elif move<0. and last[i]<=anchor_high-prepared_w and _peer_ok(feature,-1,peer_required,now,feature_time,False):
                    desired=-1;reason=2;trigger_price=anchor_high-prepared_w;prepared_support=anchor_high+observed_tick
        else:
            if fresh and fi>exit_feature and fi!=consumed_feature:
                consumed_feature=fi
                if trend:
                    if mode==2:
                        desired=d;reason=3
                        prepared_support=feature[3]-observed_tick if d==1 else feature[2]+observed_tick
                    elif setup_stage==0 or setup_side!=d:
                        setup_side=d;setup_stage=1;setup_w=prepared_w;setup_extreme=last[i];setup_pull=last[i]
                        setup_support=setup_center=np.nan
                elif mode==2 and range_state and feature[2]-feature[3]>=2.*prepared_w:
                    if last[i]<=feature[3]+.25*prepared_w:
                        setup_side=1;setup_stage=3;setup_w=prepared_w;setup_extreme=last[i]
                        setup_support=feature[3]-.25*prepared_w;setup_center=feature[4]
                    elif last[i]>=feature[2]-.25*prepared_w:
                        setup_side=-1;setup_stage=3;setup_w=prepared_w;setup_extreme=last[i]
                        setup_support=feature[2]+.25*prepared_w;setup_center=feature[4]
                elif setup_stage==1:
                    setup_stage=0;setup_side=0
            if not desired and setup_side and setup_stage:
                if setup_stage==1:
                    setup_extreme=max(setup_extreme,last[i]) if setup_side==1 else min(setup_extreme,last[i])
                    if setup_side*(setup_extreme-last[i])>=setup_w:
                        setup_side=setup_stage=0
                    elif setup_side*(setup_extreme-last[i])>=.25*setup_w:
                        setup_stage=2;setup_pull=last[i]
                elif setup_stage==2:
                    setup_pull=min(setup_pull,last[i]) if setup_side==1 else max(setup_pull,last[i])
                    if setup_side*(setup_extreme-last[i])>=setup_w:
                        setup_side=setup_stage=0
                    elif setup_side*(last[i]-setup_pull)>=.25*setup_w and _peer_ok(feature,setup_side,peer_required,now,feature_time,True):
                        desired=setup_side;reason=1;prepared_w=setup_w
                        prepared_support=setup_pull-setup_side*observed_tick;trigger_price=setup_pull+setup_side*.25*setup_w
                elif setup_stage==3:
                    setup_extreme=min(setup_extreme,last[i]) if setup_side==1 else max(setup_extreme,last[i])
                    if setup_side*(last[i]-setup_support)<=0.:
                        setup_side=setup_stage=0
                    elif setup_side*(last[i]-setup_extreme)>=.25*setup_w:
                        desired=setup_side;reason=4;prepared_w=setup_w;prepared_support=setup_support;prepared_center=setup_center
                        trigger_price=setup_extreme+setup_side*.25*setup_w
        if desired and ask[i]-bid[i]+2.*fee/multiplier<=.5*prepared_w:
            assert prepared_w>0. and math.isfinite(prepared_w)
            pending=1;pending_side=desired;pending_qty=cap//2;pending_reason=reason
            pending_row=raw;pending_time=now;pending_last=last[i];pending_bid=bid[i];pending_ask=ask[i];pending_trigger=trigger_price
            pending_w=prepared_w;pending_support=prepared_support;pending_center=prepared_center
            setup_side=setup_stage=0;last_decision_row=raw

    # ----------------------------------------
    # 通常の最終在庫曲線を残し、六分窓内だけ代理返済を別区分で追加する。
    normal_unclosed=qty;pending_close=int(pending==2)
    canceled+=int(pending in (1,3))
    proxy_groups=proxy_qty=0;proxy_row=-1;proxy_time=-1.
    if last_row>=0:
        curves,cc=_push(curves,cc,np.array([last_row,last_time,equity,cash,realized,qty if side==1 else 0,qty if side==-1 else 0,high_equity-equity]))
        if qty and session_end-360.<=last_time<=session_end:
            xp=last_bid if side==1 else last_ask;charge=math.floor(qty*fee+1e-9)
            gross=side*(xp*qty-notional)*multiplier;net=gross-entry_fees-charge
            group_mfe=max(group_mfe,net);group_mae=min(group_mae,net)
            cash+=gross-charge;realized+=net;profit+=max(0.,net);loss+=max(0.,-net);fees_paid+=charge
            wins+=int(net>0.);losses+=int(net<0.);proxy_groups=1;proxy_qty=qty;proxy_row=last_row;proxy_time=last_time
            trades,tc=_push(trades,tc,np.array([group_id,side,qty,notional,average,first_row,first_time,
                -1.,-1.,last_time,xp,gross,entry_fees,charge,net,group_mfe,group_mae,entry_reason,16.,group_w,initial_stop,group_orders,
                1.,last_row,session_end]))
            qty=0;side=0;equity=cash
    summary=np.array([equity,cash,profit,loss,fees_paid,tc,wins,losses,qty,qty,side*qty,max_long,max_short,max_dd,min_equity,
        entry_orders,entry_quantity,canceled,rejected,forced_groups,normal_groups,add_orders,group_id,first_entry,last_time,equity,
        normal_closed,proxy_groups,proxy_qty,proxy_row,proxy_time,normal_unclosed,pending_close],np.float64)
    return orders[:oc],trades[:tc],curves[:cc],summary


def evaluate(quotes: dict,features: dict,config: dict,spec: dict) -> tuple:
    """
    機能: 所有済み正常気配と確定足状態を固定十二条件の配列実行へ接続する。
    引数: quotes(dict[str,ndarray])は五気配列、features(dict)はfeature_rowsとfeatures、config/spec(dict)は商品・固定規則。
    返り値: tuple[ndarray,ndarray,ndarray,dict]は注文・完結群・時価曲線と列名付き集計。
        呼出し側はsummary['unclosed_quantity']を成功へ数えず、終端代理と通常返済を区別する。
    """
    rows=quotes['row']
    assert all(len(quotes[k])==len(rows) for k in ('time','last','bid','ask'))
    assert np.all(np.diff(rows)>0)
    fr=features['feature_rows'];fv=features['features']
    assert np.all(np.diff(fr)>0) and fv.shape==(len(fr),len(FEATURE_COLUMNS))
    indices=np.searchsorted(rows,fr)
    assert np.all(indices<len(rows)) and np.array_equal(rows[indices],fr)
    start=config.get('session_start',config.get('start'))
    end=config.get('session_end',config.get('end'))
    tick=config.get('observed_tick',config.get('tick'))
    entry_end=config.get('entry_end',config.get('new_deadline',end-1800.))
    close_time=config.get('close_time',end-360.)
    o,t,c,n=replay(rows,quotes['time'],quotes['last'],quotes['bid'],quotes['ask'],fr,fv,
        config['cap'],config['multiplier'],config['fee'],tick,spec['mode'],spec['stop_w'],spec['trail_start_w'],spec['trail_w'],
        spec['add_enabled'],spec['peer_required'],start,entry_end,close_time,end)
    return o,t,c,dict(zip(SUMMARY_COLUMNS,n.tolist()))
