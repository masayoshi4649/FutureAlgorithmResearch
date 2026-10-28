"""登録済み十二政策と追加日中の再生だけを起動し、実行前後の指紋を残す。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def read(path: Path) -> object:
    """固定JSONを読む。

    引数: path(Path)。返り値: objectはJSON値。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    """原資料又は実装の内容指紋を返す。

    引数: path(Path)。返り値: strはSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(items: list[dict]) -> None:
    """各登録ファイルが変わっていないことを確認する。

    引数: items(list[dict])はパスとSHA256の集合。返り値: None。不一致なら停止。
    """
    for row in items:
        path = Path(row["path"])
        if not path.is_absolute():
            path = ROOT / path
        assert sha(path) == row["sha256"], str(path)


def main() -> None:
    """固定登録の検証後、金融再生を一度だけ実行する。

    引数: なし。返り値: None。既存結果フォルダや旧成果を上書きしない。
    """
    receipt = read(HERE / "登録受領159.json")
    assert receipt["registered"] and receipt["returncode"] == 0
    files = receipt["sources"] + [receipt["plan"], receipt["implementation"]]
    verify(files)
    manifest = read(ROOT / "work/audit159/inputs159.json")
    original = []
    for scene in manifest["sessions"]:
        original.extend(scene["fingerprints"])
    verify(original)
    out = ROOT / "work/night159/results_go"
    assert not out.exists() or not any(out.iterdir()), "既存金融結果を上書きしない"
    cmd = ["go", "run", ".", "-manifest", "../../audit159/inputs159.json", "-configs", "../configs159.json",
           "-registration", "../../research159/登録受領159.json", "-out", "../results_go", "-workers", "8"]
    started, timer = datetime.now().astimezone().isoformat(), time.monotonic()
    print("固定26Nightと追加完了1Day、314条件場の再生を開始します。", flush=True)
    with (HERE / "金融実行159.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(cmd, cwd=ROOT / "work/night159/engine_go", stdout=log, stderr=subprocess.STDOUT, encoding="utf-8")
    verify(files)
    verify(original)
    evidence = {"started_at": started, "finished_at": datetime.now().astimezone().isoformat(), "elapsed_seconds": time.monotonic()-timer,
                "command": cmd, "exit_code": result.returncode, "sources_unchanged": True, "raw_files_checked": len(original),
                "output_files": [{"path": p.relative_to(ROOT).as_posix(), "sha256": sha(p)} for p in sorted(out.glob("*.json"))]}
    (HERE / "金融実行159.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"exit_code": result.returncode, "output_count": len(evidence["output_files"]), "elapsed_seconds": evidence["elapsed_seconds"]}, ensure_ascii=False), flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
