"""00161の入力を旧目録と全内容指紋で照合する。売買・先着採点は行わない。"""

import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def fingerprint(path: Path) -> dict:
    """ファイルを全読し改変を検査する。

    引数: path (Path) は読取対象。
    返り値: dict はSHA256・サイズ・読取前後の同一性。
    """
    before = path.stat()
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    after = path.stat()
    return {
        "path": str(path), "sha256": h.hexdigest(), "bytes": after.st_size,
        "mtime_ns": after.st_mtime_ns,
        "unchanged_during_read": (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
    }


def main() -> None:
    """53場の旧入力との一致を記録する。

    引数: なし。
    返り値: None。監査JSONだけを新規保存する。
    """
    reference = ROOT / "work/entry160/inputs160.json"
    data = json.loads(reference.read_text(encoding="utf-8-sig"))
    reference_fp = fingerprint(reference)
    scenes = data["scenes"]
    assert len(scenes) == 53 and len({s["session"] for s in scenes}) == 53
    assert Counter(s["kind"] for s in scenes) == {"Day": 27, "Night": 26}
    assert all(s["partial"] is False for s in scenes)
    files = []
    scene_rows = []
    for n, scene in enumerate(scenes, 1):
        targets = {str(Path(p)): market for market, p in scene["books"].items()}
        expected = {str(Path(f["path"])): f for f in scene["fingerprints"]}
        assert set(targets) <= set(expected)
        for p, market in targets.items():
            row = fingerprint(Path(p))
            row.update(session=scene["session"], market=market, expected_sha256=expected[p]["sha256"])
            row["matches_prior"] = row["sha256"] == row["expected_sha256"]
            assert row["matches_prior"] and row["unchanged_during_read"], row
            files.append(row)
        scene_rows.append({key: scene[key] for key in ["session", "kind", "start", "end", "cutoff", "force_close", "partial"]})
        print(f"入力同一性 {n}/53", flush=True)
    result = {
        "passed": True, "created_at": datetime.now().astimezone().isoformat(),
        "reference": reference_fp, "sessions": len(scenes), "day": 27, "night": 26,
        "raw_files": len(files), "full_read_bytes": sum(r["bytes"] for r in files),
        "financial_replays": 0, "new_entry_evaluations": 0, "api_calls": 0,
        "qualification": "既知53完了場。終端資格は旧目録を引継ぎ、今回は全原板の内容不変を照合。新しい受信時計は作らない。",
        "scenes": scene_rows, "files": files,
    }
    (OUT / "53場原板の入力不変161.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ["passed", "sessions", "raw_files", "full_read_bytes"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
