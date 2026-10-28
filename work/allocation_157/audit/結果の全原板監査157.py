"""登録済み金融実行の保存結果を独立検算する。新しい売買条件は再生しない。"""

from __future__ import annotations
from collections import defaultdict
from pathlib import Path
from datetime import datetime
import hashlib
import json
import traceback
import numpy as np
from raw_result157 import close, read_market, normal_mask, support_arrays, support_at, raw_risk, reserved_cap

BASE=Path(__file__).resolve().parents[1]
ROOT=BASE.parents[1]
PREVIOUS=BASE.parent/"s01_156"


def read(path: Path) -> dict:
    """保存JSONをUTF-8で読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def reference(path: Path) -> dict:
    """監査対象を全内容指紋で固定する。

    引数: path(Path)。返り値: dictは位置・SHA256・サイズ。
    """
    with path.open("rb") as stream: digest=hashlib.file_digest(stream,"sha256").hexdigest()
    return {"path":path.relative_to(ROOT).as_posix(),"sha256":digest,"bytes":path.stat().st_size}


def save(path: Path, value: dict) -> None:
    """原資料を変えず監査証跡だけを保存する。

    引数: path(Path)、value(dict)。返り値: None。
    """
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")


def exact_control(case: dict, previous: dict) -> dict:
    """C00を旧S01の同額数量・所有対象・判断/約定原行へ照合する。

    引数: case/previous(dict)。返り値: dictは全約定照合数。
    """
    actual=case["actual"];new=actual.get("Events") or [];old=previous.get("events") or [];assert len(new)==len(old)
    for a,b in zip(new,old):
        o=a["Order"];s=b["signal"];f=b["fill"]
        assert (o["ID"],o["Owner"],o["Campaign"],o["Side"],o["Quantity"],o["DecisionIndex"],a["FillIndex"])==(s["id"],s["owner"],s["campaign"],s["side"],10*s["quantity"],b["decision_index"],b["fill_index"])
        close(o["DecisionTime"],s["time"],"旧判断時刻");close(a["FillTime"],f["Time"],"旧約定時計");close(a["Price"],f["Price"],"旧価格");close(a["Gross"],b["gross"],"旧金額")
        assert [(x["ID"],x["Quantity"]) for x in o.get("Targets") or []]==[(x["id"],10*x["quantity"]) for x in s.get("targets") or []]
    pending=actual.get("Pending") or [];prior=previous.get("final_pending") or [];assert len(pending)==len(prior)
    for a,b in zip(pending,prior):
        assert (a["ID"],a["Side"],a["Quantity"],a["DecisionIndex"])==(b["id"],b["side"],10*b["quantity"],b["source_index"])
    close(actual["Realized"],previous["Gross"],"旧全確定")
    close(actual["Last"]["Unrealized"],previous["Unrealized"],"旧全含み")
    return {"passed":True,"events":len(new),"pending":len(pending)}


def check_support(case: dict, own: dict, peer: dict, cache: dict) -> dict:
    """保存した採否原行の支持を原板から再計算する。

    引数: case/own/peer/cache(dict)。返り値: dictは既知/未知の照合数。
    """
    counts={"known":0,"unknown":0}
    assert "decisions" in case, "保存採否列がないため支持を検査できない"
    for decision in case["decisions"] or []:
        i=decision["Index"];side=case["parents"][decision["Parent"]]["Side"];key=(i,side)
        if key not in cache: cache[key]=support_at(own,peer,i,side)
        expected=cache[key];saved=decision["Support"]
        assert bool(saved["Known"])==bool(expected["Known"]),(case["config"]["id"],decision,expected)
        for name in ("OwnAt","PeerAt","Own5","Own15","Own120","Own300","Peer120","OFI30","M","T","Opp"):
            close(saved[name],expected.get(name,0),"原板支持:"+name,1e-7)
        if expected["Known"]:
            counts["known"]+=1
        else:counts["unknown"]+=1
    return counts


def normalize(value, prefix: str):
    """候補固有の台帳接頭辞だけを取り除き同じ判断列を照合する。

    引数: value(JSON互換値)、prefix(str)。返り値: JSON互換値。
    """
    if isinstance(value,str):return value.replace(prefix,"共通判断")
    if isinstance(value,list):return [normalize(x,prefix) for x in value]
    if isinstance(value,dict):return {normalize(k,prefix):normalize(v,prefix) for k,v in value.items()}
    return value


def compare_projection(qcase: dict, hcase: dict, qpath: dict, hpath: dict, raw: np.ndarray) -> dict:
    """H/Qの同じCanonical・親内純量・省略往復・中値/BBO差を照合する。

    引数: qcase/hcase/qpath/hpath(dict)、raw(ndarray)。返り値: dictは恒等式照合結果。
    """
    qcanon=qcase["canonical"];hcanon=hcase["canonical"]
    assert normalize(qcanon,qcanon["Prefix"])==normalize(hcanon,hcanon["Prefix"]), "H/Q判断台帳分岐"
    updates=defaultdict(lambda:{"Q":[],"H":[]})
    for label,case in (("Q",qcase),("H",hcase)):
        for event in case["actual"].get("Events") or []:updates[event["FillIndex"]][label].append(event)
    positions={"Q":defaultdict(lambda:[0,0]),"H":defaultdict(lambda:[0,0])};saved_omission=0.0;checks=0;omitted_quantity=0
    for index,groups in sorted(updates.items()):
        buy_sell={"Q":[0,0],"H":[0,0]}
        for label in ("Q","H"):
            for event in groups[label]:
                order=event["Order"];side=order["Side"];qty=order["Quantity"];p=positions[label][order["Parent"]]
                buy_sell[label][0 if side==1 else 1]+=qty
                if order.get("Targets"):p[0 if side==-1 else 1]-=qty
                else:p[0 if side==1 else 1]+=qty
                assert min(p)>=0
        for key in set(positions["Q"])|set(positions["H"]):
            q=positions["Q"][key];h=positions["H"][key]
            assert q[0]-q[1]==h[0]-h[1] and min(q)==0, "親内純量不一致"
            checks+=1
        omitted_buy=buy_sell["H"][0]-buy_sell["Q"][0];omitted_sell=buy_sell["H"][1]-buy_sell["Q"][1]
        assert omitted_buy==omitted_sell and omitted_buy>=0,"省略した相殺売買が対にならない"
        saved_omission+=omitted_buy*(raw[index,3]-raw[index,2])*10;omitted_quantity+=omitted_buy
    assert np.array_equal(qpath["indices"],hpath["indices"])
    q,h=qpath["after"],hpath["after"];idx=qpath["indices"]
    assert np.all(q[:,1]-q[:,2]==h[:,1]-h[:,2])
    overlap=h[:,1]-q[:,1];assert np.all(overlap>=0) and np.array_equal(overlap,h[:,2]-q[:,2])
    difference=(h[:,0]-q[:,0])*10-overlap*(raw[idx,3]-raw[idx,2])*10
    assert np.max(np.abs(hpath["equity"]-qpath["equity"]-difference))<1e-5
    close((q[-1,0]-h[-1,0])*10,saved_omission,"省略往復の現金差")
    return {"passed":True,"parent_position_checks":checks,"normal_rows":len(idx),"omitted_roundtrip_quantity":omitted_quantity,"omitted_spread_yen":saved_omission,"q_minus_h_final_cash":float((q[-1,0]-h[-1,0])*10),"final_overlap":int(overlap[-1])}


def main() -> None:
    """金融実行完了後だけ保存結果と全原資料を読み、独立監査ゲートを作る。

    引数: なし。返り値: None。新金融・注文・データ再取得は行わない。
    """
    target=BASE/"金融監査157.json"
    proof={"passed":False,"case_count":0,"started_at":datetime.now().astimezone().isoformat(),"new_financial_replays":0}
    try:
        record=read(BASE/"金融実行157.json");assert record["終了コード"]==0 and record["参照改変数"]==0 and record["結果ファイル数"]==27
        inputs=read(PREVIOUS/"inputs156.json");files=sorted((BASE/"results_go").glob("*.json"));assert len(files)==27
        before=[reference(x) for x in files];scenes=[];totals=defaultdict(int)
        for scene in inputs["sessions"]:
            name=scene["session"];saved=read(BASE/"results_go"/(name+"_S01.json"));cases={c["config"]["id"]:c for c in saved["cases"]};assert len(cases)==23
            raw,own_ref=read_market(scene,"NK225");other,peer_ref=read_market(scene,"TOPIX")
            own,peer=support_arrays(raw),support_arrays(other);cache={};rows=[];paths={}
            old=read(PREVIOUS/"results_go"/(name+"_S01.json"));base=next(c for c in old["cases"] if c["config"]["id"]=="S01")
            control=exact_control(cases["C00"],base);totals["baseline_events"]+=control["events"]
            for identifier,case in cases.items():
                risk=raw_risk(raw,case["actual"],scene["start"],identifier in ("Q05","Q08","H05","H08"))
                if "_path" in risk:paths[identifier]=risk.pop("_path")
                cap=reserved_cap(case["actual"]);canonical_cap=reserved_cap(case["canonical"])
                supports=check_support(case,own,peer,cache)
                rows.append({"id":identifier,"risk":risk,"cap":cap,"canonical_cap":canonical_cap,"supports":supports})
                totals["cases"]+=1;totals["event_checks"]+=risk["event_checks"];totals["normal_quote_checks"]+=risk["normal_rows"];totals["known_support_checks"]+=supports["known"];totals["unknown_support_checks"]+=supports["unknown"]
            projections={q:compare_projection(cases[q],cases[h],paths[q],paths[h],raw) for q,h in (("Q05","H05"),("Q08","H08"))}
            summary={"session":name,"partial":scene["partial"],"raw":[own_ref,peer_ref],"baseline":control,"rows":rows,"projection":projections}
            save(BASE/"audit/金融結果"/(name+".json"),summary);scenes.append(summary)
            print(json.dumps({"session":name,"cases":23,"passed":True,"known_supports":sum(x["supports"]["known"] for x in rows)},ensure_ascii=False),flush=True)
        after=[reference(x) for x in files];assert before==after and totals["cases"]==621
        assert totals["known_support_checks"]>0 and totals["unknown_support_checks"]>0, "既知・未知の支持照合が実行されていない"
        proof.update({"passed":True,"case_count":621,"totals":dict(totals),"result_fingerprints":after,"results_unchanged":True,"old_s01_control_cases":27,"h_n_pairs":54,"input_raw_fingerprints":[f for scene in scenes for f in scene["raw"]],"checks":{"old_s01_exact":True,"quantity_cap_including_pending":True,"next_normal_large_bbo":True,"all_raw_equity_risk":True,"raw_support_and_no_future_peer":True,"h_n_canonical_equal":True,"h_n_parent_net_equal":True,"h_n_cashflow_bbo_identity":True,"partial_not_liquidated":True},"finished_at":datetime.now().astimezone().isoformat(),"per_session_files":[str((BASE/"audit/金融結果"/(s["session"]+".json")).relative_to(ROOT)).replace("\\","/") for s in scenes]})
        save(target,proof)
    except Exception as error:
        proof.update({"error":repr(error),"traceback":traceback.format_exc(),"finished_at":datetime.now().astimezone().isoformat()});save(target,proof);raise


if __name__=="__main__":
    main()
