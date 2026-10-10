"""既知25場を場ごとに保ち、未来を含まない確定5分方向材料を公開する。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import pickle

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent


def week_start(session: str) -> str:
    """機能: 夜間の翌朝部分もセッション開始日の週に含める。

    引数: session(str)。返り値: 月曜起点の日付(str)。
    """
    day = datetime.strptime(session[:10], '%Y-%m-%d')
    return (day - timedelta(days=day.weekday())).date().isoformat()


def direction_events(ready: dict, quotes: dict) -> np.ndarray:
    """機能: 確定5分終値7本の方向材料を次の実観測足の先頭行で公開する。

    引数: ready/quotes(dict)。返り値: 公開index、30分差、15分差、有効印の4列(ndarray)。
    空白足は過去終値据置、直近2足と7本中6本以上の実観測が必要。場を跨いで準備しない。
    """
    times, mids = ready['time_s'], quotes['mid']
    buckets = np.floor(times / 300.).astype(np.int64)
    changes = np.flatnonzero(np.r_[False, buckets[1:] != buckets[:-1]])
    if not len(changes):
        return np.empty((0, 4))
    start_bucket = int(np.floor(ready['start'] / 300.))
    all_buckets = np.arange(start_bucket, int(buckets[-1]) + 1)
    endpoints = np.r_[changes - 1, len(mids) - 1]
    observed_values = pd.Series(mids[endpoints], index=buckets[endpoints])
    close = observed_values.reindex(all_buckets).ffill()
    observed = pd.Series(np.isin(all_buckets, observed_values.index), index=all_buckets)
    valid = observed & observed.shift(1, fill_value=False) & observed.rolling(7, min_periods=7).sum().ge(6)
    d30, d15 = close - close.shift(6), close - close.shift(3)
    previous_buckets = buckets[changes] - 1
    selected = previous_buckets - start_bucket
    result = np.column_stack([changes, d30.to_numpy()[selected], d15.to_numpy()[selected],
                              valid.to_numpy()[selected].astype(float)])
    result[:, 3] *= np.isfinite(result[:, 1]) & np.isfinite(result[:, 2])
    assert np.all(times[changes - 1] < times[changes])
    return result


def load_accounts() -> dict:
    """機能: 既知50口座だけを読み、場を跨がず原本と確定足公開材料を用意する。

    引数: なし。返り値: (セッション,銘柄)ごとの原本配列・公開材料(dict)。外部取得なし。
    """
    source = HERE.parent.parent / 'wave_v60'
    inputs = pickle.loads((source / 'inputs.pkl').read_bytes())
    quotes = pickle.loads((source / 'quotes.pkl').read_bytes())
    assert set(inputs) == set(quotes) and len(inputs) == 50
    output = {}
    for key in sorted(inputs):
        ready, quote = inputs[key], quotes[key]
        np.testing.assert_array_equal(ready['seq'], quote['seq'])
        np.testing.assert_array_equal(ready['time_s'], quote['time_s'])
        assert np.all(np.diff(ready['time_s']) >= 0)
        output[key] = dict(session=key[0], symbol=key[1], week=week_start(key[0]),
            times=ready['time_s'], seqs=ready['seq'], mid=quote['mid'], bid=quote['bid'], ask=quote['ask'],
            sessions=np.zeros(len(ready['seq']), np.int64), limits=np.array([ready['limit']]),
            events=direction_events(ready, quote), tick=float(ready['tick']))
    return output


