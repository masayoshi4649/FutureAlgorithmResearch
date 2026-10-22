"""入口信号と保有中の主方向を分離し、原本行順・次行執行で再生する建玉管理器。"""

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
def simulate(time, price, atr, state, context, tick, start, end, us_open, par, detail, cap):
    """機能: 前行までの条件だけを次行以降で約定させ、全玉の時価を追跡する。

    引数: time/price/atr/state/context/par (ndarray)、tick/start/end/us_open (float)、detail (bool)、cap (int)。
    返り値: 返済台帳、組集計、資産曲線、注文台帳、検算値 (tuple[ndarray,...])。
    指定価格約定。主玉・カバー合計で買い指定上限枚数、売り指定上限枚数まで。
    """
    n=len(price);pos=np.zeros((12000,5));trades=np.zeros((24000,11))
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
        if not np.isfinite(p) or p<=0:
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
                fill=level
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
            base=realized;peak=0.;anchor=p if pending_market else pending_level;extreme=anchor
            protected_floor=-risk;main_floor=np.nan
            entry_row=i;entry_t=t;cycle_gross=0.;cycle_net=0.;split_done=False
            fill=anchor;open_side=d;open_qty=effective_qty;open_role=0;reason=20
            order_source=pending_row;pending_d=0;next_add=anchor+d*par[5]*a*(-1 if int(par[4])==2 else 1)
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
    stats=np.array([realized,dd,maxlong,maxshort,maxgross,maxnet,max_error,min_equity,max_equity,
                    inv[0]+inv[1],reversals])
    return trades[:tc],cycles[:cc],curve,orders[:oc],stats


def run(ready: dict, state: np.ndarray, config: dict, detail: bool=False, context: np.ndarray | None=None) -> dict:
    """機能: 日本語表示用の設定を固定数値へ変換し、片方向指定上限枚数で再生する。

    引数: ready/config (dict)、state (ndarray) は入口方向、detail (bool)、context (ndarray[int8]|None) は保有中の主方向。
    返り値: 台帳等 (dict)。context 未指定なら従来と同じ state を使用する。
    context は反対方向返済・反転・カバー利益返済・中立タイマーにだけ使用する。
    新規、未約定取消、増玉、連敗後の再開には state を使い続ける。
    新規はフラット時の通常新規を指す。反転に伴うカバー昇格と補充は保有管理の一部であり、
    context で成立した反転の次行に従来どおり実行し、補充だけの入口条件は追加しない。
    """
    if len(state)!=len(ready['last']):
        raise ValueError('方向信号と原本行の長さが一致しません')
    if np.any((state < -1) | (state > 1)):
        raise ValueError('方向信号は -1、0、1 に限ります')
    if config['initial_qty']<1 or config['initial_qty']>config['audit_cap']:
        raise ValueError('初期枚数が片方向上限の範囲外です')
    # ----------------------------------------
    # 指定時だけ管理方向を厳密に検査し、未指定の呼出しは旧エンジンと同じ入力を使う。
    if context is None:
        context=state
    elif not isinstance(context,np.ndarray) or context.dtype!=np.int8 or context.ndim!=1:
        raise ValueError('保有管理方向は一次元 ndarray[int8] で指定してください')
    elif len(context)!=len(ready['last']):
        raise ValueError('保有管理方向と原本行の長さが一致しません')
    elif not np.isin(context,(-1,0,1)).all():
        raise ValueError('保有管理方向は -1、0、1 に限ります')
    par=np.array([config[k] for k in PARAMS],dtype=float)
    values=simulate(ready['time_s'],ready['last'],ready['atr'],state,context,ready['tick'],
                    ready['start'],ready['limit'],ready['us_open'],par,detail,config['audit_cap'])
    return dict(zip(['trades','cycles','curve','orders','stats'],values))
