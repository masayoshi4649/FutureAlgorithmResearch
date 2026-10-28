"""研究151で再利用する既存B04保存会計26ファイルの指紋を記録する。売買再生はしない。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def canonical_digest(value: dict) -> str:
    """設定・対象ケースを正規化した内容指紋へ変換する。

    引数: value(dict)は既存保存JSONの一部。
    返り値: strはSHA256。
    """
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    """全26既存ファイルを読み取り、B04と入力Sceneの所在・指紋を保存する。

    引数: なし。
    返り値: None。原会計・原資料・既存目録は変更しない。
    """
    manifest_path = ROOT / "work/preus149/data/原資料一覧149.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    expected = {row["session"]: row for row in manifest["sessions"]}
    files = sorted((ROOT / "work/preus150/results_round2").glob("*.json"))
    assert len(files) == 26
    records = []
    configs = set()
    config = None
    for path in files:
        before = path.stat()
        raw = path.read_bytes()
        after = path.stat()
        assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
        value = json.loads(raw)
        scene = value["scene"]
        session = scene["session"]
        assert session in expected and path.stem == session
        assert all(item == expected[session][key] for key, item in scene.items()), session
        selected = [row for row in value["cases"] if row["config"]["id"] == "B04"]
        assert len(selected) == 1, session
        b04 = selected[0]
        config = b04["config"]
        configs.add(canonical_digest(config))
        records.append({
            "session": session, "partial": scene["partial"], "path": path.relative_to(ROOT).as_posix(),
            "absolute_path": path.resolve().as_posix(), "bytes": len(raw), "mtime_ns": before.st_mtime_ns,
            "sha256": hashlib.sha256(raw).hexdigest(), "unchanged_during_read": True,
            "selection": "cases 内 config.id が B04 の1件", "case_sha256": canonical_digest(b04),
            "config_sha256": canonical_digest(config), "stored_events": len(b04["events"]),
            "scene_matches_original149": True,
        })
    assert {r["session"] for r in records} == set(expected) and len(configs) == 1
    result = {
        "created_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
        "purpose": "研究151の登録前にB04保存会計の内容指紋と対象範囲を固定する",
        "source_manifest": {"path": manifest_path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(manifest_bytes).hexdigest(), "bytes": len(manifest_bytes)},
        "completed_nights": sum(not r["partial"] for r in records), "known_partial": sum(r["partial"] for r in records),
        "method_id": "B04", "config": config, "config_sha256": next(iter(configs)), "files": records,
        "financial_replays": 0, "raw_book_or_candle_content_reads": 0, "API_calls": 0,
        "limitation": "B04の保存実約定イベントの読取りであり、損切りなし両建て手法の新規約定・返済・損益を生成したものではない。後段再利用の可否は新手法の境界状態と定義を別途照合する。",
    }
    target = HERE / "B04保存会計の指紋151.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"files": len(records), "completed_nights": result["completed_nights"], "known_partial": result["known_partial"],
                      "scene_matches_original149": True, "config_identical": True,
                      "manifest_sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "financial_replays": 0}, ensure_ascii=True))


if __name__ == "__main__":
    main()
