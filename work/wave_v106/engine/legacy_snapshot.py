"""固定支持境界と価格保険を、少数状態と次正常quoteで機械的に執行する。"""

import math
import os
from pathlib import Path

import numba
from numba import njit
import numpy as np


HERE = Path(__file__).resolve().parent
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'jit')
numba.config.CACHE_DIR = str(HERE / 'jit')
ORDER_COLUMNS = ['row', 'decision_row', 'parent_id', 'source', 'action_side', 'quantity', 'price',
    'is_entry', 'reason', 'fee', 'decision_time', 'fill_time', 'limit_price', 'cycle', 'method', 'source_entry_side', 'uid']
TRADE_COLUMNS = ['parent_id', 'source', 'entry_row', 'exit_row', 'side', 'quantity', 'entry_price',
    'exit_price', 'entry_fee', 'exit_fee', 'gross', 'net', 'entry_reason', 'exit_reason', 'cycle', 'entry_decision_row']
TRACE_COLUMNS = ['held_long', 'held_short', 'occupied_long', 'occupied_short', 'pending_entry', 'pending_exit']
EVENT_COLUMNS = ['row', 'parent_id', 'source', 'code', 'side', 'quantity', 'decision_row', 'limit_price', 'mode', 'decision_time', 'cycle', 'detail']
STAT_COLUMNS = ['max_held_long', 'max_held_short', 'max_occupied_long', 'max_occupied_short', 'held_long', 'held_short', 'pending_entry',
    'pending_exit', 'max_total_held', 'range_cancellations', 'cancel_race_fills', 'trend_rejections', 'range_rejections', 'trend_reservations', 'range_reservations', 'cash']
COHORT_COLUMNS = ['parent_id', 'cohort_id', 'source', 'side', 'quantity', 'decision_row', 'decision_seq', 'decision_time',
    'entry_row', 'entry_seq', 'entry_time', 'entry_price', 'entry_fee', 'order_uid', 'exit_row', 'exit_seq', 'exit_time', 'exit_price',
    'exit_fee_share', 'gross', 'net', 'risk_budget', 'initial_quantity', 'entry_kind', 'parent_final_quantity']
JUDGMENT_COLUMNS = ['row', 'raw_seq', 'time', 'parent_id', 'phase', 'side', 'quote_valid', 'liquidation_quote', 'support_price',
    'support_line', 'initial_line', 'peak', 'wide_line', 'profit_line', 'fee_line', 'profit_active', 'stop_before', 'stop_after',
    'line_owner', 'support_hit', 'initial_hit', 'wide_hit', 'profit_hit', 'fee_hit', 'exit_reason', 'fill_row', 'fee_width', 'initial_risk_yen']
REASONS = {1: '固定支持境界', 2: '初期保険', 3: '広い価格追尾', 4: '狭い利益追尾', 5: '費用床', 6: '場内タイマー'}


@njit(cache=True)
def append_event(log, row, parent, code, side, quantity, decision_row, decision_time, detail):
    """
    機能: 物理注文状態の変更を当時の原行へ疎に記録する。
    引数: log(list[ndarray])、整数状態(int)、decision_time/detail(float)。
    返り値: None。未来の状態で過去の行を上書きしない。
    """
    log.append(np.array([row, parent, 0, code, side, quantity, decision_row, 0, 0, decision_time, parent, detail], np.float64))


@njit(cache=True)
def simulate(times, sequence, bids, asks, qok, event, quality, reset, support_values,
             tick, start, limit, quantity, multiplier, fee_unit, initial_width, wide_width,
             support_ticks, profit_trail, cooldown, start_offset, cut_offset, force_offset):
    """
    機能: 新規予約・保有・返済予約だけで、B/Tの線と物理約定を原行順に進める。
    引数: 原行配列(ndarray)、quantity/support_ticks(int)、価格/経済/時間設定(float)、profit_trail(bool)。
    返り値: tuple。注文・親・玉・全行時価・保有・途中判断・stale・候補台帳。
    """
    n = len(times)
    orders = [np.zeros(17)]
    trades = [np.zeros(16)]
    cohorts = [np.zeros(25)]
    events = [np.zeros(12)]
    judgments = [np.zeros(28)]
    candidates = [np.zeros(10)]
    curve, trace, stale = np.zeros(n), np.zeros((n, 6), np.int32), np.ones(n, np.bool_)
    phase, parent, next_parent, side = 0, 0, 0, 0
    decision_row, fill_row, entry_decision, uid, entry_uid = -1, -1, -1, 0, 0
    decision_time, entry_decision_time, entry_time, last_exit = 0., 0., 0., -1e30
    entry, support, support_line, initial_line, peak, stop = 0., 0., 0., 0., 0., 0.
    reason, active, owner = 0, False, 0
    cash, last_bid, last_ask = 0., np.nan, np.nan
    fee = math.floor(quantity * fee_unit + 1e-8)
    fee_width = math.ceil((2. * fee) / (quantity * multiplier * tick) - 1e-10) * tick
    initial_risk = 0.
    previous_quote, previous_stop, previous_phase = np.nan, np.nan, -1
    force_time, entry_cut = limit - force_offset, limit - cut_offset
    eps = tick * 1e-8
    for row in range(n):
        stamp = times[row]
        just_exited = False
        if qok[row]:
            last_bid, last_ask = bids[row], asks[row]
            stale[row] = False

        # ----------------------------------------
        # cut取消と既知場末タイマーを、通常予約の約定より先に処理する。
        if phase == 1 and stamp >= entry_cut:
            append_event(events, row, parent, 6, side, quantity, decision_row, decision_time, 1.)
            phase = 0
        if phase == 2 and stamp >= force_time:
            phase, reason = 3, 6
            decision_row, decision_time = row - 1, force_time
            append_event(events, row, parent, 2, side, quantity, decision_row, decision_time, 6.)
        if phase == 1 and qok[row] and row > decision_row:
            entry = asks[row] if side == 1 else bids[row]
            fill_row, entry_time, entry_decision, entry_decision_time = row, stamp, decision_row, decision_time
            uid += 1
            entry_uid = uid
            orders.append(np.array([row, decision_row, parent, 0, side, quantity, entry, 1, 10, fee, decision_time, stamp, 0, parent, 10, side, uid], np.float64))
            cash -= side * quantity * entry * multiplier + fee
            phase = 2
            support_line = support - side * support_ticks * tick
            initial_line = entry - side * initial_width
            stop = max(support_line, initial_line) if side == 1 else min(support_line, initial_line)
            peak = bids[row] if side == 1 else asks[row]
            active = False
            initial_risk = side * quantity * multiplier * (entry - stop) + 2. * fee
            append_event(events, row, parent, 4, side, quantity, entry_decision, entry_decision_time, entry)
        elif phase == 3 and qok[row] and row > decision_row and stamp >= decision_time:
            price = bids[row] if side == 1 else asks[row]
            uid += 1
            orders.append(np.array([row, decision_row, parent, 0, -side, quantity, price, 0, reason, fee, decision_time, stamp, 0, parent, reason, side, uid], np.float64))
            cash += side * quantity * price * multiplier - fee
            gross = side * quantity * (price - entry) * multiplier
            net = gross - 2. * fee
            trades.append(np.array([parent, 0, fill_row, row, side, quantity, entry, price, fee, fee, gross, net, 10, reason, parent, entry_decision], np.float64))
            cohorts.append(np.array([parent, parent, 0, side, quantity, entry_decision, sequence[entry_decision], entry_decision_time,
                fill_row, sequence[fill_row], entry_time, entry, fee, entry_uid, row, sequence[row], stamp, price, fee,
                gross, net, initial_width * quantity * multiplier, quantity, 10, quantity], np.float64))
            append_event(events, row, parent, 5, side, quantity, decision_row, decision_time, price)
            phase, last_exit, just_exited = 0, stamp, True

        # ----------------------------------------
        # 実fill行も正常清算気配で判断し、全停止線を有利側だけ更新する。
        if phase == 2 and qok[row]:
            quote = bids[row] if side == 1 else asks[row]
            peak = max(peak, quote) if side == 1 else min(peak, quote)
            before = stop
            wide_line, profit_line, fee_line = np.nan, np.nan, np.nan
            if profit_trail:
                if side * (peak - entry) >= fee_width + support_ticks * tick - eps:
                    active = True
                if active:
                    profit_line = peak - side * support_ticks * tick
                    fee_line = entry + side * fee_width
                    stop = max(stop, profit_line, fee_line) if side == 1 else min(stop, profit_line, fee_line)
            else:
                wide_line = peak - side * wide_width
                stop = max(stop, wide_line) if side == 1 else min(stop, wide_line)
            owner = 0
            lines = np.array([support_line, initial_line, wide_line, profit_line, fee_line])
            hits = np.zeros(5, np.int8)
            for j in range(5):
                if np.isfinite(lines[j]):
                    if abs(lines[j] - stop) <= eps:
                        owner |= 1 << j
                    if side * (quote - lines[j]) <= eps:
                        hits[j] = 1
            reason = 0
            if side * (quote - stop) <= eps:
                for j in range(5):
                    if (owner & (1 << j)) != 0:
                        reason = j + 1
                        break
                assert reason != 0
                phase, decision_row, decision_time = 3, row, stamp
                append_event(events, row, parent, 2, side, quantity, row, stamp, float(reason))
            if row == fill_row or phase != previous_phase or quote != previous_quote or stop != previous_stop:
                judgments.append(np.array([row, sequence[row], stamp, parent, phase, side, 1, quote, support,
                    support_line, initial_line, peak, wide_line, profit_line, fee_line, 1 if active else 0, before, stop,
                    owner, hits[0], hits[1], hits[2], hits[3], hits[4], reason, fill_row, fee_width, initial_risk], np.float64))
                previous_quote, previous_stop, previous_phase = quote, stop, phase

        # ----------------------------------------
        # 候補は当該原行で消費し、予約・保有・返済後の将来へ補充しない。
        if event[row] != 0:
            allowed = (phase == 0 and not just_exited and qok[row] and quality[row] and not reset[row]
                and stamp >= start + start_offset and stamp < entry_cut and stamp - last_exit >= cooldown)
            candidates.append(np.array([row, sequence[row], stamp, event[row], phase, qok[row], quality[row], reset[row], allowed, support_values[row]], np.float64))
            if allowed:
                assert np.isfinite(support_values[row]) and support_values[row] > 0
                next_parent += 1
                parent, side, support, phase = next_parent, int(event[row]), support_values[row], 1
                decision_row, decision_time = row, stamp
                append_event(events, row, parent, 1, side, quantity, row, stamp, support)
            else:
                append_event(events, row, 0, 9, int(event[row]), quantity, row, stamp, phase)
        held = phase == 2 or phase == 3
        if held:
            liquidation = last_bid if side == 1 else last_ask
            assert np.isfinite(liquidation)
            curve[row] = cash + side * quantity * liquidation * multiplier - fee
            trace[row, 0 if side == 1 else 1] = quantity
            trace[row, 2 if side == 1 else 3] = quantity
            if phase == 3:
                trace[row, 5] = quantity
        else:
            curve[row] = cash
            if phase == 1:
                trace[row, 2 if side == 1 else 3] = quantity
                trace[row, 4] = quantity
    return orders[1:], trades[1:], cohorts[1:], events[1:], judgments[1:], candidates[1:], curve, trace, stale, cash


def execute(record: dict, signal: dict, config: dict, finish: bool = True, python: bool = False) -> dict:
    """
    機能: 同一正常原行の候補をB/Tへ渡し、旧会計と互換の物理出力を返す。
    引数: record/signal/config(dict)、finish(bool)は完全入力flat要求、python(bool)は人工対照。
    返り値: dict。注文・親・玉・全行時価・疎な途中判断。原本/APIは呼ばない。
    """
    assert config['id'] in ('B1', 'B2', 'B4', 'T2', 'T4')
    if python:
        assert record.get('人工素材') is True
    symbol = record['symbol']
    assert symbol in ('TOPIX', 'NK225')
    multiplier, fee_unit, cap = (1000., 41.8, 10) if symbol == 'TOPIX' else (10., 11., 20)
    quantity = config['quantity']
    assert isinstance(quantity, int) and 0 < quantity <= cap
    n, tick = len(record['time_s']), float(record['tick'])
    if finish:
        assert n and record['time_s'][-1] >= record['limit'], '完全入力にはlimit到達の原行が必要です'
    for name in ('event', 'support_price', 'entry_quality', 'entry_reset'):
        assert signal[name].shape == (n,)
    assert signal['event'].dtype == np.int8 and np.isin(signal['event'], (-1, 0, 1)).all()
    assert signal['entry_quality'].dtype == signal['entry_reset'].dtype == np.bool_
    assert np.isfinite(signal['reference_open']) and signal['reference_open'] > 0 and tick > 0
    initial_width = max(2, math.ceil(signal['reference_open'] * config['initial_stop_fraction'] / tick - 1e-10)) * tick
    wide_width = float(signal['trend_width'])
    assert np.isfinite(wide_width) and wide_width > 0
    flag = record['quote_valid']
    qok = (flag & np.isfinite(record['time_s']) & np.isfinite(record['bid']) & np.isfinite(record['ask'])
            & (record['bid'] > 0) & (record['ask'] > record['bid']))
    function = simulate.py_func if python else simulate
    values = function(record['time_s'], record['seq'], record['bid'], record['ask'], qok,
        signal['event'], signal['entry_quality'], signal['entry_reset'], signal['support_price'], tick,
        float(record['start']), float(record['limit']), quantity, multiplier, fee_unit, initial_width, wide_width,
        int(config['support_ticks']), bool(config['profit_trail']), float(config['cooldown_seconds']),
        float(config['start_offset']), float(config['cut_offset']), float(config['force_offset']))
    orders, trades, cohorts, events, judgments, candidates = [np.asarray(values[j], np.float64).reshape(-1, width)
        for j, width in enumerate((17, 16, 25, 12, 28, 10))]
    curve, trace, stale, cash = values[6:]
    if finish:
        assert n and not trace[-1].any(), '完全入力でも保有又は予約が残っています。架空の端点清算はしません'
    stats = np.zeros(16)
    stats[:4] = trace[:, :4].max(axis=0, initial=0)
    if n:
        stats[4:8] = trace[-1, [0, 1, 4, 5]]
    stats[8] = (trace[:, 0] + trace[:, 1]).max(initial=0)
    stats[9], stats[11], stats[13], stats[15] = np.sum(events[:, 3] == 6), np.sum(events[:, 3] == 9), np.sum(events[:, 3] == 1), cash
    metadata = {int(row['row']): row for row in signal.get('decisions', [])}
    diagnostics = []
    for order in orders[orders[:, 7] == 1]:
        fill, decision = int(order[0]), int(order[1])
        original = metadata.get(decision)
        assert original is not None
        diagnostics.append(dict(parent_id=int(order[2]), decision_row=decision, decision_normal_row=decision,
            decision_raw_row=int(original['raw_row']), decision_raw_seq=int(record['seq'][decision]), decision_time=float(order[10]),
            fill_row=fill, fill_normal_row=fill, fill_raw_row=int(signal['execution_to_raw_index'][fill]),
            fill_raw_seq=int(record['seq'][fill]), fill_time=float(order[11]), side=int(order[4]), quantity=int(order[5]),
            fill_price=float(order[6]), fee=float(order[9]), order_uid=int(order[16]), episode=original,
            fixed_support_price=float(signal['support_price'][decision]), old_quantity_diagnostic=None))
    return dict(orders=orders, order_columns=ORDER_COLUMNS, trades=trades, trade_columns=TRADE_COLUMNS,
        growth_cohorts=cohorts, growth_cohort_columns=COHORT_COLUMNS, events=events, event_columns=EVENT_COLUMNS,
        stats=stats, stat_columns=STAT_COLUMNS, curve=curve, source_curve=np.column_stack((curve, np.zeros(n))),
        target_trace=trace, trace_columns=TRACE_COLUMNS, raw_entry_diagnostics=diagnostics,
        judgments=judgments, judgment_columns=JUDGMENT_COLUMNS, candidate_diagnostics=candidates,
        candidate_columns=['row', 'seq', 'time', 'side', 'phase', 'quote_valid', 'entry_quality', 'entry_reset', 'accepted', 'support_price'],
        stale_equity=stale, reasons=REASONS, exit_id=config['id'], initial_width=initial_width, wide_width=wide_width,
        quantity=quantity, source_names={0: '自己仮説', 1: '未使用'}, economics=dict(multiplier=multiplier, fee_unit=fee_unit),
        risk_definition='initial_risk_yenは初期有効線での費用後予定損失のsigned値。負値は予定利益であり、次quoteの実損失上限ではない。')
