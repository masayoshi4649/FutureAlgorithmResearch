"""ゲート実装を呼ばず、公開源注文・整数料金・確定時刻から採否を復元する。"""

from collections import defaultdict
import math
import numpy as np
import common


def completed(ready, source, virtual):
    """
    機能: 全採用の仮想実注文を親ごとに集計し、元紙上親終了後の公開時計を復元する。
    引数: ready(dict)、source(dict[str,ndarray8列])、virtual(dict)。
    返り値: list[dict]。途中返済の利益だけでは親を確定しない。
    """
    prices = np.asarray(ready['last'])
    times = np.asarray(ready['time_s'])
    n = len(prices)
    cut = int(np.searchsorted(times, ready['limit'], side='left'))
    value, fee10 = (1000, 418) if ready['symbol'] == 'TOPIX' else (10, 110)
    paper_close, paper_end = {}, {}
    for s, name in enumerate(common.SOURCES):
        live = {}
        for order in source[name]:
            row = int(order[0])
            if row >= min(n, cut):
                break
            cid, qty = int(order[2]), int(order[4])
            if order[7]:
                assert cid not in live
                live[cid] = qty
            else:
                assert cid in live and qty <= live[cid]
                live[cid] -= qty
                if live[cid] == 0:
                    if row + 1 < n:
                        paper_close[s, cid] = min(row + 1, cut)
                        paper_end[s, cid] = row
    entries, left, totals = {}, {}, {}
    for order in virtual['orders']:
        row, _, s, cid, side, qty, price, reason, new, uid = order
        row, s, cid, side, qty, reason, uid = map(int, (row, s, cid, side, qty, reason, uid))
        assert price == prices[row]
        fee = qty * fee10 // 10
        record = totals.setdefault((s, cid), dict(source=common.SOURCES[s], symbol=ready['symbol'], cid=cid,
            allocated_quantity=0, gross=0., fees=0, net=0., entry_row=None, allocated_flat_row=None,
            publish_row=None, publish_time=None, session=ready['session']))
        record['fees'] += fee
        if new:
            assert uid not in entries
            entries[uid] = side, qty, price
            left[uid] = qty
            record.update(allocated_quantity=qty, entry_row=row, entry_price=float(price), side=side)
        else:
            es, eq, ep = entries[uid]
            assert -es == side and qty <= left[uid]
            left[uid] -= qty
            record['gross'] += es * qty * (price - ep) * value
            if left[uid] == 0:
                record['allocated_flat_row'] = row
            record['last_exit_row'] = row
            if reason == 99:
                paper_close[s, cid] = row
                paper_end[s, cid] = row
                record['reason'] = 99
    result = []
    for (s, cid), record in totals.items():
        if cut < n and ((s, cid) not in paper_close or paper_close[s, cid] >= cut):
            paper_close[s, cid] = cut
            paper_end[s, cid] = cut
            record['reason'] = 99
        if record['allocated_flat_row'] is None or (s, cid) not in paper_close:
            continue
        publish = paper_close[s, cid]
        assert publish >= record['allocated_flat_row']
        if publish >= n:
            continue
        end = paper_end[s, cid]
        reason = record.get('reason')
        if reason is None:
            closing = [order for order in source[common.SOURCES[s]] if int(order[0]) == end and int(order[2]) == cid and order[7] == 0]
            assert closing
            reason = int(closing[-1][6])
        record.update(net=record['gross'] - record['fees'], publish_row=publish,
            publish_time=float(times[publish]), source_end_decision_row=end,
            source_ended=True, publication='source_end', reason=reason)
        result.append(record)
    return sorted(result, key=lambda r: (r['publish_row'], common.SOURCES.index(r['source']), r['entry_row']))


def evaluate(gate, eligible, quantity):
    """
    機能: 既に公開された親の確定損益だけから、比率又は連敗の採否を復元する。
    引数: gate(dict)、eligible(list[dict])、quantity(int)。
    返り値: dictの採否、利益損失、割合、連敗と使用履歴。
    """
    mode = gate['mode']
    window = int(gate.get('window', 0))
    loss_count = int(gate.get('loss_count', 0))
    recent = eligible[-window:] if window else eligible[-loss_count:] if loss_count else []
    profit = sum(max(float(record['net']), 0.) for record in recent)
    loss = sum(max(-float(record['net']), 0.) for record in recent)
    share = profit / (profit + loss) if profit + loss else None
    streak = 0
    for record in reversed(eligible):
        if float(record['net']) < 0:
            streak += 1
        else:
            break
    warmup = mode == 'share' and len(eligible) < int(gate.get('minimum_completed', 4))
    if not quantity:
        allowed, reason = False, '無配分'
    elif mode == 'all':
        allowed, reason = True, '全採用'
    elif warmup:
        allowed, reason = True, '確定親不足'
    elif mode == 'share':
        if share is None:
            allowed, reason = True, '利益損失ともゼロ'
        else:
            allowed = share < float(gate['threshold']) if gate.get('reverse', False) else share >= float(gate['threshold'])
            reason = '金額割合を充足' if allowed else '金額割合が不足'
    elif mode == 'streak':
        allowed = streak < loss_count
        reason = '連敗上限未満' if allowed else '連敗上限に到達'
    else:
        raise AssertionError(mode)
    return dict(allowed=allowed, selected=recent, available=len(eligible),
        warmup=warmup, warmed=not warmup, profit=profit, loss=loss, net=profit-loss,
        profit_share=share, loss_streak=streak, reason=reason)


def execution(ready, source, budgets, gate, history=None, finish=True):
    """
    機能: 観測を前進させ、公開済み完了履歴のゲートと前行予約だけで実注文を復元する。
    引数: ready/source/budgets/gate(dict)、history(dict[str,list[dict]]又はNone)、finish(bool)。
    返り値: dictの実注文・整数目標・独立仮想注文・完了・採否証跡。
    """
    n = len(ready['last'])
    times = np.asarray(ready['time_s'])
    factor = 1 if ready['symbol'] == 'TOPIX' else 2
    slots = [budgets[name] * factor for name in common.SOURCES]
    assert sum(slots) <= 10 * factor
    stop = int(np.searchsorted(times, ready['limit'], side='left'))
    if finish:
        assert stop < n
    virtual = common.OLD.reference(ready, source, budgets)
    records = completed(ready, source, virtual)
    history = history or {name: [] for name in common.SOURCES}
    incoming = {name: list(history[name]) if gate.get('history_mode') == 'carry' else [] for name in common.SOURCES}
    for name in common.SOURCES:
        assert all(record['source'] == name for record in incoming[name])
    published = defaultdict(list)
    for s, name in enumerate(common.SOURCES):
        for j, order in enumerate(source[name]):
            if int(order[0]) < min(n, stop):
                published[int(order[0])].append((s, j, order))
    paper = [dict(cid=-1, side=0, initial=0, remaining=0, target=0) for _ in common.SOURCES]
    live = [dict(cid=-1, side=0, quantity=0, uid=-1) for _ in common.SOURCES]
    queue, orders, trace, gates = [], [], [], []
    uid = 0
    ended = False
    for row in range(n):
        if row >= stop:
            if not ended:
                for s, state in enumerate(live):
                    if state['quantity']:
                        orders.append([row, row, s, state['cid'], -state['side'], state['quantity'], ready['last'][row], 99, 0, state['uid']])
                        state.update(quantity=0, side=0)
            queue = []
            ended = True
            continue
        for decision, s, cid, side, qty, reason, new in queue:
            state = live[s]
            if new:
                assert state['quantity'] == 0
                state.update(cid=cid, side=side, quantity=qty, uid=uid)
                uid += 1
            else:
                assert state['cid'] == cid and state['side'] == -side and qty <= state['quantity']
                state['quantity'] -= qty
            orders.append([row, decision, s, cid, side, qty, ready['last'][row], reason, new, state['uid']])
            if not state['quantity']:
                state['side'] = 0
        queue = []
        for s, j, order in sorted(published[row], key=lambda v: v[:2]):
            state = paper[s]
            cid, side, qty = map(int, order[2:5])
            before = state['target']
            if order[7]:
                assert state['remaining'] == 0
                name = common.SOURCES[s]
                eligible = [record for record in incoming[name] + [r for r in records if r['source'] == name]
                    if record['publish_time'] < times[row]]
                decision = evaluate(gate, eligible, slots[s])
                gates.append(dict(row=row, time=float(times[row]), source=name, cid=cid, **decision))
                target = slots[s] if decision['allowed'] else 0
                state.update(cid=cid, side=side, initial=qty, remaining=qty, target=target, accepted=decision['allowed'])
                change = target
            else:
                assert state['cid'] == cid and side == -state['side'] and qty <= state['remaining']
                state['remaining'] -= qty
                state['target'] = slots[s] * state['remaining'] // state['initial'] if state['accepted'] else 0
                change = before - state['target']
                assert change >= 0
            trace.append([row, s, cid, j, state['side'], state['initial'], state['remaining'], state['target'], change, int(order[7])])
            if change:
                queue.append((row, s, cid, side, change, int(order[6]), int(order[7])))
    if finish:
        assert all(not state['quantity'] for state in live)
    return dict(orders=np.asarray(orders, float).reshape(-1, 10), target_trace=np.asarray(trace, float).reshape(-1, 10),
        terminal=live, slots=slots, virtual_result=virtual, completion_records=records, gate_trace=gates,
        history_out={name: incoming[name] + [record for record in records if record['source'] == name] for name in common.SOURCES})
