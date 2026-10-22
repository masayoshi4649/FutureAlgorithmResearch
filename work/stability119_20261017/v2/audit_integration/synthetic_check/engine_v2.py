"""初回の約定規則を対照に、事前価格制限と期限付き返済保護を加えた別版。"""

import math
import numpy as np
from numba import njit


@njit(cache=True)
def replay(events, indexes, rows, times, bid, ask, last, pub_rows, pub_times,
           entry, exit_long, exit_short, widths, valid, anchor,
           quantity, multiplier, fee, exit_mode, entry_mode, guard,
           entry_end, close_time, order_tick=0.0, execution_mode=0, observed_tick=0.5):
    """
    機能: 一政策を原行イベント順で実行し、全清算費用込み資産と返済明細を保存する。
    引数: events/indexes(int配列)は気配優先の原row整列、rows/times/bid/askは正常気配、
          pub_rows/pub_times/entry/exit_long/exit_short/widths/valid/anchorは足公開時の既知値。
          quantity(int)、multiplier/fee(float)、exit_mode/entry_mode/guard(int)、締切/order_tick(float)、
          execution_mode(int)はbit1が新規価格制限、bit2が返済保護、observed_tick(float)は観測呼値。
    返り値: tuple。返済台帳(float[:,16])、公開時資産・保有方向、最終現金・評価・未返済枚数、
            最大資産下落、取消数、約定数、停止理由、返済期限超過数、保護待機行数、新規拒否数。
            評価清算を実返済に変えず、保護待機中も実反対気配で全残玉を評価する。
    """
    n = len(entry)
    ledger = np.empty((len(rows) + 4, 16), np.float64)
    trace = np.full(n, np.nan)
    positions = np.zeros(n, np.int8)
    count = 0
    direction = 0
    held = 0
    original = 0
    ep = 0.0
    et = 0.0
    erow = -1
    ebar = -1
    einfee = 0.0
    risk = 0.0
    peak = 0.0
    half_done = False
    cash = 0.0
    parent = 0
    pending = 0
    pd = 0
    pq = 0
    prow = -1
    ptime = 0.0
    pbar = -1
    plimit = 0.0
    prisk = 0.0
    preason = 0
    latest_bid = np.nan
    latest_ask = np.nan
    latest_time = np.nan
    latest_row = -1
    protected_limit = 0.0
    protected_fallbacks = 0
    protected_waits = 0
    rejected_entries = 0
    last_bar = -100
    cooldown = -1
    session_risk = np.nan
    high_equity = 0.0
    max_drawdown = 0.0
    canceled = 0
    fills = 0
    halted = 0

    for event in range(len(events)):
        i = indexes[event]
        if events[event] == 0:
            qr, qt = rows[i], times[i]
            latest_bid, latest_ask, latest_time, latest_row = bid[i], ask[i], qt, qr
            if pending == 1 and (qt > ptime + (60.0 if entry_mode == 0 else 180.0) or qt >= entry_end):
                pending = 0
                canceled += 1

            # ----------------------------------------
            # 判断と同rowでは約定せず、指値は反対気配の到達を必要とする。
            if pending and qr > prow:
                if pending == 1:
                    crossed = (entry_mode == 0 and not (execution_mode & 1)) or (pd == 1 and ask[i] <= plimit) or (pd == -1 and bid[i] >= plimit)
                    if crossed:
                        ep = (ask[i] if pd == 1 else bid[i]) if entry_mode == 0 else plimit
                        direction, held, original = pd, quantity, quantity
                        et, erow, ebar, risk = qt, qr, pbar, prisk
                        einfee = math.floor(quantity * fee + 1e-9)
                        cash -= einfee
                        peak, half_done = 0.0, False
                        parent += 1
                        pending = 0
                        fills += 1
                else:
                    # ----------------------------------------
                    # 返済指値は判断時Lastで固定し、期限又は場末で不可逆に成行へ戻す。
                    xp = bid[i] if direction == 1 else ask[i]
                    market_fallback = qt >= ptime + 30.0 or qt >= close_time or preason == 7
                    crosses = xp >= protected_limit if direction == 1 else xp <= protected_limit
                    if (execution_mode & 2) and not market_fallback and not crosses:
                        protected_waits += 1
                    else:
                        if (execution_mode & 2) and market_fallback and not crosses:
                            protected_fallbacks += 1
                        closed = min(pq, held)
                        xp = bid[i] if direction == 1 else ask[i]
                        gross = direction * (xp - ep) * closed * multiplier
                        outfee = math.floor(closed * fee + 1e-9)
                        inpart = einfee * closed / original
                        cash += gross - outfee
                        ledger[count, 0] = parent
                        ledger[count, 1] = erow
                        ledger[count, 2] = qr
                        ledger[count, 3] = et
                        ledger[count, 4] = qt
                        ledger[count, 5] = direction
                        ledger[count, 6] = closed
                        ledger[count, 7] = ep
                        ledger[count, 8] = xp
                        ledger[count, 9] = gross
                        ledger[count, 10] = inpart
                        ledger[count, 11] = outfee
                        ledger[count, 12] = gross - inpart - outfee
                        ledger[count, 13] = preason
                        ledger[count, 14] = ebar
                        ledger[count, 15] = qt - ptime
                        count += 1
                        held -= closed
                        pending = 0
                        fills += 1
                        if held == 0:
                            direction = 0
                            cooldown = last_bar + 2

            equity = cash
            if held:
                xp = bid[i] if direction == 1 else ask[i]
                run = direction * (xp - ep)
                equity += run * held * multiplier - math.floor(held * fee + 1e-9)
                peak = max(peak, run)
            high_equity = max(high_equity, equity)
            max_drawdown = max(max_drawdown, high_equity - equity)

            # ----------------------------------------
            # 場予算は返済発注の起点であり、次気配の約定額を保証しない。
            if guard and math.isfinite(session_risk) and halted == 0:
                if equity <= -(2.0 if guard == 2 else 3.0) * session_risk:
                    halted = 5
                elif guard == 1 and equity >= 1.5 * session_risk:
                    halted = 6
            if qt >= close_time:
                halted = 7
            if halted and pending == 1:
                pending = 0
                canceled += 1
            reason = 0
            close_qty = held
            if held and pending != 2:
                if halted:
                    reason = halted
                elif run <= -(1.2 if exit_mode == 0 else 1.0) * risk:
                    reason = 1
                elif (exit_mode == 0 and run >= .8 * risk) or (exit_mode == 3 and run >= 2.0 * risk) or (exit_mode == 5 and run >= risk):
                    reason = 2
                elif (exit_mode == 1 and peak >= risk and run <= peak - risk) or (exit_mode == 4 and peak >= risk and run <= peak - .5 * risk):
                    reason = 3
                elif exit_mode == 2:
                    if not half_done and original >= 2 and run >= risk:
                        reason, close_qty = 8, original // 2
                        half_done = True
                    elif peak >= 1.5 * risk and run <= peak - 1.25 * risk:
                        reason = 3
                if reason:
                    pending, pq, prow, ptime, preason = 2, close_qty, qr, qt, reason
                    base = last[i] - direction * 2.0 * observed_tick
                    protected_limit = (math.ceil(base / order_tick) if direction == 1 else math.floor(base / order_tick)) * order_tick if order_tick > 0 else base

        else:
            b = i
            last_bar = b
            pr, pt = pub_rows[b], pub_times[b]
            if math.isfinite(latest_bid) and latest_row <= pr and pt - latest_time <= 60.0:
                equity = cash
                if held:
                    xp = latest_bid if direction == 1 else latest_ask
                    equity += direction * (xp - ep) * held * multiplier - math.floor(held * fee + 1e-9)
                trace[b], positions[b] = equity, direction
            if held and pending != 2 and ((direction == 1 and exit_long[b]) or (direction == -1 and exit_short[b])):
                pending, pq, prow, ptime, preason = 2, held, pr, pt, 4
                base = anchor[b] - direction * 2.0 * observed_tick
                protected_limit = (math.ceil(base / order_tick) if direction == 1 else math.floor(base / order_tick)) * order_tick if order_tick > 0 else base
            if not valid[b] or not math.isfinite(widths[b]) or widths[b] <= 0:
                if pending == 1:
                    pending = 0
                    canceled += 1
                continue
            if not math.isfinite(session_risk):
                session_risk = widths[b] * quantity * multiplier
            d = int(entry[b])
            if pending == 1 and d != 0 and d != pd:
                pending = 0
                canceled += 1
            if held == 0 and pending == 0 and not halted and pt < entry_end and b >= cooldown and d != 0:
                # ----------------------------------------
                # 発注後の悪い気配を消さず、発注時の審査と固定価格上限で保護する。
                if execution_mode & 1:
                    fresh = math.isfinite(latest_bid) and latest_row <= pr and pt - latest_time <= 60.0
                    side_price = latest_ask if d == 1 else latest_bid
                    normal = fresh and latest_ask - latest_bid <= 2.0 * observed_tick + 1e-9
                    normal = normal and abs(side_price - anchor[b]) <= 2.0 * observed_tick + 1e-9
                    if not normal:
                        rejected_entries += 1
                        continue
                pending, pd, prow, ptime, pbar, prisk = 1, d, pr, pt, b, widths[b]
                plimit = anchor[b] - d * .2 * widths[b]
                if (execution_mode & 1) and entry_mode == 0:
                    plimit = anchor[b] + d * 2.0 * observed_tick
                if order_tick > 0:
                    plimit = (math.floor(plimit / order_tick) if d == 1 else math.ceil(plimit / order_tick)) * order_tick

    # ----------------------------------------
    # EOF残玉は最後に観測できた反対気配で参考評価し、実返済とは別に返す。
    final_equity = cash
    if held and math.isfinite(latest_bid):
        xp = latest_bid if direction == 1 else latest_ask
        final_equity += direction * (xp - ep) * held * multiplier - math.floor(held * fee + 1e-9)
    return ledger[:count].copy(), trace, positions, cash, final_equity, held, max_drawdown, canceled, fills, halted, protected_fallbacks, protected_waits, rejected_entries


def market_events(bars: dict, quotes: dict) -> dict:
    """
    機能: 原row昇順、同rowは気配観測→足公開の順でイベントを構成する。
    引数: bars(dict) は公開足、quotes(dict) は原順の正常気配。
    返り値: dict。未来の気配を公開時の資産へ混ぜない実行順配列。
    """
    good = bars['valid'] & np.isfinite(bars['anchor']) & (bars['pub_raw_row'] >= 0)
    good &= (bars['pub_price_time_s'] - bars['t_s'] >= 0.0) & (bars['pub_price_time_s'] - bars['t_s'] <= 60.0)
    bi = np.flatnonzero(good)
    kinds = np.concatenate((np.zeros(len(quotes['row']), np.int8), np.ones(len(bi), np.int8)))
    indexes = np.concatenate((np.arange(len(quotes['row']), dtype=np.int64), bi))
    rows = np.concatenate((quotes['row'], bars['pub_raw_row'][bi]))
    order = np.lexsort((kinds, rows))
    return dict(events=kinds[order], indexes=indexes[order], good=good)


def run_policy(bars: dict, quotes: dict, policy: dict, settings: dict, events: dict | None = None) -> dict:
    """
    機能: 一つの固定政策を実行し、親単位の損益と場全体資産を分けて返す。
    引数: bars/quotes(dict)、policy(dict) は方向と退出、settings(dict) は数量・出口・費用。
    返り値: dict。返済明細・既知資産軌跡・集計。未返済があれば昇格資格を与えない。
    """
    ev = market_events(bars, quotes) if events is None else events
    args = [ev['events'], ev['indexes'], quotes['row'], quotes['time'], quotes['bid'], quotes['ask'], quotes['last'],
            bars['pub_raw_row'], bars['pub_price_time_s'], policy['entry'], policy['exit_long'],
            policy['exit_short'], policy['width'], policy['valid'] & ev['good'], bars['anchor']]
    result = replay(*args, settings['quantity'], settings['multiplier'], settings['fee'], settings['exit_mode'],
                    settings['entry_mode'], settings['guard'], settings['entry_end'], settings['close_time'], settings.get('order_tick', 0.), settings.get('execution_mode', 0), settings.get('observed_tick', .5))
    ledger, trace, pos, cash, equity, unclosed, drawdown, canceled, fills, halted, protected_fallbacks, protected_waits, rejected_entries = result
    groups = [ledger[ledger[:, 0] == parent, 12].sum() for parent in np.unique(ledger[:, 0])]
    profit = float(sum(max(0., net) for net in groups))
    loss = float(sum(max(0., -net) for net in groups))
    if unclosed == 0:
        assert abs((profit - loss) - cash) <= 1e-5
    summary = dict(net=float(equity), realized=float(cash), profit=profit, loss=loss,
        parents=len(groups), wins=sum(net > 1e-7 for net in groups), losses=sum(net < -1e-7 for net in groups),
        closed_quantity=int(ledger[:, 6].sum()) if len(ledger) else 0,
        fees=float(ledger[:, 9].sum() - cash) if len(ledger) else float(-cash),
        unclosed=int(unclosed), max_drawdown=float(drawdown), canceled=int(canceled), fills=int(fills), halted=int(halted), protected_fallbacks=int(protected_fallbacks), protected_wait_rows=int(protected_waits), rejected_entries=int(rejected_entries))
    return dict(summary=summary, ledger=ledger, equity=trace, position=pos)
