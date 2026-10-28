"""最終証跡を検査し、登録済み 00166 の状態だけを更新する。"""
from __future__ import annotations

import argparse
from datetime import datetime
import math
from pathlib import Path

import control166 as control
import registry166 as registry
from control166 import ROOT,HERE,IDENT,read,record,verify,canonical,save


def successful(value: dict) -> None:
    """JSON の成功フラグと終了コードに矛盾がないことを確認する。

    引数: value(dict)。返り値: None。
    """
    assert "passed" in value or "returncode" in value, "成功判定がない証跡"
    if "passed" in value: assert value["passed"] is True
    if "returncode" in value: assert type(value["returncode"]) is int and value["returncode"]==0


def verify_references(value) -> int:
    """証跡内にある全てのパス・SHA 組を再帰的に確認する。

    引数: value(dict、list 又はスカラー)。返り値: 確認数(int)。
    """
    if isinstance(value,dict):
        count=0
        if isinstance(value.get("path"),str) and isinstance(value.get("sha256"),str):
            verify(value);count=1
        return count+sum(verify_references(v) for v in value.values())
    if isinstance(value,list):return sum(verify_references(v) for v in value)
    return 0


def case_check(case: dict,cap: int) -> dict:
    """各約定の整数数量・因果・方向別保有と確定純額を検算する。

    引数: case(dict)、cap(int)。返り値: 検算要約(dict)。
    """
    assert case["Cap"]==cap and case["Method"] in control.IDS
    assert case["Held"]==0 and case["Pending"]==0 and not case["Error"] and not case["Differences"]
    assert math.isfinite(case["Gross"])
    if cap==100:assert abs(case["Gross"]-case["ExpectedGross"])<=.001
    held={1:0,-1:0};maximum={1:0,-1:0};last_index=-1;gross=0.;events=case["Events"] or []
    for event in events:
        quantity=event["Quantity"];side=event["Side"]
        assert type(quantity) is int and 0<quantity<=cap
        assert type(side) is int and side in {-1,1}
        assert event["FillIndex"]>event["DecisionIndex"] and event["FillIndex"]>=last_index
        assert math.isfinite(event["Time"]) and math.isfinite(event["Price"]) and event["Price"]>0
        assert math.isfinite(event["Gross"])
        if event["Action"]=="new":
            held[side]+=quantity
            assert abs(event["Gross"])<=.001
        else:
            assert event["Action"]=="close"
            # 返済の注文方向は保有の反対方向。
            held[-side]-=quantity
        assert all(0<=q<=cap for q in held.values())
        for direction in (-1,1):maximum[direction]=max(maximum[direction],held[direction])
        last_index=event["FillIndex"];gross+=event["Gross"]
    assert held=={1:0,-1:0}
    assert abs(gross-case["Gross"])<=.001
    return dict(session=case["Session"],method=case["Method"],cap=cap,events=len(events),
        net=gross,maximum_long=maximum[1],maximum_short=maximum[-1],remaining=0,pending=0)


def full_result(cap: int) -> dict:
    """全 54 場・81 手法場と原資料の実行前後不変を確認する。

    引数: cap(int)。返り値: dict。
    """
    path=HERE/f"初回実行_full_cap{cap}.json"
    proof=read(path)
    assert proof["completed"] is True and proof["returncode"]==0 and proof["sources_unchanged"] is True
    assert proof["stage"]=="full" and proof["cap"]==cap and not proof["parameter_search"] and not proof["independent_unseen"]
    assert proof["product"]==("NK225micro" if cap==100 else "NK225mini")
    assert len(proof["results"])==54 and proof["expected_result_files"]==54
    verify_references(proof)
    scenes={s["session"]:s for s in read(control.MANIFEST)["sessions"]}
    expected={(s,m) for s,scene in scenes.items() for m in
        (["NK225_D164_15"] if scene["kind"]=="Day" else ["NK225_P164_06","NK225_U165_03"])}
    found={};rows=[]
    for source in proof["results"]:
        data=read(ROOT/source["path"])
        assert data["Error"]=="<nil>"
        for case in data["Results"]:
            key=(case["Session"],case["Method"])
            assert key not in found and key in expected
            row=case_check(case,cap);found[key]=row;rows.append(row)
    assert set(found)==expected and len(rows)==81
    audits=[]
    for phase in ("before","after"):
        audit_path=HERE/f"audit/raw_inputs/full_cap{cap}_{phase}.json"
        audit=read(audit_path)
        assert audit["passed"] and audit["result_usable"] and audit["files"]==324 and audit["changed_files"]==0
        assert audit["phase"]==phase and audit["label"]==f"full_cap{cap}"
        assert audit["original_files_written"] is False
        assert len(audit["records"])==324 and all(r["stat_unchanged"] for r in audit["records"])
        verify_references({k:v for k,v in audit.items() if k!="records"})
        audits.append(record(audit_path))
    return dict(cap=cap,proof=record(path),raw_audits=audits,cases=81,session_count=54,
        original_equivalence=cap==100,integer_granularity=cap==10,events=sum(r["events"] for r in rows),rows=rows)


def reuse_group(path: Path,cap: int,scope: str,raw_label: str,allow_original_day_failure: bool=False) -> dict:
    """固定した必要区分だけを照合し、初回の不一致日中を成功へ混ぜない。

    引数: path(Path)、cap(int)、scope(str)、raw_label(str)、allow_original_day_failure(bool)。返り値: dict。
    """
    proof=read(path)
    assert proof["sources_unchanged"] is True and proof["cap"]==cap
    if allow_original_day_failure:
        assert path==HERE/"初回実行_full_cap100.json" and scope=="Night" and cap==100
        assert len(proof["results"])==54
    else:assert proof["completed"] is True and proof["returncode"]==0
    assert not proof["parameter_search"] and not proof["independent_unseen"]
    verify_references(proof)
    scenes={s["session"]:s for s in read(control.MANIFEST)["sessions"] if scope=="All" or s["kind"]==scope}
    expected={(s,m) for s,scene in scenes.items() for m in
        (["NK225_D164_15"] if scene["kind"]=="Day" else ["NK225_P164_06","NK225_U165_03"])}
    found={};excluded=[]
    for source in proof["results"]:
        data=read(ROOT/source["path"])
        for case in data["Results"]:
            if case["Session"] not in scenes:
                excluded.append(dict(session=case["Session"],method=case["Method"],differences=case["Differences"],error=case["Error"]))
                continue
            assert data["Error"]=="<nil>"
            key=(case["Session"],case["Method"])
            assert key in expected and key not in found
            found[key]=case_check(case,cap)
    assert set(found)==expected
    audits=[]
    for phase in ("before","after"):
        audit_path=HERE/f"audit/raw_inputs/{raw_label}_{phase}.json"
        audit=read(audit_path)
        assert audit["passed"] and audit["result_usable"] and audit["files"]==324 and audit["changed_files"]==0
        assert audit["phase"]==phase and audit["label"]==raw_label and audit["original_files_written"] is False
        assert len(audit["records"])==324 and all(r["stat_unchanged"] for r in audit["records"])
        verify_references({k:v for k,v in audit.items() if k!="records"})
        audits.append(record(audit_path))
    return dict(cap=cap,scope=scope,proof=record(path),cases=len(found),raw_audits=audits,
        rows=list(found.values()),excluded_cases=excluded)


def corrected_results() -> list[dict]:
    """初回夜間と修正版日中を連結し、mini は修正版全場を別評価する。

    引数: なし。返り値: list[dict]。新しい金融再生はしない。
    """
    correction=control.module(HERE/"round2/control166r2.py","完了時訂正版166")
    correction.verify_round()
    correction.verify_stage("day_smoke")
    correction.verify_stage("day_full")
    correction.verify_stage("mini_full")
    night=reuse_group(HERE/"初回実行_full_cap100.json",100,"Night","full_cap100",True)
    day=reuse_group(HERE/"round2/実行166r2_day_full.json",100,"Day","r2_day_full_cap100")
    mini=reuse_group(HERE/"round2/実行166r2_mini_full.json",10,"All","r2_mini_full_cap10")
    assert night["cases"]==54 and day["cases"]==27 and mini["cases"]==81
    rows=day["rows"]+night["rows"]
    return [dict(cap=100,cases=81,session_count=54,original_equivalence=True,integer_granularity=False,
        events=sum(r["events"] for r in rows),rows=rows,proofs=[day["proof"],night["proof"]],
        raw_audits=day["raw_audits"]+night["raw_audits"],correction=record(correction.RECEIPT),
        initial_day_not_reused=night["excluded_cases"]),
        dict(cap=10,cases=81,session_count=54,original_equivalence=False,integer_granularity=True,
        events=sum(r["events"] for r in mini["rows"]),rows=mini["rows"],proofs=[mini["proof"]],
        raw_audits=mini["raw_audits"],correction=record(correction.RECEIPT))]


def validate(public_check: Path) -> dict:
    """正本同値・整数粒度・全試験・配布・公開の最終条件を確認する。

    引数: public_check(Path)。返り値: 検算済み証跡(dict)。台帳は更新しない。
    """
    corrected=(HERE/"round2/実装訂正受領166r2.json").exists()
    if not corrected:control.verify_receipt()
    public=read(public_check)
    assert public["passed"] is True and public["new_effectiveness_evidence"] is False
    assert public["conclusion"] and public["readme"] and public["files"]
    verify_references(public)
    checks={}
    for key in ("go_test","go_vet","distribution"):
        reference=public[key]
        proof=read(ROOT/reference["path"])
        successful(proof)
        assert verify_references(proof)>0, key+"には実ログ又は生成物の指紋が必要"
        checks[key]=reference
    initial=read(HERE/"audit/raw_inputs/全324原資料の事前SHA166.json")
    assert initial["passed"] and initial["files"]==324 and initial["original_files_written"] is False
    assert all(r["matches_registered_sha"] and r["unchanged_during_read"] for r in initial["records"])
    full=corrected_results() if corrected else [full_result(100),full_result(10)]
    return dict(passed=True,created_at=datetime.now().astimezone().isoformat(),
        registration=record(control.RECEIPT),initial_raw=record(HERE/"audit/raw_inputs/全324原資料の事前SHA166.json"),
        public_check=record(public_check),external_checks=checks,full_results=full,
        new_effectiveness_evidence=False,condition_changes=False,original_research_modified=False,implementation_corrected=corrected,
        note="cap100 の 81 手法場は正本同値、mini10 は別の整数粒度確認。移植検証を未見成績に数えない。")


def complete(public_check: Path) -> None:
    """当該試行だけを検証済みへ変更し、他行と元仕様を保持する。

    引数: public_check(Path)。返り値: None。金融再生・配布実行はしない。
    """
    assert not (HERE/"試行完了証跡166.json").exists()
    checked=validate(public_check)
    check_path=HERE/"完了前の独立検算166.json"
    assert not check_path.exists()
    public=read(public_check)
    manager=registry.manager()
    value=manager.load(deep=False)
    old_sha=value["source_sha256"]["trials.json"]
    rows=value["trials"]["trials"]
    matched=[r for r in rows if r["id"]==IDENT]
    assert len(matched)==1
    row=matched[0]
    assert row["status"]=="未実行"
    others=registry.old_rows(rows,{IDENT})
    previous_spec=canonical(row["spec"])
    registered_plan=read(ROOT/read(control.RECEIPT)["plan"]["path"])
    assert canonical(registered_plan["spec"])==previous_spec
    save(check_path,checked)
    # ----------------------------------------
    # 手法定義は変更せず、状態・公開リンク・検査根拠だけを追加する。
    row["status"]="検証済み"
    row["readme"]=public["readme"]["path"]
    if public.get("report"):row["report"]=public["report"]["path"]
    row["result_note"]=public["conclusion"]
    additional=public["files"]+[public["readme"],record(public_check),record(check_path),record(Path(__file__))]
    additional += [p for f in checked["full_results"] for p in (f["proofs"] if "proofs" in f else [f["proof"]])]
    additional += list(checked["external_checks"].values())
    seen={(e["path"],e.get("sha256")) for e in row.get("evidence",[])}
    row["evidence"]=list(row.get("evidence",[]))
    for evidence in additional:
        key=(evidence["path"],evidence.get("sha256"))
        if key not in seen:row["evidence"].append(evidence);seen.add(key)
    assert canonical(row["spec"])==previous_spec
    outcome=registry.write_registry(manager,value,old_sha,[row],others)
    save(HERE/"試行完了証跡166.json",dict(passed=True,status="検証済み",spec_unchanged=True,
        original_spec_sha256=previous_spec,completion_check=record(check_path),**outcome))
    print("00166 だけを検証済みへ更新しました。他試行と仕様は不変です。",flush=True)


def main() -> None:
    """検査のみと台帳更新を分け、明示した後者だけで状態を変更する。

    引数: CLI action(str)、--public-check(Path)。返り値: None。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["validate","complete"])
    parser.add_argument("--public-check",type=Path,default=HERE/"公開照合166.json")
    args=parser.parse_args()
    if args.action=="validate":
        validate(args.public_check);print("完了ゲート PASS。台帳は未変更です。")
    else:complete(args.public_check)


if __name__=="__main__":main()
