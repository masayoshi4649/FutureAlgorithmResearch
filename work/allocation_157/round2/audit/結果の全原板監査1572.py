"""第2巡の保存結果を全原板・独立所有台帳で検算する。新金融再生は行わない。"""

from collections import defaultdict
from pathlib import Path
from datetime import datetime
import importlib.util
import hashlib
import json
import math
import sys
import traceback
import numpy as np

BASE=Path(__file__).resolve().parents[1]
FIRST=BASE.parent
ROOT=BASE.parents[2]
PREVIOUS=FIRST.parent/"s01_156"
sys.path.insert(0,str(FIRST/"audit"))
sys.path.insert(0,str(BASE/"audit"))
from raw_result157 import close,read_market,support_arrays,raw_risk,reserved_cap
from raw_result1572 import support_at1572
spec=importlib.util.spec_from_file_location("audit157",FIRST/"audit/結果の全原板監査157.py")
prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)


def read(path: Path) -> dict:
    """保存JSONをUTF-8で読み取る。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path,value: dict) -> None:
    """監査証跡だけを保存する。

    引数: path(Path)、value(dict)。返り値: None。
    """
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")


def reference(path: Path) -> dict:
    """原資料と結果の内容指紋を作る。

    引数: path(Path)。返り値: dictは相対位置とSHA256。
    """
    return {"path":path.relative_to(ROOT).as_posix(),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}


def check_support(case: dict,own: dict,peer: dict,cache: dict) -> dict:
    """全保存採否の支持・個別既知・過去端を独立値へ照合する。

    引数: case/own/peer/cache(dict)。返り値: dictは既知と未知の照合数。
    """
    assert "decisions" in case,"採否列なし"
    counts=defaultdict(int)
    for decision in case["decisions"] or []:
        index=decision["Index"];side=case["parents"][decision["Parent"]]["Side"];key=(index,side)
        if key not in cache:cache[key]=support_at1572(own,peer,index,side)
        actual=decision["Support"];expected=cache[key]
        assert actual["Known"]==expected["Known"],(case["config"]["id"],decision,expected)
        for field in ("OwnAt","PeerAt","Own5","Own15","Own120","Own300","Peer120","OFI30","M","T","Opp"):
            close(actual[field],expected[field],"第2巡支持:"+field,1e-7)
        saved=actual["components"];want=expected["components"]
        for field in ("OwnKnown","PeerKnown","OFIKnown"):assert saved[field]==want[field],(field,decision,want)
        assert set(saved["Windows"])==set(want["Windows"])
        for name,value in want["Windows"].items():
            observed=saved["Windows"][name];assert observed["Known"]==value["Known"]
            for field in ("CurrentAt","EndpointAt","Elapsed","Delay","RawReturn","Value","IntermediateBad"):
                close(observed[field],value[field],"第2巡端点:"+name+":"+field,1e-7)
        counts["known" if expected["Known"] else "unknown"]+=1
        counts["peer_known" if want["PeerKnown"] else "peer_unknown"]+=1
        counts["ofi_known" if want["OFIKnown"] else "ofi_unknown"]+=1
    return dict(counts)


def canonical_equity_at(case: dict,raw: np.ndarray,index: int) -> float:
    """保存実約定の現金列と数量から判断原行のCanonical時価を計算する。

    引数: case(dict)、raw(ndarray)、index(int)。返り値: floatは円建て清算時価。
    """
    cash=0.;long=short=0
    for event in case["canonical"]["Events"] or []:
        if event["FillIndex"]>index:break
        order=event["Order"];side=order["Side"];q=order["Quantity"]
        cash-=side*q*event["Price"]
        if order.get("Targets"):
            if side==1:short-=q
            else:long-=q
        elif side==1:long+=q
        else:short+=q
    return (cash+long*raw[index,2]-short*raw[index,3])*10


def check_initial(case: dict,origins: dict,raw: np.ndarray) -> dict:
    """元初回親を全件照合し、フィルタ・最低量・固定量・D倍率を検算する。

    引数: case/origins(dict)、raw(ndarray)。返り値: dictは採否件数。
    """
    if case["config"]["id"]=="C00":return {"initial_checks":0,"accepted":0,"rejected":0}
    initial=[d for d in case["decisions"] or [] if d["Action"]=="初回拒否" or d["Reason"]=="initial"]
    assert len(initial)==len(origins)==case["counts"]["source_initial"]
    assert {d["Parent"] for d in initial}==set(origins)
    accepted=rejected=0
    for d in initial:
        c=case["config"];p=case["parents"][d["Parent"]];s=d["Support"]
        assert (d["Index"],d["Time"],p["Side"])==origins[d["Parent"]]
        expected=""
        if c["Filter"]:
            if not s["Known"]:expected="指標未知"
            elif s["M"]<.25 or s["T"]<.25:expected="支持閾値"
            elif p["Side"]*s["Own15"]<=0 or p["Side"]*s["Own5"]<0:expected="速度符号"
        if d["Reason"]=="場停止":assert c["SessionSave"] and case["stopped"]
        elif expected:assert d["Action"]=="初回拒否" and d["Reason"]==expected
        if d["Action"]=="初回拒否":
            assert d["Quantity"]==0;rejected+=1;continue
        assert not expected
        if c["Fixed"]:quantity=p["OldInitial"]
        elif c.get("initial_fixed",0)>0:quantity=c["initial_fixed"]
        else:
            score=s["M"]*s["T"] if s["Known"] else 0
            minimum=c.get("minimum",0)
            quantity=minimum+(100-minimum)*score**c["Power"]
        if c["SessionSave"]:quantity*=min(1,max(0,(160000+canonical_equity_at(case,raw,d["Index"]))/80000))
        wished=math.floor(quantity/c["Quantum"]+1e-10)*c["Quantum"]
        assert 0<d["Quantity"]<=wished,(c["id"],d,wished)
        assert p["InitialQty"]==d["Quantity"]
        accepted+=1
    return {"initial_checks":len(initial),"accepted":accepted,"rejected":rejected}


def main() -> None:
    """登録済み金融実行の完了後だけ、全1080条件場を独立再検算する。

    引数: なし。返り値: None。新しい売買判断を再生せず、保存約定と原板の整合を確認する。
    """
    target=BASE/"金融監査1572.json"
    proof={"passed":False,"case_count":0,"started_at":datetime.now().astimezone().isoformat(),"new_financial_replays":0}
    try:
        record=read(BASE/"金融実行1572.json")
        assert record["終了コード"]==0 and record["参照改変数"]==0 and record["結果ファイル数"]==27
        files=sorted((BASE/"results_go").glob("*.json"));assert len(files)==27
        before=[reference(p) for p in files];totals=defaultdict(int);scenes=[]
        for scene in read(PREVIOUS/"inputs156.json")["sessions"]:
            name=scene["session"];cases={c["config"]["id"]:c for c in read(BASE/"results_go"/(name+"_S01.json"))["cases"]};assert len(cases)==40
            old=read(FIRST/"results_go"/(name+"_S01.json"));first=next(c for c in old["cases"] if c["config"]["id"]=="C00")
            assert cases["C00"]==first,"初巡C00の全保存内容と不一致"
            old=read(PREVIOUS/"results_go"/(name+"_S01.json"));s01=next(c for c in old["cases"] if c["config"]["id"]=="S01")
            control=prior.exact_control(cases["C00"],s01);totals["baseline_events"]+=control["events"]
            origins={}
            for e in cases["C00"]["actual"]["Events"] or []:
                o=e["Order"]
                if not o.get("Targets") and o["Parent"] not in origins:origins[o["Parent"]]=(o["DecisionIndex"],o["DecisionTime"],o["Side"])
            totals["initial_source_parents"]+=len(origins)
            raw,raw_reference=read_market(scene,"NK225");other,peer_reference=read_market(scene,"TOPIX")
            own,peer=support_arrays(raw),support_arrays(other);cache={};rows=[];paths={}
            for identifier,case in cases.items():
                keep=identifier in ("V_Q05","V_Q08","V_H05","V_H08","J10","J12")
                risk=raw_risk(raw,case["actual"],scene["start"],keep)
                if "_path" in risk:paths[identifier]=risk.pop("_path")
                caps={"actual":reserved_cap(case["actual"]),"canonical":reserved_cap(case["canonical"])}
                supports=check_support(case,own,peer,cache);initial=check_initial(case,origins,raw)
                rows.append({"id":identifier,"risk":risk,"caps":caps,"supports":supports,"initial":initial})
                totals["cases"]+=1;totals["events"]+=risk["event_checks"];totals["normal_quote_checks"]+=risk["normal_rows"]
                for key,value in supports.items():totals["supports_"+key]+=value
                for key,value in initial.items():totals[key]+=value
            projections={q:prior.compare_projection(cases[q],cases[h],paths[q],paths[h],raw) for q,h in (("V_Q05","V_H05"),("V_Q08","V_H08"),("J10","J12"))}
            summary={"session":name,"partial":scene["partial"],"raw":[raw_reference,peer_reference],"baseline":control,"rows":rows,"projection":projections}
            save(BASE/"audit/金融結果"/(name+".json"),summary);scenes.append(summary)
            print(json.dumps({"session":name,"passed":True,"cases":40,"known_supports":sum(x["supports"].get("known",0) for x in rows),"unknown_supports":sum(x["supports"].get("unknown",0) for x in rows)},ensure_ascii=False),flush=True)
        after=[reference(p) for p in files];assert before==after
        assert totals["cases"]==1080 and totals["initial_source_parents"]==166 and totals["initial_checks"]==166*39
        assert totals["supports_known"]>0 and totals["supports_unknown"]>0,"支持検算が未実行"
        proof.update(passed=True,case_count=1080,totals=dict(totals),result_fingerprints=after,results_unchanged=True,old_s01_control_cases=27,h_n_pairs=81,input_raw_fingerprints=[f for scene in scenes for f in scene["raw"]])
        proof["checks"]={"all_source_initial_present":True,"source_initial_filter_and_quantity":True,"initial_minimum_scaled":True,"c00_all_output_exact_to_first":True,"old_s01_all_events_exact":True,"quantity_cap_including_pending":True,"next_normal_large_bbo":True,"all_raw_equity_risk":True,"raw_support_and_components":True,"past_normal_endpoint_no_future":True,"h_n_canonical_equal":True,"h_n_parent_net_equal":True,"h_n_cashflow_bbo_identity":True,"partial_not_liquidated":True}
        proof["audit_fingerprints"]=[reference(p) for p in (Path(__file__),BASE/"audit/raw_result1572.py",FIRST/"audit/raw_result157.py",FIRST/"audit/結果の全原板監査157.py")]
        proof["metadata_audit_note"]="登録済み検算器の全履歴参照は保持外の未知端にもメタデータを付けたため、事後監査用コピーにGoの340秒保持を反映。双方未知であり売買判断・原結果に変更なし。"
        proof["finished_at"]=datetime.now().astimezone().isoformat();save(target,proof)
    except Exception as error:
        proof.update(error=repr(error),traceback=traceback.format_exc(),finished_at=datetime.now().astimezone().isoformat());save(target,proof);raise


if __name__=="__main__":
    main()
