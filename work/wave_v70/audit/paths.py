"""複数玉管理の監査専用に、価格の人工経路を定義する。"""

from __future__ import annotations

import numpy as np


def cases() -> dict[str, dict]:
    """機能: 停滞・急落・往復・gap・無効気配・同秒の経路を返す。

    引数: なし。返り値: 日本語ケース名と原本配列の辞書(dict[str,dict])。
    """
    specs = {
        "一方向上昇": np.concatenate((np.full(5, 100.), np.linspace(100., 140., 41), np.full(20, 140.))),
        "一方向下落": np.concatenate((np.full(5, 100.), np.linspace(100., 60., 41), np.full(20, 60.))),
        "急落後回復": np.concatenate((np.full(5, 100.), np.linspace(100., 75., 26), np.linspace(75., 120., 46), np.full(20, 120.))),
        "同幅往復": np.concatenate((np.full(5, 100.), np.tile(np.array([100., 98., 96., 94., 96., 98., 100., 102., 100.]), 8))),
        "微細往復": np.concatenate((np.full(5, 100.), np.tile(np.array([100., 99., 100., 101.]), 15))),
        "価格跳躍": np.concatenate((np.full(5, 100.), np.array([100., 80., 78., 77., 82., 110., 115., 110., 100., 120.]), np.full(30, 120.))),
        "完全停滞": np.full(60, 100.),
    }
    result = {}
    for name, path in specs.items():
        bid = np.concatenate((path, np.full(4, path[-1])))
        ask = bid + 1.
        times = 300. + np.arange(len(bid), dtype=float)
        times[-4:] = [940., 941., 942., 943.]
        signal = np.zeros(len(bid), dtype=np.int8)
        signal[0] = 1
        result[name] = dict(bid=bid, ask=ask, time_s=times, seq=np.arange(len(bid)),
            reset=np.zeros(len(bid), dtype=bool), signal=signal)

    # ----------------------------------------
    # 突発変動直後の無効気配と、時計が同じまま進む原本を追加する。
    invalid = {name: value.copy() for name, value in result["価格跳躍"].items()}
    invalid["bid"][8:10] = np.nan
    invalid["ask"][8:10] = np.nan
    result["無効気配中断"] = invalid
    same_second = {name: value.copy() for name, value in result["急落後回復"].items()}
    same_second["time_s"][:-4] = 300.
    result["同秒原本更新"] = same_second
    return result


def reflect(data: dict, ceiling: float = 300.) -> dict:
    """機能: 買い・売りを反射し、対称な気配と方向信号を生成する。

    引数: data(dict)、ceiling(float)。返り値: 売買反射後の配列辞書(dict)。
    """
    other = {name: value.copy() for name, value in data.items()}
    other["bid"] = ceiling - data["ask"]
    other["ask"] = ceiling - data["bid"]
    other["signal"] = -data["signal"]
    return other
