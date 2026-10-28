"""固定保護後の再参加だけを追加する第2巡を、金融再生前に照合登録する。"""

import hashlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path
import zipfile


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
ID = "156_第二巡_固定保護後の同親再参加"


def read(path):
    """UTF-8のJSONを読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def reference(path):
    """プロジェクト相対の資料指紋を返す。

    引数: path(Path)。返り値: dictは場所・SHA256・サイズ。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest, "bytes": path.stat().st_size}


def save(path, value):
    """小さな証跡をUTF-8で保存する。

    引数: path(Path)、value(dict)。返り値: None。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def main():
    """第1巡の結果を根拠にした、固定18条件を照合登録する。

    引数: なし。返り値: None。金融再生・App変更・API取得はしない。
    """
    receipt_path = HERE / "登録受領1562.json"
    assert not receipt_path.exists()
    previous = read(BASE / "登録受領156.json")
    execution = read(BASE / "金融実行156.json")
    report = read(BASE / "report156.json")
    assert previous["registered"] and execution["終了コード"] == 0
    assert report["validation"]["case_accounting_matches"] == 702
    specification = read(HERE / "spec1562.json")
    configs = read(HERE / "configs1562.json")
    manifest = read(BASE / "inputs156.json")
    assert len(configs) == 18 and len(manifest["sessions"]) == 27
    assert {c["id"] for c in configs} == {"S01", "F05", "F09", "E07", "E08", "E09"} | {f"R{i:02}" for i in range(1, 13)}
    files = sorted(p for p in (HERE / "engine_go").rglob("*") if p.is_file() and (p.suffix in (".go", ".toml") or p.name in ("go.mod", "go.sum")))
    files += [HERE / p for p in ("spec1562.json", "spec1562.md", "configs1562.json", "register1562.py", "execute1562.py")]
    files += [BASE / p for p in ("inputs156.json", "report156.json", "登録受領156.json", "金融実行156.json", "spec156.json", "configs156.json")]
    assert len(files) > 30
    bundle = HERE / "再生前実装1562.zip"
    assert not bundle.exists()
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    inputs = [reference(BASE / "inputs156.json"), reference(BASE / "current_20261027/manifest.json")]
    plan = {
        "id": ID, "name": "固定利益保護後の同親再参加12条件", "purpose": "条件比較",
        "question": "早期全返済後に元仮想親が保有を続けて実玉が再参加しない経路を、新しい反発・反落での再参加だけで改善できるか",
        "change": "第1巡の固定20/40pt利益床と入口E3有無を保ち、保護全返済後に新しい極値から20/40/80pt戻れば同親同方向へ再参加する12条件。旧6条件を同値対照として残す。",
        "repeat_reason": "第1巡の固定保護16条件は全26完了Dayで全案赤字。F05は10/15に5000円を回収した後、実玉0・仮想源保有が継続し再参加せず、元同親の282000円を逃した。出口を固定したまま再参加だけを分離する。00151の40pt追尾再参加とは、S01源の同親継続・既存損切り保持・全玉利益床後限定・起動距離3対照が異なる。",
        "compares_to": [previous["id"]],
        "spec": {
            "entry": {"baseline": "S01及び第1巡F05/F09/E07/E08/E09。Rの変更は保護全返済後の再参加のみ。", "conditions": configs, "fixed_plan": specification},
            "management": {"method": "元仮想親の同方向保有中に限り、自己保護返済の約定以後のラージ返済側気配で極値を作る。旧値の即再利用なし。原注文・未確定注文が優先。元源終了・反転・親変更・場末で再参加待機を消し、再参加実玉も元退出に従う。"},
            "exit": {"method": "各実玉の利益>0で固定20/40pt床を起動し、方向付き床=max(0,最高順行幅−幅)。新しい実玉は建値と床を新規に持ち、旧最高益を流用しない。元損切り・部分返済・全返済を維持。"},
            "allocation": {"product": "NK225mini", "point_value": 100, "max_per_side": 10, "role_caps": {"core": 5, "addon": 3, "episode": 2}, "method": "再参加数量は同担当の保護全返済直前の自己数量以内、役割上限以内。保有＋予約で片方向10枚。元仮想10枚を実10枚へ拡大しない。"},
            "costs": {"fee": 0, "spread": "ラージBid/Askの次正常原行。mini板追加なし、価格を建値で埋めない。"},
            "execution": {"method": "同原行約定なし。新規も返済も次正常板。元入力の順序・指標準備・足確定遅延を維持。対照6条件は第1巡の全27場の保存全約定と同値。"},
            "data": {"sessions": [s["session"] for s in manifest["sessions"]], "input_manifests": inputs, "scope": "第1巡と完全に同じ26完了Dayと10/27の15:20未満途中1場。18条件×27=486条件場。新12の324条件場と同値対照162を区別。既知期間の開発比較。追加取得なし。"},
            "implementation": {bundle.relative_to(ROOT).as_posix(): reference(bundle)["sha256"]}
        }
    }
    path = HERE / "再生計画1562.json"
    save(path, plan)
    module_spec = importlib.util.spec_from_file_location("試行156第二巡管理", ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py")
    manager = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(manager)
    preflight = manager.analyzer().analyze(plan, [])
    assert preflight["proposal_complete"], preflight
    manager.validate({"rules": {"rules": []}, "knowledge": {"findings": []}, "trials": {"trials": [plan], "repetition_audit": []}, "studies": {"studies": []}}, deep=True)
    print("第2巡の固定18条件を照合登録します。金融再生はまだ行いません。", flush=True)
    record = manager.store_trial(plan)
    save(HERE / "事前照合1562.json", record["preflight"])
    save(receipt_path, {"id": ID, "registered": True, "returncode": 0, "created_at": datetime.now().astimezone().isoformat(), "plan": reference(path), "implementation": reference(bundle), "sources": [reference(p) for p in files], "inputs": inputs})
    print("第2巡登録完了。指紋照合後だけ金融再生できます。", flush=True)


if __name__ == "__main__":
    main()
