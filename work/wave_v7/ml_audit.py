"""未来の入力・教師を改変する反証試験と保存モデルの予測再生成を行う。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

import ml_models as ml


BASE = Path(__file__).resolve().parent


def subset(data: dict, mask: np.ndarray) -> dict:
    """入力行に対応する配列だけを同じマスクで絞る。

    引数: data (dict) は入力配列、mask (np.ndarray) は行の採否。
    返り値: dict は列名などのメタデータを保持した部分入力。
    """
    n = len(data["time_ns"])
    row_names = {"X", "session_idx", "symbol_idx", "time_ns", "valid", "future_returns", "label_end_ns", "age"}
    return {key: value[mask] if key in row_names and len(value) == n else value for key, value in data.items()}


def same_models(first: Path, second: Path, scope: str, horizon: int) -> dict:
    """モデルの保存容器ではなく学習済み係数そのものの一致を調べる。

    引数: first (Path) は元モデル、second (Path) は改変試験、scope (str) は分割、horizon (int) は教師期間。
    返り値: dict はscaler・線形係数・全seedテンソルの完全一致結果。
    """
    result = {}
    for kind in ("scaler", "logistic"):
        with np.load(first / f"{scope}_{horizon}_{kind}.npz", allow_pickle=False) as original:
            with np.load(second / f"{scope}_{horizon}_{kind}.npz", allow_pickle=False) as altered:
                result[kind] = all(np.array_equal(original[key], altered[key], equal_nan=False) for key in original.files)
    for seed in ml.SEEDS:
        original = torch.load(first / f"{scope}_{horizon}_lstm_seed{seed}.pt", map_location="cpu", weights_only=True)
        altered = torch.load(second / f"{scope}_{horizon}_lstm_seed{seed}.pt", map_location="cpu", weights_only=True)
        result[f"seed{seed}"] = all(torch.equal(original[key], altered[key]) for key in original)
    if not all(result.values()):
        raise AssertionError(f"学習済み係数が変化: {scope}/{horizon}: {result}")
    return result


def compare_probabilities(first: dict, second: dict, mask: np.ndarray, subset_mask: bool) -> dict:
    """過去に対応する予測だけを比較し、最大誤差を記録する。

    引数: first (dict) は元確率、second (dict) は比較確率、mask (ndarray) は比較する過去行、
    subset_mask (bool) は比較側が過去行だけの配列か。
    返り値: dict はモデルごとの件数・最大絶対誤差。
    """
    result = {}
    for key in first:
        a = first[key][mask]
        b = second[key] if subset_mask else second[key][mask]
        if not np.array_equal(np.isfinite(a), np.isfinite(b)):
            raise AssertionError(f"予測の有無が変化: {key}")
        known = np.isfinite(a)
        error = float(np.max(np.abs(a[known] - b[known]))) if np.any(known) else 0.0
        if error > 2e-7:
            raise AssertionError(f"過去の予測が変化: {key}: {error}")
        result[key] = {"比較数": int(np.sum(known)), "最大絶対誤差": error}
    return result


def audit_and_refresh() -> None:
    """実データの未来部分改変・末尾削除・教師削除を検証する。

    引数: なし。固定したdataset.npzと保存モデルを使用する。
    返り値: None。監査JSONと学習し直さない時系列評価予測を保存する。
    """
    data_path = BASE / "dataset.npz"
    data = ml.load_data(data_path)
    ml.initialize_torch(ml.SEEDS[0])
    audit_dir = BASE / "ml_causality_check"
    audit_dir.mkdir(exist_ok=True)
    sequence = ml.sequence_rows(data)
    records = {
        "入力SHA256": ml.digest_file(data_path),
        "機械学習コードSHA256": ml.digest_file(BASE / "ml_models.py"),
        "監査コードSHA256": ml.digest_file(Path(__file__)),
        "環境": ml.environment_record(),
        "許容誤差": 2e-7,
        "対象": "固定モデルの予測構造と学習処理の漏洩。最終モデルによる過去の成績を評価する試験ではない。",
        "学習の未来改変試験": [],
    }

    # ----------------------------------------
    for session in (2, 3, 4):
        changed = {key: value.copy() for key, value in data.items()}
        future = data["session_idx"] >= session
        changed["X"][future] = 12345.0
        changed["future_returns"][future] = 1000000.0
        changed["label_end_ns"][future] = np.iinfo(np.int64).max
        changed["valid"][future] = True
        predictions = ml.blank_predictions(len(data["time_ns"]))
        destination = audit_dir / f"未来を改変_fold{session}"
        for column, horizon in enumerate(ml.HORIZONS):
            print(f"漏洩監査: 評価セッション={session}, 教師={horizon}分", flush=True)
            record = ml.train_one(changed, sequence, column, session, destination, predictions)
            same = same_models(BASE / "models", destination, f"fold{session}", horizon)
            records["学習の未来改変試験"].append({
                "分割": session, "教師期間": horizon,
                "学習入力数": record["ロジスティック学習数"],
                "未来改変後の完全一致": same,
            })

    # ----------------------------------------
    original = ml.predict_arrays(data, BASE / "models")
    past = data["age"] <= 180
    suffix_changed = {key: value.copy() for key, value in data.items()}
    suffix_changed["X"][~past] = -54321.0
    suffix_changed.pop("future_returns")
    suffix_changed.pop("label_end_ns")
    suffix_predictions = ml.predict_arrays(suffix_changed, BASE / "models")
    records["予測の未来特徴量改変と教師削除"] = compare_probabilities(original, suffix_predictions, past, False)
    prefix_data = subset(suffix_changed, past)
    prefix_predictions = ml.predict_arrays(prefix_data, BASE / "models")
    records["予測の未来行削除"] = compare_probabilities(original, prefix_predictions, past, True)
    valid_sequences = sequence[sequence[:, 0] >= 0]
    if not np.all(data["session_idx"][valid_sequences] == data["session_idx"][valid_sequences[:, -1]][:, None]):
        raise AssertionError("系列がセッションを跨いでいます。")
    if not np.all(data["symbol_idx"][valid_sequences] == data["symbol_idx"][valid_sequences[:, -1]][:, None]):
        raise AssertionError("系列が銘柄を跨いでいます。")
    if not np.all(np.diff(data["time_ns"][valid_sequences], axis=1) == ml.MINUTE_NS):
        raise AssertionError("系列が観測欠損を跨いでいます。")
    records["系列のセッション銘柄分離と1分連続"] = {"確認数": len(valid_sequences), "一致": True}

    # ----------------------------------------
    predictions = ml.blank_predictions(len(data["time_ns"]))
    for session in (2, 3, 4):
        mask = data["session_idx"] == session
        probabilities = ml.predict_arrays(subset(data, mask), BASE / "models", f"fold{session}")
        for key in probabilities:
            predictions[key][mask] = probabilities[key]
    np.savez(BASE / "ml_predictions.npz", **predictions, time_ns=data["time_ns"], session_idx=data["session_idx"], symbol_idx=data["symbol_idx"])
    records["評価予測SHA256"] = ml.digest_file(BASE / "ml_predictions.npz")
    records["結果"] = "全件合格"
    (BASE / "ml_causality_audit.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    training_path = BASE / "ml_training_record.json"
    training = json.loads(training_path.read_text(encoding="utf-8"))
    training["再推論"] = {
        "入力SHA256": records["入力SHA256"], "予測SHA256": records["評価予測SHA256"],
        "理由": "新規判断時刻を合わせvalidをage45以降から43以降へ変更。学習はage45から5分間隔のため同一。",
        "モデル変更": False, "学習係数完全一致の独立確認": "ml_causality_audit.json",
    }
    training_path.write_text(json.dumps(training, ensure_ascii=False, indent=2), encoding="utf-8")
    print("漏洩監査と保存モデルの評価予測再生成が完了しました。", flush=True)


if __name__ == "__main__":
    audit_and_refresh()
