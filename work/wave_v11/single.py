"""予測だけの定時返済と、予測に注文条件を組み合わせる単建玉再生器。"""

from __future__ import annotations

from pathlib import Path
import importlib.util
from zoneinfo import ZoneInfo
from datetime import datetime

import numpy as np
import pandas as pd
from numba import njit

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
_spec = importlib.util.spec_from_file_location('wave_v10_previous_execution', ROOT / 'work' / 'wave_v9' / 'execution.py')
_previous = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_previous)
TICKS, MULTIPLIERS, bounds, metrics, save = (_previous.TICKS, _previous.MULTIPLIERS,
                                           _previous.bounds, _previous.metrics, _previous.save)

DEFAULTS = dict(entry_offset=.25, max_age_min=10., cooldown_min=10., warmup_min=20.,
                initial_stop_atr=2., trail_atr=2., trail_start_atr=0.,
                tighten_trigger_atr=np.inf, tighten_width_atr=2.,
                breakeven_trigger_atr=np.inf, protect_trigger_atr=np.inf, protect_fraction=0.,
                time_tighten_min=np.inf, time_width_atr=2., opposite_width_atr=np.inf,
                weak_width_atr=np.inf, us_mode='なし', us_before_min=15., us_after_min=30.,
                us_width_atr=2., entry_deadline_min=30., time_min_progress_atr=np.inf,
                state_trigger_atr=0., entry_mode=0., holding_min=np.inf, target_atr=np.inf)
PARAMETERS = list(DEFAULTS)
US_MODES = {'なし': 0., '幅変更': 1., '新規停止': 2., '返済': 3., '順行確認': 4.}
REASONS = {0: None, 1: '損切り・追跡ストップ', 2: 'セッション内返済', 3: '米国開始前後の返済',
           4: '固定時間で返済', 5: '目標利益の条件成立'}


def prepare(tape: dict, events: pd.DataFrame, session: str, symbol: str,
            state: dict | None = None, us_open: float | None = None) -> dict:
    """機能: 配列の因果順序を確認し、高速再生用の入力を一度だけ準備する。

    引数: tape (dict)、events (DataFrame)、session/symbol (str)、state (dict|None)、
    us_open (float|None) は米国現物開始のUnix秒。返り値: 準備済み入力 (dict)。
    """
    state = state or {}
    seq = np.ascontiguousarray(tape['seq'], dtype=np.int64)
    values = {key: np.ascontiguousarray(tape[key], dtype=np.float64)
              for key in ('time_s', 'bid', 'ask', 'bid_qty', 'ask_qty', 'atr')}
    if len(seq) == 0 or np.any(np.diff(seq) <= 0) or np.any(np.diff(values['time_s']) < 0):
        raise ValueError('気配は空でなく、行番号が昇順、代理時刻が非減少である必要があります。')
    if any(len(value) != len(seq) for value in values.values()):
        raise ValueError('気配配列の長さが一致しません。')
    if np.any(values['ask'] < values['bid']):
        raise ValueError('売り気配が買い気配を下回っています。')
    families = {}
    for family, group in events.groupby('family', sort=False):
        rows = group.sort_values('seq').to_dict('records')
        event_seq = np.array([row['seq'] for row in rows], dtype=np.int64)
        indices = np.searchsorted(seq, event_seq)
        if np.any(indices >= len(seq)) or np.any(seq[indices] != event_seq):
            raise ValueError('イベントの公開行が気配にありません。')
        if len(np.unique(event_seq)) != len(event_seq):
            raise ValueError('同系統の同じ行に複数イベントがあります。')
        if any(row['source_last_seq'] >= row['seq'] for row in rows):
            raise ValueError('イベント公開より前に素材を確定する必要があります。')
        if np.any(np.abs(np.array([row['time_s'] for row in rows]) - values['time_s'][indices]) > .00001):
            raise ValueError('イベント時刻が公開行時刻と一致しません。')
        families[family] = dict(rows=rows, indices=indices.astype(np.int64),
                                sides=np.array([row['side'] for row in rows], dtype=np.int64),
                                times=np.array([row['time_s'] for row in rows], dtype=np.float64),
                                deadlines=np.array([row['deadline_time_s'] for row in rows], dtype=np.float64))
    if us_open is None:
        # 時間帯は夏時間を含めて変換する。NYSE休場・短縮日の取引暦判定は別途必要。
        us_open = (datetime.fromisoformat(session[:10] + 'T09:30:00').replace(tzinfo=ZoneInfo('America/New_York')).timestamp()
                   if session.endswith('Night') else np.inf)
    prepared = dict(seq=seq, **values, families=families, session=session, symbol=symbol,
                    start=bounds(session)[0], limit=bounds(session)[1], tick=TICKS[symbol], us_open=float(us_open),
                    supplied_state=set(state))
    for name in ('board_side', 'trend_side'):
        value = np.ascontiguousarray(state.get(name, np.zeros(len(seq))), dtype=np.int64)
        if len(value) != len(seq) or np.any(~np.isin(value, [-1, 0, 1])):
            raise ValueError(f'{name}は各気配と同じ長さの-1/0/1配列が必要です。')
        prepared[name] = value
    return prepared


def parameters(config: dict) -> np.ndarray:
    """機能: 設定を検証し、固定順の数値配列へ変換する。

    引数: config (dict)。返り値: 高速再生用設定配列 (ndarray)。
    """
    combined = dict(DEFAULTS, **config)
    for name in PARAMETERS:
        if combined[name] is None:
            combined[name] = np.inf
    if combined['us_mode'] not in US_MODES:
        raise ValueError('未知の米国開始処理です。')
    for name in PARAMETERS:
        if name != 'us_mode' and (np.isnan(combined[name]) or combined[name] < 0):
            raise ValueError(f'{name}は非負数で指定してください。')
    if combined['initial_stop_atr'] <= 0 or combined['trail_atr'] <= 0 or combined['protect_fraction'] > 1:
        raise ValueError('初期損切り・追跡幅は正数、保全率は0〜1で指定してください。')
    if combined['entry_mode'] not in (0., 1., 2.):
        raise ValueError('entry_mode は追跡0、成行1、固定逆指値2です。')
    return np.array([US_MODES[combined[name]] if name == 'us_mode' else combined[name] for name in PARAMETERS], dtype=np.float64)


@njit(cache=True)
def rounded(value, side, tick):
    """機能: 買い成立価格を上、売り成立価格を下の呼値へ丸める。

    引数: value/side/tick (float)。返り値: 呼値へ丸めた価格 (float)。
    """
    return (np.ceil(value / tick) if side > 0 else np.floor(value / tick)) * tick


@njit(cache=True)
def replay(time, seq, bid, ask, bid_qty, ask_qty, atr, board, trend, event_i, event_side,
           event_time, event_deadline, p, start, limit, tick, us_open, delay):
    """機能: 全気配を観測順に一度だけ走査し、注文と建玉を更新する。

    引数: 気配・状態・イベントのndarray群、p (ndarray)、時刻・呼値 (float)、delay (int)。
    返り値: 売買記録の数値行列 (ndarray)。列の意味はsimulateで日本語理由付きに復元する。
    """
    (entry_offset, max_age_min, cooldown_min, warmup_min, initial_stop_atr, trail_atr, trail_start_atr,
     tighten_trigger_atr, tighten_width_atr, breakeven_trigger_atr, protect_trigger_atr, protect_fraction,
     time_tighten_min, time_width_atr, opposite_width_atr, weak_width_atr, us_mode, us_before_min,
     us_after_min, us_width_atr, entry_deadline_min, time_min_progress_atr, state_trigger_atr,
     entry_mode, holding_min, target_atr) = p
    result = np.full((len(event_i) + 1, 21), np.nan)
    count = 0
    consumed = np.zeros(len(event_i), dtype=np.bool_)
    latest, pointer = -1, 0
    pending, held, queued = -1, -1, 0
    pending_side, condition_i, trigger_i = 0, 0, 0
    pending_a, anchor, threshold, deadline = 0., 0., 0., 0.
    side, entry_i, exit_trigger_i, queue_i, exit_reason = 0, 0, 0, 0, 0
    A, entry, stop, extreme, favorable, queue_time, last_exit = 0., 0., 0., 0., 0., 0., -np.inf
    held_condition, held_trigger = 0, 0
    width_at_entry = 0.
    for i in range(len(seq)):
        now, b, a = time[i], bid[i], ask[i]
        in_us = us_open - us_before_min * 60 <= now < us_open + us_after_min * 60
        while pointer < len(event_i) and event_i[pointer] <= i:
            latest = pointer
            pointer += 1
        if held >= 0:
            # 表示用の最大順行には、返済成立行と約定待ちの気配も含める。
            # この更新だけで前行ストップを変更せず、同じ行への遡及約定を防ぐ。
            observed = b if side > 0 else a
            extreme = max(extreme, observed) if side > 0 else min(extreme, observed)
            favorable = max(favorable, side * (extreme - entry))
        # ----------------------------------------
        # 成立済み注文の次行約定を優先する。後から現れた反対信号で遡及取消しない。
        if queued and i >= queue_i + (2 if delay == 2 else 1) and (delay != 3 or now > queue_time):
            if queued == 1:
                if now < limit - entry_deadline_min * 60 and (ask_qty[i] if pending_side > 0 else bid_qty[i]) >= 1:
                    held, side, A = pending, pending_side, pending_a
                    held_condition, held_trigger = condition_i, trigger_i
                    entry_i, entry = i, a if side > 0 else b
                    width_at_entry = initial_stop_atr
                    stop = rounded(entry - side * width_at_entry * A, -side, tick)
                    extreme, favorable = entry, 0.
                pending, queued = -1, 0
                continue
            fill = b if side > 0 else a
            points = side * (fill - entry) - 2 * tick
            result[count] = np.array([held, side, held_condition, held_trigger, entry_i, i, A,
                                      entry, fill, stop, extreme, favorable, exit_reason, 1,
                                      points, points - 2 * tick, (now - time[entry_i]) / 60,
                                      exit_trigger_i, 0, width_at_entry, i], dtype=np.float64)
            count += 1
            held, queued, last_exit = -1, 0, now
            continue
        if queued:
            continue
        # ----------------------------------------
        # 前行までのストップを先に判定し、現在行による短縮は次行から有効にする。
        if held >= 0:
            quote = b if side > 0 else a
            exit_reason = (2 if now >= limit else 3 if in_us and us_mode == 3
                           else 1 if side * (quote - stop) <= 0
                           else 4 if now - time[entry_i] >= holding_min * 60
                           else 5 if side * (quote - entry) >= target_atr * A else 0)
            if exit_reason:
                queued, queue_i, queue_time, exit_trigger_i = 2, i, now, i
                continue
            extreme = max(extreme, quote) if side > 0 else min(extreme, quote)
            favorable = max(favorable, side * (extreme - entry))
            width = us_width_atr if in_us and us_mode == 1 else trail_atr
            if favorable >= tighten_trigger_atr * A:
                width = min(width, tighten_width_atr)
            if now - time[entry_i] >= time_tighten_min * 60 and favorable < time_min_progress_atr * A:
                width = min(width, time_width_atr)
            if favorable >= state_trigger_atr * A:
                if latest >= 0 and latest > held and event_side[latest] == -side:
                    width = min(width, opposite_width_atr)
                if board[i] == -side:
                    width = min(width, weak_width_atr)
            candidate = stop
            if favorable >= trail_start_atr * A:
                candidate = rounded(extreme - side * width * A, -side, tick)
            if favorable >= breakeven_trigger_atr * A:
                protected = rounded(entry + side * 2 * tick, -side, tick)
                candidate = max(candidate, protected) if side > 0 else min(candidate, protected)
            if favorable >= protect_trigger_atr * A:
                protected = rounded(entry + side * favorable * protect_fraction, -side, tick)
                candidate = max(candidate, protected) if side > 0 else min(candidate, protected)
            stop = max(stop, candidate) if side > 0 else min(stop, candidate)
            continue
        if now < start + warmup_min * 60 or now >= limit - entry_deadline_min * 60 or now - last_exit < cooldown_min * 60:
            pending = -1
            continue
        if in_us and (us_mode == 2 or us_mode == 3):
            pending = -1
            continue
        # ----------------------------------------
        # 旧条件の成立を先に判定してから、反対イベントや時間帯の取消を処理する。
        if pending >= 0 and now > deadline:
            pending = -1
        if pending >= 0 and i > condition_i:
            quote = a if pending_side > 0 else b
            if pending_side * (quote - threshold) >= 0:
                trigger_i, queued, queue_i, queue_time = i, 1, i, now
                continue
        if pending >= 0 and latest > pending and event_side[latest] == -pending_side:
            pending = -1
        if pending >= 0:
            if entry_offset > 0 and entry_mode == 0:
                quote = a if pending_side > 0 else b
                anchor = min(anchor, quote) if pending_side > 0 else max(anchor, quote)
                threshold = rounded(anchor + pending_side * entry_offset * pending_a, pending_side, tick)
            continue
        if latest < 0 or consumed[latest] or now > min(event_deadline[latest], event_time[latest] + max_age_min * 60):
            continue
        if not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        pending_side = event_side[latest]
        if in_us and us_mode == 4 and trend[i] != pending_side:
            continue
        pending, pending_a, condition_i = latest, atr[i], i
        anchor = a if pending_side > 0 else b
        threshold = rounded(anchor + pending_side * entry_offset * pending_a, pending_side, tick)
        deadline = min(event_deadline[latest], event_time[latest] + max_age_min * 60)
        consumed[latest] = True
        if entry_mode == 1:
            # 確定済み信号の現在行で成行要求し、約定は必ず後続の有効気配に遅らせる。
            trigger_i, queued, queue_i, queue_time = i, 1, i, now
    if held >= 0:
        i = len(seq) - 1
        fill = bid[i] if side > 0 else ask[i]
        points = side * (fill - entry) - 2 * tick
        result[count] = np.array([held, side, held_condition, held_trigger, entry_i, i, A,
                                  entry, fill, stop, extreme, favorable, 0, 0,
                                  points, points - 2 * tick, (time[i] - time[entry_i]) / 60,
                                  exit_trigger_i, exit_reason if queued == 2 else 0, width_at_entry, i], dtype=np.float64)
        count += 1
    return result[:count]


def simulate_array(prepared: dict, config: dict, delay: str = '次行') -> np.ndarray:
    """機能: 設定一つを再生し、辞書化を省いて高速集計用の数値行列を返す。

    引数: prepared (dict)、config (dict)、delay (str)。返り値: 確定・未返済売買行列 (ndarray)。
    """
    p = parameters(config)
    if np.isfinite(config.get('weak_width_atr', np.inf)) and 'board_side' not in prepared['supplied_state']:
        raise ValueError('板弱化による短縮には因果的なboard_side配列が必要です。')
    if config.get('us_mode') == '順行確認' and 'trend_side' not in prepared['supplied_state']:
        raise ValueError('米国開始の順行確認には因果的なtrend_side配列が必要です。')
    family = prepared['families'].get(config['family'])
    if family is None:
        return np.empty((0, 21), dtype=np.float64)
    delays = {'次行': 1, '２行後': 2, '次時刻': 3}
    if delay not in delays:
        raise ValueError('未知の約定遅延です。')
    return replay(*(prepared[name] for name in ('time_s', 'seq', 'bid', 'ask', 'bid_qty', 'ask_qty', 'atr', 'board_side', 'trend_side')),
                  family['indices'], family['sides'], family['times'], family['deadlines'], p, prepared['start'], prepared['limit'],
                  prepared['tick'], prepared['us_open'], delays[delay])


def summary(prepared: dict, config: dict, delay: str = '次行', raw: np.ndarray | None = None) -> dict:
    """機能: 全売買辞書を生成せず、確定収支と未返済評価を分離して集計する。

    引数: prepared/config (dict)、delay (str)、raw (ndarray|None)。返り値: 既存互換集計 (dict)。
    """
    if raw is None:
        raw = simulate_array(prepared, config, delay)
    closed, opened = raw[raw[:, 13] == 1], raw[raw[:, 13] == 0]
    multiplier, tick = MULTIPLIERS[prepared['symbol']], prepared['tick']
    net = closed[:, 14] * multiplier
    return dict(方式=config['id'], 群=config.get('group', config['family']), 系統=config['family'],
                セッション=prepared['session'], 銘柄=prepared['symbol'], 約定遅延=delay,
                取引数=len(closed), 未返済数=len(opened), 勝ち数=int((net > 0).sum()),
                利益円=float(net[net > 0].sum()), 損失円=float(-net[net < 0].sum()), 収支円=float(net.sum()),
                費用倍収支円=float(closed[:, 15].sum() * multiplier),
                費用倍ATR収支=float((closed[:, 15] / closed[:, 6]).sum()),
                評価損益円=float(opened[:, 14].sum() * multiplier),
                平均保有分=float(closed[:, 16].mean()) if len(closed) else None,
                最大順行からの返却円=float(np.maximum(0, closed[:, 11] - closed[:, 14] - 2 * tick).sum() * multiplier),
                平均利益円=float(net[net > 0].mean()) if np.any(net > 0) else None,
                平均損失円=float(-net[net < 0].mean()) if np.any(net < 0) else None,
                最悪取引円=float(net.min()) if len(net) else None,
                最大保有分=float(closed[:, 16].max()) if len(closed) else None)


def simulate(prepared: dict, config: dict, delay: str = '次行') -> list[dict]:
    """機能: 準備済み気配から設定一つを再生し、既存形式の売買辞書を返す。

    引数: prepared (dict)、config (dict)、delay (str)。返り値: 確定・未返済売買 (list[dict])。
    """
    raw = simulate_array(prepared, config, delay)
    family = prepared['families'].get(config['family'])
    result = []
    seq, time = prepared['seq'], prepared['time_s']
    for row in raw:
        event = family['rows'][int(row[0])]
        condition, trigger, entry, last = (int(row[x]) for x in (2, 3, 4, 5))
        event_i = int(family['indices'][int(row[0])])
        trade = dict(side=int(row[1]), event_id=event['event_id'], atr=float(row[6]), event_atr=float(event['atr']),
                     signal_time_s=float(event['time_s']), signal_seq=int(event['seq']),
                     signal_price=float((prepared['bid'][event_i] + prepared['ask'][event_i]) / 2),
                     source_last_seq=int(event['source_last_seq']), reason=event.get('reason', ''),
                     condition_time_s=float(time[condition]), condition_seq=int(seq[condition]), trigger_seq=int(seq[trigger]),
                     entry_time_s=float(time[entry]), entry_seq=int(seq[entry]), entry_price=float(row[7]),
                     entry_spread=float(prepared['ask'][entry] - prepared['bid'][entry]),
                     stop=float(row[9]), extreme=float(row[10]), max_favorable=float(row[11]), closed=bool(row[13]),
                     net_points=float(row[14]), stress_points=float(row[15]), duration_min=float(row[16]),
                     initial_width_atr=float(row[19]))
        if trade['closed']:
            trade.update(exit_time_s=float(time[last]), exit_seq=int(seq[last]), exit_price=float(row[8]),
                         exit_reason=REASONS[int(row[12])], exit_trigger_seq=int(seq[int(row[17])]),
                         exit_spread=float(prepared['ask'][last] - prepared['bid'][last]),
                         exit_in_session=bool(time[last] < prepared['limit'] + 300))
        else:
            trade.update(mark_time_s=float(time[last]), mark_price=float(row[8]), pending_exit=REASONS[int(row[18])])
        result.append(trade)
    if len({trade['event_id'] for trade in result}) != len(result):
        raise AssertionError('同じ転換イベントを再利用しています。')
    return result


def v9_config(config: dict) -> dict:
    """機能: 前回90条件の設定を同じ挙動の今回形式へ変換する。

    引数: config (dict)。返り値: 比較用設定 (dict)。
    """
    width = 1. if config['exit'] == '追跡1ATR' else 2.
    result = dict(id=config['id'], family=config['family'], group=config['group'],
                  entry_offset=.25 if config['entry'] == '追跡0.25ATR' else 0.,
                  initial_stop_atr=width, trail_atr=width,
                  max_age_min=config.get('expiry', 10), cooldown_min=config.get('cooldown', 10), warmup_min=config.get('warmup', 20))
    if config['exit'] == '順行1ATRで保護':
        result.update(tighten_trigger_atr=1., tighten_width_atr=.5)
    return result
