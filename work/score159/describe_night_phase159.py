"""夜間保存分析を前半P05・後半D07へ分け、既知25夜の担当混合を点検する。"""

from collections import Counter
from pathlib import Path
import hashlib
import json
import sys
import analyze159 as core

HERE = Path(__file__).resolve().parent


def main() -> None:
    """保存初回玉の時間帯別帯集計・相関と元資料の不変を確認する。

    引数: なし。返り値: None。売買再生・新しい予測モデルは作らない。
    """
    path = HERE / "夜間初回玉と支持の対応159.json"
    saved = core.read(path)
    rows = saved["rows"]
    selected = [r for r in rows if r["qualification"] == "既知開発25夜"]
    result = {"scope": "既知25夜だけ。前半P05と後半D07を分離。MFE/MAEから先着を推定しない。", "phases": {}}
    for phase in ["前半", "後半"]:
        phase_rows = [r for r in selected if r["phase"] == phase]
        result["phases"][phase] = core.describe_groups(phase_rows)
    result["unknown_reasons"] = [{"phase": phase, "owner": owner, "reason": reason, "parents": n}
        for (phase, owner, reason), n in Counter((r["phase"], r["owner"], r["support"]["components"].get("OwnReason"))
            for r in selected if not r["known"]).items()]
    result["unknown_initials"] = [{k: r[k] for k in ["session", "parent", "owner", "phase", "decision_time", "decision_index", "support"]}
                                  for r in selected if not r["known"]]
    checks = []
    for item in saved["sources"]:
        actual = hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest()
        assert actual == item["sha256"], "解析中に元夜間結果が変化した"
        checks.append(item)
    result["sources_unchanged"] = checks
    core.save(HERE / "夜間時間帯別の支持校正159.json", result)
    print(json.dumps({phase: {"parents": values["全体"]["all"]["parents"], "unknown": values["全体"]["unknown"]["parents"],
        "correlations": values["全体"]["correlations"]} for phase, values in result["phases"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
