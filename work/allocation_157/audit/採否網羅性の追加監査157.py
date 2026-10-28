"""全採否行の支持照合に加え、元親の取り落としと採否条件を検算する。"""

from pathlib import Path
import hashlib
import json
import math

BASE=Path(__file__).resolve().parents[1]


def main() -> None:
    """金融監査完了を確認し、採否網羅性と監査コード指紋を同じ証跡に追記する。

    引数: なし。返り値: None。保存売買結果だけを読み、金融再生は実行しない。
    """
    target=BASE/"金融監査157.json"
    proof=json.loads(target.read_text(encoding="utf-8"))
    assert proof["passed"] and proof["totals"]["known_support_checks"]>0 and proof["totals"]["unknown_support_checks"]>0
    initial_checks=0;quantity_checks=0;filtered={"known_accept":0,"known_reject":0,"unknown_reject":0};source_parents=0
    for path in sorted((BASE/"results_go").glob("*.json")):
        result=json.loads(path.read_text(encoding="utf-8"));cases={c["config"]["id"]:c for c in result["cases"]}
        origins={}
        for event in cases["C00"]["actual"]["Events"] or []:
            order=event["Order"]
            if not order.get("Targets") and order["Parent"] not in origins:
                origins[order["Parent"]]=(order["DecisionIndex"],order["DecisionTime"],order["Side"])
        source_parents+=len(origins)
        for identifier,case in cases.items():
            if identifier=="C00":continue
            initial=[d for d in case["decisions"] or [] if d["Action"]=="初回拒否" or d["Reason"]=="initial"]
            assert len(initial)==len(origins)==case["counts"]["source_initial"]
            assert {d["Parent"] for d in initial}==set(origins)
            for decision in initial:
                parent=case["parents"][decision["Parent"]];s=decision["Support"];config=case["config"]
                assert (decision["Index"],decision["Time"],parent["Side"])==origins[decision["Parent"]]
                expected=""
                if config["Filter"]:
                    if not s["Known"]:expected="指標未知"
                    elif s["M"]<.25 or s["T"]<.25:expected="支持閾値"
                    elif parent["Side"]*s["Own15"]<=0 or parent["Side"]*s["Own5"]<0:expected="速度符号"
                if expected:
                    assert decision["Action"]=="初回拒否" and decision["Reason"]==expected and decision["Quantity"]==0
                else:
                    assert decision["Action"]=="新規判断" and decision["Reason"]=="initial"
                    raw=parent["OldInitial"] if config["Fixed"] else 100*(s["M"]*s["T"])**config["Power"]
                    wanted=math.floor(raw/config["Quantum"]+1e-10)*config["Quantum"]
                    assert 0<decision["Quantity"]<=wanted
                    quantity_checks+=1
                if identifier=="B01":
                    filtered["unknown_reject" if not s["Known"] else "known_reject" if expected else "known_accept"]+=1
                initial_checks+=1
    assert source_parents==166 and initial_checks==166*22
    proof["initial_source_parents"]=source_parents
    proof["initial_decision_checks"]=initial_checks
    proof["accepted_initial_quantity_checks"]=quantity_checks
    proof["one_filter_all27_initial"]=filtered
    proof["checks"]["all_source_initial_decisions_present"]=True
    proof["checks"]["initial_filter_reason_and_quantity"]=True
    proof["independent_audit_correction"]={"reason":"監査器のDecisions/decisionsキー誤記により支持照合が0件だった初稿ゲートを撤回し、正しい必須キーで全原板を再読した。金融結果・登録源は変更していない。","regression_tests":2,"zero_support_checks_rejected":True}
    proof["audit_code_fingerprints"]=[]
    for name in ("結果の全原板監査157.py","raw_result157.py","test_saved_support157.py","採否網羅性の追加監査157.py"):
        p=BASE/"audit"/name
        proof["audit_code_fingerprints"].append({"path":str(p),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()})
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"passed":True,"initial_checks":initial_checks,"initial_filtered":filtered,"sha256":hashlib.sha256(target.read_bytes()).hexdigest()},ensure_ascii=False))


if __name__=="__main__":
    main()
