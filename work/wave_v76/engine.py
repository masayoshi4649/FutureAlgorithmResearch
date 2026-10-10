"""二市場の支持を継続評価し、撤退と返済後再確認のドテンを原本順で再生する。"""

import math
import numpy as np
from numba import njit


ORDER_COLUMNS=('約定行','判断行','取引番号','売買方向','枚数','価格','理由','新規')
TRADE_COLUMNS=('取引番号','新規行','返済行','方向','枚数','建値','返済値','新規料金','返済料金','料金前損益','収支')
REASONS={1:'保険の初期損切り',2:'保険のトレーリング',3:'保有時間上限',4:'場内全返済',
         6:'両市場の反対合意',7:'両市場の支持消失',10:'共同方向の新規',12:'返済後に再確認してドテン'}


@njit(cache=True,nogil=True)
def simulate(times,bid,ask,quality,reset,event,mapped_grid,tick,start,limit,
             quantity,value,fee_unit,width,entry_width,grid,valid,strong,
             loss_long,loss_short,opposite_long,opposite_short,
             manage_mode,hold_seconds,cooldown=30.,flip_expiry=30.):
    """機能: 二市場の反対合意・支持消失による管理を、保険トレールと比較する。

    引数: 原本時刻/気配・判定配列(ndarray)、価格/秒/倍率(float)、数量/方式(int)。
    manage_modeは0保険のみ、1反対合意で返済、2返済後再確認して反転、3支持消失も返済。
    hold_seconds=0は場末まで固定時間返済なし。返り値: 注文、決済、時価曲線、空休止、統計(tuple)。
    新規と返済は判断の次の有効原本行で約定する。未来の保存末尾による清算は行わない。
    """
    n=len(times)
    capacity=max(64,len(grid)*2+32)
    orders=np.zeros((capacity,8));trades=np.zeros((capacity//2+8,11));curve=np.zeros(n)
    oi=ti=0
    fee=math.floor(quantity*fee_unit+1e-8)
    cash=0.
    side=pending=pending_side=pending_flip=0
    pending_row=pending_reason=entry_i=cid=-1
    entry_price=peak=0.
    last_exit=-1e30
    last_bid=last_ask=0.
    flip_side=0;flip_exit_row=-1;flip_until=0.
    flip_count=cancel_count=0
    for i in range(n):
        stamp=times[i]
        qok=np.isfinite(bid[i]) and np.isfinite(ask[i]) and bid[i]>0 and ask[i]>=bid[i]
        if qok:last_bid,last_ask=bid[i],ask[i]
        # ----------------------------------------
        # 前観測で決めた返済又は新規を執行する。ドテンも独立した二注文である。
        if pending!=0 and i>pending_row and qok:
            if pending==1:
                if stamp<limit-300.:
                    side=pending_side;entry_i=i;cid+=1
                    entry_price=ask[i] if side==1 else bid[i];peak=entry_price
                    cash-=side*quantity*entry_price*value+fee
                    orders[oi]=np.array([i,pending_row,cid,side,quantity,entry_price,pending_reason,1.]);oi+=1
                    if pending_reason==12:flip_count+=1
                pending_flip=0
            else:
                price=bid[i] if side==1 else ask[i]
                gross=side*(price-entry_price)*quantity*value;net=gross-2*fee
                cash+=side*quantity*price*value-fee
                orders[oi]=np.array([i,pending_row,cid,-side,quantity,price,pending_reason,0.]);oi+=1
                trades[ti]=np.array([cid,entry_i,i,side,quantity,entry_price,price,fee,fee,gross,net]);ti+=1
                if pending_flip!=0 and stamp<limit-300.:
                    flip_side=pending_flip;flip_exit_row=i;flip_until=stamp+flip_expiry
                pending_flip=0;side=0;last_exit=stamp
            pending=0
        g=int(mapped_grid[i])
        new_grid=g>=0
        usable=new_grid and valid[g] and quality[i] and not reset[i]
        # ----------------------------------------
        # 保有中は予定場末、任意の時間上限、保険、二市場判断の順に判定する。
        if side!=0 and pending==0 and i>entry_i:
            reason=0;reverse=0
            if stamp>=limit-60.:reason=4
            elif hold_seconds>0 and stamp-times[entry_i]>=hold_seconds:reason=3
            elif qok:
                quote=bid[i] if side==1 else ask[i]
                if side*(quote-peak)<=-width+tick*1e-8:
                    reason=1 if abs(peak-entry_price)<tick*1e-8 else 2
                elif side*(quote-peak)>0:peak=quote
            if reason==0 and manage_mode!=0 and usable:
                opposite=opposite_long[g] if side==1 else opposite_short[g]
                unsupported=loss_long[g] if side==1 else loss_short[g]
                if opposite:
                    reason=6
                    if manage_mode in (2,3):reverse=-side
                elif manage_mode==3 and unsupported:reason=7
            if reason:
                pending=2;pending_row=i;pending_reason=reason;pending_flip=reverse
        # ----------------------------------------
        # 反転は返済の実約定後に来た新しい共通格子で、反対合意をもう一度確認する。
        if side==0 and pending==0 and flip_side!=0:
            if stamp>flip_until or stamp>=limit-300.:
                flip_side=0;cancel_count+=1
            elif new_grid and i>flip_exit_row and grid[g]>times[flip_exit_row]:
                ready=(opposite_short[g] if flip_side==1 else opposite_long[g])
                if not usable or strong[g]!=flip_side:
                    flip_side=0;cancel_count+=1
                elif ready and quality[i] and not reset[i] and qok:
                    pending=1;pending_side=flip_side;pending_row=i;pending_reason=12
                    flip_side=0
        # ----------------------------------------
        # 通常の新規イベントは建玉なし・再入場待ち後だけ受け付ける。
        if (side==0 and pending==0 and flip_side==0 and event[i]!=0 and quality[i]
                and not reset[i] and qok and stamp>=start+300. and stamp<limit-300.
                and stamp-last_exit>=cooldown):
            pending=1;pending_side=int(event[i]);pending_row=i;pending_reason=10
        curve[i]=cash
        if side!=0:curve[i]+=side*quantity*(last_bid if side==1 else last_ask)*value-fee
    stats=np.array([side,pending,flip_side,0,0,0,0,flip_count,cancel_count])
    return orders[:oi],trades[:ti],curve,np.empty((0,5)),stats
