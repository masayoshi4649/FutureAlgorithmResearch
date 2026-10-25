"""中期支持の判断層を使い、短期往復による返済と再参加を分離して検証する。"""

import numpy as np
from numba import njit
import regime_selector142 as selectors


TRACE_COLUMNS=('判断原行','種類','保有又は候補方向','状態又は行動','理由','親ID','枚数','固定R','元建値から利益R')
TRACE_KINDS={1:'新規判断',2:'途中判断の状態変更',3:'追撃判断',4:'返済判断'}


def configurations():
    """
    機能: 三つの状態参加・回復政策と標準/広めの保険幅を比較前に固定する。
    引数: なし。
    返り値: list[dict]はR01～R06。奇数は標準、偶数は広め。初回2枚、追撃なし。
    """
    names=('中期の支持状態を維持','支持状態内の押し再進行で参加','同方向失敗後は新しい押し再進行を待つ')
    result=[]
    for policy,name in enumerate(names,1):
        for wide in (False,True):
            result.append(dict(id=f'R{len(result)+1:02d}',name=name+('・広め' if wide else '・標準'),
                policy=policy,maximum=5,stop=1.5 if wide else 1.,activation=2. if wide else 1.25,
                trail=1.5 if wide else .75,exit_hold=10.,cooldown=30.,entry_cutoff=60.,
                inactive_exit=True,inactive_hold=300.,quiet_seconds=0.,spread_r=.25,
                add_step=.5,add_interval=30.,gap_seconds=15.))
    return result


@njit(cache=True)
def _record(out,count,row,source,parent,side,quantity,price,reason,new,uid,fee):
    """
    機能: 注文別手数料を付けて十列約定へ記録する。
    引数: out(ndarray)、整数識別子・枚数(int)、price(float)は出力と約定情報。
    返り値: intは更新した行数。
    """
    assert count<len(out) and row>source and quantity>0
    out[count]=np.array([row,source,parent,side,quantity,price,reason,new,uid,quantity*fee//10])
    return count+1


@njit(cache=True)
def _trace(trace,count,row,kind,side,state,reason,parent,quantity,risk,gain):
    """
    機能: 判断を原行番号・方向・理由・保有状態とともに記録する。
    引数: trace(ndarray)、count等(int)、risk/gain(float)は履歴と判断状態。
    返り値: intは更新した行数。
    """
    assert count<len(trace)
    trace[count]=np.array([row,kind,side,state,reason,parent,quantity,risk,gain])
    return count+1


@njit(cache=True)
def simulate(times,bid,ask,good,a,start,end,us_open,multiplier,fee,p):
    """
    機能: 判断層の候補を確認し、次正常板で新規・追撃・返済・反転再参加する。
    引数: times/bid/ask/good/a/p(ndarray)、start/end/us_open/multiplier(float)、fee(int)は原行・特徴・設定。
    返り値: tuple[ndarray,ndarray,ndarray]は十列注文・清算時価・判断記録。場末未返済はエラー。

    建値とRは発注判断・実約定から固定する。既発注を後続の値動きで取り消した扱いにしない。
    全返済の後でだけ逆方向を予約し、返済と新規を同じ原行で約定させない。
    """
    policy,maximum,stop,activation,trail,exit_hold,cooldown,entry_cutoff,inactive_exit,inactive_hold,quiet_seconds,spread_r,add_step,add_interval,gap_seconds=p
    policy,maximum=int(policy),int(maximum)
    n=len(times);orders=np.zeros((max(1024,2*n+16),10));trace=np.zeros((max(1024,2*n+16),9));equity=np.zeros(n)
    held=np.zeros(5,np.int64);entries=np.zeros(5)
    oc=tc=0;parent=-1;side=0;uid=0;regime=0
    cash=0.;base=0.;risk=0.;best=0.;floor=0.;initial_risk=0.
    pending=0;source=-1;pending_side=0;pending_risk=0.;pending_qty=0;pending_regime=0;pending_reason=0;pending_reversal=False
    next_ready=start;signal_side=0;signal_regime=0;signal_since=-np.inf;reverse_ready_side=0
    locked_side=0;prior_campaign_cash=0.;setup_side=0;setup_stage=0;setup_peak=0.;setup_trough=0.;setup_risk=0.
    exit_action=0;exit_since=-np.inf;inactive_since=-np.inf;last_add=-np.inf
    last_mark=np.nan;last_management=-1;last_why=-1
    for i in range(n):
        t=times[i]
        valid=good[i] and np.isfinite(bid[i]) and np.isfinite(ask[i]) and 0.<bid[i]<ask[i]
        terminal=t>=end
        quiet=np.isfinite(us_open) and quiet_seconds>0. and us_open-quiet_seconds<=t<us_open+quiet_seconds
        if i>0 and t-times[i-1]>gap_seconds:
            signal_since=exit_since=inactive_since=-np.inf
            setup_side=setup_stage=0
        # ----------------------------------------
        # 新しい判断に先立ち、過去に発注済みの注文を次正常原行で約定する。
        if pending and valid and i>source:
            price=ask[i] if pending_side>0 else bid[i]
            if pending in (1,3):
                if pending==1:
                    parent+=1;side=pending_side;regime=pending_regime;risk=pending_risk
                    prior_campaign_cash=cash
                    base=price;best=0.;floor=-stop*risk;uid=0;initial_risk=pending_qty*stop*risk
                    exit_action=0;exit_since=inactive_since=-np.inf;last_management=last_why=-1
                else:uid+=1
                held[uid]=pending_qty;entries[uid]=price
                cash-=side*pending_qty*price*multiplier+pending_qty*fee//10
                oc=_record(orders,oc,i,source,parent,side,pending_qty,price,pending_reason,1,uid,fee)
                last_add=t
            else:
                for u in range(5):
                    if held[u]:
                        q=held[u];cash+=side*q*price*multiplier-q*fee//10
                        oc=_record(orders,oc,i,source,parent,-side,q,price,pending_reason,0,u,fee)
                        held[u]=0
                locked_side=side if cash-prior_campaign_cash<0. else 0
                setup_side=setup_stage=0
                next_ready=t+cooldown
                reverse_ready_side=-side if pending_reversal else 0
                if not pending_reversal:
                    signal_side=0;signal_since=-np.inf
                exit_since=inactive_since=-np.inf
            pending=0
        total=int(held.sum())
        if valid and total:last_mark=bid[i] if side>0 else ask[i]
        candidate=0;state=0;why=10;confirmation=5.
        if valid and not total and not pending and start<=t<end-entry_cutoff and not quiet:
            candidate,state,why,confirmation,setup_side,setup_stage,setup_peak,setup_trough,setup_risk=selectors.entry_step(
                a[i],policy,locked_side,setup_side,setup_stage,setup_peak,setup_trough,setup_risk)
            if candidate and ask[i]-bid[i]>spread_r*a[i,9]:candidate=0
        elif not valid or quiet or terminal:
            setup_side=setup_stage=0
        if candidate:
            if candidate!=signal_side or state!=signal_regime or not np.isfinite(signal_since):
                signal_side,signal_regime,signal_since=candidate,state,t
        else:
            signal_side=0;signal_since=-np.inf
        if not valid:
            exit_since=inactive_since=-np.inf;exit_action=0
        # ----------------------------------------
        # 保険停止・利益追尾・場末を優先し、その後だけ判断層の返済資格を確認する。
        if total and not pending:
            close_reason=0;reverse=False;gain=side*(last_mark-base) if np.isfinite(last_mark) else 0.
            if terminal or quiet:close_reason=93 if terminal else 94
            elif valid:
                best=max(best,gain)
                if best>=activation*risk:floor=max(floor,best-trail*risk)
                if gain<=floor:close_reason=70 if floor>0. else 32
                action,manage_reason=selectors.management(a[i],side,policy,regime)
                if action!=last_management or manage_reason!=last_why:
                    tc=_trace(trace,tc,i,2,side,action,manage_reason,parent,total,risk,gain/risk)
                    last_management,last_why=action,manage_reason
                if action==3 and inactive_exit:
                    if not np.isfinite(inactive_since):inactive_since=t
                    if t-inactive_since>=inactive_hold and not close_reason:close_reason=1470
                else:inactive_since=-np.inf
                if action in (1,2):
                    if action!=exit_action or not np.isfinite(exit_since):exit_action,exit_since=action,t
                    if t-exit_since>=exit_hold and not close_reason:
                        close_reason=1450+policy;reverse=action==2
                else:exit_action=0;exit_since=-np.inf
            if close_reason:
                pending,source,pending_side,pending_reason,pending_reversal=2,i,-side,close_reason,reverse
                tc=_trace(trace,tc,i,4,side,2,close_reason,parent,total,risk,gain/risk)
        # ----------------------------------------
        # 追撃は利益保護後、初回に負った損失予算と最大5枚の両方を守る。
        if total and valid and not pending and total<maximum and uid<4 and t<end-entry_cutoff and not quiet:
            gain=side*(last_mark-base)
            if t-last_add>=add_interval and gain>=add_step*(uid+1)*risk and selectors.allow_add(a[i],side,policy,floor):
                px=ask[i] if side>0 else bid[i];stop_price=base+side*floor
                exposed=0.
                for u in range(5):exposed+=held[u]*max(0.,side*(entries[u]-stop_price))
                new_risk=max(a[i,34],side*(px-stop_price))
                if exposed+new_risk<=initial_risk and ask[i]-bid[i]<=spread_r*risk:
                    pending,source,pending_side,pending_qty,pending_reason=3,i,side,1,1449
                    tc=_trace(trace,tc,i,3,side,regime,1449,parent,1,risk,gain/risk)
        if not total and not pending and candidate and (t>=next_ready or candidate==reverse_ready_side) and t-signal_since>=confirmation:
            qty=min(maximum,selectors.initial_quantity(policy,state))
            pending,source,pending_side,pending_risk,pending_qty,pending_regime,pending_reason=1,i,candidate,a[i,9],qty,state,1440+policy
            tc=_trace(trace,tc,i,1,candidate,state,why,parent+1,qty,a[i,9],0.)
            signal_side=0;signal_since=-np.inf;reverse_ready_side=0
            setup_side=setup_stage=0
        total=int(held.sum())
        equity[i]=cash+side*total*last_mark*multiplier-total*fee/10. if total else cash
        assert 0<=total<=maximum<=5
    assert int(held.sum())==0 and pending==0,'場末の返済原行が不足'
    return orders[:oc],equity,trace[:tc]


def replay(data,config):
    """
    機能: 48列特徴と商品仕様を、完結損失と押し準備状態を持つ売買層へ渡す。
    引数: data(dict)はready/quotes/features、config(dict)は固定政策。
    返り値: tuple[ndarray,ndarray,ndarray]は注文・清算時価・判断記録。
    """
    r,q,c=data['ready'],data['quotes'],config
    assert data['features'].shape[1]>=48 and 1<=c['policy']<=3 and 1<=c['maximum']<=5
    keys=('policy','maximum','stop','activation','trail','exit_hold','cooldown','entry_cutoff','inactive_exit',
          'inactive_hold','quiet_seconds','spread_r','add_step','add_interval','gap_seconds')
    p=np.array([c[k] for k in keys],dtype=float)
    fee,multiplier=(385,100.) if r['symbol']=='NK225' else (418,1000.)
    us_open=np.nan if r['session'].endswith('_Day') else r['us_open']
    return simulate(r['time_s'],q['bid'],q['ask'],q['quote_valid'],data['features'],r['start'],r['limit'],
                    us_open,multiplier,fee,p)
