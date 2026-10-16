"""注文から全玉会計を復元し、B/Tの全判断を因果気配から独立検算する。"""

from decimal import Decimal, ROUND_CEILING
import importlib.util
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
NAME = '104全数監査の独立入力集計'
if NAME not in sys.modules:
    SPEC = importlib.util.spec_from_file_location(NAME, HERE/'入力と集計の独立部品.py')
    VALUE = importlib.util.module_from_spec(SPEC)
    sys.modules[NAME] = VALUE
    SPEC.loader.exec_module(VALUE)
COMMON = sys.modules[NAME]
COUNTS, equal, charge, totals = COMMON.COUNTS, COMMON.equal, COMMON.charge, COMMON.totals


def path_totals(curve: np.ndarray) -> dict:
    """
    機能: 全行清算時価と開始0から頂点・底点・最大下落を独立集計する。
    引数: curve(ndarray[float])は復元時価。
    返り値: dictは経路3指標。
    """
    values = np.r_[0., curve]
    return dict(equity_peak=float(values.max()), equity_trough=float(values.min()),
        equity_drawdown=float((np.maximum.accumulate(values)-values).max()))


def cohort_totals(parents: list[dict]) -> dict:
    """
    機能: 一親一玉の独立親会計を相殺前の玉会計へ写す。
    引数: parents(list[dict])は注文から復元した完結親。
    返り値: dictは玉数・金額・枚数。増玉の混入は別に拒否する。
    """
    value = totals(parents)
    for original, renamed in (('campaigns', 'cohorts'), ('winning_campaigns', 'winning_cohorts'),
                              ('losing_campaigns', 'losing_cohorts'), ('flat_campaigns', 'flat_cohorts')):
        value[renamed] = value.pop(original)
    return value


def next_quote(context: dict, after: int) -> int:
    """
    機能: 判断行より後の最初正常自己quoteを独立索引で求める。
    引数: context(dict)、after(int)は一商品入力と判断行。
    返り値: intは正常行。未来を判断情報へ使わず約定規約だけを照合する。
    """
    good = context['good']
    position = int(np.searchsorted(good, after, side='right'))
    assert position < len(good)
    return int(good[position])


def reservations(events: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """
    機能: 予約・fill・取消イベントだけから未約定新規と返済を復元する。
    引数: events(ndarray)、n(int)は台帳イベントと正常行数。
    返り値: tuple[ndarray,ndarray]は新規の方向別数量及び返済数量。
    """
    entry_delta, exit_delta = np.zeros((n, 2), np.int64), np.zeros(n, np.int64)
    pending_entry, pending_exit = {}, {}
    for event in events:
        row, parent, src, code, side, quantity = map(int, event[:6])
        assert 0 <= row < n and src in (0, 1)
        key = src, parent
        if code == 1:
            assert quantity > 0 and side in (-1, 1) and key not in pending_entry
            pending_entry[key] = side, quantity
            entry_delta[row, 0 if side == 1 else 1] += quantity
        elif code == 4:
            assert key in pending_entry and pending_entry[key] == (side, quantity)
            pending_entry.pop(key)
            entry_delta[row, 0 if side == 1 else 1] -= quantity
        elif code == 2:
            assert quantity > 0 and key not in pending_exit
            pending_exit[key] = quantity
            exit_delta[row] += quantity
        elif code == 5:
            assert key in pending_exit and pending_exit[key] == quantity
            pending_exit.pop(key)
            exit_delta[row] -= quantity
        elif code == 6 and key in pending_entry:
            direction, amount = pending_entry.pop(key)
            entry_delta[row, 0 if direction == 1 else 1] -= amount
    assert not pending_entry and not pending_exit
    entries, exits = np.cumsum(entry_delta, axis=0), np.cumsum(exit_delta)
    assert not entries[-1].any() and not exits[-1] and np.all(entries >= 0) and np.all(exits >= 0)
    return entries, exits


def stop_check(ledger: dict, context: dict, parent: dict, order: np.ndarray, config: dict) -> None:
    """
    機能: 保有中の全正常気配から因果peak・線・最初破れを独立検算する。
    引数: ledger/context/parent/config(dict)、order(ndarray)は返済物理注文。
    返り値: None。未来MFEは参照せず、通常判断までの接頭だけを使用する。
    """
    ident = config['exit_id']
    if ident == 'O':
        COUNTS['旧O停止規約は128null由来委譲'] += 1
        return
    record, side, quantity = context['record'], parent['side'], parent['quantity']
    multiplier, tick = (1000 if context['symbol'] == 'TOPIX' else 10), record['tick']
    support = context['cases'][config['entry_id']]['support_price'][parent['decision']]
    start, decision, price, reason = parent['row'], int(order[1]), parent['price'], int(order[8])
    reserve = ledger['events'][(ledger['events'][:, 1] == parent['parent_id']) & (ledger['events'][:, 3] == 2)]
    assert len(reserve) == 1
    reservation_row = int(reserve[0, 0])
    end = reservation_row-1 if reason == 6 else decision
    indexes = context['good'][(context['good'] >= start) & (context['good'] <= end)]
    assert len(indexes)
    quote = record['bid' if side == 1 else 'ask'][indexes]
    signed_quote, signed_entry = side*quote, side*price
    peak = np.maximum.accumulate(signed_quote)
    initial_width = COMMON.width(context['prepared']['reference_open'], tick)
    wide = context['prepared']['signal']['trend_width']
    k = int(ident[1:])
    support_line, initial_line = side*support-k*tick, signed_entry-initial_width
    initial_effective = max(support_line, initial_line)
    fee = charge(quantity, context['symbol'])
    fee_width = float(int((Decimal(2*fee)/Decimal(quantity*multiplier)/Decimal(str(tick))).to_integral_value(rounding=ROUND_CEILING))*Decimal(str(tick)))
    lines = np.full((len(indexes), 5), np.nan)
    lines[:, 0], lines[:, 1] = support_line, initial_line
    active = np.zeros(len(indexes), bool)
    if ident.startswith('T'):
        active = peak-signed_entry >= fee_width+k*tick-tick*1e-8
        lines[active, 3], lines[active, 4] = peak[active]-k*tick, signed_entry+fee_width
    else:
        lines[:, 2] = peak-wide
    stop = np.nanmax(lines, axis=1)
    eps = tick*1e-8
    hit = signed_quote-stop <= eps
    if reason == 6:
        assert not hit.any()
    else:
        assert hit.any() and indexes[np.flatnonzero(hit)[0]] == decision
    phase = np.where(hit, 3, 2)
    owners = np.sum((np.abs(lines-stop[:, None]) <= eps)*np.array([1, 2, 4, 8, 16]), axis=1)
    reasons = np.zeros(len(indexes), np.int64)
    for i in np.flatnonzero(hit):
        reasons[i] = next(j+1 for j in range(5) if int(owners[i]) & (1 << j))
    mask = np.r_[True, (quote[1:] != quote[:-1]) | (stop[1:] != stop[:-1]) | (phase[1:] != phase[:-1])]
    expected = np.column_stack((indexes, record['seq'][indexes], record['time_s'][indexes],
        np.full(len(indexes), parent['parent_id']), phase, np.full(len(indexes), side), np.ones(len(indexes)), quote,
        np.full(len(indexes), support), side*lines[:, 0], side*lines[:, 1], side*peak,
        side*lines[:, 2], side*lines[:, 3], side*lines[:, 4], active.astype(int),
        side*np.r_[initial_effective, stop[:-1]], side*stop, owners,
        (signed_quote[:, None]-lines <= eps).astype(np.int64), reasons,
        np.full(len(indexes), start), np.full(len(indexes), fee_width),
        np.full(len(indexes), (signed_entry-initial_effective)*quantity*multiplier+2*fee)))
    judgments = ledger['judgments'][ledger['judgments'][:, 3] == parent['parent_id']]
    np.testing.assert_allclose(judgments, expected[mask], atol=1e-5, rtol=0, equal_nan=True)
    equal(ledger['initial_width'], initial_width, '初期幅')
    equal(ledger['wide_width'], wide, '旧D幅')
    COUNTS['B_T全因果判断行'] += len(indexes)
    COUNTS['B_T全疎判断'] += len(judgments)


def audit(ledger: dict, context: dict, config: dict) -> tuple[dict, dict]:
    """
    機能: 物理注文から全親・玉・全行現金と清算時価及び予約上限を独立復元する。
    引数: ledger/context/config(dict)は保存口座、読取入力、確定条件。
    返り値: tuple[dict,dict]は独立会計行と配分連結用の小表/時価/trace。
    """
    symbol, record, raw = context['symbol'], context['record'], context['raw']
    n, multiplier = len(record['seq']), 1000 if symbol == 'TOPIX' else 10
    orders, trades, cohorts = ledger['orders'], ledger['trades'], ledger['growth_cohorts']
    assert orders.shape[1] == 17 and trades.shape[1] == 16 and np.isfinite(orders).all() and np.isfinite(trades).all()
    assert np.all(np.diff(orders[:, 0]) >= 0)
    gc = {name: i for i, name in enumerate(ledger['growth_cohort_columns'])}
    cash_delta, position_delta = np.zeros((n, 2)), np.zeros((n, 2), np.int64)
    live, parents, uids = {}, [], set()
    diagnostics = {int(value['order_uid']): value for value in ledger['raw_entry_diagnostics']}
    for order in orders:
        row, decision, parent, src, side, quantity, new, reason = [int(order[i]) for i in (0, 1, 2, 3, 4, 5, 7, 8)]
        uid, price, fee = int(order[16]), float(order[6]), float(order[9])
        assert 0 <= decision <= row < n and src in (0, 1) and side in (-1, 1) and quantity > 0 and uid not in uids
        uids.add(uid)
        assert context['qok'][row]
        equal(price, record['ask' if side == 1 else 'bid'][row], '当時約定BBO')
        equal(fee, charge(quantity, symbol), 'Decimal注文料floor')
        equal(order[11], record['time_s'][row], '実fill代理時計')
        if config['kind'] == 'portfolio':
            assert parent % 2 == src and uid % 2 == src
        key = src, parent
        if new:
            assert new == 1 and decision < row and key not in live
            assert row == next_quote(context, decision) and record['time_s'][row] < record['limit']-300
            entry_id = config['components'][src] if config['kind'] == 'portfolio' else config['entry_id']
            case = context['cases'][entry_id]
            equal(case['event'][decision], side, '同normal入口pulse')
            assert case['entry_quality'][decision] and not case['entry_reset'][decision] and context['qok'][decision]
            assert record['start']+300 <= record['time_s'][decision] < record['limit']-300
            expected_q = config['allocations'][symbol][src] if config['kind'] == 'portfolio' else config['quantity'][symbol]
            equal(quantity, expected_q, '実設定枚数')
            raw_row = int(raw['execution_to_raw_index'][decision])
            assert raw['qualified'][raw_row]
            choices = [value for value in case['decisions'] if int(value['row']) == decision]
            assert len(choices) == 1
            expected = choices[0]
            diag = diagnostics[uid]
            for field, wanted in dict(parent_id=parent, side=side, quantity=quantity, fill_price=price, fee=fee,
                decision_row=decision, decision_normal_row=decision, decision_raw_row=raw_row,
                decision_raw_seq=int(record['seq'][decision]), fill_row=row, fill_normal_row=row,
                fill_raw_row=int(raw['execution_to_raw_index'][row]), fill_raw_seq=int(record['seq'][row])).items():
                equal(diag[field], wanted, ('原行診断', field))
            COMMON.deep(diag['episode'], expected, '実判断lineage')
            live[key] = dict(parent_id=parent, source=src, side=side, quantity=quantity, price=price, fee=fee,
                row=row, decision=decision, uid=uid, entry_id=entry_id)
            COUNTS['全実新規lineage'] += 1
        else:
            assert new == 0 and key in live
            entry = live.pop(key)
            assert side == -entry['side'] and quantity == entry['quantity']
            timer = reason == (4 if config['exit_id'] == 'O' else 6)
            if timer:
                equal(order[10], record['limit']-60, '既知force時計')
                valid = context['good'][record['time_s'][context['good']] >= record['limit']-60]
                assert len(valid) and row == valid[0]
            else:
                assert decision < row and row == next_quote(context, decision)
                equal(order[10], record['time_s'][decision], '返済判断時計')
            gross = float(Decimal(entry['side']*quantity*multiplier)*(Decimal(str(price))-Decimal(str(entry['price']))))
            net = gross-entry['fee']-fee
            parent_result = dict(entry, gross=gross, fees=entry['fee']+fee, net=net, entry_row=entry['row'], exit_row=row)
            matches = trades[(trades[:, 0] == parent) & (trades[:, 1] == src)]
            assert len(matches) == 1
            for i, wanted in {2: entry['row'], 3: row, 4: entry['side'], 5: quantity, 6: entry['price'], 7: price,
                              8: entry['fee'], 9: fee, 10: gross, 11: net, 13: reason, 15: entry['decision']}.items():
                equal(matches[0, i], wanted, ('完結親', i))
            selected = cohorts[(cohorts[:, gc['parent_id']] == parent) & (cohorts[:, gc['source']] == src)]
            assert len(selected) == 1
            for name, wanted in dict(quantity=quantity, side=entry['side'], entry_row=entry['row'], exit_row=row,
                entry_price=entry['price'], exit_price=price, entry_fee=entry['fee'], exit_fee_share=fee,
                gross=gross, net=net, order_uid=entry['uid'], decision_row=entry['decision']).items():
                equal(selected[0, gc[name]], wanted, ('一親一玉', name))
            if config['kind'] == 'portfolio':
                assert int(selected[0, gc['cohort_id']]) % 2 == src
            else:
                stop_check(ledger, context, entry, order, config)
            parents.append(parent_result)
        cash_delta[row, src] -= side*quantity*price*multiplier+fee
        position_delta[row, src] += side*quantity
        COUNTS['全物理注文'] += 1
    assert not live and len(parents) == len(trades) == len(cohorts)
    position, cash = np.cumsum(position_delta, axis=0), np.cumsum(cash_delta, axis=0)
    last = np.maximum(context['last'], 0)
    bid, ask = record['bid'][last], record['ask'][last]
    liquidation = np.where(position >= 0, bid[:, None], ask[:, None])
    absolute = np.abs(position)
    remaining_fee = absolute*209//5 if symbol == 'TOPIX' else absolute*11
    sources = cash+position*liquidation*multiplier-remaining_fee
    curve = sources.sum(axis=1)
    np.testing.assert_allclose(ledger['source_curve'], sources, atol=1e-4, rtol=0)
    np.testing.assert_allclose(ledger['curve'], curve, atol=1e-4, rtol=0)
    pending, exiting = reservations(ledger['events'], n)
    held_long, held_short = np.maximum(position, 0).sum(axis=1), np.maximum(-position, 0).sum(axis=1)
    trace = np.column_stack((held_long, held_short, held_long+pending[:, 0], held_short+pending[:, 1], pending.sum(axis=1), exiting))
    np.testing.assert_array_equal(ledger['target_trace'], trace)
    assert not trace[-1].any() and np.all(trace >= 0)
    cap = (10 if symbol == 'TOPIX' else 20) if config['kind'] == 'portfolio' else config['quantity'][symbol]
    assert np.all(trace[:, :4] <= cap)
    if 'stale_equity' in ledger:
        np.testing.assert_array_equal(ledger['stale_equity'], ~context['qok'])
    if 'candidate_diagnostics' in ledger:
        case = context['cases'][config['entry_id']]
        candidate = ledger['candidate_diagnostics']
        rows = np.flatnonzero(case['event'])
        np.testing.assert_array_equal(candidate[:, 0], rows)
        accepted_rows = set(ledger['events'][ledger['events'][:, 3] == 1, 0].astype(int))
        exit_rows = set(orders[orders[:, 7] == 0, 0].astype(int))
        last_exit = -1e30
        cursor = 0
        for i, row in enumerate(rows):
            while cursor < n and cursor <= row:
                if cursor in exit_rows:
                    last_exit = record['time_s'][cursor]
                cursor += 1
            phase = 3 if trace[row, 5] else 2 if trace[row, 0]+trace[row, 1] else 1 if trace[row, 4] and row not in accepted_rows else 0
            allowed = (phase == 0 and row not in exit_rows and context['qok'][row] and case['entry_quality'][row] and not case['entry_reset'][row]
                and record['start']+300 <= record['time_s'][row] < record['limit']-300 and record['time_s'][row]-last_exit >= 30)
            expected = [row, record['seq'][row], record['time_s'][row], case['event'][row], phase, context['qok'][row],
                case['entry_quality'][row], case['entry_reset'][row], allowed, case['support_price'][row]]
            np.testing.assert_allclose(candidate[i], expected, atol=1e-5, rtol=0)
            assert allowed == (row in accepted_rows)
            COUNTS['全候補slot受付停止'] += 1
    result = dict(totals(parents), **path_totals(curve), cohorts=cohort_totals(parents),
        order_count=len(orders), entry_order_count=len(parents), adding_order_count=0)
    result['sources'] = {name: dict(totals([p for p in parents if p['source'] == src]), **path_totals(sources[:, src]))
                         for src, name in enumerate(('J2', 'O06'))}
    result['directions'] = {name: totals([p for p in parents if p['side'] == side]) for side, name in ((1, '買い'), (-1, '売り'))}
    result['cohort_directions'] = {name: cohort_totals([p for p in parents if p['side'] == side]) for side, name in ((1, '買い'), (-1, '売り'))}
    result['maximums'] = {name: int(trace[:, i].max(initial=0)) for i, name in enumerate(ledger['trace_columns'])}
    np.testing.assert_array_equal(ledger['stats'][:4], trace[:, :4].max(axis=0, initial=0))
    np.testing.assert_array_equal(ledger['stats'][4:8], trace[-1, [0, 1, 4, 5]])
    equal(ledger['stats'][15], curve[-1], '末尾全現金')
    result['event_counts'] = {str(int(code)): int(np.sum(ledger['events'][:, 3] == code)) for code in np.unique(ledger['events'][:, 3])}
    COUNTS['全新台帳'] += 1
    COUNTS['全時価_源_予約trace行'] += n
    return result, dict(orders=orders, trades=trades, growth_cohorts=cohorts, events=ledger['events'],
        curve=ledger['curve'], trace=ledger['target_trace'], raw_entry_diagnostics=ledger['raw_entry_diagnostics'],
        order_columns=ledger['order_columns'], trade_columns=ledger['trade_columns'], growth_cohort_columns=ledger['growth_cohort_columns'],
        event_columns=ledger['event_columns'])
