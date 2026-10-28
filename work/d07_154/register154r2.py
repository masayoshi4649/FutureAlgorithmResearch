"""D07の残玉と担当別初回数量を、金融再生前に固定・登録する。"""
import hashlib
import importlib.util
import json
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ID = "154_第二巡_利益回収後の再参加と遅い大口新規の限定"


def reference(path):
    """根拠の指紋を作る。

    引数: path(Path)。返り値: dictは相対名、SHA256、バイト数。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest, "bytes": path.stat().st_size}


def main():
    """既存照合器で実装と入力を記録する。

    引数: なし。返り値: なし。金融再生・実注文・稼働設定変更は行わない。
    """
    receipt_path = HERE / "登録受領154r2.json"
    assert not receipt_path.exists(), "既登録の上書きは禁止"
    spec_path = HERE / "spec154_round2.json"
    specification = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    manifest_path = HERE / "inputs154.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    assert manifest and specification
    files = sorted(p for p in (HERE / "engine_go_round2").rglob("*") if p.is_file() and (p.suffix == ".go" or p.name in ("go.mod", "go.sum") or p.suffix == ".toml"))
    assert len(files) > 50
    files += [spec_path, manifest_path, HERE / "configs154_round2.json", HERE / "spec154_round2.md"]
    bundle = HERE / "再生前実装154r2.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(HERE).as_posix())
    source_refs = [reference(p) for p in files]
    inputs = [reference(manifest_path), reference(HERE / "current_20261027/manifest.json")]
    plan = {
        "id": ID, "name": "早期利確後の別親解放と遅い重複新規だけを限定する第二巡", "purpose": "条件比較",
        "question": "一律の保護・減枚で失った大勝ちを維持しながら、早期利確後の逆張り解放と進行済みの波への大口新規を限定して安定性を改善できるか",
        "change": "初巡で検出した副作用に対応。episodeだけの親利益保護と無改修D07の仮想保有に基づく異親抑止を純対照で分離。coreは既存同方向episodeが固定R以上進んでいる入口だけを少枚数・段階投入へ変更。",
        "repeat_reason": "初巡G01は同入口利益減少に加えて新設親が計27万円損失。C03は追撃自体の利益23.1万円より初回減枚の機会損失129.2万円が大きかった。全ての入口と担当を一律に変える操作から、当時の状態による限定へ修正する。初巡結果と入力は不変。",
        "compares_to": ["154_D07の利益返しと担当別数量の改善"],
        "spec": {
            "entry": {"baseline": "現AppのNK225_D07。基本・追加・別入口の独立条件を維持。Day/Night条件は現実装のまま。", "fixed_plan": specification},
            "management": {"method": "原板を時系列処理し、観測時までの足だけを公開。Sの無改修D07影は同じ観測と次正常気配だけで逐次進め、保存された将来終了時刻を参照しない。Jの対象判定は新親採用時の実episode残玉・数量加重建値・返済側含み・初回固定Rから固定する。その他は初巡の予約/部分返済/全返済優先を維持。"},
            "exit": {"method": "元の損切り・利益回収・米国開始前後静観・場末返済を保持し、仕様に記録した担当だけ変更する。全返済は追加より優先。現在途中場は末尾で架空清算せず、実現と未実現を分離する。"},
            "allocation": {"product": "NK225mini", "point_value": 100, "max_per_side": 10, "role_caps": {"core": 5, "addon": 3, "episode": 2}, "method": "基準の固定枠と、初回1枚だけの数量対照、1枚から段階増加する条件を区別する。最大数量と未約定枠を独立検査。"},
            "costs": {"fee": 0, "spread": "手数料0で比較するが次正常ラージBBOの買ask/売bidを使う。実運用履歴は実mini約定・手数料込みの別表。模型の値を実運用損益と称さない。"},
            "execution": {"method": "全保存原板と足。市場時計の同値行は順序維持。判断の次正常自己原板で全量約定。独立受信時計とmini当時気配は無く、原価格時計模型である。未来価格・終値方向を判断へ渡さない。"},
            "data": {"sessions": [s["session"] for s in manifest["sessions"]], "input_manifests": inputs, "scope": "保存済み51完了場と2026-10-27デイ12:08未満。完了場と途中場の会計は分離。全て既知開発比較であり未見成功の証明ではない。当日取得は固定した原資料を使い回す。"},
            "implementation": {bundle.relative_to(ROOT).as_posix(): reference(bundle)["sha256"]}
        }
    }
    path = HERE / "再生計画154r2.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    manager_path = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    spec = importlib.util.spec_from_file_location("研究154の試行管理", manager_path)
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    preflight = manager.analyzer().analyze(plan, [])
    assert preflight["proposal_complete"], preflight
    manager.validate({"rules": {"rules": []}, "knowledge": {"findings": []}, "trials": {"trials": [plan], "repetition_audit": []}, "studies": {"studies": []}}, deep=True)
    print("実装・入力を固定し、既存試行との照合登録を開始します。", flush=True)
    record = manager.store_trial(plan)
    (HERE / "事前照合154r2.json").write_text(json.dumps(record["preflight"], ensure_ascii=False, indent=2), encoding="utf-8")
    receipt_path.write_text(json.dumps({"id": ID, "registered": True, "returncode": 0,
        "created_at": datetime.now(timezone(timedelta(hours=9))).isoformat(), "plan": reference(path), "implementation": reference(bundle), "sources": source_refs, "inputs": inputs}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("登録完了。固定指紋を確認した上で金融再生可能です。", flush=True)


if __name__ == "__main__":
    main()
