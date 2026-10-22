"""実注文ごとの切捨て料金と親単位の損益を、全行清算時価へ結び付ける。"""

from decimal import Decimal, ROUND_FLOOR
import numpy as np

from specification import CAP, FEE, VALUE


def metric(values: list[float]) -> dict:
    """
    機能: 勝ち負け親を区別して損益と損小利大の指標を集計する。
    引数: values(list[float])は料金後の完結親収支。
    返り値: dict。無取引・零収支を勝ちへ数えない。
    """
    a = np.asarray(values, float)
    wins, losses = a[a > 0], a[a < 0]
    gain, loss = float(wins.sum()), float(-losses.sum())
    return dict(利益=gain, 損失=loss, 収支=float(a.sum()), 親数=len(a), 勝ち親=len(wins), 負け親=len(losses),
        零親=int((a == 0).sum()), PF=gain / loss if loss > 0 else None,
        利益割合=gain / (gain + loss) if gain + loss > 0 else None,
        平均利益=float(wins.mean()) if len(wins) else None,
        平均損失=float(-losses.mean()) if len(losses) else None,
        平均損益比=float(wins.mean() / -losses.mean()) if len(wins) and len(losses) else None)


def account(key: tuple[str, str], ready: dict, quotes: dict, values: tuple, case: dict) -> tuple[dict, dict]:
    """
    機能: 注文・玉・親・全行時価を独立に足し直し、料金後会計を作る。
    引数: key(tuple)、ready/quotes/case(dict)、values(tuple)は実再生出力。
    返り値: tuple[dict,dict]。小集計と保存用会計。再生はしない。
    """
    symbol = key[1]; multiplier = VALUE[symbol]; fee = FEE[symbol]
    orders, trades, curve, stats, cycles, uids, events, states, proofs = values
    n = len(ready['last'])
    assert len(curve) == n and len(states) == n
    assert stats[9] == 0 and curve[-1, 2] == curve[-1, 3] == states[-1, 5] == states[-1, 9] == 0
    assert np.all(np.isfinite(curve))
    fees = np.array([int((Decimal(str(fee)) * Decimal(int(o[4]))).to_integral_value(rounding=ROUND_FLOOR))
                     for o in orders], np.int64)
    charge = np.zeros(n); cash = np.zeros(n); longdelta = np.zeros(n); shortdelta = np.zeros(n)
    realized = np.zeros(n)
    for i, o in enumerate(orders):
        row, source, cid, side, qty, price, reason, new = o
        row, source, cid, side, qty, new = map(int, (row, source, cid, side, qty, new))
        assert 0 <= source < row < n and side in (-1, 1) and 0 < qty <= CAP[symbol] and price > 0
        if case['execution'] != '旧現在値参考':
            assert quotes['quote_valid'][row]
            assert price == quotes['ask' if side > 0 else 'bid'][row]
        else:
            assert price == ready['last'][row]
        if new:
            assert uids[i] >= 0
        else:
            assert uids[i] == -1
        charge[row] += fees[i]; cash[row] -= side * qty * price
        if (new and side > 0) or (not new and side < 0):
            longdelta[row] += qty if new else -qty
        else:
            shortdelta[row] += qty if new else -qty
    longqty = np.cumsum(longdelta); shortqty = np.cumsum(shortdelta)
    cash = np.cumsum(cash); cumulative_fee = np.cumsum(charge)
    assert np.all((0 <= longqty) & (longqty <= CAP[symbol])) and np.all((0 <= shortqty) & (shortqty <= CAP[symbol]))
    np.testing.assert_array_equal(curve[:, 2], longqty)
    np.testing.assert_array_equal(curve[:, 3], shortqty)
    np.testing.assert_allclose(curve[:, 5], cash, atol=1e-7, rtol=1e-12)
    seen = set()
    for i, o in enumerate(orders):
        if int(o[7]) != 1:
            continue
        uid = int(uids[i]); assert uid not in seen; seen.add(uid)
        legs = trades[trades[:, 1] == uid]
        assert len(legs) and int(legs[:, 3].sum()) == int(o[4])
        assert np.all(legs[:, 2] == o[3]) and np.all(legs[:, 4] == o[5]) and np.all(legs[:, 6] == o[0])
    if len(trades):
        assert set(map(int, trades[:, 1])).issubset(seen)
        expected = trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4])
        np.testing.assert_allclose(trades[:, 10], expected, atol=1e-7, rtol=1e-12)
        np.add.at(realized, trades[:, 7].astype(int), expected)
    realized = np.cumsum(realized)
    np.testing.assert_allclose(curve[:, 1], realized, atol=1e-7, rtol=1e-12)
    if case['execution'] == '旧現在値参考':
        marked = cash + (longqty - shortqty) * ready['last']
    else:
        last = np.maximum.accumulate(np.where(quotes['quote_valid'], np.arange(n), -1))
        bid = np.where(last >= 0, quotes['bid'][np.maximum(last, 0)], 0.)
        ask = np.where(last >= 0, quotes['ask'][np.maximum(last, 0)], 0.)
        marked = cash + longqty * bid - shortqty * ask
    np.testing.assert_allclose(curve[:, 0], marked, atol=1e-7, rtol=1e-12)
    equity = marked * multiplier - cumulative_fee
    parent = []
    for c in cycles:
        cid = int(c[0]); mask = orders[:, 2] == cid; legs = trades[trades[:, 0] == cid]
        gross = float(legs[:, 10].sum() * multiplier); cost = int(fees[mask].sum())
        assert int(orders[mask & (orders[:, 7] == 1), 4].sum()) == int(legs[:, 3].sum())
        assert np.isclose(gross, c[3] * multiplier, atol=.0001)
        parent.append(dict(親=cid, 新規行=int(c[1]), 最終返済行=int(c[2]), 方向=int(c[8]),
            枚数=int(orders[mask & (orders[:, 7] == 1), 4].sum()), 費用=cost, 粗損益=gross, 収支=gross - cost))
    assert len(parent) == int((orders[:, 7] == 1).sum())
    net = sum(p['収支'] for p in parent)
    assert np.isclose(net, equity[-1], atol=.0001)
    assert np.isclose(net, realized[-1] * multiplier - fees.sum(), atol=.0001)
    m = metric([p['収支'] for p in parent])
    legs_net = []
    for leg in trades:
        uid = int(leg[1]); entry_index = int(np.flatnonzero(uids == uid)[0])
        entry = orders[entry_index]
        matching = (orders[:, 0] == leg[7]) & (orders[:, 2] == leg[0]) & (orders[:, 7] == 0)
        exits = np.flatnonzero(matching)
        # 同行の返済はこの手法の単一役割・単一方向なので枚数比例で注文料金を分配できる。
        exit_fee = float(fees[exits].sum()) * leg[3] / orders[exits, 4].sum()
        legs_net.append(leg[10] * multiplier - fees[entry_index] * leg[3] / entry[4] - exit_fee)
    assert np.isclose(sum(legs_net), net, atol=.0001)
    lotswin = sum(int(t[3]) for t, x in zip(trades, legs_net) if x > 0)
    lotsloss = sum(int(t[3]) for t, x in zip(trades, legs_net) if x < 0)
    lotszero = sum(int(t[3]) for t, x in zip(trades, legs_net) if x == 0)
    summary = dict(session=key[0], symbol=symbol, **m, 費用=int(fees.sum()),
        新規枚数=int(orders[orders[:, 7] == 1, 4].sum()), 勝ち枚数=lotswin, 負け枚数=lotsloss, 零枚数=lotszero,
        最大買枚数=int(longqty.max()), 最大売枚数=int(shortqty.max()),
        最大DD=float((np.maximum.accumulate(np.maximum(equity, 0.)) - equity).max()),
        最悪時価=float(min(0., equity.min())), 注文件数=len(orders), 全会計合格=True)
    ledger = dict(key=key, case=case, orders=orders, trades=trades, cycles=cycles, order_uids=uids,
        execution_events=events, execution_states=states, limit_events=proofs, curve_points=curve,
        order_fees=fees, equity_yen=equity, parent=parent, leg_net_yen=np.asarray(legs_net), summary=summary)
    return summary, ledger


def aggregate(rows: list[dict], parents: list[dict], sessions: list[str]) -> dict:
    """
    機能: 期間・赤字場・最大利益日除外を料金後の親会計から算出する。
    引数: rows/parents(list[dict])、sessions(list[str])は固定順の全場。
    返り値: dict。無取引を黒字へ数えず、全既知比較として扱う。
    """
    assert len(rows) == len(sessions) and {r['session'] for r in rows} == set(sessions)
    total = metric([p['収支'] for p in parents])
    active = [r for r in rows if r['親数'] > 0]
    day = {}
    for r in rows:
        name = r['session'].split('_')[0]; day[name] = day.get(name, 0.) + r['収支']
    best = max(day, key=day.get)
    best_session = max(rows, key=lambda r: r['収支'])
    periods = {}
    for name, subset in (('前16', sessions[:16]), ('後17', sessions[16:])):
        period = [r for r in rows if r['session'] in subset]
        gains = sum(r['利益'] for r in period); losses = sum(r['損失'] for r in period)
        periods[name] = dict(場数=len(period), 活動場=sum(r['親数'] > 0 for r in period),
            黒字場=sum(r['収支'] > 0 for r in period), 赤字場=sum(r['収支'] < 0 for r in period),
            収支=sum(r['収支'] for r in period), 利益=gains, 損失=losses, PF=gains / losses if losses else None)
    return dict(**total, 全場=len(rows), 活動場=len(active), 黒字場=sum(r['収支'] > 0 for r in rows),
        赤字場=sum(r['収支'] < 0 for r in rows), 無取引場=len(rows) - len(active),
        最悪場=min(rows, key=lambda r: r['収支'])['session'], 最悪場収支=min(r['収支'] for r in rows),
        最大利益日=best, 最大利益日除外収支=total['収支'] - day[best],
        最大利益場=best_session['session'], 最大利益場除外収支=total['収支'] - best_session['収支'],
        費用=sum(r['費用'] for r in rows), 期間別=periods)
