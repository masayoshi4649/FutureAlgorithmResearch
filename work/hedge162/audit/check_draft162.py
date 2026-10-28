"""初稿の独立人工検査とruntime準備の根拠を保存する。金融再生は行わない。"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def digest(path: Path) -> str:
    """資料内容のSHA256を返す。

    引数: path(Path)。返り値: str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """実資料を使わない人工検査を実行して、最終合格とは別に記録する。

    引数: なし。返り値: None。
    """
    base = Path(__file__).resolve().parents[1]
    root = base.parents[1]
    source = base / "engine/state162.py"
    test = base / "audit/test_state_independent162.py"
    before = digest(source)
    result = subprocess.run([sys.executable, "-X", "utf8", str(test)], capture_output=True,
                            text=True, encoding="utf-8", cwd=root, check=False)
    after = digest(source)
    record = {
        "created_at": datetime.now().astimezone().isoformat(),
        "scope": "仕様確定前の人工検査。金融評価・登録前合格の代用にはしない。",
        "passed": result.returncode == 0 and before == after,
        "financial_runs": 0, "artificial_tests": 5,
        "source": str(source.relative_to(root)), "source_sha256": before,
        "source_unchanged": before == after, "test_sha256": digest(test),
        "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
    }
    (base / "audit/独立人工初稿162.json").write_text(json.dumps(record, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    # ----------------------------------------
    # ランタイムと読了資料を記録するだけで、Workbookもmarkerも実行しない。
    skill = Path("C:/Users/masay/.codex/plugins/cache/openai-primary-runtime/spreadsheets/26.1017.22136/skills/spreadsheets")
    docs = ["SKILL.md", "workflows/create_workflows.md", "artifact_tool_docs/API_QUICK_START.md",
            "style_guidelines.md", "domain_guidance/scientific_research.md"]
    runtime = Path("C:/Users/masay/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules")
    prepared = {
        "created_at": record["created_at"], "marker_executions": 0, "workbook_created": False,
        "artifact_runtime": str(runtime / "@oai/artifact-tool"),
        "runtime_exists": (runtime / "@oai/artifact-tool").is_dir(),
        "junction": str(base / "report/node_modules"),
        "junction_target": str((base / "report/node_modules").resolve()),
        "marker": str(skill / "container_tools/mark_artifact_operation_started.mjs"),
        "read_documents": [{"path": str(skill / name), "sha256": digest(skill / name)} for name in docs],
    }
    (base / "report/runtime準備162.json").write_text(json.dumps(prepared, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"passed": record["passed"], "financial_runs": 0, "artificial_tests": 5,
                      "source_unchanged": record["source_unchanged"], "marker_executions": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
