"""利益カバーを個別に外さず、全玉の清算純益で組を返済する独立状態機械。"""

import math
from pathlib import Path
import os

import numpy as np

os.environ.setdefault('NUMBA_CACHE_DIR',str(Path(__file__).resolve().parent/'numba_runtime'))
from numba import njit


ORDER_COLUMNS=('uid','kind','side','decision_row','fill_row','decision_time','fill_time',
               'price','fee','reason','rung','quantity','decision_mid','fill_last',
               'fill_bid','fill_ask','net','trigger_price')
LOT_COLUMNS=('uid','side','rung','entry_decision_row','entry_row','entry_time','entry_price',
             'exit_decision_row','exit_row','exit_time','exit_price','gross','fees','net',
             'reason','mfe','mae','entry_last','exit_last')
CURVE_COLUMNS=('row','time','equity','cash','realized_net','long','short','drawdown')
SUMMARY_COLUMNS=('net','cash','profit','loss','fees','closed_lots','wins','losses','unclosed',
                 'max_long','max_short','max_drawdown','min_equity','entries','canceled',
                 'clock_rejected','step','held_entry_fees','last_equity','last_time')
REASONS={1:'玉別利益の個別追尾',9:'場内時刻返済',10:'組全体の純益追尾',11:'飽和時に逆側の最悪一枚を削減'}


@njit(cache=False,boundscheck=True)
def push(table,count,values):
    """
    機能: 注文・玉・時価の証跡を必要量だけ拡張して保存する。
    引数: table(float二次元配列)、count(int)、values(float一次元配列)。
    返り値: tuple[float二次元配列,int]は保存先と新しい行数。
    """
    if count==len(table):
        expanded=np.empty((max(8,count*2),table.shape[1]),np.float64)
        expanded[:count]=table
        table=expanded
    table[count]=values
    return table,count+1


@njit(cache=False,boundscheck=True)
def replay(rows,times,last,bid,ask,cap,multiplier,fee,observed_tick,fraction,mode,trail,
           session_start,entry_end,close_time,session_end):
    """
    機能: 初回一枚から両方向へ段階追加し、カバーを残して組全体の純益を追尾する。
    引数: rows(int一次元配列)、times/last/bid/ask(float一次元配列)は原行順の気配。
        cap/mode(int)、multiplier/fee/observed_tick/fraction/trail/場内時刻(float)。
        mode0はKEEP、mode1は両側飽和時のLast反発反落で負け玉一枚を削減するRESCUE、
        mode2は玉別純益peakが正になってから幅戻りを個別返済するROTATE。
    返り値: tuple[orders,lots,curve,summary]は18/19/8/20列の既存契約。
        一注文一枚、次正常原行のBBO約定、有限Last、価格時計逆行棄却を用いる。
        組開始は初回予約時のflat cash、全清算時価から引き、途中の実損も残す。
        EOFに架空返済せず、全flat完了行で全極値を現在Lastに再準備し、新規は翌原行から。
    """
    assert cap>0 and mode in (0,1,2) and observed_tick>0. and fraction>0. and trail>0.
    state=np.zeros((2,cap),np.int8)  # 0空き、1新規予約、2保有、3返済予約。
    anchor=np.zeros((2,cap))
    price=np.zeros((2,cap))
    uid=np.zeros((2,cap),np.int64)
    drow=np.zeros((2,cap),np.int64)
    dtime=np.zeros((2,cap))
    dmid=np.zeros((2,cap))
    trigger=np.zeros((2,cap))
    entry_limit=np.zeros((2,cap))
    erow=np.zeros((2,cap),np.int64)
    edrow=np.zeros((2,cap),np.int64)
    etime=np.zeros((2,cap))
    elast=np.zeros((2,cap))
    peak=np.zeros((2,cap))
    trough=np.zeros((2,cap))
    why=np.zeros((2,cap),np.int8)
    orders=np.empty((2048,18))
    lots=np.empty((1024,19))
    curve=np.empty((2048,8))
    oc=lc=cc=sequence=entries=canceled=rejected=wins=losses=0
    cash=realized=profit=loss=paid=high=maxdd=mineq=equity=0.
    maxlong=maxshort=0
    fee_one=math.floor(fee+1e-9)
    first=True
    step=np.nan
    previous_reference=np.nan
    lastclock=curveclock=-np.inf
    lastrow=-1
    lasttime=np.nan
    phase=0  # 0待機、1初回予約、2組運転、3全返済予約。
    basket_start=0.
    basket_peak=0.
    basket_armed=False
    restart_row=-1
    saturated=False
    rescue_low=rescue_high=0.

    for i in range(len(rows)):
        now,raw=times[i],rows[i]
        if not math.isfinite(now) or now<session_start or now>session_end or now<lastclock:
            rejected+=1
            continue
        if not (math.isfinite(last[i]) and last[i]>0. and math.isfinite(bid[i]) and math.isfinite(ask[i]) and 0.<bid[i]<=ask[i]):
            rejected+=1
            continue
        lastclock=now
        lastrow,lasttime=raw,now
        mid=(bid[i]+ask[i])*.5
        reference=last[i]
        if first:
            step=max(observed_tick,math.floor(mid*fraction/observed_tick+.5)*observed_tick)
            anchor[:,:]=reference
            previous_reference=reference
            first=False

        # ----------------------------------------
        # 既判断の返済を先に実行する。新規同行の返済と価格線での架空約定は行わない。
        for s in range(2):
            side=1 if s==0 else -1
            xp=bid[i] if side==1 else ask[i]
            for j in range(cap):
                if state[s,j]!=3 or raw<=drow[s,j]:
                    continue
                gross=side*(xp-price[s,j])*multiplier
                net=gross-2*fee_one
                cash+=gross-fee_one
                realized+=net
                paid+=fee_one
                profit+=max(0.,net)
                loss+=max(0.,-net)
                wins+=int(net>0.)
                losses+=int(net<0.)
                orders,oc=push(orders,oc,np.array([uid[s,j],2.,-side,drow[s,j],raw,
                    dtime[s,j],now,xp,fee_one,why[s,j],j,1.,dmid[s,j],reference,
                    bid[i],ask[i],net,trigger[s,j]]))
                lots,lc=push(lots,lc,np.array([uid[s,j],side,j,edrow[s,j],erow[s,j],
                    etime[s,j],price[s,j],drow[s,j],raw,now,xp,gross,2*fee_one,net,
                    why[s,j],max(peak[s,j],net),min(trough[s,j],net),elast[s,j],reference]))
                state[s,j]=0
                anchor[s,j]=reference
        if phase==3 and not np.any(state>=2):
            phase=0
            restart_row=raw
            anchor[:,:]=reference
            basket_peak=0.
            basket_armed=False
            saturated=False

        # ----------------------------------------
        # 初回予約中は一枚だけ。各予約は最初の次正常気配一回で約定又は失効する。
        for s in range(2):
            side=1 if s==0 else -1
            for j in range(cap):
                if state[s,j]!=1:
                    continue
                if now>=entry_end:
                    state[s,j]=0
                    anchor[s,j]=reference
                    canceled+=1
                    if phase==1:
                        phase=0
                        anchor[:,:]=reference
                    continue
                if raw<=drow[s,j]:
                    continue
                xp=ask[i] if side==1 else bid[i]
                affordable=xp<=entry_limit[s,j] if side==1 else xp>=entry_limit[s,j]
                if not affordable or ask[i]-bid[i]>step:
                    state[s,j]=0
                    anchor[s,j]=reference
                    canceled+=1
                    if phase==1:
                        phase=0
                        anchor[:,:]=reference
                    continue
                sequence+=1
                entries+=1
                uid[s,j]=sequence
                price[s,j]=xp
                erow[s,j],edrow[s,j],etime[s,j]=raw,drow[s,j],now
                elast[s,j]=reference
                cash-=fee_one
                paid+=fee_one
                initial=side*((bid[i] if side==1 else ask[i])-xp)*multiplier-2*fee_one
                peak[s,j]=trough[s,j]=initial
                state[s,j]=2
                if phase==1:
                    phase=2
                orders,oc=push(orders,oc,np.array([sequence,1.,side,drow[s,j],raw,
                    dtime[s,j],now,xp,fee_one,0.,j,1.,dmid[s,j],reference,
                    bid[i],ask[i],0.,trigger[s,j]]))

        # ----------------------------------------
        # ROTATEの自然flatは、同原行の既返済と既予約新規の約定・失効を全処理した後。
        # 事前に生きた新規が同原行で約定した場合は同組を維持し、途中の空瞬間で取消さない。
        if mode==2 and phase==2 and not np.any(state!=0):
            phase=0
            restart_row=raw
            anchor[:,:]=reference
            basket_peak=0.
            basket_armed=False
            saturated=False

        # ----------------------------------------
        # 全玉を返済側BBOと未払返済料で評価する。既払新規料はcashに一度だけ入る。
        equity=cash
        countlong=countshort=0
        for s in range(2):
            side=1 if s==0 else -1
            xp=bid[i] if side==1 else ask[i]
            for j in range(cap):
                if state[s,j]<2:
                    continue
                countlong+=int(s==0)
                countshort+=int(s==1)
                net=side*(xp-price[s,j])*multiplier-2*fee_one
                peak[s,j]=max(peak[s,j],net)
                trough[s,j]=min(trough[s,j],net)
                equity+=net+fee_one
                if mode==2 and phase==2 and state[s,j]==2 and now<close_time:
                    if peak[s,j]>0. and net>0. and peak[s,j]-net>=trail*step*multiplier:
                        state[s,j]=3
                        why[s,j]=1
                        drow[s,j],dtime[s,j],dmid[s,j]=raw,now,mid
                        trigger[s,j]=xp
        maxlong,maxshort=max(maxlong,countlong),max(maxshort,countshort)
        high,mineq=max(high,equity),min(mineq,equity)
        maxdd=max(maxdd,high-equity)
        if now>=curveclock+60.:
            curve,cc=push(curve,cc,np.array([raw,now,equity,cash,realized,countlong,countshort,high-equity]))
            curveclock=now
        move=reference-previous_reference
        previous_reference=reference

        # ----------------------------------------
        # 組追尾又は場末は全返済。新規予約を全取消し、全実返済完了まで再開しない。
        whole_reason=0
        if phase==2:
            basket_net=equity-basket_start
            basket_peak=max(basket_peak,basket_net)
            if mode!=2 and basket_peak>=(trail+1.)*step*multiplier:
                basket_armed=True
            if now>=close_time:
                whole_reason=9
            elif mode!=2 and basket_armed and basket_net>0. and basket_peak-basket_net>=trail*step*multiplier:
                whole_reason=10
        if whole_reason:
            for s in range(2):
                for j in range(cap):
                    if state[s,j]==1:
                        state[s,j]=0
                        anchor[s,j]=reference
                        canceled+=1
                    elif state[s,j]==2:
                        state[s,j]=3
                        why[s,j]=whole_reason
                        drow[s,j],dtime[s,j],dmid[s,j]=raw,now,mid
                        trigger[s,j]=bid[i] if s==0 else ask[i]
            phase=3
            saturated=False

        # ----------------------------------------
        # RESCUEは組全返済より後。両側実保有上限の新しい飽和から独立極値を追う。
        is_full=countlong==cap and countshort==cap
        if phase==2 and mode==1 and is_full:
            if not saturated:
                rescue_low=rescue_high=reference
                saturated=True
            else:
                rescue_low=min(rescue_low,reference)
                rescue_high=max(rescue_high,reference)
                target_side=-1
                if move>0. and reference>=rescue_low+3.*step:
                    target_side=1
                elif move<0. and reference<=rescue_high-3.*step:
                    target_side=0
                if target_side>=0 and not np.any(state==3):
                    side=1 if target_side==0 else -1
                    xp=bid[i] if side==1 else ask[i]
                    worst=0.
                    target=-1
                    for j in range(cap):
                        if state[target_side,j]!=2:
                            continue
                        net=side*(xp-price[target_side,j])*multiplier-2*fee_one
                        if net<worst:
                            worst,target=net,j
                    if target>=0:
                        state[target_side,target]=3
                        why[target_side,target]=11
                        drow[target_side,target],dtime[target_side,target],dmid[target_side,target]=raw,now,mid
                        trigger[target_side,target]=rescue_low+3.*step if target_side==1 else rescue_high-3.*step
        else:
            saturated=False

        # ----------------------------------------
        # 空き枠だけ動くLast極値を更新。初回一枚の予約後は他の全新規を止める。
        if now>=entry_end or phase in (1,3) or raw==restart_row:
            continue
        for s in range(2):
            side=1 if s==0 else -1
            for j in range(cap):
                if state[s,j]!=0:
                    continue
                anchor[s,j]=min(anchor[s,j],reference) if side==1 else max(anchor[s,j],reference)
                if ask[i]-bid[i]>step:
                    continue
                line=anchor[s,j]+side*(3.+j)*step
                crossed=reference>=line and move>0. if side==1 else reference<=line and move<0.
                if not crossed:
                    continue
                if phase==0:
                    basket_start=cash
                    basket_peak=0.
                    basket_armed=False
                    phase=1
                state[s,j]=1
                drow[s,j],dtime[s,j],dmid[s,j]=raw,now,mid
                trigger[s,j]=line
                entry_limit[s,j]=ask[i]+observed_tick if side==1 else bid[i]-observed_tick
                if phase==1:
                    break
            if phase==1:
                break

    # ----------------------------------------
    # 未約定新規は失効を数え、残実玉は未返済として残す。EOF清算を作らない。
    remaining=0
    for s in range(2):
        for j in range(cap):
            remaining+=int(state[s,j]>=2)
            canceled+=int(state[s,j]==1)
    if lastrow>=0:
        curve,cc=push(curve,cc,np.array([lastrow,lasttime,equity,cash,realized,
            np.count_nonzero(state[0]>=2),np.count_nonzero(state[1]>=2),high-equity]))
    summary=np.array([equity,cash,profit,loss,paid,lc,wins,losses,remaining,maxlong,maxshort,
        maxdd,mineq,entries,canceled,rejected,step,remaining*fee_one,equity,lasttime])
    return orders[:oc],lots[:lc],curve[:cc],summary
