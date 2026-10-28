"""保存初回支持と同じ元S01初回玉の成績を対応し、時系列校正を検査する。"""

from pathlib import Path
import hashlib
import json
import math
import sys
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SEED = 159
BINS = [0, .1, .25, .5, .75, 1]
MODELS = {
    "P0": ["core", "addon"],
    "P1": ["core", "addon", "score", "own_known", "peer_known", "ofi_known"],
    "P2": ["core", "addon", "M", "T", "own_known", "peer_known", "ofi_known"],
    "P3": ["core", "addon", "M", "T", "change", "agreement", "own_known", "peer_known", "ofi_known"],
}
CONTINUOUS = {"score", "M", "T", "change"}


def read(path: Path) -> dict:
    """JSONを読み取る。

    引数: path(Path)はUTF-8ファイル。返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: object) -> None:
    """有限の集計結果をJSONへ保存する。

    引数: path(Path)、value(object)はJSON互換値。返り値: None。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def interval(values: np.ndarray) -> list[float] | None:
    """再標本化列の95%区間を返す。

    引数: values(np.ndarray)は数値列。返り値: list[float]又はNone。
    """
    values = values[np.isfinite(values)]
    return np.quantile(values, [.025, .975]).tolist() if len(values) else None


def ranks(values: np.ndarray) -> np.ndarray:
    """同順位を平均化して順位を返す。

    引数: values(np.ndarray)は数値列。返り値: np.ndarrayは平均順位。
    """
    unique, inv, count = np.unique(values, return_inverse=True, return_counts=True)
    del unique
    starts = np.cumsum(count) - count
    return (starts + (count + 1) / 2)[inv]


def rho(x: np.ndarray, y: np.ndarray) -> float | None:
    """Spearman順位相関を算出する。

    引数: x/y(np.ndarray)は等長列。返り値: float又はNone。
    """
    if len(x) < 3:
        return None
    a, b = ranks(x), ranks(y)
    a, b = a - a.mean(), b - b.mean()
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(a @ b / denominator) if denominator > 0 else None


def make_rows() -> tuple[list[dict], list[dict]]:
    """元支持と初回玉の原行・数量・会計を照合する。

    引数: なし。返り値: tupleは対応済み親と元ファイル指紋。
    """
    manifest = read(HERE / "保存入力と可用項目159.json")
    for item in manifest["入力"]:
        path = ROOT / item["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"], path
    source = read(ROOT / manifest["入力"][0]["path"])
    cases, rows = {}, []
    for row in source["complete_parents"]:
        session = row["session"]
        if session not in cases:
            cases[session] = read(ROOT / "work/s01_156/audit/cases" / session / "S01.json")
        case = cases[session]
        parent = next(p for p in case["parents"] if f'{p["owner"]}/{p["campaign"]}' == row["parent"])
        lots = [lot for lot in case["lots"] if lot["parent"] == row["parent"]]
        first_index = min(lot["decision_index"] for lot in lots)
        initial = [lot for lot in lots if lot["decision_index"] == first_index]
        assert first_index == row["index"] == parent["first_decision_index"]
        assert len(initial) == 1, "保存模型は初回全量一括約定。複数IDは別定義が必要"
        lot = initial[0]
        assert lot["quantity"] * 10 == row["baseline_initial_micro"]
        assert sum(l["net"] for l in lots) == parent["net"] == row["baseline_net"]
        assert lot["remaining"] == 0 and row["baseline_finished"]
        support, side = row["support"], parent["side"]
        known = bool(row["known"])
        features = {
            "core": float(row["owner"] == "core"), "addon": float(row["owner"] == "addon"),
            "score": row["score"], "M": support["M"] if known else None,
            "T": support["T"] if known else None,
            "change": side * (support["Own5"] / 5 - support["Own15"] / 15) if known else None,
            "agreement": float(side * support["Own120"] > 0 and side * support["Own15"] > 0) if known else None,
            "own_known": float(known), "peer_known": float(row["coverage"]["PeerKnown"]),
            "ofi_known": float(row["coverage"]["OFIKnown"]),
        }
        rows.append({
            "session": session, "parent": row["parent"], "owner": row["owner"], "side": side,
            "decision_index": row["index"], "decision_time": row["time"],
            "initial_id": lot["id"], "entry_time": lot["entry_time"],
            "exit_time": max(c["time"] for c in lot["closes"]), "initial_qty_mini": lot["quantity"],
            "initial_net": lot["net"], "initial_pt": lot["net"] / lot["quantity"] / 100,
            "win": int(lot["net"] > 0), "flat": int(lot["net"] == 0),
            "mfe": lot["best_points"], "mae": lot["worst_points"],
            "mfe_time": lot["best_at"], "mae_time": lot["worst_at"],
            "parent_net": parent["net"], "parent_pt_initial": row["points_per_initial_micro"],
            "parent_pt_all": row["points_per_all_new_micro"],
            "score": row["score"], "known": known, "support": support, "features": features,
        })
    assert len(rows) == 155 and len(cases) == 26
    assert sum(r["parent_net"] for r in rows) == 1935000
    return rows, manifest["入力"]


def describe(rows: list[dict], sessions: list[str], bootstrap: np.ndarray) -> dict:
    """同一区分の単位成績と場単位再標本化区間を求める。

    引数: rows(list[dict])、sessions(list[str])、bootstrap(np.ndarray)は場抽出回数。
    返り値: dictは件数、平均、中央値、勝率と区間。
    """
    result = {"parents": len(rows), "sessions": len({r["session"] for r in rows})}
    if not rows:
        return result
    day_index = {d: i for i, d in enumerate(sessions)}
    ids = np.array([day_index[r["session"]] for r in rows])
    weight = bootstrap[:, ids]
    totals = weight.sum(axis=1)
    valid = totals > 0
    result.update(wins=sum(r["win"] for r in rows), flat=sum(r["flat"] for r in rows))
    result["losses"] = len(rows) - result["wins"] - result["flat"]
    for key in ["win", "initial_pt", "mfe", "mae", "parent_pt_initial", "parent_pt_all"]:
        values = np.array([r[key] for r in rows], float)
        means = (weight[valid] @ values) / totals[valid]
        order = np.argsort(values)
        cumulative = np.cumsum(weight[valid][:, order], axis=1)
        lower = ((totals[valid] - 1) // 2 + 1)[:, None]
        upper = (totals[valid] // 2 + 1)[:, None]
        medians = (values[order][(cumulative >= lower).argmax(axis=1)] +
                   values[order][(cumulative >= upper).argmax(axis=1)]) / 2
        result[key] = {"mean": float(values.mean()), "median": float(np.median(values)),
                       "cluster_mean_95": interval(means), "cluster_median_95": interval(medians)}
    return result


def describe_groups(rows: list[dict]) -> dict:
    """事前固定の支持帯・担当・売買・日付分割を比較する。

    引数: rows(list[dict])は全親。返り値: dictは記述比較と相関。
    """
    sessions = sorted({r["session"] for r in rows})
    rng = np.random.default_rng(SEED)
    samples = rng.multinomial(len(sessions), np.full(len(sessions), 1 / len(sessions)), size=5000)
    middle = len(sessions) // 2
    selectors = {"全体": rows, "買い": [r for r in rows if r["side"] == 1],
                 "売り": [r for r in rows if r["side"] == -1],
                 f"前{middle}場": [r for r in rows if r["session"] in sessions[:middle]],
                 f"後{len(sessions)-middle}場": [r for r in rows if r["session"] in sessions[middle:]]}
    for owner in ["core", "addon", "episode"]:
        selectors[owner] = [r for r in rows if r["owner"] == owner]
        for side, label in [(1, "買い"), (-1, "売り")]:
            selectors[owner + "/" + label] = [r for r in rows if r["owner"] == owner and r["side"] == side]
    result = {}
    for label, selected in selectors.items():
        known = [r for r in selected if r["known"]]
        group = {"all": describe(selected, sessions, samples),
                 "unknown": describe([r for r in selected if not r["known"]], sessions, samples), "bins": []}
        for i, (lo, hi) in enumerate(zip(BINS, BINS[1:])):
            subset = [r for r in known if r["score"] >= lo and (r["score"] < hi or i == 4)]
            group["bins"].append({"lower": lo, "upper": hi, **describe(subset, sessions, samples)})
        group["correlations"] = {}
        group["highest_minus_lowest"] = {}
        for key in ["win", "initial_pt", "mfe", "mae"]:
            parts = [[r for r in known if r["score"] < .1], [r for r in known if r["score"] >= .75]]
            if not all(parts):
                group["highest_minus_lowest"][key] = None
                continue
            draws, actual = [], []
            for part in parts:
                w = samples[:, [sessions.index(r["session"]) for r in part]]
                count = w.sum(axis=1)
                v = np.array([r[key] for r in part], float)
                draws.append(np.divide(w @ v, count, out=np.full(len(samples), np.nan), where=count > 0))
                actual.append(float(v.mean()))
            group["highest_minus_lowest"][key] = {"difference": actual[1]-actual[0], "cluster_95": interval(draws[1]-draws[0])}
        for key in ["win", "initial_pt", "mfe", "mae"]:
            x, y = np.array([r["score"] for r in known]), np.array([r[key] for r in known])
            estimates = []
            day_rows = [[i for i, r in enumerate(known) if r["session"] == d] for d in sessions]
            for repeat in samples:
                indices = [i for count, indexes in zip(repeat, day_rows) for _ in range(count) for i in indexes]
                value = rho(x[indices], y[indices])
                if value is not None:
                    estimates.append(value)
            group["correlations"][key] = {"rho": rho(x, y), "cluster_95": interval(np.array(estimates))}
        result[label] = group
    return result


def matrix(train: list[dict], test: list[dict], names: list[str]) -> tuple[np.ndarray, np.ndarray, dict]:
    """過去学習資料だけで補完・標準化する。

    引数: train/test(list[dict])とnames(list[str])。返り値: tupleは学習行列・検査行列・変換定義。
    """
    transforms, arrays = {}, []
    for group in [train, test]:
        columns = [np.ones(len(group))]
        for name in names:
            if name not in transforms:
                finite = [r["features"][name] for r in train if r["features"][name] is not None]
                center = float(np.mean(finite)) if finite else 0.
                scale = float(np.std(finite)) if finite and name in CONTINUOUS else 1.
                transforms[name] = {"fill": center, "center": center if name in CONTINUOUS else 0., "scale": scale if scale > 1e-12 else 1.}
            state = transforms[name]
            values = np.array([state["fill"] if r["features"][name] is None else r["features"][name] for r in group])
            columns.append((values - state["center"]) / state["scale"])
        arrays.append(np.column_stack(columns))
    return arrays[0], arrays[1], transforms


def sigmoid(value: np.ndarray) -> np.ndarray:
    """有限なロジットから確率を得る。

    引数: value(np.ndarray)。返り値: np.ndarrayは0〜1の確率。
    """
    return 1 / (1 + np.exp(-np.clip(value, -40, 40)))


def fit_predict(train: list[dict], test: list[dict], model: str) -> tuple[np.ndarray, np.ndarray, dict]:
    """固定L2強度で勝率と期待値幅を学習する。

    引数: train/test(list[dict])、model(str)。返り値: tupleは確率・期待pt・係数/変換記録。
    """
    names = MODELS[model]
    x, z, transforms = matrix(train, test, names)
    y = np.array([r["win"] for r in train], float)
    target = np.array([r["initial_pt"] for r in train], float)
    penalty = np.diag([0.] + [10.] * len(names))
    beta = np.zeros(x.shape[1])
    p0 = (y.sum() + 1) / (len(y) + 2)
    beta[0] = math.log(p0 / (1 - p0))
    if len(np.unique(y)) > 1:
        for _ in range(100):
            p = sigmoid(x @ beta)
            hessian = x.T @ ((p * (1 - p))[:, None] * x) + penalty + np.eye(len(beta)) * 1e-10
            step = np.linalg.solve(hessian, x.T @ (p - y) + penalty @ beta)
            beta -= step
            if np.linalg.norm(step) < 1e-10:
                break
    reg = np.linalg.solve(x.T @ x + penalty + np.eye(len(beta)) * 1e-10, x.T @ target)
    return sigmoid(z @ beta), z @ reg, {"features": ["intercept"] + names, "logistic": beta.tolist(),
                                     "ridge": reg.tolist(), "transforms": transforms}


def metrics(rows: list[dict]) -> dict:
    """予測確率と期待ptの誤差を別々に測る。

    引数: rows(list[dict])は外部日予測。返り値: dictは誤差と校正表。
    """
    if not rows:
        return {"parents": 0}
    y = np.array([r["win"] for r in rows], float)
    values = np.array([r["initial_pt"] for r in rows])
    p = np.clip([r["probability"] for r in rows], 1e-12, 1 - 1e-12)
    expected = np.array([r["expected_pt"] for r in rows])
    result = {"parents": len(rows), "sessions": len({r["session"] for r in rows}),
              "wins": int(y.sum()), "observed_win_rate": float(y.mean()),
              "brier": float(np.mean((p - y) ** 2)), "log_loss": float(np.mean(-y * np.log(p) - (1 - y) * np.log(1 - p))),
              "mae_pt": float(np.mean(np.abs(expected - values))), "rmse_pt": float(np.sqrt(np.mean((expected - values) ** 2))),
              "expected_rho": rho(expected, values), "probability_bins": []}
    for i in range(5):
        selected = (p >= i / 5) & (p <= 1 if i == 4 else p < (i + 1) / 5)
        result["probability_bins"].append({"lower": i / 5, "upper": (i + 1) / 5, "parents": int(selected.sum()),
            "predicted": float(p[selected].mean()) if selected.any() else None,
            "observed": float(y[selected].mean()) if selected.any() else None})
    result["expected_groups"] = {}
    for label, selected in [("予測正", expected > 0), ("予測非正", expected <= 0)]:
        result["expected_groups"][label] = {"parents": int(selected.sum()),
            "actual_mean_pt": float(values[selected].mean()) if selected.any() else None,
            "actual_win_rate": float(y[selected].mean()) if selected.any() else None}
    return result


def walk_forward(rows: list[dict]) -> dict:
    """先行8完了場から翌日のみを順次予測する。

    引数: rows(list[dict])は全親。返り値: dictは全予測、モデル別誤差、同一場ペア差。
    """
    dates = sorted({r["session"] for r in rows})
    predictions, fits = {m: [] for m in MODELS}, []
    for day in dates[8:]:
        train = [r for r in rows if r["session"] < day]
        test = [r for r in rows if r["session"] == day]
        assert all(r["exit_time"] < min(t["decision_time"] for t in test) for r in train)
        for model in MODELS:
            p, e, state = fit_predict(train, test, model)
            fits.append({"test_day": day, "model": model, "train_last_day": max(r["session"] for r in train),
                         "train_parents": len(train), **state})
            for row, probability, expected in zip(test, p, e):
                predictions[model].append({k: row[k] for k in ["session", "parent", "owner", "side", "decision_time", "initial_pt", "win", "known"]}
                                         | {"probability": float(probability), "expected_pt": float(expected)})
    result = {"training_initial_days": dates[:8], "evaluation_days": dates[8:], "fits": fits,
              "predictions": predictions, "models": {}, "paired_vs_P0": {}}
    for model, pred in predictions.items():
        result["models"][model] = {"overall": metrics(pred),
            "owners": {o: metrics([r for r in pred if r["owner"] == o]) for o in ["core", "addon", "episode"]},
            "sides": {str(s): metrics([r for r in pred if r["side"] == s]) for s in [-1, 1]},
            "known": {str(k): metrics([r for r in pred if r["known"] == k]) for k in [True, False]}}
    rng = np.random.default_rng(SEED + 1)
    evaluation_count = len(dates) - 8
    assert evaluation_count > 0
    counts = rng.multinomial(evaluation_count, np.full(evaluation_count, 1 / evaluation_count), size=5000)
    base = predictions["P0"]
    weight = counts[:, [dates[8:].index(r["session"]) for r in base]]
    for model in ["P1", "P2", "P3"]:
        pred = predictions[model]
        assert [(r["session"], r["parent"]) for r in pred] == [(r["session"], r["parent"]) for r in base]
        differences = {}
        for name in ["brier", "log_loss", "mae_pt"]:
            errors = []
            for values in [pred, base]:
                y = np.array([r["win"] for r in values])
                p = np.clip([r["probability"] for r in values], 1e-12, 1 - 1e-12)
                error = ((p-y)**2 if name == "brier" else -y*np.log(p)-(1-y)*np.log(1-p) if name == "log_loss"
                         else np.abs([r["expected_pt"]-r["initial_pt"] for r in values]))
                errors.append(error)
            delta = errors[0] - errors[1]
            differences[name] = {"difference": float(delta.mean()), "cluster_95": interval(weight @ delta / weight.sum(axis=1))}
        result["paired_vs_P0"][model] = differences
    return result


def main() -> None:
    """固定済み計画に基づき保存親だけを分析する。

    引数: なし。返り値: None。売買再生・当日API・元成果更新はしない。
    """
    rows, fingerprints = make_rows()
    save(HERE / "初回玉と支持の対応159.json", {"rows": rows, "sources": fingerprints})
    result = {"plan_sha256": hashlib.sha256((HERE / "分析計画159.json").read_bytes()).hexdigest(),
              "scope": "既知26日中155親の保存分析。新金融再生0。時系列も既知開発資料の疑似外部評価。",
              "groups": describe_groups(rows), "temporal": walk_forward(rows)}
    save(HERE / "支持校正の保存分析159.json", result)
    print(json.dumps({m: v["overall"] for m, v in result["temporal"]["models"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
