"""金融を実行せず隔離コピーで共有・独立人工とGo制御器接続を確認する。"""
from __future__ import annotations

import copy
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / "work/research164"
AUDIT = HERE / "audit"


def sha(path: Path) -> str:
    """内容指紋を返す。

    引数: path(Path)。返り値: str。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path: Path, value) -> None:
    """監査成果をUTF-8で保存する。

    引数: path(Path)、value(dict等)。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def record(path: Path) -> dict:
    """相対パスと指紋を返す。

    引数: path(Path)。返り値: dict。
    """
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path)}


def execute(args: list[str], cwd: Path, env: dict, log: Path) -> None:
    """人工検査を実行して全出力を保存する。

    引数: args(list[str])、cwd(Path)、env(dict)、log(Path)。返り値: None。
    """
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, encoding="utf-8", errors="replace")
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == 0, (result.returncode, str(log))


def control_connection(fixture: Path, base: Path) -> dict:
    """Go出力の実構造を人工40場へ複製して制御器に接続する。

    引数: fixture(Path)、base(Path)。返り値: dict。実市場再生や登録は行わない。
    """
    spec = importlib.util.spec_from_file_location("独立制御164", HERE / "control164.py")
    control = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(control)
    original = json.loads(fixture.read_text(encoding="utf-8"))
    manifest = json.loads((HERE / "inputs164.json").read_text(encoding="utf-8"))
    stage = "train_validation"
    control.HERE = base
    control.MANIFEST = base / "inputs164.json"
    control.SPEC = base / "計画164.md"
    control.CONFIGS = base / "configs164.json"
    write(control.MANIFEST, manifest)
    write(control.CONFIGS, original["configs"])
    control.SPEC.write_text("人工の型接続だけ。売買成績ではない。\n", encoding="utf-8")
    folder = base / "results" / stage
    folder.mkdir(parents=True)
    files = []
    for scene in manifest["sessions"]:
        if scene["split"] not in ("train", "validation"):
            continue
        obj = copy.deepcopy(original[scene["kind"].lower()])
        obj["scene"] = scene
        path = folder / (scene["session"] + ".json")
        write(path, obj)
        files.append(dict(session=scene["session"], **record(path)))
    proof = dict(completed=True, returncode=0, sources_unchanged=True, sessions=40, cases=400,
        stage=dict(stage=stage, manifest_sha256=sha(control.MANIFEST), spec_sha256=sha(control.SPEC), configs_sha256=sha(control.CONFIGS)), results=files,
        artificial_only=True, new_financial_replays=0)
    proof_path = folder / "再生完了164_train_validation.json"
    write(proof_path, proof)
    checked, results = control.stage_results(stage)
    assert len(results) == 40 and sum(len(row["cases"]) for row in results) == 400
    changed = ROOT / files[0]["path"]
    original_bytes = changed.read_bytes()
    rejected = []
    for mutation in ("同ID内の条件変更", "同場の時計変更", "同場の原資料差替え"):
        obj = json.loads(original_bytes)
        if mutation == "同ID内の条件変更":
            obj["cases"][0]["config"]["scope"] = "PreUS"
        elif mutation == "同場の時計変更":
            obj["scene"]["start"] += 1
        else:
            obj["scene"]["books"]["NK225"] = "別資料"
        write(changed, obj)
        files[0]["sha256"] = sha(changed)
        write(proof_path, proof)
        try:
            control.stage_results(stage)
        except AssertionError:
            rejected.append(mutation)
        else:
            raise AssertionError("改変を受理: " + mutation)
    changed.write_bytes(original_bytes)
    files[0]["sha256"] = sha(changed)
    write(proof_path, proof)
    control.stage_results(stage)
    return dict(passed=True, artificial_scenes=40, artificial_cases=400, rejected=rejected, fixture=record(fixture), financial_replays=0)


def main() -> None:
    """最終コピーの検査と原版不変確認を保存する。

    引数: なし。返り値: None。
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    engine = HERE / "engine"
    source_paths = [p for p in engine.rglob("*") if p.is_file() and p.suffix in {".go", ".mod", ".sum", ".toml", ".json"} and "testdata" not in p.parts]
    sources = [record(p) for p in sorted(source_paths)]
    isolated = AUDIT / ("final_isolated_" + stamp)
    shutil.copytree(engine, isolated)
    shutil.copyfile(AUDIT / "independent164_test.go", isolated / "independent164_test.go")
    fixture = AUDIT / ("Go人工出力164_" + stamp + ".json")
    env = dict(os.environ, CGO_ENABLED="0", AUDIT164_FIXTURE=str(fixture))
    env.pop("EXPORT_DAY164_CONFIGS", None)
    go_log = AUDIT / ("最終人工Go164_" + stamp + ".jsonl")
    execute(["go", "test", "./...", "-count=1", "-json"], isolated, env, go_log)
    py_log = AUDIT / ("最終人工制御164_" + stamp + ".log")
    execute(["python", "test_control164.py"], HERE, env, py_log)
    connection = control_connection(fixture, AUDIT / ("control_fixture_" + stamp))
    assert sources == [record(p) for p in sorted(source_paths)], "検査中に元実装が変更された"
    events = [json.loads(line) for line in go_log.read_text(encoding="utf-8").splitlines() if line.startswith("{")]
    passed_tests = [e["Test"] for e in events if e.get("Action") == "pass" and e.get("Test")]
    value = dict(passed=True, created_at=datetime.now().astimezone().isoformat(), financial_replays=0,
        test_count=len(passed_tests), independent_tests=[name for name in passed_tests if name.startswith("TestIndependent")],
        all_tests=passed_tests, go_log=record(go_log), python_log=record(py_log), connection=connection,
        isolated_copy=isolated.relative_to(ROOT).as_posix(), sources=sources, source_unchanged=True)
    write(AUDIT / "最終人工独立検査164.json", value)
    print(json.dumps({k:value[k] for k in ("passed", "test_count", "independent_tests", "source_unchanged", "financial_replays")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
