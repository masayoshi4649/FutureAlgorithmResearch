"""研究154の既登録2試行へ完了状態を付記する。条件・他ID・売買結果は変更しない。"""

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANAGER = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
PUBLIC = ROOT / "アルゴリズム調査/00154_D07の利益返しと多枚数新規の改善"
JST = timezone(timedelta(hours=9))
TARGETS = {
    "154_D07の利益返しと担当別数量の改善": [HERE / "report154.json"],
    "154_第二巡_利益回収後の再参加と遅い大口新規の限定": [HERE / "report154_round2.json"],
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
    """既存管理器で検査・ビュー生成し、対象2試行の状態だけを安全に置換する。

    引数: なし。
    返り値: None。重複登録はせず、他IDと条件の不変を確認した完了受領を保存する。
    """
    spec = importlib.util.spec_from_file_location("試行154の既存管理器", MANAGER)
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)

    def reference(path):
        """既存ファイルの完了根拠を返す。

        引数: path(Path)はプロジェクト内ファイル。
        返り値: dictは相対パス、SHA256、バイト数。
        """
        assert path.is_file() and path.resolve().is_relative_to(ROOT)
        return {"path": path.relative_to(ROOT).as_posix(), "sha256": manager.digest(path), "bytes": path.stat().st_size}

    now = datetime.now(JST).isoformat()
    common = [reference(PUBLIC / "README.md"), reference(PUBLIC / "検証記録.md")]
    completion = {"created_at": now, "targets": [{"id": trial_id, "status": "検証済み", "evidence": [reference(report) for report in reports] + common} for trial_id, reports in TARGETS.items()], "implementation": reference(Path(__file__).resolve()), "new_trial_registration": False, "spec_changes": False, "other_id_changes": False, "state": "証跡準備済み・正本更新前"}
    save_small(HERE / "試行完了証跡154.json", completion)
    print("2試行の完了証跡を保存。既存正本を読み取ります。", flush=True)
    lock_path = HERE / "試行状態更新154.lock"
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
            row["completion"] = {"completed_at": now, "evidence": record["evidence"], "result": "D07を基準に、残玉・初回数量・追加・親利益保護の初巡15条件と、再参加・遅い大口新規を限定する第二巡8条件を、日経の51完了場と既知途中1場で比較。全約定の独立会計と当日実約定、消えた勝ちと増えた負けを照合。結果は検証記録を参照。", "scope": "日経mini上限10枚・手数料0・次正常ラージ板の模型。全資料は既知開発データで未見成績ではない。当日APIは12:08未満を固定取得。実注文・App設定変更なし。"}
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
        print("対象2IDの条件と根拠・他ID不変を確認。正本とビューを一時保存します。", flush=True)
        staged_trials = manager.DATA / "trials.json.status154.tmp"
        staged_view = manager.DATA / "view-data.js.status154.tmp"
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
        save_small(HERE / "試行完了証跡154.json", completion)
        print(json.dumps({"updated_trials": len(TARGETS), "status": "検証済み", "other_ids_unchanged": True, "spec_unchanged": True, "view_consistent": True}, ensure_ascii=False), flush=True)
    finally:
        if lock_path.exists():
            lock_path.unlink()


if __name__ == "__main__":
    main()
