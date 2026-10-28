"""設定を保持したWindows/Linux配布ビルドと内容指紋を記録する。"""
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
APP = ROOT / "App/SessionTrader"


def digest(path):
    """ファイル全体の指紋を返す。

    引数: path(Path)。返り値: strはSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    """既存設定を保持して両OSの配布を更新し、監査記録を保存する。

    引数: なし。返り値: None。アプリの起動・実サービスへの接続はしない。
    """
    target = HERE / "配布ビルド155.json"
    assert not target.exists()
    before = {p.relative_to(ROOT).as_posix(): digest(p) for p in (APP / "dist").rglob("*.toml") if "conf" in p.parts}
    with (HERE / "配布ビルド155.log").open("w", encoding="utf-8") as stream:
        result = subprocess.run(["go", "run", "./cmd/build-dist"], cwd=APP, stdout=stream, stderr=subprocess.STDOUT)
    after = {name: digest(ROOT / name) for name in before}
    assert before == after, "既存の実設定又は実ルールが変更されました"
    data = {"時刻": datetime.now().astimezone().isoformat(), "command": "go run ./cmd/build-dist", "exit_code": result.returncode,
            "既存実設定不変": True, "保持指紋": before, "build_cgo": 0, "Linux実行": "未実行", "成果物": []}
    if result.returncode == 0:
        for platform, executable in (("windows-amd64", "sessiontrader.exe"), ("linux-amd64", "sessiontrader")):
            base = APP / "dist" / platform / "Web"
            binary = base / executable
            magic = binary.read_bytes()[:4]
            assert magic[:2] == b"MZ" if platform.startswith("windows") else magic == b"\x7fELF"
            for path in [binary, base / "conf/rules/NK225_S01.toml", base / "conf/settings.toml.sample"]:
                data["成果物"].append({"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)})
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"exit_code": result.returncode, "保持設定数": len(before), "成果物数": len(data["成果物"])}, ensure_ascii=True), flush=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
