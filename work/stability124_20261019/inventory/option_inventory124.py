"""日経オプション保存ファイルの境界と少数標本だけを読み、時刻と項目の有無を整理する。"""

from __future__ import annotations

import collections
import hashlib
import json
import pathlib
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT = pathlib.Path(__file__).resolve().parent


def save(name: str, value: Any) -> None:
    """
    機能: 日本語を保持した調査資料を UTF-8 で保存する。
    引数: name (str) 保存ファイル名、value (Any) JSON 化可能な値。
    返り値: None。
    """
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def pick(handle: Any, size: int, fraction: float) -> tuple[int, bytes]:
    """
    機能: 指定位置に続く完全な一行を選び、行位置と生データを返す。
    引数: handle (BinaryIO) 入力、size (int) 読み始めのサイズ、fraction (float) 位置比率。
    返り値: tuple[int, bytes] 行開始位置と生データ。
    """
    if fraction == 0:
        handle.seek(0)
        return 0, handle.readline()
    if fraction == 1:
        handle.seek(max(0, size - 32768))
        if handle.tell() > 0:
            handle.readline()
        data = handle.read(size - handle.tell())
        lines = data.splitlines(keepends=True)
        if not lines:
            handle.seek(0)
            return 0, handle.readline()
        return size - len(lines[-1]), lines[-1]
    handle.seek(int(size * fraction))
    handle.readline()
    offset = handle.tell()
    line = handle.readline()
    if not line:
        return pick(handle, size, 1)
    return offset, line


def compact(row: dict[str, Any]) -> dict[str, Any]:
    """
    機能: 時刻・価格・オプション指標の小さい標本を抽出する。
    引数: row (dict[str, Any]) 保存一行。
    返り値: dict[str, Any] 抽出値。
    """
    names = ["Symbol", "SymbolName", "SecurityType", "CurrentPrice", "CurrentPriceTime", "TradingVolume", "TradingVolumeTime", "CalcPrice", "IV", "Delta", "Gamma", "Theta", "Vega", "BidPrice", "AskPrice", "BidQty", "AskQty", "Buy1", "Sell1"]
    return {key: row.get(key) for key in names}


def main() -> None:
    """
    機能: オプションのファイル目録と各五位置の時刻・価格資格を保存する。
    引数: なし。
    返り値: None。
    """
    files = sorted(ROOT.glob("book/NK225op_*/*.jsonl"))
    records = []
    schema = collections.defaultdict(collections.Counter)
    sessions = collections.defaultdict(lambda: collections.Counter())
    full_samples = []
    all_rows = 0
    for path in files:
        stat = path.stat()
        _, month, side, strike = path.parent.name.split("_")
        sample_rows = []
        seen = set()
        with path.open("rb") as handle:
            for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
                offset, raw = pick(handle, stat.st_size, fraction)
                if offset in seen:
                    continue
                seen.add(offset)
                row = json.loads(raw)
                for key, value in row.items():
                    schema[key][type(value).__name__] += 1
                stats = sessions[path.stem]
                stats["標本行数"] += 1
                stats["CurrentPriceTimeあり"] += bool(row.get("CurrentPriceTime"))
                stats["TradingVolumeTimeあり"] += bool(row.get("TradingVolumeTime"))
                stats["IVあり"] += isinstance(row.get("IV"), (int, float))
                bid = (row.get("Buy1") or {}).get("Price")
                ask = (row.get("Sell1") or {}).get("Price")
                stats["正の両気配"] += isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and 0 < bid <= ask
                sample_rows.append({"fraction": fraction, "offset": offset, "sha256": hashlib.sha256(raw).hexdigest(), "fields": compact(row)})
                all_rows += 1
                if len(full_samples) < 8 and (path.name.startswith("2026-10-07") or path.name.startswith("2026-10-19")):
                    full_samples.append({"path": path.relative_to(ROOT).as_posix(), "offset": offset, "row": row})
        records.append({"path": path.relative_to(ROOT).as_posix(), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "限月": month, "種別": side, "権利行使価格": int(strike), "session": path.stem, "読取り前後でサイズと更新時刻が同じ": (stat.st_size, stat.st_mtime_ns) == (path.stat().st_size, path.stat().st_mtime_ns), "samples": sample_rows})
    # ----------------------------------------
    summary = {"目的": "保存構造と時刻資格の少数標本検査。全行統計・金融再生ではない。", "抽出": "各ファイルの最初・25%・50%・75%・末尾。位置の重複は除外。", "ファイル数": len(records), "合計bytes": sum(row["bytes"] for row in records), "標本行数": all_rows, "セッション": {session: {"ファイル数": sum(row["session"] == session for row in records), **dict(values)} for session, values in sorted(sessions.items())}, "限月": dict(collections.Counter(row["限月"] for row in records)), "トップレベル項目と標本型": {key: dict(value) for key, value in sorted(schema.items())}, "受信時刻の推定": "CurrentPriceTime は最終約定の市場時刻であり行の受信時刻とは未確認。独立受信時刻がなければ IV/気配変化をこの時刻で先物へ結合してはならない。", "行未走査": True, "金融再生": 0}
    save("オプション保存608ファイルの境界目録.json", records)
    save("オプション保存項目と時刻の標本確認.json", summary)
    save("オプション生JSONの少数標本.json", full_samples)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
