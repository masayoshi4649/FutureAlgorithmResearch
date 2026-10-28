"""独立した入口の候補と時系列選択を、評価前に固定登録する。"""

from datetime import datetime
from pathlib import Path
import hashlib
import importlib.util
import json
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
IDENT = "161_独立入口の100円先着と時系列選択"


def read(path: Path) -> dict:
    """有限JSONの計画又は監査結果を読む。

    引数: path(Path)。返り値: dictは内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, value: object) -> None:
    """登録の小さい証跡を保存する。

    引数: path(Path)、value(object)。返り値: None。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def fingerprint(path: Path) -> dict:
    """コード・入力目録・監査の内容指紋を返す。

    引数: path(Path)。返り値: dictは相対パスとSHA256。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest}


def main() -> None:
    """独立人工監査に合格した計画だけを事前照合・登録する。

    引数: なし。返り値: None。金融計測は実行しない。
    """
    receipt = HERE / "登録受領161.json"
    assert not receipt.exists()
    audit = read(HERE / "audit/preflight161.json")
    assert audit["passed"]
    assert audit["sources"], "監査した実装指紋が必要です"
    for record in audit["sources"]:
        assert fingerprint(ROOT / record["path"])["sha256"] == record["sha256"], record["path"]
    manifest = read(HERE / "inputs161.json")
    assert manifest["counts"] == {"train": 30, "validation": 10, "test": 13}
    files = sorted(p for folder in (HERE / "features", HERE / "search") for p in folder.rglob("*")
                   if p.is_file() and p.suffix in (".py", ".md", ".json") and "__pycache__" not in p.parts)
    files += [HERE / name for name in ("inputs161.json", "計画.md", "参考研究.md", "register161.py", "allow161.py", "audit/preflight161.json")]
    assert any(p.suffix == ".py" and "features" in p.parts for p in files)
    assert any(p.suffix == ".py" and "search" in p.parts for p in files)
    bundle = HERE / "評価前実装161.zip"
    assert not bundle.exists()
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in files:
            archive.write(file, file.relative_to(ROOT).as_posix())
    plan = {"id": IDENT, "name": "既存手法を使わない日経100円順行と50円逆行の先着探索", "purpose": "新仮説",
        "question": "価格・板の動態・二市場から、50円逆行より100円順行が先になる入口を独立に検出できるか",
        "change": "既存手法の初回を母集団にせず、全場の因果的観測点から新しい候補ルール/単純学習を発生させ、時系列で選択と確認を分ける。",
        "repeat_reason": "00160の現行系統は30.3%に留まった。00117/00118の先着研究とも、対象53場・100/50非対称障壁・新特徴・分割・登録実装が異なる。旧全試行の不存在を断定せず関連研究を監査。",
        "compares_to": ["159_支持校正と米国前後の夜間数量政策"],
        "spec": {
            "entry": {"method": "旧E01/S01等の通知は不使用。価格・板動態・二市場の独立ルールと単純学習。候補・閾値・学習は同梱固定仕様。", "sources": [fingerprint(p) for p in files if "search" in p.parts]},
            "management": {"method": "候補×phaseごと1予測が未決の間は新標本を作らない。条件edgeと新規後60秒最小間隔。未決中もedge状態更新。前後区分の予測重複は許すため単一運用成績とは呼ばない。数量配分と損益管理なし。"},
            "exit": {"method": "価格経路の採点のみ。建値から+100円が−50円より先なら成功、50ちょうど逆行は失敗。同じ場末まで、未到達を別掲。実戦略の収支を作らない。"},
            "allocation": {"method": "1イベントを1件として無加重計数。架空の数量増加で確度を上げない。"},
            "costs": {"fee": 0, "spread": "主評価は次正常ラージBBOで新規買Ask/売Bid、経路は買Bid/売Ask。Last補助を主選択へ使わない。"},
            "execution": {"method": "各価格時計の最初正常自己板で判断し、後続正常原行で仮想新規。特徴は自己原行prefix、相手は過去の最初正常代表。受信時計不在を明示。", "selection": "30場学習、10場選択、最大3候補固定後に13場を一度確認。全て過去研究では既知。"},
            "data": {"sessions": [s["session"] for s in manifest["sessions"]], "input_manifests": [fingerprint(HERE / "inputs161.json")], "scope": "9/21〜10/27Dayの53完了場。現在API不使用。"},
            "implementation": {bundle.relative_to(ROOT).as_posix(): fingerprint(bundle)["sha256"]}}}
    proposal = HERE / "評価計画161.json"
    save(proposal, plan)
    path = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    spec = importlib.util.spec_from_file_location("試行161管理", path)
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    manager.validate({"rules": {"rules": []}, "knowledge": {"findings": []}, "trials": {"trials": [plan], "repetition_audit": []}, "studies": {"studies": []}}, deep=True)
    checked = manager.check(plan)
    assert checked["proposal_complete"]
    save(HERE / "事前照合161.json", checked)
    print("新入口の固定仕様を事前照合しました。登録します。", flush=True)
    row = manager.store_trial(plan)
    save(receipt, {"id": IDENT, "registered": True, "returncode": 0, "created_at": datetime.now().astimezone().isoformat(),
                   "plan": fingerprint(proposal), "implementation": fingerprint(bundle), "sources": [fingerprint(p) for p in files],
                   "matching_count": len(row["preflight"]["matches"]), "new_candidate_evaluations": 0})
    print("独立入口探索の評価前登録が完了しました。", flush=True)


if __name__ == "__main__":
    main()
