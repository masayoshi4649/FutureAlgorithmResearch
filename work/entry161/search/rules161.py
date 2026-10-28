"""当時の特徴だけから、固定24入口と二つの単純学習対照の方向を計算する。"""

from __future__ import annotations

import math
import numpy as np


FAMILIES = (
    ("M", "即時の勢い", "直近5秒と15秒が同方向に進み、往復ばかりではない"),
    ("A", "加速", "5秒の進行速度が15秒平均を上回り、既に逆向きの流れではない"),
    ("P", "押し戻し後の再開", "2分の方向に対して一度押した後、5秒の動きが元方向へ戻る"),
    ("R", "失速後の反転", "1分の下落又は上昇に逆らう15秒・5秒の反転を確認する"),
    ("B", "板圧力と価格受容", "方向側の距離加重数量と注文増減が優位で、価格も逆行していない"),
    ("S", "補充と吸収の代理", "逆向きの注文増減でも価格が崩れず、方向側の数量補充と反発が見える"),
    ("L", "二市場の先行一致", "TOPIXが先に動き、日経が遅れて同じ方向へ動き始める"),
    ("C", "圧縮後の放出", "直前の狭い値幅から直近1分の高安を抜け、値幅が拡大する"),
)


def candidates():
    """事前固定した手動24条件と学習10条件を列挙する。

    引数: なし。返り値: list[dict]。値幅目標100/50は変更しない。
    """
    result = []
    for family, name, description in FAMILIES:
        for level in range(3):
            result.append(dict(id=f"{family}{level+1:02d}", family=family, name=name,
                               description=description, level=level, kind="manual"))
    for family, name in (("GL", "L2ロジット"), ("DT", "深さ2の分類木")):
        for level, threshold in enumerate((0.4, 0.5, 0.6, 0.7, 0.8), 1):
            result.append(dict(id=f"{family}{level:02d}", family=family, name=name,
                               kind="learned", threshold=threshold))
    return result


def manual_signal(features, candidate, side):
    """固定入口の成立を各観測行で計算する。

    引数: features(dict[str,ndarray])、candidate(dict)、side(int:買1/売−1)。
    返り値: ndarray[bool]。NaNを含む必須比較は不成立とし未来列を参照しない。
    """
    f, level, family = features, candidate["level"], candidate["family"]
    signed = lambda key: side * f[key]
    r5, r15, r60 = signed("ret5_pt"), signed("ret15_pt"), signed("ret60_pt")
    valid = np.isfinite(f["spread"]) & (f["spread"] > 0) & (f["spread"] <= 20)
    if family == "M":
        signal = (r5 >= (10, 20, 30)[level]) & (r15 >= (20, 30, 40)[level]) & (f["er60"] >= (.20, .35, .50)[level])
    elif family == "A":
        acceleration = side * (f["vel5_pt_s"] - f["vel15_pt_s"])
        signal = (r5 >= (10, 20, 30)[level]) & (acceleration >= (1, 2, 3)[level]) & (r15 >= 0) & (r60 >= 0) & (signed("ofi5") >= 0)
    elif family == "P":
        signal = (signed("ret120_pt") >= (40, 60, 80)[level]) & (signed("ret5_lag5_pt") <= -(10, 20, 30)[level]) & (r5 >= (10, 20, 30)[level]) & (r15 <= 10)
    elif family == "R":
        signal = (r60 <= -(40, 60, 80)[level]) & (r15 >= 0) & (r5 >= (10, 20, 30)[level]) & (signed("ofi5") >= 0)
    elif family == "B":
        position = f["pos60"] if side == 1 else 1 - f["pos60"]
        signal = (signed("depth_imb") >= (.20, .35, .50)[level]) & (signed("ofi15") >= (.10, .20, .35)[level]) & (r15 >= (0, 10, 20)[level]) & (position >= .60)
    elif family == "S":
        refill = f["bid_refill15"] if side == 1 else f["ask_refill15"]
        signal = (signed("ofi15") <= -(.10, .20, .35)[level]) & (r15 >= -(10, 10, 20)[level]) & (r5 >= (10, 20, 20)[level]) & (refill >= (.20, .40, .60)[level])
    elif family == "L":
        peer = signed("peer_ret60_bp")
        own = r60 / f["mid"] * 10000
        signal = (peer >= (1, 2, 3)[level]) & (own <= .5 * peer) & (r60 >= -10) & (r5 >= (0, 10, 20)[level]) & (f["peer_age_s"] <= (5, 5, 3)[level])
    elif family == "C":
        breakout = f["mid"] - f["high60_prev"] if side == 1 else f["low60_prev"] - f["mid"]
        signal = (f["range60_previous_pt"] <= (80, 60, 40)[level]) & (f["range60_pt"] >= 1.2 * f["range60_previous_pt"]) & (r15 >= (20, 30, 40)[level]) & (breakout >= (0, 10, 10)[level]) & (signed("ofi5") >= 0)
    else:
        raise ValueError(f"未定義の入口: {family}")
    return valid & signal


DIRECTIONAL = ("ret5_pt", "ret15_pt", "ret60_pt", "ret120_pt", "ret300_pt", "ret5_lag5_pt", "accel5_15_pt_s", "ofi5", "ofi15", "depth_imb", "imb1", "microprice_offset_pt", "peer_ret15_bp", "peer_ret60_bp")
UNDIRECTED = ("spread", "range60_pt", "range60_previous_pt", "er60", "peer_age_s")


def model_matrix(features, side):
    """買売対称の学習入力を作る。

    引数: features(dict[str,ndarray])、side(int)。返り値: ndarray[float64]。
    方向列は符号を反転し、価格水準や曜日・日付・未来列を入力しない。
    """
    columns = [side * features[name] for name in DIRECTIONAL]
    columns += [features[name] for name in UNDIRECTED]
    columns += [side * (features["pos60"] - .5)]
    columns += [features["bid_refill15"] - features["ask_refill15"] if side == 1 else features["ask_refill15"] - features["bid_refill15"]]
    return np.column_stack(columns)


def fit_preprocess(matrix):
    """学習行だけから欠測補完値と標準化値を固定する。

    引数: matrix(ndarray)。返り値: dict。全欠測列は中央値0・標準偏差1とする。
    """
    medians = []
    for column in matrix.T:
        finite = column[np.isfinite(column)]
        medians.append(float(np.median(finite)) if len(finite) else 0.0)
    filled = np.where(np.isfinite(matrix), matrix, np.asarray(medians))
    means, std = filled.mean(axis=0), filled.std(axis=0)
    std[std < 1e-9] = 1.0
    return dict(median=medians, mean=means.tolist(), std=std.tolist())


def transform(matrix, preprocess):
    """固定済みの変換で補完・標準化し、欠測指示を追加する。

    引数: matrix(ndarray)、preprocess(dict)。返り値: ndarray。
    """
    missing = ~np.isfinite(matrix)
    filled = np.where(missing, np.asarray(preprocess["median"]), matrix)
    z = (filled - np.asarray(preprocess["mean"])) / np.asarray(preprocess["std"])
    return np.column_stack((np.clip(z, -8, 8), missing.astype(float)))


def fit_logit(matrix, labels, weights):
    """固定L2罰則のロジットをニュートン法で学習する。

    引数: matrix(ndarray)、labels(ndarray:0/1)、weights(ndarray)。返り値: dict。
    罰則1、最大20反復、切片無罰則。係数探索の途中にvalidationを使わない。
    """
    x = np.column_stack((np.ones(len(matrix)), matrix))
    coefficient = np.zeros(x.shape[1])
    penalty = np.ones(x.shape[1]); penalty[0] = 0
    w = weights / weights.mean()
    for _ in range(20):
        probability = 1 / (1 + np.exp(-np.clip(x @ coefficient, -35, 35)))
        gradient = x.T @ (w * (probability - labels)) + penalty * coefficient
        curvature = w * np.maximum(probability * (1 - probability), 1e-8)
        hessian = (x.T * curvature) @ x + np.diag(penalty + 1e-8)
        change = np.linalg.solve(hessian, gradient)
        coefficient -= np.clip(change, -5, 5)
        if np.max(np.abs(change)) < 1e-7:
            break
    return dict(kind="GL", coefficient=coefficient.tolist())


def fit_tree(matrix, labels, weights, depth=0):
    """深さ2・葉20件以上の分類木を固定分位候補で学習する。

    引数: matrix/labels/weights(ndarray)、depth(int)。返り値: dict。
    分割点はtrainの10〜90百分位だけ。利益幅やvalidationは参照しない。
    """
    mass = float(weights.sum())
    probability = float(np.dot(weights, labels) / mass)
    node = dict(kind="DT", probability=probability, count=len(labels))
    if depth >= 2 or len(labels) < 40 or probability in (0, 1):
        return node
    base = mass * probability * (1 - probability)
    best = None
    for column in range(matrix.shape[1]):
        for threshold in np.unique(np.quantile(matrix[:, column], np.arange(.1, 1, .1))):
            left = matrix[:, column] <= threshold
            if left.sum() < 20 or (~left).sum() < 20:
                continue
            lm, rm = weights[left].sum(), weights[~left].sum()
            lp, rp = np.dot(weights[left], labels[left]) / lm, np.dot(weights[~left], labels[~left]) / rm
            gain = base - lm * lp * (1 - lp) - rm * rp * (1 - rp)
            if gain > 1e-12 and (best is None or gain > best[0] + 1e-12):
                best = (float(gain), column, float(threshold), left)
    if best is not None:
        _, column, threshold, left = best
        node.update(column=column, threshold=threshold,
                    left=fit_tree(matrix[left], labels[left], weights[left], depth+1),
                    right=fit_tree(matrix[~left], labels[~left], weights[~left], depth+1))
    return node


def predict(matrix, model):
    """固定済みモデルから確率形式のスコアを計算する。

    引数: matrix(ndarray)、model(dict)。返り値: ndarray[float64]。
    未見の確率校正を保証せず、実イベントの成功率と別に表示する。
    """
    if model["kind"] == "GL":
        c = np.asarray(model["coefficient"])
        return 1 / (1 + np.exp(-np.clip(c[0] + matrix @ c[1:], -35, 35)))
    if "column" not in model:
        return np.full(len(matrix), model["probability"])
    left = matrix[:, model["column"]] <= model["threshold"]
    result = np.empty(len(matrix))
    result[left] = predict(matrix[left], model["left"])
    result[~left] = predict(matrix[~left], model["right"])
    return result
