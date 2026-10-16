"""元E01の実注文接頭から、UID別の場内清算と当時会計を再構成する。"""

from decimal import Decimal, ROUND_FLOOR

import numpy as np


VALUE = {'TOPIX': 1000., 'NK225': 10.}
FEE = {'TOPIX': 41.8, 'NK225': 11.}
QUANTITY = {'TOPIX': 5, 'NK225': 10}
CAP = {'TOPIX': 10, 'NK225': 20}
TICK = {'TOPIX': .5, 'NK225': 10.}


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 一つの実注文の片道料金を円単位で切り捨てる。
    引数: quantity(int)は約定枚数、symbol(str)は商品識別子。
    返り値: intは実注文料金。残玉清算でもUID間を合算しない。
    """
    assert quantity >= 0
    return int((Decimal(quantity) * Decimal(str(FEE[symbol]))).to_integral_value(rounding=ROUND_FLOOR))


def metric(values: list[float]) -> dict:
    """
    機能: 料金後損益を正負に分け、同一商品の金額指標を求める。
    引数: values(list[float])は完結した親またはUIDの収支。
    返り値: dictは利益・損失・平均勝負比。無取引を勝ちへ数えない。
    """
    a = np.asarray(values, float); wins = a[a > 0]; losses = a[a < 0]
    gain, loss = float(wins.sum()), float(-losses.sum())
    return dict(利益=gain, 損失=loss, 収支=float(a.sum()), 親数=len(a), 勝ち親=len(wins),
        負け親=len(losses), 零親=int((a == 0).sum()), PF=gain/loss if loss else None,
        利益割合=gain/(gain+loss) if gain+loss else None,
        平均利益=float(wins.mean()) if len(wins) else None,
        平均損失=float(-losses.mean()) if len(losses) else None,
        平均損益比=float(wins.mean()/-losses.mean()) if len(wins) and len(losses) else None)


def normal_mask(quotes: dict) -> np.ndarray:
    """
    機能: 元の正常気配資格を有限で正のbid/askへ重ねる。
    引数: quotes(dict)は保存済みquote_valid/bid/ask/seq/time_s。
    返り値: ndarray[bool]は実約定可能行。未来気配の補完は行わない。
    """
    b, a = quotes['bid'], quotes['ask']
    n = len(b)
    assert all(len(quotes[key]) == n for key in ('ask', 'quote_valid', 'seq', 'time_s'))
    assert np.issubdtype(quotes['seq'].dtype, np.integer)
    return quotes['quote_valid'] & np.isfinite(b) & np.isfinite(a) & (b > 0) & (b < a)


def apply_order(outstanding: dict, order: np.ndarray, uid: int, index: int,
                symbol: str, target_uid: int = -1) -> list[dict]:
    """
    機能: 当行の実新規または返済を、実新規から作ったUID残玉へFIFO適用する。
    引数: outstanding(dict)、order(ndarray[float])、uid/index/target_uid(int)、symbol(str)。
    返り値: list[dict]は当該実返済の玉。将来のtrade配列や元仮想返済を参照しない。
    """
    row, cid, side, quantity, new = map(int, (order[0], order[2], order[3], order[4], order[7]))
    price, cost = float(order[5]), fee(quantity, symbol)
    if new:
        assert uid >= 0 and uid not in outstanding and target_uid == -1
        outstanding[uid] = dict(uid=uid, cid=cid, side=side, quantity=quantity, remaining=quantity,
            entry_row=row, entry_price=price, entry_fee=cost, entry_order=index)
        return []
    assert uid == -1
    remaining, legs = quantity, []
    for current_uid, state in outstanding.items():
        if target_uid >= 0 and current_uid != target_uid:
            continue
        if state['cid'] != cid or state['side'] != -side or not state['remaining']:
            continue
        amount = min(remaining, state['remaining']); state['remaining'] -= amount; remaining -= amount
        gross = state['side']*amount*(price-state['entry_price'])*VALUE[symbol]
        entry_fee = state['entry_fee']*amount/state['quantity']
        exit_fee = cost*amount/quantity
        legs.append(dict(uid=current_uid, 親=cid, 方向=state['side'], 枚数=amount,
            新規行=state['entry_row'], 返済行=row, 新規価格=state['entry_price'], 返済価格=price,
            粗損益=gross, 新規料金配分=entry_fee, 返済料金配分=exit_fee,
            収支=gross-entry_fee-exit_fee, 返済注文=index, 理由=int(order[6])))
        if remaining == 0:
            break
    assert remaining == 0, ('返済数量が実新規残数量を超過', order, target_uid)
    return legs


def outstanding_at(orders: np.ndarray, uids: np.ndarray, symbol: str,
                   target_uids: np.ndarray | None = None) -> dict:
    """
    機能: 受領した実注文接頭だけから、各UIDの残数量を復元する。
    引数: orders(ndarray)、uids(ndarray[int64])、symbol(str)、target_uids(ndarray|None)。
    返り値: dictは実新規由来のUID帳簿。返済済UIDも残数量ゼロで保持する。
    """
    assert len(orders) == len(uids)
    targets = np.full(len(orders), -1, np.int64) if target_uids is None else target_uids
    assert len(targets) == len(orders)
    state = {}
    for i, order in enumerate(orders):
        apply_order(state, order, int(uids[i]), i, symbol, int(targets[i]))
    return state


def reconstruct(key: tuple[str, str], orders: np.ndarray, uids: np.ndarray, quotes: dict,
                target_uids: np.ndarray | None = None, finish: bool = True) -> dict:
    """
    機能: 実注文だけから親・UID・実玉・全行清算時価と料金を独立に求める。
    引数: key(tuple[str,str])、orders/uids(ndarray)、quotes(dict)、target_uids(ndarray|None)、finish(bool)。
    返り値: dictは独立会計台帳。価格欠測行の時価は直前正常気配のみを保持する。
    """
    symbol = key[1]; multiplier = VALUE[symbol]; valid = normal_mask(quotes); n = len(valid)
    assert orders.shape == (len(uids), 8) and n > 0
    targets = np.full(len(orders), -1, np.int64) if target_uids is None else target_uids
    assert targets.shape == uids.shape and np.all(np.isfinite(orders))
    charge, cash_delta = np.zeros(n), np.zeros(n)
    long_delta, short_delta = np.zeros(n, np.int64), np.zeros(n, np.int64)
    reserved = np.zeros(n, np.int64); order_fees = np.zeros(len(orders), np.int64)
    state, legs, parent_index = {}, [], {}; cursor = 0; previous = 0; reserve = 0
    while cursor < len(orders):
        row = int(orders[cursor, 0]); assert previous <= row < n
        reserved[previous:row] = reserve
        while cursor < len(orders) and int(orders[cursor, 0]) == row:
            order = orders[cursor]
            source, cid, side, quantity, new = map(int, (order[1], order[2], order[3], order[4], order[7]))
            assert all(order[k] == int(order[k]) for k in (0, 1, 2, 3, 4, 6, 7))
            assert 0 <= source < row and side in (-1, 1) and new in (0, 1) and 0 < quantity <= CAP[symbol]
            assert valid[row] and order[5] == quotes['ask' if side > 0 else 'bid'][row]
            cost = fee(quantity, symbol); order_fees[cursor] = cost; charge[row] += cost
            cash_delta[row] -= side*quantity*order[5]
            if (new and side > 0) or (not new and side < 0):
                long_delta[row] += quantity if new else -quantity
            else:
                short_delta[row] += quantity if new else -quantity
            if cid not in parent_index:
                assert new
                parent_index[cid] = dict(親=cid, 新規行=row, 最終返済行=row, 方向=side,
                    枚数=0, 費用=0, 粗損益=0.)
            parent = parent_index[cid]; parent['費用'] += cost
            if new:
                parent['枚数'] += quantity
            else:
                parent['最終返済行'] = row
            new_legs = apply_order(state, order, int(uids[cursor]), cursor, symbol, int(targets[cursor]))
            parent['粗損益'] += sum(leg['粗損益'] for leg in new_legs); legs.extend(new_legs)
            cursor += 1
        reserve = sum(fee(item['remaining'], symbol) for item in state.values() if item['remaining'])
        previous = row
    reserved[previous:] = reserve
    long_qty, short_qty = np.cumsum(long_delta), np.cumsum(short_delta)
    assert np.all((long_qty >= 0) & (long_qty <= CAP[symbol]))
    assert np.all((short_qty >= 0) & (short_qty <= CAP[symbol]))
    paid = np.cumsum(charge); cash = np.cumsum(cash_delta)
    last = np.maximum.accumulate(np.where(valid, np.arange(n), -1))
    assert not np.any((last < 0) & ((long_qty != 0) | (short_qty != 0)))
    bid = np.where(last >= 0, quotes['bid'][np.maximum(last, 0)], 0.)
    ask = np.where(last >= 0, quotes['ask'][np.maximum(last, 0)], 0.)
    marked = cash+long_qty*bid-short_qty*ask
    equity = marked*multiplier-paid; liquidation = equity-reserved
    assert np.all(np.isfinite(equity))
    parents = list(parent_index.values())
    for parent in parents:
        parent['収支'] = parent['粗損益']-parent['費用']
    uid_accounts = []
    for uid, item in state.items():
        selected = [leg for leg in legs if leg['uid'] == uid]
        uid_accounts.append(dict(uid=uid, 親=item['cid'], 方向=item['side'], 枚数=item['quantity'],
            残枚数=item['remaining'], 新規行=item['entry_row'], 新規価格=item['entry_price'],
            収支=sum(leg['収支'] for leg in selected), 実玉数=len(selected)))
    if finish:
        assert long_qty[-1] == short_qty[-1] == reserved[-1] == 0
        assert all(item['remaining'] == 0 for item in state.values())
        for value in (sum(p['収支'] for p in parents), sum(u['収支'] for u in uid_accounts),
                      sum(l['収支'] for l in legs)):
            assert np.isclose(value, equity[-1], atol=1e-5, rtol=1e-12), (value, equity[-1])
        assert sum(p['費用'] for p in parents) == paid[-1] == order_fees.sum()
    summary = dict(session=key[0], symbol=symbol, **metric([p['収支'] for p in parents]),
        費用=int(order_fees.sum()), 新規枚数=sum(u['枚数'] for u in uid_accounts),
        勝ち枚数=sum(l['枚数'] for l in legs if l['収支'] > 0),
        負け枚数=sum(l['枚数'] for l in legs if l['収支'] < 0),
        零枚数=sum(l['枚数'] for l in legs if l['収支'] == 0),
        最大買枚数=int(long_qty.max()), 最大売枚数=int(short_qty.max()),
        最大DD=float((np.maximum.accumulate(np.maximum(equity, 0.))-equity).max()),
        最悪時価=float(min(0., equity.min())), 注文件数=len(orders), 全会計合格=bool(finish))
    return dict(key=key, orders=orders, order_uids=uids, exit_target_uids=targets, order_fees=order_fees,
        parent=parents, uid_accounts=uid_accounts, actual_legs=legs, summary=summary,
        equity_yen=equity, liquidation_yen=liquidation, reserved_exit_fees=reserved,
        long_qty=long_qty, short_qty=short_qty, cumulative_fees=paid)


def apply_policy(base: dict, quotes: dict, policy: dict) -> dict:
    """
    機能: 最初の当時清算利益または損失予算の到達で元注文接頭を止める。
    引数: base(dict)は実注文から独立再構成した基準、quotes/policy(dict)は当時気配と固定12政策。
    返り値: dictは次正常気配で残UID別返済した新台帳。将来玉テンプレートは使用しない。
    """
    symbol = base['key'][1]; valid = normal_mask(quotes)
    unit = TICK[symbol]*QUANTITY[symbol]*VALUE[symbol]
    goal = policy['profit_ticks']*unit
    loss = policy['loss_ticks']*unit if policy['loss_ticks'] is not None else None
    hit = valid & (base['liquidation_yen'] >= goal)
    if loss is not None:
        hit |= valid & (base['liquidation_yen'] <= -loss)
    positions = np.flatnonzero(hit)
    if not len(positions):
        result = reconstruct(base['key'], base['orders'], base['order_uids'], quotes)
        result['control'] = dict(発動=False, 目標=goal, 損失予算=loss)
        return result
    decision = int(positions[0]); is_profit = base['liquidation_yen'][decision] >= goal
    prefix = base['orders'][:, 0] <= decision
    orders, uids = base['orders'][prefix].copy(), base['order_uids'][prefix].copy()
    outstanding = outstanding_at(orders, uids, symbol)
    remaining = [item for item in outstanding.values() if item['remaining']]
    targets = np.full(len(orders), -1, np.int64); fill_row = decision
    if remaining:
        future = np.flatnonzero(valid[decision+1:]); assert len(future), '場内の次正常気配がない'
        fill_row = decision+1+int(future[0]); appended = []
        for item in remaining:
            side = -item['side']; price = quotes['ask' if side > 0 else 'bid'][fill_row]
            appended.append([fill_row, decision, item['cid'], side, item['remaining'], price,
                             94 if is_profit else 95, 0])
        orders = np.concatenate((orders, np.asarray(appended, float)))
        uids = np.concatenate((uids, np.full(len(appended), -1, np.int64)))
        targets = np.concatenate((targets, np.array([item['uid'] for item in remaining], np.int64)))
    result = reconstruct(base['key'], orders, uids, quotes, targets)
    np.testing.assert_allclose(result['equity_yen'][:decision+1], base['equity_yen'][:decision+1], atol=1e-5, rtol=1e-12)
    np.testing.assert_array_equal(orders[:prefix.sum()], base['orders'][prefix])
    assert not np.any(orders[(orders[:, 0] > decision) & (orders[:, 7] == 1)])
    assert result['long_qty'][fill_row:].sum() == result['short_qty'][fill_row:].sum() == 0
    result['control'] = dict(発動=True, 種別='利益目標' if is_profit else '損失予算',
        判断行=decision, 判断原seq=int(quotes['seq'][decision]), 判断価格時計=float(quotes['time_s'][decision]),
        返済行=fill_row, 返済原seq=int(quotes['seq'][fill_row]), 返済価格時計=float(quotes['time_s'][fill_row]),
        判断時清算利益=float(base['liquidation_yen'][decision]), 実返済後収支=result['summary']['収支'],
        判断から返済の悪化=result['summary']['収支']-float(base['liquidation_yen'][decision]),
        元接頭注文件数=int(prefix.sum()), 残UID別注文数=len(remaining), 目標=goal, 損失予算=loss,
        以後新規なし=True, 未来返済テンプレート参照=False)
    return result
