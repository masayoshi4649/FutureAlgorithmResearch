"""共通D273の価格管理を維持し、手法選択の所有者・取消確認・再準備を追跡する。"""

from __future__ import annotations

import numpy as np
from numba import njit

PARAMS = ['initial_qty','entry_atr','stop_atr','main_trail','add_mode','add_step',
          'add_qty','hedge_ratio','hedge_trigger','cover_add','cover_step',
          'cover_trail','reverse_mode','lock_fraction','split_target',
          'timeout_min','neutral_min','us_mode','activation_atr','tighten_atr',
          'tight_width','breakeven_atr','breakeven_floor','failure_min','failure_mfe',
          'failure_stop','cooldown_min','ttl_seconds','entry_mode','signal_exit',
          'after_open_factor','entry_cutoff_min','warmup_min','max_same_losses',
          'rearm_atr','session_budget_r','risk_yen','point_value','session_budget_yen',
          'max_reversals']
REASONS = {1:'合算損失上限',2:'主方向の追跡返済',3:'カバー追跡返済',
           4:'カバー損切り',5:'判断撤回で主玉返済',6:'方向再開でカバー返済',
           7:'一部利確',8:'保有時間上限',9:'セッション内返済',10:'中立状態で縮小',
           11:'合算利益保護',12:'米国開始帯の縮小',13:'方向状態の撤回',14:'セッション損失予算'}


SELECTION_COLUMNS = ['request_id', 'applied_id', 'pending_owner_id', 'position_owner_id',
                     'entry_source_id', 'entry_direction', 'cancel_wait', 'cancel_source_row',
                     'pending_direction', 'pending_source_row', 'pending_entry_source_id',
                     'position_entry_source_id', 'pending_level', 'cooldown_until',
                     'pending_atr', 'pending_expiry', 'position_atr', 'stop_level',
                     'trail_level', 'position_direction']
EVENT_COLUMNS = ['row', 'phase', 'event', 'request_id', 'applied_id', 'pending_owner_id',
                 'position_owner_id', 'entry_source_id', 'source_row', 'old_id', 'new_id',
                 'direction', 'price', 'quantity', 'campaign']
EVENT_NAMES = {1: '要求更新', 2: '取消要求', 3: '取消確認', 4: '適用変更', 5: '新規準備',
               6: '追跡更新', 7: '新規約定', 8: '部分返済', 9: '完全返済',
               10: '期限又は方向で取消', 11: '保有中要求保留', 12: '切替後再準備'}
PHASE_NAMES = {0: '行先頭の取消確認', 1: '既存注文の約定', 2: '現在行の判断'}


@njit(cache=True)
def selection_record(events, count, row, phase, event, requested, applied, pending_owner,
                     position_owner, actual_source, source_row, old_id, new_id, side, level, quantity, campaign):
    """機能: 選択と注文の所有者イベントを価格台帳と別に保存する。

    引数: events (ndarray)、各ID・行・件数・数量 (int)、level (float)。返り値: 追加後件数 (int)。
    phaseにより、前行取消の確認、既存注文の約定、当該行の新しい判断を区別する。
    """
    if count >= len(events):
        raise ValueError('選択イベントの上限を超えました')
    events[count, :] = np.array([row, phase, event, requested, applied, pending_owner, position_owner,
                                actual_source, source_row, old_id, new_id, side, level, quantity, campaign])
    return count + 1


@njit(cache=True)
def rounded(value, tick, side):
    """機能: 逆指値水準を呼値へ丸める。

    引数: value/tick (float)、side (int)。返り値: 丸めた価格 (float)。
    """
    return np.ceil(value/tick-1e-9)*tick if side>0 else np.floor(value/tick+1e-9)*tick


@njit(cache=True)
def close_positions(pos, used, trades, count, role, quantity, price, row, reason, campaign):
    """機能: 指定した役割の建玉を古い順に整数枚で返済し、元建値を保持する。

    引数: pos/trades (ndarray)、used/count/role/quantity/row/reason/campaign (int)、price (float)。
    返り値: 台帳件数、確定損益、返済数量 (tuple[int,float,int])。
    """
    pnl, done = 0., 0
    for k in range(used):
        if pos[k,2]<=0 or (role>=0 and int(pos[k,3])!=role):
            continue
        qty=min(int(pos[k,2]),quantity-done)
        if qty<=0:
            break
        value=qty*pos[k,0]*(price-pos[k,1])
        if count>=len(trades):
            raise ValueError('返済台帳の上限を超えました')
        # 組、元脚、方向、枚数、建値、返済値、新規行、返済行、役割、理由、損益。
        trades[count,:]=np.array([campaign,k,pos[k,0],qty,pos[k,1],price,pos[k,4],row,pos[k,3],reason,value])
        count+=1;done+=qty;pnl+=value;pos[k,2]-=qty
    return count,pnl,done


@njit(cache=True)
def inventory(pos,used):
    """機能: 保有数量・簿価を主玉とカバーに分けて集計する。

    引数: pos (ndarray)、used (int)。返り値: 数量と符号付き簿価 (ndarray)。
    """
    out=np.zeros(6)
    for k in range(used):
        qty=pos[k,2]
        if qty>0:
            role=int(pos[k,3]);out[role]+=qty
            out[2]+=qty*pos[k,0];out[3]+=qty*pos[k,0]*pos[k,1]
            out[4 if pos[k,0]>0 else 5]+=qty
    return out


@njit(cache=True)
def simulate(time, price, atr, states, request, tick, start, end, us_open, par, detail, cap, source_override, observed_fill):
    """機能: 前行までの条件だけを次行以降で約定させ、全玉の時価を追跡する。

    引数: time/price/atr/states/request/par (ndarray)、tick/start/end/us_open (float)、detail/observed_fill (bool)、cap/source_override (int)。
    返り値: 旧5台帳と選択イベント・選択全行曲線 (tuple[ndarray,...])。
    指定価格約定。主玉・カバー合計で買い指定上限枚数、売り指定上限枚数まで。
    """
    n=len(price);pos=np.zeros((12000,5));trades=np.zeros((24000,11))
    state=np.zeros(n,dtype=np.int8);context=state
    selection_curve=np.zeros((n,20))
    selection_events=np.empty((7*n+8,15));selection_count=0
    applied=int(request[0]);seen_request=0;pending_owner=0;pending_source_id=0
    position_owner=0;position_source_id=0;cancel_wait=False;cancel_row=-1;cancel_target=0
    reprepare_due_to_switch=False
    orders=np.zeros((36000,8));cycles=np.zeros((2000,10))
    curve=np.zeros((n,8)) if detail else np.zeros((1,8))
    used=0;tc=0;oc=0;cc=0;campaign=-1;d=0;realized=0.;base=0.;cash=0.
    inv=np.zeros(6);a=1.;risk=1.;peak=0.;anchor=0.;extreme=0.;cover_extreme=0.
    cover_anchor=0.;next_add=0.;next_cover=0.;entry_row=0;entry_t=0.;last_exit=-1e20
    pending_d=0;pending_level=0.;pending_until=0.;pending_atr=0.;pending_row=-1
    pending_action=0;action_row=-1;neutral_since=-1.;reversals=0;split_done=False
    stop_level=np.nan;main_level=np.nan;cover_level=np.nan;cover_reason=0
    cover_open_level=np.nan;add_level=np.nan;split_level=np.nan;stop_reason=1
    market_flags=np.zeros(6,dtype=np.bool_)
    high_equity=0.;dd=0.;maxlong=0.;maxshort=0.;maxgross=0.;maxnet=0.
    cycle_gross=0.;cycle_net=0.;max_error=0.;min_equity=0.;max_equity=0.
    protected_floor=-1e100;main_floor=np.nan;pending_extreme=0.
    effective_qty=int(par[0]);pending_qty=int(par[0]);pending_market=False
    loss_streak=np.zeros(2,dtype=np.int64);blocked=np.zeros(2,dtype=np.bool_)
    blocked_price=np.zeros(2);blocked_atr=np.ones(2);campaign_side=0
    session_halted=False;session_budget=np.nan
    if par[38]>0:
        session_budget=par[38]/par[37]
    for i in range(n):
        p=price[i];t=time[i]
        # ----------------------------------------
        # 前行の取消を行先頭で確認し、旧注文を現在価格で約定させる前に失効させる。
        if cancel_wait:
            old_owner=pending_owner
            selection_count=selection_record(selection_events,selection_count,i,0,3,int(request[i]),applied,
                pending_owner,position_owner,pending_source_id,cancel_row,old_owner,cancel_target,
                pending_d,pending_level,pending_qty,campaign)
            pending_d=0;pending_owner=0;pending_source_id=0
            old_applied=applied;applied=cancel_target;cancel_wait=False
            selection_count=selection_record(selection_events,selection_count,i,0,4,int(request[i]),applied,
                0,position_owner,source_override if source_override else applied,cancel_row,old_applied,applied,
                0,np.nan,0,campaign)
            cancel_row=-1;cancel_target=0;reprepare_due_to_switch=True
        actual_source=position_source_id if position_owner else (source_override if source_override else applied)
        state[i]=states[i,actual_source-1]
        if not np.isfinite(p) or p<=0:
            # 価格が欠測でも既に要求した取消確認は完了する。新規判断と価格売買は旧版同様に止める。
            selection_curve[i,:]=np.array([request[i],applied,pending_owner,position_owner,actual_source,state[i],
                int(cancel_wait),cancel_row,pending_d,pending_row if pending_d else -1,pending_source_id,position_source_id,
                pending_level if pending_d else np.nan,last_exit+par[26]*60,pending_atr if pending_d else np.nan,
                pending_until if pending_d else np.nan,a if d else np.nan,stop_level,main_level,d])
            continue
        acted=False;fill=0.;open_side=0;open_qty=0;open_role=0;order_source=i-1
        reason=0;close_role=-2;close_qty=0;promote=False
        # ----------------------------------------
        # 前行で決めた市場返済と方向転換を先に処理する。
        if d!=0 and pending_action!=0:
            reason=pending_action;fill=p;order_source=action_row
            close_role=0 if reason==5 else (1 if reason==6 else -1)
            close_qty=100000
            if reason==5:
                promote=True
            pending_action=0
        elif d!=0:
            # 前行で存在した価格注文のうち、観測区間で先に到達する一件を採用。
            # 一行につき一件とし、約定に応じた再設定は必ず次行から有効。
            best=1e100;event=0;level=0.;prior=price[i-1] if i else p
            levels=np.array([stop_level,main_level,cover_level,cover_open_level,add_level,split_level])
            trigger_sides=np.array([-1 if inv[2]>0 else 1,-d,d,-d,d if int(par[4])!=2 else -d,d])
            for z in range(6):
                v=levels[z];sd=trigger_sides[z]
                if not np.isfinite(v) or (not market_flags[z] and sd*(p-v)<-1e-8):
                    continue
                distance=0. if market_flags[z] else max(0.,sd*(v-prior))
                if distance<best-1e-9:
                    best=distance;event=z+1;level=p if market_flags[z] else v
            if event:
                fill=p if observed_fill else level
                if event==1:
                    reason=stop_reason;close_role=-1;close_qty=100000
                elif event==2:
                    reason=2;close_role=-1;close_qty=100000
                elif event==3:
                    reason=cover_reason;close_role=1;close_qty=100000
                elif event==4:
                    open_side=-d;open_role=1
                    if inv[1]<.5:
                        open_qty=int(np.ceil(inv[0]*par[7]))
                    else:
                        open_qty=int(par[6]) if int(par[9])==1 else max(int(par[6]),int(inv[1]))
                    open_qty=min(open_qty,cap-int(inv[5] if open_side<0 else inv[4]))
                    reason=21
                elif event==5:
                    open_side=d;open_role=0;open_qty=int(par[6])
                    if int(par[4])==3:
                        open_qty=max(open_qty,int(inv[0]))
                    elif int(par[4])==4:
                        open_qty=max(1,int(par[0]*par[0]/max(par[0],inv[0])))
                    open_qty=min(open_qty,cap-int(inv[4] if d>0 else inv[5]))
                    reason=22
                elif event==6:
                    reason=7;close_role=0;close_qty=max(1,int(inv[0]/2));split_done=True
        elif pending_d and not session_halted and t<pending_until and t<end-par[31]*60 and not (int(par[17]) in (1,2) and t>=us_open-900 and t<us_open+1800) and (pending_market or pending_d*(p-pending_level)>=-1e-8):
            d=pending_d;a=pending_atr;effective_qty=pending_qty;risk=effective_qty*par[2]*a;campaign+=1;campaign_side=d
            base=realized;peak=0.;anchor=p if (observed_fill or pending_market) else pending_level;extreme=anchor
            protected_floor=-risk;main_floor=np.nan
            entry_row=i;entry_t=t;cycle_gross=0.;cycle_net=0.;split_done=False
            fill=anchor;open_side=d;open_qty=effective_qty;open_role=0;reason=20
            order_source=pending_row
            position_owner=pending_owner;position_source_id=pending_source_id
            selection_count=selection_record(selection_events,selection_count,i,1,7,int(request[i]),applied,
                pending_owner,position_owner,position_source_id,order_source,pending_owner,position_owner,
                d,fill,open_qty,campaign)
            pending_d=0;pending_owner=0;pending_source_id=0
            next_add=anchor+d*par[5]*a*(-1 if int(par[4])==2 else 1)
            cover_anchor=0.;next_cover=0.
        # ----------------------------------------
        # 返済、カバー昇格、新規約定。反転でも過去の損失や建値を消さない。
        if close_role>=-1 and close_qty>0:
            oldtc=tc
            tc,gain,done=close_positions(pos,used,trades,tc,close_role,close_qty,fill,i,reason,campaign)
            realized+=gain
            for k in range(oldtc,tc):
                if oc>=len(orders):
                    raise ValueError('約定台帳の上限を超えました')
                cash+=trades[k,2]*trades[k,3]*fill
                orders[oc,:]=np.array([i,order_source,campaign,-trades[k,2],trades[k,3],fill,reason,0]);oc+=1
            inv=inventory(pos,used);acted=True
            selection_count=selection_record(selection_events,selection_count,i,1,9 if inv[0]+inv[1]<.5 else 8,
                int(request[i]),applied,pending_owner,position_owner,position_source_id,order_source,
                position_owner,0 if inv[0]+inv[1]<.5 else position_owner,-d,fill,done,campaign)
            if promote:
                d=-d;reversals+=1;anchor=fill;extreme=fill;split_done=False
                for k in range(used):
                    if pos[k,2]>0:
                        pos[k,3]=0
                inv=inventory(pos,used)
                open_side=d;open_role=0;open_qty=max(0,int(effective_qty-inv[0]));reason=23
                next_add=fill+d*par[5]*a*(-1 if int(par[4])==2 else 1);cover_anchor=0.;next_cover=0.
        if open_qty>0:
            if used>=len(pos) or oc>=len(orders):
                raise ValueError('約定台帳の上限を超えました')
            pos[used,:]=np.array([open_side,fill,open_qty,open_role,i]);used+=1
            cash-=open_side*fill*open_qty
            orders[oc,:]=np.array([i,order_source,campaign,open_side,open_qty,fill,reason,1]);oc+=1
            inv=inventory(pos,used);acted=True
            if open_role==0:
                next_add=fill+d*par[5]*a*(-1 if int(par[4])==2 else 1)
            else:
                cover_anchor=fill;cover_extreme=fill;next_cover=fill-d*par[10]*a
        equity=realized+inv[2]*p-inv[3]
        max_error=max(max_error,abs(equity-(cash+inv[2]*p)))
        high_equity=max(high_equity,equity);dd=max(dd,high_equity-equity)
        min_equity=min(min_equity,equity);max_equity=max(max_equity,equity)
        maxlong=max(maxlong,inv[4]);maxshort=max(maxshort,inv[5])
        maxgross=max(maxgross,inv[0]+inv[1]);maxnet=max(maxnet,abs(inv[2]))
        cycle_gross=max(cycle_gross,inv[0]+inv[1]);cycle_net=max(cycle_net,abs(inv[2]))
        if d!=0 and inv[0]+inv[1]<.5:
            if cc>=len(cycles):
                raise ValueError('組集計の上限を超えました')
            cycles[cc,:]=np.array([campaign,entry_row,i,realized-base,risk,a,cycle_gross,cycle_net,d,reason]);cc+=1
            ix=0 if campaign_side>0 else 1
            if realized-base<-.00000001:
                loss_streak[ix]+=1
                if par[33]>0 and loss_streak[ix]>=int(par[33]):
                    blocked[ix]=True;blocked_price[ix]=p;blocked_atr[ix]=a
            else:
                loss_streak[ix]=0
            d=0;last_exit=t;pending_action=0;pending_d=0;neutral_since=-1.
            position_owner=0;position_source_id=0;pending_owner=0;pending_source_id=0
        # 固定予算を割った時点から、返済だけを許し当該セッションの再開を禁止する。
        if np.isfinite(session_budget) and equity<=-session_budget+1e-8:
            session_halted=True;pending_d=0
        if detail:
            curve[i,:]=np.array([equity,realized,inv[4],inv[5],dd,cash,inv[2],campaign])
        # ----------------------------------------
        # 既存注文の約定後だけ現在要求を読む。保有中は所有者と価格出口を維持する。
        requested=int(request[i])
        changed_request=requested!=seen_request
        if changed_request:
            selection_count=selection_record(selection_events,selection_count,i,2,1,requested,applied,
                pending_owner,position_owner,position_source_id if position_owner else (source_override if source_override else applied),
                i,seen_request,requested,0,np.nan,0,campaign)
            seen_request=requested
        if d!=0:
            actual_source=position_source_id
            if changed_request and requested!=position_owner:
                selection_count=selection_record(selection_events,selection_count,i,2,11,requested,applied,
                    pending_owner,position_owner,actual_source,i,position_owner,requested,d,p,0,campaign)
        else:
            # 時間切れの注文は現在時刻では有効でないため、ID変更の取消待ちを作らない。
            if pending_d and t>=pending_until:
                selection_count=selection_record(selection_events,selection_count,i,2,10,requested,applied,
                    pending_owner,0,pending_source_id,i,pending_owner,0,pending_d,pending_level,pending_qty,campaign)
                pending_d=0;pending_owner=0;pending_source_id=0
            if requested!=applied:
                if pending_d:
                    cancel_wait=True;cancel_row=i;cancel_target=requested
                    selection_count=selection_record(selection_events,selection_count,i,2,2,requested,applied,
                        pending_owner,0,pending_source_id,i,applied,requested,pending_d,pending_level,pending_qty,campaign)
                else:
                    old_applied=applied;applied=requested
                    selection_count=selection_record(selection_events,selection_count,i,2,4,requested,applied,
                        0,0,source_override if source_override else applied,i,old_applied,applied,0,np.nan,0,campaign)
            actual_source=source_override if source_override else applied
        state[i]=states[i,actual_source-1]
        # ----------------------------------------
        # 現在行を観測して、次行以降だけで有効な注文条件を作る。
        stop_level=np.nan;main_level=np.nan;cover_level=np.nan;cover_open_level=np.nan
        add_level=np.nan;split_level=np.nan
        market_flags[:]=False
        if d!=0:
            e=equity-base;peak=max(peak,e);floor=-risk
            if par[13]>0 and peak>=risk:
                floor=max(floor,par[13]*peak)
            mfe=d*((max(extreme,p) if d>0 else min(extreme,p))-anchor)/a
            if par[21]>0 and mfe>=par[21]:
                floor=max(floor,effective_qty*par[22]*a)
            if par[23]>0 and t-entry_t>=par[23]*60 and mfe<par[24]:
                floor=max(floor,-effective_qty*par[25]*a)
            protected_floor=max(protected_floor,floor)
            floor=protected_floor
            if abs(inv[2])>.5:
                stop_level=rounded((floor+base-realized+inv[3])/inv[2],tick,-1 if inv[2]>0 else 1)
                stop_reason=11 if floor>=0 else 1
            extreme=max(extreme,p) if d>0 else min(extreme,p)
            if np.isfinite(par[3]) and d*(extreme-anchor)>=par[18]*a:
                width=par[3]
                if par[19]>0 and d*(extreme-anchor)>=par[19]*a:
                    width=min(width,par[20])
                if t>=us_open:
                    width*=par[30]
                planned_main=rounded(extreme-d*width*a,tick,-d)
                if not np.isfinite(main_floor) or d*(planned_main-main_floor)>0:
                    main_floor=planned_main
                main_level=main_floor
            if inv[1]>.5:
                cover_extreme=min(cover_extreme,p) if d>0 else max(cover_extreme,p)
                basis=0.
                for k in range(used):
                    if pos[k,2]>0 and pos[k,3]==1:
                        basis+=pos[k,1]*pos[k,2]
                basis/=inv[1]
                cover_level=basis+d*.75*a;cover_reason=4
                trail=cover_extreme+d*par[11]*a
                if -d*(basis-trail)<0:
                    # 買いカバーは平均建値より上、売りカバーは下の水準だけ利確と呼ぶ。
                    if d*(trail-cover_level)<0:
                        cover_level=trail;cover_reason=3
                cover_level=rounded(cover_level,tick,d)
                if int(par[9])>0 and inv[1]<cap:
                    cover_open_level=rounded(next_cover,tick,-d)
            elif par[7]>0 and inv[0]>.5:
                cover_open_level=rounded(extreme-d*par[8]*a,tick,-d)
            if int(par[4])>0 and inv[0]<cap and state[i]==d and e>0 and d*(p-anchor)>0:
                add_level=rounded(next_add if int(par[4])!=2 else anchor-d*par[5]*a,tick,d if int(par[4])!=2 else -d)
                if int(par[4])==2:
                    # 押し目追加の次水準も、直前の約定より一段先へ移す。
                    add_level=rounded(next_add,tick,-d)
            if not split_done and par[14]>0 and inv[0]>=2:
                split_level=rounded(anchor+d*par[14]*a,tick,d)
            if t>=end:
                pending_action=9;action_row=i
            elif session_halted:
                pending_action=14;action_row=i
            elif e<=floor-1e-8:
                pending_action=11 if floor>=0 else 1;action_row=i
            elif t-entry_t>=par[15]*60:
                pending_action=8;action_row=i
            elif context[i]==-d and par[29]>0:
                pending_action=13;action_row=i
            elif context[i]==-d and int(par[12])>0 and reversals<int(par[39]) and (int(par[12])==1 or d*(p-anchor)<=-.75*a):
                pending_action=5;action_row=i
            elif context[i]==d and inv[1]>.5 and -d*(p-cover_anchor)>0 and par[7]>0:
                # カバー方向の利益があり主方向が再確認されたときだけカバーを返済。
                pending_action=6;action_row=i
            if context[i]==0:
                if neutral_since<0:neutral_since=t
                if par[16]>0 and t<end and not session_halted and t-neutral_since>=par[16]*60:
                    pending_action=10;action_row=i
            else:neutral_since=-1.
            if int(par[17])==1 and t<end and not session_halted and t>=us_open-900 and t<us_open+1800:
                pending_action=12;action_row=i
            # 設置時点で既に通過した水準は、過去の指定価格で約定させない。
            # 条件成立済みの注文として、次の原本行の価格で執行する。
            planned=np.array([stop_level,main_level,cover_level,cover_open_level,add_level,split_level])
            sides=np.array([-1 if inv[2]>0 else 1,-d,d,-d,d if int(par[4])!=2 else -d,d])
            for z in range(6):
                market_flags[z]=np.isfinite(planned[z]) and sides[z]*(p-planned[z])>=-1e-8
        elif not cancel_wait:
            # 連敗後は同じ方向の小戻りを買い直さず、反対根拠か新値を待つ。
            for bx in range(2):
                bd=1 if bx==0 else -1
                if blocked[bx] and (state[i]==-bd or bd*(p-blocked_price[bx])>=par[34]*blocked_atr[bx]):
                    blocked[bx]=False;loss_streak[bx]=0
            if pending_d and (t>=pending_until or state[i]!=pending_d):
                selection_count=selection_record(selection_events,selection_count,i,2,10,requested,applied,
                    pending_owner,0,pending_source_id,i,pending_owner,0,pending_d,pending_level,pending_qty,campaign)
                pending_d=0;pending_owner=0;pending_source_id=0
            if pending_d and int(par[28])==1:
                pending_extreme=min(pending_extreme,p) if pending_d>0 else max(pending_extreme,p)
                changed=rounded(pending_extreme+pending_d*par[1]*pending_atr,tick,pending_d)
                if changed!=pending_level:
                    pending_level=changed;pending_row=i
                    selection_count=selection_record(selection_events,selection_count,i,2,6,requested,applied,
                        pending_owner,0,pending_source_id,i,pending_owner,pending_owner,pending_d,pending_level,pending_qty,campaign)
            paused=int(par[17]) in (1,2) and t>=us_open-900 and t<us_open+1800
            if not pending_d and not session_halted and t>=start+par[32]*60 and t<end-par[31]*60 and t>=last_exit+par[26]*60 and not paused:
                if state[i]!=0 and not blocked[0 if state[i]>0 else 1] and np.isfinite(atr[i]) and atr[i]>0:
                    pending_d=int(state[i]);pending_atr=max(atr[i],tick*2)
                    pending_level=rounded(p+pending_d*par[1]*pending_atr,tick,pending_d)
                    pending_until=t+par[27];pending_row=i;pending_extreme=p
                    pending_qty=int(par[0])
                    if par[36]>0:
                        per_contract_risk=np.ceil(pending_atr*par[2]/tick-1e-9)*tick*par[37]
                        pending_qty=min(cap,int(np.floor(par[36]/per_contract_risk)))
                    pending_market=int(par[28])==2 or pending_d*(p-pending_level)>=-1e-8
                    if pending_qty<1:
                        pending_d=0
                    elif not np.isfinite(session_budget) and par[35]>0:
                        session_budget=par[35]*pending_qty*par[2]*pending_atr
        if d==0 and pending_d and pending_owner==0:
            pending_owner=applied;pending_source_id=source_override if source_override else applied
            selection_count=selection_record(selection_events,selection_count,i,2,12 if reprepare_due_to_switch else 5,
                requested,applied,pending_owner,0,pending_source_id,pending_row,0,pending_owner,
                pending_d,pending_level,pending_qty,campaign)
            reprepare_due_to_switch=False
        selection_curve[i,:]=np.array([requested,applied,pending_owner,position_owner,actual_source,state[i],
            int(cancel_wait),cancel_row,pending_d,pending_row if pending_d else -1,pending_source_id,position_source_id,
            pending_level if pending_d else np.nan,last_exit+par[26]*60,pending_atr if pending_d else np.nan,
            pending_until if pending_d else np.nan,a if d else np.nan,stop_level,main_level,d])
    stats=np.array([realized,dd,maxlong,maxshort,maxgross,maxnet,max_error,min_equity,max_equity,
                    inv[0]+inv[1],reversals])
    return trades[:tc],cycles[:cc],curve,orders[:oc],stats,selection_events[:selection_count].copy(),selection_curve


def run(ready: dict, states: np.ndarray, request: np.ndarray, config: dict, detail: bool=False,
        source_override: int=0, observed_fill: bool=False) -> dict:
    """機能: 共通D273だけで手法選択を売買へ接続し、元台帳と所有者履歴を返す。

    引数: ready/config (dict)、states (ndarray[int8], n×2) はT/R方向、request (ndarray[int8], n) は1=T/2=R。
    detail (bool)、source_override (int) は0=選択に従う/1=T固定/2=R固定、observed_fill (bool) は全価格約定を現観測値に置換。
    返り値: trades/cycles/curve/orders/statsとselection_events/selection_curveを持つ辞書 (dict)。
    selection_curveはdetailに関わらず全行。旧5結果の列と単位は変更しない。
    所有IDと実入口源は別列。固定requestかつspecifiedなら対応する旧D273と同じ売買を再現する。
    """
    n=len(ready['last'])
    if n<1 or not isinstance(states,np.ndarray) or states.dtype!=np.int8 or states.shape!=(n,2):
        raise ValueError('T/R方向は原本行数×2のndarray[int8]で指定してください')
    if not np.isin(states,(-1,0,1)).all():
        raise ValueError('T/R方向は-1/0/1に限ります')
    if not isinstance(request,np.ndarray) or request.dtype!=np.int8 or request.shape!=(n,) or not np.isin(request,(1,2)).all():
        raise ValueError('要求IDは原本行数のndarray[int8]、1=T/2=Rで指定してください')
    if type(source_override) is not int or source_override not in (0,1,2):
        raise ValueError('入口源の上書きは整数0/1/2に限ります')
    if not isinstance(observed_fill,(bool,np.bool_)):
        raise ValueError('観測約定の指定は真偽値に限ります')
    cap=config['audit_cap']
    if cap not in (10,20) or config['initial_qty']!=cap//2:
        raise ValueError('D273はTOPIX上限10/初回5、NK上限20/初回10に限定します')
    required={'entry_atr':.25,'stop_atr':1.,'main_trail':3.,'split_target':2.,
              'activation_atr':1.5,'timeout_min':360.,'cooldown_min':5.,'ttl_seconds':300.,
              'entry_mode':1,'entry_cutoff_min':5.,'warmup_min':20.,'after_open_factor':1.}
    disabled=('add_mode','add_qty','hedge_ratio','cover_add','reverse_mode','lock_fraction','neutral_min','us_mode',
              'tighten_atr','breakeven_atr','failure_min','signal_exit','max_same_losses','session_budget_r','risk_yen','session_budget_yen')
    if any(config.get(k)!=v for k,v in required.items()) or any(config.get(k)!=0 for k in disabled):
        raise ValueError('この注文器は選択以外を変えない共通D273設定に限定します')
    par=np.array([config[k] for k in PARAMS],dtype=float)
    values=simulate(ready['time_s'],ready['last'],ready['atr'],states,request,ready['tick'],
                    ready['start'],ready['limit'],ready['us_open'],par,detail,cap,source_override,observed_fill)
    return dict(zip(['trades','cycles','curve','orders','stats','selection_events','selection_curve'],values))
