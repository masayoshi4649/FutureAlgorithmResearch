"""過去モデルの乖離を固定し、実際の復帰を二価格時計で確認して二脚を予約する。"""

from __future__ import annotations

import math
import os
from pathlib import Path

import numpy as np
from numba import njit, config


HERE = Path(__file__).resolve().parent
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'numba_runtime')
config.CACHE_DIR = str(HERE / 'numba_runtime')
ORDER_COLUMNS = ['parent', 'leg', 'kind', 'side', 'quantity', 'decision_time',
    'fill_time', 'raw_row', 'price', 'fee', 'reason', 'reference_price',
    'reference_quote_time', 'wait_seconds']
PARENT_COLUMNS = ['parent', 'complete', 'side_nk', 'decision_time', 'exit_decision_time',
    'reason', 'beta', 'center', 'sigma', 'entry_delta', 'cash_loss_budget',
    'estimated_roundtrip_cost', 'target_quantity_nk', 'target_quantity_top',
    'entry_nk', 'entry_top', 'exit_nk', 'exit_top', 'entry_time_nk', 'entry_time_top',
    'exit_time_nk', 'exit_time_top', 'gross_nk', 'gross_top', 'fees_nk', 'fees_top',
    'net_nk', 'net_top', 'net', 'filled_legs', 'single_leg_seconds',
    'maximum_single_leg_notional', 'maximum_held_quote_age', 'entry_hedge_error',
    'actual_entry_hedge_error', 'mfe_liquidation_net', 'mae_liquidation_net',
    'preparation_id', 'prepare_time', 'prepare_delta', 'extreme_delta',
    'confirmation_clock_1', 'confirmation_clock_2', 'expected_center_gross',
    'reserve_reference_nk', 'reserve_reference_top']
PREPARATION_COLUMNS = ['preparation_id', 'prepare_time', 'delta_sign', 'prepare_delta',
    'beta', 'center', 'sigma', 'extreme_delta', 'confirmation_clock_1',
    'confirmation_clock_2', 'reserve_time', 'reserve_delta', 'cash_loss_budget',
    'expected_center_gross', 'estimated_roundtrip_cost', 'quantity_nk', 'quantity_top',
    'reference_nk', 'reference_top', 'state', 'state_time']
CURVE_COLUMNS = ['time', 'realized', 'unrealized_after_close_fees', 'equity',
    'quantity_nk', 'quantity_top', 'quote_age_nk', 'quote_age_top', 'active_parent',
    'armed', 'drawdown', 'unclosed_legs']
MODEL_COLUMNS = ['time', 'known', 'beta', 'center', 'sigma', 'delta', 'quantity_nk',
    'quantity_top', 'hedge_error', 'expected_center_gross', 'estimated_roundtrip_cost',
    'candidate_side_nk', 'accepted', 'quote_age_nk', 'quote_age_top', 'armed', 'busy']
REASONS = {0: '未清算の参考時価', 1: '固定中心へ復帰', 2: '準備後の固定極値へ逆戻り',
           3: '組清算時価の円損失', 4: '未約定脚の六十価格秒期限', 5: '場末返済',
           6: '一標準偏差の改善後に半標準偏差戻り'}


def _quotes(value: dict) -> None:
    """
    機能: 既所有の正常気配が自身の原行順と価格時計順を保つことを確認する。
    引数: value(dict)はrow/time/last/bid/askを含む正常気配列。
    返り値: None。正常でない価格を補間したり市場を読み込んだりしない。
    """
    n = len(value['row'])
    assert all(np.asarray(value[key]).shape == (n,) for key in ('row', 'time', 'last', 'bid', 'ask', 'bq', 'aq'))
    assert np.issubdtype(np.asarray(value['row']).dtype, np.integer)
    assert np.all(np.diff(value['row']) > 0)
    assert np.all(np.diff(value['time']) >= 0)
    assert all(np.isfinite(value[k]).all() for k in ('time', 'last', 'bid', 'ask', 'bq', 'aq'))
    assert np.all((value['last'] > 0) & (value['bid'] > 0) & (value['ask'] > value['bid']))
    assert np.all((value['bq'] > 0) & (value['aq'] > 0))


def model_history(nk: dict, top: dict, clocks: np.ndarray, method: str, lookback: int) -> np.ndarray:
    """
    機能: 判断時計より一分以上前の連続一致足だけで局所モデルを求める。
    引数: nk/top(dict)は足、clocks(ndarray[float64])は固定判断時計、method(str)/lookback(int)は仮説。
    返り値: ndarray[N,4]はknown/beta/center/sigma。未知を零分散へ救済しない。
    """
    assert method in ('ratio_mr', 'ols_mr') and lookback in (30, 60)
    result = np.full((len(clocks), 4), np.nan)
    result[:, 0] = 0.
    for bars in (nk, top):
        n = len(bars['t_s'])
        assert all(np.asarray(bars[key]).shape == (n,) for key in ('valid', 'close', 'pub_price_time_s'))
        assert np.isfinite(bars['t_s']).all() and np.all(np.diff(bars['t_s']) == 60.)
    for i, now in enumerate(clocks):
        wanted = now - 60. * np.arange(lookback, 0, -1)
        indexes = [np.searchsorted(bars['t_s'], wanted) for bars in (nk, top)]
        if any(np.any(ix >= len(bars['t_s'])) for ix, bars in zip(indexes, (nk, top))):
            continue
        if any(not np.array_equal(bars['t_s'][ix], wanted) for ix, bars in zip(indexes, (nk, top))):
            continue
        if any(not np.all(bars['valid'][ix] & np.isfinite(bars['close'][ix]) & (bars['close'][ix] > 0)
                & np.isfinite(bars['pub_price_time_s'][ix]) & (bars['pub_price_time_s'][ix] >= bars['t_s'][ix])
                & (bars['pub_price_time_s'][ix] <= now))
                for ix, bars in zip(indexes, (nk, top))):
            continue
        y = np.log(nk['close'][indexes[0]])
        x = np.log(top['close'][indexes[1]])
        if method == 'ratio_mr':
            beta = 1.
        else:
            xc, yc = x - x.mean(), y - y.mean()
            denominator = float(xc @ xc)
            if denominator <= 1e-24:
                continue
            beta = float(xc @ yc / denominator)
            if not .2 <= beta <= 5.:
                continue
        center = float(np.mean(y - beta * x))
        sigma = float(np.std(y - beta * x, ddof=1))
        if not math.isfinite(sigma) or sigma <= 1e-12:
            continue
        result[i] = 1., beta, center, sigma
    return result


@njit(cache=True)
def choose_quantities(pn, pt, beta):
    """
    機能: 両小口上限の全正整数から最小β元本差の組を一意に選ぶ。
    引数: pn/pt/beta(float)は公開時の現在値と固定する係数。
    返り値: tuple[int,int,float]はNK枚数/TOP枚数/平均元本基準誤差。資格なしは零枚とNaN。
    """
    best, gross_best, best_n, best_t = 1e100, 1e100, 0, 0
    for qn in range(1, 21):
        for qt in range(1, 11):
            a, b = beta * qn * 10. * pn, qt * 1000. * pt
            error = abs(a - b) / ((a + b) / 2.)
            gross = qn * 10. * pn + b
            if error > .05 + 1e-12:
                continue
            improve = error < best - 1e-12
            tie = abs(error - best) <= 1e-12
            if improve or (tie and (gross < gross_best - 1e-9
                    or (abs(gross - gross_best) <= 1e-9 and (qn < best_n or (qn == best_n and qt < best_t))))):
                best, gross_best, best_n, best_t = error, gross, qn, qt
    return best_n, best_t, best if best_n else np.nan


@njit(cache=True)
def _mark(cash, held, sides, entries, bid, ask):
    """
    機能: 現実現と両脚返済側気配から費用後清算時価を評価する。
    引数: cash/held/sides/entries/bid/ask(ndarray[2])は当時までの状態。
    返り値: tuple[float,ndarray]は組全体資産と脚別含み。返済料を各脚一注文分だけ見込む。
    """
    unrealized = np.zeros(2)
    for leg in range(2):
        if held[leg] > 0:
            multiplier, fee = (10., 11.) if leg == 0 else (1000., 41.8)
            price = bid[leg] if sides[leg] == 1 else ask[leg]
            unrealized[leg] = sides[leg] * (price - entries[leg]) * held[leg] * multiplier - math.floor(held[leg] * fee + 1e-9)
    return cash.sum() + unrealized.sum(), unrealized


@njit(cache=True)
def _parent(parent, complete, side, order_time, close_time, reason, beta, center, sigma,
            delta, expected, cost, target, ep, xp, et, xt, gross, fees, cash, before,
            unpnl, single, max_single, max_age, hedge, mfe, mae):
    """
    機能: 実際に一脚以上約定した組の会計と固定モデルを保存列へ変換する。
    引数: 固定モデルと時刻・枚数・価格・費用・資産の数値又は二脚配列。
    返り値: ndarray[37]は完結又は未清算の親。未約定脚はNaN価格のまま保持する。
    """
    row = np.full(37, np.nan)
    row[:14] = np.array([parent, complete, side, order_time, close_time, reason, beta, center,
                         sigma, delta, expected, cost, target[0], target[1]])
    row[14:22] = np.array([ep[0], ep[1], xp[0], xp[1], et[0], et[1], xt[0], xt[1]])
    row[22:26] = np.array([gross[0], gross[1], fees[0], fees[1]])
    leg_net = cash - before + unpnl
    filled = int(math.isfinite(ep[0])) + int(math.isfinite(ep[1]))
    actual_error = np.nan
    if filled == 2:
        a, b = beta * target[0] * 10. * ep[0], target[1] * 1000. * ep[1]
        actual_error = abs(a - b) / ((a + b) / 2.)
    row[26:] = np.array([leg_net[0], leg_net[1], leg_net.sum(), filled, single, max_single,
                         max_age, hedge, actual_error, mfe, mae])
    return row


@njit(cache=True)
def _record_parent(base, binding):
    """
    機能: v5会計三十七列を維持し、当時の準備と二確認時計を結合する。
    引数: base(ndarray[37])は実会計、binding(ndarray[9])は予約時固定の系譜。
    返り値: ndarray[46]は会計と入口根拠。未来の極値を使わない。
    """
    result = np.empty(46)
    result[:37], result[37:] = base, binding
    return result


@njit(cache=True)
def replay(event_time, event_kind, event_index, clocks, history,
           nr, nt, nb, na, nl, tr, tt, tb, ta, tl, entry_end, force_time, exit_mode):
    """
    機能: 同時計の正常気配と既注文fillを先に処理し、共同snapshotで組を評価する。
    引数: イベント・モデル・正常気配(ndarray)、締切(float)、exit_mode(int)は極値撤回又は追尾。
    返り値: tupleは注文・親・毎分資産・モデル・累計値。未清算をEOFで返済したことにしない。
    """
    orders = np.full((len(clocks) * 4 + 8, 14), np.nan)
    parents = np.full((len(clocks) + 2, 46), np.nan)
    preparations = np.full((len(clocks) + 2, 21), np.nan)
    curve = np.full((len(clocks), 12), np.nan)
    models = np.full((len(clocks), 17), np.nan)
    cash, held, sides = np.zeros(2), np.zeros(2, np.int64), np.zeros(2, np.int64)
    last, bid, ask, quote_time = np.full(2, np.nan), np.full(2, np.nan), np.full(2, np.nan), np.full(2, np.nan)
    target, waiting = np.zeros(2, np.int64), np.zeros(2, np.bool_)
    ep, xp, et, xt = np.full(2, np.nan), np.full(2, np.nan), np.full(2, np.nan), np.full(2, np.nan)
    entry_ref, entry_ref_time = np.full(2, np.nan), np.full(2, np.nan)
    gross, fees, before = np.zeros(2), np.zeros(2), np.zeros(2)
    all_gross, all_fees = np.zeros(2), np.zeros(2)
    accepted, no_fill, canceled, norder, nparent = 0, 0, 0, 0, 0
    active, closing, armed = False, False, False
    parent, side, reason, halted = -1, 0, 0, 0
    order_time, close_time, expected, cost, delta, beta, center, sigma, hedge = 0., np.nan, 0., 0., 0., 1., 0., 1., 0.
    arm_beta, arm_center, arm_sign = 1., 0., 0
    prepared, group_quote = False, False
    nprepare, prepare_id, confirm_count = 0, -1, 0
    prepare_time, prepare_delta, prep_beta, prep_center, prep_sigma = np.nan, np.nan, 1., 0., 1.
    extreme, stop_extreme, confirm1, confirm2, best_improvement = 0., 0., np.nan, np.nan, 0.
    binding = np.full(9, np.nan)
    single, max_single, max_age, all_single, all_max_single = 0., 0., 0., 0., 0.
    previous_time, peak, maxdd, mfe, mae = np.nan, 0., 0., 0., 0.
    for event in range(len(event_time)):
        now, kind, index = event_time[event], event_kind[event], event_index[event]
        count_held = int(held[0] > 0) + int(held[1] > 0)
        if math.isfinite(previous_time) and count_held == 1:
            elapsed = now - previous_time
            single += elapsed
            all_single += elapsed
        previous_time = now
        if kind < 2:
            group_quote = True
            if kind == 0:
                qr, qp, qb, qa, ql = nr[index], nt[index], nb[index], na[index], nl[index]
            else:
                qr, qp, qb, qa, ql = tr[index], tt[index], tb[index], ta[index], tl[index]
            bid[kind], ask[kind], last[kind], quote_time[kind] = qb, qa, ql, qp

        # ----------------------------------------
        # 既知の時刻期限を先に処理する。将来の不利価格で注文を撤回しない。
        if now >= force_time:
            halted = 5
        timeout = active and (waiting[0] or waiting[1]) and now >= order_time + 60.
        if active and not closing and (halted or timeout):
            closing, close_time, reason = True, now, 5 if halted else 4
            for leg in range(2):
                if waiting[leg]:
                    waiting[leg] = False
                    canceled += 1
        if kind < 2 and active:
            leg = kind
            multiplier, fee = (10., 11.) if leg == 0 else (1000., 41.8)
            if closing and held[leg] > 0 and now > close_time:
                price = qb if sides[leg] == 1 else qa
                paid = math.floor(held[leg] * fee + 1e-9)
                gain = sides[leg] * (price - ep[leg]) * held[leg] * multiplier
                cash[leg] += gain - paid
                gross[leg] += gain
                fees[leg] += paid
                all_gross[leg] += gain
                all_fees[leg] += paid
                orders[norder] = np.array([parent, leg, 2, -sides[leg], held[leg], close_time,
                    now, qr, price, paid, reason, np.nan, np.nan, now - close_time])
                norder += 1
                held[leg] = 0
                xp[leg], xt[leg] = price, now
            elif not closing and waiting[leg] and now > order_time:
                price = qa if sides[leg] == 1 else qb
                paid = math.floor(target[leg] * fee + 1e-9)
                held[leg], waiting[leg] = target[leg], False
                ep[leg], et[leg] = price, now
                cash[leg] -= paid
                fees[leg] += paid
                all_fees[leg] += paid
                orders[norder] = np.array([parent, leg, 1, sides[leg], target[leg], order_time,
                    now, qr, price, paid, 0, entry_ref[leg], entry_ref_time[leg], now - order_time])
                norder += 1

        # ----------------------------------------
        # 同時計の途中だけに存在する相対乖離・資産上下を売買判断へ混ぜない。
        # minuteは同時計quoteの後。EOFでは観測済み末尾だけを使い未来行で補わない。
        if event + 1 < len(event_time) and event_time[event + 1] == now:
            continue
        price_group = group_quote
        group_quote = False
        age_n = now - quote_time[0] if math.isfinite(quote_time[0]) else np.nan
        age_t = now - quote_time[1] if math.isfinite(quote_time[1]) else np.nan
        fresh = math.isfinite(age_n) and math.isfinite(age_t) and 0. <= age_n <= 5. and 0. <= age_t <= 5.
        equity, unpnl = _mark(cash, held, sides, ep, bid, ask)
        if active:
            parent_net = equity - before.sum()
            mfe, mae = max(mfe, parent_net), min(mae, parent_net)
            for leg in range(2):
                if held[leg] > 0:
                    max_age = max(max_age, now - quote_time[leg])
            count_held = int(held[0] > 0) + int(held[1] > 0)
            if count_held == 1:
                leg = 0 if held[0] else 1
                nominal = held[leg] * (10. if leg == 0 else 1000.) * (bid[leg] + ask[leg]) / 2.
                max_single, all_max_single = max(max_single, nominal), max(all_max_single, nominal)
            if not closing and math.isfinite(last[0]) and math.isfinite(last[1]):
                residual = math.log(last[0]) - beta * math.log(last[1]) - center
                entry_sign = -side
                why = 0
                if entry_sign * residual <= 0.:
                    why = 1
                elif entry_sign * residual >= stop_extreme:
                    why = 2
                elif parent_net <= -expected:
                    why = 3
                if not why and exit_mode == 1:
                    improvement = entry_sign * (delta - residual)
                    best_improvement = max(best_improvement, improvement)
                    if best_improvement >= sigma and improvement <= best_improvement - .5 * sigma:
                        why = 6
                if why:
                    closing, close_time, reason = True, now, why
                    for leg in range(2):
                        if waiting[leg]:
                            waiting[leg] = False
                            canceled += 1
            if not (waiting[0] or waiting[1]) and held.sum() == 0:
                if math.isfinite(ep[0]) or math.isfinite(ep[1]):
                    parents[nparent] = _record_parent(_parent(parent, 1., side, order_time, close_time, reason,
                        beta, center, sigma, delta, expected, cost, target, ep, xp, et, xt,
                        gross, fees, cash, before, np.zeros(2), single, max_single, max_age,
                        hedge, mfe, mae), binding)
                    nparent += 1
                else:
                    no_fill += 1
                active, closing = False, False
        # ----------------------------------------
        # 準備の固定モデルが中心へ戻るまで同じ波を再利用しない。
        # 実保有が終わる前にarmを解除せず、完結後の共同正常価格で確認する。
        if armed and not active and price_group and fresh:
            arm_delta = math.log(last[0]) - arm_beta * math.log(last[1]) - arm_center
            if arm_sign * arm_delta <= 0.:
                armed = False
                if prepared:
                    preparations[prepare_id, 19:21] = np.array([2., now])
                    prepared = False
        if prepared and now >= entry_end:
            preparations[prepare_id, 19:21] = np.array([3., now])
            prepared = False
        # ----------------------------------------
        # 極値・復帰・二確認は全同時計quote後だけで評価する。
        # 候補時計の途中、将来価格又はモデル再推定で確認を救済しない。
        if prepared and not active and price_group and now > prepare_time:
            if not fresh:
                confirm_count, confirm1, confirm2 = 0, np.nan, np.nan
            else:
                current = math.log(last[0]) - prep_beta * math.log(last[1]) - prep_center
                signed = arm_sign * current
                if signed > extreme:
                    extreme = signed
                    confirm_count, confirm1, confirm2 = 0, np.nan, np.nan
                elif extreme - signed >= .5 * prep_sigma and signed >= prep_sigma:
                    if confirm_count == 0:
                        confirm_count, confirm1 = 1, now
                    elif confirm_count == 1 and now > confirm1:
                        confirm_count, confirm2 = 2, now
                else:
                    confirm_count, confirm1, confirm2 = 0, np.nan, np.nan
                preparations[prepare_id, 7] = arm_sign * extreme
                preparations[prepare_id, 8:10] = np.array([confirm1, confirm2])
                if confirm_count >= 2 and not halted and now < entry_end:
                    qn, qt, error = choose_quantities(last[0], last[1], prep_beta)
                    if qn:
                        nominal = qn * 10. * last[0]
                        goal = signed * nominal
                        roundtrip_fee = 2. * (math.floor(qn * 11. + 1e-9) + math.floor(qt * 41.8 + 1e-9))
                        estimated = roundtrip_fee + qn * 10. * (ask[0] - bid[0]) + qt * 1000. * (ask[1] - bid[1])
                        budget = (extreme - signed) * nominal + roundtrip_fee
                        if goal >= 3. * estimated:
                            parent, accepted = accepted, accepted + 1
                            side, beta, center, sigma, delta, hedge = -arm_sign, prep_beta, prep_center, prep_sigma, current, error
                            target[0], target[1] = qn, qt
                            sides[0], sides[1] = side, -side
                            waiting[:] = True
                            ep[:], xp[:], et[:], xt[:] = np.nan, np.nan, np.nan, np.nan
                            gross[:], fees[:], before[:] = 0., 0., cash
                            entry_ref[:], entry_ref_time[:] = last, quote_time
                            order_time, expected, cost, close_time, reason = now, budget, estimated, np.nan, 0
                            active, closing, prepared = True, False, False
                            stop_extreme, best_improvement = extreme, 0.
                            single, max_single, max_age, mfe, mae = 0., 0., 0., 0., 0.
                            binding = np.array([prepare_id, prepare_time, prepare_delta, arm_sign * extreme,
                                confirm1, confirm2, goal, last[0], last[1]])
                            preparations[prepare_id, 10:19] = np.array([now, current, budget, goal, estimated, qn, qt, last[0], last[1]])
                            preparations[prepare_id, 19:21] = np.array([1., now])
            if prepared:
                preparations[prepare_id, 8:10] = np.array([confirm1, confirm2])
        peak = max(peak, equity)
        maxdd = max(maxdd, peak - equity)

        # ----------------------------------------
        # 同秒の両市場正常気配を先に観測し、minute判断ではその時点までの値だけを使う。
        if kind == 2:
            i = index
            age_n = now - quote_time[0] if math.isfinite(quote_time[0]) else np.nan
            age_t = now - quote_time[1] if math.isfinite(quote_time[1]) else np.nan
            candidate, qn, qt, error, goal, estimated, current_delta = 0, 0, 0, np.nan, np.nan, np.nan, np.nan
            known, b, a, sd = history[i, 0], history[i, 1], history[i, 2], history[i, 3]
            if known and math.isfinite(last[0]) and math.isfinite(last[1]):
                current_delta = math.log(last[0]) - b * math.log(last[1]) - a
                if abs(current_delta) >= 2. * sd:
                    candidate = -1 if current_delta > 0 else 1
                    qn, qt, error = choose_quantities(last[0], last[1], b)
                    if qn:
                        goal = abs(current_delta) * qn * 10. * last[0]
                        estimated = 2. * (math.floor(qn * 11. + 1e-9) + math.floor(qt * 41.8 + 1e-9))
                        estimated += qn * 10. * (ask[0] - bid[0]) + qt * 1000. * (ask[1] - bid[1])
            models[i] = np.array([now, known, b, a, sd, current_delta, qn, qt, error,
                goal, estimated, candidate, 0., age_n, age_t, 1. if armed else 0., 1. if active else 0.])
            if not active and not armed and not halted and now < entry_end and candidate and fresh:
                prepare_id, nprepare = nprepare, nprepare + 1
                prepare_time, prepare_delta, prep_beta, prep_center, prep_sigma = now, current_delta, b, a, sd
                arm_beta, arm_center, arm_sign = b, a, -candidate
                extreme, confirm_count, confirm1, confirm2 = abs(current_delta), 0, np.nan, np.nan
                armed, prepared = True, True
                preparations[prepare_id, :8] = np.array([prepare_id, now, arm_sign, current_delta, b, a, sd, current_delta])
                preparations[prepare_id, 19:21] = np.array([0., now])
            if active and order_time == now:
                models[i] = np.array([now, 1., beta, center, sigma, delta, target[0], target[1], hedge,
                    binding[6], cost, side, 1., age_n, age_t, 1., 1.])
            curve[i] = np.array([now, cash.sum(), unpnl.sum(), equity,
                held[0] * sides[0], held[1] * sides[1], age_n, age_t,
                parent if active else -1, 1. if armed else 0., peak - equity,
                int(held[0] > 0) + int(held[1] > 0)])
    equity, unpnl = _mark(cash, held, sides, ep, bid, ask)
    if active and (math.isfinite(ep[0]) or math.isfinite(ep[1])):
        parents[nparent] = _record_parent(_parent(parent, 0., side, order_time, close_time, reason,
            beta, center, sigma, delta, expected, cost, target, ep, xp, et, xt,
            gross, fees, cash, before, unpnl, single, max_single, max_age, hedge, mfe, mae), binding)
        nparent += 1
    if prepared:
        preparations[prepare_id, 19:21] = np.array([4., event_time[-1] if len(event_time) else np.nan])
    counts = np.array([accepted, no_fill, canceled, halted, held[0], held[1],
        maxdd, all_single, all_max_single, waiting[0], waiting[1]], np.float64)
    return orders[:norder].copy(), parents[:nparent].copy(), curve, models, preparations[:nprepare].copy(), cash, unpnl, all_gross, all_fees, counts


def run_pair(nk_bars: dict, top_bars: dict, nk_quotes: dict, top_quotes: dict, settings: dict) -> dict:
    """
    機能: 四つの固定NT仮説のうち一つを、保存入力又は人工入力から完全に因果運転する。
    引数: nk_bars/top_bars(dict)は確定足、nk_quotes/top_quotes(dict)は正常気配、settings(dict)は仮説・出口と当場締切。
    返り値: dictはsummary/leg_summary/orders/parents/curve/models/preparations/positionsと列名。市場を読み書きしない。
    """
    _quotes(nk_quotes)
    _quotes(top_quotes)
    method, lookback = settings['method'], int(settings['lookback'])
    exit_mode = int(settings['exit_mode'])
    assert exit_mode in (0, 1)
    entry_end, force_time = float(settings['entry_end']), float(settings['close_time'])
    assert math.isfinite(entry_end) and math.isfinite(force_time) and entry_end < force_time
    source_clocks = np.union1d(nk_bars['t_s'] + 60., top_bars['t_s'] + 60.)
    observed_end = max(nk_quotes['time'][-1] if len(nk_quotes['time']) else -np.inf,
                       top_quotes['time'][-1] if len(top_quotes['time']) else -np.inf)
    clocks = source_clocks[source_clocks <= min(force_time, observed_end)]
    history = model_history(nk_bars, top_bars, clocks, method, lookback)
    times = np.concatenate((nk_quotes['time'], top_quotes['time'], clocks)).astype(np.float64)
    kinds = np.concatenate((np.zeros(len(nk_quotes['row']), np.int8), np.ones(len(top_quotes['row']), np.int8), np.full(len(clocks), 2, np.int8)))
    indexes = np.concatenate((np.arange(len(nk_quotes['row'])), np.arange(len(top_quotes['row'])), np.arange(len(clocks)))).astype(np.int64)
    raw_rows = np.concatenate((nk_quotes['row'], top_quotes['row'], np.zeros(len(clocks), np.int64)))
    order = np.lexsort((raw_rows, kinds, times))
    result = replay(times[order], kinds[order], indexes[order], clocks, history,
        nk_quotes['row'], nk_quotes['time'], nk_quotes['bid'], nk_quotes['ask'], nk_quotes['last'],
        top_quotes['row'], top_quotes['time'], top_quotes['bid'], top_quotes['ask'], top_quotes['last'], entry_end, force_time, exit_mode)
    orders, parents, curve, models, preparations, cash, unpnl, total_gross, total_fees, counters = result
    closed = parents[parents[:, 1] == 1.] if len(parents) else parents
    profits = float(np.maximum(closed[:, 28], 0.).sum())
    losses = float(np.maximum(-closed[:, 28], 0.).sum())
    net, realized = float(cash.sum() + unpnl.sum()), float(cash.sum())
    unclosed = int(counters[4] + counters[5])
    if not unclosed:
        assert abs(profits - losses - realized) < 1e-5
        assert abs(net - realized) < 1e-5
    if len(parents):
        assert np.all(np.abs(parents[:, 26] + parents[:, 27] - parents[:, 28]) < 1e-5)
    leg_summary = {}
    for leg, symbol in enumerate(('NK225', 'TOPIX')):
        legs = orders[orders[:, 1] == leg] if len(orders) else orders
        leg_summary[symbol] = dict(gross=float(total_gross[leg]), fees=float(total_fees[leg]),
            realized=float(cash[leg]), unrealized_after_close_fees=float(unpnl[leg]),
            net=float(cash[leg] + unpnl[leg]), fills=int(len(legs)),
            entry_quantity=int(legs[legs[:, 2] == 1., 4].sum()) if len(legs) else 0,
            closed_quantity=int(legs[legs[:, 2] == 2., 4].sum()) if len(legs) else 0,
            unclosed=int(counters[4 + leg]))
    summary = dict(net=net, realized=realized, profit=profits, loss=losses,
        parents=len(closed), wins=int(np.count_nonzero(closed[:, 28] > 1e-7)),
        losses=int(np.count_nonzero(closed[:, 28] < -1e-7)), fees=float(total_fees.sum()),
        unclosed=unclosed, max_drawdown=float(counters[6]), fills=len(orders),
        closed_quantity=int(orders[orders[:, 2] == 2., 4].sum()) if len(orders) else 0,
        canceled=int(counters[2]), halted=int(counters[3]), attempts=int(counters[0]),
        no_fill_attempts=int(counters[1]), paired_parents=int(np.count_nonzero(closed[:, 29] == 2.)),
        aborted_parents=int(np.count_nonzero(closed[:, 29] == 1.)),
        single_leg_seconds=float(counters[7]), max_single_leg_notional=float(counters[8]),
        expected_close_fees=float(sum(math.floor(counters[4 + leg] * fee + 1e-9) for leg, fee in enumerate((11., 41.8)))),
        pending_entries=int(counters[9] + counters[10]), preparations=len(preparations),
        reserved_preparations=int(np.count_nonzero(preparations[:, 19] == 1.)) if len(preparations) else 0,
        canceled_preparations=int(np.count_nonzero((preparations[:, 19] == 2.) | (preparations[:, 19] == 3.))) if len(preparations) else 0,
        unfinished_preparations=int(np.count_nonzero(preparations[:, 19] == 4.)) if len(preparations) else 0)
    return dict(summary=summary, leg_summary=leg_summary, orders=orders, parents=parents,
        curve=curve, models=models, preparations=preparations, positions=curve[:, 4:6].astype(np.int64),
        order_columns=ORDER_COLUMNS, parent_columns=PARENT_COLUMNS,
        curve_columns=CURVE_COLUMNS, model_columns=MODEL_COLUMNS, preparation_columns=PREPARATION_COLUMNS)
