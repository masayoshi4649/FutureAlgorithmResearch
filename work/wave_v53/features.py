"""当該セッションの過去確定足と公開板だけで一般的な分析指標を作る。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
MEASUREMENT = HERE.parent / 'wave_v52/measurement'
sys.path.insert(0, str(MEASUREMENT))
from quotes import load_inputs_only

BOARD = ('execution', 'recovery', 'supply', 'withdrawal', 'addition', 'repricing')


def save(path: Path, value: object) -> None:
    """機能: 日本語で測定仕様と監査結果を保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def completed_bars(ready: dict, quotes: dict, seconds: int) -> pd.DataFrame:
    """機能: 中値足を作り、次の区間の最初の原本行でだけ公開する。

    引数: ready(dict)、quotes(dict)、seconds(int:60または300)。
    返り値: 末尾未確定区間を含まない足表(DataFrame)。空白区間を捏造しない。
    """
    times, seq, mids = ready['time_s'], ready['seq'], quotes['mid']
    assert np.array_equal(seq, quotes['seq']) and np.array_equal(times, quotes['time_s'])
    buckets = np.floor(times / seconds).astype(np.int64) * seconds
    starts = np.r_[0, np.flatnonzero(np.diff(buckets) != 0) + 1]
    rows = []
    for begin, following in zip(starts[:-1], starts[1:]):
        end = following - 1
        part = mids[begin:following]
        rows.append(dict(bar_start=float(buckets[begin]), time_s=float(times[following]),
                         seq=int(seq[following]), ready_index=int(following),
                         source_last_seq=int(seq[end]), source_last_time=float(times[end]),
                         open=float(part[0]), high=float(part.max()), low=float(part.min()), close=float(part[-1]),
                         coverage_minutes=len(np.unique(np.floor(times[begin:following] / 60.))),
                         bar_age=float(times[following] - buckets[begin] - seconds)))
    result = pd.DataFrame(rows)
    if len(result):
        assert (result.source_last_seq < result.seq).all()
        assert (result.source_last_time < result.time_s).all()
        assert (result.bar_start + seconds <= result.time_s).all()
    return result


def true_range(bars: pd.DataFrame) -> np.ndarray:
    """機能: 前場を参照せず当該セッションの真の値幅を作る。

    引数: bars(DataFrame)。返り値: 各確定足のTR(ndarray)。初足は高値−安値。
    """
    h, l, c = (bars[name].to_numpy() for name in ('high', 'low', 'close'))
    values = h - l
    if len(values) > 1:
        values[1:] = np.maximum(values[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return values


def rolling_complete(bars: pd.DataFrame, count: int, exclude_current: bool = False) -> np.ndarray:
    """機能: 指定窓に欠落した分が無いかを判定する。

    引数: bars(DataFrame)、count(int)、exclude_current(bool)。返り値: 連続分の真偽(ndarray)。
    """
    t = bars.bar_start.to_numpy()
    valid = np.zeros(len(t), dtype=bool)
    for i in range(len(t)):
        end = i - int(exclude_current)
        begin = end - count + 1
        if begin >= 0:
            valid[i] = (t[end] - t[begin] == (count - 1) * 60.)
            if exclude_current:
                valid[i] = valid[i] and t[i] - t[end] == 60.
    return valid


def rsi_wilder(close: np.ndarray) -> np.ndarray:
    """機能: セッション内の最初の14変化で初期化しRSI14を更新する。

    引数: close(ndarray)。返り値: Wilder平滑のRSI14(ndarray)。準備不足はNaN。
    """
    result = np.full(len(close), np.nan)
    if len(close) < 15:
        return result
    delta = np.diff(close)
    gains, losses = np.maximum(delta, 0.), np.maximum(-delta, 0.)
    up, down = gains[:14].mean(), losses[:14].mean()
    for i in range(14, len(close)):
        if i > 14:
            up = (up * 13. + gains[i - 1]) / 14.
            down = (down * 13. + losses[i - 1]) / 14.
        result[i] = 100. * up / (up + down) if up + down > 0 else 50.
    return result


def add_swings(bars: pd.DataFrame) -> None:
    """機能: 左右2本の厳密な山谷を右側2本が確定した公開行から保持する。

    引数: bars(DataFrame)。返り値: なし(None)。元の発生足へ値を遡及しない。
    """
    for side, column in (('high', 'high'), ('low', 'low')):
        level = origin = confirmed_time = confirmed_seq = np.nan
        values = {name: [] for name in ('value', 'time', 'confirmed_time', 'confirmed_seq')}
        for i in range(len(bars)):
            if i >= 4 and bars.bar_start.iloc[i] - bars.bar_start.iloc[i - 4] == 240.:
                center = i - 2
                window = bars[column].iloc[i - 4:i + 1].to_numpy()
                others = np.r_[window[:2], window[3:]]
                exists = np.all(window[2] > others) if side == 'high' else np.all(window[2] < others)
                if exists:
                    level, origin = float(window[2]), float(bars.bar_start.iloc[center])
                    confirmed_time, confirmed_seq = float(bars.time_s.iloc[i]), int(bars.seq.iloc[i])
            for name, value in zip(values, (level, origin, confirmed_time, confirmed_seq)):
                values[name].append(value)
        for name, data in values.items():
            bars[f'swing_{side}' if name == 'value' else f'swing_{side}_{name}'] = data


def vwap_series(blocks: pd.DataFrame, start: float) -> dict:
    """機能: 自セッションの正出来高増分と源最終価格によるVWAP代理を作る。

    引数: blocks(DataFrame)、start(float)。返り値: 各公開ブロック時点の累積状態(dict)。
    提供VWAP・場初行の累積数量を使わない。出来高欠測/リセット時は再始動する。
    """
    names = ('vwap_proxy', 'cum_volume', 'vwap_anchor_time', 'vwap_reset_count', 'vwap_discontinuity_count')
    output = {name: np.full(len(blocks), np.nan) for name in names}
    numerator = denominator = 0.
    anchor, resets, discontinuities = start, 0, 0
    for i, row in enumerate(blocks.itertuples()):
        discontinuities += int(row.continuity_resets)
        if row.volume_resets > 0 or row.unavailable_volume_events > 0:
            numerator = denominator = 0.
            anchor, resets = float(row.time_s), resets + 1
        else:
            volume = float(row.source_volume_delta)
            assert volume >= 0
            numerator += volume * float(row.source_last)
            denominator += volume
        output['vwap_proxy'][i] = numerator / denominator if denominator else np.nan
        output['cum_volume'][i] = denominator
        output['vwap_anchor_time'][i] = anchor
        output['vwap_reset_count'][i] = resets
        output['vwap_discontinuity_count'][i] = discontinuities
    return output


def imbalance(up: float, down: float) -> float:
    """機能: 二量の偏りを求め、観測対象ゼロを未知にする。

    引数: up/down(float)。返り値: 偏りまたはNaN(float)。
    """
    return (up - down) / (up + down) if up + down > 0 else np.nan


def add_board(bars: pd.DataFrame, blocks: pd.DataFrame, start: float) -> None:
    """機能: 各公開行までに判明した直前60秒の板と出来高だけを結合する。

    引数: bars/blocks(DataFrame)、start(float)。返り値: なし(None)。品質不明はNaN。
    """
    columns = ('exec_buy', 'exec_sell', 'exec_unknown', 'noexec_ask_remove', 'noexec_bid_remove',
               'noexec_bid_add', 'noexec_ask_add', 'refill_bid_fixed_quote', 'refill_ask_fixed_quote',
               'both_up', 'both_down', 'valid_events', 'continuity_resets', 'volume_resets',
               'unavailable_volume_events', 'depth_incomplete_events', 'depth_disordered_events', 'depth_duplicate_events')
    a = {name: blocks[name].to_numpy() for name in blocks.columns}
    prefixes = {name: np.r_[0., np.cumsum(a[name])] for name in columns}
    vwap = vwap_series(blocks, start)
    records = []
    for row in bars.itertuples():
        right = int(np.searchsorted(a['seq'], row.seq, side='right'))
        at = right - 1
        out = {name: np.nan for name in BOARD}
        out.update(board_valid=False, board_age=np.nan, board_blocks=0, unknown_fraction=np.nan,
                   volume60=np.nan, board_source_last_seq=np.nan,
                   **{name: np.nan for name in vwap})
        if at >= 0:
            assert a['time_s'][at] <= row.time_s and a['source_last_seq'][at] < row.seq
            out.update({name: float(values[at]) for name, values in vwap.items()})
            left = max(int(np.searchsorted(a['time_s'], row.time_s - 60., side='right')),
                       int(np.searchsorted(a['source_time_s'], row.time_s - 60., side='left')))
            out.update(board_age=float(row.time_s - a['time_s'][at]), board_blocks=max(right - left, 0),
                       board_source_last_seq=int(a['source_last_seq'][at]))
            if right > left:
                sums = {name: prefixes[name][right] - prefixes[name][left] for name in columns}
                bad = sum(sums[name] for name in ('continuity_resets', 'volume_resets', 'unavailable_volume_events',
                                                 'depth_incomplete_events', 'depth_disordered_events', 'depth_duplicate_events'))
                good = right - left >= 2 and sums['valid_events'] >= 2 and bad == 0 and out['board_age'] <= 60.
                good = good and a['source_age'][left:right].max(initial=0.) <= 60.
                if good:
                    weights = a['valid_events'][left:right]
                    buy, sell, unknown = (sums[name] for name in ('exec_buy', 'exec_sell', 'exec_unknown'))
                    volume = buy + sell + unknown
                    near_bid = np.average(a['supply_bid_near'][left:right], weights=weights)
                    near_ask = np.average(a['supply_ask_near'][left:right], weights=weights)
                    out.update(board_valid=True, execution=(buy - sell) / volume if volume else np.nan,
                               unknown_fraction=unknown / volume if volume else np.nan, volume60=float(volume),
                               recovery=imbalance(sums['refill_bid_fixed_quote'], sums['refill_ask_fixed_quote']),
                               supply=imbalance(near_bid, near_ask),
                               withdrawal=imbalance(sums['noexec_ask_remove'], sums['noexec_bid_remove']),
                               addition=imbalance(sums['noexec_bid_add'], sums['noexec_ask_add']),
                               repricing=imbalance(sums['both_up'], sums['both_down']))
        records.append(out)
    for name in records[0] if records else []:
        bars[name] = [row[name] for row in records]


def build_account(ready: dict, quotes: dict, blocks: pd.DataFrame) -> pd.DataFrame:
    """機能: 一つのセッションだけの確定足・一般指標・公開済み板をまとめる。

    引数: ready(dict)、quotes(dict)、blocks(DataFrame)。返り値: 因果的な特徴表(DataFrame)。
    場開始前の価格・累積量・前セッション指標を持ち込まない。
    """
    bars = completed_bars(ready, quotes, 60)
    five = completed_bars(ready, quotes, 300)
    if not len(bars):
        return bars
    bars['source_bar_start'] = bars.bar_start
    index = bars.ready_index.to_numpy(dtype=int)
    bars['last'] = ready['last'][index]
    for name in ('bid', 'ask', 'mid'):
        bars[name] = quotes[name][index]
    bars['elapsed'] = bars.time_s - ready['start']
    bars['atr1'] = pd.Series(true_range(bars)).rolling(14, min_periods=14).mean().to_numpy()
    bars['atr5'] = np.nan
    bars['atr5_count'] = 0
    bars['atr5_coverage_minutes'] = np.nan
    bars['atr5_contiguous'] = False
    bars['atr5_source_last_seq'] = np.nan
    if len(five):
        tr = true_range(five)
        atr = pd.Series(tr).rolling(14, min_periods=4).mean().to_numpy()
        pos = np.searchsorted(five.seq.to_numpy(), bars.seq.to_numpy(), side='right') - 1
        for i, k in enumerate(pos):
            if k >= 0:
                count = min(k + 1, 14)
                begin = k - count + 1
                contiguous = (five.bar_start.iloc[k] - five.bar_start.iloc[begin] == (count - 1) * 300.)
                contiguous = contiguous and bool((five.coverage_minutes.iloc[begin:k + 1] == 5).all())
                bars.loc[i, ['atr5', 'atr5_count', 'atr5_coverage_minutes', 'atr5_contiguous', 'atr5_source_last_seq']] = [
                    atr[k], count, int(five.coverage_minutes.iloc[begin:k + 1].sum()), contiguous, int(five.source_last_seq.iloc[k])]
    close = bars.close
    bars['ema8'] = close.ewm(span=8, adjust=False).mean()
    bars['ema21'] = close.ewm(span=21, adjust=False).mean()
    bars['rsi14'] = rsi_wilder(close.to_numpy())
    bars['prior20_high'] = bars.high.shift(1).rolling(20, min_periods=20).max().where(rolling_complete(bars, 20, True))
    bars['prior20_low'] = bars.low.shift(1).rolling(20, min_periods=20).min().where(rolling_complete(bars, 20, True))
    bars['mean20'] = close.rolling(20, min_periods=20).mean().where(rolling_complete(bars, 20))
    bars['std20'] = close.rolling(20, min_periods=20).std(ddof=0).where(rolling_complete(bars, 20))
    path = close.diff().abs().rolling(15, min_periods=15).sum()
    bars['er15'] = (close - close.shift(15)).abs().div(path).where(path > 0, 0.).where(rolling_complete(bars, 16))
    bars['or30_high'] = np.nan
    bars['or30_low'] = np.nan
    bars['or30_count'] = 0
    initial = bars[(bars.bar_start >= ready['start']) & (bars.bar_start < ready['start'] + 1800.)]
    for i, row in bars.iterrows():
        if row.time_s >= ready['start'] + 1800.:
            observed = initial[initial.seq <= row.seq]
            bars.loc[i, 'or30_count'] = len(observed)
            if len(observed) == 30:
                bars.loc[i, ['or30_high', 'or30_low']] = [observed.high.max(), observed.low.min()]
    add_swings(bars)
    add_board(bars, blocks, float(ready['start']))
    previous = ('open', 'high', 'low', 'close', 'ema8', 'ema21', 'rsi14', 'prior20_high', 'prior20_low',
                'mean20', 'std20', 'er15', 'or30_high', 'or30_low', 'swing_high', 'swing_low', 'vwap_proxy')
    for name in previous:
        bars[f'prev_{name}'] = bars[name].shift(1)
    bars['sma20_lag1'] = bars['prev_mean20']
    for name, lag in (('close', 5), ('close', 15), ('ema21', 5), ('vwap_proxy', 5)):
        bars[f'{name}_lag{lag}'] = bars[name].shift(lag).where(rolling_complete(bars, lag + 1))
    bars['can_trade'] = (bars.elapsed >= 1200.) & np.isfinite(bars.atr1) & (bars.atr1 > 0) & np.isfinite(bars.atr5) & (bars.atr5 > 0) & (bars.bar_age <= 60.)
    bars['session'] = ready['session']
    bars['symbol'] = ready['symbol']
    return bars


def join_peers(features: dict) -> dict:
    """機能: 相手の60秒前までの公開値を、その時点から鮮度60秒以内で結合する。

    引数: features(dict[tuple,DataFrame])。返り値: 元表を変更しない相手列追加辞書(dict)。
    """
    output = {}
    columns = BOARD + ('board_valid', 'close', 'prev_close', 'ema8', 'ema21', 'atr5', 'er15', 'can_trade')
    for key, original in features.items():
        frame = original.copy()
        peer = features[(key[0], 'NK225' if key[1] == 'TOPIX' else 'TOPIX')]
        for name in columns:
            frame[f'peer_{name}'] = np.nan
        frame['peer_time_s'] = np.nan
        frame['peer_seq'] = np.nan
        frame['peer_age'] = np.nan
        if len(peer) and len(frame):
            target = frame.time_s.to_numpy() - 60.
            pos = np.searchsorted(peer.time_s.to_numpy(), target, side='right') - 1
            for i, k in enumerate(pos):
                if k < 0 or target[i] - peer.time_s.iloc[k] > 60.:
                    continue
                frame.loc[i, 'peer_time_s'] = float(peer.time_s.iloc[k])
                frame.loc[i, 'peer_seq'] = int(peer.seq.iloc[k])
                frame.loc[i, 'peer_age'] = float(target[i] - peer.time_s.iloc[k])
                for name in columns:
                    frame.loc[i, f'peer_{name}'] = float(peer[name].iloc[k])
            assert (frame.peer_time_s.dropna() <= frame.time_s[frame.peer_time_s.notna()] - 60.).all()
        output[key] = frame
    return output


def main() -> None:
    """機能: 全23場を測定し、全場の途中打切りと公開順序を監査する。

    引数: なし。返り値: なし(None)。原本・旧成果は変更せずAPI接続もしない。
    """
    HERE.mkdir(parents=True, exist_ok=True)
    save(HERE / '測定仕様.json', dict(
        確定足='中値OHLC。CurrentPriceTimeの次のminute区間の最初の有効原本行で前minuteを公開。旧作業の120秒遅延方式とは異なる。最終未完足は捨てる。空白minuteを補間しない。',
        ATR='1分は確定14TRの単純平均。5分は確定4TRから開始し14TRまで拡大、その後直近14平均。初足TRは高安差。atr5_count/coverage_minutes/contiguousに成熟度と空白を記録。',
        VWAP='当該セッションで公開した正出来高増分×source_lastの累積平均。提供VWAP・開始時累積量は不使用。正確な約定代金VWAPではない。出来高欠測/resetを含むblockは加算せず累積をリセットし、以後再始動。anchor_time/reset_countを記録。不正板跨ぎ等で失った出来高は復元できない。板不連続はdiscontinuity_countへ累計するが出来高リセットとは区別する。',
        指標='EMA8/21は初足closeで開始。RSI14は最初14変化を平均し以後Wilder平滑。mean/std20は現在確定足込み、stdは母標準偏差。過去20高安は現在確定足を除外。ER15は16close。各20/15分窓とlagは連続分が揃わなければ未知。',
        開始レンジ='自セッション開始から30本の連続1分足が揃った後だけ開始30分高安を公開。後から値を修正しない。',
        スイング='左右2本より厳密に高い/低い中心足。右2本確定の公開行から採用し、発生足へ遡及しない。発生time/確認time/確認seqを保持。',
        板='直前60秒の公開block。源時刻も60秒内、2block以上、連続性・出来高・10段品質不良なし。execution/recovery/supply/withdrawalは既存定義。未知はNaN。',
        相手='自己公開時刻−60秒以前の相手公開値をasof結合し、基準時刻から60秒超なら未知。',
        新規準備='can_tradeは開始20分以上、ATR1/5準備と直前足の公開遅延60秒以下。板の品質とは分離。',
        時刻限界='CurrentPriceTimeは約定時計で板受信時計ではない。同時刻行の物理順を保持するが実際の時間分布を復元できない。',
        コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 現在API取得数=0))
    inputs = load_inputs_only()
    quotes = pickle.loads((MEASUREMENT / 'quotes.pkl').read_bytes())
    blocks = pickle.loads((MEASUREMENT / 'features.pkl').read_bytes())
    base = {key: build_account(ready, quotes[key], blocks[key]) for key, ready in inputs.items()}
    features = join_peers(base)
    (HERE / '特徴.pkl').write_bytes(pickle.dumps(features, pickle.HIGHEST_PROTOCOL))
    checks = []
    sessions = sorted({key[0] for key in inputs})
    for session in sessions:
        for fraction in (.35, .75):
            partial, cutoffs = {}, {}
            for symbol in ('TOPIX', 'NK225'):
                key = (session, symbol)
                ready = inputs[key]
                cutoff_time = ready['start'] + (ready['limit'] - ready['start']) * fraction
                size = int(np.searchsorted(ready['time_s'], cutoff_time, side='right'))
                sliced_ready = {name: value[:size] if isinstance(value, np.ndarray) and len(value) == len(ready['seq']) else value for name, value in ready.items()}
                sliced_quotes = {name: value[:size] for name, value in quotes[key].items()}
                cutoff = int(ready['seq'][size - 1])
                cutoffs[key] = cutoff
                partial[key] = build_account(sliced_ready, sliced_quotes, blocks[key].loc[blocks[key].seq <= cutoff].copy())
            joined = join_peers(partial)
            for key, actual in joined.items():
                expected = features[key].loc[features[key].seq <= cutoffs[key]].reset_index(drop=True)
                pd.testing.assert_frame_equal(actual, expected, check_exact=True)
                checks.append(dict(セッション=key[0], 銘柄=key[1], 切断比率=fraction, 一致行数=len(actual), 最終原本行=cutoffs[key]))
    records = []
    for key, frame in features.items():
        records.append(dict(セッション=key[0], 銘柄=key[1], 特徴行数=len(frame),
                            取引準備済行数=int(frame.can_trade.sum()), 板品質適合行数=int(frame.board_valid.sum()),
                            開始レンジ公開行数=int(frame.or30_high.notna().sum()),
                            VWAPリセット最大=int(frame.vwap_reset_count.max()),
                            五分ATR成熟14本行数=int((frame.atr5_count == 14).sum())))
    save(HERE / '特徴監査.json', dict(合格=True, 原本口座数=len(features), セッション数=len(sessions),
                                      特徴行数=sum(len(x) for x in features.values()), 途中切断=checks,
                                      列=list(next(iter(features.values())).columns), 口座別=records,
                                      現在API取得数=0, 前場参照なし=True))
    print('特徴完了', len(features), sum(len(x) for x in features.values()), 'prefix', len(checks), flush=True)


if __name__ == '__main__':
    main()
