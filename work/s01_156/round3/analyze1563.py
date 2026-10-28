"""第3巡の局所停止6案と旧対照3案を、保存約定から独立再会計する。"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE=Path(__file__).resolve().parent
FIRST=BASE.parent
SECOND=FIRST/"round2"
sys.path.insert(0,str(FIRST))
sys.path.insert(0,str(SECOND))
from analyze156 import JST,analyze_case,compare_parents,equal,normal_indices,raw_quotes,write_json
from analyze1562 import control_equal,reentry_diagnostics,summarize_second,verify_reentry_evidence

CONTROLS=("S01","R01","R04")


def local_stop_evidence(case: dict, detail: dict, raw: object) -> dict:
    """局所停止が再参加の実建値から判断されたことと約定後の損失を分ける。

    引数: case/detail(dict)、raw(ndarray)は保存出力・独立台帳・原板。
    返り値: dictは理由15631の判断数、枚数、実損失など。
    """
    width=case["config"].get("local_stop",0)
    lots={l["id"]:l for l in detail["lots"]}
    out={"orders":0,"allocations":0,"quantity":0,"net":0,"decision_net":0,"fill_minus_decision":0,"never_positive_allocations":0,"after_positive_allocations":0}
    for event in case.get("events") or []:
        signal=event["signal"]
        if signal["action"]!="close" or signal["reason_code"]!=15631:
            continue
        assert width in (20,40,80)
        out["orders"]+=1
        for target in event["fill"]["Closed"]:
            lot=lots[target["id"]]
            assert lot["is_reentry1562"],"局所stopが初回玉を閉じた"
            mark=raw[event["decision_index"],2 if lot["side"]>0 else 3]
            gain=lot["side"]*(mark-lot["price"])
            assert gain<=-width,"局所stop距離未到達"
            q=target["quantity"]
            decision=gain*q*100
            realized=lot["side"]*(event["fill"]["Price"]-lot["price"])*q*100
            out["allocations"]+=1
            out["quantity"]+=q
            out["net"]+=realized
            out["decision_net"]+=decision
            out["fill_minus_decision"]+=realized-decision
            out["never_positive_allocations"]+=not lot["ever_positive"]
            out["after_positive_allocations"]+=lot["ever_positive"]
    detail["local_stop1563"]=out
    detail["row"]["local_stop1563"]=out
    return out


def compare_reentry_lots(baseline: dict, candidate: dict) -> dict:
    """局所停止で消えた将来の再参加と、同じ入口の退出変更を分ける。

    引数: baseline/candidate(dict)は元Rと局所停止案の独立台帳。
    返り値: dictは再参加玉だけの差分恒等式。全親会計へ重ねて加算しない。
    """
    key=lambda l:(l["owner"],l["side"],l["decision_index"])
    b={key(l):l for l in baseline["lots"] if l["is_reentry1562"]}
    c={key(l):l for l in candidate["lots"] if l["is_reentry1562"]}
    missing=[b[k] for k in b.keys()-c.keys()]
    added=[c[k] for k in c.keys()-b.keys()]
    shared=[{"key":list(k),"base_net":b[k]["net"],"candidate_net":c[k]["net"],"delta":c[k]["net"]-b[k]["net"],"base_quantity":b[k]["quantity"],"candidate_quantity":c[k]["quantity"],"base_entry_time":b[k]["entry_time"]} for k in b.keys()&c.keys()]
    delta=sum(l["net"] for l in added)-sum(l["net"] for l in missing)+sum(l["delta"] for l in shared)
    equal(delta,sum(l["net"] for l in c.values())-sum(l["net"] for l in b.values()),"再参加玉差分恒等式")
    return {"session":baseline["row"]["session"],"id":candidate["row"]["id"],"control":baseline["row"]["id"],"delta":delta,"lost_win":sum(max(0,l["net"]) for l in missing),"avoided_loss":sum(-min(0,l["net"]) for l in missing),"added_net":sum(l["net"] for l in added),"same_entry_delta":sum(l["delta"] for l in shared),"missing":missing,"added":added,"shared":shared}


def summarize_third(rows: list[dict]) -> dict:
    """完結親会計を保ったまま、局所停止配賦の件数・損失を別欄へ集計する。

    引数: rows(list[dict])は完了場の行。
    返り値: dictは親・再参加玉・局所停止配賦を区別した集計。
    """
    result=summarize_second(rows)
    keys=("orders","allocations","quantity","net","decision_net","fill_minus_decision","never_positive_allocations","after_positive_allocations")
    result["local_stop1563"]={key:sum(r["local_stop1563"][key] for r in rows) for key in keys}
    return result


def main() -> None:
    """完了した9条件×27場を検算し、第一・第二報告を固定して44手法へ統合する。

    引数: なし。入力は同じinputs156、結果は第3巡専用位置。
    返り値: なし。金融戦略を再実行せず、未完了結果では停止する。
    """
    execution=json.loads((BASE/"金融実行1563.json").read_text(encoding="utf-8"))
    assert execution["終了コード"]==0 and execution["参照改変数"]==0 and execution["結果ファイル数"]==27
    scenes=json.loads((FIRST/"inputs156.json").read_text(encoding="utf-8"))["sessions"]
    configs=json.loads((BASE/"configs1563.json").read_text(encoding="utf-8"))
    assert len(scenes)==27 and len(configs)==9
    reports=[FIRST/"report156.json",SECOND/"report1562.json"]
    original_sha={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in reports}
    previous=json.loads((FIRST/"report156_all.json").read_text(encoding="utf-8"))
    assert len(previous["methods"])==38,"第三巡統合済みを上書きしない"
    rows=defaultdict(list)
    comparisons,direct_comparisons,lot_comparisons=defaultdict(list),defaultdict(list),defaultdict(list)
    partial,audits=[],[]
    cases=controls=reentries=0
    for scene in scenes:
        path=BASE/"results_go"/(scene["session"]+"_S01.json")
        oldpath=SECOND/"results_go"/path.name
        data,old_data=path.read_bytes(),oldpath.read_bytes()
        sha,old_sha=hashlib.sha256(data).hexdigest(),hashlib.sha256(old_data).hexdigest()
        saved=json.loads(data)
        oldcases={c["config"]["id"]:c for c in json.loads(old_data)["cases"]}
        assert len(saved["cases"])==9
        raw,fingerprint=raw_quotes(scene)
        valid=normal_indices(raw)
        details={}
        for case,cfg in zip(saved["cases"],configs):
            assert case["config"]==cfg
            for key,value in fingerprint["counts"].items():
                equal(case["counts"].get("NK225_"+key,0),value,scene["session"]+key)
            if cfg["id"] in CONTROLS:
                control_equal(case,oldcases[cfg["id"]])
                controls+=1
            row,detail=analyze_case(case,scene,raw,valid)
            reentry_diagnostics(case,detail,raw)
            local_stop_evidence(case,detail,raw)
            detail["reentry_evidence"]=verify_reentry_evidence(case,detail,raw,valid)
            reentries+=detail["reentry_evidence"]["raw_extremes_matched"]
            details[cfg["id"]]=detail
            if scene["partial"]:
                partial.append(row)
            else:
                rows[cfg["id"]].append(row)
            write_json(BASE/"audit/cases"/scene["session"]/(cfg["id"]+".json"),detail)
            cases+=1
        if not scene["partial"]:
            for cfg in configs:
                if cfg["id"] not in CONTROLS:
                    comparisons[cfg["id"]].append(compare_parents(details["S01"],details[cfg["id"]]))
                    reference=cfg.get("control") or ("R01" if int(cfg["id"][1:])<=3 else "R04")
                    direct=compare_parents(details[reference],details[cfg["id"]])
                    direct["control"]=reference
                    direct_comparisons[cfg["id"]].append(direct)
                    lot_comparisons[cfg["id"]].append(compare_reentry_lots(details[reference],details[cfg["id"]]))
        assert sha==hashlib.sha256(path.read_bytes()).hexdigest()
        assert old_sha==hashlib.sha256(oldpath.read_bytes()).hexdigest()
        audits.append({"session":scene["session"],"result_sha256":sha,"previous_result_sha256":old_sha,"raw":fingerprint,"unchanged":True})
        print(json.dumps({"session":scene["session"],"checked":cases},ensure_ascii=True),flush=True)
    methods=[]
    for cfg in configs:
        rr=rows[cfg["id"]]
        assert len(rr)==26
        methods.append({"id":cfg["id"],"description":cfg["description"],"config":cfg,"rows":rr,"summary":summarize_third(rr),"up":summarize_third([r for r in rr if r["direction"]=="上昇"]),"down":summarize_third([r for r in rr if r["direction"]=="下落"]),"flat":summarize_third([r for r in rr if r["direction"]=="横ばい"])})
    assert cases==243 and controls==81 and len(partial)==9
    assert all(sha==hashlib.sha256(Path(p).read_bytes()).hexdigest() for p,sha in original_sha.items())
    report={"created_at":datetime.now(JST).isoformat(),"scope":"第三巡9条件・26完了Dayと1途中Day","methods":methods,"current_rows":partial,"partial":partial,"case_count":cases,"prior_report_sha256":original_sha,"validation":{"case_accounting_matches":cases,"saved_control_cases":controls,"raw_nk_sha_matches":27,"all_fills_next_normal_raw":True,"lots_parents_extrema_from_all_raw":True,"reserved_caps":True,"source_results_unchanged":True,"prior_reports_unchanged":True,"reentry_raw_extremes_matches":reentries,"all_reentry_evidence_valid":True},"source_sha256":audits}
    write_json(BASE/"report1563.json",report)
    write_json(BASE/"audit/comparisons1563.json",dict(comparisons))
    write_json(BASE/"audit/direct_comparisons1563.json",dict(direct_comparisons))
    write_json(BASE/"audit/reentry_lot_comparisons1563.json",dict(lot_comparisons))
    new_methods=[m for m in methods if m["id"] not in CONTROLS]
    new_partial=[r for r in partial if r["id"] not in CONTROLS]
    combined={**previous,"created_at":datetime.now(JST).isoformat(),"scope":"第一巡26＋第二巡新12＋第三巡新6＝44手法。26完了Dayと1途中Day。対照を重複計上しない。","methods":previous["methods"]+new_methods,"current_rows":previous["current_rows"]+new_partial,"partial":previous["partial"]+new_partial,"round3_report_sha256":hashlib.sha256((BASE/"report1563.json").read_bytes()).hexdigest(),"validation_round3":report["validation"]}
    combined.update(case_count=1188,unique_condition_cases=1188,evaluated_condition_cases_with_controls=1431)
    assert len(combined["methods"])==44 and len({m["id"] for m in combined["methods"]})==44 and len(combined["current_rows"])==44
    write_json(FIRST/"report156_all.json",combined)
    print(json.dumps({"complete":True,"cases":cases,"controls":controls,"combined_methods":44},ensure_ascii=True),flush=True)


if __name__=="__main__":
    main()
