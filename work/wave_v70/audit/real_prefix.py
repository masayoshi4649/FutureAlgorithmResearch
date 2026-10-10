"""実原本の複数玉管理が、切断や未来変更で過去を変えないと確認する。"""

from __future__ import annotations

import hashlib

import numpy as np

from audit_all import read, ROOT, WORK, HERE
from audit_engine import ENGINE, ENGINE_SHA
from independent_account import save


def replay(key: tuple, ready: dict, features: dict, directions: dict, schedules: dict,
    kind: int, cut: int | None = None, modified: int | None = None) -> tuple:
    """機能: 同じ実原本から管理六系の切断又は未来改変を再生する。

    引数: key(tuple)、ready/features/directions/schedules(dict)、kind(int)、
    cut/modified(int|None)。返り値: 注文・部分決済・全玉曲線・終端状態(tuple)。
    """
    row = ready[key]
    arrays = [np.asarray(value).copy() for value in (row["time_s"], features[key]["bid"],
        features[key]["ask"], directions[key][0])]
    schedule = np.asarray(schedules[key][0]).copy()
    if cut is not None:
        arrays = [value[:cut] for value in arrays]
        schedule = schedule[schedule[:, 0] < cut]
    if modified is not None:
        times, bids, asks, signal = arrays
        bids[modified:] = bids[modified] + (500 + np.arange(len(bids) - modified)) * row["tick"]
        asks[modified:] = bids[modified:] + 7 * row["tick"]
        signal[modified:] *= -1
        times[modified:] = times[modified] + np.arange(len(times) - modified) * 60
        schedule = schedule[schedule[:, 0] < modified]
    symbol = key[1]
    return ENGINE.simulate(*arrays, schedule, row["tick"], row["limit"],
        10 if symbol == "TOPIX" else 20, 1000. if symbol == "TOPIX" else 10.,
        41.8 if symbol == "TOPIX" else 11., kind, 48., 8., 8., 3600.,
        4., .25, 2., 2., 64., 8., 8., .5, 8., .25, 10., 8., 2., 0)


def main() -> None:
    """機能: 実原本八口座・六管理系の未来不変性を照合し結果保存する。

    引数: なし。返り値: なし(None)。
    """
    ready = read(ROOT / "work/wave_v69/prepared/inputs.pkl")
    features = read(ROOT / "work/wave_v69/prepared/features.pkl")
    directions = read(WORK / "inputs/signals.pkl")
    schedules = read(WORK / "inputs/schedule.pkl")
    sessions = {"2026-09-21_Day", "2026-09-30_Day", "2026-10-02_Day", "2026-10-08_Night"}
    records = []
    for key in sorted(key for key in ready if key[0] in sessions):
        cuts = sorted({int(len(ready[key]["time_s"]) * fraction) for fraction in (.33, .71)})
        for kind in range(6):
            original = replay(key, ready, features, directions, schedules, kind)
            for cut in cuts:
                for altered in (replay(key, ready, features, directions, schedules, kind, cut=cut),
                    replay(key, ready, features, directions, schedules, kind, modified=cut)):
                    np.testing.assert_array_equal(original[0][original[0][:, 0] < cut], altered[0][altered[0][:, 0] < cut])
                    np.testing.assert_array_equal(original[1][original[1][:, 2] < cut], altered[1][altered[1][:, 2] < cut])
                    np.testing.assert_array_equal(original[2][:cut], altered[2][:cut])
            records.append(dict(セッション=key[0], 銘柄=key[1], 管理kind=kind, 切断行=cuts,
                未来変更="気配・spread・方向信号・時計・将来共通入口", 過去一致=True))
            print(f"実原本因果 {key} kind={kind} 合格", flush=True)
    assert len(records) == 48
    assert hashlib.sha256((WORK / "engine.py").read_bytes()).hexdigest() == ENGINE_SHA
    save(HERE / "実原本因果検査.json", dict(合格=True, 検査数=len(records),
        切断改変組数=len(records) * 2 * 2, 結果=records, engine_SHA256=ENGINE_SHA))


if __name__ == "__main__":
    main()
