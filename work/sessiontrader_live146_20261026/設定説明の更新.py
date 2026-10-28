"""設定値を保ったまま、毎起動の所有分離と診断出力の説明を更新する。"""

from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "App" / "SessionTrader"
paths = list((APP / "conf").glob("*.toml*"))
paths += list((APP / "dist").glob("*-amd64/*/conf/*.toml*"))
changes = []
for path in paths:
    source = path.read_text(encoding="utf-8-sig")
    updated = source.replace(
        "# run: 運転 / check: 設定検査のみ / probe: 読取接続の検査のみ。起動引数は不要です。",
        "# run: 運転 / check: 設定検査 / probe: 読取接続検査 / diagnostics: 診断ZIPの出力。引数は不要です。\n"
        "# diagnosticsでは必要時だけ diagnostic_session = \"2026-10-26_Day\" を追加。省略なら最新場。\n"
        "# 通常運転へ戻す際はdiagnostic_sessionを削除。診断は注文も取消も行いません。",
    ).replace(
        "# 保存状態を区別する運転ID。再開時は同じIDを使用します。半角英数字・_・-で指定します。",
        "# 保存先を区別するID。旧注文取消と監査履歴のため同じIDを維持します。半角英数字・_・-。\n"
        "# 毎起動で戦略・仮想玉を初期化し、旧実玉は手動管理。今回の建玉だけをID別に管理します。",
    ).replace(
        "# 買い・売りそれぞれの同時保有上限（枚、1以上）。返済した分は再び新規に使えます。",
        "# 今回の起動で建てる買い・売りそれぞれの上限（枚、1以上）。未約定新規を含みます。\n"
        "# 旧玉・手動玉は上限と返済対象から除外。手動1枚＋システム10枚＝口座11枚でも運転します。\n"
        "# 枚数変更は再起動で反映。返済した分は再び新規に使えます。",
    ).replace(
        "# PG04へ変える場合はday/nightをPG04に変更。既存建玉や未確定注文が残る間は移行しません。",
        "# PG04へ変える場合はday/nightをPG04に変更して再起動。旧自己注文の終了確認後に始めます。",
    )
    previous_cap = None
    if path.name == "settings.toml" and path.parent.parent.name == "NK225mini":
        previous_cap = re.search(r"(?m)^max_per_side\s*=\s*(\d+)", updated).group(1)
        updated = re.sub(r"(?m)^max_per_side\s*=\s*\d+", "max_per_side = 10", updated)
    if updated != source:
        path.write_text(updated, encoding="utf-8")
        changes.append({"path": str(path.relative_to(ROOT)), "previous_cap": previous_cap})
(Path(__file__).parent / "設定変更記録.json").write_text(json.dumps(changes, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"設定説明の更新: {len(changes)}ファイル")
