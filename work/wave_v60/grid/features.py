"""既知25場を週ごとの原本列へ接続し、未来を含まない5分方向材料を公開する。"""

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


def load_streams(flatten_study_end: bool = True) -> dict:
    """機能: 週内の場を原本順に接続し、週末と調査末尾の強制清算を区別する。

    引数: flatten_study_end(bool) は調査末尾の仮想清算を有効にするか。
    返り値: (銘柄,週開始日)ごとの価格列・公開方向材料・場境界(dict)。
    読み取りは親が統合した既知50口座だけ。新しいAPIを取得しない。
    """
    parent = HERE.parent
    inputs = pickle.loads((parent / 'inputs.pkl').read_bytes())
    quotes = pickle.loads((parent / 'quotes.pkl').read_bytes())
    assert set(inputs) == set(quotes) and len(inputs) == 50
    all_sessions = sorted({key[0] for key in inputs})
    final_session = all_sessions[-1]
    streams = {}
    for symbol in ('TOPIX', 'NK225'):
        for week in sorted({week_start(s) for s in all_sessions}):
            sessions = [s for s in all_sessions if week_start(s) == week]
            columns = {name: [] for name in ('time_s', 'seq', 'mid', 'bid', 'ask', 'session_index')}
            events, limits, starts, offsets = [], [], [], []
            offset = 0
            for sid, session in enumerate(sessions):
                key = (session, symbol)
                ready, quote = inputs[key], quotes[key]
                np.testing.assert_array_equal(ready['seq'], quote['seq'])
                assert np.all(np.diff(ready['time_s']) >= 0)
                count = len(ready['seq'])
                offsets.append(offset)
                starts.append(ready['start'])
                limits.append(ready['limit'])
                for name in ('time_s', 'seq'):
                    columns[name].append(ready[name])
                for name in ('mid', 'bid', 'ask'):
                    columns[name].append(quote[name])
                columns['session_index'].append(np.full(count, sid, dtype=np.int64))
                published = direction_events(ready, quote)
                published[:, 0] += offset
                events.append(published)
                offset += count
            arrays = {name: np.concatenate(parts) for name, parts in columns.items()}
            assert np.all(np.diff(arrays['time_s']) >= 0)
            last = sessions[-1]
            last_day = datetime.strptime(last[:10], '%Y-%m-%d')
            if last_day.weekday() == 4 and last.endswith('_Night'):
                final_reason = 1
            elif last == final_session:
                final_reason = 2 if flatten_study_end else 0
            else:
                raise ValueError('金曜ナイト以外で週が途切れています')
            streams[(symbol, week)] = dict(**arrays, events=np.concatenate(events), sessions=sessions,
                limits=np.asarray(limits, float), starts=np.asarray(starts, float), offsets=np.asarray(offsets, np.int64),
                final_reason=final_reason, symbol=symbol, week=week, tick=float(inputs[(sessions[0], symbol)]['tick']))
    return streams
