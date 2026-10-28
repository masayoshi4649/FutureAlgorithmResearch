"""ラージ板だけによる固定幅利益保護と失速入口25案を、金融再生前に登録する。"""
import hashlib
import importlib.util
import json
import zipfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ID = "156_固定値幅の玉別利益保護と失速入口の比較"


def reference(path):
    """既存資料の場所・サイズ・内容指紋を返す。

    引数: path(Path)。返り値: dictはプロジェクト相対位置とSHA256等。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest, "bytes": path.stat().st_size}


def main():
    """条件・対象・実装を既存管理器で照合登録する。

    引数: なし。返り値: None。金融再生、追加取得、App変更、実発注はしない。
    """
    receipt = HERE / "登録受領156.json"
    assert not receipt.exists()
    specification = json.loads((HERE / "spec156.json").read_text(encoding="utf-8-sig"))
    configs = json.loads((HERE / "configs156.json").read_text(encoding="utf-8-sig"))
    manifest = json.loads((HERE / "inputs156.json").read_text(encoding="utf-8-sig"))
    assert len(manifest["sessions"]) == 27
    files = sorted(p for p in (HERE / "engine_go").rglob("*") if p.is_file() and (p.suffix in (".go", ".toml") or p.name in ("go.mod", "go.sum")))
    assert len(files) > 20
    files += [HERE / name for name in ("spec156.json", "spec156.md", "configs156.json", "inputs156.json", "current_20261027/manifest.json", "監査.md", "過去知見と反証.md", "実約定3区間の診断156.md", "実約定3区間の原板診断156.json", "実入口の失速条件156.json", "実入口の失速条件156.md")]
    files += [Path(__file__).resolve(), HERE / "execute156.py"]
    bundle = HERE / "再生前実装156.zip"
    assert not bundle.exists()
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    inputs = [reference(HERE / "inputs156.json"), reference(HERE / "current_20261027/manifest.json")]
    plan = {
        "id": ID, "name": "固定値幅の玉別利益保護と失速した入口の25条件比較", "purpose": "条件比較",
        "question": "S01の利益返しを、全玉の固定幅・建値以上の判断床で減らし、失速したcore初回を見送る条件で赤字頻度と深さを改善できるか",
        "change": "F16は固定幅10/20/40/80pt×起動0超/20pt×独立元S01同担当の占有ゲート有無。E9は直近原板の完了1分closeによる3失速判定×元出口/固定20/40。基準S01を含む26条件。売買判定はラージ板だけ。",
        "repeat_reason": "実運用14:03買5の代理最高利益30150円から実収支45084円の損失、14:52売2の利益返し、15:00の買い入口を具体診断。S01の既存保護はepisodeだけでcore/addonが未保護。154の全親0.5R/50%床と異なり各実玉・固定pt・建値床を測り、再参加解放と入口失速を分離する。",
        "compares_to": ["154_D07の利益返しと担当別数量の改善", "154_第二巡_利益回収後の再参加と遅い大口新規の限定", "155_S01の日中運用移植と全通知独立同値照合"],
        "spec": {
            "entry": {"baseline": "S01日中。Fは元入口維持。Eはcore初回親のみを、当時までの連続した完了1分closeで拒否判断。拒否親は後追いしない。", "conditions": configs, "fixed_plan": specification},
            "management": {"method": "板行で各実玉の返済側利益幅を追跡。追加・部分返済で床を下げない。親粗実現/含みと各返済pieceの利益返しを別会計。独立S01の旧親占有は同じ過去から逐次駆動し、未来返済時計を使わない。"},
            "exit": {"method": "利益>0又は>=20ptで玉別に起動。方向付き床=max(0,最高順行幅−固定幅)。元退出・未確定注文・場末を優先し、保護返済が成立する行に同担当の新規追加を出さない。床割れ判断後の次正常板で約定し、値飛びの損失も保持。"},
            "allocation": {"product": "NK225mini", "point_value": 100, "max_per_side": 10, "role_caps": {"core": 5, "addon": 3, "episode": 2}, "method": "元配分維持。予約＋実玉で片方向10枚を検査。数量変更による見かけの損失縮小としない。"},
            "costs": {"fee": 0, "spread": "ラージの次正常Bid/Ask。mini板を新規入力にせず、実商品気配での損益保証と称さない。実運用の費用込み記録とは別表。"},
            "execution": {"method": "判断と同原行で約定しない。元S01足の公開遅延は維持。Eだけは当行までの原Lastで完了した1分バケットを逐次生成し、当分の未来closeや欠測補間を使わない。完了場の基準S01は155保存約定と全件照合。"},
            "data": {"sessions": [s["session"] for s in manifest["sessions"]], "input_manifests": inputs, "scope": "保存26完了Dayと2026-10-27 Day15:20未満の途中1場。合計702条件場。全て既知開発比較、当日の指摘を見てEを作ったので当日を未見と称さない。Nightは変更せず今回金融再生の対象外。"},
            "implementation": {bundle.relative_to(ROOT).as_posix(): reference(bundle)["sha256"]}
        }
    }
    path = HERE / "再生計画156.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    module_spec = importlib.util.spec_from_file_location("試行156管理", ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py")
    manager = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(manager)
    preflight = manager.analyzer().analyze(plan, [])
    assert preflight["proposal_complete"], preflight
    manager.validate({"rules": {"rules": []}, "knowledge": {"findings": []}, "trials": {"trials": [plan], "repetition_audit": []}, "studies": {"studies": []}}, deep=True)
    print("固定25案と基準の照合登録を開始します。", flush=True)
    record = manager.store_trial(plan)
    (HERE / "事前照合156.json").write_text(json.dumps(record["preflight"], ensure_ascii=False, indent=2), encoding="utf-8")
    receipt.write_text(json.dumps({"id": ID, "registered": True, "returncode": 0, "created_at": datetime.now().astimezone().isoformat(),
        "plan": reference(path), "implementation": reference(bundle), "sources": [reference(p) for p in files], "inputs": inputs}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("登録完了。指紋確認後だけ金融再生が可能です。", flush=True)


if __name__ == "__main__":
    main()
