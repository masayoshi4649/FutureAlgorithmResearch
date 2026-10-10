"""保存した生板の方向判定と、全気配行を監視する売買再生。"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
ARCHIVE = ROOT / 'アルゴリズム調査' / '00001_波検知と売買ポイントの調査' / '保存版'
sys.dont_write_bytecode = True
sys.path.insert(0, str(ARCHIVE / 'work' / 'wave_v4'))
from signals import build_features, get_signals

SESSIONS = ['2026-09-21_Day', '2026-09-21_Night', '2026-09-22_Day', '2026-09-22_Night', '2026-09-23_Day', '2026-09-23_Night']
SYMBOLS = ['NK225', 'TOPIX']
TICKS = {'NK225': 10., 'TOPIX': .5}
MULTIPLIERS = {'NK225': 1000, 'TOPIX': 10000}
FAMILIES = {
    'B01': '最良数量の偏り', 'B02': '５段数量の偏り', 'B03': '10段数量の偏り',
    'B04': '最良と10段の偏りの差', 'B05': '最良気配OFI', 'B06': '気配の更新方向',
    'B07': '表示数量の増加', 'B08': '表示数量の減少', 'B09': '表示数量の純変化',
    'B10': '約定方向推定出来高', 'B11': '数量偏りとOFIの一致', 'B12': '板フローの多数決',
    'P00': '価格CUSUM', 'H01': '価格CUSUMとOFIの一致', 'H02': '価格CUSUMと多数決の一致',
}


def save(path: Path, value: object) -> None:
    """機能: 日本語JSONを保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    def convert(item):
        """機能: 日時と数値配列をJSON互換値に変換する。

        引数: item (object)。返り値: 変換した値 (object)。
        """
        if isinstance(item, dict):
            return {str(k): convert(v) for k, v in item.items()}
        if isinstance(item, (list, tuple, np.ndarray)):
            return [convert(v) for v in item]
        if isinstance(item, np.generic):
            item = item.item()
        if isinstance(item, float) and not np.isfinite(item):
            return None
        if isinstance(item, (Path, pd.Timestamp)):
            return str(item)
        return item
    path.write_text(json.dumps(convert(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def bounds(session: str) -> tuple[float, float]:
    """機能: 新規開始の基準時刻とセッション内の返済時刻を求める。

    引数: session (str)。返り値: 開始と返済のUnix秒 (tuple[float, float])。
    """
    day = pd.Timestamp(session[:10], tz='Asia/Tokyo')
    start = day + pd.Timedelta(hours=17) if session.endswith('Night') else day + pd.Timedelta(hours=8, minutes=45)
    limit = day + pd.Timedelta(days=1, hours=5, minutes=50) if session.endswith('Night') else day + pd.Timedelta(hours=15, minutes=35)
    return start.timestamp(), limit.timestamp()


def configs() -> list[dict]:
    """機能: 結果に依存しない108条件を列挙する。

    引数: なし。返り値: 条件辞書の一覧 (list[dict])。
    """
    result = []
    for family in FAMILIES:
        for window in ([60, 300] if family.startswith('B') else [0] if family == 'P00' else [300]):
            for entry in ['逆指値', '追跡1ATR']:
                for exit_name in ['利益保護', '板反転併用']:
                    code = f'{family}_{window}_{entry}_{exit_name}'
                    result.append(dict(id=code, family=family, window=window, entry=entry, exit=exit_name,
                                       group='板のみ' if family.startswith('B') else '価格のみ' if family == 'P00' else '価格と板'))
    assert len(result) == 108
    return result


def persist(values: np.ndarray, times: np.ndarray, seconds: float) -> np.ndarray:
    """機能: 同方向が指定秒続いた後にだけ方向を有効にする。

    引数: values/times (ndarray)、seconds (float)。返り値: 過去のみで確認した方向 (ndarray)。
    """
    output = np.zeros(len(values), dtype=np.int8)
    previous, since = 0, 0.
    for i, (value, time) in enumerate(zip(values, times)):
        if value != previous or (i and time - times[i - 1] > 60):
            previous, since = value, time
        if value and time - since >= seconds:
            output[i] = value
    return output


def directions(frame: pd.DataFrame, price: np.ndarray) -> tuple[dict, np.ndarray]:
    """機能: 解放済み板ブロックだけから12系統と混合方向を計算する。

    引数: frame (DataFrame)、price (ndarray) は同時点の確定足CUSUM。
    返り値: 系統・窓別方向と返済用方向 (tuple[dict, ndarray])。
    """
    times = frame.time_s.to_numpy(float)
    indexed = frame.set_index(pd.to_datetime(times, unit='s', utc=True))
    stale = frame.block_delay_seconds.to_numpy(float) > 60
    numeric = indexed.select_dtypes(include='number').copy()
    numeric.loc[stale, :] = np.nan
    output = {('P00', 0): price.astype(np.int8)}
    pressure = np.zeros(len(frame), dtype=np.int8)
    for window in [60, 300]:
        rolling = numeric.rolling(f'{window}s', min_periods=5).sum()
        weight = frame.valid_event_count.to_numpy(float).copy()
        weight[stale] = np.nan
        def mean(column):
            """機能: ブロック内有効行数を重みにした直近平均を求める。

            引数: column (str)。返り値: 加重平均 (ndarray)。
            """
            weighted = pd.Series(frame[column].to_numpy(float) * weight, index=indexed.index)
            return (weighted.rolling(f'{window}s', min_periods=5).sum() / rolling.valid_event_count.replace(0, np.nan)).to_numpy()
        def ratio(numerator, denominator):
            """機能: 合算フローの比率をゼロ除算せず求める。

            引数: numerator/denominator (Series)。返り値: 比率 (ndarray)。
            """
            return (numerator / denominator.replace(0, np.nan)).to_numpy()
        def sign(values, threshold):
            """機能: 対称な閾値で正負の方向を分類する。

            引数: values (ndarray)、threshold (float)。返り値: 方向 (ndarray)。
            """
            return np.where(values >= threshold, 1, np.where(values <= -threshold, -1, 0)).astype(np.int8)
        r = rolling
        im1, im5, im10 = mean('imb1'), mean('imb5'), mean('imb10')
        ofi = ratio(r.ofi_signed, r.ofi_abs)
        quote = ratio(r.quote_up - r.quote_down, r.quote_up + r.quote_down)
        added = ratio(r.added_bid - r.added_ask, r.added_bid + r.added_ask)
        removed = ratio(r.removed_ask - r.removed_bid, r.removed_ask + r.removed_bid)
        net = ratio(r.added_bid + r.removed_ask - r.added_ask - r.removed_bid,
                    r.added_bid + r.removed_ask + r.added_ask + r.removed_bid)
        trade = ratio(r.trade_pos - r.trade_neg, r.trade_pos + r.trade_neg + r.trade_unknown)
        votes = np.stack([sign(ofi, .1), sign(quote, .1), sign(net, .1)])
        consensus = np.where(((votes == 1).sum(axis=0) >= 2) & ~(votes == -1).any(axis=0), 1,
                            np.where(((votes == -1).sum(axis=0) >= 2) & ~(votes == 1).any(axis=0), -1, 0))
        agree = sign(im1, .1)
        agree = np.where(agree == sign(ofi, .075), agree, 0)
        values = [sign(im1, .2), sign(im5, .15), sign(im10, .1), sign(im1 - im10, .15),
                  sign(ofi, .15), sign(quote, .15), sign(added, .15), sign(removed, .15),
                  sign(net, .12), sign(trade, .2), agree, consensus]
        for number, value in enumerate(values, 1):
            value[stale] = 0
            output[(f'B{number:02d}', window)] = persist(value, times, 30)
        if window == 300:
            for family, source in [('H01', 'B05'), ('H02', 'B12')]:
                board = output[(source, window)]
                output[(family, window)] = np.where(price == board, price, 0).astype(np.int8)
            opposing = sign(ofi, .1)
            opposing = np.where(opposing == sign(quote, .1), opposing, 0)
            opposing[stale] = 0
            pressure = persist(opposing, times, 60)
    return output, pressure


def price_features(session: str, symbol: str, event_times: np.ndarray, cutoff: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """機能: 確定足に追加1分の待機を課したATRとCUSUMを作る。

    引数: session/symbol (str)、event_times (ndarray)、cutoff (float|None)。
    返り値: 各イベント時点のATRと価格方向 (tuple[ndarray, ndarray])。
    """
    root = ROOT / 'work' / 'wave_v7' / 'live' if session == SESSIONS[-1] else ROOT
    frames = []
    for interval in [1, 5]:
        frame = pd.read_csv(root / f'candle_{interval}min' / symbol / f'{session}.csv')
        frame['time'] = pd.to_datetime(frame.time)
        frame = frame[frame.closed.astype(str).str.lower().eq('true')].set_index('time')
        if cutoff is not None:
            available = frame.index.as_unit('ns').asi8 / 1e9 + (interval + 1) * 60
            frame = frame.loc[available <= cutoff]
        frames.append(frame)
    one, five = frames
    known_end = pd.Timestamp(float(np.max(event_times)) - 120, unit='s', tz=one.index.tz).floor('min')
    z = build_features(one, five, None, TICKS[symbol], known_end)
    signs = get_signals(z, z, 9, .75).to_numpy()
    available = z.index.as_unit('ns').asi8 / 1e9 + 120
    pos = np.searchsorted(available, event_times, side='right') - 1
    valid = pos >= 0
    atr = np.full(len(event_times), np.nan)
    direction = np.zeros(len(event_times), dtype=np.int8)
    atr[valid] = z.atr.to_numpy()[pos[valid]]
    direction[valid] = signs[pos[valid]]
    return atr, direction


def simulate(tape: dict, features: pd.DataFrame, signal: np.ndarray, atr: np.ndarray, pressure: np.ndarray,
             config: dict, session: str, symbol: str, delay: str = '次行') -> list[dict]:
    """機能: 全生板の順序で条件注文を監視し、成立後の気配で1枚の売買を再生する。

    引数: tape (dict)、features (DataFrame)、signal/atr/pressure (ndarray)、
    config (dict)、session/symbol/delay (str)。返り値: 確定・未返済取引 (list[dict])。
    """
    time, seq, bid, ask = (tape[key] for key in ['time_s', 'seq', 'bid', 'ask'])
    bidqty, askqty = tape['bid_qty'], tape['ask_qty']
    feature_pos = np.searchsorted(features.seq.to_numpy(), seq, side='right') - 1
    feature_time = features.time_s.to_numpy(float)
    start, limit = bounds(session)
    tick = TICKS[symbol]
    pending = position = queued = None
    last_exit = -np.inf
    trades = []
    def round_stop(value, direction):
        """機能: 買い閾値を上、売り閾値を下の呼値へ丸める。

        引数: value (float)、direction (int)。返り値: 閾値価格 (float)。
        """
        return (np.ceil(value / tick) if direction > 0 else np.floor(value / tick)) * tick
    def enqueue(kind, i, payload):
        """機能: 成立した条件を次の観測以降の約定待ちにする。

        引数: kind (str)、i (int)、payload (dict)。返り値: 待機情報 (dict)。
        """
        return dict(kind=kind, index=i, time=float(time[i]), payload=payload)
    def ready(order, i):
        """機能: 指定した観測遅延を満たしたかを判定する。

        引数: order (dict)、i (int)。返り値: 約定評価可能性 (bool)。
        """
        return i >= order['index'] + (2 if delay == '２行後' else 1) and (delay != '次時刻' or time[i] > order['time'])
    for i in range(len(time)):
        now, b, a = float(time[i]), float(bid[i]), float(ask[i])
        fi = feature_pos[i]
        direction = int(signal[fi]) if fi >= 0 else 0
        fresh = fi >= 0 and now - feature_time[fi] <= 60
        if config['group'] != '価格のみ' and not fresh:
            direction = 0
            pending = None
        current_atr = float(atr[fi]) if fi >= 0 else np.nan
        # ----------------------------------------
        # 前行以前に成立した注文だけを現在の最良気配で評価する。
        if queued and ready(queued, i):
            if queued['kind'] == '新規':
                p = queued['payload']
                side = p['side']
                if now < limit - 1800 and (askqty[i] if side > 0 else bidqty[i]) >= 1:
                    fill = a if side > 0 else b
                    position = dict(side=side, entry_price=fill, entry_time_s=now, entry_seq=int(seq[i]),
                                    atr=p['atr'], signal_seq=p['signal_seq'], source_last_seq=p['source_last_seq'],
                                    signal_time_s=p['signal_time_s'], trigger_seq=p['trigger_seq'],
                                    extreme=fill, stop=round_stop(fill - side * 2.5 * p['atr'], -side),
                                    max_favorable=0., entry_spread=a-b)
                pending, queued = None, None
                continue
            else:
                side = position['side']
                fill = b if side > 0 else a
                points = side * (fill - position['entry_price']) - 2 * tick
                trades.append(dict(**position, closed=True, exit_time_s=now, exit_seq=int(seq[i]), exit_price=fill,
                                   exit_reason=queued['payload']['reason'], exit_trigger_seq=queued['payload']['trigger_seq'],
                                   net_points=points, stress_points=points-2*tick, duration_min=(now-position['entry_time_s'])/60,
                                   exit_spread=a-b, exit_in_session=now < limit + 600))
                position, queued, pending, last_exit = None, None, None, now
                continue
        if queued:
            continue
        # ----------------------------------------
        # 保有中は同一時刻内の全気配変動も損切り・追跡に反映する。
        if position:
            side, A = position['side'], position['atr']
            executable = b if side > 0 else a
            reason = None
            if now >= limit:
                reason = 'セッション内返済'
            elif side * (executable - position['stop']) <= 0:
                reason = '保護ストップ'
            elif config['exit'] == '板反転併用' and fresh and pressure[fi] == -side:
                reason = '板フロー反転'
            if reason:
                queued = enqueue('返済', i, dict(reason=reason, trigger_seq=int(seq[i])))
                continue
            position['extreme'] = max(position['extreme'], executable) if side > 0 else min(position['extreme'], executable)
            favorable = side * (position['extreme'] - position['entry_price'])
            position['max_favorable'] = max(position['max_favorable'], favorable)
            width = .5 if favorable >= 2.5 * A else 4.
            candidate = round_stop(position['extreme'] - side * width * A, -side)
            position['stop'] = max(position['stop'], candidate) if side > 0 else min(position['stop'], candidate)
            continue
        if now < start + 2700 or now >= limit - 1800 or now - last_exit < 2700:
            pending = None
            continue
        if not np.isfinite(current_atr) or current_atr <= 0:
            continue
        if pending and (now - pending['created'] > 1500 or direction == -pending['side']):
            pending = None
        if pending is None and direction:
            side = direction
            quote = a if side > 0 else b
            pending = dict(side=side, atr=current_atr, created=now, anchor=quote,
                           threshold=round_stop(quote + side * (current_atr if config['entry'] == '追跡1ATR' else 0), side),
                           signal_seq=int(seq[i]), source_last_seq=int(features.source_last_seq.iloc[fi]),
                           signal_time_s=now, created_index=i)
            continue
        if pending and i > pending['created_index']:
            side = pending['side']
            quote = a if side > 0 else b
            if side * (quote - pending['threshold']) >= 0:
                pending['trigger_seq'] = int(seq[i])
                queued = enqueue('新規', i, pending.copy())
                pending = None
                continue
            if config['entry'] == '追跡1ATR':
                pending['anchor'] = min(pending['anchor'], quote) if side > 0 else max(pending['anchor'], quote)
                pending['threshold'] = round_stop(pending['anchor'] + side * pending['atr'], side)
    if position:
        now, side = float(time[-1]), position['side']
        fill = float(bid[-1] if side > 0 else ask[-1])
        points = side * (fill - position['entry_price']) - 2 * tick
        trades.append(dict(**position, closed=False, mark_time_s=now, mark_price=fill,
                           net_points=points, stress_points=points-2*tick,
                           duration_min=(now-position['entry_time_s'])/60,
                           pending_exit=queued['payload']['reason'] if queued and queued['kind'] == '返済' else None))
    return trades


def metrics(trades: list[dict], session: str, symbol: str, config: dict, delay: str = '次行') -> dict:
    """機能: spreadと追加費用を控除した確定損益を未返済と分けて集計する。

    引数: trades (list[dict])、session/symbol (str)、config (dict)、delay (str)。返り値: 集計辞書 (dict)。
    """
    closed = [t for t in trades if t['closed']]
    net = np.array([t['net_points'] * MULTIPLIERS[symbol] for t in closed])
    return dict(方式=config['id'], 群=config['group'], セッション=session, 銘柄=symbol, 約定遅延=delay,
                取引数=len(closed), 未返済数=len(trades)-len(closed), 勝ち数=int((net > 0).sum()),
                利益円=float(net[net > 0].sum()), 損失円=float(-net[net < 0].sum()), 収支円=float(net.sum()),
                費用倍収支円=float(sum(t['stress_points']*MULTIPLIERS[symbol] for t in closed)),
                費用倍ATR収支=float(sum(t['stress_points']/t['atr'] for t in closed)),
                評価損益円=float(sum(t['net_points']*MULTIPLIERS[symbol] for t in trades if not t['closed'])),
                平均保有分=float(np.mean([t['duration_min'] for t in closed])) if closed else None,
                最大順行からの返却円=float(sum(max(0, t['max_favorable']-t['net_points']-2*TICKS[symbol])*MULTIPLIERS[symbol] for t in closed)))
