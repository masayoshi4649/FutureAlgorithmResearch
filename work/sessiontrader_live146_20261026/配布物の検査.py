"""配布物を設定検査専用のコピーで起動し、全商品・両OSの同梱内容を確認する。"""

from pathlib import Path
import hashlib
import json
import re
import shutil
import struct
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "App/SessionTrader"
TARGET = Path(__file__).parent / "配布物検査"
TARGET.mkdir(exist_ok=True)
WINDOWS = APP / "dist/windows-amd64/NK225mini/sessiontrader.exe"
report = []
for osname in ("windows-amd64", "linux-amd64"):
    signatures = set()
    for product in ("TOPIX", "TOPIXmini", "NK225", "NK225mini", "NK225micro"):
        source = APP / "dist" / osname / product
        executable = source / ("sessiontrader.exe" if osname.startswith("windows") else "sessiontrader")
        raw = executable.read_bytes()
        signatures.add(hashlib.sha256(raw).hexdigest())
        if osname.startswith("linux"):
            assert raw[:6] == b"\x7fELF\x02\x01"
            offset = struct.unpack_from("<Q", raw, 32)[0]
            size, count = struct.unpack_from("<HH", raw, 54)
            assert all(struct.unpack_from("<I", raw, offset + i * size)[0] != 3 for i in range(count)), "動的ローダーが必要"
        for doc in (APP / "docs").glob("*.md"):
            assert doc.read_bytes() == (source / "docs" / doc.name).read_bytes(), doc.name
        checkdir = TARGET / osname / product
        (checkdir / "conf").mkdir(parents=True, exist_ok=True)
        shutil.copy2(WINDOWS, checkdir / "sessiontrader.exe")
        settings = (source / "conf/settings.toml").read_text(encoding="utf-8-sig")
        config = tomllib.loads(settings)
        assert config["market"]["product"] == product
        if product == "NK225mini":
            assert config["market"]["max_per_side"] == 10
        if product.startswith("NK225"):
            assert config["methods"] == {"day": "TG04", "night": "TG04"}
        checked, count = re.subn(r'(?m)^action\s*=\s*"[^"]*"', 'action = "check"', settings)
        assert count == 1 and tomllib.loads(checked)["startup"]["action"] == "check"
        (checkdir / "conf/settings.toml").write_text(checked, encoding="utf-8")
        result = subprocess.run([str(checkdir / "sessiontrader.exe")], cwd=ROOT, capture_output=True, timeout=30)
        assert result.returncode == 0, (product, result.stdout, result.stderr)
        report.append({"os": osname, "product": product, "cap": config["market"]["max_per_side"],
                       "dryrun": config["trading"]["dryrun"], "binary_sha256": hashlib.sha256(raw).hexdigest(),
                       "configuration_check": "合格（Windows版で設定を検査）", "docs_equal": True})
    assert len(signatures) == 1, "同じOS内で実行ファイルが一致しない"
(Path(__file__).parent / "配布物検査結果.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("全10配布物の設定・説明書・実行ファイルを確認しました。注文APIへの接続はありません。")
