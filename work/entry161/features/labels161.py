"""特徴と分離した100円順行/50円逆行の将来ラベルだけを作る。"""
from __future__ import annotations

import numpy as np


class BarrierTree:
    """価格の範囲極値から最初の障壁到達原行を探索する木。"""

    def __init__(self, values: np.ndarray, valid: np.ndarray, maximum: bool):
        """有限有効値だけで範囲木を構築する。

        引数: values/valid(ndarray)、maximum(bool)。返り値: None。
        """
        self.length, self.maximum = len(values), maximum
        self.size = 1 << max(0, (len(values)-1).bit_length())
        fill = -np.inf if maximum else np.inf
        self.tree = np.full(self.size*2, fill)
        self.tree[self.size:self.size+len(values)] = np.where(valid, values, fill)
        operation = np.maximum if maximum else np.minimum
        width = self.size//2
        while width:
            self.tree[width:width*2] = operation(self.tree[width*2:width*4:2], self.tree[width*2+1:width*4:2])
            width //= 2

    def first(self, start: int, threshold: float) -> int:
        """start以降で最初に閾値以上又は以下となる原行を返す。

        引数: start(int)、threshold(float)。返り値: int、未到達は-1。
        """
        stack = [(1, 0, self.size)]
        while stack:
            node, left, right = stack.pop()
            if right <= start or left >= self.length:
                continue
            extreme = self.tree[node]
            if extreme < threshold if self.maximum else extreme > threshold:
                continue
            if right-left == 1:
                return left
            middle = (left+right)//2
            stack.append((node*2+1, middle, right))
            stack.append((node*2, left, middle))
        return -1


def make_labels(market: dict, observation_indices: np.ndarray, scene: dict | None = None) -> dict:
    """判断後の次正常板を起点に両方向・二価格定義の先着を作る。

    引数: market(dict)、observation_indices(ndarray)、scene(dict|None)は場時計。
    返り値: dictはNPZ向け配列。経路品質は将来側情報であり、特徴値へ混ぜない。
    """
    observations = observation_indices
    count = len(observations)
    normal = np.flatnonzero(market["valid"])
    after = np.searchsorted(normal, observations, side="right")
    eligible = after < len(normal)
    entries = np.full(count, -1, dtype=np.int64)
    entries[eligible] = normal[after[eligible]]
    times = np.full(count, np.nan)
    times[eligible] = market["time"][entries[eligible]]
    prices = np.full((count, 2), np.nan)
    prices[eligible, 0] = market["ask"][entries[eligible]]
    prices[eligible, 1] = market["bid"][entries[eligible]]
    bad_prefix = np.r_[0, np.cumsum(~market["valid"])]
    gap_prefix = np.r_[0, np.cumsum(np.r_[False, np.diff(market["time"]) > 15])]
    long_gap_prefix = np.r_[0, np.cumsum(np.r_[False, np.diff(market["time"]) > 60])]
    skipped = np.full(count, -1, dtype=np.int64)
    skipped[eligible] = bad_prefix[entries[eligible]]-bad_prefix[observations[eligible]+1]
    cross_phase = np.zeros(count, dtype=bool)
    if scene is not None and scene["kind"] == "Night":
        cross_phase[eligible] = ((market["time"][observations[eligible]] < scene["us_open"])
                                 != (times[eligible] < scene["us_open"]))
    output = {"decision_index": observations.copy(), "decision_time": market["time"][observations], "entry_index": entries,
              "entry_time": times, "entry_price": prices, "entry_price_clock_gap_s": times-market["time"][observations],
              "entry_skipped_bad_bbo": skipped, "entry_cross_phase": cross_phase,
              "entry_gap_gt60": (times-market["time"][observations]) > 60,
              "side": np.asarray([1, -1], dtype=np.int8), "last_normal_index": np.int64(normal[-1]), "last_normal_time": market["time"][normal[-1]]}
    for definition in ("primary", "last"):
        valid = market["valid"] if definition == "primary" else np.ones(len(market["time"]), dtype=bool)
        fields = ("bid", "ask") if definition == "primary" else ("last", "last")
        trees = {(field, maximum): BarrierTree(market[field], valid, maximum) for field in set(fields) for maximum in (False, True)}
        first_up = np.full((count, 2), -1, dtype=np.int64)
        first_down = np.full((count, 2), -1, dtype=np.int64)
        resolution = np.full((count, 2), -1, dtype=np.int64)
        status = np.full((count, 2), -2, dtype=np.int8)
        for row in np.flatnonzero(eligible):
            at = entries[row]
            for side_index, side in enumerate((1, -1)):
                field = fields[side_index]
                base = prices[row, side_index] if definition == "primary" else market["last"][at]
                up = trees[(field, side > 0)].first(at, base+side*100)
                down = trees[(field, side < 0)].first(at, base-side*50)
                first_up[row, side_index], first_down[row, side_index] = up, down
                if up == -1 and down == -1:
                    status[row, side_index] = 0
                elif up != -1 and (down == -1 or up < down):
                    status[row, side_index], resolution[row, side_index] = 1, up
                else:
                    status[row, side_index], resolution[row, side_index] = -1, down
        for name, indices in (("first_up", first_up), ("first_down", first_down), ("resolution", resolution)):
            clock = np.full((count, 2), np.nan)
            has = indices >= 0
            clock[has] = market["time"][indices[has]]
            if name == "resolution":
                clock[~has] = market["time"][-1] if definition == "last" else market["time"][normal[-1]]
            output[f"{definition}_{name}_index"], output[f"{definition}_{name}_time"] = indices, clock
        output[f"{definition}_status"] = status
        # ----------------------------------------
        # 判断後の品質はラベル領域だけへ保存し、成功例だけを捨てる選別に使わない。
        stop = np.where(resolution >= 0, resolution, len(market["time"])-1 if definition == "last" else normal[-1])
        bad = np.full((count, 2), -1, dtype=np.int64)
        gaps = np.zeros((count, 2), dtype=np.int64)
        long_gaps = np.zeros((count, 2), dtype=np.int64)
        bad[eligible] = bad_prefix[stop[eligible]+1]-bad_prefix[entries[eligible, None]]
        gaps[eligible] = gap_prefix[stop[eligible]+1]-gap_prefix[entries[eligible, None]+1]
        long_gaps[eligible] = long_gap_prefix[stop[eligible]+1]-long_gap_prefix[entries[eligible, None]+1]
        output[f"{definition}_path_bad_bbo"] = bad
        output[f"{definition}_path_gap_count"] = gaps
        output[f"{definition}_path_gap"] = gaps > 0
        output[f"{definition}_path_gap_gt60"] = long_gaps > 0
        path_cross = np.zeros((count, 2), dtype=bool)
        if scene is not None and scene["kind"] == "Night":
            path_cross[eligible] = ((market["time"][entries[eligible, None]] < scene["us_open"])
                                     != (market["time"][stop[eligible]] < scene["us_open"]))
        output[f"{definition}_path_cross_phase"] = path_cross
    output["path_bad_bbo"] = output["primary_path_bad_bbo"].copy()
    output["path_gap"] = output["primary_path_gap"].copy()
    output["path_gap_gt60"] = output["primary_path_gap_gt60"].copy()
    return output
