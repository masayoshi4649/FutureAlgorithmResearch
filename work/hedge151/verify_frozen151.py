"""金融再生の直前に、登録した実装と分離済み入力の指紋を照合する。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def verify(item):
    """一つの登録ファイルを照合する。

    引数: item(dict)はpathとsha256を持つ登録参照。
    返り値: strは照合済みファイルの相対パス。不一致は例外にする。
    """
    path = ROOT / item["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"], str(path)
    return str(path.relative_to(ROOT))


def main():
    """登録受領とその入れ子参照を全て確認する。

    引数: なし。返り値: None。成功時に検査証跡を保存する。
    """
    receipt = json.loads((HERE / "登録受領151.json").read_text(encoding="utf-8"))
    assert receipt["registered"] is True and receipt["returncode"] == 0
    checked = [verify(receipt[key]) for key in ("plan", "implementation", "inputs")]
    checked += [verify(row) for row in receipt["sources"]]
    inputs = json.loads((ROOT / receipt["inputs"]["path"]).read_text(encoding="utf-8"))
    checked += [verify(row) for row in inputs]
    notifications = json.loads((HERE / "data/B04保存会計の指紋151.json").read_text(encoding="utf-8"))
    checked += [verify(row) for row in notifications["files"]]
    audit = json.loads((HERE / "audit/金融前の独立実装監査.json").read_text(encoding="utf-8"))
    assert audit["all_checks_passed"]
    for row in audit["source_files_checked"]:
        assert hashlib.sha256((HERE / "engine_go" / row["name"]).read_bytes()).hexdigest() == row["sha256"]
    result = {"passed": True, "checked_files": len(checked), "financial_replays": 0, "files": checked}
    (HERE / "audit/登録後入力照合151.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "checked_files": len(checked)}))


if __name__ == "__main__":
    main()
