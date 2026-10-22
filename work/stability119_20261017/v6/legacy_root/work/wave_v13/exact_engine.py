"""費用を控除せず、事前指定価格への到達を原本順で判定する理想約定再生器。"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from numba import njit

TICKS = {'NK225': 10., 'TOPIX': .5}
MULTIPLIERS = {'NK225': 1000., 'TOPIX': 10000.}
ENTRY_MODES = {'market': 0, 'stop': 1, 'trail': 2, 'limit': 3, 'straddle': 4}
ADD_MODES = {'none': 0, 'simultaneous': 1, 'pyramid': 2, 'grid': 3, 'hedge': 4}
REASONS = {0: '打切り時評価', 1: '初期・追跡ストップ', 2: '指定利益幅',
           3: '保有時間上限', 4: 'セッション内返済', 5: '反対信号',
           6: '米国開始前後の返済', 7: '建玉合算の損失上限', 8: '建玉合算の利益目標'}
RAW_COLUMNS = ['サイクル番号', '脚番号', '方向', 'イベント番号', '条件行位置',
               '新規行位置', '返済評価行位置', '固定ATR', '新規価格', '返済評価価格',
               '最終ストップ', '順行極値', '最大順行幅', '理由番号', '返済済み',
               '収支ポイント', '保有分', '返済条件行位置', '新規指定価格',
               '信号原本行番号', '新規原本行番号', '返済評価原本行番号']
EQUITY_COLUMNS = ['時刻秒', '原本行番号', '評価損益円', '評価損益ATR', '総枚数',
                  '確定損益円', '最大ドローダウン円']
DEFAULTS = dict(entry_mode='trail', entry_atr=.25, initial_stop_atr=1.,
                trail_atr=2., trail_start_atr=1., target_atr=None,
                tighten_trigger_atr=None, tighten_width_atr=.5,
                breakeven_trigger_atr=None, protect_trigger_atr=None, protect_fraction=0.,
                time_tighten_min=None, time_width_atr=.5, holding_min=None,
                reverse_exit=False, max_legs=1, add_mode='none', add_step_atr=.5,
                leg_targets=None, cooldown_min=5., max_age_min=10., warmup_min=20.,
                entry_deadline_min=30., us_pause=False, us_exit=False,
                us_before_min=15., us_after_min=30., basket_stop_atr=None,
                basket_target_atr=None, direction_multiplier=1, opposite_width_atr=None,
                weak_width_atr=None, us_width_atr=None, state_trigger_atr=0.)
PARAMETERS = ['entry_mode', 'entry_atr', 'initial_stop_atr', 'trail_atr',
              'trail_start_atr', 'target_atr', 'tighten_trigger_atr', 'tighten_width_atr',
              'breakeven_trigger_atr', 'protect_trigger_atr', 'protect_fraction',
              'time_tighten_min', 'time_width_atr', 'holding_min', 'reverse_exit',
              'max_legs', 'add_mode', 'add_step_atr', 'cooldown_min', 'max_age_min',
              'warmup_min', 'entry_deadline_min', 'us_pause', 'us_exit',
              'us_before_min', 'us_after_min', 'basket_stop_atr', 'basket_target_atr',
              'direction_multiplier', 'opposite_width_atr', 'weak_width_atr', 'us_width_atr',
              'state_trigger_atr']


def bounds(session: str) -> tuple[float, float]:
    """機能: セッション開始と、セッション内返済条件の時刻を返す。

    引数: session (str)。返り値: 開始と返済条件のUnix秒 (tuple[float, float])。
    """
    day = datetime.fromisoformat(session[:10]).replace(tzinfo=ZoneInfo('Asia/Tokyo'))
    start = day + (timedelta(hours=17) if session.endswith('Night') else timedelta(hours=8, minutes=45))
    end = day + (timedelta(days=1, hours=5, minutes=50) if session.endswith('Night') else timedelta(hours=15, minutes=35))
    return start.timestamp(), end.timestamp()


def prepare(tape: dict, events: pd.DataFrame, session: str, symbol: str,
            state: dict | None = None) -> dict:
    """機能: 原本価格と因果順序を確認し、繰返し再生用の配列を準備する。

    引数: tape (dict) はseq/time_s/last/atr、events (DataFrame)、session/symbol (str)、
    state (dict|None) は任意のboard_side/trend_side。返り値: 再生入力 (dict)。
    """
    seq = np.ascontiguousarray(tape['seq'], dtype=np.int64)
    result = {name: np.ascontiguousarray(tape[name], dtype=np.float64)
              for name in ('time_s', 'last', 'atr')}
    if not len(seq) or any(len(v) != len(seq) for v in result.values()):
        raise ValueError('原本配列は空でなく、すべて同じ長さである必要があります。')
    if np.any(np.diff(seq) <= 0) or np.any(np.diff(result['time_s']) < 0):
        raise ValueError('原本行は増加順、代理時刻は非減少順である必要があります。')
    if np.any(~np.isfinite(result['time_s'])):
        raise ValueError('代理時刻は有限値である必要があります。')
    families = {}
    if len(events):
        for family, group in events.groupby('family', sort=False):
            rows = group.sort_values('seq').to_dict('records')
            event_seq = np.array([row['seq'] for row in rows], dtype=np.int64)
            indices = np.searchsorted(seq, event_seq)
            if np.any(indices >= len(seq)) or np.any(seq[indices] != event_seq):
                raise ValueError('イベント公開行が原本価格配列にありません。')
            if len(np.unique(event_seq)) != len(event_seq):
                raise ValueError('同系統の同一行に複数イベントがあります。')
            sides = np.array([row['side'] for row in rows], dtype=np.int64)
            if np.any(~np.isin(sides, [-1, 1])):
                raise ValueError('イベント方向は-1か1です。')
            if any(row['source_last_seq'] >= row['seq'] for row in rows):
                raise ValueError('素材の最終行はイベント公開行より前である必要があります。')
            if any(abs(row['time_s'] - result['time_s'][idx]) > .00001 for row, idx in zip(rows, indices)):
                raise ValueError('イベント時刻と公開行時刻が一致しません。')
            families[family] = dict(rows=rows, indices=indices.astype(np.int64), sides=sides,
                                    deadlines=np.array([row.get('deadline_time_s', np.inf) for row in rows], dtype=float))
    state = state or {}
    for key in ('board_side', 'trend_side'):
        values = np.ascontiguousarray(state.get(key, tape.get(key, np.zeros(len(seq)))), dtype=np.int64)
        if len(values) != len(seq) or np.any(~np.isin(values, [-1, 0, 1])):
            raise ValueError(f'{key}は原本と同じ長さの-1/0/1配列が必要です。')
        result[key] = values
    us_open = (datetime.fromisoformat(session[:10] + 'T09:30:00').replace(tzinfo=ZoneInfo('America/New_York')).timestamp()
               if session.endswith('Night') else np.inf)
    return dict(result, seq=seq, families=families, session=session, symbol=symbol,
                start=bounds(session)[0], limit=bounds(session)[1], tick=TICKS[symbol], us_open=us_open)


def parameters(config: dict) -> tuple[np.ndarray, np.ndarray]:
    """機能: 設定を検証し、数値配列と脚別利確幅へ変換する。

    引数: config (dict)。返り値: 設定と脚別利確幅 (tuple[ndarray, ndarray])。
    """
    cfg = dict(DEFAULTS, **config)
    if 'signal_multiplier' in config:
        cfg['direction_multiplier'] = config['signal_multiplier']
    if cfg['entry_mode'] not in ENTRY_MODES or cfg['add_mode'] not in ADD_MODES:
        raise ValueError('未知の入口または追加方法です。')
    if int(cfg['max_legs']) != cfg['max_legs'] or cfg['max_legs'] not in (1, 2, 3):
        raise ValueError('最大建玉は1〜3枚です。')
    if cfg['add_mode'] == 'none' and cfg['max_legs'] != 1:
        raise ValueError('追加なしは最大1枚にしてください。')
    if cfg['add_mode'] == 'hedge' and cfg['max_legs'] != 2:
        raise ValueError('両建ては最大2枚にしてください。')
    if cfg['direction_multiplier'] not in (-1, 1):
        raise ValueError('方向係数は-1か1です。')
    for key in PARAMETERS:
        if key not in ('entry_mode', 'add_mode'):
            cfg[key] = np.inf if cfg[key] is None else float(cfg[key])
            if np.isnan(cfg[key]) or (cfg[key] < 0 and key != 'direction_multiplier'):
                raise ValueError(f'{key}に不正な値があります。')
    if cfg['initial_stop_atr'] <= 0 or cfg['trail_atr'] <= 0 or cfg['tighten_width_atr'] <= 0:
        raise ValueError('損切り・追跡幅は正数かNoneです。')
    if not np.isfinite(cfg['initial_stop_atr']) and not np.isfinite(cfg['holding_min']):
        raise ValueError('初期損切りなしの場合は有限の保有時間上限が必要です。')
    if cfg['protect_fraction'] > 1:
        raise ValueError('利益保全率は0〜1です。')
    targets = np.full(3, cfg['target_atr'], dtype=float)
    if cfg['leg_targets'] is not None:
        if len(cfg['leg_targets']) != int(cfg['max_legs']):
            raise ValueError('脚別利確は最大建玉と同じ数を指定してください。')
        for j, value in enumerate(cfg['leg_targets']):
            targets[j] = np.inf if value is None else float(value)
    if np.any(np.isnan(targets)) or np.any(targets <= 0):
        raise ValueError('利確幅は正数かNoneです。')
    cfg['entry_mode'] = ENTRY_MODES[cfg['entry_mode']]
    cfg['add_mode'] = ADD_MODES[cfg['add_mode']]
    return np.array([cfg[key] for key in PARAMETERS], dtype=float), targets


@njit(cache=True)
def rounded(value, direction, tick):
    """機能: 上方向条件を切上げ、下方向条件を切下げ、呼値へ合わせる。

    引数: value/direction/tick (float)。返り値: 呼値へ丸めた価格 (float)。
    """
    if not np.isfinite(value):
        return value
    return (np.ceil(value / tick) if direction > 0 else np.floor(value / tick)) * tick


@njit(cache=True)
def replay(time, seq, last, atr, board, trend, event_i, event_side, event_deadline,
           p, targets, start, limit, tick, us_open, multiplier, detail):
    """機能: 現在価格を原本順で走査し、指定価格での理想約定と評価損益を求める。

    引数: 原本・信号・設定のndarray群、時刻・呼値・倍率 (float)、detail (bool)。
    返り値: 売買、評価曲線、集計数値 (tuple[ndarray, ndarray, ndarray])。
    """
    (entry_mode, entry_width, initial_width, trail_width, trail_start, target_width,
     tight_trigger, tight_width, be_trigger, protect_trigger, protect_fraction,
     time_tighten, time_width, hold_limit, reverse_exit, cap, add_mode, add_step,
     cooldown, age_limit, warmup, entry_deadline, us_pause, us_exit, us_before,
     us_after, basket_stop, basket_target, direction_multiplier, opposite_width,
     weak_width, us_width, state_trigger) = p
    cap = int(cap)
    result = np.full((len(event_i) * cap + 3, 22), np.nan)
    eq_capacity = (int(max(0., time[-1] - time[0]) // 60) + 4) if detail else 1
    equity = np.zeros((eq_capacity, 7))
    active = np.zeros(3, dtype=np.bool_)
    side = np.zeros(3, dtype=np.int64)
    entry_idx = np.zeros(3, dtype=np.int64)
    condition_idx = np.zeros(3, dtype=np.int64)
    pending_exit_i = np.full(3, -1, dtype=np.int64)
    pending_exit_reason = np.zeros(3, dtype=np.int64)
    entry = np.zeros(3)
    stop = np.zeros(3)
    target = np.zeros(3)
    extreme = np.zeros(3)
    mfe = np.zeros(3)
    specified = np.zeros(3)
    n_result, n_equity, pointer = 0, 0, 0
    pending_event, pending_i, basket_event, basket_condition = -1, -1, -1, -1
    pending_side, basket_side, basket_id, next_leg = 0, 0, -1, 0
    pending_anchor, pending_threshold, pending_atr, pending_deadline = 0., 0., 0., 0.
    basket_atr, basket_first, basket_start, basket_realized = 0., 0., 0., 0.
    basket_add_i, last_valid, total_closed, total_wins, total_loss_count, opened = -1, -1, 0, 0, 0, 0
    last_exit, realized, realized_atr, profit, loss, high, dd, high_atr, dd_atr = -np.inf, 0., 0., 0., 0., 0., 0., 0., 0.
    gross_peak, last_minute, new_events, expired, cancelled = 0, -np.inf, 0, 0, 0
    additions_cancelled = False
    latest_event, entry_gap_count, exit_gap_count, ideal_advantage = -1, 0, 0, 0.
    final_equity, final_atr, final_gross = 0., 0., 0
    for i in range(len(seq)):
        now, price = time[i], last[i]
        event = -1
        while pointer < len(event_i) and event_i[pointer] <= i:
            latest_event = pointer
            if event_i[pointer] == i:
                event = pointer
            pointer += 1
        if not np.isfinite(price) or price <= 0:
            continue
        last_valid = i
        in_us = us_open - us_before * 60 <= now < us_open + us_after * 60
        blocked_entry = now < start + warmup * 60 or now >= limit - entry_deadline * 60 or (us_pause and in_us)
        closed_this_row = False
        # ----------------------------------------
        # 前行までに設定された返済条件を先に判定する。同じ行の極値はここへ遡及させない。
        for j in range(cap):
            if not active[j]:
                continue
            direction = side[j]
            observed_favorable = max(0., direction * (price - entry[j]))
            mfe[j] = max(mfe[j], observed_favorable)
            fill, reason, exit_condition = 0., 0, i
            if pending_exit_i[j] >= 0 and i > pending_exit_i[j]:
                fill, reason, exit_condition = price, pending_exit_reason[j], pending_exit_i[j]
            elif i > entry_idx[j] and direction * (price - stop[j]) <= 0:
                fill, reason = stop[j], 1
            elif i > entry_idx[j] and direction * (price - target[j]) >= 0:
                fill, reason = target[j], 2
            if reason:
                points = direction * (fill - entry[j])
                if reason in (1, 2) and abs(fill - price) > .000001:
                    exit_gap_count += 1
                    ideal_advantage += direction * (fill - price)
                result[n_result] = np.array([basket_id, j, direction, basket_event, condition_idx[j],
                    entry_idx[j], i, basket_atr, entry[j], fill, stop[j], extreme[j], mfe[j], reason,
                    1., points, (now - time[entry_idx[j]]) / 60, exit_condition, specified[j],
                    seq[basket_condition], seq[entry_idx[j]], seq[i]], dtype=np.float64)
                n_result += 1
                active[j], pending_exit_i[j] = False, -1
                realized += points
                realized_atr += points / basket_atr
                basket_realized += points
                profit += max(0., points)
                loss += min(0., points)
                total_closed += 1
                total_wins += int(points > 0)
                total_loss_count += int(points < 0)
                closed_this_row = True
                additions_cancelled = True
        active_count = 0
        basket_mark = basket_realized
        for j in range(cap):
            if active[j]:
                active_count += 1
                basket_mark += side[j] * (price - entry[j])
        if closed_this_row and active_count == 0:
            last_exit = now
            basket_event = -1
        # ----------------------------------------
        # 時間・反対信号・合算損益の返済は現在行で予約し、次の有効原本行で現在価格約定。
        for j in range(cap):
            if not active[j]:
                continue
            direction = side[j]
            reason = (4 if now >= limit else 6 if us_exit and in_us
                      else 3 if now >= time[entry_idx[j]] + hold_limit * 60
                      else 5 if reverse_exit and event >= 0 and event_side[event] * direction_multiplier == -direction
                      else 7 if basket_mark <= -basket_stop * basket_atr
                      else 8 if basket_mark >= basket_target * basket_atr else 0)
            if reason and pending_exit_i[j] < 0:
                pending_exit_i[j], pending_exit_reason[j] = i, reason
                additions_cancelled = True
            if pending_exit_i[j] >= 0:
                continue
            extreme[j] = max(extreme[j], price) if direction > 0 else min(extreme[j], price)
            favorable = max(0., direction * (extreme[j] - entry[j]))
            width = trail_width
            if favorable >= tight_trigger * basket_atr:
                width = min(width, tight_width)
            if now >= time[entry_idx[j]] + time_tighten * 60:
                width = min(width, time_width)
            if favorable >= state_trigger * basket_atr:
                if latest_event > basket_event and event_side[latest_event] * direction_multiplier == -direction:
                    width = min(width, opposite_width)
                if board[i] == -direction:
                    width = min(width, weak_width)
            if in_us:
                width = min(width, us_width)
            candidate = stop[j]
            if favorable >= trail_start * basket_atr:
                candidate = rounded(extreme[j] - direction * width * basket_atr, -direction, tick)
            if favorable >= be_trigger * basket_atr:
                candidate = max(candidate, entry[j]) if direction > 0 else min(candidate, entry[j])
            if favorable >= protect_trigger * basket_atr:
                protect = rounded(entry[j] + direction * favorable * protect_fraction, -direction, tick)
                candidate = max(candidate, protect) if direction > 0 else min(candidate, protect)
            stop[j] = max(stop[j], candidate) if direction > 0 else min(stop[j], candidate)
        # ----------------------------------------
        # 有限追加の価格は最初の新規約定で固定。追加後に再利用せず、返済があれば残注文を取消す。
        if basket_event >= 0 and active_count > 0 and not additions_cancelled and not blocked_entry and i > basket_add_i:
            for j in range(next_leg, cap):
                if add_mode not in (2., 3.):
                    break
                sign = 1 if add_mode == 2 else -1
                threshold = rounded(basket_first + basket_side * sign * add_step * basket_atr * j,
                                    basket_side * sign, tick)
                if basket_side * sign * (price - threshold) < 0:
                    break
                active[j], side[j], entry_idx[j], condition_idx[j] = True, basket_side, i, basket_add_i
                if abs(threshold - price) > .000001:
                    entry_gap_count += 1
                    ideal_advantage += basket_side * (price - threshold)
                entry[j], specified[j], extreme[j] = threshold, threshold, threshold
                stop[j] = rounded(threshold - basket_side * initial_width * basket_atr, -basket_side, tick)
                target[j] = rounded(threshold + basket_side * targets[j] * basket_atr, basket_side, tick)
                mfe[j], pending_exit_i[j] = max(0., basket_side * (price - threshold)), -1
                next_leg, opened = j + 1, opened + 1
        # ----------------------------------------
        # 未約定入口は前行の指定値を使う。現在価格から追跡値を変更するのは判定後。
        if pending_event >= 0:
            if now > pending_deadline or blocked_entry:
                expired += int(now > pending_deadline)
                cancelled += int(now <= pending_deadline)
                pending_event = -1
            elif i > pending_i:
                direction, fill, reached = pending_side, pending_threshold, False
                if entry_mode == 0:
                    fill, reached = price, True
                elif entry_mode in (1., 2.):
                    reached = direction * (price - pending_threshold) >= 0
                elif entry_mode == 3:
                    reached = direction * (price - pending_threshold) <= 0
                else:
                    up = rounded(pending_anchor + entry_width * pending_atr, 1., tick)
                    down = rounded(pending_anchor - entry_width * pending_atr, -1., tick)
                    if price >= up:
                        direction, fill, reached = 1, up, True
                    elif price <= down:
                        direction, fill, reached = -1, down, True
                if reached:
                    basket_id += 1
                    basket_event, basket_condition, basket_side = pending_event, pending_i, direction
                    basket_atr, basket_first, basket_start, basket_realized = pending_atr, fill, now, 0.
                    basket_add_i, additions_cancelled = i, False
                    count = cap if add_mode in (1., 4.) else 1
                    for j in range(count):
                        d = -direction if add_mode == 4 and j == 1 else direction
                        if entry_mode != 0 and abs(fill - price) > .000001:
                            entry_gap_count += 1
                            ideal_advantage += d * (price - fill)
                        active[j], side[j], entry_idx[j], condition_idx[j] = True, d, i, pending_i
                        entry[j], specified[j], extreme[j] = fill, (np.nan if entry_mode == 0 else fill), fill
                        stop[j] = rounded(fill - d * initial_width * basket_atr, -d, tick)
                        target[j] = rounded(fill + d * targets[j] * basket_atr, d, tick)
                        mfe[j], pending_exit_i[j] = max(0., d * (price - fill)), -1
                        opened += 1
                    next_leg, pending_event = count, -1
                elif event >= 0 and event_side[event] * direction_multiplier == -pending_side:
                    pending_event = -1
                    cancelled += 1
                elif entry_mode == 2:
                    pending_anchor = min(pending_anchor, price) if direction > 0 else max(pending_anchor, price)
                    pending_threshold = rounded(pending_anchor + direction * entry_width * pending_atr, direction, tick)
        # ----------------------------------------
        # 新しいイベントは設定にのみ使う。設定した行では絶対に入口を約定させない。
        any_active = False
        for j in range(cap):
            any_active = any_active or active[j]
        if event >= 0 and not any_active and pending_event < 0 and not closed_this_row and not blocked_entry and now >= last_exit + cooldown * 60:
            if np.isfinite(atr[i]) and atr[i] > 0:
                pending_event, pending_i = event, i
                pending_side, pending_anchor, pending_atr = int(event_side[event] * direction_multiplier), price, max(atr[i], tick * 2)
                pending_deadline = min(event_deadline[event], now + age_limit * 60)
                sign = -1 if entry_mode == 3 else 1
                pending_threshold = rounded(price + pending_side * sign * entry_width * pending_atr,
                                            pending_side * sign, tick)
                new_events += 1
        # ----------------------------------------
        # 全脚を現在価格で同時評価し、利益脚だけの決済でも含み損を除外しない。
        mark, mark_atr, gross = realized, realized_atr, 0
        for j in range(cap):
            if active[j]:
                value = side[j] * (price - entry[j])
                mark += value
                mark_atr += value / basket_atr
                gross += 1
        high, high_atr = max(high, mark), max(high_atr, mark_atr)
        dd, dd_atr = max(dd, high - mark), max(dd_atr, high_atr - mark_atr)
        gross_peak = max(gross_peak, gross)
        final_equity, final_atr, final_gross = mark, mark_atr, gross
        minute = np.floor(now / 60)
        if detail and (minute != last_minute or i == len(seq) - 1):
            equity[n_equity] = np.array([now, seq[i], mark * multiplier, mark_atr, gross, realized * multiplier, dd * multiplier])
            n_equity += 1
            last_minute = minute
    if last_valid >= 0:
        i = last_valid
        for j in range(cap):
            if active[j]:
                points = side[j] * (last[i] - entry[j])
                result[n_result] = np.array([basket_id, j, side[j], basket_event, condition_idx[j], entry_idx[j], i,
                    basket_atr, entry[j], last[i], stop[j], extreme[j], mfe[j], 0., 0., points,
                    (time[i] - time[entry_idx[j]]) / 60, pending_exit_i[j], specified[j],
                    seq[basket_condition], seq[entry_idx[j]], seq[i]], dtype=np.float64)
                n_result += 1
        if detail and (n_equity == 0 or equity[n_equity - 1, 1] != seq[i]):
            equity[n_equity] = np.array([time[i], seq[i], final_equity * multiplier, final_atr,
                                        final_gross, realized * multiplier, dd * multiplier])
            n_equity += 1
    stats = np.array([final_equity * multiplier, realized * multiplier, profit * multiplier, loss * multiplier,
                      (final_equity - realized) * multiplier, final_atr, realized_atr, dd * multiplier, dd_atr,
                      total_closed, total_wins, total_loss_count, final_gross, gross_peak, opened,
                      new_events, expired, cancelled, int(pending_event >= 0), entry_gap_count,
                      exit_gap_count, ideal_advantage * multiplier], dtype=np.float64)
    return result[:n_result], equity[:n_equity], stats


def simulate(prepared: dict, family: str, config: dict, detail: bool = False) -> dict:
    """機能: 一系統の信号と指定条件を再生し、費用ゼロの集計を返す。

    引数: prepared (dict)、family (str)、config (dict)、detail (bool)。
    返り値: summary/raw/trades/equity/diagnosticsを持つ結果 (dict)。
    """
    p, targets = parameters(config)
    events = prepared['families'].get(family, {})
    board = prepared['board_side'] if 'board_side' in prepared else np.zeros(len(prepared['seq']), dtype=np.int64)
    trend = prepared['trend_side'] if 'trend_side' in prepared else np.zeros(len(prepared['seq']), dtype=np.int64)
    raw, equity, stats = replay(prepared['time_s'], prepared['seq'], prepared['last'], prepared['atr'],
        board, trend,
        events.get('indices', np.zeros(0, dtype=np.int64)), events.get('sides', np.zeros(0, dtype=np.int64)),
        events.get('deadlines', np.zeros(0)), p, targets, prepared['start'], prepared['limit'], prepared['tick'],
        prepared['us_open'], MULTIPLIERS[prepared['symbol']], detail)
    names = ['net_yen', 'closed_net_yen', 'profit_yen', 'loss_yen', 'open_yen', 'net_atr',
             'closed_net_atr', 'max_drawdown_yen', 'max_drawdown_atr', 'closed_count',
             'win_count', 'loss_count', 'open_count', 'gross_peak', 'entry_count',
             'accepted_events', 'expired_entries', 'cancelled_entries', 'pending_entries',
             'ideal_entry_gap_count', 'ideal_exit_gap_count', 'ideal_fill_benefit_yen']
    summary = dict(zip(names, stats.tolist()))
    for name in names[9:-1]:
        summary[name] = int(summary[name])
    summary['win_rate'] = summary['win_count'] / summary['closed_count'] if summary['closed_count'] else None
    summary['cap_net_yen'] = summary['net_yen'] / int(p[15])
    summary['cap_net_atr'] = summary['net_atr'] / int(p[15])
    summary['fee_yen'] = 0.
    summary['spread_cost_yen'] = 0.
    summary['ideal_fill_gap_count'] = summary['ideal_entry_gap_count'] + summary['ideal_exit_gap_count']
    trades = []
    if detail:
        for row in raw:
            trade = dict(zip(RAW_COLUMNS, row.tolist()))
            trade.update(銘柄=prepared['symbol'], セッション=prepared['session'],
                         条件設定時刻=float(prepared['time_s'][int(row[4])]),
                         新規時刻=float(prepared['time_s'][int(row[5])]),
                         返済評価時刻=float(prepared['time_s'][int(row[6])]),
                         収支円=float(row[15] * MULTIPLIERS[prepared['symbol']]),
                         返済理由=REASONS[int(row[13])])
            trades.append(trade)
    diagnostics = dict(費用=0, 気配差控除=0, 監視価格='原本CurrentPrice',
                       条件価格約定='前行までの指定価格。ギャップも指定価格で約定する理想仮定',
                       時間返済='条件成立の次の有効原本行のCurrentPrice',
                       同行追跡変更='変更した条件は次行以降に有効',
                       追加上限=int(p[15]), 現在未返済枚数=summary['open_count'])
    return dict(summary=summary, raw=raw, trades=trades, equity=equity, diagnostics=diagnostics)
