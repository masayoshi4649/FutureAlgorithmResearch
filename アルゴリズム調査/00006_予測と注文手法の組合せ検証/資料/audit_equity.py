"""独立した全取引走査で、含み損込みの単建玉資産曲線と最大下落を監査する。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

import accounting
from audit_single import config, fixture
import single

OUT = Path(__file__).resolve().parent


def independent(ready: dict, raw: np.ndarray) -> tuple[np.ndarray, dict]:
    """機能: 各気配について全取引を独立に見直し、清算価値と下落を計算する。

    引数: ready (dict) は準備済み気配、raw (ndarray) は単建玉売買行列。
    返り値: tuple[ndarray, dict]。全行曲線と下落・最大保有・最小清算価値。
    """
    rows = []
    tick, multiplier = ready["tick"], single.MULTIPLIERS[ready["symbol"]]
    for index in range(len(ready["seq"])):
        value, stress, atr_value, atr_stress, gross = 0., 0., 0., 0., 0
        for trade in raw:
            if int(trade[4]) > index:
                continue
            if trade[13] == 1 and int(trade[5]) <= index:
                quote = trade[8]
            else:
                quote = ready["bid"][index] if trade[1] > 0 else ready["ask"][index]
                gross += 1
            points = trade[1] * (quote - trade[7]) - 2 * tick
            value += points * multiplier
            stress += (points - 2 * tick) * multiplier
            atr_value += points / trade[6]
            atr_stress += (points - 2 * tick) / trade[6]
        rows.append([ready["time_s"][index], ready["seq"][index], value, stress, atr_value, atr_stress, gross])
    array = np.array(rows)
    dd = []
    for column in range(2, 6):
        maximum, worst = 0., 0.
        for value in array[:, column]:
            maximum = max(maximum, value)
            worst = max(worst, maximum - value)
        dd.append(worst)
    return array, dict(下落=dd, 最大保有=int(array[:, 6].max()), 最低清算価値=float(min(0., array[:, 2].min())))


def main() -> None:
    """機能: 勝ち取引・負け取引・未返済を混ぜ、全行と毎分の会計を照合する。

    引数: なし。
    返り値: None。独立した資産曲線監査の JSON を保存する。
    """
    ready = fixture([990, 1000, 1100, 1040, 1050, 1060, 970, 980, 990, 1000])
    first = ready["families"]["監査"]["rows"][0]
    records = []
    for index, side in [(0, 1), (4, -1), (8, 1)]:
        records.append(dict(first, event_id=f"監査_{index}", seq=index + 1, source_last_seq=index,
                            time_s=float(ready["time_s"][index]), side=side))
    ready["families"]["監査"] = dict(rows=records, indices=np.array([0, 4, 8]), sides=np.array([1, -1, 1]),
                                      times=ready["time_s"][[0, 4, 8]], deadlines=ready["time_s"][[0, 4, 8]] + 600)
    condition = config(holding_min=.01, philosophy="予測主導")
    raw = single.simulate_array(ready, condition)
    expected, stats = independent(ready, raw)
    curve, observed = accounting.equity_replay(*(ready[key] for key in ("time_s", "seq", "bid", "ask")),
                                              raw, ready["tick"], 1000.)
    assert len(raw) == 3 and int(raw[:, 13].sum()) == 2
    assert np.allclose(curve, expected[curve[:, 1].astype(int) - 1])
    assert np.allclose(observed[:4], stats["下落"])
    assert observed[4] == stats["最大保有"] == 1
    assert observed[6] == stats["最低清算価値"] == -30000.
    assert np.allclose(expected[-1, 2:6], [30000., -30000., .3, -.3])
    assert np.allclose(observed[:4], [90000., 110000., .9, 1.1])
    summary, _ = accounting.summarize(ready, condition, raw)
    assert summary["収支円"] == 60000. and summary["評価損益円"] == -30000.
    assert summary["未返済数"] == 1 and summary["全行最大下落円"] == 90000.
    single.save(OUT / "含み損込み資産曲線の独立監査.json", dict(
        実装SHA256={name: hashlib.sha256((OUT / name).read_bytes()).hexdigest() for name in ["single.py", "accounting.py"]},
        確定２件未返済１件の手計算一致=True, 全行数=len(expected), 毎分と末尾行数=len(curve),
        費用２呼値清算価値円=30000., 費用４呼値清算価値円=-30000.,
        費用２呼値最大下落円=90000., 費用４呼値最大下落円=110000.,
        確定収支円=60000., 未返済評価円=-30000., 全行の独立曲線=expected, 集計=summary))
    print("確定２件と未返済１件を含む全行資産曲線・両費用の下落が手計算と一致しました。", flush=True)


if __name__ == "__main__":
    main()
