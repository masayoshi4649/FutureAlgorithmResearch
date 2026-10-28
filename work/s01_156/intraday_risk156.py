"""保存実約定と全正常ラージ原板だけから場内の時価・確定損失を再会計する。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import math
import os

import numpy as np


BASE = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))


def equal(actual: float, expected: float, name: str) -> None:
    """有限数値を金額許容差以内で一致確認する。

    引数: actual/expected(float)は比較数値、name(str)は対象。
    返り値: None。不一致なら停止する。
    """
    assert math.isfinite(actual) and math.isfinite(expected) and abs(actual-expected)<1e-5, (name,actual,expected)


def moment(raw: np.ndarray, index: int, start: float, phase: str, realized: float,
           qlong: int, qshort: int, long_cost: float, short_cost: float, point: float) -> dict:
    """原行・実保有・返済側気配を伴う時価断面を作る。

    引数: raw(ndarray)、index(int)、start(float)、phase(str)は原行と評価位置。
    realized/long_cost/short_cost/point(float)、qlong/qshort(int)は全実玉会計。
    返り値: dictは時刻・原行・確定・含み・時価。index=-1は当場開始0。
    """
    if index < 0:
        at,bid,ask,unrealized = start,None,None,0.0
    else:
        at,bid,ask = (float(raw[index,c]) for c in (0,2,3))
        unrealized = (qlong*bid-long_cost+short_cost-qshort*ask)*point
    return {"time":at,"at":datetime.fromtimestamp(at,JST).isoformat(),"index":int(index),"phase":phase,
            "bid":bid,"ask":ask,"long_quantity":int(qlong),"short_quantity":int(qshort),
            "realized":float(realized),"unrealized":float(unrealized),"equity":float(realized+unrealized)}


def measure(raw: np.ndarray, case: dict, start: float, point: float = 100.0) -> dict:
    """全正常板を原行順に評価し、約定前後を含む場内極値を算出する。

    引数: raw(ndarray)はTime/Last/Bid/Ask、case(dict)は実events、start/point(float)は開始と倍率。
    返り値: dictは時価最小・最大下落・確定最小と原行根拠。新しい注文は生成しない。
    """
    valid = np.flatnonzero(np.isfinite(raw[:,2]) & np.isfinite(raw[:,3]) & (raw[:,2]>0) & (raw[:,3]>raw[:,2]))
    assert len(valid)
    initial = moment(raw,-1,start,"当場開始",0,0,0,0,0,point)
    minimum = peak = peak_dd = trough_dd = minimum_realized = initial
    drawdown = 0.0
    realized = long_cost = short_cost = 0.0
    qlong = qshort = 0
    lots = {}
    cursor = 0
    observations = 0
    fill_count = 0
    previous_fill = -1

    def scan(indices: np.ndarray, phase: str) -> None:
        """一定枚数区間を配列評価し、全原板の極値と先行ピークを更新する。

        引数: indices(ndarray)は正常原行添字、phase(str)は評価位置。
        返り値: None。外側の極値だけを更新する。
        """
        nonlocal minimum,peak,peak_dd,trough_dd,drawdown,observations
        if not len(indices):
            return
        equity = realized+(qlong*raw[indices,2]-long_cost+short_cost-qshort*raw[indices,3])*point
        observations += len(indices)
        low = int(np.argmin(equity))
        if equity[low] < minimum["equity"]:
            minimum = moment(raw,int(indices[low]),start,phase,realized,qlong,qshort,long_cost,short_cost,point)
        cumulative_peak = np.maximum.accumulate(np.maximum(equity,peak["equity"]))
        differences = cumulative_peak-equity
        bad = int(np.argmax(differences))
        if differences[bad] > drawdown:
            drawdown = float(differences[bad])
            trough_dd = moment(raw,int(indices[bad]),start,phase,realized,qlong,qshort,long_cost,short_cost,point)
            prior = int(np.argmax(equity[:bad+1]))
            peak_dd = (moment(raw,int(indices[prior]),start,phase,realized,qlong,qshort,long_cost,short_cost,point)
                       if equity[prior] > peak["equity"] else peak)
        high = int(np.argmax(equity))
        if equity[high] > peak["equity"]:
            peak = moment(raw,int(indices[high]),start,phase,realized,qlong,qshort,long_cost,short_cost,point)

    for event_no,event in enumerate(case.get("events") or []):
        signal,fill = event["signal"],event["fill"]
        index = event["fill_index"]
        assert index >= previous_fill
        previous_fill = index
        location = int(np.searchsorted(valid,index))
        assert location < len(valid) and valid[location] == index
        scan(valid[cursor:location+1],"原板・約定前")
        cursor = location+1
        side = signal["side"]
        equal(fill["Price"],float(raw[index,3 if side==1 else 2]),"返済側BBO約定")
        equal(fill.get("Fee",0),0,"費用0")
        gross = 0.0
        if signal["action"] == "new":
            key,q,price = fill["HoldID"],fill["Quantity"],fill["Price"]
            assert key not in lots and q>0
            lots[key] = {"quantity":q,"price":price,"side":side}
            if side==1:
                qlong += q
                long_cost += q*price
            else:
                qshort += q
                short_cost += q*price
        else:
            assert signal["action"]=="close"
            targets = fill.get("Closed") or []
            assert sum(t["quantity"] for t in targets)==fill["Quantity"]
            for target in targets:
                lot = lots[target["id"]]
                q = target["quantity"]
                assert 0 < q <= lot["quantity"] and lot["side"]==-side
                gross += lot["side"]*q*(fill["Price"]-lot["price"])*point
                lot["quantity"] -= q
                if lot["side"]==1:
                    qlong -= q
                    long_cost -= q*lot["price"]
                else:
                    qshort -= q
                    short_cost -= q*lot["price"]
        equal(gross,event["gross"],"保存確定損益")
        realized += gross
        phase = f"約定後:{event_no}"
        scan(np.array([index],dtype=np.int64),phase)
        if realized < minimum_realized["realized"]:
            minimum_realized = moment(raw,index,start,phase,realized,qlong,qshort,long_cost,short_cost,point)
        fill_count += 1
    scan(valid[cursor:],"原板・約定前")
    final = moment(raw,int(valid[-1]),start,"観測末尾",realized,qlong,qshort,long_cost,short_cost,point)
    equal(realized,case["Gross"],"全確定")
    equal(final["unrealized"],case["Unrealized"],"末尾含み")
    equal(peak_dd["equity"]-trough_dd["equity"],drawdown,"最大下落の起終点")
    return {"min_equity":minimum["equity"],"min_equity_at":minimum,
            "max_drawdown":drawdown,"drawdown_peak":peak_dd,"drawdown_trough":trough_dd,
            "min_realized":minimum_realized["realized"],"min_realized_at":minimum_realized,
            "highest_equity":peak["equity"],"highest_equity_at":peak,"final":final,
            "normal_raw_quotes":int(len(valid)),"valuation_points":observations,"fills":fill_count,
            "all_actual_owners_combined":True,"virtual_source_positions_excluded":True}


def synthetic_event(index: int, action: str, side: int, qty: int, price: float,
                    hold_id: str, targets: list, gross: float) -> dict:
    """再会計検査専用の人工約定を作る。

    引数: index/side/qty(int)、action/hold_id(str)、price/gross(float)、targets(list)は人工条件。
    返り値: dictは実結果と同じ最小構造。市場売買の検証ではない。
    """
    return {"fill_index":index,"signal":{"action":action,"side":side},
            "fill":{"Quantity":qty,"Price":price,"HoldID":hold_id,"Closed":targets,"Fee":0},"gross":gross}


def self_test() -> None:
    """両建て、部分返済、同秒、不正板、初期0を人工例で検査する。

    引数: なし。返り値: None。保存金融結果は読まない。
    """
    outcomes=[]
    raw=np.array([[10,100,99,101],[11,110,109,111],[12,120,119,121]],dtype=float)
    empty=measure(raw,{"events":[],"Gross":0,"Unrealized":0},10)
    assert empty["min_equity"]==empty["max_drawdown"]==empty["min_realized"]==0
    outcomes.append({"name":"無取引・初期0", "pass":True})
    events=[synthetic_event(0,"new",1,2,101,"L",[],0),synthetic_event(0,"new",-1,2,99,"S",[],0),
            synthetic_event(1,"close",-1,2,109,"",[{"id":"L","quantity":2}],1600)]
    hedge=measure(raw,{"events":events,"Gross":1600,"Unrealized":-4400},10)
    assert hedge["final"]["equity"]==-2800 and hedge["min_equity"]==-2800 and hedge["max_drawdown"]==2800 and hedge["min_realized"]==0
    outcomes.append({"name":"利益だけ返済した両建ての残含み損", "pass":True,"result":hedge})
    raw2=np.array([[10,100,99,101],[10,110,110,112],[11,105,105,107]],dtype=float)
    events=[synthetic_event(0,"new",1,1,101,"A",[],0),synthetic_event(2,"close",-1,1,105,"",[{"id":"A","quantity":1}],400)]
    test=measure(raw2,{"events":events,"Gross":400,"Unrealized":0},10)
    assert test["min_equity"]==-200 and test["max_drawdown"]==500 and test["drawdown_peak"]["index"]==1
    outcomes.append({"name":"同秒別原行の最高から返済後下落", "pass":True,"result":test})
    bad=np.array([[10,100,99,101],[11,1000,1000,1000],[12,100,99,101]],dtype=float)
    events=[synthetic_event(0,"new",1,2,101,"A",[],0),synthetic_event(2,"close",-1,1,99,"",[{"id":"A","quantity":1}],-200)]
    test=measure(bad,{"events":events,"Gross":-200,"Unrealized":-200},10)
    assert test["highest_equity"]==0 and test["min_equity"]==-400 and test["min_realized"]==-200
    outcomes.append({"name":"不正板を除外し部分返済を重複計上しない", "pass":True,"result":test})
    (BASE/"場内リスクの人工検査156.json").write_text(json.dumps({"tests":outcomes,"financial_replays":0},ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"artificial_tests":len(outcomes),"pass":True}))


def run(merge: bool) -> None:
    """最終統合に載る候補だけを全原板で再会計し、別資料へ保存する。

    引数: merge(bool)は最終統合だけへ追記する指定。返り値: None。
    初巡・各巡の元reportや保存金融結果は編集しない。
    """
    source=BASE/"report156_all.json"
    before=source.read_bytes()
    report=json.loads(before)
    wanted={m["id"] for m in report["methods"]}
    spec=importlib.util.spec_from_file_location("analyze156_risk_reader",BASE/"analyze156.py")
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest=json.loads((BASE/"inputs156.json").read_text(encoding="utf-8"))
    folders=[BASE/"results_go"]+[p/"results_go" for p in sorted(BASE.glob("round*")) if p.is_dir()]
    rows,sources=[],[]
    for scene in manifest["sessions"]:
        raw,fingerprint=module.raw_quotes(scene)
        selected={}
        result_sources=[]
        for folder in folders:
            for filename in folder.glob(scene["session"]+"_*.json"):
                data=filename.read_bytes()
                parsed=json.loads(data)
                used=[]
                for case in parsed["cases"]:
                    method=case["config"]["id"]
                    if method in wanted and method not in selected:
                        selected[method]=case
                        used.append(method)
                if used:
                    result_sources.append({"path":str(filename),"sha256":hashlib.sha256(data).hexdigest(),"ids":used})
        assert set(selected)==wanted, (scene["session"],sorted(wanted-set(selected)))
        for method,case in selected.items():
            risk=measure(raw,case,scene["start"])
            rows.append({"session":scene["session"],"id":method,"partial":scene.get("partial",False),"intraday_risk":risk})
        sources.append({"session":scene["session"],"raw":fingerprint,"results":result_sources})
        print(scene["session"],len(selected),flush=True)
    assert len(rows)==len(wanted)*len(manifest["sessions"])
    current=source.read_bytes()
    assert current==before,"集計中に最終会計が変更されました"
    by_key={(r["session"],r["id"]):r["intraday_risk"] for r in rows}
    for method in report["methods"]:
        for row in method["rows"]:
            risk=by_key[(row["session"],method["id"])]
            equal(risk["final"]["realized"],row["net"],"最終統合の実現値")
            equal(risk["final"]["unrealized"],row["unrealized"],"最終統合の含み値")
            row["intraday_risk"]=risk
    for name in ("current_rows","partial"):
        for row in report.get(name,[]):
            risk=by_key[(row["session"],row["id"])]
            equal(risk["final"]["realized"],row["net"],"途中統合の実現値")
            equal(risk["final"]["unrealized"],row["unrealized"],"途中統合の含み値")
            row["intraday_risk"]=risk
    out={"spec":{"scope":"最終統合の全候補・26完了と1途中を分離","initial_equity":0,"mark":"実玉全ownerを買Bid・売Askで同時計算",
                 "order":"同秒でも原行順。原行BBOで約定前を評価→同原行の保存約定を順に反映して再評価",
                 "virtual_source_positions":False,"missing_quotes":"正常BBOなしの区間を補間しない",
                 "drawdown":"当場開始0を含む先行最高時価からの下落。セッションを跨がない"},
         "source_report_sha256":hashlib.sha256(before).hexdigest(),"cases":len(rows),"rows":rows,"sources":sources}
    risk_path=BASE/"場内リスク156.json"
    risk_path.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    if merge:
        report["intraday_risk_source"]={"path":str(risk_path),"sha256":hashlib.sha256(risk_path.read_bytes()).hexdigest(),"cases":len(rows)}
        destination=BASE/"report156_all.risk.tmp"
        destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        assert source.read_bytes()==before
        os.replace(destination,source)
    print(json.dumps({"cases":len(rows),"methods":len(wanted),"merged":merge}))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--run",action="store_true")
    parser.add_argument("--merge",action="store_true")
    args=parser.parse_args()
    if args.run:
        run(args.merge)
    else:
        self_test()
