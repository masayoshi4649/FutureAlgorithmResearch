"""登録受領・実装・原資料を再照合する。売買計算は実行しない。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path):
    """既存ファイルのSHA256を読む。

    引数: path(Path)。返り値: strは内容指紋。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    """登録内容と原資料を確認し、再生前の証跡を保存する。

    引数: なし。返り値: None。不一致なら再生前に停止する。
    """
    receipt = json.loads((HERE / "登録受領153.json").read_text(encoding="utf-8"))
    assert receipt["registered"] and receipt["returncode"] == 0
    for ref in [receipt["plan"], receipt["implementation"], *receipt["inputs"], *receipt["sources"]]:
        path = ROOT / ref["path"]
        assert path.stat().st_size == ref["bytes"] and digest(path) == ref["sha256"], path
    manifest = json.loads((HERE / "data/入力目録153.json").read_text(encoding="utf-8"))
    originals = {ref["path"]: ref for scene in manifest["sessions"] for ref in scene["fingerprints"]}
    for name, ref in originals.items():
        path = Path(name)
        before = path.stat()
        assert before.st_size == ref["bytes"]
        assert digest(path) == ref["sha256"], name
        after = path.stat()
        assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), name
    record = {"登録成功": True, "実装一致": True, "原資料一致": len(originals), "金融再生": 0, "API取得": 0}
    (HERE / "再生前指紋確認153.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
