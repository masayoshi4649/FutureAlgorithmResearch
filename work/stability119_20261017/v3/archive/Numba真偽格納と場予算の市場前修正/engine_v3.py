"""試し玉の損失予算を固定した順行増加と、費用後建値・追尾を比較する。"""

import math
import os
from pathlib import Path

import numpy as np

os.environ.setdefault('NUMBA_CACHE_DIR', str(Path(__file__).resolve().parent / 'numba_runtime'))
from numba import njit

ORDER_COLUMNS = ('parent', 'kind', 'decision_raw_row', 'fill_raw_row', 'decision_time', 'fill_time',
                 'side', 'quantity', 'signed_quantity', 'price', 'fee', 'basket_quantity_after',
                 'wac_after', 'fixed_risk_width', 'stop_after')
PARENT_COLUMNS = ('parent', 'side', 'signal_bar', 'decision_raw_row', 'entry_raw_row', 'exit_raw_row',
                  'entry_time', 'exit_time', 'original_entry_price', 'wac', 'initial_quantity',
                  'max_quantity', 'closed_quantity', 'add_fills', 'fixed_risk_width',
                  'initial_loss_budget', 'entry_fees', 'exit_fee', 'gross', 'net', 'stop_reason',
                  'be_armed', 'final_stop', 'peak_close_price', 'mae_liquidation_net',
                  'mfe_liquidation_net', 'stop_source')
ORDER_KINDS = {1: '初回新規', 2: '順行追加', 3: '全返済'}
STOP_REASONS = {1: '有利側だけ更新する価格停止線', 4: '家族の撤回', 5: '場損失予算', 7: '場末'}
STOP_SOURCES = {1: '当初円損失予算', 2: '費用後バスケット建値', 3: '保険トレーリング'}


# ----------------------------------------


@njit(cache=True)
def charged_fee(quantity, fee):
    """
    機能: 実際の一注文枚数に対する手数料を円未満切捨てで求める。
    引数: quantity(int)、fee(float) は注文枚数と一枚片道料金。
    返り値: int。一括返済をlot毎の別料金にしない。
    """
    return int(math.floor(quantity * fee + 1e-9))


@njit(cache=True)
def advance_stop(side, current, candidate):
    """
    機能: 停止線を有利方向だけへ更新する。
    引数: side(int)、current/candidate(float) は方向と旧・候補価格。
    返り値: float は後退しない価格。
    """
    return max(current, candidate) if side == 1 else min(current, candidate)


@njit(cache=True)
def replay(events, indexes, rows, times, bid, ask, pub_rows, pub_times,
           entry, exit_long, exit_short, widths, valid,
           cap, multiplier, fee, allocation_mode, trail_multiple, entry_end, close_time):
    """
    機能: 初回固定予算を守る追加予約と次原row市場約定を逐次処理する。
    引数: events/indexes(int配列)、rows/times/bid/askは正常気配の原順配列。
        pub_rows/pub_times/entry/exit_long/exit_short/widths/validは公開時既知の一分列。
        cap/allocation_mode(int)、multiplier/fee/trail_multiple/entry_end/close_time(float)。
    返り値: tuple は実注文・完結親・公開時資産/方向/現金/下落/数量/停止線と最終集計。
        追加は予約時に段階を消費する。反対entryだけでは取消しない。価格時計を壁時計と呼ばない。
    """
    n = len(entry)
    orders = np.empty((len(rows)+4, 15), np.float64)
    parents = np.empty((len(rows)+4, 27), np.float64)
    traces = np.full((n, 5), np.nan)
    positions = np.zeros(n, np.int8)
    quantities = np.zeros(n, np.int64)
    oc = pc = 0
    parent = 0
    side = held = initial_qty = max_qty = parent_adds = 0
    wac = origin = risk = budget = entry_fees = 0.
    entry_row = entry_source = signal_bar = last_fill_row = -1
    entry_time = 0.
    stop = peak = 0.
    stop_source = 1
    be_armed = False
    local_min, local_max = np.inf, -np.inf
    stage = 0
    # ----------------------------------------
    # 初回又は追加の先行注文と、撤回・停止の全返済予約を別々に保持する。
    pending_kind = pending_side = pending_quantity = 0
    pending_row = pending_bar = -1
    pending_time = pending_risk = 0.
    close_pending = False
    close_row = -1
    close_time_decision = 0.
    close_reason = 0
    cash = paid = 0.
    high_equity = max_dd = 0.
    latest_bid = latest_ask = latest_time = np.nan
    latest_row = last_bar = -1
    session_risk = np.nan
    halted = canceled = fills = add_fills = global_max_qty = 0
    cooldown = -1
    for event in range(len(events)):
        i = indexes[event]
        if events[event] == 0:
            qr, qt = int(rows[i]), times[i]
            order_on_row = -1
            latest_bid, latest_ask, latest_time, latest_row = bid[i], ask[i], qt, qr
            if pending_kind and (qt > pending_time+60. or qt >= entry_end or halted or qt >= close_time):
                pending_kind = 0
                canceled += 1
            # ----------------------------------------
            # 予約済み追加は悪い到来気配でも約定する。約定後に新停止線を評価する。
            if pending_kind and qr > pending_row:
                q, kind = pending_quantity, pending_kind
                px = ask[i] if pending_side == 1 else bid[i]
                cost = charged_fee(q, fee)
                if kind == 1:
                    parent += 1
                    side, held, initial_qty, max_qty = pending_side, q, q, q
                    wac = origin = px
                    risk = pending_risk
                    budget = initial_qty*risk*multiplier+2*charged_fee(initial_qty, fee)
                    entry_fees = float(cost)
                    entry_row, last_fill_row, entry_source, signal_bar = qr, qr, pending_row, pending_bar
                    entry_time = qt
                    parent_adds = 0
                    stop = wac-side*risk
                    stop_source = 1
                    peak = bid[i] if side == 1 else ask[i]
                    be_armed = False
                    local_min, local_max = np.inf, -np.inf
                    stage = 0
                else:
                    assert held > 0 and side == pending_side and held+q <= cap
                    wac = (wac*held+px*q)/(held+q)
                    held += q
                    max_qty = max(max_qty, held)
                    parent_adds += 1
                    add_fills += 1
                    entry_fees += cost
                    last_fill_row = qr
                paid += cost
                cash -= cost
                closefee = charged_fee(held, fee)
                hard = wac+side*(entry_fees+closefee-budget)/(held*multiplier)
                updated = advance_stop(side, stop, hard)
                if updated != stop:
                    stop_source = 1
                stop = updated
                orders[oc] = np.array([parent, kind, pending_row, qr, pending_time, qt, side,
                    q, side*q, px, cost, held, wac, risk, stop])
                order_on_row = oc
                oc += 1
                fills += 1
                global_max_qty = max(global_max_qty, held)
                pending_kind = 0
            # ----------------------------------------
            # 先行追加が同行で約定した場合は全返済を更に後の原rowまで待つ。
            if close_pending and held and qr > close_row and qr > last_fill_row:
                px = bid[i] if side == 1 else ask[i]
                q = held
                outfee = charged_fee(q, fee)
                gross = side*(px-wac)*q*multiplier
                net = gross-entry_fees-outfee
                peak = max(peak, px) if side == 1 else min(peak, px)
                local_min, local_max = min(local_min, net), max(local_max, net)
                cash += gross-outfee
                paid += outfee
                orders[oc] = np.array([parent, 3., close_row, qr, close_time_decision, qt, -side,
                    q, -side*q, px, outfee, 0., wac, risk, stop])
                oc += 1
                parents[pc] = np.array([parent, side, signal_bar, entry_source, entry_row, qr,
                    entry_time, qt, origin, wac, initial_qty, max_qty, q, parent_adds,
                    risk, budget, entry_fees, outfee, gross, net, close_reason,
                    float(be_armed), stop, peak, local_min, local_max, stop_source])
                pc += 1
                fills += 1
                side = held = 0
                close_pending = False
                cooldown = last_bar+2
            # ----------------------------------------
            # 損失予算と建値は費用込み。追加しても予算は初回から不変である。
            equity = cash
            local = 0.
            if held:
                liquidation = bid[i] if side == 1 else ask[i]
                peak = max(peak, liquidation) if side == 1 else min(peak, liquidation)
                closefee = charged_fee(held, fee)
                local = side*(liquidation-wac)*held*multiplier-entry_fees-closefee
                equity += side*(liquidation-wac)*held*multiplier-closefee
                local_min, local_max = min(local_min, local), max(local_max, local)
                if side*(liquidation-origin) >= risk:
                    be_armed = True
                hard = wac+side*(entry_fees+closefee-budget)/(held*multiplier)
                updated = advance_stop(side, stop, hard)
                if updated != stop:
                    stop_source = 1
                stop = updated
                if be_armed:
                    breakeven = wac+side*(entry_fees+closefee)/(held*multiplier)
                    updated = advance_stop(side, stop, breakeven)
                    if updated != stop:
                        stop_source = 2
                    stop = updated
                    trailing = peak-side*trail_multiple*risk
                    updated = advance_stop(side, stop, trailing)
                    if updated != stop:
                        stop_source = 3
                    stop = updated
                if order_on_row >= 0:
                    orders[order_on_row, 14] = stop
            high_equity = max(high_equity, equity)
            max_dd = max(max_dd, high_equity-equity)
            if not halted:
                if math.isfinite(session_risk) and equity <= -2.*session_risk:
                    halted = 5
                elif qt >= close_time:
                    halted = 7
            if halted and pending_kind:
                pending_kind = 0
                canceled += 1
            if held and not close_pending:
                reason = halted if halted else (1 if side*(liquidation-stop) <= 0 else 0)
                if reason:
                    close_pending, close_row, close_time_decision, close_reason = True, qr, qt, reason
            if held and allocation_mode == 2 and not close_pending and not pending_kind and not halted and qt < entry_end:
                progress = side*(liquidation-origin)/risk
                level = 3 if progress >= 1.5 else (2 if progress >= 1. else (1 if progress >= .5 else 0))
                if level > stage:
                    stage = level
                    target = int(math.floor(cap*(.4 if level == 1 else .7 if level == 2 else 1.)+1e-9))
                    if target > held:
                        pending_kind, pending_side, pending_quantity = 2, side, target-held
                        pending_row, pending_time, pending_bar, pending_risk = qr, qt, signal_bar, risk
        else:
            b = i
            last_bar = b
            pr, pt = int(pub_rows[b]), pub_times[b]
            if math.isfinite(latest_bid) and latest_row <= pr and 0 <= pt-latest_time <= 60.:
                equity = cash
                if held:
                    px = latest_bid if side == 1 else latest_ask
                    equity += side*(px-wac)*held*multiplier-charged_fee(held, fee)
                traces[b, 0], traces[b, 1], traces[b, 2] = equity, cash, high_equity-equity
                traces[b, 3], traces[b, 4] = stop if held else np.nan, local if held else 0.
                positions[b], quantities[b] = side, held
            withdrawn = held and ((side == 1 and exit_long[b]) or (side == -1 and exit_short[b]))
            if withdrawn and not close_pending:
                close_pending, close_row, close_time_decision, close_reason = True, pr, pt, 4
            # ----------------------------------------
            # 反対entryは既送付注文の取消理由へ転用しない。validは新規審査だけで使う。
            if not valid[b] or not math.isfinite(widths[b]) or widths[b] <= 0:
                continue
            if not math.isfinite(session_risk):
                session_risk = widths[b]*cap*multiplier
            d = int(entry[b])
            if held == 0 and pending_kind == 0 and not close_pending and not halted and pt < entry_end and b >= cooldown and d != 0:
                q = cap if allocation_mode == 1 else max(1, int(math.floor(.2*cap+1e-9)))
                pending_kind, pending_side, pending_quantity = 1, d, q
                pending_row, pending_time, pending_bar, pending_risk = pr, pt, b, widths[b]
    # ----------------------------------------
    # 未返済は最後の既知反対気配で評価するだけ。EOFで架空の返済を作らない。
    final_equity = cash
    if held:
        px = latest_bid if side == 1 else latest_ask
        final_equity += side*(px-wac)*held*multiplier-charged_fee(held, fee)
    counters = np.array([cash, final_equity, held, max_dd, fills, canceled, halted, paid,
                         global_max_qty, add_fills, pending_kind, int(close_pending)])
    return orders[:oc].copy(), parents[:pc].copy(), traces, positions, quantities, counters


# ----------------------------------------


def market_events(bars: dict, quotes: dict) -> dict:
    """
    機能: 既119と同じ原row優先・同行気配観測先のイベント列を作る。
    引数: bars/quotes(dict[str,ndarray]) は公開足と正常気配。
    返り値: dict はevents/indexes/good。形成中の未来足を参照しない。
    """
    good = bars['valid'] & np.isfinite(bars['anchor']) & (bars['pub_raw_row'] >= 0)
    good &= (bars['pub_price_time_s']-bars['t_s'] >= 0.) & (bars['pub_price_time_s']-bars['t_s'] <= 60.)
    bi = np.flatnonzero(good)
    kinds = np.concatenate((np.zeros(len(quotes['row']), np.int8), np.ones(len(bi), np.int8)))
    indexes = np.concatenate((np.arange(len(quotes['row']), dtype=np.int64), bi))
    rows = np.concatenate((quotes['row'], bars['pub_raw_row'][bi]))
    order = np.lexsort((kinds, rows))
    return dict(events=kinds[order], indexes=indexes[order], good=good)


def run_policy(bars: dict, quotes: dict, policy: dict, settings: dict, events: dict | None = None) -> dict:
    """
    機能: 3配分と2保険幅の一つを因果原順で実行し、全注文・親・公開資産を返す。
    引数: bars/quotes/policy(dict) は既v2と同じ列、settings(dict) はquantity上限10/20・
        multiplier/fee/entry_end/close_time・allocation_mode(0/1/2)・trail_multiple(.5/1.)。
        events(dict|None) は既engine119.market_eventsの互換配列。
    返り値: dict はorders/parents(float2D)、equity/position/cash/drawdown/quantity/stop配列とsummary。
        初回・追加は60秒と新規締切で失効。反対entry又はvalid消失だけでは取消しない。
    """
    cap = int(settings['quantity'])
    mode = int(settings['allocation_mode'])
    trail = float(settings['trail_multiple'])
    assert cap in (10, 20) and mode in (0, 1, 2) and trail in (.5, 1.)
    assert settings.get('entry_mode', 0) == settings.get('execution_mode', 0) == 0
    assert settings.get('guard', 2) == 2
    assert settings['multiplier'] > 0 and settings['fee'] >= 0
    ev = market_events(bars, quotes) if events is None else events
    values = replay(ev['events'], ev['indexes'], quotes['row'], quotes['time'], quotes['bid'], quotes['ask'],
                    bars['pub_raw_row'], bars['pub_price_time_s'], policy['entry'], policy['exit_long'],
                    policy['exit_short'], policy['width'], policy['valid'] & ev['good'],
                    cap, float(settings['multiplier']), float(settings['fee']), mode, trail,
                    float(settings['entry_end']), float(settings['close_time']))
    orders, parents, traces, positions, quantities, counters = values
    realized, net, unclosed, dd, fills, canceled, halted, fees, maximum, adds, pending, closing = counters
    pnl = parents[:, PARENT_COLUMNS.index('net')]
    profit, loss = float(np.maximum(pnl, 0).sum()), float(-np.minimum(pnl, 0).sum())
    if unclosed == 0:
        assert abs(realized-profit+loss) < 1e-5
    assert (orders[:, ORDER_COLUMNS.index('quantity')] > 0).all()
    assert (orders[:, ORDER_COLUMNS.index('basket_quantity_after')] <= cap).all()
    assert np.all(orders[:, ORDER_COLUMNS.index('fill_raw_row')] > orders[:, ORDER_COLUMNS.index('decision_raw_row')])
    initial = orders[orders[:, ORDER_COLUMNS.index('kind')] == 1, ORDER_COLUMNS.index('quantity')]
    summary = dict(net=float(net), realized=float(realized), profit=profit, loss=loss, parents=len(parents),
        wins=int((pnl > 1e-7).sum()), losses=int((pnl < -1e-7).sum()),
        closed_quantity=int(parents[:, PARENT_COLUMNS.index('closed_quantity')].sum()), fees=float(fees),
        unclosed=int(unclosed), max_drawdown=float(dd), fills=int(fills), canceled=int(canceled), halted=int(halted),
        initial_quantity_min=int(initial.min()) if len(initial) else None,
        initial_quantity_max=int(initial.max()) if len(initial) else None,
        max_quantity=int(maximum), add_fills=int(adds), pending_entry_or_add=int(pending), pending_close=bool(closing))
    return dict(summary=summary, orders=orders, parents=parents, equity=traces[:, 0], position=positions,
                cash=traces[:, 1], drawdown=traces[:, 2], quantity=quantities, stop=traces[:, 3],
                parent_liquidation_net=traces[:, 4], order_columns=list(ORDER_COLUMNS), parent_columns=list(PARENT_COLUMNS))
