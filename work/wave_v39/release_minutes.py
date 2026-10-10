"""公開済み板ブロックを、実際に到達した1分境界へ因果的にまとめる。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def build(ready: dict, frame: pd.DataFrame) -> dict:
    """機能: 未来の公開・同秒後続行を使わず、板ブロックを分単位へ集約する。

    引数: ready (dict) は原本順の価格・公開ATR、frame (DataFrame) は板の公開記録。
    返り値: 原本行、公開時刻、規格化圧力、価格変化、品質等の列 (dict[str, ndarray])。
    対象は素材時刻の完全な1分足ではなく、各決定行までに新たに公開されたブロック。
    """
    times = np.asarray(ready['time_s'], float)
    rawseq = np.asarray(ready['seq'], np.int64)
    assert len(times) == len(rawseq) and np.all(np.diff(times) >= 0)
    assert np.all(np.diff(rawseq) > 0)
    minute = np.floor((times - ready['start']) / 60).astype(np.int64)
    first = np.r_[True, np.diff(minute) > 0]
    indices = np.flatnonzero(first & (minute >= 1))
    n = len(indices)
    decisions = rawseq[indices]
    f = frame.loc[(frame.seq <= rawseq[-1]) & (frame.time_s <= times[-1])].copy()
    releases = f.seq.to_numpy(np.int64)
    assert np.all(np.diff(releases) > 0)
    assert np.all(f.source_last_seq.to_numpy(np.int64) < releases)
    bins = np.searchsorted(decisions, releases, side='left')
    last = np.searchsorted(releases, decisions, side='right') - 1
    counts = np.bincount(bins[bins < n], minlength=n)
    signed = np.bincount(bins[bins < n], weights=f.ofi_signed.to_numpy(float)[bins < n], minlength=n)
    absolute = np.bincount(bins[bins < n], weights=f.ofi_abs.to_numpy(float)[bins < n], minlength=n)
    # ----------------------------------------
    # 可視板の不連続や欠測を、無圧力という観測へ置き換えない。
    block_gap = np.r_[np.inf, np.diff(f.time_s.to_numpy(float))]
    block_ok = (f.valid_event_count.to_numpy(float) > 0)
    block_ok &= f.continuity_reset_count.to_numpy(float) == 0
    block_ok &= block_gap <= 60
    block_ok &= (f.time_s.to_numpy(float)-f.source_time_s.to_numpy(float)) <= 60
    block_ok &= np.isfinite(f.ofi_signed.to_numpy(float)) & np.isfinite(f.ofi_abs.to_numpy(float))
    bad = np.bincount(bins[bins < n], weights=(~block_ok)[bins < n], minlength=n)
    endpoint = last >= 0
    safe = np.maximum(last, 0)
    mid = np.full(n, np.nan)
    depth = np.full(n, np.nan)
    spread = np.full(n, np.nan)
    source = np.full(n, np.nan)
    if len(f):
        mid[endpoint] = f.source_mid_last.to_numpy(float)[safe[endpoint]]
        depth[endpoint] = (f.bid_qty.to_numpy(float)+f.ask_qty.to_numpy(float))[safe[endpoint]]
        spread[endpoint] = f.spread_ticks.to_numpy(float)[safe[endpoint]]
        source[endpoint] = f.source_time_s.to_numpy(float)[safe[endpoint]]
    valid = endpoint & (counts > 0) & (bad == 0)
    valid &= (times[indices]-source >= 0) & (times[indices]-source <= 60)
    valid &= np.isfinite(mid) & (depth > 0) & np.isfinite(spread)
    valid &= np.r_[False, (np.diff(times[indices]) <= 90) & (np.diff(minute[indices]) == 1)] if n else np.empty(0, bool)
    previous_depth = np.r_[np.nan, depth[:-1]]
    flow = signed / np.where(previous_depth > 0, previous_depth, np.nan)
    flow = np.sign(flow) * np.log1p(np.abs(flow))
    atr = np.asarray(ready['atr'], float)[indices]
    change = np.r_[np.nan, np.diff(mid)] / atr
    valid &= np.isfinite(flow) & np.isfinite(change) & np.isfinite(atr) & (atr > 0)
    source_last = np.full(n, -1, np.int64)
    source_last[endpoint] = releases[safe[endpoint]]
    assert np.all(source_last <= decisions)
    return dict(indices=indices, seq=decisions, time_s=times[indices], minute=minute[indices],
        valid=valid, flow=flow, signed=signed, absolute=absolute, change=change,
        spread=spread, atr=atr, depth=depth, mid=mid, source_time_s=source,
        source_seq=source_last, block_count=counts, bad_block_count=bad)


def model_rows(events: dict, lag: int = 3) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """機能: 現在区間の板圧力を、過去区間だけから予測する行列を作る。

    引数: events (dict[str, ndarray])、lag (int) はOFIの過去本数。
    返り値: 過去特徴X、現在板圧力y、連続した有効行mask (tuple[ndarray, ndarray, ndarray])。
    現在区間の価格・スプレッドを説明変数へ入れない。
    """
    assert lag >= 1
    n = len(events['time_s'])
    x = np.full((n, lag+2), np.nan)
    mask = np.asarray(events['valid'], bool).copy()
    for offset in range(1, lag+1):
        x[offset:, offset-1] = events['flow'][:-offset]
        previous = np.zeros(n, bool)
        previous[offset:] = events['valid'][:-offset]
        continuous = np.zeros(n, bool)
        continuous[offset:] = events['minute'][offset:]-events['minute'][:-offset] == offset
        mask &= previous & continuous
    x[1:, lag] = events['change'][:-1]
    x[1:, lag+1] = events['spread'][:-1]
    mask &= np.isfinite(x).all(axis=1)
    return x, np.asarray(events['flow'], float).copy(), mask
