"""固定幅と失速入口の比較156の既登録3試行へ完了状態を付記する。条件・他ID・売買結果は変更しない。"""

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANAGER = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
PUBLIC = ROOT / "アルゴリズム調査/00156_固定値幅の利益保護と遅い入口の再検証"
JST = timezone(timedelta(hours=9))
TARGETS = {
    "156_固定値幅の玉別利益保護と失速入口の比較": [HERE / "report156.json", HERE / "金融実行156.json", HERE / "独立監査指紋156.json", HERE / "独立人工156.jsonl", HERE / "実行後指紋156.json"],
    "156_第二巡_固定保護後の同親再参加": [HERE / "round2/report1562.json", HERE / "round2/金融実行1562.json", HERE / "round2/実行後指紋1562.json", HERE / "round2/独立監査指紋1562.json", HERE / "round2/独立人工1562.jsonl", HERE / "report156_all.json"],
    "156_第三巡_再参加玉の初期逆行制限": [HERE / "round3/report1563.json", HERE / "round3/金融実行1563.json", HERE / "round3/実行後指紋1563.json", HERE / "round3/独立監査指紋1563.json", HERE / "round3/独立人工1563.jsonl"],
}


def canonical_digest(value):
    """巨大なオブジェクトを文字列一括化せず内容指紋へ変換する。

    引数: value(object)はJSON互換値。
    返り値: strはキー順を正規化した内容のSHA256。
    """
    digest = hashlib.sha256()
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))
    for part in encoder.iterencode(value):
        digest.update(part.encode("utf-8"))
    return digest.hexdigest()


def save_small(path, value):
    """小さい完了証跡をUTF-8で保存する。

    引数: path(Path)、value(dict)は出力先と証跡。
    返り値: None。巨大な正本はこの関数へ渡さない。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    """既存管理器で検査・ビュー生成し、対象3試行の状態だけを安全に置換する。

    引数: なし。
    返り値: None。重複登録はせず、他IDと条件の不変を確認した完了受領を保存する。
    """
    spec = importlib.util.spec_from_file_location("試行156の既存管理器", MANAGER)
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)

    def reference(path):
        """既存ファイルの完了根拠を返す。

        引数: path(Path)はプロジェクト内ファイル。
        返り値: dictは相対パス、SHA256、バイト数。
        """
        assert path.is_file() and path.resolve().is_relative_to(ROOT)
        return {"path": path.relative_to(ROOT).as_posix(), "sha256": manager.digest(path), "bytes": path.stat().st_size}

    # ----------------------------------------
    # 登録の成功を再確認する。新規登録や売買再生をこの完成器から呼ばない。
    receipt_path = HERE / "登録受領156.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    assert receipt.get("registered") is True and receipt.get("returncode") == 0
    assert receipt.get("id") == next(iter(TARGETS))
    report = json.loads((HERE / "report156.json").read_text(encoding="utf-8-sig"))
    execution = json.loads((HERE / "金融実行156.json").read_text(encoding="utf-8-sig"))
    validation = report["validation"]
    assert execution["終了コード"] == 0 and execution["条件場数"] == 702 and execution["参照改変数"] == 0
    assert validation["case_accounting_matches"] == 702
    assert validation["saved_baseline_sessions"] == 26 and validation["raw_nk_sha_matches"] == 27
    for key in ("all_fills_next_normal_raw", "lots_parents_extrema_from_all_raw", "reserved_caps", "baseline_155", "source_results_unchanged"):
        assert validation[key] is True, key
    receipt2_path = HERE / "round2/登録受領1562.json"
    receipt2 = json.loads(receipt2_path.read_text(encoding="utf-8-sig"))
    assert receipt2["registered"] is True and receipt2["returncode"] == 0
    assert receipt2["id"] in TARGETS and receipt2["id"] != receipt["id"]
    run2 = json.loads((HERE / "round2/金融実行1562.json").read_text(encoding="utf-8-sig"))
    report2 = json.loads((HERE / "round2/report1562.json").read_text(encoding="utf-8-sig"))
    assert run2["終了コード"] == 0 and run2["参照改変数"] == 0 and run2["条件場数"] == 486
    validation2 = report2["validation"]
    assert validation2["case_accounting_matches"] == 486 and validation2["saved_control_cases"] == 162
    assert validation2["raw_nk_sha_matches"] == 27 and validation2["first_report_unchanged"] is True
    receipt3_path = HERE / "round3/登録受領1563.json"
    receipt3 = json.loads(receipt3_path.read_text(encoding="utf-8-sig"))
    assert receipt3["registered"] is True and receipt3["returncode"] == 0
    assert receipt3["id"] in TARGETS and receipt3["id"] not in (receipt["id"], receipt2["id"])
    run3 = json.loads((HERE / "round3/金融実行1563.json").read_text(encoding="utf-8-sig"))
    report3 = json.loads((HERE / "round3/report1563.json").read_text(encoding="utf-8-sig"))
    assert run3["終了コード"] == 0 and run3["参照改変数"] == 0 and run3["条件場数"] == 243
    validation3 = report3["validation"]
    assert validation3["case_accounting_matches"] == 243 and validation3["saved_control_cases"] == 81
    assert validation3["raw_nk_sha_matches"] == 27 and validation3["prior_reports_unchanged"] is True
    for key in ("all_fills_next_normal_raw", "lots_parents_extrema_from_all_raw", "reserved_caps", "source_results_unchanged", "all_reentry_evidence_valid"):
        assert validation3[key] is True, key
    combined = json.loads((HERE / "report156_all.json").read_text(encoding="utf-8-sig"))
    assert len(combined["methods"]) == len(combined["current_rows"]) == 44
    now = datetime.now(JST).isoformat()
    common_paths = [PUBLIC / "README.md", PUBLIC / "検証記録.md", PUBLIC / "利益保護と再参加と入口見直しの全日中損益.xlsx", HERE / "report156_all.json", HERE / "結果の独立反証156.md", HERE / "xlsx_checks/Excel照合156.json", HERE / "xlsx_checks/保存Excelの独立検算156.json", HERE / "xlsx_checks/目視確認156.json"]
    common = [reference(path) for path in common_paths]
    completion = {"created_at": now, "targets": [{"id": trial_id, "status": "検証済み", "evidence": [reference(report) for report in reports] + common} for trial_id, reports in TARGETS.items()], "implementation": reference(Path(__file__).resolve()), "registration": reference(receipt_path), "registration2": reference(receipt2_path), "registration3": reference(receipt3_path), "validation_case_count": 1431, "unique_case_count": 1188, "new_effectiveness_evidence": True, "new_trial_registration": False, "spec_changes": False, "other_id_changes": False, "state": "証跡準備済み・正本更新前"}
    save_small(HERE / "試行完了証跡156.json", completion)
    print("3試行の完了証跡を保存。既存正本を読み取ります。", flush=True)
    lock_path = HERE / "試行状態更新156.lock"
    with lock_path.open("x", encoding="utf-8") as lock:
        lock.write(now)
    try:
        trials_path, view_path = manager.DATA / "trials.json", manager.DATA / "view-data.js"
        old_hash = manager.digest(trials_path)
        old_view_hash = manager.digest(view_path)
        value = manager.load(deep=False)
        assert value["source_sha256"]["trials.json"] == old_hash
        all_source_hashes = dict(value["source_sha256"])
        table = value["trials"]
        rows = table["trials"]
        ids_before = [row["id"] for row in rows]
        assert len(set(ids_before)) == len(ids_before)
        targets = {row["id"]: row for row in rows if row["id"] in TARGETS}
        assert set(targets) == set(TARGETS)
        unchanged_before = canonical_digest([row for row in rows if row["id"] not in TARGETS])
        metadata_before = canonical_digest({key: item for key, item in table.items() if key not in ("trials", "updated_at")})
        fixed_before = {trial_id: canonical_digest({key: item for key, item in row.items() if key not in ("status", "evidence", "completion")}) for trial_id, row in targets.items()}
        spec_before = {trial_id: canonical_digest(row["spec"]) for trial_id, row in targets.items()}
        for record in completion["targets"]:
            row = targets[record["id"]]
            assert row.get("status") == "未実行", (record["id"], row.get("status"))
            row["status"] = "検証済み"
            evidence = list(row.get("evidence", []))
            prior = {entry["path"]: entry for entry in evidence}
            for item in record["evidence"]:
                if item["path"] in prior:
                    assert prior[item["path"]]["sha256"] == item["sha256"]
                else:
                    evidence.append(item)
            row["evidence"] = evidence
            row["completion"] = {"completed_at": now, "evidence": record["evidence"], "result": "第1巡702・第2巡486・第3巡243の計1431条件場を独立会計。固有44条件1188条件場、対照243件を新規有効性に数えない。完了26日中と10月27日15:20までの途中1場を分離。再参加と局所逆行制限は累計赤字、入口案には利益減と場内リスク低下の交換条件。全原板で場内リスクを再会計し、43項目反証と46シートの全損益を公開。初回5/3/2配分は比較元のままで、数量最適化ではない。", "scope": "日経mini片方向10枚・費用0、全判断ラージ板、次正常BBO約定。既知期間の開発比較。今回1回固定取得した10月27日日中を見て入口案を設計したので未見検証とはしない。mini板追加なし。実運用9約定の費用込み会計とは別。App・dist・稼働環境・実注文は変更しない。1分複数取引の戦略完成を意味しない。"}
        table["updated_at"] = now
        assert [row["id"] for row in rows] == ids_before
        assert canonical_digest([row for row in rows if row["id"] not in TARGETS]) == unchanged_before
        assert canonical_digest({key: item for key, item in table.items() if key not in ("trials", "updated_at")}) == metadata_before
        for trial_id, row in targets.items():
            assert canonical_digest(row["spec"]) == spec_before[trial_id]
            assert canonical_digest({key: item for key, item in row.items() if key not in ("status", "evidence", "completion")}) == fixed_before[trial_id]
        manager.validate(value, deep=False)
        # ----------------------------------------
        # 更新対象の実装・入力・新しい完了根拠だけを深く照合する。過去他IDの条件は変更しない。
        focused = {"rules": {"rules": []}, "knowledge": {"findings": []}, "trials": {"trials": list(targets.values()), "repetition_audit": []}, "studies": {"studies": []}}
        manager.validate(focused, deep=True)
        print("対象3IDの条件と根拠・他ID不変を確認。正本とビューを一時保存します。", flush=True)
        staged_trials = manager.DATA / "trials.json.status156.tmp"
        staged_view = manager.DATA / "view-data.js.status156.tmp"
        assert not staged_trials.exists() and not staged_view.exists()
        with staged_trials.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(table, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        new_hash = manager.digest(staged_trials)
        value["source_sha256"]["trials.json"] = new_hash
        rendered = manager.bundle(value)
        with staged_view.open("w", encoding="utf-8", newline="\n") as stream:
            for start in range(0, len(rendered), 1024 * 1024):
                stream.write(rendered[start:start + 1024 * 1024])
        new_view_hash = manager.digest(staged_view)
        # ----------------------------------------
        # 他処理が正本を更新していないことを確かめ、旧正本と旧ビューを内容指紋付きで退避する。
        assert manager.digest(trials_path) == old_hash
        assert manager.digest(view_path) == old_view_hash
        for source_name, source_hash in all_source_hashes.items():
            assert manager.digest(manager.DATA / source_name) == source_hash, source_name
        history = manager.DATA / "history"
        history.mkdir(exist_ok=True)
        backup = history / f"trials_{old_hash}.json"
        view_backup = history / f"view-data_{old_view_hash}.js"
        for original, destination, expected in ((trials_path, backup, old_hash), (view_path, view_backup, old_view_hash)):
            if not destination.exists():
                shutil.copyfile(original, destination)
            assert manager.digest(destination) == expected
        staged_trials.replace(trials_path)
        try:
            staged_view.replace(view_path)
        except OSError:
            shutil.copyfile(backup, trials_path)
            shutil.copyfile(view_backup, view_path)
            raise
        assert manager.digest(trials_path) == new_hash
        assert manager.digest(view_path) == new_view_hash
        # bundleは同じ検査済みオブジェクトから一度だけ生成し、書出し指紋で一致を確認する。
        completion.update(state="正本と閲覧データの更新完了", changed_ids=list(TARGETS), unchanged_other_trials=True, unchanged_specs=spec_before,
                          before_trials_sha256=old_hash, after_trials_sha256=new_hash, before_view_sha256=old_view_hash, after_view_sha256=new_view_hash,
                          backup=backup.relative_to(ROOT).as_posix(), view_backup=view_backup.relative_to(ROOT).as_posix(),
                          trial_count=len(rows), full_structure_validated=True, target_evidence_deep_validated=True, view_from_same_validated_object=True)
        save_small(HERE / "試行完了証跡156.json", completion)
        print(json.dumps({"updated_trials": len(TARGETS), "status": "検証済み", "other_ids_unchanged": True, "spec_unchanged": True, "view_consistent": True}, ensure_ascii=False), flush=True)
    finally:
        if lock_path.exists():
            lock_path.unlink()


if __name__ == "__main__":
    main()
