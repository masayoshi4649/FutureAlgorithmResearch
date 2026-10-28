"""数量配分157の登録条件を保ったまま、独立会計・公開成果付きの完了状態へ更新する。"""

from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = ROOT / "アルゴリズム調査/00157_支持別の数量配分と両建ての場内リスク検証"
ID = "157_支持別の数量配分と両建ての場内リスク"
SECOND_ID = "157_第二巡_観測間隔と少量参加の数量配分"
THIRD_ID = "157_第三巡_元玉出口と追加カバーの分離"
IDS = (ID, SECOND_ID, THIRD_ID)


def read(path):
    """JSON証跡を読み取る。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest_value(value):
    """巨大なJSONを一括文字列にせず正規化指紋へ変換する。

    引数: value(object)。返り値: strはSHA256。
    """
    digest = hashlib.sha256()
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))
    for part in encoder.iterencode(value):
        digest.update(part.encode("utf-8"))
    return digest.hexdigest()


def save(path, value):
    """小さい完了証跡をUTF-8で保存する。

    引数: path(Path)、value(dict)。返り値: None。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    """検査済みの成果を照合し、対象3IDだけの状態と完了根拠を更新する。

    引数: なし。返り値: None。売買再生・新規試行登録は行わない。
    """
    receipt = read(HERE / "登録受領157.json")
    execution = read(HERE / "金融実行157.json")
    audit = read(HERE / "金融監査157.json")
    report = read(HERE / "report157.json")
    configs = read(HERE / "configs157.json")
    assert receipt["registered"] and receipt["returncode"] == 0 and receipt["id"] == ID
    assert execution["終了コード"] == 0 and execution["参照改変数"] == 0
    assert audit["passed"] and audit["case_count"] == execution["条件場数"] == len(configs) * 27
    assert len(report["methods"]) == len(configs)
    second = HERE / "round2"
    second_receipt = read(second / "登録受領1572.json")
    second_execution = read(second / "金融実行1572.json")
    second_audit = read(second / "金融監査1572.json")
    second_report = read(second / "report1572.json")
    second_configs = read(second / "configs1572.json")
    assert second_receipt["registered"] and second_receipt["returncode"] == 0 and second_receipt["id"] == SECOND_ID
    assert second_execution["終了コード"] == 0 and second_execution["参照改変数"] == 0
    assert second_audit["passed"] and second_audit["case_count"] == second_execution["条件場数"] == len(second_configs) * 27 == 1080
    assert len(second_report["methods"]) == len(second_configs) == 40
    third = HERE / "round3"
    third_receipt = read(third / "登録受領1573.json")
    third_execution = read(third / "金融実行1573.json")
    third_audit = read(third / "金融監査1573.json")
    third_report = read(third / "report1573.json")
    assert third_receipt["registered"] and third_receipt["returncode"] == 0 and third_receipt["id"] == THIRD_ID
    assert third_execution["終了コード"] == 0 and third_execution["参照改変数"] == 0
    assert third_audit["passed"] and third_audit["case_count"] == third_execution["条件場数"] == 324
    assert len(third_report["methods"]) == len(read(third / "configs1573.json")) == 12
    assert len(read(HERE / "report157_all.json")["methods"]) == 73
    assert read(HERE / "xlsx_checks/保存Excelの独立検算157.json")["passed"]
    assert read(HERE / "xlsx_checks/目視確認157.json")["passed"]
    module_spec = importlib.util.spec_from_file_location("試行157完了管理", ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py")
    manager = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(manager)

    def ref(path):
        """根拠の存在と位置を確認し内容指紋を返す。

        引数: path(Path)。返り値: dictは相対位置・SHA256・バイト数。
        """
        assert path.is_file() and path.resolve().is_relative_to(ROOT)
        return {"path": path.relative_to(ROOT).as_posix(), "sha256": manager.digest(path), "bytes": path.stat().st_size}

    files = [PUBLIC / "README.md", PUBLIC / "検証記録.md", PUBLIC / "支持別配分と両建ての全日中損益.xlsx"]
    files += [HERE / name for name in ("report157.json", "金融実行157.json", "実行後指紋157.json", "金融監査157.json", "xlsx_checks/保存Excelの独立検算157.json", "xlsx_checks/目視確認157.json")]
    files += [HERE / "report157_all.json"]
    files += [second / name for name in ("report1572.json", "金融実行1572.json", "実行後指紋1572.json", "金融監査1572.json", "spec1572.json", "configs1572.json")]
    files += [third / name for name in ("report1573.json", "金融実行1573.json", "実行後指紋1573.json", "金融監査1573.json", "spec1573.json", "configs1573.json")]
    files += [HERE / "結果の独立反証157.md"]
    files += [second / name for name in ("結果の独立反証1572.md", "支持と元S01損益の関係1572.md", "支持と元S01損益の関係1572.json", "増枚と配分の算術分解1572.md", "第二巡の数量政策の具体診断1572.md")]
    files += [third / name for name in ("結果の独立反証1573.md", "第三巡の数量管理と逆玉回収の具体診断1573.md", "第三巡の数量管理と逆玉回収の具体診断1573.json", "第三巡の順行追加_勝ちと負けの原板図.png")]
    evidence = [ref(path) for path in files]
    now = datetime.now().astimezone().isoformat()
    completion = {"created_at": now, "ids": list(IDS), "status": "検証済み", "evidence": evidence, "implementation": ref(Path(__file__).resolve()), "spec_changes": False, "other_id_changes": False, "state": "完了根拠確認済み・正本更新前"}
    save(HERE / "試行完了証跡157.json", completion)
    lock_path = HERE / "試行状態更新157.lock"
    with lock_path.open("x", encoding="utf-8") as lock:
        lock.write(now)
    try:
        print("157の根拠確認済み。既存正本を読み取ります。", flush=True)
        trials_path, view_path = manager.DATA / "trials.json", manager.DATA / "view-data.js"
        old_hash, old_view = manager.digest(trials_path), manager.digest(view_path)
        value = manager.load(deep=False)
        assert value["source_sha256"]["trials.json"] == old_hash
        old_sources = dict(value["source_sha256"])
        table = value["trials"]
        rows = table["trials"]
        selected = [row for row in rows if row["id"] in IDS]
        assert len(selected) == 3 and {row["id"] for row in selected} == set(IDS)
        assert all(row["status"] == "未実行" for row in selected)
        others_before = digest_value([row for row in rows if row["id"] not in IDS])
        fixed_before = {target["id"]: digest_value({key: item for key, item in target.items() if key not in ("status", "evidence", "completion")}) for target in selected}
        for target in selected:
            target["status"] = "検証済み"
            current = list(target.get("evidence", []))
            known = {entry["path"]: entry for entry in current}
            for item in evidence:
                if item["path"] in known:
                    assert known[item["path"]]["sha256"] == item["sha256"]
                else:
                    current.append(item)
            target["evidence"] = current
            run_note = {
                ID: "第一巡23条件621条件場。145/155初回親が支持未知となった参加不足を診断。",
                SECOND_ID: "第二巡40条件1080条件場。観測間隔と補助欠測を明示し、初回の最低5/10/20micro＋支持量と固定10microを比較。",
                THIRD_ID: "第三巡12条件324条件場。元玉の旧出口と独自追加・カバー・逆玉だけの利益追尾・支持崩壊返済を分離。"
            }[target["id"]]
            target["completion"] = {"completed_at": now, "evidence": evidence, "result": run_note + "三巡の固有73条件を26完了日中と当日途中1場で比較。共通C00とO00/J02は同額再現で新たな成功例に数えない。初回・追加・抑制・逆行回復・親内両建てを分離。全場損益、場内リスクと具体時刻の診断は公開成果参照。", "scope": "micro100枚相当=mini10枚相当／片方向。手数料0、次正常ラージ気配。支持を成功確率にしない。既知期間の開発比較。Night、実micro約定性能、実アプリへの移植は未検証。"}
        table["updated_at"] = now
        assert digest_value([row for row in rows if row["id"] not in IDS]) == others_before
        assert all(digest_value({key: item for key, item in target.items() if key not in ("status", "evidence", "completion")}) == fixed_before[target["id"]] for target in selected)
        manager.validate(value, deep=False)
        manager.validate({"rules": {"rules": []}, "knowledge": {"findings": []}, "trials": {"trials": selected, "repetition_audit": []}, "studies": {"studies": []}}, deep=True)
        print("157の条件と他ID不変を確認。正本とビューを保存します。", flush=True)
        staged_trials = manager.DATA / "trials.json.status157.tmp"
        staged_view = manager.DATA / "view-data.js.status157.tmp"
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
        new_view = manager.digest(staged_view)
        for name, expected in old_sources.items():
            assert manager.digest(manager.DATA / name) == expected, name
        assert manager.digest(trials_path) == old_hash and manager.digest(view_path) == old_view
        history = manager.DATA / "history"
        history.mkdir(exist_ok=True)
        backups = [(trials_path, history / f"trials_{old_hash}.json", old_hash), (view_path, history / f"view-data_{old_view}.js", old_view)]
        for original, destination, expected in backups:
            if not destination.exists():
                shutil.copyfile(original, destination)
            assert manager.digest(destination) == expected
        staged_trials.replace(trials_path)
        try:
            staged_view.replace(view_path)
        except OSError:
            for original, backup, _ in backups:
                shutil.copyfile(backup, original)
            raise
        assert manager.digest(trials_path) == new_hash and manager.digest(view_path) == new_view
        completion.update(state="正本と閲覧データの更新完了", changed_ids=list(IDS), unchanged_other_trials=True, unchanged_spec=True, before_trials_sha256=old_hash, after_trials_sha256=new_hash, before_view_sha256=old_view, after_view_sha256=new_view, full_structure_validated=True, target_evidence_deep_validated=True)
        save(HERE / "試行完了証跡157.json", completion)
        print("157の完了登録成功。条件と他IDは変更なし。", flush=True)
    finally:
        if lock_path.exists():
            lock_path.unlink()


if __name__ == "__main__":
    main()
