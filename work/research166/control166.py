"""選定三手法の移植同値検査を固定して登録し、指紋確認後だけ実行を許可する。"""
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
IDENT = "166_選定三手法のWeb実装の独立再検証"
RECEIPT = HERE / "登録受領166.json"
MANIFEST = ROOT / "work/research164/r2/inputs164r2.json"
BASELINE = HERE / "研究正本166.json"
PLAN = HERE / "計画166.md"
FREEZE = HERE / "初回実装の凍結166.json"
IDS = {"NK225_D164_15", "NK225_P164_06", "NK225_U165_03"}


def read(path: Path):
    """有限値の JSON を読み取る。

    引数: path(Path)。返り値: dict 又は list。
    """
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    json.dumps(value, allow_nan=False)
    return value


def sha(path: Path) -> str:
    """ファイルを逐次読みして内容指紋を計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value) -> str:
    """キー順に依存しない構造指紋を返す。

    引数: value(dict 又は list)。返り値: SHA256(str)。
    """
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def record(path: Path) -> dict:
    """根拠をルート相対パスと内容指紋へ変換する。

    引数: path(Path)。返り値: dict。
    """
    return dict(path=path.resolve().relative_to(ROOT).as_posix(), sha256=sha(path))


def verify(source: dict) -> None:
    """保存した根拠の現在内容が一致することを確認する。

    引数: source(dict)。返り値: None。
    """
    path = Path(source["path"])
    if not path.is_absolute(): path = ROOT / path
    assert sha(path) == source["sha256"], f"内容指紋が不一致: {path}"


def save(path: Path, value) -> None:
    """証跡を新規保存し、以前の結果を上書きしない。

    引数: path(Path)、value(dict 又は list)。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def module(path: Path, name: str):
    """指定モジュールを読み込み、巨大台帳はこの時点では開かない。

    引数: path(Path)、name(str)。返り値: module。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def prepare() -> None:
    """既存正本の全 81 手法場と固定定義を内容指紋で一覧化する。

    引数: なし。返り値: None。金融再生はしない。
    """
    assert not BASELINE.exists()
    scenes = read(MANIFEST)["sessions"]
    assert len(scenes) == 54 and len({s["session"] for s in scenes}) == 54
    assert sum(s["kind"] == "Day" for s in scenes) == 27
    assert sum(s["kind"] == "Night" for s in scenes) == 27
    records = []
    for scene in scenes:
        methods = ["NK225_D164_15"] if scene["kind"] == "Day" else ["NK225_P164_06", "NK225_U165_03"]
        for method in methods:
            base = ROOT / ("work/research165/results" if method == "NK225_U165_03" else "work/research164/r2/results")
            choices = [base/stage/(scene["session"]+".json") for stage in ("train_validation", "confirmation")]
            paths = [p for p in choices if p.is_file()]
            assert len(paths) == 1, scene["session"]
            data = read(paths[0])
            found = [c for c in data["cases"] if c["config"]["id"] == method]
            assert len(found) == 1
            records.append(dict(session=scene["session"], method=method, source=record(paths[0]),
                actual_realized=found[0]["actual"]["Realized"], known_development=True))
    definitions = [ROOT/"work/research164/r2/engine/configs164r2.json", ROOT/"work/research165/night_engine/configs165.json",
        ROOT/"work/research164/r2/再生全完了164r2.json", ROOT/"work/research165/再生全完了165.json",
        ROOT/"work/research164/r2/登録受領164r2.json", ROOT/"work/research165/登録受領165.json"]
    save(BASELINE, dict(methods=sorted(IDS), sessions=54, cases=81, new_financial_replays=0,
        manifest=record(MANIFEST), definitions=[record(p) for p in definitions], cases_by_session=records,
        note="研究正本の結果は保存再利用。今回の移植照合は収益性の追加証拠ではない。"))


def required_sources() -> set[Path]:
    """初回検査に関わる App とリプレイの実行源・設定を列挙する。

    引数: なし。返り値: set[Path]。
    """
    app = ROOT / "App/SessionTrader"
    sources = {PLAN, MANIFEST, BASELINE, Path(__file__), HERE/"registry166.py", HERE/"execute166.py", HERE/"test_registry166.py",
        HERE/"test_control166.py", app/"go.mod", app/"go.sum"}
    for folder in [app/"internal", app/"conf/rules", HERE/"replay"]:
        sources.update(p for p in folder.rglob("*") if p.is_file() and p.suffix in
            {".go", ".mod", ".sum", ".toml", ".html", ".js", ".css"})
    sources.add(HERE/"parity166.exe")
    assert any(p.suffix == ".exe" for p in sources), "ビルド済み照合器の指紋が必要"
    return {p.resolve() for p in sources}


def freeze() -> None:
    """初回実装と正本を凍結し、実際の登録計画を 8 部品で作る。

    引数: なし。返り値: None。金融再生・台帳更新はしない。
    """
    assert not RECEIPT.exists() and not FREEZE.exists()
    baseline = read(BASELINE)
    for source in [baseline["manifest"]]+baseline["definitions"]+[r["source"] for r in baseline["cases_by_session"]]: verify(source)
    artificial = read(HERE/"人工検証166.json")
    assert artificial["passed"] and artificial["new_financial_replays"] == 0
    for source in artificial["sources"]: verify(source)
    sources = required_sources() | {HERE/"人工検証166.json"}
    bundle = HERE/"初回実装166.zip"
    before = [record(p) for p in sorted(sources)]
    with zipfile.ZipFile(bundle, "x", zipfile.ZIP_DEFLATED) as archive:
        for source in before: archive.write(ROOT/source["path"], source["path"])
    for source in before: verify(source)
    fixed = dict(created_at=datetime.now().astimezone().isoformat(), source_frozen=True, new_financial_replays=0,
        sources=before, implementation=record(bundle), baseline=record(BASELINE), manifest=record(MANIFEST), methods=sorted(IDS))
    save(FREEZE, fixed)
    plan = build_plan(record(bundle))
    save(HERE/"再検証計画166.json", plan)
    schema_check(plan)
    print("00166 の初回実装を固定しました。金融再生・台帳登録は未実行です。", flush=True)


def build_plan(implementation: dict) -> dict:
    """正本定義と移植差分を必須 8 部品へ記録する。

    引数: implementation(dict)。返り値: 計画(dict)。
    """
    definition = record(BASELINE)
    return dict(id=IDENT, name="選定三手法の Web 実装と研究正本の独立同値確認", purpose="独立再検証",
        question="指定した三手法が Web 実装でも当時情報・実所有 ID・整数数量で研究正本を再現するか",
        change="売買条件は変更しない。App 実装・Expr・整数商品換算・部分約定と個別取消・設定移行を接続する。",
        repeat_reason="00164 第二巡と 00165 の保存正本を変更せず、別の App 実装の正確さを検査する。00155 の移植確認、00157/00159 の投影・返済配賦差も踏まえ、収支だけでなく原行・実約定・所有数量を比較する。新しい有効性には数えない。",
        compares_to=["164r2_待機増幅の抑制と元夜間入口の利益保護", "165_米国開始後の板追随と損失安定化"],
        spec=dict(entry=dict(definitions=definition, methods=sorted(IDS), conditions="固定した研究正本を維持"),
            management=dict(definitions=definition, ownership="仮想 Source と実玉・予約・延期親を分離"),
            exit=dict(definitions=definition, timing="所有 ID の実建値判定、判断後次正常板。場末/US境界は正本どおり"),
            allocation=dict(equivalence=dict(product="NK225micro",cap=100,point_value=10),
                granularity=dict(product="NK225mini",cap=10,point_value=100), rounding="整数切捨て、完全返済は所有残全て", source="固定 mini10 相当"),
            costs=dict(fee=0,spread="ラージの Ask 買い/Bid 売り。手数料と区別"),
            execution=dict(specification=record(PLAN), methods=sorted(IDS), selection=False, unseen=False,
                first_smoke="2026-09-24 の Day/Night 3 手法場を先に照合。不一致は保存して実装訂正後に再確認。",
                correction="条件不変の不具合修正だけをラウンド別源 SHA・理由・人工証拠・出力と共に保持"),
            data=dict(sessions=[s["session"] for s in read(MANIFEST)["sessions"]],input_manifests=[record(MANIFEST)],previous_results=[definition]),
            implementation={implementation["path"]:implementation["sha256"], definition["path"]:definition["sha256"]}))


def schema_check(plan: dict) -> None:
    """巨大正本を読まず、実計画の構造・8 部品・根拠を検査する。

    引数: plan(dict)。返り値: None。
    """
    m = module(ROOT/"アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py", "登録構造166")
    scope = dict(rules=dict(rules=[]), knowledge=dict(findings=[]), trials=dict(trials=[plan], repetition_audit=[]), studies=dict(studies=[]))
    m.validate(scope, deep=True)
    assert m.analyzer().analyze(plan, [])["proposal_complete"], "実計画の 8 部品が不足"


def register() -> None:
    """凍結した初回実装を共通照合して 1 件だけ事前登録する。

    引数: なし。返り値: None。金融再生はしない。
    """
    assert not RECEIPT.exists()
    fixed = read(FREEZE)
    assert fixed["source_frozen"] and fixed["new_financial_replays"] == 0
    for source in fixed["sources"]+[fixed["implementation"],fixed["baseline"]]: verify(source)
    assert {str(ROOT/s["path"]) for s in fixed["sources"]} >= {str(p) for p in required_sources()}
    plan_path = HERE/"再検証計画166.json"
    plan = read(plan_path)
    assert plan == build_plan(fixed["implementation"])
    schema_check(plan)
    registry = module(HERE/"registry166.py", "対象限定登録166")
    checked = registry.register_plan(plan)
    save(RECEIPT, dict(id=IDENT, registered=True, returncode=0, created_at=datetime.now().astimezone().isoformat(),
        sources=fixed["sources"], implementation=fixed["implementation"], plan=record(plan_path),
        preflight=checked, frozen=record(FREEZE), manifest=record(MANIFEST), baseline=record(BASELINE),
        new_financial_replays=0, independent_unseen=False, parameter_search=False))
    print("00166 の事前登録完了。金融再生は未実行です。", flush=True)


def verify_receipt() -> dict:
    """登録受領と初回源・正本の全指紋を確認する。

    引数: なし。返り値: 登録受領(dict)。
    """
    receipt = read(RECEIPT)
    assert receipt["id"] == IDENT and receipt["registered"] and receipt["returncode"] == 0
    for source in receipt["sources"]+[receipt[k] for k in ("implementation","plan","preflight","frozen","manifest","baseline")]: verify(source)
    baseline = read(BASELINE)
    for source in baseline["definitions"]+[r["source"] for r in baseline["cases_by_session"]]: verify(source)
    return receipt


def allow(name: str) -> None:
    """固定実装を確認して、初回実行ラウンドの許可証跡だけを作る。

    引数: name(str) は smoke 又は full。返り値: None。再生は起動しない。
    """
    receipt = verify_receipt()
    assert name in {"smoke", "full"}
    smoke = check_smoke() if name == "full" else None
    save(HERE/("実行許可166_"+name+".json"), dict(registered=True,returncode=0,stage=name,
        created_at=datetime.now().astimezone().isoformat(),registration=record(RECEIPT),
        methods=sorted(IDS),caps=[100,10],session_filter="2026-09-24" if name=="smoke" else "",
        source_frozen=True, sources=receipt["sources"], parameter_search=False,smoke=smoke))
    print("初回実装の指紋確認と実行許可保存: "+name, flush=True)


def check_smoke() -> dict:
    """最初の 3 手法場が正本同値であることを確認してから全場へ進める。

    引数: なし。返り値: dict。結果の金融再生はしない。
    """
    proof = read(HERE/"初回実行_smoke_cap100.json")
    assert proof["completed"] and proof["returncode"] == 0
    sources = proof["results"]
    assert len(sources) == 2
    found=[]
    for source in sources:
        verify(source)
        data=read(ROOT/source["path"])
        assert data["Error"] == "<nil>"
        for case in data["Results"]:
            assert case["Session"] in {"2026-09-24_Day","2026-09-24_Night"}
            assert case["Cap"] == 100 and case["Pending"] == 0 and case["Held"] == 0
            assert not case["Differences"] and not case["Error"]
            assert abs(case["Gross"]-case["ExpectedGross"]) <= .001
            found.append(case["Method"])
    assert len(found)==3 and set(found)==IDS
    return dict(passed=True,cases=3,execution=record(HERE/"初回実行_smoke_cap100.json"),results=sources)


def main() -> None:
    """準備・凍結・登録・指紋確認を明示コマンドで分離する。

    引数: CLI の action(str)。返り値: None。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["prepare","freeze","register","verify","allow-smoke","allow-full"])
    args=parser.parse_args()
    if args.action=="prepare": prepare()
    elif args.action=="freeze": freeze()
    elif args.action=="register": register()
    elif args.action=="verify": verify_receipt(); print("登録源・正本の内容指紋が一致しました。")
    else: allow(args.action.removeprefix("allow-"))


if __name__=="__main__": main()
