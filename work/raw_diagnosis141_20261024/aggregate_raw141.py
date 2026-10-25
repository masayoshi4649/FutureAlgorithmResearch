"""全100原板の走査証跡を結合し、既存原本SHAとpacket対応を検証する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def read(path: Path) -> dict | list:
    """UTF-8の保存済み証跡を読み取る。

    引数: path(Path)は証跡ファイル。
    返り値: dict又はlistはJSON内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path: Path) -> str:
    """証跡ファイルの内容指紋を取る。

    引数: path(Path)は対象。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """100原板の全読取・原本一致・原順対応を確認して目録を新規保存する。

    引数: なし。
    返り値: None。金融再生は行わず、原板と既存証跡を変更しない。
    """
    paths = sorted((HERE / "coverage_reports").glob("*.json"))
    records = [read(path) for path in paths]
    assert len(records) == 100
    keys = {(row["symbol"], row["session"]) for row in records}
    assert len(keys) == 100
    scenes = sorted({row["session"] for row in records})
    assert len(scenes) == 50 and all((symbol, scene) in keys for scene in scenes for symbol in ["NK225", "TOPIX"])
    old = read(ROOT / "work/aggressive140_20261024/moved_materials140.json")
    inventory = read(ROOT / "work/aggressive140_20261024/inventory140.json")
    expected = {}
    for item in old["materials"] + inventory["materials"]:
        path = Path(item["path"])
        if path.name != "book.jsonl":
            continue
        expected[(path.parent.parent.name, path.parent.name)] = item["sha256"]
    finite = {(row["symbol"], row["session"]): row["finite_clock_backward_steps"] for row in read(HERE / "finite_clock_audit141.json")}
    for row in records:
        key = (row["symbol"], row["session"])
        assert row["source_sha256"] == expected[key], (key, "原本SHAが既存証跡と違います")
        stat = Path(row["source_path"]).stat()
        assert (stat.st_size, stat.st_mtime_ns) == (row["source_bytes"], row["source_mtime_ns"]), (key, "原本変更")
        assert row["all_lines_parsed_or_recorded"] and row["offset_contiguous"] and row["unchanged_during_read"]
        assert row["invalid_json_count"] == 0, (key, "JSON不正")
        assert row["source_bytes"] == row["uncompressed_bytes_read"]
        assert row["packet"]["sequence_is_zero_based_raw_line"]
        assert all(check["mismatches"] == 0 for check in row["packet"]["checks"].values())
        assert row["packet"]["quote_valid_equal_raw_book_valid"]
        row["finite_price_clock_backward_steps"] = row.get("finite_price_clock_backward_steps", finite.get(key))
        assert row["finite_price_clock_backward_steps"] is not None
        row["matches_previous_raw_sha256"] = True
    unchanged_steps = sum(row["normal_session_same_clock_steps"] for row in records)
    changed_steps = sum(row["normal_session_same_clock_book_changes"] for row in records)
    result = {"complete": True, "sessions": scenes, "files": 100,
        "raw_rows": sum(row["rows_read"] for row in records), "raw_bytes": sum(row["uncompressed_bytes_read"] for row in records),
        "packet_rows": sum(row["packet"]["rows"] for row in records), "all_raw_sha_match_previous_evidence": True,
        "all_packet_raw_alignment_checks_passed": True, "invalid_json_total": 0,
        "finite_price_clock_backward_steps": sum(row["finite_price_clock_backward_steps"] for row in records),
        "normal_session_same_clock_steps": unchanged_steps, "normal_session_same_clock_book_changes": changed_steps,
        "normal_session_same_clock_book_change_fraction": changed_steps / unchanged_steps,
        "raw_features_bytes": sum(Path(row["raw_features"]).stat().st_size for row in records),
        "aligned_features_bytes": sum(Path(row["packet"]["aligned_path"]).stat().st_size for row in records),
        "financial_replays": 0, "records": records,
        "coverage_proofs": [{"path": str(path), "sha256": digest(path)} for path in paths],
        "frozen_implementations": read(HERE / "変換実装の同値確認141.json")}
    destination = HERE / "coverage_all_sessions141.json"
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: value for key, value in result.items() if key not in {"records", "coverage_proofs", "frozen_implementations", "sessions"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
