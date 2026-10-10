"""共通入口の後の両建て、縮小、持ち替え、分割利確を原本気配で管理する。"""

import math

import numpy as np
from numba import njit, types
from numba.typed import List

ORDER_TYPE = types.UniTuple(types.float64,9)
TRADE_TYPE = types.UniTuple(types.float64,12)

REASONS = {1:'元方向の逆指値',2:'元方向のトレーリング',3:'保有期限',4:'場内全返済',
           5:'全玉の損失枠',6:'全玉の利益保護',7:'段階保険新規',8:'保険の反転返済',
           9:'元方向誤判定の返済',10:'共通初回新規',11:'反転後の不足枚数追加',12:'分割利確',
           13:'段階利益固定',14:'保険の損切り'}
ORDER_COLUMNS = ('約定行','判断行','組','売買方向','枚数','価格','理由','新規','新規時役割')
TRADE_COLUMNS = ('組','新規行','返済行','建玉方向','枚数','建値','返済値','新規料金配賦','返済料金配賦','料金前損益','収支','新規時役割')


@njit(cache=True)
def held(qtys, dirs, side):
    """機能: 指定方向の保有枚数を全役割から合算する。

    引数: qtys/dirs(ndarray)、side(int)。返り値: 保有枚数(int)。
    """
    total = 0
    for k in range(len(qtys)):
        if dirs[k]==side:
            total += qtys[k]
    return total


@njit(cache=True)
def new_lot(i, decision, cid, side, qty, role, reason, bid, ask, value, fee_unit,
            qtys, dirs, roles, originals, closed, fees, rows, prices, orders):
    """機能: 新規注文を買いask・売りbidで執行し、独立した玉を記録する。

    引数: 各行・組・方向・枚数・役割・理由(int)、気配/倍率/料金(float)、台帳配列(ndarray/list)。
    返り値: 現金変化(float)。空き玉枠がない場合は例外を発生する。
    """
    if qty<=0:
        return 0.
    slot = -1
    for k in range(len(qtys)):
        if qtys[k]==0:
            slot = k
            break
    assert slot>=0
    price = ask if side==1 else bid
    fee = math.floor(qty*fee_unit+1e-8)
    qtys[slot],dirs[slot],roles[slot] = qty,side,role
    originals[slot],closed[slot],fees[slot],rows[slot],prices[slot] = qty,0,fee,i,price
    orders.append((float(i),float(decision),float(cid),float(side),float(qty),price,float(reason),1.,float(role)))
    return -side*qty*price*value-fee


@njit(cache=True)
def close_lots(i, decision, cid, side, qty, role, reason, bid, ask, value, fee_unit,
               qtys, dirs, roles, originals, closed, fees, rows, prices, orders, trades):
    """機能: 指定方向・役割の玉をFIFOで返済し、料金を累積切捨てで配賦する。

    引数: 各行・組・方向・枚数・役割・理由(int)、気配/倍率/料金(float)、台帳配列(ndarray/list)。
    返り値: 現金変化(float)。返済数量が保有数量を超える場合は例外を発生する。
    """
    if qty<=0:
        return 0.
    out = bid if side==1 else ask
    fee = math.floor(qty*fee_unit+1e-8)
    orders.append((float(i),float(decision),float(cid),float(-side),float(qty),out,float(reason),0.,float(role)))
    left = qty
    allocated = 0
    while left>0:
        slot = -1
        oldest = 1<<60
        for k in range(len(qtys)):
            if qtys[k]>0 and dirs[k]==side and roles[k]==role and rows[k]<oldest:
                slot,oldest = k,rows[k]
        assert slot>=0
        take = min(left,qtys[slot])
        before = closed[slot]
        entry_fee = math.floor(fees[slot]*(before+take)/originals[slot]+1e-8)-math.floor(fees[slot]*before/originals[slot]+1e-8)
        exit_fee = math.floor(fee*(allocated+take)/qty+1e-8)-math.floor(fee*allocated/qty+1e-8)
        gross = side*(out-prices[slot])*take*value
        trades.append((float(cid),float(rows[slot]),float(i),float(side),float(take),prices[slot],out,
                       float(entry_fee),float(exit_fee),gross,gross-entry_fee-exit_fee,float(role)))
        qtys[slot] -= take
        closed[slot] += take
        allocated += take
        left -= take
    return side*qty*out*value-fee


@njit(cache=True)
def close_direction(i, decision, cid, side, reason, bid, ask, value, fee_unit,
                    qtys, dirs, roles, originals, closed, fees, rows, prices, orders, trades):
    """機能: 一方向を新規時役割ごとの注文へまとめ、全返済する。

    引数: 各行・組・方向・理由(int)、気配/倍率/料金(float)、台帳配列(ndarray/list)。
    返り値: 現金変化(float)。役割を跨ぐ手数料の注文合算は行わない。
    """
    delta = 0.
    for role in range(2):
        qty = 0
        for k in range(len(qtys)):
            if dirs[k]==side and roles[k]==role:
                qty += qtys[k]
        delta += close_lots(i,decision,cid,side,qty,role,reason,bid,ask,value,fee_unit,
                            qtys,dirs,roles,originals,closed,fees,rows,prices,orders,trades)
    return delta


@njit(cache=True)
def arrays(orders, trades):
    """機能: 可変長の注文・決済記録を一定列数の配列へ変換する。

    引数: orders/trades(list[tuple])。返り値: 注文・決済(tuple[ndarray,ndarray])。
    """
    oo = np.zeros((len(orders),9))
    tt = np.zeros((len(trades),12))
    for i in range(len(orders)):
        for j in range(9):
            oo[i,j] = orders[i][j]
    for i in range(len(trades)):
        for j in range(12):
            tt[i,j] = trades[i][j]
    return oo,tt


@njit(cache=True)
def simulate(times,bid,ask,signal,schedule,tick,limit,cap,value,fee_unit,
             kind,stop,activation,trail,hold_seconds,grid,step_fraction,cover_activation,cover_trail,
             basket_stop,basket_activation,basket_trail,flip_fraction,partial_level,partial_fraction,
             tighten_minutes,ratchet_step,ratchet_keep,grid_mode):
    """機能: 共通初回約定から、全玉の保険・途中判断・場内返済を機械的に再生する。

    引数: 時刻/気配/入口信号(ndarray)、共通初回約定schedule(ndarray5列)、価格/時間/倍率(float)、
    cap/kind/grid_mode(int)、各管理変数(float)。kindは0基準、1保険、2保険持替、3分割、4時間短縮、5段階利益固定。
    返り値: 注文9列、決済12列、料金後全玉清算時価、最大方向枚数と終端状態(tuple[ndarray,...])。
    全管理の初回を同時刻・同方向・満額に揃え、早期全返済後も共通60分枠まで次入口を待つ。
    """
    n = len(times)
    qtys = np.zeros(64,dtype=np.int64)
    dirs = np.zeros(64,dtype=np.int8)
    roles = np.zeros(64,dtype=np.int8)
    originals = np.zeros(64,dtype=np.int64)
    closed = np.zeros(64,dtype=np.int64)
    fees = np.zeros(64,dtype=np.int64)
    rows = np.zeros(64,dtype=np.int64)
    prices = np.zeros(64)
    orders = List.empty_list(ORDER_TYPE)
    trades = List.empty_list(TRADE_TYPE)
    curve = np.zeros(n)
    cash = 0.
    last_bid = last_ask = 0.
    maxlong = maxshort = 0
    pointer = 0
    cid = -1
    side = 0
    initial_i = watch_i = -1
    cover_watch_i = -1
    anchor = grid_anchor = core_extreme = cover_extreme = 0.
    grid_used = 0
    core_started = cover_started = False
    partial_done = False
    flipped = False
    pending = 0
    pending_row = -1
    pending_qty = 0
    pending_reason = 0
    restore_pending = False
    group_cash = basket_peak = 0.
    ratchet_floor = 0.
    ratchet_armed = False
    step = max(1,int(math.ceil(cap*step_fraction)))
    for i in range(n):
        qok = np.isfinite(bid[i]) and np.isfinite(ask[i]) and bid[i]>0 and ask[i]>=bid[i]
        if qok:
            last_bid,last_ask = bid[i],ask[i]
        # ----------------------------------------
        # 前行までに決めた注文は、価格が戻っても取り消さず次有効気配で執行する。
        if pending!=0 and i>pending_row and qok:
            if pending==1:
                if times[i]<limit-300.:
                    qty = min(pending_qty,cap-held(qtys,dirs,-side))
                    cash += new_lot(i,pending_row,cid,-side,qty,1,7,bid[i],ask[i],value,fee_unit,
                                    qtys,dirs,roles,originals,closed,fees,rows,prices,orders)
                    cover_started = False
                    cover_extreme = 0.
                    cover_watch_i = i
            elif pending==2:
                cash += close_direction(i,pending_row,cid,-side,pending_reason,bid[i],ask[i],value,fee_unit,
                                        qtys,dirs,roles,originals,closed,fees,rows,prices,orders,trades)
                cover_started = False
                cover_extreme = 0.
                cover_watch_i = i
                grid_anchor = bid[i] if side==1 else ask[i]
                grid_used = 0
            elif pending==3:
                cash += close_direction(i,pending_row,cid,side,9,bid[i],ask[i],value,fee_unit,
                                        qtys,dirs,roles,originals,closed,fees,rows,prices,orders,trades)
                side = -side
                flipped = True
                anchor = ask[i] if side==1 else bid[i]
                grid_anchor = bid[i] if side==1 else ask[i]
                grid_used = 0
                core_started = cover_started = False
                core_extreme = cover_extreme = 0.
                restore_pending = held(qtys,dirs,side)<cap
                watch_i = i
            elif pending==4:
                cash += close_lots(i,pending_row,cid,side,pending_qty,0,12,bid[i],ask[i],value,fee_unit,
                                   qtys,dirs,roles,originals,closed,fees,rows,prices,orders,trades)
                partial_done = True
            elif pending==5:
                cash += close_direction(i,pending_row,cid,side,pending_reason,bid[i],ask[i],value,fee_unit,
                                        qtys,dirs,roles,originals,closed,fees,rows,prices,orders,trades)
                cash += close_direction(i,pending_row,cid,-side,pending_reason,bid[i],ask[i],value,fee_unit,
                                        qtys,dirs,roles,originals,closed,fees,rows,prices,orders,trades)
                side = 0
                restore_pending = False
            elif pending==6:
                if times[i]<limit-300.:
                    qty = cap-held(qtys,dirs,side)
                    cash += new_lot(i,pending_row,cid,side,qty,0,11,bid[i],ask[i],value,fee_unit,
                                    qtys,dirs,roles,originals,closed,fees,rows,prices,orders)
                    watch_i = i
                restore_pending = False
            pending = 0
        # ----------------------------------------
        # 共通の初回だけは固定した親注文の判断行を引き継ぐ。
        if pointer<len(schedule) and int(schedule[pointer,0])==i:
            assert side==0 and pending==0 and held(qtys,dirs,1)==0 and held(qtys,dirs,-1)==0
            assert qok
            side = int(schedule[pointer,3])
            anchor = schedule[pointer,4]
            cid += 1
            group_cash = cash
            cash += new_lot(i,int(schedule[pointer,1]),cid,side,cap,0,10,bid[i],ask[i],value,fee_unit,
                            qtys,dirs,roles,originals,closed,fees,rows,prices,orders)
            initial_i = watch_i = i
            grid_anchor = anchor
            grid_used = 0
            core_started = cover_started = False
            core_extreme = cover_extreme = 0.
            cover_watch_i = -1
            partial_done = flipped = restore_pending = False
            ratchet_floor = 0.
            ratchet_armed = False
            basket_peak = 0.
            pointer += 1
        # ----------------------------------------
        # 含み損益は両方向を別々の清算気配へ評価する。ネット数量だけに気配を掛けない。
        long_qty,short_qty = held(qtys,dirs,1),held(qtys,dirs,-1)
        maxlong,maxshort = max(maxlong,long_qty),max(maxshort,short_qty)
        assert long_qty<=cap and short_qty<=cap
        equity = cash+(long_qty*last_bid-short_qty*last_ask)*value
        curve[i] = equity
        if side==0 or pending!=0 or i<=watch_i:
            continue
        q = held(qtys,dirs,side)
        cover = held(qtys,dirs,-side)
        pnl = equity-group_cash
        basket_peak = max(basket_peak,pnl)
        reason = 0
        if times[i]>=limit-60.:
            reason = 4
        elif times[i]-times[initial_i]>=hold_seconds:
            reason = 3
        elif basket_stop>0 and pnl<=-basket_stop*cap*tick*value:
            reason = 5
        elif basket_activation>0 and basket_peak>=basket_activation*cap*tick*value and pnl<=basket_peak-basket_trail*cap*tick*value:
            reason = 6
        if reason==0 and qok:
            close_quote = bid[i] if side==1 else ask[i]
            advance = side*(close_quote-anchor)/tick
            effective_trail = trail
            if kind==4:
                age = (times[i]-times[initial_i])/60.
                if age>=tighten_minutes:
                    effective_trail = min(effective_trail,4.)
                if age>=2*tighten_minutes:
                    effective_trail = min(effective_trail,2.)
            if advance<=-stop:
                reason = 1
            else:
                if not core_started and advance>=activation:
                    core_started = True
                    core_extreme = close_quote
                if core_started:
                    if side*(close_quote-core_extreme)>0:
                        core_extreme = close_quote
                    if side*(close_quote-core_extreme)<=-effective_trail*tick:
                        reason = 2
                    elif kind==5:
                        mfe = side*(core_extreme-anchor)/tick
                        if ratchet_armed and advance<=ratchet_floor:
                            reason = 13
                        elif mfe>=ratchet_step:
                            floor_gain = math.floor(mfe/ratchet_step)*ratchet_step-ratchet_keep
                            ratchet_floor = max(ratchet_floor,floor_gain)
                            ratchet_armed = True
            if reason==0 and kind==3 and not partial_done and advance>=partial_level:
                pending,pending_row,pending_qty = 4,i,min(q,max(1,int(math.ceil(cap*partial_fraction))))
            if reason==0 and pending==0 and restore_pending:
                pending,pending_row = 6,i
            # ----------------------------------------
            # 保険は順次縮小するネット露出と同じ反対枚数。反転判断も観測済み情報だけを使う。
            if reason==0 and pending==0 and kind in (1,2):
                if kind==2 and not flipped and cover>=int(math.ceil(cap*flip_fraction)) and signal[i]==-side:
                    pending,pending_row = 3,i
                else:
                    if cover>0 and i>cover_watch_i:
                        cover_quote = ask[i] if side==1 else bid[i]
                        cover_gain = 0.
                        for k in range(len(qtys)):
                            if qtys[k]>0 and dirs[k]==-side:
                                cover_gain += -side*(cover_quote-prices[k])*qtys[k]*value
                        if not cover_started and cover_gain>=cover_activation*cover*tick*value:
                            cover_started = True
                            cover_extreme = cover_quote
                        if cover_started:
                            if -side*(cover_quote-cover_extreme)>0:
                                cover_extreme = cover_quote
                            anticipated_fee = 2*math.floor(cover*fee_unit+1e-8)
                            if side*(cover_quote-cover_extreme)>=cover_trail*tick and cover_gain>anticipated_fee:
                                pending,pending_row,pending_reason = 2,i,8
                    if pending==0:
                        if grid_mode==1 and cover==0 and side*(close_quote-grid_anchor)>0:
                            grid_anchor = close_quote
                        adverse = -side*(close_quote-grid_anchor)/tick
                        reached = int(math.floor(max(0.,adverse)/grid))
                        if reached>grid_used and cover<cap and times[i]<limit-300.:
                            pending_qty = min(cap-cover,(reached-grid_used)*step)
                            grid_used = reached
                            pending,pending_row = 1,i
        if reason!=0:
            pending,pending_row,pending_reason = 5,i,reason
    oo,tt = arrays(orders,trades)
    return oo,tt,curve,np.array([maxlong,maxshort,held(qtys,dirs,1),held(qtys,dirs,-1),pending,pointer])
