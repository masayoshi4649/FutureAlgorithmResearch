"""二銘柄同期・片側停止・市場矛盾の人工経路を作成する。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime

import numpy as np


START = datetime.fromisoformat("2026-10-09T08:45:00+09:00").timestamp()
SCALES = {"TOPIX": (4000., .5), "NK225": (65000., 10.)}


def market(symbol: str, sign: int = 1, seconds: float = 5., offset: float = 0., empty: bool = False) -> dict:
    """機能: 同じ因果的方向を商品別の呼値尺度で表した単一銘柄経路を作る。

    引数: symbol(str)、sign(int)、seconds/offset(float)、empty(bool)。
    返り値: ready/featuresに接続可能な観測辞書(dict)。
    """
    base, tick = SCALES[symbol]
    times = np.arange(START + offset, START + 3900., seconds, dtype=float)
    if empty:
        times = np.array([], dtype=float)
    step = np.round((times - START) / 30.)
    mid = base + sign * step * tick
    return dict(symbol=symbol, time_s=times, seq=np.arange(len(times), dtype=np.int64) * (3 if symbol == "TOPIX" else 7) + (101 if symbol == "TOPIX" else 9001),
        mid=mid, last=mid.copy(), bid=mid - tick / 2., ask=mid + tick / 2.,
        valid=np.ones(len(times), dtype=bool), reset=np.zeros(len(times), dtype=bool),
        ofi=np.full(len(times), .4 * sign), best_ofi=np.full(len(times), .4 * sign), imbalance=np.full(len(times), .3 * sign),
        tick=tick, start=START, limit=START + 3600., opening=base)


def paired_cases() -> dict[str, dict]:
    """機能: 二市場の方向・鮮度・時計・場境界に関する人工事例を作る。

    引数: なし。返り値: 名前から二市場辞書への対応(dict)。
    """
    baseline = {symbol: market(symbol) for symbol in SCALES}
    result = {
        "両方上昇": baseline,
        "両方下落": {symbol: market(symbol, -1) for symbol in SCALES},
        "方向矛盾": {"TOPIX": market("TOPIX", -1), "NK225": market("NK225", 1)},
        "片方の更新間隔が長い": {"TOPIX": market("TOPIX", seconds=19.), "NK225": market("NK225", seconds=7., offset=3.)},
        "片市場全欠測": {"TOPIX": market("TOPIX", empty=True), "NK225": market("NK225")},
        "全空": {symbol: market(symbol, empty=True) for symbol in SCALES},
    }
    stopped = deepcopy(baseline)
    for name, value in stopped["TOPIX"].items():
        if isinstance(value, np.ndarray):
            stopped["TOPIX"][name] = value[:280].copy()
    result["片方停止"] = stopped
    invalid = deepcopy(baseline)
    invalid["TOPIX"]["valid"][150:300] = False
    invalid["TOPIX"]["reset"][300] = True
    invalid["TOPIX"]["bid"][150:300] = np.nan
    invalid["TOPIX"]["ask"][150:300] = np.nan
    result["片方無効気配から復帰"] = invalid
    same_clock = deepcopy(baseline)
    for symbol in SCALES:
        same_clock[symbol]["time_s"] = START + np.floor((same_clock[symbol]["time_s"] - START) / 15.) * 15.
    result["同時計の原本複数行"] = same_clock
    midnight = deepcopy(baseline)
    new_start = datetime.fromisoformat("2026-10-09T23:45:00+09:00").timestamp()
    for data in midnight.values():
        data["time_s"] += new_start - START
        data["start"], data["limit"] = new_start, new_start + 3600.
    result["日跨ぎ夜間時計"] = midnight
    prior_session = deepcopy(baseline)
    prior_session["TOPIX"]["time_s"] -= 24 * 3600.
    prior_session["TOPIX"]["start"] -= 24 * 3600.
    prior_session["TOPIX"]["limit"] -= 24 * 3600.
    result["片側だけ前日データ"] = prior_session
    flat = deepcopy(baseline)
    for data in flat.values():
        for name in ("mid", "last"):
            data[name][:] = data["opening"]
        data["bid"][:] = data["opening"] - data["tick"] / 2.
        data["ask"][:] = data["opening"] + data["tick"] / 2.
        data["ofi"][:] = 0.
        data["best_ofi"][:] = 0.
        data["imbalance"][:] = 0.
    result["双方静止"] = flat
    return result


def one_side_future(data: dict, symbol: str, cutoff: float) -> dict:
    """機能: 一方だけcutoff以後の価格・板・品質を極端に変更する。

    引数: data(dict)、symbol(str)、cutoff(float)。返り値: 改変した二市場辞書(dict)。
    """
    output = deepcopy(data)
    changed = output[symbol]
    mask = changed["time_s"] >= cutoff
    for name in ("mid", "last", "bid", "ask"):
        changed[name][mask] *= .8
    changed["ofi"][mask] = -.95
    changed["best_ofi"][mask] = -.95
    changed["imbalance"][mask] = -.95
    changed["valid"][mask] = False
    changed["reset"][mask] = True
    return output


def cut_one_side(data: dict, symbol: str, cutoff: float) -> dict:
    """機能: 一方の観測だけを時計で切り、元の場時刻と他方を維持する。

    引数: data(dict)、symbol(str)、cutoff(float)。返り値: 切断した二市場辞書(dict)。
    """
    output = deepcopy(data)
    own = output[symbol]
    mask = own["time_s"] < cutoff
    for name, value in own.items():
        if isinstance(value, np.ndarray):
            own[name] = value[mask].copy()
    return output


def swap(data: dict) -> dict:
    """機能: 二市場の役割を交換し、別の銘柄seq値に依存しない対称性を検査する。

    引数: data(dict)。返り値: 銘柄辞書の交換結果(dict)。
    価格を同一単位にしたモデル用写像は確定APIで別に接続する。
    """
    return {"TOPIX": deepcopy(data["NK225"]), "NK225": deepcopy(data["TOPIX"])}
