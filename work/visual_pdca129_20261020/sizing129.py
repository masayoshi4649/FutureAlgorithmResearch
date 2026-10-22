"""保存された夜間判断を保ち、守れる利益床から追加数量を決める。"""

import numpy as np
from numba import njit


ORDER_COLUMNS = ("実行行", "判断行", "影ID", "方向", "枚数", "価格", "理由", "新規")
PARENT_COLUMNS = ("影ID", "初回実行行", "最終返済行", "建方向", "初回枚数", "最大枚数",
                  "初回建値", "初期幅", "粗損益", "全手数料", "差引損益", "追加枚数",
                  "追加注文数", "最終返済理由", "残枚数", "最終平均建値")
CURVE_COLUMNS = ("全行差引清算価値", "符号付き枚数", "累計費用", "実現収支から費用を控除")
EVENT_COLUMNS = ("判断行", "種別", "影ID", "床価格", "追加予算価格", "返済予算価格",
                 "保有数", "追加数", "支払済費用", "予定追加返済費用", "予定差引",
                 "最高順行幅", "利益床幅")


@njit(cache=True)
def simulate(times, bid, ask, qok, base_orders, base_trades, tick,
             initial_quantity, maximum_quantity, step_quantity, multiplier,
             fee_tenths, addition_mode):
    """
    機能: 元の夜間判断行を一度ずつ消費し、少量開始と利益床内の追加を運転する。
    引数: times/bid/ask/qok/base_orders/base_trades(ndarray)は原行と保存影通知、
          tick/multiplier(float)、initial_quantity/maximum_quantity/step_quantity/
          fee_tenths/addition_mode(int)。mode0は減量のみ、1は利益床で追加する。
    返り値: tuple[ndarray,...]はorders8列、parents16列、curve4列、events13列。
            元tradesで参照するのは、当時既知の初期幅の列11だけ。
    """
    assert 0 < initial_quantity <= maximum_quantity
    assert step_quantity > 0 and tick > 0. and multiplier > 0.
    assert addition_mode == 0 or addition_mode == 1
    n = len(times)
    capacity = max(128, len(base_orders)*(maximum_quantity+4)+16)
    orders = np.zeros((capacity, 8))
    parents = np.zeros((max(1, len(base_trades)), 16))
    parents[:, :3] = -1.
    curve = np.zeros((n, 4))
    events = np.zeros((capacity*3, 13))
    oc = 0
    ec = 0
    pointer = 0
    pending = 0
    pending_source = -1
    pending_quantity = 0
    pending_reason = 0
    pending_cid = -1
    pending_side = 0
    pending_width = 0.
    cid = -1
    side = 0
    held = 0
    cost = 0.
    first_price = 0.
    width = 0.
    peak = 0.
    floor = -np.inf
    cash = 0.
    fees = 0.
    last_bid = np.nan
    last_ask = np.nan
    exit_notified = False
    for i in range(n):
        t = times[i]
        good = qok[i] and np.isfinite(bid[i]) and np.isfinite(ask[i])
        good = good and 0. < bid[i] < ask[i]
        if good:
            last_bid = bid[i]
            last_ask = ask[i]
        # ----------------------------------------
        # 前行までの予約を先に約定する。当行で判明する影の出口へ遡って取消さない。
        if pending and good and i > pending_source:
            if pending == 1:
                assert held == 0
                cid = pending_cid
                side = pending_side
                held = pending_quantity
                first_price = ask[i] if side > 0 else bid[i]
                cost = held*first_price
                width = pending_width
                peak = 0.
                floor = -width
                fee = held*fee_tenths//10
                fees += fee
                cash -= fee
                parents[cid] = np.array([cid, i, -1., side, held, held, first_price, width,
                    0., fee, -fee, 0., 0., 0., held, first_price])
                orders[oc] = np.array([i, pending_source, cid, side, held, first_price, 1., 1.])
                oc += 1
                exit_notified = False
            elif pending == 2:
                assert held > 0 and not exit_notified
                quantity = pending_quantity
                assert held+quantity <= maximum_quantity
                fill = ask[i] if side > 0 else bid[i]
                cost += quantity*fill
                held += quantity
                fee = quantity*fee_tenths//10
                fees += fee
                cash -= fee
                parents[cid, 5] = max(parents[cid, 5], held)
                parents[cid, 9] += fee
                parents[cid, 10] = parents[cid, 8]-parents[cid, 9]
                parents[cid, 11] += quantity
                parents[cid, 12] += 1.
                parents[cid, 14] = held
                parents[cid, 15] = cost/held
                orders[oc] = np.array([i, pending_source, cid, side, quantity, fill, 81., 1.])
                oc += 1
            else:
                assert pending == 3 and held > 0
                fill = bid[i] if side > 0 else ask[i]
                gross = side*(held*fill-cost)*multiplier
                fee = held*fee_tenths//10
                cash += gross-fee
                fees += fee
                orders[oc] = np.array([i, pending_source, cid, -side, held, fill, pending_reason, 0.])
                oc += 1
                parents[cid, 2] = i
                parents[cid, 8] += gross
                parents[cid, 9] += fee
                parents[cid, 10] = parents[cid, 8]-parents[cid, 9]
                parents[cid, 13] = pending_reason
                parents[cid, 14] = 0.
                held = 0
                side = 0
                cost = 0.
            pending = 0
        # ----------------------------------------
        # 保存影の約定値・未来出口・MFEは使わず、当行の判断通知だけを消費する。
        while pointer < len(base_orders) and int(base_orders[pointer, 1]) == i:
            event = base_orders[pointer]
            pointer += 1
            original_cid = int(event[2])
            if event[7] == 1.:
                assert held == 0 and pending == 0
                assert 0 <= original_cid < len(base_trades)
                # この初期幅は元の入口判断までに確定した値。未来の他列を読まない。
                initial_width = base_trades[original_cid, 11]
                assert np.isfinite(initial_width) and initial_width > 0.
                pending = 1
                pending_source = i
                pending_quantity = initial_quantity
                pending_cid = original_cid
                pending_side = int(event[3])
                pending_width = initial_width
                events[ec] = np.array([i, 1., original_cid, 0., 0., 0., 0.,
                    initial_quantity, 0., 0., 0., 0., -initial_width])
                ec += 1
            else:
                assert int(event[7]) == 0
                if pending == 1:
                    # 正常気配がなく初回未約定のまま影終了通知を受けた場合。
                    assert pending_cid == original_cid
                    pending = 0
                elif held:
                    assert cid == original_cid and int(event[3]) == -side
                    if pending == 2:
                        events[ec] = np.array([i, 4., cid, 0., 0., 0., held,
                            pending_quantity, parents[cid, 9], 0., 0., peak, floor])
                        ec += 1
                    pending = 3
                    pending_source = i
                    pending_quantity = held
                    pending_reason = int(event[6])
                    exit_notified = True
                events[ec] = np.array([i, 2., original_cid, 0., 0., 0., held,
                    0., 0., 0., 0., peak, floor])
                ec += 1
        assert pointer == len(base_orders) or int(base_orders[pointer, 1]) > i
        # ----------------------------------------
        # 元影と同じ初回建値から最高順行と1R起動/.75R追尾を因果再構成する。
        if held and good:
            mark = bid[i] if side > 0 else ask[i]
            movement = side*(mark-first_price)
            peak = max(peak, movement)
            if peak >= width:
                floor = max(floor, peak-.75*width)
            if addition_mode == 1 and not pending and not exit_notified and held < maximum_quantity and floor > 0.:
                quantity = min(step_quantity, maximum_quantity-held)
                # 現在気配より1呼値不利な取得、床を不利に丸めさらに1呼値不利な返済。
                floor_price = first_price+side*floor
                if side > 0:
                    entry_budget = np.ceil((ask[i]+tick)/tick-1e-10)*tick
                    exit_budget = np.floor(floor_price/tick+1e-10)*tick-tick
                else:
                    entry_budget = np.floor((bid[i]-tick)/tick+1e-10)*tick
                    exit_budget = np.ceil(floor_price/tick-1e-10)*tick+tick
                future_fees = quantity*fee_tenths//10 + (held+quantity)*fee_tenths//10
                projected_gross = side*((held+quantity)*exit_budget-cost-quantity*entry_budget)*multiplier
                projected_net = parents[cid, 8]+projected_gross-parents[cid, 9]-future_fees
                if entry_budget > 0. and exit_budget > 0. and projected_net >= 0.:
                    pending = 2
                    pending_source = i
                    pending_quantity = quantity
                    pending_cid = cid
                    events[ec] = np.array([i, 3., cid, floor_price, entry_budget, exit_budget,
                        held, quantity, parents[cid, 9], future_fees, projected_net, peak, floor])
                    ec += 1
        assert 0 <= held <= maximum_quantity
        unrealized = 0.
        if held:
            mark = last_bid if side > 0 else last_ask
            assert np.isfinite(mark)
            unrealized = side*(held*mark-cost)*multiplier
        curve[i] = np.array([cash+unrealized, side*held, fees, cash])
        assert oc < len(orders) and ec < len(events)
    assert pointer == len(base_orders)
    completed = parents[:, 1] >= 0.
    return orders[:oc], parents[completed], curve, events[:ec]
