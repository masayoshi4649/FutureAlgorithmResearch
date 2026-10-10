"""新即時板・短期窓を、独立の式と原本区間逐次集計で検査する。"""

from __future__ import annotations

import hashlib
import importlib.util
import math
import os
from pathlib import Path
import sys

import numba
import numpy as np
from numba import njit

from independent_account import save
from sync_oracle import asof_fast


HERE = Path(__file__).resolve().parent
os.environ.setdefault("NUMBA_CACHE_DIR", str(HERE / "cache"))
numba.config.CACHE_DIR = str(HERE / "cache")
FIELDS = ("best_imbalance", "microprice", "micro_offset_ticks", "weighted_bid_qty", "weighted_ask_qty",
    "depth_imbalance", "bid_weighted_distance", "ask_weighted_distance")


def snapshot(raw: dict, tick: float) -> dict:
    """機能: 20個の表示板を配列化し、八つの即時特徴を別の式で算出する。

    引数: raw(dict)、tick(float)。返り値: 特徴とvalid(dict)。原本一行以外を参照しない。
    """
    missing = {f: math.nan for f in FIELDS} | {"valid": False}
    if not math.isfinite(tick) or tick <= 0:
        return missing
    try:
        prices = np.array([[float(raw[f"{side}{i}"]["Price"]) for i in range(1, 11)] for side in ("Buy", "Sell")])
        sizes = np.array([[float(raw[f"{side}{i}"]["Qty"]) for i in range(1, 11)] for side in ("Buy", "Sell")])
    except (KeyError, TypeError, ValueError):
        return missing
    if not np.isfinite(prices).all() or not np.isfinite(sizes).all() or (prices <= 0).any() or (sizes < 0).any():
        return missing
    if not (np.diff(prices[0]) < 0).all() or not (np.diff(prices[1]) > 0).all():
        return missing
    if sizes[0, 0] <= 0 or sizes[1, 0] <= 0 or prices[0, 0] >= prices[1, 0]:
        return missing
    distances = np.abs(prices - prices[:, :1]) / tick
    weighted = sizes / (1. + distances)
    totals = weighted.sum(axis=1)
    centers = (weighted * distances).sum(axis=1) / totals
    imbalance = (sizes[0, 0] - sizes[1, 0]) / sizes[:, 0].sum()
    middle, spread = prices[:, 0].mean(), prices[1, 0] - prices[0, 0]
    return dict(best_imbalance=float(imbalance), microprice=float(middle + imbalance * spread / 2.),
        micro_offset_ticks=float(imbalance * spread / (2. * tick)),
        weighted_bid_qty=float(totals[0]), weighted_ask_qty=float(totals[1]),
        depth_imbalance=float((totals[0] - totals[1]) / totals.sum()),
        bid_weighted_distance=float(centers[0]), ask_weighted_distance=float(centers[1]), valid=True)


@njit(cache=True)
def windows(now, old, times, bid, ask, mid, broken, ofi, best, depth, tick):
    """機能: 各窓の原本区間を直接走査し、累積和を使わずOFIと品質を集計する。

    引数: 参照行・原本特徴(ndarray)、tick(float)。返り値: 数値十列、フラグ六列、イベント数(tuple)。
    """
    n = len(now)
    values = np.full((n, 10), np.nan)
    flags = np.zeros((n, 6), dtype=np.bool_)
    counts = np.zeros(n, dtype=np.int32)
    for row in range(n):
        end, begin = now[row], old[row]
        if end < 0 or begin < 0:
            continue
        flags[row, 2] = end == begin
        cross = False
        for i in range(begin + 1, end + 1):
            cross |= broken[i]
        flags[row, 3] = cross
        source_valid = begin < end and not cross
        flags[row, 0] = source_valid
        if not source_valid:
            continue
        total = absolute = 0.
        missing = False
        count = 0
        for i in range(begin + 1, end + 1):
            if not np.isfinite(ofi[i]):
                missing = True
            else:
                total += ofi[i]
                absolute += abs(ofi[i])
                count += int(ofi[i] != 0.)
        flags[row, 4], flags[row, 5] = missing, absolute <= 0.
        valid = not missing and absolute > 0.
        flags[row, 1] = valid
        counts[row] = count
        if valid:
            values[row, 0] = total / absolute
        values[row, 1:4] = total, absolute, times[end] - times[begin]
        values[row, 4] = 10000. * (mid[end] / mid[begin] - 1.)
        values[row, 5] = (bid[end] - bid[begin]) / tick
        values[row, 6] = (ask[end] - ask[begin]) / tick
        values[row, 7] = best[end] - best[begin]
        values[row, 8] = depth[end] - depth[begin]
    return values, flags, counts


def market(grid: np.ndarray, delay: int, ready: dict, book: dict, snap: dict, max_age: float = 30.) -> dict:
    """機能: 厳密過去の同時計先頭参照と、四短期窓を独立に再構成する。

    引数: grid(ndarray)、delay(int)、ready/book/snap(dict)、max_age(float)。返り値: 特徴辞書(dict)。
    """
    times, tick = ready["time_s"], ready["tick"]
    quality = np.asarray(book["valid"] & snap["valid"] & np.isfinite(book["bid"]) & np.isfinite(book["ask"])
        & (book["bid"] > 0) & (book["ask"] > book["bid"]) & (book["ask"] - book["bid"] <= 2 * tick + 1.e-9))
    now, age = asof_fast(grid - delay, times, quality, book["reset"], max_age)
    good = now >= 0
    current = dict(index=now, age=age, actual_age=age + delay, valid=good)
    for field in FIELDS:
        current[field] = np.full(len(grid), np.nan)
        current[field][good] = snap[field][now[good]]
    current["spread_ticks"] = np.full(len(grid), np.nan)
    current["spread_ticks"][good] = (book["ask"][now[good]] - book["bid"][now[good]]) / tick
    output = dict(current=current, windows={})
    broken = ~book["valid"] | book["reset"] | ~snap["valid"]
    floats = ("ofi_ratio", "ofi_sum", "ofi_abs_sum", "actual_seconds", "mid_change_bp", "bid_change_ticks",
        "ask_change_ticks", "best_imbalance_change", "depth_imbalance_change")
    bools = ("source_valid", "valid", "same_row", "reset_or_invalid_cross", "missing_ofi", "zero_ofi_denominator")
    for window in (5, 15, 30, 60):
        old, old_age = asof_fast(grid - delay - window, times, quality, book["reset"], max_age)
        values, flags, count = windows(now, old, times, book["bid"], book["ask"], book["mid"], broken,
            book["best_ofi"], snap["best_imbalance"], snap["depth_imbalance"], tick)
        w = {field: values[:, i] for i, field in enumerate(floats)}
        w.update({field: flags[:, i] for i, field in enumerate(bools)})
        w.update(now=now, old=old, old_age=old_age, nonzero_ofi_count=count)
        output["windows"][window] = w
    return output


def compare(got: dict, expected: dict) -> int:
    """機能: current/windowsの参照行、欠測フラグ、数値を全点照合する。

    引数: got/expected(dict)。返り値: 比較した配列数(int)。
    """
    checks = 0
    for group, values in [("current", expected["current"])] + [(w, d) for w, d in expected["windows"].items()]:
        actual = got["current"] if group == "current" else got["windows"][group]
        for field, value in values.items():
            if np.asarray(value).dtype.kind in "biu":
                np.testing.assert_array_equal(actual[field], value, err_msg=f"{group}/{field}")
            else:
                np.testing.assert_allclose(actual[field], value, atol=2.e-7, rtol=1.e-9,
                    equal_nan=True, err_msg=f"{group}/{field}")
            checks += 1
    return checks


def digest(path: Path) -> str:
    """機能: 大きな入力を小さい塊で内容指紋化する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()
