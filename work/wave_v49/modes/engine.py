"""自動追従・反復モードを、単一保有と翌観測行注文で比較する。"""

import numpy as np
from numba import njit


TRACE_COLUMNS = ('position', 'mode', 'campaign', 'entry', 'initial_atr', 'peak',
                 'stop', 'stop_reason', 'stop_source', 'market_exit', 'market_source',
                 'entry_plan_side', 'entry_plan_level', 'entry_plan_source',
                 'entry_plan_atr', 'entry_plan_mode', 'cooldown', 'flip_hint',
                 'entry_plan_market')


@njit(cache=True)
def rounded(value, tick, side):
    """機能: 逆指値を売買方向へ呼値単位に丸める。

    引数: value/tick(float)、side(int)。返り値: 呼値価格(float)。
    """
    return np.ceil(value/tick-1e-9)*tick if side>0 else np.floor(value/tick+1e-9)*tick


@njit(cache=True)
def replay(time,price,atr,mode,trend,rangeside,score,valid,absorb,support,resistance,
           limit,tick,qty,mode_choice,book_rule,exit_rule,flip_rule,mode_exit,sr_rule,
           require_flat=True):
    """機能: 公開済み信号から次行注文を作り、場内で全返済する。

    引数: time/price/atr/score/support/resistance(float配列)、mode/trend/rangeside/absorb(int配列)、
    valid(bool配列)、limit/tick(float)、qty及び各rule(int)、require_flat(bool)。
    返り値: orders(8列)、trades(11列)、equity(float配列)、modes(取引組のモード配列)、
    trace(TRACE_COLUMNSに従う行後19列)。require_flat=Falseは途中切断の監査だけに使う。
    既存候補1の再現器ではなく、新しい出口・自動選択を比較する共通試作器。
    """
    n=len(time)
    orders=np.zeros((n,8));trades=np.zeros((n,11));trade_modes=np.zeros(n,np.int8)
    equity=np.zeros(n);trace=np.full((n,19),np.nan)
    oc=0;tc=0;cash=0.;pos=0;cid=-1;entry=0.;entryrow=0;entrytime=0.
    fixedatr=0.;active_mode=0;peak=0.;peak_at=0.;stop=0.;stop_source=-1;stop_reason=1
    market_exit=0;market_source=-1
    plan=0;plan_side=0;plan_level=0.;plan_source=-1;plan_atr=0.;plan_mode=0;plan_market=False
    setup_side=0;setup_mode=0;setup_atr=0.;setup_at=0.;extreme=0.
    cooldown=-1.;flip_hint=0;flip_deadline=-1.
    for i in range(n):
        now=time[i];px=price[i]
        assert np.isfinite(px) and px>0 and np.isfinite(now)
        assert i==0 or now>=time[i-1]
        # ----------------------------------------
        # 前行で既に有効だった返済と新規を先に評価し、現在の観測で過去の注文を取り消さない。
        if pos:
            reason=0;fill=0.;source=-1
            if market_exit:
                reason=market_exit;fill=px;source=market_source
            elif pos*(px-stop)<=0:
                reason=stop_reason;fill=stop;source=stop_source
            if reason:
                pnl=pos*(fill-entry)*qty
                orders[oc]=np.array([i,source,cid,-pos,qty,fill,reason,0.]);oc+=1
                trades[tc]=np.array([cid,0.,pos,qty,entry,fill,entryrow,i,0.,reason,pnl])
                trade_modes[tc]=active_mode;tc+=1;cash+=pnl
                if flip_rule and active_mode==2 and pnl>0 and reason==2:
                    flip_hint=-pos;flip_deadline=now+120.
                else:flip_hint=0
                pos=0;market_exit=0;cooldown=now+60.;setup_side=0
        if not pos and plan and now<limit and i>plan_source:
            if plan_market or plan_side*(px-plan_level)>=-1e-8:
                pos=plan_side;entry=px if plan_market else plan_level
                entryrow=i;entrytime=now;fixedatr=plan_atr
                active_mode=plan_mode;peak=entry;peak_at=now;cid+=1
                stop=rounded(entry-pos*fixedatr*(1. if active_mode==1 else .8),tick,-pos)
                stop_source=i;stop_reason=1;market_exit=0
                orders[oc]=np.array([i,plan_source,cid,pos,qty,entry,20.,1.]);oc+=1
                plan=0;setup_side=0;flip_hint=0
        equity[i]=cash+(pos*(px-entry)*qty if pos else 0.)
        # ----------------------------------------
        # 保有中は新規時モードの出口を継続し、既設ストップを決して緩めない。
        if pos:
            plan=0
            if pos*(px-peak)>0:peak=px;peak_at=now
            favorable=pos*(peak-entry)/fixedatr
            width=3. if active_mode==1 else .35
            activation=1.5 if active_mode==1 else .5
            if active_mode==1 and favorable>=3.:width=.75
            age=now-entrytime;stall=now-peak_at
            if exit_rule in (1,5):
                if age>=(1800. if active_mode==1 else 600.):width=min(width,1. if active_mode==1 else .25)
                if age>=(3600. if active_mode==1 else 1200.):width=min(width,.5 if active_mode==1 else .15)
            elif exit_rule==2:
                if age>=(3600. if active_mode==1 else 1200.):width=min(width,1. if active_mode==1 else .25)
                if age>=(7200. if active_mode==1 else 2400.):width=min(width,.5 if active_mode==1 else .15)
            elif exit_rule in (3,6):
                if stall>=600.:width=min(width,.5 if active_mode==1 else .25)
            elif exit_rule==4:
                if stall>=1200.:width=min(width,.5 if active_mode==1 else .25)
            if exit_rule in (5,6,7) and valid[i] and pos*score[i]<-.15:
                width=min(width,.5 if active_mode==1 else .25)
            if favorable>=activation:
                newstop=rounded(peak-pos*width*fixedatr,tick,-pos)
                if pos*(newstop-stop)>0:stop=newstop;stop_reason=2
            stop_source=i
            # ----------------------------------------
            # 幅短縮時に既に通過した価格は過去約定にせず、次行の観測価格で返済する。
            if pos*(px-stop)<=1e-8:
                market_exit=stop_reason;market_source=i
            if now>=limit:market_exit=4;market_source=i
            elif age>=(21600. if active_mode==1 else 2700.):market_exit=3;market_source=i
            elif mode_exit and mode[i]!=0 and (mode[i]!=active_mode or (mode[i]==1 and trend[i]!=pos)):
                market_exit=5;market_source=i
            trace[i]=np.array([pos,active_mode,cid,entry,fixedatr,peak,stop,stop_reason,
                stop_source,market_exit,market_source,0.,np.nan,-1.,np.nan,0.,cooldown,flip_hint,0.])
            continue
        # ----------------------------------------
        # モードと板が不明な場合は見送り。新規は0.2ATR反発を追う注文を毎観測後に更新する。
        if now>=limit-60.:
            plan=0;setup_side=0
            trace[i]=np.array([0.,0.,cid,np.nan,np.nan,np.nan,np.nan,0.,-1.,0.,-1.,
                0.,np.nan,-1.,np.nan,0.,cooldown,flip_hint,0.])
            continue
        chosen=int(mode[i])
        if mode_choice and chosen!=mode_choice:chosen=0
        direction=int(trend[i]) if chosen==1 else int(rangeside[i]) if chosen==2 else 0
        current_atr=atr[i]
        if not np.isfinite(current_atr) or current_atr<2*tick:direction=0
        if chosen==2 and sr_rule:
            direction=1 if px<=support[i]+.25*current_atr else -1 if px>=resistance[i]-.25*current_atr else 0
        if chosen==1 and sr_rule==2:
            if direction==1 and px<resistance[i]+.1*current_atr:direction=0
            if direction==-1 and px>support[i]-.1*current_atr:direction=0
        forced=False
        if flip_hint and now<=flip_deadline and chosen==2:
            if flip_rule==1:
                direction=flip_hint;forced=True
            elif direction==flip_hint and valid[i] and direction*score[i]>.1:
                forced=True
        elif now>flip_deadline:flip_hint=0
        if now<cooldown and not forced:direction=0
        if book_rule==1 and (not valid[i] or direction*score[i]<=.1):direction=0
        if book_rule==2:
            if chosen==2 and (not valid[i] or absorb[i]!=direction):direction=0
            if chosen==1 and (not valid[i] or direction*score[i]<=.1):direction=0
        if not direction:
            plan=0;setup_side=0
            trace[i]=np.array([0.,0.,cid,np.nan,np.nan,np.nan,np.nan,0.,-1.,0.,-1.,
                0.,np.nan,-1.,np.nan,0.,cooldown,flip_hint,0.])
            continue
        if direction!=setup_side or chosen!=setup_mode or now-setup_at>300.:
            setup_side=direction;setup_mode=chosen;setup_at=now;setup_atr=current_atr;extreme=px
        if direction*(px-extreme)<0:extreme=px
        plan_level=rounded(px+direction*tick if forced and flip_rule==1 else extreme+direction*.2*setup_atr,tick,direction)
        plan=1;plan_side=direction;plan_source=i;plan_atr=setup_atr;plan_mode=chosen
        # 新規でも、設置した時点で条件成立済みなら次行観測価格を使う。
        plan_market=direction*(px-plan_level)>=-1e-8
        trace[i]=np.array([0.,0.,cid,np.nan,np.nan,np.nan,np.nan,0.,-1.,0.,-1.,
            plan_side,plan_level,plan_source,plan_atr,plan_mode,cooldown,flip_hint,int(plan_market)])
    if require_flat:
        assert pos==0
    return orders[:oc],trades[:tc],equity,trade_modes[:tc],trace
