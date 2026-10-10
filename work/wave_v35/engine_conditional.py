"""固定A0候補を毎行維持し、現在ATRによる追跡短縮だけを因果条件で追加する。"""

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


ATR_COLUMNS = ['direction', 'initial_atr', 'current_atr', 'used_width_atr', 'extreme',
               'trail_active', 'trail_level', 'initial_risk', 'stop_level', 'pending_initial_atr',
               'current_atr_source_row', 'trail_source_row']


PREPARE_COLUMNS = ['prepare_id', 'row', 'side', 'level', 'initial_atr', 'expiry_time', 'qty']
ENTRY_PREPARATION_COLUMNS = ['campaign', 'fill_row', 'prepare_id', 'prepare_row']

CONDITIONAL_COLUMNS = ['direction', 'deterioration_direction', 'deterioration_source_row',
    'shortening_enabled', 'initial_atr', 'current_atr', 'used_width_atr', 'prior_level',
    'fixed_candidate', 'short_candidate', 'selected_candidate', 'final_level', 'advanced',
    'advance_kind', 'current_atr_source_row', 'line_source_row', 'line_evidence_row',
    'line_evidence_source_row']
TRAIL_EVENT_COLUMNS = ['row', 'campaign', 'direction', 'prior_level', 'fixed_candidate',
    'short_candidate', 'final_level', 'advance_kind', 'initial_atr', 'current_atr',
    'used_width_atr', 'current_atr_source_row', 'evidence_row', 'evidence_source_row',
    'evidence_direction']
ADVANCE_KINDS = {1: '固定A0候補', 2: '常時最小幅の追加短縮', 3: '悪化根拠による追加短縮'}


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
def simulate(time, price, atr, trail_atr, state, context, tick, start, end, us_open, par, detail, cap, width_mode, observed_fill, prepare_allow, deterioration, deterioration_source):
    """機能: 前行までの条件だけを次行以降で約定させ、全玉の時価を追跡する。

    引数: time/price/atr/trail_atr/state/context/par/prepare_allow/deterioration/deterioration_source (ndarray)、tick/start/end/us_open (float)、detail/observed_fill (bool)、cap/width_mode (int)。
    返り値: 旧8結果と条件詳細・追跡進行イベント (tuple[ndarray,...])。
    指定価格約定。主玉・カバー合計で買い指定上限枚数、売り指定上限枚数まで。
    """
    n=len(price);pos=np.zeros((12000,5));trades=np.zeros((24000,11))
    # 新設は一行に最大一件。追跡更新でこのID・行は変更しない。
    prepare_events=np.zeros((n,7));prepare_count=0
    entry_preparations=np.zeros((2000,4));entry_prepare_count=0
    pending_prepare_id=-1;pending_prepare_row=-1
    atr_curve=np.full((n,12),np.nan) if detail else np.full((1,12),np.nan)
    current_atr=1.;current_atr_source=-1;trail_source=-1
    conditional_curve=np.full((n,18),np.nan) if detail else np.full((1,18),np.nan)
    trail_events=np.zeros((n,15));trail_event_count=0
    line_evidence_row=-1;line_evidence_source=-1
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
        prior_main=main_floor if d else np.nan
        fixed_candidate=np.nan;short_candidate=np.nan;planned_main=np.nan
        advanced=0;advance_kind=0
        shortening=(d!=0 and (width_mode==1 or (width_mode==2 and deterioration[i]==-d)))
        # ----------------------------------------
        # ATRの公開値を保有中だけ保持する。価格欠測でも既存線の約定や更新は行わない。
        if d!=0 and np.isfinite(trail_atr[i]) and trail_atr[i]>0:
            current_atr=max(trail_atr[i],tick*2);current_atr_source=i
        if not np.isfinite(p) or p<=0:
            if detail:
                atr_curve[i,:]=np.array([d,a if d else np.nan,current_atr if d else np.nan,
                    (min(a,current_atr) if (width_mode==1 or (width_mode==2 and deterioration[i]==-d)) else a) if d else np.nan,extreme if d else np.nan,
                    int(d!=0 and np.isfinite(main_level)),main_level,risk if d else np.nan,stop_level,
                    pending_atr if pending_d else np.nan,current_atr_source if d else -1,trail_source if d else -1])
                conditional_curve[i,:]=np.array([d,deterioration[i],deterioration_source[i],int(shortening),
                    a if d else np.nan,current_atr if d else np.nan,
                    (min(a,current_atr) if shortening else a) if d else np.nan,
                    prior_main,np.nan,np.nan,np.nan,main_floor if d else np.nan,0,0,
                    current_atr_source if d else -1,trail_source if d else -1,
                    line_evidence_row if d else -1,line_evidence_source if d else -1])
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
            current_atr=a;current_atr_source=-1;trail_source=-1
            line_evidence_row=-1;line_evidence_source=-1
            entry_row=i;entry_t=t;cycle_gross=0.;cycle_net=0.;split_done=False
            fill=anchor;open_side=d;open_qty=effective_qty;open_role=0;reason=20
            order_source=pending_row
            if entry_prepare_count>=len(entry_preparations):
                raise ValueError('約定元準備の記録上限を超えました')
            entry_preparations[entry_prepare_count,:]=np.array([campaign,i,pending_prepare_id,pending_prepare_row])
            entry_prepare_count+=1
            pending_d=0;next_add=anchor+d*par[5]*a*(-1 if int(par[4])==2 else 1)
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
        # 固定予算を割った時点から、返済だけを許し当該セッションの再開を禁止する。
        if np.isfinite(session_budget) and equity<=-session_budget+1e-8:
            session_halted=True;pending_d=0
        if detail:
            curve[i,:]=np.array([equity,realized,inv[4],inv[5],dd,cash,inv[2],campaign])
        # ----------------------------------------
        # 現在行を観測して、次行以降だけで有効な注文条件を作る。
        stop_level=np.nan;main_level=np.nan;cover_level=np.nan;cover_open_level=np.nan
        add_level=np.nan;split_level=np.nan
        market_flags[:]=False
        if d!=0:
            # 当該行の新規約定ではA0から開始し、公開済みの当該行Atがあれば置き換える。
            # Atは追跡幅だけに使用し、リスク・始動・部分返済等のaを上書きしない。
            if np.isfinite(trail_atr[i]) and trail_atr[i]>0:
                current_atr=max(trail_atr[i],tick*2);current_atr_source=i
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
                shortening=(width_mode==1 or (width_mode==2 and deterioration[i]==-d))
                width_atr=min(a,current_atr) if shortening else a
                # 条件が偽でも固定候補は必ず更新する。既設の短縮線も緩めない。
                fixed_candidate=rounded(extreme-d*width*a,tick,-d)
                planned_main=fixed_candidate;candidate_kind=1
                if shortening:
                    short_candidate=rounded(extreme-d*width*width_atr,tick,-d)
                    if d*(short_candidate-fixed_candidate)>0:
                        planned_main=short_candidate;candidate_kind=2 if width_mode==1 else 3
                if not np.isfinite(main_floor) or d*(planned_main-main_floor)>0:
                    prior_main=main_floor;main_floor=planned_main;trail_source=i
                    advanced=1;advance_kind=candidate_kind
                    line_evidence_row=i if candidate_kind==3 else -1
                    line_evidence_source=int(deterioration_source[i]) if candidate_kind==3 else -1
                    trail_events[trail_event_count,:]=np.array([i,campaign,d,prior_main,fixed_candidate,
                        short_candidate,main_floor,candidate_kind,a,current_atr,width_atr,current_atr_source,
                        line_evidence_row,line_evidence_source,int(deterioration[i]) if candidate_kind==3 else 0])
                    trail_event_count+=1
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
        else:
            # 連敗後は同じ方向の小戻りを買い直さず、反対根拠か新値を待つ。
            for bx in range(2):
                bd=1 if bx==0 else -1
                if blocked[bx] and (state[i]==-bd or bd*(p-blocked_price[bx])>=par[34]*blocked_atr[bx]):
                    blocked[bx]=False;loss_streak[bx]=0
            if pending_d and (t>=pending_until or state[i]!=pending_d):pending_d=0
            if pending_d and int(par[28])==1:
                pending_extreme=min(pending_extreme,p) if pending_d>0 else max(pending_extreme,p)
                changed=rounded(pending_extreme+pending_d*par[1]*pending_atr,tick,pending_d)
                if changed!=pending_level:
                    pending_level=changed;pending_row=i
            paused=int(par[17]) in (1,2) and t>=us_open-900 and t<us_open+1800
            # 許可は新しい準備にだけ必要。既設注文の更新・取消・約定へは作用しない。
            if prepare_allow[i] and not pending_d and not session_halted and t>=start+par[32]*60 and t<end-par[31]*60 and t>=last_exit+par[26]*60 and not paused:
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
                    if pending_d:
                        pending_prepare_id=prepare_count;pending_prepare_row=i
                        prepare_events[prepare_count,:]=np.array([prepare_count,i,pending_d,pending_level,pending_atr,pending_until,pending_qty])
                        prepare_count+=1
        if detail:
            atr_curve[i,:]=np.array([d,a if d else np.nan,current_atr if d else np.nan,
                (min(a,current_atr) if (width_mode==1 or (width_mode==2 and deterioration[i]==-d)) else a) if d else np.nan,extreme if d else np.nan,
                int(d!=0 and np.isfinite(main_level)),main_level,risk if d else np.nan,stop_level,
                pending_atr if pending_d else np.nan,current_atr_source if d else -1,trail_source if d else -1])
            shortening=(d!=0 and (width_mode==1 or (width_mode==2 and deterioration[i]==-d)))
            conditional_curve[i,:]=np.array([d,deterioration[i],deterioration_source[i],int(shortening),
                a if d else np.nan,current_atr if d else np.nan,
                (min(a,current_atr) if shortening else a) if d else np.nan,
                prior_main,fixed_candidate,short_candidate,planned_main,main_floor if d else np.nan,
                advanced,advance_kind,current_atr_source if d else -1,trail_source if d else -1,
                line_evidence_row if d else -1,line_evidence_source if d else -1])
    stats=np.array([realized,dd,maxlong,maxshort,maxgross,maxnet,max_error,min_equity,max_equity,
                    inv[0]+inv[1],reversals])
    return trades[:tc],cycles[:cc],curve,orders[:oc],stats,atr_curve,prepare_events[:prepare_count],entry_preparations[:entry_prepare_count],conditional_curve,trail_events[:trail_event_count]


def run(ready: dict, state: np.ndarray, config: dict, detail: bool=False,
        context: np.ndarray | None=None, width_mode: int=0, observed_fill: bool=False,
        trail_atr: np.ndarray | None=None, prepare_allow: np.ndarray | None=None,
        deterioration: np.ndarray | None=None, deterioration_source: np.ndarray | None=None) -> dict:
    """機能: 共通D273の固定追跡へ、常時又は悪化確認時だけ最小ATR幅を追加する。

    引数: ready/config (dict)、state/context (ndarray[int8]|None)、detail/observed_fill (bool)。
    width_mode (int) は0固定A0、1常時min(A0,At)、2悪化方向が保有方向の逆の時だけmin。
    trail_atr (一次元浮動小数ndarray|None) は公開済みAt。Noneはready['atr']。
    prepare_allow (一次元ndarray[bool]|None) は新規準備だけの許可。Noneは全行。
    deterioration (一次元ndarray[int8]|None) は悪化を認めた価格方向。Noneは全中立。
    deterioration_source (一次元ndarray[int64]|None) は悪化根拠の参照原本行。
    非中立では0以上かつ当該行以下。Noneは当該行を記録し、外部特徴の因果性は呼出側が保証する。
    返り値: 旧8結果、conditional_curveとtrail_events (dict[str,ndarray])。
    旧8結果の列・単位は不変。追加詳細曲線はdetail=Falseで一行に省略、進行イベントは常に保存。
    初期A0・予算・1.5A0始動・2A0部分返済・全返済後5分等は従来D273に固定。
    Atは初回A0、有限正値だけ2呼値以上で採用し、欠測は直前値を維持する。
    固定3A0候補は毎有効保有行で更新し、条件は追加短縮だけを許可する。既設線を緩めない。
    現行の既設注文を先に執行した後で線を更新し、新線は次原本行から有効。
    observed_fill=Trueは新規・部分・全返済をすべて現在観測価格にする。
    影は別のmode0通常運転でAtと悪化条件に依存せず、そのfresh準備行を許可列とする。
    """
    n=len(ready['last'])
    if deterioration is None:
        deterioration=np.zeros(n,dtype=np.int8)
    elif not isinstance(deterioration,np.ndarray) or deterioration.dtype!=np.int8 or deterioration.ndim!=1 or len(deterioration)!=n or not np.isin(deterioration,(-1,0,1)).all():
        raise ValueError('悪化方向は原本行対応の一次元ndarray[int8]、-1/0/1に限ります')
    if deterioration_source is None:
        deterioration_source=np.where(deterioration!=0,np.arange(n),-1).astype(np.int64)
    elif not isinstance(deterioration_source,np.ndarray) or deterioration_source.dtype!=np.int64 or deterioration_source.ndim!=1 or len(deterioration_source)!=n:
        raise ValueError('悪化根拠行は原本行対応の一次元ndarray[int64]に限ります')
    if np.any(deterioration_source>np.arange(n)) or np.any(deterioration_source < -1) or np.any((deterioration!=0)&(deterioration_source<0)):
        raise ValueError('悪化根拠に未来行又は非中立の不明行は指定できません')
    if prepare_allow is None:
        prepare_allow=np.ones(n,dtype=np.bool_)
    elif not isinstance(prepare_allow,np.ndarray) or prepare_allow.dtype!=np.bool_ or prepare_allow.ndim!=1 or len(prepare_allow)!=n:
        raise ValueError('新規準備許可は原本行対応の一次元ndarray[bool]に限ります')
    if n<1 or not isinstance(state,np.ndarray) or state.ndim!=1 or len(state)!=n or not np.isin(state,(-1,0,1)).all():
        raise ValueError('入口は原本行対応の一次元-1/0/1配列に限ります')
    if type(width_mode) is not int or width_mode not in (0,1,2):
        raise ValueError('追跡幅方式は整数0=固定A0/1=常時最小/2=悪化時最小に限ります')
    if not isinstance(observed_fill,(bool,np.bool_)):
        raise ValueError('観測約定は真偽値で指定してください')
    if trail_atr is None:
        trail_atr=ready['atr']
    if not isinstance(trail_atr,np.ndarray) or trail_atr.ndim!=1 or len(trail_atr)!=n or not np.issubdtype(trail_atr.dtype,np.floating):
        raise ValueError('追跡ATRは原本行対応の一次元浮動小数配列に限ります')
    if context is None:
        context=state
    elif not isinstance(context,np.ndarray) or context.dtype!=np.int8 or context.ndim!=1 or len(context)!=n or not np.isin(context,(-1,0,1)).all():
        raise ValueError('保有管理方向は原本行対応のndarray[int8]、-1/0/1に限ります')
    cap=config['audit_cap']
    if cap not in (10,20) or config['initial_qty']!=cap//2:
        raise ValueError('D273はTOPIX上限10/初回5、NK上限20/初回10に限ります')
    required={'entry_atr':.25,'stop_atr':1.,'main_trail':3.,'split_target':2.,
              'activation_atr':1.5,'timeout_min':360.,'cooldown_min':5.,'ttl_seconds':300.,
              'entry_mode':1,'entry_cutoff_min':5.,'warmup_min':20.,'after_open_factor':1.}
    disabled=('add_mode','add_qty','hedge_ratio','cover_add','reverse_mode','lock_fraction','neutral_min','us_mode',
              'tighten_atr','breakeven_atr','failure_min','signal_exit','max_same_losses','session_budget_r','risk_yen','session_budget_yen')
    if any(config.get(k)!=v for k,v in required.items()) or any(config.get(k)!=0 for k in disabled):
        raise ValueError('追跡ATR以外は共通D273から変更できません')
    par=np.array([config[k] for k in PARAMS],dtype=float)
    values=simulate(ready['time_s'],ready['last'],ready['atr'],trail_atr,state,context,ready['tick'],
                    ready['start'],ready['limit'],ready['us_open'],par,detail,cap,width_mode,observed_fill,prepare_allow,deterioration,deterioration_source)
    return dict(zip(['trades','cycles','curve','orders','stats','atr_curve','prepare_events','entry_preparations','conditional_curve','trail_events'],values))
