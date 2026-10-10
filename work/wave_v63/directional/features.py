"""当該セッションの確定1分だけから押し戻し・価格拒否・二指数確認を公開する。"""

from pathlib import Path
import pickle

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
SETTINGS = ({'id': 'M1_20', 'short': 3, 'long': 20},)


def load_inputs() -> tuple[dict, dict]:
    """機能: 最終約定値を除外した共通価格キャッシュを取得する。

    引数: なし。
    返り値: 価格入力と気配入力(tuple[dict,dict])。全50口座は既知データとして扱う。
    """
    inputs = pickle.loads((WORK.parent / 'wave_v60/inputs.pkl').read_bytes())
    quotes = pickle.loads((WORK.parent / 'wave_v60/quotes.pkl').read_bytes())
    assert len(inputs) == 50 and set(inputs) == set(quotes)
    assert all('last' not in value for value in inputs.values())
    assert all('last' not in value for value in quotes.values())
    return inputs, quotes


def build(ready: dict, quotes: dict, setting: dict) -> pd.DataFrame:
    """機能: 1分足が完了した後の最初の実観測行で、過去のみの特徴を公開する。

    引数: ready(dict)、quotes(dict)、setting(dict) は短長の移動平均期間。
    返り値: 公開原本行番号と確定指標を持つ表(pd.DataFrame)。
    空白足は直前終値で据置し、観測flagは偽を保持する。未確定の末尾足は使用しない。
    """
    times, seq, mid = ready['time_s'], ready['seq'], quotes['mid']
    np.testing.assert_array_equal(seq, quotes['seq'])
    np.testing.assert_array_equal(times, quotes['time_s'])
    assert np.all(np.diff(times) >= 0) and np.all(np.diff(seq) > 0)
    seconds, short, long = 60, setting['short'], setting['long']
    buckets = np.floor(times / seconds).astype(np.int64)
    starts = np.r_[0, np.flatnonzero(np.diff(buckets)) + 1]
    ends = np.r_[starts[1:] - 1, len(times) - 1]
    actual = pd.DataFrame({'open': mid[starts], 'close': mid[ends], 'high': np.maximum.reduceat(mid, starts),
                           'low': np.minimum.reduceat(mid, starts), 'source_last_seq': seq[ends],
                           'source_last_time': times[ends]}, index=buckets[starts])
    grid = np.arange(int(np.floor(ready['start'] / seconds)), buckets[-1], dtype=np.int64)
    bars = pd.DataFrame(index=grid).join(actual)
    bars['observed'] = bars['close'].notna()
    for name in ('close', 'source_last_seq', 'source_last_time'):
        bars[name] = bars[name].ffill().astype(float)
    for name in ('open', 'high', 'low'):
        bars[name] = bars[name].fillna(bars['close'])
    bars['short'] = bars['close'].rolling(short, min_periods=short).mean()
    bars['long'] = bars['close'].rolling(long, min_periods=long).mean()
    bars['std'] = bars['close'].rolling(long, min_periods=long).std(ddof=0)
    bars['gap'] = bars['short'] - bars['long']
    bars['prior_high'] = bars['high'].shift(1).rolling(long, min_periods=long).max()
    bars['prior_low'] = bars['low'].shift(1).rolling(long, min_periods=long).min()
    displacement = (bars['close'] - bars['close'].shift(long)).abs()
    travel = bars['close'].diff().abs().rolling(long, min_periods=long).sum()
    bars['er'] = (displacement / travel).where(travel.ne(0), 0.)
    bars['observed_fraction'] = bars['observed'].rolling(long, min_periods=long).mean()
    bars['prior_observed_fraction'] = bars['observed'].shift(1).rolling(long, min_periods=long).mean()
    bars['ret10'] = bars['close'] - bars['close'].shift(10)
    travel10 = bars['close'].diff().abs().rolling(10, min_periods=10).sum()
    bars['er10'] = (bars['ret10'].abs() / travel10).where(travel10.ne(0), 0.)
    for lag in (1, 2, 3):
        for name in ('open', 'high', 'low', 'close', 'short', 'long', 'std', 'gap', 'observed'):
            bars[f'{name}_lag{lag}'] = bars[name].shift(lag)
    # ----------------------------------------
    # 空白をまたいでも、過去の各足を同じ原本行で重複発火させない。
    published = starts[1:]
    frame = bars.reindex(buckets[published] - 1).reset_index(names='source_bucket')
    frame['bar_start'] = frame['source_bucket'] * seconds
    frame['bar_end'] = frame['bar_start'] + seconds
    frame['i'] = published
    frame['seq'], frame['time_s'] = seq[published], times[published]
    frame['mid'] = mid[published]
    frame['spread'] = quotes['ask'][published] - quotes['bid'][published]
    frame['bar_age'] = frame['time_s'] - frame['source_last_time']
    frame['publication_delay'] = frame['time_s'] - frame['bar_end']
    frame['elapsed_s'] = frame['time_s'] - ready['start']
    frame['quality'] = (frame['observed'].eq(True) & frame['observed_lag1'].eq(True)
                          & frame['bar_age'].between(0, seconds)
                          & frame['publication_delay'].between(0, seconds))
    frame['can_trade'] = (frame['quality'] & frame['elapsed_s'].ge((long + 3) * seconds)
                          & frame['observed_fraction'].ge(.8)
                          & frame[['short', 'long', 'long_lag3', 'gap_lag1', 'er']].notna().all(axis=1))
    assert (frame['source_last_seq'] < frame['seq']).all()
    assert (frame['source_last_time'] < frame['time_s']).all()
    assert (frame['bar_end'] <= frame['time_s']).all()
    return frame


def audit(ready: dict, quotes: dict, setting: dict, full: pd.DataFrame) -> dict:
    """機能: 原本の途中切断と未来気配の変更に対して既公開特徴の不変性を確認する。

    引数: ready(dict)、quotes(dict)、setting(dict)、full(pd.DataFrame)。
    返り値: 因果検査回数と準備可能数(dict)。損益を使用しない。
    """
    checks = 0
    for size in (1, len(ready['seq']) // 3, len(ready['seq']) * 3 // 4):
        clipped = dict(ready)
        for name in ('seq', 'time_s'):
            clipped[name] = ready[name][:size]
        quote_part = {name: value[:size] for name, value in quotes.items()}
        expected = full[full['i'] < size].reset_index(drop=True)
        pd.testing.assert_frame_equal(build(clipped, quote_part, setting), expected, check_exact=True)
        changed = {name: value.copy() for name, value in quotes.items()}
        for name in ('bid', 'ask', 'mid'):
            changed[name][size:] += 999 * ready['tick']
        modified = build(ready, changed, setting)
        pd.testing.assert_frame_equal(modified[modified['i'] < size].reset_index(drop=True), expected, check_exact=True)
        checks += 2
    return {'切断と未来改変一致': checks, '公開特徴数': len(full), '準備可能数': int(full['can_trade'].sum())}
