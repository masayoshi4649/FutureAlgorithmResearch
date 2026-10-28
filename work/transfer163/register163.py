"""元手法の局所減枚と復元10条件を、実行前の照合と人工監査後に登録する。"""
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
IDENT = "163r1_元手法への局所減枚と一度復元"
MANIFEST = HERE / "inputs163.json"
SPEC = HERE / "計画163.md"
CONFIGS = HERE / "engine/configs163.json"
AUDIT = HERE / "audit/preflight163_corrected1b.json"
RECEIPT = HERE / "登録受領163r1.json"
FREEZE = HERE / "results/selection_frozen163.json"
RANKING = ["赤字場数の少ない順", "場収支25%点の高い順", "全場内の最悪時価収支の高い順", "全場収支合計の高い順", "ID昇順"]
CONFIG_IDS = {"B00", "C50", "D40", "D80", "G40", "G80", "R40", "R80", "E40", "E80"}
CANDIDATE_IDS = CONFIG_IDS-{"B00", "C50"}


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
    spec = importlib.util.spec_from_file_location("試行163管理", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_plan(bundle: dict, sources: list[dict]) -> dict:
    """登録する仕様と比較元を組み立てる。

    引数: bundle(dict)、sources(list[dict])。返り値: dict は登録計画。
    """
    manifest = read(MANIFEST)
    original = read(ROOT / "work/hedge162/登録受領162.json")
    previous = read(HERE / "登録受領163.json")
    return dict(id=IDENT, name="有望だった元手法への局所的な減枚と一度だけの復元・金融前訂正1", purpose="不具合修正",
        question="元S01/P05+D07の入口と元出口を残し、逆行区間の一度減枚と回復時の一度復元で損失を減らせるか",
        change="訂正前163は金融未実施。同親のSource残量が0の間もRの不利極値を全正常原行で追う正式意図に合わせ、Ended分岐前へ極値更新を移す。他の10条件・Source・入力・順位は変更しない。",
        repeat_reason="旧登録の最終境界確認で、空玉期間を飛ばす実装と全正常原行を追う仕様の差を金融前に発見した。旧受領・ZIP・源・人工証跡を保持し、別IDとして修正1を登録する。00162で見た数量縮小の効果を元手法へ移す主仮説は同じ。",
        compares_to=[original["id"], previous["id"]], spec={
            "entry": {"method": "日中S01、夜間米国前P05・前後静観・後半D07の元Source通知を維持。旧先着ラベルとR02/GL入口は使わない。", "sources": sources},
            "management": {"method": "40/80円逆行、又は15秒−20円以下/5秒非正も確認して半量へ。一親の減枚/復元は各一回。縮小中のSource追加も半量。未知を弱支持としない。"},
            "exit": {"method": "元Sourceの返済を優先。復元は不利極値から40円回復又は初回中値回復と5/15秒正を確認し、現存するSource残量内だけ。新逆玉は使わない。"},
            "allocation": {"method": "micro100枚相当を片側上限にし、元Source/政策/所有IDを分離。初回はB00と同じ、C50のみ一律半量。返済未約定を空き枠にしない。"},
            "costs": {"fee": 0, "spread": "ラージの次正常Ask/Bidで約定代理、micro1枚の1円幅=10円、100micro=mini10枚相当。"},
            "execution": {"method": "元Sourceと同じ全原行順・時間枠。B00源同値とC50半量対照を検査し、独自減枚後の源返済量を現在残量へ写す。",
                          "selection": "前40場をDay/Night別に赤字場数→収支25%点→最悪時価→合計→IDで順位化、B00/C50を除く8案から各1を固定。後13場は全10、選び直さない。F00は固定昼夜の保存場行を連結し追加金融なし。",
                          "registration_correction": {"previous_unexecuted": record(HERE/"登録受領163.json"), "preserved_source": record(HERE/"評価前実装163.zip"), "evidence": record(HERE/"audit/訂正前版の凍結163.json"), "financial_replays_before_correction": 0}},
            "data": {"sessions": [s["session"] for s in manifest["sessions"]], "input_manifests": [record(MANIFEST)],
                     "scope": "既知53場30/10/13。比較候補の選択は前40場、既知後13場は追加確認であり未見実証ではない。"},
            "implementation": {bundle["path"]: bundle["sha256"]}})


def schema_check(plan: dict) -> None:
    """小さい仮正本で必須schemaを検査する。

    引数: plan(dict)。返り値: None。巨大な正本のload/check/storeは呼ばない。
    """
    manager = manager_module()
    manager.validate({"rules": {"rules": []}, "knowledge": {"findings": []},
        "trials": {"trials": [plan], "repetition_audit": []}, "studies": {"studies": []}}, deep=False)
    checked = manager.analyzer().analyze(plan, [])
    assert checked["proposal_complete"] is True, checked["提案不完全理由"]


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
    assert not list((HERE/"results").glob("*/再生完了163_*.json")), "登録前の金融成果が存在する"
    audit = read(AUDIT)
    assert audit.get("passed") is True and audit.get("sources"), "最終人工監査が必要"
    for item in audit["sources"]:
        assert_fingerprint(item)
    manifest, configs = read(MANIFEST), read(CONFIGS)
    assert len(manifest["sessions"]) == 53
    assert CounterSplit(manifest) == {"train":30, "validation":10, "test":13}
    assert len(configs) == 10 and {config_id(c) for c in configs} == CONFIG_IDS
    audited = {item["path"] for item in audit["sources"]}
    required = [*sorted(p for p in (HERE/"engine").rglob("*") if p.is_file() and (p.suffix in {".go", ".toml", ".json"} or p.name in {"go.mod", "go.sum"})), CONFIGS, SPEC, MANIFEST,
                *[HERE/name for name in ("register163.py", "allow163.py", "freeze163.py", "complete163.py")]]
    assert all(p.relative_to(ROOT).as_posix() in audited for p in required), "実装・ゲートの最終監査指紋が不足"
    # ----------------------------------------
    # 原板と金融結果は同梱せず、源・定義・人工監査・尺度根拠だけを固定する。
    files = [ROOT/x["path"] for x in audit["sources"]]
    files += [AUDIT, HERE/"prepare163.py", HERE/"audit/訂正前版の凍結163.json", HERE/"登録受領163.json", HERE/"audit/preflight163.json", HERE/"audit/登録失敗163r1.json", HERE/"audit/登録失敗163r1_register.py"]
    files += [p for p in (HERE/"design").iterdir() if p.is_file() and p.suffix in {".py", ".md", ".json"}]
    files = sorted(set(files))
    bundle = HERE/"評価前実装163r1_checked.zip"
    assert not bundle.exists()
    with zipfile.ZipFile(bundle, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    plan = build_plan(record(bundle), [record(p) for p in required if "engine" in p.parts])
    schema_check(plan)
    proposal = HERE/"評価計画163r1_checked.json"
    save(proposal, plan)
    manager = manager_module()
    print("00163の10条件を内部照合付きで登録します。", flush=True)
    row = manager.store_trial(plan)
    # store_trial が実際に使用した照合を別ファイルへ残し、二重のcheck呼出しを避ける。
    check_path = HERE/"事前照合163r1.json"
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


def config_id(config: dict) -> str:
    """JSONの定義識別子を取得し、大小表記の矛盾を拒否する。

    引数: config(dict)。返り値: str。
    """
    value = config.get("id", config.get("ID"))
    assert isinstance(value, str) and value
    assert "id" not in config or "ID" not in config or config["id"] == config["ID"]
    return value


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
        schema_check(build_plan(record(Path(__file__)), [record(HERE/"engine/transfer163.go")]))
        print("小さい仮正本のschema確認PASS。実登録0、金融再生0。")
    else:
        register()


if __name__ == "__main__":
    main()
