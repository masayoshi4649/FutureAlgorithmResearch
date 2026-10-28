"""保存済み初回玉だけで、担当と支持の交互作用を時系列評価する。"""

from copy import deepcopy
from pathlib import Path
import hashlib
import json
import sys
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import analyze159 as core

INTERACTIONS = ["core_M", "core_T", "addon_M", "addon_T"]
CHANGES = ["core_change", "addon_change"]
MODELS = {"P0": core.MODELS["P0"], "P3": core.MODELS["P3"],
          "P4": core.MODELS["P3"] + INTERACTIONS,
          "P5": core.MODELS["P3"] + INTERACTIONS + CHANGES}


def expand_rows(rows: list[dict]) -> list[dict]:
    """当時特徴から担当交互作用だけを作り、元行は変えない。

    引数: rows(list[dict])は初回玉全行。返り値: list[dict]は複製した解析用行。
    """
    result = deepcopy(rows)
    for row in result:
        f = row["features"]
        for owner in ["core", "addon"]:
            for key in ["M", "T", "change"]:
                f[f"{owner}_{key}"] = f[key] if row["owner"] == owner else 0.
    return result


def configure() -> None:
    """実行プロセス内だけへ固定4モデルを設定する。

    引数: なし。返り値: None。第一分析の保存ファイルは変更しない。
    """
    core.MODELS = deepcopy(MODELS)
    core.CONTINUOUS = core.CONTINUOUS | set(INTERACTIONS + CHANGES)


def evaluate(rows: list[dict]) -> dict:
    """先行8場以上だけで学習し、翌日の初回玉を予測する。

    引数: rows(list[dict])は26Day全親。返り値: dictは予測・係数・誤差。
    """
    dates = sorted({r["session"] for r in rows})
    assert len(dates) == 26
    predictions, fits = {m: [] for m in MODELS}, []
    for day in dates[8:]:
        train = [r for r in rows if r["session"] < day]
        test = [r for r in rows if r["session"] == day]
        assert all(r["exit_time"] < min(t["decision_time"] for t in test) for r in train)
        for model in MODELS:
            p, e, state = core.fit_predict(train, test, model)
            fits.append({"test_day": day, "model": model, "train_last_day": max(r["session"] for r in train),
                         "train_parents": len(train), **state})
            for row, probability, expected in zip(test, p, e):
                predictions[model].append({k: row[k] for k in ["session", "parent", "owner", "side", "decision_time", "initial_pt", "win", "known"]}
                    | {"probability": float(probability), "expected_pt": float(expected)})
    result = {"training_initial_days": dates[:8], "evaluation_days": dates[8:], "fits": fits,
              "predictions": predictions, "models": {}, "paired": {}}
    for model, pred in predictions.items():
        assert len(pred) == 120
        result["models"][model] = {"overall": core.metrics(pred),
            "owners": {o: core.metrics([r for r in pred if r["owner"] == o]) for o in ["core", "addon", "episode"]},
            "sides": {str(s): core.metrics([r for r in pred if r["side"] == s]) for s in [-1, 1]},
            "known": {str(k): core.metrics([r for r in pred if r["known"] == k]) for k in [True, False]}}
    # ----------------------------------------
    # 同じ評価場を丸ごと引き直し、予測は再学習せずペア誤差の不確実性を測る。
    rng = np.random.default_rng(160)
    n = len(dates) - 8
    counts = rng.multinomial(n, np.full(n, 1 / n), size=5000)
    weight = counts[:, [dates[8:].index(r["session"]) for r in predictions["P0"]]]
    for model in ["P4", "P5"]:
        for base in ["P0", "P3"]:
            assert [(r["session"], r["parent"]) for r in predictions[model]] == [(r["session"], r["parent"]) for r in predictions[base]]
            differences = {}
            for name in ["brier", "log_loss", "mae_pt"]:
                errors = []
                for values in [predictions[model], predictions[base]]:
                    y = np.array([r["win"] for r in values])
                    p = np.clip([r["probability"] for r in values], 1e-12, 1 - 1e-12)
                    error = ((p-y)**2 if name == "brier" else -y*np.log(p)-(1-y)*np.log(1-p) if name == "log_loss"
                             else np.abs([r["expected_pt"]-r["initial_pt"] for r in values]))
                    errors.append(error)
                delta = errors[0] - errors[1]
                differences[name] = {"difference": float(delta.mean()), "cluster_95": core.interval(weight @ delta / weight.sum(axis=1))}
            result["paired"][f"{model}-{base}"] = differences
    return result


def digest(path: Path) -> dict:
    """入力を内容指紋で記録する。

    引数: path(Path)。返り値: dictは絶対パス・SHA256・bytes。
    """
    content = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}


def main() -> None:
    """固定計画と入力を先に保存し、解析終了時に元結果不変を確認する。

    引数: なし。返り値: None。新金融売買とApp変更をしない。
    """
    paths = [HERE / "分析計画159r2.json", HERE / "analyze159r2.py", HERE.parent / "analyze159.py",
             HERE.parent / "初回玉と支持の対応159.json", HERE.parent / "支持校正の保存分析159.json"]
    sources = [digest(p) for p in paths]
    core.save(HERE / "解析前入力指紋159r2.json", {"sources": sources, "新金融再生": False})
    rows = expand_rows(core.read(paths[-2])["rows"])
    assert len(rows) == 155
    configure()
    result = evaluate(rows)
    old = core.read(paths[-1])["temporal"]
    exact = {}
    for model in ["P0", "P3"]:
        assert result["predictions"][model] == old["predictions"][model]
        assert [r for r in result["fits"] if r["model"] == model] == [r for r in old["fits"] if r["model"] == model]
        exact[model] = {"全予測一致": 120, "学習係数一致": 18}
    assert [digest(p) for p in paths] == sources
    core.save(HERE / "担当交互作用の時系列校正159r2.json", {
        "scope": "第一分析後の開発追加2案。既知26Day155初回親、18評価場120親。真正未見選択ではない。",
        "models": MODELS, "temporal": result, "baseline_exact": exact, "sources": sources,
        "source_unchanged": True, "新金融再生": False})
    print(json.dumps({"models": {m: r["overall"] for m, r in result["models"].items()}, "paired": result["paired"], "exact": exact}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
