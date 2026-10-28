"""登録済み実装の不変性を確認し、探索又は固定後確認の許可証跡を作る。"""

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def read(path: Path) -> dict:
    """UTF-8の証跡を読む。

    引数: path(Path)。返り値: dict。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    """ファイルの内容指紋を返す。

    引数: path(Path)。返り値: strはSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    """登録実装の変更を拒否し、段階限定の実行許可を保存する。

    引数: CLIのstage(str)。返り値: None。価格評価は行わない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("train_validation", "locked_test"))
    args = parser.parse_args()
    registered = HERE / "登録受領161.json"
    receipt = read(registered)
    assert receipt["registered"] is True and receipt["returncode"] == 0
    for record in receipt["sources"] + [receipt["plan"], receipt["implementation"]]:
        assert sha(ROOT / record["path"]) == record["sha256"], record["path"]
    value = {"registered": True, "returncode": 0, "allowed_stages": [args.stage],
             "registered_receipt_sha256": sha(registered),
             "manifest_sha256": sha(HERE / "inputs161.json"),
             "spec_sha256": sha(HERE / "search/spec161.json"),
             "created_at": datetime.now().astimezone().isoformat()}
    if args.stage == "locked_test":
        freeze = HERE / "results/selection_frozen161.json"
        frozen = read(freeze)
        assert frozen["test_opened"] is False
        assert frozen["manifest_sha256"] == value["manifest_sha256"]
        assert frozen["spec_sha256"] == value["spec_sha256"]
        assert not (HERE / "results/locked_test161.json").exists()
        value["freeze_sha256"] = sha(freeze)
    target = HERE / (args.stage + "_許可161.json")
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"登録実装の不変と段階許可を保存: {args.stage}", flush=True)


if __name__ == "__main__":
    main()
