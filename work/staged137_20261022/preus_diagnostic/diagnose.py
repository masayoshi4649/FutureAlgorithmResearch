"""保存済み夜間1分足の時間帯別性質を診断する。金融再生は行わない。"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
JST = ZoneInfo("Asia/Tokyo")
NY = ZoneInfo("America/New_York")
LABELS = {
    "開始直後": "17:00〜19:00",
    "米朝前": "19:00〜米08:30（対象期間21:30）",
    "米朝発表枠": "米08:30〜09:30（対象期間21:30〜22:30）",
    "米現物寄付": "米09:30〜10:00（対象期間22:30〜23:00）",
    "米現物以後": "米10:00〜日本06:00（対象期間23:00〜翌06:00）",
    "米現物前全体": "17:00〜米09:30（対象期間22:30）",
    "米朝前全体": "17:00〜米08:30（対象期間21:30）",
    "米現物後全体": "米09:30〜日本06:00（対象期間22:30〜翌06:00）",
    "利用者指定の夜間前半": "17:00〜21:00",
    "利用者指定の夜間移行帯": "21:00〜23:30",
    "日本寄付前": "08:45〜09:00",
    "日本前場": "09:00〜11:30",
    "日本昼休み": "11:30〜12:30",
    "日本後場": "12:30〜15:30",
    "日本引け後": "15:30〜15:40",
}


def med(values: list[float]) -> float | None:
    """有限な数値の中央値を求める。

    引数: values (list[float]) は候補値。
    返り値: float | None は中央値、空ならNone。
    """
    vals = [float(x) for x in values if x is not None and np.isfinite(x)]
    return float(np.median(vals)) if vals else None


def read_bars(path: Path) -> tuple[dict[datetime, dict], dict]:
    """有効な確定足だけを読む。

    引数: path (Path) は読取専用の保存1分足CSV。
    返り値: tuple[dict, dict] は時刻別足と除外・重複の監査情報。
    """
    bars = {}
    excluded = 0
    duplicates = 0
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("closed", "true").lower() != "true":
                excluded += 1
                continue
            t = datetime.fromisoformat(row["time"]).astimezone(JST)
            vals = {k: float(row[k]) for k in ("open", "high", "low", "close")}
            if not all(np.isfinite(v) and v > 0 for v in vals.values()):
                excluded += 1
                continue
            assert vals["low"] <= min(vals["open"], vals["close"]) <= max(vals["open"], vals["close"]) <= vals["high"]
            if t in bars:
                duplicates += 1
                assert bars[t] == vals, f"異なる重複足: {path} {t}"
            bars[t] = vals
    return bars, {"path": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "closed_valid": len(bars), "excluded": excluded, "duplicates": duplicates}


def bounds(day: str, session_type: str) -> dict[str, tuple[datetime, datetime]]:
    """米東部時計を日本時間へ変換して事前に区間を固定する。

    引数: day (str) は開始日YYYY-MM-DD、session_type (str) はDay/Night。
    返り値: dict[str, tuple[datetime, datetime]] は半開区間。
    """
    d = datetime.fromisoformat(day)
    if session_type == "Day":
        times = [(8,45), (9,0), (11,30), (12,30), (15,30), (15,40)]
        cut = [d.replace(hour=h, minute=m, tzinfo=JST) for h,m in times]
        names = ["日本寄付前", "日本前場", "日本昼休み", "日本後場", "日本引け後"]
        return {name: (a,b) for name,a,b in zip(names, cut, cut[1:])}
    start = d.replace(hour=17, tzinfo=JST)
    j19 = d.replace(hour=19, tzinfo=JST)
    m830 = d.replace(hour=8, minute=30, tzinfo=NY).astimezone(JST)
    m930 = d.replace(hour=9, minute=30, tzinfo=NY).astimezone(JST)
    m1000 = d.replace(hour=10, tzinfo=NY).astimezone(JST)
    end = (d + timedelta(days=1)).replace(hour=6, tzinfo=JST)
    return {"開始直後": (start, j19), "米朝前": (j19, m830), "米朝発表枠": (m830, m930), "米現物寄付": (m930, m1000), "米現物以後": (m1000, end), "米現物前全体": (start, m930), "米朝前全体": (start, m830), "米現物後全体": (m930, end), "利用者指定の夜間前半": (start, d.replace(hour=21, tzinfo=JST)), "利用者指定の夜間移行帯": (d.replace(hour=21,tzinfo=JST), d.replace(hour=23,minute=30,tzinfo=JST))}


def diagnose_segment(bars: dict, a: datetime, b: datetime, tail_threshold: float) -> dict:
    """欠測を埋めず区間の価格性質を集計する。

    引数: bars (dict) は時刻別足、a/b (datetime) は区間、tail_threshold (float) は当場1分変化の90分位。
    返り値: dict は観測幅、連続20分の効率、方向反転、絶対変化と資料資格。
    """
    times = sorted(t for t in bars if a <= t < b)
    one = []
    changes = {}
    paths = []
    paths5 = []
    for t in times:
        p = t - timedelta(minutes=1)
        if p in bars:
            delta = bars[t]["close"] - bars[p]["close"]
            changes[t] = delta
            one.append(abs(delta) / bars[p]["close"] * 10000)
        window5 = [t - timedelta(minutes=k) for k in range(5, -1, -1)]
        if window5[0] >= a and all(w in bars for w in window5):
            x5 = np.array([bars[w]["close"] for w in window5])
            dist5 = float(np.abs(np.diff(x5)).sum())
            if dist5:
                paths5.append(abs(float(x5[-1] - x5[0])) / dist5)
        window = [t - timedelta(minutes=k) for k in range(20, -1, -1)]
        if window[0] < a or not all(w in bars for w in window):
            continue
        x = np.array([bars[w]["close"] for w in window])
        distance = float(np.abs(np.diff(x)).sum())
        if distance:
            paths.append({"end": t.isoformat(), "efficiency": abs(float(x[-1] - x[0])) / distance, "net": float(x[-1] - x[0]), "range": float(x.max() - x.min())})
    flips = sum(changes[t] * changes.get(t - timedelta(minutes=1), 0) < 0 for t in changes)
    flip_den = sum(changes[t] != 0 and changes.get(t - timedelta(minutes=1), 0) != 0 for t in changes)
    first = bars[times[0]]["open"] if times else None
    width = max(bars[t]["high"] for t in times) - min(bars[t]["low"] for t in times) if times else None
    signed_net = bars[times[-1]]["close"] - first if times else None
    expected = int((b - a).total_seconds() / 60)
    strong = sum(x["efficiency"] >= 0.5 for x in paths)
    return {
        "start": a.isoformat(), "end_exclusive": b.isoformat(), "expected_minutes": expected, "observed_minutes": len(times), "missing_minutes": expected-len(times),
        "coverage": len(times)/expected, "observed_range": width, "observed_range_bp": width/first*10000 if first else None,
        "observed_net": signed_net, "observed_absnet_range_ratio": abs(signed_net)/width if width else None,
        "continuous_1min_changes": len(one), "abs_1min_bp_median": med(one), "abs_1min_bp_p90": float(np.quantile(one, 0.9)) if one else None,
        "large_1min_changes": sum(x >= tail_threshold and x > 0 for x in one), "large_1min_threshold_bp": tail_threshold,
        "nonzero_consecutive_pairs": flip_den, "sign_flips": flips, "sign_flip_fraction": flips/flip_den if flip_den else None,
        "continuous_20min_windows": len(paths), "efficiency_20min_median": med([x["efficiency"] for x in paths]),
        "efficiency_at_least_half": strong, "efficiency_at_least_half_fraction": strong/len(paths) if paths else None,
        "continuous_5min_windows": len(paths5), "efficiency_5min_median": med(paths5),
    }


def summary(rows: list[dict]) -> dict:
    """各場を等ウェイトにして区間を比較する。

    引数: rows (list[dict]) は同一商品の同一区間を持つ各場。
    返り値: dict は場間中央値と総分母。
    """
    out = {}
    for key in rows[0]["segments"]:
        parts = [r["segments"][key] for r in rows]
        v = {"sessions": len(parts)}
        for col in ("coverage", "observed_range", "observed_range_bp", "observed_absnet_range_ratio", "abs_1min_bp_median", "abs_1min_bp_p90", "sign_flip_fraction", "efficiency_20min_median", "efficiency_5min_median", "efficiency_at_least_half_fraction"):
            v[col + "_session_median"] = med([p[col] for p in parts])
        for col in ("expected_minutes", "observed_minutes", "missing_minutes", "continuous_1min_changes", "large_1min_changes", "continuous_20min_windows", "continuous_5min_windows", "efficiency_at_least_half", "nonzero_consecutive_pairs", "sign_flips"):
            v[col] = sum(p[col] for p in parts)
        v["large_1min_rate"] = v["large_1min_changes"] / v["continuous_1min_changes"] if v["continuous_1min_changes"] else None
        v["efficiency_observed_sessions"] = sum(p["efficiency_20min_median"] is not None for p in parts)
        out[key] = v
    pairs = [(r["segments"]["米朝前全体"]["efficiency_20min_median"], r["segments"]["米現物後全体"]["efficiency_20min_median"]) for r in rows if "米朝前全体" in r["segments"]]
    pairs = [(a,b) for a,b in pairs if a is not None and b is not None]
    out["場内対比較"] = {"valid_sessions": len(pairs), "pre_higher_efficiency": sum(a>b for a,b in pairs), "post_higher_efficiency": sum(a<b for a,b in pairs), "equal_efficiency": sum(a==b for a,b in pairs), "median_pre_minus_post": med([a-b for a,b in pairs])}
    return out


def main() -> None:
    """全保存夜間を読み区間診断を保存する。

    引数: なし。
    返り値: None。JSONをこの作業専用フォルダへ保存する。
    """
    all_rows = []
    audits = []
    for product in ("NK225", "TOPIX"):
        for path in sorted((ROOT / "candle_1min" / product).glob("*.csv")):
            day = path.stem[:10]
            session_type = path.stem.split("_")[-1]
            if session_type not in ("Day", "Night") or not "2026-09-21" <= day <= "2026-10-22" or (day == "2026-10-22" and session_type == "Night"):
                continue
            bars, audit = read_bars(path)
            audits.append(audit)
            bb = bounds(day, session_type)
            aa = min(a for a,b in bb.values())
            zz = max(b for a,b in bb.values())
            jumps = []
            for t in sorted(bars):
                p = t - timedelta(minutes=1)
                if aa <= p < t < zz and p in bars:
                    jumps.append({"time": t.isoformat(), "change": bars[t]["close"]-bars[p]["close"], "abs_bp": abs(bars[t]["close"]-bars[p]["close"])/bars[p]["close"]*10000})
            threshold = float(np.quantile([x["abs_bp"] for x in jumps], .9))
            segments = {k: diagnose_segment(bars, a, b, threshold) for k,(a,b) in bb.items()}
            known = day <= ("2026-10-21" if session_type == "Day" else "2026-10-20")
            group = ("既知23日中" if session_type=="Day" else "既知22夜間") if known else ("追加10月22日日中別枠" if session_type=="Day" else "追加10月21日夜間別枠")
            all_rows.append({"product": product, "session": path.stem, "group": group, "日本現物休日": day in ("2026-09-21", "2026-09-22", "2026-09-23", "2026-10-12"), "segments": segments, "largest_10_changes": sorted(jumps, key=lambda x:x["abs_bp"], reverse=True)[:10]})
    result = {"目的": "米国前を全静観する妥当性の価格性質診断。方向予測・金融再生・手法成績ではない。", "金融再生": 0, "現在API取得": 0, "売買注文": 0,
              "定義": {"方向効率": "連続する21本の終値で20分の始終差絶対値÷毎分差絶対値合計。欠測を補間しない。全不変窓を効率0に置かず除外。", "区間": LABELS, "大変動": "各場全体の連続1分絶対変化90分位以上。実取引判断には未来の閾値として利用不可。", "注意": "20分窓は重複する。独立な標本数でも勝率でもない。高安幅は観測足のみの下限。欠測は無変動と異なる。"},
              "集計": {group: {product: summary([r for r in all_rows if r["group"]==group and r["product"]==product]) for product in ("NK225", "TOPIX")} for group in ("既知23日中", "既知22夜間", "追加10月22日日中別枠", "追加10月21日夜間別枠")}, "各場": all_rows, "入力監査": audits}
    result["日中現物通常日と休場日"] = {kind: {product: summary([r for r in all_rows if r["group"]=="既知23日中" and r["product"]==product and r["日本現物休日"]==holiday]) for product in ("NK225", "TOPIX")} for kind,holiday in (("現物通常19日",False),("現物休場4日",True))}
    (OUT / "昼夜時間帯診断.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["集計"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
