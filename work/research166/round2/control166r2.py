"""初回不一致を保全し、条件不変の実装訂正版だけを別ラウンドで検査する。"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
from pathlib import Path
import subprocess
import sys
import zipfile

HERE=Path(__file__).resolve().parent
BASE=HERE.parent
sys.path.insert(0,str(BASE))
import control166 as original
import audit_inputs166 as inputs
from control166 import ROOT,read,record,verify,save,sha

RECEIPT=HERE/"実装訂正受領166r2.json"
EXE=HERE/"parity166r2.exe"
STAGES={"day_smoke":("2026-10-26_Day",100,1,1),"day_full":("_Day",100,27,27),"mini_full":("",10,54,81)}


def original_frozen() -> dict:
    """元の受領・固定 ZIP・研究正本を確認し、現在 App との差は消さない。

    引数: なし。返り値: dict。
    """
    receipt=read(original.RECEIPT)
    assert receipt["registered"] and receipt["returncode"]==0 and receipt["id"]==original.IDENT
    for key in ("implementation","plan","preflight","frozen","manifest","baseline"):verify(receipt[key])
    with zipfile.ZipFile(ROOT/receipt["implementation"]["path"]) as archive:
        for source in receipt["sources"]:
            assert hashlib.sha256(archive.read(source["path"])).hexdigest()==source["sha256"],source["path"]
    baseline=read(original.BASELINE)
    for source in baseline["definitions"]+[r["source"] for r in baseline["cases_by_session"]]:verify(source)
    initial=read(BASE/"初回実行_full_cap100.json")
    assert len(initial["results"])==54 and initial["sources_unchanged"] is True
    assert initial["registration"]==record(original.RECEIPT)
    for source in initial["results"]:verify(source)
    return receipt


def freeze(reason_path: Path) -> None:
    """変更理由・変更許可パス・人工根拠と訂正版の全源を実行前に固定する。

    引数: reason_path(Path)。返り値: None。金融再生・台帳変更はしない。
    """
    assert not RECEIPT.exists()
    old=original_frozen()
    reason=read(reason_path)
    assert reason["condition_changes"] is False and reason["parameter_search"] is False
    assert reason["reason"] and reason["changed_paths"] and reason["artificial_evidence"]
    for evidence in reason["artificial_evidence"]:
        verify(evidence)
        check=read(ROOT/evidence["path"])
        assert check.get("passed") is True or check.get("returncode")==0
        if "passed" in check:assert check["passed"] is True
        if "returncode" in check:assert check["returncode"]==0
    sources=original.required_sources()|{Path(__file__).resolve(),HERE/"test_control166r2.py",EXE,reason_path.resolve()}
    assert EXE.is_file()
    before={s["path"]:s for s in old["sources"]}
    now=[record(p) for p in sorted(sources)]
    modifications=[dict(path=s["path"],before=before[s["path"]]["sha256"],after=s["sha256"])
        for s in now if s["path"] in before and s["sha256"]!=before[s["path"]]["sha256"]]
    added=[s["path"] for s in now if s["path"] not in before and s["path"].startswith("App/")]
    deleted=[s for s in before if s.startswith("App/") and s not in {r["path"] for r in now}]
    assert {r["path"] for r in modifications}|set(added)|set(deleted)==set(reason["changed_paths"])
    assert all(p.startswith("App/SessionTrader/") for p in reason["changed_paths"]),"今回の訂正は App 実装のみ"
    bundle=HERE/"訂正版実装166r2.zip"
    with zipfile.ZipFile(bundle,"x",zipfile.ZIP_DEFLATED) as archive:
        for source in now:archive.write(ROOT/source["path"],source["path"])
    for source in now:verify(source)
    save(RECEIPT,dict(registered_under_original=True,returncode=0,created_at=datetime.now().astimezone().isoformat(),
        original_registration=record(original.RECEIPT),original_execution=record(BASE/"初回実行_full_cap100.json"),
        correction_reason=record(reason_path),implementation=record(bundle),sources=now,modifications=modifications,
        added_app_sources=added,deleted_app_sources=deleted,condition_changes=False,new_financial_replays=0,
        methods=sorted(original.IDS),app_scope="日中修正。初回 Night 54 ケースは保存再利用。"))
    print("訂正版を別指紋で固定しました。元登録・正本・初回不一致は保持しています。",flush=True)


def verify_round() -> dict:
    """訂正版の受領と全源が実行前の固定内容に一致するか確認する。

    引数: なし。返り値: dict。
    """
    original_frozen()
    receipt=read(RECEIPT)
    assert receipt["registered_under_original"] and receipt["returncode"]==0 and receipt["condition_changes"] is False
    for key in ("original_registration","original_execution","correction_reason","implementation"):verify(receipt[key])
    for source in receipt["sources"]:verify(source)
    return receipt


def stage_proof(stage: str) -> Path:
    """段階ごとの完了記録位置を返す。

    引数: stage(str)。返り値: Path。
    """
    return HERE/("実行166r2_"+stage+".json")


def verify_stage(stage: str) -> dict:
    """実装訂正後のケース数・正本同値・残玉を独立に検査する。

    引数: stage(str)。返り値: dict。
    """
    substring,cap,files,cases=STAGES[stage]
    proof=read(stage_proof(stage))
    assert proof["completed"] and proof["returncode"]==0 and proof["sources_unchanged"]
    assert proof["stage"]==stage and proof["cap"]==cap and len(proof["results"])==files
    count=0;keys=set()
    for source in proof["results"]:
        verify(source);data=read(ROOT/source["path"]);assert data["Error"]=="<nil>"
        for case in data["Results"]:
            count+=1
            assert substring in case["Session"] and case["Cap"]==cap
            allowed={"NK225_D164_15"} if case["Session"].endswith("_Day") else {"NK225_P164_06","NK225_U165_03"}
            key=(case["Session"],case["Method"])
            assert case["Method"] in allowed and key not in keys
            keys.add(key)
            assert not case["Error"] and not case["Differences"] and case["Held"]==0 and case["Pending"]==0
            if cap==100:assert abs(case["Gross"]-case["ExpectedGross"])<=.001
    assert count==cases
    return proof


def run(stage: str) -> None:
    """原資料の前後監査を伴って、指定した訂正確認段階だけを一度実行する。

    引数: stage(str)。返り値: None。実注文/API 通信なし。
    """
    receipt=verify_round()
    if stage=="day_full":verify_stage("day_smoke")
    if stage=="mini_full":verify_stage("day_full")
    substring,cap,files,cases=STAGES[stage]
    out=HERE/("results_"+stage)
    assert not out.exists() and not stage_proof(stage).exists()
    label="r2_"+stage+"_cap"+str(cap)
    before=inputs.check("before",label)
    command=[str(EXE),"-root",str(ROOT),"-cap",str(cap),"-out",str(out),"-workers","3"]
    if substring:command += ["-session",substring]
    started=datetime.now().astimezone().isoformat()
    log=HERE/("実行166r2_"+stage+".log")
    with log.open("x",encoding="utf-8") as stream:
        result=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=False)
    unchanged=True;error=None
    try:verify_round()
    except (AssertionError,OSError) as failure:unchanged=False;error=str(failure)
    raw_passed=True
    try:after=inputs.check("after",label)
    except (AssertionError,OSError) as failure:
        raw_passed=False;error=(error or "")+" / "+str(failure)
        after=inputs.AUDIT/(label+"_after.json")
    results=sorted(out.glob("*.json"))
    save(stage_proof(stage),dict(completed=result.returncode==0 and unchanged and raw_passed and len(results)==files,
        returncode=result.returncode,started_at=started,finished_at=datetime.now().astimezone().isoformat(),stage=stage,cap=cap,
        product="NK225micro" if cap==100 else "NK225mini",sources_unchanged=unchanged,raw_unchanged=raw_passed,error=error,
        registration=record(original.RECEIPT),correction=record(RECEIPT),raw_before=record(before),
        raw_after=record(after) if after.exists() else None,command=command,log=record(log),
        results=[record(p) for p in results],expected_result_files=files,expected_cases=cases,
        parameter_search=False,independent_unseen=False))
    verify_stage(stage)
    print("訂正確認終了: "+stage+" / 全 "+str(cases)+" 手法場 PASS",flush=True)


def main() -> None:
    """実装凍結・確認・各再実行を明示コマンドで分離する。

    引数: CLI action、--reason、--stage。返り値: None。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["freeze","verify","run"])
    parser.add_argument("--reason",type=Path)
    parser.add_argument("--stage",choices=list(STAGES))
    args=parser.parse_args()
    if args.action=="freeze":assert args.reason;freeze(args.reason)
    elif args.action=="verify":verify_round();print("訂正版の全指紋が一致しました。")
    else:assert args.stage;run(args.stage)


if __name__=="__main__":main()
