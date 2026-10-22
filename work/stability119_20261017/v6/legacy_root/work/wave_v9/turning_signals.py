"""確定足の収束と解放済み生板の反転から、一度限りの転換イベントを作る。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SESSIONS = ['2026-09-21_Day', '2026-09-21_Night', '2026-09-22_Day',
            '2026-09-22_Night', '2026-09-23_Day', '2026-09-23_Night']
TICKS = {'NK225': 10., 'TOPIX': .5}
FAMILIES = {
    'T00': '比較・CUSUM方向変化',
    'T01': 'EMA乖離の拡大から収束への変化',
    'T02': 'EMA3とEMA8の交差',
    'T03': 'EMA３本帯の圧縮から再拡散',
    'T04': 'MACDヒストグラムの増減反転',
    'T05': '短期EMAの傾き反転と長期乖離縮小',
    'T06': '最良気配OFIの正負反転',
    'T07': '短期OFIと長期OFIの交差',
    'T08': '気配更新方向の反転',
    'T09': '最良数量偏りの反転',
    'T10': '５段数量偏りの反転',
    'T11': '共通価格の表示数量純変化の反転',
    'T12': 'EMA収束転換と自銘柄板圧力転換',
    'T13': '両銘柄の板圧力転換',
    'T14': '他銘柄の板圧力転換後に自銘柄EMA転換',
}
GROUPS = {key: '比較CUSUM' if key == 'T00' else '移動平均転換' if key <= 'T05'
          else '単独板転換' if key <= 'T11' else '移動平均と板' if key == 'T12'
          else '２銘柄転換' for key in FAMILIES}
EVENT_COLUMNS = ['event_id', 'family', 'seq', 'time_s', 'side', 'atr',
                 'deadline_time_s', 'source_last_seq', 'reason',
                 'peer_seq', 'peer_source_last_seq', 'peer_time_s', 'peer_available_time_s']


def session_start(session: str) -> pd.Timestamp:
    """機能: 保存セッションの日本時間の開始を返す。

    引数: session (str)。返り値: 開始時刻 (Timestamp)。
    """
    day = pd.Timestamp(session[:10], tz='Asia/Tokyo')
    return day + pd.Timedelta(hours=17) if session.endswith('Night') else day + pd.Timedelta(hours=8, minutes=45)


def price_grid(session: str, symbol: str, last_time: float) -> pd.DataFrame:
    """機能: その時点で確定・待機済みの１分足と５分足から価格指標を作る。

    引数: session/symbol (str)、last_time (float): 利用可能な最終Unix秒。
    返り値: １分格子の因果的価格特徴 (DataFrame)。
    """
    root = ROOT / 'work' / 'wave_v7' / 'live' if session == SESSIONS[-1] else ROOT
    frames = []
    for interval in [1, 5]:
        frame = pd.read_csv(root / f'candle_{interval}min' / symbol / f'{session}.csv')
        frame['time'] = pd.to_datetime(frame.time)
        frame = frame[frame.closed.astype(str).str.lower().eq('true')].set_index('time').sort_index()
        available = frame.index.as_unit('ns').asi8 / 1e9 + (interval + 1) * 60
        frames.append(frame.loc[available <= last_time].copy())
    one, five = frames
    end = pd.Timestamp(last_time - 120, unit='s', tz='Asia/Tokyo').floor('min')
    if one.empty or end < session_start(session):
        return pd.DataFrame()
    if one.index.duplicated().any() or five.index.duplicated().any():
        raise ValueError('足時刻の重複は許可しません')
    grid = pd.date_range(session_start(session), end, freq='min')
    z = one.reindex(grid)
    observed = z.close.notna()
    z['close'] = z.close.ffill()
    seen = pd.Series(np.nan, index=grid)
    seen.loc[observed] = grid[observed].as_unit('ns').asi8 / 1e9
    z['stale_minutes'] = (grid.as_unit('ns').asi8 / 1e9 - seen.ffill()) / 60
    z['available_time_s'] = grid.as_unit('ns').asi8 / 1e9 + 120
    z['age'] = np.arange(len(grid))

    # ----------------------------------------
    # ATRは５分足の終了にさらに１分を足した時刻から利用する。
    ranges = pd.concat([five.high - five.low, (five.high - five.close.shift()).abs(),
                        (five.low - five.close.shift()).abs()], axis=1).max(axis=1)
    atr = ranges.ewm(alpha=1 / 12, adjust=False, min_periods=3).mean().clip(lower=2 * TICKS[symbol])
    atr.index += pd.Timedelta(minutes=4)
    z['atr'] = atr.reindex(grid, method='ffill')
    for span in [3, 8, 13, 21]:
        z[f'ema{span}'] = z.close.ewm(span=span, adjust=False, min_periods=span).mean()
    z['gap38'] = z.ema3 - z.ema8
    z['gap321'] = z.ema3 - z.ema21
    z['band'] = z[['ema3', 'ema8', 'ema21']].max(axis=1) - z[['ema3', 'ema8', 'ema21']].min(axis=1)
    z.loc[z.ema21.isna(), 'band'] = np.nan
    z['macd'] = z.ema3 - z.ema13
    z['hist'] = z.macd - z.macd.ewm(span=5, adjust=False, min_periods=5).mean()
    return z


def load_price_frame(session: str, symbol: str, cutoff: float | None = None) -> pd.DataFrame:
    """機能: 実際の判定と同じ価格指標を、利用可能時刻の索引で図解用に返す。

    引数: session/symbol (str)、cutoff (float|None): 利用可能時刻の上限。
    返り値: 利用可能時刻索引と元足時刻を持つ特徴表 (DataFrame)。
    """
    if cutoff is None:
        f = pd.read_csv(ROOT / 'work' / 'wave_v8' / 'features' / f'{symbol}_{session}.csv', usecols=['time_s'])
        if f.empty:
            return pd.DataFrame()
        cutoff = float(f.time_s.iloc[-1])
    output = price_grid(session, symbol, cutoff)
    if output.empty:
        return output
    output['source_bar_time'] = output.index
    output.index = pd.to_datetime(output.available_time_s, unit='s', utc=True).dt.tz_convert('Asia/Tokyo')
    output.index.name = 'available_time'
    return output


def minute_events(z: pd.DataFrame) -> list[dict]:
    """機能: 未来の極値を使わず確定済み指標の変化だけで価格転換を記録する。

    引数: z (DataFrame): １分格子。返り値: 価格転換イベント (list[dict])。
    """
    if z.empty:
        return []
    events = []
    positive = negative = 0.
    cusum_side = 0
    compression = None
    was_compressed = False
    records = z.to_dict('records')

    def add(i: int, family: str, side: int, detail: dict) -> None:
        """機能: 価格イベントに発生時刻とその時点の根拠を付ける。

        引数: i (int)、family (str)、side (int)、detail (dict)。返り値: なし (None)。
        """
        row = records[i]
        events.append(dict(family=family, side=int(side), minute_available_time_s=float(row['available_time_s']),
                           reason=dict(**detail, minute_available_time_s=float(row['available_time_s']),
                                       close=float(row['close']), ema3=float(row['ema3']), ema8=float(row['ema8']))))

    for i, row in enumerate(records):
        valid = np.isfinite(row['atr']) and row['stale_minutes'] <= 10
        if valid and row['age'] >= 14 and i and np.isfinite(records[i-1]['close']):
            change = (row['close'] - records[i-1]['close']) / row['atr']
            positive = max(0., positive + change - .025)
            negative = min(0., negative + change + .025)
            new_side = cusum_side
            if positive >= .6375:
                new_side, positive, negative = 1, 0., 0.
            elif negative <= -.6375:
                new_side, positive, negative = -1, 0., 0.
            if new_side != cusum_side:
                add(i, 'T00', new_side, dict(delta_atr=float(change)))
                cusum_side = new_side
        if not valid or row['stale_minutes'] > 1 or i < 3:
            compression, was_compressed = None, False
            continue
        p1, p2, p3 = records[i-1], records[i-2], records[i-3]
        if any(p['stale_minutes'] > 1 for p in [p1, p2, p3]):
            compression, was_compressed = None, False
            continue
        gap = row['gap38']
        old_gaps = [p['gap38'] for p in [p1, p2, p3]]
        if np.isfinite(gap) and all(np.isfinite(v) for v in old_gaps):
            sign = int(np.sign(gap))
            same_side = sign != 0 and all(np.sign(v) == sign for v in old_gaps[:2])
            contracted = abs(gap) < abs(old_gaps[0]) < abs(old_gaps[1])
            expanded_before = abs(old_gaps[1]) >= abs(old_gaps[2])
            if same_side and contracted and expanded_before and abs(old_gaps[1]) >= .1 * row['atr']:
                add(i, 'T01', -sign, dict(gap=float(gap), gap_previous=float(old_gaps[0]),
                                         gap_two_minutes_ago=float(old_gaps[1]), atr=float(row['atr'])))
            if gap > 0 and old_gaps[0] <= 0:
                add(i, 'T02', 1, dict(gap=float(gap), gap_previous=float(old_gaps[0])))
            elif gap < 0 and old_gaps[0] >= 0:
                add(i, 'T02', -1, dict(gap=float(gap), gap_previous=float(old_gaps[0])))

        # ----------------------------------------
        # 狭い帯への収束を準備状態とし、その後の拡散初動で方向を決める。
        compressed = bool(np.isfinite(row['band']) and row['band'] <= .6 * row['atr']
                          and row['band'] < p1['band'] < p2['band'])
        if compressed and not was_compressed:
            compression = dict(time=row['available_time_s'], width=row['band'], atr=row['atr'])
        was_compressed = compressed
        if compression is not None:
            if row['available_time_s'] - compression['time'] > 600:
                compression = None
            elif row['band'] >= compression['width'] + .05 * compression['atr']:
                slope = row['ema3'] - p1['ema3']
                direction = int(np.sign(slope)) if np.isfinite(slope) else 0
                if direction and direction * gap > 0 and row['band'] > p1['band']:
                    add(i, 'T03', direction, dict(band=float(row['band']), compressed_band=float(compression['width']),
                                                  compression_time_s=float(compression['time']), ema3_slope=float(slope)))
                    compression = None
        hist, h1, h2 = row['hist'], p1['hist'], p2['hist']
        if np.isfinite(hist) and np.isfinite(h1) and np.isfinite(h2) and abs(h1) >= .025 * row['atr']:
            if hist < 0 and hist > h1 and h1 <= h2:
                add(i, 'T04', 1, dict(hist=float(hist), hist_previous=float(h1), hist_two_minutes_ago=float(h2)))
            elif hist > 0 and hist < h1 and h1 >= h2:
                add(i, 'T04', -1, dict(hist=float(hist), hist_previous=float(h1), hist_two_minutes_ago=float(h2)))
        slope, old_slope = row['ema3'] - p1['ema3'], p1['ema3'] - p2['ema3']
        long_gap = row['gap321']
        shrinking = abs(long_gap) < abs(p1['gap321']) < abs(p2['gap321'])
        if np.isfinite(long_gap) and shrinking:
            if slope > 0 >= old_slope and long_gap < 0:
                add(i, 'T05', 1, dict(ema3_slope=float(slope), slope_previous=float(old_slope), gap321=float(long_gap)))
            elif slope < 0 <= old_slope and long_gap > 0:
                add(i, 'T05', -1, dict(ema3_slope=float(slope), slope_previous=float(old_slope), gap321=float(long_gap)))
    return events


def board_values(features: pd.DataFrame) -> pd.DataFrame:
    """機能: 解放済みブロックの過去60秒・300秒だけから板の転換用値を作る。

    引数: features (DataFrame)。返り値: 正規化したフローと数量偏り (DataFrame)。
    """
    if features.empty:
        return pd.DataFrame(index=features.index)
    numeric = features.select_dtypes(include='number').copy()
    numeric.index = pd.to_datetime(features.time_s.to_numpy(), unit='s', utc=True)
    stale = features.block_delay_seconds.to_numpy(float) > 60
    numeric.loc[stale, :] = np.nan
    output = pd.DataFrame(index=features.index)
    for window in [60, 300]:
        r = numeric.rolling(f'{window}s', min_periods=5).sum()
        output[f'ofi{window}'] = (r.ofi_signed / r.ofi_abs.replace(0, np.nan)).to_numpy()
        if window != 60:
            continue
        output['quote60'] = ((r.quote_up-r.quote_down)/(r.quote_up+r.quote_down).replace(0, np.nan)).to_numpy()
        output['net60'] = ((r.added_bid+r.removed_ask-r.added_ask-r.removed_bid) /
                           (r.added_bid+r.removed_ask+r.added_ask+r.removed_bid).replace(0, np.nan)).to_numpy()
        for depth in [1, 5]:
            weighted = numeric[f'imb{depth}'] * numeric.valid_event_count
            output[f'imb{depth}_60'] = (weighted.rolling('60s', min_periods=5).sum() /
                                       r.valid_event_count.replace(0, np.nan)).to_numpy()
    output['ofi_cross'] = output.ofi60 - output.ofi300
    output['pressure'] = output[['ofi60', 'quote60', 'net60']].mean(axis=1, skipna=False)
    output.loc[stale, :] = np.nan
    return output


def reversal_events(values: np.ndarray, features: pd.DataFrame, threshold: float,
                    extra: np.ndarray | None = None) -> np.ndarray:
    """機能: デッドバンド反対側を異なる２ブロックで確認した時だけ一回発火する。

    引数: values (ndarray)、features (DataFrame)、threshold (float)、extra (ndarray|None): 追加方向値。
    返り値: 初回状態を除いた正負反転イベント列 (ndarray)。
    """
    result = np.zeros(len(features), dtype=np.int8)
    state = candidate = count = 0
    times = features.time_s.to_numpy(float)
    for i, value in enumerate(values):
        if features.block_delay_seconds.iloc[i] > 60 or (i and times[i] - times[i-1] > 60) or not np.isfinite(value):
            state = candidate = count = 0
            continue
        side = 1 if value >= threshold else -1 if value <= -threshold else 0
        if not side or (extra is not None and (not np.isfinite(extra[i]) or side * extra[i] <= 0)):
            candidate = count = 0
            continue
        if side == candidate:
            count += 1
        else:
            candidate, count = side, 1
        if count >= 2 and side != state:
            if state:
                result[i] = side
            state = side
    return result


def board_turns(features: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    """機能: 七つの独立した板転換仮説と複合用圧力転換を作る。

    引数: features (DataFrame)。返り値: 指標と瞬間イベント列 (tuple[DataFrame, dict])。
    """
    values = board_values(features)
    definitions = {'T06': ('ofi60', .10), 'T07': ('ofi_cross', .10), 'T08': ('quote60', .15),
                   'T09': ('imb1_60', .15), 'T10': ('imb5_60', .10), 'T11': ('net60', .12),
                   '_pressure': ('pressure', .10)}
    if features.empty:
        return values, {key: np.zeros(0, dtype=np.int8) for key in definitions}
    return values, {key: reversal_events(values[column].to_numpy(), features, threshold,
                                         values.ofi60.to_numpy() if key == 'T07' else None)
                    for key, (column, threshold) in definitions.items()}


def build_events(session: str, symbol: str, features: pd.DataFrame,
                 peer_features: pd.DataFrame | None = None, cutoff: float | None = None,
                 peer_lag: int = 60) -> tuple[pd.DataFrame, dict]:
    """機能: 自銘柄と遅延付き他銘柄の過去データから15系統の一回限りイベントを作る。

    引数: session/symbol (str)、features/peer_features (DataFrame|None)、cutoff (float|None)、peer_lag (int)。
    返り値: 一意なイベント表と因果関係の監査情報 (tuple[DataFrame, dict])。
    """
    f = features.copy()
    if cutoff is not None:
        f = f.loc[f.time_s <= cutoff].copy()
    f = f.reset_index(drop=True)
    empty = pd.DataFrame(columns=EVENT_COLUMNS)
    if f.empty:
        return empty, dict(イベント数=0, 系統別={}, 他銘柄追加待機秒=peer_lag)
    if np.any(np.diff(f.seq.to_numpy()) <= 0) or np.any(np.diff(f.time_s.to_numpy()) <= 0):
        raise ValueError('特徴行の順序は厳密増加である必要があります')
    if not (f.source_last_seq < f.seq).all():
        raise ValueError('未解放の生板を含んでいます')
    time_s = f.time_s.to_numpy(float)
    z = price_grid(session, symbol, float(time_s[-1]))
    if z.empty:
        return empty, dict(イベント数=0, 系統別={}, 他銘柄追加待機秒=peer_lag)
    minute_time = z.available_time_s.to_numpy(float)
    pos = np.searchsorted(minute_time, time_s, side='right') - 1
    atr = np.where(pos >= 0, z.atr.to_numpy()[np.maximum(pos, 0)], np.nan)
    own_fresh = f.block_delay_seconds.to_numpy(float) <= 60
    can_emit = own_fresh & np.isfinite(atr)
    values, turns = board_turns(f)
    events = {}

    def add(i: int, family: str, side: int, reason: dict, peer_i: int | None = None) -> None:
        """機能: 元行・固定ATR・期限を記録し同一系統同一観測の重複を置換する。

        引数: i (int)、family (str)、side (int)、reason (dict)、peer_i (int|None)。返り値: なし (None)。
        """
        if not can_emit[i]:
            return
        row = f.iloc[i]
        detail = dict(event_id=f'{session}:{symbol}:{family}:{int(row.seq)}', family=family,
                      seq=int(row.seq), time_s=float(row.time_s), side=int(side), atr=float(atr[i]),
                      deadline_time_s=float(row.time_s)+600, source_last_seq=int(row.source_last_seq),
                      reason=reason, peer_seq=-1, peer_source_last_seq=-1, peer_time_s=np.nan, peer_available_time_s=np.nan)
        if peer_i is not None:
            other = peer.iloc[peer_i]
            detail.update(peer_seq=int(other.seq), peer_source_last_seq=int(other.source_last_seq),
                          peer_time_s=float(other.time_s), peer_available_time_s=float(other.time_s)+peer_lag)
        events[(family, i)] = detail

    for event in minute_events(z):
        i = int(np.searchsorted(time_s, event['minute_available_time_s'], side='left'))
        if i < len(f) and time_s[i] - event['minute_available_time_s'] <= 60:
            add(i, event['family'], event['side'], event['reason'])
    for family, sides in turns.items():
        if family.startswith('_'):
            continue
        for i in np.flatnonzero(sides):
            add(int(i), family, int(sides[i]), {key: float(value) for key, value in values.iloc[i].items()})

    # ----------------------------------------
    # 二つの転換が近い時刻に生じた場合だけ複合イベントを作り、材料を再使用しない。
    last_ma = last_board = None
    used_ma = used_board = -1
    for i in range(len(f)):
        if not own_fresh[i] or (i and time_s[i]-time_s[i-1] > 60):
            last_ma = last_board = None
            continue
        if ('T01', i) in events:
            last_ma = (i, events[('T01', i)]['side'])
        if turns['_pressure'][i]:
            last_board = (i, int(turns['_pressure'][i]))
        if last_ma is None or last_board is None:
            continue
        mi, ms = last_ma
        bi, bs = last_board
        if ms == bs and mi != used_ma and bi != used_board and time_s[i]-min(time_s[mi], time_s[bi]) <= 300:
            add(i, 'T12', ms, dict(ma_seq=int(f.seq.iloc[mi]), ma_time_s=float(time_s[mi]),
                                   board_seq=int(f.seq.iloc[bi]), board_time_s=float(time_s[bi]),
                                   pressure=float(values.pressure.iloc[bi])))
            used_ma, used_board = mi, bi

    peer = peer_features.copy().reset_index(drop=True) if peer_features is not None else pd.DataFrame()
    if not peer.empty:
        peer = peer.loc[peer.time_s + peer_lag <= time_s[-1]].reset_index(drop=True)
    pair_valid_count = 0
    if not peer.empty:
        peer_values, peer_turns = board_turns(peer)
        peer_times = peer.time_s.to_numpy(float)
        peer_indices = np.searchsorted(peer_times + peer_lag, time_s, side='right') - 1
        last_own = last_peer = None
        used_own = used_peer = used_leading_peer = -1
        processed_peer = -1
        for i, pi in enumerate(peer_indices):
            if not own_fresh[i] or (i and time_s[i]-time_s[i-1] > 60):
                last_own = last_peer = None
                processed_peer = int(pi)
                continue
            for j in range(processed_peer+1, int(pi)+1):
                if peer.block_delay_seconds.iloc[j] > 60 or (j and peer_times[j]-peer_times[j-1] > 60):
                    last_peer = None
                if peer_turns['_pressure'][j]:
                    last_peer = (j, int(peer_turns['_pressure'][j]))
            processed_peer = int(pi)
            if turns['_pressure'][i]:
                last_own = (i, int(turns['_pressure'][i]))
            if pi < 0 or time_s[i]-peer_times[pi] > 180 or peer.block_delay_seconds.iloc[pi] > 60:
                continue
            pair_valid_count += 1
            if last_peer is None:
                continue
            pj, ps = last_peer
            if time_s[i]-peer_times[pj] > 180 or time_s[i] < peer_times[pj]+peer_lag:
                continue
            detail = dict(peer_turn_seq=int(peer.seq.iloc[pj]), peer_turn_time_s=float(peer_times[pj]),
                          peer_pressure=float(peer_values.pressure.iloc[pj]), peer_lag_seconds=peer_lag)
            if last_own is not None:
                oi, os = last_own
                if os == ps and oi != used_own and pj != used_peer and time_s[i]-time_s[oi] <= 300:
                    add(i, 'T13', os, dict(**detail, own_turn_seq=int(f.seq.iloc[oi]),
                                           own_turn_time_s=float(time_s[oi]), own_pressure=float(values.pressure.iloc[oi])), pj)
                    used_own, used_peer = oi, pj
            for ma_family in ['T01', 'T02']:
                ma = events.get((ma_family, i))
                if ma is not None and ma['side'] == ps and pj != used_leading_peer and ma['reason']['minute_available_time_s'] >= peer_times[pj]+peer_lag:
                    add(i, 'T14', ps, dict(**detail, ma_family=ma_family, ma_reason=ma['reason']), pj)
                    used_leading_peer = pj
                    break
    output = pd.DataFrame(list(events.values()), columns=EVENT_COLUMNS).sort_values(['seq', 'family']).reset_index(drop=True)
    if not output.empty:
        assert output.event_id.is_unique
        assert (output.source_last_seq < output.seq).all()
        assert (output.peer_available_time_s.dropna() <= output.loc[output.peer_available_time_s.notna(), 'time_s']).all()
    audit = dict(イベント数=len(output), 系統別={family: int(output.family.eq(family).sum()) for family in FAMILIES},
                 他銘柄追加待機秒=peer_lag, 他銘柄有効観測数=pair_valid_count,
                 説明='確定１分足は開始から２分後、５分ATRは開始から６分後。イベントは発生後60秒以内の最初の自銘柄解放行に一回だけ写す。',
                 板時刻制約='CurrentPriceTimeは約定時刻であり受信時刻ではない。他銘柄は60秒遅延と180秒鮮度制限による近似。')
    return output, audit


def events_for_csv(events: pd.DataFrame) -> pd.DataFrame:
    """機能: 根拠辞書を日本語JSONへ変換してCSV保存可能にする。

    引数: events (DataFrame)。返り値: 保存用イベント表 (DataFrame)。
    """
    def clean(value):
        """機能: 指標不足の非有限値を空値へ揃える。

        引数: value (object)。返り値: JSON互換値 (object)。
        """
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        return None if isinstance(value, (float, np.floating)) and not np.isfinite(value) else value

    output = events.copy()
    output['reason'] = output.reason.map(lambda value: json.dumps(clean(value), ensure_ascii=False, sort_keys=True, allow_nan=False))
    return output
