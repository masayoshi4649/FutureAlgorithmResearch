"""巨大な試行台帳の上位メタデータだけを読み、関連試行を索引化する。"""

from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main() -> None:
    """機能: 台帳正本を行順に読み、関連研究のID・変更理由を抽出する。
    引数: なし。
    返り値: None。全specを比較した重複判定とは呼ばず、金融も行わない。
    """
    source = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json"
    before = source.stat()
    digest = hashlib.sha256()
    accepted = {"id", "name", "study_id", "status", "question", "change", "result", "repeat_reason", "limitations"}
    regex = re.compile(rb'^      "([a-z_]+)": (.*?)(?:,)?\r?\n?$')
    entries, current = [], None
    with source.open("rb") as stream:
        for line in stream:
            digest.update(line)
            match = regex.match(line)
            if not match:
                continue
            field = match.group(1).decode("ascii")
            if field not in accepted:
                continue
            raw = match.group(2).strip()
            if raw.endswith(b","):
                raw = raw[:-1]
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if field == "id":
                if current:
                    entries.append(current)
                current = {field: value}
            elif current is not None:
                current[field] = value
    if current:
        entries.append(current)
    after = source.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), "照合中に台帳が変化"
    studies = {"00118", "00128", "00130", "00131", "00140", "00142", "00143", "00148", "00149", "00150", "00151", "00154", "00157"}
    selected = [e for e in entries if e.get("study_id") in studies or re.match(r"^(118|128|130|131|140|142|143|148|149|150|151|154|157)_", str(e.get("id", "")))]
    result = {"passed": True, "source": str(source), "source_sha256": digest.hexdigest(),
              "source_bytes": after.st_size, "unchanged_during_read": True,
              "all_top_level_trials": len(entries), "selected_count": len(selected),
              "scope": "上位メタデータの関連研究索引。全spec同値の機械照合ではない。未整理試行を重複なしとしない。",
              "new_financial_replays": 0, "trials": selected}
    (HERE / "関連試行の索引159.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "trials"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
