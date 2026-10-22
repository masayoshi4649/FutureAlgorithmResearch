"""確定足・解放済み板だけで、転換入口の20個の事前固定仮説を比較する。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
SESSIONS = ['2026-09-21_Day', '2026-09-21_Night', '2026-09-22_Day',
            '2026-09-22_Night', '2026-09-23_Day', '2026-09-23_Night']
SYMBOLS = ['NK225', 'TOPIX']
TICKS = {'NK225': 10., 'TOPIX': .5}
_spec = importlib.util.spec_from_file_location('監査済み転換信号_v9', ROOT/'work'/'wave_v9'/'turning_signals.py')
_old = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_old)
EVENT_COLUMNS = _old.EVENT_COLUMNS
board_values = _old.board_values
reversal_events = _old.reversal_events


def profiles() -> list[dict]:
    """機能: 結果を見る前に固定した20個の信号仮説を返す。

    引数: なし。返り値: ID・名称・群・条件の一覧 (list[dict])。
    """
    definitions = [
        ('S01', 'EMA3/8収束', '移動平均', 'EMA3−EMA8の乖離が拡大後２本連続で縮小。乖離と反対方向。'),
        ('S02', 'EMA5/13収束', '移動平均', 'S01のEMA期間を5と13へ変更。'),
        ('S03', 'EMA3/8交差', '移動平均', 'EMA3がEMA8を上抜けたら買い、下抜けたら売り。'),
        ('S04', 'EMA5/13交差', '移動平均', 'S03のEMA期間を5と13へ変更。'),
        ('S05', 'EMA帯収束後の再拡散', '移動平均', 'EMA3/8/21帯が２本連続縮小し0.6ATR以下。その後10分以内に0.05ATR拡散しEMA3傾きと3/8乖離が同方向。'),
        ('S06', 'OFI反転0.1', '板', '最良気配OFI60秒が反対側の±0.1閾値を２ブロック連続で満たす。'),
        ('S07', '板圧力反転0.1', '板', 'OFI・気配更新・共通価格数量純変化の60秒平均が反対側±0.1を２ブロック確認。'),
        ('S08', '板圧力反転0.2', '板', 'S07の閾値を±0.2へ変更。'),
        ('S09', 'EMA収束と板反転300秒', '価格と板', 'S01とS07が同方向で300秒以内。両材料は一回だけ使う。v9 T12と同一。'),
        ('S10', 'EMA収束と板反転180秒', '価格と板', 'S09の同期窓を180秒へ短縮。'),
        ('S11', 'EMA収束と板反転60秒', '価格と板', 'S09の同期窓を60秒へ短縮。'),
        ('S12', '緩いEMA収束と板反転', '価格と板', 'S02とS07が同方向で300秒以内。'),
        ('S13', 'EMA交差と板反転', '価格と板', 'S03とS07が同方向で180秒以内。'),
        ('S14', 'EMA収束と強い板反転', '価格と板', 'S01とS08が同方向で300秒以内。'),
        ('S15', 'EMA収束と板反転・逆行回避', '価格と板', 'S09発生時、EMA21の直近３分変化がエントリー方向に対して−0.05ATR未満なら除外。'),
        ('S16', 'EMA収束と板反転・他銘柄確認', '２銘柄', 'S09発生時、他銘柄の遅延付き板圧力が同方向に0.1以上。'),
        ('S17', '両銘柄の板反転0.1', '２銘柄', '自銘柄圧力反転は５分以内、他銘柄は60秒待機後かつ元時刻３分以内。同方向。v9 T13と同一。'),
        ('S18', '両銘柄の板反転0.2', '２銘柄', 'S17の両銘柄閾値を±0.2へ変更。'),
        ('S19', 'EMA帯再拡散と板現状', '価格と板', 'S05発生時、自銘柄の板圧力が同方向に0.1以上。新しい板反転は要求しない。'),
        ('S20', 'EMA収束と板現状', '価格と板', 'S01発生時、自銘柄の板圧力が同方向に0.1以上。新しい板反転は要求しない。'),
    ]
    return [dict(id=i, family=i, name=n, group=g, description=d) for i, n, g, d in definitions]


def candle_root(session: str) -> Path:
    """機能: 完了分と既知部分夜間を区別して足原本の置き場を返す。

    引数: session (str)。返り値: 足保存ルート (Path)。
    """
    return ROOT/'work'/'wave_v9'/'live'/'work'/'wave_v7'/'live' if session == SESSIONS[-1] else ROOT


def feature_root(session: str) -> Path:
    """機能: 既存監査済みの特徴・全有効気配の置き場を返す。

    引数: session (str)。返り値: 特徴保存ルート (Path)。
    """
    return ROOT/'work'/'wave_v9'/'live'/'features' if session == SESSIONS[-1] else ROOT/'work'/'wave_v8'/'features'


def atr_at(session: str, symbol: str, times: np.ndarray, cutoff: float | None = None) -> np.ndarray:
    """機能: 確定５分足の終了から１分待機したATRを過去方向で対応する。

    引数: session/symbol (str)、times (ndarray)、cutoff (float|None)。
    返り値: 各時刻で既知のATR配列 (ndarray)。
    """
    five = pd.read_csv(candle_root(session)/'candle_5min'/symbol/f'{session}.csv')
    five = five.loc[five.closed.astype(str).str.lower().eq('true')].copy()
    five['time'] = pd.to_datetime(five.time)
    five = five.sort_values('time')
    available = five.time.array.as_unit('ns').asi8 / 1e9 + 360
    if cutoff is not None:
        five, available = five.loc[available <= cutoff], available[available <= cutoff]
    result = np.full(len(times), np.nan)
    if five.empty:
        return result
    tr = pd.concat([five.high-five.low, (five.high-five.close.shift()).abs(),
                    (five.low-five.close.shift()).abs()], axis=1).max(axis=1)
    values = tr.ewm(alpha=1/12, adjust=False, min_periods=3).mean().clip(lower=2*TICKS[symbol]).to_numpy()
    positions = np.searchsorted(available, times, side='right') - 1
    valid = positions >= 0
    result[valid] = values[positions[valid]]
    return result


def price_grid(session: str, symbol: str, last_time: float) -> pd.DataFrame:
    """機能: v9の確定足解放規則を保ち、比較用EMA5を追加する。

    引数: session/symbol (str)、last_time (float)。返り値: 因果的な１分格子 (DataFrame)。
    """
    old_root = _old.ROOT
    try:
        _old.ROOT = ROOT/'work'/'wave_v9'/'live' if session == SESSIONS[-1] else ROOT
        z = _old.price_grid(session, symbol, last_time)
    finally:
        _old.ROOT = old_root
    if not z.empty:
        z['ema5'] = z.close.ewm(span=5, adjust=False, min_periods=5).mean()
        z['gap513'] = z.ema5-z.ema13
        z['trend_change_atr'] = z.ema21.diff(3)/z.atr
    return z


def load_price_frame(session: str, symbol: str, cutoff: float | None = None) -> pd.DataFrame:
    """機能: 判定と同じEMAを利用可能時刻の索引で図解用に返す。

    引数: session/symbol (str)、cutoff (float|None)。返り値: 指標表 (DataFrame)。
    """
    if cutoff is None:
        f = pd.read_csv(feature_root(session)/f'{symbol}_{session}.csv', usecols=['time_s'])
        if f.empty:
            return pd.DataFrame()
        cutoff = float(f.time_s.iloc[-1])
    z = price_grid(session, symbol, cutoff)
    if not z.empty:
        z['source_bar_time'] = z.index
        z.index = pd.to_datetime(z.available_time_s, unit='s', utc=True).dt.tz_convert('Asia/Tokyo')
        z.index.name = 'available_time'
    return z


def slow_minute_events(z: pd.DataFrame) -> list[dict]:
    """機能: EMA5/13の収束開始と交差を、確定した過去４本から一回検知する。

    引数: z (DataFrame)。返り値: 分足利用可能時刻付きイベント (list[dict])。
    """
    if z.empty:
        return []
    records, result = z.to_dict('records'), []
    for i in range(3, len(records)):
        row, p1, p2, p3 = records[i], records[i-1], records[i-2], records[i-3]
        if any(r['stale_minutes'] > 1 for r in [row, p1, p2, p3]) or not np.isfinite(row['atr']):
            continue
        gaps = [r['gap513'] for r in [row, p1, p2, p3]]
        if not all(np.isfinite(v) for v in gaps):
            continue
        gap, g1, g2, g3 = gaps
        side = int(np.sign(gap))
        families = []
        if side and np.sign(g1) == side and np.sign(g2) == side and abs(gap) < abs(g1) < abs(g2) and abs(g2) >= abs(g3) and abs(g2) >= .1*row['atr']:
            families.append(('S02', -side))
        if gap > 0 >= g1:
            families.append(('S04', 1))
        elif gap < 0 <= g1:
            families.append(('S04', -1))
        for family, direction in families:
            result.append(dict(family=family, side=direction,
                               minute_available_time_s=float(row['available_time_s']),
                               reason=dict(gap=float(gap), gap_previous=float(g1), gap_two_minutes_ago=float(g2),
                                           ema5=float(row['ema5']), ema13=float(row['ema13']),
                                           minute_available_time_s=float(row['available_time_s']))))
    return result


def build_events(session: str, symbol: str, features: pd.DataFrame,
                 peer_features: pd.DataFrame | None = None, cutoff: float | None = None,
                 peer_lag: int = 60) -> tuple[pd.DataFrame, dict]:
    """機能: 20仮説の入口を原本の解放順で一回ずつ検知する。

    引数: session/symbol (str)、features/peer_features (DataFrame|None)、cutoff (float|None)、peer_lag (int)。
    返り値: v9互換イベント表と監査情報 (tuple[DataFrame, dict])。
    """
    if peer_lag < 60:
        raise ValueError('他銘柄は最低60秒の追加待機を必要とします')
    f = features.loc[features.time_s <= cutoff].copy() if cutoff is not None else features.copy()
    f = f.reset_index(drop=True)
    if f.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS), dict(イベント数=0, 系統別={}, 他銘柄追加待機秒=peer_lag)
    if np.any(np.diff(f.seq) <= 0) or np.any(np.diff(f.time_s) <= 0) or not (f.source_last_seq < f.seq).all():
        raise ValueError('原本解放順・時刻順の厳密増加が必要です')
    times, seqs = f.time_s.to_numpy(float), f.seq.to_numpy(int)
    fresh = f.block_delay_seconds.to_numpy(float) <= 60
    z = price_grid(session, symbol, float(times[-1]))
    if z.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS), dict(イベント数=0, 系統別={}, 他銘柄追加待機秒=peer_lag)
    pos = np.searchsorted(z.available_time_s.to_numpy(float), times, side='right')-1
    atr = np.where(pos >= 0, z.atr.to_numpy()[np.maximum(pos, 0)], np.nan)
    valid = fresh & np.isfinite(atr)
    values = board_values(f)
    pressure = values.pressure.to_numpy(float)
    turns = {str(threshold): reversal_events(pressure, f, threshold) for threshold in [.1, .2]}
    ofi = reversal_events(values.ofi60.to_numpy(float), f, .1)
    events = {}
    peer = peer_features.copy().reset_index(drop=True) if peer_features is not None else pd.DataFrame()
    if not peer.empty:
        peer = peer.loc[peer.time_s+peer_lag <= times[-1]].reset_index(drop=True)
        if np.any(np.diff(peer.seq) <= 0) or np.any(np.diff(peer.time_s) <= 0) or not (peer.source_last_seq < peer.seq).all():
            raise ValueError('他銘柄の未解放または逆順の特徴は使用できません')

    def add(i: int, family: str, side: int, reason: dict, peer_i: int | None = None) -> None:
        """機能: 既知のATRと根拠を伴う一意なイベントを保存する。

        引数: i (int)、family (str)、side (int)、reason (dict)、peer_i (int|None)。返り値: なし (None)。
        """
        if not valid[i]:
            return
        detail = dict(event_id=f'{session}:{symbol}:{family}:{seqs[i]}', family=family, seq=int(seqs[i]),
                      time_s=float(times[i]), side=int(side), atr=float(atr[i]), deadline_time_s=float(times[i])+600,
                      source_last_seq=int(f.source_last_seq.iloc[i]), reason=reason,
                      peer_seq=-1, peer_source_last_seq=-1, peer_time_s=np.nan, peer_available_time_s=np.nan)
        if peer_i is not None:
            other = peer.iloc[peer_i]
            detail.update(peer_seq=int(other.seq), peer_source_last_seq=int(other.source_last_seq),
                          peer_time_s=float(other.time_s), peer_available_time_s=float(other.time_s)+peer_lag)
        events[(family, i)] = detail

    minute_map = {'T01': 'S01', 'T02': 'S03', 'T03': 'S05'}
    minute = [dict(event, family=minute_map[event['family']]) for event in _old.minute_events(z) if event['family'] in minute_map]
    minute += slow_minute_events(z)
    for event in minute:
        i = int(np.searchsorted(times, event['minute_available_time_s'], side='left'))
        if i < len(f) and times[i]-event['minute_available_time_s'] <= 60:
            add(i, event['family'], event['side'], event['reason'])
    for family, sides in [('S06', ofi), ('S07', turns['0.1']), ('S08', turns['0.2'])]:
        for i in np.flatnonzero(sides):
            add(int(i), family, int(sides[i]), {key: float(value) for key, value in values.iloc[i].items()})

    # ----------------------------------------
    # 材料が先後どちらに生じても同期窓内で一回だけ使い、その組合せを再使用しない。
    combinations = [('S09', 'S01', '0.1', 300), ('S10', 'S01', '0.1', 180),
                    ('S11', 'S01', '0.1', 60), ('S12', 'S02', '0.1', 300),
                    ('S13', 'S03', '0.1', 180), ('S14', 'S01', '0.2', 300)]
    for family, ma_family, threshold, window in combinations:
        last_ma = last_board = None
        used_ma = used_board = -1
        sides = turns[threshold]
        for i in range(len(f)):
            if not fresh[i] or (i and times[i]-times[i-1] > 60):
                last_ma = last_board = None
                continue
            ma = events.get((ma_family, i))
            if ma is not None:
                last_ma = (i, ma['side'])
            if sides[i]:
                last_board = (i, int(sides[i]))
            if last_ma is None or last_board is None:
                continue
            mi, ms = last_ma
            bi, bs = last_board
            if ms == bs and mi != used_ma and bi != used_board and times[i]-min(times[mi], times[bi]) <= window:
                add(i, family, ms, dict(ma_seq=int(seqs[mi]), ma_time_s=float(times[mi]),
                                       board_seq=int(seqs[bi]), board_time_s=float(times[bi]), pressure=float(pressure[bi])))
                used_ma, used_board = mi, bi

    for i in range(len(f)):
        base = events.get(('S09', i))
        if base is not None and pos[i] >= 0:
            row = z.iloc[pos[i]]
            change = float(row['trend_change_atr'])
            if row['stale_minutes'] <= 1 and np.isfinite(change) and base['side']*change >= -.05:
                add(i, 'S15', base['side'], dict(**base['reason'], ema21_change_3min_atr=change))
        for family, source in [('S19', 'S05'), ('S20', 'S01')]:
            base = events.get((source, i))
            if base is not None and np.isfinite(pressure[i]) and base['side']*pressure[i] >= .1:
                add(i, family, base['side'], dict(source_family=source, source_reason=base['reason'], pressure=float(pressure[i])))

    # ----------------------------------------
    # 共通の受信順が無いため、他銘柄には60秒以上の待機と180秒の鮮度制限を設ける。
    peer_valid_count = 0
    if not peer.empty:
        pv = board_values(peer)
        ptimes = peer.time_s.to_numpy(float)
        pindices = np.searchsorted(ptimes+peer_lag, times, side='right')-1
        for i, pi in enumerate(pindices):
            if pi < 0 or not fresh[i] or times[i]-ptimes[pi] > 180 or peer.block_delay_seconds.iloc[pi] > 60:
                continue
            peer_valid_count += 1
            base = events.get(('S09', i))
            pressure_peer = float(pv.pressure.iloc[pi])
            if base is not None and np.isfinite(pressure_peer) and base['side']*pressure_peer >= .1:
                add(i, 'S16', base['side'], dict(**base['reason'], peer_pressure=pressure_peer,
                                               peer_lag_seconds=peer_lag), int(pi))
        for family, threshold in [('S17', .1), ('S18', .2)]:
            peer_turn = reversal_events(pv.pressure.to_numpy(float), peer, threshold)
            own_turn = turns[str(threshold)]
            last_own = last_peer = None
            used_own = used_peer = processed_peer = -1
            for i, pi in enumerate(pindices):
                if not fresh[i] or (i and times[i]-times[i-1] > 60):
                    last_own = last_peer = None
                    processed_peer = int(pi)
                    continue
                for j in range(processed_peer+1, int(pi)+1):
                    if peer.block_delay_seconds.iloc[j] > 60 or (j and ptimes[j]-ptimes[j-1] > 60):
                        last_peer = None
                    if peer_turn[j]:
                        last_peer = (j, int(peer_turn[j]))
                processed_peer = int(pi)
                if own_turn[i]:
                    last_own = (i, int(own_turn[i]))
                if pi < 0 or times[i]-ptimes[pi] > 180 or peer.block_delay_seconds.iloc[pi] > 60 or last_peer is None:
                    continue
                pj, ps = last_peer
                if times[i]-ptimes[pj] > 180 or times[i] < ptimes[pj]+peer_lag or last_own is None:
                    continue
                oi, os = last_own
                if os == ps and oi != used_own and pj != used_peer and times[i]-times[oi] <= 300:
                    add(i, family, os, dict(peer_turn_seq=int(peer.seq.iloc[pj]), peer_turn_time_s=float(ptimes[pj]),
                                           peer_pressure=float(pv.pressure.iloc[pj]), peer_lag_seconds=peer_lag,
                                           own_turn_seq=int(seqs[oi]), own_turn_time_s=float(times[oi]),
                                           own_pressure=float(pressure[oi])), pj)
                    used_own, used_peer = oi, pj
    output = pd.DataFrame(list(events.values()), columns=EVENT_COLUMNS).sort_values(['seq', 'family']).reset_index(drop=True)
    if not output.empty:
        assert output.event_id.is_unique and (output.source_last_seq < output.seq).all()
        pvalid = output.peer_available_time_s.notna()
        assert (output.loc[pvalid, 'peer_available_time_s'] <= output.loc[pvalid, 'time_s']).all()
    audit = dict(イベント数=len(output), 系統別={p['id']: int(output.family.eq(p['id']).sum()) for p in profiles()},
                 他銘柄追加待機秒=peer_lag, 他銘柄有効観測数=peer_valid_count,
                 時刻制約='受信時刻なし。CurrentPriceTime連続同時刻ブロックは次時刻まで封印。peerは60秒待機と180秒鮮度。',
                 確定足待機='１分足は開始から２分、５分ATRは開始から６分で利用可能。')
    return output, audit


def state_at(tape: dict, features: pd.DataFrame, z: pd.DataFrame) -> dict:
    """機能: 出口と時間帯確認に使う板・EMA状態を全有効気配へ因果対応する。

    引数: tape (dict)、features/z (DataFrame)。返り値: 全気配長の状態配列 (dict)。
    """
    n = len(tape['seq'])
    pressure = np.full(n, np.nan)
    board_side = np.zeros(n, dtype=np.int8)
    trend_side = np.zeros(n, dtype=np.int8)
    trend_gap_atr = np.full(n, np.nan)
    positions = np.searchsorted(features.seq.to_numpy(int), tape['seq'], side='right')-1
    valid = positions >= 0
    indices = np.maximum(positions, 0)
    if len(features):
        values = board_values(features).pressure.to_numpy(float)
        valid &= features.block_delay_seconds.to_numpy(float)[indices] <= 60
        valid &= tape['time_s']-features.time_s.to_numpy(float)[indices] <= 60
        pressure[valid] = values[indices[valid]]
        board_side[pressure >= .1] = 1
        board_side[pressure <= -.1] = -1
    if not z.empty:
        zp = np.searchsorted(z.available_time_s.to_numpy(float), tape['time_s'], side='right')-1
        zi = np.maximum(zp, 0)
        ok = (zp >= 0) & (z.stale_minutes.to_numpy(float)[zi] <= 1)
        gap = z.gap38.to_numpy(float)[zi]
        ok &= np.isfinite(gap)
        trend_side[ok] = np.sign(gap[ok]).astype(np.int8)
        trend_gap_atr[ok] = gap[ok]/z.atr.to_numpy(float)[zi[ok]]
    return dict(board_side=board_side, board_pressure=pressure, trend_side=trend_side, trend_gap_atr=trend_gap_atr)


def load_inputs() -> dict:
    """機能: 保存原本だけから全12銘柄セッションの20入口と全気配状態を作る。

    引数: なし。返り値: (セッション,銘柄)をキーとする入力辞書 (dict)。
    """
    output = {}
    for session in SESSIONS:
        folder = feature_root(session)
        frames = {symbol: pd.read_csv(folder/f'{symbol}_{session}.csv') for symbol in SYMBOLS}
        for symbol in SYMBOLS:
            f, peer = frames[symbol], frames[SYMBOLS[1-SYMBOLS.index(symbol)]]
            events, audit = build_events(session, symbol, f, peer)
            tape = dict(np.load(folder/f'約定系列_{symbol}_{session}.npz', allow_pickle=False))
            tape['atr'] = atr_at(session, symbol, tape['time_s'])
            z = price_grid(session, symbol, float(tape['time_s'][-1]))
            price_frame = load_price_frame(session, symbol, float(tape['time_s'][-1]))
            output[(session, symbol)] = dict(features=f, peer_features=peer, tape=tape, events=events,
                                            state=state_at(tape, f, z), price_frame=price_frame, event_audit=audit)
    return output


def main() -> None:
    """機能: 事前固定の20信号定義を書き出す。損益探索は別の処理で行う。

    引数: なし。返り値: なし (None)。
    """
    (OUT/'信号条件一覧.json').write_text(json.dumps(profiles(), ensure_ascii=False, indent=2), encoding='utf-8')
    frozen = dict(固定時刻=str(pd.Timestamp.now(tz='Asia/Tokyo')), 今回API取得回数=0, 条件数=20,
                  signals_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  v9依存_SHA256=hashlib.sha256((ROOT/'work'/'wave_v9'/'turning_signals.py').read_bytes()).hexdigest())
    (OUT/'信号事前固定.json').write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding='utf-8')
    print('転換入口20条件を保存しました。損益は未計算です。')


if __name__ == '__main__':
    main()
