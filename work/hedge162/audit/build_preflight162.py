"""金融原資料を再生せず、最終源・人工検査・段階制御の独立監査証跡を固定する。"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


def digest(path: Path) -> str:
    """内容指紋を返す。

    引数: path(Path)。返り値: str。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    """共有19・制御5・独立12人工と凍結源の不変性を記録する。

    引数: なし。返り値: None。新金融再生・登録・現在API取得は0。
    """
    here = Path(__file__).resolve().parent
    work = here.parent
    root = work.parents[1]
    target = here/"preflight162.json"
    assert not target.exists(), "最終事前監査を上書きしない"
    paths = [p for p in (work/"engine").iterdir() if p.is_file() and p.suffix in {".py", ".json", ".md"}]
    paths += [work/name for name in ("inputs162.json", "計画162.md", "prepare162.py", "register162.py",
                                    "allow162.py", "freeze162.py", "complete162.py", "test_control162.py")]
    paths += [here/"test_state_independent162.py", Path(__file__), here/"監査方針162.md"]
    paths += [p for p in (work/"measure").iterdir() if p.is_file() and p.suffix in {".py", ".json", ".md"}]
    paths.append(root/"work/entry161/results/selection_frozen161.json")
    paths = sorted(set(paths))
    before = {p: digest(p) for p in paths}
    commands = [([sys.executable, "-X", "utf8", "-m", "unittest", "discover", "-s", "work/hedge162/engine", "-p", "test_*.py", "-v"], 19),
                ([sys.executable, "-X", "utf8", "work/hedge162/test_control162.py", "-v"], 5),
                ([sys.executable, "-X", "utf8", "work/hedge162/audit/test_state_independent162.py"], 12)]
    tests = []
    for args, expected in commands:
        result = subprocess.run(args, cwd=root, capture_output=True, encoding="utf-8", check=False)
        text = result.stdout+result.stderr
        found = re.search(r"Ran (\d+) tests?", text)
        count = int(found.group(1)) if found else None
        tests.append({"command": args, "returncode": result.returncode, "tests": count,
                      "expected_tests": expected, "passed": result.returncode == 0 and count == expected,
                      "output": text})
    # ----------------------------------------
    # 入力とコピー源の同一性だけを確認し、原板・将来ラベルは開かない。
    manifest = json.loads((work/"inputs162.json").read_text(encoding="utf-8"))
    scenes = manifest["sessions"]
    assert len(scenes) == 53 and len({s["session"] for s in scenes}) == 53
    assert Counter(s["split"] for s in scenes) == {"train": 30, "validation": 10, "test": 13}
    assert Counter(s["kind"] for s in scenes) == {"Day": 27, "Night": 26}
    assert digest(work/"engine/source161_features.py") == manifest["market_reader"]["sha256"]
    assert digest(work/"engine/source161_rules.py") == next(v["sha256"] for v in manifest["signal_implementation"] if v["path"].endswith("rules161.py"))
    assert digest(root/manifest["signal_source"]["path"]) == manifest["signal_source"]["sha256"]
    assert all("/features/" in s["features"].replace("\\", "/") for s in scenes)
    configs = json.loads((work/"engine/configs162.json").read_text(encoding="utf-8"))
    assert len(configs) == 26 and sum(bool(c["cover"]) for c in configs) == 24
    assert not list((work/"results").glob("*/再生完了162_*.json"))
    unchanged = all(digest(p) == h for p, h in before.items())
    output = {
        "created_at": datetime.now().astimezone().isoformat(),
        "passed": all(t["passed"] for t in tests) and unchanged,
        "new_strategy_financial_evaluations": 0,
        "current_api_requests": 0, "raw_market_replays": 0,
        "artificial_tests": sum(t["tests"] or 0 for t in tests), "tests": tests,
        "sources_unchanged": unchanged,
        "sources": [{"path": p.relative_to(root).as_posix(), "sha256": h} for p, h in before.items()],
        "input_qualification": {"sessions": 53, "Day": 27, "Night": 26, "train": 30,
                                "validation": 10, "test": 13, "source_copies_match": True,
                                "feature_file_sha_verified_by_driver": True,
                                "no_future_labels_in_driver": True},
        "reviewed_analysis_source": {"path": "work/hedge162/aggregate162.py", "sha256": digest(work/"aggregate162.py")},
        "fixed_issues": ["前40場と選択凍結後13場の段階実行を分離", "因果特徴NPZを目録の固定SHAへ直接照合",
                         "同値板省略中もカバー枠不足の原行数を一致", "場末代理の価格原行をreferenceへ収録"],
        "checks": ["実保有と新規予約を含む片側10枚・親所有・反対新主の空き配分",
                   "同時計の次正常原行・BBO執行・各約定前後の全玉現金恒等式",
                   "中値段アンカーと実建値分離・即追尾の負spread初期ピーク",
                   "360秒代理資格・未約定新規取消・既返済予約の一回置換",
                   "26条件の高速版と逐次版の全出力・root集計器との人工接続",
                   "固定モデルの未来行変更で過去信号不変・段階許可/凍結/順位schema"],
        "limitations": ["原板時計は受信時計ではない。同時計内は採用原行順に限定",
                        "ラージBBOをminiの約定代理へ使用し、実注文の充足を保証しない",
                        "全53場の終端は直前6分BBOの代理精算。通常の次板約定と別扱い",
                        "後半13場も既知の追加開発資料で、真の未見検証ではない",
                        "人工合格は利益の有効性を示さない。金融後に原板全時価と保存会計を別検算"]
    }
    with target.open("x", encoding="utf-8") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"passed": output["passed"], "artificial_tests": output["artificial_tests"],
                      "sources": len(before), "sha256": digest(target), "financial_evaluations": 0}, ensure_ascii=False))
    if not output["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
