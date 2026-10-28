"""隔離した研究ソースへ独立人工試験だけを追加し、原板再生なしで検証する。"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work/audit159"
SOURCE = ROOT / "work/night159/engine_go"


def sha(path: Path) -> str:
    """内容指紋を返す。

    引数: path(Path)は読取対象。返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """実装を隔離コピーして人工試験だけを実行する。

    引数: なし。返り値: None。元ソース・原資料・共有台帳へ書き込まない。
    """
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    target = WORK / ("engine人工_" + stamp)
    fingerprints = []
    for path in sorted(SOURCE.rglob("*")):
        if not path.is_file() or path.suffix not in {".go", ".mod", ".sum", ".toml"}:
            continue
        rel = path.relative_to(SOURCE)
        out = target / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        before = sha(path)
        shutil.copyfile(path, out)
        assert before == sha(out) == sha(path), str(path)
        fingerprints.append({"path": str(path.relative_to(ROOT)), "sha256": before})
    shutil.copyfile(WORK / "independent159_test.go", target / "independent159_test.go")
    subprocess.run(["gofmt", "-w", "independent159_test.go"], cwd=target, check=True)
    run = subprocess.run(["go", "test", ".", "-v", "-count=1"], cwd=target, capture_output=True, text=True, encoding="utf-8")
    log = WORK / ("独立人工検査159_" + stamp + ".log")
    log.write_text(run.stdout + run.stderr, encoding="utf-8")
    unchanged = all(sha(ROOT / v["path"]) == v["sha256"] for v in fingerprints)
    result = {"passed": run.returncode == 0, "returncode": run.returncode, "created_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(), "source_unchanged": unchanged,
              "command": ["go", "test", ".", "-v", "-count=1"], "scope": "共有人工試験＋独立人工試験のみ。市場原板・保存相場fixture・金融mainは未実行。",
              "new_financial_replays": 0, "existing_fixture_replays": 0,
              "passed_tests": [x.split(" ")[2] for x in run.stdout.splitlines() if x.startswith("--- PASS:")],
              "isolation": str(target.relative_to(ROOT)), "log": str(log.relative_to(ROOT)), "log_sha256": sha(log), "source_fingerprints": fingerprints}
    (WORK / "独立人工検査159.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in {"source_fingerprints"}}, ensure_ascii=False))
    if run.returncode:
        print(run.stdout + run.stderr)
        raise SystemExit(run.returncode)


if __name__ == "__main__":
    main()
