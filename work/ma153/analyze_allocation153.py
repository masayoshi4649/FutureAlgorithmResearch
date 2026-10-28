"""保存約定だけから、初回玉と追加玉の寄与を分けます。新しい売買再生は行いません。"""
from __future__ import annotations
import json
import math
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
JST=ZoneInfo("Asia/Tokyo")


def stamp(value: float) -> str:
    """機能: 保存UNIX秒を日本時間へ表示します。引数: value(float)。返り値: str。"""
    return datetime.fromtimestamp(value,JST).strftime("%Y-%m-%d %H:%M:%S")


def empty() -> dict:
    """機能: 売買枚数とFIFO会計の集計箱を作ります。引数: なし。返り値: dict。"""
    return dict(lots=0,opened_qty=0,closed_qty=0,remaining_qty=0,profit=0.,loss=0.,net=0.,weighted_points=0.,positive_closed_qty=0,negative_closed_qty=0,entry_abs_slope_qty=0.,entry_premium_qty=0.)


def combine(target: dict, source: dict) -> None:
    """機能: 同定義の会計を加算します。引数: target/source(dict)。返り値: なし。"""
    for key in target: target[key]+=source[key]


def finalize(values: dict) -> dict:
    """機能: 枚数で加重した価格幅と傾きを付けます。引数: values(dict)。返り値: dict。"""
    result=dict(values)
    result["points_per_closed_contract"]=values["weighted_points"]/values["closed_qty"] if values["closed_qty"] else None
    result["mean_abs_entry_slope_by_qty"]=values["entry_abs_slope_qty"]/values["opened_qty"] if values["opened_qty"] else None
    result["mean_entry_premium_to_parent_by_qty"]=values["entry_premium_qty"]/values["opened_qty"] if values["opened_qty"] else None
    return result


def signature(event: dict) -> tuple:
    """機能: 同じ初回入口の因果的な注文経路を識別します。引数: event(dict)。返り値: tuple。"""
    order=event["Order"]
    return (order["Side"],order["Quantity"],order["DecisionIndex"],order["DecisionTime"],event["FillIndex"],event["FillTime"],event["Price"])


def parse_case(case: dict, scene: dict, symbol: str) -> dict:
    """機能: 保存新規とFIFO返済をlot別に突合します。引数: case/scene(dict)、symbol(str)。返り値: dict。"""
    entries=[e for e in case["Events"] if e["Order"]["Action"]=="new"]
    lots=case["Lots"] or []
    assert len(entries)==len(lots)
    parents={p["ID"]:p for p in case["Parents"] or []}
    if case.get("open_parent"): parents[case["open_parent"]["ID"]]=case["open_parent"]
    closes=defaultdict(list)
    for event in case["Events"]:
        for a in event.get("Closed") or []:
            closes[a["LotID"]].append(dict(event=event,allocation=a))
    initial=empty(); added=empty(); first={}; class_by_lot={}; diagnostics=[]
    by_parent=defaultdict(lambda:dict(initial_net=0.,added_net=0.,added_qty=0,initial_qty=0))
    for lot,event in zip(lots,entries):
        assert lot["ParentID"]==event["Order"]["ParentID"] and lot["At"]==event["FillTime"] and lot["Initial"]==event["Order"]["Quantity"] and lot["Price"]==event["Price"]
        pid=lot["ParentID"]; category="initial" if pid not in first else "added"
        if category=="initial": first[pid]=event
        class_by_lot[lot["ID"]]=category
        group=initial if category=="initial" else added
        parent=parents[pid]; slope=event["Order"]["Feature"]["Slope"]
        premium=lot["Side"]*(lot["Price"]-parent["Anchor"])
        group["lots"]+=1;group["opened_qty"]+=lot["Initial"];group["remaining_qty"]+=lot["Quantity"]
        group["entry_abs_slope_qty"]+=abs(slope)*lot["Initial"]
        group["entry_premium_qty"]+=premium*lot["Initial"]
        gross=0.; qty=0; records=[]
        for item in closes[lot["ID"]]:
            close=item["event"]; a=item["allocation"]
            expected=lot["Side"]*(close["Price"]-lot["Price"])*a["Quantity"]*case["PointValue"]
            assert math.isclose(a["Gross"],expected,abs_tol=1e-7)
            qty+=a["Quantity"];gross+=expected;group["net"]+=expected
            group["closed_qty"]+=a["Quantity"];group["weighted_points"]+=expected/case["PointValue"]
            if expected>0: group["profit"]+=expected;group["positive_closed_qty"]+=a["Quantity"]
            if expected<0: group["loss"]-=expected;group["negative_closed_qty"]+=a["Quantity"]
            records.append(dict(time=stamp(close["FillTime"]),time_s=close["FillTime"],price=close["Price"],qty=a["Quantity"],gross=expected,points=lot["Side"]*(close["Price"]-lot["Price"]),reason=close["Order"]["Reason"],slope=close["Order"]["Feature"]["Slope"],decision_time=stamp(close["Order"]["DecisionTime"]),decision_index=close["Order"]["DecisionIndex"],fill_index=close["FillIndex"],decision_line=close["Order"]["DecisionLine"],fill_line=close["FillLine"]))
        assert math.isclose(gross,lot["Realized"],abs_tol=1e-6) and qty+lot["Quantity"]==lot["Initial"]
        by_parent[pid][category+"_net"]+=gross
        by_parent[pid][category+"_qty"]+=lot["Initial"]
        if category=="added":
            initial_event=first[pid]
            diagnostics.append(dict(session=scene["session"],symbol=symbol,partial=scene["partial"],method=case["Config"]["id"],parent_id=pid,lot_id=lot["ID"],side=lot["Side"],quantity=lot["Initial"],remaining=lot["Quantity"],entry_time=stamp(event["FillTime"]),entry_time_s=event["FillTime"],entry_price=lot["Price"],decision_time=stamp(event["Order"]["DecisionTime"]),decision_index=event["Order"]["DecisionIndex"],decision_line=event["Order"]["DecisionLine"],fill_index=event["FillIndex"],fill_line=event["FillLine"],slope=slope,entry_premium_points=premium,gross=gross,points_per_closed_contract=gross/case["PointValue"]/qty if qty else None,initial_time=stamp(initial_event["FillTime"]),initial_price=initial_event["Price"],initial_qty=initial_event["Order"]["Quantity"],initial_slope=initial_event["Order"]["Feature"]["Slope"],parent_exit_time=stamp(parent["CloseTime"]) if parent["CloseTime"] else None,parent_exit_reason=parent["ExitReason"],parent_peak_gain=parent["PeakGain"],parent_worst_gain=parent["WorstGain"],parent_gross=parent["Realized"],closes=records))
    assert math.isclose(initial["net"]+added["net"],case["Gross"],abs_tol=1e-6)
    assert math.isclose(initial["profit"]+added["profit"],case["Profit"],abs_tol=1e-6)
    assert math.isclose(initial["loss"]+added["loss"],case["Loss"],abs_tol=1e-6)
    return dict(initial=initial,added=added,parents=parents,first=first,by_parent=by_parent,diagnostics=diagnostics,lots=lots,events=case["Events"],gross=case["Gross"])


def main() -> None:
    """機能: 完了104保存会計だけを読み、数量寄与と具体約定を保存します。引数: なし。返り値: なし。"""
    paths=sorted((ROOT/"results_go").glob("*.json"));assert len(paths)==104
    summaries={}
    for symbol in ["NK225","TOPIX"]:
        summaries[symbol]={scope:{"M09_initial":empty(),"M12_initial":empty(),"M12_added":empty(),"files":0,"parents_m09":0,"parents_m12":0,"matched_entry_parents":0,"same_close_parents":0,"entry_mismatch_examples":[],"close_mismatch_examples":[]} for scope in ["complete","partial"]}
    rows=[];worst=defaultdict(list);best=defaultdict(list);improvements=defaultdict(list)
    for index,path in enumerate(paths):
        data=json.loads(path.read_text(encoding="utf-8"));scene=data["scene"];symbol=data["symbol"]
        selected={c["Config"]["id"]:c for c in data["cases"] if c["Config"]["id"] in ["M09","M12"]};assert len(selected)==2
        a=parse_case(selected["M09"],scene,symbol);b=parse_case(selected["M12"],scene,symbol)
        scope="partial" if scene["partial"] else "complete";total=summaries[symbol][scope]
        total["files"]+=1;combine(total["M09_initial"],a["initial"]);combine(total["M12_initial"],b["initial"]);combine(total["M12_added"],b["added"])
        assert a["added"]["lots"]==0
        total["parents_m09"]+=len(a["parents"]);total["parents_m12"]+=len(b["parents"])
        entry_match=0;close_match=0;parent_delta=[]
        amap={signature(e):pid for pid,e in a["first"].items()}
        for pid,e in b["first"].items():
            other=amap.get(signature(e))
            if other is None:
                if len(total["entry_mismatch_examples"])<8:total["entry_mismatch_examples"].append(dict(session=scene["session"],parent_id=pid,entry=signature(e)))
                continue
            entry_match+=1
            pa,pb=a["parents"][other],b["parents"][pid]
            if pa["CloseTime"]==pb["CloseTime"] and pa["ExitReason"]==pb["ExitReason"]:close_match+=1
            elif len(total["close_mismatch_examples"])<8:total["close_mismatch_examples"].append(dict(session=scene["session"],m09_parent=other,m12_parent=pid,m09_close=pa["CloseTime"],m12_close=pb["CloseTime"],m09_reason=pa["ExitReason"],m12_reason=pb["ExitReason"]))
            d=pb["Realized"]-pa["Realized"]
            parent_delta.append(dict(session=scene["session"],symbol=symbol,m09_parent=other,m12_parent=pid,side=pb["Side"],entry_time=stamp(e["FillTime"]),entry_price=e["Price"],entry_qty=e["Order"]["Quantity"],entry_slope=e["Order"]["Feature"]["Slope"],m09_gross=pa["Realized"],m12_gross=pb["Realized"],difference=d,initial_exit_difference=b["by_parent"][pid]["initial_net"]-a["by_parent"][other]["initial_net"],added_net=b["by_parent"][pid]["added_net"],added_qty=b["by_parent"][pid]["added_qty"]))
        total["matched_entry_parents"]+=entry_match;total["same_close_parents"]+=close_match
        row=dict(session=scene["session"],kind=scene["kind"],symbol=symbol,partial=scene["partial"],m09=finalize(a["initial"]),m12_initial=finalize(b["initial"]),m12_added=finalize(b["added"]),difference=b["gross"]-a["gross"],initial_exit_difference=b["initial"]["net"]-a["initial"]["net"],added_net=b["added"]["net"],entry_matched=entry_match,close_matched=close_match,parents_m09=len(a["parents"]),parents_m12=len(b["parents"]))
        assert math.isclose(row["difference"],row["initial_exit_difference"]+row["added_net"],abs_tol=1e-6)
        rows.append(row)
        if not scene["partial"]:
            candidates=sorted(b["diagnostics"],key=lambda x:x["gross"])
            worst[symbol].extend(candidates[:5]);best[symbol].extend(candidates[-5:])
            improvements[symbol].extend(sorted(parent_delta,key=lambda x:x["difference"],reverse=True)[:3])
        del data,selected,a,b
        if (index+1)%20==0:print(f"保存会計読取 {index+1}/104",flush=True)
    for symbol,scopes in summaries.items():
        for scope,s in scopes.items():
            for label in ["M09_initial","M12_initial","M12_added"]:s[label]=finalize(s[label])
            s["initial_exit_difference"]=s["M12_initial"]["net"]-s["M09_initial"]["net"]
            s["added_contribution"]=s["M12_added"]["net"]
            s["total_difference"]=s["initial_exit_difference"]+s["added_contribution"]
    out=dict(definition="保存されたM09/M12の新規・FIFO返済だけを独立再会計。利益/損失は各返済配賦、1枚当たり幅は枚数加重。途中場は別。追加再生・原板再読なし。",source_files=104,summaries=summaries,sessions=rows,worst_additions={s:sorted(v,key=lambda x:x["gross"])[:10] for s,v in worst.items()},best_additions={s:sorted(v,key=lambda x:x["gross"],reverse=True)[:5] for s,v in best.items()},largest_parent_improvements={s:sorted(v,key=lambda x:x["difference"],reverse=True)[:5] for s,v in improvements.items()})
    (ROOT/"allocation_analysis153.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(out["summaries"],ensure_ascii=False,indent=2))
    print("最悪追加玉",json.dumps({s:v[:3] for s,v in out["worst_additions"].items()},ensure_ascii=False))

if __name__=="__main__":main()
