"""登録済み第二巡だけを起動し、全入力の実行前後不変を確認する。"""

from datetime import datetime
import json
from pathlib import Path
import subprocess
import time
from execute159 import read, sha, verify

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "work/research159/round2"
ENGINE = ROOT / "work/night159/round2"


def main() -> None:
    """第二巡104新条件場と26同値対照を一度再生する。

    引数: なし。返り値: None。旧成果を上書きしない。
    """
    receipt = read(HERE / "登録受領159r2.json")
    assert receipt["registered"] and receipt["returncode"] == 0
    files = receipt["sources"] + [receipt["plan"], receipt["implementation"]]
    verify(files)
    manifest = read(ENGINE / "inputs159r2.json")
    raw = [f for s in manifest["sessions"] for f in s["fingerprints"]]
    verify(raw)
    out = ENGINE / "results_go"
    assert not out.exists() or not any(out.iterdir())
    command = ["go", "run", ".", "-manifest", "../inputs159r2.json", "-configs", "../configs159r2.json", "-registration", "../../../research159/round2/登録受領159r2.json", "-out", "../results_go", "-workers", "8"]
    started, timer = datetime.now().astimezone().isoformat(), time.monotonic()
    print("第二巡104新条件場と26同値対照を開始します。", flush=True)
    with (HERE / "金融実行159r2.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=ENGINE / "engine_go", stdout=log, stderr=subprocess.STDOUT, encoding="utf-8")
    verify(files)
    verify(raw)
    evidence = {"exit_code": result.returncode, "started_at": started, "finished_at": datetime.now().astimezone().isoformat(),
                "elapsed_seconds": time.monotonic()-timer, "sources_unchanged": True, "raw_files_checked": len(raw), "command": command,
                "output_files": [{"path": p.relative_to(ROOT).as_posix(), "sha256": sha(p)} for p in sorted(out.glob("*.json"))]}
    (HERE / "金融実行159r2.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"exit_code": result.returncode, "outputs": len(evidence["output_files"]), "elapsed": evidence["elapsed_seconds"]}), flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
