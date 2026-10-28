"""第二巡の登録実装を確認し、段階許可を保存する。"""

import argparse
from datetime import datetime
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
BASE = HERE.parent


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
    """第一巡と第二巡の実装不変を検査して許可を保存する。

    引数: CLIのstage(str)。返り値: None。金融評価は実行しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("train_validation", "locked_test"))
    args = parser.parse_args()
    for folder, name in ((BASE, "登録受領161.json"), (HERE, "登録受領161r2.json")):
        receipt = read(folder/name)
        assert receipt["registered"] is True and receipt["returncode"] == 0
        for source in receipt["sources"] + [receipt["implementation"], receipt["plan"]]:
            assert sha(ROOT/source["path"]) == source["sha256"], source["path"]
    value = {"registered": True, "returncode": 0, "allowed_stages": [args.stage],
             "spec_sha256": sha(HERE/"search/spec161.json"),
             "manifest_sha256": sha(BASE/"inputs161.json"),
             "known_test": True, "created_at": datetime.now().astimezone().isoformat()}
    if args.stage == "locked_test":
        freeze = HERE/"results/selection_frozen161.json"
        selected = read(freeze)
        assert selected["spec_sha256"] == value["spec_sha256"]
        assert selected["manifest_sha256"] == value["manifest_sha256"]
        assert not (HERE/"results/locked_test161.json").exists()
        value["freeze_sha256"] = sha(freeze)
    with (HERE/(args.stage+"_許可161r2.json")).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print("第二巡の登録不変と段階許可を保存: "+args.stage, flush=True)


if __name__ == "__main__":
    main()
