"""追加1場の保存素材を読み取り、研究入力の指紋と収録範囲を保存する。"""

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SESSION = "2026-10-22_Day"
START = "2026-10-22T08:45:00+09:00"
END = "2026-10-22T15:45:00+09:00"


def audit_book(path: Path) -> dict:
    """原板の形式・価格時計・気配・指紋を確認する。

    引数: path (Path) は読み取り対象の原板JSONL。
    返り値: dict は監査値。価格時計の空白は受信途絶と断定しない。
    """
    before = path.stat()
    digest = hashlib.sha256()
    result = {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": before.st_size,
        "mtime_ns": before.st_mtime_ns,
        "rows": 0,
        "invalid_json": 0,
        "null_price_clocks": 0,
        "earlier_session_clocks": 0,
        "after_end_clocks": 0,
        "backwards_price_clocks": 0,
        "session_price_rows": 0,
        "first_session_price_clock": None,
        "last_session_price_clock": None,
        "non_positive_or_crossed_bbo": 0,
    }
    previous = None
    maximum_gap = (0, None, None)
    with path.open("rb") as source:
        for raw in source:
            result["rows"] += 1
            digest.update(raw)
            try:
                row = json.loads(raw)
            except (ValueError, UnicodeError):
                result["invalid_json"] += 1
                continue
            stamp = row.get("CurrentPriceTime")
            if not stamp:
                result["null_price_clocks"] += 1
                continue
            if stamp < START:
                result["earlier_session_clocks"] += 1
                continue
            if stamp > END:
                result["after_end_clocks"] += 1
                continue
            result["session_price_rows"] += 1
            if result["first_session_price_clock"] is None:
                result["first_session_price_clock"] = stamp
            result["last_session_price_clock"] = stamp
            if previous and stamp < previous:
                result["backwards_price_clocks"] += 1
            if previous and stamp > previous:
                gap = (datetime.fromisoformat(stamp) - datetime.fromisoformat(previous)).total_seconds()
                if gap > maximum_gap[0]:
                    maximum_gap = (gap, previous, stamp)
            previous = stamp
            bid = (row.get("Buy1") or {}).get("Price")
            ask = (row.get("Sell1") or {}).get("Price")
            if not bid or not ask or bid >= ask:
                result["non_positive_or_crossed_bbo"] += 1

    # ----------------------------------------
    # 研究で必要な返済時刻への到達と、読取中の素材不変を確認する。
    after = path.stat()
    last = result["last_session_price_clock"]
    result.update(
        sha256=digest.hexdigest(),
        unchanged_during_read=(before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
        reaches_force_close=bool(last and last >= "2026-10-22T15:35:00+09:00"),
        reaches_last_six_minutes=bool(last and last >= "2026-10-22T15:39:00+09:00"),
        maximum_price_clock_gap=maximum_gap,
    )
    return result


def audit_candle(path: Path, minutes: int) -> dict:
    """保存足の終端、連続性、指紋を確認する。

    引数: path (Path) はCSV、minutes (int) は足の時間幅。
    返り値: dict は行数、欠けた時刻、収録範囲、指紋。
    """
    before = path.stat()
    raw = path.read_bytes()
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    after = path.stat()
    gaps = []
    for left, right in zip(rows, rows[1:]):
        seconds = (datetime.fromisoformat(right["time"]) - datetime.fromisoformat(left["time"])).total_seconds()
        if seconds != minutes * 60:
            gaps.append([left["time"], right["time"], seconds])
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": before.st_size,
        "mtime_ns": before.st_mtime_ns,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "unchanged_during_read": (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
        "rows": len(rows),
        "first": rows[0] if rows else {},
        "last": rows[-1] if rows else {},
        "unexpected_time_gaps": gaps,
        "unclosed_rows": sum(row.get("closed") != "true" for row in rows),
        "incomplete_volume_rows": sum(row.get("volume_complete") != "true" for row in rows),
    }


def main() -> None:
    """対象6素材を監査し、再生入力の選択に必要なJSONを保存する。

    引数: なし。
    返り値: None。原本は変更せず同作業領域へ監査結果を保存する。
    """
    materials = []
    for symbol in ("TOPIX", "NK225"):
        materials.append(audit_book(ROOT / "book" / symbol / f"{SESSION}.jsonl"))
        for folder, minutes in (("candle_1min", 1), ("candle_5min", 5)):
            materials.append(audit_candle(ROOT / folder / symbol / f"{SESSION}.csv", minutes))
    result = {
        "new_complete_file_sets": [SESSION],
        "materials": materials,
        "mini_micro_book_directories": [path.name for path in (ROOT / "book").iterdir() if path.is_dir() and ("mini" in path.name.lower() or "micro" in path.name.lower())],
        "notes": [
            "CurrentPriceTimeは最終価格の時刻。差が長いことだけで受信中断と判定しない。",
            "両商品ともデイ15:35の研究返済を越えて収録。終値15:45の清算結果を含むとは断定しない。",
            "研究時のラージ気配による代理約定であり、実TOPIXmini板の再現ではない。",
        ],
    }
    target = HERE / "素材監査.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
    for material in materials:
        print(material["path"], material["rows"], material.get("unexpected_time_gaps", []))


if __name__ == "__main__":
    main()
