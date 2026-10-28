"""S01の実アプリ移植を、固定研究との独立照合前に登録する。"""
import hashlib
import importlib.util
import json
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
APP = ROOT / "App/SessionTrader"
ID = "155_S01の日中運用移植と全通知独立同値照合"


def reference(path):
    """固定ファイルの相対位置と内容指紋を返す。

    引数: path(Path)はプロジェクト内の既存ファイル。
    返り値: dictは相対パス、SHA256、バイト数。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest, "bytes": path.stat().st_size}


def main():
    """実装・固定入力・比較仕様を照合台帳へ事前登録する。

    引数: なし。返り値: None。
    金融再生、原資料取得、実注文、稼働環境の変更は行わない。
    """
    receipt = HERE / "登録受領155.json"
    assert not receipt.exists(), "登録受領の上書きは禁止"
    spec_path, manifest_path = HERE / "spec155.json", HERE / "inputs155.json"
    specification = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    assert reference(manifest_path)["sha256"] == "d30747d798397efd31b4ce73c9a9cf0a4519346946c331889037ce724b691b90"
    files = [p for p in (HERE / "replay_go").rglob("*") if p.is_file() and (p.suffix in (".go", ".toml") or p.name in ("go.mod", "go.sum"))]
    files += [p for folder in ("internal", "cmd", "conf") for p in (APP / folder).rglob("*") if p.is_file() and p.suffix in (".go", ".toml")]
    files += [APP / "go.mod", APP / "go.sum", APP / "main.go", APP / "web-conf/settings.toml.sample"]
    files += [spec_path, manifest_path, HERE / "spec155.md", HERE / "独立監査指紋155.json", Path(__file__).resolve()]
    files = sorted(set(files))
    assert len(files) > 150
    bundle = HERE / "再生前実装155.zip"
    assert not bundle.exists()
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    sources = [reference(p) for p in files]
    inputs = [reference(manifest_path)]
    plan = {
        "id": ID, "name": "S01の実アプリ移植と全通知・約定の独立照合", "purpose": "独立再検証",
        "question": "S01のDay実装が研究154の逐次判断・次原行約定・親利益床・再参加抑止を保持し、変更しないD07のDay/Nightも同値か",
        "change": "研究用S01を実AppのNK225_S01へ移植。Day標準とし、部分約定q0確定、鮮度、注文所有、保存復元、外部Expr異常停止を実運転へ接続。Nightは既存P05/静観/D07を保持。新パラメータ探索はしない。",
        "repeat_reason": "ユーザーのS01をベースにしたプログラムへの変更依頼に対応。研究保存結果の再利用だけでは実Appの売買同値を確認できないため、凍結入力を独立照合する。新たな収益性の証拠へ加算しない。",
        "compares_to": ["154_D07の利益返しと担当別数量の改善", "154_第二巡_利益回収後の再参加と遅い大口新規の限定"],
        "spec": {
            "entry": {"method": "D07の基本・追加・別入口を維持。S01は別入口で独立D07が異なる親を保有又は予約中なら新親を拒否。拒否親を後追い採用しない。", "fixed_plan": specification},
            "management": {"method": "前行以前の独立影予約を次正常板で約定させ、当行影判断後に実判断。実別入口の親粗実現＋返済側含みを管理し、追加や部分返済で初回R・q0・最高益を再初期化しない。未来終了時刻を入力しない。"},
            "exit": {"method": "初回固定R×初回確定実数量×倍率の0.5で保護を起動し、最高親利益の50%床を単調維持。元退出優先・全返済時追加なし。途中場の架空清算なし。ライブ鮮度と部分約定の拡張は別人工で確認。"},
            "allocation": {"product": "NK225mini", "point_value": 100, "max_per_side": 10, "role_caps": {"core": 5, "addon": 3, "episode": 2}, "method": "研究時と同じ5/3/2。実玉＋未約定枠を独立検算。"},
            "costs": {"fee": 0, "spread": "次正常NK225ラージBBOの買ask/売bid。実アプリの手数料記録と混同しない。"},
            "execution": {"method": "全保存板の時系列と同時刻行順、154の確定足公開遅延を維持。判断と同原行で約定させず次正常自己原行で全量約定。期待結果は比較器だけが持ち判断へ渡さない。"},
            "data": {"sessions": [s["session"] for s in manifest["sessions"]], "input_manifests": inputs, "scope": "既知52資料（Day26完了/Night25完了/10月27日Day12:08未満）。D07全52＋S01 Day27の79条件場。研究154の固定原資料のみ。未見資料追加・現API再取得なし。"},
            "implementation": {bundle.relative_to(ROOT).as_posix(): reference(bundle)["sha256"]}
        }
    }
    plan_path = HERE / "再生計画155.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    manager_path = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    module_spec = importlib.util.spec_from_file_location("試行155管理", manager_path)
    manager = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(manager)
    preflight = manager.analyzer().analyze(plan, [])
    assert preflight["proposal_complete"], preflight
    manager.validate({"rules": {"rules": []}, "knowledge": {"findings": []}, "trials": {"trials": [plan], "repetition_audit": []}, "studies": {"studies": []}}, deep=True)
    print("実装・入力固定済み。既存照合台帳へ登録します。", flush=True)
    record = manager.store_trial(plan)
    (HERE / "事前照合155.json").write_text(json.dumps(record["preflight"], ensure_ascii=False, indent=2), encoding="utf-8")
    receipt.write_text(json.dumps({"id": ID, "registered": True, "returncode": 0,
        "created_at": datetime.now(timezone(timedelta(hours=9))).isoformat(), "plan": reference(plan_path),
        "implementation": reference(bundle), "sources": sources, "inputs": inputs}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("登録完了。固定指紋照合後に79条件場の独立照合を実行できます。", flush=True)


if __name__ == "__main__":
    main()
