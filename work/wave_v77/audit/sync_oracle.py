"""二市場の代理時計同期を逐次検索で独立確認するための参照器。"""

from __future__ import annotations

from bisect import bisect_left
import numpy as np


def asof(targets: np.ndarray, times: np.ndarray, valid: np.ndarray, reset: np.ndarray, max_age: float = 10.) -> tuple[np.ndarray, np.ndarray]:
    """機能: cutoff厳密以前の最新時計を選び、同時計の最初の原本行だけ採用する。

    引数: targets/times(np.ndarray[float])、valid/reset(np.ndarray[bool])、max_age(float)。
    返り値: 参照行と古さ(tuple[np.ndarray,np.ndarray])。不成立は行-1、古さNaN。
    原本順は単一銘柄内だけで使用し、異なる銘柄のseqを比較しない。
    """
    times = np.asarray(times, dtype=float)
    targets = np.asarray(targets, dtype=float)
    assert times.ndim == targets.ndim == 1 and len(times) == len(valid) == len(reset)
    assert np.all(np.isfinite(times)) and np.all(np.diff(times) >= 0)
    result = np.full(len(targets), -1, dtype=np.int64)
    ages = np.full(len(targets), np.nan, dtype=float)
    for row, cutoff in enumerate(targets):
        eligible = np.flatnonzero(times < cutoff)
        if not len(eligible):
            continue
        stamp = times[eligible[-1]]
        first = int(np.flatnonzero(times == stamp)[0])
        age = float(cutoff - stamp)
        if age <= max_age and valid[first] and not reset[first]:
            result[row], ages[row] = first, age
    return result, ages


def asof_fast(targets: np.ndarray, times: np.ndarray, valid: np.ndarray, reset: np.ndarray, max_age: float = 10.) -> tuple[np.ndarray, np.ndarray]:
    """機能: 独立に時計群を作り、Python標準二分探索で参照器の検査を高速化する。

    引数: targets/times(np.ndarray[float])、valid/reset(np.ndarray[bool])、max_age(float)。
    返り値: 参照行と古さ(tuple[np.ndarray,np.ndarray])。被検査器のsearchsortedを使わない。
    """
    result = np.full(len(targets), -1, dtype=np.int64)
    ages = np.full(len(targets), np.nan, dtype=float)
    if not len(times):
        return result, ages
    assert np.all(np.isfinite(times)) and np.all(np.diff(times) >= 0)
    first_rows = np.r_[0, np.flatnonzero(np.diff(times) != 0) + 1]
    stamps = times[first_rows].tolist()
    for index, cutoff in enumerate(targets):
        if not np.isfinite(cutoff):
            continue
        position = bisect_left(stamps, float(cutoff)) - 1
        if position < 0:
            continue
        source = int(first_rows[position])
        age = float(cutoff - stamps[position])
        if age <= max_age and valid[source] and not reset[source]:
            result[index], ages[index] = source, age
    return result, ages


def fixed_grid(start: float, limit: float, seconds: float = 15.) -> np.ndarray:
    """機能: 保存配列末尾に依存せず、既知のセッション時刻から判断時計を生成する。

    引数: start/limit/seconds(float)。返り値: 判断時計(np.ndarray[float])。
    """
    assert seconds > 0 and limit > start
    return np.arange(start, limit, seconds, dtype=float)


def after_grid(grid: np.ndarray, own_times: np.ndarray) -> np.ndarray:
    """機能: 共同判断時計を各銘柄のその時点以降の最初の原本行へ写す。

    引数: grid/own_times(np.ndarray[float])。返り値: 判断行、末尾以降は-1(np.ndarray[int64])。
    この行が発注判断行なら、約定はさらに次の有効原本行で行う。
    """
    indices = np.searchsorted(own_times, grid, side="left")
    return np.where(indices < len(own_times), indices, -1).astype(np.int64)
