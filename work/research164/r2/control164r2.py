"""手法定義の不変登録、前40場の選択、固定後14場の実行を管理する。"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
IDENT = "164r2_待機増幅の抑制と元夜間入口の利益保護"
MANIFEST = HERE/"inputs164r2.json"
SPEC = HERE/"計画164r2.md"
CONFIGS = HERE/"engine/configs164r2.json"
AUDIT = HERE/"audit/preflight164r2_final.json"
RECEIPT = HERE/"登録受領164r2.json"
FREEZE = HERE/"results/selection_frozen164r2.json"
SCOPES = {"Day":("D",4,12), "PreUS":("P",4,4), "PostUS":("U",4,4)}
IDS = {f"NK225_{letter}164_{index:02d}" for letter,count,start in SCOPES.values() for index in range(start,start+count)}
RANKING = ["累計黒字の候補を優先", "無取引場数の少ない順", "赤字場数の少ない順", "平均赤字絶対額の小さい順", "場内最悪赤字絶対額の小さい順", "収支合計の高い順", "ID昇順"]


def read(path: Path):
    """JSON成果を有限な構造として読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    json.dumps(value, allow_nan=False)
    return value


def sha(path: Path) -> str:
    """内容を逐次読みSHA256を返す。

    引数: path(Path)。返り値: str。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value) -> str:
    """順序に依存しない構造指紋を返す。

    引数: value(dict又はlist)。返り値: str。
    """
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",",":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def record(path: Path) -> dict:
    """プロジェクト相対の根拠と内容指紋を返す。

    引数: path(Path)。返り値: dict。
    """
    return dict(path=path.resolve().relative_to(ROOT).as_posix(), sha256=sha(path))


def verify(item: dict) -> None:
    """記録されたファイルの内容が変わっていないことを確認する。

    引数: item(dict)。返り値: None。
    """
    path = Path(item["path"])
    path = path if path.is_absolute() else ROOT/path
    assert sha(path) == item["sha256"], str(path)


def save(path: Path, value) -> None:
    """証跡を上書きせず新規保存する。

    引数: path(Path)、value(dict又はlist)。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def module(path: Path, name: str):
    """管理器の関数を読み、巨大な試行正本はこの時点で読まない。

    引数: path(Path)、name(str)。返り値: module。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def manager():
    """共通試行管理器を読み出す。

    引数: なし。返り値: module。
    """
    return module(ROOT/"アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py", "管理164")


def configs() -> list[dict]:
    """IDの重複と時間帯での定義差し替えがない第二巡固定12条件を確認する。

    引数: なし。返り値: list[dict]。
    """
    items = read(CONFIGS)
    assert len(items) == 12 and {c["id"] for c in items} == IDS
    for scope, (letter, count, start) in SCOPES.items():
        matching = [c for c in items if c["scope"] == scope]
        assert len(matching) == count
        assert {c["id"] for c in matching} == {f"NK225_{letter}164_{i:02d}" for i in range(start,start+count)}
        assert all(isinstance(c["rule_hash"],str) and len(c["rule_hash"]) == 64 for c in matching)
    return items


def verify_receipt() -> dict:
    """登録成功と登録源の全指紋を確認する。

    引数: なし。返り値: dict。
    """
    receipt = read(RECEIPT)
    assert receipt["registered"] is True and receipt["returncode"] == 0 and receipt["id"] == IDENT
    for item in receipt["sources"]+[receipt["implementation"],receipt["plan"],receipt["preflight"]]:
        verify(item)
    return receipt


def schema_check(plan: dict) -> None:
    """実提案を小さい仮正本と空履歴で事前照合する。

    引数: plan(dict)。返り値: None。巨大正本へアクセスしない。
    """
    m = manager()
    m.validate({"rules":{"rules":[]},"knowledge":{"findings":[]},"trials":{"trials":[plan],"repetition_audit":[]},"studies":{"studies":[]}}, deep=False)
    checker = module(Path(m.HERE)/"duplicate_check.py", "重複164")
    result = checker.analyze(plan, [])
    assert result["proposal_complete"], result["note"]


def register() -> None:
    """人工検査後の第二巡12手法を一括登録し、売買は実行しない。

    引数: なし。返り値: None。
    """
    assert not RECEIPT.exists()
    assert not list((HERE/"results").glob("*/*.json")), "金融成果を先に生成しない"
    audit = read(AUDIT)
    assert audit["passed"] is True and audit["sources"]
    for item in audit["sources"]:
        verify(item)
    fixed = configs()
    manifest = read(MANIFEST)
    assert len(manifest["sessions"]) == 54
    sources = [ROOT/x["path"] for x in audit["sources"]]
    required = [MANIFEST,SPEC,CONFIGS,Path(__file__)]+[p for p in (HERE/"engine").rglob("*") if p.is_file() and p.suffix in {".go",".mod",".sum",".toml",".json"} and "testdata" not in p.parts]
    assert set(required).issubset(set(sources)), "固定源の事前監査指紋が不足"
    sources = sorted(set(sources+[AUDIT]))
    bundle = HERE/"再生前実装164r2.zip"
    assert not bundle.exists()
    with zipfile.ZipFile(bundle, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in sources:
            archive.write(path, path.relative_to(ROOT).as_posix())
    definitions = record(CONFIGS)
    prior = read(HERE.parent/"登録受領164.json")
    plan = dict(id=IDENT, name="日中の待機数量上限と元夜間入口への実玉利益保護", purpose="条件比較",
        question="利益返しを減らしつつ、待機時の増枚と初回未順行損・再参加連敗を抑えられるか",
        change="日中は残玉保護と追加限定停止を組合せ、失速待機時に当初希望量を超えない。夜は失敗した短期反発入口から元P05/D07へ戻し、全玉/残玉/小量初回/追加の保護を分離。",
        repeat_reason="第一巡の全54場で、日中は待機時の未校正支持による数量増幅、夜前は初回未順行損と気配差、夜後は尺度と条件の同時成立不足を確認。別IDを発行した追加開発であり独立未見検証ではない。",
        compares_to=[prior["id"]],
        spec={
            "entry":{"definitions":definitions,"day":"157第二巡J02と上限付き失速待機","night":"元P05/D07の入口と失速待機を別ID","scope_ids":{s:[x["id"] for x in fixed if x["scope"]==s] for s in SCOPES}},
            "management":{"definitions":definitions,"method":"Actual所有玉ごとの利益保護、元の初回・追加・利益残玉を分け、独自の頻繁な再参加は足さない"},
            "exit":{"definitions":definitions,"method":"全原行で保護判定、次正常原行約定。場内終了・米国静観前に完済。50円停止はDayの戦術玉対照とし全初回へ一律追加しない"},
            "allocation":{"definitions":definitions,"max_per_side_micro":100,"equivalent_mini":10,"method":"DayJ02当初希望量を解除時上限に。Night元Source通知数量と生存残量を上限に。スコアは勝率ではない"},
            "costs":{"fee":0,"point_value_micro":10,"execution":"参照ラージ次正常Ask買/Bid売で気配差を含む"},
            "execution":{"specification":record(SPEC),"ranking":RANKING,"selection":"前40場で第一巡の保存結果を含めDay/PreUS/PostUS別に固定、後14で再選択しない。第二巡は全54既知の追加開発","composition":"時間割の構成IDを明示し、夜間合計を別手法IDとしない"},
            "data":{"sessions":[s["session"] for s in manifest["sessions"]],"input_manifests":[record(MANIFEST)],"previous_results":[record(HERE.parent/"再生全完了164.json"),record(HERE.parent/"results/train_validation/再生完了164_train_validation.json")],"scope":"第一巡で全54場確認済みの追加開発。入力SHAを再生前後確認"},
            "implementation":{record(bundle)["path"]:sha(bundle),definitions["path"]:definitions["sha256"]}})
    schema_check(plan)
    proposal = HERE/"再生計画164r2.json"
    save(proposal, plan)
    print("小さい実提案照合PASS。第二巡の固定12手法を管理器で一括照合・登録します。", flush=True)
    row = manager().store_trial(plan)
    check_path = HERE/"事前照合164r2.json"
    save(check_path, row["preflight"])
    save(RECEIPT, dict(id=IDENT, registered=True,returncode=0,created_at=datetime.now().astimezone().isoformat(),
        sources=[record(p) for p in sources],implementation=record(bundle),plan=record(proposal),preflight=record(check_path),
        spec=record(SPEC),configs=record(CONFIGS),manifest=record(MANIFEST),new_financial_replays=0))
    print("登録完了。新金融は未実行です。", flush=True)


def allow(stage: str) -> None:
    """固定登録と前半選択を検査して段階実行を許す。

    引数: stage(str)。返り値: None。
    """
    verify_receipt()
    assert stage in ("train_validation","confirmation")
    assert not list((HERE/"results"/stage).glob("*.json"))
    value = dict(registered=True,returncode=0,allowed_stages=[stage],manifest_sha256=sha(MANIFEST),
        spec_sha256=sha(SPEC),configs_sha256=sha(CONFIGS),registration=record(RECEIPT),
        known_confirmation=True,created_at=datetime.now().astimezone().isoformat())
    if stage == "confirmation":
        frozen = read(FREEZE)
        assert frozen["test_opened"] is False and frozen["selection_sessions"] == 40
        assert set(frozen["selected"]) == set(SCOPES)
        assert frozen["ranking_order"] == RANKING
        for key,path in (("manifest_sha256",MANIFEST),("spec_sha256",SPEC),("configs_sha256",CONFIGS)):
            assert frozen[key] == sha(path)
        assert frozen["content_sha256"] == canonical({k:v for k,v in frozen.items() if k!="content_sha256"})
        for item in frozen["results"]+[frozen["complete_proof"],frozen["selection_implementation"],frozen["reused_first_round_proof"]]:
            verify(item)
        value["freeze_sha256"] = sha(FREEZE)
    save(HERE/(stage+"_許可164r2.json"),value)
    print("段階許可を保存: "+stage)


def stage_results(stage: str) -> tuple[dict,list[dict]]:
    """完了証跡と各場結果の定義・SHA・完済を照合する。

    引数: stage(str)。返り値: 完了dictと結果dictのlist。
    """
    count,cases = (40,240) if stage=="train_validation" else (14,84)
    folder = HERE/"results"/stage
    proof = read(folder/("再生完了164r2_"+stage+".json"))
    assert proof["completed"] is True and proof["returncode"] == 0 and proof["sources_unchanged"] is True
    assert proof["sessions"] == count and proof["cases"] == cases and len(proof["results"]) == count
    assert proof["stage"]["stage"] == stage
    for key,path in (("manifest_sha256",MANIFEST),("spec_sha256",SPEC),("configs_sha256",CONFIGS)):
        assert proof["stage"][key] == sha(path)
    scenes = {s["session"]:s for s in read(MANIFEST)["sessions"] if (s["split"] in ("train","validation")) == (stage=="train_validation")}
    assert {item["session"] for item in proof["results"]} == set(scenes)
    definitions = {c["id"]:c for c in configs()}
    results = []
    for item in proof["results"]:
        verify(item)
        path = Path(item["path"])
        path = path if path.is_absolute() else ROOT/path
        assert path.resolve() == (folder/(item["session"]+".json")).resolve()
        data = read(path)
        scene = scenes[item["session"]]
        for key in ("session","kind","start","end","force_close","cutoff","us_open","partial","books","candles","split"):
            assert data["scene"][key] == scene[key], "出力と入力目録の場定義不一致: "+key
        assert {f["path"]:f["sha256"] for f in data["scene"]["fingerprints"]} == {f["path"]:f["sha256"] for f in scene["fingerprints"]}
        ids = {c["id"] for c in definitions.values() if (c["scope"]=="Day") == (data["scene"]["kind"]=="Day")}
        assert len(data["cases"]) == len(ids) and {c["config"]["id"] for c in data["cases"]} == ids
        for case in data["cases"]:
            c = case["config"]
            assert c["scope"] == definitions[c["id"]]["scope"] and c["rule_hash"] == definitions[c["id"]]["rule_hash"]
            assert c == definitions[c["id"]], "保存条件と固定定義の全構造が一致しない"
            ledger = case["actual"]
            assert not ledger["Active"] and not ledger["Pending"]
            assert all(lot["Remaining"] == 0 for lot in ledger["Lots"].values())
        results.append(data)
    return proof,results


def rank(rows: list[dict]) -> list[dict]:
    """候補を固定した基準で並べる。

    引数: rows(list[dict])。返り値: list[dict]。後半の結果を入力しない。
    """
    return sorted(rows,key=lambda r:(r["net"]<=0,r["no_entries"],r["negative_sessions"],r["mean_negative_absolute"],r["worst_equity_absolute"],-r["net"],r["id"]))


def freeze() -> None:
    """前40場だけで各時間帯の候補を一つ固定する。

    引数: なし。返り値: None。
    """
    verify_receipt()
    assert not FREEZE.exists() and not list((HERE/"results/confirmation").glob("*.json"))
    proof, results = stage_results("train_validation")
    previous = module(HERE.parent/"control164.py", "第一巡制御164")
    previous.verify_receipt()
    prior_proof, prior_results = previous.stage_results("train_validation")
    candidates = previous.configs()+configs()
    results = prior_results+results
    ranking = {}
    for scope in SCOPES:
        rows = []
        for method in [c for c in candidates if c["scope"] == scope]:
            group = [c for data in results for c in data["cases"] if c["config"]["id"] == method["id"]]
            assert len(group) == 20
            nets = [c["actual"]["Realized"] for c in group]
            negatives = [-x for x in nets if x < 0]
            no_entries = sum(not any(not ev["Order"]["Targets"] for ev in c["actual"]["Events"] or []) for c in group)
            rows.append(dict(id=method["id"],scope=scope,sessions=20,net=sum(nets),no_entries=no_entries,
                negative_sessions=len(negatives),mean_negative_absolute=sum(negatives)/len(negatives) if negatives else 0,
                worst_equity_absolute=max(0,-min(c["actual"]["Risk"]["Minimum"] for c in group))))
        ranking[scope] = rank(rows)
    value = dict(selected={s:r[0]["id"] for s,r in ranking.items()}, ranking=ranking, ranking_order=RANKING,
        selected_is_adoption=False,selection_sessions=40,test_opened=False,known_confirmation=True,
        manifest_sha256=sha(MANIFEST),spec_sha256=sha(SPEC),configs_sha256=sha(CONFIGS),
        results=prior_proof["results"]+proof["results"],complete_proof=record(HERE/"results/train_validation/再生完了164r2_train_validation.json"),
        reused_first_round_proof=record(HERE.parent/"results/train_validation/再生完了164_train_validation.json"),
        selection_implementation=record(Path(__file__)),created_at=datetime.now().astimezone().isoformat(),
        composition="夜間は選択したPreUS/PostUSの非重複会計を連結する。合計に手法IDは付けない。")
    value["content_sha256"] = canonical(value)
    save(FREEZE,value)
    print("前40から固定: "+str(value["selected"]))


def complete() -> None:
    """両段階の完了・選択不変を確認する。

    引数: なし。返り値: None。
    """
    verify_receipt()
    frozen = read(FREEZE)
    proofs = []
    for stage in ("train_validation","confirmation"):
        proof,_ = stage_results(stage)
        if stage == "confirmation":
            assert proof["stage"]["freeze_sha256"] == sha(FREEZE)
            assert proof["stage"]["selected"] == frozen["selected"]
        proofs.append(record(HERE/"results"/stage/("再生完了164r2_"+stage+".json")))
    save(HERE/"再生全完了164r2.json",dict(completed=True,returncode=0,sessions=54,cases=324,
        selected=frozen["selected"],freeze=record(FREEZE),proofs=proofs,known_confirmation=True,
        reselection_after_confirmation=False,created_at=datetime.now().astimezone().isoformat()))
    print("第二巡54場・12手法・324条件場の完了を確認しました。")


def main() -> None:
    """明示された段階管理コマンドだけを実行する。

    引数: CLI(command,stage)。返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("command",choices=("register","allow","freeze","complete"))
    parser.add_argument("stage",nargs="?",choices=("train_validation","confirmation"))
    args = parser.parse_args()
    if args.command == "register": register()
    elif args.command == "allow": allow(args.stage)
    elif args.command == "freeze": freeze()
    else: complete()


if __name__ == "__main__":
    main()
