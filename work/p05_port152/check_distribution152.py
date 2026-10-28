"""新しい配布実行ファイルと保持された設定を、実サービスへ接続せず確認する。"""

import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import time
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
APP = ROOT / "App/SessionTrader"


def digest(path):
    """ファイルの内容指紋を求める。

    引数: path(Path)。返り値: strはSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    """配布保護対象を照合し、全商品OFFのWindows実行ファイルからRESTを読む。

    引数: なし。返り値: None。設定検査と8秒の模擬運転は専用コピー内だけで行う。
    """
    protected = json.loads((HERE / "配布更新前の保護対象.json").read_text(encoding="utf-8"))
    for row in protected:
        assert digest(ROOT / row["path"]) == row["sha256"], row["path"]
    base = APP / "dist/windows-amd64/Web"
    clone = HERE / "binary_smoke"
    assert not clone.exists(), "既存の実行資料へ上書きしない"
    clone.mkdir()
    shutil.copy2(base / "sessiontrader.exe", clone / "sessiontrader.exe")
    shutil.copytree(base / "conf", clone / "conf")
    config_path = clone / "conf/settings.toml"
    source = config_path.read_text(encoding="utf-8-sig")
    assert 'mode = "live"' not in source and 'mode = "dryrun"' not in source
    check = source.replace('action = "run"', 'action = "check"')
    assert check != source
    config_path.write_text(check, encoding="utf-8")
    flags = subprocess.CREATE_NO_WINDOW
    completed = subprocess.run([str(clone / "sessiontrader.exe")], cwd=clone, stdin=subprocess.DEVNULL, capture_output=True, creationflags=flags, timeout=30)
    (HERE / "配布実行ファイルの設定検査.txt").write_bytes(completed.stdout + completed.stderr)
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    assert completed.stdout.count(b"NK225_P05") == 3
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # 接続先を到達不能なloopbackへ置換し、全OFFのまま画面を読む。
    runtime = source.replace('action = "run"', 'action = "run"\nduration_seconds = 8')
    runtime = runtime.replace('port = 8090', f'port = {port}').replace('host = "0.0.0.0"', 'host = "127.0.0.1"')
    runtime = runtime.replace('http://10.10.100.1:8080', 'http://127.0.0.1:1')
    config_path.write_text(runtime, encoding="utf-8")
    with (HERE / "配布実行ファイルのWeb検査.txt").open("wb") as output:
        process = subprocess.Popen([str(clone / "sessiontrader.exe")], cwd=clone, stdin=subprocess.DEVNULL, stdout=output, stderr=output, creationflags=flags)
        origin = f"http://127.0.0.1:{port}"
        try:
            for _ in range(50):
                try:
                    with urllib.request.urlopen(origin + "/api/settings", timeout=1) as response:
                        settings = json.load(response)
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise AssertionError("配布Webが起動しない")
            with urllib.request.urlopen(origin + "/api/rules", timeout=2) as response:
                catalog = json.load(response)
            with urllib.request.urlopen(origin + "/api/state", timeout=2) as response:
                state = json.load(response)
            with urllib.request.urlopen(origin + "/app.js", timeout=2) as response:
                javascript = response.read().decode("utf-8")
            assert "snapshot.session_realized_yen" in javascript
            items = settings["instruments"]
            assert len(items) == 5 and all(i["mode"] == "off" for i in items)
            for item in items:
                if item["product"].startswith("NK225"):
                    assert [w["method"] for w in item["windows"]] == ["NK225_D07", "NK225_P05", "", "NK225_D07"]
            p05 = next(r for r in catalog["rules"] if r["name"] == "NK225_P05")
            assert p05["supported"] and p05["night"] and not p05["day"] and p05["window_only"]
            assert process.wait(timeout=15) == 0
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
    result = {"passed": True, "protected_files_unchanged": len(protected), "all_products_off": True,
        "windows_binary_configuration": True, "windows_binary_rest": True, "p05_standard_products": 3,
        "linux": "CGOなしビルド確認。実行未確認。", "live_controller_contact": False,
        "artifacts": [{"path": p.relative_to(ROOT).as_posix(), "sha256": digest(p)} for p in (
            APP / "dist/windows-amd64/Web/sessiontrader.exe", APP / "dist/linux-amd64/Web/sessiontrader")],
        "settings": settings, "state": state}
    (HERE / "配布確認152.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("settings", "state", "artifacts")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
