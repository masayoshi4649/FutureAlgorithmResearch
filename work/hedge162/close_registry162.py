"""結果と報告の確定後に、00162の試行状態だけを更新する事務処理。"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil

from register162 import ROOT, HERE, IDENT, FREEZE, read, sha, record, save
from register162 import canonical, manager_module, verify_receipt, assert_fingerprint

PUBLIC = ROOT/"アルゴリズム調査/00162_主玉の逆行を短期カバーで補う"
WORKBOOK = PUBLIC/"主玉とカバーの全セッション損益.xlsx"


def unchanged_rows(rows: list[dict], excluded: str) -> dict:
    """対象以外の各試行の正規化指紋を取得する。

    引数: rows(list[dict])、excluded(str)。返り値: dict[str,str]。
    """
    return {row["id"]: canonical(row) for row in rows if row["id"] != excluded}


def check_evidence(audit_path: Path, report_check: Path) -> list[dict]:
    """全再生・最終監査・報告書が同じ固定選択と成果を参照することを確認する。

    引数: audit_path/report_check(Path)。返り値: list[dict] は根拠一覧。
    """
    verify_receipt()
    final = HERE/"再生全完了162.json"
    data_path = HERE/"report_data162.json"
    complete, data, frozen = read(final), read(data_path), read(FREEZE)
    assert complete.get("completed") is True and type(complete.get("returncode")) is int and complete["returncode"] == 0
    assert complete["sessions"] == 53 and complete["cases"] == 53*26
    assert complete["reselection_after_confirmation"] is False
    assert complete["selected"] == frozen["selected"] == data["selected"]
    assert complete["freeze"]["sha256"] == sha(FREEZE)
    assert data["known_development"] is True and len(data["methods"]) == 26
    assert all(len(m["rows"]) == 53 for m in data["methods"])
    for source in data["sources"]+complete["proofs"]:
        assert_fingerprint(source)
    audit, checked = read(audit_path), read(report_check)
    assert audit.get("passed") is True, "最終金融監査の合格が必要"
    assert checked.get("passed") is True, "xlsxと元会計の検算合格が必要"
    assert checked["source_sha256"] == sha(data_path)
    assert checked["workbook_sha256"] == sha(WORKBOOK)
    selected_path = HERE/"audit/selection_audit162.json"
    public_path = HERE/"公開照合162.json"
    diagnosis_path = HERE/"diagnosis/診断完了162.json"
    selected_check, public_check, diagnosis_check = read(selected_path), read(public_path), read(diagnosis_path)
    assert selected_check.get("passed") is True and selected_check["selected"] == frozen["selected"]
    assert selected_check["selection_uses_confirmation_values"] is False
    assert selected_check["reselection_after_confirmation"] is False
    assert public_check.get("passed") is True and public_check["workbook_sha256"] == sha(WORKBOOK)
    assert diagnosis_check.get("completed") is True and diagnosis_check["sources_unchanged"] is True
    assert diagnosis_check["new_financial_replay"] is False and diagnosis_check["source_changes"] is False
    for item in diagnosis_check["files"]:
        assert_fingerprint(item)
    files = [PUBLIC/"README.md", PUBLIC/"検証記録.md", WORKBOOK,
             audit_path, report_check, final, data_path, FREEZE,
             HERE/"登録受領162.json", HERE/"事前照合162.json",
             HERE/"measure/幅候補の根拠162.md", HERE/"measure/尺度記述の照合162.json",
             selected_path, public_path, diagnosis_path,
             HERE/"diagnosis/価格時計と末尾精算162.json",
             HERE/"diagnosis/即追尾と具体機構162.json",
             HERE/"diagnosis/即追尾気配差分解162.json",
             HERE/"diagnosis/結論と具体機構162.md",
             Path(__file__)]
    return [record(path) for path in files]


def main() -> None:
    """明示適用時だけ対象試行を検証済みへ変更し、仕様と他試行の不変を検証する。

    引数: CLI の --apply、--audit(Path)、--report-check(Path)。返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", required=True)
    parser.add_argument("--audit", type=Path, default=HERE/"audit/audit162.json")
    parser.add_argument("--report-check", type=Path, default=HERE/"report/検算162.json")
    args = parser.parse_args()
    proof_path = HERE/"試行完了証跡162.json"
    assert not proof_path.exists(), "試行完了証跡は上書きしない"
    evidence = check_evidence(args.audit, args.report_check)
    manager = manager_module()
    target = manager.DATA/"trials.json"
    old_hash = sha(target)
    print("00162の成果・監査・報告を確認。対象の試行状態だけを更新します。", flush=True)
    # ----------------------------------------
    # ここからだけ管理器を通して正本を読む。準備段階では実行しない。
    value = manager.load(deep=False)
    assert value["source_sha256"]["trials.json"] == old_hash
    rows = value["trials"]["trials"]
    selected = [row for row in rows if row["id"] == IDENT]
    assert len(selected) == 1
    row = selected[0]
    before_spec = canonical(row["spec"])
    before_others = unchanged_rows(rows, IDENT)
    before_row = canonical(row)
    row["status"] = "検証済み"
    row["evidence"] = evidence
    row["readme"] = (PUBLIC/"README.md").relative_to(ROOT).as_posix()
    row["report"] = WORKBOOK.relative_to(ROOT).as_posix()
    row["result_note"] = "固定R02/GL01/GL02入口と主玉/カバーを買売各10枚の連続会計で比較。26条件×既知53場、前40場で3候補固定、後13場の確認後に再選択なし。手数料0、気配差と場末代理を保持し、役割別損益と場内全玉時価を併記。"
    assert canonical(row["spec"]) == before_spec
    assert unchanged_rows(rows, IDENT) == before_others
    value["trials"]["updated_at"] = datetime.now().astimezone().isoformat()
    manager.validate(value, deep=True)
    serialized = json.dumps(value["trials"], ensure_ascii=False, indent=2, allow_nan=False)+"\n"
    new_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    value["source_sha256"]["trials.json"] = new_hash
    rendered = manager.bundle(value)
    assert sha(target) == old_hash, "他の登録と競合したため停止"
    history = manager.DATA/"history"/("trials_"+old_hash+".json")
    history.parent.mkdir(exist_ok=True)
    if not history.exists():
        shutil.copyfile(target, history)
    staged = manager.DATA/"trials.json.tmp"
    staged_view = manager.DATA/"view-data.js.tmp"
    staged.write_text(serialized, encoding="utf-8", newline="\n")
    staged_view.write_text(rendered, encoding="utf-8", newline="\n")
    assert sha(target) == old_hash, "保存直前に他の登録と競合したため停止"
    staged.replace(target)
    try:
        staged_view.replace(manager.DATA/"view-data.js")
    except OSError:
        shutil.copyfile(history, target)
        raise
    assert sha(target) == new_hash
    save(proof_path, dict(passed=True, ids=[IDENT], status="検証済み", spec_changes=False,
        other_trial_changes=False, previous_sha256=old_hash, new_sha256=new_hash,
        previous_target_row_sha256=before_row, updated_target_row_sha256=canonical(row),
        other_trial_count=len(before_others), evidence=evidence))
    print("00162だけを検証済みへ更新。登録仕様と他試行は不変。", flush=True)


if __name__ == "__main__":
    main()
