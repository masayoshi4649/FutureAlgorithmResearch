"""移植検証155の既登録1試行へ完了状態を付記する。条件・他ID・売買結果は変更しない。"""

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANAGER = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
PUBLIC = ROOT / "アルゴリズム調査/00155_S01の日中運用への移植"
JST = timezone(timedelta(hours=9))
# 配布確認器の確定出力名が変わる場合は、この定義だけを変更する。
BINARY_SMOKE = HERE / "binary_smoke155.json"
TARGETS = {
    "155_S01の日中運用移植と全通知独立同値照合": [HERE / "report155.json", BINARY_SMOKE, HERE / "配布ビルド155.json", HERE / "アプリ検査155.json"],
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
    """既存管理器で検査・ビュー生成し、対象1試行の状態だけを安全に置換する。

    引数: なし。
    返り値: None。重複登録はせず、他IDと条件の不変を確認した完了受領を保存する。
    """
    spec = importlib.util.spec_from_file_location("試行155の既存管理器", MANAGER)
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
    receipt_path = HERE / "登録受領155.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    assert receipt.get("registered") is True and receipt.get("returncode") == 0
    assert receipt.get("id") == next(iter(TARGETS))
    report = json.loads((HERE / "report155.json").read_text(encoding="utf-8-sig"))
    smoke = json.loads(BINARY_SMOKE.read_text(encoding="utf-8-sig"))
    build = json.loads((HERE / "配布ビルド155.json").read_text(encoding="utf-8-sig"))
    assert report["same_order_fill_cases"] == report["independent_accounting_cases"] == report["total_cases"] == 79
    assert report["source_data_expected_changes"] == 0
    assert smoke["passed"] is True and smoke["exit_code"] == 0 and not smoke["controller_requests"]
    assert build["exit_code"] == 0 and build["既存実設定不変"] is True
    now = datetime.now(JST).isoformat()
    common = [reference(PUBLIC / "README.md"), reference(PUBLIC / "検証記録.md")]
    completion = {"created_at": now, "targets": [{"id": trial_id, "status": "検証済み", "evidence": [reference(report) for report in reports] + common} for trial_id, reports in TARGETS.items()], "implementation": reference(Path(__file__).resolve()), "registration": reference(receipt_path), "validation_case_count": 79, "new_effectiveness_evidence": False, "new_trial_registration": False, "spec_changes": False, "other_id_changes": False, "state": "証跡準備済み・正本更新前"}
    save_small(HERE / "試行完了証跡155.json", completion)
    print("1試行の完了証跡を保存。既存正本を読み取ります。", flush=True)
    lock_path = HERE / "試行状態更新155.lock"
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
            row["completion"] = {"completed_at": now, "evidence": record["evidence"], "result": "研究154の固定入力と期待結果を使い、S01の日中27条件場と変更しないD07の全52条件場、計79条件場について全通知・判断順序・次正常板約定・終端実現損益と含みを独立照合。実アプリの部分約定、鮮度、所有ID、復元、異常停止を人工試験し、配布版を隔離確認。結果は検証記録を参照。", "scope": "実アプリ移植の同値検査であり、新たな有効性や新条件の探索ではない。日経mini上限10枚・費用0・次正常ラージBBO、既知51完了場と保存済み10月27日日中12:08未満を再利用。未見データ追加・現API再取得・実注文・稼働環境への配布なし。日中標準をS01へ変更するローカル実装であり、夜のP05・静観・D07を維持。"}
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
        print("対象1IDの条件と根拠・他ID不変を確認。正本とビューを一時保存します。", flush=True)
        staged_trials = manager.DATA / "trials.json.status155.tmp"
        staged_view = manager.DATA / "view-data.js.status155.tmp"
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
        save_small(HERE / "試行完了証跡155.json", completion)
        print(json.dumps({"updated_trials": len(TARGETS), "status": "検証済み", "other_ids_unchanged": True, "spec_unchanged": True, "view_consistent": True}, ensure_ascii=False), flush=True)
    finally:
        if lock_path.exists():
            lock_path.unlink()


if __name__ == "__main__":
    main()
