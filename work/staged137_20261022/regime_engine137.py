"""時間帯別の初回枚数と、成立し直した二市場支持による追加を比較する。

現行採用手法の移植ではなく、比較用の独立した状態機械。
人工経路以外の実行には、呼出側で試行登録と入力内容指紋を必要とする。
"""

import math

import numpy as np
from numba import njit


ORDER_FIELDS = ("約定原行", "判断原行", "親番号", "注文売買方向", "枚数", "価格", "理由番号", "新規", "玉区分", "料金")
EVENT_FIELDS = ("原行", "事象番号", "親番号", "保有方向", "玉区分", "枚数", "時間帯", "値")
REASONS = {1: "弱支持から初回", 2: "順行後の追加", 3: "元玉の初期停止", 4: "追加玉の停止", 5: "利益追尾", 6: "二市場逆行の継続", 7: "予定終場返済"}
EVENTS = {1: "発注判断", 2: "約定", 3: "終場による新規取消", 4: "入力終端で未返済", 5: "入力終端で未約定", 6: "支持時計の中断"}


@njit(cache=True)
def _event(output, index, row, event, parent, side, leg, quantity, phase, value):
    """
    機能: 型の異なる事象値を八列の浮動小数表へ保存する。
    引数: output(ndarray)、index等(int)、value(float)は保存先と事象値。
    返り値: None。指定行を更新する。
    """
    output[index, 0], output[index, 1], output[index, 2], output[index, 3] = row, event, parent, side
    output[index, 4], output[index, 5], output[index, 6], output[index, 7] = leg, quantity, phase, value


@njit(cache=True)
def _run(times, bid, ask, qok, atr, market, phase, start, end, parameters):
    """
    機能: 当該原行までの情報だけで判断し、次の正常原行で約定する。
    引数: times等(ndarray)は時系列、start/end(float)は場時計、parameters(ndarray)は固定設定。
    返り値: tuple[ndarray,ndarray]は十列注文と八列状態事象。金融成績はここでは集計しない。
    """
    timed, initial, target, maximum, add_mode, add_width, stop_width, trail_start, trail_width, support_hold, opposite_hold, cooldown, fee, minimum_risk, avoid_shock, cutoff, add_stop = parameters
    initial, target, maximum, add_mode = int(initial), int(target), int(maximum), int(add_mode)
    n = len(times)
    orders = np.empty((max(8, n * 2), 10), dtype=np.float64)
    events = np.empty((max(16, n * 4), 8), dtype=np.float64)
    no, ne = 0, 0
    quantity = np.zeros(2, dtype=np.int64)
    entry = np.zeros(2)
    risk = np.zeros(2)
    extreme = np.zeros(2)
    protected = np.zeros(2, dtype=np.bool_)
    pending = np.zeros(2, dtype=np.int64)
    pending_reason = np.zeros(2, dtype=np.int64)
    pending_row = np.zeros(2, dtype=np.int64)
    pending_risk = np.zeros(2)
    side, parent, parent_counter = 0, 0, 0
    weak_side, weak_since, strong_since, opposite_since = 0, -1., -1., -1.
    strong_released, added, closing = False, False, False
    last_flat = -np.inf
    last_time = -np.inf
    for i in range(n):
        t = times[i]
        if t < start:
            last_time = t
            continue
        p = int(phase[i])
        quote = bool(qok[i]) and np.isfinite(bid[i]) and np.isfinite(ask[i]) and bid[i] > 0. and ask[i] > bid[i]
        known = quote and np.isfinite(atr[i]) and atr[i] > 0. and market[i, 11] == 1.
        known = known and np.isfinite(market[i, 8]) and 0. <= t - market[i, 8] <= 15.
        for k in range(4, 8):
            known = known and np.isfinite(market[i, k])
        interrupted = t - last_time > 15. or not known
        if interrupted:
            if weak_since >= 0. or strong_since >= 0. or opposite_since >= 0.:
                _event(events, ne, i, 6, parent, side, -1, quantity.sum(), p, t - last_time)
                ne += 1
            weak_since, strong_since, opposite_since = -1., -1., -1.
            weak_side = 0
        last_time = t

        # ----------------------------------------
        # 注文は判断した原行を飛ばし、後続の正常気配でのみ約定する。
        filled_initial = False
        for leg in range(2):
            if pending[leg] == 0 or i <= pending_row[leg] or not quote:
                continue
            is_new = pending[leg] > 0
            if is_new and t >= end - cutoff:
                _event(events, ne, i, 3, parent, side, leg, pending[leg], p, 0.)
                ne += 1
                pending[leg] = 0
                if quantity.sum() == 0:
                    side = 0
                    weak_since, strong_since, opposite_since = -1., -1., -1.
                continue
            qty = abs(pending[leg])
            order_side = side if is_new else -side
            price = ask[i] if order_side == 1 else bid[i]
            order_fee = math.floor(qty * fee + 1e-9)
            orders[no, 0], orders[no, 1], orders[no, 2] = i, pending_row[leg], parent
            orders[no, 3], orders[no, 4], orders[no, 5] = order_side, qty, price
            orders[no, 6], orders[no, 7], orders[no, 8], orders[no, 9] = pending_reason[leg], int(is_new), leg, order_fee
            no += 1
            _event(events, ne, i, 2, parent, side, leg, qty, p, price)
            ne += 1
            if is_new:
                quantity[leg], entry[leg], risk[leg] = qty, price, pending_risk[leg]
                extreme[leg] = bid[i] if side == 1 else ask[i]
                protected[leg] = False
                if leg == 0:
                    filled_initial = True
                    added, closing, strong_released = False, False, False
                    strong_since, opposite_since = -1., -1.
            else:
                quantity[leg] = 0
            pending[leg] = 0
        if side != 0 and quantity.sum() == 0 and pending.sum() == 0:
            side, closing = 0, False
            last_flat = t
            weak_since, strong_since, opposite_since = -1., -1., -1.
            weak_side = 0

        # ----------------------------------------
        # 返済を追加より先に決める。元玉と追加玉の停止線を独立に保つ。
        if quantity.sum() > 0:
            reverse = known and side * market[i, 4] <= -.05 and side * market[i, 6] <= -.05
            if reverse:
                if opposite_since < 0.:
                    opposite_since = t
            else:
                opposite_since = -1.
            reverse_exit = opposite_since >= 0. and t - opposite_since >= opposite_hold
            if t >= end or reverse_exit:
                closing = True
            exit_decided = False
            for leg in range(2):
                if quantity[leg] == 0 or pending[leg] != 0:
                    continue
                reason = 0
                if t >= end:
                    reason = 7
                elif reverse_exit:
                    reason = 6
                elif quote:
                    liquidation = bid[i] if side == 1 else ask[i]
                    if side * (liquidation - extreme[leg]) > 0.:
                        extreme[leg] = liquidation
                    if side * (extreme[leg] - entry[leg]) >= trail_start * risk[leg]:
                        protected[leg] = True
                    width = stop_width if leg == 0 else add_stop
                    if side * (liquidation - entry[leg]) <= -width * risk[leg]:
                        reason = 3 if leg == 0 else 4
                    elif protected[leg] and side * (extreme[leg] - liquidation) >= trail_width * risk[leg]:
                        reason = 5
                if reason:
                    pending[leg], pending_row[leg], pending_reason[leg] = -quantity[leg], i, reason
                    _event(events, ne, i, 1, parent, side, leg, -quantity[leg], p, reason)
                    ne += 1
                    exit_decided = True
                    if leg == 0:
                        closing = True
            if closing and pending[1] > 0:
                pending[1] = 0
            if closing or exit_decided or pending[0] != 0 or pending[1] != 0:
                continue

            # ----------------------------------------
            # 追加は初回約定後に成立し直した支持で判定する。未知は不成立の証拠にしない。
            strong = known and side * market[i, 4] >= .05 and side * market[i, 6] >= .05
            strong = strong and side * market[i, 5] >= .2 and side * market[i, 7] >= .2
            if known and not strong:
                strong_released = True
                strong_since = -1.
            elif strong and strong_released:
                if strong_since < 0.:
                    strong_since = t
            else:
                strong_since = -1.
            ready = add_mode == 1 or (add_mode == 2 and strong_since >= 0. and t - strong_since >= support_hold)
            executable = bid[i] if side == 1 else ask[i]
            progress = quote and side * (executable - entry[0]) >= add_width * risk[0]
            add_qty = min(target, maximum) - int(quantity.sum())
            if not added and add_mode > 0 and quantity[0] > 0 and add_qty > 0 and t < end - cutoff and ready and progress:
                pending[1], pending_row[1], pending_reason[1] = add_qty, i, 2
                pending_risk[1] = risk[0]
                added = True
                _event(events, ne, i, 1, parent, side, 1, add_qty, p, 2.)
                ne += 1
            continue

        # ----------------------------------------
        # 空の時だけ新規を準備する。時間帯は方向を与えず、必要支持と数量を変える。
        if side != 0 or pending[0] != 0 or pending[1] != 0 or t >= end - cutoff or t - last_flat < cooldown:
            continue
        if not known or ask[i] - bid[i] > .5 * atr[i]:
            weak_since, weak_side = -1., 0
            continue
        threshold120, threshold30, size = .15, 0., initial
        shock = p == 0 or p == 7 or p == 9
        if timed:
            if shock and avoid_shock:
                weak_since, weak_side = -1., 0
                continue
            if shock:
                threshold120, threshold30, size = .3, .05, min(initial, 1)
            elif p == 2:
                threshold120, size = .25, min(initial, 1)
        direction = 0
        for sign in (-1, 1):
            if sign * market[i, 5] >= threshold120 and sign * market[i, 7] >= threshold120 and sign * market[i, 4] >= threshold30 and sign * market[i, 6] >= threshold30:
                direction = sign
        if direction == 0:
            weak_since, weak_side = -1., 0
            continue
        if direction != weak_side or weak_since < 0.:
            weak_since, weak_side = t, direction
        if t - weak_since < support_hold:
            continue
        parent_counter += 1
        parent, side = parent_counter, direction
        pending[0], pending_row[0], pending_reason[0] = min(size, maximum), i, 1
        pending_risk[0] = max(atr[i], minimum_risk)
        _event(events, ne, i, 1, parent, side, 0, pending[0], p, 1.)
        ne += 1
        weak_since, weak_side = -1., 0

    # ----------------------------------------
    # データ不足の残玉は、架空の終値で清算せず明示して呼出側の監査へ渡す。
    for leg in range(2):
        if quantity[leg] > 0:
            _event(events, ne, max(0, n - 1), 4, parent, side, leg, quantity[leg], int(phase[-1]) if n else -1, entry[leg])
            ne += 1
        if pending[leg] != 0:
            _event(events, ne, max(0, n - 1), 5, parent, side, leg, pending[leg], int(phase[-1]) if n else -1, pending_reason[leg])
            ne += 1
    return orders[:no].copy(), events[:ne].copy()


def simulate(times, bid, ask, qok, atr, market, phase, start, end, us_open, config):
    """
    機能: 固定設定を検査し、時間帯・二市場支持・独立玉停止の再生器へ接続する。
    引数: times/bid/ask/qok/atr/market/phase(ndarray)は原行順入力、start/end/us_open(float)は時計、config(dict)は固定条件。
    返り値: tuple[ndarray,ndarray]は注文十列と事象八列。us_openは区分を呼出側で作成済みのため再参照しない。
    """
    n = len(times)
    if any(len(x) != n for x in (bid, ask, qok, atr, market, phase)) or np.shape(market) != (n, 12):
        raise ValueError("全入力の原行数と二市場十二列を一致させてください")
    times = np.asarray(times, dtype=np.float64)
    if not np.isfinite(times).all() or np.any(np.diff(times) < 0.):
        raise ValueError("原行時刻は有限かつ非減少順が必要です")
    if end <= start:
        raise ValueError("予定終場は開始より後が必要です")
    mode = config.get("mode", "uniform")
    if mode not in ("uniform", "time"):
        raise ValueError("modeはuniform又はtimeを指定してください")
    initial = int(config.get("initial_qty", 2))
    target = int(config.get("target_qty", 5))
    maximum = int(config.get("max_per_side", 10))
    if not 1 <= initial <= target <= maximum or maximum > 10:
        raise ValueError("1以上の初回枚数≦目標枚数≦片方向上限10枚が必要です")
    if int(config.get("add_mode", 2)) not in (0, 1, 2):
        raise ValueError("add_modeは0、1、2のいずれかが必要です")
    values = (mode == "time", initial, target, maximum, config.get("add_mode", 2), config.get("add_width", .25),
              config.get("exit_stop", 1.), config.get("trail_start", 1.), config.get("trail_width", .75),
              config.get("support_hold", 15.), config.get("opposite_hold", 30.), config.get("cooldown", 300.),
              config.get("fee_per_contract", 38.5), config.get("min_risk", 20.), config.get("avoid_shock", False),
              config.get("entry_cutoff", 300.), config.get("add_stop", .5))
    parameters = np.asarray(values, dtype=np.float64)
    if not np.isfinite(parameters).all() or np.any(parameters < 0.):
        raise ValueError("設定数値には有限の非負数が必要です")
    return _run(times, np.asarray(bid, dtype=np.float64), np.asarray(ask, dtype=np.float64),
                np.asarray(qok, dtype=np.bool_), np.asarray(atr, dtype=np.float64), np.asarray(market, dtype=np.float64),
                np.asarray(phase, dtype=np.int64), float(start), float(end), parameters)
