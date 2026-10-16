"""源別の固定予約枠を保ち、公開注文を次観測の実注文へ写す。"""

import numpy as np

SOURCES = ('GU', 'M3', 'C03')
ORDER_COLUMNS = ('実行行', '判断行', '源番号', '親ID', '売買', '数量', '価格', '理由', '新規', '新規UID')


def execute(ready, source_orders, budgets, finish=True):
    """
    機能: 紙上注文だけを順に公開し、整数目標を次有効観測で実行する。
    引数: ready(dict)、source_orders(dict[str,ndarray8列])、budgets(dict[str,int])、finish(bool)。
    返り値: dict。実注文10列・整数目標証跡・終端状態。将来の紙上成績を読まない。
    """
    prices = np.asarray(ready['last'])
    times = np.asarray(ready['time_s'])
    n = len(prices)
    assert n and np.isfinite(prices).all() and (prices > 0).all()
    assert np.all(np.diff(times) >= 0)
    factor = 1 if ready['symbol'] == 'TOPIX' else 2
    slots = [int(budgets[name])*factor for name in SOURCES]
    assert min(slots) >= 0 and sum(slots) <= 10*factor
    cut = int(np.searchsorted(times, ready['limit'], side='left'))
    if finish:
        assert cut < n, '場内清算後の有効観測が必要です'
    paper = []
    for s, name in enumerate(SOURCES):
        orders = np.asarray(source_orders[name], float).reshape(-1, 8)
        assert np.all(np.diff(orders[:, 0]) >= 0)
        for j, order in enumerate(orders):
            row = int(order[0])
            if row < min(n, cut):
                assert 0 <= row and int(order[1]) <= row
                paper.append((row, s, j, order))
    paper.sort(key=lambda v: v[:3])
    states = [dict(cid=-1, side=0, initial=0, remaining=0, target=0) for _ in SOURCES]
    plans, trace = [], []
    for row, s, order_index, order in paper:
        state = states[s]
        cid, side, quantity = int(order[2]), int(order[3]), int(order[4])
        assert quantity > 0 and quantity == order[4] and side in (-1, 1)
        if order[7] == 1:
            assert state['remaining'] == 0
            state.update(cid=cid, side=side, initial=quantity, remaining=quantity, target=slots[s])
            change = slots[s]
            new = 1
        else:
            assert order[7] == 0 and (cid, side) == (state['cid'], -state['side'])
            assert quantity <= state['remaining']
            state['remaining'] -= quantity
            target = slots[s]*state['remaining']//state['initial']
            assert target <= state['target']
            change = state['target']-target
            state['target'] = target
            new = 0
        trace.append((row, s, cid, order_index, state['side'], state['initial'], state['remaining'], state['target'], change, new))
        if change and row+1 < min(n, cut):
            plans.append((row+1, s, order_index, cid, side, change, int(order[6]), new, row))
    plans.sort(key=lambda v: v[:3])
    live = [dict(cid=-1, side=0, quantity=0, uid=-1) for _ in SOURCES]
    actual, uid = [], 0
    for row, s, j, cid, side, quantity, reason, new, decision in plans:
        state = live[s]
        if new:
            assert state['quantity'] == 0 and quantity <= slots[s]
            state.update(cid=cid, side=side, quantity=quantity, uid=uid)
            uid += 1
        else:
            assert state['cid'] == cid and state['side'] == -side and quantity <= state['quantity']
            state['quantity'] -= quantity
        actual.append((row, decision, s, cid, side, quantity, prices[row], reason, new, state['uid']))
        if not state['quantity']:
            state['side'] = 0
        assert sum(v['quantity'] for v in live if v['side'] > 0) <= 10*factor
        assert sum(v['quantity'] for v in live if v['side'] < 0) <= 10*factor
    if cut < n:
        for s, state in enumerate(live):
            if state['quantity']:
                actual.append((cut, cut, s, state['cid'], -state['side'], state['quantity'], prices[cut], 99, 0, state['uid']))
                state.update(quantity=0, side=0)
    if finish:
        assert all(not state['quantity'] for state in live)
    return dict(orders=np.asarray(actual, float).reshape(-1, 10),
                target_trace=np.asarray(trace, float).reshape(-1, 10),
                terminal=live, slots=slots, order_columns=ORDER_COLUMNS)
