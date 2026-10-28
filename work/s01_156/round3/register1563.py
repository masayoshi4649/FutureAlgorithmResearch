"""再参加玉だけの初期逆行制限を追加する第3巡を、金融再生前に照合登録する。"""

import hashlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path
import zipfile


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
ID = "156_第三巡_再参加玉の初期逆行制限"


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
    """第2巡の結果を根拠にした、固定9条件を照合登録する。

    引数: なし。返り値: None。金融再生・App変更・API取得はしない。
    """
    receipt_path = HERE / "登録受領1563.json"
    assert not receipt_path.exists()
    previous = read(BASE / "round2/登録受領1562.json")
    execution = read(BASE / "round2/金融実行1562.json")
    report = read(BASE / "round2/report1562.json")
    assert previous["registered"] and execution["終了コード"] == 0
    assert report["validation"]["case_accounting_matches"] == 486
    specification = read(HERE / "spec1563.json")
    configs = read(HERE / "configs1563.json")
    manifest = read(BASE / "inputs156.json")
    assert len(configs) == 9 and len(manifest["sessions"]) == 27
    assert {c["id"] for c in configs} == {"S01", "R01", "R04"} | {f"L{i:02}" for i in range(1, 7)}
    files = sorted(p for p in (HERE / "engine_go").rglob("*") if p.is_file() and (p.suffix in (".go", ".toml") or p.name in ("go.mod", "go.sum")))
    files += [HERE / p for p in ("spec1563.json", "spec1563.md", "configs1563.json", "register1563.py", "execute1563.py")]
    files += [BASE / p for p in ("inputs156.json", "report156.json", "round2/report1562.json", "round2/登録受領1562.json", "round2/金融実行1562.json", "round2/spec1562.json", "round2/configs1562.json")]
    assert len(files) > 30
    bundle = HERE / "再生前実装1563.zip"
    assert not bundle.exists()
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    inputs = [reference(BASE / "inputs156.json"), reference(BASE / "current_20261027/manifest.json")]
    plan = {
        "id": ID, "name": "再参加玉だけの建値基準の固定損失制限6条件", "purpose": "条件比較",
        "question": "小利益回収後に新たな勢いで再参加しても、未順行の新玉を元Sourceの遠い退出まで持つ損失が支配する非対称を、新玉だけの固定幅で縮小できるか",
        "change": "R01/R04を基礎に再参加玉だけ20/40/80ptの建値基準の逆行で返済判断する6案。元の初回・仮想Source・利益床・配分は保持。損切り後は元仕様どおり再参加armを作らず、同波の回転はいったん終了する。S01/R01/R04を同値対照とする。",
        "repeat_reason": "第二巡全12条件は26完了Dayで赤字。R01の再参加1192玉は291黒字・140赤字・761同値、利益151.6万円に対し損失436.1万円。一度も順行しない118玉の損失419万円が支配的。利益幅と再参加時の初期逆行許容の非対称へ限定して手を入れる。停止後に消える再上昇も計上し、単なる減枚・無取引の改善と混同しない。",
        "compares_to": [previous["id"], "156_固定値幅の玉別利益保護と失速入口の比較"],
        "spec": {
            "entry": {"baseline": "R01/R04の元初回・全保護返済後の20pt追尾再参加。入口は一切変更しない。", "conditions": configs, "fixed_plan": specification},
            "management": {"method": "負番号ticketの再参加実玉だけ、当時のラージ返済側価格と当玉の実建値の方向付き差を比較。元Source・元初回玉・新規予約数量は変えない。局所stop後は元ルール通りarmなしで、同波の回転終了を含む結果として測る。"},
            "exit": {"method": "再参加実玉だけ方向付き含みが−20/−40/−80pt以下なら未返済自己IDへ返済判断。元の退出・部分返済予約・成立済み利益床を優先。判断後の次正常板で約定し、指定幅に価格を補正しない。"},
            "allocation": {"product": "NK225mini", "point_value": 100, "max_per_side": 10, "role_caps": {"core": 5, "addon": 3, "episode": 2}, "method": "第2巡と同じ。再参加数量は保護完済前自己数以内。予約＋保有で上限を確認。"},
            "costs": {"fee": 0, "spread": "ラージの次正常Bid/Askを維持。mini板追加なし。利益損失の幅は約定保証でなく判断幅。"},
            "execution": {"method": "同原行約定なし。基準S01は第一巡、R01/R04は第二巡の全27場保存約定と同値を要求。元価格指標・Eを含む入力側の変更なし。"},
            "data": {"sessions": [x["session"] for x in manifest["sessions"]], "input_manifests": inputs, "scope": "同じ26完了Dayと10/27 15:20未満途中1場。9×27=243条件場、新6×27=162と同値対照81を区別。既知期間の開発比較、追加取得なし。"},
            "implementation": {bundle.relative_to(ROOT).as_posix(): reference(bundle)["sha256"]}
        }
    }
    path = HERE / "再生計画1563.json"
    save(path, plan)
    module_spec = importlib.util.spec_from_file_location("試行156第三巡管理", ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py")
    manager = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(manager)
    preflight = manager.analyzer().analyze(plan, [])
    assert preflight["proposal_complete"], preflight
    manager.validate({"rules": {"rules": []}, "knowledge": {"findings": []}, "trials": {"trials": [plan], "repetition_audit": []}, "studies": {"studies": []}}, deep=True)
    print("第3巡の固定9条件を照合登録します。金融再生はまだ行いません。", flush=True)
    record = manager.store_trial(plan)
    save(HERE / "事前照合1563.json", record["preflight"])
    save(receipt_path, {"id": ID, "registered": True, "returncode": 0, "created_at": datetime.now().astimezone().isoformat(), "plan": reference(path), "implementation": reference(bundle), "sources": [reference(p) for p in files], "inputs": inputs})
    print("第3巡登録完了。指紋照合後だけ金融再生できます。", flush=True)


if __name__ == "__main__":
    main()
