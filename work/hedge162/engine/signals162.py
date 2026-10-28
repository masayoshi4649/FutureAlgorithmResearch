"""00161で固定された当時特徴から全観測の条件を作る。先着ラベルを読まない。"""
import numpy as np

from source161_rules import candidates, manual_signal, model_matrix, transform, predict

EXPECTED = {"Day":"R02","preUS":"GL01","postUS":"GL02"}


def make_signals(features: dict, frozen: dict) -> tuple[np.ndarray, np.ndarray]:
    """保存特徴と固定学習モデルから、保有に依存しない元の条件真偽を返す。

    引数: features/frozen(dict)。返り値: tuple[ndarray,ndarray]は買/売の全観測条件。
    原164件等の採用イベントを入力せず、間隔・保有・予約は状態器で評価する。
    """
    if frozen["selected"] != EXPECTED:
        raise ValueError("00161で固定した3候補と異なる")
    names = [str(x) for x in features["feature_names"]]
    data = {name:features["features"][:,i] for i,name in enumerate(names)}
    result = [np.zeros(len(features["time"]),dtype=bool) for _ in range(2)]
    catalog = {c["id"]:c for c in candidates()}
    for phase_number,phase in enumerate(("Day","preUS","postUS")):
        mask = features["phase"] == phase_number
        if not mask.any():
            continue
        candidate = catalog[EXPECTED[phase]]
        if candidate["kind"] == "manual":
            signals = [manual_signal(data,candidate,s) for s in (1,-1)]
        else:
            matrix = model_matrix(data,1)
            valid = ((data["spread"] > 0) & (data["spread"] <= 20) & np.isfinite(data["ret15_pt"])
                     & np.isfinite(data["ret60_pt"]) & (np.isfinite(matrix).sum(axis=1) >= 12))
            trained = frozen["models"][phase]
            signals = [(predict(transform(model_matrix(data,s),trained["preprocess"]),trained[candidate["family"]]) >= candidate["threshold"]) & valid for s in (1,-1)]
        for column in (0,1):
            result[column][mask] = signals[column][mask]
    return tuple(result)
