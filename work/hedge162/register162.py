"""主玉とカバーの26条件を、実行前の照合と人工監査後に登録する。"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
IDENT = "162_主玉の逆行と短期カバーの連続運転"
MANIFEST = HERE / "inputs162.json"
SPEC = HERE / "計画162.md"
CONFIGS = HERE / "engine/configs162.json"
AUDIT = HERE / "audit/preflight162.json"
RECEIPT = HERE / "登録受領162.json"
FREEZE = HERE / "results/selection_frozen162.json"
RANKING = ["赤字場数の少ない順", "場収支25%点の高い順", "全場内の最悪時価収支の高い順", "全場収支合計の高い順", "ID昇順"]


def read(path: Path):
    """小さい資料と明示された成果を有限 JSON として読む。

    引数: path(Path)。返り値: dict 又は list。
    """
    result = json.loads(path.read_text(encoding="utf-8-sig"))
    json.dumps(result, allow_nan=False)
    return result


def sha(path: Path) -> str:
    """内容指紋を逐次計算する。

    引数: path(Path)。返り値: str は SHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def record(path: Path) -> dict:
    """根拠の相対パスと内容指紋を返す。

    引数: path(Path)。返り値: dict。
    """
    return {"path": path.resolve().relative_to(ROOT).as_posix(), "sha256": sha(path)}


def save(path: Path, value: dict) -> None:
    """新しい証跡を上書きせず保存する。

    引数: path(Path)、value(dict)。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def canonical(value: dict) -> str:
    """辞書の正規化指紋を返す。

    引数: value(dict)。返り値: str。
    """
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def manager_module():
    """管理器の関数だけを読み、巨大な試行正本を明示的に読まない。

    引数: なし。返り値: module。正本への登録は呼出側が明示する。
    """
    path = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    spec = importlib.util.spec_from_file_location("試行162管理", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_plan(bundle: dict, sources: list[dict]) -> dict:
    """登録する仕様と比較元を組み立てる。

    引数: bundle(dict)、sources(list[dict])。返り値: dict は登録計画。
    """
    manifest = read(MANIFEST)
    original = read(ROOT / "work/entry161/登録受領161.json")
    return dict(id=IDENT, name="主玉の逆行を短期の逆方向カバーで補う", purpose="新仮説",
        question="100円到達を待つ主玉に逆方向の段階追加と早いカバー退出を組み合わせ、全玉損失を減らせるか",
        change="既存50円先着標本を独立売買へ変換せず、全特徴の条件エッジから主玉とカバーを連続運転。買売各10枚を共有する26条件。",
        repeat_reason="00161の順序不問到達率と途中逆行を分けて検証。00067等の利益玉だけ回収する両建てとも入口・幅・共有上限・対象53場が異なる。旧全試行の不存在は断定しない。",
        compares_to=[original["id"]], spec={
            "entry": {"method": "固定R02/GL01/GL02と元モデルを全観測で評価。false→true、60秒判断間隔。将来ラベルと旧未決ロックは使わない。", "sources": sources},
            "management": {"method": "主の逆行中に中値アンカーから等間隔1枚カバー。固定段再交差又は返済後新基準。保有中も新主信号を評価し、反対方向の空き枠を許す。"},
            "exit": {"method": "主100円順行又は場末。S00だけ50円逆行停止。主返済時は親カバーも返済。カバーは利益起動又は即追尾、起動後0以下でも返済を拒まない。"},
            "allocation": {"method": "日経mini買10/売10、合計20可。主+逆玉+新規予約を方向別合算、返済未約定を空き枠にせず、他親へ干渉しない。"},
            "costs": {"fee": 0, "spread": "ラージの次正常Ask/Bidで約定代理、1円幅×1mini=100円。"},
            "execution": {"method": "全原行順。場末だけ既知タイマーで360秒内の最終正常BBO代理を許し、古ければ未解消停止。",
                          "selection": "前40場で赤字場数→収支25%点→最悪時価→合計→IDの固定順。cover24から3固定後に既知後13場の全26を確認。後半で再選択しない。"},
            "data": {"sessions": [s["session"] for s in manifest["sessions"]], "input_manifests": [record(MANIFEST)],
                     "scope": "既知53場。幅の記述はtrain30場だけ、戦略選択は前40場、既知後13場は追加確認。"},
            "implementation": {bundle["path"]: bundle["sha256"]}})


def schema_check(plan: dict) -> None:
    """小さい仮正本で必須schemaを検査する。

    引数: plan(dict)。返り値: None。巨大な正本のload/check/storeは呼ばない。
    """
    manager_module().validate({"rules": {"rules": []}, "knowledge": {"findings": []},
        "trials": {"trials": [plan], "repetition_audit": []}, "studies": {"studies": []}}, deep=False)


def assert_fingerprint(item: dict) -> None:
    """根拠パスと指紋の一致を確認する。

    引数: item(dict)。返り値: None。
    """
    path = (ROOT/item["path"]).resolve()
    assert path.is_relative_to(ROOT), item["path"]
    assert sha(path) == item["sha256"], item["path"]


def verify_receipt() -> dict:
    """登録成功と登録時の全源が不変であることを確認する。

    引数: なし。返り値: dict は登録受領。
    """
    receipt = read(RECEIPT)
    assert receipt.get("registered") is True and type(receipt.get("returncode")) is int and receipt["returncode"] == 0
    assert receipt["id"] == IDENT
    for item in receipt["sources"]+[receipt["implementation"], receipt["plan"], receipt["preflight"]]:
        assert_fingerprint(item)
    return receipt


def register() -> None:
    """最終人工監査済みの源を梱包し、管理器の内部照合結果付きで登録する。

    引数: なし。返り値: None。金融再生はしない。
    """
    assert not RECEIPT.exists(), "登録受領は上書きしない"
    assert not list((HERE/"results").glob("*/再生完了162_*.json")), "登録前の金融成果が存在する"
    audit = read(AUDIT)
    assert audit.get("passed") is True and audit.get("sources"), "最終人工監査が必要"
    for item in audit["sources"]:
        assert_fingerprint(item)
    manifest, configs = read(MANIFEST), read(CONFIGS)
    assert len(manifest["sessions"]) == 53
    assert CounterSplit(manifest) == {"train":30, "validation":10, "test":13}
    assert len(configs) == 26 and sum(bool(c["cover"]) for c in configs) == 24
    audited = {item["path"] for item in audit["sources"]}
    required = [*sorted((HERE/"engine").glob("*.py")), CONFIGS, SPEC, MANIFEST,
                *[HERE/name for name in ("register162.py", "allow162.py", "freeze162.py", "complete162.py")]]
    assert all(p.relative_to(ROOT).as_posix() in audited for p in required), "実装・ゲートの最終監査指紋が不足"
    # ----------------------------------------
    # 原板と金融結果は同梱せず、源・定義・人工監査・尺度根拠だけを固定する。
    files = [ROOT/x["path"] for x in audit["sources"]]
    files += [AUDIT, HERE/"prepare162.py"]
    files += [p for p in (HERE/"measure").iterdir() if p.is_file() and p.suffix in {".py", ".md", ".json"}]
    files += [ROOT/manifest["signal_source"]["path"]]
    files = sorted(set(files))
    bundle = HERE/"評価前実装162.zip"
    assert not bundle.exists()
    with zipfile.ZipFile(bundle, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    plan = build_plan(record(bundle), [record(p) for p in required if "engine" in p.parts])
    schema_check(plan)
    proposal = HERE/"評価計画162.json"
    save(proposal, plan)
    manager = manager_module()
    print("00162の26条件を内部照合付きで登録します。", flush=True)
    row = manager.store_trial(plan)
    # store_trial が実際に使用した照合を別ファイルへ残し、二重のcheck呼出しを避ける。
    check_path = HERE/"事前照合162.json"
    save(check_path, row["preflight"])
    save(RECEIPT, dict(id=IDENT, registered=True, returncode=0,
        created_at=datetime.now().astimezone().isoformat(), sources=[record(p) for p in files],
        implementation=record(bundle), plan=record(proposal), preflight=record(check_path),
        spec=record(SPEC), configs=record(CONFIGS), manifest=record(MANIFEST),
        new_strategy_replays=0, known_confirmation=True))
    print("登録完了。金融再生は実行していません。", flush=True)


def CounterSplit(manifest: dict) -> dict:
    """目録の区間ごとの場数を数える。

    引数: manifest(dict)。返り値: dict[str,int]。
    """
    return {key: sum(s["split"] == key for s in manifest["sessions"]) for key in ("train", "validation", "test")}


def main() -> None:
    """明示されたschema確認又は実登録だけを実行する。

    引数: CLI の --schema-check/--register。返り値: None。
    """
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--schema-check", action="store_true")
    mode.add_argument("--register", action="store_true")
    args = parser.parse_args()
    if args.schema_check:
        schema_check(build_plan(record(Path(__file__)), []))
        print("小さい仮正本のschema確認PASS。実登録0、金融再生0。")
    else:
        register()


if __name__ == "__main__":
    main()
