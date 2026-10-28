"""00145の原資料・既存特徴の同一性と全場網羅性を再確認する。金融再生は行わない。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT.parent / "JP_OSE_Data" / "future"
JST = timezone(timedelta(hours=9))


def read(path):
    """JSON資料を読む。

    引数: path(Path)は入力資料。
    返り値: dict又はlistは保存内容。
    """
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def inspect(item):
    """一つのファイルを全文ハッシュし、事前指紋と読取中の不変性を検査する。

    引数: item(dict)はpath・role・期待SHAを持つ資料。
    返り値: dictは実測指紋と合否。原資料への書込みは行わない。
    """
    path = Path(item["path"])
    before = path.stat()
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    unchanged = (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    return dict(item, bytes=before.st_size, mtime_ns=before.st_mtime_ns, sha256=sha,
                matches_expected=sha == item["expected_sha256"] if item.get("expected_sha256") else None,
                unchanged_during_read=unchanged)


def main():
    """全保存場と対応キャッシュを列挙し、並列2で同一性を再確認する。

    引数: なし。
    返り値: None。目録と一場ごとのデータ範囲を新規作業領域に保存する。
    """
    started = time.perf_counter()
    HERE.mkdir(exist_ok=True)
    old = ROOT / "work/aggressive140_20261024"
    proof_path = ROOT / "work/raw_diagnosis141_20261024/coverage_all_sessions141.json"
    proof = read(proof_path)
    coverage = {(x["symbol"], x["session"]): x for x in proof["records"]}
    expected = {str(Path(x["path"]).resolve()): x["sha256"]
                for filename in ("moved_materials140.json", "inventory140.json")
                for x in read(old / filename)["materials"]}
    packets = [x for name in ("known_manifest140.json", "inputs/input_manifest.json")
               for x in read(old / name)["packets"]]
    known = set(x["session"] for x in packets)
    listings = {symbol: sorted(p.name for p in (SOURCE / symbol).iterdir() if p.is_dir())
                for symbol in ("NK225", "TOPIX")}
    items, sessions = [], []
    for symbol, scenes in listings.items():
        for scene in scenes:
            record = coverage.get((symbol, scene))
            folder = SOURCE / symbol / scene
            for name in ("book.jsonl", "candle_1min.csv", "candle_5min.csv"):
                path = folder / name
                items.append(dict(path=str(path.resolve()), role="原板" if name == "book.jsonl" else "分足",
                                  symbol=symbol, session=scene, expected_sha256=expected.get(str(path.resolve()))))
            if record:
                for role, path, sha in (("原板特徴", record["raw_features"], record["raw_features_sha256"]),
                                        ("行対応特徴", record["packet"]["aligned_path"], record["packet"]["aligned_sha256"])):
                    items.append(dict(path=path, role=role, symbol=symbol, session=scene, expected_sha256=sha))
                first = record["first_normal_in_session_board"]["time"]
                last = record["last_normal_in_session_board"]["time"]
                day = datetime.fromisoformat(scene[:10]).replace(tzinfo=JST)
                end = day.replace(hour=15, minute=45) if scene.endswith("_Day") else (day + timedelta(days=1)).replace(hour=6)
                gap = (end - datetime.fromisoformat(last)).total_seconds()
                sessions.append(dict(symbol=symbol, session=scene, known_development=scene in known,
                    raw_rows=record["rows_read"], eligible_rows=record["packet"]["rows"],
                    first_normal_price_time=first, final_normal_price_time=last, session_end=end.isoformat(),
                    final_gap_seconds=gap, final_quote_within_previous_six_minutes=0 <= gap <= 360,
                    independent_receive_clock_present=record["independent_receive_clock_present"]))
            else:
                sessions.append(dict(symbol=symbol, session=scene, known_development=False, previous_coverage=False))
    for p in packets:
        path = Path(p["path"])
        if not path.is_absolute():
            path = ROOT / path
        items.append(dict(path=str(path), role="二市場準備パケット", session=p["session"], expected_sha256=p["sha256"]))
    # ----------------------------------------
    # 凍結済みの10/26午前は完全場・未見検証に混ぜず、別資料として指紋だけ再照合する。
    partial_dir = ROOT / "work/sessiontrader_live146_20261026/data"
    for p in read(partial_dir / "manifest.json"):
        items.append(dict(path=str(partial_dir / p["file"]), role="十月二十六日午前の部分資料",
                          symbol=p["product"], session="2026-10-26_Day", expected_sha256=p["sha256"], cutoff=p["to"]))
    results = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        for count, result in enumerate(executor.map(inspect, items), 1):
            results.append(result)
            if count % 50 == 0:
                print(f"全文照合 {count}/{len(items)} / {time.perf_counter()-started:.1f}秒", flush=True)
    mismatches = [x for x in results if x["matches_expected"] is False or not x["unchanged_during_read"]]
    missing = {s: sorted(known-set(listings[s])) for s in listings}
    added = {s: sorted(set(listings[s])-known) for s in listings}
    payload = dict(checked_at=datetime.now(JST).isoformat(), financial_replays=0,
        all_checks_passed=not mismatches and not any(missing.values()), sessions=listings,
        known_sessions=sorted(known), new_sessions=added, missing_sessions=missing,
        raw_files=sum(x["role"] == "原板" for x in results),
        raw_rows=sum(x.get("raw_rows", 0) for x in sessions),
        eligible_rows=sum(x.get("eligible_rows", 0) for x in sessions),
        raw_bytes=sum(x["bytes"] for x in results if x["role"] == "原板"),
        checked_files=len(results), checked_bytes=sum(x["bytes"] for x in results),
        seconds=time.perf_counter()-started, mismatches=mismatches, sessions_detail=sessions,
        files=results, previous_whole_raw_scan={"path":str(proof_path), "sha256":inspect(dict(path=str(proof_path),role="既存監査"))["sha256"]},
        limitations=["既知50場の開発資料。今回の調整結果を未見期間の優位性とは扱わない。",
                    "10月26日午前の凍結資料は仮説の発端であり、完全場の合算・未見検証には含めない。",
                    "独立した板受信時計がなく原価格時計を代理使用する。厳密な実時間遅延の証明ではない。",
                    "既存原板全行構文解析と特徴照合の証拠を、今回の全文SHA一致によって再利用した。今回は生JSONの全行再解析ではない。"])
    (HERE / "全保存資料の再照合145.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({k:payload[k] for k in ("all_checks_passed","raw_files","raw_rows","eligible_rows","raw_bytes","checked_files","checked_bytes","seconds","new_sessions","missing_sessions")},ensure_ascii=False),flush=True)
    assert payload["all_checks_passed"], "原資料又はキャッシュが以前の証拠と一致しない"


if __name__ == "__main__":
    main()
