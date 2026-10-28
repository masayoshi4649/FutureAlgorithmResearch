"""既存日中26場と一度取得した当日日中を、固定値幅の比較用目録へまとめる。"""
import hashlib
import json
from pathlib import Path
from datetime import datetime

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def fingerprint(path):
    """入力全体の指紋を取得する。

    引数: path(Path)。返り値: dictは絶対位置、SHA256、サイズ。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.as_posix(), "sha256": digest, "bytes": path.stat().st_size}


def main():
    """元の場内時計を保った日中目録を作成する。

    引数: なし。返り値: None。金融再生、元資料の変更、API再取得なし。
    """
    output = HERE / "inputs156.json"
    assert not output.exists()
    source = ROOT / "work/d07_154/inputs154.json"
    original = json.loads(source.read_text(encoding="utf-8"))
    fetched = json.loads((HERE / "current_20261027/manifest.json").read_text(encoding="utf-8"))
    assert all("error" not in f for f in fetched["files"])
    scenes = [x for x in original["sessions"] if x["kind"] == "Day"]
    assert len(scenes) == 27
    today = next(x for x in scenes if x["session"] == "2026-10-27_Day")
    assert today["partial"]
    today["cutoff"] = datetime.fromisoformat(fetched["cutoff_exclusive"]).timestamp()
    today["source"] = "研究156で一度取得した2026-10-27 Day 15:20未満。未完了場。"
    today.pop("qualification", None)
    inputs = []
    for ref in ("NK225", "TOPIX"):
        book = HERE / "current_20261027" / (ref + "_book.jsonl")
        today["books"][ref] = book.as_posix()
        inputs.append(fingerprint(book))
        for seconds, minutes in ((60, 1), (300, 5)):
            path = HERE / "current_20261027" / (ref + f"_candles_{minutes}min.json")
            today["candles"][ref][str(seconds)] = path.as_posix()
            inputs.append(fingerprint(path))
    today["fingerprints"] = inputs
    record = {"created_at": datetime.now().astimezone().isoformat(), "purpose": "既知日中26完了場と当日15:20未満の固定値幅比較。完了と途中を分離。",
              "source_manifest": fingerprint(source), "current_manifest": fingerprint(HERE / "current_20261027/manifest.json"),
              "financial_replays": 0, "actual_mini_book_available": False, "sessions": scenes}
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"sessions": len(scenes), "partial": sum(x["partial"] for x in scenes), "cutoff": fetched["cutoff_exclusive"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
