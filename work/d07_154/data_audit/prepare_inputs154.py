"""00154用に全保存51場と取得済み当場を全文再照合し、入力目録を固定する。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import time


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
JST = timezone(timedelta(hours=9))
SOURCE_PATH = ROOT/"work/ma153/data/audit_inputs153.py"
SPEC = importlib.util.spec_from_file_location("qualified153", SOURCE_PATH)
SOURCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SOURCE)


def read(path: Path):
    """既存JSONを読む。

    引数: path(Path)。返り値: dict又はlist。元資料は変更しない。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def reference(path: Path) -> dict:
    """作業資料の全文指紋を記録する。

    引数: path(Path)。返り値: dictはpath、bytes、sha256。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.resolve().as_posix(), "bytes": path.stat().st_size, "sha256": digest}


def main() -> None:
    """同じ入力の再利用を全文SHA一致で確認して52場のSceneを作る。

    引数: なし。
    返り値: None。API取得、売買再生、旧入力の変更はしない。
    """
    began = time.monotonic()
    previous_path = ROOT/"work/ma153/data/入力目録153.json"
    previous = read(previous_path)
    download_path = WORK/"current_20261027/manifest.json"
    download = read(download_path)
    cutoff = datetime.fromisoformat(download["cutoff_exclusive"])
    assert cutoff.isoformat() == "2026-10-27T12:08:00+09:00"
    scenes = []
    expected = {}
    for old in previous["sessions"]:
        if old["partial"]:
            continue
        item = {key: copy.deepcopy(old[key]) for key in ("session", "kind", "start", "us_open", "force_close", "end", "cutoff", "partial", "books", "candles")}
        item["source"] = "JP_OSE_Data保存完了場"
        scenes.append(item)
        expected.update({Path(row["path"]): row for row in old["fingerprints"]})
    assert len(scenes) == 51
    current_dir = WORK/"current_20261027"
    start = datetime(2026, 10, 27, 8, 45, tzinfo=JST)
    end = datetime(2026, 10, 27, 15, 45, tzinfo=JST)
    current = {"session": "2026-10-27_Day", "kind": "Day", "start": start.timestamp(), "us_open": 0,
               "force_close": (end-timedelta(minutes=10)).timestamp(), "end": end.timestamp(), "cutoff": cutoff.timestamp(), "partial": True,
               "books": {symbol: (current_dir/f"{symbol}_book.jsonl").resolve().as_posix() for symbol in ("NK225", "TOPIX")},
               "candles": {symbol: {"60": (current_dir/f"{symbol}_candles_1min.json").resolve().as_posix(),
                                    "300": (current_dir/f"{symbol}_candles_5min.json").resolve().as_posix()} for symbol in ("NK225", "TOPIX")},
               "source": "本作業で既に取得済み・12時08分未満の途中場。未見検証ではない。"}
    scenes.append(current)
    for row in download["files"]:
        path = Path(row["path"])
        if path.name.startswith(("NK225_", "TOPIX_")):
            expected[path] = row
    assert len(expected) == 312
    with ThreadPoolExecutor(max_workers=4) as pool:
        fresh = list(pool.map(SOURCE.fingerprint, expected))
    fingerprints = {}
    for record in fresh:
        path = Path(record["path"])
        old = expected[path]
        assert record["exists"] and record["unchanged_during_read"]
        assert record["bytes"] == old["bytes"] and record["sha256"] == old["sha256"], str(path)
        record["prior_sha256"] = old["sha256"]
        record["full_read_matches_prior"] = True
        fingerprints[path] = record
    for item in scenes:
        opened = datetime.fromtimestamp(item["start"], JST)
        ending = datetime.fromtimestamp(item["end"], JST)
        cut = datetime.fromtimestamp(item["cutoff"], JST) if item["partial"] else None
        qualified, refs = {}, []
        for symbol in ("NK225", "TOPIX"):
            book = Path(item["books"][symbol])
            edges = SOURCE.book_edges(book, opened, ending, cut)
            assert edges["first"] and edges["last"]
            refs.append(fingerprints[book])
            bars = {}
            for interval in (60, 300):
                path = Path(item["candles"][symbol][str(interval)])
                bars[str(interval)] = SOURCE.inspect_candles(path, interval, opened, ending, cut)
                refs.append(fingerprints[path])
                assert bars[str(interval)]["eligible_closed_rows"] > 0
            gap = item["end"]-edges["last"]["unix"]
            complete = not item["partial"] and 0 <= gap <= 360 and edges["last"]["unix"] >= item["force_close"]
            assert item["partial"] or complete
            first, last = edges["first"]["last"], edges["last"]["last"]
            qualified[symbol] = {"book": edges, "candles": bars, "eligible_complete_session": complete,
                                  "seconds_before_formal_end": gap, "first_usable_at": edges["first"]["time"], "last_usable_at": edges["last"]["time"],
                                  "direction": "上昇" if last > first else "下落" if last < first else "横ばい",
                                  "direction_source": "当場最初Lastと最後Last。完了場では終了前6分以内の代理で正式終値ではない。途中場は観測末尾。事後採点専用。"}
        item["qualification"] = qualified
        item["fingerprints"] = refs
    result = {"created_at": datetime.now(JST).isoformat(), "financial_replays": 0, "API_calls_in_this_script": 0,
              "purpose": "保存51完了場と取得済み10月27日昼途中を現Goの固定13条件へ渡すための資格確認。", "sessions": scenes,
              "symbol_traded": "NK225mini", "point_value": 100, "max_per_side": 10, "fees": 0,
              "complete_sessions": 51, "complete_day_sessions": 26, "complete_night_sessions": 25,
              "partial_sessions": ["2026-10-27_Day"], "files_fully_rehashed": len(fresh), "bytes_read_for_hash": sum(row["bytes"] for row in fresh),
              "all_hashes_match_prior": True, "all_unchanged_during_read": True,
              "excluded": [{"session": "2026-10-26_Night", "reason": "既存21:13:52未満の途中断片は今回の当場10/27昼ではなく、完了場でもないため主比較・途中対照に含めない。"}],
              "provenance": {"previous153_manifest": reference(previous_path), "current_acquisition_manifest": reference(download_path),
                             "qualification_reader": reference(SOURCE_PATH), "script": reference(Path(__file__))},
              "clock": {"quote": "CurrentPriceTime。独立受信時計は無い。同値時計は原行順。", "candles": "確定足開始+足幅+現Go既定60秒公開待機。closed=trueだけで当時公開としない。",
                        "final_qualification": "先頭末尾を原文から再読。正常Last・BBOと正数量の厳しい資格。全行の欠測不存在を保証しない。",
                        "main_direction": "qualification内のLast始終は採点専用。Scene readerは入力判断へ渡さない。",
                        "partial": "12:08:00は排他上限。各ファイルは実際に取得できた末尾で終わり、この時刻まで観測が揃うとは保証しない。"},
              "duration_seconds": time.monotonic()-began}
    target = WORK/"inputs154.json"
    assert not target.exists(), "既存の登録候補目録を上書きしません"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    proof = {"state": "全件一致", "manifest": reference(target), "files": len(fresh), "bytes": result["bytes_read_for_hash"],
             "complete": 51, "partial": 1, "current_edges": current["qualification"], "duration_seconds": result["duration_seconds"]}
    (HERE/"入力全文再照合154.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("state", "manifest", "files", "bytes", "complete", "partial", "duration_seconds")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
