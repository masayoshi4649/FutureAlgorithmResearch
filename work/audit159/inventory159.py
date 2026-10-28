"""保存済み資料の増分・終端資格・原指紋を確認する。売買再生は行わない。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import hashlib
import importlib.util
import json
import os

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT.parent / "JP_OSE_Data/future"
JST = ZoneInfo("Asia/Tokyo")
HELPER_PATH = ROOT / "work/ma153/data/audit_inputs153.py"
_spec = importlib.util.spec_from_file_location("入力資格153", HELPER_PATH)
HELPER = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(HELPER)


def load(path: Path) -> dict:
    """機能: 小容量の既存入力目録を読む。
    引数: path (Path) は入力目録。
    返り値: dict は保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def key(path: Path | str) -> str:
    """機能: Windowsパスの比較キーを作る。
    引数: path (Path又はstr) は資料位置。
    返り値: str は絶対パスの大文字小文字を統一したキー。
    """
    return os.path.normcase(str(Path(path).resolve()))


def main() -> None:
    """機能: 全保存53場を棚卸しし、夜26場と追加デイの登録用目録を保存する。
    引数: なし。
    返り値: None。原資料・過去目録・共有台帳は変更しない。
    """
    HERE.mkdir(parents=True, exist_ok=True)
    previous_path = ROOT / "work/d07_154/inputs154.json"
    previous = load(previous_path)
    previous_scenes = {s["session"]: s for s in previous["sessions"] if not s["partial"]}
    previous_files = {key(fp["path"]): fp for s in previous["sessions"] for fp in s["fingerprints"]}
    names = {symbol: sorted(p.name for p in (DATA / symbol).iterdir() if p.is_dir()) for symbol in ["NK225", "TOPIX"]}
    assert names["NK225"] == names["TOPIX"], "二市場の保存場が一致しない"
    selected = [name for name in names["NK225"] if name.endswith("_Night") or name == "2026-10-27_Day"]
    files, metadata = {}, []
    for symbol in names:
        for name in names[symbol]:
            for filename in ["book.jsonl", "candle_1min.csv", "candle_5min.csv"]:
                p = DATA / symbol / name / filename
                stat = p.stat()
                old = previous_files.get(key(p))
                row = {"path": p.resolve().as_posix(), "symbol": symbol, "session": name,
                       "name": filename, "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                       "prior_registered": old is not None,
                       "metadata_matches_prior": old is not None and old["bytes"] == stat.st_size and old["mtime_ns"] == stat.st_mtime_ns}
                metadata.append(row)
                if name in selected:
                    files[key(p)] = p
    # ----------------------------------------
    # 再生予定の全入力を今回実際に読み、旧SHAの転記だけで済ませない。
    fingerprints = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for fp in pool.map(HELPER.fingerprint, files.values()):
            assert fp["exists"] and fp["unchanged_during_read"], fp["path"]
            old = previous_files.get(key(fp["path"]))
            fp["previous154_sha256"] = old["sha256"] if old else None
            fp["matches_previous154"] = fp["sha256"] == old["sha256"] if old else None
            if old:
                assert fp["matches_previous154"], ("旧原資料の内容変化", fp["path"])
            fingerprints[key(fp["path"])] = fp
    scenes = []
    for name in selected:
        start, end = HELPER.scene_clock(name)
        kind = "Night" if name.endswith("_Night") else "Day"
        us_open = datetime.fromisoformat(name[:10]).replace(hour=9, minute=30, tzinfo=ZoneInfo("America/New_York")).timestamp() if kind == "Night" else 0
        scene = {"session": name, "kind": kind, "start": start.timestamp(), "us_open": us_open,
                 "force_close": (end - timedelta(minutes=10)).timestamp(), "end": end.timestamp(),
                 "cutoff": (end + timedelta(minutes=1)).timestamp(), "partial": False,
                 "books": {}, "candles": {}, "qualification": {}, "fingerprints": [],
                 "cohort": "既知25夜" if name in previous_scenes else "追加完了夜" if kind == "Night" else "追加完了デイ",
                 "prior_observed_prefix": "2026-10-26T21:13:52+09:00未満" if name == "2026-10-26_Night" else "2026-10-27T15:20:00+09:00未満" if name == "2026-10-27_Day" else None,
                 "independent_unseen_session": False}
        for symbol in names:
            base = DATA / symbol / name
            scene["books"][symbol] = (base / "book.jsonl").resolve().as_posix()
            scene["candles"][symbol] = {str(sec): (base / f"candle_{sec//60}min.csv").resolve().as_posix() for sec in [60, 300]}
            book = HELPER.book_edges(base / "book.jsonl", start, end, None)
            assert book["first"] and book["last"], (name, symbol, "正常原板なし")
            gap = end.timestamp() - book["last"]["unix"]
            qualifies = 0 <= gap <= 360 and book["first"]["unix"] <= start.timestamp() + 360
            assert qualifies, (name, symbol, gap, "場端資格不足")
            scene["qualification"][symbol] = {
                "book": book, "end_gap_seconds": gap, "eligible_complete_session": qualifies,
                "candles": {str(sec): HELPER.inspect_candles(base / f"candle_{sec//60}min.csv", sec, start, end, None) for sec in [60, 300]},
                "end_note": "正常BBOの価格時計が正式終了前6分以内。正式終値・全時刻無欠測・実受信時刻を保証しない。"}
            scene["fingerprints"] += [fingerprints[key(base / f)] for f in ["book.jsonl", "candle_1min.csv", "candle_5min.csv"]]
        scene["complete_for_both"] = True
        scenes.append(scene)
        print(name + " 終端資格・原資料6件確認", flush=True)
    # ----------------------------------------
    # 既知の旧26Dayも現在の保存網羅性に含める。再生予定外はメタデータ照合と旧資格を明示。
    changed_old = [r for r in metadata if r["prior_registered"] and not r["metadata_matches_prior"]]
    inventory = {"created_at": datetime.now(JST).isoformat(), "financial_replays": 0, "API_calls": 0,
                 "saved_counts": {s: {"Day": sum(n.endswith("_Day") for n in v), "Night": sum(n.endswith("_Night") for n in v)} for s, v in names.items()},
                 "names": names, "files": metadata, "changed_old_metadata": changed_old,
                 "full_read_files_for_new_manifest": len(fingerprints), "full_read_bytes": sum(x["bytes"] for x in fingerprints.values()),
                 "latest_saved": names["NK225"][-1], "missing_current_night": "2026-10-27_Night",
                 "older_day_note": "旧26Dayは154で全文指紋・終端資格済み。今回再生対象外のため全原板は再読せずsize/mtime比較。"}
    manifest = {"created_at": inventory["created_at"], "purpose": "支持校正と夜間研究用の保存資料資格。売買未実行。",
                "financial_replays": 0, "API_calls": 0, "fees": 0, "symbol_traded": "NK225",
                "max_per_side_micro": 100, "point_value_micro": 10,
                "complete_night_sessions": 26, "added_complete_night_sessions": 1,
                "additional_complete_day_sessions": 1, "partial_sessions": 0,
                "clock": {"board": "CurrentPriceTime。受信時計ではない。同秒は原行順を維持。",
                          "force_close": "Day15:35、Night翌05:50の返済判断。次正常BBOで執行。終端6分代理資格とは別。",
                          "candle": "確定足開始＋幅以後に公開。従来模型はさらに60秒遅延。保存closed=trueだけで過去公開としない。"},
                "sources": [{"path": previous_path.as_posix(), "sha256": hashlib.sha256(previous_path.read_bytes()).hexdigest()},
                            {"path": HELPER_PATH.as_posix(), "sha256": hashlib.sha256(HELPER_PATH.read_bytes()).hexdigest()}],
                "sessions": scenes}
    for fp in fingerprints.values():
        stat = Path(fp["path"]).stat()
        assert (stat.st_size, stat.st_mtime_ns) == (fp["bytes"], fp["mtime_ns"]), ("確認中に変更", fp["path"])
    (HERE / "保存網羅性159.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    out = HERE / "inputs159.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "saved": {"Day": 27, "Night": 26}, "selected_scenes": len(scenes),
                      "full_read_files": len(fingerprints), "changed_old_metadata": len(changed_old),
                      "manifest_sha256": hashlib.sha256(out.read_bytes()).hexdigest()}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
