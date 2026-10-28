"""D07前半の閾値緩和を、金融再生の前に凍結・照合・登録する。"""

import hashlib
import importlib.util
import json
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREVIOUS = ROOT / "work/preus149"
TRIAL_ID = "150_D07米国前の閾値緩和と開始前リセット"


def digest(path):
    """既存ファイルの内容指紋を計算する。

    引数: path(Path)は対象。返り値: strはSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def reference(path):
    """プロジェクト内の資料を相対パスと指紋で示す。

    引数: path(Path)は既存ファイル。返り値: dictは参照情報。
    """
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path), "bytes": path.stat().st_size}


def main():
    """全17条件と実装を先に固定し、既存試行と照合して登録する。

    引数: なし。返り値: None。登録成功後だけ受領JSONを保存する。
    """
    receipt = HERE / "登録受領150.json"
    assert not receipt.exists(), "同じ登録を繰り返さない"
    configs = json.loads((HERE / "configs150.json").read_text(encoding="utf-8-sig"))
    assert len(configs) == 17 and {c["id"] for c in configs} == {f"A{i:02d}" for i in range(17)}
    source_manifest = PREVIOUS / "data/原資料一覧149.json"
    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    engine = HERE / "engine_go"
    sources = sorted(p for p in engine.rglob("*") if p.is_file() and (p.suffix in (".go", ".toml") or p.name in ("go.mod", "go.sum")))
    sources += [HERE / "configs150.json", HERE / "engine仕様150.md"]
    assert sources and len(sources) > 20
    frozen = HERE / "再生前実装150.zip"
    with zipfile.ZipFile(frozen, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sources:
            archive.write(path, path.relative_to(HERE).as_posix())
    # ----------------------------------------
    plan = {
        "id": TRIAL_ID,
        "name": "D07の米国前だけ閾値を緩め、米国前全返済・後半新規状態で運転する17対照",
        "purpose": "条件比較",
        "question": "価格・板の正常性を維持したままD07前半の入口閾値と再参加を緩めれば、実参加を増やし前半と全夜の収支・赤字頻度を改善できるか",
        "change": "A00は主担当通常入口を17時解禁しZ04補完はUS+30のまま。A01〜14は前半の閾値・数量・出口を個別変更し、A15/16は事前固定の組合せ。後半は全条件で149 S04の指標保持・新Portfolioへ揃える。",
        "repeat_reason": "149は時計と指標初期化を比較したがD07自体の前半閾値を緩めていない。補完17時化による強制参加を閾値緩和と混同せず、主担当の通常入口から検証する。",
        "compares_to": ["149_米国前の時刻制限と米国後の全初期化", "149_第二巡_指標履歴と後半準備時計の分離"],
        "spec": {
            "entry": {"method": "前半の主担当効率・確認・突破進行・押戻り・再反発、追加担当の型選択・反発・確認を個別に変更。相手時計・価格品質・必要特徴数は緩めない。", "configurations": [dict(c, owners=c.get("owners") or "全担当") for c in configs]},
            "management": {"method": "前半だけ再参加確認・追撃進行・初回数量・追尾幅を比較。全条件US15分前に自己玉全返済し、完済後USから新しい売買状態・予算へ。特徴履歴は維持し前半損失も会計に残す。後半は主担当22分/補完30分時計でS04と全注文同値を検査。"},
            "exit": {"method": "D07出口を基準。A14/A16だけ前半追加担当の利益追尾幅を変更。US15分前と場末は利益損失を問わず返済、約定は判断次正常原板。途中資料の末尾精算はせず含みを別表示。"},
            "allocation": {"product": "NK225mini", "cap": 10, "point_value": 100, "method": "主担当5・追加3・独立2の上限を固定、余枠は貸さない。A13の追加初回1枚だけ別対照。数量の減少を方向予測改善や積極性向上と呼ばない。"},
            "costs": {"fee": 0, "spread": "ラージ買ask/売bid。気配差は計上、mini実約定保証ではない。"},
            "execution": {"method": "各市場の原順序を保ち価格時計で安定結合、判断の次正常日経原行で約定。既に送信判断した成行新規は境界後でも消さず、約定後に返済判断し次正常行で返す。正常性未成立中は後半新規禁止。確定足の公開時刻を守る。", "clock": "保存CurrentPriceTime順。独立した受信時計を捏造しない。", "baseline": "現Goに揃えた149 C00/S04/S02を保存対照として再利用し重複再生しない。"},
            "data": {"sessions": [s["session"] for s in manifest["sessions"]], "input_manifests": [reference(source_manifest)], "range": "既知25夜と10/26 21:13:52未満の保存途中資料を分離。新API取得なし。朝09:00とUS寄付の急変診断は売買入力に使わない。"},
            "implementation": {frozen.relative_to(ROOT).as_posix(): digest(frozen)},
        },
    }
    plan_path = HERE / "再生計画150.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    refs = [reference(p) for p in sources]
    (HERE / "凍結ソース150.json").write_text(json.dumps(refs, ensure_ascii=False, indent=2), encoding="utf-8")
    # ----------------------------------------
    manager_path = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    spec = importlib.util.spec_from_file_location("研究150試行管理", manager_path)
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    assert manager.analyzer().analyze(plan, [])["proposal_complete"]
    print("17条件と実装を凍結。既存試行との照合・登録を開始。", flush=True)
    record = manager.store_trial(plan)
    (HERE / "事前照合150.json").write_text(json.dumps(record["preflight"], ensure_ascii=False, indent=2), encoding="utf-8")
    receipt.write_text(json.dumps({"id": TRIAL_ID, "registered": True, "returncode": 0,
        "created_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
        "plan": reference(plan_path), "implementation": reference(frozen), "inputs": reference(source_manifest), "sources": refs}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("登録完了。指紋確認後にのみ金融再生可能。", flush=True)


if __name__ == "__main__":
    main()
