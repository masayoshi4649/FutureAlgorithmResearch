"""小さい全オプション一分足と生データ標本の時刻制限を整理する。"""

from __future__ import annotations

import collections
import csv
import datetime as dt
import hashlib
import json
import pathlib
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT = pathlib.Path(__file__).resolve().parent
CONTROLLER = pathlib.Path("S:/GitHub/masayoshi4649/kabus-controller")


def save(name: str, value: Any) -> None:
    """
    機能: 日本語 JSON を調査領域へ保存する。
    引数: name (str) 保存名、value (Any) JSON 化可能値。
    返り値: None。
    """
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    """
    機能: 全オプション一分足の件数と、同時刻コール・プット対を数える。
    引数: なし。
    返り値: None。
    """
    files = sorted(ROOT.glob("candle_1min/NK225op_*/*.csv"))
    records = []
    all_bars = []
    counts = collections.defaultdict(collections.Counter)
    minute_sides = collections.defaultdict(set)
    for path in files:
        raw = path.read_bytes()
        _, month, side, strike = path.parent.name.split("_")
        bars = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
        counts[path.stem]["ファイル数"] += 1
        counts[path.stem]["ヘッダのみ"] += not bars
        counts[path.stem]["足のある銘柄数"] += bool(bars)
        counts[path.stem]["足数"] += len(bars)
        for row in bars:
            counts[path.stem]["確定足数"] += row["closed"] == "true"
            counts[path.stem]["出来高完備足数"] += row["volume_complete"] == "true"
            counts[path.stem]["出来高増分合計"] += float(row["volume"])
            minute_sides[(path.stem, month, strike, row["time"])].add(side)
            all_bars.append({"source": path.relative_to(ROOT).as_posix(), "session": path.stem, "限月": month, "種別": side, "権利行使価格": int(strike), **row})
        records.append({"path": path.relative_to(ROOT).as_posix(), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "rows": len(bars), "first": bars[0] if bars else None, "last": bars[-1] if bars else None})
    # ----------------------------------------
    for (session, month, strike, minute), sides in minute_sides.items():
        if sides == {"C", "P"}:
            counts[session]["同分同限月同権利行使のコールプット対数"] += 1
    summary = {"ファイル数": len(records), "bytes": sum(row["bytes"] for row in records), "足数": len(all_bars), "対象": "保存済み全608オプション一分足。先物は読んでいない。", "セッション": {session: dict(values) for session, values in sorted(counts.items())}, "足利用方針": "確定足のみ。足の末尾時刻より前に使わない。次の1分以降で使用し、欠測をゼロにしない。保存時の closed=true は各足の開始時刻で既知だったことを意味しない。", "生板とIV": "保存JSONLに独立受信時刻が残らないため同時刻先物と安全な同期不可。CurrentPriceTimeは最終約定時刻であり気配/IVの到着時刻ではない。"}
    save("オプション一分足608ファイルの完全目録.json", records)
    save("オプション一分足の全行小キャッシュ.json", all_bars)
    save("オプション一分足の利用可能範囲.json", summary)
    # ----------------------------------------
    boundaries = json.loads((OUT / "オプション保存608ファイルの境界目録.json").read_text(encoding="utf-8"))
    example_rows = []
    pair_counts = collections.Counter()
    for file in boundaries:
        samples = file["samples"]
        for before, after in zip(samples, samples[1:]):
            a, b = before["fields"], after["fields"]
            if a["CurrentPriceTime"] == b["CurrentPriceTime"]:
                pair_counts["同一約定時刻の標本対"] += 1
                changed = any(a[key] != b[key] for key in ["IV", "Delta", "Gamma", "Theta", "Vega"])
                pair_counts["同一約定時刻でIV等が変化"] += changed
                pair_counts["時刻nullのままIV等が変化"] += changed and a["CurrentPriceTime"] is None
                if changed and len(example_rows) < 8:
                    example_rows.append({"path": file["path"], "before": before, "after": after})
    evidence = []
    for relative in ["docs/future-history.md", "future_history_archive.go", "future_history_store.go", "future_history_candles.go"]:
        path = CONTROLLER / relative
        raw = path.read_bytes()
        target = "controller_" + path.name
        (OUT / target).write_bytes(raw)
        evidence.append({"source": str(path), "snapshot": target, "sha256": hashlib.sha256(raw).hexdigest()})
    save("受信時刻欠落と約定時刻の非代用性.json", {"標本対": dict(pair_counts), "代表例": example_rows, "仕様と実装の保存根拠": evidence, "不許可": "現在値時刻の同じ行をその時刻へ集約して気配・IVの最後を使うこと。受信が将来の行が古い約定時刻へ戻る。", "可能": "受信時刻を今後保存する。または確定足の後出し利用、前場完了情報を次場から利用する。", "未確認": "ネットワーク遅延分布、全行のBBO/IV資格と時刻遅れ、実トレード成績、オプションの売買手数料。"})
    print(json.dumps(summary, ensure_ascii=False))
    print(json.dumps(dict(pair_counts), ensure_ascii=False))


if __name__ == "__main__":
    main()
