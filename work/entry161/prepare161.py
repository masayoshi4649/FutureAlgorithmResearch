"""既存入口を含まない原板目録と固定時系列区分を作る。"""

from datetime import datetime
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main() -> None:
    """53場の板だけを選び30/10/13場へ区分して保存する。

    引数: なし。返り値: None。原板・金融結果は読取以外の操作をしない。
    """
    source = ROOT / "work/entry160/inputs160.json"
    original = json.loads(source.read_text(encoding="utf-8"))
    rows = []
    for old in original["scenes"]:
        date = old["session"][:10]
        split = "train" if date <= "2026-10-09" else "validation" if date <= "2026-10-16" else "test"
        row = {k: old[k] for k in ("session", "kind", "start", "end", "us_open", "partial", "cutoff", "books")}
        paths = {Path(p) for p in row["books"].values()}
        row["fingerprints"] = [f for f in old["fingerprints"] if Path(f["path"]) in paths]
        assert len(row["fingerprints"]) == 2 and not row["partial"]
        row["split"] = split
        rows.append(row)
    counts = {s: sum(r["split"] == s for r in rows) for s in ("train", "validation", "test")}
    assert counts == {"train": 30, "validation": 10, "test": 13}
    target = HERE / "inputs161.json"
    assert not target.exists()
    result = {"created_at": datetime.now().astimezone().isoformat(), "purpose": "旧入口を一切含まない新入口の原板目録",
              "source": {"path": source.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
              "financial_replays": 0, "counts": counts, "sessions": rows}
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(counts)


if __name__ == "__main__":
    main()
