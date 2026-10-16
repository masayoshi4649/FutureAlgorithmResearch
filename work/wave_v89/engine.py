"""源ごとの完了済み仮想成績で新しい親だけを採否判定する。"""

from copy import deepcopy
import math

import numpy as np

SOURCES = ('GU', 'M3', 'C03')
ORDER_COLUMNS = ('実行行', '判断行', '源番号', '親ID', '売買', '数量', '価格', '理由', '新規', '新規UID')
MULTIPLIERS = dict(TOPIX=1000., NK225=10.)
FEE_TENTHS = dict(TOPIX=418, NK225=110)


def decide(gate, records, clock, quantity):
    """
    機能: 判断時計より厳密に過去の完了だけで新規親の採否を決める。
    引数: gate(dict)、records(list[dict])、clock(float)、quantity(int)。
    返り値: dict。最少完了数未充足は許可し、無配分は成績に関係なく拒否する。
    """
    mode = gate.get('mode', 'all')
    window = int(gate.get('window', 0))
    threshold = float(gate.get('threshold', 0.))
    minimum = int(gate.get('minimum_completed', 4))
    loss_count = int(gate.get('loss_count', 0))
    reverse = gate.get('reverse', False)
    assert isinstance(reverse, bool) and (not reverse or mode == 'share')
    assert mode in ('all', 'share', 'streak') and window >= 0 and minimum >= 0
    assert mode != 'share' or window >= minimum > 0
    assert mode != 'streak' or loss_count > 0
    assert math.isfinite(threshold)
    available = [value for value in records if value['publish_time'] < clock]
    selected = available[-window:] if window else available[-loss_count:] if loss_count else []
    profit = sum(max(value['net'], 0.) for value in selected)
    loss = sum(max(-value['net'], 0.) for value in selected)
    total = sum(value['net'] for value in selected)
    share = profit / (profit + loss) if profit + loss else None
    warmup = mode == 'share' and len(available) < minimum
    streak = 0
    for record in reversed(available):
        if record['net'] >= 0:
            break
        streak += 1
    if not quantity:
        allowed, reason = False, '無配分'
    elif mode == 'all':
        allowed, reason = True, '常時採用対照'
    elif warmup:
        allowed, reason = True, '完了窓の準備中'
    elif mode == 'share':
        allowed = share is None or (share < threshold if reverse else share >= threshold)
        if share is None:
            reason = '過去窓の金額分母が0'
        elif reverse:
            reason = '過去の金額利益割合が基準未満の逆対照' if allowed else '過去の金額利益割合が基準以上の逆対照見送り'
        else:
            reason = '過去の金額利益割合が基準以上' if allowed else '過去の金額利益割合が基準未達'
    else:
        allowed = streak < loss_count
        reason = '仮想連敗が停止基準未満' if allowed else '仮想連敗が停止基準以上'
    return dict(allowed=allowed, reason=reason, mode=mode, window=window,
                threshold=threshold, minimum_completed=minimum, minimum_applies=mode == 'share',
                loss_count=loss_count, reverse=reverse,
                loss_streak=streak, available=len(available), selected=deepcopy(selected),
                warmup=warmup, warmed=not warmup, profit=profit, loss=loss, net=total, profit_share=share)


# ----------------------------------------


def execute(ready, source_orders, budgets, gate=None, history=None, finish=True):
    """
    機能: 常時仮想執行と採用親の実執行を、公開行順に独立して進める。
    引数: ready(dict)、source_orders(dict[str,ndarray8列])、budgets(dict[str,int])、
        gate(dict又はNone)、history(dict[str,list[dict]]又はNone)、finish(bool)。
    返り値: dict。旧形式実注文、仮想注文、完了公開履歴、採否根拠、終端状態。
    """
    gate = dict(gate or dict(mode='all', window=0, threshold=0.))
    publication = gate.get('publication', 'source_end')
    assert publication == 'source_end'
    prices = np.asarray(ready['last'])
    times = np.asarray(ready['time_s'])
    n = len(prices)
    assert n and len(times) == n and np.isfinite(prices).all() and (prices > 0).all()
    assert np.isfinite(times).all() and np.all(np.diff(times) >= 0)
    factor = 1 if ready['symbol'] == 'TOPIX' else 2
    slots = [int(budgets[name])*factor for name in SOURCES]
    assert all(budgets[name] == int(budgets[name]) for name in SOURCES)
    assert min(slots) >= 0 and sum(slots) <= 10*factor
    cut = int(np.searchsorted(times, ready['limit'], side='left'))
    if finish:
        assert cut < n, '場内清算後の有効観測が必要です'
    value, fee_tenths = MULTIPLIERS[ready['symbol']], FEE_TENTHS[ready['symbol']]
    history_mode = gate.get('history_mode', 'session')
    assert history_mode in ('session', 'carry')
    prior = deepcopy(history) if history is not None and history_mode == 'carry' else {name: [] for name in SOURCES}
    assert set(prior) == set(SOURCES)
    for s, name in enumerate(SOURCES):
        for record in prior[name]:
            assert record['source'] == name and record['symbol'] == ready['symbol']
            assert record['allocated_quantity'] == slots[s] and slots[s] > 0
            assert math.isfinite(record['publish_time']) and math.isfinite(record['net'])
        assert all(a['publish_time'] <= b['publish_time'] for a, b in zip(prior[name], prior[name][1:]))
    published = {}
    for s, name in enumerate(SOURCES):
        source = np.asarray(source_orders[name], float).reshape(-1, 8)
        current = source[(source[:, 0] >= 0) & (source[:, 0] < min(n, cut))]
        assert np.all(np.diff(current[:, 0]) >= 0)
        for j, order in enumerate(source):
            row = int(order[0])
            if row < min(n, cut):
                assert 0 <= row and order[0] == row and 0 <= int(order[1]) <= row
                published.setdefault(row, []).append((s, j, order))
    for items in published.values():
        items.sort(key=lambda item: item[:2])
    paper = [dict(cid=-1, side=0, initial=0, remaining=0, target=0, accepted=False) for _ in SOURCES]
    virtual_live = [dict(cid=-1, side=0, quantity=0, uid=-1) for _ in SOURCES]
    actual_live = [dict(cid=-1, side=0, quantity=0, uid=-1) for _ in SOURCES]
    virtual_orders, actual_orders, virtual_trace, actual_trace = [], [], [], []
    completions, gate_trace, pending = [], [], {}
    virtual_parents = {}
    counters = dict(virtual=0, actual=0)

    def fill(world, live, orders, row, decision, s, cid, side, quantity, reason, new):
        """
        機能: 一つの注文を当行CurrentPriceで全量執行し、UIDと残数を更新する。
        引数: world(str)、live/ orders(list)、row/decision/s/cid/side/quantity/reason/new(int)。
        返り値: None。常時仮想だけが仮想親の確定会計へ計上される。
        """
        assert quantity > 0
        state = live[s]
        if new:
            assert not state['quantity'] and quantity <= slots[s]
            state.update(cid=cid, side=side, quantity=quantity, uid=counters[world])
            counters[world] += 1
        else:
            assert state['cid'] == cid and state['side'] == -side and quantity <= state['quantity']
            state['quantity'] -= quantity
        orders.append((row, decision, s, cid, side, quantity, prices[row], reason, new, state['uid']))
        if world == 'virtual':
            key = s, cid
            charge = quantity*fee_tenths//10
            if new:
                assert key not in virtual_parents
                virtual_parents[key] = dict(source=SOURCES[s], symbol=ready['symbol'], session=ready['session'],
                    cid=cid, allocated_quantity=slots[s], entry_row=row, entry_price=float(prices[row]),
                    side=side, remaining=quantity, gross=0., fees=charge, net=-float(charge),
                    last_exit_row=None, allocated_flat_row=None, completed=False)
            else:
                parent = virtual_parents[key]
                parent['remaining'] -= quantity
                parent['gross'] += parent['side']*(prices[row]-parent['entry_price'])*quantity*value
                parent['fees'] += charge
                parent['net'] = parent['gross']-parent['fees']
                parent['last_exit_row'] = row
                if not parent['remaining']:
                    parent['allocated_flat_row'] = row
        if not state['quantity']:
            state['side'] = 0
        assert sum(item['quantity'] for item in live if item['side'] > 0) <= 10*factor
        assert sum(item['quantity'] for item in live if item['side'] < 0) <= 10*factor

    def complete(s, cid, row, decision, source_ended, reason):
        """
        機能: 実配分が全返済済みの仮想親だけを完了履歴へ初公開する。
        引数: s/cid/row/decision/reason(int)、source_ended(bool)。
        返り値: None。未新規・未返済・重複公開は履歴へ加えない。
        """
        key = s, cid
        if key not in virtual_parents:
            return
        parent = virtual_parents[key]
        if parent['completed'] or parent['remaining']:
            return
        if not source_ended:
            return
        parent['completed'] = True
        record = {name: parent[name] for name in ('source', 'symbol', 'session', 'cid', 'allocated_quantity',
                  'entry_row', 'entry_price', 'side', 'gross', 'fees', 'net', 'last_exit_row', 'allocated_flat_row')}
        record.update(publish_row=row, publish_time=float(times[row]), source_end_decision_row=decision,
                      source_ended=source_ended, reason=reason, publication=publication)
        name = SOURCES[s]
        assert not prior[name] or prior[name][-1]['publish_time'] <= record['publish_time']
        prior[name].append(record)
        completions.append(record)

    events = sorted(set(published) | {row+1 for row in published if row+1 < min(n, cut)} |
                    ({cut} if cut < n else set()))
    for row in events:
        if row == cut:
            for s in range(len(SOURCES)):
                for world, live, orders in (('virtual', virtual_live, virtual_orders), ('actual', actual_live, actual_orders)):
                    state = live[s]
                    if state['quantity']:
                        fill(world, live, orders, row, row, s, state['cid'], -state['side'], state['quantity'], 99, 0)
                for ps, cid in tuple(virtual_parents):
                    if ps == s:
                        complete(s, cid, row, row, True, 99)
            pending.clear()
            continue
        for decision, s, j, cid, side, quantity, reason, new, accepted, source_ended in pending.pop(row, []):
            if quantity:
                fill('virtual', virtual_live, virtual_orders, row, decision, s, cid, side, quantity, reason, new)
                if accepted:
                    fill('actual', actual_live, actual_orders, row, decision, s, cid, side, quantity, reason, new)
            if not new:
                complete(s, cid, row, decision, source_ended, reason)
        for s, j, order in published.get(row, []):
            state = paper[s]
            cid, side, quantity = int(order[2]), int(order[3]), int(order[4])
            assert quantity > 0 and quantity == order[4] and side in (-1, 1)
            assert cid == order[2]
            if order[7] == 1:
                assert not state['remaining']
                answer = decide(gate, prior[SOURCES[s]], float(times[row]), slots[s])
                gate_trace.append(dict(row=row, time=float(times[row]), source=SOURCES[s], source_index=s,
                    cid=cid, side=side, allocated_quantity=slots[s], **answer))
                state.update(cid=cid, side=side, initial=quantity, remaining=quantity,
                             target=slots[s], accepted=answer['allowed'])
                change, new = slots[s], 1
            else:
                assert order[7] == 0 and (cid, side) == (state['cid'], -state['side'])
                assert quantity <= state['remaining']
                before = state['target']
                state['remaining'] -= quantity
                state['target'] = slots[s]*state['remaining']//state['initial']
                assert state['target'] <= before
                change, new = before-state['target'], 0
            source_ended = state['remaining'] == 0
            base_trace = (row, s, cid, j, state['side'], state['initial'], state['remaining'])
            virtual_trace.append(base_trace+(state['target'], change, new))
            actual_trace.append(base_trace+(state['target'] if state['accepted'] else 0,
                                            change if state['accepted'] else 0, new))
            if (change or source_ended) and row+1 < min(n, cut):
                pending.setdefault(row+1, []).append((row, s, j, cid, side, change, int(order[6]),
                                                      new, state['accepted'], source_ended))
    if finish:
        assert all(not state['quantity'] for state in virtual_live+actual_live)
        assert all(parent['completed'] for parent in virtual_parents.values())
    virtual = dict(orders=np.asarray(virtual_orders, float).reshape(-1, 10),
        target_trace=np.asarray(virtual_trace, float).reshape(-1, 10), terminal=virtual_live,
        slots=slots, order_columns=ORDER_COLUMNS)
    return dict(orders=np.asarray(actual_orders, float).reshape(-1, 10),
        target_trace=np.asarray(actual_trace, float).reshape(-1, 10), terminal=actual_live,
        slots=slots, order_columns=ORDER_COLUMNS, virtual_result=virtual,
        completion_records=completions, gate_trace=gate_trace, history_out=prior,
        virtual_parent_states=deepcopy(list(virtual_parents.values())), gate=gate)
