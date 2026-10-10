"""原本順の短期板信号と、先に完了した影取引だけによる入口校正を再生する。"""

import math
import numpy as np
from numba import njit


ORDER_COLUMNS=('decision_i','fill_i','kind','side','qty','price','fee','realized_gross','cycle_net')
TRADE_COLUMNS=('entry_decision_i','entry_i','exit_decision_i','exit_i','side','qty','entry_price','exit_price','entry_fee','exit_fee','gross','net','reason')
REASONS={1:'小幅目標に到達',2:'当初損切り',3:'保有期限',4:'セッション内返済',5:'順行後の利益保護'}


@njit(cache=True)
def candidate_signals(bid,ask,bq,aq,ofi,valid,reset,execbuy,execsell,unknown,times,events_i,events_side,events_qty,events_best,events_price,tick,start):
    """機能: 過去64/256更新の圧力・補充から、単銘柄の候補方向を作る。

    引数: 各原本行の気配/数量/OFI/品質/執行代理/時計(ndarray)、補充配列(ndarray)、tick/start(float)。
    返り値: 2機構×3強さ×原本行の方向(ndarray int8)。未来行は使わない。
    """
    n=len(bid)
    signal=np.zeros((6,n),dtype=np.int8)
    prefix=np.zeros((5,n+1))
    for i in range(n):
        prefix[0,i+1]=prefix[0,i]+(ofi[i] if np.isfinite(ofi[i]) else 0.)
        prefix[1,i+1]=prefix[1,i]+(bq[i]+aq[i])/2.
        prefix[2,i+1]=prefix[2,i]+(execbuy[i] if np.isfinite(execbuy[i]) else 0.)
        prefix[3,i+1]=prefix[3,i]+(execsell[i] if np.isfinite(execsell[i]) else 0.)
        prefix[4,i+1]=prefix[4,i]+(unknown[i] if np.isfinite(unknown[i]) else 0.)
    last_reset=0
    pointer=0
    recent_bid_i=recent_ask_i=-1000
    recent_bid_strength=recent_ask_strength=0.
    recent_bid_price=recent_ask_price=0.
    for i in range(n):
        if reset[i] or not valid[i]:
            last_reset=i
        while pointer<len(events_i) and events_i[pointer]<=i:
            if events_side[pointer]==1:
                recent_bid_i=events_i[pointer]
                recent_bid_strength=events_qty[pointer]/max(events_best[pointer],1.)
                recent_bid_price=events_price[pointer]
            else:
                recent_ask_i=events_i[pointer]
                recent_ask_strength=events_qty[pointer]/max(events_best[pointer],1.)
                recent_ask_price=events_price[pointer]
            pointer+=1
        if i<256 or i%16!=0 or i-last_reset<256 or times[i]-start<300.:
            continue
        if times[i]-times[i-256]>120. or ask[i]-bid[i]>tick*1.001:
            continue
        depth=(prefix[1,i+1]-prefix[1,i-63])/64.
        if depth<=0 or bq[i]+aq[i]<=0:
            continue
        f64=(prefix[0,i+1]-prefix[0,i-63])/depth
        f256=(prefix[0,i+1]-prefix[0,i-255])/( (prefix[1,i+1]-prefix[1,i-255])/256. )
        f16=(prefix[0,i+1]-prefix[0,i-15])/((prefix[1,i+1]-prefix[1,i-15])/16.)
        imbalance=(bq[i]-aq[i])/(bq[i]+aq[i])
        movement=((bid[i]+ask[i])-(bid[i-64]+ask[i-64]))/(2*tick)
        buy=prefix[2,i+1]-prefix[2,i-63]
        sell=prefix[3,i+1]-prefix[3,i-63]
        un=prefix[4,i+1]-prefix[4,i-63]
        known=buy+sell
        if known+un>0 and un/(known+un)>.4:
            continue
        for level in range(3):
            threshold=2. if level==0 else 4. if level==1 else 8.
            qi=.4 if level==0 else .6 if level==1 else .8
            if f64>=threshold and f256>0 and imbalance>=qi and movement>=1. and (known==0 or buy>=sell):
                signal[level,i]=1
            elif f64<=-threshold and f256<0 and imbalance<=-qi and movement<=-1. and (known==0 or sell>=buy):
                signal[level,i]=-1
            strength=.5 if level==0 else 1. if level==1 else 2.
            if i-recent_bid_i<=64 and recent_bid_i>last_reset and recent_bid_strength>=strength and abs(bid[i]-recent_bid_price)<=2*tick and sell>=depth and abs(movement)<=2. and f16>=threshold:
                signal[3+level,i]=1
            elif i-recent_ask_i<=64 and recent_ask_i>last_reset and recent_ask_strength>=strength and abs(ask[i]-recent_ask_price)<=2*tick and buy>=depth and abs(movement)<=2. and f16<=-threshold:
                signal[3+level,i]=-1
    return signal


@njit(cache=True)
def replay(times,bid,ask,signal,tick,start,limit,value,qty,fee_unit,target_ticks,stop_ticks,hold_seconds,cooldown,protect,calibration,required_wins,window):
    """機能: 次原本行約定で、単一建玉と独立した影取引を全場再生する。

    引数: times/bid/ask/signal(ndarray)、価格/時間/倍率/費用(float)、数量/各幅/校正指定(int)。
    返り値: 注文・決済・資産曲線・校正カウンタ(tuple)。返済費用は実返済時にのみ発生する。
    """
    n=len(times)
    entries_possible=np.count_nonzero(signal)
    orders=np.zeros((min(n+16,2*entries_possible+16),9))
    trades=np.zeros((min(n//2+16,entries_possible+16),13))
    equity=np.zeros(n)
    on=tn=0
    side=0
    entry=0.
    entry_i=decision_i=-1
    pending=0
    pending_i=-1
    pending_reason=0
    realized=fees=0.
    high_profit=0.
    last_exit=-1e20
    fee=math.floor(qty*fee_unit+1e-9)
    paper_side=0
    paper_entry=0.
    paper_time=0.
    paper_high_profit=0.
    paper_last_exit=-1e20
    paper_pending=0
    paper_pending_reason=0
    paper_outcomes=np.zeros(max(window,1))
    paper_pointer=paper_count=0
    positive_paper=0
    allowed=blocked=0
    for i in range(n):
        # ----------------------------------------
        # 判断済みの影取引を先に約定し、既に終了した結果だけを校正へ渡す。
        if paper_pending!=0:
            if paper_pending==1:
                if times[i]>=limit-300.:
                    paper_side=0
                else:
                    paper_entry=ask[i] if paper_side==1 else bid[i]
                    paper_time=times[i]
                    paper_high_profit=0.
            else:
                assert times[i]<limit+300.,'影返済が保存対象場を超えました'
                exit_price=bid[i] if paper_side==1 else ask[i]
                pnl=paper_side*(exit_price-paper_entry)*qty*value-2*fee
                if paper_count>=window:
                    positive_paper-=int(paper_outcomes[paper_pointer]>0)
                paper_outcomes[paper_pointer]=pnl
                positive_paper+=int(pnl>0)
                paper_pointer=(paper_pointer+1)%window
                paper_count+=1
                paper_side=0
                paper_last_exit=times[i]
            paper_pending=0
        # ----------------------------------------
        # 実口座の次行約定を処理する。影取引と資金は混ぜない。
        if pending!=0:
            if pending==1:
                if times[i]>=limit-300.:
                    side=0
                else:
                    entry=ask[i] if side==1 else bid[i]
                    entry_i=i
                    fees+=fee
                    high_profit=0.
                    orders[on]=np.array([pending_i,i,1,side,qty,entry,fee,0.,0.])
                    on+=1
            else:
                assert times[i]<limit+300.,'返済約定が保存対象場を超えました'
                exit_price=bid[i] if side==1 else ask[i]
                gross=side*(exit_price-entry)*qty*value
                net=gross-2*fee
                realized+=gross
                fees+=fee
                orders[on]=np.array([pending_i,i,2,-side,qty,exit_price,fee,gross,net])
                on+=1
                trades[tn]=np.array([decision_i,entry_i,pending_i,i,side,qty,entry,exit_price,fee,fee,gross,net,pending_reason])
                tn+=1
                side=0
                last_exit=times[i]
            pending=0
        if paper_side!=0:
            pp=paper_side*((bid[i] if paper_side==1 else ask[i])-paper_entry)
            paper_high_profit=max(paper_high_profit,pp)
            paper_protected=protect and paper_high_profit>=target_ticks*tick*.5 and pp<=2*fee/(qty*value)+tick*.5
            if pp>=target_ticks*tick or pp<=-stop_ticks*tick or times[i]>=paper_time+hold_seconds or times[i]>=limit-60. or paper_protected:
                paper_pending=2
        elif signal[i]!=0 and times[i]<limit-300. and times[i]-paper_last_exit>=cooldown:
            paper_side=int(signal[i])
            paper_pending=1
        if side!=0:
            points=side*((bid[i] if side==1 else ask[i])-entry)
            high_profit=max(high_profit,points)
            reason=0
            if times[i]>=limit-60.:
                reason=4
            elif points<=-stop_ticks*tick:
                reason=2
            elif points>=target_ticks*tick:
                reason=1
            elif protect and high_profit>=target_ticks*tick*.5 and points<=2*fee/(qty*value)+tick*.5:
                reason=5
            elif times[i]>=times[entry_i]+hold_seconds:
                reason=3
            if reason!=0:
                pending=2
                pending_i=i
                pending_reason=reason
        elif signal[i]!=0 and times[i]<limit-300. and times[i]-last_exit>=cooldown:
            can=not calibration or (paper_count>=window and positive_paper>=required_wins)
            if can:
                side=int(signal[i])
                pending=1
                pending_i=i
                decision_i=i
                allowed+=1
            else:
                blocked+=1
        unrealized=side*((bid[i] if side==1 else ask[i])-entry)*qty*value if side!=0 and pending!=1 else 0.
        equity[i]=realized-fees+unrealized
    return orders[:on],trades[:tn],equity,np.array([side,paper_count,positive_paper,allowed,blocked,pending,paper_pending])
