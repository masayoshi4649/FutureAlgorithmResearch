"""追加された保存夜間データの品質を監査し、凍結済み抽出器で板特徴を生成する。"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SESSION = "2026-09-22_Night"
CUTOFF = datetime.fromisoformat("2026-09-23T00:28:00+09:00")
SPEC = importlib.util.spec_from_file_location("frozen_book_features", ROOT / "work/wave_v2/book_features.py")
BOOK = importlib.util.module_from_spec(SPEC)
sys.dont_write_bytecode = True
SPEC.loader.exec_module(BOOK)


def truth(value: object) -> bool:
    """保存形式の異なる真偽値を統一する。

    引数: value（object）CSV文字列またはJSON真偽値。
    返り値: bool。値が真を表す場合のみ True。
    """
    return value is True or str(value).lower() == "true"


def read_candles(instrument: str, period: int) -> list[dict]:
    """読み取り専用フォルダから追加足を読み込み、型を統一する。

    引数: instrument（str）銘柄、period（int）足の分数。
    返り値: list[dict]。時刻順の足。
    """
    path = ROOT / f"candle_{period}min" / instrument / f"{SESSION}.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return [canonical(row) for row in rows]


def canonical(row: dict) -> dict:
    """足の項目を比較可能な型にそろえる。

    引数: row（dict）足データ。
    返り値: dict。数値、真偽値、ISO時刻を含む足。
    """
    return {
        "time": row["time"],
        **{key: float(row[key]) for key in ("open", "high", "low", "close", "volume")},
        "volume_complete": truth(row.get("volume_complete", row.get("volumeComplete"))),
        "closed": truth(row.get("closed")),
    }


def gaps(times: list[datetime], step: int) -> dict:
    """保存足の時間間隔と欠けた時刻を数える。

    引数: times（list[datetime]）観測時刻、step（int）期待間隔の分数。
    返り値: dict。欠落本数、最長間隔、欠落時刻。
    """
    if not times:
        return {"missing_count": 0, "max_gap_minutes": 0, "missing_times": []}
    known = set(times)
    cursor, missing = min(times), []
    while cursor <= max(times):
        if cursor not in known:
            missing.append(cursor.isoformat())
        cursor += timedelta(minutes=step)
    return {
        "missing_count": len(missing),
        "max_gap_minutes": max(((b - a).total_seconds() / 60 for a, b in zip(times, times[1:])), default=0),
        "missing_times": missing,
    }


def candle_audit(instrument: str, period: int, rows: list[dict]) -> dict:
    """足の時刻、OHLC整合性と旧取得分との一致を監査する。

    引数: instrument（str）銘柄、period（int）分数、rows（list[dict]）保存足。
    返り値: dict。品質検査と旧確定足比較結果。
    """
    times = [datetime.fromisoformat(row["time"]) for row in rows]
    cache_path = ROOT / "work/wave_research/現在セッション固定" / f"{instrument}_{period}min.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8-sig"))
    prior = [canonical(row) for row in cache["data"] if truth(row["closed"]) and datetime.fromisoformat(row["time"]) + timedelta(minutes=period) <= CUTOFF]
    current = {row["time"]: row for row in rows if datetime.fromisoformat(row["time"]) + timedelta(minutes=period) <= CUTOFF}
    differences = []
    for row in prior:
        now = current.get(row["time"])
        for key, value in row.items():
            if now is None or now[key] != value:
                differences.append({"time": row["time"], "field": key, "prior": value, "current": None if now is None else now[key]})
    prior_times = {row["time"] for row in prior}
    return {
        "instrument": instrument, "period_minutes": period, "rows": len(rows),
        "first": times[0].isoformat(), "last": times[-1].isoformat(),
        "duplicate_time_rows": len(times) - len(set(times)),
        "time_reversals": sum(a > b for a, b in zip(times, times[1:])),
        "not_closed_rows": sum(not row["closed"] for row in rows),
        "incomplete_volume_times": [row["time"] for row in rows if not row["volume_complete"]],
        "invalid_ohlc_times": [row["time"] for row in rows if not row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"]],
        "negative_volume_times": [row["time"] for row in rows if row["volume"] < 0],
        **gaps(times, period),
        "cache_as_of": cache["snapshot"]["asOf"], "cache_closed_rows_compared": len(prior),
        "cache_differences": differences,
        "extra_historical_times": sorted(set(current) - prior_times),
    }


def aggregation_audit(minutes: list[dict], fives: list[dict]) -> dict:
    """保存一分足を五分単位に束ね、保存五分足との一致を調べる。

    引数: minutes（list[dict]）一分足、fives（list[dict]）五分足。
    返り値: dict。OHLCVと出来高完全性の相違。
    """
    groups = defaultdict(list)
    for row in minutes:
        time = datetime.fromisoformat(row["time"])
        bucket = time.replace(minute=time.minute // 5 * 5)
        groups[bucket.isoformat()].append(row)
    differences = []
    for row in fives:
        sub = groups.get(row["time"], [])
        if not sub:
            differences.append({"time": row["time"], "reason": "対応する一分足なし"})
            continue
        computed = {"open": sub[0]["open"], "high": max(x["high"] for x in sub), "low": min(x["low"] for x in sub), "close": sub[-1]["close"], "volume": sum(x["volume"] for x in sub), "volume_complete": all(x["volume_complete"] for x in sub)}
        for key, value in computed.items():
            if value != row[key]:
                differences.append({"time": row["time"], "field": key, "one_minute_aggregate": value, "five_minute_value": row[key]})
    return {"compared_rows": len(fives), "differences": differences, "missing_five_minute_times": sorted(set(groups) - {row["time"] for row in fives})}


def extract_book(instrument: str, candles: list[dict]) -> tuple[list[dict], dict]:
    """凍結した板抽出器を再利用し、同時に原時刻と先読みを監査する。

    引数: instrument（str）銘柄、candles（list[dict]）一分足。
    返り値: tuple[list[dict], dict]。特徴量と監査。
    """
    path = ROOT / "book" / instrument / f"{SESSION}.jsonl"
    start, end = BOOK.bounds(path)
    tick = 10 if instrument == "NK225" else .5
    processor = BOOK.Extractor(start, end, tick)
    prefix = BOOK.Extractor(start, CUTOFF, tick)
    digest = hashlib.sha256()
    raw_times, outside_times, null_times = Counter(), Counter(), 0
    first_row, last_row = None, None
    quote_time_keys = set()
    raw_ohlc = {}
    with path.open("rb") as stream:
        for line in stream:
            digest.update(line)
            row = json.loads(line)
            if first_row is None:
                first_row = row
            last_row = row
            quote_time_keys.update(key for key in row if "Time" in key or "time" in key)
            processor.accept(row)
            stamp_text = row.get("CurrentPriceTime")
            if not stamp_text:
                null_times += 1
                continue
            stamp = datetime.fromisoformat(stamp_text)
            raw_times[stamp] += 1
            if stamp < CUTOFF:
                prefix.accept(row)
            if not start <= stamp < end:
                outside_times[stamp] += 1
                continue
            price = row.get("CurrentPrice")
            if price is not None:
                minute = stamp.replace(second=0, microsecond=0).isoformat()
                if minute not in raw_ohlc:
                    raw_ohlc[minute] = {"open": price, "high": price, "low": price, "close": price, "last_trade_time": stamp.isoformat()}
                else:
                    target = raw_ohlc[minute]
                    target["high"] = max(target["high"], price)
                    target["low"] = min(target["low"], price)
                    target["close"] = price
                    target["last_trade_time"] = stamp.isoformat()
    rows = processor.rows(instrument, SESSION)
    prefix_rows = prefix.rows(instrument, SESSION)
    historical_rows = [row for row in rows if datetime.fromisoformat(row["available_at"]) <= CUTOFF]
    ohlc_diff = []
    for candle in candles:
        raw = raw_ohlc.get(candle["time"])
        for key in ("open", "high", "low", "close"):
            if raw is None or raw[key] != candle[key]:
                ohlc_diff.append({"time": candle["time"], "field": key, "raw": None if raw is None else raw[key], "candle": candle[key], "last_raw_trade_time": None if raw is None else raw["last_trade_time"]})
    delays = sorted(processor.delays)
    raw_valid_minutes = set(raw_ohlc)
    candle_times = {row["time"] for row in candles}
    audit = dict(processor.audit)
    audit.update({
        "source": str(path.relative_to(ROOT)), "source_sha256": digest.hexdigest(),
        "start": start.isoformat(), "end_exclusive": end.isoformat(),
        "first_raw_trade_time": first_row.get("CurrentPriceTime"), "last_raw_trade_time": last_row.get("CurrentPriceTime"),
        "raw_timestamp_field_names": sorted(quote_time_keys),
        "raw_distinct_trade_timestamps": len(raw_times), "raw_repeated_trade_timestamp_rows": sum(count - 1 for count in raw_times.values()),
        "raw_outside_timestamps": {key.isoformat(): count for key, count in sorted(outside_times.items())},
        "null_trade_times": null_times,
        "anchor_delay_median_seconds": median(delays),
        "anchor_delay_p95_seconds": delays[int(.95 * (len(delays) - 1))], "anchor_delay_max_seconds": max(delays),
        "feature_first_time": rows[0]["time"], "feature_last_time": rows[-1]["time"],
        "feature_first_available": rows[0]["available_at"], "feature_last_available": rows[-1]["available_at"],
        "feature_duplicate_times": len(rows) - len({row["time"] for row in rows}),
        "feature_availability_invalid_count": sum(datetime.fromisoformat(row["available_at"]) != datetime.fromisoformat(row["time"]) + timedelta(minutes=1) or datetime.fromisoformat(row["available_at"]) > end for row in rows),
        "prefix_cutoff": CUTOFF.isoformat(), "prefix_rows": len(prefix_rows), "historical_rows": len(historical_rows),
        "prefix_features_unchanged": prefix_rows == historical_rows,
        "raw_candle_ohlc_differences": ohlc_diff,
        "raw_price_minutes_without_candle": sorted(raw_valid_minutes - candle_times),
        "candle_minutes_without_raw_price": sorted(candle_times - raw_valid_minutes),
    })
    return rows, audit


def report(audit: dict) -> str:
    """検証上の注意点を含む日本語の監査報告を組み立てる。

    引数: audit（dict）監査の全結果。
    返り値: str。Markdown本文。
    """
    lines = ["# 追加データ監査", "", "対象は保存済み 2026-09-22_Night の NK225・TOPIX。APIには接続せず、元データと前回のコード・設定・結果は変更していない。", "", "## 足の品質", "", "|銘柄|足|本数|最初→最後|時刻重複|未確定|時刻欠落数|最長時刻間隔（分）|", "|---|---:|---:|---|---:|---:|---:|---:|"]
    for row in audit["candles"]:
        lines.append(f"|{row['instrument']}|{row['period_minutes']}分|{row['rows']}|{row['first'][11:16]}→翌{row['last'][11:16]}|{row['duplicate_time_rows']}|{row['not_closed_rows']}|{row['missing_count']}|{row['max_gap_minutes']:g}|")
    lines.extend(["", "『時刻欠落』は最初から最後までの時間枠に足がないことを指す。価格更新がない分は足が生成されないため、欠落数をそのまま収集障害数とは扱わない。終端は両銘柄とも翌05:54であり、06:00までの完全収録は確認できない。前回ルールの05:50返済を再生する時間範囲はある。", "", "## 旧取得分との比較", "", "確定足の終端が 2026-09-23 00:28以前にある旧キャッシュを比較した。取得時刻は約00:28:30〜33で、旧取得時に未確定だった足を過去改変の検査対象には含めない。", "", "|銘柄|足|比較した旧確定足|値の相違項目数|同区間の追加時刻数|", "|---|---:|---:|---:|---:|"])
    for row in audit["candles"]:
        lines.append(f"|{row['instrument']}|{row['period_minutes']}分|{row['cache_closed_rows_compared']}|{len(row['cache_differences'])}|{len(row['extra_historical_times'])}|")
    lines.extend(["", "## 一分足と五分足、生板との対応", ""])
    for instrument, row in audit["aggregation"].items():
        lines.append(f"- {instrument}: 一分足から再集約した五分足 {row['compared_rows']} 本、OHLCV・出来高完全性の相違 {len(row['differences'])} 項目、五分足欠落 {len(row['missing_five_minute_times'])} 枠。")
    for row in audit["books"]:
        lines.append(f"- {row['instrument']}: 生板の CurrentPriceTime ごとの価格を一分集約したOHLCと保存一分足の相違 {len(row['raw_candle_ohlc_differences'])} 項目。")
    lines.extend(["", "生板との相違は NK225 の18:51・翌00:02・00:03、TOPIX の21:51・翌02:45の計5分に限られ、すべて1ティック。これらの生板最終約定時刻は各分の59秒であり、分の確定処理と遅れて到着したイベントの扱いに由来する可能性がある。ただし受信時刻と収集処理がないため原因の断定はできない。新保存一分足と旧取得一分足の一致から、今回追加による過去の価格改変ではない。今回の価格評価は保存足を正本とし、生板から作り直して差し替えない。", "", "|銘柄|足時刻|項目|生板再集約|保存足|", "|---|---|---|---:|---:|"])
    for row in audit["books"]:
        for diff in row["raw_candle_ohlc_differences"]:
            lines.append(f"|{row['instrument']}|{diff['time']}|{diff['field']}|{diff['raw']:g}|{diff['candle']:g}|")
    lines.extend(["", "最初の17:00足は両銘柄とも volume_complete=false。初回の累積出来高差分が欠けるため、絶対出来高の完全性は保証されない。他の不完全出来高時刻は JSON に記録した。", "", "## 生板特徴と利用可能時刻", "", "前回の book_features.py の Extractor をそのまま再利用した。板数量の偏り、OFI、気配方向、出来高方向など全列は前回と同じ定義。板の受信時刻は保存されておらず、CurrentPriceTime は最終約定時刻のため、同時刻の多数行を単純な重複として捨てない。次の約定時刻が到来してから前ブロックを解放し、その解放先の一分が終わる時刻を available_at とする。末尾ブロックは破棄する。この遅延は先読みを避けるためであり、板の厳密な受信時刻の再現ではない。", "", "|銘柄|生板行|範囲外行|有効板更新|特徴量の分数|解放遅延 中央値/95%/最大（秒）|最終利用可能時刻|", "|---|---:|---:|---:|---:|---|---|"])
    for row in audit["books"]:
        lines.append(f"|{row['instrument']}|{row['raw_rows']}|{row.get('outside_session_rows', 0)}|{row.get('valid_quote_events', 0)}|{row['feature_minutes']}|{row['anchor_delay_median_seconds']:g}/{row['anchor_delay_p95_seconds']:g}/{row['anchor_delay_max_seconds']:g}|{row['feature_last_available']}|")
    lines.extend(["", "先頭の前日中セッションの約定状態は範囲外として除外した。同一約定時刻に後から記録された板状態を、その約定時刻へ遡って利用していない。00:28より前でファイルを打ち切る再生と、全件から00:28以前の利用可能特徴を切り出す再生を比較した。"])
    for row in audit["books"]:
        result = "完全一致" if row["prefix_features_unchanged"] else "不一致あり"
        lines.append(f"- {row['instrument']}: 特徴量 {row['prefix_rows']} 行が{result}、利用可能時刻異常={row['feature_availability_invalid_count']} 件。")
    lines.extend(["", "両銘柄で観測一分足時刻が一致する本数は " + str(audit["cross_instrument"]["one_minute_common_rows"]) + " 本。相手指数の確認は確定後に利用できた情報だけを結合し、将来時刻への前方補完を行わないこと。", "", "詳細数値、相違の全項目、欠落時刻、ファイルSHA-256は 追加データ監査.json に記録。"])
    return "\n".join(lines) + "\n"


def main() -> None:
    """監査と新規板特徴の保存を行う。

    引数: なし。
    返り値: None。作業フォルダにのみ成果物を書き込む。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    sys.stdout.reconfigure(encoding="utf-8")
    BOOK.self_test()
    audit = {"session": SESSION, "api_requested": False, "extractor_sha256": hashlib.sha256((ROOT / "work/wave_v2/book_features.py").read_bytes()).hexdigest(), "candles": [], "aggregation": {}, "books": []}
    saved = {}
    for instrument in ("NK225", "TOPIX"):
        minutes, fives = read_candles(instrument, 1), read_candles(instrument, 5)
        saved[instrument] = minutes
        for period, rows in ((1, minutes), (5, fives)):
            audit["candles"].append(candle_audit(instrument, period, rows))
        audit["aggregation"][instrument] = aggregation_audit(minutes, fives)

        # ----------------------------------------
        # 元コードの出力関数を呼ばず、この監査専用フォルダにのみ板特徴を保存する。
        features, book_audit = extract_book(instrument, minutes)
        book_audit["instrument"] = instrument
        audit["books"].append(book_audit)
        path = OUT / f"板特徴_{instrument}_{SESSION}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=BOOK.FIELDS)
            writer.writeheader()
            writer.writerows(features)
        print(json.dumps({"完了": instrument, "特徴量本数": len(features), "原板行数": book_audit["raw_rows"], "過去特徴量一致": book_audit["prefix_features_unchanged"]}, ensure_ascii=False), flush=True)
    left = {row["time"] for row in saved["NK225"]}
    right = {row["time"] for row in saved["TOPIX"]}
    audit["cross_instrument"] = {"one_minute_common_rows": len(left & right), "nk225_only_times": sorted(left - right), "topix_only_times": sorted(right - left)}
    (OUT / "追加データ監査.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "追加データ監査.md").write_text(report(audit), encoding="utf-8")


if __name__ == "__main__":
    main()
