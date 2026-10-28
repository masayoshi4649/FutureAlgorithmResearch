"""研究コードを監査内に複写し、実資料を使わない追加試験だけを用意する。"""

from pathlib import Path
import hashlib
import json
import shutil
import sys


def main():
    """機能: 元コードを変更せず監査用Go作業コピーを準備する。

    引数: なし。
    返り値: なし。金融資料はコピーせず、ソース指紋をJSONへ保存する。
    """
    audit = Path(__file__).resolve().parent
    second = "--round2" in sys.argv[1:]
    source = audit.parent / ("engine_go_round2" if second else "engine_go")
    target = audit / ("第二巡人工試験用コピー" if second else "人工試験用コピー")
    records = []
    for item in sorted(source.rglob("*")):
        if not item.is_file() or item.suffix not in {".go", ".mod", ".sum", ".toml"}:
            continue
        relative = item.relative_to(source)
        output = target / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, output)
        records.append({"相対パス": str(relative), "sha256": hashlib.sha256(item.read_bytes()).hexdigest()})
    shutil.copy2(audit.parent / "configs150.json", audit / "configs150.json")
    shutil.copy2(audit.parent / "configs_round2.json", audit / "configs_round2.json")
    shutil.copy2(audit / "独立人工試験_test.go", target / "audit_independent150_test.go")
    if second:
        shutil.copy2(audit.parent / "configs_round2_150.json", audit / "configs_round2_150.json")
        shutil.copy2(audit / "第二巡独立人工試験_test.go", target / "audit_independent150_round2_test.go")
    fingerprint = "第二巡独立人工試験の元指紋.json" if second else "独立人工試験の元指紋.json"
    (audit / fingerprint).write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"金融再生": 0, "複写ソース数": len(records), "試験先": str(target)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
