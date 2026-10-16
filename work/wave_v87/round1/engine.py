"""料金後黒字の再参加へ、新しい同調周期と前組高安突破を加える別生成器。"""
from __future__ import annotations
import numpy as np
from numba import njit
from wave85_engine import close_slots, shadow_engine, FIELDS
import wave86_shadow as shadow_original
@njit(cache=True)
def simulate(time, price, good, good_source, good_valid, end, cutoff, q0, cap, kind, fraction, restore_mode, maximum, restore_seconds, observed_fill, detail, budget_enabled, min_delay_seconds, branch_direction, branch_source, branch_valid, branch_choice, branch_mode, branch_seed, losspar, raw_bad, raw_source, raw_valid, ema_direction, ema_source, ema_peer_source, ema_valid, quiet, quiet_force, quiet_not_before, atr, state, tick, start, us_open, session_close, ns_par, xs_par, signal_bad, signal_source, signal_valid, dynamic, dynamic_activation, dynamic_width, cooldown_seconds, profit_fast_enabled, reentry_filter):
    """機能: 通常影、改修出口影、実玉を同じ保存観測の順で更新する。

    引数: time/price/atr/state と公開根拠・静観配列(ndarray)、両影設定(ns_par/xs_par:ndarray)、
    数量・方針(int)、閾値・実返済後休止(float)、約定モデル・詳細(bool)。
    返り値: 旧実玉18配列と両影計画・準備・幅短縮・実返済時計・半減根拠(tuple[ndarray,...])。
    現在行で作った条件は次の原本行以降へ適用し、料金後黒字の実全返済だけ、次行から両影を再準備する。赤字・ゼロは元通常影の終了を待つ。
    通常影のMFEを途中半減へ使い、EMA・ATR・B00の過去情報を消さない。"""
    n = len(price)
    restart_active = False
    restart_side = 0
    restart_row = -1
    restart_extreme = np.nan
    restart_seen_row = -1
    actual_extreme = np.nan
    restart_events = np.zeros((24000, 10))
    restart_count = 0
    ns_ready_after=-np.inf
    xs_ready_after=-np.inf
    profit_restart_pending=False
    profit_reentry_events=np.zeros((12000,7))
    profit_reentry_count=0
    ns_dynamic_events = np.zeros((12000, 7))
    ns_dynamic_count = 0
    ns_narrowed = False
    n = len(price)
    ns_pos = np.zeros((12000, 5))
    ns_trades = np.zeros((24000, 11))
    ns_plans = np.full((n, 37), np.nan)
    ns_execution_plans = np.full((n, 37), np.nan)
    ns_mature_row = -1
    ns_prepare_events = np.zeros((n, 7))
    ns_prepare_count = 0
    ns_entry_preparations = np.zeros((2000, 4))
    ns_entry_prepare_count = 0
    ns_pending_prepare_id = -1
    ns_pending_prepare_row = -1
    ns_atr_curve = np.full((n, 12), np.nan) if detail else np.full((1, 12), np.nan)
    ns_current_atr = 1.0
    ns_current_atr_source = -1
    ns_trail_source = -1
    ns_orders = np.zeros((36000, 8))
    ns_cycles = np.zeros((2000, 10))
    ns_curve = np.zeros((n, 8)) if detail else np.zeros((1, 8))
    ns_used = 0
    ns_tc = 0
    ns_oc = 0
    ns_cc = 0
    ns_campaign = -1
    ns_d = 0
    ns_realized = 0.0
    ns_base = 0.0
    ns_cash = 0.0
    ns_inv = np.zeros(6)
    ns_a = 1.0
    ns_risk = 1.0
    ns_peak = 0.0
    ns_anchor = 0.0
    ns_extreme = 0.0
    ns_cover_extreme = 0.0
    ns_cover_anchor = 0.0
    ns_next_add = 0.0
    ns_next_cover = 0.0
    ns_entry_row = 0
    ns_entry_t = 0.0
    ns_last_exit = -1e+20
    ns_pending_d = 0
    ns_pending_level = 0.0
    ns_pending_until = 0.0
    ns_pending_atr = 0.0
    ns_pending_row = -1
    ns_pending_action = 0
    ns_action_row = -1
    ns_neutral_since = -1.0
    ns_reversals = 0
    ns_split_done = False
    ns_stop_level = np.nan
    ns_main_level = np.nan
    ns_cover_level = np.nan
    ns_cover_reason = 0
    ns_cover_open_level = np.nan
    ns_add_level = np.nan
    ns_split_level = np.nan
    ns_stop_reason = 1
    ns_market_flags = np.zeros(6, dtype=np.bool_)
    ns_high_equity = 0.0
    ns_dd = 0.0
    ns_maxlong = 0.0
    ns_maxshort = 0.0
    ns_maxgross = 0.0
    ns_maxnet = 0.0
    ns_cycle_gross = 0.0
    ns_cycle_net = 0.0
    ns_max_error = 0.0
    ns_min_equity = 0.0
    ns_max_equity = 0.0
    ns_protected_floor = -1e+100
    ns_main_floor = np.nan
    ns_pending_extreme = 0.0
    ns_effective_qty = int(ns_par[0])
    ns_pending_qty = int(ns_par[0])
    ns_pending_market = False
    ns_loss_streak = np.zeros(2, dtype=np.int64)
    ns_blocked = np.zeros(2, dtype=np.bool_)
    ns_blocked_price = np.zeros(2)
    ns_blocked_atr = np.ones(2)
    ns_campaign_side = 0
    ns_session_halted = False
    ns_session_budget = np.nan
    if ns_par[38] > 0:
        ns_session_budget = ns_par[38] / ns_par[37]
    xs_dynamic_events = np.zeros((12000, 7))
    xs_dynamic_count = 0
    xs_narrowed = False
    n = len(price)
    xs_pos = np.zeros((12000, 5))
    xs_trades = np.zeros((24000, 11))
    xs_plans = np.full((n, 37), np.nan)
    xs_execution_plans = np.full((n, 37), np.nan)
    xs_mature_row = -1
    xs_prepare_events = np.zeros((n, 7))
    xs_prepare_count = 0
    xs_entry_preparations = np.zeros((2000, 4))
    xs_entry_prepare_count = 0
    xs_pending_prepare_id = -1
    xs_pending_prepare_row = -1
    xs_atr_curve = np.full((n, 12), np.nan) if detail else np.full((1, 12), np.nan)
    xs_current_atr = 1.0
    xs_current_atr_source = -1
    xs_trail_source = -1
    xs_orders = np.zeros((36000, 8))
    xs_cycles = np.zeros((2000, 10))
    xs_curve = np.zeros((n, 8)) if detail else np.zeros((1, 8))
    xs_used = 0
    xs_tc = 0
    xs_oc = 0
    xs_cc = 0
    xs_campaign = -1
    xs_d = 0
    xs_realized = 0.0
    xs_base = 0.0
    xs_cash = 0.0
    xs_inv = np.zeros(6)
    xs_a = 1.0
    xs_risk = 1.0
    xs_peak = 0.0
    xs_anchor = 0.0
    xs_extreme = 0.0
    xs_cover_extreme = 0.0
    xs_cover_anchor = 0.0
    xs_next_add = 0.0
    xs_next_cover = 0.0
    xs_entry_row = 0
    xs_entry_t = 0.0
    xs_last_exit = -1e+20
    xs_pending_d = 0
    xs_pending_level = 0.0
    xs_pending_until = 0.0
    xs_pending_atr = 0.0
    xs_pending_row = -1
    xs_pending_action = 0
    xs_action_row = -1
    xs_neutral_since = -1.0
    xs_reversals = 0
    xs_split_done = False
    xs_stop_level = np.nan
    xs_main_level = np.nan
    xs_cover_level = np.nan
    xs_cover_reason = 0
    xs_cover_open_level = np.nan
    xs_add_level = np.nan
    xs_split_level = np.nan
    xs_stop_reason = 1
    xs_market_flags = np.zeros(6, dtype=np.bool_)
    xs_high_equity = 0.0
    xs_dd = 0.0
    xs_maxlong = 0.0
    xs_maxshort = 0.0
    xs_maxgross = 0.0
    xs_maxnet = 0.0
    xs_cycle_gross = 0.0
    xs_cycle_net = 0.0
    xs_max_error = 0.0
    xs_min_equity = 0.0
    xs_max_equity = 0.0
    xs_protected_floor = -1e+100
    xs_main_floor = np.nan
    xs_pending_extreme = 0.0
    xs_effective_qty = int(xs_par[0])
    xs_pending_qty = int(xs_par[0])
    xs_pending_market = False
    xs_loss_streak = np.zeros(2, dtype=np.int64)
    xs_blocked = np.zeros(2, dtype=np.bool_)
    xs_blocked_price = np.zeros(2)
    xs_blocked_atr = np.ones(2)
    xs_campaign_side = 0
    xs_session_halted = False
    xs_session_budget = np.nan
    if xs_par[38] > 0:
        xs_session_budget = xs_par[38] / xs_par[37]
    plans = xs_plans
    execution_plans = xs_execution_plans
    shadow_atr = xs_atr_curve
    bad = np.zeros(n, np.int8)
    bad_source = signal_source
    ns_allow = np.zeros(n, np.bool_)
    xs_allow = np.zeros(n, np.bool_)
    feedback_row = -1
    feedback_price = 0.0
    reentry_events = np.zeros((12000, 6))
    reentry_count = 0
    gate_arm = -1
    gate_campaign = -1
    gate_entry = -1
    gate_mfe = np.zeros(n)
    gate_arm_rows = np.full(n, -1, np.int64)
    gate_armed = np.zeros(n, np.bool_)
    gate_eligible = np.zeros(n, np.bool_)
    n = len(price)
    if quiet is None:
        quiet = np.zeros(n, np.bool_)
    if quiet_force is None:
        quiet_force = np.zeros(n, np.bool_)
    if quiet_not_before is None:
        quiet_not_before = np.full(n, -np.inf)
    time_events = np.zeros((12000, 7))
    qc = 0
    last_quiet_prepare = -1
    pos = np.zeros((12000, 5))
    used = 0
    trades = np.zeros((24000, 11))
    tc = 0
    orders = np.zeros((36000, 8))
    oc = 0
    cycles = np.zeros((2000, 10))
    cc = 0
    curve = np.zeros((n, 8)) if detail else np.zeros((1, 8))
    atr_curve = shadow_atr.copy() if detail else np.full((1, 12), np.nan)
    control = np.zeros((n, 20)) if detail else np.zeros((1, 20))
    slot_curve = np.zeros((n, q0), dtype=np.int8) if detail else np.zeros((1, q0), dtype=np.int8)
    slot_events = np.zeros((100000, 11))
    sc = 0
    adjustment = np.zeros((24000, 11))
    ac = 0
    budgets = np.zeros((6000, 8))
    bc = 0
    branch_events = np.zeros((12000, 10))
    brc = 0
    branch_curve = np.full((n, 4), -1.0) if detail else np.full((1, 4), -1.0)
    chosen_restore = restore_mode
    branch_row = -1
    branch_evidence = -1
    branch_class = 0
    alive = np.zeros(q0, dtype=np.bool_)
    restorable = np.zeros(q0, dtype=np.bool_)
    slot_leg = np.full(q0, -1, dtype=np.int64)
    pending_slots = np.zeros(q0, dtype=np.bool_)
    split_count = q0 // 2
    campaign = -1
    shadow_campaign = -1
    d = 0
    entry_row = -1
    base = 0.0
    a = 1.0
    risk = 1.0
    closed = True
    phase = 0
    reductions = 0
    barrier = -1
    reduction_row = -1
    reduction_time = 0.0
    pending = 0
    pending_row = -1
    pending_evidence = -1
    budget = False
    budget_row = -1
    budget_time = 0.0
    realized = 0.0
    cash = 0.0
    high_equity = 0.0
    dd = 0.0
    min_equity = 0.0
    max_equity = 0.0
    max_error = 0.0
    maxlong = 0.0
    maxshort = 0.0
    maxgross = 0.0
    maxnet = 0.0
    cycle_max = 0.0
    last_exit = -1e+20
    inv = np.zeros(6)
    early_peak = 0.0
    early_action = 0
    early_row = -1
    early_evidence = -1
    reduce_reason = 30
    actual_anchor = 0.0
    campaign_fees = 0.0
    loss_streak = 0
    cumulative_r = 0.0
    pause_until = -1e+20
    risk_events = np.zeros((12000, 10))
    rc = 0
    guard_peak = 0.0
    guard_floor = -np.inf
    guard_pending = False
    guard_row = -1
    guard_curve = np.zeros((n, 8)) if detail else np.zeros((1, 8))
    guard_events = np.zeros((36000, 10))
    gc = 0
    block_events = np.zeros((24000, 8))
    xc = 0
    direction_losses = np.zeros(2, np.int64)
    blocked = np.zeros(2, np.bool_)
    reset_seen = np.zeros(2, np.bool_)
    block_row = np.full(2, -1, np.int64)
    reset_own = np.full(2, -1, np.int64)
    reset_peer = np.full(2, -1, np.int64)
    for i in range(n):
        # ----------------------------------------
        # 実組の保有中の現在値だけで極値を更新する。返済観測を含む。
        if not closed and np.isfinite(price[i]) and price[i] > 0:
            actual_extreme = max(actual_extreme, price[i]) if d > 0 else min(actual_extreme, price[i])
        # 欠測や古いEMAは非支持の観測に数えない。
        if restart_active and restart_seen_row < 0 and i > restart_row and ema_valid[i] and ema_direction[i] != restart_side and ema_source[i] > restart_row and ema_peer_source[i] > restart_row:
            restart_seen_row = i
            if restart_count >= len(restart_events): raise ValueError('再参加条件証跡の上限です')
            restart_events[restart_count,:] = np.array([i, 2, restart_row, restart_side, restart_extreme, restart_seen_row, ema_source[i], ema_peer_source[i], state[i], np.nan])
            restart_count += 1
        restart_ok = True
        if restart_active and state[i] == restart_side and reentry_filter & 1:
            restart_ok = restart_seen_row >= 0 and ema_valid[i] and ema_direction[i] == restart_side and ema_source[i] > restart_row and ema_peer_source[i] > restart_row
        if feedback_row >= 0:
            profit_restart_pending=True
            if reentry_count >= len(reentry_events):
                raise ValueError('実返済時計証跡の保存上限です')
            reentry_events[reentry_count, :] = np.array([feedback_row, i, time[feedback_row] + cooldown_seconds, campaign, ns_campaign, xs_campaign])
            reentry_count += 1
        ns_allow[i] = closed and restart_ok and (not profit_restart_pending or (not quiet[i] and not quiet_force[i]))
        if feedback_row >= 0:
            if ns_d != 0 and ns_inv[0] + ns_inv[1] > 0.5:
                ns_oldtc = ns_tc
                ns_tc, ns_gain, ns_done = shadow_original.close_positions(ns_pos, ns_used, ns_trades, ns_tc, -1, 100000, feedback_price, feedback_row, 72, ns_campaign)
                ns_realized += ns_gain
                for ns_k in range(ns_oldtc, ns_tc):
                    if ns_oc >= len(ns_orders):
                        raise ValueError('影終了の記録上限です')
                    ns_cash += ns_trades[ns_k, 2] * ns_trades[ns_k, 3] * feedback_price
                    ns_orders[ns_oc, :] = np.array([feedback_row, feedback_row - 1, ns_campaign, -ns_trades[ns_k, 2], ns_trades[ns_k, 3], feedback_price, 72.0, 0.0])
                    ns_oc += 1
                ns_inv = shadow_original.inventory(ns_pos, ns_used)
                if ns_cc >= len(ns_cycles):
                    raise ValueError('影組の記録上限です')
                ns_cycles[ns_cc, :] = np.array([ns_campaign, ns_entry_row, feedback_row, ns_realized - ns_base, ns_risk, ns_a, ns_cycle_gross, ns_cycle_net, ns_d, 72.0])
                ns_cc += 1
            ns_d = 0
            ns_pending_d = 0
            ns_pending_action = 0
            ns_pending_prepare_row = -1
            ns_pending_prepare_id = -1
            ns_pending_until = 0.0
            ns_pending_row = -1
            ns_main_floor = np.nan
            ns_main_level = np.nan
            ns_stop_level = np.nan
            ns_split_level = np.nan
            ns_split_done = False
            ns_narrowed = False
            ns_peak = 0.0
            ns_last_exit = time[feedback_row]
            ns_ready_after=time[feedback_row]+cooldown_seconds
            ns_neutral_since = -1.0
        if feedback_row >= 0:
            if xs_d != 0 and xs_inv[0] + xs_inv[1] > 0.5:
                xs_oldtc = xs_tc
                xs_tc, xs_gain, xs_done = shadow_original.close_positions(xs_pos, xs_used, xs_trades, xs_tc, -1, 100000, feedback_price, feedback_row, 72, xs_campaign)
                xs_realized += xs_gain
                for xs_k in range(xs_oldtc, xs_tc):
                    if xs_oc >= len(xs_orders):
                        raise ValueError('影終了の記録上限です')
                    xs_cash += xs_trades[xs_k, 2] * xs_trades[xs_k, 3] * feedback_price
                    xs_orders[xs_oc, :] = np.array([feedback_row, feedback_row - 1, xs_campaign, -xs_trades[xs_k, 2], xs_trades[xs_k, 3], feedback_price, 72.0, 0.0])
                    xs_oc += 1
                xs_inv = shadow_original.inventory(xs_pos, xs_used)
                if xs_cc >= len(xs_cycles):
                    raise ValueError('影組の記録上限です')
                xs_cycles[xs_cc, :] = np.array([xs_campaign, xs_entry_row, feedback_row, xs_realized - xs_base, xs_risk, xs_a, xs_cycle_gross, xs_cycle_net, xs_d, 72.0])
                xs_cc += 1
            xs_d = 0
            xs_pending_d = 0
            xs_pending_action = 0
            xs_pending_prepare_row = -1
            xs_pending_prepare_id = -1
            xs_pending_until = 0.0
            xs_pending_row = -1
            xs_main_floor = np.nan
            xs_main_level = np.nan
            xs_stop_level = np.nan
            xs_split_level = np.nan
            xs_split_done = False
            xs_narrowed = False
            xs_peak = 0.0
            xs_last_exit = time[feedback_row]
            xs_ready_after=time[feedback_row]+cooldown_seconds
            xs_neutral_since = -1.0
        # ----------------------------------------
        # 通常影の更新。元の半減根拠となる価格進捗を保つ。
        for ns_once in range(1):
            ns_p = price[i]
            ns_t = time[i]
            if ns_d != 0 and np.isfinite(atr[i]) and (atr[i] > 0):
                ns_current_atr = max(atr[i], tick * 2)
                ns_current_atr_source = i
            if not np.isfinite(ns_p) or ns_p <= 0:
                if i > 0:
                    ns_plans[i, :] = ns_plans[i - 1, :]
                if detail:
                    ns_atr_curve[i, :] = np.array([ns_d, ns_a if ns_d else np.nan, ns_current_atr if ns_d else np.nan, (ns_a if 0 == 0 else ns_current_atr) if ns_d else np.nan, ns_extreme if ns_d else np.nan, int(ns_d != 0 and np.isfinite(ns_main_level)), ns_main_level, ns_risk if ns_d else np.nan, ns_stop_level, ns_pending_atr if ns_pending_d else np.nan, ns_current_atr_source if ns_d else -1, ns_trail_source if ns_d else -1])
                continue
            ns_acted = False
            ns_fill = 0.0
            ns_open_side = 0
            ns_open_qty = 0
            ns_open_role = 0
            ns_order_source = i - 1
            ns_reason = 0
            ns_close_role = -2
            ns_close_qty = 0
            ns_promote = False
            while ns_mature_row + 1 < i and time[ns_mature_row + 1] <= ns_t - min_delay_seconds + 1e-09:
                ns_mature_row += 1
            ns_effective = np.full(37, np.nan)
            if ns_mature_row >= 0 and np.isfinite(ns_plans[ns_mature_row, 33]):
                ns_candidate = ns_plans[ns_mature_row]
                if int(ns_candidate[1]) == ns_campaign and int(ns_candidate[0]) == ns_d:
                    ns_effective = ns_candidate.copy()
                    ns_effective[7] = ns_inv[0]
                    ns_effective[8] = ns_realized
                    ns_effective[9] = ns_base
                    if ns_split_done:
                        ns_effective[14] = np.nan
                        ns_effective[17] = 0.0
                    ns_effective[11] = int(ns_split_done)
            if ns_t >= session_close:
                if ns_d != 0:
                    raise ValueError('終場までに有効な全返済行がありません')
                ns_effective[:] = np.nan
            if False or False or (ns_pending_prepare_row >= 0 and time[ns_pending_prepare_row] < -np.inf):
                ns_pending_d = 0
                ns_effective[21] = 0.0
            if False and ns_d != 0:
                ns_effective[18] = 71.0
                ns_effective[19] = i - 1
            if feedback_row >= 0:
                ns_effective[:] = np.nan
            ns_execution_plans[i, :] = ns_effective
            if np.isfinite(ns_effective[33]):
                ns_order_source = i - 1 if min_delay_seconds == 0 else int(ns_effective[33])
                if ns_d != 0 and int(ns_effective[18]) != 0:
                    ns_reason = int(ns_effective[18])
                    ns_fill = ns_p
                    ns_order_source = int(ns_effective[19])
                    ns_close_role = -1
                    ns_close_qty = 100000
                    ns_pending_action = 0
                elif ns_d != 0:
                    ns_best = 1e+100
                    ns_event = 0
                    ns_level = 0.0
                    ns_prior = price[i - 1] if i else ns_p
                    for ns_z in range(3):
                        ns_value = ns_effective[12 + ns_z]
                        ns_side = ns_d if ns_z == 2 else -ns_d
                        ns_flag = bool(ns_effective[15 + ns_z])
                        if not np.isfinite(ns_value) or (not ns_flag and ns_side * (ns_p - ns_value) < -1e-08):
                            continue
                        ns_distance = 0.0 if ns_flag else max(0.0, ns_side * (ns_value - ns_prior))
                        if ns_distance < ns_best - 1e-09:
                            ns_best = ns_distance
                            ns_event = ns_z + 1
                            ns_level = ns_p if ns_flag else ns_value
                    if ns_event:
                        ns_fill = ns_p if observed_fill else ns_level
                        ns_reason = int(ns_effective[20]) if ns_event == 1 else 2 if ns_event == 2 else 7
                        ns_close_role = -1 if ns_event != 3 else 0
                        ns_close_qty = 100000 if ns_event != 3 else max(1, int(ns_inv[0] / 2))
                        if ns_event == 3:
                            ns_split_done = True
                elif int(ns_effective[21]) and (not bool(ns_effective[30])) and (ns_t < ns_effective[23]) and (ns_t < end - ns_par[31] * 60):
                    ns_pd = int(ns_effective[21])
                    ns_market = bool(ns_effective[26])
                    if ns_market or ns_pd * (ns_p - ns_effective[22]) >= -1e-08:
                        ns_d = ns_pd
                        ns_a = ns_effective[24]
                        ns_effective_qty = int(ns_effective[25])
                        ns_risk = ns_effective_qty * ns_par[2] * ns_a
                        ns_campaign += 1
                        ns_campaign_side = ns_d
                        ns_base = ns_realized
                        ns_peak = 0.0
                        ns_anchor = ns_p if observed_fill or ns_market else ns_effective[22]
                        ns_extreme = ns_anchor
                        ns_protected_floor = -ns_risk
                        ns_main_floor = np.nan
                        ns_current_atr = ns_a
                        ns_current_atr_source = -1
                        ns_trail_source = -1
                        ns_entry_row = i
                        ns_entry_t = ns_t
                        ns_cycle_gross = 0.0
                        ns_cycle_net = 0.0
                        ns_split_done = False
                        ns_narrowed = False
                        ns_fill = ns_anchor
                        ns_open_side = ns_d
                        ns_open_qty = ns_effective_qty
                        ns_open_role = 0
                        ns_reason = 20
                        ns_order_source = int(ns_effective[27])
                        if ns_entry_prepare_count >= len(ns_entry_preparations):
                            raise ValueError('約定元準備の記録上限を超えました')
                        ns_entry_preparations[ns_entry_prepare_count, :] = np.array([ns_campaign, i, ns_effective[28], ns_effective[29]])
                        ns_entry_prepare_count += 1
                        ns_pending_d = 0
                        ns_next_add = ns_anchor + ns_d * ns_par[5] * ns_a * (-1 if int(ns_par[4]) == 2 else 1)
                        ns_cover_anchor = 0.0
                        ns_next_cover = 0.0
            if ns_close_role >= -1 and ns_close_qty > 0:
                ns_oldtc = ns_tc
                ns_tc, ns_gain, ns_done = shadow_original.close_positions(ns_pos, ns_used, ns_trades, ns_tc, ns_close_role, ns_close_qty, ns_fill, i, ns_reason, ns_campaign)
                ns_realized += ns_gain
                for ns_k in range(ns_oldtc, ns_tc):
                    if ns_oc >= len(ns_orders):
                        raise ValueError('約定台帳の上限を超えました')
                    ns_cash += ns_trades[ns_k, 2] * ns_trades[ns_k, 3] * ns_fill
                    ns_orders[ns_oc, :] = np.array([i, ns_order_source, ns_campaign, -ns_trades[ns_k, 2], ns_trades[ns_k, 3], ns_fill, ns_reason, 0])
                    ns_oc += 1
                ns_inv = shadow_original.inventory(ns_pos, ns_used)
                ns_acted = True
                if ns_promote:
                    ns_d = -ns_d
                    ns_reversals += 1
                    ns_anchor = ns_fill
                    ns_extreme = ns_fill
                    ns_split_done = False
                    for ns_k in range(ns_used):
                        if ns_pos[ns_k, 2] > 0:
                            ns_pos[ns_k, 3] = 0
                    ns_inv = shadow_original.inventory(ns_pos, ns_used)
                    ns_open_side = ns_d
                    ns_open_role = 0
                    ns_open_qty = max(0, int(ns_effective_qty - ns_inv[0]))
                    ns_reason = 23
                    ns_next_add = ns_fill + ns_d * ns_par[5] * ns_a * (-1 if int(ns_par[4]) == 2 else 1)
                    ns_cover_anchor = 0.0
                    ns_next_cover = 0.0
            if ns_open_qty > 0:
                if ns_used >= len(ns_pos) or ns_oc >= len(ns_orders):
                    raise ValueError('約定台帳の上限を超えました')
                ns_pos[ns_used, :] = np.array([ns_open_side, ns_fill, ns_open_qty, ns_open_role, i])
                ns_used += 1
                ns_cash -= ns_open_side * ns_fill * ns_open_qty
                ns_orders[ns_oc, :] = np.array([i, ns_order_source, ns_campaign, ns_open_side, ns_open_qty, ns_fill, ns_reason, 1])
                ns_oc += 1
                ns_inv = shadow_original.inventory(ns_pos, ns_used)
                ns_acted = True
                if ns_open_role == 0:
                    ns_next_add = ns_fill + ns_d * ns_par[5] * ns_a * (-1 if int(ns_par[4]) == 2 else 1)
                else:
                    ns_cover_anchor = ns_fill
                    ns_cover_extreme = ns_fill
                    ns_next_cover = ns_fill - ns_d * ns_par[10] * ns_a
            ns_equity = ns_realized + ns_inv[2] * ns_p - ns_inv[3]
            ns_max_error = max(ns_max_error, abs(ns_equity - (ns_cash + ns_inv[2] * ns_p)))
            ns_high_equity = max(ns_high_equity, ns_equity)
            ns_dd = max(ns_dd, ns_high_equity - ns_equity)
            ns_min_equity = min(ns_min_equity, ns_equity)
            ns_max_equity = max(ns_max_equity, ns_equity)
            ns_maxlong = max(ns_maxlong, ns_inv[4])
            ns_maxshort = max(ns_maxshort, ns_inv[5])
            ns_maxgross = max(ns_maxgross, ns_inv[0] + ns_inv[1])
            ns_maxnet = max(ns_maxnet, abs(ns_inv[2]))
            ns_cycle_gross = max(ns_cycle_gross, ns_inv[0] + ns_inv[1])
            ns_cycle_net = max(ns_cycle_net, abs(ns_inv[2]))
            if ns_d != 0 and ns_inv[0] + ns_inv[1] < 0.5:
                if ns_cc >= len(ns_cycles):
                    raise ValueError('組集計の上限を超えました')
                ns_cycles[ns_cc, :] = np.array([ns_campaign, ns_entry_row, i, ns_realized - ns_base, ns_risk, ns_a, ns_cycle_gross, ns_cycle_net, ns_d, ns_reason])
                ns_cc += 1
                ns_ix = 0 if ns_campaign_side > 0 else 1
                if ns_realized - ns_base < -1e-08:
                    ns_loss_streak[ns_ix] += 1
                    if ns_par[33] > 0 and ns_loss_streak[ns_ix] >= int(ns_par[33]):
                        ns_blocked[ns_ix] = True
                        ns_blocked_price[ns_ix] = ns_p
                        ns_blocked_atr[ns_ix] = ns_a
                else:
                    ns_loss_streak[ns_ix] = 0
                ns_d = 0
                ns_last_exit = ns_t
                ns_ready_after=ns_t+300.
                ns_pending_action = 0
                ns_pending_d = 0
                ns_neutral_since = -1.0
            if np.isfinite(ns_session_budget) and ns_equity <= -ns_session_budget + 1e-08:
                ns_session_halted = True
                ns_pending_d = 0
            if detail:
                ns_curve[i, :] = np.array([ns_equity, ns_realized, ns_inv[4], ns_inv[5], ns_dd, ns_cash, ns_inv[2], ns_campaign])
            ns_stop_level = np.nan
            ns_main_level = np.nan
            ns_cover_level = np.nan
            ns_cover_open_level = np.nan
            ns_add_level = np.nan
            ns_split_level = np.nan
            ns_market_flags[:] = False
            if ns_d != 0:
                if np.isfinite(atr[i]) and atr[i] > 0:
                    ns_current_atr = max(atr[i], tick * 2)
                    ns_current_atr_source = i
                ns_e = ns_equity - ns_base
                ns_peak = max(ns_peak, ns_e)
                ns_floor = -ns_risk
                if ns_par[13] > 0 and ns_peak >= ns_risk:
                    ns_floor = max(ns_floor, ns_par[13] * ns_peak)
                ns_mfe = ns_d * ((max(ns_extreme, ns_p) if ns_d > 0 else min(ns_extreme, ns_p)) - ns_anchor) / ns_a
                if ns_par[21] > 0 and ns_mfe >= ns_par[21]:
                    ns_floor = max(ns_floor, ns_effective_qty * ns_par[22] * ns_a)
                if ns_par[23] > 0 and ns_t - ns_entry_t >= ns_par[23] * 60 and (ns_mfe < ns_par[24]):
                    ns_floor = max(ns_floor, -ns_effective_qty * ns_par[25] * ns_a)
                ns_protected_floor = max(ns_protected_floor, ns_floor)
                ns_floor = ns_protected_floor
                if abs(ns_inv[2]) > 0.5:
                    ns_stop_level = shadow_original.rounded((ns_floor + ns_base - ns_realized + ns_inv[3]) / ns_inv[2], tick, -1 if ns_inv[2] > 0 else 1)
                    ns_stop_reason = 11 if ns_floor >= 0 else 1
                ns_extreme = max(ns_extreme, ns_p) if ns_d > 0 else min(ns_extreme, ns_p)
                if False and (not ns_narrowed) and signal_valid[i] and (signal_bad[i] == -ns_d) and (signal_source[i] > ns_entry_row) and (signal_source[i] <= i) and (ns_d * (ns_extreme - ns_anchor) >= dynamic_activation * ns_a):
                    ns_narrowed = True
                    ns_old_width = ns_par[3]
                    if ns_par[19] > 0 and ns_d * (ns_extreme - ns_anchor) >= ns_par[19] * ns_a:
                        ns_old_width = min(ns_old_width, ns_par[20])
                    if ns_t >= us_open:
                        ns_old_width *= ns_par[30]
                    if ns_dynamic_count >= len(ns_dynamic_events):
                        raise ValueError('幅短縮証跡の保存上限です')
                    ns_dynamic_events[ns_dynamic_count, :] = np.array([i, ns_campaign, signal_source[i], ns_d, ns_d * (ns_extreme - ns_anchor) / ns_a, ns_old_width, min(ns_old_width, dynamic_width)])
                    ns_dynamic_count += 1
                if np.isfinite(ns_par[3]) and ns_d * (ns_extreme - ns_anchor) >= ns_par[18] * ns_a:
                    ns_width = ns_par[3]
                    if ns_par[19] > 0 and ns_d * (ns_extreme - ns_anchor) >= ns_par[19] * ns_a:
                        ns_width = min(ns_width, ns_par[20])
                    if ns_t >= us_open:
                        ns_width *= ns_par[30]
                    if ns_narrowed:
                        ns_width = min(ns_width, dynamic_width)
                    ns_width_atr = ns_a if 0 == 0 else ns_current_atr
                    ns_planned_main = shadow_original.rounded(ns_extreme - ns_d * ns_width * ns_width_atr, tick, -ns_d)
                    if not np.isfinite(ns_main_floor) or ns_d * (ns_planned_main - ns_main_floor) > 0:
                        ns_main_floor = ns_planned_main
                        ns_trail_source = i
                    ns_main_level = ns_main_floor
                if ns_inv[1] > 0.5:
                    ns_cover_extreme = min(ns_cover_extreme, ns_p) if ns_d > 0 else max(ns_cover_extreme, ns_p)
                    ns_basis = 0.0
                    for ns_k in range(ns_used):
                        if ns_pos[ns_k, 2] > 0 and ns_pos[ns_k, 3] == 1:
                            ns_basis += ns_pos[ns_k, 1] * ns_pos[ns_k, 2]
                    ns_basis /= ns_inv[1]
                    ns_cover_level = ns_basis + ns_d * 0.75 * ns_a
                    ns_cover_reason = 4
                    ns_trail = ns_cover_extreme + ns_d * ns_par[11] * ns_a
                    if -ns_d * (ns_basis - ns_trail) < 0:
                        if ns_d * (ns_trail - ns_cover_level) < 0:
                            ns_cover_level = ns_trail
                            ns_cover_reason = 3
                    ns_cover_level = shadow_original.rounded(ns_cover_level, tick, ns_d)
                    if int(ns_par[9]) > 0 and ns_inv[1] < cap:
                        ns_cover_open_level = shadow_original.rounded(ns_next_cover, tick, -ns_d)
                elif ns_par[7] > 0 and ns_inv[0] > 0.5:
                    ns_cover_open_level = shadow_original.rounded(ns_extreme - ns_d * ns_par[8] * ns_a, tick, -ns_d)
                if int(ns_par[4]) > 0 and ns_inv[0] < cap and (state[i] == ns_d) and (ns_e > 0) and (ns_d * (ns_p - ns_anchor) > 0):
                    ns_add_level = shadow_original.rounded(ns_next_add if int(ns_par[4]) != 2 else ns_anchor - ns_d * ns_par[5] * ns_a, tick, ns_d if int(ns_par[4]) != 2 else -ns_d)
                    if int(ns_par[4]) == 2:
                        ns_add_level = shadow_original.rounded(ns_next_add, tick, -ns_d)
                if not ns_split_done and ns_par[14] > 0 and (ns_inv[0] >= 2):
                    ns_split_level = shadow_original.rounded(ns_anchor + ns_d * ns_par[14] * ns_a, tick, ns_d)
                if ns_t >= end:
                    ns_pending_action = 9
                    ns_action_row = i
                elif ns_session_halted:
                    ns_pending_action = 14
                    ns_action_row = i
                elif ns_e <= ns_floor - 1e-08:
                    ns_pending_action = 11 if ns_floor >= 0 else 1
                    ns_action_row = i
                elif ns_t - ns_entry_t >= ns_par[15] * 60:
                    ns_pending_action = 8
                    ns_action_row = i
                elif state[i] == -ns_d and ns_par[29] > 0:
                    ns_pending_action = 13
                    ns_action_row = i
                elif state[i] == -ns_d and int(ns_par[12]) > 0 and (ns_reversals < int(ns_par[39])) and (int(ns_par[12]) == 1 or ns_d * (ns_p - ns_anchor) <= -0.75 * ns_a):
                    ns_pending_action = 5
                    ns_action_row = i
                elif state[i] == ns_d and ns_inv[1] > 0.5 and (-ns_d * (ns_p - ns_cover_anchor) > 0) and (ns_par[7] > 0):
                    ns_pending_action = 6
                    ns_action_row = i
                if state[i] == 0:
                    if ns_neutral_since < 0:
                        ns_neutral_since = ns_t
                    if ns_par[16] > 0 and ns_t < end and (not ns_session_halted) and (ns_t - ns_neutral_since >= ns_par[16] * 60):
                        ns_pending_action = 10
                        ns_action_row = i
                else:
                    ns_neutral_since = -1.0
                if int(ns_par[17]) == 1 and ns_t < end and (not ns_session_halted) and (ns_t >= us_open - 900) and (ns_t < us_open + 1800):
                    ns_pending_action = 12
                    ns_action_row = i
                ns_planned = np.array([ns_stop_level, ns_main_level, ns_cover_level, ns_cover_open_level, ns_add_level, ns_split_level])
                ns_sides = np.array([-1 if ns_inv[2] > 0 else 1, -ns_d, ns_d, -ns_d, ns_d if int(ns_par[4]) != 2 else -ns_d, ns_d])
                for ns_z in range(6):
                    ns_market_flags[ns_z] = np.isfinite(ns_planned[ns_z]) and ns_sides[ns_z] * (ns_p - ns_planned[ns_z]) >= -1e-08
            else:
                for ns_bx in range(2):
                    ns_bd = 1 if ns_bx == 0 else -1
                    if ns_blocked[ns_bx] and (state[i] == -ns_bd or ns_bd * (ns_p - ns_blocked_price[ns_bx]) >= ns_par[34] * ns_blocked_atr[ns_bx]):
                        ns_blocked[ns_bx] = False
                        ns_loss_streak[ns_bx] = 0
                if ns_pending_d and (ns_t >= ns_pending_until or state[i] != ns_pending_d):
                    ns_pending_d = 0
                if ns_pending_d and int(ns_par[28]) == 1:
                    ns_pending_extreme = min(ns_pending_extreme, ns_p) if ns_pending_d > 0 else max(ns_pending_extreme, ns_p)
                    ns_changed = shadow_original.rounded(ns_pending_extreme + ns_pending_d * ns_par[1] * ns_pending_atr, tick, ns_pending_d)
                    if restart_active and reentry_filter & 2 and ns_pending_d == restart_side:
                        boundary = restart_extreme + restart_side * tick
                        ns_changed = max(ns_changed, boundary) if restart_side > 0 else min(ns_changed, boundary)
                    if ns_changed != ns_pending_level:
                        ns_pending_level = ns_changed
                        ns_pending_row = i
                ns_paused = int(ns_par[17]) in (1, 2) and ns_t >= us_open - 900 and (ns_t < us_open + 1800)
                if ns_allow[i] and (not False) and (not False) and (not ns_pending_d) and (not ns_session_halted) and (ns_t >= start + ns_par[32] * 60) and (ns_t < end - ns_par[31] * 60) and (ns_t >= ns_ready_after) and (not ns_paused):
                    if state[i] != 0 and (not ns_blocked[0 if state[i] > 0 else 1]) and np.isfinite(atr[i]) and (atr[i] > 0):
                        ns_pending_d = int(state[i])
                        ns_pending_atr = max(atr[i], tick * 2)
                        ns_pending_level = shadow_original.rounded(ns_p + ns_pending_d * ns_par[1] * ns_pending_atr, tick, ns_pending_d)
                        if restart_active and reentry_filter & 2 and ns_pending_d == restart_side:
                            boundary = restart_extreme + restart_side * tick
                            ns_pending_level = max(ns_pending_level, boundary) if restart_side > 0 else min(ns_pending_level, boundary)
                        ns_pending_until = ns_t + ns_par[27]
                        ns_pending_row = i
                        ns_pending_extreme = ns_p
                        ns_pending_qty = int(ns_par[0])
                        if ns_par[36] > 0:
                            ns_per_contract_risk = np.ceil(ns_pending_atr * ns_par[2] / tick - 1e-09) * tick * ns_par[37]
                            ns_pending_qty = min(cap, int(np.floor(ns_par[36] / ns_per_contract_risk)))
                        ns_pending_market = int(ns_par[28]) == 2 or ns_pending_d * (ns_p - ns_pending_level) >= -1e-08
                        if ns_pending_qty < 1:
                            ns_pending_d = 0
                        elif not np.isfinite(ns_session_budget) and ns_par[35] > 0:
                            ns_session_budget = ns_par[35] * ns_pending_qty * ns_par[2] * ns_pending_atr
                        if ns_pending_d:
                            ns_pending_prepare_id = ns_prepare_count
                            ns_pending_prepare_row = i
                            ns_prepare_events[ns_prepare_count, :] = np.array([ns_prepare_count, i, ns_pending_d, ns_pending_level, ns_pending_atr, ns_pending_until, ns_pending_qty])
                            ns_prepare_count += 1
            if detail:
                ns_atr_curve[i, :] = np.array([ns_d, ns_a if ns_d else np.nan, ns_current_atr if ns_d else np.nan, (ns_a if 0 == 0 else ns_current_atr) if ns_d else np.nan, ns_extreme if ns_d else np.nan, int(ns_d != 0 and np.isfinite(ns_main_level)), ns_main_level, ns_risk if ns_d else np.nan, ns_stop_level, ns_pending_atr if ns_pending_d else np.nan, ns_current_atr_source if ns_d else -1, ns_trail_source if ns_d else -1])
            ns_plans[i, :] = np.array([ns_d, ns_campaign, ns_a, ns_anchor, ns_risk, ns_entry_row, ns_entry_t, ns_inv[0], ns_realized, ns_base, ns_extreme, int(ns_split_done), ns_stop_level, ns_main_level, ns_split_level, int(ns_market_flags[0]), int(ns_market_flags[1]), int(ns_market_flags[5]), ns_pending_action, ns_action_row, ns_stop_reason, ns_pending_d, ns_pending_level, ns_pending_until, ns_pending_atr, ns_pending_qty, int(ns_pending_market), ns_pending_row, ns_pending_prepare_id, ns_pending_prepare_row, int(ns_session_halted), ns_last_exit, ns_effective_qty, i, ns_trail_source, ns_current_atr, ns_current_atr_source])
        xs_allow[i] = ns_prepare_count > 0 and ns_prepare_events[ns_prepare_count - 1, 1] == i
        if xs_allow[i]:
            profit_restart_pending=False
            if restart_active:
                if restart_count >= len(restart_events): raise ValueError('再参加条件証跡の上限です')
                restart_events[restart_count,:] = np.array([i, 3, restart_row, restart_side, restart_extreme, restart_seen_row, ema_source[i], ema_peer_source[i], state[i], ns_pending_level])
                restart_count += 1
        # ----------------------------------------
        # 改修出口影の更新。通常影の新準備行だけ開始する。
        for xs_once in range(1):
            xs_p = price[i]
            xs_t = time[i]
            if xs_d != 0 and np.isfinite(atr[i]) and (atr[i] > 0):
                xs_current_atr = max(atr[i], tick * 2)
                xs_current_atr_source = i
            if not np.isfinite(xs_p) or xs_p <= 0:
                if i > 0:
                    xs_plans[i, :] = xs_plans[i - 1, :]
                if detail:
                    xs_atr_curve[i, :] = np.array([xs_d, xs_a if xs_d else np.nan, xs_current_atr if xs_d else np.nan, (xs_a if 0 == 0 else xs_current_atr) if xs_d else np.nan, xs_extreme if xs_d else np.nan, int(xs_d != 0 and np.isfinite(xs_main_level)), xs_main_level, xs_risk if xs_d else np.nan, xs_stop_level, xs_pending_atr if xs_pending_d else np.nan, xs_current_atr_source if xs_d else -1, xs_trail_source if xs_d else -1])
                continue
            xs_acted = False
            xs_fill = 0.0
            xs_open_side = 0
            xs_open_qty = 0
            xs_open_role = 0
            xs_order_source = i - 1
            xs_reason = 0
            xs_close_role = -2
            xs_close_qty = 0
            xs_promote = False
            while xs_mature_row + 1 < i and time[xs_mature_row + 1] <= xs_t - min_delay_seconds + 1e-09:
                xs_mature_row += 1
            xs_effective = np.full(37, np.nan)
            if xs_mature_row >= 0 and np.isfinite(xs_plans[xs_mature_row, 33]):
                xs_candidate = xs_plans[xs_mature_row]
                if int(xs_candidate[1]) == xs_campaign and int(xs_candidate[0]) == xs_d:
                    xs_effective = xs_candidate.copy()
                    xs_effective[7] = xs_inv[0]
                    xs_effective[8] = xs_realized
                    xs_effective[9] = xs_base
                    if xs_split_done:
                        xs_effective[14] = np.nan
                        xs_effective[17] = 0.0
                    xs_effective[11] = int(xs_split_done)
            if xs_t >= session_close:
                if xs_d != 0:
                    raise ValueError('終場までに有効な全返済行がありません')
                xs_effective[:] = np.nan
            if quiet[i] or quiet_force[i] or (xs_pending_prepare_row >= 0 and time[xs_pending_prepare_row] < quiet_not_before[i]):
                xs_pending_d = 0
                xs_effective[21] = 0.0
            if quiet_force[i] and xs_d != 0:
                xs_effective[18] = 71.0
                xs_effective[19] = i - 1
            if feedback_row >= 0:
                xs_effective[:] = np.nan
            xs_execution_plans[i, :] = xs_effective
            if np.isfinite(xs_effective[33]):
                xs_order_source = i - 1 if min_delay_seconds == 0 else int(xs_effective[33])
                if xs_d != 0 and int(xs_effective[18]) != 0:
                    xs_reason = int(xs_effective[18])
                    xs_fill = xs_p
                    xs_order_source = int(xs_effective[19])
                    xs_close_role = -1
                    xs_close_qty = 100000
                    xs_pending_action = 0
                elif xs_d != 0:
                    xs_best = 1e+100
                    xs_event = 0
                    xs_level = 0.0
                    xs_prior = price[i - 1] if i else xs_p
                    for xs_z in range(3):
                        xs_value = xs_effective[12 + xs_z]
                        xs_side = xs_d if xs_z == 2 else -xs_d
                        xs_flag = bool(xs_effective[15 + xs_z])
                        if not np.isfinite(xs_value) or (not xs_flag and xs_side * (xs_p - xs_value) < -1e-08):
                            continue
                        xs_distance = 0.0 if xs_flag else max(0.0, xs_side * (xs_value - xs_prior))
                        if xs_distance < xs_best - 1e-09:
                            xs_best = xs_distance
                            xs_event = xs_z + 1
                            xs_level = xs_p if xs_flag else xs_value
                    if xs_event:
                        xs_fill = xs_p if observed_fill else xs_level
                        xs_reason = int(xs_effective[20]) if xs_event == 1 else 2 if xs_event == 2 else 7
                        xs_close_role = -1 if xs_event != 3 else 0
                        xs_close_qty = 100000 if xs_event != 3 else max(1, int(xs_inv[0] / 2))
                        if xs_event == 3:
                            xs_split_done = True
                elif int(xs_effective[21]) and (not bool(xs_effective[30])) and (xs_t < xs_effective[23]) and (xs_t < end - xs_par[31] * 60):
                    xs_pd = int(xs_effective[21])
                    xs_market = bool(xs_effective[26])
                    if xs_market or xs_pd * (xs_p - xs_effective[22]) >= -1e-08:
                        xs_d = xs_pd
                        xs_a = xs_effective[24]
                        xs_effective_qty = int(xs_effective[25])
                        xs_risk = xs_effective_qty * xs_par[2] * xs_a
                        xs_campaign += 1
                        xs_campaign_side = xs_d
                        xs_base = xs_realized
                        xs_peak = 0.0
                        xs_anchor = xs_p if observed_fill or xs_market else xs_effective[22]
                        xs_extreme = xs_anchor
                        xs_protected_floor = -xs_risk
                        xs_main_floor = np.nan
                        xs_current_atr = xs_a
                        xs_current_atr_source = -1
                        xs_trail_source = -1
                        xs_entry_row = i
                        xs_entry_t = xs_t
                        xs_cycle_gross = 0.0
                        xs_cycle_net = 0.0
                        xs_split_done = False
                        xs_narrowed = False
                        xs_fill = xs_anchor
                        xs_open_side = xs_d
                        xs_open_qty = xs_effective_qty
                        xs_open_role = 0
                        xs_reason = 20
                        xs_order_source = int(xs_effective[27])
                        if xs_entry_prepare_count >= len(xs_entry_preparations):
                            raise ValueError('約定元準備の記録上限を超えました')
                        xs_entry_preparations[xs_entry_prepare_count, :] = np.array([xs_campaign, i, xs_effective[28], xs_effective[29]])
                        xs_entry_prepare_count += 1
                        xs_pending_d = 0
                        xs_next_add = xs_anchor + xs_d * xs_par[5] * xs_a * (-1 if int(xs_par[4]) == 2 else 1)
                        xs_cover_anchor = 0.0
                        xs_next_cover = 0.0
            if xs_close_role >= -1 and xs_close_qty > 0:
                xs_oldtc = xs_tc
                xs_tc, xs_gain, xs_done = shadow_original.close_positions(xs_pos, xs_used, xs_trades, xs_tc, xs_close_role, xs_close_qty, xs_fill, i, xs_reason, xs_campaign)
                xs_realized += xs_gain
                for xs_k in range(xs_oldtc, xs_tc):
                    if xs_oc >= len(xs_orders):
                        raise ValueError('約定台帳の上限を超えました')
                    xs_cash += xs_trades[xs_k, 2] * xs_trades[xs_k, 3] * xs_fill
                    xs_orders[xs_oc, :] = np.array([i, xs_order_source, xs_campaign, -xs_trades[xs_k, 2], xs_trades[xs_k, 3], xs_fill, xs_reason, 0])
                    xs_oc += 1
                xs_inv = shadow_original.inventory(xs_pos, xs_used)
                xs_acted = True
                if xs_promote:
                    xs_d = -xs_d
                    xs_reversals += 1
                    xs_anchor = xs_fill
                    xs_extreme = xs_fill
                    xs_split_done = False
                    for xs_k in range(xs_used):
                        if xs_pos[xs_k, 2] > 0:
                            xs_pos[xs_k, 3] = 0
                    xs_inv = shadow_original.inventory(xs_pos, xs_used)
                    xs_open_side = xs_d
                    xs_open_role = 0
                    xs_open_qty = max(0, int(xs_effective_qty - xs_inv[0]))
                    xs_reason = 23
                    xs_next_add = xs_fill + xs_d * xs_par[5] * xs_a * (-1 if int(xs_par[4]) == 2 else 1)
                    xs_cover_anchor = 0.0
                    xs_next_cover = 0.0
            if xs_open_qty > 0:
                if xs_used >= len(xs_pos) or xs_oc >= len(xs_orders):
                    raise ValueError('約定台帳の上限を超えました')
                xs_pos[xs_used, :] = np.array([xs_open_side, xs_fill, xs_open_qty, xs_open_role, i])
                xs_used += 1
                xs_cash -= xs_open_side * xs_fill * xs_open_qty
                xs_orders[xs_oc, :] = np.array([i, xs_order_source, xs_campaign, xs_open_side, xs_open_qty, xs_fill, xs_reason, 1])
                xs_oc += 1
                xs_inv = shadow_original.inventory(xs_pos, xs_used)
                xs_acted = True
                if xs_open_role == 0:
                    xs_next_add = xs_fill + xs_d * xs_par[5] * xs_a * (-1 if int(xs_par[4]) == 2 else 1)
                else:
                    xs_cover_anchor = xs_fill
                    xs_cover_extreme = xs_fill
                    xs_next_cover = xs_fill - xs_d * xs_par[10] * xs_a
            xs_equity = xs_realized + xs_inv[2] * xs_p - xs_inv[3]
            xs_max_error = max(xs_max_error, abs(xs_equity - (xs_cash + xs_inv[2] * xs_p)))
            xs_high_equity = max(xs_high_equity, xs_equity)
            xs_dd = max(xs_dd, xs_high_equity - xs_equity)
            xs_min_equity = min(xs_min_equity, xs_equity)
            xs_max_equity = max(xs_max_equity, xs_equity)
            xs_maxlong = max(xs_maxlong, xs_inv[4])
            xs_maxshort = max(xs_maxshort, xs_inv[5])
            xs_maxgross = max(xs_maxgross, xs_inv[0] + xs_inv[1])
            xs_maxnet = max(xs_maxnet, abs(xs_inv[2]))
            xs_cycle_gross = max(xs_cycle_gross, xs_inv[0] + xs_inv[1])
            xs_cycle_net = max(xs_cycle_net, abs(xs_inv[2]))
            if xs_d != 0 and xs_inv[0] + xs_inv[1] < 0.5:
                if xs_cc >= len(xs_cycles):
                    raise ValueError('組集計の上限を超えました')
                xs_cycles[xs_cc, :] = np.array([xs_campaign, xs_entry_row, i, xs_realized - xs_base, xs_risk, xs_a, xs_cycle_gross, xs_cycle_net, xs_d, xs_reason])
                xs_cc += 1
                xs_ix = 0 if xs_campaign_side > 0 else 1
                if xs_realized - xs_base < -1e-08:
                    xs_loss_streak[xs_ix] += 1
                    if xs_par[33] > 0 and xs_loss_streak[xs_ix] >= int(xs_par[33]):
                        xs_blocked[xs_ix] = True
                        xs_blocked_price[xs_ix] = xs_p
                        xs_blocked_atr[xs_ix] = xs_a
                else:
                    xs_loss_streak[xs_ix] = 0
                xs_d = 0
                xs_last_exit = xs_t
                xs_ready_after=xs_t+300.
                xs_pending_action = 0
                xs_pending_d = 0
                xs_neutral_since = -1.0
            if np.isfinite(xs_session_budget) and xs_equity <= -xs_session_budget + 1e-08:
                xs_session_halted = True
                xs_pending_d = 0
            if detail:
                xs_curve[i, :] = np.array([xs_equity, xs_realized, xs_inv[4], xs_inv[5], xs_dd, xs_cash, xs_inv[2], xs_campaign])
            xs_stop_level = np.nan
            xs_main_level = np.nan
            xs_cover_level = np.nan
            xs_cover_open_level = np.nan
            xs_add_level = np.nan
            xs_split_level = np.nan
            xs_market_flags[:] = False
            if xs_d != 0:
                if np.isfinite(atr[i]) and atr[i] > 0:
                    xs_current_atr = max(atr[i], tick * 2)
                    xs_current_atr_source = i
                xs_e = xs_equity - xs_base
                xs_peak = max(xs_peak, xs_e)
                xs_floor = -xs_risk
                if xs_par[13] > 0 and xs_peak >= xs_risk:
                    xs_floor = max(xs_floor, xs_par[13] * xs_peak)
                xs_mfe = xs_d * ((max(xs_extreme, xs_p) if xs_d > 0 else min(xs_extreme, xs_p)) - xs_anchor) / xs_a
                if xs_par[21] > 0 and xs_mfe >= xs_par[21]:
                    xs_floor = max(xs_floor, xs_effective_qty * xs_par[22] * xs_a)
                if xs_par[23] > 0 and xs_t - xs_entry_t >= xs_par[23] * 60 and (xs_mfe < xs_par[24]):
                    xs_floor = max(xs_floor, -xs_effective_qty * xs_par[25] * xs_a)
                xs_protected_floor = max(xs_protected_floor, xs_floor)
                xs_floor = xs_protected_floor
                if abs(xs_inv[2]) > 0.5:
                    xs_stop_level = shadow_original.rounded((xs_floor + xs_base - xs_realized + xs_inv[3]) / xs_inv[2], tick, -1 if xs_inv[2] > 0 else 1)
                    xs_stop_reason = 11 if xs_floor >= 0 else 1
                xs_extreme = max(xs_extreme, xs_p) if xs_d > 0 else min(xs_extreme, xs_p)
                if dynamic and (not xs_narrowed) and signal_valid[i] and (signal_bad[i] == -xs_d) and (signal_source[i] > xs_entry_row) and (signal_source[i] <= i) and (xs_d * (xs_extreme - xs_anchor) >= dynamic_activation * xs_a):
                    xs_narrowed = True
                    xs_old_width = xs_par[3]
                    if xs_par[19] > 0 and xs_d * (xs_extreme - xs_anchor) >= xs_par[19] * xs_a:
                        xs_old_width = min(xs_old_width, xs_par[20])
                    if xs_t >= us_open:
                        xs_old_width *= xs_par[30]
                    if xs_dynamic_count >= len(xs_dynamic_events):
                        raise ValueError('幅短縮証跡の保存上限です')
                    xs_dynamic_events[xs_dynamic_count, :] = np.array([i, xs_campaign, signal_source[i], xs_d, xs_d * (xs_extreme - xs_anchor) / xs_a, xs_old_width, min(xs_old_width, dynamic_width)])
                    xs_dynamic_count += 1
                if np.isfinite(xs_par[3]) and xs_d * (xs_extreme - xs_anchor) >= xs_par[18] * xs_a:
                    xs_width = xs_par[3]
                    if xs_par[19] > 0 and xs_d * (xs_extreme - xs_anchor) >= xs_par[19] * xs_a:
                        xs_width = min(xs_width, xs_par[20])
                    if xs_t >= us_open:
                        xs_width *= xs_par[30]
                    if xs_narrowed:
                        xs_width = min(xs_width, dynamic_width)
                    xs_width_atr = xs_a if 0 == 0 else xs_current_atr
                    xs_planned_main = shadow_original.rounded(xs_extreme - xs_d * xs_width * xs_width_atr, tick, -xs_d)
                    if not np.isfinite(xs_main_floor) or xs_d * (xs_planned_main - xs_main_floor) > 0:
                        xs_main_floor = xs_planned_main
                        xs_trail_source = i
                    xs_main_level = xs_main_floor
                if xs_inv[1] > 0.5:
                    xs_cover_extreme = min(xs_cover_extreme, xs_p) if xs_d > 0 else max(xs_cover_extreme, xs_p)
                    xs_basis = 0.0
                    for xs_k in range(xs_used):
                        if xs_pos[xs_k, 2] > 0 and xs_pos[xs_k, 3] == 1:
                            xs_basis += xs_pos[xs_k, 1] * xs_pos[xs_k, 2]
                    xs_basis /= xs_inv[1]
                    xs_cover_level = xs_basis + xs_d * 0.75 * xs_a
                    xs_cover_reason = 4
                    xs_trail = xs_cover_extreme + xs_d * xs_par[11] * xs_a
                    if -xs_d * (xs_basis - xs_trail) < 0:
                        if xs_d * (xs_trail - xs_cover_level) < 0:
                            xs_cover_level = xs_trail
                            xs_cover_reason = 3
                    xs_cover_level = shadow_original.rounded(xs_cover_level, tick, xs_d)
                    if int(xs_par[9]) > 0 and xs_inv[1] < cap:
                        xs_cover_open_level = shadow_original.rounded(xs_next_cover, tick, -xs_d)
                elif xs_par[7] > 0 and xs_inv[0] > 0.5:
                    xs_cover_open_level = shadow_original.rounded(xs_extreme - xs_d * xs_par[8] * xs_a, tick, -xs_d)
                if int(xs_par[4]) > 0 and xs_inv[0] < cap and (state[i] == xs_d) and (xs_e > 0) and (xs_d * (xs_p - xs_anchor) > 0):
                    xs_add_level = shadow_original.rounded(xs_next_add if int(xs_par[4]) != 2 else xs_anchor - xs_d * xs_par[5] * xs_a, tick, xs_d if int(xs_par[4]) != 2 else -xs_d)
                    if int(xs_par[4]) == 2:
                        xs_add_level = shadow_original.rounded(xs_next_add, tick, -xs_d)
                if not xs_split_done and xs_par[14] > 0 and (xs_inv[0] >= 2):
                    xs_split_level = shadow_original.rounded(xs_anchor + xs_d * xs_par[14] * xs_a, tick, xs_d)
                if xs_t >= end:
                    xs_pending_action = 9
                    xs_action_row = i
                elif xs_session_halted:
                    xs_pending_action = 14
                    xs_action_row = i
                elif xs_e <= xs_floor - 1e-08:
                    xs_pending_action = 11 if xs_floor >= 0 else 1
                    xs_action_row = i
                elif xs_t - xs_entry_t >= xs_par[15] * 60:
                    xs_pending_action = 8
                    xs_action_row = i
                elif state[i] == -xs_d and xs_par[29] > 0:
                    xs_pending_action = 13
                    xs_action_row = i
                elif state[i] == -xs_d and int(xs_par[12]) > 0 and (xs_reversals < int(xs_par[39])) and (int(xs_par[12]) == 1 or xs_d * (xs_p - xs_anchor) <= -0.75 * xs_a):
                    xs_pending_action = 5
                    xs_action_row = i
                elif state[i] == xs_d and xs_inv[1] > 0.5 and (-xs_d * (xs_p - xs_cover_anchor) > 0) and (xs_par[7] > 0):
                    xs_pending_action = 6
                    xs_action_row = i
                if state[i] == 0:
                    if xs_neutral_since < 0:
                        xs_neutral_since = xs_t
                    if xs_par[16] > 0 and xs_t < end and (not xs_session_halted) and (xs_t - xs_neutral_since >= xs_par[16] * 60):
                        xs_pending_action = 10
                        xs_action_row = i
                else:
                    xs_neutral_since = -1.0
                if int(xs_par[17]) == 1 and xs_t < end and (not xs_session_halted) and (xs_t >= us_open - 900) and (xs_t < us_open + 1800):
                    xs_pending_action = 12
                    xs_action_row = i
                xs_planned = np.array([xs_stop_level, xs_main_level, xs_cover_level, xs_cover_open_level, xs_add_level, xs_split_level])
                xs_sides = np.array([-1 if xs_inv[2] > 0 else 1, -xs_d, xs_d, -xs_d, xs_d if int(xs_par[4]) != 2 else -xs_d, xs_d])
                for xs_z in range(6):
                    xs_market_flags[xs_z] = np.isfinite(xs_planned[xs_z]) and xs_sides[xs_z] * (xs_p - xs_planned[xs_z]) >= -1e-08
            else:
                for xs_bx in range(2):
                    xs_bd = 1 if xs_bx == 0 else -1
                    if xs_blocked[xs_bx] and (state[i] == -xs_bd or xs_bd * (xs_p - xs_blocked_price[xs_bx]) >= xs_par[34] * xs_blocked_atr[xs_bx]):
                        xs_blocked[xs_bx] = False
                        xs_loss_streak[xs_bx] = 0
                if xs_pending_d and (xs_t >= xs_pending_until or state[i] != xs_pending_d):
                    xs_pending_d = 0
                if xs_pending_d and int(xs_par[28]) == 1:
                    xs_pending_extreme = min(xs_pending_extreme, xs_p) if xs_pending_d > 0 else max(xs_pending_extreme, xs_p)
                    xs_changed = shadow_original.rounded(xs_pending_extreme + xs_pending_d * xs_par[1] * xs_pending_atr, tick, xs_pending_d)
                    if restart_active and reentry_filter & 2 and xs_pending_d == restart_side:
                        boundary = restart_extreme + restart_side * tick
                        xs_changed = max(xs_changed, boundary) if restart_side > 0 else min(xs_changed, boundary)
                    if xs_changed != xs_pending_level:
                        xs_pending_level = xs_changed
                        xs_pending_row = i
                xs_paused = int(xs_par[17]) in (1, 2) and xs_t >= us_open - 900 and (xs_t < us_open + 1800)
                if xs_allow[i] and (not quiet[i]) and (not quiet_force[i]) and (not xs_pending_d) and (not xs_session_halted) and (xs_t >= start + xs_par[32] * 60) and (xs_t < end - xs_par[31] * 60) and (xs_t >= xs_ready_after) and (not xs_paused):
                    if state[i] != 0 and (not xs_blocked[0 if state[i] > 0 else 1]) and np.isfinite(atr[i]) and (atr[i] > 0):
                        xs_pending_d = int(state[i])
                        xs_pending_atr = max(atr[i], tick * 2)
                        xs_pending_level = shadow_original.rounded(xs_p + xs_pending_d * xs_par[1] * xs_pending_atr, tick, xs_pending_d)
                        if restart_active and reentry_filter & 2 and xs_pending_d == restart_side:
                            boundary = restart_extreme + restart_side * tick
                            xs_pending_level = max(xs_pending_level, boundary) if restart_side > 0 else min(xs_pending_level, boundary)
                        xs_pending_until = xs_t + xs_par[27]
                        xs_pending_row = i
                        xs_pending_extreme = xs_p
                        xs_pending_qty = int(xs_par[0])
                        if xs_par[36] > 0:
                            xs_per_contract_risk = np.ceil(xs_pending_atr * xs_par[2] / tick - 1e-09) * tick * xs_par[37]
                            xs_pending_qty = min(cap, int(np.floor(xs_par[36] / xs_per_contract_risk)))
                        xs_pending_market = int(xs_par[28]) == 2 or xs_pending_d * (xs_p - xs_pending_level) >= -1e-08
                        if xs_pending_qty < 1:
                            xs_pending_d = 0
                        elif not np.isfinite(xs_session_budget) and xs_par[35] > 0:
                            xs_session_budget = xs_par[35] * xs_pending_qty * xs_par[2] * xs_pending_atr
                        if xs_pending_d:
                            xs_pending_prepare_id = xs_prepare_count
                            xs_pending_prepare_row = i
                            xs_prepare_events[xs_prepare_count, :] = np.array([xs_prepare_count, i, xs_pending_d, xs_pending_level, xs_pending_atr, xs_pending_until, xs_pending_qty])
                            xs_prepare_count += 1
            if detail:
                xs_atr_curve[i, :] = np.array([xs_d, xs_a if xs_d else np.nan, xs_current_atr if xs_d else np.nan, (xs_a if 0 == 0 else xs_current_atr) if xs_d else np.nan, xs_extreme if xs_d else np.nan, int(xs_d != 0 and np.isfinite(xs_main_level)), xs_main_level, xs_risk if xs_d else np.nan, xs_stop_level, xs_pending_atr if xs_pending_d else np.nan, xs_current_atr_source if xs_d else -1, xs_trail_source if xs_d else -1])
            xs_plans[i, :] = np.array([xs_d, xs_campaign, xs_a, xs_anchor, xs_risk, xs_entry_row, xs_entry_t, xs_inv[0], xs_realized, xs_base, xs_extreme, int(xs_split_done), xs_stop_level, xs_main_level, xs_split_level, int(xs_market_flags[0]), int(xs_market_flags[1]), int(xs_market_flags[5]), xs_pending_action, xs_action_row, xs_stop_reason, xs_pending_d, xs_pending_level, xs_pending_until, xs_pending_atr, xs_pending_qty, int(xs_pending_market), xs_pending_row, xs_pending_prepare_id, xs_pending_prepare_row, int(xs_session_halted), xs_last_exit, xs_effective_qty, i, xs_trail_source, xs_current_atr, xs_current_atr_source])
        if feedback_row >= 0 and (not np.isfinite(price[i]) or price[i] <= 0):
            ns_plans[i, :] = np.nan
            xs_plans[i, :] = np.nan
        # ----------------------------------------
        # 通常影の1.5ATR到達後に新しく公開されたB00だけ半減へ渡す。
        if ns_d == 0:
            gate_arm = -1
            gate_campaign = -1
            gate_entry = -1
        elif not np.isfinite(price[i]) or price[i] <= 0:
            pass
        else:
            if ns_campaign != gate_campaign or ns_entry_row != gate_entry:
                gate_arm = -1
                gate_campaign = ns_campaign
                gate_entry = ns_entry_row
            gate_mfe[i] = ns_d * (ns_extreme - ns_anchor) / ns_a
            if gate_arm < 0 and gate_mfe[i] >= 1.5:
                gate_arm = i
            gate_arm_rows[i] = gate_arm
            gate_armed[i] = gate_arm >= 0
            if gate_arm >= 0 and signal_source[i] > gate_arm:
                bad[i] = signal_bad[i]
                gate_eligible[i] = True
        atr_curve[i, :] = xs_atr_curve[i, :]
        feedback_row = -1
        # ----------------------------------------
        # 実玉の独立約定・枠会計。現在行で作った線は使わない。
        if used + 1 >= len(pos) or tc + q0 >= len(trades) or oc + q0 + 1 >= len(orders) or (cc + 1 >= len(cycles)) or (sc + 2 * q0 >= len(slot_events)) or (ac + 3 >= len(adjustment)) or (bc + 3 >= len(budgets)):
            raise ValueError('数量調整台帳の保存上限に達しました')
        p = price[i]
        t = time[i]
        old_oc = oc
        if not np.isfinite(p) or p <= 0:
            if detail and i:
                control[i] = control[i - 1]
                slot_curve[i] = slot_curve[i - 1]
                branch_curve[i] = branch_curve[i - 1]
                if closed and atr_curve[i, 0] != 0:
                    atr_curve[i, 0] = 0.0
                    atr_curve[i, 1:9] = np.nan
                    atr_curve[i, 5] = 0.0
                    atr_curve[i, 10] = -1.0
            if detail and i:
                guard_curve[i] = guard_curve[i - 1]
            continue
        plan_row = -1
        source = i - 1
        original_reason = 0
        original_fill = 0.0
        is_entry = False
        planned_qty = 0.0
        selected = np.zeros(q0, dtype=np.bool_)
        acted = False
        reason = 0
        fill = 0.0
        closed_now = False
        if i and np.isfinite(execution_plans[i, 33]):
            plan = execution_plans[i]
            plan_row = int(plan[33])
            sd = int(plan[0])
            shadow_campaign = int(plan[1])
            planned_qty = plan[7]
            source = i - 1 if min_delay_seconds == 0 else plan_row
            if sd:
                if int(plan[18]):
                    original_reason = int(plan[18])
                    original_fill = p
                    source = int(plan[19])
                else:
                    best = 1e+100
                    prior = price[i - 1]
                    for z in range(3):
                        level = plan[12 + z]
                        side = sd if z == 2 else -sd
                        flag = bool(plan[15 + z])
                        if not np.isfinite(level) or (not flag and side * (p - level) < -1e-08):
                            continue
                        distance = 0.0 if flag else max(0.0, side * (level - prior))
                        if distance < best - 1e-09:
                            best = distance
                            original_reason = int(plan[20]) if z == 0 else 2 if z == 1 else 7
                            original_fill = p if observed_fill or flag else level
            elif int(plan[21]) and (not bool(plan[30])) and (t < plan[23]) and (t < end - cutoff * 60) and (t >= pause_until) and (not blocked[0 if plan[21] > 0 else 1]) and (not quiet[i]) and (not quiet_force[i]) and (time[int(plan[29])] >= quiet_not_before[i]):
                pd = int(plan[21])
                if bool(plan[26]) or pd * (p - plan[22]) >= -1e-08:
                    is_entry = True
                    d = pd
                    a = plan[24]
                    risk = q0 * a
                    planned_qty = q0
                    campaign = int(plan[1]) + 1
                    shadow_campaign = campaign
                    base = realized
                    entry_row = i
                    fill = p if observed_fill or bool(plan[26]) else plan[22]
                    source = int(plan[27])
                    original_reason = 20
                    closed = False
                    phase = 0
                    reductions = 0
                    barrier = i
                    reduction_row = -1
                    budget = False
                    budget_row = -1
                    chosen_restore = restore_mode
                    branch_row = -1
                    branch_evidence = -1
                    branch_class = 0
                    pending = 0
                    pending_row = -1
                    pending_evidence = -1
                    pending_slots[:] = False
                    alive[:] = True
                    restorable[:] = False
                    slot_leg[:] = -1
                    cycle_max = 0.0
                    if t < last_exit + cooldown_seconds - 1e-08:
                        raise ValueError('実全返済からの指定休止が終わっていません')
                    selected[:] = True
                    guard_peak = 0.0
                    guard_floor = -np.inf
                    guard_pending = False
                    guard_row = -1
                    actual_anchor = fill
                    actual_extreme = p
                    if restart_active:
                        if restart_count >= len(restart_events): raise ValueError('再参加条件証跡の上限です')
                        restart_events[restart_count,:] = np.array([i, 4, restart_row, restart_side, restart_extreme, restart_seen_row, ema_source[i], ema_peer_source[i], d, fill])
                        restart_count += 1
                    restart_active = False
                    early_peak = 0.0
                    early_action = 0
                    early_row = -1
                    early_evidence = -1
                    reduce_reason = 30
                    campaign_fees = 0.0
                    if kind == 1:
                        count = int(np.floor(fraction * q0))
                        selected[:count] = False
                    elif kind == 2:
                        qs = q0 - int(np.floor(fraction * q0))
                        k = qs // 2
                        selected[:] = False
                        selected[:k] = True
                        selected[q0 - (qs - k):] = True
                    qty = int(np.sum(selected))
                    leg = used
                    pos[used] = np.array([d, fill, qty, 0.0, i])
                    used += 1
                    orders[oc] = np.array([i, source, campaign, d, qty, fill, 20.0, 1.0])
                    oc += 1
                    cash -= d * qty * fill
                    for slot in range(q0):
                        if selected[slot]:
                            slot_leg[slot] = leg
                            slot_events[sc] = np.array([i, source, campaign, slot + 1, 1.0, leg, d, fill, 1.0, 20.0, plan_row])
                            sc += 1
                    acted = True
                    reason = 20
        if i and np.isfinite(execution_plans[i, 33]):
            plan = execution_plans[i]
            if int(plan[21]) and int(plan[28]) != last_quiet_prepare and (quiet[i] or time[int(plan[29])] < quiet_not_before[i]):
                last_quiet_prepare = int(plan[28])
                time_events[qc] = np.array([i, int(plan[1]) + 1, 2.0, int(plan[29]), 0.0, quiet_not_before[i] - 1800.0, quiet_not_before[i]])
                qc += 1
        if not closed and (not is_entry) and quiet_force[i]:
            original_reason = 71
            original_fill = p
            source = i - 1
            time_events[qc] = np.array([i, campaign, 1.0, source, shadow_engine.inventory(pos, used)[0], quiet_not_before[i] - 1800.0, quiet_not_before[i]])
            qc += 1
        if qc >= len(time_events) - 3:
            raise ValueError('時間回避の証跡上限です')
        if not is_entry and original_reason:
            planned_qty = planned_qty - split_count if original_reason == 7 else 0.0
        if not is_entry and original_reason and (not closed):
            fill = original_fill
            reason = original_reason
            early_action = 0
            if pending:
                mask = 0
                for slot in range(q0):
                    if pending_slots[slot]:
                        mask += 1 << slot
                adjustment[ac] = np.array([i, campaign, 3.0, pending, pending_row, pending_evidence, np.sum(pending_slots), reason, mask, reductions, plan_row])
                ac += 1
                pending = 0
                pending_slots[:] = False
            barrier = i
            old_restorable = int(np.sum(restorable))
            selected[:] = True
            if reason == 7:
                selected[split_count:] = False
            for slot in range(q0):
                if selected[slot] and alive[slot]:
                    slot_events[sc] = np.array([i, source, campaign, slot + 1, 4.0 if reason == 7 else 5.0, slot_leg[slot], d, fill, 1.0 if slot_leg[slot] >= 0 else 0.0, reason, plan_row])
                    sc += 1
                    alive[slot] = False
                    restorable[slot] = False
            tc, oc, gain, move, done = close_slots(pos, used, slot_leg, selected, fill, i, source, reason, campaign, trades, tc, orders, oc)
            realized += gain
            cash += move
            acted = True
            if reason == 7:
                if not np.any(restorable):
                    if old_restorable:
                        adjustment[ac] = np.array([i, campaign, 4.0, 0.0, source, -1.0, 0.0, 7.0, 0.0, reductions, plan_row])
                        ac += 1
                    phase = 0
                else:
                    phase = 2
                if budget:
                    inv = shadow_engine.inventory(pos, used)
                    e = realized - base + inv[2] * p - inv[3]
                    budgets[bc] = np.array([i, campaign, 3.0, budget_row, risk, e, max(0.0, -e - risk), t - budget_time])
                    bc += 1
                if guard_pending:
                    guard_events[gc] = np.array([i, campaign, 4.0, guard_row, 0.0, guard_peak, guard_floor, 0.0, d, 7.0])
                    gc += 1
            else:
                if guard_pending:
                    guard_events[gc] = np.array([i, campaign, 5.0, guard_row, 0.0, guard_peak, guard_floor, 0.0, d, reason])
                    gc += 1
                closed_now = True
        elif not is_entry and (not closed) and budget and (i > budget_row) and (t >= budget_time + min_delay_seconds - 1e-09):
            fill = p
            reason = 32
            source = budget_row
            selected[:] = True
            for slot in range(q0):
                if alive[slot]:
                    slot_events[sc] = np.array([i, source, campaign, slot + 1, 5.0, slot_leg[slot], d, fill, 1.0 if slot_leg[slot] >= 0 else 0.0, reason, plan_row])
                    sc += 1
            tc, oc, gain, move, done = close_slots(pos, used, slot_leg, selected, fill, i, source, reason, campaign, trades, tc, orders, oc)
            realized += gain
            cash += move
            acted = True
            closed_now = True
        elif not is_entry and (not closed) and guard_pending and (i > guard_row):
            fill = p
            reason = 70
            source = guard_row
            selected[:] = True
            for slot in range(q0):
                if alive[slot]:
                    slot_events[sc] = np.array([i, source, campaign, slot + 1, 5.0, slot_leg[slot], d, fill, 1.0 if slot_leg[slot] >= 0 else 0.0, reason, plan_row])
                    sc += 1
            tc, oc, gain, move, done = close_slots(pos, used, slot_leg, selected, fill, i, source, reason, campaign, trades, tc, orders, oc)
            realized += gain
            cash += move
            acted = True
            closed_now = True
            guard_events[gc] = np.array([i, campaign, 3.0, source, 0.0, guard_peak, guard_floor, done, d, reason])
            gc += 1
        elif not is_entry and (not closed) and early_action and (i > early_row):
            fill = p
            reason = early_action
            source = early_row
            selected[:] = True
            for slot in range(q0):
                if alive[slot]:
                    slot_events[sc] = np.array([i, source, campaign, slot + 1, 5.0, slot_leg[slot], d, fill, 1.0 if slot_leg[slot] >= 0 else 0.0, reason, plan_row])
                    sc += 1
            tc, oc, gain, move, done = close_slots(pos, used, slot_leg, selected, fill, i, source, reason, campaign, trades, tc, orders, oc)
            realized += gain
            cash += move
            acted = True
            closed_now = True
            risk_events[rc] = np.array([i, campaign, 2.0, early_action, source, early_evidence, done, early_peak, loss_streak, cumulative_r])
            rc += 1
            early_action = 0
        elif not is_entry and (not closed) and pending and (not budget) and (i > pending_row) and (t >= time[pending_row] + min_delay_seconds - 1e-09):
            fill = p
            reason = reduce_reason if pending < 0 else 31
            source = pending_row
            mask = 0
            for slot in range(q0):
                if pending_slots[slot]:
                    mask += 1 << slot
            if pending < 0:
                for slot in range(q0):
                    if pending_slots[slot]:
                        if slot_leg[slot] < 0 or not alive[slot]:
                            raise ValueError('減量枠が生存していません')
                        slot_events[sc] = np.array([i, source, campaign, slot + 1, 2.0, slot_leg[slot], d, fill, 1.0, reason, plan_row])
                        sc += 1
                        restorable[slot] = True
                tc, oc, gain, move, done = close_slots(pos, used, slot_leg, pending_slots, fill, i, source, reason, campaign, trades, tc, orders, oc)
                realized += gain
                cash += move
                reductions += 1
                reduction_row = i
                reduction_time = t
                phase = 2
                if branch_mode:
                    is_valid = bool(branch_valid[i])
                    bd = int(branch_direction[i])
                    branch_class = 0 if not is_valid else 1 if bd == 0 else 2 if bd == d else 3
                    adverse = is_valid and bd == -d
                    choose_signal = adverse if branch_mode == 1 else not adverse if branch_mode == 2 else bool(branch_choice[i])
                    chosen_restore = 1 if choose_signal else 2
                    branch_row = i
                    branch_evidence = int(branch_source[i])
                    if brc >= len(branch_events):
                        raise ValueError('復元分岐の記録上限です')
                    branch_events[brc] = np.array([i, campaign, reductions, chosen_restore, bd, branch_evidence, int(is_valid), branch_class, branch_mode, branch_seed])
                    brc += 1
            else:
                qty = int(np.sum(pending_slots))
                leg = used
                for slot in range(q0):
                    if pending_slots[slot] and (not alive[slot] or not restorable[slot] or slot_leg[slot] >= 0):
                        raise ValueError('復元資格がありません')
                pos[used] = np.array([d, fill, qty, 0.0, i])
                used += 1
                orders[oc] = np.array([i, source, campaign, d, qty, fill, reason, 1.0])
                oc += 1
                cash -= d * qty * fill
                for slot in range(q0):
                    if pending_slots[slot]:
                        slot_leg[slot] = leg
                        restorable[slot] = False
                        slot_events[sc] = np.array([i, source, campaign, slot + 1, 3.0, leg, d, fill, 1.0, reason, plan_row])
                        sc += 1
                phase = 0
            adjustment[ac] = np.array([i, campaign, 2.0, pending, pending_row, pending_evidence, np.sum(pending_slots), reason, mask, reductions, plan_row])
            ac += 1
            barrier = i
            pending = 0
            pending_slots[:] = False
            acted = True
        for fee_order in range(old_oc, oc):
            campaign_fees += np.floor(orders[fee_order, 4] * losspar[12] + 1e-08) / losspar[13]
        inv = shadow_engine.inventory(pos, used)
        equity = realized + inv[2] * p - inv[3]
        max_error = max(max_error, abs(equity - (cash + inv[2] * p)))
        high_equity = max(high_equity, equity)
        dd = max(dd, high_equity - equity)
        min_equity = min(min_equity, equity)
        max_equity = max(max_equity, equity)
        maxlong = max(maxlong, inv[4])
        maxshort = max(maxshort, inv[5])
        maxgross = max(maxgross, inv[0])
        maxnet = max(maxnet, abs(inv[2]))
        if inv[4] > cap or inv[5] > cap:
            raise ValueError('片方向保有上限違反です')
        if not closed:
            cycle_max = max(cycle_max, inv[0])
        if closed_now:
            net_campaign = realized - base - campaign_fees
            ix = 0 if d > 0 else 1
            direction_losses[ix] = direction_losses[ix] + 1 if net_campaign < 0 else 0
            if losspar[18] > 0 and direction_losses[ix] >= 2:
                blocked[ix] = True
                reset_seen[ix] = False
                block_row[ix] = i
                block_events[xc] = np.array([i, campaign, 1.0, d, direction_losses[ix], i, ema_source[i], ema_peer_source[i]])
                xc += 1
            guard_pending = False
            loss_streak = loss_streak + 1 if net_campaign < 0 else 0
            cumulative_r += net_campaign / risk
            if losspar[9] > 0 and loss_streak >= losspar[9]:
                pause_until = end if losspar[10] < 0 else t + losspar[10]
                loss_streak = 0
                risk_events[rc] = np.array([i, campaign, 3.0, 60.0, i, -1.0, 0.0, early_peak, 0.0, cumulative_r])
                rc += 1
            if losspar[11] > 0 and cumulative_r <= -losspar[11]:
                pause_until = end
                risk_events[rc] = np.array([i, campaign, 3.0, 61.0, i, -1.0, 0.0, early_peak, loss_streak, cumulative_r])
                rc += 1
            early_action = 0
            cycles[cc] = np.array([campaign, entry_row, i, realized - base, risk, a, cycle_max, cycle_max, d, reason])
            cc += 1
            if budget:
                e = realized - base
                budgets[bc] = np.array([i, campaign, 2.0, budget_row, risk, e, max(0.0, -e - risk), t - budget_time])
                bc += 1
            alive[:] = False
            restorable[:] = False
            slot_leg[:] = -1
            pending = 0
            pending_slots[:] = False
            budget = False
            d = 0
            phase = 0
            closed = True
            last_exit = t
        if not closed:
            e = equity - base
            if budget_enabled and e - (campaign_fees if losspar[8] < 1.0 else 0.0) <= -risk * losspar[8] and (not budget):
                budget = True
                budget_row = i
                budget_time = t
                budgets[bc] = np.array([i, campaign, 1.0, i, risk, e, max(0.0, -e - risk), 0.0])
                bc += 1
                if pending:
                    mask = 0
                    for slot in range(q0):
                        if pending_slots[slot]:
                            mask += 1 << slot
                    adjustment[ac] = np.array([i, campaign, 3.0, pending, pending_row, pending_evidence, np.sum(pending_slots), 32.0, mask, reductions, plan_row])
                    ac += 1
                    pending = 0
                    pending_slots[:] = False
                    phase = 2 if np.any(restorable) else 0
            early_peak = max(early_peak, d * (p - actual_anchor) / a)
            close_fee = np.floor(inv[0] * losspar[12] + 1e-08) / losspar[13]
            net_liquidation = e - campaign_fees - close_fee
            guard_peak = max(guard_peak, net_liquidation)
            if losspar[15] > 0 and guard_peak >= losspar[16] * risk:
                first_guard = not np.isfinite(guard_floor)
                guard_floor = max(guard_floor, losspar[17] * guard_peak)
                if first_guard:
                    guard_events[gc] = np.array([i, campaign, 1.0, i, net_liquidation, guard_peak, guard_floor, inv[0], d, 70.0])
                    gc += 1
                if net_liquidation <= guard_floor and (not guard_pending) and (not budget):
                    guard_pending = True
                    guard_row = i
                    early_action = 0
                    if pending:
                        mask = 0
                        for slot in range(q0):
                            if pending_slots[slot]:
                                mask += 1 << slot
                        adjustment[ac] = np.array([i, campaign, 3.0, pending, pending_row, pending_evidence, np.sum(pending_slots), 70.0, mask, reductions, plan_row])
                        ac += 1
                        pending = 0
                        pending_slots[:] = False
                    guard_events[gc] = np.array([i, campaign, 2.0, i, net_liquidation, guard_peak, guard_floor, inv[0], d, 70.0])
                    gc += 1
            if not acted and (not pending) and (not budget) and (not early_action) and (not guard_pending):
                fresh_bad = raw_valid[i] and raw_bad[i] == -d and (raw_source[i] > barrier) and (raw_source[i] > entry_row)
                bad_failed = losspar[0] > 0 and fresh_bad and (early_peak < losspar[1]) and (d * (p - actual_anchor) / a <= -losspar[2])
                timed_failed = losspar[3] > 0 and t - time[entry_row] >= losspar[3] and (early_peak < losspar[4]) and (d * (p - actual_anchor) / a <= -losspar[5])
                ema_failed = losspar[6] > 0 and ema_source[i] > entry_row and (ema_direction[i] != d) and (d * (p - actual_anchor) / a <= -losspar[7])
                action = 0
                why = 0
                evidence_row = i
                if bad_failed:
                    action = int(losspar[0])
                    why = 50
                    evidence_row = raw_source[i]
                elif timed_failed:
                    action = int(losspar[14])
                    why = 51
                elif ema_failed:
                    action = 2
                    why = 52
                    evidence_row = ema_source[i]
                if action == 1 and reductions < maximum:
                    count = min(int(np.sum(alive)) - 1, max(1, int(np.floor(fraction * np.sum(alive)))))
                    if count > 0:
                        pending = -1
                        pending_row = i
                        pending_evidence = evidence_row
                        reduce_reason = why
                        for slot in range(q0):
                            if count > 0 and alive[slot] and (slot_leg[slot] >= 0):
                                pending_slots[slot] = True
                                count -= 1
                        phase = 1
                        risk_events[rc] = np.array([i, campaign, 1.0, why, i, evidence_row, np.sum(pending_slots), early_peak, loss_streak, cumulative_r])
                        rc += 1
                elif action == 2:
                    early_action = why
                    early_row = i
                    early_evidence = evidence_row
                    risk_events[rc] = np.array([i, campaign, 1.0, why, i, evidence_row, inv[0], early_peak, loss_streak, cumulative_r])
                    rc += 1
            if kind == 3 and (not acted) and (not pending) and (not budget) and (not early_action) and (not guard_pending):
                evidence = -1
                if phase == 0 and reductions < maximum and (bad[i] == -d) and (bad_source[i] > barrier):
                    pending = -1
                    evidence = bad_source[i]
                    reduce_reason = 30
                    count = min(int(np.sum(alive)) - 1, max(1, int(np.floor(fraction * np.sum(alive)))))
                    for slot in range(q0):
                        if count > 0 and alive[slot] and (slot_leg[slot] >= 0):
                            pending_slots[slot] = True
                            count -= 1
                    phase = 1
                elif phase == 2 and chosen_restore and (good_source[i] > barrier) and (good_source[i] > reduction_row):
                    fresh = good[i] == d and (branch_mode == 0 or good_valid[i]) if chosen_restore == 1 else good_valid[i] and t >= reduction_time + restore_seconds and (time[good_source[i]] >= reduction_time + restore_seconds)
                    if fresh and np.any(restorable):
                        pending = 1
                        evidence = good_source[i]
                        pending_slots[:] = restorable
                        phase = 3
                if pending:
                    pending_row = i
                    pending_evidence = evidence
                    mask = 0
                    for slot in range(q0):
                        if pending_slots[slot]:
                            mask += 1 << slot
                    adjustment[ac] = np.array([i, campaign, 1.0, pending, i, evidence, np.sum(pending_slots), 30.0 if pending < 0 else 31.0, mask, reductions, plan_row])
                    ac += 1
        if losspar[18] > 0 and ema_valid[i]:
            for ix in range(2):
                side = 1 if ix == 0 else -1
                if blocked[ix] and ema_source[i] > block_row[ix] and (ema_peer_source[i] > block_row[ix]):
                    if not reset_seen[ix] and ema_direction[i] != side:
                        reset_seen[ix] = True
                        reset_own[ix] = ema_source[i]
                        reset_peer[ix] = ema_peer_source[i]
                        block_events[xc] = np.array([i, campaign, 2.0, side, direction_losses[ix], block_row[ix], ema_source[i], ema_peer_source[i]])
                        xc += 1
                    elif reset_seen[ix] and ema_direction[i] == side and (ema_source[i] > reset_own[ix]) and (ema_peer_source[i] > reset_peer[ix]):
                        blocked[ix] = False
                        reset_seen[ix] = False
                        direction_losses[ix] = 0
                        block_events[xc] = np.array([i, campaign, 3.0, side, 0.0, block_row[ix], ema_source[i], ema_peer_source[i]])
                        xc += 1
        if gc >= len(guard_events) - 5 or xc >= len(block_events) - 5:
            raise ValueError('利益保護又は再開待ちの証跡上限です')
        if detail:
            close_fee = np.floor(inv[0] * losspar[12] + 1e-08) / losspar[13]
            net_liquidation = equity - base - campaign_fees - close_fee if campaign >= 0 else 0.0
            guard_curve[i] = np.array([guard_peak, guard_floor, net_liquidation, int(guard_pending), int(blocked[0]), int(blocked[1]), direction_losses[0], direction_losses[1]])
            branch_curve[i] = np.array([chosen_restore, branch_row, branch_evidence, branch_class])
            curve[i] = np.array([equity, realized, inv[4], inv[5], dd, cash, inv[2], campaign])
            if closed and atr_curve[i, 0] != 0:
                atr_curve[i, 0] = 0.0
                atr_curve[i, 1:9] = np.nan
                atr_curve[i, 5] = 0.0
                atr_curve[i, 10] = -1.0
            control[i] = np.array([shadow_campaign, campaign, phase, d, planned_qty, inv[0], np.sum(restorable), reductions, pending, pending_row if pending else -1, pending_evidence if pending else -1, equity - base if campaign >= 0 else 0.0, risk if campaign >= 0 else 0.0, int(budget), budget_row if budget else -1, int(closed), barrier, reduction_row, plan_row, max(0.0, -(equity - base) - risk) if campaign >= 0 else 0.0])
            for slot in range(q0):
                slot_curve[i, slot] = int(alive[slot]) + 2 * int(slot_leg[slot] >= 0) + 4 * int(restorable[slot])
        feedback_row = -1
        if closed_now:
            # ----------------------------------------
            # 料金後親組の円額で判定し、最後の返済脚や理由名では判定しない。
            realized_yen=net_campaign*losspar[13]
            use_fast=profit_fast_enabled and realized_yen>1e-7
            if profit_reentry_count>=len(profit_reentry_events): raise ValueError("利確再参加証跡の上限です")
            profit_reentry_events[profit_reentry_count,:]=np.array([i,campaign,realized_yen,int(use_fast),t+cooldown_seconds if use_fast else np.nan,ns_d,ns_entry_row])
            profit_reentry_count+=1
            if use_fast:
                restart_active = True
                restart_side = int(cycles[cc - 1, 8])
                restart_row = i
                restart_extreme = actual_extreme
                restart_seen_row = -1
                if restart_count >= len(restart_events): raise ValueError('再参加条件証跡の上限です')
                restart_events[restart_count,:] = np.array([i, 1, restart_row, restart_side, restart_extreme, restart_seen_row, ema_source[i], ema_peer_source[i], state[i], np.nan])
                restart_count += 1
                feedback_row = i
                feedback_price = fill
    stats = np.array([realized, dd, maxlong, maxshort, maxgross, maxnet, max_error, min_equity, max_equity, inv[0], 0.0])
    return (trades[:tc], cycles[:cc], curve, orders[:oc], stats, atr_curve, control, slot_curve, slot_events[:sc], adjustment[:ac], budgets[:bc], branch_events[:brc], branch_curve, risk_events[:rc], guard_curve, guard_events[:gc], block_events[:xc], time_events[:qc], ns_plans, ns_execution_plans, ns_prepare_events[:ns_prepare_count], ns_entry_preparations[:ns_entry_prepare_count], xs_plans, xs_execution_plans, xs_prepare_events[:xs_prepare_count], xs_entry_preparations[:xs_entry_prepare_count], xs_dynamic_events[:xs_dynamic_count], reentry_events[:reentry_count], gate_mfe, gate_arm_rows, gate_armed, gate_eligible, profit_reentry_events[:profit_reentry_count], restart_events[:restart_count])
