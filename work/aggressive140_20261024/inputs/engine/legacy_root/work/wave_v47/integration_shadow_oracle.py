"""D273の公開計画と成熟注文を、売買実装を呼ばず入力・過去約定から検算する。"""

from __future__ import annotations

import numpy as np
from numba import njit
import adaptive_shadow_oracle as baseline_oracle


@njit(cache=True)
def _tick(value, step, side):
    """機能: 指定方向へ呼値を丸める独立式。

    引数: value/step(float)、side(int)。返り値: 価格(float)。
    """
    units=value/step
    return step*(np.ceil(units-1e-9) if side>0 else np.floor(units+1e-9))


@njit(cache=True)
def publication(time,price,atr,state,cash,realized,net,open_price,open_side,prepared_id,split,
                tick,start,limit,q0,tighten_atr,tight_width,prepare_allow):
    """機能: 過去約定の後状態と入力からD273の全行公開計画を独立に作る。

    引数: 時系列・会計・約定情報(ndarray)、tick/start/limit(float)、q0(int)。
    返り値: 独立37列計画と独立新規準備7列(tuple[ndarray,ndarray])。
    現行売買コード・その計画列を計算元にしない。当行約定の妥当性は別の前状態検査で確認する。
    """
    n=len(price);out=np.full((n,37),np.nan);preparations=np.zeros((n,7));count=0
    campaign=-1;a=1.;anchor=0.;risk=1.;entry=0;entry_time=0.;base=0.;extreme=0.
    split_done=False;last_exit=-1e20;main_floor=np.nan;trail_source=-1
    current_atr=1.;atr_source=-1
    pd=0;level=0.;expiry=0.;pa=0.;pending_source=-1;prepare_id=-1;prepare_row=-1;pending_extreme=0.;market=False
    action=0;action_source=-1
    for i in range(n):
        p=price[i];t=time[i];prior_side=0 if i==0 else int(np.sign(net[i-1]));d=int(np.sign(net[i]))
        if prior_side and np.isfinite(atr[i]) and atr[i]>0:
            current_atr=max(2*tick,atr[i]);atr_source=i
        if open_side[i]:
            pid=int(prepared_id[i])
            if pid<0 or pid>=count:raise AssertionError('新規が過去の独立準備へ対応しません')
            if preparations[pid,2]!=open_side[i]:raise AssertionError('新規の準備方向が違います')
            campaign+=1;a=preparations[pid,4];anchor=open_price[i];risk=q0*a;base=realized[i]
            entry=i;entry_time=t;extreme=anchor;split_done=False;main_floor=np.nan;trail_source=-1
            current_atr=a;atr_source=-1;pd=0
        if split[i]:split_done=True
        if prior_side and not d:
            last_exit=t;action=0;pd=0
        stop=np.nan;trail=np.nan;target=np.nan;sm=False;tm=False;pm=False
        if d:
            if np.isfinite(atr[i]) and atr[i]>0:current_atr=max(2*tick,atr[i]);atr_source=i
            basis=realized[i]-cash[i]
            stop=_tick((-risk+base-realized[i]+basis)/net[i],tick,-d)
            extreme=max(extreme,p) if d>0 else min(extreme,p)
            if d*(extreme-anchor)>=1.5*a:
                width=tight_width if tighten_atr>0 and d*(extreme-anchor)>=tighten_atr*a else 3.
                proposed=_tick(extreme-d*width*a,tick,-d)
                if not np.isfinite(main_floor) or d*(proposed-main_floor)>0:
                    main_floor=proposed;trail_source=i
                trail=main_floor
            if not split_done and abs(net[i])>=2:target=_tick(anchor+d*2*a,tick,d)
            equity=realized[i]+net[i]*p-basis-base
            if t>=limit:action=9;action_source=i
            elif equity<=-risk-1e-8:action=1;action_source=i
            elif t-entry_time>=360*60:action=8;action_source=i
            sm=np.isfinite(stop) and -d*(p-stop)>=-1e-8
            tm=np.isfinite(trail) and -d*(p-trail)>=-1e-8
            pm=np.isfinite(target) and d*(p-target)>=-1e-8
        else:
            if pd and (t>=expiry or state[i]!=pd):pd=0
            if pd:
                pending_extreme=min(pending_extreme,p) if pd>0 else max(pending_extreme,p)
                changed=_tick(pending_extreme+pd*.25*pa,tick,pd)
                if changed!=level:level=changed;pending_source=i
            if not pd and t>=start+1200 and t<limit-300 and t>=last_exit+300:
                if prepare_allow[i] and state[i]!=0 and np.isfinite(atr[i]) and atr[i]>0:
                    pd=int(state[i]);pa=max(atr[i],2*tick);pending_extreme=p
                    level=_tick(p+pd*.25*pa,tick,pd);expiry=t+300;pending_source=i
                    market=pd*(p-level)>=-1e-8;prepare_id=count;prepare_row=i
                    preparations[count]=np.array([count,i,pd,level,pa,expiry,q0]);count+=1
        out[i]=np.array([d,campaign,a,anchor,risk,entry,entry_time,abs(net[i]),realized[i],base,
            extreme,int(split_done),stop,trail,target,int(sm),int(tm),int(pm),action,action_source,1,
            pd,level,expiry,pa,q0,int(market),pending_source,prepare_id,prepare_row,0,last_exit,q0,i,
            trail_source,current_atr,atr_source])
    return out,preparations[:count]


def _compare(a: np.ndarray,b: np.ndarray,label: str) -> None:
    """機能: 欠測位置と有限値を比較する。

    引数: a/b(ndarray)、label(str)。返り値: なし(None)。
    """
    assert a.shape==b.shape,label+'形'
    assert np.array_equal(np.isnan(a),np.isnan(b)),label+'欠測'
    assert not np.isinf(a).any() and not np.isinf(b).any(),label+'無限値'
    valid=np.isfinite(a)&np.isfinite(b)
    assert np.all(np.abs(a[valid]-b[valid])<=1e-6),label+'値'


def account(ready: dict,result: dict) -> dict:
    """機能: 注文と返済脚から全行現金・数量・実現損益を独立計算する。

    引数: ready/result(dict)。返り値: cash/net/realized/equity等(dict[str,ndarray])。
    """
    p=ready['last'];n=len(p);cash=np.zeros(n);net=np.zeros(n);realized=np.zeros(n)
    opening=np.zeros(n,np.int8);opening_price=np.zeros(n);split=np.zeros(n,np.bool_)
    for row in result['orders']:
        i=int(row[0]);cash[i]-=row[3]*row[4]*row[5];net[i]+=row[3]*row[4]
        if row[7]:
            assert row[6]==20 and not opening[i]
            opening[i]=int(row[3]);opening_price[i]=row[5]
        elif row[6]==7:split[i]=True
    for row in result['trades']:
        assert abs(row[10]-row[2]*row[3]*(row[5]-row[4]))<=1e-6
        realized[int(row[7])]+=row[10]
    cash=np.cumsum(cash);net=np.cumsum(net);realized=np.cumsum(realized);equity=cash+net*p
    expected=np.column_stack((equity,realized,np.maximum(net,0),np.maximum(-net,0),
                              np.maximum.accumulate(np.maximum.accumulate(np.r_[0.,equity])[1:]-equity),cash,net))
    _compare(expected,result['curve'][:,:7],'影の独立会計')
    return dict(cash=cash,net=net,realized=realized,equity=equity,opening=opening,opening_price=opening_price,split=split)


@njit(cache=True)
def order_reference(p,t,effective,limit,min_delay_seconds,observed_fill):
    """機能: 成熟済みの前状態から各行の成立注文を独立に判定する。

    引数: p/t/effective(ndarray)、limit/min_delay_seconds(float)、observed_fill(bool)。
    返り値: 期待注文8列(ndarray)。何も成立しない行もすべて走査する。
    """
    expected=np.zeros((len(p),8));count=0
    for i in range(len(p)):
        ep=effective[i]
        if not np.isfinite(ep[33]):continue
        d=int(ep[0]);reason=0;fill=0.;side=0;qty=0;opening=0
        source=int(i-1 if min_delay_seconds==0 else ep[33]);campaign=int(ep[1])
        if d:
            if ep[18]:reason=int(ep[18]);fill=p[i];source=int(ep[19]);qty=int(ep[7]);side=-d
            else:
                distance=1e100;selected=-1;selected_price=0.;selected_flag=False
                for z in range(3):
                    level=ep[12+z];sign=d if z==2 else -d;flag=bool(ep[15+z])
                    if np.isfinite(level) and (flag or sign*(p[i]-level)>=-1e-8):
                        candidate=0. if flag else max(0.,sign*(level-p[i-1]))
                        if candidate<distance-1e-9:
                            distance=candidate;selected=z;selected_price=level;selected_flag=flag
                if selected>=0:
                    reason=int(ep[20]) if selected==0 else (2 if selected==1 else 7)
                    fill=p[i] if observed_fill or selected_flag else selected_price;side=-d
                    qty=max(1,int(ep[7]/2)) if selected==2 else int(ep[7])
        elif ep[21] and not ep[30] and t[i]<ep[23] and t[i]<limit-300:
            side=int(ep[21]);flag=bool(ep[26])
            if flag or side*(p[i]-ep[22])>=-1e-8:
                reason=20;fill=p[i] if observed_fill or flag else ep[22]
                qty=int(ep[25]);opening=1;source=int(ep[27]);campaign+=1
        if reason:
            expected[count]=np.array([i,source,campaign,side,qty,fill,reason,opening]);count+=1
    return expected[:count]


def audit(ready: dict,result: dict,config: dict,state: np.ndarray,min_delay_seconds: float,
          observed_fill: bool) -> dict:
    """機能: 公開計画・最新成熟元・全行の成立注文を別式で照合する。

    引数: ready/result/config(dict)、state(ndarray)、min_delay_seconds(float)、observed_fill(bool)。
    返り値: 独立検査の件数・真偽値(dict)。resultは独立影の結果を渡す。
    """
    p,t=ready['last'],ready['time_s'];n=len(p);q0=int(config['initial_qty'])
    assert np.isfinite(p).all() and (p>0).all()
    assert min_delay_seconds==0., '今回の統合は伝達0秒だけ'
    assert (config['tighten_atr'],config['tight_width']) in ((0.,1.),(3.,1.5),(3.,.75))
    assert config['entry_atr']==.25 and config['stop_atr']==1. and config['main_trail']==3.
    assert config['split_target']==2. and config['activation_atr']==1.5 and config['timeout_min']==360.
    scheduler=result['scheduler']
    baseline_config=dict(config,tighten_atr=0.,tight_width=1.)
    baseline_proof=baseline_oracle.audit(ready,scheduler,baseline_config,state,0.,observed_fill)
    assert all(baseline_proof[k] is True for k in ('影全会計一致','独立公開計画一致','独立準備一致','最新成熟計画一致','全行注文成立不成立一致'))
    allow=np.zeros(n,np.bool_)
    fresh=scheduler['prepare_events'][:,1].astype(np.int64)
    assert np.all((fresh>=0)&(fresh<n)) and len(np.unique(fresh))==len(fresh)
    allow[fresh]=True
    assert np.asarray(result['schedule_prepare_allow']).dtype==np.bool_
    assert np.array_equal(allow,result['schedule_prepare_allow'])
    for field in ('prepare_events','entry_preparations'):_compare(result[field],scheduler[field],'同期初回/'+field)
    _compare(result['orders'][result['orders'][:,7]==1],scheduler['orders'][scheduler['orders'][:,7]==1],'同期初回注文')
    curves=account(ready,result);pid=np.full(n,-1,np.int64)
    for c,i,prepared,source in result['entry_preparations']:pid[int(i)]=int(prepared)
    planned,prepares=publication(t,p,ready['atr'],state,curves['cash'],curves['realized'],curves['net'],
        curves['opening_price'],curves['opening'],pid,curves['split'],ready['tick'],ready['start'],ready['limit'],q0,
        config['tighten_atr'],config['tight_width'],allow)
    _compare(planned,result['plans'],'独立公開計画37列');_compare(prepares,result['prepare_events'],'独立新規準備')
    # ----------------------------------------
    # 受信前状態は現在行の約定をまだ含めない。成熟asofは独立の二分探索で決める。
    chosen=np.minimum(np.arange(n)-1,np.searchsorted(t,t-min_delay_seconds,side='right')-1)
    effective=np.full_like(planned,np.nan)
    previous_d=np.r_[0,np.sign(curves['net'][:-1])]
    previous_c=np.r_[-1,planned[:-1,1]]
    present=chosen>=0;idx=np.flatnonzero(present);origin=chosen[present]
    valid=(planned[origin,0]==previous_d[idx])&(planned[origin,1]==previous_c[idx])
    idx=idx[valid];origin=origin[valid]
    effective[idx]=planned[origin]
    effective[idx,7]=np.abs(curves['net'][idx-1]);effective[idx,8]=curves['realized'][idx-1]
    effective[idx,9]=planned[idx-1,9]
    done=planned[idx-1,11].astype(bool);effective[idx,11]=done
    effective[idx[done],14]=np.nan;effective[idx[done],17]=0.
    effective[t>=ready.get('session_close',ready['limit']+600)]=np.nan
    _compare(effective,result['execution_plans'],'独立の最新成熟有効計画')
    expected=order_reference(p,t,effective,ready['limit'],min_delay_seconds,observed_fill)
    _compare(expected,result['orders'],'全行の成立注文と不成立行')
    return dict(影全会計一致=True,独立公開計画一致=True,独立準備一致=True,最新成熟計画一致=True,
                全行注文成立不成立一致=True,原本行数=n,準備数=len(prepares),注文数=len(expected))
