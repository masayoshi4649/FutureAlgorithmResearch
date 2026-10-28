"""P05移植の同値確認を、保存原板の再生前に照合・登録する。"""

import hashlib
import importlib.util
import json
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SESSIONS = ["2026-09-30_Night", "2026-10-01_Night", "2026-10-21_Night"]
TRIAL_ID = "152_P05運用移植の原板同値確認"


def reference(path):
    """既存ファイルを内容指紋で固定する。

    引数: path(Path)。返り値: dictはプロジェクト相対パス・SHA256・サイズ。
    """
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha, "bytes": path.stat().st_size}


def main():
    """移植コードと既存資料を固定し、試行照合へ登録する。

    引数: なし。返り値: None。金融再生は行わない。
    """
    receipt = HERE / "登録受領152.json"
    assert not receipt.exists(), "受領済みの再登録は禁止"
    engine = HERE / "engine_go"
    assert (engine / "main.go").exists() and (engine / "internal/strategy/p05.go").exists()
    sources = sorted(p for p in engine.rglob("*") if p.is_file() and (p.suffix in (".go", ".toml") or p.name in ("go.mod", "go.sum")))
    manifest_path = ROOT / "work/preus149/data/原資料一覧149.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected = [s for s in manifest["sessions"] if s["session"] in SESSIONS]
    assert len(selected) == 3
    for scene in selected:
        for original in scene["fingerprints"]:
            path = Path(original["path"])
            with path.open("rb") as stream:
                sha = hashlib.file_digest(stream, "sha256").hexdigest()
            assert sha == original["sha256"], str(path)
    references = [reference(manifest_path)]
    for session in SESSIONS:
        references.append(reference(ROOT / "work/preus150/results_round2" / (session + ".json")))
        references.append(reference(ROOT / "work/hedge151/results_go" / (session + ".json")))
    inputs_path = HERE / "入力指紋152.json"
    inputs_path.write_text(json.dumps({"references": references, "sessions": selected}, ensure_ascii=False, indent=2), encoding="utf-8")
    implementation = HERE / "再生前実装152.zip"
    with zipfile.ZipFile(implementation, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sources:
            archive.write(path, path.relative_to(HERE).as_posix())
    source_refs = [reference(p) for p in sources]
    # ----------------------------------------
    plan = {
        "id": TRIAL_ID,
        "name": "P05の運用実装を保存済みB04通知・P05会計へ照合",
        "purpose": "独立再検証",
        "question": "独立した仮想B04と実玉を分けたGo移植は研究P05の判断・約定を再現するか",
        "change": "SessionTraderへP05専用Portfolio・Expr条件・実約定別追尾を移植。アプリの場別表示とCSV履歴も別の人工試験で確認。",
        "repeat_reason": "新たな収益探索ではない。00151保存結果を期待値として使い、代表3夜の原板から入口を再構成して運用コードの同値を確認する。",
        "compares_to": ["151_損切りなし両建てと利益玉トレーリング", "150_第二巡_主担当の近隣しきい値と浅い押戻り"],
        "spec": {
            "entry": {"method": "独立したB04仮想運転のnew通知のみを利用。主担当効率.25、押戻り.40R、戻り.125R、17時解禁。実利確で陰の入口状態を変更しない。期待約定を入口の入力にしない。"},
            "management": {"method": "実約定別に建値・最高利益を保存し、買売片側上限は保有＋未約定新規。仮想B04は費用0・次正常ラージ板で進める。"},
            "exit": {"method": "実玉の価格損切りなし。返済側価格で利益40pt到達後、最高利益から10pt戻りかつ現在利益>0で返済。US15分前全返済。今回は前半P05の同値だけ、後半D07は既存実装。"},
            "allocation": {"product": "NK225mini", "cap_per_side": 10, "point_value": 100, "method": "B04通知数量をそのまま採用、予約込み片側10枚上限。"},
            "costs": {"fee": 0, "spread": "研究と同じ次正常ラージBBO。実アプリの商品気配約定と同一とは称さない。"},
            "execution": {"method": "通知の次の正常原行で新規・返済。原行・判断時刻・売買方向・枚数・価格・玉所属を保存会計と照合。人工試験で取消・部分約定・遅延境界約定を別検査。"},
            "data": {"sessions": SESSIONS, "input_manifests": [reference(inputs_path)], "scope": "既知3夜の移植確認。未見成績・有効性の新証拠には数えない。現在API取得0。"},
            "implementation": {implementation.relative_to(ROOT).as_posix(): reference(implementation)["sha256"]},
        },
    }
    plan_path = HERE / "再生計画152.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    manager_path = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    spec = importlib.util.spec_from_file_location("移植試行管理152", manager_path)
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    preflight = manager.analyzer().analyze(plan, [])
    assert preflight["proposal_complete"], preflight
    print("実装と原資料を固定。既試行と照合・登録中。", flush=True)
    record = manager.store_trial(plan)
    (HERE / "事前照合152.json").write_text(json.dumps(record["preflight"], ensure_ascii=False, indent=2), encoding="utf-8")
    receipt.write_text(json.dumps({"id": TRIAL_ID, "registered": True, "returncode": 0,
        "created_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
        "plan": reference(plan_path), "implementation": reference(implementation), "inputs": reference(inputs_path), "sources": source_refs,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("登録完了。固定指紋の照合後に3夜を再生可能。", flush=True)


if __name__ == "__main__":
    main()
