"""板の強方向・弱支持・持続確認・新規イベントを独立に判定する。"""

from __future__ import annotations

from bisect import bisect_left

import numpy as np


def single(definition: dict, market: dict) -> tuple:
    """機能: 一市場の強方向と弱い支持を、観測可能と証拠十分を分けて算定する。

    引数: definition/market(dict)。返り値: 強方向・弱支持・有効・参照行(tuple)。
    """
    c, kind, threshold = market["current"], definition["kind"], definition["threshold"]
    strong = np.zeros(len(c["valid"]), dtype=np.int8)
    weak, valid = strong.copy(), c["valid"].copy()
    w = market["windows"].get(definition["window"])
    for row in range(len(strong)):
        if kind in ("Q", "D"):
            x = c["best_imbalance" if kind == "Q" else "depth_imbalance"][row]
            valid[row] &= np.isfinite(x)
            if valid[row]:
                strong[row] = int(np.sign(x)) if abs(x) >= threshold else 0
                weak[row] = int(np.sign(x)) if abs(x) >= threshold / 2. else 0
        elif kind == "P":
            valid[row] &= w["source_valid"][row]
            if valid[row]:
                bid, ask = w["bid_change_ticks"][row], w["ask_change_ticks"][row]
                strong[row] = 1 if min(bid, ask) >= 1. - 1.e-8 else -1 if max(bid, ask) <= -1. + 1.e-8 else 0
                weak[row] = int(np.sign(w["mid_change_bp"][row]))
        else:
            valid[row] &= w["source_valid"][row] and not w["missing_ofi"][row]
            evidence = w["valid"][row] and w["nonzero_ofi_count"][row] >= 3
            if valid[row] and evidence:
                x = w["ofi_ratio"][row]
                sign = int(np.sign(x))
                depth = c["depth_imbalance"][row]
                if abs(x) >= threshold and (kind != "FD" or sign * depth >= threshold):
                    strong[row] = sign
                if abs(x) >= threshold / 2. and (kind != "FD" or sign * depth >= threshold / 2.):
                    weak[row] = sign
    return strong, weak, valid, c["index"]


def confirmation(grid: np.ndarray, condition: np.ndarray, valid: np.ndarray,
        source_a: np.ndarray, source_b: np.ndarray, seconds: float) -> np.ndarray:
    """機能: 有効条件の連続区間を配列境界から作り、秒数と双方更新を判定する。

    引数: grid/condition/valid/source_a/source_b(ndarray)、seconds(float)。返り値: 成立(bool ndarray)。
    根拠の開始行を全区間に伝播させる方式であり、被検査器の逐次状態ループを流用しない。
    """
    eligible = condition & valid
    if seconds == 0:
        return eligible.copy()
    if not len(grid):
        return np.zeros(0, bool)
    discontinuity = np.r_[True, np.diff(grid) > 5. + 1.e-8]
    starts = eligible & (discontinuity | np.r_[True, ~eligible[:-1]])
    start_indices = np.maximum.accumulate(np.where(starts, np.arange(len(grid)), -1))
    out = np.zeros(len(grid), bool)
    good = eligible & (start_indices >= 0)
    rows = np.flatnonzero(good)
    origin = start_indices[good]
    out[rows] = ((grid[rows] - grid[origin] >= seconds) & (source_a[rows] > source_a[origin])
        & (source_b[rows] > source_b[origin]))
    return out


def pulses(grid: np.ndarray, strong: np.ndarray, valid: np.ndarray, confirmed: np.ndarray) -> np.ndarray:
    """機能: 合意なしの10秒再準備・反対成立・60秒発火間隔を独立追跡する。

    引数: grid/strong/valid/confirmed(ndarray)。返り値: 新規イベント(int8 ndarray)。
    """
    out = np.zeros(len(grid), dtype=np.int8)
    emitted, began, fired = 0, None, None
    for row, stamp in enumerate(grid):
        if row and stamp - grid[row - 1] > 5. + 1.e-8:
            began = None
        if not valid[row]:
            began = None
            continue
        if strong[row] == 0:
            if began is None:
                began = float(stamp)
            if stamp - began >= 10.:
                emitted = 0
        else:
            began = None
        direction = int(confirmed[row])
        if direction and direction != emitted and (fired is None or stamp - fired >= 60.):
            out[row], emitted, fired = direction, direction, float(stamp)
    return out


def joint(definition: dict, session: dict) -> dict:
    """機能: 両市場一致・不一致・支持・確認・発火を全て独立に算定する。

    引数: definition/session(dict)。返り値: 共同証拠辞書(dict)。
    """
    grid = session["grid"]
    a, wa, va, sa = single(definition, session["markets"]["TOPIX"])
    b, wb, vb, sb = single(definition, session["markets"]["NK225"])
    valid = va & vb
    strong = np.zeros(len(grid), np.int8)
    equal = valid & (a == b)
    strong[equal] = a[equal]
    long, short = valid & (wa == 1) & (wb == 1), valid & (wa == -1) & (wb == -1)
    out = dict(grid=grid, strong=strong, valid=valid, own_strong=a, peer_strong=b, own_weak=wa, peer_weak=wb,
        source_top=sa, source_nk=sb, disagreement=valid & (a * b == -1), support_long=long,
        support_short=short, entry={}, management={})
    for seconds in (0, 10):
        yes = confirmation(grid, strong == 1, valid, sa, sb, float(seconds))
        no = confirmation(grid, strong == -1, valid, sa, sb, float(seconds))
        direction = yes.astype(np.int8) - no.astype(np.int8)
        out["entry"][seconds] = pulses(grid, strong, valid, direction)
    for seconds in (15, 30):
        out["management"][seconds] = {
            "loss_long": confirmation(grid, ~long, valid, sa, sb, float(seconds)),
            "loss_short": confirmation(grid, ~short, valid, sa, sb, float(seconds)),
            "opposite_long": confirmation(grid, strong == -1, valid, sa, sb, float(seconds)),
            "opposite_short": confirmation(grid, strong == 1, valid, sa, sb, float(seconds))}
    return out


def mapping(grid: np.ndarray, times: np.ndarray) -> np.ndarray:
    """機能: 共同格子以後の最初行を標準二分探索で取り、同じ行は最新格子へ置換する。

    引数: grid/times(ndarray)。返り値: 格子番号(int32 ndarray)。
    """
    out = np.full(len(times), -1, dtype=np.int32)
    rows = times.tolist()
    for g, stamp in enumerate(grid):
        position = bisect_left(rows, float(stamp))
        if position < len(rows) and rows[position] - stamp <= 10.:
            out[position] = g
    return out


def compare(got: dict, expected: dict) -> int:
    """機能: 共同状態と入場・途中確認の全配列を比較する。

    引数: got/expected(dict)。返り値: 照合配列数(int)。
    """
    count = 0
    for field, values in expected.items():
        if field == "entry":
            for seconds, array in values.items():
                np.testing.assert_array_equal(got[field][seconds], array, err_msg=f"{field}/{seconds}")
                count += 1
        elif field == "management":
            for seconds, arrays in values.items():
                for name, array in arrays.items():
                    np.testing.assert_array_equal(got[field][seconds][name], array, err_msg=f"{field}/{seconds}/{name}")
                    count += 1
        else:
            np.testing.assert_array_equal(got[field], values, err_msg=field)
            count += 1
    return count
