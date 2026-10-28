"""登録済み26条件の比較を一度実行し、前後の原資料・実装不変を確認する。"""
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path):
    """JSONを読み取る。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fingerprint(path):
    """全内容のSHA256と位置を返す。

    引数: path(Path)。返り値: dictは絶対位置、SHA256、サイズ。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.as_posix(), "sha256": digest, "bytes": path.stat().st_size}


def verify():
    """受領・入力・基準会計の指紋を検査する。

    引数: なし。返り値: dictは実装、原資料、期待比較元の全指紋。
    """
    receipt = read(HERE / "登録受領156.json")
    assert receipt["registered"] is True and receipt["returncode"] == 0
    manifest = read(HERE / "inputs156.json")
    entries = receipt["sources"] + receipt["inputs"] + [receipt["plan"], receipt["implementation"]]
    entries += [row for scene in manifest["sessions"] for row in scene["fingerprints"]]
    verified = []
    for entry in entries:
        path = Path(entry["path"])
        if not path.is_absolute():
            path = ROOT / path
        actual = fingerprint(path)
        assert actual["sha256"] == entry["sha256"], str(path)
        verified.append(actual)
    baseline = [fingerprint(ROOT / "work/s01_155/results" / (scene["session"] + ".json")) for scene in manifest["sessions"] if not scene["partial"]]
    assert len(baseline) == 26
    return {"registered_and_inputs": verified, "baseline": baseline}


def save(path, value):
    """小容量の監査記録を保存する。

    引数: path(Path)、value(dict)。返り値: None。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    """固定入力の比較を起動し、成功/失敗と変更の有無を残す。

    引数: なし。返り値: None。原資料追加取得・実口座接続なし。
    """
    record_path = HERE / "金融実行156.json"
    output = HERE / "results_go"
    assert not record_path.exists() and not output.exists()
    print("登録実装・原資料・26場の基準会計を照合します。", flush=True)
    before = verify()
    save(HERE / "実行前指紋156.json", before)
    command = ["go", "run", ".", "-manifest", "../inputs156.json", "-configs", "../configs156.json", "-registration", "../登録受領156.json", "-out", "../results_go", "-workers", "4"]
    record = {"開始": datetime.now().astimezone().isoformat(), "command": command, "金融実行回数": 1, "比較条件数": 26, "対象場数": 27, "条件場数": 702}
    save(record_path, record)
    with (HERE / "金融実行156.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=HERE / "engine_go", stdout=log, stderr=subprocess.STDOUT)
    record.update({"終了": datetime.now().astimezone().isoformat(), "終了コード": result.returncode})
    save(record_path, record)
    after = verify()
    assert before == after, "実行前後で参照資料が変更されました"
    save(HERE / "実行後指紋156.json", after)
    record["参照改変数"] = 0
    files = sorted(output.glob("*.json"))
    record["結果ファイル数"] = len(files)
    if result.returncode == 0:
        assert len(files) == 27
        assert sum(len(read(p)["cases"]) for p in files) == 702
    save(record_path, record)
    print(json.dumps(record, ensure_ascii=False), flush=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
