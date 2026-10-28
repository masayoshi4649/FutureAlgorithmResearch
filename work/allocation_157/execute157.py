"""登録した数量配分の条件を一度だけ金融再生し、原資料・実装の前後指紋を照合する。"""

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / "work/s01_156"


def read(path):
    """UTF-8のJSONを読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fingerprint(path):
    """ファイル全体の位置と内容指紋を返す。

    引数: path(Path)。返り値: dictは絶対位置・SHA256・サイズ。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.as_posix(), "sha256": digest, "bytes": path.stat().st_size}


def save(path, value):
    """実行証跡を保存する。

    引数: path(Path)、value(dict)。返り値: None。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def verify():
    """登録した全実装・入力・比較元の内容を照合する。

    引数: なし。返り値: dictは照合した内容指紋。
    """
    receipt = read(HERE / "登録受領157.json")
    assert receipt["registered"] is True and receipt["returncode"] == 0
    manifest = read(BASE / "inputs156.json")
    entries = receipt["sources"] + receipt["inputs"] + [receipt["plan"], receipt["implementation"]]
    entries += [entry for row in manifest["sessions"] for entry in row["fingerprints"]]
    verified = []
    for entry in entries:
        path = Path(entry["path"])
        if not path.is_absolute():
            path = ROOT / path
        actual = fingerprint(path)
        assert actual["sha256"] == entry["sha256"], str(path)
        verified.append(actual)
    controls = [fingerprint(path) for path in sorted((BASE / "results_go").glob("*.json"))]
    assert len(controls) == 27
    return {"registered_and_inputs": verified, "controls": controls}


def main():
    """事前登録済み比較を一回起動し、前後不変と終了状態を残す。

    引数: なし。返り値: None。追加API取得・実注文・アプリ更新なし。
    """
    record_path = HERE / "金融実行157.json"
    output = HERE / "results_go"
    assert not record_path.exists() and not output.exists()
    configs = read(HERE / "configs157.json")
    manifest = read(BASE / "inputs156.json")
    print("157の登録実装・原資料・旧S01比較元を照合します。", flush=True)
    before = verify()
    save(HERE / "実行前指紋157.json", before)
    command = ["go", "run", ".", "-manifest", "../../s01_156/inputs156.json", "-configs", "../configs157.json", "-registration", "../登録受領157.json", "-out", "../results_go", "-workers", "8"]
    count = len(configs) * len(manifest["sessions"])
    record = {"開始": datetime.now().astimezone().isoformat(), "command": command, "金融実行回数": 1, "比較条件数": len(configs), "対象場数": len(manifest["sessions"]), "条件場数": count}
    save(record_path, record)
    with (HERE / "金融実行157.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=HERE / "engine_go", stdout=log, stderr=subprocess.STDOUT)
    record.update({"終了": datetime.now().astimezone().isoformat(), "終了コード": result.returncode})
    save(record_path, record)
    after = verify()
    assert before == after, "前後で参照資料が変更されました"
    save(HERE / "実行後指紋157.json", after)
    record["参照改変数"] = 0
    files = sorted(output.glob("*.json"))
    record["結果ファイル数"] = len(files)
    if result.returncode == 0:
        assert len(files) == len(manifest["sessions"])
        assert sum(len(read(path)["cases"]) for path in files) == count
    save(record_path, record)
    print(json.dumps(record, ensure_ascii=False), flush=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
