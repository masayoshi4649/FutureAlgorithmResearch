"""損切りなし両建ての仕様・入口通知・原資料を、金融再生より前に固定する。"""

import hashlib
import importlib.util
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TRIAL_ID = "151_損切りなし両建てと利益玉トレーリング"


def digest(path):
    """資料の内容指紋を算出する。

    引数: path(Path)は既存ファイル。返り値: strはSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def reference(path):
    """入力・実装の参照をプロジェクト相対パスで保存する。

    引数: path(Path)は既存ファイル。返り値: dictは指紋とサイズ。
    """
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path), "bytes": path.stat().st_size}


def main():
    """全18条件を固定し、既試行との照合・登録を完了させる。

    引数: なし。返り値: None。金融再生は登録受領の作成後だけ許す。
    """
    receipt = HERE / "登録受領151.json"
    assert not receipt.exists(), "登録済みの試行を再登録しない"
    configurations = json.loads((HERE / "configs151.json").read_text(encoding="utf-8-sig"))
    assert len(configurations) == 18
    assert {c["id"] for c in configurations} == {f"P{i:02d}" for i in range(1, 12)} | {f"N{i:02d}" for i in range(1, 8)}
    manifest_path = ROOT / "work/preus149/data/原資料一覧149.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    notification_manifest = HERE / "data/B04保存会計の指紋151.json"
    old_inputs = json.loads(notification_manifest.read_text(encoding="utf-8"))
    for item in old_inputs["files"]:
        assert digest(ROOT / item["path"]) == item["sha256"], item["path"]
    # ----------------------------------------
    inputs = [reference(manifest_path), reference(notification_manifest), reference(HERE / "data/保存資料の一覧と再利用151.json"),
              reference(ROOT / "work/preus150/report150.json")]
    for scene in manifest["sessions"]:
        inputs.append(reference(ROOT / "work/preus149/results_round2" / (scene["session"] + ".json")))
        inputs.append(reference(ROOT / "work/preus149/results_go" / (scene["session"] + ".json")))
    inputs += [reference(path) for path in sorted((HERE / "inputs").glob("*.json"))]
    assert len(list((HERE / "inputs").glob("*.json"))) == 26
    inputs_path = HERE / "入力指紋151.json"
    inputs_path.write_text(json.dumps(inputs, ensure_ascii=False, indent=2), encoding="utf-8")
    sources = sorted(p for p in (HERE / "engine_go").rglob("*") if p.is_file() and (p.suffix == ".go" or p.name in ("go.mod", "go.sum")))
    sources += [HERE / "configs151.json", HERE / "engine仕様151.md"]
    assert sources and all(p.exists() for p in sources)
    implementation = HERE / "再生前実装151.zip"
    with zipfile.ZipFile(implementation, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sources:
            archive.write(path, path.relative_to(HERE).as_posix())
    source_refs = [reference(p) for p in sources]
    # ----------------------------------------
    plan = {
        "id": TRIAL_ID, "name": "D07由来の両側新規に損切りなし利益追尾を組み合わせる18対照",
        "purpose": "条件比較", "question": "負け玉を残し買売双方の利益だけを回転させれば、場内全清算後も損失を補えるか",
        "change": "B04の仮想新規通知を保存時点で受け、実玉の価格損切り・方向退出を廃止。玉別の利益開始と浅追尾、数量、両建て禁止対照、US前清算と夜末までの保持、利確後価格再参加を分離比較する。",
        "repeat_reason": "00120/00121は類似の上下対称利益玉回転だが、Last段階新規・旧商品数量・費用込み・別期間。本試行はD07由来通知・mini片側10枚・費用0・米国前分離で異なる。00150は初期損切りと元出口を保持しており本試行と異なる。未整理の既試行全てを重複なしとは断定しない。",
        "compares_to": ["150_D07米国前の閾値緩和と開始前リセット", "150_第二巡_主担当の近隣しきい値と浅い押戻り"],
        "spec": {
            "entry": {"method": "B04の独立した仮想売買が発したnew通知を判断原行で使用。仮想側の元損切り・返済は次の入口候補の形成に残すが、実玉の返済へ適用しない。通知型には未来約定・返済・収支を渡さない。保存済み全通知の網羅性と原行添字を独立監査する。", "configurations": configurations},
            "management": {"method": "買玉と売玉を所有IDごとに独立。実保有と未約定新規を片方向10枚へ制約。利益返済の予定では余枠を増やさない。P10/P11/N06/N07だけ実利確後に同側・同数量でLast極値から40pt反発/反落の再新規を準備し反復。待機・予約・実玉は枠ごとに排他、境界で未発注待機解除。"},
            "exit": {"method": "初期価格損切りと元方向退出なし。返済側BBOの利益A到達後に最高利益からT戻りで返済。P09/N05だけ判断時の利益>0を再要求せず、他は利益が残る玉だけ返す。全案の次板約定損は計上。P群はUS15分前、N群は05:50に損益問わず全返済判断し次正常板で約定。途中打切り時は強制精算せず含み別計上。"},
            "allocation": {"product": "NK225mini", "cap_per_side": 10, "point_value": 100, "method": "買最大10・売最大10の予約込み。元通知数量、通知当たり上限1枚/2枚を比較。両側同時最大20枚を隠さない。"},
            "costs": {"fee": 0, "spread": "新規買ask/売bid、返済は逆。判断次正常ラージBBO代理。mini実約定数量や市場インパクトは未再現。"},
            "execution": {"method": "149と同じ原価格時計・正常BBO判定。判断原行より後の最初の正常板で約定。境界前の既決定新規は取り消して消さず次板で約定させ、境界超過なら同観測で全返済判断→さらに次正常板。P群は完済が保存S04後半の最初の新規判断より早いことを全場検査して合算。後半会計は新規判断へ渡さない。", "limitations": "独立した受信時計なし。未来の約定可否による入口選別をしない。利益判断でも次板で赤字になり得る。"},
            "data": {"sessions": [s["session"] for s in manifest["sessions"]], "input_manifests": [reference(inputs_path), reference(notification_manifest)], "range": "既知25完了夜と10/26取得済途中を分離。現在API取得なし。原資料156ファイルの内容指紋は149を継承、前回以降のsize/mtime不変を確認。", "scope": "日中は今回変更せず再生しない。C00/B04の保存会計を対照として再利用。"},
            "implementation": {implementation.relative_to(ROOT).as_posix(): digest(implementation)},
        },
    }
    plan_path = HERE / "再生計画151.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    (HERE / "凍結ソース151.json").write_text(json.dumps(source_refs, ensure_ascii=False, indent=2), encoding="utf-8")
    manager_path = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    spec = importlib.util.spec_from_file_location("研究151試行管理", manager_path)
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    preflight = manager.analyzer().analyze(plan, [])
    assert preflight["proposal_complete"], preflight
    print("18条件と実装を固定。既試行との照合・登録を開始します。", flush=True)
    record = manager.store_trial(plan)
    (HERE / "事前照合151.json").write_text(json.dumps(record["preflight"], ensure_ascii=False, indent=2), encoding="utf-8")
    receipt.write_text(json.dumps({"id": TRIAL_ID, "registered": True, "returncode": 0,
        "created_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
        "plan": reference(plan_path), "implementation": reference(implementation), "inputs": reference(inputs_path),
        "sources": source_refs}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("登録完了。指紋照合後に金融再生できます。", flush=True)


if __name__ == "__main__":
    main()
