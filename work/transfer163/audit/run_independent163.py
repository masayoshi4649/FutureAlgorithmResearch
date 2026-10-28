"""研究00163の隔離コピーで人工試験だけを実行する。"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[3]
WORK = Path(__file__).resolve().parent
SOURCE = WORK.parent / "engine"


def sha(path: Path) -> str:
    """対象ファイルの内容指紋を計算する。

    引数: path(Path)は対象ファイル。返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """元源を変更せず、共有人工と独立人工を実行する。

    引数: なし。返り値: None。相場資料、金融main、保存相場fixtureを実行しない。
    """
    independent = WORK / "independent163_test.go"
    if not independent.is_file():
        raise RuntimeError("独立人工の実装前です")
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = WORK / ("engine人工_" + stamp)
    sources = []
    for path in sorted(SOURCE.rglob("*")):
        if not path.is_file() or path.suffix not in {".go", ".mod", ".sum", ".toml", ".json"}:
            continue
        if "testdata" in path.parts:
            continue
        relative = path.relative_to(SOURCE)
        copied = target / relative
        copied.parent.mkdir(parents=True, exist_ok=True)
        before = sha(path)
        shutil.copyfile(path, copied)
        assert sha(copied) == sha(path) == before
        sources.append({"path": path.relative_to(ROOT).as_posix(), "sha256": before})
    shutil.copyfile(independent, target / independent.name)
    hook = WORK / "人工予約補助163.go"
    shutil.copyfile(hook, target / "internal/strategy/independent_seed163.go")
    subprocess.run(["gofmt", "-w", independent.name], cwd=target, check=True)

    # ----------------------------------------
    # 金融mainを呼ばず、明示した人工試験名だけを実行する。
    command = ["go", "test", ".", "-run", "Test.*163|TestPhaseTransitionsArtificial159|TestNamespaceAndRegistration159", "-v", "-count=1"]
    run = subprocess.run(command, cwd=target, capture_output=True, text=True, encoding="utf-8")
    log = WORK / ("独立人工検査163_" + stamp + ".log")
    log.write_text(run.stdout + run.stderr, encoding="utf-8")
    unchanged = all(sha(ROOT / row["path"]) == row["sha256"] for row in sources)
    passed_tests = [line.split(" ")[2] for line in run.stdout.splitlines() if line.startswith("--- PASS:")]
    output = {
        "passed": run.returncode == 0 and unchanged and bool(passed_tests),
        "returncode": run.returncode,
        "created_at": dt.datetime.now().astimezone().isoformat(),
        "scope": "共有人工と独立人工のみ。新金融再生・相場fixture再生・API取得なし。",
        "financial_runs": 0,
        "existing_fixture_runs": 0,
        "source_unchanged": unchanged,
        "command": command,
        "isolation": target.relative_to(ROOT).as_posix(),
        "passed_tests": passed_tests,
        "log": log.relative_to(ROOT).as_posix(),
        "log_sha256": sha(log),
        "sources": sources,
    }
    result = WORK / "独立人工検査163.json"
    result.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in output.items() if key != "sources"}, ensure_ascii=False))
    if not output["passed"]:
        print(run.stdout + run.stderr)
        raise SystemExit(run.returncode or 1)


if __name__ == "__main__":
    main()
