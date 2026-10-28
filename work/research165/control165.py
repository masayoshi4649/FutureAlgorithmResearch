"""米国後の固定14手法を登録し、前20夜の選択と後7夜の確認を分ける。"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import statistics
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
IDENT = "165_米国開始後の板追随と損失安定化"
MANIFEST = HERE / "inputs165.json"
BASELINE = HERE / "baseline165.json"
CONFIGS = HERE / "night_engine/configs165.json"
SPEC = HERE / "計画165.md"
PREFLIGHT = HERE / "audit/preflight165.json"
RECEIPT = HERE / "登録受領165.json"
FREEZE = HERE / "results/selection_frozen165.json"
IDS = {f"NK225_U165_{i:02d}" for i in range(1, 15)}
CONTROLS = {"NK225_U165_01", "NK225_U165_12"}
RANKING = ["累計黒字を優先", "無取引0を優先", "上位3場除外黒字を優先", "赤字場数の少ない順",
    "全場の悪い側25%の平均損失の小さい順", "平均赤字の小さい順", "場内最悪赤字の小さい順", "累計の高い順", "ID順"]


def read(path: Path):
    """JSONを有限値の構造として読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    json.dumps(value, allow_nan=False)
    return value


def sha(path: Path) -> str:
    """逐次読みでファイルの内容指紋を計算する。

    引数: path(Path)。返り値: str。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value) -> str:
    """キー順に依存しない構造の指紋を計算する。

    引数: value(dict又はlist)。返り値: str。
    """
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def record(path: Path) -> dict:
    """ルート相対の根拠パスと内容指紋を返す。

    引数: path(Path)。返り値: dict[str,str]。
    """
    return dict(path=path.resolve().relative_to(ROOT).as_posix(), sha256=sha(path))


def verify(source: dict) -> None:
    """根拠の内容が固定時点から変わっていないことを確認する。

    引数: source(dict)。返り値: None。
    """
    path = Path(source["path"])
    if not path.is_absolute():
        path = ROOT / path
    assert sha(path) == source["sha256"], str(path)


def save(path: Path, value) -> None:
    """証跡を新規作成し、既存の内容を上書きしない。

    引数: path(Path)、value(dict又はlist)。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def module(path: Path, name: str):
    """管理関数を読み込み、巨大台帳はここでは開かない。

    引数: path(Path)、name(str)。返り値: module。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def configs() -> list[dict]:
    """14個の固有IDと対象区間を確認する。

    引数: なし。返り値: list[dict]。
    """
    values = read(CONFIGS)
    assert len(values) == len(IDS) and {v["id"] for v in values} == IDS
    assert all(v["scope"] == "PostUS" and len(v["rule_hash"]) == 64 for v in values)
    return values


def scenes_for_stage(stage: str) -> dict[str, dict]:
    """27夜の一意性と前20・後7の時系列分離を検査する。

    引数: stage(str)。返り値: 場名から入力への辞書(dict[str,dict])。
    """
    assert stage in ("train_validation", "confirmation")
    scenes = read(MANIFEST)["sessions"]
    assert len(scenes) == 27 and len({s["session"] for s in scenes}) == 27
    assert all(s["kind"] == "Night" and not s["partial"] for s in scenes)
    assert all(a["start"] < b["start"] for a,b in zip(scenes,scenes[1:]))
    assert all(s["split"] in ("train","validation") for s in scenes[:20])
    assert all(s["split"] in ("test","extra") for s in scenes[20:])
    chosen = scenes[:20] if stage == "train_validation" else scenes[20:]
    return {s["session"]:s for s in chosen}


def baseline_scene_matches(old: dict, current: dict) -> bool:
    """旧保存基準の入力を時計・原資料指紋で照合する。

    引数: old/current(dict)。返り値: bool。追加された監査メタデータは経済入力と分ける。
    """
    keys = ("session","kind","start","us_open","force_close","end","cutoff","partial","books","candles","split")
    return all(old[k] == current[k] for k in keys) and \
        {x["path"]:x["sha256"] for x in old["fingerprints"]} == \
        {x["path"]:x["sha256"] for x in current["fingerprints"]}


def verify_receipt() -> dict:
    """実行前の登録と実装・入力・条件の不変性を確認する。

    引数: なし。返り値: dict。
    """
    receipt = read(RECEIPT)
    assert receipt["registered"] and receipt["returncode"] == 0 and receipt["id"] == IDENT
    for source in receipt["sources"] + [receipt["implementation"], receipt["plan"], receipt["preflight"]]:
        verify(source)
    return receipt


def row_from_case(scene: dict, case: dict) -> dict:
    """実返済配賦を集計し、1夜の損益と場内リスクを返す。

    引数: scene(dict)、case(dict)。返り値: dict。影会計は集計しない。
    """
    ledger = case["actual"]
    assert not ledger["Pending"] and all(l["Remaining"] == 0 for l in ledger["Lots"].values())
    pieces = [p for event in ledger["Events"] for p in (event["Pieces"] or [])]
    profit = sum(max(0, p["Gross"]) for p in pieces)
    loss = sum(max(0, -p["Gross"]) for p in pieces)
    assert math.isclose(profit - loss, ledger["Realized"], abs_tol=1e-7)
    risk = ledger["Risk"]
    assert risk["MaxLong"] <= 100 and risk["MaxShort"] <= 100
    new_events = [e for e in ledger["Events"] if e["HoldID"]]
    return dict(session=scene["session"], split=scene["split"], profit=profit, loss=loss, net=profit-loss,
        minimum_equity=risk["Minimum"], maximum_dd=risk["MaxDD"], new_orders=len(new_events),
        closed_micro=sum(p["Quantity"] for p in pieces), held_seconds=risk["HeldSeconds"],
        gross_seconds=risk["GrossSeconds"], source_scope="PostUS")


def summary(rows: list[dict]) -> dict:
    """数量対照と比較可能な場別安定指標を計算する。

    引数: rows(list[dict])。返り値: dict。下位25%は全場のceil(n/4)場。
    """
    assert rows
    values = [r["net"] for r in rows]
    losses = [-v for v in values if v < 0]
    bad = sorted(values)[:math.ceil(len(values)/4)]
    profit, loss = sum(r["profit"] for r in rows), sum(r["loss"] for r in rows)
    closed = sum(r["closed_micro"] for r in rows)
    return dict(sessions=len(rows), profit=profit, loss=loss, net=sum(values), negative_sessions=len(losses),
        no_entries=sum(r["new_orders"] == 0 for r in rows), mean_loss=statistics.mean(losses) if losses else 0,
        median_loss=statistics.median(losses) if losses else 0, maximum_loss=max(losses, default=0),
        worst_quarter_loss=statistics.mean(max(0, -v) for v in bad),
        worst_quarter_mean=statistics.mean(bad), excluding_top3=sum(values)-sum(sorted(values, reverse=True)[:3]),
        minimum_equity=min(r["minimum_equity"] for r in rows), maximum_dd=max(r["maximum_dd"] for r in rows),
        loss_share=loss/(profit+loss) if profit+loss else None,
        net_per_closed_micro_point=sum(values)/(closed*10) if closed else None,
        closed_micro=closed, new_orders=sum(r["new_orders"] for r in rows))


def rank(methods: list[dict]) -> list[dict]:
    """数量対照を別扱いにして事前指定の安定性順へ並べる。

    引数: methods(list[dict])はidとsummaryを持つ。返り値: list[dict]。
    """
    def key(item: dict):
        """候補一つの比較キーを返す。

        引数: item(dict)。返り値: tuple。
        """
        s = item["summary"]
        return (s["net"] <= 0, s["no_entries"] != 0, s["excluding_top3"] <= 0,
                s["negative_sessions"], s["worst_quarter_loss"], s["mean_loss"],
                abs(min(0, s["minimum_equity"])), -s["net"], item["id"])
    return sorted([m for m in methods if m["id"] not in CONTROLS], key=key)


def eligible(method: dict) -> bool:
    """比較候補の最低資格を判定し、順位と採用を混同しない。

    引数: method(dict)はsummaryを持つ。返り値: bool。
    """
    s = method["summary"]
    return s["net"] > 0 and s["no_entries"] == 0 and s["excluding_top3"] > 0


def verified_freeze() -> dict:
    """凍結内容・順位・資格・全前半根拠の不変性を確認する。

    引数: なし。返り値: 凍結記録(dict)。後半結果は読まない。
    """
    fixed = read(FREEZE)
    assert not fixed["test_opened"] and fixed["selection_sessions"] == 20 and fixed["ranking_order"] == RANKING
    assert fixed["content_sha256"] == canonical({k:v for k,v in fixed.items() if k != "content_sha256"})
    for key, path in (("manifest_sha256",MANIFEST),("spec_sha256",SPEC),("configs_sha256",CONFIGS)):
        assert fixed[key] == sha(path)
    for source in fixed["results"]+[fixed["complete_proof"],fixed["selection_implementation"],fixed["baseline"]]:
        verify(source)
    comparisons = fixed["comparisons"]
    assert len(comparisons) == len(IDS)+1 and {c["id"] for c in comparisons} == IDS | {"NK225_U164_00"}
    assert all(c["summary"]["sessions"] == 20 for c in comparisons)
    ranking = rank(comparisons)
    assert fixed["ranking"] == ranking
    assert fixed["selected"] == {"PostUS":ranking[0]["id"]}
    assert fixed["shortlist"] == [c["id"] for c in ranking[:3]]
    assert fixed["quantity_controls"] == sorted(CONTROLS)
    assert fixed["selected_eligible"] == eligible(ranking[0])
    assert fixed["adoption_confirmed"] is False
    return fixed


def register() -> None:
    """人工検査済みの条件を共通の照合器へ渡して一括登録する。

    引数: なし。返り値: None。登録前に金融成果を作らない。
    """
    assert not RECEIPT.exists()
    assert not list((HERE / "results").glob("*/*.json"))
    definitions = configs()
    scenes_for_stage("train_validation")
    audit = read(PREFLIGHT)
    assert audit["passed"] and audit["new_financial_replays"] == 0
    for source in audit["sources"]:
        verify(source)
    sources = {ROOT / s["path"] for s in audit["sources"]}
    required = {MANIFEST, BASELINE, CONFIGS, SPEC, Path(__file__), HERE / "registry165.py"}
    required.update(p for p in (HERE / "night_engine").rglob("*") if p.is_file() and p.suffix in {".go", ".mod", ".sum", ".toml", ".json"})
    assert required <= sources, sorted(str(p) for p in required-sources)
    sources.add(PREFLIGHT)
    bundle = HERE / "再生前実装165.zip"
    with zipfile.ZipFile(bundle, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(sources):
            archive.write(path, path.relative_to(ROOT).as_posix())
    definition = record(CONFIGS)
    plan = dict(id=IDENT, name="米国開始後の国内板の価格帯移動と維持・失敗", purpose="条件比較",
        question="外部価格への追随を想定した国内板の状態判定で、黒字を保ちながら夜間損失を安定して減らせるか",
        change="同価格数量変化・両気配の移動・移動後の維持を原行順に判定し、初回/追加/残玉/初期逆行を分ける。14新IDと保存U00の比較。",
        repeat_reason="00099は同価格数量の消失/回復と新価格定着を旧32場・30分出口・1枚・費用ありで検証済み。本比較は米国開始後の既存保有管理、原行イベントと価格時計の区別、数量を加える効果を価格だけ対照から分離する条件比較。00164の一律浅い利益保護は勝ちを削り、短期窓は時計反復と尺度で無信号となった。全27夜は既知資料。",
        compares_to=["164_J02の日中改修と夜間独立手法", "164r2_待機増幅の抑制と元夜間入口の利益保護"],
        spec=dict(entry=dict(definitions=definition, method="元D07の失敗拒否/待機と、独立価格帯移動入口を別ID"),
            management=dict(definitions=definition, method="国内板の価格帯維持と反転を分ける。米国データは不使用"),
            exit=dict(definitions=definition, method="実玉の状態と次正常板。利益残玉限定保護、親一度半減、独立入口の対称出口"),
            allocation=dict(definitions=definition,max_per_side_micro=100,equivalent_mini=10,controls=sorted(CONTROLS)),
            costs=dict(fee=0,point_value_micro=10,execution="判断後次正常ラージAsk買い/Bid売り"),
            execution=dict(specification=record(SPEC),ranking=RANKING,selection="前20夜で固定し後7夜で再選択しない。既知開発。",us_market_data=False),
            data=dict(sessions=[s["session"] for s in read(MANIFEST)["sessions"]],input_manifests=[record(MANIFEST)],previous_results=[record(BASELINE)]),
            implementation={record(bundle)["path"]:sha(bundle),definition["path"]:definition["sha256"]}))
    save(HERE / "再生計画165.json", plan)
    registry = module(HERE / "registry165.py", "登録165")
    checked = registry.register_plan(plan)
    save(RECEIPT, dict(id=IDENT,registered=True,returncode=0,created_at=datetime.now().astimezone().isoformat(),
        sources=[record(p) for p in sorted(sources)],implementation=record(bundle),plan=record(HERE/"再生計画165.json"),
        preflight=checked,spec=record(SPEC),configs=record(CONFIGS),manifest=record(MANIFEST),new_financial_replays=0))
    print("14新手法の事前登録完了。金融再生は未実行です。", flush=True)


def allow(stage: str) -> None:
    """登録と固定順序を確認して指定段階の実行証跡を作る。

    引数: stage(str)。返り値: None。
    """
    verify_receipt()
    scenes_for_stage(stage)
    assert not list((HERE / "results" / stage).glob("*.json"))
    value = dict(registered=True,returncode=0,allowed_stages=[stage],manifest_sha256=sha(MANIFEST),
        spec_sha256=sha(SPEC),configs_sha256=sha(CONFIGS),registration=record(RECEIPT),known_confirmation=True)
    if stage == "confirmation":
        fixed = verified_freeze()
        value.update(freeze_sha256=sha(FREEZE),selected=fixed["selected"])
    save(HERE / (stage + "_許可165.json"), value)
    print("実行段階を固定: " + stage, flush=True)


def stage_results(stage: str) -> tuple[dict, list[dict]]:
    """完了記録・条件定義・入力・全ケースの会計を確認する。

    引数: stage(str)。返り値: tuple[dict,list[dict]]。
    """
    scenes = scenes_for_stage(stage)
    folder = HERE / "results" / stage
    proof = read(folder / ("再生完了165_" + stage + ".json"))
    expected = 20 if stage == "train_validation" else 7
    assert proof["completed"] and proof["returncode"] == 0 and proof["sources_unchanged"]
    assert proof["sessions"] == expected and proof["cases"] == expected*len(IDS)
    assert proof["stage"]["stage"] == stage
    for key, path in (("manifest_sha256",MANIFEST), ("spec_sha256",SPEC), ("configs_sha256",CONFIGS)):
        assert proof["stage"][key] == sha(path)
    definitions = {c["id"]:c for c in configs()}
    result = []
    assert len(proof["results"]) == expected
    for source in proof["results"]:
        verify(source)
        path = Path(source["path"])
        saved = read(path if path.is_absolute() else ROOT/path)
        assert saved["scene"] == scenes[source["session"]]
        assert len(saved["cases"]) == len(IDS) and {c["config"]["id"] for c in saved["cases"]} == IDS
        for case in saved["cases"]:
            assert case["config"] == definitions[case["config"]["id"]]
            row_from_case(saved["scene"], case)
        result.append(saved)
    assert {s["scene"]["session"] for s in result} == set(scenes)
    return proof, result


def freeze() -> None:
    """前20夜の成績だけで比較候補を固定する。

    引数: なし。返り値: None。後7夜の金融結果は読まない。
    """
    verify_receipt()
    assert not FREEZE.exists() and not list((HERE / "results/confirmation").glob("*.json"))
    proof, results = stage_results("train_validation")
    expected_scenes = scenes_for_stage("train_validation")
    groups = {name:[] for name in IDS | {"NK225_U164_00"}}
    for saved in results:
        for case in saved["cases"]:
            groups[case["config"]["id"]].append(row_from_case(saved["scene"],case))
    baseline_scenes = []
    for item in read(BASELINE)["cases"]:
        if item["scene"]["split"] in ("train","validation"):
            name = item["scene"]["session"]
            assert baseline_scene_matches(item["scene"],expected_scenes[name])
            assert item["case"]["config"]["id"] == "NK225_U164_00"
            baseline_scenes.append(name)
            groups["NK225_U164_00"].append(row_from_case(item["scene"],item["case"]))
    assert len(baseline_scenes) == 20 and set(baseline_scenes) == set(expected_scenes)
    comparisons = [dict(id=name,summary=summary(rows)) for name,rows in sorted(groups.items())]
    assert all(c["summary"]["sessions"] == 20 for c in comparisons)
    ranking = rank(comparisons)
    value = dict(selected={"PostUS":ranking[0]["id"]},shortlist=[c["id"] for c in ranking[:3]],
        selected_eligible=eligible(ranking[0]),adoption_confirmed=False,
        selection_note="比較上位の固定であり採用確定ではない。最低資格を満たさない場合も比較対象として保持する。",
        ranking=ranking,comparisons=comparisons,quantity_controls=sorted(CONTROLS),ranking_order=RANKING,
        test_opened=False,selection_sessions=20,manifest_sha256=sha(MANIFEST),spec_sha256=sha(SPEC),configs_sha256=sha(CONFIGS),
        results=proof["results"],complete_proof=record(HERE/"results/train_validation/再生完了165_train_validation.json"),
        selection_implementation=record(Path(__file__)),baseline=record(BASELINE),
        known_development=True,independent_unseen=False,created_at=datetime.now().astimezone().isoformat())
    value["content_sha256"] = canonical(value)
    save(FREEZE,value)
    print("前20夜で固定: " + str(value["selected"]), flush=True)


def complete() -> None:
    """全27夜の完了と確認後の再選択がないことを記録する。

    引数: なし。返り値: None。
    """
    verify_receipt()
    fixed = verified_freeze()
    proofs = []
    for stage in ("train_validation", "confirmation"):
        proof, _ = stage_results(stage)
        if stage == "confirmation":
            assert proof["stage"]["freeze_sha256"] == sha(FREEZE)
            assert proof["stage"]["selected"] == fixed["selected"]
        proofs.append(record(HERE / "results" / stage / ("再生完了165_"+stage+".json")))
    save(HERE / "再生全完了165.json",dict(completed=True,returncode=0,sessions=27,cases=27*len(IDS),
        selected=fixed["selected"],selected_eligible=fixed["selected_eligible"],adoption_confirmed=False,
        freeze=record(FREEZE),proofs=proofs,reselection_after_confirmation=False,
        known_development=True,independent_unseen=False,us_market_data_used=False))
    print("全27夜・378条件場の再生完了。後半での再選択なし。", flush=True)


def main() -> None:
    """登録・段階許可・選択固定・完了を順番に呼び出す。

    引数: CLI command(str)、stage(str省略可)。返り値: None。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=("register","allow","freeze","complete"))
    parser.add_argument("stage",nargs="?",choices=("train_validation","confirmation"))
    args=parser.parse_args()
    if args.command == "register": register()
    elif args.command == "allow": allow(args.stage)
    elif args.command == "freeze": freeze()
    else: complete()


if __name__ == "__main__":
    main()
