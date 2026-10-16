"""固定価格の表示量と最終価格方向代理から、独立C/Rエピソードを因果的に進める。"""

from pathlib import Path
import os

import numba
from numba import njit
import numpy as np


HERE = Path(__file__).resolve().parent
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'jit')
numba.config.CACHE_DIR = str(HERE / 'jit')
SIDES = (1, -1)
EVENT_COLUMNS = ['row', 'intent', 'direction', 'code', 'reason', 'phase', 'anchor_row',
    'prepared_row', 'recovery_row', 'moved_row', 'ready_row', 'first_price_move_row',
    'anchor_time', 'bid0', 'ask0', 'fixed_price', 'initial_quantity', 'support_price',
    'initial_support_quantity', 'activity_decrease', 'activity_volume', 'post_volume']
EVENT_CODES = {1: '基準作成', 2: '初期活動準備', 3: '回復確認', 4: '価格移動段階通過',
               5: '移動後確認', 6: '表示支持不足', 7: '表示支持回復', 8: '破棄', 9: '価格移動だけを観測'}
RESET_REASONS = {1: '情報不明又はreset', 2: '期限又は原行寿命', 3: '固定価格の遠端外',
                 4: '観測した価格移動が破れた', 5: 'Rの元方向への到達'}


@njit(cache=True)
def fixed_quantity(prices, quantities, fixed_price, bid_side, complete):
    """
    機能: 完全10段の固定価格数量を返し、競争的空領域だけ既知0とする。
    引数: prices/quantities(ndarray[float]10列)、fixed_price(float)、bid_side/complete(bool)。
    返り値: float。遠端外又は不完全板はNaN。未表示の範囲内価格は0。
    """
    if not complete or len(prices) != 10 or len(quantities) != 10 or not np.isfinite(fixed_price):
        return np.nan
    for j in range(10):
        if not np.isfinite(prices[j]) or not np.isfinite(quantities[j]) or prices[j] <= 0 or quantities[j] < 0:
            return np.nan
        if j and ((bid_side and prices[j] >= prices[j-1]) or (not bid_side and prices[j] <= prices[j-1])):
            return np.nan
    if bid_side:
        if fixed_price > prices[0]:
            return 0.
        if fixed_price < prices[-1]:
            return np.nan
    else:
        if fixed_price < prices[0]:
            return 0.
        if fixed_price > prices[-1]:
            return np.nan
    for j in range(10):
        if prices[j] == fixed_price:
            return quantities[j]
    return 0.


def volume_direction_proxy(raw: dict) -> np.ndarray:
    """
    機能: 正usable差と同期した最終価格を、直前正常BBOへ一意に分類する。
    引数: raw(dict)は103の全原行配列。方向別真の約定量を入力へ要求しない。
    返り値: ndarray[int8]。+1/-1/0。曖昧・非同期・不明を方向推測で補完しない。
    """
    n = len(raw['price_time_s'])
    output = np.zeros(n, np.int8)
    if n < 2:
        return output
    qualified = row_qualified(raw)
    bid, ask = raw['bid'][:-1], raw['ask'][:-1]
    last = raw['last'][1:]
    good = (qualified[1:] & qualified[:-1] & raw['volume_delta_usable'][1:] & np.isfinite(raw['volume_delta'][1:])
        & (raw['volume_delta'][1:] > 0)
        & (raw['volume_time_s'][1:] == raw['price_time_s'][1:])
        & np.isfinite(last) & (last > 0) & np.isfinite(bid) & np.isfinite(ask)
        & (bid > 0) & (ask > bid) & raw['best_price_valid'][:-1])
    output[1:][good & (last >= ask)] = 1
    output[1:][good & (last <= bid)] = -1
    return output


def row_qualified(raw: dict) -> np.ndarray:
    """
    機能: 全方式で共通の価格・LP・10段・出来高隣接差資格を算定する。
    引数: raw(dict)は103入力。欠測又はresetはprice-onlyでも同じく不明とする。
    返り値: ndarray[bool]。未知を出来高0又は数量0へ置換しない。
    """
    time, last, bid, ask = (raw[name] for name in ('price_time_s', 'last', 'bid', 'ask'))
    good = (raw['price_time_valid'] & raw['in_session'] & raw['price_row_valid']
        & raw['best_price_valid'] & raw['best_quantity_valid'] & raw['depth_valid'] & raw['depth_transition_valid']
        & raw['volume_delta_usable'] & np.isfinite(raw['volume_delta']) & (raw['volume_delta'] >= 0)
        & np.isfinite(time) & np.isfinite(last) & (last > 0)
        & np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask > bid)
        & np.isfinite(raw['bid_qty']) & np.isfinite(raw['ask_qty'])
        & (raw['bid_qty'] > 0) & (raw['ask_qty'] > 0))
    for name in ('price_reset_reason', 'depth_reset_reason', 'lp_reset_reason', 'volume_reset_reason'):
        good &= raw[name] == 0
    if len(time) > 1:
        good[1:] &= (np.isfinite(time[:-1]) & (time[1:] >= time[:-1])
                     & (raw['raw_seq'][1:] == raw['raw_seq'][:-1] + 1))
    return good


@njit(cache=True)
def log_event(log, row, intent, family, code, reason, phase, indexes, values):
    """
    機能: 段階の原行と固定分母を、その時点のcopyとして追加する。
    引数: log(list[ndarray])、row/intent/family/code/reason/phase(int)、indexes/values(ndarray)。
    返り値: None。後の段階や損益から過去記録を上書きしない。
    """
    out = np.empty(22, np.float64)
    out[:6] = np.array([row, intent, intent if family == 1 else -intent, code, reason, phase], np.float64)
    out[6:12] = indexes
    out[12:22] = values[:10]
    log.append(out)


@njit(cache=True)
def seed(row, intent, bid, ask, bidq, askq, stamp, indexes, values):
    """
    機能: 正常現在原行を新基準へ固定し、同じ行では活動を進めない。
    引数: row/intent(int)、bid/ask/bidq/askq/stamp(float)、indexes/values(ndarray)。
    返り値: None。開始時の両数量を後から変更しない。
    """
    indexes[:] = -1
    indexes[0] = row
    values[:] = 0.
    values[0:3] = np.array([stamp, bid, ask])
    values[3] = ask if intent == 1 else bid
    values[4] = askq if intent == 1 else bidq
    values[5] = bid if intent == 1 else ask
    values[6] = bidq if intent == 1 else askq
    values[10] = values[4]


@njit(cache=True)
def simulate(times, bids, asks, bidq, askq, last, delta, direction, good,
             bid_prices, bid_quantities, ask_prices, ask_quantities, raw_seq,
             family, strength, use_supply, use_volume, tick, max_seconds, max_rows):
    """
    機能: C又はRの二意図を独立基準・寿命で原行順に進める。
    引数: 原行数値/資格配列(ndarray)、family/max_rows(int)、幅強度等(float)、部品flag(bool)。
    返り値: tuple[ndarray,ndarray,ndarray,list]。準備完了、基準seq、段階、段階ログ。
    """
    n = len(times)
    ready = np.zeros((n, 2), np.bool_)
    anchors = np.full((n, 2), -1, np.int64)
    stages = np.full((n, 2), -1, np.int8)
    active = np.zeros(2, np.bool_)
    phase = np.zeros(2, np.int8)
    was_ready = np.zeros(2, np.bool_)
    indexes = np.full((2, 6), -1, np.int64)
    values = np.zeros((2, 11), np.float64)
    log = [np.zeros(22, np.float64)]
    epsilon = tick * 1e-8
    for row in range(n):
        for j in range(2):
            intent = 1 if j == 0 else -1
            out_side = intent if family == 1 else -intent
            column = 0 if out_side == 1 else 1
            ix, v = indexes[j], values[j]
            if not good[row]:
                if active[j]:
                    log_event(log, row, intent, family, 8, 1, phase[j], ix, v)
                active[j] = was_ready[j] = False
                continue
            if not active[j]:
                seed(row, intent, bids[row], asks[row], bidq[row], askq[row], times[row], ix, v)
                phase[j], active[j] = 0, True
                log_event(log, row, intent, family, 1, 0, 0, ix, v)
            else:
                reset_reason = 0
                if times[row] - v[0] >= max_seconds or row - ix[0] >= max_rows:
                    reset_reason = 2
                if intent == 1:
                    opposite_q = fixed_quantity(ask_prices[row], ask_quantities[row], v[3], False, True)
                    support_p = v[3] if family == 1 else v[5]
                    support_q = fixed_quantity(bid_prices[row], bid_quantities[row], support_p, True, True) if family == 1 else fixed_quantity(ask_prices[row], ask_quantities[row], support_p, False, True)
                else:
                    opposite_q = fixed_quantity(bid_prices[row], bid_quantities[row], v[3], True, True)
                    support_p = v[3] if family == 1 else v[5]
                    support_q = fixed_quantity(ask_prices[row], ask_quantities[row], support_p, False, True) if family == 1 else fixed_quantity(bid_prices[row], bid_quantities[row], support_p, True, True)
                if not np.isfinite(opposite_q) or not np.isfinite(support_q):
                    reset_reason = 3
                if family == 2 and ((intent == 1 and bids[row] >= v[3] - epsilon)
                                    or (intent == -1 and asks[row] <= v[3] + epsilon)):
                    reset_reason = 5
                if family == 1:
                    moved = (bids[row] >= v[3] - epsilon and asks[row] >= v[2] + tick - epsilon) if intent == 1 else (asks[row] <= v[3] + epsilon and bids[row] <= v[1] - tick + epsilon)
                else:
                    moved = (bids[row] <= v[1] - tick + epsilon and asks[row] <= v[2] - tick + epsilon) if intent == 1 else (bids[row] >= v[1] + tick - epsilon and asks[row] >= v[2] + tick - epsilon)
                if ix[5] >= 0 and not moved:
                    reset_reason = 4
                if reset_reason:
                    log_event(log, row, intent, family, 8, reset_reason, phase[j], ix, v)
                    seed(row, intent, bids[row], asks[row], bidq[row], askq[row], times[row], ix, v)
                    phase[j], was_ready[j] = 0, False
                    log_event(log, row, intent, family, 1, 0, 0, ix, v)
                elif phase[j] == 0:
                    decrease = max(0., v[10] - opposite_q)
                    in_band = abs(last[row] - v[3]) <= tick + epsilon
                    aligned = delta[row] > 0 and direction[row] == intent and in_band
                    if use_supply and use_volume:
                        if decrease > 0 and aligned:
                            v[7] += decrease
                            v[8] += delta[row]
                    elif use_supply:
                        v[7] += decrease
                    elif use_volume and aligned:
                        v[8] += delta[row]
                    v[10] = opposite_q
                    if (not use_supply or v[7] >= .5 * v[4]) and (not use_volume or v[8] >= strength * v[4]):
                        ix[1], phase[j] = row, 1
                        log_event(log, row, intent, family, 2, 0, 1, ix, v)
                        if moved and ix[5] < 0:
                            ix[5] = row
                            log_event(log, row, intent, family, 9, 0, phase[j], ix, v)
                elif family == 2 and phase[j] == 1:
                    recovered = opposite_q > v[10] and opposite_q >= .8 * v[4]
                    v[10] = opposite_q
                    if not use_supply or recovered:
                        ix[2], phase[j] = row, 2
                        log_event(log, row, intent, family, 3, 0, 2, ix, v)
                        if moved and ix[5] < 0:
                            ix[5] = row
                            log_event(log, row, intent, family, 9, 0, phase[j], ix, v)
                elif (family == 1 and phase[j] == 1) or (family == 2 and phase[j] == 2):
                    if moved:
                        if ix[5] < 0:
                            ix[5] = row
                            log_event(log, row, intent, family, 9, 0, phase[j], ix, v)
                        denominator = v[4] if family == 1 else v[6]
                        if not use_supply or support_q >= .5 * denominator:
                            ix[3], v[9] = row, 0.
                            phase[j] = 2 if family == 1 else 3
                            log_event(log, row, intent, family, 4, 0, phase[j], ix, v)
                else:
                    support_denominator = v[4] if family == 1 else v[6]
                    supported = not use_supply or support_q >= .5 * support_denominator
                    band_origin = v[3] if family == 1 else v[5]
                    progress = out_side * (last[row] - band_origin)
                    if use_volume and delta[row] > 0 and direction[row] == out_side and progress >= -epsilon and progress <= 2. * tick + epsilon:
                        v[9] += delta[row]
                    completed = supported and (not use_volume or v[9] >= strength * v[4])
                    if completed:
                        if ix[4] < 0:
                            ix[4] = row
                            phase[j] = 3 if family == 1 else 4
                            log_event(log, row, intent, family, 5, 0, phase[j], ix, v)
                        elif not was_ready[j]:
                            log_event(log, row, intent, family, 7, 0, phase[j], ix, v)
                    elif was_ready[j]:
                        log_event(log, row, intent, family, 6, 0, phase[j], ix, v)
                    was_ready[j] = completed
            if active[j]:
                anchors[row, column] = raw_seq[ix[0]]
                stages[row, column] = phase[j]
                ready[row, column] = was_ready[j]
    return ready, anchors, stages, log[1:]


def run(raw: dict, item: dict, config: dict, python: bool = False) -> dict:
    """
    機能: 確定103入力と1入口条件から、原行の準備完了及び各段階原行を返す。
    引数: raw/item/config(dict)、python(bool)は人工でPython実装も比較する設定。
    返り値: dict。原行状態と疎な段階ログ。金融再生又は入力の書換えをしない。
    """
    assert config['family'] in ('C', 'R') and config['strength'] in (.5, 1., 2.)
    n = len(raw['raw_seq'])
    for name in ('bid_prices', 'bid_quantities', 'ask_prices', 'ask_quantities'):
        assert raw[name].shape == (n, 10)
    tick = float(item['tick'])
    assert np.isfinite(tick) and tick > 0
    qualified, direction = row_qualified(raw), volume_direction_proxy(raw)
    function = simulate.py_func if python else simulate
    ready, anchors, phases, events = function(raw['price_time_s'], raw['bid'], raw['ask'],
        raw['bid_qty'], raw['ask_qty'], raw['last'], raw['volume_delta'], direction, qualified,
        raw['bid_prices'], raw['bid_quantities'], raw['ask_prices'], raw['ask_quantities'], raw['raw_seq'],
        1 if config['family'] == 'C' else 2, float(config['strength']),
        bool(config['use_supply']), bool(config['use_volume']), tick, 120., 5000)
    table = np.asarray(events, np.float64).reshape(-1, 22)
    rows = table[:, 0].astype(np.int64)
    anchor_rows = table[:, 6].astype(np.int64)
    return dict(config=dict(config), qualified=qualified, volume_direction_proxy=direction,
        ready=ready, anchor_raw_seq=anchors, phases=phases, events=table,
        event_raw_seq=raw['raw_seq'][rows].copy(), event_anchor_raw_seq=raw['raw_seq'][anchor_rows].copy(),
        event_columns=EVENT_COLUMNS, event_codes=EVENT_CODES, reset_reasons=RESET_REASONS,
        raw_seq=raw['raw_seq'], price_time_s=raw['price_time_s'])


def publication(raw: dict) -> dict:
    """
    機能: 相手の新最大価格時計に対する最初原行だけを公表源へする。
    引数: raw(dict)は原順を保つ相手入力。
    返り値: dict。単調な時計と原行index。不明状態の新最大行も後続で置換しない。
    """
    rows, maximum = [], -np.inf
    for row, stamp in enumerate(raw['price_time_s']):
        if raw['price_time_valid'][row] and np.isfinite(stamp) and stamp > maximum:
            maximum = stamp
            rows.append(row)
    indexes = np.asarray(rows, np.int64)
    return dict(rows=indexes, times=raw['price_time_s'][indexes].copy())


def pulses(own: dict, peer: dict | None, own_raw: dict, peer_raw: dict | None,
           use_peer: bool = True) -> dict:
    """
    機能: 自己準備を厳密過去の同family相手公表と確認し、自己episodeを一度消費する。
    引数: own/own_raw(dict)、peer/peer_raw(dict|None)、use_peer(bool)。
    返り値: dict。pulse、相手原行、意図基準seq。保有や受付外で捨てたpulseを補充しない。
    """
    n = len(own_raw['raw_seq'])
    event = np.zeros(n, np.int8)
    peer_rows = np.full(n, -1, np.int64)
    consumed, records = set(), []
    if use_peer:
        assert peer is not None and peer_raw is not None and peer['config']['family'] == own['config']['family']
        published = publication(peer_raw)
        positions = np.searchsorted(published['times'], own_raw['price_time_s'], side='left') - 1
        known = positions >= 0
        known &= own_raw['price_time_valid'] & np.isfinite(own_raw['price_time_s'])
        peer_rows[known] = published['rows'][positions[known]]
    for row in range(n):
        if not own['qualified'][row]:
            continue
        candidates = []
        for column, side in enumerate(SIDES):
            if not own['ready'][row, column]:
                continue
            source = int(peer_rows[row])
            if use_peer and (source < 0 or not peer['qualified'][source]
                    or not peer['ready'][source, column]
                    or own_raw['price_time_s'][row] - peer_raw['price_time_s'][source] > 15.):
                continue
            intent = side if own['config']['family'] == 'C' else -side
            key = (own['config']['family'], intent, int(own['anchor_raw_seq'][row, column]))
            candidates.append((side, key, source))
        if len(candidates) != 1 or candidates[0][1] in consumed:
            continue
        side, key, source = candidates[0]
        event[row] = side
        consumed.add(key)
        records.append(dict(row=row, raw_seq=int(own_raw['raw_seq'][row]), side=side,
                            episode=key, peer_row=source))
    return dict(event=event, peer_rows=peer_rows, decisions=records)


def union_pulses(components: dict, own_raw: dict) -> dict:
    """
    機能: C1/R1の準備思想を同時に見て、同方向は1pulse、反対同時は保留する。
    引数: components(dict)はfamilyごとの自己/相手packet及びraw、own_raw(dict)。
    返り値: dict。単一1枚のpulse。C/Rの独立signal pulseを後からORしていない。
    """
    n = len(own_raw['raw_seq'])
    event = np.zeros(n, np.int8)
    consumed, records = set(), []
    indexes = {}
    for family, value in components.items():
        published = publication(value['peer_raw'])
        p = np.searchsorted(published['times'], own_raw['price_time_s'], side='left') - 1
        rows = np.full(n, -1, np.int64)
        known = (p >= 0) & own_raw['price_time_valid'] & np.isfinite(own_raw['price_time_s'])
        rows[known] = published['rows'][p[known]]
        indexes[family] = rows
    for row in range(n):
        candidates = []
        for family, value in components.items():
            own, peer, peer_raw = value['own'], value['peer'], value['peer_raw']
            source = int(indexes[family][row])
            if not own['qualified'][row] or source < 0 or not peer['qualified'][source] or own_raw['price_time_s'][row] - peer_raw['price_time_s'][source] > 15.:
                continue
            for column, side in enumerate(SIDES):
                if own['ready'][row, column] and peer['ready'][source, column]:
                    intent = side if family == 'C' else -side
                    key = family, intent, int(own['anchor_raw_seq'][row, column])
                    candidates.append((side, key, source))
        directions = {value[0] for value in candidates}
        if len(directions) != 1:
            continue
        if not any(value[1] not in consumed for value in candidates):
            continue
        side = next(iter(directions))
        event[row] = side
        consumed.update(value[1] for value in candidates)
        records.append(dict(row=row, raw_seq=int(own_raw['raw_seq'][row]), side=side,
                            episodes=[value[1] for value in candidates], peer_rows=[value[2] for value in candidates]))
    return dict(event=event, decisions=records)
