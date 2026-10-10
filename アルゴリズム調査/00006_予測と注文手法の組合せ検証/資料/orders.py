"""方向予測を使わない有限在庫の注文手法を全気配で再生する。"""

from __future__ import annotations

from pathlib import Path
import importlib.util
import hashlib
import numpy as np
import pandas as pd
from numba import njit

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location('wave_v11_orders_previous', ROOT/'work/wave_v10/engine.py')
_previous = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_previous)
prepare = _previous.prepare
TICKS, MULTIPLIERS = _previous.TICKS, _previous.MULTIPLIERS

FAMILIES = {'O01': '定刻コイントス', 'O02': '同時両建てと勝ち脚追跡',
            'O03': '上下逆指値の競合取消', 'O04': '有限の固定中心グリッド',
            'O05': '範囲離脱で中心を再設定するグリッド', 'O06': '在庫偏りで新規価格を補正するグリッド',
            'O07': '上下突破と利益方向への追加', 'O08': '三脚の段階利確と残脚追跡',
            'O09': '両建ての利益脚を先に返済', 'O10': '両建てを合算損益で返済'}
DEFAULTS = dict(family='O01', max_positions=1, seed=20260924, warmup_min=20.,
                repeat_min=60., pending_min=30., cooldown_min=5., gap_atr=.75,
                initial_stop_atr=.75, trail_atr=2., trail_start_atr=1.,
                take_profit_atr=np.inf, tighten_trigger_atr=np.inf,
                tighten_width_atr=.5, max_hold_min=180., basket_stop_atr=4.,
                session_stop_atr=8., reset_width_atr=3., reset_min=90.,
                inventory_skew=.25, entry_deadline_min=30., us_pause=False,
                basket_take_profit_atr=2., signal_family=None)
REASONS = {0: None, 1: '初期・追跡ストップ', 2: '利確条件', 3: '保有時間上限',
           4: 'セッション内返済', 5: '建玉全体の損失上限', 6: '中心再設定', 7: 'セッション損失上限', 8: '建玉全体の利確'}
RAW_COLUMNS = ['建玉番号', '方向', '条件行位置', '成立行位置', '新規約定行位置', '返済・評価行位置',
               '固定ATR', '新規価格', '返済・評価価格', '最終ストップ', '順行極値', '最大順行幅',
               '返済理由番号', '返済済み', '費用２呼値収支', '費用４呼値収支', '保有分',
               '返済成立行位置', '返済待ち理由', '初期損切幅ATR', 'サイクル番号', 'スロット番号',
               '信号行位置', '新規条件価格']


def catalog() -> list[dict]:
    """機能: 結果を見る前に定める注文手法と近傍の条件集合を返す。

    引数: なし。返り値: 設定辞書の一覧 (list[dict])。
    """
    sources = {
        'O01': 'https://dspace.mit.edu/entities/publication/47fd0df9-2fcb-4d78-aa1d-290c49a1e207',
        'O02': 'https://arxiv.org/abs/1701.03960',
        'O03': 'https://arxiv.org/abs/1701.03960',
        'O04': 'https://arxiv.org/abs/2506.11921',
        'O05': 'https://arxiv.org/abs/2506.11921',
        'O06': 'https://arxiv.org/abs/1105.3115',
        'O07': 'https://dspace.mit.edu/entities/publication/47fd0df9-2fcb-4d78-aa1d-290c49a1e207',
        'O08': 'https://arxiv.org/abs/1701.03960',
        'O09': 'https://arxiv.org/abs/1701.03960', 'O10': 'https://arxiv.org/abs/2506.11921'}
    output = []
    for family, name in FAMILIES.items():
        grid = family in ('O04', 'O05', 'O06')
        cap = 2 if family in ('O02', 'O09', 'O10') else 3 if grid or family in ('O07', 'O08') else 1
        for j, gap in enumerate((.5, .75, 1.)):
            for k, exit_name in enumerate(('固定利確併用', '利益方向を追跡')):
                cfg = dict(DEFAULTS, id=f'{family}_G{j}_X{k}', family=family, group='注文手法',
                           label=f'{name}・幅{gap:g}ATR・{exit_name}', max_positions=cap,
                           gap_atr=gap, initial_stop_atr=2. if grid else .75,
                           take_profit_atr=gap if grid and k == 0 else 2. if k == 0 else np.inf,
                           trail_atr=1. if grid else 2., trail_start_atr=gap if grid else 1.,
                           tighten_trigger_atr=np.inf if k == 0 else 1.5,
                           reset_width_atr=3*gap, provenance=sources[family])
                if family in ('O01', 'O02', 'O08'):
                    cfg['initial_stop_atr'] = gap
                if family in ('O09', 'O10'):
                    cfg.update(initial_stop_atr=3., take_profit_atr=gap,
                               trail_start_atr=np.inf, basket_take_profit_atr=gap,
                               max_hold_min=60. if k == 0 else 120.)
                    cfg['label'] = f"{name}・利確{gap:g}ATR・保有上限{cfg['max_hold_min']:g}分"
                elif family in ('O01', 'O02', 'O08'):
                    cfg['label'] = f'{name}・初期損切{gap:g}ATR・{exit_name}'
                cfg['exact_rules'] = explain(cfg)
                output.append(cfg)
    return output


def explain(config: dict) -> str:
    """機能: 価格・時間・枚数の設定を日本語の機械的条件にする。

    引数: config (dict)。返り値: 日本語説明 (str)。
    """
    c = dict(DEFAULTS, **config)
    family, gap = c['family'], c['gap_atr']
    detail = {
        'O01': f"開始20分後から{c['repeat_min']:g}分の固定枠ごとに、固定種の公平コインで１枚の方向を決める。前の建玉が残る枠は見送る。",
        'O02': f"開始20分後から{c['repeat_min']:g}分の固定枠で買い１枚・売り１枚を独立建玉として同時発注する。両脚に別々の損切りと追跡を置く。",
        'O03': f"固定枠の中値を中心に上下{gap:g}ATRの逆指値を監視し、先に成立した片側１枚を発注して他方を取消す。",
        'O04': f"開始時の中値から上下に{gap:g}ATR間隔の３段を置き、下で買い・上で売る。中心はセッション中固定する。",
        'O05': f"上下{gap:g}ATR間隔の３段で逆張りし、中心から{c['reset_width_atr']:g}ATR離脱または{c['reset_min']:g}分経過で全返済して中心を作り直す。",
        'O06': f"上下{gap:g}ATR間隔の３段で逆張りする。買越し枚数×{c['inventory_skew']:g}ATRだけ中心を下げ、売越しでは上げる。未成立価格だけ毎分更新する。",
        'O07': f"上下{gap:g}ATRの突破で初回１枚。初回の実約定価格から利益方向へ{gap:g}ATRごとに１枚を追加し、最大３枚にする。",
        'O08': '固定枠のコイン方向に３枚を別建玉として発注する。最初の脚を１ATR、２番目を２ATRで利確し、３番目は追跡だけで返済する。',
        'O09': f"買い１枚・売り１枚を同時に発注し、各脚の利益が{gap:g}ATRに達すればその脚だけを返済する。損失脚も初期損切り・時間上限・全体損失上限の対象とする。",
        'O10': f"買い１枚・売り１枚を同時に発注し、個別利確を行わず、両脚と確定分を合算したサイクル損益が{c['basket_take_profit_atr']:g}ATRに達すれば残存脚を全部返済する。"}[family]
    if c.get('signal_family'):
        detail = f"{c['signal_family']}の確定方向信号を初回注文のきっかけに使う。" + detail.replace('固定枠のコイン方向に', '信号方向に').replace(f'上下{gap:g}ATRの突破で初回１枚。', '信号方向に初回１枚を発注する。')
    tp = '固定利確なし' if not np.isfinite(c['take_profit_atr']) else f"{c['take_profit_atr']:g}ATRの利確条件"
    protection = '' if not np.isfinite(c['tighten_trigger_atr']) else f"、最大順行{c['tighten_trigger_atr']:g}ATRで追跡幅{c['tighten_width_atr']:g}ATRへ短縮"
    return (detail + f" 各脚の初期損切り{c['initial_stop_atr']:g}ATR、順行{c['trail_start_atr']:g}ATRから追跡幅{c['trail_atr']:g}ATR{protection}、{tp}、保有上限{c['max_hold_min']:g}分。"
            f"最大総建玉{c['max_positions']}枚。サイクル損失{c['basket_stop_atr']:g}ATRで全返済、セッション損失{c['session_stop_atr']:g}ATRで停止。幅はサイクル開始時ATRで固定。"
            "指値条件は相手気配が１呼値通過してから監視上成立とし、次の有効な相手気配で不利な価格変化も含めて約定。約定価格の保証は置かない。両建ての全脚に費用を課す。")


@njit(cache=True)
def _round(value, side, tick):
    """機能: 買い方向は切り上げ、売り方向は切り下げて呼値へ合わせる。

    引数: value/side/tick (float)。返り値: 価格 (float)。
    """
    return (np.ceil(value/tick) if side > 0 else np.floor(value/tick))*tick


@njit(cache=True)
def _replay(time, seq, bid, ask, bid_qty, ask_qty, atr, p, coins, event_indices, event_sides, start, limit, tick, us_open, delay):
    """機能: 有限の注文と建玉を全観測行に沿って更新する。

    引数: 気配配列 (ndarray群)、p/coins (ndarray)、時刻・呼値 (float)、delay (int)。
    返り値: 売買行列・毎分評価行列・全行診断値 (tuple[ndarray, ndarray, ndarray])。
    """
    (family, cap, warmup, repeat, expiry, cooldown, gap, initial, trail, trail_start,
     take_profit, tighten_trigger, tighten_width, max_hold, basket_limit, session_limit,
     reset_width, reset_minutes, skew, entry_deadline, us_pause, basket_profit, signal_mode) = p
    cap = int(cap)
    is_grid = family == 4 or family == 5 or family == 6
    nslots = 6
    state = np.zeros(nslots, np.int64)
    side = np.zeros(nslots, np.int64)
    kind = np.zeros(nslots, np.int64)
    condition = np.zeros(nslots, np.int64)
    trigger = np.zeros(nslots, np.int64)
    entry_i = np.zeros(nslots, np.int64)
    queue_i = np.zeros(nslots, np.int64)
    exit_trigger = np.zeros(nslots, np.int64)
    reason = np.zeros(nslots, np.int64)
    leg_id = np.zeros(nslots, np.int64)
    born_cycle = np.zeros(nslots, np.int64)
    cycle_signal = np.zeros(nslots, np.int64)
    level = np.zeros(nslots)
    original_level = np.zeros(nslots)
    A = np.zeros(nslots)
    entry = np.zeros(nslots)
    stop = np.zeros(nslots)
    extreme = np.zeros(nslots)
    favorable = np.zeros(nslots)
    leg_profit = np.zeros(nslots)
    dead = np.zeros(nslots)
    available_after = np.zeros(nslots)
    rearmed = np.ones(nslots, np.bool_)
    result = np.full((len(seq)+8, 24), np.nan)
    eq = np.full((int((time[-1]-time[0])//60)+4, 11), np.nan)
    count, eq_count, serial, cycle = 0, 0, 0, -1
    active, resetting, stopped = False, False, False
    anchor, cycle_atr, session_atr, cycle_start, cycle_realized = 0., 0., 0., 0., 0.
    signal_i, last_bucket, first_side, adds = 0, -1, 0, 0
    first_entry, next_cycle = 0., start+warmup*60
    realized, stress_realized, peak, stress_peak, maximum_dd, stress_dd = 0., 0., 0., 0., 0., 0.
    atr_realized, atr_stress_realized, atr_peak, atr_stress_peak, atr_dd, atr_stress_dd = 0., 0., 0., 0., 0., 0.
    max_gross, max_net, max_risk, last_minute = 0, 0, 0., -1
    crossed_limit_waits, skipped_capacity, reset_count, basket_stops, session_stops = 0, 0, 0, 0, 0
    event_pointer = 0
    for i in range(len(seq)):
        now, b, a = time[i], bid[i], ask[i]
        bid_left, ask_left = bid_qty[i], ask_qty[i]
        in_us = us_open-900 <= now < us_open+1800
        signal_event, observed_side = False, 0
        while event_pointer < len(event_indices) and event_indices[event_pointer] <= i:
            if event_indices[event_pointer] == i:
                signal_event, observed_side = True, event_sides[event_pointer]
            event_pointer += 1
        allow_entry = now < limit-entry_deadline*60 and not stopped and not resetting and not (us_pause and in_us)
        gross = 0
        net_inventory = 0
        for j in range(nslots):
            if state[j] >= 3:
                gross += 1
                net_inventory += side[j]
                quote = b if side[j] > 0 else a
                # 報告用最大順行は、成立行と約定待ち行も含めた実行可能気配で更新する。
                extreme[j] = max(extreme[j], quote) if side[j] > 0 else min(extreme[j], quote)
                favorable[j] = max(favorable[j], side[j]*(extreme[j]-entry[j]))
        # ----------------------------------------
        # 返済を先に照合し、同じ観測の最良気配数量を新規と共同で消費する。
        for j in range(nslots):
            if state[j] != 4:
                continue
            due = i >= queue_i[j]+(2 if delay == 2 else 1) and (delay != 3 or now > time[queue_i[j]])
            liquidity = bid_left if side[j] > 0 else ask_left
            if not due or liquidity < 1:
                continue
            fill = b if side[j] > 0 else a
            pnl = side[j]*(fill-entry[j])-2*tick
            result[count] = np.array([leg_id[j], side[j], condition[j], trigger[j], entry_i[j], i,
                A[j], entry[j], fill, stop[j], extreme[j], favorable[j], reason[j], 1,
                pnl, pnl-2*tick, (now-time[entry_i[j]])/60, exit_trigger[j], 0, initial,
                born_cycle[j], j, cycle_signal[j], original_level[j]], dtype=np.float64)
            count += 1
            realized += pnl
            stress_realized += pnl-2*tick
            atr_realized += pnl/A[j]
            atr_stress_realized += (pnl-2*tick)/A[j]
            if side[j] > 0:
                bid_left -= 1
            else:
                ask_left -= 1
            gross -= 1
            net_inventory -= side[j]
            state[j] = 0
            available_after[j] = now+cooldown*60
            rearmed[j] = False
        for j in range(nslots):
            if state[j] != 2:
                continue
            if not allow_entry or now > dead[j]:
                state[j] = 0
                continue
            due = i >= queue_i[j]+(2 if delay == 2 else 1) and (delay != 3 or now > time[queue_i[j]])
            if not due:
                continue
            fill = a if side[j] > 0 else b
            if family == 7 and j >= 2:
                permitted = gross > 0
                for k in range(nslots):
                    if state[k] >= 3 and side[k]*((b if side[k] > 0 else a)-entry[k]) <= 0:
                        permitted = False
                if not permitted:
                    state[j] = 0
                    continue
            if kind[j] == 2 and side[j]*(fill-level[j]) > 0:
                crossed_limit_waits += 1
            if gross >= cap:
                skipped_capacity += 1
                continue
            if (ask_left if side[j] > 0 else bid_left) < 1:
                continue
            serial += 1
            leg_id[j], entry_i[j], entry[j], state[j] = serial, i, fill, 3
            stop[j] = _round(fill-side[j]*initial*A[j], -side[j], tick)
            extreme[j], favorable[j] = fill, 0.
            if side[j] > 0:
                ask_left -= 1
            else:
                bid_left -= 1
            gross += 1
            net_inventory += side[j]
            if family == 7 and first_side == 0:
                first_side, first_entry = side[j], fill
        # ----------------------------------------
        # 直前行までに確定した返済条件を判定してから、追跡値を次行用に更新する。
        for j in range(nslots):
            if state[j] != 3 or entry_i[j] == i:
                continue
            quote = b if side[j] > 0 else a
            r = 4 if now >= limit else 1 if side[j]*(quote-stop[j]) <= 0 else 2 if side[j]*(quote-entry[j]) >= leg_profit[j]*A[j] else 3 if now-time[entry_i[j]] >= max_hold*60 else 0
            if r:
                state[j], reason[j], queue_i[j], exit_trigger[j] = 4, r, i, i
                continue
            extreme[j] = max(extreme[j], quote) if side[j] > 0 else min(extreme[j], quote)
            favorable[j] = max(favorable[j], side[j]*(extreme[j]-entry[j]))
            width = min(trail, tighten_width) if favorable[j] >= tighten_trigger*A[j] else trail
            if favorable[j] >= trail_start*A[j]:
                candidate = _round(extreme[j]-side[j]*width*A[j], -side[j], tick)
                stop[j] = max(stop[j], candidate) if side[j] > 0 else min(stop[j], candidate)
        equity, stress_equity, risk = realized, stress_realized, 0.
        atr_equity, atr_stress_equity = atr_realized, atr_stress_realized
        for j in range(nslots):
            if state[j] >= 3:
                quote = b if side[j] > 0 else a
                mark = side[j]*(quote-entry[j])-2*tick
                equity += mark
                stress_equity += mark-2*tick
                atr_equity += mark/A[j]
                atr_stress_equity += (mark-2*tick)/A[j]
                risk += initial*A[j]
        peak, stress_peak = max(peak, equity), max(stress_peak, stress_equity)
        maximum_dd, stress_dd = max(maximum_dd, peak-equity), max(stress_dd, stress_peak-stress_equity)
        atr_peak, atr_stress_peak = max(atr_peak, atr_equity), max(atr_stress_peak, atr_stress_equity)
        atr_dd, atr_stress_dd = max(atr_dd, atr_peak-atr_equity), max(atr_stress_dd, atr_stress_peak-atr_stress_equity)
        max_gross, max_net, max_risk = max(max_gross, gross), max(max_net, abs(net_inventory)), max(max_risk, risk)
        minute = int((now-time[0])//60)
        if minute != last_minute or i == len(seq)-1:
            eq[eq_count] = np.array([now, seq[i], equity, stress_equity, atr_equity, atr_stress_equity, gross,
                                   net_inventory, maximum_dd, stress_dd, realized], np.float64)
            eq_count += 1
            last_minute = minute
        # ----------------------------------------
        # バスケットとセッションの損失には未返済建玉と全脚の返済費用を含める。
        global_reason = 0
        if active and not stopped and session_atr > 0 and equity <= -session_limit*session_atr:
            global_reason, stopped = 7, True
            session_stops += 1
        elif active and not resetting and equity-cycle_realized <= -basket_limit*cycle_atr:
            global_reason = 5
            basket_stops += 1
            if family == 4 or family == 6:
                stopped = True
        elif active and family == 10 and not resetting and equity-cycle_realized >= basket_profit*cycle_atr:
            global_reason = 8
        elif active and family == 5 and not resetting and (abs((a+b)/2-anchor) >= reset_width*cycle_atr or now-cycle_start >= reset_minutes*60):
            global_reason = 6
            reset_count += 1
        if global_reason:
            resetting = True
            next_cycle = max(next_cycle, now+cooldown*60) if not is_grid else now+cooldown*60
            for j in range(nslots):
                if state[j] == 3:
                    state[j], reason[j], queue_i[j], exit_trigger[j] = 4, global_reason, i, i
                elif state[j] < 3:
                    state[j] = 0
        if now >= limit-entry_deadline*60 or stopped or resetting or (us_pause and in_us):
            for j in range(nslots):
                if state[j] == 1 or state[j] == 2:
                    state[j] = 0
        if resetting and gross == 0:
            active, resetting = False, False
        # ----------------------------------------
        # 未成立条件は成立時にも同じ総枚数上限を守る。成立後の実約定は必ず後続行。
        reservations = gross
        for j in range(nslots):
            if state[j] == 2:
                reservations += 1
        for j in range(nslots):
            if state[j] != 1 or i <= condition[j]:
                continue
            if now > dead[j] or not allow_entry:
                state[j] = 0
                continue
            quote = a if side[j] > 0 else b
            if family == 7 and j >= 2:
                permitted = gross > 0
                for k in range(nslots):
                    if state[k] >= 3 and side[k]*((b if side[k] > 0 else a)-entry[k]) <= 0:
                        permitted = False
                if not permitted:
                    if gross == 0:
                        state[j] = 0
                    continue
            hit = kind[j] == 0 or (kind[j] == 1 and side[j]*(quote-level[j]) >= 0) or (kind[j] == 2 and side[j]*(quote-level[j]) <= -tick)
            if not hit or reservations >= cap:
                continue
            if (family == 3 or (family == 7 and not signal_mode)) and first_side == 0 and j < 2:
                other = 1-j
                other_quote = a if side[other] > 0 else b
                if state[other] == 1 and side[other]*(other_quote-level[other]) >= 0:
                    continue
                if state[other] == 1:
                    state[other] = 0
            state[j], trigger[j], queue_i[j] = 2, i, i
            dead[j] = min(dead[j], now+60)
            reservations += 1
        if not allow_entry or not np.isfinite(atr[i]) or atr[i] <= 0 or now < start+warmup*60:
            continue
        pending = 0
        for j in range(nslots):
            if state[j] > 0:
                pending += 1
        bucket = int((now-start-warmup*60)//(repeat*60))
        if not is_grid and pending == 0:
            active = False
        # ----------------------------------------
        # 定刻枠の乱数は取引経路に依存しない。前枠保有中の枠は後から取り直さない。
        if not is_grid and ((signal_mode and signal_event) or (not signal_mode and bucket > last_bucket)):
            if not signal_mode:
                last_bucket = bucket
            if pending > 0:
                continue
            if now < next_cycle:
                continue
            active, cycle = True, cycle+1
            anchor, cycle_atr, cycle_start, cycle_realized, signal_i = (a+b)/2, atr[i], now, realized, i
            if session_atr == 0:
                session_atr = cycle_atr
            next_cycle = now+cooldown*60 if signal_mode else start+warmup*60+(bucket+1)*repeat*60
            first_side, adds = 0, 0
            for j in range(nslots):
                state[j] = 0
            n = 3 if family == 8 else 2 if family in (2, 3, 9, 10) or (family == 7 and not signal_mode) else 1
            for j in range(n):
                side[j] = observed_side if signal_mode else coins[min(bucket, len(coins)-1)] if family in (1, 8) else 1 if j == 0 else -1
                kind[j] = 1 if family == 3 or (family == 7 and not signal_mode) else 0
                level[j] = _round(anchor+side[j]*gap*cycle_atr, side[j], tick)
                original_level[j] = level[j]
                state[j], condition[j], A[j], dead[j] = 1, i, cycle_atr, now+expiry*60
                born_cycle[j], cycle_signal[j] = cycle, signal_i
                leg_profit[j] = (j+1 if j < 2 else np.inf) if family == 8 else np.inf if family == 10 else take_profit
        if is_grid and not active and now >= next_cycle:
            active, cycle = True, cycle+1
            anchor, cycle_atr, cycle_start, cycle_realized, signal_i = (a+b)/2, atr[i], now, realized, i
            if session_atr == 0:
                session_atr = cycle_atr
            for j in range(nslots):
                state[j], rearmed[j], available_after[j] = 0, True, now
        if is_grid and active:
            shifted_anchor = anchor-skew*net_inventory*cycle_atr if family == 6 else anchor
            for j in range(nslots):
                direction = 1 if j < 3 else -1
                distance = (j%3+1)*gap*cycle_atr
                target = _round(shifted_anchor-direction*distance, -direction, tick)
                if state[j] == 0:
                    quote = a if direction > 0 else b
                    if not rearmed[j] and direction*(quote-target) >= tick:
                        rearmed[j] = True
                    if now >= available_after[j] and rearmed[j]:
                        side[j], state[j], kind[j], level[j], original_level[j] = direction, 1, 2, target, target
                        condition[j], A[j], dead[j] = i, cycle_atr, limit-entry_deadline*60
                        born_cycle[j], cycle_signal[j] = cycle, signal_i
                        leg_profit[j] = take_profit
                elif family == 6 and state[j] == 1 and int(now//60) != int(time[max(0,i-1)]//60):
                    level[j], original_level[j], condition[j] = target, target, i
        if family == 7 and active and first_side != 0 and adds < cap-1:
            occupied = False
            for j in range(2, nslots):
                if state[j] == 1 or state[j] == 2:
                    occupied = True
            # 追加は現在の全建玉に含み益がある時だけ許す。損失方向への追加は行わない。
            all_profitable = gross > 0
            for j in range(nslots):
                if state[j] >= 3 and side[j]*((b if side[j] > 0 else a)-entry[j]) <= 0:
                    all_profitable = False
            if not occupied and all_profitable:
                j = 2+adds
                side[j], state[j], kind[j] = first_side, 1, 1
                level[j] = _round(first_entry+first_side*(adds+1)*gap*cycle_atr, first_side, tick)
                original_level[j] = level[j]
                condition[j], A[j], dead[j] = i, cycle_atr, now+expiry*60
                born_cycle[j], cycle_signal[j] = cycle, signal_i
                leg_profit[j] = take_profit
                adds += 1
    # ----------------------------------------
    # 保存断面の終端を架空の返済にしない。返済費用を含む評価を別の行として返す。
    i = len(seq)-1
    for j in range(nslots):
        if state[j] >= 3:
            fill = bid[i] if side[j] > 0 else ask[i]
            pnl = side[j]*(fill-entry[j])-2*tick
            result[count] = np.array([leg_id[j], side[j], condition[j], trigger[j], entry_i[j], i,
                A[j], entry[j], fill, stop[j], extreme[j], favorable[j], 0, 0,
                pnl, pnl-2*tick, (time[i]-time[entry_i[j]])/60, exit_trigger[j], reason[j] if state[j] == 4 else 0,
                initial, born_cycle[j], j, cycle_signal[j], original_level[j]], np.float64)
            count += 1
    diagnostics = np.array([maximum_dd, stress_dd, max_gross, max_net, max_risk, cycle+1,
                            crossed_limit_waits, skipped_capacity, reset_count, basket_stops, session_stops,
                            atr_dd, atr_stress_dd], np.float64)
    return result[:count], eq[:eq_count], diagnostics


def simulate_array(prepared: dict, config: dict, delay: str = '次行') -> dict:
    """機能: 固定設定を高速再生し、売買・評価・診断を返す。

    引数: prepared/config (dict)、delay (str)。返り値: trades/equity/diagnosticsを持つ辞書 (dict)。
    """
    c = dict(DEFAULTS, **config)
    if c['family'] not in FAMILIES or not 1 <= c['max_positions'] <= 3:
        raise ValueError('既知の系統と１〜３枚の総建玉上限が必要です。')
    if c['family'] in ('O02', 'O09', 'O10') and c['max_positions'] < 2:
        raise ValueError('両建てには２枚の総建玉上限が必要です。')
    names = ['max_positions', 'warmup_min', 'repeat_min', 'pending_min', 'cooldown_min',
             'gap_atr', 'initial_stop_atr', 'trail_atr', 'trail_start_atr', 'take_profit_atr',
             'tighten_trigger_atr', 'tighten_width_atr', 'max_hold_min', 'basket_stop_atr',
             'session_stop_atr', 'reset_width_atr', 'reset_min', 'inventory_skew',
             'entry_deadline_min', 'us_pause', 'basket_take_profit_atr']
    if any(np.isnan(float(c[name])) or float(c[name]) < 0 for name in names) or c['repeat_min'] == 0:
        raise ValueError('設定は非負で、繰返し間隔は正数である必要があります。')
    seed_text = f"{c['seed']}|{prepared['session']}|{prepared['symbol']}"
    seed = int.from_bytes(hashlib.sha256(seed_text.encode()).digest()[:8], 'little')
    rng = np.random.default_rng(seed)
    coin_count = max(2, int((prepared['limit']-prepared['start'])/(c['repeat_min']*60))+2)
    coins = np.ascontiguousarray(rng.choice(np.array([-1, 1], dtype=np.int64), coin_count))
    p = np.array([int(c['family'][1:])]+[c[name] for name in names]+[bool(c['signal_family'])], dtype=np.float64)
    if c['signal_family']:
        if c['family'] not in ('O07', 'O08'):
            raise ValueError('予測信号との組合せは順張り追加・段階利確で指定してください。')
        family_events = prepared['families'].get(c['signal_family'])
        event_indices = family_events['indices'] if family_events is not None else np.array([], dtype=np.int64)
        event_sides = family_events['sides'] if family_events is not None else np.array([], dtype=np.int64)
    else:
        event_indices, event_sides = np.array([], dtype=np.int64), np.array([], dtype=np.int64)
    delays = {'次行': 1, '２行後': 2, '次時刻': 3}
    if delay not in delays:
        raise ValueError('約定遅延は次行・２行後・次時刻のいずれかです。')
    raw, equity, diagnostics = _replay(*(prepared[name] for name in ('time_s', 'seq', 'bid', 'ask', 'bid_qty', 'ask_qty', 'atr')),
        p, coins, event_indices, event_sides, prepared['start'], prepared['limit'], prepared['tick'], prepared['us_open'], delays[delay])
    keys = ['全行最大DD点', '全行費用倍最大DD点', '最大総建玉枚数', '最大純建玉枚数', '最大初期損切幅合計点',
            'サイクル数', '指値条件後に条件価格より不利な約定行数', '枚数上限の約定待ち行数', '中心再設定数', 'バスケット停止数', 'セッション停止数',
            '全行最大下落ATR', '費用倍全行最大下落ATR']
    equity[:, [2, 3, 8, 9, 10]] *= MULTIPLIERS[prepared['symbol']]
    return dict(trades=raw, equity=equity, diagnostics=dict(zip(keys, diagnostics)))


def summary(prepared: dict, config: dict, delay: str = '次行', raw: dict | None = None) -> dict:
    """機能: 全脚の確定収支・未返済評価・全行損失をまとめる。

    引数: prepared/config (dict)、delay (str)、raw (dict|None)。返り値: 日本語集計 (dict)。
    """
    if raw is None:
        raw = simulate_array(prepared, config, delay)
    trades = raw['trades']
    closed, opened = trades[trades[:, 13] == 1], trades[trades[:, 13] == 0]
    multiplier, cap = MULTIPLIERS[prepared['symbol']], config.get('max_positions', 1)
    net = closed[:, 14]*multiplier
    result = dict(方式=config['id'], 群=config.get('group', '注文手法'), 系統=config['family'],
        セッション=prepared['session'], 銘柄=prepared['symbol'], 約定遅延=delay,
        取引数=len(closed), 未返済数=len(opened), 勝ち数=int((net > 0).sum()), 負け数=int((net < 0).sum()),
        利益円=float(net[net > 0].sum()), 損失円=float(-net[net < 0].sum()), 収支円=float(net.sum()),
        費用倍収支円=float(closed[:, 15].sum()*multiplier),
        ATR収支=float(np.sum(closed[:, 14]/closed[:, 6])), 費用倍ATR収支=float(np.sum(closed[:, 15]/closed[:, 6])),
        評価損益円=float(opened[:, 14].sum()*multiplier), 費用倍評価損益円=float(opened[:, 15].sum()*multiplier),
        平均保有分=float(closed[:, 16].mean()) if len(closed) else None,
        平均利益円=float(net[net > 0].mean()) if np.any(net > 0) else None,
        平均損失円=float(-net[net < 0].mean()) if np.any(net < 0) else None,
        最悪取引円=float(net.min()) if len(net) else None, 設定総枚数上限=int(cap),
        上限枚数当たり収支円=float(net.sum()/cap),
        上限枚数当たり費用倍収支円=float(closed[:, 15].sum()*multiplier/cap),
        全行最大DD円=float(raw['diagnostics']['全行最大DD点']*multiplier),
        全行費用倍最大DD円=float(raw['diagnostics']['全行費用倍最大DD点']*multiplier),
        最大順行からの返却円=float(np.maximum(0, closed[:, 11]-closed[:, 14]-2*prepared['tick']).sum()*multiplier))
    result.update(raw['diagnostics'])
    result.update(全行最大下落円=result['全行最大DD円'], 費用倍全行最大下落円=result['全行費用倍最大DD円'],
                  設定最大枚数=int(cap), 最大保有枚数=int(raw['diagnostics']['最大総建玉枚数']),
                  枚数上限換算収支円=float(net.sum()/cap),
                  枚数上限換算費用倍収支円=float(closed[:, 15].sum()*multiplier/cap),
                  枚数上限換算評価円=float(opened[:, 14].sum()*multiplier/cap))
    return result


def simulate(prepared: dict, config: dict, delay: str = '次行', raw: dict | None = None) -> list[dict]:
    """機能: 数値売買を図解・検査に使える辞書形式へ復元する。

    引数: prepared/config (dict)、delay (str)、raw (dict|None)。返り値: 各脚の売買 (list[dict])。
    """
    if raw is None:
        raw = simulate_array(prepared, config, delay)
    result, time, seq = [], prepared['time_s'], prepared['seq']
    for row in raw['trades']:
        condition, trigger, entry, last, signal = (int(row[x]) for x in (2, 3, 4, 5, 22))
        origin = condition if config['family'] in ('O04', 'O05', 'O06') else signal
        item = dict(side=int(row[1]), event_id=f"{config['id']}_{prepared['session']}_{prepared['symbol']}_脚{int(row[0])}",
            atr=float(row[6]), event_atr=float(row[6]), signal_time_s=float(time[origin]), signal_seq=int(seq[origin]),
            signal_price=float((prepared['bid'][origin]+prepared['ask'][origin])/2), source_last_seq=int(seq[origin]),
            reason=FAMILIES[config['family']], condition_time_s=float(time[condition]), condition_seq=int(seq[condition]),
            trigger_seq=int(seq[trigger]), entry_time_s=float(time[entry]), entry_seq=int(seq[entry]), entry_price=float(row[7]),
            entry_spread=float(prepared['ask'][entry]-prepared['bid'][entry]), stop=float(row[9]), extreme=float(row[10]),
            max_favorable=float(row[11]), closed=bool(row[13]), net_points=float(row[14]), stress_points=float(row[15]),
            duration_min=float(row[16]), initial_width_atr=float(row[19]), cycle_id=int(row[20]), slot_id=int(row[21]),
            order_threshold=float(row[23]), order_family=config['family'],
            cycle_start_time_s=float(time[signal]), cycle_start_seq=int(seq[signal]),
            source_description='条件作成行で観測済みの気配。成立と約定はそれぞれ後続行。')
        if config.get('signal_family'):
            family = prepared['families'].get(config['signal_family'])
            if family:
                at = np.searchsorted(family['indices'], signal)
                if at < len(family['rows']) and family['indices'][at] == signal:
                    event = family['rows'][at]
                    item.update(source_last_seq=int(event['source_last_seq']), source_description='確定予測信号の素材最終行')
        if item['closed']:
            item.update(exit_time_s=float(time[last]), exit_seq=int(seq[last]), exit_price=float(row[8]),
                exit_reason=REASONS[int(row[12])], exit_trigger_seq=int(seq[int(row[17])]),
                exit_spread=float(prepared['ask'][last]-prepared['bid'][last]), exit_in_session=bool(time[last] < prepared['limit']+300))
        else:
            item.update(mark_time_s=float(time[last]), mark_price=float(row[8]), pending_exit=REASONS[int(row[18])])
        result.append(item)
    return result
