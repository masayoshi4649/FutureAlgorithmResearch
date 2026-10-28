"""確定済み価格の勢いで入り、赤字の反証と黒字の追跡を分離する研究エンジン。"""

import math

import numpy as np
from numba import njit


WINDOWS = (3, 5, 10, 20)
REASONS = {
    1: "方向一致の新規",
    2: "順行を確認した追撃",
    3: "玉別の初期最大損失",
    4: "未保護の赤字玉で方向反証が継続",
    5: "含み益到達後の玉別トレール",
    6: "米国開始15分前の区間終了",
    7: "境界または欠測による未約定新規取消",
}


def prepare(data):
    """
    機能: 正常気配から確定1分足終値と過去窓のOLS傾きを構築する。
    引数: data(dict)。ready.time_s/startとquotes.bid/ask/quote_validを読む。
    返り値: dict。各時点が参照可能な確定窓の添字と、傾き・前分差を含む。

    空の分足は欠測のまま残す。未来の終値を現在の時点へ補完しない。
    比較する傾きはpt/分、前分差は前の確定1分足時点からの傾きの差である。
    """
    ready = data["ready"]
    quotes = data["quotes"]
    times = np.asarray(ready["time_s"], dtype=np.float64)
    bid = np.asarray(quotes["bid"], dtype=np.float64)
    ask = np.asarray(quotes["ask"], dtype=np.float64)
    assert len(times) == len(bid) == len(ask)
    assert np.isfinite(times).all() and np.all(np.diff(times) >= 0.0)
    valid = np.asarray(quotes["quote_valid"], dtype=np.bool_)
    valid = valid & np.isfinite(bid) & np.isfinite(ask) & (bid > 0.0) & (ask > bid)
    start = float(ready["start"])
    if not len(times):
        return dict(times=times, bid=bid, ask=ask, valid=valid,
                    bar_index=np.empty(0, dtype=np.int64), bars=np.empty((0, 9)),
                    bar_close=np.empty(0), bar_end=np.empty(0), start=start)
    count = max(0, int(math.floor((times[-1] - start) / 60.0)) + 1)
    closes = np.full(count, np.nan)
    observed = np.full(count, np.nan)
    ids = np.flatnonzero(valid & (times >= start))
    if len(ids):
        buckets = np.floor((times[ids] - start) / 60.0).astype(np.int64)
        last = np.r_[buckets[1:] != buckets[:-1], True]
        close_ids = ids[last]
        closes[buckets[last]] = (bid[close_ids] + ask[close_ids]) * 0.5
        observed[buckets[last]] = times[close_ids]
    bars = np.full((count, 9), np.nan)
    for column, window in enumerate(WINDOWS):
        x = np.arange(window, dtype=float)
        weight = (x - x.mean()) / np.sum((x - x.mean()) ** 2)
        for k in range(window - 1, count):
            values = closes[k - window + 1:k + 1]
            if np.isfinite(values).all():
                bars[k, column] = float(np.dot(values, weight))
        if count > 1:
            bars[1:, column + 4] = np.diff(bars[:, column])
    bars[:, 8] = observed
    ends = start + (np.arange(count) + 1.0) * 60.0
    index = np.searchsorted(ends, times, side="right") - 1
    return dict(times=times, bid=bid, ask=ask, valid=valid,
                bar_index=index.astype(np.int64), bars=bars,
                bar_close=closes, bar_end=ends, start=start)


def _parameters(config):
    """
    機能: 固定した設定を検証し、数値配列へ変換する。
    引数: config(dict)。事前登録済みの条件。
    返り値: tuple[ndarray,ndarray,ndarray]。設定、枚数、追撃閾値。
    """
    quantities = np.asarray(config["quantities"], dtype=np.int64)
    gains = np.asarray(config["add_gain_points"], dtype=np.float64)
    assert 1 <= len(quantities) <= 3 and len(gains) == len(quantities) - 1
    assert np.all(quantities > 0) and np.sum(quantities) <= config["max_per_side"] <= 10
    assert config["hard_stop_points"] > 0 and config["trail_points"] > 0
    assert config["activation_points"] >= config["trail_points"]
    assert config["fee_yen"] == 0.0
    p = np.asarray([
        WINDOWS.index(config["fast_window"]), WINDOWS.index(config["slow_window"]),
        config["minimum_fast_speed"], config["minimum_slow_speed"],
        float(config["require_acceleration"]), config["minimum_acceleration"],
        config["entry_confirm_seconds"], config["hard_stop_points"],
        config["refutation_seconds"], config["activation_points"], config["trail_points"],
        config["cooldown_seconds"], config["add_wait_seconds"],
        config["quote_unknown_seconds"], config["confirmation_gap_seconds"],
    ], dtype=np.float64)
    return p, quantities, gains


@njit(cache=True)
def _replay(times, bid, ask, valid, bar_index, bars, start, cutoff, p, quantities, gains):
    """
    機能: 価格を先頭から一度ずつ読み、判断の次正常気配で注文を約定させる。
    引数: times/bid/ask/valid/bar_index/bars/p/quantities/gains(ndarray)、start/cutoff(float)。
    返り値: tuple。注文配列、判断配列、玉状態、未約定状態、終了時の親状態。
    """
    orders = [(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)]
    orders.pop()
    events = [(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)]
    events.pop()
    held = np.zeros(3, dtype=np.int64)
    entry = np.zeros(3)
    best = np.zeros(3)
    protected = np.zeros(3, dtype=np.bool_)
    fill_index = np.full(3, -1, dtype=np.int64)
    pending_kind = np.zeros(3, dtype=np.int64)
    pending_decision = np.full(3, -1, dtype=np.int64)
    pending_reason = np.zeros(3, dtype=np.int64)
    pending_qty = np.zeros(3, dtype=np.int64)
    parent = 0
    side = 0
    stage = 0
    had_exit = False
    first_price = 0.0
    last_fill_time = -1.0e30
    last_exit_time = -1.0e30
    previous_valid_time = -1.0e30
    confirm_side = 0
    confirm_since = -1.0
    support_side = 0
    support_since = -1.0
    refute_since = -1.0
    fast_col = int(p[0])
    slow_col = int(p[1])
    last_liquidation = np.nan

    for i in range(len(times)):
        now = times[i]
        if now < start:
            continue
        gap = valid[i] and previous_valid_time > -1.0e20 and now - previous_valid_time > p[14]
        stale_gap = valid[i] and previous_valid_time > -1.0e20 and now - previous_valid_time > p[13]
        if gap:
            confirm_side = 0
            confirm_since = -1.0
            support_side = 0
            support_since = -1.0
            refute_since = -1.0

        # ----------------------------------------
        # 前の判断による注文だけを、次の正常気配で処理する。
        for slot in range(3):
            if pending_kind[slot] == 0:
                continue
            if pending_kind[slot] == 1 and (now >= cutoff or stale_gap):
                events.append((float(i), 7.0, float(parent), float(slot + 1),
                               float(side), float(pending_qty[slot]), np.nan,
                               np.nan, np.nan, np.nan, np.nan, np.nan, 0.0, float(pending_decision[slot])))
                pending_kind[slot] = 0
                pending_qty[slot] = 0
                continue
            if not valid[i] or i <= pending_decision[slot]:
                continue
            is_new = pending_kind[slot] == 1
            order_side = side if is_new else -side
            price = ask[i] if order_side > 0 else bid[i]
            qty = pending_qty[slot]
            orders.append((float(i), float(pending_decision[slot]), float(parent),
                           float(order_side), float(qty), price, float(pending_reason[slot]),
                           1.0 if is_new else 0.0, float(slot + 1), 0.0))
            if is_new:
                held[slot] = qty
                entry[slot] = price
                best[slot] = bid[i] if side > 0 else ask[i]
                protected[slot] = False
                fill_index[slot] = i
                last_fill_time = now
                if slot == 0:
                    first_price = price
                stage = slot + 1
            else:
                held[slot] = 0
                had_exit = True
            pending_kind[slot] = 0
            pending_qty[slot] = 0

        if side != 0 and held.sum() == 0 and pending_kind.sum() == 0:
            side = 0
            last_exit_time = now
            stage = 0
            confirm_side = 0
            confirm_since = -1.0
            refute_since = -1.0

        # ----------------------------------------
        # 区間境界は価格指標が欠測していても返済判断を行う。
        if now >= cutoff:
            for slot in range(3):
                if held[slot] and pending_kind[slot] == 0:
                    pending_kind[slot] = 2
                    pending_decision[slot] = i
                    pending_reason[slot] = 6
                    pending_qty[slot] = held[slot]
                    events.append((float(i), 6.0, float(parent), float(slot + 1), float(side),
                                   float(held[slot]), np.nan, np.nan, np.nan, np.nan,
                                   np.nan, best[slot], 1.0 if protected[slot] else 0.0, float(i)))
            if valid[i]:
                previous_valid_time = now
                if side:
                    last_liquidation = bid[i] if side > 0 else ask[i]
            continue
        if not valid[i]:
            continue
        previous_valid_time = now
        fast = np.nan
        slow = np.nan
        acceleration = np.nan
        known = False
        k = bar_index[i]
        if k >= 0:
            fast = bars[k, fast_col]
            slow = bars[k, slow_col]
            acceleration = bars[k, fast_col + 4]
            known = np.isfinite(fast) and np.isfinite(slow) and np.isfinite(bars[k, 8]) and now - bars[k, 8] <= p[13]
        direction = 0
        if known:
            if fast >= p[2] and slow >= p[3]:
                direction = 1
            elif fast <= -p[2] and slow <= -p[3]:
                direction = -1
        entry_direction = direction
        if direction == 0:
            support_side = 0
            support_since = -1.0
        elif direction != support_side:
            support_side = direction
            support_since = now
        if p[4] > 0 and (not np.isfinite(acceleration) or entry_direction * acceleration < p[5]):
            entry_direction = 0
        if entry_direction == 0:
            confirm_side = 0
            confirm_since = -1.0
        elif entry_direction != confirm_side:
            confirm_side = entry_direction
            confirm_since = now
        if not known:
            refute_since = -1.0

        # ----------------------------------------
        # 最大損失・含み益後トレールを玉別に処理し、追加で停止価格を緩めない。
        if side != 0 and held.sum() > 0:
            liquidation = bid[i] if side > 0 else ask[i]
            last_liquidation = liquidation
            if direction == -side:
                if refute_since < 0.0:
                    refute_since = now
            else:
                refute_since = -1.0
            for slot in range(3):
                if held[slot] == 0 or pending_kind[slot] != 0:
                    continue
                gain = side * (liquidation - entry[slot])
                if side * (liquidation - best[slot]) > 0:
                    best[slot] = liquidation
                if gain >= p[9]:
                    protected[slot] = True
                reason = 0
                if gain <= -p[7]:
                    reason = 3
                elif protected[slot] and side * (best[slot] - liquidation) >= p[10]:
                    reason = 5
                elif not protected[slot] and gain <= 0.0 and refute_since >= 0.0 and now - refute_since >= p[8]:
                    reason = 4
                if reason:
                    pending_kind[slot] = 2
                    pending_decision[slot] = i
                    pending_reason[slot] = reason
                    pending_qty[slot] = held[slot]
                    had_exit = True
                    events.append((float(i), float(reason), float(parent), float(slot + 1), float(side),
                                   float(held[slot]), liquidation, fast, slow, acceleration,
                                   gain, best[slot], 1.0 if protected[slot] else 0.0, float(i)))

            # ----------------------------------------
            # 一度でも返済判断した親では追撃を再開しない。
            if not had_exit and stage < len(quantities) and stage > 0 and pending_kind.sum() == 0:
                if direction == side and support_since >= 0.0 and now - support_since >= p[6] and now - last_fill_time >= p[12] and side * (liquidation - first_price) >= gains[stage - 1]:
                    slot = stage
                    pending_kind[slot] = 1
                    pending_decision[slot] = i
                    pending_reason[slot] = 2
                    pending_qty[slot] = quantities[stage]
                    events.append((float(i), 2.0, float(parent), float(slot + 1), float(side),
                                   float(quantities[stage]), liquidation, fast, slow, acceleration,
                                   side * (liquidation - first_price), np.nan, 0.0, float(i)))

        # ----------------------------------------
        # 方向支持が連続し、返済後の待ち時間を終えた場合だけ新しい親を作る。
        if side == 0 and entry_direction != 0 and confirm_since >= 0:
            if now - confirm_since >= p[6] and now - last_exit_time >= p[11]:
                parent += 1
                side = entry_direction
                stage = 0
                had_exit = False
                refute_since = -1.0
                pending_kind[0] = 1
                pending_decision[0] = i
                pending_reason[0] = 1
                pending_qty[0] = quantities[0]
                events.append((float(i), 1.0, float(parent), 1.0, float(side),
                               float(quantities[0]), ask[i] if side > 0 else bid[i],
                               fast, slow, acceleration, 0.0, np.nan, 0.0, float(i)))

    positions = np.zeros((3, 7))
    pending = np.zeros((3, 5))
    for slot in range(3):
        positions[slot, 0] = held[slot]
        positions[slot, 1] = entry[slot]
        positions[slot, 2] = best[slot]
        positions[slot, 3] = 1.0 if protected[slot] else 0.0
        positions[slot, 4] = fill_index[slot]
        positions[slot, 5] = last_liquidation
        positions[slot, 6] = side * (last_liquidation - entry[slot]) if held[slot] else 0.0
        pending[slot, 0] = pending_kind[slot]
        pending[slot, 1] = pending_decision[slot]
        pending[slot, 2] = pending_reason[slot]
        pending[slot, 3] = pending_qty[slot]
        pending[slot, 4] = slot + 1
    return orders, events, positions, pending, parent, side


def simulate(data, config, prepared=None):
    """
    機能: 米国開始前限定の戦略を、未来の価格を使わず時系列で再生する。
    引数: data(dict)、config(dict)、prepared(dict|None)。preparedは同じdataのprepare結果。
    返り値: dict。既存会計互換orders、判断diagnostics、未決済positions、終了状態を含む。

    区間はセッション開始から米国開始15分前まで。現在の途中資料では、
    最終行を架空の返済時点とせず、残玉と未約定判断をそのまま返す。
    """
    prepared = prepare(data) if prepared is None else prepared
    p, quantities, gains = _parameters(config)
    ready = data["ready"]
    cutoff = float(ready["us_open"]) - float(config["cutoff_before_us_seconds"])
    assert np.array_equal(prepared["times"], np.asarray(ready["time_s"]))
    raw_orders, raw_events, raw_positions, raw_pending, parent, side = _replay(
        prepared["times"], prepared["bid"], prepared["ask"], prepared["valid"],
        prepared["bar_index"], prepared["bars"], float(ready["start"]), cutoff,
        p, quantities, gains)
    orders = np.asarray(raw_orders, dtype=float).reshape((-1, 10))
    columns = ("index", "reason_code", "parent", "ticket", "side", "quantity", "decision_price",
               "fast_speed", "slow_speed", "acceleration", "gain_points", "best_price",
               "protected", "original_decision_index")
    diagnostics = []
    for row in raw_events:
        event = dict(zip(columns, row))
        event["time_s"] = float(prepared["times"][int(event["index"])])
        event["reason"] = REASONS[int(event["reason_code"])]
        diagnostics.append(event)
    positions = []
    for slot, row in enumerate(raw_positions):
        if row[0] > 0:
            positions.append(dict(parent=int(parent), ticket=slot + 1, side=int(side),
                                  quantity=int(row[0]), entry=float(row[1]), best_price=float(row[2]),
                                  protected=bool(row[3]), fill_index=int(row[4]),
                                  liquidation_price=float(row[5]), unrealized_points=float(row[6]),
                                  hard_stop_price=float(row[1] - side * config["hard_stop_points"]),
                                  trail_price=float(row[2] - side * config["trail_points"]) if row[3] else None))
    pending = [dict(kind=int(row[0]), decision_index=int(row[1]), reason=REASONS[int(row[2])],
                    quantity=int(row[3]), ticket=int(row[4]), side=int(side), parent=int(parent))
               for row in raw_pending if row[0] != 0]
    return dict(orders=orders, decisions=diagnostics, diagnostics=diagnostics, positions=positions,
                final_state=dict(parent=int(parent), side=int(side), pending_orders=pending,
                                 cutoff=cutoff, final_time=float(prepared["times"][-1]) if len(prepared["times"]) else None),
                feature_metadata=dict(windows=list(WINDOWS), unit="pt/分", acceleration="同窓傾きの前分差",
                                      interpolation=False, source="正常最良買気配と最良売気配の中値"))
