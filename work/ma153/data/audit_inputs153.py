"""研究153の保存入力を全文指紋・足の確定時刻・セッション終端で資格確認する。売買再生はしない。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATA = ROOT.parent / "JP_OSE_Data" / "future"
JST = timezone(timedelta(hours=9))


def read_json(path: Path):
    """保存JSONを復号する。

    引数: path(Path)は入力資料。
    返り値: dict又はlistは資料の内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def identity(path: Path) -> str:
    """保存先比較の大文字小文字と絶対位置を正規化する。

    引数: path(Path)は比較対象。
    返り値: strはWindows上での同一性キー。
    """
    return os.path.normcase(str(path.resolve()))


def fingerprint(path: Path) -> dict:
    """資料全文をSHA256照合し、読取中に元資料が変更されていないことを確認する。

    引数: path(Path)は読み取り専用の入力。
    返り値: dictは存在・指紋・サイズ・更新時刻と読取不変性。
    """
    value = {"path": path.resolve().as_posix(), "exists": path.is_file()}
    if not value["exists"]:
        return value
    before = path.stat()
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    value.update(bytes=before.st_size, mtime_ns=before.st_mtime_ns, sha256=sha,
                 unchanged_during_read=(before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns))
    return value


def timestamp(value):
    """明示時計を日本時間のdatetimeへ変換する。

    引数: value(str又はNone)は元時計。
    返り値: datetime又はNoneは有効なタイムゾーン付き時計。無時差の時計は採用しない。
    """
    if not isinstance(value, str):
        return None
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return at.astimezone(JST) if at.tzinfo is not None else None
    except ValueError:
        return None


def positive(value) -> bool:
    """有限で正の価格又は数量であるか判定する。

    引数: value(any)は元JSON値。
    返り値: boolは正常値のとき真。
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def normal_row(raw: bytes, start: datetime, end: datetime, cutoff: datetime | None) -> dict | None:
    """一行の現在価格時計と正常BBOを確認する。

    引数: raw(bytes)は原行、start/end/cutoff(datetime又はNone)は対象範囲。
    返り値: dict又はNoneは採用可能な最良気配。TradingVolumeTimeで判定しない。
    """
    row = json.loads(raw)
    at = timestamp(row.get("CurrentPriceTime"))
    if at is None or at < start or at > end or (cutoff is not None and at >= cutoff):
        return None
    buy, sell = row.get("Buy1") or {}, row.get("Sell1") or {}
    if not all(positive(x) for x in (row.get("CurrentPrice"), buy.get("Price"), sell.get("Price"), buy.get("Qty"), sell.get("Qty"))) or sell["Price"] <= buy["Price"]:
        return None
    return {"time": at.isoformat(), "unix": at.timestamp(), "last": row["CurrentPrice"], "bid": buy["Price"], "ask": sell["Price"],
            "independent_receive_clock_present": any(k in row for k in ("ReceivedAt", "received_at", "ReceiveTime", "receivedAt"))}


def book_edges(path: Path, start: datetime, end: datetime, cutoff: datetime | None) -> dict:
    """原文の先頭と末尾を読み、最初と終端の正常BBOを確認する。

    引数: path(Path)、start/end/cutoff(datetime又はNone)は入力と期間。
    返り値: dictは先頭・末尾正常行。末尾4MBで見つからない場合だけ全行を走査する。
    """
    if not path.is_file():
        return {"first": None, "last": None, "exists": False}
    first, last, head_rows = None, None, 0
    with path.open("rb") as stream:
        for raw in stream:
            head_rows += 1
            if raw.strip():
                first = normal_row(raw, start, end, cutoff)
                if first:
                    break
        offset = max(0, path.stat().st_size - 4 * 1024 * 1024)
        stream.seek(offset)
        if offset:
            stream.readline()
        tail = stream.read().splitlines()
    for raw in reversed(tail):
        if raw.strip():
            last = normal_row(raw, start, end, cutoff)
            if last:
                break
    full_fallback = last is None
    if full_fallback:
        with path.open("rb") as stream:
            for raw in stream:
                if raw.strip():
                    candidate = normal_row(raw, start, end, cutoff)
                    if candidate:
                        last = candidate
    return {"first": first, "last": last, "head_rows_read": head_rows, "tail_rows_read": len(tail), "tail_full_scan_fallback": full_fallback,
            "method": "全文指紋照合後に先頭・末尾原行を独立再読。全行の時計逆行統計は既存141/145を参照。"}


def inspect_candles(path: Path, interval: int, start: datetime, end: datetime, cutoff: datetime | None) -> dict:
    """分足の全行を読み、確定・期間・欠落・最早公開時計を検査する。

    引数: path(Path)、interval(int秒)、start/end/cutoff(datetime又はNone)。
    返り値: dictは資格と公開時刻。保存時のclosedを事前公開とはみなさない。
    """
    if not path.is_file():
        return {"exists": False, "eligible_closed_rows": 0}
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    else:
        root = read_json(path)
        rows = root.get("data", root.get("Data", []))
        rows = [{str(k).lower(): v for k, v in row.items()} for row in rows]
    observed, eligible, invalid = [], [], 0
    for row in rows:
        at = timestamp(row.get("time"))
        if at is None:
            invalid += 1
            continue
        values = []
        try:
            values = [float(row[name]) for name in ("open", "high", "low", "close")]
        except (ValueError, TypeError, KeyError):
            invalid += 1
            continue
        if not all(positive(value) for value in values) or values[1] < max(values[0], values[2], values[3]) or values[2] > min(values[0], values[1], values[3]):
            invalid += 1
            continue
        closed = str(row.get("closed", "")).lower() == "true"
        observed.append(at)
        close = at + timedelta(seconds=interval)
        if closed and at >= start and close <= end and (cutoff is None or close < cutoff):
            eligible.append(at)
    ordered = sorted(eligible)
    missing = sum(max(0, int((b - a).total_seconds() // interval) - 1) for a, b in zip(ordered, ordered[1:]))
    return {"exists": True, "rows": len(rows), "invalid_rows": invalid, "eligible_closed_rows": len(eligible),
            "duplicates": len(eligible) - len(set(eligible)), "chronological": eligible == ordered,
            "missing_intervals_between_first_last": missing,
            "first": ordered[0].isoformat() if ordered else None, "last": ordered[-1].isoformat() if ordered else None,
            "earliest_closed_available": (ordered[0] + timedelta(seconds=interval)).isoformat() if ordered else None,
            "earliest_available_with_legacy_delay60": (ordered[0] + timedelta(seconds=interval+60)).isoformat() if ordered else None,
            "publication_clock_measured": False,
            "availability_rule": "closed=true、足開始+足幅を過ぎてから使用。従来145/149比較は更に60秒の公開遅延。受信時計不明なので実際の公開時刻とは断定しない。"}


def scene_clock(session: str) -> tuple[datetime, datetime]:
    """保存セッション名から資格確認の開始終了時計を作る。

    引数: session(str)はYYYY-MM-DD_Day/Night。
    返り値: tuple[datetime,datetime]は日本時間の開始・終了。
    """
    day = datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    if session.endswith("_Day"):
        return day.replace(hour=8, minute=45), day.replace(hour=15, minute=45)
    return day.replace(hour=17), (day + timedelta(days=1)).replace(hour=6)


def main() -> None:
    """全保存原資料と取得済み途中資料を照合し、登録用の独立目録を作る。

    引数: なし。
    返り値: None。原資料・149目録・既存会計・共有台帳へ書き込まない。
    """
    started = time.perf_counter()
    old145_path = ROOT / "work/research145_data/全保存資料の再照合145.json"
    old149_path = ROOT / "work/preus149/data/原資料一覧149.json"
    old145, old149 = read_json(old145_path), read_json(old149_path)
    prior145 = {identity(Path(row["path"])): row for row in old145["files"]}
    prior149 = {identity(Path(row["path"])): row for scene in old149["sessions"] for row in scene["fingerprints"]}
    coverage145 = {(row["symbol"], row["session"]): row for row in old145["sessions_detail"]}
    night149 = {row["session"]: row for row in old149["sessions"]}
    names = {symbol: sorted(path.name for path in (DATA / symbol).iterdir() if path.is_dir()) for symbol in ("NK225", "TOPIX")}
    scenes, paths = [], set()
    for name in sorted(set(names["NK225"]) | set(names["TOPIX"])):
        start, end = scene_clock(name)
        scene = {"session": name, "kind": name.rsplit("_", 1)[1], "start": start.timestamp(), "end": end.timestamp(),
                 "force_close": end.timestamp()-600, "us_open": night149.get(name, {}).get("us_open", 0),
                 "cutoff": end.timestamp()+60, "partial": False, "books": {}, "candles": {}, "source_kind": "保存フォルダ"}
        for symbol in ("NK225", "TOPIX"):
            folder = DATA / symbol / name
            scene["books"][symbol] = (folder / "book.jsonl").as_posix()
            scene["candles"][symbol] = {"60": (folder / "candle_1min.csv").as_posix(), "300": (folder / "candle_5min.csv").as_posix()}
            paths.update([folder / "book.jsonl", folder / "candle_1min.csv", folder / "candle_5min.csv"])
        scenes.append(scene)
    for saved in old149["sessions"]:
        if not saved["partial"]:
            continue
        scene = {key: saved[key] for key in ("session", "start", "end", "force_close", "us_open", "cutoff", "partial", "books", "candles")}
        scene.update(kind=scene["session"].rsplit("_", 1)[1], source_kind="取得済み既知途中・追加APIなし")
        scenes.append(scene)
        for symbol in ("NK225", "TOPIX"):
            paths.add(Path(scene["books"][symbol]))
            paths.update(Path(value) for value in scene["candles"][symbol].values())

    # ----------------------------------------
    # 内容を再読して同一性を証明する。メタデータ一致だけでSHAを転記しない。
    fingerprints = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        for count, item in enumerate(executor.map(fingerprint, sorted(paths)), 1):
            key = identity(Path(item["path"]))
            for version, prior in (("145", prior145.get(key)), ("149", prior149.get(key))):
                item["previous"+version+"_sha256"] = prior.get("sha256") if prior else None
                item["matches_previous"+version] = item.get("sha256") == prior["sha256"] if prior and item["exists"] else None
            fingerprints[key] = item
            if count % 50 == 0:
                print(f"SHA {count}/{len(paths)} {time.perf_counter()-started:.1f}s", flush=True)

    # ----------------------------------------
    # 確定足は全行、原板資格は指紋一致を前提に端部だけ再確認する。
    for index, scene in enumerate(scenes, 1):
        start, end = datetime.fromtimestamp(scene["start"], JST), datetime.fromtimestamp(scene["end"], JST)
        cutoff = datetime.fromtimestamp(scene["cutoff"], JST) if scene["partial"] else None
        scene["qualification"], scene["fingerprints"] = {}, []
        for symbol in ("NK225", "TOPIX"):
            book = Path(scene["books"][symbol])
            qualified = book_edges(book, start, end, cutoff)
            candle_result = {key: inspect_candles(Path(path), int(key), start, end, cutoff) for key, path in scene["candles"][symbol].items()}
            info = {"book": qualified, "candles": candle_result, "previous145_coverage": coverage145.get((symbol, scene["session"]))}
            last, first = qualified["last"], qualified["first"]
            gap = scene["end"] - last["unix"] if last else None
            info.update(first_usable_at=first["time"] if first else None, last_usable_at=last["time"] if last else None,
                        final_gap_seconds=gap, final_quote_within_previous_six_minutes=gap is not None and 0 <= gap <= 360,
                        opening_gap_seconds=first["unix"]-scene["start"] if first else None,
                        force_close_quote_available=bool(last and last["unix"] >= scene["force_close"]))
            files = [fingerprints[identity(book)]] + [fingerprints[identity(Path(path))] for path in scene["candles"][symbol].values()]
            available = all(row["exists"] and row["bytes"] > 0 and row["unchanged_during_read"] for row in files)
            info["all_three_present_unchanged"] = available
            info["eligible_complete_session"] = available and bool(first and last) and info["final_quote_within_previous_six_minutes"] and not scene["partial"] and all(value["eligible_closed_rows"] > 0 and value["invalid_rows"] == 0 for value in candle_result.values())
            info["qualification_note"] = "終端6分以内の正常気配による完了資格。15:45/06:00ちょうどの約定・全時刻無欠測・実受信時計を証明しない。"
            scene["qualification"][symbol] = info
            scene["fingerprints"].extend(files)
        scene["complete_for_both"] = all(value["eligible_complete_session"] for value in scene["qualification"].values())
        if index % 10 == 0:
            print(f"EDGES {index}/{len(scenes)} {time.perf_counter()-started:.1f}s", flush=True)

    mismatches = [item for item in fingerprints.values() if item.get("matches_previous145") is False or item.get("matches_previous149") is False or not item.get("unchanged_during_read", False)]
    result = {
        "created_at": datetime.now(JST).isoformat(), "purpose": "研究153の資料資格のみ。売買・損益の新規再生なし。",
        "API_calls": 0, "financial_replays": 0, "ledger_changes": 0,
        "provenance": [fingerprint(old145_path), fingerprint(old149_path)],
        "saved_counts": {symbol: {"all": len(values), "Day": sum(name.endswith("_Day") for name in values), "Night": sum(name.endswith("_Night") for name in values)} for symbol, values in names.items()},
        "source_file_count": len(fingerprints), "content_bytes_read_for_hash": sum(item.get("bytes", 0) for item in fingerprints.values()),
        "mismatches": mismatches, "sessions": scenes,
        "complete_for_both": sum(scene["complete_for_both"] for scene in scenes), "known_partial": sum(scene["partial"] for scene in scenes),
        "assumptions": {
            "fee_yen": 0, "products": {"NK225": {"product": "NK225mini", "cap_per_side": 10, "point_value": 100}, "TOPIX": {"product": "TOPIXmini", "cap_per_side": 10, "point_value": 1000}},
            "force_close": "終了10分前に全返済判断し、次の正常板で約定。終端資格の6分とは別。",
            "primary_features": "原板中値の時間加重SMA。窓60/180/300/600秒、傾き差30/60秒。同時計多行は時間重み0、正常BBOの保持は120秒まで。その先及び不正板から未知区間。分足は指標入力にしない。",
            "candles": "チャート用参考のみ。保存のtimeは足開始。closed=trueでも判断時刻がtime+足幅を過ぎた足だけ使用可。従来145/149はさらに60秒の名目公開遅延。公開実時計は保存されていない。",
            "missing_candles": "空白時間を補完した架空の足は作らない。必要本数を満たすまで準備状態。",
            "board_clock": "CurrentPriceTimeは価格の市場時計で受信時計ではない。原行順を保持し同値時計をまとめない。TradingVolumeTime=nullを板排除理由にしない。",
            "existing_reader": "work/preus149/engine_go/main.goのloadBoards/loadCandlesは再利用可能。異常BBO行も時計有効なら残して戦略で無効処理する。Received=CurrentPriceTimeの模型仮定と、同時計の市場間参照を厳密過去へ制限する点を明記する。",
            "legacy_cache": "145は異常BBOを除外したキャッシュ。原行ベース149と同じ時系列とみなさない。153は原資料から統一readerで準備すること。",
            "compressed_copies": "同フォルダbook.jsonl.gzは重複保存として入力から除外。非圧縮book.jsonlを正本参照。",
            "partial": "10/26Nightは既知の21:13:52排他まで。完了場統計に混ぜず、端末現セッションや未見検証と呼ばない。"},
        "duration_seconds": time.perf_counter()-started}
    HERE.mkdir(parents=True, exist_ok=True)
    target = HERE / "入力目録153.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("saved_counts", "source_file_count", "content_bytes_read_for_hash", "complete_for_both", "known_partial", "duration_seconds")}, ensure_ascii=False), flush=True)
    print("MISMATCHES", len(mismatches), "MANIFEST_SHA256", fingerprint(target)["sha256"], flush=True)
    if mismatches:
        raise SystemExit("入力不一致を検出。金融再生へ渡さないでください。")


if __name__ == "__main__":
    main()
