"""controllerの返済条件を独立な純Pythonで監視する人工経路の参照器。"""

from __future__ import annotations

from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent


def first_child_decision(time_s: np.ndarray, bid: np.ndarray, ask: np.ndarray,
    valid: np.ndarray, entry_row: int, side: int, reference: float,
    stop_width: float, activation_width: float, trail_width: float,
    holding_seconds: float, end_time: float) -> tuple[int, int]:
    """機能: 子作成後の次行から独立に損切り・トレール・期限を監視する。

    引数: time_s/bid/ask/valid(np.ndarray)、entry_row/side(int)、referenceと各幅(float)、
    holding_seconds/end_time(float)。返り値: 最初の発注判断行と理由(tuple[int,int])。
    理由は1当初損切り、2利益トレール、3保有期限、4セッション期限、0成立なし。
    """
    armed = False
    extreme = 0.0
    for row in range(entry_row+1, len(time_s)-1):
        if time_s[row] >= end_time:
            return row, 4
        if time_s[row] >= time_s[entry_row]+holding_seconds:
            return row, 3
        if not valid[row]:
            continue
        current = bid[row] if side > 0 else ask[row]
        if stop_width > 0 and side*(current-reference) <= -stop_width:
            return row, 1
        if not armed:
            if activation_width <= 0 or side*(current-reference) >= activation_width:
                armed = True
                extreme = current
        elif side*(current-extreme) > 0:
            extreme = current
        if armed and side*(current-extreme) <= -trail_width:
            return row, 2
    return -1, 0


def following_fill(valid: np.ndarray, decision_row: int) -> int:
    """機能: 発注判断後の最初の有効気配行だけを約定に使う。

    引数: valid(np.ndarray)、decision_row(int)。返り値: 約定行または未約定の-1(int)。
    """
    if decision_row < 0:
        return -1
    for row in range(decision_row+1, len(valid)):
        if valid[row]:
            return row
    return -1


def self_test() -> None:
    """機能: 子の次行監視・開始幅境界・OCO優先・無効気配遅延を確認する。

    引数: なし。返り値: なし(None)。
    """
    times = np.arange(9, dtype=float)
    valid = np.ones(9, dtype=bool)
    # ----------------------------------------
    # 約定行での価格急落は子作成前として監視せず、次行の戻りを使う。
    bids = np.array([100., 80., 100., 103.9, 104., 108., 104., 99., 99.])
    asks = bids+1
    decision, reason = first_child_decision(times, bids, asks, valid, 1, 1, 100., 8., 4., 4., 60., 100.)
    assert (decision, reason) == (6, 2)
    assert following_fill(valid, decision) == 7
    # ----------------------------------------
    # 損切り成立が利益トレールとの同時成立に先行し、次行を約定に使う。
    falling = np.array([100., 100., 104., 108., 91., 89., 87., 85., 84.])
    decision, reason = first_child_decision(times, falling, falling+1, valid, 1, 1, 100., 8., 4., 4., 60., 100.)
    assert (decision, reason) == (4, 1)
    assert following_fill(valid, decision) == 5
    # ----------------------------------------
    # 買い／売りの気配を反射すると同じ行で同じ理由となる。
    center = 300.
    reflected_bid, reflected_ask = center-asks, center-bids
    other = first_child_decision(times, reflected_bid, reflected_ask, valid, 1, -1, center-100., 8., 4., 4., 60., 100.)
    assert other == (6, 2)
    # ----------------------------------------
    # 判断は成立後固定し、次の有効原本行までのみ約定を遅延する。
    delayed = valid.copy()
    delayed[5:7] = False
    assert following_fill(delayed, 4) == 7
    assert following_fill(delayed, 8) == -1
    # ----------------------------------------
    # 返済子の監視は原本順で行い、同秒を一つの将来高安に集約しない。
    same_second = np.zeros(9)
    assert first_child_decision(same_second, bids, asks, valid, 1, 1, 100., 8., 4., 4., 60., 100.) == (6, 2)


if __name__ == "__main__":
    self_test()
