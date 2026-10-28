"""10月27日日中の既知部分について入力と保存約定の接続資格を確認する。"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import itertools
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work/audit159"
SESSION = "2026-10-27_Day"


def load(path: Path) -> dict:
    """JSONを読取専用で復元する。

    引数: path(Path)。返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def timestamp(value: str) -> float:
    """ISO価格時計をUNIX秒へ変換する。

    引数: value(str)。返り値: floatは秒。
    """
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def board_rows(path: str, start: float, cutoff: float):
    """Go readerが採用する価格時計順の判断入力列を返す。

    引数: path(str)、start/cutoff(float)。返り値: generator[tuple]。受信時計へ置換しない。
    """
    previous = start
    with Path(path).open(encoding="utf-8-sig") as stream:
        for line in stream:
            row = json.loads(line)
            clock = row.get("CurrentPriceTime")
            if not clock:
                continue
            try:
                at = timestamp(clock)
            except ValueError:
                continue
            if at < start or at >= cutoff or at < previous:
                continue
            last = row.get("CurrentPrice", 0) or 0
            if not math.isfinite(last) or last <= 0:
                continue
            previous = at
            prices = []
            for side in ("Buy", "Sell"):
                for level in range(1, 11):
                    value = row.get(f"{side}{level}") or {}
                    prices += [value.get("Price", 0) or 0, value.get("Qty", 0) or 0]
            yield (at, last, *prices)


def candles(path: str, width: int, start: float, cutoff: float) -> list:
    """同じ名目公開時刻までに利用可能な確定足を比較用に正規化する。

    引数: path(str)、width(int)、start/cutoff(float)。返り値: listは時刻OHLC列。遅延60秒を含む。
    """
    p = Path(path)
    if p.suffix == ".csv":
        with p.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    else:
        rows = {key.lower(): value for key, value in load(p).items()}["data"]
    out = []
    for row in rows:
        row = {key.lower(): value for key, value in row.items()}
        if row.get("closed") not in (True, "true"):
            continue
        at = timestamp(row["time"])
        if at >= start and at + width + 60 < cutoff:
            out.append((at, *(float(row[k]) for k in ("open", "high", "low", "close"))))
    return sorted(out)


def compare_inputs(old: dict, new: dict) -> dict:
    """保存資料の採用列を逐次比較し最初の差だけを報告する。

    引数: old/new(dict)はScene。返り値: dictは板・足の一致結果。
    """
    cutoff, result = old["cutoff"], {"cutoff_exclusive": old["cutoff"], "markets": {}}
    for symbol in ("NK225", "TOPIX"):
        before, after, differences = 0, 0, []
        digests = [hashlib.sha256(), hashlib.sha256()]
        for index, pair in enumerate(itertools.zip_longest(board_rows(old["books"][symbol], old["start"], cutoff), board_rows(new["books"][symbol], new["start"], cutoff))):
            left, right = pair
            for j, row in enumerate(pair):
                if row is not None:
                    digests[j].update(json.dumps(row, separators=(",", ":")).encode())
            before += left is not None
            after += right is not None
            if left != right and len(differences) < 3:
                differences.append({"index": index, "old": left, "new": right})
        candle_checks = []
        for width in (60, 300):
            left = candles(old["candles"][symbol][str(width)], width, old["start"], cutoff)
            right = candles(new["candles"][symbol][str(width)], width, new["start"], cutoff)
            diff = [(i, a, b) for i, (a, b) in enumerate(itertools.zip_longest(left, right)) if a != b]
            candle_checks.append({"width": width, "old_rows": len(left), "new_rows": len(right), "equal": not diff, "first_differences": diff[:3]})
        result["markets"][symbol] = {"old_rows": before, "new_rows": after, "equal": not differences, "old_adopted_sha256": digests[0].hexdigest(), "new_adopted_sha256": digests[1].hexdigest(), "first_differences": differences, "candles": candle_checks}
    result["passed"] = all(v["equal"] and all(x["equal"] for x in v["candles"]) for v in result["markets"].values())
    return result


def main() -> None:
    """再生前でも許される入力接続確認だけを実行する。

    引数: なし。返り値: None。売買判断・金融再生は行わない。
    """
    old = next(s for s in load(ROOT / "work/s01_156/inputs156.json")["sessions"] if s["session"] == SESSION)
    new = next(s for s in load(WORK / "inputs159.json")["sessions"] if s["session"] == SESSION)
    report = compare_inputs(old, new)
    report["new_financial_replays"] = 0
    target = WORK / "日中既知部分の入力照合159.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "markets": {k:{"old_rows":v["old_rows"], "new_rows":v["new_rows"], "equal":v["equal"], "candles_equal":all(x["equal"] for x in v["candles"])} for k,v in report["markets"].items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
