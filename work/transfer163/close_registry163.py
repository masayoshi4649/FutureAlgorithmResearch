"""結果と報告の確定後に、00163の試行状態だけを更新する事務処理。"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil

from register163 import ROOT, HERE, IDENT, FREEZE, RECEIPT, read, sha, record, save
from register163 import canonical, manager_module, verify_receipt, assert_fingerprint

PUBLIC = ROOT/"アルゴリズム調査/00163_元手法への局所減枚と復元"
WORKBOOK = PUBLIC/"元手法の局所減枚と復元の全セッション損益.xlsx"


def unchanged_rows(rows: list[dict], excluded: set[str]) -> dict:
    """対象以外の各試行の正規化指紋を取得する。

    引数: rows(list[dict])、excluded(set[str])。返り値: dict[str,str]。
    """
    return {row["id"]: canonical(row) for row in rows if row["id"] not in excluded}


def check_evidence(audit_path: Path, report_check: Path) -> list[dict]:
    """全再生・最終監査・報告書が同じ固定選択と成果を参照することを確認する。

    引数: audit_path/report_check(Path)。返り値: list[dict] は根拠一覧。
    """
    verify_receipt()
    final = HERE/"再生全完了163.json"
    data_path = HERE/"report_data163.json"
    complete, data, frozen = read(final), read(data_path), read(FREEZE)
    assert complete.get("completed") is True and type(complete.get("returncode")) is int and complete["returncode"] == 0
    assert complete["sessions"] == 53 and complete["cases"] == 53*10
    assert complete["reselection_after_confirmation"] is False
    assert complete["selected"] == frozen["selected"] == data["selected"]
    assert complete["freeze"]["sha256"] == sha(FREEZE)
    assert data["known_development"] is True and len(data["methods"]) == 11
    assert {m["id"] for m in data["methods"]} == {"B00","C50","D40","D80","G40","G80","R40","R80","E40","E80","F00"}
    assert complete["composition"]["id"] == "F00" and complete["composition"]["new_financial_replay"] is False
    assert all(len(m["rows"]) == 53 for m in data["methods"])
    for source in data["sources"]+complete["proofs"]:
        assert_fingerprint(source)
    audit, checked = read(audit_path), read(report_check)
    assert audit.get("passed") is True, "最終金融監査の合格が必要"
    assert checked.get("passed") is True, "xlsxと元会計の検算合格が必要"
    assert checked["source_sha256"] == sha(data_path)
    assert checked["workbook_sha256"] == sha(WORKBOOK)
    selected_path = HERE/"audit/selection_audit163.json"
    public_path = HERE/"公開照合163.json"
    diagnosis_path = HERE/"diagnosis/診断完了163.json"
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
             RECEIPT, HERE/"事前照合163r1.json",
             HERE/"登録受領163.json", HERE/"audit/訂正前版の凍結163.json",
             HERE/"design/移植する法則と比較設計163.md",
             selected_path, public_path, diagnosis_path,
             Path(__file__)]
    files += [ROOT/item["path"] for item in diagnosis_check["files"]]
    files = sorted(set(files))
    return [record(path) for path in files]


def main() -> None:
    """明示適用時だけ対象試行を検証済みへ変更し、仕様と他試行の不変を検証する。

    引数: CLI の --apply、--audit(Path)、--report-check(Path)。返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", required=True)
    parser.add_argument("--audit", type=Path, default=HERE/"audit/audit163.json")
    parser.add_argument("--report-check", type=Path, default=HERE/"report/検算163.json")
    args = parser.parse_args()
    proof_path = HERE/"試行完了証跡163.json"
    assert not proof_path.exists(), "試行完了証跡は上書きしない"
    evidence = check_evidence(args.audit, args.report_check)
    manager = manager_module()
    target = manager.DATA/"trials.json"
    old_hash = sha(target)
    print("00163の成果・監査・報告を確認。対象の試行状態だけを更新します。", flush=True)
    # ----------------------------------------
    # ここからだけ管理器を通して正本を読む。準備段階では実行しない。
    value = manager.load(deep=False)
    assert value["source_sha256"]["trials.json"] == old_hash
    rows = value["trials"]["trials"]
    selected = [row for row in rows if row["id"] == IDENT]
    assert len(selected) == 1
    row = selected[0]
    before_spec = canonical(row["spec"])
    previous_receipt = read(HERE/"登録受領163.json")
    previous_proof = read(HERE/"audit/訂正前版の凍結163.json")
    assert previous_proof["financial_replays"] == 0 and previous_proof["next_id"] == IDENT
    previous_id = previous_receipt["id"]
    previous_rows = [item for item in rows if item["id"] == previous_id]
    assert len(previous_rows) == 1 and previous_id != IDENT
    previous = previous_rows[0]
    assert previous["status"] == "未実行"
    previous_spec = canonical(previous["spec"])
    previous_row = canonical(previous)
    changed_ids = {IDENT, previous_id}
    before_others = unchanged_rows(rows, changed_ids)
    before_row = canonical(row)
    row["status"] = "検証済み"
    row["evidence"] = evidence
    row["readme"] = (PUBLIC/"README.md").relative_to(ROOT).as_posix()
    row["report"] = WORKBOOK.relative_to(ROOT).as_posix()
    row["result_note"] = "元S01日中/P05+D07夜間のSource入口と出口を維持し、逆玉なしの局所半量化と一度復元を比較。10条件×既知53場、前40場で昼夜各1候補固定し後13場で選び直さない。F00は凍結昼夜の保存ケース行を連結し追加金融なし。micro100枚=mini10枚相当、手数料0、元の返済判断と次正常気配を維持。"
    previous["status"] = "中止"
    previous["result_note"] = "金融未実施。登録直後・再生前に空玉期間のR極値追跡の実装境界差を発見。旧実装・登録ZIP・受領・人工証跡を保持し、修正1の別IDへ移行した。損益結果を見た条件変更ではない。"
    previous["evidence"] = [record(HERE/"audit/訂正前版の凍結163.json"), record(HERE/"登録受領163.json"), record(RECEIPT)]
    assert canonical(row["spec"]) == before_spec
    assert canonical(previous["spec"]) == previous_spec
    assert unchanged_rows(rows, changed_ids) == before_others
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
    save(proof_path, dict(passed=True, ids=sorted(changed_ids), status="修正1検証済み・訂正前版金融未実施中止", spec_changes=False,
        other_trial_changes=False, previous_sha256=old_hash, new_sha256=new_hash,
        previous_target_row_sha256=before_row, updated_target_row_sha256=canonical(row),
        cancelled_id=previous_id, cancelled_financial_replays=0,
        cancelled_before_sha256=previous_row, cancelled_after_sha256=canonical(previous),
        other_trial_count=len(before_others), evidence=evidence))
    print("00163修正1を検証済み、訂正前版を金融未実施中止へ更新。双方の仕様と他試行は不変。", flush=True)


if __name__ == "__main__":
    main()
