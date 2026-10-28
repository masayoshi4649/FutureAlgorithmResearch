"""登録済み第三巡12条件だけを一度再生し、入力と旧結果の不変を確認する。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / "work/s01_156"


def read(path):
    """JSONを読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fingerprint(path):
    """ファイルの内容を指紋化する。

    引数: path(Path)。返り値: dictは位置・SHA256・サイズ。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.as_posix(), "sha256": digest, "bytes": path.stat().st_size}


def save(path, value):
    """実行証跡をUTF-8で保存する。

    引数: path(Path)、value(dict)。返り値: None。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def verify():
    """登録源・原資料・過去三組の結果を照合する。

    引数: なし。返り値: dictは全内容指紋。
    """
    receipt = read(HERE / "登録受領1573.json")
    assert receipt["registered"] and receipt["returncode"] == 0
    manifest = read(BASE / "inputs156.json")
    entries = receipt["sources"] + receipt["inputs"] + [receipt["plan"], receipt["implementation"]]
    entries += [item for row in manifest["sessions"] for item in row["fingerprints"]]
    verified = []
    for entry in entries:
        path = Path(entry["path"])
        if not path.is_absolute():
            path = ROOT / path
        actual = fingerprint(path)
        assert actual["sha256"] == entry["sha256"], str(path)
        verified.append(actual)
    controls = {}
    for name, folder in (("基準156", BASE), ("第一巡", HERE.parent), ("第二巡", HERE.parent / "round2")):
        rows = [fingerprint(path) for path in sorted((folder / "results_go").glob("*.json"))]
        assert len(rows) == 27
        controls[name] = rows
    return {"registered_and_inputs": verified, "controls": controls}


def main():
    """第三巡を上書きせず一度だけ起動し、前後の指紋と件数を記録する。

    引数: なし。返り値: None。API取得・実注文・アプリ更新は行わない。
    """
    record_path = HERE / "金融実行1573.json"
    output = HERE / "results_go"
    assert not record_path.exists() and not output.exists()
    assert len(read(HERE / "configs1573.json")) == 12
    print("第三巡の登録実装・原資料・旧結果を照合します。", flush=True)
    before = verify()
    save(HERE / "実行前指紋1573.json", before)
    command = ["go", "run", ".", "-manifest", "../../../s01_156/inputs156.json", "-configs", "../configs1573.json", "-registration", "../登録受領1573.json", "-out", "../results_go", "-workers", "8"]
    record = {"開始": datetime.now().astimezone().isoformat(), "command": command, "金融実行回数": 1, "比較条件数": 12, "対象場数": 27, "条件場数": 324}
    save(record_path, record)
    with (HERE / "金融実行1573.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=HERE / "engine_go", stdout=log, stderr=subprocess.STDOUT)
    record.update({"終了": datetime.now().astimezone().isoformat(), "終了コード": result.returncode})
    save(record_path, record)
    after = verify()
    assert before == after, "前後で参照資料が変わりました"
    save(HERE / "実行後指紋1573.json", after)
    record["参照改変数"] = 0
    files = sorted(output.glob("*.json"))
    record["結果ファイル数"] = len(files)
    if result.returncode == 0:
        assert len(files) == 27 and sum(len(read(path)["cases"]) for path in files) == 324
    save(record_path, record)
    print(json.dumps(record, ensure_ascii=False), flush=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
