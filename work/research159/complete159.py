"""検証成果の確定後に二つの登録試行へ完了根拠を結び付ける。"""

from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PUBLIC = ROOT / "アルゴリズム調査/00159_支持スコアの確度検証と夜間配分"
IDS = {"159_支持校正と米国前後の夜間数量政策", "159_第二巡_未知支持の基準量と超過分の保護"}


def sha(path: Path) -> str:
    """成果又は台帳の内容指紋を返す。

    引数: path(Path)。返り値: strはSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path: Path) -> object:
    """確定したJSONを読む。

    引数: path(Path)。返り値: objectはJSON値。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, value: object) -> None:
    """小さい完了証跡を保存する。

    引数: path(Path)、value(object)。返り値: None。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def main() -> None:
    """実行・監査・Excel確認を必須にし、対象二IDだけを検証済みへ更新する。

    引数: なし。返り値: None。金融再生と実口座操作は行わない。
    """
    checks = [ROOT / "work/audit159/金融結果の独立監査159.json", ROOT / "work/audit159/round2/金融結果の独立監査159r2.json",
              ROOT / "work/audit159/xlsx_checks/保存Excelの独立検算159.json", ROOT / "work/audit159/xlsx_checks/目視確認159.json"]
    for path in checks:
        assert read(path)["passed"], str(path)
    assert read(HERE / "金融実行159.json")["exit_code"] == 0
    assert read(HERE / "round2/金融実行159r2.json")["exit_code"] == 0
    files = [PUBLIC / name for name in ("README.md", "支持スコアの検証.md", "検証記録.md", "支持スコアと昼夜の全セッション損益.xlsx")]
    files += checks + [HERE / "report159_all.json", HERE / "金融実行159.json", HERE / "round2/金融実行159r2.json", HERE / "round2/会計照合159r2.json"]
    files += [ROOT / "work/score159/支持校正の保存分析159.json", ROOT / "work/score159/夜間支持校正159.json",
              ROOT / "work/score159/夜間時間帯別の支持校正159.json", ROOT / "work/score159/round2/担当交互作用の時系列校正159r2.json",
              ROOT / "work/night159/round2/diagnosis/第二巡の救済と利益消失159.md",
              ROOT / "work/night159/round2/diagnosis/第二巡の救済と利益消失159.json"]
    evidence = [{"path": p.relative_to(ROOT).as_posix(), "sha256": sha(p)} for p in files]
    module_spec = importlib.util.spec_from_file_location("試行159完了管理", ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py")
    manager = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(manager)
    target = manager.DATA / "trials.json"
    old_hash = sha(target)
    print("成果と独立監査を確認しました。試行状態を更新します。", flush=True)
    value = manager.load(deep=False)
    assert value["source_sha256"]["trials.json"] == old_hash
    rows = value["trials"]["trials"]
    selected = [r for r in rows if r["id"] in IDS]
    assert len(selected) == 2
    old_specs = {r["id"]: json.dumps(r["spec"], ensure_ascii=False, sort_keys=True) for r in selected}
    for row in selected:
        row["status"] = "検証済み"
        row["evidence"] = evidence
        row["readme"] = (PUBLIC / "README.md").relative_to(ROOT).as_posix()
        row["report"] = (PUBLIC / "支持スコアと昼夜の全セッション損益.xlsx").relative_to(ROOT).as_posix()
        row["result_note"] = "支持の識別は保存初回玉を時系列評価。夜間16条件・26場、追加日中は配賦版差を分離。既知開発・元結果は不変。"
    assert old_specs == {r["id"]: json.dumps(r["spec"], ensure_ascii=False, sort_keys=True) for r in selected}
    value["trials"]["updated_at"] = datetime.now().astimezone().isoformat()
    manager.validate(value, deep=True)
    serialized = json.dumps(value["trials"], ensure_ascii=False, indent=2, allow_nan=False)+"\n"
    new_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    value["source_sha256"]["trials.json"] = new_hash
    view = manager.bundle(value)
    assert sha(target) == old_hash, "他の登録と競合しました"
    history = manager.DATA / "history" / ("trials_"+old_hash+".json")
    if not history.exists():
        shutil.copyfile(target, history)
    staged = manager.DATA / "trials.json.tmp"
    staged_view = manager.DATA / "view-data.js.tmp"
    staged.write_text(serialized, encoding="utf-8", newline="\n")
    staged_view.write_text(view, encoding="utf-8", newline="\n")
    staged.replace(target)
    try:
        staged_view.replace(manager.DATA / "view-data.js")
    except OSError:
        shutil.copyfile(history, target)
        raise
    save(HERE / "試行完了証跡159.json", {"passed": True, "ids": sorted(IDS), "status": "検証済み", "spec_changes": False,
         "other_trial_changes": False, "previous_sha256": old_hash, "new_sha256": sha(target), "evidence": evidence})
    print("二試行の完了状態と根拠を保存しました。", flush=True)


if __name__ == "__main__":
    main()
