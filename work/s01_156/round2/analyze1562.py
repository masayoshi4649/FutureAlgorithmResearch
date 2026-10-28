"""00156第二巡の保存約定を独立再会計し、第一巡の固定結果と分離する。"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import numpy as np

BASE = Path(__file__).resolve().parent
FIRST = BASE.parent
sys.path.insert(0, str(FIRST))
from analyze156 import JST, analyze_case, compare_parents, equal, normal_indices, raw_quotes, summarize, write_json

CONTROLS = ("S01", "F05", "F09", "E07", "E08", "E09")


def old_evidence_preserved(previous: object, current: object) -> None:
    """追加診断キーだけを許し、元の判断根拠値を全て検査する。

    引数: previous/current(object)はJSON互換の値。
    返り値: なし。不一致はAssertionError。
    """
    if isinstance(previous,dict):
        assert isinstance(current,dict)
        for key,value in previous.items():
            assert key in current, "元の根拠キーが消失"
            old_evidence_preserved(value,current[key])
    elif isinstance(previous,list):
        assert isinstance(current,list) and len(previous)==len(current)
        for a,b in zip(previous,current):
            old_evidence_preserved(a,b)
    else:
        assert previous==current, "元の根拠値が変更"


def control_equal(current: dict, previous: dict) -> None:
    """変更していない6対照の全約定・会計・残玉を検査する。

    引数: current/previous(dict)は第二巡と第一巡の同条件。
    返り値: なし。不一致はAssertionError。
    """
    old, new = previous.get("events") or [], current.get("events") or []
    assert len(old) == len(new), "対照の約定数差"
    for a, b in zip(old, new):
        sa = {k:v for k,v in a["signal"].items() if k != "evidence"}
        sb = {k:v for k,v in b["signal"].items() if k != "evidence"}
        assert sa == sb, "対照の注文差"
        old_evidence_preserved(a["signal"].get("evidence"),b["signal"].get("evidence"))
        for field in ("fill", "decision_index", "fill_index", "gross"):
            assert a[field] == b[field], "対照の実約定差"+field
        assert a.get("pieces") == b.get("pieces"), "対照の配賦差"
    for field in ("Gross", "Unrealized", "entries", "parents", "last_quote"):
        assert current[field] == previous[field], "対照会計/時価差"+field
    def signals_only(values: list) -> list:
        """診断表示だけを除いた注文列を得る。

        引数: values(list)は通知配列。
        返り値: listは意味のある全注文属性。
        """
        return [{k:v for k,v in item.items() if k!="evidence"} for item in values or []]
    assert signals_only(current.get("signals")) == signals_only(previous.get("signals"))
    assert signals_only(current.get("final_pending")) == signals_only(previous.get("final_pending"))


def reentry_diagnostics(case: dict, detail: dict, raw: object) -> None:
    """再参加玉の初回逆行と旧源の停止線を、通常初回から分けて記録する。

    引数: case/detail(dict)は保存出力と独立明細、raw(ndarray)は原板。
    返り値: なし。detailへ診断を追記する。売買条件へは戻さない。
    """
    entries={e["fill"]["HoldID"]:e for e in case.get("events") or [] if e["signal"]["action"]=="new"}
    snapshots={s["Index"]:s for s in case.get("snapshots") or []}
    found=[]
    for lot in detail["lots"]:
        event=entries[lot["id"]]
        sig=event["signal"]
        lot["entry_reason"]=sig["reason_code"]
        lot["is_reentry1562"]=sig["reason_code"]==15630
        if not lot["is_reentry1562"]:
            continue
        diag=next((d for d in snapshots.get(sig["source_index"],{}).get("Diagnostics",[]) if d["owner"]==lot["owner"]),{})
        source=next((diag[k] for k in ("core_exit_shadow","active_exit","episode_exit") if k in diag),{})
        stop=source.get("stop_price")
        trail=source.get("trail_price")
        lot["source_stop_at_entry"]=stop
        lot["source_trail_at_entry"]=trail
        lot["source_anchor_at_entry"]=source.get("anchor")
        lot["entry_to_old_source_stop_points"]=lot["side"]*(lot["price"]-stop) if stop is not None else None
        lot["entry_to_old_source_trail_points"]=lot["side"]*(lot["price"]-trail) if trail is not None and trail>0 else None
        price_lines=[x for x in (stop,trail) if x is not None and x>0]
        effective=(max(price_lines) if lot["side"]>0 else min(price_lines)) if price_lines else None
        lot["source_price_floor_at_entry"]=effective
        lot["entry_to_source_price_floor_points"]=lot["side"]*(lot["price"]-effective) if effective is not None else None
        lot["entry_spread_points"]=float(raw[lot["entry_index"],3]-raw[lot["entry_index"],2])
        lot["decision_spread_points"]=float(raw[lot["decision_index"],3]-raw[lot["decision_index"],2])
        lot["ever_positive"]=lot["best_points"]>0
        lot["has_partial_close"]=len(lot["closes"])>1 or (len(lot["closes"])==1 and lot["remaining"]>0)
        found.append(lot)
    closed=[l for l in found if l["remaining"]==0]
    never=[l for l in closed if not l["ever_positive"]]
    summary={"entries":len(found),"quantity":sum(l["quantity"] for l in found),"net":sum(l["net"] for l in found),"unrealized":sum(l["unrealized"] for l in found),"closed_lots":len(closed),"never_positive_closed_lots":len(never),"never_positive_loss":sum(-min(0,l["net"]) for l in never),"maximum_adverse_points":max((-l["worst_points"] for l in found),default=0),"partial_close_lots":sum(l["has_partial_close"] for l in found),"partial_close_net":sum(l["net"] for l in found if l["has_partial_close"])}
    detail["reentry1562"]=summary
    detail["row"]["reentry1562"]=summary


def summarize_second(rows: list[dict]) -> dict:
    """同じ完結親会計へ、再参加玉の内訳だけを独立した欄で付ける。

    引数: rows(list[dict])は完了場の独立会計。
    返り値: dictは親集計と再参加の玉別内訳。両者を加算しない。
    """
    result=summarize(rows)
    keys=("entries","quantity","net","unrealized","closed_lots","never_positive_closed_lots","never_positive_loss","partial_close_lots","partial_close_net")
    result["reentry1562"]={key:sum(r["reentry1562"][key] for r in rows) for key in keys}
    result["reentry1562"]["maximum_adverse_points"]=max((r["reentry1562"]["maximum_adverse_points"] for r in rows),default=0)
    return result


def verify_reentry_evidence(case: dict, detail: dict, raw: object, valid: object) -> dict:
    """再参加の準備を実完済へ、発注極値を当時までの全正常原板へ照合する。

    引数: case/detail(dict)、raw/valid(ndarray)は保存結果・独立会計・原板。
    返り値: dictは検査件数。戦略や売買を再実行せず記録の数式を検算する。
    """
    state=case.get("reentry1562") or {}
    audits=state.get("Audit") or []
    signals=[s for s in case.get("signals") or [] if s["action"]=="new" and s["reason_code"]==15630]
    by_key={(s["owner"],s["campaign"],s["ticket"],s["source_index"]):s for s in signals}
    assert len(by_key)==len(signals)
    arms={}
    preparations=orders=cancellations=0
    for audit in audits:
        owner,index= audit["Owner"],audit["Index"]
        equal(raw[index,0],audit["Time"],"再参加監査時計")
        action=audit["Action"]
        if action in ("準備","発注"):
            location=int(np.searchsorted(valid,index))
            assert location<len(valid) and valid[location]==index,"再参加準備/発注が正常板でない"
        if action=="準備":
            held=0
            for lot in detail["lots"]:
                if lot["owner"]==owner and lot["entry_index"]<=index:
                    held+=lot["quantity"]-sum(c["quantity"] for c in lot["closes"] if c["index"]<=index)
            assert held==0,"実玉が残るのに再参加準備"
            exits=[e for e in case.get("events") or [] if e["fill_index"]==index and e["signal"]["owner"]==owner and e["signal"]["action"]=="close"]
            assert exits and all(e["signal"]["reason_code"] in (15601,15602) for e in exits),"元返済だけから再参加準備"
            assert owner not in arms,"待機を二重生成"
            arms[owner]=audit
            preparations+=1
        elif action=="取消":
            assert owner in arms,"準備のない取消"
            del arms[owner]
            cancellations+=1
        elif action=="発注":
            assert owner in arms,"準備のない再新規"
            prepared=arms.pop(owner)
            begin=int(np.searchsorted(valid,prepared["Index"],side="right"))
            end=int(np.searchsorted(valid,index,side="right"))
            selected=valid[begin:end]
            assert len(selected)>=2,"完済行又は極値初期化行で発注"
            side=audit["Side"]
            mark=raw[index,2 if side>0 else 3]
            prices=raw[selected,2 if side>0 else 3]
            extreme=float(np.min(prices) if side>0 else np.max(prices))
            equal(extreme,audit["Extreme"],"再参加の新極値")
            equal(mark,audit["Mark"],"再参加の判断気配")
            assert side*(mark-extreme)>=state["Width"],"指定幅未到達の再参加"
            assert prepared["Quantity"]==audit["Quantity"] and prepared["Campaign"]==audit["Campaign"] and prepared["Side"]==side
            key=(owner,audit["Campaign"],audit["Ticket"],index)
            assert key in by_key,"監査発注と実通知の不一致"
            signal=by_key.pop(key)
            assert signal["quantity"]==audit["Quantity"] and signal["side"]==side and audit["Ticket"]<0
            target=state["Targets"][str(audit["Ticket"])]
            assert target["Requested"]==signal["quantity"] and target["Owner"]==owner and target["Campaign"]==signal["campaign"]
            orders+=1
        else:
            raise AssertionError("未知の再参加監査種類")
    assert not by_key,"監査記録のない再参加発注"
    assert set(arms)==set(state.get("Arms") or {}),"保存された待機数と監査数の不一致"
    return {"preparations":preparations,"orders":orders,"cancellations":cancellations,"remaining_arms":len(arms),"raw_extremes_matched":orders}


def main() -> None:
    """完成した第二巡18条件×27場を読み、独立会計と38手法の統合表を作る。

    引数: CLI --results(Path)、--configs(Path)は第二巡専用位置。
    返り値: なし。原結果・第一巡reportは変更しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=BASE/"results_go")
    parser.add_argument("--configs", type=Path, default=BASE/"configs1562.json")
    args = parser.parse_args()
    scenes = json.loads((FIRST/"inputs156.json").read_text(encoding="utf-8"))["sessions"]
    configs = json.loads(args.configs.read_text(encoding="utf-8"))
    assert len(scenes)==27 and len(configs)==18
    assert {c["id"] for c in configs if c["id"] in CONTROLS} == set(CONTROLS)
    first_report_path = FIRST/"report156.json"
    first_payload = first_report_path.read_bytes()
    first_sha = hashlib.sha256(first_payload).hexdigest()
    first_report = json.loads(first_payload)
    paths = [args.results/(s["session"]+"_S01.json") for s in scenes]
    if not all(p.exists() for p in paths):
        raise SystemExit("第二巡27結果が完成する前の分析はしません")
    rows, comparisons, direct_comparisons = defaultdict(list), defaultdict(list), defaultdict(list)
    partial, audits = [], []
    total, control_count, reentry_evidence_count = 0, 0, 0
    for scene,path in zip(scenes,paths):
        payload = path.read_bytes()
        before = hashlib.sha256(payload).hexdigest()
        saved = json.loads(payload)
        oldpath = FIRST/"results_go"/path.name
        old_payload = oldpath.read_bytes()
        old_sha = hashlib.sha256(old_payload).hexdigest()
        oldcases = {c["config"]["id"]:c for c in json.loads(old_payload)["cases"]}
        assert len(saved["cases"])==18
        raw,fingerprint = raw_quotes(scene)
        valid = normal_indices(raw)
        details = {}
        for case,cfg in zip(saved["cases"],configs):
            assert case["config"]==cfg
            for key,value in fingerprint["counts"].items():
                equal(case["counts"].get("NK225_"+key,0),value,scene["session"]+key)
            if cfg["id"] in CONTROLS:
                control_equal(case,oldcases[cfg["id"]])
                control_count += 1
            row,detail = analyze_case(case,scene,raw,valid)
            reentry_diagnostics(case,detail,raw)
            detail["reentry_evidence"]=verify_reentry_evidence(case,detail,raw,valid)
            reentry_evidence_count+=detail["reentry_evidence"]["raw_extremes_matched"]
            details[cfg["id"]] = detail
            if scene["partial"]:
                partial.append(row)
            else:
                rows[cfg["id"]].append(row)
            write_json(BASE/"audit"/"cases"/scene["session"]/(cfg["id"]+".json"),detail)
            total += 1
        if not scene["partial"]:
            for cfg in configs:
                if cfg["id"] not in CONTROLS:
                    comparisons[cfg["id"]].append(compare_parents(details["S01"],details[cfg["id"]]))
                    direct=compare_parents(details[cfg["control"]],details[cfg["id"]])
                    direct["control"]=cfg["control"]
                    direct_comparisons[cfg["id"]].append(direct)
        assert before==hashlib.sha256(path.read_bytes()).hexdigest()
        assert old_sha==hashlib.sha256(oldpath.read_bytes()).hexdigest()
        audits.append({"session":scene["session"],"result_sha256":before,"first_result_sha256":old_sha,"saved_control_cases":6,"raw":fingerprint,"unchanged":True})
        print(json.dumps({"session":scene["session"],"checked":total},ensure_ascii=True),flush=True)
    methods=[]
    for cfg in configs:
        rr=rows[cfg["id"]]
        assert len(rr)==26
        methods.append({"id":cfg["id"],"description":cfg["description"],"config":cfg,"rows":rr,"summary":summarize_second(rr),"up":summarize_second([r for r in rr if r["direction"]=="上昇"]),"down":summarize_second([r for r in rr if r["direction"]=="下落"]),"flat":summarize_second([r for r in rr if r["direction"]=="横ばい"])})
    assert total==486 and control_count==162 and len(partial)==18
    report={"created_at":datetime.now(JST).isoformat(),"scope":"第二巡18条件・26完了Day＋1途中Day","methods":methods,"current_rows":partial,"partial":partial,"case_count":total,"first_report_sha256":first_sha,"validation":{"case_accounting_matches":total,"saved_control_cases":control_count,"raw_nk_sha_matches":27,"all_fills_next_normal_raw":True,"lots_parents_extrema_from_all_raw":True,"reserved_caps":True,"source_results_unchanged":True,"first_report_unchanged":True,"reentry_raw_extremes_matches":reentry_evidence_count,"all_reentry_evidence_valid":True},"source_sha256":audits}
    assert first_sha==hashlib.sha256(first_report_path.read_bytes()).hexdigest()
    write_json(BASE/"report1562.json",report)
    write_json(BASE/"audit"/"comparisons1562.json",dict(comparisons))
    write_json(BASE/"audit"/"direct_comparisons1562.json",dict(direct_comparisons))
    newmethods=[m for m in methods if m["id"] not in CONTROLS]
    newpartial=[r for r in partial if r["id"] not in CONTROLS]
    combined={**first_report,"created_at":datetime.now(JST).isoformat(),"scope":"第一巡26＋第二巡新12＝38条件・26完了Dayと1途中Day。対照6を重複計上しない。","methods":first_report["methods"]+newmethods,"current_rows":first_report["current_rows"]+newpartial,"partial":first_report["partial"]+newpartial,"first_report_sha256":first_sha,"round2_report_sha256":hashlib.sha256((BASE/"report1562.json").read_bytes()).hexdigest(),"validation_round2":report["validation"]}
    assert len(combined["methods"])==38 and len(combined["current_rows"])==38
    assert len({m["id"] for m in combined["methods"]})==38
    write_json(FIRST/"report156_all.json",combined)
    print(json.dumps({"complete":True,"cases":total,"controls":control_count,"combined_methods":38},ensure_ascii=True),flush=True)


if __name__=="__main__":
    main()
