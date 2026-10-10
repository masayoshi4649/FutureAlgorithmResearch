"""公開原本行の10段を直接抽出する。売買や帯の検出は行わない。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def digest(path: Path) -> str:
    """機能: 読取専用資料のSHA256を計算する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1048576):
            result.update(block)
    return result.hexdigest()


def number(value: object) -> float:
    """機能: 有限の数値だけを読み、不明をNaNとして残す。

    引数: value (object)。返り値: 有限値またはNaN (float)。
    """
    if isinstance(value, bool):
        return float('nan')
    try:
        result = float(value)
    except (ValueError, TypeError):
        return float('nan')
    return result if np.isfinite(result) else float('nan')


def read_records(path: Path, seq: np.ndarray, max_rows: int | None = None) -> dict:
    """機能: 指定された公開原本行だけを読み、5段mapを介さず保存する。

    引数: path (Path)、seq (ndarray[int64])、max_rows (int|None) は先頭行数。
    返り値: 原本0始まり行番号から原JSONへの対応 (dict[int, dict])。
    """
    wanted = set(map(int, seq))
    if max_rows is not None:
        wanted = {value for value in wanted if value < max_rows}
    if not wanted:
        return {}
    last = max(wanted)
    records = {}
    with path.open('rb') as stream:
        for index, line in enumerate(stream):
            if index > last:
                break
            if index in wanted:
                records[index] = json.loads(line)
    assert set(records) == wanted, '公開原本行が不足'
    return records


def extract_records(records: dict, ready: dict, frame: pd.DataFrame) -> dict:
    """機能: current公開行の10段と因果的品質を、原本順を保って抽出する。

    引数: records (dict[int, dict])、ready (dict)、frame (DataFrame) は公開記録。
    返り値: 公開seq/time・ready行・価格数量(n,10)・品質列 (dict[str, ndarray])。
    frameのsource_mid_lastや平均板量は使わず、seqで指定した当該原本を使う。
    """
    rawseq = np.asarray(ready['seq'], np.int64)
    times = np.asarray(ready['time_s'], float)
    assert len(rawseq) and len(rawseq) == len(times)
    assert np.all(np.diff(rawseq) > 0) and np.all(np.diff(times) >= 0)
    f = frame.loc[frame.seq <= rawseq[-1]].copy()
    seq = f.seq.to_numpy(np.int64)
    released = f.time_s.to_numpy(float)
    indices = np.searchsorted(rawseq, seq, side='left')
    assert np.all(indices < len(rawseq)) and np.array_equal(rawseq[indices], seq)
    assert np.array_equal(times[indices], released), '原本行と公開時計の不一致'
    assert np.all(np.diff(seq) > 0) and np.all(np.diff(released) > 0)
    assert np.all(f.source_last_seq.to_numpy(np.int64) < seq)
    assert np.all(f.source_time_s.to_numpy(float) < released)
    n = len(seq)
    arrays = {name: np.full((n, 10), np.nan) for name in
              ['bid_prices', 'ask_prices', 'bid_qty', 'ask_qty']}
    for index, source in enumerate(seq):
        raw = records[int(source)]
        stamp = datetime.fromisoformat(raw['CurrentPriceTime'])
        assert stamp.tzinfo is not None and stamp.timestamp() == released[index]
        for side, price_name, qty_name in [('Buy', 'bid_prices', 'bid_qty'),
                                          ('Sell', 'ask_prices', 'ask_qty')]:
            for level in range(1, 11):
                value = raw.get(f'{side}{level}')
                if not isinstance(value, dict):
                    continue
                price, qty = number(value.get('Price')), number(value.get('Qty'))
                if price > 0:
                    arrays[price_name][index, level-1] = price
                    if qty >= 0:
                        arrays[qty_name][index, level-1] = qty
    # ----------------------------------------
    # 価格だけの比較を、数量欠測や10段品質へ依存させない。
    bp, ap, bq, aq = (arrays[k] for k in ['bid_prices', 'ask_prices', 'bid_qty', 'ask_qty'])
    price_valid = np.isfinite(bp[:, 0]) & np.isfinite(ap[:, 0]) & (bp[:, 0] < ap[:, 0])
    best_valid = price_valid & (bq[:, 0] > 0) & (aq[:, 0] > 0)
    complete = np.isfinite(bp).all(axis=1) & np.isfinite(ap).all(axis=1)
    complete &= np.isfinite(bq).all(axis=1) & np.isfinite(aq).all(axis=1)
    duplicate = np.zeros(n, bool)
    for index in range(n):
        for prices in [bp[index], ap[index]]:
            finite = prices[np.isfinite(prices)]
            duplicate[index] |= len(np.unique(finite)) != len(finite)
    ordered = (np.diff(bp, axis=1) < 0).all(axis=1) & (np.diff(ap, axis=1) > 0).all(axis=1)
    crossed = np.isfinite(bp[:, 0]) & np.isfinite(ap[:, 0]) & (bp[:, 0] >= ap[:, 0])
    depth_valid = complete & best_valid & ordered & ~duplicate & ~crossed
    gap = np.r_[np.nan, np.diff(released)] if n else np.empty(0)
    delay = f.block_delay_seconds.to_numpy(float)
    assert np.array_equal(delay, released-f.source_time_s.to_numpy(float))
    continuity = f.continuity_reset_count.to_numpy(float)
    clock_quality = np.isfinite(delay) & (delay > 0) & (delay <= 60)
    clock_quality &= np.isfinite(gap) & (gap > 0) & (gap <= 60)
    quality = clock_quality & (continuity == 0)
    atr = np.asarray(ready['atr'], float)[indices].copy()
    atr_valid = np.isfinite(atr) & (atr > 0)
    # ----------------------------------------
    # 既存特徴のcurrent最良値を別資料として完全照合する。
    for actual, column in [(bp[:, 0], 'bid'), (ap[:, 0], 'ask'),
                           (bq[:, 0], 'bid_qty'), (aq[:, 0], 'ask_qty')]:
        np.testing.assert_array_equal(actual, f[column].to_numpy(float))
    return dict(seq=seq, time_s=released, ready_index=indices.astype(np.int64), atr=atr,
                source_time_s=f.source_time_s.to_numpy(float),
                source_last_seq=f.source_last_seq.to_numpy(np.int64),
                block_delay_seconds=delay, previous_release_gap=gap,
                continuity_reset_count=continuity, price_valid=price_valid,
                best_valid=best_valid, depth_valid=depth_valid, complete=complete,
                duplicate=duplicate, ordered=ordered, crossed=crossed,
                clock_quality=clock_quality, publication_quality=quality, atr_valid=atr_valid,
                valid=depth_valid & quality & atr_valid, **arrays)


def extract(path: Path, ready: dict, frame: pd.DataFrame,
            max_rows: int | None = None) -> dict:
    """機能: 原本公開行を読み、打切り範囲に限定した10段を抽出する。

    引数: path (Path)、ready (dict)、frame (DataFrame)、max_rows (int|None)。
    返り値: extract_recordsと同じ公開列 (dict[str, ndarray])。
    """
    if max_rows is not None:
        count = np.searchsorted(ready['seq'], max_rows, side='left')
        assert count > 0
        ready = {key: value[:count] if isinstance(value, np.ndarray)
                 and len(value) == len(ready['seq']) else value for key, value in ready.items()}
    selected = frame.loc[frame.seq <= ready['seq'][-1], 'seq'].to_numpy(np.int64)
    records = read_records(path, selected, max_rows)
    return extract_records(records, ready, frame)
