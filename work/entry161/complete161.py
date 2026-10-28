"""二巡の確定した先着検証を試行台帳へ結び付ける。"""

from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PUBLIC = ROOT/"アルゴリズム調査/00161_日経100円先着の独立入口探索"
IDS = {"161_独立入口の100円先着と時系列選択", "161_第二巡_板数量変化の尺度修正"}


def sha(path: Path) -> str:
    """内容の指紋を算出する。

    引数: path(Path)。返り値: strはSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path: Path) -> dict:
    """確定したJSONを読む。

    引数: path(Path)。返り値: dict。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> None:
    """二巡の監査合格を確認して対象試行だけを検証済みへ変更する。

    引数: なし。返り値: None。原板評価は行わない。
    """
    checks = [HERE/"audit/audit161.json", HERE/"round2/audit/audit161r2.json"]
    for path in checks:
        assert read(path)["passed"], str(path)
    files = [PUBLIC/name for name in ("README.md", "検証記録.md", "全セッションの先着率.md", "全候補の開発比較.md")]
    files += checks + [HERE/"報告用集計161.json", HERE/"diagnosis/診断161.json", HERE/"diagnosis/50先着後の100到達161.json"]
    for folder, authorization in ((HERE, "test完了許可161.json"), (HERE/"round2", "test完了許可161r2.json")):
        proof = read(folder/authorization)
        assert proof["completed"] is True and proof["returncode"] == 0
        assert proof["locked_test_sha256"] == sha(folder/"results/locked_test161.json")
        assert proof["freeze_sha256"] == sha(folder/"results/selection_frozen161.json")
        files += [folder/authorization] + [folder/"results"/name for name in ("train_validation161.json", "selection_frozen161.json", "locked_test161.json")]
    evidence = [{"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path)} for path in files]
    location = ROOT/"アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    spec = importlib.util.spec_from_file_location("試行161完了管理", location)
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    target = manager.DATA/"trials.json"
    old_hash = sha(target)
    print("二巡の成果と監査を確認しました。試行状態を更新します。", flush=True)
    value = manager.load(deep=False)
    assert value["source_sha256"]["trials.json"] == old_hash
    rows = [row for row in value["trials"]["trials"] if row["id"] in IDS]
    assert len(rows) == 2
    old_specs = {row["id"]: json.dumps(row["spec"], ensure_ascii=False, sort_keys=True) for row in rows}
    for row in rows:
        row["status"] = "検証済み"
        row["evidence"] = evidence
        row["readme"] = (PUBLIC/"README.md").relative_to(ROOT).as_posix()
        row["report"] = (PUBLIC/"全セッションの先着率.md").relative_to(ROOT).as_posix()
        row["result_note"] = "既存入口に依存しない100円/50円先着。第一巡34条件、板尺度修正24条件。第二巡後半は既知追加開発。数量・損益評価なし。"
    assert old_specs == {row["id"]: json.dumps(row["spec"], ensure_ascii=False, sort_keys=True) for row in rows}
    value["trials"]["updated_at"] = datetime.now().astimezone().isoformat()
    manager.validate(value, deep=True)
    serialized = json.dumps(value["trials"], ensure_ascii=False, indent=2, allow_nan=False)+"\n"
    value["source_sha256"]["trials.json"] = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    view = manager.bundle(value)
    assert sha(target) == old_hash, "他の登録と競合しました"
    history = manager.DATA/"history"/("trials_"+old_hash+".json")
    if not history.exists():
        shutil.copyfile(target, history)
    temporary = manager.DATA/"trials.json.tmp"
    staged_view = manager.DATA/"view-data.js.tmp"
    temporary.write_text(serialized, encoding="utf-8", newline="\n")
    staged_view.write_text(view, encoding="utf-8", newline="\n")
    temporary.replace(target)
    try:
        staged_view.replace(manager.DATA/"view-data.js")
    except OSError:
        shutil.copyfile(history, target)
        raise
    proof = {"passed": True, "ids": sorted(IDS), "status": "検証済み", "spec_changes": False,
             "other_trial_changes": False, "previous_sha256": old_hash, "new_sha256": sha(target), "evidence": evidence}
    with (HERE/"試行完了証跡161.json").open("x", encoding="utf-8") as stream:
        json.dump(proof, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print("二試行の完了状態と根拠を保存しました。", flush=True)


if __name__ == "__main__":
    main()
