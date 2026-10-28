"""夜間候補と追加日中の固定仕様を、売買再生前に既存台帳へ登録する。"""

from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "work/research159"
ENGINE = ROOT / "work/night159"
MANIFEST = ROOT / "work/audit159/inputs159.json"
ID = "159_支持校正と米国前後の夜間数量政策"


def read(path: Path) -> object:
    """保存JSONを変更せず読む。

    引数: path(Path)。返り値: objectはJSON値。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, value: object) -> None:
    """有限なJSONをUTF-8で保存する。

    引数: path(Path)、value(object)。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def fingerprint(path: Path) -> dict:
    """登録対象を内容指紋で固定する。

    引数: path(Path)。返り値: dictは相対パス、SHA256、バイト数。
    """
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha, "bytes": path.stat().st_size}


def main() -> None:
    """候補、入力、人工監査の固定を確認して事前照合・登録する。

    引数: なし。返り値: None。金融再生を起動しない。
    """
    receipt = HERE / "登録受領159.json"
    assert not receipt.exists(), "既登録の計画を上書きしない"
    configs = read(ENGINE / "configs159.json")
    spec = read(ENGINE / "spec159.json")
    artificial = read(ENGINE / "人工検証159.json")
    audit = read(ROOT / "work/audit159/金融前監査159.json")
    assert artificial["dedicated_artificial_tests"]["returncode"] == 0 and audit["passed"]
    assert artificial["new_candidate_replays"] == 0
    manifest = read(MANIFEST)
    assert manifest["complete_night_sessions"] == 26
    files = sorted(p for p in (ENGINE / "engine_go").rglob("*") if p.is_file() and (p.suffix in (".go", ".toml") or p.name in ("go.mod", "go.sum")))
    files += [ENGINE / name for name in ("configs159.json", "spec159.json", "実装仕様159.md", "人工検証159.json")]
    files += [Path(__file__), HERE / "execute159.py", MANIFEST, ROOT / "work/audit159/金融前監査159.json"]
    bundle = HERE / "再生前実装159.zip"
    assert not bundle.exists()
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    # ----------------------------------------
    # 旧台帳へ原板本文を複製せず、固定目録と各仕様の指紋を参照します。
    plan = {
        "id": ID, "name": "支持の識別と米国前後の夜間数量政策", "purpose": "条件比較",
        "question": "支持の強さに応じた初回量が日中と夜間で単位損益を識別し、夜間の損失頻度・深さを軽減するか",
        "change": "日中S01用J02の数量政策を、現行時間枠と同じ米国前P05・後D07の夜間へ分離接続。初回支持量、逆支持反証、追加量再評価、失速時配分、後半利益保護、前半逆行防御を別条件で比較。追加10/27Dayは同じS01/J02だけを確認。",
        "repeat_reason": "157は日中だけで、支持と初回玉の勝率・単位損益の時間順評価が不足。旧151夜間と現行枠の後半初期化は同一と断定せず、新基準で夜間差を測る。追加資料は既知途中場の完了版で、完全未見の場ではない。",
        "compares_to": ["157_第二巡_観測間隔と少量参加の数量配分", "157_第三巡_元玉出口と追加カバーの分離"],
        "spec": {
            "entry": {"method": "日中S01、夜間米国前P05・後D07。時刻・状態・支持は固定仕様。", "conditions": configs, "fixed_specification": spec},
            "management": {"method": "数量政策は当時支持で決定し、弱支持と欠測を分ける。前後独立Sourceと同時予約の上限を守る。具体条件はentryの固定仕様と実装指紋。"},
            "exit": {"method": "元Source返済を保持。米国前全返済、後半新状態、場末全返済。指定条件だけ利益保護又は逆行防御。到達線での約定を保証しない。"},
            "allocation": {"method": "mini10枚相当=micro100枚相当／片方向。所有と新規予約を合算。初回少量固定を必須としない。比較条件の固定少量は反証用。", "max_per_side": 100, "point_value": 10},
            "costs": {"fee": 0, "spread": "次正常ラージBBOで買Ask・売Bid、全玉を清算側で時価評価。mini/micro実市場の気配性能は未再現。"},
            "execution": {"method": "現在行で判断し後続正常行で執行。1分足は確定と公開遅延後。原行ごとの約定前後で場内最小時価と最大下落を評価。"},
            "data": {"sessions": [row["session"] for row in manifest["sessions"]], "input_manifests": [fingerprint(MANIFEST)], "scope": "26完了Nightと追加10/27Day。旧25Nightと追加完了1Nightを分離。現在APIなし。既知開発。"},
            "implementation": {bundle.relative_to(ROOT).as_posix(): fingerprint(bundle)["sha256"]},
        },
    }
    proposal = HERE / "再生計画159.json"
    save(proposal, plan)
    location = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    module_spec = importlib.util.spec_from_file_location("試行159管理", location)
    manager = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(manager)
    manager.validate({"rules": {"rules": []}, "knowledge": {"findings": []}, "trials": {"trials": [plan], "repetition_audit": []}, "studies": {"studies": []}}, deep=True)
    checked = manager.check(plan)
    save(HERE / "事前照合159.json", checked)
    assert checked["proposal_complete"]
    print("事前照合完了。旧台帳へ仕様・入力・実装を登録します。", flush=True)
    result = manager.store_trial(plan)
    save(receipt, {"id": ID, "registered": True, "returncode": 0, "created_at": datetime.now().astimezone().isoformat(),
                   "plan": fingerprint(proposal), "implementation": fingerprint(bundle),
                   "sources": [fingerprint(p) for p in files], "manifest": fingerprint(MANIFEST),
                   "matching_count": len(result["preflight"]["matches"]), "financial_replays": 0})
    print("登録完了。指紋照合後だけ金融再生を実行できます。", flush=True)


if __name__ == "__main__":
    main()
