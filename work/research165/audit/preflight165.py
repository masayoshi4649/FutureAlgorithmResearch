"""固定14条件の金融前証跡を集約する。登録・原板再生・実台帳操作は行わない。"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / "work/research165"
AUDIT = HERE / "audit"
ENGINE = HERE / "night_engine"
OUTPUT = AUDIT / "preflight165.json"
IDS = {f"NK225_U165_{number:02d}" for number in range(1, 15)}
SUFFIXES = {".go", ".mod", ".sum", ".toml", ".json"}


def read(path: Path):
    """有限値だけを許して JSON を読み取る。

    引数: path(Path)。返り値: dict 又は list。
    """
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    json.dumps(value, allow_nan=False)
    return value


def sha(path: Path) -> str:
    """ファイル内容の SHA-256 を逐次計算する。

    引数: path(Path)。返り値: str。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def resolve(path: str | Path) -> Path:
    """ルート相対の証跡パスを絶対パスへ揃える。

    引数: path(str 又は Path)。返り値: Path。
    """
    value = Path(path)
    return (value if value.is_absolute() else ROOT / value).resolve()


def record(path: Path) -> dict:
    """ルート相対パスと現時点の内容指紋を返す。

    引数: path(Path)。返り値: dict[str,str]。
    """
    path = path.resolve()
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path)}


def save_new(path: Path, value) -> None:
    """既存証跡を上書きせず新規保存する。

    引数: path(Path)、value(dict 又は list)。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def verify_records(values: list[dict]) -> None:
    """証跡に記載された現在版の内容指紋を全件照合する。

    引数: values(list[dict])。返り値: None。
    """
    for value in values:
        path = resolve(value["path"])
        assert sha(path) == value["sha256"], f"指紋不一致: {path}"


def require_success(path: Path, count: int | None = None) -> dict:
    """金融を実行していない完了証跡だけを受理する。

    引数: path(Path)、count(int 又は None)。返り値: dict。
    """
    proof = read(path)
    assert proof.get("passed") is True or proof.get("completed") is True, str(path)
    assert proof.get("returncode", 0) == 0, str(path)
    zero_keys = [key for key in ("financial_runs", "new_financial_replays") if key in proof]
    assert zero_keys and all(proof[key] == 0 for key in zero_keys), str(path)
    if count is not None:
        assert proof["artificial_tests"] == count, str(path)
    verify_records(proof.get("sources", []))
    if isinstance(proof.get("log"), dict):
        verify_records([proof["log"]])
    return proof


def control_module():
    """段階制御の純粋な読取関数を読み込む。登録関数は呼ばない。

    引数: なし。返り値: module。
    """
    spec = importlib.util.spec_from_file_location("control165_preflight", HERE / "control165.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def required_sources() -> set[Path]:
    """登録器が要求する全実装・定義・入力と監査補助源を集める。

    引数: なし。返り値: set[Path]。
    """
    values = {HERE / name for name in ("inputs165.json", "baseline165.json", "計画165.md",
        "control165.py", "registry165.py", "test_control165.py", "test_registry165.py")}
    values.add(Path(__file__).resolve())
    values.update(path for path in ENGINE.rglob("*") if path.is_file() and path.suffix in SUFFIXES)
    assert ENGINE / "configs165.json" in values, "固定14定義が未完成"
    return {path.resolve() for path in values}


def inspect_inputs(control) -> dict:
    """27夜の分割、基準入力、原資料指紋の内部対応を確認する。

    引数: control(module)。返り値: dict。
    """
    manifest = read(HERE / "inputs165.json")
    front = control.scenes_for_stage("train_validation")
    later = control.scenes_for_stage("confirmation")
    assert len(front) == 20 and len(later) == 7 and not set(front) & set(later)
    assert manifest["independent_unseen"] is False and manifest["us_market_data_used"] is False
    assert manifest["point_value"] == 10 and manifest["max_per_side"] == 100 and manifest["fees"] == 0
    baseline = read(HERE / "baseline165.json")
    assert baseline["method_id"] == "NK225_U164_00" and baseline["new_financial_replays"] == 0
    assert len(baseline["cases"]) == 27
    by_name = {case["scene"]["session"]: case for case in baseline["cases"]}
    assert len(by_name) == 27 and set(by_name) == set(front) | set(later)
    refs = 0
    for scene in list(front.values()) + list(later.values()):
        assert control.baseline_scene_matches(by_name[scene["session"]]["scene"], scene)
        expected = set(scene["books"].values())
        expected.update(path for values in scene["candles"].values() for path in values.values())
        actual = {item["path"] for item in scene["fingerprints"]}
        assert expected == actual and len(actual) == 6
        assert all(item["exists"] and len(item["sha256"]) == 64 for item in scene["fingerprints"])
        refs += len(actual)
    verify_records(manifest["sources"])
    verify_records(baseline["sources"])
    return {"nights": 27, "front_nights": 20, "confirmation_nights": 7,
        "raw_references": refs, "baseline_scene_inputs_equal": True,
        "raw_hash_reread_here": False, "raw_hash_gate": "登録後 driver が各場の前後で6原資料の内容指紋を再検査"}


def inspect_copy() -> dict:
    """旧164正本の不変と、起点関数名だけを変更したコピーを照合する。

    引数: なし。返り値: dict。
    """
    source = read(ENGINE / "コピー元165.json")
    assert source["financial_runs"] == 0 and len(source["files"]) == 87
    differences = []
    for item in source["files"]:
        old, new = resolve(item["source"]), resolve(item["copy"])
        assert sha(old) == item["sha256"], f"旧164正本が変更: {old}"
        if sha(new) != item["sha256"]:
            assert new.name == "main164.go", f"未申告の旧実装差: {new}"
            before, after = old.read_text(encoding="utf-8"), new.read_text(encoding="utf-8")
            assert before.count("func main()") == 1
            assert after == before.replace("func main()", "func legacyMain164R2()"), str(new)
            differences.append(new.name)
    assert differences == ["main164.go"]
    return {"old_files_unchanged": 87, "copies_byte_identical": 86,
        "entrypoint_only_rename": differences, "financial_condition_changes_in_old_source": 0}


def inspect_feature_outputs(feature_proof: Path, control) -> dict:
    """前20夜だけのラベル不使用計測と、最終特徴源への対応を確認する。

    引数: feature_proof(Path)、control(module)。返り値: dict。
    """
    provenance = require_success(feature_proof)
    assert provenance["labels_read"] is False
    assert provenance["confirmation_nights_read"] == 0
    assert provenance["training_nights"] == 20
    assert provenance["feature_semantics_unchanged"] is True
    latest_path = HERE / "features/最終源での状態分布再照合165.json"
    latest = read(latest_path)
    assert latest["completed"] is True and latest["financial_runs"] == 0
    assert latest["labels_read"] is False and latest["future_or_us_data"] is False
    previous_state = read(HERE / "features/前20夜の状態成立分布165.json")
    assert latest["sessions"] == previous_state["sessions"]
    assert latest["equal_session_quantiles"] == previous_state["equal_session_quantiles"]
    first = read(HERE / "features/前20夜の特徴分布165.json")
    assert first["equal_session_quantiles"] == latest["equal_session_quantiles"]
    for old, new in zip(first["sessions"], latest["sessions"]):
        assert old["Session"] == new["Session"] and old["Values"] == new["Values"]
        assert all(new["Counts"][key] == value for key, value in old["Counts"].items())
    front = control.scenes_for_stage("train_validation")
    results = []
    for name in ("前20夜の特徴分布165.json", "前20夜の状態成立分布165.json"):
        path = HERE / "features" / name
        value = read(path)
        assert value["completed"] is True and value["financial_runs"] == 0
        assert value["labels_read"] is False and value["future_or_us_data"] is False
        assert value["manifest_sha256"] == sha(HERE / "inputs165.json")
        assert len(value["sessions"]) == 20
        assert {item["Session"] for item in value["sessions"]} == set(front)
        for item in value["sessions"]:
            scene = front[item["Session"]]
            assert item["Path"] == scene["books"]["NK225"]
            raw = next(row for row in scene["fingerprints"] if row["path"] == item["Path"])
            assert item["SHA256"] == raw["sha256"]
            assert item["SourceBefore"] == item["SourceAfter"]
            assert item["SizeBefore"] == item["SizeAfter"]
        results.append(record(path))
    return {"labels_read": False, "confirmation_nights_read": 0, "training_nights": 20,
        "new_measurement_runs_here": 0, "future_or_us_data": False,
        "provenance": record(feature_proof), "outputs": results,
        "final_source_remeasurement": record(latest_path), "independent_saved_values_equal": True,
        "historical_proof": record(HERE / "features/特徴計測証跡165.json"),
        "note": "計測時の古い driver 指紋を最終版一致と読み替えず、別証跡で特徴意味の不変を確認"}


def run_artificial(command: list[str], cwd: Path, log: Path) -> dict:
    """引数固定の人工試験又は定義出力だけを実行しログを保存する。

    引数: command(list[str])、cwd(Path)、log(Path)。返り値: dict。
    """
    assert command[0] in {"go", sys.executable}
    assert (command[:3] == ["go", "test", "-json"] or
        command[:4] == ["go", "run", ".", "-export-configs"] or
        command[1:4] == ["-m", "unittest", "discover"]), command
    environment = os.environ.copy()
    environment.update({"CGO_ENABLED": "0", "PYTHONIOENCODING": "utf-8"})
    with log.open("x", encoding="utf-8", newline="\n") as stream:
        completed = subprocess.run(command, cwd=cwd, env=environment, stdout=stream,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", timeout=600)
    assert completed.returncode == 0, f"人工失敗: {log}"
    return {"command": command, "returncode": completed.returncode, "log": record(log)}


def inspect_config_hashes(values: list[dict]) -> dict:
    """Goの構造体順 JSON から14個の定義指紋を別式で再計算する。

    引数: values(list[dict])。返り値: dict。
    """
    assert len(values) == 14 and {value["id"] for value in values} == IDS
    hashes = {}
    for value in values:
        copied = dict(value)
        copied["rule_hash"] = ""
        raw = json.dumps(copied, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        for text, replacement in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"),
            ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
            raw = raw.replace(text, replacement)
        calculated = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        assert calculated == value["rule_hash"], value["id"]
        assert value["scope"] == "PostUS"
        hashes[value["id"]] = calculated
    assert len(set(hashes.values())) == 14
    return hashes


def execute(args) -> dict:
    """最終凍結と独立合格を確認してから金融前の集約証跡を作る。

    引数: args(argparse.Namespace)。返り値: dict。
    """
    assert args.finalize, "作者と独立レビュアーの凍結後だけ --finalize で実行"
    assert not OUTPUT.exists(), "確定済み preflight を上書きしない"
    assert not (HERE / "登録受領165.json").exists(), "登録後に金融前証跡を作り直さない"
    for stage in ("train_validation", "confirmation"):
        assert not list((HERE / "results" / stage).glob("*.json")), "新条件金融結果が既に存在"
    author_path, reviewer_path, feature_path = map(resolve,
        (args.author_proof, args.reviewer_proof, args.feature_proof))
    author = require_success(author_path)
    reviewer = require_success(reviewer_path)
    assert author["source_frozen"] is True
    assert reviewer["plan_sha256"] == sha(HERE / "計画165.md")
    assert reviewer["tests"]["pass"] is True and reviewer["tests"]["count"] >= 10
    control_proof = require_success(AUDIT / "制御人工165.json", 16)
    registry_proof = require_success(AUDIT / "仮台帳の保存と復元検査165.json", 15)
    for proof in (control_proof, registry_proof):
        assert proof["actual_registration_calls"] == proof["actual_registry_reads"] == proof["actual_registry_writes"] == 0

    # ----------------------------------------
    # 現在版の源と、過去の計測結果を区別して照合する。
    control = control_module()
    input_checks = inspect_inputs(control)
    copy_checks = inspect_copy()
    feature_checks = inspect_feature_outputs(feature_path, control)
    sources = required_sources()
    sources.update((author_path, reviewer_path, feature_path, AUDIT / "制御人工165.json",
        AUDIT / "仮台帳の保存と復元検査165.json", HERE / "features/特徴計測証跡165.json"))
    sources.update(resolve(value["path"]) for value in feature_checks["outputs"])
    sources.add(resolve(feature_checks["final_source_remeasurement"]["path"]))
    for proof in (author, reviewer, control_proof, registry_proof):
        sources.update(resolve(value["path"]) for value in proof.get("sources", []))
    initial = {path: sha(path) for path in sources}
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = AUDIT / "preflight_runs" / stamp
    run_dir.mkdir(parents=True, exist_ok=False)

    # ----------------------------------------
    # 原板を読まない人工試験と、金融0の構造定義出力だけを実行する。
    go_test = run_artificial(["go", "test", "-json", "-count=1", "./..."], ENGINE, run_dir / "Go全人工.jsonl")
    test_events = [json.loads(line) for line in resolve(go_test["log"]["path"]).read_text(encoding="utf-8").splitlines() if line.startswith("{")]
    passed_tests = [item for item in test_events if item.get("Action") == "pass" and item.get("Test")]
    assert passed_tests and not any(item.get("Action") == "fail" for item in test_events)
    reviewer_tests = [item["Test"] for item in passed_tests if item["Test"].startswith("TestAdversary165")]
    assert len(reviewer_tests) >= reviewer["tests"]["count"]
    go_test.update({"passed_tests": len(passed_tests), "independent_layer_tests": reviewer_tests})
    python_test = run_artificial([sys.executable, "-m", "unittest", "discover", "-s",
        "work/research165", "-p", "test_*165.py", "-v"], ROOT, run_dir / "管理制御人工.log")
    python_text = resolve(python_test["log"]["path"]).read_text(encoding="utf-8")
    assert "Ran 31 tests" in python_text and "\nOK\n" in python_text
    python_test["passed_tests"] = 31
    dump_path = run_dir / "実コード14定義.json"
    dump = run_artificial(["go", "run", ".", "-export-configs", str(dump_path)], ENGINE, run_dir / "定義出力.log")
    assert read(dump_path) == control.configs(), "固定JSONと実コードの定義差"
    hashes = inspect_config_hashes(read(dump_path))
    dump.update({"output": record(dump_path), "rule_hashes": hashes})
    for path, before in initial.items():
        assert sha(path) == before, f"最終検査中の並行変更: {path}"
    assert required_sources() <= sources, "最終検査中に必要な実装ファイルが増加"
    sources.update((resolve(go_test["log"]["path"]), resolve(python_test["log"]["path"]),
        resolve(dump["log"]["path"]), dump_path))
    proof = {"passed": True, "returncode": 0, "created_at": datetime.now().astimezone().isoformat(),
        "new_financial_replays": 0, "financial_runs": 0, "actual_registration_calls": 0,
        "actual_registry_reads": 0, "actual_registry_writes": 0, "market_raw_reads": 0,
        "registered": False, "source_frozen": True, "methods": 14, "comparison_methods": 15,
        "financial_cases_planned": 378, "known_development": True, "independent_unseen": False,
        "sources": [record(path) for path in sorted(sources)], "inputs": input_checks,
        "source_164": copy_checks, "features": feature_checks,
        "author": record(author_path), "independent_review": record(reviewer_path),
        "control_artificial": record(AUDIT / "制御人工165.json"),
        "registry_artificial": record(AUDIT / "仮台帳の保存と復元検査165.json"),
        "tests": {"go": go_test, "management": python_test, "config_dump": dump},
        "limitations": ["価格時計は受信時計ではない。同時計の原行順を使用する。",
            "表示数量回復は取消・約定・補充を識別する証拠ではない。",
            "後7夜を含む27夜は既知資料。独立未見の有効性確認とは称さない。",
            "本証跡は金融前の人工・構造・指紋確認。新候補の利益や安定性は未測定。"]}
    save_new(OUTPUT, proof)
    return {"passed": True, "path": record(OUTPUT)["path"], "sha256": sha(OUTPUT),
        "source_count": len(sources), "new_financial_replays": 0}


def main() -> None:
    """完了証跡の明示指定を必須にして最終監査を開始する。

    引数: CLI 引数。返り値: None。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--author-proof", required=True)
    parser.add_argument("--feature-proof", required=True)
    parser.add_argument("--reviewer-proof", default="work/research165/review/独立実装レビュー165.json")
    args = parser.parse_args()
    print(json.dumps(execute(args), ensure_ascii=False))


if __name__ == "__main__":
    main()
