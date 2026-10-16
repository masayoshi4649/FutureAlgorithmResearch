"""Cの不変B4と、R純価格の固定停止/中心及び待機指値を単一四状態で実行する。"""

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
    'line_owner', 'support_hit', 'initial_hit', 'wide_hit', 'profit_hit', 'fee_hit', 'exit_reason', 'fill_row', 'fee_width', 'initial_risk_yen', 'chosen_family', 'fixed_centre_target']
REASONS = {1: '固定支持境界', 2: '初期保険', 3: '広い価格追尾', 4: '狭い利益追尾', 5: '費用床',
           6: '場内タイマー', 7: 'セッション損失枠', 8: '初期R不正', 9: '静観開始タイマー', 10: 'R固定中心到達', 11: 'R純価格範囲外停止'}
CONTROL_COLUMNS = ['row', 'raw_seq', 'time', 'parent_id', 'phase', 'side', 'risk_R', 'risk_valid',
    'fill_stop_broken', 'alpha', 'beta', 'exact_fee_width', 'profit_trail_width', 'profit_floor_margin',
    'profit_active', 'stop', 'equity', 'session_budget', 'brake_latched', 'brake_qualifier',
    'band_long_active', 'band_short_active', 'band_long_anchor', 'band_short_anchor', 'band_long_radius',
    'band_short_radius', 'escape_long_seq', 'escape_short_seq']
CONTROL_EVENT_COLUMNS = ['row', 'raw_seq', 'time', 'parent_id', 'code', 'side', 'support',
    'risk_R', 'lower', 'upper', 'escape_seq', 'detail']
CONTROL_INTEGER_COLUMNS = ['row', 'raw_seq', 'parent_id', 'escape_seq', 'candidate_anchor_seq']
CANDIDATE_CONTROL_COLUMNS = ['row', 'raw_seq', 'time', 'side', 'phase', 'accepted', 'rejection',
    'blocked_mask', 'external_filter', 'filter_reason', 'band_active', 'band_anchor', 'band_radius',
    'escape_seq', 'candidate_anchor_seq', 'support_price', 'band_release', 'brake_latched']
CONTROL_CODES = {1: 'fill時の固定R', 2: 'R不正又はfill行支持破れ', 3: '確定損失で支持帯作成',
    4: '支持帯を順方向へ脱出', 5: '脱出根拠を破棄', 6: '新根拠で支持帯解除',
    7: 'session損失枠へ到達', 8: 'session停止で新規予約取消', 9: 'session停止で返済予約',
    10: 'R不正で返済予約', 11: 'R不存在の損失帯未作成', 12: '既知静観開始で返済予約', 13: '静観開始で新規予約取消', 14: 'R待機を固定stop外で取消', 15: 'R待機をknownTRENDで取消'}
REJECTIONS = {0: '受付', 1: '保有予約又は同row返済後', 2: '気配不明', 3: '入口資格なし',
    4: 'reset', 5: '受付時間外', 6: '返済後cooldown', 7: '外部入口filter',
    8: 'session損失停止', 9: '同方向支持帯の再参加停止', 10: '既知開場静観窓'}


@njit(cache=True)
def append_event(log, row, parent, code, side, quantity, decision_row, decision_time, detail):
    """
    機能: 物理注文状態の変更を当時の原行へ疎に記録する。
    引数: log(list[ndarray])、整数状態(int)、decision_time/detail(float)。
    返り値: None。未来の状態で過去の行を上書きしない。
    """
    log.append(np.array([row, parent, 0, code, side, quantity, decision_row, 0, 0, decision_time, parent, detail], np.float64))


@njit(cache=True)
def control_event(log, integer_log, row, sequence, stamp, parent, code, side, support,
                  risk_r, lower, upper, escape, detail, anchor):
    """
    機能: risk・再参加・sessionの因果変更を疎に記録する。
    引数: log/integer_log(list[ndarray])、整数識別(int)、価格/時刻/内容(float)。
    返り値: None。原seqとanchor比較の整数値を別int64台帳にも保持する。
    """
    log.append(np.array([row, sequence, stamp, parent, code, side, support, risk_r,
                         lower, upper, escape, detail], np.float64))
    integer_log.append(np.array([row, sequence, parent, escape, anchor], np.int64))


@njit(cache=True)
def current_equity(phase, cash, side, quantity, multiplier, last_bid, last_ask, fee):
    """
    機能: 保有時の清算気配と残玉料、flat時の確定cashから当時時価を求める。
    引数: phase/side/quantity(int)、cash/multiplier/last_bid/last_ask/fee(float)。
    返り値: floatは全清算時価。不明気配時は呼出側がstale資格を分離する。
    """
    if phase == 2 or phase == 3:
        liquidation = last_bid if side == 1 else last_ask
        return cash + side * quantity * liquidation * multiplier - fee
    return cash


@njit(cache=True)
def simulate(times, sequence, bids, asks, qok, event, quality, reset, support_values,
             tick, start, limit, quantity, multiplier, fee_unit, initial_width, wide_width,
             support_ticks, profit_trail, cooldown, start_offset, cut_offset, force_offset,
             r_profit, alpha, beta, reentry_band, session_brake, budget_multiple,
             anchor_sequence, entry_filter, filter_reason, quiet, quiet_start_s, entry_families, target_prices, entry_stop_prices, entry_limit_prices, entry_modes, range_pending_trend):
    """
    機能: 新規予約・保有・返済予約だけで、B/Tの線と物理約定を原行順に進める。
    引数: 原行配列(ndarray)、整数量/支持幅(int)、価格/料/係数(float)、各部品(bool)、anchor/filter配列(ndarray)。
    返り値: tuple。104互換注文・親・玉・全行時価と105の制御判断・候補拒否・整数lineage。
    """
    n = len(times)
    orders = [np.zeros(17)]
    trades = [np.zeros(16)]
    cohorts = [np.zeros(25)]
    events = [np.zeros(12)]
    judgments = [np.zeros(30)]
    candidates = [np.zeros(10)]
    controls = [np.zeros(28)]
    control_events = [np.zeros(12)]
    control_integers = [np.zeros(5, np.int64)]
    candidate_controls = [np.zeros(18)]
    candidate_integers = [np.zeros(4,np.int64)]
    curve, trace, stale = np.zeros(n), np.zeros((n, 6), np.int32), np.ones(n, np.bool_)
    phase, parent, next_parent, side = 0, 0, 0, 0
    decision_row, fill_row, entry_decision, uid, entry_uid = -1, -1, -1, 0, 0
    decision_time, entry_decision_time, entry_time, last_exit = 0., 0., 0., -1e30
    entry, support, support_line, initial_line, peak, stop = 0., 0., 0., 0., 0., 0.
    reason, active, owner = 0, False, 0
    chosen_family, fixed_target, trade_r_profit = 0, np.nan, False
    fixed_range_stop, pending_limit, pending_mode, entry_reason = np.nan, np.nan, 0, 10
    cash, last_bid, last_ask = 0., np.nan, np.nan
    fee = math.floor(quantity * fee_unit + 1e-8)
    fee_width = math.ceil((2. * fee) / (quantity * multiplier * tick) - 1e-10) * tick
    initial_risk = 0.
    risk_r, risk_valid, fill_stop_broken = np.nan, False, False
    r_trail_width, r_floor_margin = np.nan, np.nan
    exact_fee_width = 2. * fee / (quantity * multiplier)
    bands_active = np.zeros(2, np.bool_)
    bands_anchor, bands_radius = np.full(2, np.nan), np.full(2, np.nan)
    escape_seq, escape_row = np.full(2, -1, np.int64), np.full(2, -1, np.int64)
    brake_latched, brake_first_row = False, -1
    brake_first_time, brake_first_equity = np.nan, np.nan
    session_budget = budget_multiple * initial_width * quantity * multiplier
    budget_excess = 0.
    previous_quote, previous_stop, previous_phase = np.nan, np.nan, -1
    force_time, entry_cut = limit - force_offset, limit - cut_offset
    eps = tick * 1e-8
    for row in range(n):
        stamp = times[row]
        just_exited = False
        price_judged, control_changed = False, False
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
        # ----------------------------------------
        # 静観開始は予定時計で判断する。通常予約fill前に取消し、場末forceは優先する。
        quiet_timer = np.isfinite(quiet_start_s[row])
        if phase == 1 and (quiet[row] or quiet_timer):
            append_event(events, row, parent, 6, side, quantity, decision_row, decision_time, 9.)
            control_event(control_events, control_integers, row, sequence[row], stamp, parent,
                13, side, support, risk_r, np.nan, np.nan, -1, quiet_start_s[row], -1)
            phase, control_changed = 0, True
        if quiet_timer and (phase == 2 or phase == 3) and stamp < force_time:
            phase, reason = 3, 9
            decision_row, decision_time = row - 1, quiet_start_s[row]
            append_event(events, row, parent, 2, side, quantity, decision_row, decision_time, 9.)
            control_event(control_events, control_integers, row, sequence[row], stamp, parent,
                12, side, support, risk_r, np.nan, np.nan, -1, decision_time, -1)
            control_changed = True
        # ----------------------------------------
        # 既知の確定損失又は正常清算時価で停止をラッチし、新規予約はfillより先に取消す。
        brake_qualifier = qok[row] or (phase != 2 and phase != 3)
        equity = current_equity(phase, cash, side, quantity, multiplier, last_bid, last_ask, fee)
        if session_brake and brake_qualifier:
            budget_excess = max(budget_excess, -session_budget - equity)
            if not brake_latched and equity <= -session_budget:
                brake_latched, brake_first_row = True, row
                brake_first_time, brake_first_equity = stamp, equity
                control_changed = True
                control_event(control_events, control_integers, row, sequence[row], stamp, parent,
                    7, side, support, risk_r, np.nan, np.nan, -1, equity, -1)
        if brake_latched and phase == 1:
            append_event(events, row, parent, 6, side, quantity, decision_row, decision_time, 7.)
            control_event(control_events, control_integers, row, sequence[row], stamp, parent,
                8, side, support, risk_r, np.nan, np.nan, -1, equity, -1)
            phase, control_changed = 0, True
        can_fill = (phase == 1 and qok[row] and row > decision_row and
            (chosen_family == 1 or pending_mode == 1 or
             (side == 1 and asks[row] <= pending_limit + eps) or (side == -1 and bids[row] >= pending_limit - eps)))
        if can_fill:
            entry = asks[row] if side == 1 else bids[row]
            fill_row, entry_time, entry_decision, entry_decision_time = row, stamp, decision_row, decision_time
            uid += 1
            entry_uid = uid
            entry_reason = 10 if chosen_family == 1 else 11 if pending_mode == 1 else 12
            orders.append(np.array([row, decision_row, parent, 0, side, quantity, entry, 1, entry_reason, fee, decision_time, stamp,
                pending_limit if chosen_family == 2 and pending_mode == 2 else 0., parent, entry_reason, side, uid], np.float64))
            cash -= side * quantity * entry * multiplier + fee
            phase = 2
            trade_r_profit = r_profit and chosen_family == 1
            support_line = support - side * support_ticks * tick if chosen_family == 1 else fixed_range_stop
            initial_line = entry - side * initial_width if chosen_family == 1 else np.nan
            stop = (max(support_line, initial_line) if side == 1 else min(support_line, initial_line)) if chosen_family == 1 else fixed_range_stop
            peak = bids[row] if side == 1 else asks[row]
            active = False
            initial_risk = side * quantity * multiplier * (entry - stop) + 2. * fee
            raw_r = side * (entry - stop) + exact_fee_width
            risk_valid = np.isfinite(raw_r) and raw_r > 0.
            risk_r = math.ceil(raw_r / tick - 1e-10) * tick if risk_valid else np.nan
            risk_valid = risk_valid and risk_r > 0.
            fill_stop_broken = side * (peak - stop) <= eps
            r_trail_width = max(tick, math.ceil(beta * risk_r / tick - 1e-10) * tick) if trade_r_profit and risk_valid else np.nan
            r_floor_margin = fee_width + (alpha - beta) * risk_r if trade_r_profit and risk_valid else np.nan
            control_changed = True
            control_event(control_events, control_integers, row, sequence[row], stamp, parent,
                1, side, support, risk_r, stop, fee_width, -1, initial_risk, anchor_sequence[entry_decision])
            if not risk_valid or fill_stop_broken:
                control_event(control_events, control_integers, row, sequence[row], stamp, parent,
                    2, side, support, risk_r, stop, fee_width, -1, raw_r, anchor_sequence[entry_decision])
            append_event(events, row, parent, 4, side, quantity, entry_decision, entry_decision_time, entry)
        elif phase == 3 and qok[row] and row > decision_row and stamp >= decision_time:
            price = bids[row] if side == 1 else asks[row]
            uid += 1
            orders.append(np.array([row, decision_row, parent, 0, -side, quantity, price, 0, reason, fee, decision_time, stamp, 0, parent, reason, side, uid], np.float64))
            cash += side * quantity * price * multiplier - fee
            gross = side * quantity * (price - entry) * multiplier
            net = gross - 2. * fee
            trades.append(np.array([parent, 0, fill_row, row, side, quantity, entry, price, fee, fee, gross, net, entry_reason, reason, parent, entry_decision], np.float64))
            cohorts.append(np.array([parent, parent, 0, side, quantity, entry_decision, sequence[entry_decision], entry_decision_time,
                fill_row, sequence[fill_row], entry_time, entry, fee, entry_uid, row, sequence[row], stamp, price, fee,
                gross, net, initial_width * quantity * multiplier, quantity, entry_reason, quantity], np.float64))
            append_event(events, row, parent, 5, side, quantity, decision_row, decision_time, price)
            phase, last_exit, just_exited = 0, stamp, True
            if reentry_band and net < 0.:
                band_index = 0 if side == 1 else 1
                if risk_valid:
                    bands_active[band_index] = True
                    bands_anchor[band_index], bands_radius[band_index] = support, risk_r
                    escape_seq[band_index], escape_row[band_index] = -1, -1
                    control_event(control_events, control_integers, row, sequence[row], stamp, parent,
                        3, side, support, risk_r, support-risk_r, support+risk_r, -1, net, -1)
                else:
                    control_event(control_events, control_integers, row, sequence[row], stamp, parent,
                        11, side, support, risk_r, np.nan, np.nan, -1, net, -1)
                control_changed = True

        # ----------------------------------------
        # Rの既live注文は到達fillを先に処理する。残った待機だけをTREND/固定stopで取消す。
        if phase == 1 and chosen_family == 2 and row > decision_row:
            pending_stop_broken = qok[row] and side * ((bids[row] if side == 1 else asks[row]) - fixed_range_stop) <= eps
            if range_pending_trend[row] or pending_stop_broken:
                cancel_reason = 12 if pending_stop_broken else 11
                append_event(events, row, parent, 6, side, quantity, decision_row, decision_time, float(cancel_reason))
                control_event(control_events, control_integers, row, sequence[row], stamp, parent,
                    14 if pending_stop_broken else 15, side, fixed_range_stop, risk_r, pending_limit, fixed_target, -1, 0., -1)
                phase, control_changed = 0, True

        # ----------------------------------------
        # 実fill行も正常清算気配で判断し、全停止線を有利側だけ更新する。
        if phase == 2 and qok[row]:
            quote = bids[row] if side == 1 else asks[row]
            peak = max(peak, quote) if side == 1 else min(peak, quote)
            before = stop
            wide_line, profit_line, fee_line = np.nan, np.nan, np.nan
            if chosen_family == 2:
                pass
            elif trade_r_profit:
                if risk_valid and not fill_stop_broken:
                    if side * (peak - entry) >= fee_width + alpha * risk_r - eps:
                        active = True
                    if active:
                        profit_line = peak - side * r_trail_width
                        fee_line = entry + side * r_floor_margin
                        stop = max(stop, profit_line, fee_line) if side == 1 else min(stop, profit_line, fee_line)
            elif profit_trail:
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
                        reason = 11 if chosen_family == 2 else j + 1
                        break
                assert reason != 0
                phase, decision_row, decision_time = 3, row, stamp
                append_event(events, row, parent, 2, side, quantity, row, stamp, float(reason))
            # ----------------------------------------
            # Rは判断時に固定した中心目標へ到達した原行で返済予約し、次正常quoteで約定する。
            if phase == 2 and chosen_family == 2 and side * (quote-fixed_target) >= -eps:
                phase, reason, decision_row, decision_time = 3, 10, row, stamp
                append_event(events, row, parent, 2, side, quantity, row, stamp, 10.)
            if row == fill_row or phase != previous_phase or quote != previous_quote or stop != previous_stop:
                judgments.append(np.array([row, sequence[row], stamp, parent, phase, side, 1, quote, support,
                    support_line, initial_line, peak, wide_line, profit_line, fee_line, 1 if active else 0, before, stop,
                    owner, hits[0], hits[1], hits[2], hits[3], hits[4], reason, fill_row, fee_width, initial_risk, chosen_family, fixed_target], np.float64))
                previous_quote, previous_stop, previous_phase = quote, stop, phase
                price_judged = True
            if trade_r_profit and not risk_valid and phase == 2:
                phase, reason, decision_row, decision_time = 3, 8, row, stamp
                append_event(events, row, parent, 2, side, quantity, row, stamp, 8.)
                control_event(control_events, control_integers, row, sequence[row], stamp, parent,
                    10, side, support, risk_r, stop, fee_width, -1, initial_risk, -1)
                control_changed = True

        # ----------------------------------------
        # fillの費用又は実返済で新しく破った予算も、当該行で新規停止・次quote返済へ結ぶ。
        brake_qualifier = qok[row] or (phase != 2 and phase != 3)
        equity = current_equity(phase, cash, side, quantity, multiplier, last_bid, last_ask, fee)
        if session_brake and brake_qualifier:
            budget_excess = max(budget_excess, -session_budget - equity)
            if not brake_latched and equity <= -session_budget:
                brake_latched, brake_first_row = True, row
                brake_first_time, brake_first_equity = stamp, equity
                control_changed = True
                control_event(control_events, control_integers, row, sequence[row], stamp, parent,
                    7, side, support, risk_r, np.nan, np.nan, -1, equity, -1)
        if brake_latched and phase == 2:
            phase, reason, decision_row, decision_time = 3, 7, row, stamp
            append_event(events, row, parent, 2, side, quantity, row, stamp, 7.)
            control_event(control_events, control_integers, row, sequence[row], stamp, parent,
                9, side, support, risk_r, np.nan, np.nan, -1, equity, -1)
            control_changed = True

        # ----------------------------------------
        # 損失帯は価格の別正常原行脱出と新anchorだけで解除する。不明は破綻へ代用しない。
        if reentry_band:
            for band_index in range(2):
                if not bands_active[band_index]:
                    continue
                band_side = 1 if band_index == 0 else -1
                proof_bad = not qok[row] or reset[row]
                band_quote = bids[row] if band_side == 1 else asks[row]
                outside = not proof_bad and band_side * (band_quote-bands_anchor[band_index]) > bands_radius[band_index] + eps
                if proof_bad or not outside:
                    if escape_seq[band_index] >= 0:
                        control_event(control_events, control_integers, row, sequence[row], stamp, parent,
                            5, band_side, bands_anchor[band_index], bands_radius[band_index],
                            bands_anchor[band_index]-bands_radius[band_index], bands_anchor[band_index]+bands_radius[band_index],
                            escape_seq[band_index], 1. if not qok[row] else 2. if reset[row] else 3., -1)
                        control_changed = True
                    escape_seq[band_index], escape_row[band_index] = -1, -1
                elif escape_seq[band_index] < 0:
                    escape_seq[band_index], escape_row[band_index] = sequence[row], row
                    control_event(control_events, control_integers, row, sequence[row], stamp, parent,
                        4, band_side, bands_anchor[band_index], bands_radius[band_index],
                        bands_anchor[band_index]-bands_radius[band_index], bands_anchor[band_index]+bands_radius[band_index],
                        escape_seq[band_index], band_quote, -1)
                    control_changed = True

        # ----------------------------------------
        # 候補は当該原行で消費し、予約・保有・返済後の将来へ補充しない。
        if event[row] != 0:
            band_index = 0 if event[row] == 1 else 1
            band_released = False
            band_was_active = reentry_band and bands_active[band_index]
            remembered_anchor, remembered_radius, remembered_escape = bands_anchor[band_index], bands_radius[band_index], escape_seq[band_index]
            release_ready = (band_was_active and qok[row] and quality[row] and not reset[row]
                and phase == 0 and not just_exited and entry_filter[row] and not brake_latched
                and stamp >= start+start_offset and stamp < entry_cut and stamp-last_exit >= cooldown
                and escape_row[band_index] >= 0 and row > escape_row[band_index]
                and anchor_sequence[row] > escape_seq[band_index]
                and event[row] * (support_values[row]-bands_anchor[band_index]) > bands_radius[band_index] + eps)
            if release_ready:
                bands_active[band_index] = False
                band_released = True
                control_event(control_events, control_integers, row, sequence[row], stamp, parent,
                    6, int(event[row]), remembered_anchor, remembered_radius,
                    remembered_anchor-remembered_radius, remembered_anchor+remembered_radius,
                    remembered_escape, support_values[row], anchor_sequence[row])
                escape_seq[band_index], escape_row[band_index] = -1, -1
                control_changed = True
            band_block = reentry_band and bands_active[band_index]
            blocked = 0
            if phase != 0 or just_exited: blocked |= 1
            if not qok[row]: blocked |= 2
            if entry_families[row] == 1 and not quality[row]: blocked |= 4
            if entry_families[row] == 1 and reset[row]: blocked |= 8
            if not (stamp >= start+start_offset and stamp < entry_cut): blocked |= 16
            if not stamp-last_exit >= cooldown: blocked |= 32
            if not entry_filter[row]: blocked |= 64
            if brake_latched: blocked |= 128
            if band_block: blocked |= 256
            if quiet[row]: blocked |= 512
            allowed = blocked == 0
            rejected = 0
            if blocked & 512: rejected = 10
            elif blocked & 128: rejected = 8
            elif blocked & 256: rejected = 9
            elif blocked & 64: rejected = 7
            else:
                for bit in range(6):
                    if blocked & (1 << bit):
                        rejected = bit+1
                        break
            candidates.append(np.array([row, sequence[row], stamp, event[row], phase, qok[row], quality[row], reset[row], allowed, support_values[row]], np.float64))
            candidate_controls.append(np.array([row, sequence[row], stamp, event[row], phase, allowed, rejected,
                blocked, entry_filter[row], filter_reason[row], band_was_active, remembered_anchor, remembered_radius,
                remembered_escape, anchor_sequence[row], support_values[row], band_released, brake_latched], np.float64))
            candidate_integers.append(np.array([row,sequence[row],anchor_sequence[row],remembered_escape],np.int64))
            control_changed = True
            if allowed:
                assert np.isfinite(support_values[row]) and support_values[row] > 0
                chosen_family = int(entry_families[row])
                assert chosen_family == 1 or chosen_family == 2
                fixed_target = target_prices[row]
                pending_mode = int(entry_modes[row]) if chosen_family == 2 else 1
                pending_limit = entry_limit_prices[row]
                fixed_range_stop = entry_stop_prices[row]
                if chosen_family == 2:
                    assert np.isfinite(fixed_target) and fixed_target > 0
                    assert np.isfinite(fixed_range_stop) and fixed_range_stop > 0 and pending_mode in (1,2)
                    assert event[row] * (fixed_target - fixed_range_stop) > 0.
                    assert pending_mode == 1 or (np.isfinite(pending_limit) and pending_limit > 0.)
                next_parent += 1
                parent, side, support, phase = next_parent, int(event[row]), support_values[row], 1
                risk_r, risk_valid, fill_stop_broken = np.nan, False, False
                r_trail_width, r_floor_margin = np.nan, np.nan
                decision_row, decision_time = row, stamp
                append_event(events, row, parent, 1, side, quantity, row, stamp, support)
            else:
                append_event(events, row, 0, 9, int(event[row]), quantity, row, stamp, phase)
        if price_judged or control_changed:
            controls.append(np.array([row, sequence[row], stamp, parent, phase, side, risk_r, risk_valid,
                fill_stop_broken, alpha, beta, exact_fee_width, r_trail_width, r_floor_margin, active, stop,
                equity, session_budget, brake_latched, brake_qualifier, bands_active[0], bands_active[1],
                bands_anchor[0], bands_anchor[1], bands_radius[0], bands_radius[1], escape_seq[0], escape_seq[1]], np.float64))
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
    control_stats = np.array([session_brake, session_budget, brake_latched, brake_first_row,
        brake_first_time, brake_first_equity, max(0., budget_excess), bands_active[0], bands_active[1]], np.float64)
    return (orders[1:], trades[1:], cohorts[1:], events[1:], judgments[1:], candidates[1:], curve, trace, stale, cash,
            controls[1:], control_events[1:], control_integers[1:], candidate_controls[1:], control_stats,candidate_integers[1:])


def execute(record: dict, signal: dict, config: dict, finish: bool = True, python: bool = False) -> dict:
    """
    機能: 同一正常原行の候補を105へ渡し、104互換の物理出力と制御診断を返す。
    引数: record/signal/config(dict)、finish(bool)は完全入力flat要求、python(bool)は人工対照。
    返り値: dict。注文・親・玉・全行時価・疎な判断と制御台帳。原本/APIは呼ばない。
    """
    assert isinstance(config['id'], str) and config['id']
    if python:
        assert record.get('人工素材') is True
    symbol = record['symbol']
    assert symbol in ('TOPIX', 'NK225')
    multiplier, fee_unit, cap = (1000., 41.8, 10) if symbol == 'TOPIX' else (10., 11., 20)
    quantity = config['quantity']
    assert isinstance(quantity, int) and not isinstance(quantity,bool) and 0 < quantity <= cap
    assert isinstance(config['support_ticks'],int) and config['support_ticks'] > 0
    assert np.isfinite(config['initial_stop_fraction']) and config['initial_stop_fraction'] > 0.
    n, tick = len(record['time_s']), float(record['tick'])
    if finish:
        assert n and record['time_s'][-1] >= record['limit'], '完全入力にはlimit到達の原行が必要です'
    for name in ('event', 'support_price', 'entry_quality', 'entry_reset'):
        assert signal[name].shape == (n,)
    assert signal['event'].dtype == np.int8 and np.isin(signal['event'], (-1, 0, 1)).all()
    assert signal['entry_quality'].dtype == signal['entry_reset'].dtype == np.bool_
    assert np.isfinite(signal['reference_open']) and signal['reference_open'] > 0 and tick > 0
    r_profit, reentry_band, session_brake = (config.get(name, False) for name in ('r_profit','reentry_band','session_brake'))
    assert all(isinstance(value, bool) for value in (r_profit,reentry_band,session_brake,config['profit_trail']))
    alpha, beta = float(config.get('alpha', 2.)), float(config.get('beta', 1.))
    if r_profit:
        assert np.isfinite(alpha) and np.isfinite(beta) and alpha > beta > 0.
    budget_multiple = float(config.get('session_budget_multiple', 0.))
    assert not session_brake or np.isfinite(budget_multiple) and budget_multiple > 0.
    anchor_sequence = signal.get('anchor_raw_seq', np.full(n,-1,np.int64))
    entry_filter = signal.get('entry_filter',np.ones(n,bool))
    filter_reason = signal.get('filter_reason',np.zeros(n,np.int32))
    assert anchor_sequence.dtype == np.int64 and anchor_sequence.shape == (n,)
    assert entry_filter.dtype == np.bool_ and entry_filter.shape == (n,)
    assert np.issubdtype(filter_reason.dtype,np.integer) and filter_reason.shape == (n,)
    assert np.all(anchor_sequence[signal['event'] != 0] <= record['seq'][signal['event'] != 0])
    if reentry_band:
        assert (anchor_sequence[signal['event'] != 0] >= 0).all(), '損失帯には当時選択された根拠の原seqが必須です'
    initial_width = max(2, math.ceil(signal['reference_open'] * config['initial_stop_fraction'] / tick - 1e-10)) * tick
    wide_width = float(signal['trend_width'])
    assert np.isfinite(wide_width) and wide_width > 0
    flag = record['quote_valid']
    qok = (flag & np.isfinite(record['time_s']) & np.isfinite(record['bid']) & np.isfinite(record['ask'])
            & (record['bid'] > 0) & (record['ask'] > record['bid']))
    quiet=signal.get('quiet',np.zeros(n,np.bool_))
    quiet_start_s=signal.get('quiet_start_s',np.full(n,np.nan,np.float64))
    assert quiet.dtype==np.bool_ and quiet.shape==(n,)
    assert quiet_start_s.dtype==np.float64 and quiet_start_s.shape==(n,)
    assert np.all(quiet_start_s[np.isfinite(quiet_start_s)]<=record['time_s'][np.isfinite(quiet_start_s)])
    entry_families=signal.get('entry_families',np.where(signal['event']!=0,1,0).astype(np.int8))
    target_prices=signal.get('target_prices',np.full(n,np.nan,np.float64))
    assert entry_families.shape==(n,) and entry_families.dtype==np.int8
    assert target_prices.shape==(n,) and target_prices.dtype==np.float64
    assert np.all(np.isin(entry_families[signal['event']!=0],(1,2)))
    assert not r_profit and not reentry_band and not session_brake and not config['profit_trail'], '24対照はC_B4/R固定線だけです'
    entry_stop_prices=signal['entry_stop_prices'];entry_limit_prices=signal['entry_limit_prices']
    entry_modes=signal['entry_modes'];range_pending_trend=signal['range_pending_trend']
    for array in (entry_stop_prices,entry_limit_prices):assert array.dtype==np.float64 and array.shape==(n,)
    assert entry_modes.dtype==np.int8 and entry_modes.shape==(n,)
    assert range_pending_trend.dtype==np.bool_ and range_pending_trend.shape==(n,)
    function = simulate.py_func if python else simulate
    values = function(record['time_s'], record['seq'], record['bid'], record['ask'], qok,
        signal['event'], signal['entry_quality'], signal['entry_reset'], signal['support_price'], tick,
        float(record['start']), float(record['limit']), quantity, multiplier, fee_unit, initial_width, wide_width,
        int(config['support_ticks']), bool(config['profit_trail']), float(config['cooldown_seconds']),
        float(config['start_offset']), float(config['cut_offset']), float(config['force_offset']),
        r_profit,alpha,beta,reentry_band,session_brake,budget_multiple,anchor_sequence,entry_filter,filter_reason,quiet,quiet_start_s,entry_families,target_prices,entry_stop_prices,entry_limit_prices,entry_modes,range_pending_trend)
    orders, trades, cohorts, events, judgments, candidates = [np.asarray(values[j], np.float64).reshape(-1, width)
        for j, width in enumerate((17, 16, 25, 12, 30, 10))]
    curve, trace, stale, cash = values[6:10]
    controls, control_events, control_integers, candidate_controls = [
        np.asarray(values[index],dtype).reshape(-1,width) for index,width,dtype in
        ((10,28,np.float64),(11,12,np.float64),(12,5,np.int64),(13,18,np.float64))]
    control_stats = values[14]
    candidate_integers = np.asarray(values[15],np.int64).reshape(-1,4)
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
        risk_definition='initial_risk_yenは初期有効線での費用後予定損失のsigned値。Rはその価格幅を呼値切上げしてfill時固定。負又は0のRは不正として別記。次quoteの実損失上限ではない。',
        control_judgments=controls,control_columns=CONTROL_COLUMNS,
        control_events=control_events,control_event_columns=CONTROL_EVENT_COLUMNS,control_event_codes=CONTROL_CODES,
        control_integer_events=control_integers,control_integer_columns=CONTROL_INTEGER_COLUMNS,
        candidate_controls=candidate_controls,candidate_control_columns=CANDIDATE_CONTROL_COLUMNS,rejections=REJECTIONS,
        candidate_integer_keys=candidate_integers,candidate_integer_columns=['row','raw_seq','anchor_raw_seq','escape_raw_seq'],
        control_stats=control_stats,control_stat_columns=['session_brake_enabled','session_budget_yen','brake_latched',
            'brake_first_row','brake_first_time','brake_first_equity','max_budget_excess_yen','long_band_active','short_band_active'],
        config_id=config['id'],legacy_exit_id=('T' if config['profit_trail'] else 'B')+str(config['support_ticks']),
        effective_exit='R' if r_profit else ('T' if config['profit_trail'] else 'B')+str(config['support_ticks']),
        component_settings=dict(r_profit=r_profit,alpha=alpha,beta=beta,reentry_band=reentry_band,
            session_brake=session_brake,session_budget_multiple=budget_multiple),
        risk_R_definition='R=ceil_tick(d*(E-L0)+exact_roundtrip_fees/(q*m))。非正は不正、利益R管理及び損失帯へ使用しない。',
        brake_definition='budget=h*S*q*m。各実qty単一口座の当時清算時価で停止。次quote約定でbudget超過はあり得る。二腿共通brakeではない。')
