"""第二巡の人工監査と資料不変を記録する。金融再生・原板読込は行わない。"""

from pathlib import Path
from datetime import datetime
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "work/audit159"
SOURCE = ROOT / "work/night159/round2/engine_go"
COPY = AUDIT / "round2_engine"


def sha(path: Path) -> str:
    """ファイルの内容指紋を求める。

    引数: path(Path)。返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files_at(path: Path) -> list[Path]:
    """研究実装のGo・TOMLと依存定義を列挙する。

    引数: path(Path)。返り値: list[Path]は固定順。
    """
    return sorted(p for p in path.rglob("*") if p.is_file() and (p.suffix in [".go", ".toml"] or p.name in ["go.mod", "go.sum"]))


def main() -> None:
    """最終共有源と監査コピーを照合し、人工テストと初巡不変を保存する。

    引数: なし。返り値: None。失敗時はpassed=falseを保存し非0終了。
    """
    source_files = files_at(SOURCE)
    signatures = [{"path": str(p.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(p)} for p in source_files]
    for path in source_files:
        assert sha(path) == sha(COPY / path.relative_to(SOURCE)), f"独立コピー不一致:{path}"
    specs = [SOURCE.parent / n for n in ["configs159r2.json", "spec159r2.json", "実装仕様159r2.md", "inputs159r2.json"]]
    for path in specs:
        signatures.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(path)})
    first = ROOT / "work/night159/engine_go"
    changed = []
    for path in source_files:
        old = first / path.relative_to(SOURCE)
        if not old.exists() or sha(old) != sha(path):
            changed.append(str(path.relative_to(SOURCE)).replace("\\", "/"))
    # ----------------------------------------
    # 政策の局所差分以外、とくに元Source・特徴・元手法は初巡と同一を必須とする。
    allowed = {"config159.go", "ledger157.go", "main159.go", "management159.go", "policy157.go", "excess159.go", "round2159_test.go"}
    assert set(changed) <= allowed, changed
    previous_spec = json.loads((ROOT / "work/night159/spec159.json").read_text(encoding="utf-8"))
    original_files = previous_spec["sources"]
    assert all(sha(ROOT / x["path"]) == x["sha256"] for x in original_files), "初巡源が変化"
    inputs = json.loads((SOURCE.parent / "inputs159r2.json").read_text(encoding="utf-8"))["sessions"]
    initial = json.loads((AUDIT / "inputs159.json").read_text(encoding="utf-8"))["sessions"]
    expected = [x for x in initial if x["kind"] == "Night"]
    assert inputs == expected and len(inputs) == 26, "初巡Night入力と異なる"
    p = subprocess.run(["go", "test", ".", "-count=1", "-json"], cwd=COPY, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (AUDIT / "第二巡人工検査159.jsonl").write_bytes(p.stdout)
    events = [json.loads(line) for line in p.stdout.decode("utf-8").splitlines() if line.startswith("{")]
    tests = [e["Test"] for e in events if e["Action"] == "pass" and e.get("Test")]
    independent = [name for name in tests if name.startswith("TestAuditR2")]
    after = [{"path": x["path"], "sha256": sha(ROOT / x["path"])} for x in signatures]
    unchanged = signatures == after and all(sha(ROOT / x["path"]) == x["sha256"] for x in original_files)
    passed = p.returncode == 0 and unchanged and len(independent) == 6
    result = {
        "passed": passed, "created_at": datetime.now().astimezone().isoformat(),
        "scope": "固定R00〜R03、26Nightの金融前監査。Go root packageの人工のみ。原板金融再生0、実App変更0。",
        "new_candidate_financial_replays": 0, "existing_fixture_replays": 0,
        "dedicated_artificial_tests": {"shared_count": len(tests)-len(independent), "independent_count": len(independent),
            "total_passed": len(tests), "tests": tests, "exit_code": p.returncode},
        "source_still_matches": unchanged, "sources": signatures, "changed_from_round1": changed,
        "initial_source_fingerprints_verified": len(original_files), "night_input_exact": len(inputs),
        "checks": ["未知初回は元Source量・前半維持・上下対称", "実80/元50→元部分予約32/元残30の同原行では追加保護18だけ",
            "先に超過30を返済→実50→元部分2/5は20返済→実30", "既予約返済控除・新しい玉優先・他親除外",
            "40/80起動差・返済側床・次正常板gap損失", "R03逆行80pt/反対支持5秒・未知/空白解除・基準50保持",
            "共有人工の複数Source玉の比例返済差・元全返済・予約上限"],
        "limitations": ["新保護は判断時の自由残量をSourceQty未満へ削らない。ただし元Sourceの比例返済が後から実残量を基準以下へ減らす場合がある。",
            "超過へ新たに割当された玉でも保有中の過去最高順行を使う。未来値ではないが割当後だけの順行とは異なる。",
            "全量次正常BBO模型。判定床の約定保証や実機の部分約定/送信遅延の保証ではない。"]}
    (AUDIT / "第二巡金融前監査159.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": passed, "tests": len(tests), "independent": len(independent), "changed": changed,
                      "source_count": len(signatures)}, ensure_ascii=False))
    if not passed:
        print(p.stdout.decode("utf-8"))
        raise SystemExit(1)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
