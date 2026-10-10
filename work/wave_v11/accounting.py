"""単建玉売買を原気配で再評価し、含み損を含む損益を計算する。"""

from __future__ import annotations

import numpy as np
from numba import njit

import single


@njit(cache=True)
def equity_replay(time, seq, bid, ask, raw, tick, multiplier):
    """機能: 各原気配で全建玉の清算価値を計算する。

    引数: 時刻/行番号/気配/売買 (ndarray)、呼値/倍率 (float)。
    返り値: 毎分と末尾の曲線、全行最大下落等 (tuple[ndarray, ndarray])。
    """
    curve = np.zeros((len(time), 7))
    count, pointer, held = 0, 0, -1
    realized, realized_stress, realized_a, realized_stress_a = 0., 0., 0., 0.
    peak, peak_stress, peak_a, peak_stress_a = 0., 0., 0., 0.
    dd, dd_stress, dd_a, dd_stress_a = 0., 0., 0., 0.
    last_bucket, max_gross, max_notional, minimum = -1., 0., 0., 0.
    for i in range(len(time)):
        if held >= 0 and raw[held, 13] == 1 and i == int(raw[held, 5]):
            r = raw[held]
            realized += r[14] * multiplier
            realized_stress += r[15] * multiplier
            realized_a += r[14] / r[6]
            realized_stress_a += r[15] / r[6]
            held = -1
        if pointer < len(raw) and i == int(raw[pointer, 4]):
            held = pointer
            pointer += 1
        value, stress, value_a, stress_a = realized, realized_stress, realized_a, realized_stress_a
        gross = 0
        if held >= 0:
            r = raw[held]
            quote = bid[i] if r[1] > 0 else ask[i]
            points = r[1] * (quote - r[7]) - 2 * tick
            value += points * multiplier
            stress += (points - 2 * tick) * multiplier
            value_a += points / r[6]
            stress_a += (points - 2 * tick) / r[6]
            gross = 1
            max_notional = max(max_notional, quote * multiplier)
        max_gross = max(max_gross, gross)
        minimum = min(minimum, value)
        peak, peak_stress = max(peak, value), max(peak_stress, stress)
        peak_a, peak_stress_a = max(peak_a, value_a), max(peak_stress_a, stress_a)
        dd, dd_stress = max(dd, peak-value), max(dd_stress, peak_stress-stress)
        dd_a, dd_stress_a = max(dd_a, peak_a-value_a), max(dd_stress_a, peak_stress_a-stress_a)
        bucket = np.floor(time[i] / 60)
        if bucket != last_bucket or i == len(time)-1:
            curve[count] = np.array([time[i], seq[i], value, stress, value_a, stress_a, gross])
            count += 1
            last_bucket = bucket
    return curve[:count], np.array([dd, dd_stress, dd_a, dd_stress_a, max_gross, max_notional, minimum])


def summarize(prepared: dict, config: dict, raw: np.ndarray | None = None,
              delay: str = '次行') -> tuple[dict, np.ndarray]:
    """機能: 確定収支と未返済評価を分け、全原気配の含み損込み下落を付加する。

    引数: prepared/config (dict)、raw (ndarray|None)、delay (str)。
    返り値: 日本語集計と毎分曲線 (tuple[dict, ndarray])。
    """
    if raw is None:
        raw = single.simulate_array(prepared, config, delay)
    result = single.summary(prepared, config, delay, raw)
    curve, diagnostics = equity_replay(*(prepared[k] for k in ('time_s', 'seq', 'bid', 'ask')),
                                       raw, prepared['tick'], single.MULTIPLIERS[prepared['symbol']])
    closed = raw[raw[:, 13] == 1]
    result.update(思想=config['philosophy'], 実行器='単建玉', 設定最大枚数=1,
                  最大保有枚数=int(diagnostics[4]), 最大総建玉金額円=float(diagnostics[5]),
                  全行最大下落円=float(diagnostics[0]), 費用倍全行最大下落円=float(diagnostics[1]),
                  全行最大下落ATR=float(diagnostics[2]), 費用倍全行最大下落ATR=float(diagnostics[3]),
                  最低清算価値円=float(diagnostics[6]), ATR収支=float((closed[:, 14]/closed[:, 6]).sum()),
                  負け数=int((closed[:, 14] < 0).sum()), 引分数=int((closed[:, 14] == 0).sum()),
                  枚数上限換算収支円=result['収支円'], 枚数上限換算費用倍収支円=result['費用倍収支円'],
                  枚数上限換算評価円=result['評価損益円'])
    return result, curve
