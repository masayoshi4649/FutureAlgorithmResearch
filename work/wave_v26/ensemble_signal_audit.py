"""合意条件の倍率1再現、経過秒判定、方向重複、未来非参照を損益なしで検査する。"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys
import time

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
OLD = HERE.parent / "wave_v23"
V25 = HERE.parent / "wave_v25"
_spec = importlib.util.spec_from_file_location("v26_audited_signals", HERE / "ensemble_signals.py")
SIGNALS = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = SIGNALS
_spec.loader.exec_module(SIGNALS)


def _old_price_functions() -> dict:
    """機能: 元P02の入口と保持関数だけを読み、売買・成績コードを実行しない。

    引数: なし。返り値: 元 candidates/hold を含む私有名前空間 (dict)。
    注意: ソース不変。Numbaの保存を防ぐため保持関数の装飾だけを外し、同じPython計算を実行する。
    """
    source = V25 / "d016_price_control.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    selected = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ("candidates", "hold"):
            node.decorator_list = []
            selected.append(node)
    assert len(selected) == 2
    namespace = {"np": np, "signals": SIGNALS.COMPONENTS}
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])), str(source), "exec"), namespace)
    return namespace


def nominal_check(inputs: dict, features: dict) -> dict:
    """機能: 倍率1と遅延1の4基礎方向が元方向と全26入力で一致するか検査する。

    引数: inputs/features (dict)。返り値: 基礎別一致件数と比較行数 (dict)。
    """
    params = SIGNALS.catalog()[0]["params"]
    parts = SIGNALS._components(inputs, features, params)
    references = {}
    for name in ("F32", "D016", "D056"):
        with np.load(V25 / "directions" / f"{name}.npz") as archive:
            references[name] = {tuple(key.split("|")): archive[key] for key in archive.files}
    old_functions = _old_price_functions()
    models = {key: SIGNALS.COMPONENTS._book(ready, features[key], 60) for key, ready in inputs.items()}
    price_reference = {}
    original = next(item for item in SIGNALS.COMPONENTS.catalog() if item["id"] == "D016")["params"]
    for key, ready in inputs.items():
        peer_key = (key[0], "TOPIX" if key[1] == "NK225" else "NK225")
        model = models[key]
        peer = SIGNALS.COMPONENTS._peer(model, models[peer_key], ("ofi", "progress", "price_short"), 60)
        candidate, veto, _ = old_functions["candidates"](model, peer, "P02", original)
        held = old_functions["hold"](candidate, veto, model["time_s"], 120, 120)
        value = SIGNALS.COMPONENTS._asof(model["seq"], held, ready["seq"]).astype(np.int8)
        value[ready["time_s"] < ready["start"] + 1200] = 0
        value[~np.isfinite(ready["atr"]) | (ready["atr"] <= 0)] = 0
        price_reference[key] = value
    references["P02"] = price_reference
    counts = {}
    for name in SIGNALS.BASE_NAMES:
        row_count = 0
        for key, ready in inputs.items():
            event_values = parts[key][name][1 if name == "F32" else 4]
            value = SIGNALS.COMPONENTS._asof(parts[key]["seq"], event_values, ready["seq"]).astype(np.int8)
            value[ready["time_s"] < ready["start"] + 1200] = 0
            value[~np.isfinite(ready["atr"]) | (ready["atr"] <= 0)] = 0
            np.testing.assert_array_equal(value, references[name][key], err_msg=f"倍率1の再現不一致: {name}/{key}")
            row_count += len(value)
        counts[name] = dict(入力数=len(inputs), 一致方向要素=row_count)
    return counts


def mechanical_checks() -> dict:
    """機能: 反対票、優先切替、経過秒と同値時刻の扱いを具体例で確認する。

    引数: なし。返り値: 固定した論理例の検査結果 (dict)。
    """
    votes = np.array([[1, 1, 1, -1, 0], [1, 1, 0, -1, 0], [0, -1, 0, 0, 0]], dtype=np.int8)
    np.testing.assert_array_equal(SIGNALS._vote(votes, 2 / 3), [1, 0, 0, -1, 0])
    np.testing.assert_array_equal(SIGNALS._vote(votes, 1.), [0, 0, 0, 0, 0])
    votes9 = np.r_[np.ones((6, 1), dtype=np.int8), np.zeros((3, 1), dtype=np.int8)]
    np.testing.assert_array_equal(SIGNALS._vote(votes9, 2 / 3), [1])
    votes9[-1] = -1
    np.testing.assert_array_equal(SIGNALS._vote(votes9, 2 / 3), [0])
    values = np.array([[1, 1, 1, 0, 1], [0, -1, 0, 1, 0], [0, 0, 1, 0, 1], [0, 0, -1, 1, 1]], dtype=np.int8)
    np.testing.assert_array_equal(SIGNALS._combine(values, "D016_first"), [1, 0, 0, 1, 1])
    np.testing.assert_array_equal(SIGNALS._combine(values, "D056_first"), [1, 0, 0, 0, 1])
    np.testing.assert_array_equal(SIGNALS._combine(values, "price_and_flow"), [1, 0, 0, 1, 1])
    np.testing.assert_array_equal(SIGNALS._combine(values, "two_agree"), [0, 0, 0, 1, 1])
    candidate = np.array([1, 1, 1, 1, 1, 0, -1, -1, -1, -1], dtype=np.int8)
    times = np.array([0, 0, 0, 9, 10, 11, 12, 22, 143, 153.])
    np.testing.assert_array_equal(SIGNALS._confirm(candidate, times, 10), [0, 0, 0, 0, 1, 0, 0, -1, 0, -1])
    np.testing.assert_array_equal(SIGNALS._confirm(candidate, times, 0), candidate)
    return dict(反対票は拒否=True, 合意6票の整数閾値=True, 優先先と代替先を固定=True,
                行数でなく経過秒=True, 中立と逆方向で再確認=True, 観測欠落120秒超で再確認=True)


def _cut(inputs: dict, features: dict, cutoff: float) -> tuple[dict, dict]:
    """機能: 原本と公開済み特徴を同じ絶対時刻で切断する。

    引数: inputs/features (dict)、cutoff (float)。返り値: 切断した入力と特徴 (tuple[dict,dict])。
    """
    shorter, frames = {}, {}
    for key, ready in inputs.items():
        count = int(np.searchsorted(ready["time_s"], cutoff, side="right"))
        total = len(ready["seq"])
        shorter[key] = {name: value[:count].copy() if isinstance(value, np.ndarray) and value.ndim and len(value) == total else value for name, value in ready.items()}
        frame = features[key]
        frames[key] = frame.loc[(frame.time_s <= shorter[key]["time_s"][-1]) & (frame.seq <= shorter[key]["seq"][-1])].copy()
    return shorter, frames


def _future_change(inputs: dict, features: dict, cutoff: float) -> tuple[dict, dict]:
    """機能: 未来の価格・ATR・板数値だけを大きく変え、過去へ影響しないか調べる。

    引数: inputs/features (dict)、cutoff (float)。返り値: 未来改変した入力と特徴 (tuple[dict,dict])。
    """
    changed, frames = {}, {}
    for key, ready in inputs.items():
        modified = dict(ready)
        future = ready["time_s"] > cutoff
        for name in ("last", "atr"):
            modified[name] = ready[name].copy()
            modified[name][future] = modified[name][future] * 1.7 + 300
        changed[key] = modified
        frame = features[key].copy()
        future_feature = frame.time_s > cutoff
        for column in frame.select_dtypes(include="number").columns:
            if "time" in column or "seq" in column:
                continue
            frame[column] = frame[column].astype(float)
            frame.loc[future_feature, column] = frame.loc[future_feature, column] * 1.7 + 300
        frames[key] = frame
    return changed, frames


def causal_checks(inputs: dict, features: dict) -> dict:
    """機能: 全8方式・両窓集合を代表する条件と全有効近傍で過去方向を比較する。

    引数: inputs/features (dict)。返り値: 未来削除・未来改変の一致件数 (dict)。
    """
    catalog = SIGNALS.catalog()
    indices = [window * 48 + (mode % 2) * 24 + (mode % 3) * 8 + mode for window in (0, 1) for mode in range(8)]
    indices = sorted(set(indices + [1, 3, 9, 25]))
    specs = [catalog[index] for index in indices]
    variants = []
    for spec in specs:
        variants.append(spec)
        variants.extend(item for item in SIGNALS.neighbor_specs(spec) if item["applied"])
    chosen_sessions = ["2026-09-22_Night", "2026-09-29_Day"]
    record = dict(基準条件数=len(specs), 有効近傍を含む条件数=len(variants), 検査条件=[item["id"] for item in variants],
                  prefix比較数=0, 未来改変比較数=0, 方向要素=0, 不一致=[], 足ファイル不要=False)
    for session in chosen_sessions:
        pair = {key: value for key, value in inputs.items() if key[0] == session}
        frames = {key: features[key] for key in pair}
        SIGNALS.clear_cache()
        original_root = SIGNALS.COMPONENTS.LEGACY.ROOT
        try:
            SIGNALS.COMPONENTS.LEGACY.ROOT = HERE / "存在しない足データの検査先"
            full = {spec["id"]: SIGNALS.build(spec, pair, frames) for spec in variants}
            record["足ファイル不要"] = True
        finally:
            SIGNALS.COMPONENTS.LEGACY.ROOT = original_root
        start = max(value["time_s"][0] for value in pair.values())
        end = min(value["time_s"][-1] for value in pair.values())
        for fraction in (.27, .63):
            cutoff = float(np.floor((start + (end - start) * fraction) / 60) * 60)
            short, short_frames = _cut(pair, frames, cutoff)
            future, future_frames = _future_change(pair, frames, cutoff)
            for label, changed, changed_frames in (("prefix", short, short_frames), ("future", future, future_frames)):
                SIGNALS.clear_cache()
                for spec in variants:
                    produced = SIGNALS.build(spec, changed, changed_frames)
                    for key in pair:
                        count = len(short[key]["seq"])
                        np.testing.assert_array_equal(full[spec["id"]][key][:count], produced[key][:count],
                                                      err_msg=f"{label}: {session}/{spec['id']}/{key[1]}")
                        record["prefix比較数" if label == "prefix" else "未来改変比較数"] += 1
                        record["方向要素"] += count
            SIGNALS.clear_cache()
        print(f"{session} の切断・未来改変が一致", flush=True)
    return record


def main() -> None:
    """機能: 新損益を計算せず、固定した96条件の再現性と因果性を検査して保存する。

    引数: なし。返り値: なし (None)。
    """
    started = time.perf_counter()
    source_paths = [V25 / "discovery_signals.py", V25 / "d016_price_control.py", OLD / "signals.py"]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    SIGNALS.freeze_design()
    inputs = pickle.loads((OLD / "inputs.pkl").read_bytes())
    features = pickle.loads((OLD / "features_depth.pkl").read_bytes())
    nominal = nominal_check(inputs, features)
    print("倍率1の4基礎×全26入力が元方向と完全一致", flush=True)
    logic = mechanical_checks()
    seen, fingerprints, duplicates = {}, [], []
    for spec in SIGNALS.catalog():
        direction = SIGNALS.build(spec, inputs, features)
        fingerprint = SIGNALS.direction_hash(direction)
        record = dict(id=spec["id"], hash=fingerprint, 非中立原本行数=sum(int(np.count_nonzero(value)) for value in direction.values()))
        if fingerprint in seen:
            record["同一方向の先行条件"] = seen[fingerprint]
            duplicates.append(dict(id=spec["id"], same_as=seen[fingerprint]))
        else:
            seen[fingerprint] = spec["id"]
        fingerprints.append(record)
    structural = [dict(id=item["id"], category=item["diagnostic_category"], reason=item["skip_reason"])
                  for spec in SIGNALS.catalog() for item in SIGNALS.neighbor_specs(spec) if not item["applied"]]
    print(f"96条件の方向生成と重複確認: 一意{len(seen)}、重複{len(duplicates)}", flush=True)
    SIGNALS.clear_cache()
    causal = causal_checks(inputs, features)
    after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    assert before == after
    report = dict(新損益閲覧と計算=False, 現在API取得数=0, 固定条件数=96, 倍率1の基礎方向再現=nominal, 機械的論理=logic,
                  一意方向数=len(seen), 重複方向数=len(duplicates), 方向ハッシュ=fingerprints, 重複条件=duplicates,
                  構造上無効な近傍=structural, 因果監査=causal, 旧凍結コード不変=True, 旧凍結SHA256=before,
                  実行秒=round(time.perf_counter() - started, 3),
                  注意="同じ方向になる条件は独立の発見ではない。prefixは記録に対する因果性であり、実受信順の証明ではない。")
    (HERE / "ensemble_signal_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({name: report[name] for name in ("一意方向数", "重複方向数", "旧凍結コード不変", "実行秒")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
