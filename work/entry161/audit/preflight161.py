"""原資料採点前に人工試験と固定源の独立監査証跡を作る。"""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]


def sha(path: Path) -> str:
    """ファイルの内容指紋を算出する。

    引数: path(Path)。返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """全人工試験に合格した確定源だけを登録ゲートへ渡す。

    引数: なし。返り値: None。原板の先着採点・試行台帳更新はしない。
    """
    target = HERE / "preflight161.json"
    assert not target.exists(), "既存監査を上書きしない"
    assert not (WORK/"登録受領161.json").exists(), "登録前の監査専用"
    assert not list(WORK.rglob("*.npz")), "実資料抽出前の監査専用"
    assert (WORK/"search/spec161.json").exists()
    assert list((WORK/"features").glob("*.md")) and list((WORK/"features").glob("*.json")), "特徴仕様の確定を待つ"
    files = sorted(p for directory in [WORK/"features", WORK/"search"] for p in directory.rglob("*")
                   if p.is_file() and p.suffix in {".py", ".md", ".json"})
    files += [WORK/name for name in ["inputs161.json", "計画.md", "参考研究.md", "prepare161.py", "register161.py", "allow161.py"]]
    files += sorted(HERE.glob("*.py"))
    files += [HERE/name for name in ["53場原板の入力不変161.json", "新目録と時系列分割の照合161.json", "監査方針と関連既知161.md"]]
    before = {str(path.relative_to(ROOT)).replace("\\", "/"): sha(path) for path in files}
    tests = [WORK/"features/test_features161.py", WORK/"search/test_engine161.py",
             HERE/"test_features_independent161.py", HERE/"test_search_independent161.py", HERE/"test_allow_independent161.py"]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    runs = []
    for n, test in enumerate(tests, 1):
        run = subprocess.run([sys.executable, str(test)], cwd=ROOT, env=env, text=True,
                             encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        log = HERE / f"人工最終検査161_{n}.log"
        log.write_text(run.stdout, encoding="utf-8")
        found = re.search(r"Ran (\d+) tests?", run.stdout)
        assert run.returncode == 0 and found and re.search(r"\bOK\b", run.stdout), (test, run.stdout[-2000:])
        runs.append(dict(path=test.relative_to(ROOT).as_posix(), tests=int(found.group(1)), returncode=run.returncode,
                         log=log.relative_to(ROOT).as_posix(), log_sha256=sha(log)))
    for path, expected in before.items():
        assert sha(ROOT/path) == expected, path
    source_spec = json.loads((WORK/"search/spec161.json").read_text(encoding="utf-8-sig"))
    assert source_spec["candidate_count"] == 34
    for record in source_spec["implementation"]:
        assert sha(WORK/"search"/record["file"]) == record["sha256"]
    inputs = json.loads((HERE/"53場原板の入力不変161.json").read_text(encoding="utf-8-sig"))
    assert inputs["passed"] and inputs["raw_files"] == 106
    for record in inputs["files"]:
        now = Path(record["path"]).stat()
        assert (now.st_size, now.st_mtime_ns) == (record["bytes"], record["mtime_ns"]), record["path"]
    output = {
        "passed": True, "created_at": datetime.now().astimezone().isoformat(),
        "candidate_financial_measurements": 0, "new_candidate_evaluations": 0, "raw_extractions": 0,
        "financial_replays": 0, "api_calls": 0, "candidate_count": 34,
        "scope": {"sessions": 53, "Day": 27, "Night": 26, "train": 30, "validation": 10, "test": 13},
        "tests": runs, "tests_total": sum(run["tests"] for run in runs),
        "independent_tests": sum(run["tests"] for run in runs[2:]),
        "raw_full_hash_verification": {"path": "work/entry161/audit/53場原板の入力不変161.json", "files": 106, "bytes": inputs["full_read_bytes"], "metadata_still_unchanged": True},
        "sources": [dict(path=path, sha256=value) for path, value in sorted(before.items())],
        "resolved_findings": [
            "特徴/ラベルNPZのsplit階層が探索側と不一致→生成器schemaの結合人工で訂正確認",
            "phase数値0/1/2と探索文字列の不一致→読込時正規化を人工確認",
            "decision_time一致検査の不足→必須時刻一致と不一致拒否を人工確認",
            "失敗登録の許可段階だけで通過→registered true/整数終了0の明示を人工確認",
            "testラベルを選択凍結前に抽出可能→選択/モデル内容SHAと段階許可を人工確認",
        ],
        "accepted_boundaries": [
            "CurrentPriceTimeは受信時計でなく、自己原行prefixと相手strict過去代表での代理同期",
            "過去端は15秒遅れを許容。指定5秒窓が最大20秒の実変化となり得る。速度は実経過で規格化",
            "不正板を挟む端点価格変化は連続経路保証と区別し、品質を別記",
            "表示数量回復/OFIは代理であり注文ID・実補充・成行方向の直接観測ではない",
            "未決lockは候補×phaseごと。前後予測が重なり得るため単一非重複戦略の成績としない",
            "候補34×3時間区分の選択。後13場は今回選択に未使用だが過去研究では既知",
            "未決/次気配なしを主分母から除外しない。Last補助や反対向き結果を選択へ使わない",
            "候補確率のみ。金額PL・実行可能な約定保証・連続市場の先着保証を示さない",
        ],
        "open_blockers": [],
    }
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(dict(passed=True, tests_total=output["tests_total"], independent_tests=output["independent_tests"], sources=len(before), preflight_sha256=sha(target)), ensure_ascii=False))


if __name__ == "__main__":
    main()
