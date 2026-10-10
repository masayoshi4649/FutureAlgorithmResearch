"""配布物、検証結果、今回追加した文書リンクを確認して記録する。"""

from pathlib import Path
import hashlib
import json
import re

root = Path(__file__).resolve().parents[2]
app = root / "App/E01"
report = root / "アルゴリズム調査/00047_E01のGo注文プログラム"
events = [json.loads(line) for line in (root / "work/go_e01_validation/go_tests.jsonl").read_text(encoding="utf-8-sig").splitlines() if line.strip()]
failures = [event for event in events if event.get("Action") == "fail"]
passed = [event for event in events if event.get("Action") == "pass" and event.get("Test") and "/" not in event["Test"]]
packages = [event["Package"] for event in events if event.get("Action") == "pass" and not event.get("Test")]
assert not failures, failures

# ----------------------------------------
# 今回の案内に掲載したローカル参照だけを検査する。
links = []
for path in (app / "README.md", app / "docs/仕様.md", app / "docs/検証結果.md", report / "README.md"):
    for target in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding="utf-8")):
        if "://" in target or target.startswith("#"):
            continue
        destination = (path.parent / target.split("#")[0]).resolve()
        assert destination == report / "検証記録.json" or destination.exists(), (path, target)
        links.append(str(destination.relative_to(root)))

# ----------------------------------------
# ビルドと固定期待値の識別情報を残す。
files = [app / "dist/e01.exe", app / "dist/e01-linux-amd64", *sorted((app / "dist/conf").glob("*.toml.sample")), *sorted((app / "internal/strategy/testdata").glob("*.gz"))]
hashes = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
status = json.loads((app / "state/status_dryrun.json").read_text(encoding="utf-8"))
assert status["稼働中"] is False and status["未確定注文"] is False and not status["所有建玉"]
result = {
    "日付": "2026-10-03",
    "全合格": True,
    "通常テスト数": len(passed),
    "合格パッケージ": packages,
    "Go静的検査": "go vet ./... 成功",
    "Windowsビルド": "成功",
    "Linux_amd64ビルド": "成功。実機運転は未検証",
    "配布構成": "dist。設定サンプル4種と初回用の実設定を同梱。再配布時は既存の実設定・記録・状態を保持",
    "実API180秒": {"開始": "2026-10-03T04:30:01+09:00", "終了": "2026-10-03T04:33:01+09:00", "セッション": "2026-10-02_Night", "モード": "dryrun", "銘柄": "TOPIXmini", "片方向上限": 10, "初回枚数": 5, "有効PUSH": {"NK225": 337, "TOPIX": 500, "TOPIXmini": 287}, "仮想約定": 0, "実注文送信": 0},
    "再起動30秒": {"開始": "2026-10-03T04:36:57+09:00", "終了": "2026-10-03T04:37:27+09:00", "結果": "同じ正本から復元して正常終了", "仮想約定": 0, "実注文送信": 0},
    "原本データ": "変更なし。運転はcontroller APIだけを使用",
    "文書リンク数": len(links),
    "SHA256": hashes,
}
(report / "検証記録.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
assert all((root / link).exists() for link in links)
print(json.dumps({"全合格": True, "テスト数": len(passed), "文書リンク数": len(links)}, ensure_ascii=False))
