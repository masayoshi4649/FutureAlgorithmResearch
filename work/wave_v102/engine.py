"""101の実数量と固定R0を保持し、増玉の初期幅余裕と停止線据置を別判定する。"""

import math
import numpy as np
from numba import njit


ORDER_COLUMNS = ['row', 'decision_row', 'parent_id', 'source', 'action_side', 'quantity', 'price',
                 'is_entry', 'reason', 'fee', 'decision_time', 'fill_time', 'limit_price', 'cycle',
                 'method', 'source_entry_side', 'uid']
TRADE_COLUMNS = ['parent_id', 'source', 'entry_row', 'exit_row', 'side', 'quantity', 'entry_price',
                 'exit_price', 'entry_fee', 'exit_fee', 'gross', 'net', 'entry_reason', 'exit_reason',
                 'cycle', 'entry_decision_row']
TRACE_COLUMNS = ['held_long', 'held_short', 'occupied_long', 'occupied_short', 'pending_entry', 'pending_exit']
EVENT_COLUMNS = ['row', 'parent_id', 'source', 'code', 'side', 'quantity', 'decision_row',
                 'limit_price', 'mode', 'decision_time', 'cycle', 'detail']
STAT_COLUMNS = ['max_held_long', 'max_held_short', 'max_occupied_long', 'max_occupied_short',
                'held_long', 'held_short', 'pending_entry', 'pending_exit', 'max_total_held',
                'range_cancellations', 'cancel_race_fills', 'trend_rejections', 'range_rejections',
                'trend_reservations', 'range_reservations', 'cash']
SLOT_COLUMNS = ['status', 'side', 'quantity', 'parent_id', 'entry_price', 'entry_row', 'entry_fee',
                'peak', 'stop', 'deadline', 'decision_row', 'decision_time', 'limit_price',
                'cancel_decision_row', 'cancel_decision_time', 'cycle', 'entry_decision_row', 'entry_reason']
RANGE_STATE_COLUMNS = ['phase', 'range_anchor', 'peer_anchor', 'width', 'peer_width', 'episode',
                       'watch_side', 'own_low', 'own_low_row', 'own_high', 'own_high_row',
                       'peer_low', 'peer_low_source', 'peer_high', 'peer_high_source',
                       'center_held', 'center_self_seen', 'center_peer_seen', 'last_exit_row',
                       'last_exit_peer_source', 'center_return_row', 'prepared_row',
                       'prepared_peer_source', 'witness_stop', 'range_armed']
RISK_STATE_COLUMNS = ['gate_consumed', 'gate_row', 'gate_accepted', 'gate_side', 'planned_entry',
                      'planned_liquidation', 'spread', 'fee_width', 'planned_extreme_risk',
                      'center_gain', 'risk_proxy', 'center_ratio', 'entry_failure_line',
                      'entry_target_line', 'entry_center', 'entry_peer_center', 'entry_width',
                      'entry_peer_width', 'exit_width_flag', 'exit_witness_flag', 'exit_target_flag',
                      'failure_paused', 'failure_center', 'failure_peer_center', 'failure_width',
                      'failure_peer_width', 'failure_exit_row', 'failure_exit_time',
                      'failure_exit_own_source', 'failure_exit_peer_source', 'failure_false_seen',
                      'failure_false_grid', 'failure_false_own_source', 'failure_false_peer_source',
                      'failure_release_row', 'failure_self_seen', 'failure_peer_seen',
                      'raw_observable', 'raw_range', 'raw_oldest_time']
RANGE_PARENT_COLUMNS = ['parent_id', 'decision_row', 'entry_row', 'exit_row', 'side', 'quantity',
                        'episode', 'center', 'peer_center', 'width', 'peer_width', 'extreme',
                        'extreme_row', 'failure_line', 'planned_entry', 'planned_liquidation',
                        'spread', 'fee_width', 'planned_extreme_risk', 'center_gain', 'risk_proxy',
                        'center_ratio', 'target_line', 'actual_extreme_risk', 'exit_decision_row',
                        'exit_width_flag', 'exit_witness_flag', 'exit_target_flag', 'net',
                        'entry_peer_source', 'exit_peer_source', 'exit_time', 'failure_pause_started']
PRICE_SOURCE_COLUMNS = ['lane', 'grid', 'price_own_index', 'price_peer_index',
                        'price_own_raw_seq', 'price_peer_raw_seq', 'execution_own_index',
                        'execution_peer_index', 'price_own_time', 'price_peer_time',
                        'execution_own_time', 'execution_peer_time', 'price_own_valid',
                        'price_peer_valid', 'price_observable', 'mode', 'context_kind',
                        'context_decision_row', 'context_accepted', 'execution_current_valid',
                        'execution_peer_valid', 'price_mode']
REASONS = {1: '初期損切り', 2: '追跡返済', 3: '保有期限', 4: '場内返済',
           5: '指値の利確幅到達', 6: '指値の損切り幅到達', 7: '反対の二市場追従で返済',
           8: '独立した二市場の反対確認で返済', 9: '往復利益の追跡返済',
           10: '共通方向の新規', 11: '上下到達から持続指値新規',
           12: '逸脱後の回復確認で成行新規', 13: '観測極値の失敗線で返済',
           14: '固定幅と観測極値の停止ORで返済', 15: '準備時中心の利益目標で返済', 16: '同親の条件付き追加新規'}
EVENT_CODES = {1: '新規予約', 2: '返済予約', 3: '取消判断', 4: '新規約定', 5: '返済約定',
               6: '取消有効', 7: '取消前の約定を保持', 8: '親終了', 9: '新規不参加', 10: '指値基準の再設定',
               11: '往復開始時の基準更新', 12: '往復仮説を準備', 13: '往復仮説を解除',
               14: '往復利益の追跡を開始', 15: '往復利益の追跡線を更新',
               16: '相手市場の中心を確定', 17: '逸脱方向を一度だけ選択',
               18: '自己市場の安値を更新', 19: '自己市場の高値を更新',
               20: '相手市場の安値を更新', 21: '相手市場の高値を更新',
               22: '回復確認を成立', 23: '実返済後も中心を保持',
               24: '中心帯への帰還を成立', 25: '次の逸脱を再準備',
               26: '中心保持エピソードを解除', 27: '初回回復の入口余地を判定',
               28: '極値失敗の実損切り後に休止', 29: '失敗後の有効なraw往復否定を観測',
               30: '失敗後休止を新観測で解除'}


LOSS_OBSERVATION_COLUMNS = ['own_bbo_index', 'own_bbo_seq', 'own_bbo_time', 'own_bid', 'own_ask',
    'peer_bbo_index', 'peer_bbo_seq', 'peer_bbo_time', 'peer_bid', 'peer_ask',
    'own_lp_index', 'own_lp_seq', 'own_lp_time', 'own_lp_value',
    'peer_lp_index', 'peer_lp_seq', 'peer_lp_time', 'peer_lp_value',
    'own_bbo_valid', 'peer_bbo_valid', 'own_lp_valid', 'peer_lp_valid']
LOSS_EVENT_COLUMNS = ['row', 'code', 'previous_parent', 'previous_side', 'previous_exit_reason',
    'previous_net', 'previous_exit_row', 'previous_exit_time', 'loss_active', 'anchor_kind',
    'anchor_row', 'anchor_grid'] + ['anchor_' + name for name in LOSS_OBSERVATION_COLUMNS] + [
    'observed_' + name for name in LOSS_OBSERVATION_COLUMNS] + ['candidate_side', 'gate_required',
    'fresh_sources', 'quotes_progress', 'prices_progress', 'sustained', 'gate_accepted',
    'sustain_start_grid', 'reentry_kind', 'trigger_kind']
LOSS_EVENT_CODES = {1: '実親終了で損失記憶を更新', 2: '実親終了で反転制限を解除',
    3: '返済後の初回有効ペアを別基準に固定', 4: '反対候補を一度だけ判定',
    5: '両市場反転証拠の持続を開始', 6: '欠測又は格子欠落で持続を破棄'}


TREND_EXIT_STATE_COLUMNS = ['parent_id', 'status', 'side', 'entry_price', 'initial_width',
    'trail_width', 'activation_width', 'quote', 'quote_valid', 'peak', 'initial_line',
    'trail_line', 'fee_line', 'half_line', 'protection_active', 'protection_floor',
    'stop_before', 'stop_after', 'effective_line_owner', 'deadline_enabled', 'deadline',
    'decision_reason', 'decision_row']
TREND_PARENT_COLUMNS = ['parent_id', 'entry_row', 'exit_row', 'side', 'quantity', 'entry_price',
    'initial_width', 'trail_width', 'activation_width', 'initial_line', 'fee_line',
    'decision_peak', 'protection_active', 'protection_floor', 'decision_row', 'decision_time',
    'decision_quote', 'decision_stop', 'initial_line_hit', 'trail_line_hit',
    'protection_line_hit', 'effective_line_owner', 'deadline_enabled', 'exit_reason',
    'exit_price', 'net', 'decision_observation_row']
TREND_LINE_OWNERS = {1: '初期停止線', 2: '常時追尾線', 4: '費用込み利益床', 8: '最大順行の半分の床'}

ENTRY_WATCH_COLUMNS = ['active', 'phase', 'side', 'candidate_id', 'candidate_row', 'candidate_seq',
    'candidate_time', 'candidate_quote', 'deadline', 'width', 'advance_width', 'pullback_width',
    'recovery_width', 'favorable_peak', 'opposite_extreme', 'phase_row', 'phase_time',
    'own_anchor_index', 'own_anchor_seq', 'own_anchor_time', 'own_anchor_bid', 'own_anchor_ask',
    'peer_anchor_index', 'peer_anchor_seq', 'peer_anchor_time', 'peer_anchor_bid', 'peer_anchor_ask',
    'anchor_valid', 'fallback_used', 'anchor_row', 'anchor_grid', 'kind']
ENTRY_OBSERVATION_COLUMNS = ['own_index', 'own_seq', 'own_time', 'own_bid', 'own_ask',
    'peer_index', 'peer_seq', 'peer_time', 'peer_bid', 'peer_ask']
ENTRY_FLAGS_COLUMNS = ['grid_index', 'j2_allowed', 'hard_opposite', 'fresh_sources', 'quotes_progress',
    'price_ready', 'cancel_flags', 'pair_valid']
WATCH_STATE_COLUMNS = ENTRY_WATCH_COLUMNS + ['observed_' + name for name in ENTRY_OBSERVATION_COLUMNS] + ENTRY_FLAGS_COLUMNS
ENTRY_WAIT_EVENT_COLUMNS = ['row', 'code', 'reason', 'parent_id', 'grid_index',
    'arriving_candidate_id', 'arriving_side'] + ['state_' + name for name in ENTRY_WATCH_COLUMNS] + [
    'observed_' + name for name in ENTRY_OBSERVATION_COLUMNS] + ENTRY_FLAGS_COLUMNS
ENTRY_PARENT_COLUMNS = ['parent_id', 'candidate_id', 'candidate_row', 'candidate_seq', 'candidate_time',
    'candidate_quote', 'kind', 'side', 'quantity', 'width', 'advance_width', 'pullback_width',
    'recovery_width', 'phase_row', 'phase_time', 'favorable_peak', 'opposite_extreme',
    'own_anchor_index', 'own_anchor_seq', 'own_anchor_time', 'own_anchor_bid', 'own_anchor_ask',
    'peer_anchor_index', 'peer_anchor_seq', 'peer_anchor_time', 'peer_anchor_bid', 'peer_anchor_ask',
    'fallback_used', 'trigger_row', 'trigger_seq', 'trigger_time', 'trigger_quote', 'trigger_grid',
    'j2_allowed', 'bbo_confirmation', 'fresh_sources', 'quotes_progress', 'fill_row', 'fill_seq',
    'fill_time', 'fill_price', 'market_outcome', 'exit_row', 'net', 'pair_valid']
ENTRY_WAIT_EVENT_CODES = {1: '候補受理して待機', 2: '新候補を消費して不参加', 3: '候補取消',
    4: '有利極値を更新', 5: '押しを経験して不利極値を開始', 6: '不利極値を更新',
    7: '未知基準の最初の正常ペアを固定', 8: '価格と現在確認で市場新規を予約',
    9: '市場予約を場末受付で取消'}
ENTRY_WAIT_REASONS = {0: '該当なし', 1: '場末新規停止', 2: '候補期限', 3: '自己原行間隔超過',
    4: '自己reset', 5: '自己気配不明', 6: '両300秒価格の硬い反対', 7: '行頭で待機中',
    8: '市場予約又は保有中', 9: '旧新規受付資格不足'}


# ----------------------------------------
# 価格時計の差と有効取消、再準備の源を旧待機列と混ぜずに保存する。
ENTRY_CAP_STATE_COLUMNS = ['enabled', 'multiple', 'cap_width', 'watch_active', 'candidate_id',
    'candidate_time', 'candidate_quote', 'width', 'side', 'current_entry_quote', 'quote_valid',
    'adverse_width', 'cap_pass', 'old_trigger', 'selected_trigger', 'cap_blocked', 'deadline',
    'row_time', 'parent_id', 'cancel_flags']
ENTRY_CAP_PARENT_COLUMNS = ['parent_id', 'candidate_id', 'candidate_time', 'side', 'quantity',
    'candidate_quote', 'width', 'enabled', 'multiple', 'cap_width', 'trigger_row', 'trigger_time',
    'trigger_quote', 'trigger_adverse_width', 'trigger_inside_cap', 'fill_row', 'fill_time',
    'fill_price', 'fill_adverse_width', 'fill_cap_excess', 'market_outcome']


GROWTH_COHORT_COLUMNS = ['parent_id', 'cohort_id', 'source', 'side', 'quantity', 'decision_row',
    'decision_seq', 'decision_time', 'entry_row', 'entry_seq', 'entry_time', 'entry_price',
    'entry_fee', 'order_uid', 'exit_row', 'exit_seq', 'exit_time', 'exit_price', 'exit_fee_share',
    'gross', 'net', 'risk_budget', 'initial_quantity', 'entry_kind', 'parent_final_quantity']
GROWTH_STATE_BASE_COLUMNS = ['parent_id', 'mode', 'held_quantity', 'pending_quantity', 'initial_quantity',
    'maximum_quantity', 'risk_budget', 'entry_cash', 'entry_fees', 'exit_fee_estimate', 'total_fees',
    'weighted_entry', 'liquidation_quote', 'current_net', 'first_fill_price', 'first_fill_time',
    'first_fill_row', 'last_fill_row', 'initial_line', 'price_peak', 'trail_line', 'budget_line',
    'protection_active', 'fee_line', 'effective_stop', 'deadline', 'pending_row', 'pending_time',
    'last_action', 'anchor_valid', 'anchor_row', 'anchor_grid', 'proposed_quantity',
    'proposed_total_quantity', 'proposed_entry', 'proposed_cash', 'proposed_fees', 'proposed_net',
    'proposed_budget_line', 'proposed_fee_line', 'proposed_stop', 'proposed_cushion',
    'current_allowed', 'pair_valid', 'fresh_sources', 'quotes_progress', 'net_allowed',
    'cushion_allowed', 'eligible', 'same_fill_row_blocked']
GROWTH_STATE_COLUMNS = GROWTH_STATE_BASE_COLUMNS + ['anchor_' + name for name in ENTRY_OBSERVATION_COLUMNS] + [
    'observed_' + name for name in ENTRY_OBSERVATION_COLUMNS]
GROWTH_EVENT_COLUMNS = ['row', 'code', 'reason', 'quantity'] + GROWTH_STATE_COLUMNS
GROWTH_EVENT_CODES = {1: '初回実約定と固定予算開始', 2: '追加を市場予約', 3: '追加を実約定',
    4: '未約定追加を取消', 5: '未知peer復帰の基準だけを設定', 6: '全cohortを実返済'}
GROWTH_PARENT_COLUMNS = ['parent_id', 'side', 'first_fill_row', 'first_fill_time', 'first_fill_price',
    'initial_quantity', 'final_quantity', 'risk_budget', 'entry_cash', 'entry_fees', 'exit_fee',
    'weighted_entry', 'exit_row', 'exit_seq', 'exit_time', 'exit_price', 'gross', 'net',
    'realized_budget_excess', 'maximum_observed_budget_excess', 'cohort_count', 'deadline',
    'protection_active', 'final_stop']

# ----------------------------------------
# 新しい余裕と据置資格は旧70列を拡張せず、判断と実fillの事実を分けて保存する。
GROWTH_GATE_STATE_COLUMNS = ['parent_id', 'cushion_basis', 'cushion_initial_multiple',
    'preserve_stop', 'initial_width', 'required_cushion', 'old_stop_after_normal_update',
    'planned_stop', 'planned_net_at_old_stop', 'risk_budget', 'cushion_allowed',
    'budget_at_old_allowed', 'stop_preserved', 'base_eligible', 'eligible',
    'actual_added_quantity', 'actual_fill_old_stop', 'actual_fill_new_stop', 'actual_fill_tightened']


@njit(cache=True, inline='always')
def growth_round(price, side, tick):
    """
    機能: 価格全体を損失予算又は利益床を保護する方向へ呼値で丸める。
    引数: price/tick(float)、side(int)。
    返り値: floatはロングceil又はショートfloor。費用幅だけの丸めを使わない。
    """
    return (math.ceil(price / tick) if side == 1 else math.floor(price / tick)) * tick


@njit(cache=True, inline='always')
def growth_lines(side, quantity, cash, fees, risk, initial_line, peak, trail_width,
                 old_stop, active, quote, initial_quantity, initial_width, value, tick, protection_mode):
    """
    機能: 固定R0・非緩和線・初期線・追尾・現在実grossに基づく費用床を統合する。
    引数: side/quantity/initial_quantity/protection_mode(int)、価格費用幅等(float)、active(bool)。
    返り値: tuple[float,float,float,bool]は予算線・費用線・有効停止線・保護active。
    """
    weighted = cash / (quantity * value)
    budget = growth_round(weighted - side * (risk - fees) / (quantity * value), side, tick)
    fee_line = growth_round(weighted + side * fees / (quantity * value), side, tick) + side * tick
    gross = side * (quantity * quote * value - cash)
    activated = active or (protection_mode != 0 and gross >= initial_quantity * 2. * initial_width * value)
    effective = old_stop
    for candidate in (initial_line, peak - side * trail_width, budget):
        if side * (candidate - effective) > 0:
            effective = candidate
    if activated and side * (fee_line - effective) > 0:
        effective = fee_line
    return budget, fee_line, effective, activated


@njit(cache=True, inline='always')
def growth_sources(anchor, observed, pair_ok, anchor_ok, phase_time, side, tick, peer_tick):
    """
    機能: 最後の実fill時点の両気配源から旧C1の源更新と1呼値進行を判定する。
    引数: anchor/observed(ndarray[float]、10列)、pair_ok/anchor_ok(bool)、その他(float/int)。
    返り値: tuple[bool,bool]は源更新と両bid/ask進行。LP源をBBO源へ置換しない。
    """
    if not pair_ok or not anchor_ok:
        return False, False
    fresh = (observed[0] > anchor[0] and observed[1] > anchor[1] and observed[2] > phase_time
        and observed[2] > anchor[2] and observed[5] > anchor[5] and observed[6] > anchor[6]
        and observed[7] > phase_time and observed[7] > anchor[7])
    progress = (fresh and side * (observed[3] - anchor[3]) >= tick - tick*1e-8
        and side * (observed[4] - anchor[4]) >= tick - tick*1e-8
        and side * (observed[8] - anchor[8]) >= peer_tick - peer_tick*1e-8
        and side * (observed[9] - anchor[9]) >= peer_tick - peer_tick*1e-8)
    return fresh, progress


@njit(cache=True, inline='always')
def growth_snapshot(slots, stats, watch, initial_quantity, pending_quantity):
    """
    機能: 初回待機枠と追加予約枠を実保有枚数から分離して上限へ含める。
    引数: slots/stats/watch(ndarray)、initial_quantity/pending_quantity(int)。
    返り値: ndarray[float]は旧6列。追加無しなら旧関数と完全同値。
    """
    trace = entry_snapshot(slots, stats, watch, initial_quantity)
    if pending_quantity > 0:
        side = int(slots[0, 1])
        trace[2 if side == 1 else 3] += pending_quantity
        trace[4] += pending_quantity
        stats[2 if side == 1 else 3] = max(stats[2 if side == 1 else 3], trace[2 if side == 1 else 3])
        stats[6] = trace[4]
    return trace


@njit(cache=True, inline='always')
def growth_cohort_close(cohorts, begin, end, row, sequence, stamp, price, fee, value, final_quantity):
    """
    機能: 全量返済一注文の整数円料金を最大剰余法で各実cohortへ配分する。
    引数: cohorts(ndarray[float]、25列)、begin/end/row/sequence/final_quantity(int)、その他(float)。
    返り値: None。剰余同値は実fill作成順の早いcohortを優先し料金合計を一致させる。
    """
    assigned = np.zeros(end - begin, np.float64)
    remaining = int(fee)
    for k in range(begin, end):
        allocation = fee * cohorts[k, 4] / final_quantity
        assigned[k - begin] = allocation - math.floor(allocation)
        cohorts[k, 18] = math.floor(allocation)
        remaining -= int(cohorts[k, 18])
    for unused in range(remaining):
        best = int(np.argmax(assigned))
        cohorts[begin + best, 18] += 1.
        assigned[best] = -1.
    for k in range(begin, end):
        gross = cohorts[k, 3] * (price - cohorts[k, 11]) * cohorts[k, 4] * value
        cohorts[k, 14:18] = np.array([row, sequence, stamp, price], dtype=np.float64)
        cohorts[k, 19] = gross
        cohorts[k, 20] = gross - cohorts[k, 12] - cohorts[k, 18]
        cohorts[k, 24] = final_quantity


ENTRY_POLICY_INTERNAL_COLUMNS = ['policy', 'paused', 'candidate_id', 'epoch_count', 'epoch_row',
    'epoch_time', 'epoch_anchor_valid', 'epoch_anchor_row', 'epoch_anchor_grid',
    'epoch_own_index', 'epoch_own_seq', 'epoch_own_time', 'epoch_own_bid', 'epoch_own_ask',
    'epoch_peer_index', 'epoch_peer_seq', 'epoch_peer_time', 'epoch_peer_bid', 'epoch_peer_ask',
    'reprepare_row']
ENTRY_POLICY_FLAG_COLUMNS = ['observed_gap', 'gap_pause_started', 'baseline_created',
    'epoch_sources_fresh', 'current_j2_allowed', 'reprepare_started', 'effective_cancel_flags',
    'geometry_paused', 'watch_active', 'market_status']
ENTRY_POLICY_STATE_COLUMNS = ENTRY_POLICY_INTERNAL_COLUMNS + [
    'observed_' + name for name in ENTRY_OBSERVATION_COLUMNS] + ENTRY_POLICY_FLAG_COLUMNS
ENTRY_POLICY_EVENT_COLUMNS = ['row', 'code', 'reason', 'grid_index'] + ENTRY_POLICY_STATE_COLUMNS + [
    'phase', 'phase_row', 'phase_time', 'favorable_peak', 'opposite_extreme', 'deadline']
ENTRY_POLICY_EVENT_CODES = {1: '価格時計gapを観測', 2: 'gap後の別epochを開始して休止',
    3: '未知epochの初回正常ペアを基準だけに固定', 4: '新源で局所価格位相を再準備',
    5: '候補取消を政策診断へ保存', 6: '候補成立を政策診断へ保存'}


@njit(cache=True, inline='always')
def entry_policy_candidate(state, policy, candidate):
    """
    機能: 新候補の政策状態を初期化し、以前のgap基準を流用しない。
    引数: state(ndarray[float]、20列)、policy(int)、candidate(int)。
    返り値: None。元のwatch価格・TTL・予約数量には触れない。
    """
    state[:] = np.nan
    state[:4] = np.array([policy, 0., candidate, 0.])
    state[4] = state[7] = state[8] = state[19] = -1.
    state[6] = 0.


@njit(cache=True, inline='always')
def entry_policy_epoch(state, observation, pair_ok, row, stamp, grid_index):
    """
    機能: gap行の自己源とその時まで公開された相手源を別epochへ固定する。
    引数: state/observation(ndarray)、pair_ok(bool)、row/grid_index(int)、stamp(float)。
    返り値: None。未知ペアは未知のまま保存し、価格phase・候補TTLを変えない。
    """
    state[1] = 1.
    state[3] += 1.
    state[4:9] = np.array([row, stamp, pair_ok, row, grid_index])
    state[9:19] = observation
    state[19] = -1.


@njit(cache=True, inline='always')
def entry_policy_sources(state, observation, pair_ok):
    """
    機能: epochと各anchorより後の両板源を、価格進行とは別に確認する。
    引数: state/observation(ndarray)、pair_ok(bool)。
    返り値: bool。両index/seqと両clockの厳密更新を要求し、板価格進行は要求しない。
    """
    return (pair_ok and state[6] != 0
        and observation[0] > state[9] and observation[1] > state[10]
        and observation[2] > state[5] and observation[2] > state[11]
        and observation[5] > state[14] and observation[6] > state[15]
        and observation[7] > state[5] and observation[7] > state[16])


@njit(cache=True, inline='always')
def entry_policy_log(log, cursor, row, code, reason, grid_index, state, observation, flags, watch):
    """
    機能: gap観測と休止・再準備を旧57列の候補イベントと別に記録する。
    引数: log/state/observation/flags/watch(ndarray)、cursor等(int)。
    返り値: intは次の保存位置。20内部状態・10源・10旗・6価格幾何を固定する。
    """
    assert cursor < len(log)
    log[cursor] = np.concatenate((np.array([row, code, reason, grid_index], dtype=np.float64),
        state, observation, flags, np.array([watch[1], watch[15], watch[16], watch[13],
                                            watch[14], watch[8]])))
    return cursor + 1


@njit(cache=True, inline='always')
def entry_pair_valid(observation, own_ok, peer_ok):
    """
    機能: 自己実原行と相手既公開行を別源の正常BBOペアとして判定する。
    引数: observation(ndarray[float]、10列)、own_ok/peer_ok(bool)。
    返り値: boolは全源番号時計が有限で0<bid<askのペア。相手時計は自己判断時計以下。
    """
    if not own_ok or not peer_ok:
        return False
    for k in range(10):
        if not np.isfinite(observation[k]):
            return False
    return (observation[0] >= 0 and observation[1] >= 0 and observation[5] >= 0
            and observation[6] >= 0 and observation[3] > 0 and observation[4] > observation[3]
            and observation[8] > 0 and observation[9] > observation[8]
            and observation[7] <= observation[2] + 1e-8)


@njit(cache=True, inline='always')
def entry_anchor(watch, observation, pair_ok, row, grid_index):
    """
    機能: 位相価格を変更せず、自己と相手BBOの比較基準だけを同時に固定する。
    引数: watch/observation(ndarray)、pair_ok(bool)、row/grid_index(int)。
    返り値: None。未知ペアは有効な基準に変換しない。
    """
    watch[17:27] = observation
    if not pair_ok:
        watch[22:27] = np.nan
    watch[27] = pair_ok
    watch[29] = row
    watch[30] = grid_index


@njit(cache=True, inline='always')
def entry_watch_start(watch, candidate_id, side, row, sequence, stamp, quote, width,
                      advance, pullback, recovery, seconds, kind, observation, pair_ok, grid_index):
    """
    機能: 当時の候補quoteと独立Wを固定し、以後の価格位相だけを初期化する。
    引数: watch/observation(ndarray)、候補番号等(int)、価格/幅/秒数(float)、pair_ok(bool)。
    返り値: None。旧実建値又は将来の出口peakを参照しない。
    """
    watch[:] = np.nan
    watch[:17] = np.array([1., 1., side, candidate_id, row, sequence, stamp, quote, stamp + seconds,
                           width, advance, pullback, recovery, quote, quote, row, stamp])
    watch[28] = 0.
    watch[31] = kind
    entry_anchor(watch, observation, pair_ok, row, grid_index)


@njit(cache=True, inline='always')
def entry_bbo_status(watch, observation, pair_ok, own_tick, peer_tick, clock_policy=0):
    """
    機能: 旧位相後確認又は各市場の基準後確認で、両板源と両気配の順行を判定する。
    引数: watch/observation(ndarray)、pair_ok(bool)、own_tick/peer_tick(float)、clock_policy(int)。
    返り値: tuple[bool,bool]は源更新と両bid/ask進行。C2だけ各anchorの時計非逆行を使う。
    """
    if not pair_ok or watch[27] == 0:
        return False, False
    if clock_policy == 2:
        fresh = (observation[0] > watch[17] and observation[1] > watch[18]
                 and observation[2] >= watch[19]
                 and observation[5] > watch[22] and observation[6] > watch[23]
                 and observation[7] >= watch[24])
    else:
        fresh = (observation[0] > watch[17] and observation[1] > watch[18]
                 and observation[2] > watch[16] and observation[2] > watch[19]
                 and observation[5] > watch[22] and observation[6] > watch[23]
                 and observation[7] > watch[16] and observation[7] > watch[24])
    side = int(watch[2])
    progress = (fresh and side * (observation[3] - watch[20]) >= own_tick - own_tick*1e-8
                and side * (observation[4] - watch[21]) >= own_tick - own_tick*1e-8
                and side * (observation[8] - watch[25]) >= peer_tick - peer_tick*1e-8
                and side * (observation[9] - watch[26]) >= peer_tick - peer_tick*1e-8)
    return fresh, progress


@njit(cache=True, inline='always')
def entry_wait_log(log, cursor, row, code, reason, parent, grid_index, arriving_id,
                   arriving_side, watch, observation, flags):
    """
    機能: 候補消費・位相変更・取消・実新規予約を別の疎イベントへ固定する。
    引数: log/watch/observation/flags(ndarray)、cursor等(int)。
    返り値: intは次の追記位置。既存注文イベントや数量統計を書き換えない。
    """
    assert cursor < len(log)
    log[cursor] = np.concatenate((np.array([row, code, reason, parent, grid_index, arriving_id,
                                           arriving_side], dtype=np.float64), watch, observation, flags))
    return cursor + 1


@njit(cache=True, inline='always')
def entry_snapshot(slots, stats, watch, quantity):
    """
    機能: 待機予約量を占有と新規待ちだけに加えて、保有数量と分離する。
    引数: slots/stats/watch(ndarray)、quantity(int)。
    返り値: ndarray[float]は旧6数量。市場予約への移行前にwatchを解除する。
    """
    result = snapshot(slots, stats)
    if watch[0] != 0:
        assert slots[0, 0] == 0
        index = 2 if watch[2] == 1 else 3
        result[index] += quantity
        result[4] += quantity
        stats[index] = max(stats[index], result[index])
    return result


@njit(cache=True, inline='always')
def entry_parent_record(parents, cursor, parent, watch, row, sequence, stamp, quote,
                        quantity, grid_index, j2_allowed, bbo_confirm, fresh_sources, progress, pair_ok):
    """
    機能: 元候補と価格位相及び実予約を、後の実fillと照合できる親へ保存する。
    引数: parents/watch(ndarray)、cursor等(int)、stamp/quote(float)、各確認旗(bool)。
    返り値: intは保存した親診断の行番号。候補を約定行へ遡って動かさない。
    """
    assert cursor < len(parents)
    parents[cursor, :37] = np.array([parent, watch[3], watch[4], watch[5], watch[6], watch[7],
        watch[31], watch[2], quantity, watch[9], watch[10], watch[11], watch[12], watch[15], watch[16],
        watch[13], watch[14], watch[17], watch[18], watch[19], watch[20], watch[21], watch[22],
        watch[23], watch[24], watch[25], watch[26], watch[28], row, sequence, stamp, quote, grid_index,
        j2_allowed, bbo_confirm, fresh_sources, progress])
    parents[cursor, 44] = pair_ok
    return cursor


@njit(cache=True, inline='always')
def trend_line_owner(stop, initial_line, trail_line, fee_line, half_line, active, tick):
    """
    機能: 有効な合成停止線と同じ価格の全構成線をビットの論理和で記録する。
    引数: stop/initial_line/trail_line/fee_line/half_line/tick(float)、active(bool)。
    返り値: intは初期1・追尾2・費用床4・半分床8。等価な線を一つへ潰さない。
    """
    owner = 0
    tolerance = tick * 1e-8
    if abs(stop - initial_line) <= tolerance:
        owner |= 1
    if abs(stop - trail_line) <= tolerance:
        owner |= 2
    if active and abs(stop - fee_line) <= tolerance:
        owner |= 4
    if active and np.isfinite(half_line) and abs(stop - half_line) <= tolerance:
        owner |= 8
    return owner


@njit(cache=True, inline='always')
def trend_exit_diagnostic(parent, slots, row, stamp, observation_row, quote, qok, reason,
                          initial_line, trail_line, fee_line, half_line, active, floor, tick,
                          hold_enabled):
    """
    機能: 返済予約時の停止線と共存証拠を実決済の親診断へ固定する。
    引数: parent/slots(ndarray)、row/observation_row/reason(int)、価格時刻(float)、旗(bool)。
    返り値: None。既知場末の予約番号と実際に観測した原行を別々に保持する。
    """
    side = int(slots[0, 1])
    stop = slots[0, 8]
    parent[11] = slots[0, 7]
    parent[12] = active
    parent[13] = floor if active else np.nan
    parent[14] = row
    parent[15] = stamp
    parent[16] = quote if qok else np.nan
    parent[17] = stop
    parent[18] = qok and side * (quote - initial_line) <= tick * 1e-8
    parent[19] = qok and side * (quote - trail_line) <= tick * 1e-8
    parent[20] = active and qok and side * (quote - floor) <= tick * 1e-8
    parent[21] = trend_line_owner(stop, initial_line, trail_line, fee_line, half_line, active, tick)
    parent[22] = hold_enabled
    parent[23] = reason
    parent[26] = observation_row


@njit(cache=True, inline='always')
def loss_pair_valid(observation):
    """
    機能: 独立LPと旧BBOの四源がすべて正常であることを確認する。
    引数: observation(ndarray[float])は22列の価格及び執行観測。
    返り値: boolは同一格子で四源を観測可能なこと。LPで不正板を救済しない。
    """
    for k in (18, 19, 20, 21):
        if observation[k] != 1:
            return False
    for k in range(18):
        if not np.isfinite(observation[k]):
            return False
    return (observation[0] >= 0 and observation[5] >= 0 and observation[10] >= 0
            and observation[14] >= 0 and observation[1] >= 0 and observation[6] >= 0
            and observation[11] >= 0 and observation[15] >= 0 and 0 < observation[3] < observation[4]
            and 0 < observation[8] < observation[9] and observation[13] > 0 and observation[17] > 0)


@njit(cache=True, inline='always')
def loss_gate_status(observation, anchor, exit_time, side, own_tick, peer_tick):
    """
    機能: 実返済後の四源更新と双方両気配及びLP進行を別々に判定する。
    引数: observation/anchor(ndarray[float])、exit_time/own_tick/peer_tick(float)、side(int)。
    返り値: tuple[bool,bool,bool]は新源、気配進行、LP進行。原seqと独立indexを分ける。
    """
    fresh = loss_pair_valid(observation) and loss_pair_valid(anchor)
    for index, sequence, clock in ((0, 1, 2), (5, 6, 7), (10, 11, 12), (14, 15, 16)):
        fresh = (fresh and observation[index] > anchor[index] and observation[sequence] > anchor[sequence]
                 and observation[clock] > exit_time and observation[clock] > anchor[clock])
    quotes = (fresh and side * (observation[3] - anchor[3]) >= own_tick - 1e-8
              and side * (observation[4] - anchor[4]) >= own_tick - 1e-8
              and side * (observation[8] - anchor[8]) >= peer_tick - 1e-8
              and side * (observation[9] - anchor[9]) >= peer_tick - 1e-8)
    prices = (fresh and side * (observation[13] - anchor[13]) >= own_tick - 1e-8
              and side * (observation[17] - anchor[17]) >= peer_tick - 1e-8)
    return fresh, quotes, prices


@njit(cache=True, inline='always')
def loss_event(log, cursor, row, code, parent_info, active, anchor_kind, anchor_row,
               anchor_grid, anchor, observed, side, required, fresh, quotes, prices,
               sustained, accepted, sustain_start, kind, trigger):
    """
    機能: 実終了親・四源基準・候補の判定を旧イベントと別の疎な台帳へ保存する。
    引数: log/parent_info/anchor/observed(ndarray)、cursor/row/code/side/kind/trigger等(int又はbool)。
    返り値: intは次の記録位置。旧注文・親・状態列の意味を変更しない。
    """
    assert cursor < len(log)
    log[cursor, :12] = np.array([row, code, parent_info[0], parent_info[1], parent_info[2],
        parent_info[3], parent_info[4], parent_info[5], active, anchor_kind, anchor_row, anchor_grid])
    log[cursor, 12:34] = anchor
    log[cursor, 34:56] = observed
    log[cursor, 56:] = np.array([side, required, fresh, quotes, prices, sustained, accepted,
                               sustain_start, kind, trigger])
    return cursor + 1


@njit(cache=True, inline='always')
def range_event(events, cursor, row, code, side, quantity, center, mode, stamp, cycle, detail):
    """
    機能: 保有前後の中心・極値・帰還を当時行に対応する証拠として記録する。
    引数: events(ndarray)、cursor/row/code/side/quantity/mode/cycle(int)、その他(float)。
    返り値: int は次の追記位置。detailの源番号は相手市場の保持済み原板行である。
    """
    assert cursor < len(events)
    events[cursor] = np.array([row, 0, 1, code, side, quantity, row, center,
                              mode, stamp, cycle, detail])
    return cursor + 1


@njit(cache=True, inline='always')
def snapshot(slots, stats):
    """
    機能: 同じ行の途中で解消した保有・予約も最大枚数へ反映する。
    引数: slots/stats (ndarray[float])。
    返り値: ndarray[float] は保有・予約・発注待ちの6数量。
    """
    result = np.zeros(6, np.float64)
    for source in range(2):
        status = int(slots[source, 0])
        if status == 0:
            continue
        side = int(slots[source, 1])
        quantity = slots[source, 2]
        result[2 if side == 1 else 3] += quantity
        if status == 1:
            result[4] += quantity
        else:
            result[0 if side == 1 else 1] += quantity
            if status == 3:
                result[5] += quantity
    for index in range(4):
        stats[index] = max(stats[index], result[index])
    stats[8] = max(stats[8], result[0] + result[1])
    return result


@njit(cache=True, inline='always')
def record_event(events, cursor, slots, source, row, code, mode, detail):
    """
    機能: 予約・取消・約定順を原板行と親識別番号付きで追記する。
    引数: events/slots (ndarray)、cursor/source/row/code/mode (int)、detail (float)。
    返り値: int は次の追記位置。
    """
    assert cursor < len(events)
    decision_row = slots[source, 10]
    decision_time = slots[source, 11]
    if code == 3 or (code == 6 and detail == 0):
        decision_row = slots[source, 13]
        decision_time = slots[source, 14]
    events[cursor] = np.array([row, slots[source, 3], source, code, slots[source, 1], slots[source, 2],
                              decision_row, slots[source, 12], mode, decision_time,
                              slots[source, 15], detail])
    return cursor + 1


@njit(cache=True, inline='always')
def reserve_entry(slots, events, cursor, stats, source, side, quantity, row, stamp,
                  limit_price, parent, cycle, mode):
    """
    機能: 一源の新規を予約し、約定前から方向別上限を占有する。
    引数: slots/events/stats (ndarray)、cursor等 (int)、stamp/limit_price (float)。
    返り値: int は次のイベント追記位置。
    """
    slots[source, :] = 0
    slots[source, 0] = 1
    slots[source, 1] = side
    slots[source, 2] = quantity
    slots[source, 3] = parent
    slots[source, 10] = row
    slots[source, 11] = stamp
    slots[source, 12] = limit_price
    slots[source, 13] = -1
    slots[source, 15] = cycle
    slots[source, 16] = row
    slots[source, 17] = 10 if source == 0 else 11
    cursor = record_event(events, cursor, slots, source, row, 1, mode, 0)
    snapshot(slots, stats)
    return cursor


@njit(cache=True, inline='always')
def reserve_exit(slots, events, cursor, source, row, stamp, reason, mode):
    """
    機能: 返済を予約し、次有効気配までは保有数量を残す。
    引数: slots/events (ndarray)、cursor/source/row/reason/mode (int)、stamp (float)。
    返り値: int は次のイベント追記位置。
    """
    slots[source, 0] = 3
    slots[source, 10] = row
    slots[source, 11] = stamp
    return record_event(events, cursor, slots, source, row, 2, mode, reason)


@njit(cache=True, nogil=True)
def simulate(times, prices, bids, asks, price_valid, quote_valid, quality, reset, event, mapped,
             grid, mode_values, tick, start, limit, trend_width, trend_budget, range_budget,
             selection, cancel_pending, exit_opposite_range, value, fee_unit, cap,
             width_ticks, stop_multiple, target_multiple, hold_seconds, improve_limit, activate_anchor,
             persistent_arm, ungated_trend, current_valid, arm_common, reverse_long, reverse_short,
             reverse_trend, reverse_range, actual_range_width, break_widths, profit_trail,
             profit_activate_widths, profit_trail_widths, recovery_market, recovery_confirmation,
             recovery_fraction, adverse_watch_clear, witness_extreme, reentry_kind,
             center_fraction, center_after_all, center_release, peer_mid_values,
             peer_source_values, peer_valid_values, peer_width, peer_tick,
             entry_max_risk_widths, entry_min_center_ratio, stop_or, target_kind,
             center_target_offset, failure_reentry_kind, failure_center_fraction,
             own_source_values, own_source_times, peer_source_times, raw_range_valid,
             raw_range_eligible, raw_oldest_times, price_lane, context_kind,
             price_observable_values, price_own_indices, price_peer_indices,
             price_own_sequences, price_peer_sequences, price_own_times, price_peer_times,
             price_own_valid, price_peer_valid, price_mode_values, loss_observations,
             execution_sequences, execution_lp_indices, loss_kind, loss_trigger, loss_seconds,
             initial_stop_width, protection_mode, entry_kind, entry_wait_seconds, entry_wait_width,
             entry_advance_width, entry_pullback_width, entry_recovery_width, entry_confirm_bbo,
             entry_j2_long, entry_j2_short, wait_opposite_long, wait_opposite_short, entry_peer_bbo,
             clock_policy, entry_cap_enabled, entry_cap_multiple, initial_quantity, growth_mode, growth_cushion_ticks,
             growth_cushion_basis, growth_cushion_initial_multiple, growth_preserve_stop):
    """
    機能: 原板順に二源の予約・取消・約定と全原板清算時価を計算する。
    引数: 原板/信号 (ndarray)、価格時刻料金と固定幅 (float)、数量選択 (int)、取消返済等 (bool)。
    返り値: tuple は旧台帳と別の19列増玉gate状態。旧列は拡張しない。
    improve_limitは指値成立時の買ask/売bidを使う気配改善代理。
    persistent_armは一度の往復準備を不明状態で引き直さず、明確共同方向又は3幅破綻で解除する。
    reverse_long/shortは入口ERと別に作った格子別の反対確認である。
    指値成立を取消効力より先に扱い、通常注文は判断行より後の気配でのみ約定する。
    """
    n = len(times)
    allocation = max(2048, n * 2 + 64)
    orders = np.zeros((allocation, 17), np.float64)
    trades = np.zeros((allocation // 2 + 64, 16), np.float64)
    events = np.zeros((allocation * 4, 12), np.float64)
    curve = np.zeros(n, np.float64)
    source_curve = np.zeros((n, 2), np.float64)
    trace = np.zeros((n, 6), np.float64)
    range_state_trace = np.zeros((n, 25), np.float64)
    risk_state_trace = np.zeros((n, 40), np.float64)
    price_source_trace = np.zeros((n, 22), np.float64)
    range_parents = np.zeros((allocation // 2 + 64, 33), np.float64)
    range_parent = np.full(33, np.nan)
    loss_log = np.zeros((max(2048, len(grid) * 4 + 64) if loss_kind != 0 else 1, 66), np.float64)
    loss_cursor = 0
    loss_parent_info = np.array([0., 0., 0., 0., -1., -1e30])
    loss_active = False
    loss_anchor = np.full(22, np.nan)
    loss_anchor_kind = 0
    loss_anchor_row = loss_anchor_grid = -1
    loss_sustain_start = -1
    loss_sustain_previous = -1e30
    loss_sustain_sources = np.full(22, np.nan)
    loss_sustained = False
    loss_fresh = loss_quotes = loss_prices = False

    # ----------------------------------------
    # 初期停止と利益床は追従源だけに適用し、旧枠・列はそのまま保持する。
    trend_exit_state_trace = np.full((n, 23), np.nan)
    trend_parents = np.zeros((allocation // 2 + 64, 27), np.float64)
    trend_parent = np.full(27, np.nan)
    trend_parent_cursor = 0
    trend_initial_line = trend_trail_line = trend_fee_line = trend_half_line = np.nan
    trend_protection_floor = np.nan
    trend_protection_active = False
    trend_stop_before = np.nan
    trend_hold_enabled = hold_seconds > 0

    # ----------------------------------------
    # 待機中の価格とBBO源は実建玉から切り離し、同候補を再利用しない。
    watch = np.full(32, np.nan)
    watch[:4] = 0.
    watch[31] = entry_kind
    watch_state_trace = np.full((n, 50), np.nan)
    entry_wait_events = np.zeros((allocation, 57), np.float64)
    entry_wait_cursor = 0
    entry_parents = np.full((allocation // 2 + 64, 45), np.nan)
    entry_parent_cursor = 0
    active_entry_parent = -1
    entry_candidate_counter = 0

    # ----------------------------------------
    # gapの観測と価格位相の休止は別状態にし、旧watchの列定義を変更しない。
    policy_state = np.full(20, np.nan)
    entry_policy_candidate(policy_state, clock_policy, 0)
    entry_policy_state_trace = np.full((n, 40), np.nan)
    entry_policy_events = np.zeros((allocation, 50), np.float64)
    entry_policy_cursor = 0

    # ----------------------------------------
    # 上限は候補価格からの判断だけに作用し、予約後の成行約定は変更しない。
    entry_cap_state_trace = np.full((n, 20), np.nan)
    entry_cap_width = entry_cap_multiple * entry_wait_width if entry_cap_enabled else np.nan

    # ----------------------------------------
    # 追加は同じ親の別成行予約と実cohortで管理し、未保有数量の利益を先取りしない。
    growth_pending = np.array([0., -1., np.nan, np.nan], dtype=np.float64)
    growth_state_trace = np.full((n, 70), np.nan)
    growth_gate_state_trace = np.full((n, 19), np.nan)
    growth_events = np.zeros((allocation, 74), np.float64)
    growth_event_cursor = 0
    growth_cohorts = np.full((allocation // 2 + 64, 25), np.nan)
    growth_cohort_cursor = growth_cohort_begin = 0
    growth_parents = np.full((allocation // 2 + 64, 24), np.nan)
    growth_parent_cursor = 0
    growth_r0 = growth_cash = growth_first_price = growth_first_time = np.nan
    growth_first_row = growth_last_fill = growth_anchor_row = growth_anchor_grid = -1
    growth_phase_time = -1e30
    growth_anchor = np.full(10, np.nan)
    growth_anchor_valid = False
    growth_budget_line = np.nan
    growth_max_excess = 0.
    growth_parent_id = 0

    slots = np.zeros((2, 18), np.float64)
    stats = np.zeros(16, np.float64)
    cash = np.zeros(2, np.float64)
    exit_reason = np.zeros(2, np.int64)
    cycles = np.zeros(2, np.int64)
    last_exit = -1e30
    last_bid = last_ask = np.nan
    latest = -1
    parent = 1
    no = nt = ne = nrp = 0
    range_anchor = np.nan
    reset_anchor_after = -1
    last_anchor_row = -1
    previous_range_eligible = False
    previous_price = np.nan
    previous_rejected_side = 0
    width = actual_range_width if actual_range_width > 0 else width_ticks * tick
    range_armed = False
    range_trail_active = False
    new_state_enabled = recovery_market or reentry_kind != 0
    peer_anchor = np.nan
    own_low = own_high = peer_low = peer_high = np.nan
    own_low_row = own_high_row = peer_low_source = peer_high_source = -1
    prepared_row = prepared_peer_source = -1
    episode = 0
    watch_side = 0
    witness_stop = np.nan
    center_held = False
    center_self_seen = center_peer_seen = False
    last_range_exit_row = last_range_exit_peer_source = -1
    center_return_row = -1
    reentry_ready = True
    require_reprepare = False
    gate_consumed = False
    gate_row = -1
    gate_accepted = gate_side = 0
    planned_entry = planned_liquidation = planned_spread = fee_width = np.nan
    planned_risk = center_gain = risk_proxy = center_ratio = np.nan
    entry_failure_line = entry_target_line = entry_center = entry_peer_center = np.nan
    entry_width = entry_peer_width = np.nan
    exit_width_flag = exit_witness_flag = exit_target_flag = False
    failure_paused = False
    failure_center = failure_peer_center = failure_width = failure_peer_width = np.nan
    failure_exit_row = failure_exit_own_source = failure_exit_peer_source = -1
    failure_exit_time = -1e30
    failure_false_seen = False
    failure_false_grid = failure_false_own_source = failure_false_peer_source = -1
    failure_release_row = -1
    failure_self_seen = failure_peer_seen = False
    context_decision_row = -1
    context_accepted = 0
    gated_entry = entry_max_risk_widths > 0 or entry_min_center_ratio > 0 or context_kind != 0
    entry_cut = limit - 300.0
    range_entry_cut = limit - 120.0
    force_time = limit - 60.0
    closing = False

    for i in range(n):
        stamp = times[i]
        qok = quote_valid[i] and np.isfinite(bids[i]) and np.isfinite(asks[i]) and bids[i] > 0 and asks[i] > bids[i]
        if qok:
            last_bid, last_ask = bids[i], asks[i]
        updated = int(mapped[i])
        if updated >= 0:
            latest = updated
        fresh = latest >= 0 and stamp - grid[latest] <= 10.0 + 1e-8
        mode = int(mode_values[latest]) if fresh else 0
        current_fresh = fresh and current_valid[latest]
        joint_direction = int(arm_common[latest]) if current_fresh else 0
        peer_ok = (fresh and peer_valid_values[latest] and np.isfinite(peer_mid_values[latest])
                   and peer_mid_values[latest] > 0)
        peer_mid = peer_mid_values[latest] if peer_ok else np.nan
        peer_source = int(peer_source_values[latest]) if peer_ok else -1
        # 欠測でも判断器へ既に公開された源番号は失わない。真の受信時計とは区別する。
        published_peer_source = int(peer_source_values[latest]) if latest >= 0 else -1
        published_own_source = int(own_source_values[latest]) if latest >= 0 else -1
        own_source_time = own_source_times[latest] if latest >= 0 else np.nan
        peer_source_time = peer_source_times[latest] if latest >= 0 else np.nan
        raw_observable = fresh and raw_range_valid[latest]
        raw_range = raw_observable and raw_range_eligible[latest]
        raw_oldest_time = raw_oldest_times[latest] if latest >= 0 else np.nan
        price_observable = fresh and price_observable_values[latest]
        price_mode = int(price_mode_values[latest]) if fresh else 0
        own_mid = .5 * (bids[i] + asks[i]) if qok else np.nan

        ew_had_watch = watch[0] != 0
        ew_had_market = slots[0, 0] != 0
        ew_created = False
        growth_row_events = np.zeros((4, 3), np.float64)
        growth_row_event_count = 0
        growth_planned = np.full(10, np.nan)
        growth_flags = np.zeros(8, np.float64)
        required_cushion = (growth_cushion_initial_multiple * initial_stop_width
                            if growth_cushion_basis == 1 else growth_cushion_ticks * tick)
        growth_gate_row = np.full(19, np.nan)
        growth_gate_row[:6] = np.array([growth_parent_id, growth_cushion_basis,
            growth_cushion_initial_multiple if growth_cushion_basis == 1 else np.nan,
            growth_preserve_stop, initial_stop_width, required_cushion])
        growth_gate_row[9] = growth_r0
        growth_gate_row[15] = 0.
        cap_old_trigger = cap_selected_trigger = cap_blocked = False
        cap_quote = cap_adverse = np.nan
        cap_quote_valid = cap_pass = False
        ew_observation = np.full(10, np.nan)
        ew_observation[:5] = np.array([i, execution_sequences[i], stamp, bids[i], asks[i]])
        if latest >= 0:
            ew_observation[5:] = entry_peer_bbo[latest, :5]
        ew_peer_ok = fresh and entry_peer_bbo[latest, 5] == 1. if latest >= 0 else False
        ew_pair_ok = entry_pair_valid(ew_observation, qok, ew_peer_ok)
        ew_flags = np.zeros(8, np.float64)
        ew_flags[0] = latest
        ew_flags[7] = ew_pair_ok
        ew_raw_gap = i > 0 and stamp - times[i - 1] > 10. + 1e-8
        policy_flags = np.zeros(10, np.float64)
        policy_flags[8] = watch[0]
        policy_flags[9] = slots[0, 0]
        ew_policy_blocked = False
        if watch[0] != 0:
            ew_side = int(watch[2])
            ew_flags[1] = fresh and (entry_j2_long[latest] if ew_side == 1 else entry_j2_short[latest])
            ew_flags[2] = fresh and (wait_opposite_long[latest] if ew_side == 1 else wait_opposite_short[latest])
            ew_flags[6] = ((1 if stamp >= entry_cut else 0) | (2 if stamp >= watch[8] else 0)
                           | (4 if ew_raw_gap and clock_policy == 0 else 0) | (8 if reset[i] else 0)
                           | (16 if not qok else 0) | (32 if ew_flags[2] != 0 else 0))
            policy_flags[0] = ew_raw_gap
            policy_flags[4] = ew_flags[1]
            policy_flags[6] = ew_flags[6]
            if ew_raw_gap:
                entry_policy_cursor = entry_policy_log(entry_policy_events, entry_policy_cursor,
                    i, 1, 0, latest, policy_state, ew_observation, policy_flags, watch)
            ew_cancel = 0
            if stamp >= entry_cut:
                ew_cancel = 1
            elif stamp >= watch[8]:
                ew_cancel = 2
            elif ew_raw_gap and clock_policy == 0:
                ew_cancel = 3
            elif reset[i]:
                ew_cancel = 4
            elif not qok:
                ew_cancel = 5
            elif ew_flags[2] != 0:
                ew_cancel = 6
            if ew_cancel != 0:
                entry_wait_cursor = entry_wait_log(entry_wait_events, entry_wait_cursor, i, 3,
                    ew_cancel, 0, latest, 0, 0, watch, ew_observation, ew_flags)
                policy_state[1] = 0.
                entry_policy_cursor = entry_policy_log(entry_policy_events, entry_policy_cursor,
                    i, 5, ew_cancel, latest, policy_state, ew_observation, policy_flags, watch)
                watch[0] = watch[1] = 0.
            elif ew_raw_gap and clock_policy == 3:
                entry_policy_epoch(policy_state, ew_observation, ew_pair_ok, i, stamp, latest)
                policy_flags[1] = policy_flags[7] = 1.
                entry_policy_cursor = entry_policy_log(entry_policy_events, entry_policy_cursor,
                    i, 2, 0, latest, policy_state, ew_observation, policy_flags, watch)

        # ----------------------------------------
        # 既知の場末だけは通常取消・判断遅延と区別して先行させる。
        if stamp >= range_entry_cut and slots[1, 0] == 1:
            ne = record_event(events, ne, slots, 1, i, 6, mode, 1)
            slots[1, 0] = 0
            stats[9] += 1
        if stamp >= entry_cut and slots[0, 0] == 1:
            if active_entry_parent >= 0:
                entry_parents[active_entry_parent, 41] = 2.
                entry_wait_cursor = entry_wait_log(entry_wait_events, entry_wait_cursor, i, 9,
                    1, int(slots[0, 3]), latest, 0, 0, watch, ew_observation, ew_flags)
                active_entry_parent = -1
            ne = record_event(events, ne, slots, 0, i, 6, mode, 1)
            slots[0, 0] = 0
        if not closing and stamp >= force_time:
            closing = True
            for source in range(2):
                if slots[source, 0] == 2:
                    exit_reason[source] = 4
                    if source == 0:
                        trend_stop_before = slots[source, 8]
                        quote = bids[i] if slots[source, 1] == 1 else asks[i]
                        trend_exit_diagnostic(trend_parent, slots, i - 1, force_time, i, quote, qok,
                            4, trend_initial_line, trend_trail_line, trend_fee_line, trend_half_line,
                            trend_protection_active, trend_protection_floor, tick, trend_hold_enabled)
                    ne = reserve_exit(slots, events, ne, source, i - 1, force_time, 4, mode)
                    events[ne - 1, 0] = i

        # ----------------------------------------
        # 生きていた指値、次の成行、取消の順。取消前の成立は消さない。
        if growth_pending[0] > 0:
            growth_cancel = (1 if closing else 2 if slots[0, 0] == 3 else
                             3 if trend_hold_enabled and stamp >= slots[0, 9] else
                             4 if slots[0, 0] != 2 else 0)
            if growth_cancel != 0:
                growth_row_events[growth_row_event_count] = np.array([4., growth_cancel, growth_pending[0]])
                growth_row_event_count += 1
                growth_pending[0] = 0.
            elif qok and i > growth_pending[1]:
                side = int(slots[0, 1])
                delta = int(growth_pending[0])
                fill = asks[i] if side == 1 else bids[i]
                fee = math.floor(delta * fee_unit + 1e-8)
                assert no < len(orders) and growth_cohort_cursor < len(growth_cohorts)
                orders[no] = np.array([i, growth_pending[1], slots[0, 3], 0, side, delta, fill,
                    1, 16, fee, growth_pending[2], stamp, 0, slots[0, 15], 0, side, no + 1])
                no += 1
                cash[0] -= side * delta * fill * value + fee
                growth_cash += delta * fill * value
                slots[0, 2] += delta
                slots[0, 4] = growth_cash / (slots[0, 2] * value)
                slots[0, 6] += fee
                growth_cohorts[growth_cohort_cursor, :14] = np.array([slots[0, 3],
                    growth_cohort_cursor - growth_cohort_begin + 1, 0, side, delta,
                    growth_pending[1], growth_pending[3], growth_pending[2], i,
                    execution_sequences[i], stamp, fill, fee, no])
                growth_cohorts[growth_cohort_cursor, 21:24] = np.array([growth_r0, initial_quantity, 1.])
                growth_cohort_cursor += 1
                growth_pending[0] = 0.
                growth_last_fill = i
                growth_phase_time = stamp
                growth_anchor[:] = ew_observation
                growth_anchor_valid = ew_pair_ok
                growth_anchor_row, growth_anchor_grid = i, latest
                if not ew_pair_ok:
                    growth_anchor[5:] = np.nan
                quantity = int(slots[0, 2])
                fees = slots[0, 6] + math.floor(quantity * fee_unit + 1e-8)
                quote = bids[i] if side == 1 else asks[i]
                actual_fill_old_stop = slots[0, 8]
                growth_budget_line, trend_fee_line, new_stop, trend_protection_active = growth_lines(
                    side, quantity, growth_cash, fees, growth_r0, trend_initial_line, slots[0, 7],
                    trend_width, slots[0, 8], trend_protection_active, quote, initial_quantity,
                    initial_stop_width, value, tick, protection_mode)
                slots[0, 8] = new_stop
                growth_gate_row[15:] = np.array([delta, actual_fill_old_stop, new_stop,
                    side * (new_stop-actual_fill_old_stop) > 0.])
                trend_protection_floor = trend_fee_line if trend_protection_active else np.nan
                growth_row_events[growth_row_event_count] = np.array([3., 0., delta])
                growth_row_event_count += 1
                snapshot(slots, stats)
        for source in range(2):
            status = int(slots[source, 0])
            if status != 1 and status != 3:
                continue
            if not qok or i <= slots[source, 10]:
                continue
            side = int(slots[source, 1])
            quantity = int(slots[source, 2])
            is_entry = status == 1
            action = side if is_entry else -side
            fill = asks[i] if action == 1 else bids[i]
            can_fill = True
            if is_entry and source == 1 and not recovery_market:
                limit_price = slots[source, 12]
                can_fill = asks[i] <= limit_price if side == 1 else bids[i] >= limit_price
                if can_fill and not improve_limit:
                    fill = limit_price
            if can_fill:
                assert no < len(orders)
                fee = math.floor(quantity * fee_unit + 1e-8)
                reason = int(slots[source, 17]) if is_entry else int(exit_reason[source])
                orders[no] = np.array([i, slots[source, 10], slots[source, 3], source, action, quantity,
                                       fill, 1 if is_entry else 0, reason, fee, slots[source, 11], stamp,
                                       slots[source, 12] if is_entry else 0, slots[source, 15],
                                       1 if is_entry and source == 1 and not recovery_market else 0,
                                       side, no + 1])
                no += 1
                cash[source] -= action * quantity * fill * value + fee
                if is_entry:
                    if source == 1 and slots[source, 13] >= 0:
                        stats[10] += 1
                        ne = record_event(events, ne, slots, source, i, 7, mode, 0)
                    slots[source, 0] = 2
                    slots[source, 4] = fill
                    slots[source, 5] = i
                    slots[source, 6] = fee
                    if source == 0 and active_entry_parent >= 0:
                        entry_parents[active_entry_parent, 37:42] = np.array([i, execution_sequences[i], stamp, fill, 1.])
                    slots[source, 7] = fill
                    slots[source, 8] = fill - side * trend_width
                    if source == 0:
                        growth_parent_id = int(slots[source, 3])
                        growth_cash = quantity * fill * value
                        growth_r0 = quantity * initial_stop_width * value + 2. * fee
                        growth_first_price, growth_first_time = fill, stamp
                        growth_first_row = growth_last_fill = i
                        growth_phase_time = stamp
                        growth_anchor[:] = ew_observation
                        growth_anchor_valid = ew_pair_ok
                        growth_anchor_row, growth_anchor_grid = i, latest
                        if not ew_pair_ok:
                            growth_anchor[5:] = np.nan
                        growth_budget_line = fill - side * initial_stop_width
                        growth_max_excess = 0.
                        growth_cohort_begin = growth_cohort_cursor
                        assert growth_cohort_cursor < len(growth_cohorts)
                        growth_cohorts[growth_cohort_cursor, :14] = np.array([slots[source, 3], 1, 0,
                            side, quantity, slots[source, 10], execution_sequences[int(slots[source, 10])],
                            slots[source, 11], i, execution_sequences[i], stamp, fill, fee, no])
                        growth_cohorts[growth_cohort_cursor, 21:24] = np.array([growth_r0, initial_quantity, 0.])
                        growth_cohort_cursor += 1
                        growth_row_events[growth_row_event_count] = np.array([1., 0., quantity])
                        growth_row_event_count += 1
                        trend_initial_line = fill - side * initial_stop_width
                        trend_trail_line = fill - side * trend_width
                        slots[source, 8] = trend_initial_line
                        if side * (trend_trail_line - slots[source, 8]) > 0:
                            slots[source, 8] = trend_trail_line
                        trend_fee_width = 2. * fee / (quantity * value)
                        protected_width = math.ceil(trend_fee_width / tick) * tick + tick
                        assert protected_width <= 2. * initial_stop_width, '費用床幅は固定2S開始値以下である必要があります'
                        trend_fee_line = fill + side * protected_width
                        trend_half_line = np.nan
                        trend_protection_active = False
                        trend_protection_floor = np.nan
                        trend_stop_before = slots[source, 8]
                        trend_parent = np.full(27, np.nan)
                        trend_parent[:11] = np.array([slots[source, 3], i, np.nan, side, quantity,
                            fill, initial_stop_width, trend_width, 2. * initial_stop_width,
                            trend_initial_line, trend_fee_line])
                    if source == 1 and profit_trail:
                        slots[source, 8] = fill - side * stop_multiple * width
                        range_trail_active = False
                    slots[source, 9] = stamp + hold_seconds
                    if source == 0 and not trend_hold_enabled:
                        slots[source, 9] = 0.
                    slots[source, 13] = -1
                    if source == 1 and recovery_market:
                        range_parent[2] = i
                        range_parent[23] = side * (fill - entry_failure_line)
                    ne = record_event(events, ne, slots, source, i, 4, mode, 0)
                    snapshot(slots, stats)
                else:
                    assert nt < len(trades)
                    gross = side * (fill - slots[source, 4]) * quantity * value
                    trades[nt] = np.array([slots[source, 3], source, slots[source, 5], i, side, quantity,
                                          slots[source, 4], fill, slots[source, 6], fee, gross,
                                          gross - slots[source, 6] - fee, slots[source, 17], reason,
                                          slots[source, 15], slots[source, 16]])
                    nt += 1
                    if source == 0:
                        growth_cohort_close(growth_cohorts, growth_cohort_begin, growth_cohort_cursor,
                            i, execution_sequences[i], stamp, fill, fee, value, quantity)
                        assert growth_parent_cursor < len(growth_parents)
                        net = gross - slots[source, 6] - fee
                        growth_max_excess = max(growth_max_excess, -net-growth_r0)
                        growth_parents[growth_parent_cursor] = np.array([slots[source, 3], side,
                            growth_first_row, growth_first_time, growth_first_price, initial_quantity,
                            quantity, growth_r0, growth_cash, slots[source, 6], fee, slots[source, 4],
                            i, execution_sequences[i], stamp, fill, gross, net, max(0., -net-growth_r0),
                            growth_max_excess, growth_cohort_cursor-growth_cohort_begin,
                            slots[source, 9], trend_protection_active, slots[source, 8]])
                        growth_parent_cursor += 1
                        growth_row_events[growth_row_event_count] = np.array([6., 0., quantity])
                        growth_row_event_count += 1
                        assert trend_parent_cursor < len(trend_parents)
                        trend_parent[4] = quantity
                        trend_parent[5] = slots[source, 4]
                        trend_parent[2] = i
                        trend_parent[24] = fill
                        trend_parent[25] = gross - slots[source, 6] - fee
                        trend_parents[trend_parent_cursor] = trend_parent
                        trend_parent_cursor += 1
                        if active_entry_parent >= 0:
                            entry_parents[active_entry_parent, 42] = i
                            entry_parents[active_entry_parent, 43] = gross - slots[source, 6] - fee
                            active_entry_parent = -1
                    ne = record_event(events, ne, slots, source, i, 5, mode, reason)
                    ne = record_event(events, ne, slots, source, i, 8, mode, gross - slots[source, 6] - fee)
                    slots[source, 0] = 0
                    if source == 0:
                        last_exit = stamp
                        if loss_kind != 0:
                            net = gross - slots[source, 6] - fee
                            loss_parent_info = np.array([slots[source, 3], side, reason, net, i, stamp])
                            loss_active = net < 0 and (loss_trigger == 0 or reason == 1 or reason == 2)
                            loss_anchor = np.full(22, np.nan)
                            loss_anchor_kind = 0
                            loss_anchor_row = i
                            loss_anchor_grid = latest
                            loss_sustain_start = -1
                            loss_sustain_previous = -1e30
                            loss_sustained = False
                            observed = loss_observations[latest].copy() if fresh else np.full(22, np.nan)
                            if loss_active:
                                loss_anchor = observed.copy()
                                loss_anchor[0] = i
                                loss_anchor[1] = execution_sequences[i]
                                loss_anchor[2] = stamp
                                loss_anchor[3] = bids[i]
                                loss_anchor[4] = asks[i]
                                loss_anchor[10] = execution_lp_indices[i]
                                loss_anchor[11] = execution_sequences[i]
                                loss_anchor[12] = stamp
                                loss_anchor[13] = prices[i]
                                loss_anchor[18] = qok
                                loss_anchor[20] = price_valid[i] and np.isfinite(prices[i]) and prices[i] > 0 and execution_lp_indices[i] >= 0
                                if loss_pair_valid(loss_anchor):
                                    loss_anchor_kind = 1
                            loss_cursor = loss_event(loss_log, loss_cursor, i, 1 if loss_active else 2,
                                loss_parent_info, loss_active, loss_anchor_kind, loss_anchor_row,
                                loss_anchor_grid, loss_anchor, observed, 0, False, False, False, False,
                                False, False, -1, loss_kind, loss_trigger)

                    elif recovery_market:
                        range_parent[3] = i
                        range_parent[24] = slots[source, 10]
                        range_parent[25] = exit_width_flag
                        range_parent[26] = exit_witness_flag
                        range_parent[27] = exit_target_flag
                        range_parent[28] = gross - slots[source, 6] - fee
                        range_parent[30] = published_peer_source
                        range_parent[31] = stamp
                        range_parent[32] = (failure_reentry_kind != 0 and exit_witness_flag
                                            and range_parent[28] < 0)
                        range_parents[nrp] = range_parent
                        nrp += 1
                    if (source == 1 and failure_reentry_kind != 0 and exit_witness_flag
                            and gross - slots[source, 6] - fee < 0):
                        # 返済予約時の証拠と実返済純額の双方で初めて失敗を確定する。
                        failure_paused = True
                        failure_center, failure_peer_center = entry_center, entry_peer_center
                        failure_width, failure_peer_width = entry_width, entry_peer_width
                        failure_exit_row, failure_exit_time = i, stamp
                        failure_exit_own_source, failure_exit_peer_source = published_own_source, published_peer_source
                        failure_false_seen = False
                        failure_false_grid = failure_false_own_source = failure_false_peer_source = -1
                        failure_release_row = -1
                        failure_self_seen = failure_peer_seen = False
                        range_armed = False
                        range_anchor = peer_anchor = np.nan
                        reset_anchor_after = i
                        range_trail_active = False
                        previous_rejected_side = 0
                        center_held = False
                        watch_side = 0
                        witness_stop = np.nan
                        reentry_ready = True
                        require_reprepare = True
                        ne = range_event(events, ne, i, 28, side, range_budget, failure_center,
                                         mode, stamp, cycles[1], gross - slots[source, 6] - fee)
                    elif (reentry_kind != 0 and np.isfinite(range_anchor) and not require_reprepare
                          and source == 1
                          and (center_after_all or gross - slots[source, 6] - fee > 0)):
                        # 黒字限定は実約定と両側料金の確定netだけで判定する。
                        center_held = True
                        reentry_ready = reentry_kind == 1
                        center_self_seen = center_peer_seen = False
                        last_range_exit_row = i
                        last_range_exit_peer_source = published_peer_source
                        center_return_row = i if reentry_ready else -1
                        range_trail_active = False
                        watch_side = 0
                        witness_stop = np.nan
                        range_armed = persistent_arm
                        ne = range_event(events, ne, i, 23, 0, range_budget, range_anchor,
                                         mode, stamp, cycles[1], gross - slots[source, 6] - fee)
                        if reentry_ready:
                            cycles[1] += 1
                            own_low = own_high = own_mid
                            own_low_row = own_high_row = i
                            peer_low = peer_high = peer_mid
                            peer_low_source = peer_high_source = peer_source
                            prepared_row, prepared_peer_source = i, peer_source
                            ne = range_event(events, ne, i, 25, 0, range_budget, range_anchor,
                                             mode, stamp, cycles[1], peer_source)
                    elif source == 1 and persistent_arm:
                        range_armed = False
                        range_anchor = np.nan
                        reset_anchor_after = i
                        range_trail_active = False
                        previous_rejected_side = 0
                        events[ne] = np.array([i, 0, 1, 13, 0, range_budget, i, 0,
                                              mode, stamp, cycles[1], 3])
                        ne += 1
                        if new_state_enabled:
                            center_held = False
                            peer_anchor = np.nan
                            watch_side = 0
                            witness_stop = np.nan
                            reentry_ready = True
                    elif source == 1 and new_state_enabled and require_reprepare:
                        # 解除済みの保有が後に黒字になっても無効な中心を復活させない。
                        range_anchor = peer_anchor = np.nan
                        center_held = False
                        reset_anchor_after = i
                        watch_side = 0
                        witness_stop = np.nan
                        reentry_ready = True
                    elif source == 1 and price_valid[i]:
                        range_anchor = prices[i]
                        cycles[1] += 1
                        last_anchor_row = i
                        previous_rejected_side = 0
                        events[ne] = np.array([i, 0, 1, 10, 0, range_budget, i, range_anchor, mode, stamp, cycles[1], 0])
                        ne += 1
                        if new_state_enabled:
                            center_held = False
                            peer_anchor = peer_mid
                            episode += 1
                            prepared_row, prepared_peer_source = i, peer_source
                            watch_side = 0
                            witness_stop = np.nan
                            reentry_ready = True
                            if peer_ok:
                                ne = range_event(events, ne, i, 16, 0, range_budget, peer_anchor,
                                                 mode, stamp, cycles[1], peer_source)
            elif source == 1 and slots[source, 13] >= 0 and i > slots[source, 13]:
                ne = record_event(events, ne, slots, source, i, 6, mode, 0)
                slots[source, 0] = 0
                stats[9] += 1
                reset_anchor_after = i
                range_anchor = np.nan
                range_armed = False
                previous_rejected_side = 0
                if new_state_enabled:
                    center_held = False
                    peer_anchor = np.nan
                    watch_side = 0
                    witness_stop = np.nan
                    reentry_ready = True

        # ----------------------------------------
        # 通常返済は新規約定と別の観測から。指標欠測だけで保有を捨てない。
        for source in range(2):
            if slots[source, 0] != 2 or i <= slots[source, 5]:
                continue
            side = int(slots[source, 1])
            if source == 0:
                trend_stop_before = slots[source, 8]
            reason = 0
            width_hit = (source == 1 and (not witness_extreme or stop_or) and price_valid[i]
                         and side * (prices[i] - slots[source, 4]) <= -stop_multiple * width)
            witness_hit = (source == 1 and witness_extreme and qok and np.isfinite(witness_stop)
                           and side * ((bids[i] if side == 1 else asks[i]) - witness_stop) <= tick * 1e-8)
            if closing:
                reason = 4
            elif ((reverse_trend if source == 0 else reverse_range) and fresh
                  and (reverse_long[latest] if side == 1 else reverse_short[latest])):
                reason = 8
            elif source == 0:
                if trend_hold_enabled and stamp >= slots[source, 9]:
                    reason = 3
                elif qok:
                    quote = bids[i] if side == 1 else asks[i]
                    if side * (quote - slots[source, 8]) <= tick * 1e-8:
                        reason = 1 if abs(slots[source, 7] - slots[source, 4]) < tick * 1e-8 else 2
                    else:
                        if side * (quote - slots[source, 7]) > 0:
                            slots[source, 7] = quote
                        candidate = slots[source, 7] - side * trend_width
                        trend_trail_line = candidate
                        if side * (candidate - slots[source, 8]) > 0:
                            slots[source, 8] = candidate
                        progress = side * (slots[source, 7] - slots[source, 4])
                        if growth_mode != 0:
                            quantity = int(slots[source, 2])
                            fees = slots[source, 6] + math.floor(quantity * fee_unit + 1e-8)
                            growth_budget_line, trend_fee_line, new_stop, trend_protection_active = growth_lines(
                                side, quantity, growth_cash, fees, growth_r0, trend_initial_line, slots[source, 7],
                                trend_width, slots[source, 8], trend_protection_active, quote,
                                initial_quantity, initial_stop_width, value, tick, protection_mode)
                            slots[source, 8] = new_stop
                            trend_protection_floor = trend_fee_line if trend_protection_active else np.nan
                        elif protection_mode != 0 and progress >= 2. * initial_stop_width:
                            trend_protection_active = True
                        if trend_protection_active and growth_mode == 0:
                            trend_protection_floor = trend_fee_line
                            if protection_mode == 2:
                                half_width = math.floor(progress * .5 / tick) * tick
                                trend_half_line = slots[source, 4] + side * half_width
                                if side * (trend_half_line - trend_protection_floor) > 0:
                                    trend_protection_floor = trend_half_line
                            if side * (trend_protection_floor - slots[source, 8]) > 0:
                                slots[source, 8] = trend_protection_floor
            elif stop_or and (width_hit or witness_hit):
                reason = 14
            elif witness_hit:
                reason = 13
            elif price_valid[i]:
                progress = side * (prices[i] - slots[source, 4])
                if not witness_extreme and progress <= -stop_multiple * width:
                    reason = 6
                elif not profit_trail and target_kind != 0 and np.isfinite(entry_target_line) and (
                        side * (prices[i] - entry_target_line) >= -tick * 1e-8):
                    reason = 15
                elif not profit_trail and target_kind == 0 and progress >= target_multiple * width:
                    reason = 5
                elif exit_opposite_range and mode == -side:
                    reason = 7
                elif profit_trail and qok:
                    quote = bids[i] if side == 1 else asks[i]
                    profit = side * (quote - slots[source, 4])
                    if range_trail_active and side * (quote - slots[source, 8]) <= tick * 1e-8:
                        reason = 9
                    else:
                        if not range_trail_active and profit >= profit_activate_widths * width:
                            range_trail_active = True
                            ne = record_event(events, ne, slots, source, i, 14, mode, profit)
                        if side * (quote - slots[source, 7]) > 0:
                            slots[source, 7] = quote
                        if range_trail_active:
                            candidate = slots[source, 7] - side * profit_trail_widths * width
                            if side * (candidate - slots[source, 8]) > 0:
                                slots[source, 8] = candidate
                                ne = record_event(events, ne, slots, source, i, 15, mode, candidate)
            if reason:
                if source == 0:
                    quote = bids[i] if side == 1 else asks[i]
                    trend_exit_diagnostic(trend_parent, slots, i, stamp, i, quote, qok, reason,
                        trend_initial_line, trend_trail_line, trend_fee_line, trend_half_line,
                        trend_protection_active, trend_protection_floor, tick, trend_hold_enabled)
                if source == 1:
                    # 停止ORの双方証拠は表示理由の優先に依存させず親へ固定する。
                    exit_width_flag = width_hit if reason in (6, 13, 14) else False
                    exit_witness_flag = witness_hit if reason in (6, 13, 14) else False
                    exit_target_flag = reason == 5 or reason == 15
                exit_reason[source] = reason
                ne = reserve_exit(slots, events, ne, source, i, stamp, reason, mode)
                if source == 0 and growth_pending[0] > 0:
                    growth_row_events[growth_row_event_count] = np.array([4., 2., growth_pending[0]])
                    growth_row_event_count += 1
                    growth_pending[0] = 0.

        # ----------------------------------------
        # 追加資格は初回とは別に判定し、実fill同行と未知peer基準作成同行では予約しない。
        if growth_mode != 0 and slots[0, 0] == 2 and qok:
            side = int(slots[0, 1])
            quantity = int(slots[0, 2])
            quote = bids[i] if side == 1 else asks[i]
            current_net = side * (quantity * quote * value - growth_cash) - slots[0, 6] - math.floor(quantity*fee_unit+1e-8)
            growth_max_excess = max(growth_max_excess, -current_net-growth_r0)
            current_allowed = fresh and (entry_j2_long[latest] if side == 1 else entry_j2_short[latest])
            new_anchor = False
            if not growth_anchor_valid and ew_pair_ok and i > growth_last_fill:
                growth_anchor[:] = ew_observation
                growth_anchor_valid = True
                growth_anchor_row, growth_anchor_grid = i, latest
                new_anchor = True
                growth_row_events[growth_row_event_count] = np.array([5., 0., 0.])
                growth_row_event_count += 1
            source_fresh, quotes_progress = growth_sources(growth_anchor, ew_observation,
                ew_pair_ok, growth_anchor_valid, growth_phase_time, side, tick, peer_tick)
            growth_flags[:4] = np.array([current_allowed, ew_pair_ok, source_fresh, quotes_progress], dtype=np.float64)
            growth_flags[7] = i == growth_last_fill
            delta = min(quantity, trend_budget - quantity)
            if delta > 0:
                total = quantity + delta
                entry_quote = asks[i] if side == 1 else bids[i]
                planned_cash = growth_cash + delta * entry_quote * value
                planned_fees = slots[0, 6] + math.floor(delta*fee_unit+1e-8) + math.floor(total*fee_unit+1e-8)
                planned_net = side * (total*quote*value-planned_cash)-planned_fees
                old_stop_after_normal_update = slots[0, 8]
                planned_budget, planned_fee, planned_stop, unused_active = growth_lines(side, total,
                    planned_cash, planned_fees, growth_r0, trend_initial_line, slots[0, 7], trend_width,
                    slots[0, 8], trend_protection_active, quote, initial_quantity, initial_stop_width,
                    value, tick, protection_mode)
                cushion = side * (quote-planned_stop)
                growth_planned[:] = np.array([delta, total, entry_quote, planned_cash, planned_fees,
                    planned_net, planned_budget, planned_fee, planned_stop, cushion])
                growth_flags[4] = current_net >= 0 and planned_net >= 0
                growth_flags[5] = cushion >= required_cushion
                planned_net_at_old_stop = side * (total*old_stop_after_normal_update*value-planned_cash)-planned_fees
                budget_at_old_allowed = planned_net_at_old_stop >= -growth_r0
                stop_preserved = side * (planned_stop-old_stop_after_normal_update) == 0.
                # 基本資格には余裕Bも据置T1も含めない。通常追尾の更新後の旧線だけと比較する。
                base_eligible = (not new_anchor and i > growth_last_fill and growth_pending[0] == 0
                    and quality[i] and not reset[i] and not closing and stamp < entry_cut
                    and current_allowed and ew_pair_ok and quotes_progress
                    and growth_flags[4] != 0)
                eligible = (base_eligible and growth_flags[5] != 0
                    and (not growth_preserve_stop or budget_at_old_allowed and stop_preserved))
                growth_flags[6] = eligible
                growth_gate_row[6:15] = np.array([old_stop_after_normal_update, planned_stop,
                    planned_net_at_old_stop, growth_r0, growth_flags[5], budget_at_old_allowed,
                    stop_preserved, base_eligible, eligible])
                if eligible:
                    growth_pending[:] = np.array([delta, i, stamp, execution_sequences[i]], dtype=np.float64)
                    growth_row_events[growth_row_event_count] = np.array([2., 0., delta])
                    growth_row_event_count += 1

        # ----------------------------------------
        # 指値の失効判断。取消効力は次の有効気配、そこでも成立を先に扱う。
        if (not persistent_arm and cancel_pending and slots[1, 0] == 1
                and slots[1, 13] < 0 and mode != 2):
            slots[1, 13] = i
            slots[1, 14] = stamp
            ne = record_event(events, ne, slots, 1, i, 3, mode, 0)

        # ----------------------------------------
        # 往復仮説は分類不明で保持し、明確な二市場方向又は固定幅の破綻だけで解除する。
        if persistent_arm and range_armed:
            broken = (price_valid[i] and abs(prices[i] - range_anchor) >= break_widths * width - tick * 1e-8)
            common_break = joint_direction != 0
            if recovery_market and adverse_watch_clear and watch_side != 0:
                common_break = joint_direction == -watch_side
            if common_break or broken:
                range_armed = False
                reset_anchor_after = i
                detail = 1 if common_break else 2
                events[ne] = np.array([i, slots[1, 3] if slots[1, 0] else 0, 1, 13,
                                      slots[1, 1] if slots[1, 0] else 0,
                                      slots[1, 2] if slots[1, 0] else range_budget,
                                      i, range_anchor, mode, stamp, cycles[1], detail])
                ne += 1
                if slots[1, 0] == 1 and slots[1, 13] < 0:
                    slots[1, 13] = i
                    slots[1, 14] = stamp
                    ne = record_event(events, ne, slots, 1, i, 3, mode, detail)
                elif slots[1, 0] == 0:
                    range_anchor = np.nan
                if new_state_enabled:
                    center_held = False
                    reentry_ready = True
                    require_reprepare = True
                    peer_anchor = np.nan
                    watch_side = 0
                    center_self_seen = center_peer_seen = False
        elif center_held and center_release:
            # 非持続型の中心保持だけに追加する解除。初回入口の条件は変えない。
            broken = (price_valid[i] and abs(prices[i] - range_anchor) >= break_widths * width - tick * 1e-8)
            if joint_direction != 0 or broken:
                ne = range_event(events, ne, i, 26, 0, range_budget, range_anchor,
                                 mode, stamp, cycles[1], 1 if joint_direction != 0 else 2)
                center_held = False
                reentry_ready = True
                require_reprepare = True
                reset_anchor_after = i
                watch_side = 0
                peer_anchor = np.nan
                center_self_seen = center_peer_seen = False
                if slots[1, 0] == 1 and slots[1, 13] < 0:
                    slots[1, 13] = i
                    slots[1, 14] = stamp
                    ne = record_event(events, ne, slots, 1, i, 3, mode, 1)
                elif slots[1, 0] == 0:
                    range_anchor = np.nan

        # ----------------------------------------
        # 帰還は実返済後の新源を同じ判断行で確認し、別行から次の逸脱を監視する。
        if (new_state_enabled and center_held and not reentry_ready and slots[1, 0] == 0
                and i > last_range_exit_row and price_valid[i] and qok):
            center_self_seen = (price_valid[i] and abs(prices[i] - range_anchor)
                                <= center_fraction * width + tick * 1e-8)
            center_peer_seen = (peer_ok and np.isfinite(peer_anchor)
                                and peer_source > max(last_range_exit_peer_source, prepared_peer_source)
                                and abs(peer_mid - peer_anchor) <= center_fraction * peer_width + peer_tick * 1e-8)
            returned = center_self_seen and (reentry_kind != 3 or center_peer_seen)
            if returned:
                reentry_ready = True
                center_return_row = i
                prepared_row, prepared_peer_source = i, peer_source
                own_low = own_high = own_mid
                own_low_row = own_high_row = i
                peer_low = peer_high = peer_mid
                peer_low_source = peer_high_source = peer_source
                watch_side = 0
                cycles[1] += 1
                ne = range_event(events, ne, i, 24, 0, range_budget, range_anchor,
                                 mode, stamp, cycles[1], peer_source)
                ne = range_event(events, ne, i, 25, 0, range_budget, range_anchor,
                                 mode, stamp, cycles[1], peer_source)
        elif new_state_enabled and center_held and not reentry_ready:
            center_self_seen = center_peer_seen = False

        # ----------------------------------------
        # 失敗中心は新注文の中心から隔離し、実返済後の新しい観測だけで休止を解く。
        if failure_paused and slots[1, 0] == 0 and i > failure_exit_row:
            failure_self_seen = (price_valid[i] and qok and np.isfinite(failure_center)
                                 and abs(prices[i] - failure_center)
                                 <= failure_center_fraction * failure_width + tick * 1e-8)
            failure_peer_seen = (peer_ok and np.isfinite(failure_peer_center)
                                 and peer_source > failure_exit_peer_source
                                 and np.isfinite(peer_source_time) and peer_source_time > failure_exit_time
                                 and abs(peer_mid - failure_peer_center)
                                 <= failure_center_fraction * failure_peer_width + peer_tick * 1e-8)
            released = False
            if failure_reentry_kind == 1:
                released = failure_self_seen
            elif failure_reentry_kind == 2:
                released = failure_self_seen and failure_peer_seen
            elif failure_reentry_kind == 3:
                # 300秒・180秒・共同方向窓の最古の実源まで実返済後であることを要求する。
                new_observation = (updated >= 0 and raw_observable
                                   and np.isfinite(raw_oldest_time) and raw_oldest_time > failure_exit_time
                                   and published_own_source > failure_exit_own_source
                                   and published_peer_source > failure_exit_peer_source
                                   and np.isfinite(own_source_time) and own_source_time > failure_exit_time
                                   and np.isfinite(peer_source_time) and peer_source_time > failure_exit_time)
                if new_observation and not raw_range and not failure_false_seen:
                    failure_false_seen = True
                    failure_false_grid = latest
                    failure_false_own_source, failure_false_peer_source = published_own_source, published_peer_source
                    ne = range_event(events, ne, i, 29, 0, range_budget, failure_center,
                                     mode, stamp, cycles[1], latest)
                if (new_observation and failure_false_seen and latest > failure_false_grid
                        and raw_range and mode == 2
                        and published_own_source > failure_false_own_source
                        and published_peer_source > failure_false_peer_source):
                    released = True
            if released:
                failure_paused = False
                failure_release_row = i
                reset_anchor_after = i
                range_anchor = peer_anchor = np.nan
                range_armed = False
                require_reprepare = True
                ne = range_event(events, ne, i, 30, 0, range_budget, failure_center,
                                 mode, stamp, cycles[1], failure_reentry_kind)

        # ----------------------------------------
        # 実終了親が負けた後だけ、反対方向の四源証拠を更新する。同方向は制限しない。
        if loss_kind >= 2 and loss_active:
            observed = loss_observations[latest].copy() if fresh else np.full(22, np.nan)
            side = -int(loss_parent_info[1])
            just_anchored = False
            if loss_anchor_kind == 0 and fresh and loss_pair_valid(observed):
                after_exit = True
                for clock in (2, 7, 12, 16):
                    after_exit = after_exit and observed[clock] > loss_parent_info[5]
                if after_exit:
                    loss_anchor = observed.copy()
                    loss_anchor_kind = 2
                    loss_anchor_row = i
                    loss_anchor_grid = latest
                    just_anchored = True
                    loss_cursor = loss_event(loss_log, loss_cursor, i, 3, loss_parent_info,
                        loss_active, loss_anchor_kind, loss_anchor_row, loss_anchor_grid, loss_anchor,
                        observed, 0, False, False, False, False, False, False, -1, loss_kind, loss_trigger)
            loss_fresh, loss_quotes, loss_prices = loss_gate_status(observed, loss_anchor,
                loss_parent_info[5], side, tick, peer_tick) if loss_anchor_kind != 0 else (False, False, False)
            if just_anchored:
                loss_fresh = loss_quotes = loss_prices = False
            if loss_kind == 4:
                raw = loss_quotes and loss_prices and not just_anchored
                gap = updated >= 0 and grid[latest] - loss_sustain_previous > 5.0 + 1e-8
                if not raw or gap:
                    if loss_sustain_start >= 0:
                        loss_cursor = loss_event(loss_log, loss_cursor, i, 6, loss_parent_info,
                            loss_active, loss_anchor_kind, loss_anchor_row, loss_anchor_grid, loss_anchor,
                            observed, 0, False, loss_fresh, loss_quotes, loss_prices, False, False,
                            loss_sustain_start, loss_kind, loss_trigger)
                    loss_sustain_start = -1
                    loss_sustained = False
                if updated >= 0:
                    loss_sustain_previous = grid[latest]
                    if raw:
                        if loss_sustain_start < 0:
                            loss_sustain_start = latest
                            loss_sustain_sources = observed.copy()
                            loss_cursor = loss_event(loss_log, loss_cursor, i, 5, loss_parent_info,
                                loss_active, loss_anchor_kind, loss_anchor_row, loss_anchor_grid, loss_anchor,
                                observed, 0, False, loss_fresh, loss_quotes, loss_prices, False, False,
                                loss_sustain_start, loss_kind, loss_trigger)
                        advanced = True
                        for source_index, source_sequence, source_clock in ((0, 1, 2), (5, 6, 7), (10, 11, 12), (14, 15, 16)):
                            advanced = (advanced and observed[source_index] > loss_sustain_sources[source_index]
                                and observed[source_sequence] > loss_sustain_sources[source_sequence]
                                and observed[source_clock] > loss_sustain_sources[source_clock])
                        loss_sustained = (grid[latest] - grid[loss_sustain_start] >= loss_seconds and advanced)

        # ----------------------------------------
        # 追従源は選択した候補とJ2許可を使い、旧数量・出口・執行を保持する。

        ew_arriving_id = 0
        if event[i] != 0:
            entry_candidate_counter += 1
            ew_arriving_id = entry_candidate_counter

        if (entry_kind == 0 and trend_budget > 0 and slots[0, 0] == 0 and event[i] != 0 and quality[i]
                and not reset[i] and qok and stamp >= start + 300.0 and stamp < entry_cut
                and stamp - last_exit >= 30.0):
            side = int(event[i])
            allowed = ungated_trend or selection == 0 or mode == side
            free = selection != 1 or slots[1, 0] == 0
            required = loss_kind != 0 and loss_active and side == -int(loss_parent_info[1])
            accepted = (not required or (loss_kind == 2 and loss_quotes)
                        or (loss_kind == 3 and loss_quotes and loss_prices)
                        or (loss_kind == 4 and loss_sustained))
            if required:
                observed = loss_observations[latest].copy() if fresh else np.full(22, np.nan)
                loss_cursor = loss_event(loss_log, loss_cursor, i, 4, loss_parent_info,
                    loss_active, loss_anchor_kind, loss_anchor_row, loss_anchor_grid, loss_anchor,
                    observed, side, True, loss_fresh, loss_quotes, loss_prices, loss_sustained,
                    accepted, loss_sustain_start, loss_kind, loss_trigger)
            if allowed and free and accepted:
                ew_descriptor = np.full(32, np.nan)
                ew_quote = asks[i] if side == 1 else bids[i]
                entry_watch_start(ew_descriptor, ew_arriving_id, side, i, execution_sequences[i], stamp,
                    ew_quote, entry_wait_width, 0., 0., 0., entry_wait_seconds, 0, ew_observation, ew_pair_ok, latest)
                ew_descriptor[0] = ew_descriptor[1] = 0.
                ew_descriptor[8] = np.nan
                ew_j2 = fresh and (entry_j2_long[latest] if side == 1 else entry_j2_short[latest])
                ew_flags[1] = ew_j2
                active_entry_parent = entry_parent_record(entry_parents, entry_parent_cursor,
                    parent, ew_descriptor, i, execution_sequences[i], stamp, ew_quote, trend_budget,
                    latest, ew_j2, False, False, False, ew_pair_ok)
                entry_parent_cursor += 1
                entry_wait_cursor = entry_wait_log(entry_wait_events, entry_wait_cursor, i, 8,
                    0, parent, latest, ew_arriving_id, side, ew_descriptor, ew_observation, ew_flags)
                cycles[0] += 1
                ne = reserve_entry(slots, events, ne, stats, 0, side, initial_quantity, i, stamp,
                                   0, parent, cycles[0], mode)
                parent += 1
                stats[13] += 1
            else:
                stats[11] += 1
                events[ne] = np.array([i, 0, 0, 9, side, trend_budget, i, 0, mode, stamp, cycles[0], 0])
                ne += 1

        # ----------------------------------------
        # 待機は行頭で存在した候補だけ進め、忙しい間の新イベントは保存して消費する。
        if entry_kind != 0 and event[i] != 0:
            ew_side = int(event[i])
            ew_ignore = (7 if ew_had_watch else 8 if ew_had_market or slots[0, 0] != 0 else 0)
            ew_accept = (ew_ignore == 0 and trend_budget > 0 and quality[i] and not reset[i]
                and qok and stamp >= start + 300. and stamp < entry_cut and stamp - last_exit >= 30.
                and (ungated_trend or selection == 0 or mode == ew_side)
                and (selection != 1 or slots[1, 0] == 0))
            if ew_accept:
                ew_quote = asks[i] if ew_side == 1 else bids[i]
                entry_watch_start(watch, ew_arriving_id, ew_side, i, execution_sequences[i], stamp,
                    ew_quote, entry_wait_width, entry_advance_width, entry_pullback_width,
                    entry_recovery_width, entry_wait_seconds, entry_kind, ew_observation, ew_pair_ok, latest)
                entry_policy_candidate(policy_state, clock_policy, ew_arriving_id)
                ew_created = True
                policy_flags[4] = fresh and (entry_j2_long[latest] if ew_side == 1 else entry_j2_short[latest])
                entry_snapshot(slots, stats, watch, initial_quantity)
                entry_wait_cursor = entry_wait_log(entry_wait_events, entry_wait_cursor, i, 1,
                    0, 0, latest, ew_arriving_id, ew_side, watch, ew_observation, ew_flags)
                if ew_raw_gap:
                    policy_flags[0] = 1.
                    policy_flags[8] = 1.
                    entry_policy_cursor = entry_policy_log(entry_policy_events, entry_policy_cursor,
                        i, 1, 0, latest, policy_state, ew_observation, policy_flags, watch)
                    if clock_policy == 0:
                        ew_flags[6] = 4.
                        policy_flags[6] = 4.
                        entry_wait_cursor = entry_wait_log(entry_wait_events, entry_wait_cursor, i, 3,
                            3, 0, latest, 0, 0, watch, ew_observation, ew_flags)
                        entry_policy_cursor = entry_policy_log(entry_policy_events, entry_policy_cursor,
                            i, 5, 3, latest, policy_state, ew_observation, policy_flags, watch)
                        watch[0] = watch[1] = 0.
                    elif clock_policy == 3:
                        entry_policy_epoch(policy_state, ew_observation, ew_pair_ok, i, stamp, latest)
                        policy_flags[1] = policy_flags[7] = 1.
                        entry_policy_cursor = entry_policy_log(entry_policy_events, entry_policy_cursor,
                            i, 2, 0, latest, policy_state, ew_observation, policy_flags, watch)
            else:
                entry_wait_cursor = entry_wait_log(entry_wait_events, entry_wait_cursor, i, 2,
                    ew_ignore if ew_ignore else 9, 0, latest, ew_arriving_id, ew_side,
                    watch, ew_observation, ew_flags)
        elif entry_kind == 0 and event[i] != 0 and ew_had_market:
            entry_wait_cursor = entry_wait_log(entry_wait_events, entry_wait_cursor, i, 2,
                8, 0, latest, ew_arriving_id, int(event[i]), watch, ew_observation, ew_flags)
        elif entry_kind == 0 and event[i] != 0 and slots[0, 0] == 0:
            # 即時の不参加診断は旧統計へ追加しない。受理済み予約はstatus1でここを通らない。
            entry_wait_cursor = entry_wait_log(entry_wait_events, entry_wait_cursor, i, 2,
                9, 0, latest, ew_arriving_id, int(event[i]), watch, ew_observation, ew_flags)

        if watch[0] != 0:
            ew_side = int(watch[2])
            ew_quote = asks[i] if ew_side == 1 else bids[i]
            ew_flags[1] = fresh and (entry_j2_long[latest] if ew_side == 1 else entry_j2_short[latest])
            ew_flags[2] = fresh and (wait_opposite_long[latest] if ew_side == 1 else wait_opposite_short[latest])
            ew_phase_changed = False
            ew_fallback_row = False
            policy_flags[4] = ew_flags[1]
            if clock_policy == 3 and policy_state[1] != 0:
                # ----------------------------------------
                # gap後は幾何を動かさず、epoch基準と新源を別に確かめてから局所位相を始める。
                ew_policy_blocked = True
                policy_flags[7] = 1.
                if (policy_state[6] == 0 and ew_pair_ok and i > policy_state[4]
                        and ew_observation[2] > policy_state[5]
                        and ew_observation[7] > policy_state[5]):
                    policy_state[6:9] = np.array([1., i, latest])
                    policy_state[9:19] = ew_observation
                    policy_flags[2] = 1.
                    entry_policy_cursor = entry_policy_log(entry_policy_events, entry_policy_cursor,
                        i, 3, 0, latest, policy_state, ew_observation, policy_flags, watch)
                else:
                    policy_flags[3] = entry_policy_sources(policy_state, ew_observation, ew_pair_ok)
                    if (policy_flags[3] != 0 and quality[i] and not reset[i] and qok
                            and fresh and ew_flags[1] != 0):
                        policy_state[1] = 0.
                        policy_state[19] = i
                        watch[1] = 1.
                        watch[13:17] = np.array([ew_quote, ew_quote, i, stamp])
                        entry_anchor(watch, ew_observation, True, i, latest)
                        policy_flags[5] = 1.
                        entry_policy_cursor = entry_policy_log(entry_policy_events, entry_policy_cursor,
                            i, 4, 0, latest, policy_state, ew_observation, policy_flags, watch)
            if not ew_created and not ew_policy_blocked:
                if ew_side * (ew_quote - watch[13]) > 0:
                    watch[13] = ew_quote
                    entry_wait_cursor = entry_wait_log(entry_wait_events, entry_wait_cursor, i, 4,
                        0, 0, latest, 0, 0, watch, ew_observation, ew_flags)
                if entry_kind >= 6 and watch[1] == 1 and (
                        ew_side * (watch[13] - ew_quote) >= entry_pullback_width - tick*1e-8):
                    watch[1] = 2.
                    watch[14] = ew_quote
                    watch[15] = i
                    watch[16] = stamp
                    entry_anchor(watch, ew_observation, ew_pair_ok, i, latest)
                    ew_phase_changed = True
                    entry_wait_cursor = entry_wait_log(entry_wait_events, entry_wait_cursor, i, 5,
                        0, 0, latest, 0, 0, watch, ew_observation, ew_flags)
                elif (entry_kind == 5 or (entry_kind >= 6 and watch[1] == 2)) and (
                        ew_side * (ew_quote - watch[14]) < 0):
                    watch[14] = ew_quote
                    watch[15] = i
                    watch[16] = stamp
                    entry_anchor(watch, ew_observation, ew_pair_ok, i, latest)
                    ew_phase_changed = True
                    entry_wait_cursor = entry_wait_log(entry_wait_events, entry_wait_cursor, i, 6,
                        0, 0, latest, 0, 0, watch, ew_observation, ew_flags)
                ew_fallback_clock = ((ew_observation[2] >= watch[16]) if clock_policy == 2
                    else (ew_observation[2] > watch[16] and ew_observation[7] > watch[16]))
                if (entry_confirm_bbo and watch[27] == 0 and ew_pair_ok and i > watch[15]
                        and ew_fallback_clock):
                    entry_anchor(watch, ew_observation, True, i, latest)
                    watch[28] = 1.
                    ew_fallback_row = True
                    entry_wait_cursor = entry_wait_log(entry_wait_events, entry_wait_cursor, i, 7,
                        0, 0, latest, 0, 0, watch, ew_observation, ew_flags)
            ew_source_fresh, ew_quotes_progress = entry_bbo_status(watch, ew_observation,
                                                                  ew_pair_ok, tick, peer_tick, clock_policy)
            ew_flags[3] = ew_source_fresh
            ew_flags[4] = ew_quotes_progress
            if entry_kind == 1:
                ew_price_ready = True
            elif entry_kind in (2, 3, 4):
                ew_price_ready = ew_side * (ew_quote - watch[7]) >= entry_advance_width - tick*1e-8
            else:
                ew_price_ready = (entry_kind == 5 or watch[1] == 2) and (
                    ew_side * (ew_quote - watch[14]) >= entry_recovery_width - tick*1e-8)
            ew_flags[5] = ew_price_ready
            ew_trigger = (not ew_created and not ew_phase_changed and not ew_fallback_row and not ew_policy_blocked
                and i > watch[15] and ew_price_ready and quality[i] and not reset[i] and qok
                and fresh and ew_flags[1] != 0 and ew_pair_ok and stamp < entry_cut
                and stamp - last_exit >= 30. and (not entry_confirm_bbo or ew_quotes_progress))
            cap_old_trigger = ew_trigger
            cap_quote = ew_quote
            cap_quote_valid = (qok and np.isfinite(ew_quote) and ew_quote > 0
                               and np.isfinite(watch[7]) and watch[7] > 0)
            cap_adverse = ew_side * (ew_quote - watch[7]) if cap_quote_valid else np.nan
            cap_pass = cap_quote_valid and (not entry_cap_enabled or cap_adverse <= entry_cap_width)
            if entry_cap_enabled:
                ew_trigger = ew_trigger and cap_pass
            cap_selected_trigger = ew_trigger
            cap_blocked = cap_old_trigger and entry_cap_enabled and not cap_pass
            if ew_trigger:
                active_entry_parent = entry_parent_record(entry_parents, entry_parent_cursor,
                    parent, watch, i, execution_sequences[i], stamp, ew_quote, initial_quantity, latest,
                    True, entry_confirm_bbo, ew_source_fresh, ew_quotes_progress, ew_pair_ok)
                entry_parent_cursor += 1
                entry_wait_cursor = entry_wait_log(entry_wait_events, entry_wait_cursor, i, 8,
                    0, parent, latest, 0, 0, watch, ew_observation, ew_flags)
                policy_state[1] = 0.
                policy_flags[8] = 1.
                entry_policy_cursor = entry_policy_log(entry_policy_events, entry_policy_cursor,
                    i, 6, 0, latest, policy_state, ew_observation, policy_flags, watch)
                watch[0] = watch[1] = 0.
                cycles[0] += 1
                ne = reserve_entry(slots, events, ne, stats, 0, ew_side, initial_quantity, i, stamp,
                                   0, parent, cycles[0], mode)
                parent += 1
                stats[13] += 1

        # ----------------------------------------
        # 持続仮説だけ低ERの初回に準備し、旧対照の基準更新を独立した分岐で保持する。
        range_eligible = (range_budget > 0 and selection != 0 and mode == 2
                          and slots[1, 0] == 0 and (selection != 1 or slots[0, 0] == 0)
                          and not closing and stamp < range_entry_cut and price_valid[i] and qok
                          and i > reset_anchor_after and not failure_paused)
        if (range_budget > 0 and (price_valid[i] or (recovery_market and qok))
                and i > reset_anchor_after and not failure_paused):
            if persistent_arm:
                if (not range_armed and slots[1, 0] == 0 and mode == 2 and current_fresh
                        and price_valid[i] and qok and (not recovery_market or peer_ok)
                        and not closing and stamp < range_entry_cut
                        and (selection != 1 or slots[0, 0] == 0)):
                    range_armed = True
                    range_anchor = prices[i]
                    cycles[1] += 1
                    last_anchor_row = i
                    previous_rejected_side = 0
                    events[ne] = np.array([i, 0, 1, 12, 0, range_budget, i, range_anchor,
                                          mode, stamp, cycles[1], width])
                    ne += 1
                    if new_state_enabled:
                        peer_anchor = peer_mid
                        episode += 1
                        prepared_row, prepared_peer_source = i, peer_source
                        own_low = own_high = own_mid
                        own_low_row = own_high_row = i
                        peer_low = peer_high = peer_mid
                        peer_low_source = peer_high_source = peer_source
                        watch_side = 0
                        witness_stop = np.nan
                        require_reprepare = False
                        gate_consumed = False
                        gate_row = -1
                        gate_accepted = gate_side = 0
                        context_decision_row = -1
                        context_accepted = 0
                        planned_entry = planned_liquidation = planned_spread = fee_width = np.nan
                        planned_risk = center_gain = risk_proxy = center_ratio = np.nan
                        if peer_ok:
                            ne = range_event(events, ne, i, 16, 0, range_budget, peer_anchor,
                                             mode, stamp, cycles[1], peer_source)
            else:
                can_prepare = (not require_reprepare or (mode == 2 and current_fresh and qok
                               and peer_ok and slots[1, 0] == 0 and not closing
                               and stamp < range_entry_cut))
                if not np.isfinite(range_anchor) and can_prepare:
                    range_anchor = prices[i]
                    cycles[1] += 1
                    last_anchor_row = i
                    events[ne] = np.array([i, 0, 1, 10, 0, range_budget, i, range_anchor, mode, stamp, cycles[1], 0])
                    ne += 1
                    if new_state_enabled:
                        peer_anchor = peer_mid
                        episode += 1
                        prepared_row, prepared_peer_source = i, peer_source
                        require_reprepare = False
                        if peer_ok:
                            ne = range_event(events, ne, i, 16, 0, range_budget, peer_anchor,
                                             mode, stamp, cycles[1], peer_source)
                # 旧A対照は往復参加開始時だけ再基準化する。
                if activate_anchor and range_eligible and not previous_range_eligible:
                    range_anchor = prices[i]
                    if last_anchor_row != i:
                        cycles[1] += 1
                    last_anchor_row = i
                    previous_rejected_side = 0
                    events[ne] = np.array([i, 0, 1, 11, 0, range_budget, i, range_anchor, mode, stamp, cycles[1], 0])
                    ne += 1
            # 相手格子がまだ無い初回は、最初に公開された有効源で中心を確定する。
            if (new_state_enabled and not require_reprepare and np.isfinite(range_anchor)
                    and not np.isfinite(peer_anchor) and peer_ok):
                peer_anchor = peer_mid
                # 初めての相手中心作成は帰還ではない。この源より新たな公開を待つ。
                prepared_peer_source = peer_source
                ne = range_event(events, ne, i, 16, 0, range_budget, peer_anchor,
                                 mode, stamp, cycles[1], peer_source)

            # ----------------------------------------
            # 極値は実価格が進んだ時だけ更新し、同値へ新しい源時刻を貼り直さない。
            if recovery_market and range_armed and reentry_ready and slots[1, 0] == 0:
                if qok:
                    if not np.isfinite(own_low) or own_mid < own_low:
                        own_low, own_low_row = own_mid, i
                        ne = range_event(events, ne, i, 18, watch_side, range_budget, own_low,
                                         mode, stamp, cycles[1], own_low_row)
                    if not np.isfinite(own_high) or own_mid > own_high:
                        own_high, own_high_row = own_mid, i
                        ne = range_event(events, ne, i, 19, watch_side, range_budget, own_high,
                                         mode, stamp, cycles[1], own_high_row)
                if peer_ok:
                    if not np.isfinite(peer_low) or peer_mid < peer_low:
                        peer_low, peer_low_source = peer_mid, peer_source
                        ne = range_event(events, ne, i, 20, watch_side, range_budget, peer_low,
                                         mode, stamp, cycles[1], peer_low_source)
                    if not np.isfinite(peer_high) or peer_mid > peer_high:
                        peer_high, peer_high_source = peer_mid, peer_source
                        ne = range_event(events, ne, i, 21, watch_side, range_budget, peer_high,
                                         mode, stamp, cycles[1], peer_high_source)
            if slots[1, 0] == 0 and not closing and stamp < range_entry_cut and qok:
                side = 1 if prices[i] <= range_anchor - width else -1 if prices[i] >= range_anchor + width else 0
                allowed = (range_armed and current_fresh) if persistent_arm else (selection == 0 or mode == 2)
                free = selection != 1 or slots[0, 0] == 0
                if new_state_enabled:
                    allowed = allowed and not require_reprepare
                    if center_held:
                        allowed = allowed and reentry_ready
                        if reentry_kind != 1:
                            allowed = allowed and i > center_return_row
                        elif recovery_market:
                            allowed = allowed and i > prepared_row
                if recovery_market:
                    allowed = allowed and peer_ok and not gate_consumed
                    if side and watch_side == 0 and price_valid[i] and allowed and free:
                        watch_side = side
                        ne = range_event(events, ne, i, 17, side, range_budget,
                                         range_anchor - side * width, mode, stamp, cycles[1], prices[i])
                    side = watch_side
                    own_extreme = own_low if side == 1 else own_high
                    own_extreme_row = own_low_row if side == 1 else own_high_row
                    peer_extreme = peer_low if side == 1 else peer_high
                    peer_extreme_source = peer_low_source if side == 1 else peer_high_source
                    self_recovered = (side != 0 and i > own_extreme_row and np.isfinite(own_extreme)
                                      and side * (own_mid - own_extreme) >= recovery_fraction * width - tick * 1e-8)
                    peer_recovered = (side != 0 and peer_source > peer_extreme_source
                                      and np.isfinite(peer_extreme) and peer_ok
                                      and side * (peer_mid - peer_extreme)
                                      >= recovery_fraction * peer_width - peer_tick * 1e-8)
                    confirmed = (recovery_confirmation == 0 or (self_recovered and
                                 (recovery_confirmation == 1 or peer_recovered)))
                    if side and allowed and free and confirmed:
                        # 判断行の予定気配と観測極値だけを使い、次約定へ先取りしない。
                        planned_entry = asks[i] if side == 1 else bids[i]
                        planned_liquidation = bids[i] if side == 1 else asks[i]
                        planned_spread = asks[i] - bids[i]
                        fee_width = 2. * math.floor(range_budget * fee_unit + 1e-8) / (range_budget * value)
                        candidate_failure = own_extreme - side * tick
                        planned_risk = side * (planned_entry - candidate_failure)
                        center_gain = side * (range_anchor - planned_entry) - planned_spread - fee_width
                        risk_proxy = min(planned_risk, width + planned_spread) + fee_width
                        center_ratio = center_gain / risk_proxy if risk_proxy > 0 else np.nan
                        accepted = True
                        if context_kind != 0:
                            accepted = price_observable and (context_kind != 2 or price_mode == 2)
                            context_decision_row, context_accepted = i, int(accepted)
                        if entry_max_risk_widths > 0:
                            accepted = (accepted and planned_risk > 0
                                        and planned_risk <= entry_max_risk_widths * width + tick * 1e-8)
                        if entry_min_center_ratio > 0:
                            accepted = (accepted and planned_risk > 0 and center_gain > 0 and risk_proxy > 0
                                        and side * (planned_liquidation - candidate_failure) > tick * 1e-8
                                        and center_ratio >= entry_min_center_ratio - 1e-12)
                        if gated_entry:
                            gate_consumed = True
                            gate_row, gate_accepted, gate_side = i, int(accepted), side
                            ne = range_event(events, ne, i, 27, side, range_budget, planned_entry,
                                             mode, stamp, cycles[1], 1 if accepted else 0)
                        if accepted:
                            entry_failure_line = candidate_failure
                            entry_center, entry_peer_center = range_anchor, peer_anchor
                            entry_width, entry_peer_width = width, peer_width
                            entry_target_line = (range_anchor + side * center_target_offset * width
                                                 if target_kind != 0 else np.nan)
                            exit_width_flag = exit_witness_flag = exit_target_flag = False
                            witness_stop = entry_failure_line if witness_extreme else np.nan
                            range_parent[:] = np.nan
                            range_parent[0] = parent
                            range_parent[1] = i
                            range_parent[4:23] = np.array([side, range_budget, episode, entry_center,
                                entry_peer_center, width, peer_width, own_extreme, own_extreme_row,
                                entry_failure_line, planned_entry, planned_liquidation, planned_spread,
                                fee_width, planned_risk, center_gain, risk_proxy, center_ratio, entry_target_line])
                            range_parent[29] = peer_source
                            ne = range_event(events, ne, i, 22, side, range_budget, own_extreme,
                                             mode, stamp, cycles[1], peer_extreme_source)
                            ne = reserve_entry(slots, events, ne, stats, 1, side, range_budget, i, stamp,
                                               0, parent, cycles[1], mode)
                            slots[1, 17] = 12
                            parent += 1
                            stats[14] += 1
                            previous_rejected_side = 0
                    elif side and (prices[i] != previous_price or updated >= 0 or side != previous_rejected_side):
                        stats[12] += 1
                        events[ne] = np.array([i, 0, 1, 9, side, range_budget, i, 0,
                                              mode, stamp, cycles[1], 0])
                        ne += 1
                        previous_rejected_side = side
                    elif not side:
                        previous_rejected_side = 0
                elif side:
                    if allowed and free:
                        ne = reserve_entry(slots, events, ne, stats, 1, side, range_budget, i, stamp,
                                           range_anchor - side * width, parent, cycles[1], mode)
                        parent += 1
                        stats[14] += 1
                        previous_rejected_side = 0
                    elif (prices[i] != previous_price or updated >= 0 or side != previous_rejected_side):
                        stats[12] += 1
                        events[ne] = np.array([i, 0, 1, 9, side, range_budget, i, range_anchor - side * width,
                                              mode, stamp, cycles[1], 0])
                        ne += 1
                        previous_rejected_side = side
                else:
                    previous_rejected_side = 0
            previous_price = prices[i]
        previous_range_eligible = range_eligible

        # ----------------------------------------
        # 未返済玉は全行で売bid・買askに清算し、残玉返済料金も控除する。
        trace[i] = growth_snapshot(slots, stats, watch, initial_quantity, int(growth_pending[0]))
        assert stats[2] <= cap and stats[3] <= cap
        watch_state_trace[i, :32] = watch
        cap_has_candidate = watch[3] > 0 and np.isfinite(watch[7])
        if cap_has_candidate:
            cap_side = int(watch[2])
            cap_quote = asks[i] if cap_side == 1 else bids[i]
            cap_quote_valid = (qok and np.isfinite(cap_quote) and cap_quote > 0
                               and np.isfinite(watch[7]) and watch[7] > 0)
            cap_adverse = cap_side * (cap_quote - watch[7]) if cap_quote_valid else np.nan
            cap_pass = cap_quote_valid and (not entry_cap_enabled or cap_adverse <= entry_cap_width)
        entry_cap_state_trace[i] = np.array([entry_cap_enabled,
            entry_cap_multiple if entry_cap_enabled else np.nan, entry_cap_width, watch[0],
            watch[3] if cap_has_candidate else 0., watch[6], watch[7], entry_wait_width,
            watch[2], cap_quote, cap_quote_valid, cap_adverse, cap_pass, cap_old_trigger,
            cap_selected_trigger, cap_blocked, watch[8], stamp,
            slots[0, 3] if slots[0, 0] != 0 else 0., ew_flags[6]])
        if watch[0] != 0 or ew_had_watch:
            watch_state_trace[i, 32:42] = ew_observation
            watch_state_trace[i, 42:] = ew_flags
        else:
            watch_state_trace[i, 32:42] = np.nan
            watch_state_trace[i, 42:] = 0.
            watch_state_trace[i, 42] = -1.
        entry_policy_state_trace[i, :20] = policy_state
        if watch[0] != 0 or ew_had_watch or ew_created:
            policy_flags[6] = ew_flags[6]
            policy_flags[8] = watch[0]
            policy_flags[9] = slots[0, 0]
            entry_policy_state_trace[i, 20:30] = ew_observation
            entry_policy_state_trace[i, 30:] = policy_flags
        else:
            entry_policy_state_trace[i, 20:30] = np.nan
            entry_policy_state_trace[i, 30:] = 0.
            entry_policy_state_trace[i, 39] = slots[0, 0]
        trend_exit_state_trace[i, :3] = np.array([slots[0, 3] if slots[0, 0] != 0 else 0,
                                                slots[0, 0], slots[0, 1] if slots[0, 0] != 0 else 0])
        held = int(slots[0, 2]) if slots[0, 0] == 2 or slots[0, 0] == 3 else 0
        liquidation = (bids[i] if slots[0, 1] == 1 else asks[i]) if held and qok else np.nan
        exit_fee = math.floor(held*fee_unit+1e-8) if held else 0.
        total_fees = slots[0, 6] + exit_fee if held else np.nan
        current_net = (slots[0, 1]*(held*liquidation*value-growth_cash)-total_fees) if held and qok else np.nan
        if held and qok:
            growth_max_excess = max(growth_max_excess, -current_net-growth_r0)
        growth_state_trace[i, :32] = np.array([growth_parent_id, growth_mode, held, growth_pending[0],
            initial_quantity, trend_budget, growth_r0, growth_cash, slots[0, 6] if held else np.nan,
            exit_fee if held else np.nan, total_fees, slots[0, 4] if held else np.nan, liquidation,
            current_net, growth_first_price, growth_first_time, growth_first_row, growth_last_fill,
            trend_initial_line, slots[0, 7] if held else np.nan, trend_trail_line, growth_budget_line,
            trend_protection_active, trend_fee_line, slots[0, 8] if held else np.nan,
            slots[0, 9] if held else np.nan, growth_pending[1] if growth_pending[0] else -1.,
            growth_pending[2] if growth_pending[0] else np.nan,
            growth_row_events[growth_row_event_count-1, 0] if growth_row_event_count else 0.,
            growth_anchor_valid, growth_anchor_row, growth_anchor_grid])
        growth_state_trace[i, 32:42] = growth_planned
        growth_state_trace[i, 42:50] = growth_flags
        growth_state_trace[i, 50:60] = growth_anchor
        growth_state_trace[i, 60:] = ew_observation
        growth_gate_row[0] = growth_parent_id
        growth_gate_row[9] = growth_r0
        growth_gate_state_trace[i] = growth_gate_row
        for event_index in range(growth_row_event_count):
            assert growth_event_cursor < len(growth_events)
            growth_events[growth_event_cursor, :4] = np.array([i,
                growth_row_events[event_index, 0], growth_row_events[event_index, 1],
                growth_row_events[event_index, 2]])
            growth_events[growth_event_cursor, 4:] = growth_state_trace[i]
            growth_event_cursor += 1
        if slots[0, 0] == 2 or slots[0, 0] == 3:
            side = int(slots[0, 1])
            quote = bids[i] if side == 1 else asks[i]
            trend_exit_state_trace[i, 3:] = np.array([slots[0, 4], initial_stop_width, trend_width,
                2. * initial_stop_width, quote if qok else np.nan, qok, slots[0, 7],
                trend_initial_line, trend_trail_line, trend_fee_line, trend_half_line,
                trend_protection_active, trend_protection_floor, trend_stop_before, slots[0, 8],
                trend_line_owner(slots[0, 8], trend_initial_line, trend_trail_line, trend_fee_line,
                                 trend_half_line, trend_protection_active, tick),
                trend_hold_enabled, slots[0, 9], exit_reason[0] if slots[0, 0] == 3 else 0,
                slots[0, 10] if slots[0, 0] == 3 else -1])
        if new_state_enabled:
            phase = 1 if np.isfinite(range_anchor) else 0
            if center_held:
                phase = 6 if reentry_ready else 5
            if watch_side != 0:
                phase = 2
            if slots[1, 0] == 1:
                phase = 3
            elif slots[1, 0] == 2 or slots[1, 0] == 3:
                phase = 4
            range_state_trace[i] = np.array([phase, range_anchor, peer_anchor, width, peer_width,
                                             episode, watch_side, own_low, own_low_row, own_high,
                                             own_high_row, peer_low, peer_low_source, peer_high,
                                             peer_high_source, center_held, center_self_seen,
                                             center_peer_seen, last_range_exit_row,
                                             last_range_exit_peer_source, center_return_row,
                                             prepared_row, prepared_peer_source, witness_stop, range_armed])
        risk_state_trace[i] = np.array([gate_consumed, gate_row, gate_accepted, gate_side,
            planned_entry, planned_liquidation, planned_spread, fee_width, planned_risk, center_gain,
            risk_proxy, center_ratio, entry_failure_line, entry_target_line, entry_center,
            entry_peer_center, entry_width, entry_peer_width, exit_width_flag, exit_witness_flag,
            exit_target_flag, failure_paused, failure_center, failure_peer_center, failure_width,
            failure_peer_width, failure_exit_row, failure_exit_time, failure_exit_own_source,
            failure_exit_peer_source, failure_false_seen, failure_false_grid, failure_false_own_source,
            failure_false_peer_source, failure_release_row, failure_self_seen, failure_peer_seen,
            raw_observable, raw_range, raw_oldest_time])
        if latest >= 0:
            price_source_trace[i] = np.array([price_lane, latest, price_own_indices[latest],
                price_peer_indices[latest], price_own_sequences[latest], price_peer_sequences[latest],
                published_own_source, published_peer_source, price_own_times[latest],
                price_peer_times[latest], own_source_time, peer_source_time, price_own_valid[latest],
                price_peer_valid[latest], price_observable, mode, context_kind, context_decision_row,
                context_accepted, current_fresh, peer_ok, price_mode])
        else:
            price_source_trace[i] = np.array([price_lane, -1, -1, -1, -1, -1, -1, -1,
                np.nan, np.nan, np.nan, np.nan, 0, 0, 0, 0, context_kind,
                context_decision_row, context_accepted, 0, 0, 0])
        for source in range(2):
            equity = cash[source]
            if slots[source, 0] == 2 or slots[source, 0] == 3:
                side = int(slots[source, 1])
                quantity = int(slots[source, 2])
                liquidation = last_bid if side == 1 else last_ask
                equity += side * quantity * liquidation * value - math.floor(quantity * fee_unit + 1e-8)
            source_curve[i, source] = equity
        curve[i] = source_curve[i, 0] + source_curve[i, 1]
    if n:
        stats[4] = trace[-1, 0]
        stats[5] = trace[-1, 1]
        stats[6] = trace[-1, 4]
        stats[7] = trace[-1, 5]
    stats[15] = cash[0] + cash[1]
    return (orders[:no].copy(), trades[:nt].copy(), curve, source_curve, trace,
            events[:ne].copy(), stats, slots, range_state_trace, risk_state_trace,
            range_parents[:nrp].copy(), price_source_trace, loss_log[:loss_cursor].copy(),
            trend_exit_state_trace, trend_parents[:trend_parent_cursor].copy(), watch_state_trace,
            entry_parents[:entry_parent_cursor].copy(), entry_wait_events[:entry_wait_cursor].copy(),
            entry_policy_state_trace, entry_policy_events[:entry_policy_cursor].copy(), entry_cap_state_trace,
            growth_state_trace, growth_events[:growth_event_cursor].copy(),
            growth_cohorts[:growth_cohort_cursor].copy(), growth_parents[:growth_parent_cursor].copy(),
            growth_gate_state_trace)


def entry_cap_parents(parents: np.ndarray, enabled: bool, multiple: float) -> np.ndarray:
    """
    機能: 旧入口親の実際に記録された候補・判断・約定から上限超過を別診断する。
    引数: parents(ndarray[float]、45列)、enabled(bool)、multiple(float)。
    返り値: ndarray[float]は21列。未約定のfillは不明のままで、金融判断には使わない。
    """
    result = np.full((len(parents), 21), np.nan)
    for i, parent in enumerate(parents):
        side, width = parent[7], parent[9]
        candidate, trigger, fill = parent[5], parent[31], parent[40]
        cap_width = multiple * width if enabled else np.nan
        trigger_distance = side * (trigger - candidate)
        trigger_inside = np.isfinite(trigger_distance) and (not enabled or trigger_distance <= cap_width)
        fill_distance = side * (fill - candidate) if np.isfinite(fill) else np.nan
        fill_excess = max(0., fill_distance - cap_width) if enabled and np.isfinite(fill_distance) else np.nan
        result[i] = [parent[0], parent[1], parent[4], side, parent[8], candidate, width,
            enabled, multiple if enabled else np.nan, cap_width, parent[28], parent[30],
            trigger, trigger_distance, trigger_inside, parent[37], parent[39], fill,
            fill_distance, fill_excess, parent[41]]
    return result


def execute(record, signal, config, finish=True):
    """
    機能: 商品倍率と枚数を設定して二源共通エンジンを実行する。
    引数: record (dict) は原板、signal (dict) は過去状態、config (dict)、finish (bool)。
    返り値: dict は注文・源別決済親・全原板清算時価・予約台帳・列定義。
    finish=Trueでは既知の場末まである完全入力の最終全返済を要求する。
    人工又は未来切断のprefixはfinish=Falseで端点の強制清算を作らない。
    """
    symbol = record['symbol']
    scale, value, fee_unit, cap = (1, 1000.0, 41.8, 10) if symbol == 'TOPIX' else (2, 10.0, 11.0, 20)
    trend_budget = int(config['trend_budget']) * scale
    range_budget = int(config['range_budget']) * scale
    selection = {'fixed': 0, 'regime': 1, 'gated_fixed': 2}[config['selection']]
    assert 0 <= trend_budget <= cap and 0 <= range_budget <= cap
    declared_initial = config.get('trend_initial_quantity')
    initial_quantity = trend_budget if declared_initial is None else int(declared_initial)
    assert declared_initial is None or declared_initial in (1, 2, 4), '初回は両商品で絶対1/2/4枚です'
    assert 0 <= initial_quantity <= trend_budget
    growth_mode = int(config.get('trend_growth_mode', 0))
    growth_cushion = int(config.get('trend_growth_cushion_ticks', growth_mode))
    assert growth_mode in (0, 1, 2) and growth_cushion == growth_mode
    cushion_basis_name = config.get('trend_growth_cushion_basis', 'ticks')
    assert cushion_basis_name in ('ticks', 'initial_width')
    growth_cushion_basis = 1 if cushion_basis_name == 'initial_width' else 0
    growth_cushion_initial_multiple = float(config.get('trend_growth_cushion_initial_multiple', 0.))
    growth_preserve_stop = config.get('trend_growth_preserve_stop', False)
    assert isinstance(growth_preserve_stop, bool)
    assert math.isfinite(growth_cushion_initial_multiple)
    if growth_cushion_basis == 1:
        assert growth_mode != 0 and growth_cushion_initial_multiple in (.5, 1., 2.)
    else:
        assert growth_cushion_initial_multiple == 0. and not growth_preserve_stop
    assert growth_mode == 0 or initial_quantity > 0 and range_budget == 0
    if selection != 1:
        assert trend_budget + range_budget <= cap
    reverse_sources = config.get('reverse_sources', 'none')
    assert reverse_sources in ('none', 'trend', 'range', 'both')
    persistent_arm = bool(config.get('persistent_arm', False))
    assert not persistent_arm or float(config.get('break_widths', 3)) >= 3
    assert config.get('arm_direction_kind', 'common') in ('common', 'trend300')
    profit_mode = config.get('range_profit_mode', 'target')
    assert profit_mode in ('target', 'trail')
    entry_kind = config.get('range_entry_kind', 'limit')
    assert entry_kind in ('limit', 'recovery_market')
    confirmation = config.get('recovery_confirmation', 'none')
    assert confirmation in ('none', 'self', 'both')
    reentry_kind = config.get('range_reentry_kind', 'legacy')
    assert reentry_kind in ('legacy', 'keep', 'return_self', 'return_both')
    stop_kind = config.get('range_stop_kind', 'width')
    assert stop_kind in ('width', 'witness_extreme', 'width_or_witness')
    assert stop_kind == 'width' or entry_kind == 'recovery_market'
    target_kind = config.get('range_target_kind', 'widths')
    assert target_kind in ('widths', 'center', 'center_plus')
    target_offset = float(config.get('range_center_target_offset', 0))
    assert target_offset >= 0
    assert target_kind != 'center' or target_offset == 0
    failure_kind = config.get('range_failure_reentry_kind', 'legacy')
    assert failure_kind in ('legacy', 'return_self', 'return_both', 'prepare_reset')
    assert failure_kind == 'legacy' or stop_kind == 'width_or_witness'
    max_risk = float(config.get('range_entry_max_risk_widths', 0))
    min_ratio = float(config.get('range_entry_min_center_ratio', 0))
    price_lane = config.get('price_lane', 'I0')
    context = config.get('range_entry_context', 'legacy')
    assert price_lane in ('I0', 'I1', 'I2', 'I3')
    assert context in ('legacy', 'observable', 'confirmed_range')
    assert context == 'legacy' or entry_kind == 'recovery_market'
    assert max_risk >= 0 and min_ratio >= 0
    assert not (max_risk > 0 or min_ratio > 0 or target_kind != 'widths') or entry_kind == 'recovery_market'
    assert target_kind == 'widths' or profit_mode == 'target'
    assert config.get('watch_clear_common', 'any') in ('any', 'adverse')
    assert config.get('center_after', 'profit') in ('profit', 'all')
    size = len(signal['grid'])
    default_valid = np.ones(size, dtype=bool)
    default_direction = np.zeros(size, dtype=np.int8)
    default_reverse = np.zeros(size, dtype=bool)
    if failure_kind != 'legacy':
        for field in ('own_source', 'own_source_time', 'peer_source_time', 'raw_range_valid',
                      'raw_range_eligible', 'raw_oldest_time'):
            assert field in signal, f'失敗後の新観測確認には{field}が必要です'
    if context != 'legacy':
        assert 'price_observable' in signal, '現在の新規資格には独立価格の可観測性が必要です'
    loss_name = config.get('loss_reentry_kind', 'none')
    loss_trigger_name = config.get('loss_reentry_trigger', 'any_net_negative')
    assert loss_name in ('none', 'ban_opposite', 'fresh_quotes', 'fresh_price_quotes', 'sustained_price_quotes')
    assert loss_trigger_name in ('any_net_negative', 'stop_net_negative')
    loss_data = signal.get('loss_observations', np.full((size, 22), np.nan))
    assert loss_data.shape == (size, 22)
    loss_seconds = float(config.get('loss_confirm_seconds', 10.))
    assert loss_seconds >= 0
    initial_stop_width = float(signal.get('trend_initial_stop_width', signal['trend_width']))
    protection_mode = int(config.get('trend_protection_mode', 0))
    hold_seconds = float(config.get('trend_hold_seconds', 1800.))
    assert np.isfinite(initial_stop_width) and initial_stop_width >= 2. * record['tick']
    assert protection_mode in (0, 1, 2)
    assert np.isfinite(hold_seconds) and hold_seconds >= 0
    wait_kind = int(config.get('entry_wait_kind', 0))
    clock_policy_name = config.get('entry_clock_policy', 'C0')
    assert clock_policy_name in ('C0', 'C1', 'C2', 'C3'), '価格時計政策はC0からC3で指定します'
    clock_policy = int(clock_policy_name[1])
    assert wait_kind != 0 or clock_policy == 0, '即時対照には時計政策を追加しません'
    wait_seconds = float(config.get('entry_wait_seconds', 300.))
    assert wait_kind in range(9) and np.isfinite(wait_seconds) and wait_seconds > 0
    confirm_bbo = bool(config.get('entry_bbo_confirm', wait_kind not in (0, 2)))
    assert confirm_bbo == (wait_kind not in (0, 2))
    if wait_kind != 0:
        for field in ('entry_wait_width', 'entry_advance_width', 'entry_pullback_width',
                      'entry_recovery_width', 'entry_j2_long', 'entry_j2_short',
                      'wait_opposite_long', 'wait_opposite_short', 'entry_peer_bbo'):
            assert field in signal, '候補後待機に必要な過去素材: ' + field
        peer_tick = float(signal.get('peer_tick', np.nan))
        assert np.isfinite(peer_tick) and peer_tick > 0, '待機確認には相手の正の呼値が必要です'
        for field in ('entry_j2_long', 'entry_j2_short', 'wait_opposite_long', 'wait_opposite_short'):
            assert isinstance(signal[field], np.ndarray), '待機確認素材は配列で指定します: ' + field
            assert signal[field].shape == (size,) and signal[field].dtype == np.bool_, '待機確認素材の型又は長さが違います: ' + field
    wait_width = float(signal.get('entry_wait_width', 2. * record['tick']))
    advance_width = float(signal.get('entry_advance_width', 0.))
    pullback_width = float(signal.get('entry_pullback_width', 0.))
    recovery_width = float(signal.get('entry_recovery_width', 0.))
    assert np.isfinite(wait_width) and wait_width >= 2. * record['tick']
    assert all(np.isfinite(number) and number >= 0 for number in (advance_width, pullback_width, recovery_width))
    entry_peer = signal.get('entry_peer_bbo', np.full((size, 6), np.nan))
    assert entry_peer.shape == (size, 6)
    cap_multiple = config.get('entry_price_cap_multiple')
    cap_enabled = cap_multiple is not None
    cap_number = float(cap_multiple) if cap_enabled else 0.
    assert not cap_enabled or (wait_kind != 0 and np.isfinite(cap_number) and cap_number >= 0), '即時対照と不正幅には判断上限を追加しません'
    output = simulate(record['time_s'], record['price'], record['bid'], record['ask'],
                      record['price_valid'], record['quote_valid'], signal['quality'], signal['reset'],
                      signal['event'], signal['mapped'], signal['grid'], signal['mode'], record['tick'],
                      record['start'], record['limit'], signal['trend_width'], trend_budget, range_budget,
                      selection, bool(config['cancel_pending']), bool(config['exit_opposite_range']),
                      value, fee_unit, cap, float(config.get('width_ticks', 8)),
                      float(config.get('stop_widths', 1)), float(config.get('target_widths', 3)),
                      hold_seconds,
                      bool(config.get('improve_limit', False)), bool(config.get('activate_anchor', False)),
                      persistent_arm, bool(config.get('ungated_trend', False)),
                      signal.get('current_valid', default_valid),
                      signal.get('arm_trend300' if config.get('arm_direction_kind', 'common') == 'trend300'
                                 else 'arm_common', default_direction),
                      signal.get('reverse_long', default_reverse), signal.get('reverse_short', default_reverse),
                      reverse_sources in ('trend', 'both'), reverse_sources in ('range', 'both'),
                      float(signal.get('range_width', 0)), float(config.get('break_widths', 3)),
                      profit_mode == 'trail', float(config.get('profit_activate_widths', 1)),
                      float(config.get('profit_trail_widths', .5)), entry_kind == 'recovery_market',
                      {'none': 0, 'self': 1, 'both': 2}[confirmation],
                      float(config.get('recovery_fraction', .25)),
                      config.get('watch_clear_common', 'any') == 'adverse',
                      stop_kind in ('witness_extreme', 'width_or_witness'),
                      {'legacy': 0, 'keep': 1, 'return_self': 2, 'return_both': 3}[reentry_kind],
                      float(config.get('center_fraction', .25)), config.get('center_after', 'profit') == 'all',
                      bool(config.get('center_release', False)),
                      signal.get('peer_mid', np.full(size, np.nan)),
                      signal.get('peer_source', np.full(size, -1, dtype=np.int64)),
                      signal.get('peer_valid', np.zeros(size, dtype=bool)),
                      float(signal.get('peer_width', 0)), float(signal.get('peer_tick', 0)),
                      max_risk, min_ratio, stop_kind == 'width_or_witness',
                      {'widths': 0, 'center': 1, 'center_plus': 2}[target_kind], target_offset,
                      {'legacy': 0, 'return_self': 1, 'return_both': 2, 'prepare_reset': 3}[failure_kind],
                      float(config.get('failure_center_fraction', .25)),
                      signal.get('own_source', np.full(size, -1, dtype=np.int64)),
                      signal.get('own_source_time', np.full(size, np.nan)),
                      signal.get('peer_source_time', np.full(size, np.nan)),
                      signal.get('raw_range_valid', np.zeros(size, dtype=bool)),
                      signal.get('raw_range_eligible', np.zeros(size, dtype=bool)),
                      signal.get('raw_oldest_time', np.full(size, np.nan)),
                      {'I0': 0, 'I1': 1, 'I2': 2, 'I3': 3}[price_lane],
                      {'legacy': 0, 'observable': 1, 'confirmed_range': 2}[context],
                      signal.get('price_observable', np.zeros(size, dtype=bool)),
                      signal.get('price_own_index', np.full(size, -1, dtype=np.int64)),
                      signal.get('price_peer_index', np.full(size, -1, dtype=np.int64)),
                      signal.get('price_own_raw_seq', np.full(size, -1, dtype=np.int64)),
                      signal.get('price_peer_raw_seq', np.full(size, -1, dtype=np.int64)),
                      signal.get('price_own_time', np.full(size, np.nan)),
                      signal.get('price_peer_time', np.full(size, np.nan)),
                      signal.get('price_own_valid', np.zeros(size, dtype=bool)),
                      signal.get('price_peer_valid', np.zeros(size, dtype=bool)),
                      signal.get('price_mode', signal['mode']), loss_data,
                      record.get('seq', np.arange(len(record['time_s']), dtype=np.int64)),
                      signal.get('execution_lp_index', np.full(len(record['time_s']), -1, np.int64)),
                      {'none': 0, 'ban_opposite': 1, 'fresh_quotes': 2, 'fresh_price_quotes': 3,
                       'sustained_price_quotes': 4}[loss_name],
                      {'any_net_negative': 0, 'stop_net_negative': 1}[loss_trigger_name], loss_seconds,
                      initial_stop_width, protection_mode, wait_kind, wait_seconds, wait_width,
                      advance_width, pullback_width, recovery_width, confirm_bbo,
                      signal.get('entry_j2_long', default_reverse), signal.get('entry_j2_short', default_reverse),
                      signal.get('wait_opposite_long', default_reverse), signal.get('wait_opposite_short', default_reverse),
                      entry_peer, clock_policy, cap_enabled, cap_number,
                      initial_quantity, growth_mode, growth_cushion, growth_cushion_basis,
                      growth_cushion_initial_multiple, growth_preserve_stop)
    names = ('orders', 'trades', 'curve', 'source_curve', 'target_trace', 'events', 'stats', 'slots',
              'range_state_trace', 'risk_state_trace', 'range_parent_diagnostics', 'price_source_trace', 'loss_reentry_events',
              'trend_exit_state_trace', 'trend_parent_diagnostics', 'watch_state_trace',
              'entry_parent_diagnostics', 'entry_wait_events', 'entry_policy_state_trace', 'entry_policy_events',
              'entry_cap_state_trace', 'growth_state_trace', 'growth_events',
              'growth_cohorts', 'growth_parent_diagnostics', 'growth_gate_state_trace')
    answer = dict(zip(names, output))
    answer['entry_cap_parent_diagnostics'] = entry_cap_parents(answer['entry_parent_diagnostics'], cap_enabled, cap_number)
    answer.update(order_columns=ORDER_COLUMNS, trade_columns=TRADE_COLUMNS, trace_columns=TRACE_COLUMNS,
                  event_columns=EVENT_COLUMNS, stat_columns=STAT_COLUMNS, slot_columns=SLOT_COLUMNS,
                  reasons=REASONS, event_codes=EVENT_CODES, range_state_columns=RANGE_STATE_COLUMNS,
                  risk_state_columns=RISK_STATE_COLUMNS, range_parent_columns=RANGE_PARENT_COLUMNS,
                  price_source_columns=PRICE_SOURCE_COLUMNS, loss_event_columns=LOSS_EVENT_COLUMNS,
                  loss_event_codes=LOSS_EVENT_CODES, trend_exit_state_columns=TREND_EXIT_STATE_COLUMNS,
                  trend_parent_columns=TREND_PARENT_COLUMNS, trend_line_owners=TREND_LINE_OWNERS,
                  watch_state_columns=WATCH_STATE_COLUMNS, entry_parent_columns=ENTRY_PARENT_COLUMNS,
                  entry_wait_event_columns=ENTRY_WAIT_EVENT_COLUMNS, entry_wait_event_codes=ENTRY_WAIT_EVENT_CODES,
                  entry_wait_reasons=ENTRY_WAIT_REASONS,
                  entry_policy_state_columns=ENTRY_POLICY_STATE_COLUMNS,
                  entry_policy_event_columns=ENTRY_POLICY_EVENT_COLUMNS,
                  entry_policy_event_codes=ENTRY_POLICY_EVENT_CODES,
                  entry_cap_state_columns=ENTRY_CAP_STATE_COLUMNS,
                  entry_cap_parent_columns=ENTRY_CAP_PARENT_COLUMNS,
                  growth_state_columns=GROWTH_STATE_COLUMNS,
                  growth_event_columns=GROWTH_EVENT_COLUMNS, growth_event_codes=GROWTH_EVENT_CODES,
                  growth_cohort_columns=GROWTH_COHORT_COLUMNS, growth_parent_columns=GROWTH_PARENT_COLUMNS,
                  growth_gate_state_columns=GROWTH_GATE_STATE_COLUMNS)
    if finish:
        assert len(record['time_s']) and record['time_s'][-1] >= record['limit'], '完結入力には既知の場末までの原板が必要です'
        assert np.all(answer['slots'][:, 0] == 0), '場末の未返済又は未約定予約が残りました'
        assert answer['watch_state_trace'][-1, 0] == 0, '場末の新規待機が残りました'
        assert answer['entry_policy_state_trace'][-1, 1] == 0, '場末の政策休止が残りました'
        assert abs(answer['curve'][-1] - answer['stats'][15]) < 1e-4
    return answer
