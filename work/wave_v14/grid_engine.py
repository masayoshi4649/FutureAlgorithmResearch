"""有限枚数の指値・逆指値格子を原本現在価格で再生し、全建玉を同時評価する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from numba import njit

OUT = Path(__file__).resolve().parent
TICKS = {'NK225': 10., 'TOPIX': .5}
MULTIPLIERS = {'NK225': 1000., 'TOPIX': 10000.}
DEFAULTS = dict(entry_kind='limit', directions='both', max_legs=10, gap_mode='atr', gap_value=.5,
    target_gap=1., initial_stop_gap=None, trail_gap=None, trail_start_gap=0.,
    tighten_start_gap=None, tighten_gap=.5, protect_start_gap=None, protect_fraction=0.,
    holding_min=None, basket_stop_gap=None, basket_target_gap=None,
    basket_trail_start_gap=None, basket_trail_gap=None, session_stop_gap=None,
    disable_add_after_loss=False, rearm='fixed', reset_min=5., warmup_min=20., entry_deadline_min=30.)
ENTRY_KINDS = {'limit': 0, 'stop': 1, 'mixed': 2}
DIRECTIONS = {'both': 0, 'long': 1, 'short': -1}
REARMS = {'fixed': 0, 'advance': 1}
PARAMETERS = ['entry_kind', 'directions', 'max_legs', 'gap_mode', 'gap_value', 'target_gap',
    'initial_stop_gap', 'trail_gap', 'trail_start_gap', 'tighten_start_gap', 'tighten_gap',
    'protect_start_gap', 'protect_fraction', 'holding_min', 'basket_stop_gap', 'basket_target_gap',
    'basket_trail_start_gap', 'basket_trail_gap', 'session_stop_gap', 'disable_add_after_loss',
    'rearm', 'reset_min', 'warmup_min', 'entry_deadline_min']
RAW_COLUMNS = ['サイクル番号', '脚番号', '方向', 'イベント番号', '条件行位置',
               '新規行位置', '返済評価行位置', '固定ATR', '新規価格', '返済評価価格',
               '最終ストップ', '順行極値', '最大順行幅', '理由番号', '返済済み',
               '収支ポイント', '保有分', '返済条件行位置', '新規指定価格',
               '信号原本行番号', '新規原本行番号', '返済評価原本行番号']
REASONS = {0: '打切り時評価', 1: '個別損切り・追跡', 2: '利益幅による返済',
    3: '個別保有時間上限', 4: 'セッション内返済', 7: 'かご損失上限',
    8: '含み損益込みかご利確', 9: '含み損益込みかご追跡', 10: 'セッション損失上限'}


def catalog() -> list[dict]:
    """機能: 実データ損益を見る前に定める18思想と３つの格子幅を返す。

    引数: なし。返り値: 条件辞書の一覧 (list[dict])。
    """
    styles = [
        ('G01', '危険参照・上下指値の利益玉だけ返済', dict()),
        ('G02', '危険参照・買い指値10枠の利益玉だけ返済', dict(directions='long')),
        ('G03', '危険参照・売り指値10枠の利益玉だけ返済', dict(directions='short')),
        ('G04', '指値格子・損切１段と利確２段', dict(initial_stop_gap=1., target_gap=2.)),
        ('G05', '指値格子・かご損失５段で全返済', dict(basket_stop_gap=5.)),
        ('G06', '指値格子・滞留60分を返済', dict(holding_min=60.)),
        ('G07', '指値格子・含み込み３段利確とセッション損失上限',
         dict(basket_target_gap=3., session_stop_gap=10.)),
        ('G08', '指値格子・含み込みかご追跡で利益保護',
         dict(basket_stop_gap=5., basket_trail_start_gap=3., basket_trail_gap=1.)),
        ('G09', '指値格子・損切り発生後は追加停止',
         dict(initial_stop_gap=1., target_gap=2., disable_add_after_loss=True)),
        ('G10', '逆指値格子・損切１段と利確２段',
         dict(entry_kind='stop', initial_stop_gap=1., target_gap=2.)),
        ('G11', '逆指値格子・順行増玉と２段追跡',
         dict(entry_kind='stop', initial_stop_gap=.75, target_gap=None, trail_gap=2., trail_start_gap=1., rearm='advance')),
        ('G12', '逆指値格子・順行利益75%の保護',
         dict(entry_kind='stop', initial_stop_gap=1., target_gap=None, trail_gap=2., trail_start_gap=1.,
              protect_start_gap=2., protect_fraction=.75)),
        ('G13', '買い逆指値10枠・順行追跡',
         dict(entry_kind='stop', directions='long', initial_stop_gap=1., target_gap=None, trail_gap=2., trail_start_gap=1., rearm='advance')),
        ('G14', '売り逆指値10枠・順行追跡',
         dict(entry_kind='stop', directions='short', initial_stop_gap=1., target_gap=None, trail_gap=2., trail_start_gap=1., rearm='advance')),
        ('G15', '上下の指値と逆指値を各２枠併設',
         dict(entry_kind='mixed', max_legs=8, initial_stop_gap=1., target_gap=2., holding_min=90.)),
        ('G16', '逆指値格子・かご追跡と滞留上限',
         dict(entry_kind='stop', initial_stop_gap=1., target_gap=None, trail_gap=2., trail_start_gap=1.,
              basket_stop_gap=5., basket_trail_start_gap=4., basket_trail_gap=1., holding_min=90.)),
        ('G17', '指値格子・順行後0.75段追跡',
         dict(initial_stop_gap=2., target_gap=None, trail_gap=.75, trail_start_gap=1.)),
        ('G18', '指値格子・個別利確なしで全玉一括返済',
         dict(target_gap=None, basket_stop_gap=5., basket_target_gap=5., holding_min=90.)),
    ]
    rows = []
    for family, label, values in styles:
        for code, gap_name, gap_cfg in [('A05', '0.5ATR', dict(gap_mode='atr', gap_value=.5)),
                                        ('A10', '1ATR', dict(gap_mode='atr', gap_value=1.)),
                                        ('T10', '10呼値・TOPIX５ポイント', dict(gap_mode='ticks', gap_value=10.))]:
            cfg = dict(DEFAULTS, **values)
            cfg.update(gap_cfg)
            cfg.update(id=f'{family}_{code}', family=family, philosophy='有限格子と全建玉管理',
                       group='利益玉だけ返済の危険参照' if family in ('G01', 'G02', 'G03') else '格子の損失・利益管理',
                       origin='新規注文方式', label=f'{label}／幅{gap_name}',
                       dangerous_reference=family in ('G01', 'G02', 'G03'))
            rows.append(cfg)
    return rows


def save_catalog() -> dict:
    """機能: 損益を参照せず条件一覧と配置解釈を一度だけ保存する。

    引数: なし。返り値: 条件固定記録 (dict)。
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    OUT.mkdir(parents=True, exist_ok=True)
    cfgs = catalog()
    record = dict(固定時刻=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), 条件数=len(cfgs),
                  思想数=len({cfg['family'] for cfg in cfgs}), 損益参照前=True, API取得回数=0,
                  条件一覧=cfgs,
                  配置解釈='開始20分後の有効価格が中心。上下型は買い５枠・売り５枠、片側型は10枠。併設型は上下指値各２＋上下逆指値各２の８枠。',
                  再配置='固定型は返済後に同水準へ戻す。逆指値は価格が水準手前へ戻ってから再突破。前進型は返済価格のさらに順行１段先へ移動。新条件は次行から有効。',
                  リスク='全保有上限10枚。利益脚のみ返済の参照も含み損とセッション強制返済を除外しない。')
    with (OUT / '格子条件_損益前固定.json').open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2, allow_nan=False)
    return record


def parameters(config: dict) -> np.ndarray:
    """機能: 枚数上限と格子の条件を検証し、数値設定へ変換する。

    引数: config (dict)。返り値: 再生用設定配列 (ndarray)。
    """
    cfg = dict(DEFAULTS, **config)
    if cfg['entry_kind'] not in ENTRY_KINDS or cfg['directions'] not in DIRECTIONS or cfg['rearm'] not in REARMS:
        raise ValueError('未知の格子方式です')
    cap = cfg['max_legs']
    if int(cap) != cap or cap < 1 or cap > 10:
        raise ValueError('格子の最大枚数は１〜10枚です')
    if cfg['directions'] == 'both' and cap % 2:
        raise ValueError('対称格子の枠数は偶数です')
    if cfg['entry_kind'] == 'mixed' and (cfg['directions'] != 'both' or cap % 4):
        raise ValueError('指値・逆指値併設は上下対称かつ４の倍数枠です')
    if cfg['gap_mode'] not in ('atr', 'ticks'):
        raise ValueError('格子幅はATRまたは呼値数で指定してください')
    cfg['entry_kind'], cfg['directions'], cfg['rearm'] = ENTRY_KINDS[cfg['entry_kind']], DIRECTIONS[cfg['directions']], REARMS[cfg['rearm']]
    cfg['gap_mode'] = int(cfg['gap_mode'] == 'ticks')
    for key in PARAMETERS:
        cfg[key] = np.inf if cfg[key] is None else float(cfg[key])
        if np.isnan(cfg[key]) or (cfg[key] < 0 and key != 'directions'):
            raise ValueError(f'{key}は非負数またはNoneにしてください')
    for key in ('gap_value', 'target_gap', 'initial_stop_gap', 'trail_gap', 'tighten_gap',
                'basket_stop_gap', 'basket_target_gap', 'basket_trail_gap', 'session_stop_gap'):
        if cfg[key] <= 0:
            raise ValueError(f'{key}は正数またはNoneにしてください')
    if cfg['protect_fraction'] > 1:
        raise ValueError('利益保全率は０〜１です')
    return np.array([cfg[key] for key in PARAMETERS], dtype=float)


@njit(cache=True)
def rounded(value, direction, tick):
    """機能: 上方向条件を切上げ、下方向条件を切下げて呼値に合わせる。

    引数: value/direction/tick (float)。返り値: 指定価格 (float)。
    """
    if not np.isfinite(value):
        return value
    return (np.ceil(value / tick) if direction > 0 else np.floor(value / tick)) * tick


@njit(cache=True)
def append_row(result, count, row):
    """機能: 固定上限枚数の再配置による可変数の取引を配列へ追記する。

    引数: result/row (ndarray)、count (int)。返り値: 配列と新件数 (tuple[ndarray, int])。
    """
    if count >= len(result):
        larger = np.empty((max(16, len(result) * 2), 22))
        larger[:len(result)] = result
        result = larger
    result[count] = row
    return result, count + 1


@njit(cache=True)
def replay(time, seq, price, atr, p, start, limit, tick, multiplier, detail):
    """機能: 有限格子の条件・再配置・全建玉返済を原本順で逐次再生する。

    引数: 原本と設定のndarray群、開始・終了・呼値・倍率 (float)、detail (bool)。
    返り値: 売買・評価曲線・集計 (tuple[ndarray, ndarray, ndarray])。
    """
    (entry_kind, directions, cap, gap_mode, gap_value, target_gap, initial_gap, trail_gap,
     trail_start, tighten_start, tighten_gap, protect_start, protect_fraction, holding_min,
     basket_stop, basket_target, basket_trail_start, basket_trail_gap, session_stop,
     ban_after_loss, rearm, reset_min, warmup, entry_deadline) = p
    cap = int(cap)
    active, pending, armed = np.zeros(cap, dtype=np.bool_), np.zeros(cap, dtype=np.bool_), np.zeros(cap, dtype=np.bool_)
    sides, kinds = np.zeros(cap, dtype=np.int64), np.zeros(cap, dtype=np.int64)
    condition_i, entry_i, exit_i = np.zeros(cap, dtype=np.int64), np.zeros(cap, dtype=np.int64), np.full(cap, -1, dtype=np.int64)
    arm_i, queued_reason = np.zeros(cap, dtype=np.int64), np.zeros(cap, dtype=np.int64)
    levels, fixed_levels, entries, stops, targets = np.zeros(cap), np.zeros(cap), np.zeros(cap), np.zeros(cap), np.zeros(cap)
    extremes, mfe, entry_conditions = np.zeros(cap), np.zeros(cap), np.zeros(cap, dtype=np.int64)
    result = np.empty((256, 22))
    capacity = int(max(0., time[-1] - time[0]) // 60) + 4 if detail else 1
    equity = np.zeros((capacity, 7))
    n_result = n_equity = 0
    realized = realized_atr = profit = loss = high = high_atr = dd = dd_atr = 0.
    cycle_realized = cycle_high = cycle_atr = gap = first_gap = 0.
    cycle, cycle_origin, last_valid = -1, -1, -1
    cycle_live, closing, halted = False, False, False
    next_cycle = start + warmup * 60
    total_closed = win_count = loss_count = gross_peak = total_opened = 0
    gap_entry_count = gap_exit_count = placements = resets = 0
    ideal_benefit = final_mark = final_atr = 0.
    final_gross = 0
    last_minute = -np.inf
    for i in range(len(seq)):
        now, current = time[i], price[i]
        if not np.isfinite(current) or current <= 0:
            continue
        last_valid = i
        prohibit = now >= limit - entry_deadline * 60
        # ----------------------------------------
        # 既存の返済条件だけを先に判定。新しい極値や新規条件を同じ行へ遡及しない。
        for j in range(cap):
            if not active[j]:
                continue
            side = sides[j]
            mfe[j] = max(mfe[j], side * (current - entries[j]))
            fill, reason, trigger = 0., 0, i
            if exit_i[j] >= 0 and i > exit_i[j]:
                fill, reason, trigger = current, queued_reason[j], exit_i[j]
            elif i > entry_i[j] and side * (current - stops[j]) <= 0:
                fill, reason = stops[j], 1
            elif i > entry_i[j] and side * (current - targets[j]) >= 0:
                fill, reason = targets[j], 2
            if not reason:
                continue
            points = side * (fill - entries[j])
            row = np.array([cycle, j, side, cycle, entry_conditions[j], entry_i[j], i, cycle_atr,
                entries[j], fill, stops[j], extremes[j], mfe[j], reason, 1., points,
                (now - time[entry_i[j]]) / 60, trigger, entries[j], seq[cycle_origin], seq[entry_i[j]], seq[i]])
            result, n_result = append_row(result, n_result, row)
            active[j], exit_i[j] = False, -1
            realized += points
            realized_atr += points / cycle_atr
            cycle_realized += points
            profit += max(0., points)
            loss += min(0., points)
            total_closed += 1
            win_count += int(points > 0)
            loss_count += int(points < 0)
            if reason in (1, 2) and abs(fill - current) > .000001:
                gap_exit_count += 1
                ideal_benefit += side * (fill - current)
            if points < 0 and ban_after_loss:
                halted = True
            if not closing and not halted and not prohibit:
                levels[j] = rounded(fill + side * gap, side, tick) if rearm else fixed_levels[j]
                condition_i[j], arm_i[j], pending[j] = i, i, True
                sign = side if kinds[j] else -side
                armed[j] = sign * (current - levels[j]) < 0
                placements += 1
        # ----------------------------------------
        # 個別利確を差し引く前後を問わず、同じかごの全確定・含み損益で保護を判定。
        gross, cycle_mark = 0, cycle_realized
        for j in range(cap):
            if active[j]:
                gross += 1
                cycle_mark += sides[j] * (current - entries[j])
        global_mark = realized + cycle_mark - cycle_realized
        reason = 0
        if now >= limit:
            reason, halted = 4, True
        elif cycle_live and global_mark <= -session_stop * first_gap:
            reason, halted = 10, True
        elif cycle_live and not closing:
            if cycle_mark <= -basket_stop * gap:
                reason = 7
            elif cycle_mark >= basket_target * gap:
                reason = 8
            elif cycle_high >= basket_trail_start * gap and cycle_mark <= cycle_high - basket_trail_gap * gap:
                reason = 9
        if reason:
            closing = True
            for j in range(cap):
                pending[j] = False
                if active[j] and exit_i[j] < 0:
                    exit_i[j], queued_reason[j] = i, reason
        if halted or prohibit:
            pending[:] = False
        if cycle_live:
            cycle_high = max(cycle_high, cycle_mark)
        if cycle_live and (closing or halted or prohibit) and gross == 0:
            cycle_live, closing = False, False
            next_cycle = now + reset_min * 60
            resets += 1
        # ----------------------------------------
        # 既存建玉の時間返済予約と追跡更新。強めた保護を再び緩めない。
        for j in range(cap):
            if not active[j] or exit_i[j] >= 0:
                continue
            side = sides[j]
            if now >= time[entry_i[j]] + holding_min * 60:
                exit_i[j], queued_reason[j] = i, 3
                continue
            extremes[j] = max(extremes[j], current) if side > 0 else min(extremes[j], current)
            favorable = max(0., side * (extremes[j] - entries[j]))
            width = min(trail_gap, tighten_gap) if favorable >= tighten_start * gap else trail_gap
            candidate = stops[j]
            if favorable >= trail_start * gap:
                candidate = rounded(extremes[j] - side * width * gap, -side, tick)
            if favorable >= protect_start * gap:
                protected = rounded(entries[j] + side * favorable * protect_fraction, -side, tick)
                candidate = max(candidate, protected) if side > 0 else min(candidate, protected)
            stops[j] = max(stops[j], candidate) if side > 0 else min(stops[j], candidate)
        # ----------------------------------------
        # 空枠の再配置は、条件作成行より後、価格が成立側へ再度入ったときだけ約定する。
        if cycle_live and not closing and not halted and not prohibit:
            for j in range(cap):
                if not pending[j] or active[j] or i <= condition_i[j]:
                    continue
                side = sides[j]
                sign = side if kinds[j] else -side
                if not armed[j]:
                    if sign * (current - levels[j]) < 0:
                        armed[j], arm_i[j] = True, i
                    continue
                if i <= arm_i[j] or sign * (current - levels[j]) < 0:
                    continue
                fill = levels[j]
                entries[j], extremes[j], entry_i[j] = fill, fill, i
                stops[j] = rounded(fill - side * initial_gap * gap, -side, tick)
                targets[j] = rounded(fill + side * target_gap * gap, side, tick)
                mfe[j], entry_conditions[j] = max(0., side * (current - fill)), condition_i[j]
                pending[j], active[j], exit_i[j] = False, True, -1
                total_opened += 1
                if abs(fill - current) > .000001:
                    gap_entry_count += 1
                    ideal_benefit += side * (current - fill)
        # ----------------------------------------
        # 中心の新設定は最後に行い、その行では配置した注文を約定させない。
        if not cycle_live and not halted and not prohibit and now >= next_cycle and np.isfinite(atr[i]) and atr[i] > 0:
            cycle += 1
            cycle_live, cycle_origin = True, i
            cycle_atr = max(atr[i], tick * 2)
            gap = max(tick, np.ceil(gap_value * (tick if gap_mode else cycle_atr) / tick) * tick)
            if first_gap == 0:
                first_gap = gap
            cycle_realized, cycle_high = 0., 0.
            for j in range(cap):
                if entry_kind == 2:
                    quarter = cap // 4
                    group = j // quarter
                    side = 1 if group in (0, 2) else -1
                    kind = 0 if group < 2 else 1
                    rank = j % quarter + 1
                else:
                    half = cap // 2
                    side = (1 if j < half else -1) if directions == 0 else int(directions)
                    kind = int(entry_kind)
                    rank = j % half + 1 if directions == 0 else j + 1
                sign = side if kind else -side
                sides[j], kinds[j] = side, kind
                levels[j] = rounded(current + sign * rank * gap, sign, tick)
                fixed_levels[j] = levels[j]
                pending[j], armed[j], condition_i[j], arm_i[j] = True, True, i, i
                placements += 1
        # ----------------------------------------
        # 含み損のある脚を含めて毎行評価し、確定利確だけによる見かけの利益を除く。
        mark, mark_atr, gross = realized, realized_atr, 0
        for j in range(cap):
            if active[j]:
                value = sides[j] * (current - entries[j])
                mark += value
                mark_atr += value / cycle_atr
                gross += 1
        high, high_atr = max(high, mark), max(high_atr, mark_atr)
        dd, dd_atr = max(dd, high - mark), max(dd_atr, high_atr - mark_atr)
        gross_peak = max(gross_peak, gross)
        final_mark, final_atr, final_gross = mark, mark_atr, gross
        minute = np.floor(now / 60)
        if detail and (minute != last_minute or i == len(seq) - 1):
            equity[n_equity] = np.array([now, seq[i], mark * multiplier, mark_atr, gross, realized * multiplier, dd * multiplier])
            n_equity += 1
            last_minute = minute
    if last_valid >= 0:
        i = last_valid
        for j in range(cap):
            if active[j]:
                points = sides[j] * (price[i] - entries[j])
                row = np.array([cycle, j, sides[j], cycle, entry_conditions[j], entry_i[j], i, cycle_atr,
                    entries[j], price[i], stops[j], extremes[j], mfe[j], 0., 0., points,
                    (time[i] - time[entry_i[j]]) / 60, exit_i[j], entries[j], seq[cycle_origin], seq[entry_i[j]], seq[i]])
                result, n_result = append_row(result, n_result, row)
        if detail and (n_equity == 0 or equity[n_equity - 1, 1] != seq[i]):
            equity[n_equity] = np.array([time[i], seq[i], final_mark * multiplier, final_atr,
                final_gross, realized * multiplier, dd * multiplier])
            n_equity += 1
    stats = np.array([final_mark * multiplier, realized * multiplier, profit * multiplier, loss * multiplier,
        (final_mark - realized) * multiplier, final_atr, realized_atr, dd * multiplier, dd_atr,
        total_closed, win_count, loss_count, final_gross, gross_peak, total_opened, placements,
        gap_entry_count, gap_exit_count, ideal_benefit * multiplier, cycle + 1, resets, int(halted), first_gap,
        cycle if cycle_live else -1])
    return result[:n_result].copy(), equity[:n_equity], stats


def simulate(prepared: dict, config: dict, detail: bool = False) -> dict:
    """機能: 費用ゼロの有限格子を再生し、v13互換の記録と全玉評価を返す。

    引数: prepared (dict)、config (dict)、detail (bool)。返り値: 再生結果 (dict)。
    """
    p = parameters(config)
    symbol = prepared['symbol']
    seq = np.asarray(prepared['seq'], dtype=np.int64)
    times = np.asarray(prepared['time_s'], dtype=float)
    prices, atr = np.asarray(prepared['last'], dtype=float), np.asarray(prepared['atr'], dtype=float)
    if not len(seq) or any(len(array) != len(seq) for array in (times, prices, atr)):
        raise ValueError('原本配列の長さが不正です')
    if np.any(np.diff(seq) <= 0) or np.any(np.diff(times) < 0) or np.any(~np.isfinite(times)):
        raise ValueError('原本は昇順の行番号と非減少の有限時刻が必要です')
    raw, equity, values = replay(times, seq, prices, atr, p, prepared['start'], prepared['limit'],
        TICKS[symbol], MULTIPLIERS[symbol], detail)
    names = ['net_yen', 'closed_net_yen', 'profit_yen', 'loss_yen', 'open_yen', 'net_atr',
        'closed_net_atr', 'max_drawdown_yen', 'max_drawdown_atr', 'closed_count', 'win_count',
        'loss_count', 'open_count', 'gross_peak', 'entry_count', 'order_placements',
        'ideal_entry_gap_count', 'ideal_exit_gap_count', 'ideal_fill_benefit_yen', 'grid_cycles',
        'grid_resets', 'entry_halted', 'first_gap_points', 'incomplete_cycle_id']
    summary = dict(zip(names, values.tolist()))
    for key in names[9:18] + names[19:22]:
        summary[key] = int(summary[key])
    summary['incomplete_cycle_id'] = int(summary['incomplete_cycle_id'])
    summary.update(win_rate=summary['win_count'] / summary['closed_count'] if summary['closed_count'] else None,
        cap_net_yen=summary['net_yen'] / p[2], cap_net_atr=summary['net_atr'] / p[2],
        fee_yen=0., spread_cost_yen=0., ideal_fill_gap_count=summary['ideal_entry_gap_count'] + summary['ideal_exit_gap_count'])
    trades = []
    if detail:
        for row in raw:
            trade = dict(zip(RAW_COLUMNS, row.tolist()))
            trade.update(銘柄=symbol, セッション=prepared['session'],
                条件設定時刻=float(times[int(row[4])]), 新規時刻=float(times[int(row[5])]),
                返済評価時刻=float(times[int(row[6])]), 収支円=float(row[15] * MULTIPLIERS[symbol]),
                返済理由=REASONS[int(row[13])])
            trades.append(trade)
    return dict(summary=summary, raw=raw, trades=trades, equity=equity,
        incomplete_cycle_ids=[summary['incomplete_cycle_id']] if summary['incomplete_cycle_id'] >= 0 else [],
        diagnostics=dict(最大保有枚数=int(p[2]), 費用=0, 監視='CurrentPrice',
            再配置='同一価格再利用は価格が条件手前へ戻った後の再到達。新設定行で約定しない。',
            サイクル='中心設定からかご全返済・中心再設定またはセッション終了まで。途中利確再配置を同じ単位に含む。'))


def main() -> None:
    """機能: 実データを読み込まず条件表を保存する。

    引数: コマンドライン。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser(description='有限格子の損益前条件固定')
    parser.add_argument('--catalog', action='store_true', required=True)
    parser.parse_args()
    record = save_catalog()
    print(json.dumps(dict(条件数=record['条件数'], 思想数=record['思想数']), ensure_ascii=False))


if __name__ == '__main__':
    main()
