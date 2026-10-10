"""二市場の入口に独立損切り・利益保護・順行時だけの追加を組み合わせる原本順再生器。"""

import math
import numpy as np
from numba import njit


ORDER_COLUMNS=('約定行','判断行','組番号','売買方向','枚数','価格','理由','新規','注文料金','建値番号')
TRADE_COLUMNS=('組番号','新規行','返済行','方向','枚数','建値','返済値','新規料金','返済配賦料金','料金前損益','収支','建値番号')
REASONS={1:'初期損切り',2:'利益追従',3:'保有時間上限',4:'場内全返済',6:'二市場の反対合意',
         8:'約定後の追加リスク超過',9:'進行失敗と停滞',10:'共同方向の新規',11:'順行を確認して追加'}


@njit(cache=True,nogil=True)
def simulate(times,bid,ask,quality,reset,event,mapped,grid,valid,common,opposite_long,opposite_short,
             reference_long,reference_short,tick,start,limit,cap,value,fee_unit,stop_width,trail_width,
             hold_seconds,policy,allocation,cooldown=300.):
    """機能: 建値ごとの全損失を残し、保護された利益の範囲でのみ順行追加する。

    引数: 原本・共通状態・構造線(ndarray)、価格/時刻/価値/料金(float)、cap/policy/allocation(int)。
    policyは0従来トレール、1独立損切り、2早期建値保護、3段階保護、4直前構造損切り、5停滞整理。
    allocationは0全量初回、1初回2割/追加3割/5割。返り値: 注文・建値別決済・全行清算時価・統計・追加リスク記録(tuple)。
    約定は判断後の次有効原本行。保護線更新は追加約定当行に行わず、返済の判定を追加より優先する。
    """
    n=len(times);capacity=max(128,len(grid)*8+64)
    orders=np.zeros((capacity,10));trades=np.zeros((capacity,12));curve=np.zeros(n);risk_events=np.zeros((capacity,8))
    oi=ti=ri=0;cid=-1;side=pending=0;pending_row=-1;pending_side=0;pending_reason=0;pending_qty=0
    pending_reference=0.;last_exit=-1e30;first_i=last_fill=-1;quantity=stage=0
    leg_prices=np.zeros(3);leg_qty=np.zeros(3,dtype=np.int64);leg_rows=np.zeros(3,dtype=np.int64);leg_fees=np.zeros(3)
    cost_sum=paid_fees=entry_price=peak=stop=risk=risk_budget=0.
    cash=last_bid=last_ask=0.;max_long=max_short=adds=excesses=0
    stall_start=-1.;last_grid_stamp=-1e30
    for i in range(n):
        stamp=times[i]
        qok=np.isfinite(bid[i]) and np.isfinite(ask[i]) and bid[i]>0 and ask[i]>=bid[i]
        if qok:last_bid,last_ask=bid[i],ask[i]
        filled_now=False
        # ----------------------------------------
        # 判断済みの注文を次の有効気配で約定する。追加も独立注文として料金を課す。
        if pending and i>pending_row and qok:
            if pending==1:
                if stamp<limit-300.:
                    price=ask[i] if pending_side==1 else bid[i]
                    fee=math.floor(pending_qty*fee_unit+1e-8)
                    if side==0:
                        side=pending_side;cid+=1;first_i=i;stage=0;quantity=0;cost_sum=paid_fees=0.
                        entry_price=price;peak=price;stall_start=-1.;last_grid_stamp=-1e30
                        risk=stop_width
                        if policy==4:risk=side*(price-pending_reference)
                        stop=price-side*risk
                        risk_budget=pending_qty*max(risk,0.)*value+2*fee
                    leg_prices[stage]=price;leg_qty[stage]=pending_qty;leg_rows[stage]=i;leg_fees[stage]=fee
                    orders[oi]=np.array([i,pending_row,cid,side,pending_qty,price,pending_reason,1.,fee,stage]);oi+=1
                    cash-=side*pending_qty*price*value+fee
                    quantity+=pending_qty;cost_sum+=pending_qty*price;paid_fees+=fee;stage+=1;last_fill=i;filled_now=True
                    if pending_reason==11:adds+=1
                    max_long=max(max_long,quantity if side==1 else 0);max_short=max(max_short,quantity if side==-1 else 0)
            else:
                price=bid[i] if side==1 else ask[i]
                exit_fee=math.floor(quantity*fee_unit+1e-8)
                orders[oi]=np.array([i,pending_row,cid,-side,quantity,price,pending_reason,0.,exit_fee,-1]);oi+=1
                used_qty=used_fee=0
                for leg in range(stage):
                    used_qty+=leg_qty[leg]
                    cumulative=math.floor(exit_fee*used_qty/quantity+1e-8)
                    allocated=cumulative-used_fee;used_fee=cumulative
                    gross=side*(price-leg_prices[leg])*leg_qty[leg]*value
                    net=gross-leg_fees[leg]-allocated
                    trades[ti]=np.array([cid,leg_rows[leg],i,side,leg_qty[leg],leg_prices[leg],price,leg_fees[leg],allocated,gross,net,leg]);ti+=1
                cash+=side*quantity*price*value-exit_fee
                side=0;quantity=0;stage=0;last_exit=stamp
            pending=0
        g=int(mapped[i]);usable=g>=0 and valid[g] and quality[i] and not reset[i]
        # ----------------------------------------
        # 初期損失幅と利益追従を分ける。支持の一時消失だけでは利益玉を切らない。
        if side and pending==0:
            reason=0
            if stamp>=limit-60.:reason=4
            elif hold_seconds>0 and stamp-times[first_i]>=hold_seconds:reason=3
            elif risk<=0 or policy==4 and risk>stop_width+tick*1e-8:reason=8
            elif qok:
                quote=bid[i] if side==1 else ask[i]
                if policy==0:
                    if i>first_i:
                        if side*(quote-peak)<=-trail_width+tick*1e-8:reason=1 if abs(peak-entry_price)<tick*1e-8 else 2
                        elif side*(quote-peak)>0:peak=quote
                        stop=peak-side*trail_width
                else:
                    if (i>first_i or filled_now and stage>1) and side*(quote-stop)<=tick*1e-8:
                        reason=1 if side*(stop-entry_price)<-tick*1e-8 else 2
                    if reason==0 and i>last_fill:
                        if side*(quote-peak)>0:peak=quote
                        advance=side*(peak-entry_price)
                        trigger=(.5 if policy==2 else 1.)*risk
                        if advance>=trigger:
                            gap=trail_width*(.5 if policy==3 and advance>=2*risk else 1.)
                            candidate=peak-side*gap
                            if side*(candidate-stop)>0:stop=candidate
                        if policy in (2,3) and advance>=(.5 if policy==2 else 2.)*risk:
                            exit_fee=math.floor(quantity*fee_unit+1e-8)
                            floor_price=(cost_sum+side*(paid_fees+exit_fee)/value)/quantity
                            protected=(math.ceil(floor_price/tick-1e-8) if side==1 else math.floor(floor_price/tick+1e-8))*tick
                            if policy==3:protected=entry_price+side*max(risk,side*(protected-entry_price))
                            if side*(protected-stop)>0:stop=protected
                    # ----------------------------------------
                    # 既発注の追加は未来の約定を見て取消さない。約定後の超過なら次行で全返済する。
                    if reason==0 and filled_now and stage>1:
                        projected=side*(stop*quantity-cost_sum)*value-paid_fees-math.floor(quantity*fee_unit+1e-8)
                        risk_events[ri]=np.array([i,cid,1.,risk_budget,stop,projected,quantity,side]);ri+=1
                        if -projected>risk_budget+1e-6:reason=8;excesses+=1
            if reason==0 and policy!=0 and usable:
                if opposite_long[g] if side==1 else opposite_short[g]:reason=6
                if policy==5 and reason==0:
                    weak=common[g]!=side and side*(peak-entry_price)<.5*risk and stamp-times[first_i]>=300.
                    if not weak or grid[g]-last_grid_stamp>5.+1e-8:stall_start=-1.
                    if weak:
                        if stall_start<0:stall_start=grid[g]
                        if grid[g]-stall_start>=30.:reason=9
                    last_grid_stamp=grid[g]
            elif g>=0 and not usable:
                stall_start=-1.;last_grid_stamp=-1e30
            if reason:
                pending=2;pending_row=i;pending_reason=reason
        # ----------------------------------------
        # 追加前に全玉の共通保護線・全料金を評価し、初回の総損失枠以内に収める。
        if side and pending==0 and allocation==1 and stage<3 and usable and i>last_fill and qok and stamp<limit-300.:
            quote=bid[i] if side==1 else ask[i]
            if common[g]==side and side*(quote-entry_price)>=.5*risk*stage:
                extra=cap*3//10 if stage==1 else cap-quantity
                new_price=ask[i] if side==1 else bid[i]
                fee=math.floor(extra*fee_unit+1e-8);new_quantity=quantity+extra
                projected=side*(stop*new_quantity-cost_sum-extra*new_price)*value-paid_fees-fee-math.floor(new_quantity*fee_unit+1e-8)
                if extra>0 and new_quantity<=cap and -projected<=risk_budget+1e-6:
                    risk_events[ri]=np.array([i,cid,0.,risk_budget,stop,projected,new_quantity,side]);ri+=1
                    pending=1;pending_side=side;pending_qty=extra;pending_row=i;pending_reason=11
        # ----------------------------------------
        # 新規は片方向上限内で開始し、構造損切りは判断時点で幅も検査する。
        if side==0 and pending==0 and event[i]!=0 and quality[i] and not reset[i] and qok and stamp>=start+300. and stamp<limit-300. and stamp-last_exit>=cooldown:
            direction=int(event[i]);allowed=True;reference=0.
            if policy==4:
                if not usable:allowed=False
                else:
                    reference=reference_long[g] if direction==1 else reference_short[g]
                    price=ask[i] if direction==1 else bid[i]
                    distance=direction*(price-reference)
                    allowed=np.isfinite(reference) and distance>=2*tick and distance<=stop_width
            if allowed:
                pending=1;pending_side=direction;pending_qty=cap if allocation==0 else max(1,cap*2//10)
                pending_row=i;pending_reason=10;pending_reference=reference
        curve[i]=cash
        if side:curve[i]+=side*quantity*(last_bid if side==1 else last_ask)*value-math.floor(quantity*fee_unit+1e-8)
    return orders[:oi],trades[:ti],curve,np.array([side,pending,quantity,max_long,max_short,adds,excesses]),risk_events[:ri]
