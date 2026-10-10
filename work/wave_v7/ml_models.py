"""未来のラベルを隔離し、固定条件の線形モデルと単方向LSTMを時系列評価する。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import numpy as np
import torch
from torch import nn


BASE = Path(__file__).resolve().parent
SEEDS = (1729, 1730, 1731)
HORIZONS = (30, 60, 120)
SEQUENCE = 30
EPOCHS = 20
BATCH = 128
LEARNING_RATE = 0.001
L2 = 0.01
NEWTON_STEPS = 60
MINUTE_NS = 60_000_000_000


def digest_file(path: Path) -> str:
    """ファイルのSHA256を求める。

    引数: path (Path) は対象ファイル。
    返り値: str は内容のSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest_arrays(*arrays: np.ndarray) -> str:
    """配列の形・型・値をまとめて識別する。

    引数: arrays (np.ndarray列) は順序付きの対象配列。
    返り値: str はSHA256。
    """
    digest = hashlib.sha256()
    for array in arrays:
        contiguous = np.ascontiguousarray(array)
        digest.update(str(contiguous.shape).encode())
        digest.update(str(contiguous.dtype).encode())
        digest.update(contiguous.tobytes())
    return digest.hexdigest()


def stamp(value: int) -> str | None:
    """ナノ秒のUTC時刻をISO8601へ変換する。

    引数: value (int) はUTCエポックのナノ秒。
    返り値: strまたはNone は有効な日時または欠測。
    """
    if value <= 0:
        return None
    return datetime.fromtimestamp(value / 1e9, tz=timezone.utc).isoformat()


def load_data(path: Path, require_labels: bool = True) -> dict[str, np.ndarray]:
    """NPZを読み取り、時系列・列・ラベルの基本整合性を確認する。

    引数: path (Path) は入力、require_labels (bool) は学習列を必要とするか。
    返り値: dict[str,np.ndarray] は入力配列。
    """
    with np.load(path, allow_pickle=False) as source:
        data = {name: source[name] for name in source.files}
    required = {"X", "feature_names", "session_idx", "symbol_idx", "time_ns", "valid"}
    if require_labels:
        required |= {"future_returns", "label_end_ns", "horizons"}
    if required - data.keys():
        raise ValueError(f"不足列: {sorted(required - data.keys())}")
    n, f = data["X"].shape
    if len(data["feature_names"]) != f:
        raise ValueError("特徴量名と入力列数が一致しません。")
    for name in ("session_idx", "symbol_idx", "time_ns", "valid"):
        if data[name].shape != (n,):
            raise ValueError(f"行数不一致: {name}")
    for session in np.unique(data["session_idx"]):
        for symbol in np.unique(data["symbol_idx"]):
            rows = np.flatnonzero((data["session_idx"] == session) & (data["symbol_idx"] == symbol))
            if len(rows) and np.any(np.diff(data["time_ns"][rows]) <= 0):
                raise ValueError("同一セッション・銘柄内の時刻が厳密な昇順ではありません。")
    if require_labels:
        if tuple(data["horizons"].tolist()) != HORIZONS:
            raise ValueError("教師期間は30/60/120分に固定しています。")
        if data["future_returns"].shape != (n, 3) or data["label_end_ns"].shape != (n, 3):
            raise ValueError("教師配列の形が不正です。")
        for column in range(3):
            known = np.isfinite(data["future_returns"][:, column])
            if np.any(data["label_end_ns"][known, column] <= data["time_ns"][known]):
                raise ValueError("教師の満了日時が判断時刻より後ではありません。")
            for session in np.unique(data["session_idx"]):
                rows = data["session_idx"] == session
                latest = int(data["time_ns"][rows].max())
                if np.any(data["label_end_ns"][rows & known, column] > latest):
                    raise ValueError("教師が所属セッションの観測末尾を越えています。")
    return data


def sequence_rows(data: dict[str, np.ndarray]) -> np.ndarray:
    """同じ銘柄・セッション内の連続30分だけを系列にする。

    引数: data (dict[str,np.ndarray]) は入力配列。
    返り値: np.ndarray は各判断行の過去30行番号。不成立行はすべて-1。
    """
    n = len(data["time_ns"])
    result = np.full((n, SEQUENCE), -1, dtype=np.int64)
    for session in np.unique(data["session_idx"]):
        for symbol in np.unique(data["symbol_idx"]):
            rows = np.flatnonzero((data["session_idx"] == session) & (data["symbol_idx"] == symbol))
            for offset in range(SEQUENCE - 1, len(rows)):
                window = rows[offset - SEQUENCE + 1:offset + 1]
                if np.all(np.diff(data["time_ns"][window]) == MINUTE_NS):
                    result[rows[offset]] = window
    return result


def fit_scaler(x: np.ndarray) -> dict[str, np.ndarray]:
    """指定された学習入力だけから補完値と標準化係数を求める。

    引数: x (np.ndarray) は学習に実際に用いる入力行。
    返り値: dict[str,np.ndarray] は中央値・平均・標準偏差。
    """
    clean = np.where(np.isfinite(x), x, np.nan).astype(np.float64)
    median = np.zeros(clean.shape[1], dtype=np.float64)
    for column in range(clean.shape[1]):
        finite = clean[:, column][np.isfinite(clean[:, column])]
        median[column] = np.median(finite) if len(finite) else 0.0
    filled = np.where(np.isfinite(clean), clean, median)
    mean = filled.mean(axis=0)
    scale = filled.std(axis=0)
    scale[scale < 1e-12] = 1.0
    return {"median": median, "mean": mean, "scale": scale}


def transform(x: np.ndarray, scaler: dict[str, np.ndarray]) -> np.ndarray:
    """保存済みの係数だけで補完・標準化する。

    引数: x (np.ndarray) は入力、scaler (dict) は学習済み係数。
    返り値: np.ndarray は標準化済みfloat32。予測対象からの再学習は行わない。
    """
    filled = np.where(np.isfinite(x), x, scaler["median"])
    return ((filled - scaler["mean"]) / scaler["scale"]).astype(np.float32)


def sigmoid(x: np.ndarray) -> np.ndarray:
    """数値の発散を抑えてロジスティック関数を計算する。

    引数: x (np.ndarray) は実数値。
    返り値: np.ndarray は0〜1の値。
    """
    return 1.0 / (1.0 + np.exp(-np.clip(x, -40.0, 40.0)))


def fit_logistic(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """L2正則化ロジスティック回帰を固定60回のNewton法で学習する。

    引数: x (np.ndarray) は標準化入力、y (np.ndarray) は0/1の教師。
    返り値: np.ndarray は末尾を切片とする係数。L2係数は0.01で切片は除外。
    """
    design = np.column_stack((x.astype(np.float64), np.ones(len(x))))
    weights = np.zeros(design.shape[1], dtype=np.float64)
    penalty = np.full(len(weights), L2)
    penalty[-1] = 0.0
    for _ in range(NEWTON_STEPS):
        p = sigmoid(design @ weights)
        curvature = np.maximum(p * (1.0 - p), 1e-8)
        gradient = design.T @ (p - y) / len(y) + penalty * weights
        hessian = (design.T * curvature) @ design / len(y) + np.diag(penalty + 1e-9)
        weights -= np.linalg.solve(hessian, gradient)
    return weights


class DirectionLSTM(nn.Module):
    """30分の過去入力を読む単方向・1層・隠れ状態16の分類器。"""

    def __init__(self, features: int):
        """固定構成の層を生成する。

        引数: features (int) は入力の特徴量数。
        返り値: None。
        """
        super().__init__()
        self.recurrent = nn.LSTM(features, 16, num_layers=1, batch_first=True, bidirectional=False)
        self.output = nn.Linear(16, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """過去系列の末尾の隠れ状態から上昇のスコアを返す。

        引数: x (torch.Tensor) はバッチ×30×特徴量。
        返り値: torch.Tensor はバッチごとの対数オッズ。
        """
        _, (hidden, _) = self.recurrent(x)
        return self.output(hidden[-1]).squeeze(-1)


def initialize_torch(seed: int) -> torch.device:
    """乱数と決定的演算を設定し、使用可能ならGPUを選ぶ。

    引数: seed (int) は固定乱数値。
    返り値: torch.device は選択した演算装置。
    """
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(1)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    if hasattr(torch.backends.cuda.matmul, "allow_tf32"):
        torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def fit_lstm(x: np.ndarray, y: np.ndarray, seed: int) -> tuple[DirectionLSTM, list[float]]:
    """指定seedで20epochすべて学習し、途中やseedの成績で選別しない。

    引数: x (np.ndarray) は学習系列、y (np.ndarray) は教師、seed (int) は乱数値。
    返り値: tuple は学習済みモデルと各epochの学習損失。
    """
    device = initialize_torch(seed)
    model = DirectionLSTM(x.shape[-1]).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    criterion = nn.BCEWithLogitsLoss()
    features = torch.as_tensor(x, dtype=torch.float32, device=device)
    labels = torch.as_tensor(y, dtype=torch.float32, device=device)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    losses = []
    model.train()
    for _ in range(EPOCHS):
        permutation = torch.randperm(len(y), generator=generator).to(device)
        total = 0.0
        for start in range(0, len(y), BATCH):
            rows = permutation[start:start + BATCH]
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(features[rows]), labels[rows])
            loss.backward()
            optimizer.step()
            total += float(loss.detach().cpu()) * len(rows)
        losses.append(total / len(y))
    return model.cpu().eval(), losses


def predict_lstm(model: DirectionLSTM, x: np.ndarray) -> np.ndarray:
    """学習済みモデルを更新せず入力系列ごとの上昇確率を求める。

    引数: model (DirectionLSTM) は保存モデル、x (np.ndarray) は系列入力。
    返り値: np.ndarray は上昇確率。空入力なら空配列。
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = model.to(device).eval()
    chunks = []
    with torch.no_grad():
        for start in range(0, len(x), 512):
            batch = torch.as_tensor(x[start:start + 512], dtype=torch.float32, device=device)
            chunks.append(torch.sigmoid(model(batch)).cpu().numpy())
    model.cpu()
    return np.concatenate(chunks).astype(np.float64) if chunks else np.empty(0)


# ----------------------------------------


def model_parameters() -> dict:
    """評価前に固定した条件を返す。

    引数: なし。
    返り値: dict は再現に必要な定数。
    """
    return {
        "対象期間分": list(HORIZONS), "LSTMの乱数": list(SEEDS), "系列長": SEQUENCE,
        "LSTM隠れ状態": 16, "LSTM層数": 1, "双方向": False, "epoch": EPOCHS,
        "batch": BATCH, "optimizer": "Adam", "学習率": LEARNING_RATE,
        "ロジスティックL2": L2, "ロジスティック固定反復": NEWTON_STEPS,
        "学習抽出": "セッション開始からの分数ageについて(age-45)%5=0。差0は除外。両銘柄をまとめて学習。",
        "推論": "有効な行を毎分。LSTMは同一セッション・同一銘柄の連続30分。",
        "判定閾値": 0.5, "早期停止": False, "seed選別": False,
        "主LSTM予測": "3seedの予測確率を等重みで平均",
    }


def environment_record() -> dict:
    """実行環境と演算装置を記録する。

    引数: なし。
    返り値: dict はバージョン・装置・決定的演算設定。
    """
    device = initialize_torch(SEEDS[0])
    return {
        "Python": sys.version, "実行ファイル": sys.executable, "OS": platform.platform(),
        "numpy": np.__version__, "torch": torch.__version__, "CUDA": torch.version.cuda,
        "HIP": torch.version.hip, "装置": str(device),
        "GPU": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "cudnn": torch.backends.cudnn.version(), "決定的演算": True,
        "CUBLAS_WORKSPACE_CONFIG": os.environ["CUBLAS_WORKSPACE_CONFIG"],
        "cudnn_benchmark": False, "TF32": False,
    }


def train_one(data: dict, sequence: np.ndarray, column: int, test_session: int | None,
              model_dir: Path, predictions: dict) -> dict:
    """1期間・1分割の学習と隔離された評価予測を行う。

    引数: data (dict) は入力、sequence (ndarray) は因果系列、column (int) は教師列、
    test_session (int/None) は評価セッションまたは全学習、model_dir (Path) は保存先、
    predictions (dict) は確率配列の格納先。
    返り値: dict は学習期間・補完・モデルの監査記録。
    """
    horizon = HORIZONS[column]
    label = data["future_returns"][:, column]
    valid = data["valid"].astype(bool)
    sample = (data["age"] - 45) % 5 == 0
    known = np.isfinite(label) & (label != 0)
    train_mask = valid & sample & known
    test_start = None
    if test_session is not None:
        test_mask = (data["session_idx"] == test_session) & valid
        test_start = int(data["time_ns"][data["session_idx"] == test_session].min())
        train_mask &= data["session_idx"] < test_session
        train_mask &= data["label_end_ns"][:, column] < test_start
        scope = f"fold{test_session}"
    else:
        test_mask = np.zeros(len(label), dtype=bool)
        scope = "final"
    rows = np.flatnonzero(train_mask)
    lstm_rows = rows[sequence[rows, 0] >= 0]
    if len(rows) < 10 or len(lstm_rows) < 10:
        raise ValueError(f"{scope}/{horizon}: 学習行が不足しています。")
    scaler_rows = np.unique(np.concatenate((rows, sequence[lstm_rows].ravel())))
    scaler = fit_scaler(data["X"][scaler_rows])
    scaled = transform(data["X"], scaler)
    model_dir.mkdir(parents=True, exist_ok=True)
    scaler_path = model_dir / f"{scope}_{horizon}_scaler.npz"
    np.savez(scaler_path, **scaler, feature_names=data["feature_names"])
    weights = fit_logistic(scaled[rows], (label[rows] > 0).astype(np.float64))
    logistic_path = model_dir / f"{scope}_{horizon}_logistic.npz"
    np.savez(logistic_path, weights=weights)
    test_rows = np.flatnonzero(test_mask)
    if len(test_rows):
        predictions[f"logistic_{horizon}"][test_rows] = sigmoid(
            scaled[test_rows].astype(np.float64) @ weights[:-1] + weights[-1])
    test_lstm_rows = test_rows[sequence[test_rows, 0] >= 0]
    seed_predictions = []
    lstm_records = []
    for seed in SEEDS:
        model, losses = fit_lstm(scaled[sequence[lstm_rows]], (label[lstm_rows] > 0).astype(np.float32), seed)
        model_path = model_dir / f"{scope}_{horizon}_lstm_seed{seed}.pt"
        torch.save(model.state_dict(), model_path)
        if len(test_lstm_rows):
            probability = predict_lstm(model, scaled[sequence[test_lstm_rows]])
            predictions[f"lstm_seed{seed}_{horizon}"][test_lstm_rows] = probability
            seed_predictions.append(probability)
        lstm_records.append({"seed": seed, "ファイル": str(model_path), "SHA256": digest_file(model_path), "学習損失": losses})
    if seed_predictions:
        predictions[f"lstm_{horizon}"][test_lstm_rows] = np.mean(seed_predictions, axis=0)
    label_max = int(data["label_end_ns"][rows, column].max())
    if test_start is not None and label_max >= test_start:
        raise AssertionError("未来ラベルの混入を検知しました。")
    return {
        "分割": scope, "期間分": horizon, "学習セッション": np.unique(data["session_idx"][rows]).tolist(),
        "ロジスティック学習数": len(rows), "LSTM学習数": len(lstm_rows),
        "教師上昇比率": float(np.mean(label[rows] > 0)), "差0除外数": int(np.sum(valid & sample & (label == 0) & (data["session_idx"] < (test_session if test_session is not None else np.inf)))),
        "学習最初判断UTC": stamp(int(data["time_ns"][rows].min())),
        "学習最終判断UTC": stamp(int(data["time_ns"][rows].max())),
        "最終教師満了UTC": stamp(label_max), "評価最初判断UTC": stamp(test_start or 0),
        "ラベル隔離": test_start is None or label_max < test_start,
        "標準化入力数": len(scaler_rows), "標準化最終判断UTC": stamp(int(data["time_ns"][scaler_rows].max())),
        "標準化SHA256": digest_arrays(scaler["median"], scaler["mean"], scaler["scale"]),
        "標準化ファイル": str(scaler_path), "標準化ファイルSHA256": digest_file(scaler_path),
        "ロジスティック": {"ファイル": str(logistic_path), "SHA256": digest_file(logistic_path)},
        "LSTM": lstm_records,
        "ロジスティック評価数": len(test_rows), "LSTM評価数": len(test_lstm_rows),
    }


def blank_predictions(n: int) -> dict[str, np.ndarray]:
    """行対応を保つ欠測の予測配列を準備する。

    引数: n (int) は入力行数。
    返り値: dict[str,np.ndarray] はモデル・期間別の確率格納先。
    """
    return {f"{name}_{horizon}": np.full(n, np.nan, dtype=np.float64)
            for horizon in HORIZONS for name in ("logistic", "lstm", *(f"lstm_seed{seed}" for seed in SEEDS))}


def train(data_path: Path, output_dir: Path) -> None:
    """3分割の予測と全保存期間で学習した最終モデルを保存する。

    引数: data_path (Path) は凍結入力、output_dir (Path) は出力先。
    返り値: None。学習記録・予測NPZ・モデルを保存する。
    """
    data = load_data(data_path)
    sequence = sequence_rows(data)
    predictions = blank_predictions(len(data["time_ns"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    records = {
        "検証の区分": "既に研究した保存期間の時間順再評価。真の未観測試験ではない。",
        "開始UTC": datetime.now(timezone.utc).isoformat(),
        "入力": str(data_path), "入力SHA256": digest_file(data_path),
        "コードSHA256": digest_file(Path(__file__)), "条件": model_parameters(),
        "環境": environment_record(), "学習記録": [],
    }
    (output_dir / "ml_fixed_protocol.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    for test_session in (2, 3, 4, None):
        for column, horizon in enumerate(HORIZONS):
            print(f"学習: 評価セッション={test_session}, 教師={horizon}分", flush=True)
            record = train_one(data, sequence, column, test_session, output_dir / "models", predictions)
            records["学習記録"].append(record)
            (output_dir / "ml_training_record.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    np.savez(output_dir / "ml_predictions.npz", **predictions, time_ns=data["time_ns"], session_idx=data["session_idx"], symbol_idx=data["symbol_idx"])
    records["終了UTC"] = datetime.now(timezone.utc).isoformat()
    records["予測SHA256"] = digest_file(output_dir / "ml_predictions.npz")
    (output_dir / "ml_training_record.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print("固定条件の機械学習比較と最終モデルの保存が完了しました。", flush=True)


def predict_arrays(data: dict, model_dir: Path, scope: str = "final") -> dict[str, np.ndarray]:
    """保存モデルだけで新入力を予測する。教師列は一切参照しない。

    引数: data (dict) は過去だけの入力、model_dir (Path) は固定モデル、scope (str) は分割名。
    返り値: dict[str,np.ndarray] は入力行に対応する確率配列。
    """
    initialize_torch(SEEDS[0])
    predictions = blank_predictions(len(data["time_ns"]))
    sequence = sequence_rows(data)
    rows = np.flatnonzero(data["valid"].astype(bool))
    lstm_rows = rows[sequence[rows, 0] >= 0]
    for horizon in HORIZONS:
        with np.load(model_dir / f"{scope}_{horizon}_scaler.npz", allow_pickle=False) as source:
            if not np.array_equal(source["feature_names"], data["feature_names"]):
                raise ValueError("学習時と特徴量名・順序が一致しません。")
            scaler = {key: source[key] for key in ("median", "mean", "scale")}
        scaled = transform(data["X"], scaler)
        with np.load(model_dir / f"{scope}_{horizon}_logistic.npz", allow_pickle=False) as source:
            weights = source["weights"]
        predictions[f"logistic_{horizon}"][rows] = sigmoid(scaled[rows].astype(np.float64) @ weights[:-1] + weights[-1])
        seed_predictions = []
        for seed in SEEDS:
            model = DirectionLSTM(data["X"].shape[1])
            model.load_state_dict(torch.load(model_dir / f"{scope}_{horizon}_lstm_seed{seed}.pt", map_location="cpu", weights_only=True))
            probability = predict_lstm(model, scaled[sequence[lstm_rows]])
            predictions[f"lstm_seed{seed}_{horizon}"][lstm_rows] = probability
            seed_predictions.append(probability)
        predictions[f"lstm_{horizon}"][lstm_rows] = np.mean(seed_predictions, axis=0)
    return predictions


def predict(data_path: Path, model_dir: Path, output: Path, scope: str) -> None:
    """再学習せず別NPZの予測を保存するCLI処理。

    引数: data_path (Path) は入力、model_dir (Path) は保存モデル、output (Path) は予測先、scope (str) は分割名。
    返り値: None。教師なしでも予測できるNPZを保存する。
    """
    data = load_data(data_path, require_labels=False)
    predictions = predict_arrays(data, model_dir, scope)
    np.savez(output, **predictions, time_ns=data["time_ns"], session_idx=data["session_idx"], symbol_idx=data["symbol_idx"])
    print(f"保存モデルだけによる予測完了: {output}", flush=True)


def main() -> None:
    """学習と固定モデルによる予測を引数で切り替える。

    引数: コマンドライン引数。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description="因果的な固定条件の機械学習比較")
    subparsers = parser.add_subparsers(dest="command", required=True)
    train_parser = subparsers.add_parser("train", help="時系列再評価と最終モデル保存")
    train_parser.add_argument("--data", type=Path, default=BASE / "dataset.npz")
    train_parser.add_argument("--output-dir", type=Path, default=BASE)
    predict_parser = subparsers.add_parser("predict", help="保存モデルだけで新入力を予測")
    predict_parser.add_argument("--data", type=Path, required=True)
    predict_parser.add_argument("--models", type=Path, default=BASE / "models")
    predict_parser.add_argument("--output", type=Path, default=BASE / "live_predict.npz")
    predict_parser.add_argument("--scope", default="final")
    args = parser.parse_args()
    if args.command == "train":
        train(args.data.resolve(), args.output_dir.resolve())
    else:
        predict(args.data.resolve(), args.models.resolve(), args.output.resolve(), args.scope)


if __name__ == "__main__":
    main()
