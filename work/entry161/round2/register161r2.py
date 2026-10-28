"""板特徴の尺度修正を別試行として事前登録する。"""

from datetime import datetime
from pathlib import Path
import hashlib
import importlib.util
import json
import zipfile

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
IDENT = "161_第二巡_板数量変化の尺度修正"


def read(path: Path) -> dict:
    """JSONを読み込む。

    引数: path(Path)。返り値: dict。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def record(path: Path) -> dict:
    """根拠ファイルの内容指紋を返す。

    引数: path(Path)。返り値: dictは相対パスとSHA256。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest}


def save(path: Path, value: dict) -> None:
    """小さい新規証跡を保存する。

    引数: path(Path)、value(dict)。返り値: None。既存証跡を上書きしない。
    """
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def main() -> None:
    """人工監査済みの第二巡だけを同一性照合後に登録する。

    引数: なし。返り値: None。候補の採点は行わない。
    """
    receipt = HERE / "登録受領161r2.json"
    assert not receipt.exists()
    audit_path = HERE / "audit/preflight161r2_corrected.json"
    audit = read(audit_path)
    assert audit["passed"] and audit["sources"]
    for source in audit["sources"]:
        assert record(ROOT/source["path"])["sha256"] == source["sha256"], source["path"]
    original = read(BASE/"登録受領161.json")
    for source in original["sources"] + [original["implementation"], original["plan"]]:
        assert record(ROOT/source["path"])["sha256"] == source["sha256"], source["path"]
    files = sorted(p for p in (HERE/"search").rglob("*") if p.is_file() and p.suffix in {".py", ".json", ".md"})
    files += [HERE/"計画161r2.md", HERE/"register161r2.py", HERE/"allow161r2.py", audit_path]
    bundle = HERE/"評価前実装161r2.zip"
    with zipfile.ZipFile(bundle, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    plan = {"id": IDENT, "name": "板の偏りと補充代理を学習分位の尺度で確認", "purpose": "不具合修正",
        "question": "第一巡でほぼ無信号だった板系統を妥当な尺度へ直すと100円先着を識別できるか",
        "change": "学習特徴分布の分位で閾値を固定し、OFI・厚み・補充の単独と組合せ24条件を比較。元34条件は不変。",
        "repeat_reason": "平均化OFIに0.1、補充に0.2の第一巡閾値がほぼ成立しないことが判明。板情報の有効性を判断できる標本を作る。後半13場は既知追加開発として明示する。",
        "compares_to": [original["id"]],
        "spec": {
            "entry": {"method": "学習30場の特徴だけでphase別対称分位50/75/90を固定。数量変化、厚み、補充単独と価格受容との組合せ24条件。", "sources": [record(p) for p in files if "search" in p.parts]},
            "management": {"method": "第一巡と同じ候補×phaseの未決ロック、false→true、判断間隔60秒。前後重複を単一運用成績としない。"},
            "exit": {"method": "次正常板建値から100円順行が50円逆行より先なら成功。場内終端、未到達/未約定も分母に保持。"},
            "allocation": {"method": "事象を無加重計数。枚数・金額評価なし。"},
            "costs": {"fee": 0, "spread": "新規Ask/Bid、評価Bid/Ask。Lastは補助。"},
            "execution": {"method": "凍結済み特徴・ラベルを再利用、30場学習特徴/10場選択/候補固定後の既知13場で追加比較。完全未見ではない。"},
            "data": {"sessions": [scene["session"] for scene in read(BASE/"inputs161.json")["sessions"]],
                     "input_manifests": [record(BASE/"inputs161.json")], "extraction_proofs": [record(p) for p in sorted((BASE/"data").glob("*extraction161.json"))]},
            "implementation": {bundle.relative_to(ROOT).as_posix(): record(bundle)["sha256"], original["implementation"]["path"]: original["implementation"]["sha256"]}}}
    save(HERE/"評価計画161r2.json", plan)
    location = ROOT/"アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    spec = importlib.util.spec_from_file_location("試行161第二巡管理", location)
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    print("第二巡の尺度修正を照合・事前登録します。", flush=True)
    # ----------------------------------------
    # store_trial内部のcheckで実行前に照合し、その結果も別証跡として保存する。
    row = manager.store_trial(plan)
    save(HERE/"事前照合161r2.json", row["preflight"])
    save(receipt, {"id": IDENT, "registered": True, "returncode": 0,
                   "created_at": datetime.now().astimezone().isoformat(),
                   "sources": [record(p) for p in files], "implementation": record(bundle),
                   "plan": record(HERE/"評価計画161r2.json"), "candidate_evaluations": 0,
                   "known_test": True})
    print("第二巡の登録を完了しました。", flush=True)


if __name__ == "__main__":
    main()
