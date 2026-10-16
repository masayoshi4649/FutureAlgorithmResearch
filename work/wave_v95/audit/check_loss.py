"""実注文の料金後損益から、反対候補の記憶・四源基準・全66列を独立復元する。"""

import math

import numpy as np

import common


KINDS = dict(none=0, ban_opposite=1, fresh_quotes=2, fresh_price_quotes=3, sustained_price_quotes=4)
SOURCES = ((0, 1, 2), (5, 6, 7), (10, 11, 12), (14, 15, 16))


def publication(record: dict, signal: dict) -> tuple[np.ndarray, np.ndarray]:
    """
    機能: 自己原行へ公開済みの最新格子と10秒鮮度を、別の累積式で求める。
    引数: record(dict)。執行原行。signal(dict)。格子とmapped。
    返り値: tuple[ndarray[int],ndarray[bool]]。最新番号と鮮度。
    """
    latest = np.maximum.accumulate(signal['mapped'])
    safe = np.maximum(latest, 0)
    fresh = (latest >= 0) & (record['time_s'] - signal['grid'][safe] <= 10. + 1e-8)
    return latest, fresh


def normal(pair: np.ndarray) -> bool:
    """
    機能: 同一判断の独立LP二源・旧BBO二源がすべて既知かを判定する。
    引数: pair(ndarray[float])。22列の公開観測。
    返り値: bool。四源が有効で価格と時計及び識別子が有限のとき真。
    """
    return bool(np.isfinite(pair).all() and np.all(pair[18:] == 1)
                and np.all(pair[[0, 5, 10, 14]] >= 0)
                and 0 < pair[3] < pair[4] and 0 < pair[8] < pair[9]
                and pair[13] > 0 and pair[17] > 0)


def evidence(pair: np.ndarray, anchor: np.ndarray, exit_time: float, side: int,
             own_tick: float, peer_tick: float) -> tuple[bool, bool, bool]:
    """
    機能: 実返済後の四源更新・両気配の進行・LP進行を別々の共同条件で計算する。
    引数: pair/anchor(ndarray[float])、exit_time/own_tick/peer_tick(float)、side(int)。
    返り値: tuple[bool,bool,bool]。fresh、両気配進行、両LP進行。
    同clock後続index又は別時点の自己・相手支持を合算しない。
    """
    fresh = normal(pair) and normal(anchor)
    for index, sequence, clock in SOURCES:
        fresh &= (pair[index] > anchor[index] and pair[sequence] > anchor[sequence]
                  and pair[clock] > max(exit_time, anchor[clock]))
    quotes = fresh and all(side * (pair[column] - anchor[column]) >= width - 1e-8
                           for column, width in ((3, own_tick), (4, own_tick), (8, peer_tick), (9, peer_tick)))
    prices = fresh and side * (pair[13] - anchor[13]) >= own_tick - 1e-8
    prices &= side * (pair[17] - anchor[17]) >= peer_tick - 1e-8
    return bool(fresh), bool(quotes), bool(prices)


def emit(row: int, code: int, parent: np.ndarray, active: bool, anchor_kind: int,
         anchor_row: int, anchor_grid: int, anchor: np.ndarray, observed: np.ndarray,
         side: int, required: bool, fresh: bool, quotes: bool, prices: bool,
         sustained: bool, accepted: bool, sustain_start: int, kind: int, trigger: int) -> np.ndarray:
    """
    機能: 独立復元した履歴を、公開schemaの66列へ組み立てる。
    引数: row/code/anchor_kind/anchor_row/anchor_grid/side/sustain_start/kind/trigger(int)、
        parent/anchor/observed(ndarray)、各旗(bool)。
    返り値: ndarray[float64]。66列の一行。正式loss_event関数は呼ばない。
    """
    return np.r_[row, code, parent, active, anchor_kind, anchor_row, anchor_grid, anchor, observed,
                 side, required, fresh, quotes, prices, sustained, accepted, sustain_start, kind, trigger].astype(float)


def observation_rows(signal: dict, fresh: np.ndarray, orders: np.ndarray, events: np.ndarray) -> np.ndarray:
    """
    機能: 四源履歴の値が変わり得る行を、公開更新・鮮度境界・全注文機会から列挙する。
    引数: signal(dict)、fresh(ndarray[bool])、orders/events(ndarray)。
    返り値: ndarray[int64]。処理対象原行。全原板会計又は原入力を間引かない。
    値が一定の公開格子の途中行では新しいlossイベントが生成されないことを全原行経路と照合する。
    """
    updated = np.flatnonzero(signal['mapped'] >= 0)
    opportunities = np.flatnonzero(signal['event'] != 0)
    boundaries = np.flatnonzero(fresh != np.r_[False, fresh[:-1]])
    old_events = events[events[:, 2] == 0, 0].astype(np.int64)
    closed = orders[(orders[:, 3] == 0) & (orders[:, 7] == 0), 0].astype(np.int64)
    return np.unique(np.r_[updated, opportunities, boundaries, old_events, closed]).astype(np.int64)


def restore(record: dict, signal: dict, config: dict, orders: np.ndarray, events: np.ndarray,
            all_rows: bool = False) -> np.ndarray:
    """
    機能: 独立に検算した確定注文と原観測から、失敗記憶と反転gateを逐次復元する。
    引数: record/signal/config(dict)、orders(ndarray[17列])、events(ndarray[12列])、all_rows(bool)。
    返り値: ndarray[float64,66列]。独立した損失後再参加履歴。
    元のloss traceを状態生成へ使わず、実entry/exit注文から料金後netを計算する。
    """
    kind = KINDS[config['loss_reentry_kind']]
    if kind == 0:
        return np.empty((0, 66), float)
    trigger = 0 if config['loss_reentry_trigger'] == 'any_net_negative' else 1
    latest, fresh = publication(record, signal)
    times, bids, asks = (record[name] for name in ('time_s', 'bid', 'ask'))
    quote_valid = record['quote_valid'] & np.isfinite(bids) & np.isfinite(asks) & (bids > 0) & (asks > bids)
    rows = []
    parent = np.array([0., 0., 0., 0., -1., -1e30])
    active, anchor_kind = False, 0
    anchor, anchor_row, anchor_grid = np.full(22, np.nan), -1, -1
    sustain_start, previous_grid_time = -1, -1e30
    sustain_sources = np.full(22, np.nan)
    sustained = source_fresh = quotes = prices = False
    exits = {int(order[0]): order for order in orders if order[7] == 0 and order[3] == 0}
    entries = {int(order[2]): order for order in orders if order[7] == 1 and order[3] == 0}
    event_rows = {}
    for event in events:
        if event[2] == 0:
            event_rows.setdefault(int(event[0]), []).append(event)
    status = 0
    last_exit = -1e30
    tick, peer_tick = record['tick'], signal['peer_tick']
    processing = np.arange(len(times), dtype=np.int64) if all_rows else observation_rows(signal, fresh, orders, events)
    for row in processing:
        stamp = times[row]
        current = signal['loss_observations'][latest[row]].copy() if fresh[row] else np.full(22, np.nan)
        observed = current
        row_events = event_rows.get(row, [])
        # ----------------------------------------
        # 実fill・取消を先に反映し、未確定返済の予約は失敗へ代用しない。
        for event in row_events:
            code = int(event[3])
            if code == 4:
                status = 2
            elif code == 5 or code == 6:
                status = 0
            elif code == 2:
                status = 3
        if row in exits:
            closed = exits[row]
            opened = entries[int(closed[2])]
            side, quantity, reason = int(opened[4]), opened[5], int(closed[8])
            multiplier, fee_unit = (1000., 41.8) if record['symbol'] == 'TOPIX' else (10., 11.)
            entry_fee = math.floor(quantity * fee_unit + 1e-8)
            exit_fee = math.floor(closed[5] * fee_unit + 1e-8)
            assert opened[9] == entry_fee and closed[9] == exit_fee and quantity == closed[5]
            net = side * (closed[6] - opened[6]) * quantity * multiplier - entry_fee - exit_fee
            parent = np.array([closed[2], side, reason, net, row, stamp])
            active = net < 0 and (trigger == 0 or reason in (1, 2))
            anchor, anchor_kind, anchor_row, anchor_grid = np.full(22, np.nan), 0, row, int(latest[row])
            sustain_start, previous_grid_time, sustained = -1, -1e30, False
            last_exit = stamp
            if active:
                anchor = current.copy()
                anchor[0:5] = [row, record['seq'][row], stamp, bids[row], asks[row]]
                anchor[10:14] = [signal['execution_lp_index'][row], record['seq'][row], stamp, record['price'][row]]
                anchor[18] = quote_valid[row]
                anchor[20] = (record['price_valid'][row] and np.isfinite(record['price'][row])
                              and record['price'][row] > 0 and signal['execution_lp_index'][row] >= 0)
                if normal(anchor):
                    anchor_kind = 1
            rows.append(emit(row, 1 if active else 2, parent, active, anchor_kind, anchor_row,
                             anchor_grid, anchor, current, 0, False, False, False, False, False,
                             False, -1, kind, trigger))
        # ----------------------------------------
        # 返済時未知の四源は、最初の後続正常pairを新しい別基準にする。
        if kind >= 2 and active:
            just_anchored = False
            if anchor_kind == 0 and fresh[row] and normal(current):
                if all(current[clock] > parent[5] for _, _, clock in SOURCES):
                    anchor, anchor_kind, anchor_row, anchor_grid = current.copy(), 2, row, int(latest[row])
                    just_anchored = True
                    rows.append(emit(row, 3, parent, active, anchor_kind, anchor_row, anchor_grid,
                                     anchor, current, 0, False, False, False, False, False, False, -1, kind, trigger))
            source_fresh, quotes, prices = evidence(current, anchor, parent[5], -int(parent[1]), tick, peer_tick)
            if just_anchored:
                source_fresh = quotes = prices = False
            if kind == 4:
                raw = quotes and prices and not just_anchored
                updated = signal['mapped'][row] >= 0
                gap = updated and signal['grid'][latest[row]] - previous_grid_time > 5. + 1e-8
                if not raw or gap:
                    if sustain_start >= 0:
                        rows.append(emit(row, 6, parent, active, anchor_kind, anchor_row, anchor_grid,
                                         anchor, current, 0, False, source_fresh, quotes, prices, False,
                                         False, sustain_start, kind, trigger))
                    sustain_start, sustained = -1, False
                if updated:
                    previous_grid_time = signal['grid'][latest[row]]
                    if raw:
                        if sustain_start < 0:
                            sustain_start, sustain_sources = int(latest[row]), current.copy()
                            rows.append(emit(row, 5, parent, active, anchor_kind, anchor_row, anchor_grid,
                                             anchor, current, 0, False, source_fresh, quotes, prices,
                                             False, False, sustain_start, kind, trigger))
                        advanced = all(current[index] > sustain_sources[index]
                                       and current[sequence] > sustain_sources[sequence]
                                       and current[clock] > sustain_sources[clock]
                                       for index, sequence, clock in SOURCES)
                        sustained = (signal['grid'][latest[row]] - signal['grid'][sustain_start]
                                     >= config['loss_confirm_seconds'] and advanced)
        # ----------------------------------------
        # 新規機会は当時のpulseのみ。後のgate成立で見送り機会を復活させない。
        eligible = (status == 0 and signal['event'][row] != 0 and signal['quality'][row]
                    and not signal['reset'][row] and quote_valid[row]
                    and record['start'] + 300. <= stamp < record['limit'] - 300.
                    and stamp - last_exit >= 30.)
        reserves = [event for event in row_events if event[3] == 1]
        if eligible:
            side = int(signal['event'][row])
            required = active and side == -int(parent[1])
            accepted = (not required or (kind == 2 and quotes) or (kind == 3 and quotes and prices)
                        or (kind == 4 and sustained))
            if required:
                rows.append(emit(row, 4, parent, active, anchor_kind, anchor_row, anchor_grid, anchor,
                                 current, side, True, source_fresh, quotes, prices, sustained, accepted,
                                 sustain_start, kind, trigger))
            assert bool(reserves) == accepted, ('反対gateと当時新規予約の不一致', row, required, accepted)
            if accepted:
                assert len(reserves) == 1 and reserves[0][4] == side
            else:
                rejected = [event for event in row_events if event[3] == 9]
                assert len(rejected) == 1 and rejected[0][4] == side
        else:
            assert not reserves, ('元J8新規資格外の予約', row)
        if reserves:
            status = 1
    return np.asarray(rows, float).reshape((-1, 66))


def verify(record: dict, signal: dict, config: dict, result: dict) -> dict:
    """
    機能: 正式66列を独立履歴に照合し、対象別件数を返す。
    引数: record/signal/config/result(dict)。入力と人工又は根許可の正式結果。
    返り値: dict。実終了・別基準・候補判定・持続開始/破棄の照合数。
    """
    expected = restore(record, signal, config, result['orders'], result['events'])
    common.exact(expected, result['loss_reentry_events'])
    return {name: int((expected[:, 1] == code).sum()) for code, name in
            ((1, '損失記憶'), (2, '記憶解除'), (3, '別基準'), (4, '反対候補判定'), (5, '持続開始'), (6, '持続破棄'))}
