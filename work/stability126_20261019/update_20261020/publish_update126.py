"""追加二場の独立監査後だけ、同じＨＴＭＬの損益と累計を四十三場へ更新する。"""

import copy
import json
from pathlib import Path
import re

from run_update126 import HERE, ROOT, RESULT_NAME, read, save, sha


PUBLIC = ROOT / "アルゴリズム調査/00126_E01の損失抑制と方向偏りの再検証"


def main() -> None:
    """
    機能: 旧表示の全数値を維持して追加会計だけ結合し、累計と案内を更新する。
    引数: なし。
    返り値: None。売買再生、条件再選択、金融結果の上書きを行わない。
    """
    result_path = HERE / RESULT_NAME
    result = read(result_path)
    audit_path = HERE / "audit/追加二場三十二会計の全注文と全行清算の独立監査.json"
    audit = read(audit_path)
    assert result["passed"] and audit["passed"]
    assert audit["result"]["sha256"] == sha(result_path)
    report = PUBLIC / "E01改修のセッション損益.html"
    text = report.read_text(encoding="utf-8")
    match = re.search(r'(<script id="accounts" type="application/json">)(.*?)(</script>)', text, re.S)
    assert match
    payload = json.loads(match.group(2))
    previous = copy.deepcopy(payload)
    assert len(payload["sessions"]) == 41 and not (set(payload["sessions"]) & set(result["sessions"]))
    payload["sessions"].extend(result["sessions"])
    assert payload["sessions"] == sorted(payload["sessions"]) and len(payload["sessions"]) == 43
    summary = {}
    fields = ("method", "session", "symbol", "profit", "loss", "net")
    for model in payload["models"]:
        addition = [row for row in result["rows"] if row["model"] == model["id"]]
        assert len(addition) == len(model["methods"]) * 4
        model["rows"].extend({key: row[key] for key in fields} for row in addition)
        model["sources"].append(dict(path=result_path.relative_to(ROOT).as_posix(),
            sha256=sha(result_path), model_filter=model["id"]))
        original = next(v for v in previous["models"] if v["id"] == model["id"])
        assert model["rows"][:len(original["rows"])] == original["rows"]
        for method in model["methods"]:
            for symbol in ("TOPIX", "NK225"):
                rows = [r for r in model["rows"] if r["method"] == method["id"] and r["symbol"] == symbol]
                assert len(rows) == 43 and len({r["session"] for r in rows}) == 43
                summary[model["id"], method["id"], symbol] = dict(
                    profit=sum(r["profit"] for r in rows), loss=sum(r["loss"] for r in rows),
                    net=sum(r["net"] for r in rows), red=sum(r["net"] < 0 for r in rows),
                    black=sum(r["net"] > 0 for r in rows))
    payload["note"] = "手数料0円・全て場内返済。利益／損失は返済ごとの正負。旧41場で選んだ条件を固定し、追加2場を含む全43セッションを表示。"
    json_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    updated = text[:match.start(2)] + json_text + text[match.end(2):]
    assert updated.count("全41セッション 累計") == 1
    updated = updated.replace("全41セッション 累計", "全43セッション 累計").replace("全四十一場の会計", "全対象セッションの会計")
    before = HERE / "更新前の四十一場損益.html"
    assert not before.exists()
    before.write_bytes(report.read_bytes())
    report.write_text(updated, encoding="utf-8")
    save(HERE / "全四十三場の公開会計.json", dict(passed=True, sessions=payload["sessions"], models=payload["models"],
        previous_41_unchanged=True, conditions_changed=False,
        added_result=dict(path=result_path.relative_to(ROOT).as_posix(), sha256=sha(result_path)),
        report_sha256=sha(report)))
    save(HERE / "公開更新の記録.json", dict(passed=True, report=report.relative_to(ROOT).as_posix(),
        before_sha256=sha(before), after_sha256=sha(report), previous_rows_unchanged=True,
        sessions=43, added_sessions=result["sessions"], financial_replays=0,
        cumulative=[dict(model=k[0], method=k[1], symbol=k[2], **v) for k, v in summary.items()]))
    print(json.dumps(dict(passed=True, sessions=43, report_sha256=sha(report),
        GU_Q={s: summary["next_normal_bbo", "GU_Q", s] for s in ("TOPIX", "NK225")}), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
