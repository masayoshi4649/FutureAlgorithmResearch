"""J8固定候補から単一追従の予約、出口、親会計を独立再構成する。"""

import math

import numpy as np
from numba import njit

import common


def widths(record: dict, config: dict, reference: float) -> tuple[float, float, float]:
    """
    機能: 始値と実数量から初期幅、旧追尾幅、料金込み利益床幅を独立計算する。
    引数: record/config(dict)、reference(float)は原行0から既知の保存始値。
    返り値: tuple[float,float,float]。初期S、追尾D、利益床C。
    """
    tick = record['tick']
    quantity, unit, fee_unit = ((8, 1000., 41.8) if record['symbol'] == 'TOPIX'
                               else (16, 10., 11.))
    initial = max(2, math.ceil(reference * config['trend_initial_stop_bp'] / 10000. / tick - 1e-10)) * tick
    trail = max(2, math.ceil(reference * .004 / tick - 1e-10)) * tick
    fee = math.floor(quantity * fee_unit + 1e-8)
    protected = math.ceil((2 * fee / (quantity * unit)) / tick) * tick + tick
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


def oracle(record: dict, signal: dict, config: dict, reference: float) -> dict:
    """
    機能: 商品倍率と独立幅を設定して単一追従oracleを実行する。
    引数: record/signal/config(dict)、reference(float)は保存始値。
    返り値: dict。独立経済配列と出口状態。
    """
    initial, trail, protected = widths(record, config, reference)
    common.exact(signal['trend_width'], trail, '旧D40幅')
    quantity, unit, fee = (8, 1000., 41.8) if record['symbol'] == 'TOPIX' else (16, 10., 11.)
    result = replay(record['time_s'], record['bid'], record['ask'], record['quote_valid'],
                    signal['quality'], signal['reset'], signal['event'], record['start'], record['limit'],
                    record['tick'], initial, trail, protected, int(config['trend_protection_mode']),
                    float(config['trend_hold_seconds']), quantity, unit, fee)
    return dict(zip(('orders', 'trades', 'target_trace', 'curve', 'trend_exit_state_trace', 'trend_parent_diagnostics'), result))


def compare(record: dict, signal: dict, config: dict, reference: float, actual: dict) -> dict:
    """
    機能: 本体経済と独立原板再生を比較し、全注文と最初返済を同時に検算する。
    引数: record/signal/config/actual(dict)、reference(float)。
    返り値: dict。注文、親、原板行の照合件数。
    """
    expected = oracle(record, signal, config, reference)
    for name in ('orders', 'trades', 'target_trace', 'trend_exit_state_trace', 'trend_parent_diagnostics'):
        common.exact(actual[name], expected[name], config['id'] + '/' + name)
    common.money(actual['curve'], expected['curve'], config['id'] + '/curve')
    return dict(注文=len(expected['orders']), 決済親=len(expected['trades']), 原板行=len(record['time_s']))
