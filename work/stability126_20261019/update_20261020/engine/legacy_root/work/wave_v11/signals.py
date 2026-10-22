"""一次研究を参考に、平均回帰・継続・板・２銘柄の24仮説を因果的に生成する。"""

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
CANDLE_OVERRIDES: dict[str, Path] = {}
FEATURE_OVERRIDES: dict[str, Path] = {}
_spec = importlib.util.spec_from_file_location('研究比較_v10信号', ROOT/'work'/'wave_v10'/'signals.py')
_legacy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_legacy)
EVENT_COLUMNS = _legacy.EVENT_COLUMNS
board_values = _legacy.board_values
SOURCES = {
    '平均回帰': 'https://arxiv.org/abs/1411.5062',
    'チャート': 'https://www.nber.org/papers/w7613',
    '出来高反転': 'https://web.mit.edu/wangj/www/pap/CampbellGrossmanWang93.pdf',
    '出来高継続': 'https://www.nber.org/papers/w8312',
    '継続': 'https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum',
    'OFI': 'https://arxiv.org/abs/1011.6402',
    '板数量': 'https://arxiv.org/abs/1512.03492',
    '多段板': 'https://arxiv.org/abs/1907.06230',
    '先行遅行': 'https://arxiv.org/abs/1111.7103',
}


def profiles() -> list[dict]:
    """機能: 閾値変更を別思想に数えない24系統の定義と一次資料を返す。

    引数: なし。返り値: 条件・思想・出典を持つ一覧 (list[dict])。
    """
    rows = [
        ('P01', '価格偏差からの反発', '平均回帰', '終値の20分平均からの偏差が±1.5標準偏差以上、直近１分変化が平均へ戻る方向。', '平均回帰'),
        ('P02', '出来高加重平均への回帰', '平均回帰', '既知の典型価格×出来高によるセッション近似VWAPから1ATR以上離れ、直近３分が平均へ戻る方向。', '平均回帰'),
        ('P03', '局所OU回帰', '平均回帰', '過去60分で終値AR(1)を推定。係数0〜1、半減期２〜30分、推定均衡まで0.5ATR以上、終値偏差1標準偏差以上なら均衡方向。', '平均回帰'),
        ('P04', '過熱解消の反転', '平均回帰', '確定１分足RSI7が20を上抜けて買い、80を下抜けて売り。', 'チャート'),
        ('P05', '直近レンジ突破の失敗', '平均回帰', '過去20分の高安を当該足が一旦突破し、終値が旧境界の内側へ0.1ATR以上戻り、実体も反対方向。', 'チャート'),
        ('P06', '大出来高と長い反対ヒゲ', '平均回帰', '出来高が直前20分平均の２倍以上、前終値から0.5ATR以上動き、終値が値幅の反対側３分の１なら反転方向。', '出来高反転'),
        ('P07', '20分レンジ突破の継続', '順張りと出来高', '終値が直前20分の最高値を0.05ATR上回れば買い、最安値を0.05ATR下回れば売り。', 'チャート'),
        ('P08', 'トレンド中の押し戻り完了', '順張りと出来高', 'EMA21の３分傾きが0.1ATR以上。終値がEMA8をトレンド方向に抜き直す。', '継続'),
        ('P09', '累積方向変化CUSUM', '順張りと出来高', '１分値動き/ATRに片側0.025の控除をし累積0.6375超で方向変更。初回方向と反転だけ検知。', 'チャート'),
        ('P10', '価格帯圧縮後の放出', '順張りと出来高', '直前10分高安幅が1.2ATR未満で、終値がその高安を0.05ATR突破した方向。', 'チャート'),
        ('P11', '出来高付きレンジ突破', '順張りと出来高', 'P07のレンジ突破時に出来高が直前20分平均の1.5倍以上。', '出来高継続'),
        ('P12', '出来高を伴う持続方向', '順張りと出来高', '５分の終値変化が0.5ATR以上、出来高加重の符号付き５分値動き/絶対値動きが同方向0.6以上。', '出来高継続'),
        ('P13', 'OFIの持続', '板', '解放済み60秒OFI/絶対OFIが±0.2以上かつ300秒OFIが同方向0.05以上。異なる２ブロックで確認。', 'OFI'),
        ('P14', '最良数量偏り', '板', '60秒イベント加重平均の最良数量偏りが±0.25以上。異なる２ブロックで確認。', '板数量'),
        ('P15', '深い板と最良板の合意', '板', '５段数量偏り60秒が±0.15以上、最良数量偏りも同方向0.05以上。２ブロック確認。', '多段板'),
        ('P16', '約定方向推定と気配更新', '板', 'tick-rule出来高偏り60秒が±0.3以上、既知出来高５以上、気配更新偏りも同方向。２ブロック確認。', '出来高継続'),
        ('P17', 'OFIの加速', '板', '60秒OFI−300秒OFIが±0.2以上かつ60秒OFIが同方向0.1以上。２ブロック確認。', 'OFI'),
        ('P18', 'フロー吸収後の反転', '板', '60秒OFIが±0.2以上なのに60秒の中値変化がその方向へ0.1ATR以下で、直近15秒中値が逆行したらOFIと逆方向。２ブロック確認。', 'OFI'),
        ('P19', '他銘柄の価格先行', '２銘柄', '他銘柄の遅延付き５分変化が0.75ATR以上、自銘柄の同方向変化が0.25ATR未満なら追随方向。', '先行遅行'),
        ('P20', '他銘柄OFIと自銘柄トレンド', '２銘柄', '他銘柄60秒OFIが±0.2以上、自銘柄EMA3−EMA8が同方向0.1ATR以上。２ブロック確認。', '先行遅行'),
        ('P21', '相対値動きの戻り', '２銘柄', 'ATR標準化５分値動きの自−他差が±1以上で、直近１分の自銘柄が差を埋める向きに変化した方向。', '平均回帰'),
        ('P22', '両銘柄板圧力の合意', '２銘柄', '自・他のOFI/気配更新/同一価格数量変化の平均が同方向0.1以上。２ブロック確認。', '先行遅行'),
        ('P23', '旧EMA収束と板反転', '旧方式比較', '既存S09と同じ。EMA3/8収束と板圧力反転が同方向で300秒以内。', 'チャート'),
        ('P24', '旧両銘柄板反転', '旧方式比較', '既存S17と同じ。両銘柄の板圧力反転が同方向、自銘柄５分以内、他銘柄は60秒待機かつ３分以内。', '先行遅行'),
    ]
    result = []
    for key, label, group, rules, source in rows:
        note = 'P01〜P22は論文の着想を保存データへ置換した機械的仮説であり、論文の再現・保証ではない。'
        result.append(dict(id=key, family=key, name=label, label=label, group=group, description=rules,
                           rules=rules, source=SOURCES[source], source_name=source, research_note=note))
    return result


def candle_root(session: str) -> Path:
    """機能: 完了原本・既知夜間・今回取得分の足保存場所を区別する。

    引数: session (str)。返り値: candle_1min/candle_5minの親 (Path)。
    """
    if session in CANDLE_OVERRIDES:
        return Path(CANDLE_OVERRIDES[session])
    if session == SESSIONS[-1]:
        return ROOT/'work'/'wave_v10'/'live'/'work'/'wave_v9'/'live'/'work'/'wave_v7'/'live'
    return ROOT


def feature_root(session: str) -> Path:
    """機能: 解放済み板特徴と全有効気配の保存場所を返す。

    引数: session (str)。返り値: 保存先 (Path)。
    """
    if session in FEATURE_OVERRIDES:
        return Path(FEATURE_OVERRIDES[session])
    return ROOT/'work'/'wave_v10'/'live'/'features' if session == SESSIONS[-1] else ROOT/'work'/'wave_v8'/'features'


def read_bars(session: str, symbol: str, interval: int, cutoff: float) -> pd.DataFrame:
    """機能: 確定・追加１分待機済みの足だけを読み、時刻順を検査する。

    引数: session/symbol (str)、interval (int)、cutoff (float)。返り値: 元足開始時刻索引の表 (DataFrame)。
    """
    f = pd.read_csv(candle_root(session)/f'candle_{interval}min'/symbol/f'{session}.csv')
    f['time'] = pd.to_datetime(f.time)
    f = f.loc[f.closed.astype(str).str.lower().eq('true')].set_index('time').sort_index()
    if f.index.duplicated().any():
        raise ValueError('足時刻に重複があります')
    available = f.index.as_unit('ns').asi8 / 1e9 + (interval+1)*60
    return f.loc[available <= cutoff].copy()


def atr_at(session: str, symbol: str, times: np.ndarray, cutoff: float | None = None) -> np.ndarray:
    """機能: 確定５分足終了から１分待ったATRを各時点へ対応する。

    引数: session/symbol (str)、times (ndarray)、cutoff (float|None)。返り値: ATR配列 (ndarray)。
    """
    output = np.full(len(times), np.nan)
    if not len(times):
        return output
    f = read_bars(session, symbol, 5, float(times[-1]) if cutoff is None else cutoff)
    if f.empty:
        return output
    tr = pd.concat([f.high-f.low, (f.high-f.close.shift()).abs(), (f.low-f.close.shift()).abs()], axis=1).max(axis=1)
    values = tr.ewm(alpha=1/12, adjust=False, min_periods=3).mean().clip(lower=2*TICKS[symbol]).to_numpy()
    positions = np.searchsorted(f.index.as_unit('ns').asi8/1e9+360, times, side='right')-1
    ok = positions >= 0
    output[ok] = values[positions[ok]]
    return output


def price_grid(session: str, symbol: str, last_time: float) -> pd.DataFrame:
    """機能: 過去方向の価格・出来高・局所AR(1)特徴を１分格子で作る。

    引数: session/symbol (str)、last_time (float)。返り値: 利用可能時刻を付けた特徴表 (DataFrame)。
    """
    one = read_bars(session, symbol, 1, last_time)
    start = _legacy._old.session_start(session)
    end = pd.Timestamp(last_time-120, unit='s', tz='Asia/Tokyo').floor('min')
    if one.empty or end < start:
        return pd.DataFrame()
    grid = pd.date_range(start, end, freq='min')
    z = one.reindex(grid)
    observed = z.close.notna()
    seen = pd.Series(np.nan, index=grid)
    seen.loc[observed] = grid[observed].as_unit('ns').asi8/1e9
    z['stale_minutes'] = (grid.as_unit('ns').asi8/1e9-seen.ffill())/60
    z['close'] = z.close.ffill()
    z['available_time_s'] = grid.as_unit('ns').asi8/1e9+120
    z['age'] = np.arange(len(z))
    z['atr'] = atr_at(session, symbol, z.available_time_s.to_numpy(float))
    for span in [3, 5, 8, 13, 21]:
        z[f'ema{span}'] = z.close.ewm(span=span, adjust=False, min_periods=span).mean()
    z['gap38'], z['gap513'], z['gap321'] = z.ema3-z.ema8, z.ema5-z.ema13, z.ema3-z.ema21
    z['band'] = z[['ema3', 'ema8', 'ema21']].max(axis=1)-z[['ema3', 'ema8', 'ema21']].min(axis=1)
    z.loc[z.ema21.isna(), 'band'] = np.nan
    z['macd'] = z.ema3-z.ema13
    z['hist'] = z.macd-z.macd.ewm(span=5, adjust=False, min_periods=5).mean()
    z['trend_change_atr'] = z.ema21.diff(3)/z.atr
    z['delta1'], z['delta3'], z['delta5'] = z.close.diff(), z.close.diff(3), z.close.diff(5)
    z['return5_atr'] = z.delta5/z.atr
    mean20, std20 = z.close.rolling(20, min_periods=20).mean(), z.close.rolling(20, min_periods=20).std(ddof=0)
    z['z20'] = (z.close-mean20)/std20.clip(lower=TICKS[symbol])
    for window in [10, 20]:
        z[f'high{window}_prev'] = z.high.shift().rolling(window, min_periods=window).max()
        z[f'low{window}_prev'] = z.low.shift().rolling(window, min_periods=window).min()
    gain = z.delta1.clip(lower=0).ewm(alpha=1/7, adjust=False, min_periods=7).mean()
    loss = (-z.delta1.clip(upper=0)).ewm(alpha=1/7, adjust=False, min_periods=7).mean()
    z['rsi7'] = 100*gain/(gain+loss).replace(0, np.nan)

    # ----------------------------------------
    # 未観測分の出来高を０として補完せず、完全フラグのある足だけを材料にする。
    complete = z.volume_complete.astype(str).str.lower().eq('true') & observed & (z.volume >= 0)
    volume = z.volume.where(complete)
    typical = (z.high+z.low+z.close)/3
    z['volume_valid'] = complete
    z['vwap'] = (typical*volume).cumsum()/volume.cumsum().replace(0, np.nan)
    z['vwap_complete'] = ((~observed) | complete).cummin()
    z['volume_ratio'] = volume/volume.shift().rolling(20, min_periods=20).mean().replace(0, np.nan)
    weighted = z.delta1*volume
    z['volume_direction5'] = weighted.rolling(5, min_periods=5).sum()/weighted.abs().rolling(5, min_periods=5).sum().replace(0, np.nan)

    # ----------------------------------------
    # 60組の既知の隣接終値だけで局所AR(1)を推定し、次時点への回帰仮説に使う。
    x, y = z.close.shift(), z.close
    mx, my = x.rolling(60, min_periods=60).mean(), y.rolling(60, min_periods=60).mean()
    covariance = (x*y).rolling(60, min_periods=60).mean()-mx*my
    variance = (x*x).rolling(60, min_periods=60).mean()-mx*mx
    beta = covariance/variance.where(variance > TICKS[symbol]**2)
    beta = beta.where((beta > 0) & (beta < 1))
    z['ou_beta'] = beta
    z['ou_mean'] = (my-beta*mx)/(1-beta)
    z['ou_half_life'] = -np.log(2)/np.log(beta)
    z['ou_fresh'] = z.stale_minutes.le(1).rolling(61, min_periods=61).min().eq(1)
    return z


def load_price_frame(session: str, symbol: str, cutoff: float | None = None) -> pd.DataFrame:
    """機能: 図表用の価格特徴を利用可能時刻の索引で返す。

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


def signed_condition(positive: pd.Series | np.ndarray, negative: pd.Series | np.ndarray) -> np.ndarray:
    """機能: 対称な買い・売り条件を符号へ変換し、両成立は見送る。

    引数: positive/negative (Series|ndarray)。返り値: -1/0/1の配列 (ndarray)。
    """
    buy, sell = np.asarray(positive, dtype=bool), np.asarray(negative, dtype=bool)
    return np.where(buy & ~sell, 1, np.where(sell & ~buy, -1, 0)).astype(np.int8)


def sampled_events(sides: np.ndarray, times: np.ndarray, fresh: np.ndarray, confirm: int = 1) -> np.ndarray:
    """機能: 条件成立を確認し、同方向の再通知を５分空けて記録する。

    引数: sides/times/fresh (ndarray)、confirm (int)。返り値: 一回通知の方向列 (ndarray)。
    """
    result = np.zeros(len(sides), dtype=np.int8)
    candidate = count = last_side = 0
    last_time = -np.inf
    for i, side in enumerate(sides):
        if not fresh[i] or (i and times[i]-times[i-1] > 120):
            candidate = count = 0
            continue
        if not side:
            candidate = count = 0
            continue
        count = count+1 if side == candidate else 1
        candidate = int(side)
        if count >= confirm and (side != last_side or times[i]-last_time >= 300):
            result[i] = side
            last_side, last_time = int(side), float(times[i])
    return result


def minute_conditions(z: pd.DataFrame) -> dict[str, np.ndarray]:
    """機能: 平均回帰６・継続６の条件を、確定済み指標だけで判定する。

    引数: z (DataFrame)。返り値: 系統ごとの方向条件 (dict[str, ndarray])。
    """
    c, a = z.close, z.atr
    result = {}
    result['P01'] = signed_condition((z.z20 <= -1.5) & (z.delta1 > 0), (z.z20 >= 1.5) & (z.delta1 < 0))
    result['P02'] = signed_condition((c-z.vwap <= -a) & (z.delta3 > 0) & z.vwap_complete,
                                     (c-z.vwap >= a) & (z.delta3 < 0) & z.vwap_complete)
    ou = z.ou_half_life.between(2, 30) & z.ou_fresh & (z.z20.abs() >= 1)
    result['P03'] = signed_condition(ou & (z.ou_mean-c >= .5*a), ou & (z.ou_mean-c <= -.5*a))
    result['P04'] = signed_condition((z.rsi7 > 20) & (z.rsi7.shift() <= 20), (z.rsi7 < 80) & (z.rsi7.shift() >= 80))
    result['P05'] = signed_condition((z.low < z.low20_prev) & (c >= z.low20_prev+.1*a) & (c > z.open),
                                     (z.high > z.high20_prev) & (c <= z.high20_prev-.1*a) & (c < z.open))
    body_position = (c-z.low)/(z.high-z.low).replace(0, np.nan)
    result['P06'] = signed_condition((z.volume_ratio >= 2) & (z.delta1 <= -.5*a) & (body_position >= 2/3),
                                     (z.volume_ratio >= 2) & (z.delta1 >= .5*a) & (body_position <= 1/3))
    result['P07'] = signed_condition(c >= z.high20_prev+.05*a, c <= z.low20_prev-.05*a)
    result['P08'] = signed_condition((z.trend_change_atr >= .1) & (c > z.ema8) & (c.shift() <= z.ema8.shift()),
                                     (z.trend_change_atr <= -.1) & (c < z.ema8) & (c.shift() >= z.ema8.shift()))
    result['P09'] = np.zeros(len(z), dtype=np.int8)
    available = {float(value): i for i, value in enumerate(z.available_time_s)}
    for event in _legacy._old.minute_events(z):
        if event['family'] == 'T00':
            result['P09'][available[event['minute_available_time_s']]] = event['side']
    squeeze = (z.high10_prev-z.low10_prev < 1.2*a)
    result['P10'] = signed_condition(squeeze & (c >= z.high10_prev+.05*a), squeeze & (c <= z.low10_prev-.05*a))
    result['P11'] = np.where(z.volume_ratio >= 1.5, result['P07'], 0).astype(np.int8)
    result['P12'] = signed_condition((z.delta5 >= .5*a) & (z.volume_direction5 >= .6),
                                     (z.delta5 <= -.5*a) & (z.volume_direction5 <= -.6))
    return result


def board_extended(f: pd.DataFrame, atr: np.ndarray) -> pd.DataFrame:
    """機能: 板状態にtick-rule出来高と過去中値変化を追加する。

    引数: f (DataFrame)、atr (ndarray)。返り値: 過去だけの板特徴 (DataFrame)。
    """
    v = board_values(f)
    numeric = f.select_dtypes(include='number').copy()
    numeric.index = pd.to_datetime(f.time_s.to_numpy(), unit='s', utc=True)
    numeric.loc[f.block_delay_seconds.to_numpy() > 60, :] = np.nan
    total = numeric[['trade_pos', 'trade_neg', 'trade_unknown']].rolling('60s', min_periods=5).sum()
    v['trade_total60'] = total.sum(axis=1, skipna=False).to_numpy()
    v['trade_direction60'] = ((total.trade_pos-total.trade_neg)/total.sum(axis=1, skipna=False).replace(0, np.nan)).to_numpy()
    times = f.time_s.to_numpy(float)
    for seconds in [15, 60]:
        p = np.searchsorted(times, times-seconds, side='right')-1
        ok, ix = p >= 0, np.maximum(p, 0)
        ok &= times-seconds-times[ix] <= 60
        delta = (f.source_mid_last.to_numpy(float)-f.source_mid_last.to_numpy(float)[ix])/atr
        v[f'mid_change{seconds}_atr'] = np.where(ok, delta, np.nan)
    return v


def build_events(session: str, symbol: str, features: pd.DataFrame,
                 peer_features: pd.DataFrame | None = None, cutoff: float | None = None,
                 peer_lag: int = 60) -> tuple[pd.DataFrame, dict]:
    """機能: 24仮説を原本の解放順へ対応し、将来を含まない入口を作る。

    引数: session/symbol (str)、features/peer_features (DataFrame|None)、cutoff (float|None)、peer_lag (int)。
    返り値: v10互換イベント表と因果制約の監査値 (tuple[DataFrame, dict])。
    """
    if peer_lag < 60:
        raise ValueError('他銘柄の追加待機は60秒以上が必要です')
    f = features.loc[features.time_s <= cutoff].copy() if cutoff is not None else features.copy()
    f = f.reset_index(drop=True)
    if f.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS), dict(イベント数=0, 系統別={})
    if np.any(np.diff(f.seq) <= 0) or np.any(np.diff(f.time_s) <= 0) or not (f.source_last_seq < f.seq).all():
        raise ValueError('未解放または逆順の板特徴を検出しました')
    times, seqs = f.time_s.to_numpy(float), f.seq.to_numpy(int)
    z = price_grid(session, symbol, float(times[-1]))
    if z.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS), dict(イベント数=0, 系統別={})
    atr = atr_at(session, symbol, times)
    fresh = (f.block_delay_seconds.to_numpy(float) <= 60) & np.isfinite(atr)
    events: dict[tuple, dict] = {}
    peer = peer_features.copy().reset_index(drop=True) if peer_features is not None else pd.DataFrame()
    peer = peer.loc[peer.time_s+peer_lag <= times[-1]].reset_index(drop=True) if not peer.empty else peer

    def add(i: int, family: str, side: int, reason: dict, peer_i: int | None = None) -> None:
        """機能: 既知素材と発生行を伴うイベントを一意に記録する。

        引数: i (int)、family (str)、side (int)、reason (dict)、peer_i (int|None)。返り値: なし (None)。
        """
        if not fresh[i] or not side:
            return
        row = dict(event_id=f'{session}:{symbol}:{family}:{seqs[i]}', family=family, seq=int(seqs[i]),
                   time_s=float(times[i]), side=int(side), atr=float(atr[i]), deadline_time_s=float(times[i])+600,
                   source_last_seq=int(f.source_last_seq.iloc[i]), reason=reason,
                   peer_seq=-1, peer_source_last_seq=-1, peer_time_s=np.nan, peer_available_time_s=np.nan)
        if peer_i is not None:
            p = peer.iloc[peer_i]
            row.update(peer_seq=int(p.seq), peer_source_last_seq=int(p.source_last_seq),
                       peer_time_s=float(p.time_s), peer_available_time_s=float(p.time_s)+peer_lag)
        events[(family, i)] = row

    # ----------------------------------------
    # 分足条件は開始時刻＋２分で解放し、その後の最初の板解放行で使う。
    mtimes = z.available_time_s.to_numpy(float)
    mfresh = z.stale_minutes.le(1).to_numpy() & np.isfinite(z.atr.to_numpy())
    for family, candidates in minute_conditions(z).items():
        sides = candidates if family == 'P09' else sampled_events(candidates, mtimes, mfresh)
        for j in np.flatnonzero(sides):
            i = int(np.searchsorted(times, mtimes[j], side='left'))
            if i < len(f) and times[i]-mtimes[j] <= 60 and mfresh[j]:
                row = z.iloc[j]
                detail = {key: float(row[key]) for key in ['close', 'atr', 'z20', 'vwap', 'volume_ratio', 'rsi7',
                                                           'ou_beta', 'ou_half_life', 'ou_mean', 'gap38', 'delta5']}
                add(i, family, int(sides[j]), dict(**detail, minute_available_time_s=float(mtimes[j])))

    # ----------------------------------------
    # 板仮説は単なるmicropriceと最良数量の重複を独立思想として数えない。
    values = board_extended(f, atr)
    ofi, ofi300, imb, deep = values.ofi60, values.ofi300, values.imb1_60, values.imb5_60
    board = {
        'P13': signed_condition((ofi >= .2) & (ofi300 >= .05), (ofi <= -.2) & (ofi300 <= -.05)),
        'P14': signed_condition(imb >= .25, imb <= -.25),
        'P15': signed_condition((deep >= .15) & (imb >= .05), (deep <= -.15) & (imb <= -.05)),
        'P16': signed_condition((values.trade_direction60 >= .3) & (values.trade_total60 >= 5) & (values.quote60 > 0),
                                (values.trade_direction60 <= -.3) & (values.trade_total60 >= 5) & (values.quote60 < 0)),
        'P17': signed_condition((values.ofi_cross >= .2) & (ofi >= .1), (values.ofi_cross <= -.2) & (ofi <= -.1)),
        'P18': signed_condition((ofi <= -.2) & (values.mid_change60_atr >= -.1) & (values.mid_change15_atr > 0),
                                (ofi >= .2) & (values.mid_change60_atr <= .1) & (values.mid_change15_atr < 0)),
    }
    for family, candidates in board.items():
        for i in np.flatnonzero(sides := sampled_events(candidates, times, fresh, 2)):
            add(int(i), family, int(sides[i]), {key: float(value) for key, value in values.iloc[i].items()})

    # ----------------------------------------
    # ２銘柄は受信時計がないため他銘柄を追加60秒待ち、元解放時刻から180秒以内のみ有効とする。
    if not peer.empty:
        if np.any(np.diff(peer.seq) <= 0) or np.any(np.diff(peer.time_s) <= 0) or not (peer.source_last_seq < peer.seq).all():
            raise ValueError('他銘柄に未解放または逆順の板特徴があります')
        ptimes = peer.time_s.to_numpy(float)
        ppos = np.searchsorted(ptimes+peer_lag, times, side='right')-1
        pidx = np.maximum(ppos, 0)
        pair_fresh = fresh & (ppos >= 0) & (times-ptimes[pidx] <= 180) & (peer.block_delay_seconds.to_numpy()[pidx] <= 60)
        pv = board_values(peer)
        peer_symbol = SYMBOLS[1-SYMBOLS.index(symbol)]
        pz = price_grid(session, peer_symbol, float(ptimes[-1]))
        ownpos = np.searchsorted(mtimes, times, side='right')-1
        ownidx = np.maximum(ownpos, 0)
        price_fresh = pair_fresh & (ownpos >= 0) & (z.stale_minutes.to_numpy()[ownidx] <= 1)
        if not pz.empty:
            peerpos = np.searchsorted(pz.available_time_s.to_numpy(float), ptimes[pidx], side='right')-1
            peeridx = np.maximum(peerpos, 0)
            price_fresh &= (peerpos >= 0) & (pz.stale_minutes.to_numpy()[peeridx] <= 1)
            ownret = z.return5_atr.to_numpy()[ownidx]
            peerret = pz.return5_atr.to_numpy()[peeridx]
            difference = ownret-peerret
            own_delta = z.delta1.to_numpy()[ownidx]
            joint = {
                'P19': signed_condition((peerret >= .75) & (ownret < .25), (peerret <= -.75) & (ownret > -.25)),
                'P20': signed_condition((pv.ofi60.to_numpy()[pidx] >= .2) & (z.gap38.to_numpy()[ownidx] >= .1*atr),
                                        (pv.ofi60.to_numpy()[pidx] <= -.2) & (z.gap38.to_numpy()[ownidx] <= -.1*atr)),
                'P21': signed_condition((difference <= -1) & (own_delta > 0), (difference >= 1) & (own_delta < 0)),
                'P22': signed_condition((values.pressure >= .1) & (pv.pressure.to_numpy()[pidx] >= .1),
                                        (values.pressure <= -.1) & (pv.pressure.to_numpy()[pidx] <= -.1)),
            }
            for family, candidates in joint.items():
                eligibility = pair_fresh if family == 'P22' else price_fresh
                for i in np.flatnonzero(sides := sampled_events(candidates, times, eligibility, 2)):
                    detail = dict(own_return5_atr=float(ownret[i]), peer_return5_atr=float(peerret[i]),
                                  relative_return5_atr=float(difference[i]), peer_ofi60=float(pv.ofi60.iloc[pidx[i]]),
                                  own_pressure=float(values.pressure.iloc[i]), peer_pressure=float(pv.pressure.iloc[pidx[i]]),
                                  minute_available_time_s=float(mtimes[ownidx[i]]),
                                  peer_minute_available_time_s=float(pz.available_time_s.iloc[peeridx[i]]),
                                  peer_lag_seconds=peer_lag)
                    add(int(i), family, int(sides[i]), detail, int(pidx[i]))

    # ----------------------------------------
    # 旧方式は条件を変えず比較対象に残す。足読み込みだけ最新の既知原本へ差し替える。
    _legacy.price_grid = price_grid
    previous, _ = _legacy.build_events(session, symbol, f, peer, cutoff=cutoff, peer_lag=peer_lag)
    for old_id, new_id in [('S09', 'P23'), ('S17', 'P24')]:
        for row in previous.loc[previous.family.eq(old_id)].to_dict('records'):
            row['family'] = new_id
            row['event_id'] = f'{session}:{symbol}:{new_id}:{row["seq"]}'
            i = int(np.searchsorted(seqs, row['seq']))
            events[(new_id, i)] = row
    output = pd.DataFrame(list(events.values()), columns=EVENT_COLUMNS).sort_values(['seq', 'family']).reset_index(drop=True)
    if not output.empty:
        assert output.event_id.is_unique and (output.source_last_seq < output.seq).all()
        paired = output.peer_available_time_s.notna()
        assert (output.loc[paired, 'peer_available_time_s'] <= output.loc[paired, 'time_s']).all()
    audit = dict(イベント数=len(output), 系統別={p['id']: int(output.family.eq(p['id']).sum()) for p in profiles()},
                 他銘柄追加待機秒=peer_lag, 足解放='１分足開始＋２分、５分ATR開始＋６分',
                 信号再通知='P01〜P22は同方向の再通知を５分空ける。板は異なる２解放ブロック確認。CUSUMは方向初回・反転だけ。',
                 出来高='完全フラグのある観測足だけ使用。P02は全既知分が完全な場合だけ。tick-ruleは真の成行方向ではない。',
                 受信時刻='CurrentPriceTimeは約定時計。同時刻ブロックを次時刻まで封印し、他銘柄には60秒待機・180秒鮮度。')
    return output, audit


def state_at(tape: dict, features: pd.DataFrame, z: pd.DataFrame) -> dict:
    """機能: 注文管理用の既知板・価格方向を全気配へ対応する。

    引数: tape (dict)、features/z (DataFrame)。返り値: 注文器と互換の状態 (dict)。
    """
    return _legacy.state_at(tape, features, z)


def load_inputs(sessions: list[str] | None = None) -> dict:
    """機能: 保存データだけから全対象の24信号と生板系列を準備する。

    引数: sessions (list[str]|None)。返り値: (session,symbol)をキーとした入力 (dict)。
    """
    output = {}
    for session in SESSIONS if sessions is None else sessions:
        folder = feature_root(session)
        frames = {symbol: pd.read_csv(folder/f'{symbol}_{session}.csv') for symbol in SYMBOLS}
        for symbol in SYMBOLS:
            f, peer = frames[symbol], frames[SYMBOLS[1-SYMBOLS.index(symbol)]]
            events, audit = build_events(session, symbol, f, peer)
            tape = dict(np.load(folder/f'約定系列_{symbol}_{session}.npz', allow_pickle=False))
            tape['atr'] = atr_at(session, symbol, tape['time_s'])
            z = price_grid(session, symbol, float(tape['time_s'][-1]))
            output[(session, symbol)] = dict(features=f, peer_features=peer, tape=tape, events=events,
                                            state=state_at(tape, f, z), price_frame=load_price_frame(session, symbol, float(tape['time_s'][-1])),
                                            event_audit=audit)
    return output


def main() -> None:
    """機能: 24仮説を損益計算前に保存し、実装ハッシュとAPI未取得を記録する。

    引数: なし。返り値: なし (None)。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/'信号条件一覧.json').write_text(json.dumps(profiles(), ensure_ascii=False, indent=2), encoding='utf-8')
    frozen = dict(固定時刻=str(pd.Timestamp.now(tz='Asia/Tokyo')), 今回API取得回数=0, 条件数=24,
                  signals_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  既知末尾='2026-09-24T00:02:00+09:00', 説明='仕様作成時に既存５完了セッションは既知。統計的な完全未使用学習標本ではない。')
    (OUT/'信号事前固定.json').write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding='utf-8')
    print('24信号定義を保存しました。今回の損益は未計算、APIは未取得です。')


if __name__ == '__main__':
    main()
