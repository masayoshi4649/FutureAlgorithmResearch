"""初巡の損失原因に対応する8条件を、追加金融再生より先に登録する。"""

import hashlib
import importlib.util
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ROUND = HERE / "round2"
TRIAL_ID = "153_第二巡_冷却後再参加と利益中の追撃"


def reference(path):
    """既存資料を内容指紋で示す。

    引数: path(Path)。返り値: dictは相対位置・サイズ・SHA256。
    """
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha, "bytes": path.stat().st_size}


def main():
    """第二巡の仕様と原因資料を固定して照合登録する。

    引数: なし。返り値: None。新たな金融再生は行わない。
    """
    receipt = ROUND / "登録受領153r2.json"
    assert not receipt.exists()
    configs_path = ROUND / "configs153r2.json"
    configs = json.loads(configs_path.read_text(encoding="utf-8-sig"))
    assert len(configs) == 8 and {c["id"] for c in configs} == {f"R{i:02d}" for i in range(1, 9)}
    manifest_path = HERE / "data/入力目録153.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = sorted(p for p in (ROUND / "engine_go").rglob("*") if p.is_file() and (p.suffix == ".go" or p.name in ("go.mod", "go.sum")))
    sources += [configs_path, ROUND / "spec153r2.md"]
    archive_path = ROUND / "再生前実装153r2.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in sources:
            archive.write(source, source.relative_to(ROUND).as_posix())
    first = json.loads((HERE / "再生計画153.json").read_text(encoding="utf-8"))
    spec = dict(first["spec"])
    spec.update(
        entry={"configurations": configs, "method": "3分Dと10分Tの基準に4案ずつ。全案、同方向への再参加はその方向の傾きが0.125bp/分以下へ一度冷えてから再び0.25以上となることを要求。初期は両方向準備可、新規判断で当方向解除、全返済実約定で再度解除、返済後の別原行で冷却を観測。第2案以降は現在中値が予定方向でMAより先、60/30短期傾きも同方向の新規だけ。"},
        management={"method": "各基準の第1/2案は初回比例枚数、第3案は従来の動的増減、第4案は枚数差2枚以上の増減。第4案の追加は初回基準の返済側含みが正、かつ直前新規/追加実約定値から返済側価格が現在気配差以上順行した場合だけ。縮小に含み益条件は課さない。未知は追加しない。親固定基準・上限・FIFO・次正常板は初巡のまま。"},
        allocation={"products": {"NK225mini": {"cap": 10, "point_value": 100}, "TOPIXmini": {"cap": 10, "point_value": 1000}}, "method": "初巡と同じ0.25→1枚、2.5→10枚。R03/R07は通常の動的比例、R04/R08は利益中の進行確認と2枚差だけを追加。数量が減っただけの金額縮小を方向予測の改善とは呼ばない。"},
        implementation={archive_path.relative_to(ROOT).as_posix(): reference(archive_path)["sha256"]},
    )
    spec["data"] = dict(spec["data"], scope="初巡と同じ既知51完了場＋途中1場。損失を見て修正した開発比較。初巡の金融再生を繰り返さず保存結果を比較元にする。現在API取得0。")
    proposal = {
        "id": TRIAL_ID, "name": "古い傾きでの再入場と値動きに負ける追加を抑える8条件",
        "purpose": "条件比較",
        "question": "同じ入口角度でも再参加を新しい冷却後に限定し、現在方向確認と利益中の追加を加えると、気配差の反復と遅い追加による損失が減るか",
        "change": "3分D/10分Tで、冷却後再参加、現在価格/短期傾きとの整合、途中比例増減、利益中だけ追加かつ2枚差を段階比較する。",
        "repeat_reason": "初巡では日経F01が1場平均約244新規、約113秒保有で−1946.7万円。中値方向−85.8万円に対し気配差1860.9万円。M09→M12は追加玉の−5656.1万円が縮小による改善を上回った。原因へ対応する状態条件を先に固定して全場で再検証する。",
        "compares_to": ["153_移動平均の傾きと比例枚数の独立比較"],
        "evidence": [reference(HERE / "report153.json"), reference(HERE / "loss_decomposition153.json")],
        "spec": spec,
    }
    plan_path = ROUND / "再生計画153r2.json"
    plan_path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2), encoding="utf-8")
    manager_path = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    module_spec = importlib.util.spec_from_file_location("研究153追加の試行管理", manager_path)
    manager = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(manager)
    preflight = manager.analyzer().analyze(proposal, [])
    assert preflight["proposal_complete"], preflight
    focused = {"rules": {"rules": []}, "knowledge": {"findings": []}, "trials": {"trials": [proposal], "repetition_audit": []}, "studies": {"studies": []}}
    manager.validate(focused, deep=True)
    print("第二巡8条件を固定。既試行へ照合登録中。", flush=True)
    result = manager.store_trial(proposal)
    (ROUND / "事前照合153r2.json").write_text(json.dumps(result["preflight"], ensure_ascii=False, indent=2), encoding="utf-8")
    receipt.write_text(json.dumps({"id": TRIAL_ID, "registered": True, "returncode": 0,
        "created_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
        "plan": reference(plan_path), "implementation": reference(archive_path),
        "inputs": spec["data"]["input_manifests"], "sources": [reference(p) for p in sources],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("第二巡登録完了。指紋一致確認後のみ再生可能。", flush=True)


if __name__ == "__main__":
    main()
