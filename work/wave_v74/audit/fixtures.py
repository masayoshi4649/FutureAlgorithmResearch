"""新しい方向限定と待機・収束の監査用価格経路を生成する。"""

from __future__ import annotations

import numpy as np


def path(mid: np.ndarray, seconds: float = 10., opening: float = 100., previous: float = 100.) -> dict:
    """機能: 人工中値から気配と観測順を作り、末尾に返済可能な観測を残す。

    引数: mid(np.ndarray)、seconds/opening/previous(float)。
    返り値: time_s/seq/bid/ask/mid/valid/resetと参照価格(dict)。
    """
    mid = np.asarray(mid, dtype=float)
    n = len(mid)
    assert n >= 4
    times = seconds * np.arange(n, dtype=float)
    return dict(time_s=times, seq=np.arange(n, dtype=np.int64) + 701,
        mid=mid.copy(), bid=mid - .5, ask=mid + .5, valid=np.ones(n, dtype=bool),
        reset=np.zeros(n, dtype=bool), opening=float(opening), previous=float(previous), tick=1.,
        limit=float(times[-2] + 60.))


def cases() -> dict[str, dict]:
    """機能: 符号、急変、連続損失、収束、同秒、無効気配の人工経路を作る。

    引数: なし。返り値: 名前から人工入力への辞書(dict[str,dict])。
    """
    result = {
        "基準上の一方向上昇": path(np.r_[np.full(4, 100.), np.arange(101., 137.), np.full(8, 136.)]),
        "基準下の一方向下落": path(np.r_[np.full(4, 100.), np.arange(99., 63., -1.), np.full(8, 64.)]),
        "基準線の往復": path(np.r_[np.full(4, 100.), np.tile([102., 104., 101., 98., 96., 99.], 12), np.full(8, 100.)]),
        "追跡開始後に急反転": path(np.r_[np.full(4, 100.), np.arange(101., 113.), [90., 87., 86.], np.full(8, 86.)]),
        "無変化": path(np.full(48, 100.)),
        "連続損切り候補": path(np.r_[np.full(4, 100.), np.tile([104., 106., 103., 86., 84., 97., 96., 99., 118., 121., 106., 100.], 12), np.full(8, 100.)]),
        "長い逆行から収束して再開": path(np.r_[np.full(4, 100.), np.arange(103., 81., -1.), np.tile([82., 83., 82.5, 83.5], 18), np.arange(84., 113.), np.full(8, 112.)]),
        "始値と前終値の符号不一致": path(np.r_[np.full(4, 100.), np.arange(99., 93., -1.), np.full(8, 94.)], previous=90.),
        "前終値なし": path(np.r_[np.full(4, 100.), np.arange(101., 115.), np.full(8, 114.)], previous=np.nan),
    }
    missing = path(np.r_[np.full(4, 100.), np.arange(101., 116.), np.full(8, 115.)])
    missing["bid"][6:10] = np.nan
    missing["ask"][6:10] = np.nan
    missing["valid"][6:10] = False
    missing["reset"][10] = True
    result["無効気配中断から復帰"] = missing
    same = path(np.r_[np.full(4, 100.), np.arange(101., 115.), np.arange(114., 100., -1.), np.full(8, 100.)])
    same["time_s"][:22] = 0.
    result["同秒原本更新"] = same
    return result


def reflect(data: dict) -> dict:
    """機能: 同じ観測順で価格を反射し、ロングとショートの対称性を調べる。

    引数: data(dict)。返り値: 気配と参照価格を反射した新辞書(dict)。
    """
    pivot = data["opening"]
    result = {name: value.copy() if isinstance(value, np.ndarray) else value for name, value in data.items()}
    result["bid"] = 2 * pivot - data["ask"]
    result["ask"] = 2 * pivot - data["bid"]
    result["mid"] = 2 * pivot - data["mid"]
    result["previous"] = 2 * pivot - data["previous"]
    return result


def prefix(data: dict, cut: int) -> dict:
    """機能: 観測配列だけを切り、元のセッション返済時刻を維持する。

    引数: data(dict)、cut(int)。返り値: 切断した新辞書(dict)。
    """
    return {name: value[:cut].copy() if isinstance(value, np.ndarray) else value for name, value in data.items()}
