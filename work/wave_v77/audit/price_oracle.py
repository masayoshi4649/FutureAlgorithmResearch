"""同時計先頭の価格窓・直前レンジ・OFIを直接区間走査で再構成する。"""

from __future__ import annotations

import numpy as np
from numba import njit

from board_oracle import windows as flow_windows
from sync_oracle import asof_fast


@njit(cache=True, nogil=True)
def price_values(now, old, positions, first, times, bid, ask, mid, broken, tick):
    """機能: 原本品質を直接調べ、時計先頭だけの価格差絶対和とnow抜き高安を計算する。

    引数: 参照行・価格・時計先頭・品質(ndarray)、tick(float)。
    返り値: 価格数値/フラグ/レンジ数値/件数のtuple。累積和・単調dequeは使わない。
    """
    n = len(now)
    numeric = np.full((n, 9), np.nan)
    flags = np.zeros((n, 6), dtype=np.bool_)
    bounds = np.full((n, 8), np.nan)
    counts = np.zeros((n, 2), dtype=np.int32)
    for row in range(n):
        end, begin = now[row], old[row]
        if end < 0 or begin < 0:
            continue
        flags[row, 1] = end == begin
        crossed = False
        for j in range(begin + 1, end + 1):
            crossed |= broken[j]
        flags[row, 2] = crossed
        valid = begin < end and not crossed
        flags[row, 0] = valid
        if not valid:
            continue
        a, b = positions[begin], positions[end]
        variation = 0.
        for j in range(a+1, b+1):
            variation += abs(mid[first[j]] - mid[first[j-1]])
        displacement = mid[end] - mid[begin]
        numeric[row, :7] = (times[end]-times[begin], displacement/mid[begin]*10000.,
            (bid[end]-bid[begin])/tick, (ask[end]-ask[begin])/tick, displacement, variation,
            abs(displacement)/variation if variation > 0 else np.nan)
        flags[row, 3] = variation <= 0
        counts[row, 0] = b-a+1
        high, low = -np.inf, np.inf
        for j in range(a, b):
            high = max(high, mid[first[j]])
            low = min(low, mid[first[j]])
        rvalid = b-a >= 2 and np.isfinite(high) and np.isfinite(low)
        flags[row, 4] = rvalid
        if rvalid:
            width = high-low
            flags[row, 5] = width > 0
            bounds[row] = (high, low, width, (mid[end]-low)/width if width > 0 else np.nan,
                (mid[end]-high)/tick, (mid[end]-low)/tick, times[begin], times[first[b-1]])
            counts[row, 1] = b-a
    return numeric, flags, bounds, counts


def market(grid: np.ndarray, delay: int, ready: dict, book: dict, snap: dict) -> dict:
    """機能: 5価格窓・2直前レンジ・2OFI窓を独立のstrictpast参照へ接続する。

    引数: grid(ndarray)、delay(int)、ready/book/snap(dict)。返り値: 全特徴(dict)。
    """
    times, tick = ready["time_s"], ready["tick"]
    endpoint = book["valid"] & np.isfinite(book["bid"]) & np.isfinite(book["ask"])
    endpoint &= (book["bid"] > 0) & (book["ask"] > book["bid"]) & (book["ask"]-book["bid"] <= 2*tick+1.e-9)
    now, age = asof_fast(grid-delay, times, endpoint, book["reset"], 30.)
    good = now >= 0
    safe = np.maximum(now, 0)
    qvalid = good & snap["valid"][safe]
    current = dict(index=now, age=age, actual_age=age+delay, valid=good, q_valid=qvalid)
    for field in ("mid", "bid", "ask", "last"):
        current[field] = np.full(len(grid), np.nan)
        current[field][good] = book[field][now[good]]
    for field in ("best_imbalance", "depth_imbalance"):
        current[field] = np.full(len(grid), np.nan)
        current[field][qvalid] = snap[field][now[qvalid]]
    current["spread_ticks"] = (current["ask"]-current["bid"])/tick
    first = np.r_[0, np.flatnonzero(np.diff(times) != 0) + 1].astype(np.int64)
    positions = np.repeat(np.arange(len(first)), np.diff(np.r_[first, len(times)]))
    output = dict(current=current, windows={}, ranges={}, flow={})
    broken = ~book["valid"] | book["reset"]
    pf = ("actual_seconds", "ret_bp", "bid_change_ticks", "ask_change_ticks", "displacement", "total_variation", "efficiency")
    rf = ("high", "low", "width", "position", "high_distance_ticks", "low_distance_ticks", "first_time", "last_time")
    for window in (30, 60, 180, 300, 600):
        old, old_age = asof_fast(grid-delay-window, times, endpoint, book["reset"], 30.)
        numbers, flags, bounds, counts = price_values(now, old, positions, first, times, book["bid"], book["ask"], book["mid"], broken, tick)
        w = {f: numbers[:, i] for i, f in enumerate(pf)}
        w.update(old=old, now=now, old_age=old_age, source_valid=flags[:, 0], same_row=flags[:, 1],
            reset_or_invalid_cross=flags[:, 2], zero_variation=flags[:, 3], unique_observations=counts[:, 0])
        output["windows"][window] = w
        if window in (60, 180):
            r = {f: bounds[:, i] for i, f in enumerate(rf)}
            r.update(old=old, now=now, source_valid=flags[:, 4], position_valid=flags[:, 5], unique_observations=counts[:, 1])
            output["ranges"][window] = r
    # ----------------------------------------
    # Fは価格可用性とは別に全深さsnapshot品質を要求し、無活動と欠測を分離する。
    flow_endpoint = endpoint & snap["valid"]
    flow_now, _ = asof_fast(grid-delay, times, flow_endpoint, book["reset"], 30.)
    ff = ("ofi_ratio", "ofi_sum", "ofi_abs_sum", "actual_seconds", "mid_change_bp", "bid_change_ticks", "ask_change_ticks", "best_imbalance_change", "depth_imbalance_change")
    fb = ("source_valid", "valid", "same_row", "reset_or_invalid_cross", "missing_ofi", "zero_ofi_denominator")
    for window in (15, 30):
        old, old_age = asof_fast(grid-delay-window, times, flow_endpoint, book["reset"], 30.)
        numbers, flags, counts = flow_windows(flow_now, old, times, book["bid"], book["ask"], book["mid"],
            broken | ~snap["valid"], book["best_ofi"], snap["best_imbalance"], snap["depth_imbalance"], tick)
        w = {f: numbers[:, i] for i, f in enumerate(ff)}
        w.update({f: flags[:, i] for i, f in enumerate(fb)})
        w.update(old=old, now=flow_now, old_age=old_age, nonzero_ofi_count=counts)
        output["flow"][window] = w
    return output


def compare(actual: dict, expected: dict) -> int:
    """機能: 全現在・窓・レンジ・フローの配列をNaNを含めて照合する。

    引数: actual/expected(dict)。返り値: 比較配列数(int)。
    """
    count = 0
    for group, value in expected.items():
        dictionaries = [(actual[group], value)] if group == "current" else [(actual[group][k], v) for k, v in value.items()]
        for a, e in dictionaries:
            for field, v in e.items():
                if np.asarray(v).dtype.kind in "biu":
                    np.testing.assert_array_equal(a[field], v, err_msg=f"{group}/{field}")
                else:
                    np.testing.assert_allclose(a[field], v, equal_nan=True, rtol=1.e-9, atol=2.e-7, err_msg=f"{group}/{field}")
                count += 1
    return count
