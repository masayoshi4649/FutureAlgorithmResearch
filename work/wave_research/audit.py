"""保存済み足と板スナップショットの品質を監査する。外部通信は行わない。"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def read_candles(path: Path) -> list[dict]:
    """機能: 足ＣＳＶを型変換して読む。

    引数: path (Path) は読み取り専用のＣＳＶパス。
    返り値: list[dict] は時刻・数値・真偽値を変換した足配列。
    """
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    for row in rows:
        row["time"] = datetime.fromisoformat(row["time"])
        for key in ("open", "high", "low", "close", "volume"):
            row[key] = float(row[key])
        for key in ("closed", "volume_complete"):
            row[key] = row[key].lower() == "true"
    return rows


def summarize_candles(rows: list[dict], minutes: int) -> dict:
    """機能: 足の欠損、時刻順序、重複、価格整合を監査する。

    引数: rows (list[dict]) は足配列、minutes (int) は足の分数。
    返り値: dict は品質統計。
    """
    times = [row["time"] for row in rows]
    gaps = []
    for previous, current in zip(times, times[1:]):
        missing = int((current - previous).total_seconds() // (60 * minutes)) - 1
        if missing > 0:
            gaps.append({"直前": previous.isoformat(), "直後": current.isoformat(), "欠損数": missing})
    invalid = sum(
        not (row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"])
        or any(not math.isfinite(row[key]) for key in ("open", "high", "low", "close", "volume"))
        or row["volume"] < 0
        for row in rows
    )
    return {
        "件数": len(rows),
        "開始": min(times).isoformat(),
        "終了": max(times).isoformat(),
        "時刻重複": len(times) - len(set(times)),
        "時刻逆行": sum(current < previous for previous, current in zip(times, times[1:])),
        "欠損本数": sum(gap["欠損数"] for gap in gaps),
        "欠損区間": gaps,
        "価格等不整合": invalid,
        "未確定足数": sum(not row["closed"] for row in rows),
        "出来高不完全足": [row["time"].isoformat() for row in rows if not row["volume_complete"]],
        "出来高ゼロ足数": sum(row["volume"] == 0 for row in rows),
        "最終足確定": rows[-1]["closed"],
        "出来高合計": sum(row["volume"] for row in rows),
    }


def aggregate_five(rows: list[dict], five: list[dict]) -> dict:
    """機能: １分足を５分単位に集約し、保存済み５分足と照合する。

    引数: rows (list[dict]) は１分足、five (list[dict]) は５分足。
    返り値: dict は欠損と各列の不一致件数。
    """
    groups = defaultdict(list)
    for row in rows:
        stamp = row["time"].replace(minute=row["time"].minute // 5 * 5, second=0, microsecond=0)
        groups[stamp].append(row)
    mismatches = Counter()
    examples = []
    for row in five:
        group = groups.get(row["time"])
        if not group:
            mismatches["対応１分足なし"] += 1
            continue
        expected = {
            "open": group[0]["open"], "high": max(item["high"] for item in group),
            "low": min(item["low"] for item in group), "close": group[-1]["close"],
            "volume": sum(item["volume"] for item in group),
            "volume_complete": all(item["volume_complete"] for item in group),
            "closed": all(item["closed"] for item in group),
        }
        for key, value in expected.items():
            if not math.isclose(row[key], value, abs_tol=1e-7):
                mismatches[key] += 1
                if len(examples) < 5:
                    examples.append({"時刻": row["time"].isoformat(), "列": key, "保存値": row[key], "集約値": value})
    return {
        "比較５分足数": len(five), "列別不一致": dict(mismatches), "例": examples,
        "１分足５本未満の５分区間数": sum(len(group) < 5 for group in groups.values()),
        "保存５分足なし": len(set(groups) - {row["time"] for row in five}),
    }


def quantiles(values: list[float]) -> dict:
    """機能: 観測値の分位点を計算する。

    引数: values (list[float]) は対象数値。
    返り値: dict は最小、中央値、９０％点、最大。
    """
    if not values:
        return {}
    ordered = sorted(values)
    return {"最小": ordered[0], "中央値": median(ordered), "９０％点": ordered[int((len(ordered) - 1) * 0.9)], "最大": ordered[-1]}


def audit_book(path: Path, candles: list[dict]) -> dict:
    """機能: 板を順次読み、重複・約定時刻・価格刻み・足への再集約を監査する。

    引数: path (Path) は生板ファイル、candles (list[dict]) は対応１分足。
    返り値: dict は品質統計。将来価格の方向や収益を集計しない。
    """
    counts = Counter()
    keys = set()
    symbols = set()
    seen = set()
    previous_hash = None
    previous_time = None
    previous_volume = None
    first_volume = None
    final_volume = None
    min_time = None
    max_time = None
    spreads = []
    price_set = set()
    volume_increments = []
    reset_events = []
    unique_times = set()
    trade_time_gaps = []
    price_bars = {}
    volume_bars = defaultdict(float)
    candle_lookup = {row["time"].isoformat(): row for row in candles}
    candle_start = min(row["time"] for row in candles)
    candle_end = max(row["time"] for row in candles) + timedelta(minutes=1)
    with path.open(encoding="utf-8-sig") as source:
        for line in source:
            counts["行数"] += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                counts["不正ＪＳＯＮ"] += 1
                continue
            keys.update(row)
            symbols.add(row.get("SymbolName", ""))
            digest = hashlib.blake2b(line.strip().encode(), digest_size=16).digest()
            counts["同一内容重複"] += digest in seen
            counts["連続同一内容重複"] += digest == previous_hash
            seen.add(digest)
            previous_hash = digest

            # ----------------------------------------
            sell = row.get("Sell1", {}).get("Price")
            buy = row.get("Buy1", {}).get("Price")
            if sell is not None and buy is not None and sell > 0 and buy > 0:
                spreads.append(sell - buy)
                counts["売気配が買気配未満"] += sell < buy
                counts["売買同値"] += sell == buy
            counts["BidPriceとSell1一致"] += row.get("BidPrice") == sell
            counts["AskPriceとBuy1一致"] += row.get("AskPrice") == buy

            # ----------------------------------------
            price = row.get("CurrentPrice")
            stamp = row.get("CurrentPriceTime")
            volume_stamp = row.get("TradingVolumeTime")
            if price is None or stamp is None:
                counts["約定価格または時刻なし"] += 1
            else:
                moment = datetime.fromisoformat(stamp)
                unique_times.add(moment)
                min_time = moment if min_time is None else min(min_time, moment)
                max_time = moment if max_time is None else max(max_time, moment)
                if previous_time is not None:
                    counts["約定時刻逆行"] += moment < previous_time
                    counts["直前と約定時刻同じ"] += moment == previous_time
                    if moment > previous_time:
                        trade_time_gaps.append((moment - previous_time).total_seconds())
                previous_time = moment
                minute = moment.replace(second=0, microsecond=0).isoformat()
                counts["保存時間範囲より前の約定時刻行"] += moment < candle_start
                counts["保存時間範囲内だが足なしの約定時刻行"] += candle_start <= moment < candle_end and minute not in candle_lookup
                if minute not in candle_lookup:
                    counts["保存足範囲外の約定時刻行"] += 1
                else:
                    price_set.add(round(float(price) * 10000))
                    if minute not in price_bars:
                        price_bars[minute] = {"open": price, "high": price, "low": price, "close": price}
                    else:
                        price_bars[minute]["high"] = max(price_bars[minute]["high"], price)
                        price_bars[minute]["low"] = min(price_bars[minute]["low"], price)
                        price_bars[minute]["close"] = price
                counts["価格時刻と出来高時刻不一致"] += stamp != volume_stamp

            # ----------------------------------------
            volume = row.get("TradingVolume")
            if volume is not None:
                if first_volume is None:
                    first_volume = volume
                final_volume = volume
                if previous_volume is not None:
                    change = volume - previous_volume
                    counts["累積出来高減少"] += change < 0
                    if change < 0:
                        reset_events.append({"出来高時刻": volume_stamp, "直前累積値": previous_volume, "累積値": volume})
                    counts["累積出来高不変"] += change == 0
                    if change > 0:
                        volume_increments.append(change)
                        if volume_stamp is not None:
                            minute = datetime.fromisoformat(volume_stamp).replace(second=0, microsecond=0).isoformat()
                            volume_bars[minute] += change
                previous_volume = volume

    # ----------------------------------------
    mismatches = Counter()
    mismatch_examples = []
    maximum_errors = defaultdict(float)
    for stamp, candle in candle_lookup.items():
        if stamp not in price_bars:
            mismatches["対応約定なし"] += 1
            continue
        for key in ("open", "high", "low", "close"):
            if not math.isclose(candle[key], price_bars[stamp][key], abs_tol=1e-7):
                mismatches[key] += 1
                maximum_errors[key] = max(maximum_errors[key], abs(candle[key] - price_bars[stamp][key]))
                mismatch_examples.append({"時刻": stamp, "列": key, "絶対差": abs(candle[key] - price_bars[stamp][key])})
        if not math.isclose(candle["volume"], volume_bars[stamp], abs_tol=1e-7):
            mismatches["volume"] += 1
            maximum_errors["volume"] = max(maximum_errors["volume"], abs(candle["volume"] - volume_bars[stamp]))
            mismatch_examples.append({"時刻": stamp, "列": "volume", "絶対差": abs(candle["volume"] - volume_bars[stamp])})
    sorted_prices = sorted(price_set)
    differences = [b - a for a, b in zip(sorted_prices, sorted_prices[1:])]
    tick = math.gcd(*differences) / 10000 if differences else None
    counts["異なる約定時刻数"] = len(unique_times)
    return {
        "統計": dict(counts), "銘柄名": sorted(symbols), "キー": sorted(keys),
        "約定時刻最小": min_time.isoformat() if min_time else None,
        "約定時刻最大": max_time.isoformat() if max_time else None,
        "観測価格最小刻み": tick,
        "売１価格引く買１価格": quantiles(spreads),
        "正の売１価格引く買１価格": quantiles([value for value in spreads if value > 0]),
        "約定時刻更新間隔秒": quantiles(trade_time_gaps),
        "累積出来高増分": quantiles(volume_increments),
        "最初の累積出来高": first_volume, "最後の累積出来高": final_volume,
        "累積出来高差": final_volume - first_volume if final_volume is not None else None,
        "累積出来高リセット": reset_events,
        "１分足再現不一致": dict(mismatches), "不一致時刻例": mismatch_examples,
        "再現絶対誤差最大": dict(maximum_errors),
        "注意": "受信時刻フィールドがないため通信遅延や板更新時刻は判定不能。約定時刻が不変の板行を新しい約定として数えない。",
    }


def main() -> None:
    """機能: 保存データの監査結果を日本語のＪＳＯＮと文書へ保存する。

    引数: なし。
    返り値: None。
    """
    results = {}
    for symbol in ("NK225", "TOPIX"):
        for path in sorted((ROOT / "candle_1min" / symbol).glob("*.csv")):
            name = path.stem
            print(f"監査中: {symbol} {name}", flush=True)
            one = read_candles(path)
            five = read_candles(ROOT / "candle_5min" / symbol / path.name)
            results[f"{symbol}/{name}"] = {
                "１分足": summarize_candles(one, 1), "５分足": summarize_candles(five, 5),
                "足同士照合": aggregate_five(one, five),
                "板": audit_book(ROOT / "book" / symbol / f"{name}.jsonl", one),
            }
    (OUT / "audit.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 保存データ品質監査", "",
        "対象は保存済み３セッションの２銘柄。現在セッションＡＰＩは呼んでいない。評価用９月２２日日中は品質統計のみ計算し、方向別成績や収益は計算していない。", "",
        "| 銘柄・セッション | １分足 | １分欠損 | ５分足 | ５分欠損 | 未確定１分 | 生板行数 |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for label, result in results.items():
        one, five, book = result["１分足"], result["５分足"], result["板"]
        lines.append(f"| {label} | {one['件数']} | {one['欠損本数']} | {five['件数']} | {five['欠損本数']} | {one['未確定足数']} | {book['統計']['行数']} |")
    lines.extend(["", "## 詳細", ""])
    for label, result in results.items():
        one, five, book = result["１分足"], result["５分足"], result["板"]
        stats = book["統計"]
        lines.extend([
            f"### {label}", "",
            f"- 時間範囲: {one['開始']} ～ {one['終了']}。１分足時刻重複 {one['時刻重複']}、逆行 {one['時刻逆行']}、価格等不整合 {one['価格等不整合']}。",
            f"- 出来高不完全な１分足: {'、'.join(one['出来高不完全足']) or 'なし'}。ゼロ出来高 {one['出来高ゼロ足数']} 本。",
            f"- １分→５分集約の不一致: {json.dumps(result['足同士照合']['列別不一致'], ensure_ascii=False)}。１分足５本未満の区間 {result['足同士照合']['１分足５本未満の５分区間数']}。",
            f"- 板→１分足再現の不一致: {json.dumps(book['１分足再現不一致'], ensure_ascii=False)}。列別絶対差最大: {json.dumps(book['再現絶対誤差最大'], ensure_ascii=False)}。",
            f"- 生板の約定時刻逆行 {stats.get('約定時刻逆行', 0)}、直前と同じ約定時刻 {stats.get('直前と約定時刻同じ', 0)}、完全同一内容重複 {stats.get('同一内容重複', 0)}。",
            f"- 累積出来高差 {book['累積出来高差']}、１分足出来高合計 {one['出来高合計']}。累積出来高減少 {stats.get('累積出来高減少', 0)}。",
            f"- 観測価格最小刻み {book['観測価格最小刻み']}。売１価格－買１価格の分位点: {json.dumps(book['売１価格引く買１価格'], ensure_ascii=False)}。",
            f"- 売１が買１未満 {stats.get('売気配が買気配未満', 0)}、売買同値 {stats.get('売買同値', 0)}。", "",
        ])
    lines.extend([
        "## 検証への扱い", "",
        "- 足時刻は区間開始。時刻ｔの１分足の終値・高安・出来高を使用できるのはｔ＋１分以降、５分足はｔ＋５分以降。",
        "- 生板は受信時刻を持たない。CurrentPriceTime は最後の約定時刻であり、各行の板の更新時刻ではない。保存順序だけでは厳密な通信遅延・足確定時刻の再現はできない。",
        "- TradingVolume は累積出来高である。同じ値の板行を足してはいけない。足の出来高は非負の差分を時刻で集約する。９月２１日日中・夜間の先頭１分足は volume_complete=false、９月２２日日中は全足 true。初回基準設定や累積値リセットを区別する必要がある。",
        "- 夜間ファイルでは累積出来高が１回リセットされる。ファイル先頭には前セッションの約定時刻を保持する板が含まれる。セッション境界は足の時間範囲で切り、前セッションの残存約定時刻を除外する。",
        "- BidPrice / AskPrice の英語名を一般的な買気配／売気配へ直訳しない。板階層 Sell1（売側）、Buy1（買側）を参照する。非同期更新や板寄せに見える交差・同値の状態は即時約定可能なスプレッド推定から除外する。",
        "- 欠損１分足の各時刻には、生板にも対応する CurrentPriceTime が存在しない。観測範囲では無約定区間と整合するが、受信時刻や収集ログがなく収集停止との区別は断定できない。特徴量の窓は時刻差と連続性を確認し、存在する行を等間隔扱いしない。",
        "- 保存範囲終端の閉場後データは存在しない。最後の足の closed=true はファイル内の確定フラグであり、翌区間への継続やセッション終端までの網羅性を保証しない。",
        "- 板からの素朴な再集約と足の間には少数の価格・出来高差異がある。価格差は列別絶対差最大を確認し、検証価格系列は１分足ＣＳＶを正本として固定する。受信時刻・足生成実装がないため差異原因は確定できない。",
        "", "再現: `python work/wave_research/audit.py`。機械可読詳細は `audit.json`。",
    ])
    (OUT / "audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("品質監査完了", flush=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
