# 旧96独立出口を保持し、候補後待機を別状態へ分離する。

import math
import numpy as np
from numba import njit
import common
import watch
import support
import caps


def widths(record: dict, config: dict, reference: float) -> tuple[float, float, float]:
    """
    機能: 実fillから使う96の出口幅と料金保護幅を独立計算する。
    引数: record/config(dict)、reference(float)は既知保存始値。
    返り値: tuple[float,float,float]。初期S、常時D、費用床C。
    """
    tick = record['tick']
    quantity, unit, fee = (8, 1000., 41.8) if record['symbol'] == 'TOPIX' else (16, 10., 11.)
    initial = max(2, math.ceil(reference * config['trend_initial_stop_bp'] / 10000. / tick - 1e-10)) * tick
    trail = max(2, math.ceil(reference * .004 / tick - 1e-10)) * tick
    protected = math.ceil((2 * math.floor(quantity * fee + 1e-8) / (quantity * unit)) / tick) * tick + tick
    return initial, trail, protected


@njit(cache=True)
def owners(line: float, initial_line: float, trail_line: float, fee_line: float,
           half_line: float, active: bool, tick: float) -> int:
    """
    機能: 有効lineと同値の構成線を、独立にビット和へ復元する。
    引数: line/initial_line/trail_line/fee_line/half_line/tick(float)、active(bool)。
    返り値: int。初期1、追尾2、費用4、半分8の和。
    """
    result = 0
    if abs(line - initial_line) <= tick * 1e-8:
        result += 1
    if abs(line - trail_line) <= tick * 1e-8:
        result += 2
    if active and abs(line - fee_line) <= tick * 1e-8:
        result += 4
    if active and np.isfinite(half_line) and abs(line - half_line) <= tick * 1e-8:
        result += 8
    return result


@njit(cache=True)
def exit_snapshot(parent: int, entry_row: int, side: int, quantity: int, entry_price: float,
                  initial: float, trail: float, protected: float, peak: float, active: bool,
                  floor: float, half_line: float, line: float, row: int, clock: float,
                  observed: int, quote: float, valid: bool, reason: int,
                  enabled: bool, tick: float) -> np.ndarray:
    """
    機能: 独立保有状態から返済予約時の27列を固定する。
    引数: parent/entry_row/side/quantity/row/observed/reason(int)、価格・幅・clock(float)、旗(bool)。
    返り値: ndarray[float]。fill後に実exit価格とnetを足す親診断。
    """
    initial_line = entry_price - side * initial
    trail_line = peak - side * trail
    fee_line = entry_price + side * protected
    output = np.full(27, np.nan)
    output[:11] = np.array([parent, entry_row, np.nan, side, quantity, entry_price,
                            initial, trail, 2 * initial, initial_line, fee_line])
    output[11:24] = np.array([peak, 1. if active else 0., floor if active else np.nan, row, clock,
        quote if valid else np.nan, line,
        1. if valid and side * (quote - initial_line) <= tick * 1e-8 else 0.,
        1. if valid and side * (quote - trail_line) <= tick * 1e-8 else 0.,
        1. if active and valid and side * (quote - floor) <= tick * 1e-8 else 0.,
        owners(line, initial_line, trail_line, fee_line, half_line, active, tick), 1. if enabled else 0., reason])
    output[26] = observed
    return output


@njit(cache=True)
def replay(times: np.ndarray, bid: np.ndarray, ask: np.ndarray, quote_valid: np.ndarray,
           quality: np.ndarray, reset: np.ndarray, event: np.ndarray, start: float, limit: float,
           tick: float, initial: float, trail: float, protected: float, mode: int,
           hold: float, quantity: int, unit: float, fee_unit: float) -> tuple:
    """
    機能: 本体の状態関数を呼ばず、候補と原板から予約、実fill、最初出口を再生する。
    引数: times/bid/ask(ndarray[float])、quote_valid/quality/reset(ndarray[bool])、event(ndarray[int])。
          start/limit/tick/initial/trail/protected/hold/unit/fee_unit(float)、mode/quantity(int)。
    返り値: tuple。独立注文17列、親16列、保有予約6列、全原板時価、出口状態23列、親診断27列。
    """
    n = len(times)
    orders, trades = np.zeros((n + 2, 17)), np.zeros((n + 2, 16))
    trace, curve, states = np.zeros((n, 6)), np.zeros(n), np.full((n, 23), np.nan)
    diagnostics, pending_diagnostic = np.full((n + 2, 27), np.nan), np.full(27, np.nan)
    status = side = parent = cycle = 0
    decision = entry_row = entry_decision = -1
    entry_price = peak = line = deadline = 0.
    before = 0.
    floor = half_line = np.nan
    decision_time = 0.
    active = False
    reason = 0
    no = nt = 0
    cash = 0.
    closing = False
    last_exit = -1e30
    last_bid = last_ask = np.nan
    fee = math.floor(quantity * fee_unit + 1e-8)
    for row in range(n):
        clock = times[row]
        valid = (quote_valid[row] and np.isfinite(bid[row]) and np.isfinite(ask[row])
                 and bid[row] > 0 and ask[row] > bid[row])
        if valid:
            last_bid, last_ask = bid[row], ask[row]
        # ----------------------------------------
        # 既知運用末を先に判定し、pending新規を取り消して保有を予約返済へ変える。
        if clock >= limit - 300. and status == 1:
            status = 0
        if not closing and clock >= limit - 60.:
            closing = True
            if status == 2:
                before = line
                quote = bid[row] if side == 1 else ask[row]
                pending_diagnostic = exit_snapshot(parent, entry_row, side, quantity, entry_price,
                    initial, trail, protected, peak, active, floor, half_line, line, row - 1,
                    limit - 60., row, quote, valid, 4, hold > 0, tick)
                status, decision, decision_time, reason = 3, row - 1, limit - 60., 4
        if status in (1, 3) and valid and row > decision:
            entry = status == 1
            action = side if entry else -side
            price = ask[row] if action == 1 else bid[row]
            orders[no] = np.array([row, decision, parent, 0, action, quantity, price, int(entry),
                                   10 if entry else reason, fee, decision_time, clock, 0., cycle, 0., side, no + 1])
            no += 1
            cash -= action * quantity * price * unit + fee
            if entry:
                status, entry_row, entry_price, entry_decision = 2, row, price, decision
                peak, line = price, price - side * min(initial, trail)
                before = line
                active = False
                floor = half_line = np.nan
                deadline = clock + hold if hold > 0 else 0.
            else:
                gross = side * (price - entry_price) * quantity * unit
                trades[nt] = np.array([parent, 0, entry_row, row, side, quantity, entry_price,
                                       price, fee, fee, gross, gross - 2 * fee, 10, reason, cycle, entry_decision])
                pending_diagnostic[2] = row
                pending_diagnostic[24] = price
                pending_diagnostic[25] = gross - 2 * fee
                diagnostics[nt] = pending_diagnostic
                nt += 1
                status, last_exit = 0, clock
        # ----------------------------------------
        # 既存lineを判定してから、未hitの有効清算気配でpeakと保護lineを更新する。
        if status == 2 and row > entry_row:
            before = line
            exit_reason = 4 if closing else 3 if hold > 0 and clock >= deadline else 0
            if exit_reason == 0 and valid:
                quote = bid[row] if side == 1 else ask[row]
                if side * (quote - line) <= tick * 1e-8:
                    exit_reason = 1 if abs(peak - entry_price) < tick * 1e-8 else 2
                else:
                    if side * (quote - peak) > 0:
                        peak = quote
                    favorable = max(0., side * (peak - entry_price))
                    if mode != 0 and favorable >= 2 * initial:
                        active = True
                    oriented = max(side * line, side * entry_price - initial, side * peak - trail)
                    if active:
                        floor_width = protected
                        if mode == 2:
                            half_line = entry_price + side * math.floor(favorable * .5 / tick) * tick
                            floor_width = max(floor_width, side * (half_line - entry_price))
                        floor = entry_price + side * floor_width
                        oriented = max(oriented, side * floor)
                    line = side * oriented
            if exit_reason:
                quote = bid[row] if side == 1 else ask[row]
                pending_diagnostic = exit_snapshot(parent, entry_row, side, quantity, entry_price,
                    initial, trail, protected, peak, active, floor, half_line, line, row, clock,
                    row, quote, valid, exit_reason, hold > 0, tick)
                status, decision, decision_time, reason = 3, row, clock, exit_reason
        # ----------------------------------------
        # 候補は当該原行で一度だけ評価し、保有中やcooldown中のpulseを復活させない。
        if (status == 0 and event[row] != 0 and quality[row] and not reset[row] and valid
                and clock >= start + 300. and clock < limit - 300. and clock - last_exit >= 30.):
            side, status, decision, decision_time = int(event[row]), 1, row, clock
            parent += 1
            cycle += 1
        held = status in (2, 3)
        occupying = status != 0
        trace[row] = np.array([quantity if held and side == 1 else 0,
                              quantity if held and side == -1 else 0,
                              quantity if occupying and side == 1 else 0,
                              quantity if occupying and side == -1 else 0,
                              quantity if status == 1 else 0,
                              quantity if status == 3 else 0])
        curve[row] = cash
        if held:
            quote = last_bid if side == 1 else last_ask
            curve[row] += side * quantity * quote * unit - fee
        states[row, :3] = np.array([parent if status else 0, status, side if status else 0])
        if held:
            quote = bid[row] if side == 1 else ask[row]
            initial_line, trail_line, fee_line = entry_price - side * initial, peak - side * trail, entry_price + side * protected
            states[row, 3:] = np.array([entry_price, initial, trail, 2 * initial,
                quote if valid else np.nan, 1. if valid else 0., peak, initial_line, trail_line, fee_line,
                half_line, 1. if active else 0., floor, before, line,
                owners(line, initial_line, trail_line, fee_line, half_line, active, tick),
                1. if hold > 0 else 0., deadline, reason if status == 3 else 0, decision if status == 3 else -1])
    return orders[:no].copy(), trades[:nt].copy(), trace, curve, states, diagnostics[:nt].copy()


@njit(cache=True)
def lifetime(times: np.ndarray, bid: np.ndarray, ask: np.ndarray, valid: np.ndarray,
             trigger: int, side: int, limit: float, initial: float, trail: float,
             protected: float, mode: int, hold: float, tick: float) -> tuple:
    """
    機能: 一つの発注判断から実fillと因果的な最初返済を計算し、候補の占有区間を定める。
    引数: times/bid/ask(ndarray)、valid(ndarray[bool])、trigger/side/mode(int)、幅・時刻(float)。
    返り値: tuple[int,int,int]。実entry、実exit、受付取消行。未確定は-1。
    未来の利益で候補を選ばず、確定した占有区間内の候補は全て消費する。
    """
    n = len(times)
    entry = -1
    for row in range(trigger + 1, n):
        if times[row] >= limit - 300.:
            return -1, -1, row
        if valid[row]:
            entry = row
            break
    if entry < 0:
        return -1, -1, -1
    price = ask[entry] if side == 1 else bid[entry]
    peak, stop = price, price - side * min(initial, trail)
    active, pending = False, False
    for row in range(entry + 1, n):
        clock = times[row]
        if pending:
            if valid[row]:
                return entry, row, -1
            continue
        if clock >= limit - 60.:
            if valid[row]:
                return entry, row, -1
            pending = True
            continue
        if hold > 0 and clock >= times[entry] + hold:
            pending = True
            continue
        if not valid[row]:
            continue
        quote = bid[row] if side == 1 else ask[row]
        if side * (quote - stop) <= tick * 1e-8:
            pending = True
            continue
        if side * (quote - peak) > 0:
            peak = quote
        progress = side * (peak - price)
        if mode and progress >= 2 * initial:
            active = True
        line = max(side * stop, side * peak - trail)
        if active:
            floor = protected
            if mode == 2:
                floor = max(floor, math.floor(progress * .5 / tick) * tick)
            line = max(line, side * price + floor)
        stop = side * line
    return entry, -1, -1


def observation(record: dict, signal: dict, row: int, side: int, latest: int) -> dict:
    """
    機能: 自己現rawとその時まで公表済みpeerを、独立の判断観測へ接続する。
    引数: record/signal(dict)、row/side/latest(int)。
    返り値: dict。原行源、鮮度、旧密J2、硬反対、自己gap。
    """
    clock = record['time_s'][row]
    own = np.array([row, record['seq'][row], clock, record['bid'][row], record['ask'][row]], float)
    fresh = bool(latest >= 0 and clock - signal['grid'][latest] <= 10. + 1e-8)
    peer = signal['entry_peer_bbo'][latest, :5].copy() if latest >= 0 else np.full(5, np.nan)
    qok = bool(record['quote_valid'][row] and np.isfinite(own[3:5]).all() and 0 < own[3] < own[4])
    result = dict(own=own, peer=peer, side=side, qok=qok, quality=bool(signal['quality'][row]),
        reset=bool(signal['reset'][row]), fresh=fresh, peer_valid=bool(fresh and signal['entry_peer_bbo'][latest, 5]),
        j2_allowed=bool(fresh and signal['entry_j2_long' if side == 1 else 'entry_j2_short'][latest]),
        opposite=bool(fresh and signal['wait_opposite_long' if side == 1 else 'wait_opposite_short'][latest]),
        gap=clock - record['time_s'][row - 1] if row else 0., grid_index=latest)
    return result


def trigger_schedule(record: dict, signal: dict, config: dict, reference: float) -> dict:
    """
    機能: 生候補と既知価格経路だけから待機・取消・最初触発と占有区間を構成する。
    引数: record/signal/config(dict)、reference(float)は保存始値。
    返り値: dict。市場触発列、待機予約列、候補根拠、局所状態の変化記録。
    latent待機traceは使用せず、完了した入口から先の占有区間内の候補を一律消費する。
    """
    n, kind = len(record['time_s']), int(config['entry_wait_kind'])
    latest = np.maximum.accumulate(signal['mapped'])
    candidates = np.flatnonzero(signal['event'])
    candidate_ids = np.cumsum(signal['event'] != 0)
    valid = record['quote_valid'] & np.isfinite(record['bid']) & np.isfinite(record['ask'])
    valid &= (record['bid'] > 0) & (record['ask'] > record['bid'])
    triggers, waiting = np.zeros(n, np.int8), np.zeros((n, 2), int)
    details, changes, accepted = {}, [], []
    blocked_until, last_exit = -1, -1e30
    initial, trail, protected = widths(record, config, reference)
    peer_tick = 10. if record['symbol'] == 'TOPIX' else .5
    for candidate in candidates:
        candidate = int(candidate)
        clock, side = record['time_s'][candidate], int(signal['event'][candidate])
        if candidate <= blocked_until:
            continue
        if not (valid[candidate] and signal['quality'][candidate] and not signal['reset'][candidate]
                and clock >= record['start'] + 300. and clock < record['limit'] - 300.
                and clock - last_exit >= 30.):
            continue
        accepted.append((candidate, side))
        trigger, state = candidate, None
        if not kind:
            first = observation(record, signal, candidate, side, int(latest[candidate]))
            state = watch.start(first, config, reference, record['tick'])
            state['candidate_id'] = int(candidate_ids[candidate])
        if kind:
            first = observation(record, signal, candidate, side, int(latest[candidate]))
            state = watch.start(first, config, reference, record['tick'])
            state['candidate_id'] = int(candidate_ids[candidate])
            changes.append((candidate, deepcopy_state(state), '候補'))
            if first['gap'] > 10. + 1e-8 and config['entry_clock_policy'] == 'C0':
                state['active'] = False
                blocked_until = candidate
                changes.append((candidate, deepcopy_state(state), '自己gap取消'))
                continue
            if first['gap'] > 10. + 1e-8 and config['entry_clock_policy'] == 'C3':
                watch.begin_epoch(state, first)
                changes.append((candidate, deepcopy_state(state), '別epoch開始'))
            waiting[candidate, 0 if side == 1 else 1] = 8 if record['symbol'] == 'TOPIX' else 16
            trigger = -1
            for row in range(candidate + 1, n):
                seen = observation(record, signal, row, side, int(latest[row]))
                state, decision = watch.step(state, seen, record['tick'], peer_tick, record['limit'] - 300.)
                changes.append((row, deepcopy_state(state), decision))
                if decision['trigger']:
                    trigger = row
                    break
                if not state['active']:
                    blocked_until = row
                    break
                waiting[row, 0 if side == 1 else 1] = 8 if record['symbol'] == 'TOPIX' else 16
            if trigger < 0:
                if state['active']:
                    blocked_until = n - 1
                continue
        triggers[trigger] = side
        details[trigger] = dict(candidate_row=candidate, candidate_id=int(candidate_ids[candidate]),
            side=side, state=state)
        fill, closed, canceled = lifetime(record['time_s'], record['bid'], record['ask'], valid,
            trigger, side, record['limit'], initial, trail, protected, int(config['trend_protection_mode']),
            float(config['trend_hold_seconds']), record['tick'])
        blocked_until = closed if closed >= 0 else canceled if canceled >= 0 else n - 1
        if closed >= 0:
            last_exit = record['time_s'][closed]
    return dict(event=triggers, waiting=waiting, details=details, changes=changes, accepted=accepted)


def deepcopy_state(state: dict) -> dict:
    """
    機能: 独立の状態変化を後の更新で書き換えない形で記録する。
    引数: state(dict)は当時の局所状態。
    返り値: dict。配列も複製した状態。
    """
    return {key: value.copy() if isinstance(value, np.ndarray) else value for key, value in state.items()}


def watch_vector(state: dict, record: dict) -> np.ndarray:
    """
    機能: 独立の局所状態を公表watch32列の名前順へ変換する。
    引数: state/record(dict)は独立状態と原板。
    返り値: ndarray[float]。本体traceから値を引用しない32列。
    """
    phase_value = (2 if state['pullback_armed'] else 1) if state['active'] else 0
    result = np.array([float(state['active']), phase_value, state['side'], state['candidate_id'],
        state['candidate_row'], record['seq'][state['candidate_row']], state['candidate_time'],
        state['candidate_price'], state['expires'], state['width'], state['advance'], state['pullback'],
        state['recovery'], state['side'] * state['favorable'], state['side'] * state['extreme'],
        state['phase_row'], state['phase_time'], *state['anchor_own'], *state['anchor_peer'],
        float(state['anchor_valid']), float(state['fallback_used']), state['anchor_row'],
        state['anchor_grid'], state['kind']], float)
    assert len(result) == 32
    return result


def verify_entry(record: dict, signal: dict, config: dict, expected: dict, actual: dict) -> None:
    """
    機能: 独立candidate/phase/最初triggerと本体45親、取消、全rawのwatch32状態を照合する。
    引数: record/signal/config/expected/actual(dict)。
    返り値: None。候補や極値の相違は例外で停止。
    """
    schedule = expected['schedule']
    actual_parents = np.asarray(actual['entry_parent_diagnostics'], float).reshape(-1, 45)
    assert len(actual_parents) == len(schedule['details'])
    peer_tick = signal.get('peer_tick', 10. if record['symbol'] == 'TOPIX' else .5)
    latest = np.maximum.accumulate(signal['mapped'])
    for ordinal, (trigger, detail) in enumerate(schedule['details'].items(), 1):
        candidate, side = detail['candidate_row'], detail['side']
        state = detail['state']
        seen = observation(record, signal, trigger, side, int(latest[trigger]))
        baseline = np.array([ordinal, detail['candidate_id'], candidate, record['seq'][candidate],
            record['time_s'][candidate], record['ask'][candidate] if side == 1 else record['bid'][candidate],
            config['entry_wait_kind'], side, 8 if record['symbol'] == 'TOPIX' else 16], float)
        common.exact(actual_parents[ordinal - 1, :9], baseline, '候補と親対応')
        vector = watch_vector(state, record)
        common.exact(actual_parents[ordinal - 1, 9:28], np.r_[vector[[9, 10, 11, 12, 15, 16, 13, 14]], vector[17:27], vector[28]], '独立phaseと別anchor')
        common.exact(actual_parents[ordinal - 1, 28:33], [trigger, record['seq'][trigger], record['time_s'][trigger],
            record['ask'][trigger] if side == 1 else record['bid'][trigger], int(latest[trigger])], '最初触発')
        if config['entry_wait_kind']:
            common.exact(actual_parents[ordinal - 1, 33:37], [seen['j2_allowed'], config['entry_bbo_confirm'],
                watch.bbo_fresh(state, seen), watch.bbo_confirmation(state, seen, record['tick'], peer_tick)], '源進行の証拠')
    if config['entry_wait_kind']:
        dense = np.full((len(record['time_s']), 32), np.nan)
        dense[:, :4] = 0.
        dense[:, 31] = config['entry_wait_kind']
        previous, begin = None, 0
        for row, state, decision in schedule['changes']:
            if previous is not None:
                dense[begin:row] = previous
            previous, begin = watch_vector(state, record), row
            if isinstance(decision, dict) and decision['cancel_flags']:
                events = actual['entry_wait_events']
                assert np.any((events[:, 0] == row) & (events[:, 1] == 3)), '取消原行の欠落'
        if previous is not None:
            dense[begin:] = previous
        common.exact(actual['watch_state_trace'][:, :32], dense, '全raw待機状態')


def policy_vector(state: dict | None, policy: str) -> np.ndarray:
    """
    機能: 独立epoch記憶を本体20内部列へ変換し、未受理時は明示空状態を作る。
    引数: state(dict|None)は独立状態、policy(str)はC0〜C3。
    返り値: ndarray[float]。latent政策traceの値は使わない。
    """
    value = np.full(20, np.nan)
    value[:4] = [int(policy[1]), 0., 0., 0.]
    value[[4, 7, 8, 19]] = -1.
    value[6] = 0.
    if state is not None:
        value[:9] = [int(policy[1]), state['epoch_active'], state['candidate_id'],
            state['gap_count'], state['epoch_row'], state['epoch_time'], state['epoch_valid'],
            state['epoch_baseline_row'], state['epoch_baseline_grid']]
        value[9:19] = np.r_[state['epoch_own'], state['epoch_peer']]
        value[19] = state['reprepare_row']
    return value


def verify_policy(record: dict, signal: dict, config: dict, expected: dict, actual: dict) -> None:
    """
    機能: 新epoch内部20列、10観測列及び政策イベントの発生・源・取消を独立照合する。
    引数: record/signal/config/expected/actual(dict)。
    返り値: None。不一致は例外。旧候補記憶と別epochを混合しない。
    """
    n, policy = len(record['time_s']), config['entry_clock_policy']
    trace = np.asarray(actual['entry_policy_state_trace'])
    events = np.asarray(actual['entry_policy_events']).reshape(-1, 50)
    assert trace.shape == (n, 40)
    changes = expected['schedule']['changes'] if config['entry_wait_kind'] else []
    dense = np.tile(policy_vector(None, policy), (n, 1))
    previous, begin = None, 0
    rows_by_code = {code: set() for code in range(1, 7)}
    after = {}
    for row, state, decision in changes:
        if previous is not None:
            dense[begin:row] = previous
        previous, begin = policy_vector(state, policy), row
        after[row] = state
        if isinstance(decision, dict):
            if decision.get('epoch_started'):
                rows_by_code[2].add(row)
            if decision.get('epoch_baseline'):
                rows_by_code[3].add(row)
            if decision.get('reprepared'):
                rows_by_code[4].add(row)
            if decision['cancel_flags']:
                rows_by_code[5].add(row)
        elif decision == '別epoch開始':
            rows_by_code[2].add(row)
        elif decision == '自己gap取消':
            rows_by_code[5].add(row)
        if row and record['time_s'][row] - record['time_s'][row-1] > 10. + 1e-8:
            rows_by_code[1].add(row)
    if previous is not None:
        dense[begin:] = previous
    common.exact(trace[:, :20], dense, '独立政策内部20列')
    rows_by_code[6] = set(expected['schedule']['details']) if config['entry_wait_kind'] else set()
    for code, rows in rows_by_code.items():
        common.exact(events[events[:, 1] == code, 0], sorted(rows), '政策イベント行/' + str(code))
    latest = np.maximum.accumulate(signal['mapped'])
    for event in events:
        row = int(event[0])
        seen = observation(record, signal, row, 1, int(latest[row]))
        common.exact(event[3], latest[row], '政策格子源')
        common.exact(event[24:34], np.r_[seen['own'], seen['peer']], '政策の別公開源')
        if int(event[1]) in (2, 3, 4, 5, 6):
            common.exact(event[4:24], policy_vector(after[row], policy), '政策イベントの独立内部記憶')
        if int(event[1]) in (2, 3, 4):
            assert policy == 'C3'
        if int(event[1]) == 4:
            assert event[47] == event[48] and event[45] == row
            assert event[49] == record['time_s'][int(after[row]['candidate_row'])] + config['entry_wait_seconds']
    # ----------------------------------------
    # 実観測を表示する行の全10源だけ検査し、内部記憶の資格を観測源へ救済しない。
    visible = np.flatnonzero(np.isfinite(trace[:, 20]))
    own = np.column_stack((visible, record['seq'][visible], record['time_s'][visible],
        record['bid'][visible], record['ask'][visible]))
    peer = np.full((len(visible), 5), np.nan)
    published = latest[visible] >= 0
    peer[published] = signal['entry_peer_bbo'][latest[visible[published]], :5]
    common.exact(trace[visible, 20:30], np.column_stack((own, peer)), '政策表示の自己/相手源')


def oracle(record: dict, signal: dict, config: dict, reference: float) -> dict:
    """
    機能: 独立候補待機と既検証の出口を接続し、実経済と予約枠を再構成する。
    引数: record/signal/config(dict)、reference(float)。
    返り値: dict。経済6配列と候補待機根拠。
    """
    schedule = trigger_schedule(record, signal, config, reference)
    initial, trail, protected = widths(record, config, reference)
    common.exact(signal['trend_width'], trail)
    quantity, unit, fee = (8, 1000., 41.8) if record['symbol'] == 'TOPIX' else (16, 10., 11.)
    output = replay(record['time_s'], record['bid'], record['ask'], record['quote_valid'],
        signal['quality'], signal['reset'], schedule['event'], record['start'], record['limit'],
        record['tick'], initial, trail, protected, int(config['trend_protection_mode']),
        float(config['trend_hold_seconds']), quantity, unit, fee)
    result = dict(zip(('orders', 'trades', 'target_trace', 'curve', 'trend_exit_state_trace', 'trend_parent_diagnostics'), output))
    assert not np.any(result['target_trace'][:, 2:4][schedule['waiting'].sum(axis=1) > 0])
    result['target_trace'][:, 2:4] += schedule['waiting']
    result['target_trace'][:, 4] += schedule['waiting'].sum(axis=1)
    result['schedule'] = schedule
    return result


def compare(record: dict, signal: dict, config: dict, reference: float, actual: dict,
            prepared_value: dict | None = None) -> dict:
    """
    機能: 生候補から独立再構成した入口・出口・数量枠・現金を本体へ照合する。
    引数: record/signal/config/actual(dict)、reference(float)、prepared_value(dict|None)は別支持素材。
    返り値: dict。注文、親、原板の検査件数。
    """
    if config['entry_support_lane'] == 'L1':
        assert prepared_value is not None, 'L1独立比較は原支持59素材を必要とします'
    if prepared_value is not None:
        signal, allowed = support.selected(prepared_value, config)
        support.verify_trace(prepared_value, config, signal, allowed, actual)
    expected = oracle(record, signal, config, reference)
    for name in ('orders', 'trades', 'target_trace', 'trend_exit_state_trace', 'trend_parent_diagnostics'):
        common.exact(actual[name], expected[name], config['id'] + '/' + name)
    common.money(actual['curve'], expected['curve'], config['id'] + '/curve')
    verify_entry(record, signal, config, expected, actual)
    verify_policy(record, signal, config, expected, actual)
    caps.verify(record, config, reference, expected, actual, watch_vector)
    return dict(注文=len(expected['orders']), 決済親=len(expected['trades']), 原板行=len(record['time_s']),
                候補受理=len(expected['schedule']['accepted']), 触発=len(expected['schedule']['details']))
