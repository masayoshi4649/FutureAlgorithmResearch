"""登録済みP05移植の実装・入力を再生前に照合する。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def verify(row):
    """一つのファイルの現在指紋を登録値と比較する。

    引数: row(dict)はpathとsha256。返り値: None。不一致は例外。
    """
    path = ROOT / row["path"]
    with path.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == row["sha256"], str(path)


def main():
    """実装・保存会計・原資料の指紋を照合し、金融前の証跡を作る。

    引数: なし。返り値: None。
    """
    receipt = json.loads((HERE / "登録受領152.json").read_text(encoding="utf-8"))
    assert receipt["registered"] and receipt["returncode"] == 0
    checked = [receipt[k] for k in ("plan", "implementation", "inputs")] + receipt["sources"]
    inputs = json.loads((ROOT / receipt["inputs"]["path"]).read_text(encoding="utf-8"))
    checked += inputs["references"]
    checked += [row for session in inputs["sessions"] for row in session["fingerprints"]]
    for row in checked:
        verify(row)
    result = {"passed": True, "checked_files": len(checked), "sessions": [s["session"] for s in inputs["sessions"]], "financial_replays": 0}
    (HERE / "再生前指紋照合152.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
