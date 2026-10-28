"""00156の保存約定を独立に再会計する。売買条件の生成・実注文・API取得は行わない。"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))


def equal(a: float, b: float, name: str) -> None:
    """会計の一致を検査する。

    引数: 数値a/b、対象名str。
    返り値: なし。
    """
    if not math.isfinite(a) or not math.isfinite(b) or abs(a-b) > 1e-6:
        raise AssertionError(f"{name}: {a} != {b}")


def jst(at: float) -> str:
    """原時計を日本時間へ表示する。

    引数: UNIX秒float。
    返り値: str。
    """
    return datetime.fromtimestamp(at, JST).isoformat()


def write_json(path: Path, value: object) -> None:
    """UTF-8の分析成果を保存する。

    引数: Path、JSON互換値。
    返り値: なし。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def raw_quotes(scene: dict) -> tuple[np.ndarray, dict]:
    """日経原行を一度読み、研究と同じ採番だけを再構成する。

    引数: 場dict。
    返り値: ndarrayと指紋dict。
    """
    path = Path(scene["books"]["NK225"])
    digest = hashlib.sha256()
    previous, rows, counts = scene["start"], [], defaultdict(int)
    with path.open("rb") as stream:
        for line in stream:
            digest.update(line)
            counts["原行"] += 1
            row = json.loads(line)
            clock = row.get("CurrentPriceTime")
            if not clock:
                counts["時計欠測"] += 1
                continue
            try:
                at = datetime.fromisoformat(clock).timestamp()
            except (TypeError, ValueError):
                counts["時計欠測"] += 1
                continue
            if at < scene["start"] or at > scene["end"] or (scene.get("cutoff", 0) > 0 and at >= scene["cutoff"]):
                counts["範囲外"] += 1
                continue
            if at < previous:
                counts["逆行"] += 1
                continue
            last = float(row.get("CurrentPrice") or 0)
            if last <= 0 or not math.isfinite(last):
                counts["Last欠測"] += 1
                continue
            previous = at
            bid = float((row.get("Buy1") or {}).get("Price") or 0)
            ask = float((row.get("Sell1") or {}).get("Price") or 0)
            rows.append((at, last, bid, ask))
            counts["採用"] += 1
    data = np.asarray(rows, dtype=np.float64)
    if len(data) == 0:
        raise AssertionError("採用日経原行なし")
    expected = next(f["sha256"] for f in scene["fingerprints"] if Path(f["path"]) == path)
    assert digest.hexdigest() == expected, "原板の事前指紋不一致"
    return data, {"path": str(path), "sha256": digest.hexdigest(), "matches_registered_input":True, "counts": dict(counts)}


def normal_indices(raw: np.ndarray) -> np.ndarray:
    """正で逆転しない有限BBOだけを抽出する。

    引数: ndarray。
    返り値: 原行添字ndarray。
    """
    return np.flatnonzero(np.isfinite(raw[:, 2]) & np.isfinite(raw[:, 3]) & (raw[:, 2] > 0) & (raw[:, 3] > raw[:, 2]))


def gains(raw: np.ndarray, valid: np.ndarray, begin: int, end: int, side: int, entry: float) -> tuple[float, float, float, float]:
    """実保有区間の全正常原板から順逆行極値を求める。

    引数: 原板/正常添字、区間int、方向int、建値float。
    返り値: 最高/最低幅と時計。
    """
    idx = valid[np.searchsorted(valid, begin):np.searchsorted(valid, end, side="right")]
    values = side*(raw[idx, 2 if side == 1 else 3]-entry)
    best = max(0.0, float(values.max())) if len(values) else 0.0
    worst = min(0.0, float(values.min())) if len(values) else 0.0
    best_at = float(raw[idx[int(np.argmax(values))], 0]) if best > 0 else float(raw[begin, 0])
    worst_at = float(raw[idx[int(np.argmin(values))], 0]) if worst < 0 else float(raw[begin, 0])
    return best, worst, best_at, worst_at


def parent_extrema(parent: dict, raw: np.ndarray, valid: np.ndarray) -> tuple[float, float, float, float]:
    """売買条件を再実行せず、約定区間の親総時価を全板で算出する。

    引数: 親dict、原板/正常添字。
    返り値: 最高/最低時価と時計。
    """
    quantity, signed_cost, realized = 0, 0.0, 0.0
    peak, low, peak_at, low_at = 0.0, 0.0, 0.0, 0.0
    events = parent["movements"]
    for i, event in enumerate(events):
        q, px, index = event["quantity"], event["price"], event["index"]
        if event["action"] == "new":
            quantity += q
            signed_cost += parent["side"]*q*px*100
        else:
            quantity -= q
            signed_cost -= parent["side"]*q*event["entry"]*100
            realized += event["net"]
        finish = events[i+1]["index"] if i+1 < len(events) else int(valid[-1])
        indices = valid[np.searchsorted(valid, index):np.searchsorted(valid, finish, side="right")]
        if not len(indices):
            continue
        prices = raw[indices, 2 if parent["side"] == 1 else 3]
        equities = realized + parent["side"]*quantity*prices*100-signed_cost
        best, worst = float(equities.max()), float(equities.min())
        if best > peak:
            peak, peak_at = best, float(raw[indices[int(np.argmax(equities))], 0])
        if worst < low:
            low, low_at = worst, float(raw[indices[int(np.argmin(equities))], 0])
    return peak, low, peak_at, low_at


def verify_limits(case: dict) -> dict:
    """通知予約と実約定を原行順へ結合して上限を再検査する。

    引数: 保存case。
    返り値: 最大保有/予約指標dict。
    """
    rows = defaultdict(lambda: {"fills": [], "signals": []})
    for event in case["events"] or []:
        rows[event["fill_index"]]["fills"].append(event)
    for signal in case["signals"] or []:
        rows[signal["source_index"]]["signals"].append(signal)
    pending, lots = {}, {}
    maximum_side, maximum_total, maximum_owner = 0, 0, defaultdict(int)
    for index in sorted(rows):
        for event in rows[index]["fills"]:
            signal, fill = event["signal"], event["fill"]
            if pending.pop(signal["id"], None) != signal:
                raise AssertionError("予約なし又は内容不一致の実約定")
            if signal["action"] == "new":
                lots[fill["HoldID"]] = {"side": signal["side"], "owner": signal["owner"], "quantity": fill["Quantity"]}
            else:
                for target in fill["Closed"]:
                    lots[target["id"]]["quantity"] -= target["quantity"]
        for signal in rows[index]["signals"]:
            if signal["id"] in pending:
                raise AssertionError("二重予約")
            pending[signal["id"]] = signal
        sides, owners = defaultdict(int), defaultdict(int)
        for lot in lots.values():
            sides[lot["side"]] += lot["quantity"]
            owners[lot["owner"]] += lot["quantity"]
        for signal in pending.values():
            if signal["action"] == "new":
                sides[signal["side"]] += signal["quantity"]
                owners[signal["owner"]] += signal["quantity"]
        if any(q > 10 or q < 0 for q in sides.values()) or any(q > {"core": 5, "addon": 3, "episode": 2}[owner] or q < 0 for owner, q in owners.items()):
            raise AssertionError("予約込み上限違反")
        maximum_side = max(maximum_side, max(sides.values(), default=0))
        maximum_total = max(maximum_total, sum(sides.values()))
        for owner, q in owners.items():
            maximum_owner[owner] = max(maximum_owner[owner], q)
    saved = {s["id"]: s for s in case.get("final_pending") or []}
    if pending != saved:
        raise AssertionError("末尾予約不一致")
    return {"max_reserved_side": maximum_side, "max_reserved_total": maximum_total, "max_reserved_by_owner": dict(maximum_owner)}


def analyze_case(case: dict, scene: dict, raw: np.ndarray, valid: np.ndarray) -> tuple[dict, dict]:
    """全約定・原板・親/玉別会計を独立照合する。

    引数: 保存case、固定場、原板/正常添字。
    返り値: 主行と詳細dict。
    """
    ident = case["config"]["id"]
    name = scene["session"] + "/" + ident
    lots, parents, pieces = {}, {}, []
    total, allocation_profit, allocation_loss = 0.0, 0.0, 0.0
    source_signals = {s["id"]: s for s in case.get("signals") or []}
    if len(source_signals) != len(case.get("signals") or []):
        raise AssertionError("同一IDの通知")
    for signal in source_signals.values():
        i = signal["source_index"]
        equal(signal["time"], float(raw[i, 0]), name+"判断時計")
        obs = signal["evidence"]["observation"]
        equal(obs["Index"], i, name+"判断添字")
        for key, col in (("Time",0),("Last",1),("Bid",2),("Ask",3)):
            equal(obs[key], float(raw[i,col]), name+"判断原板"+key)
    previous = -1
    for event in case.get("events") or []:
        signal, fill = event["signal"], event["fill"]
        di, fi = event["decision_index"], event["fill_index"]
        assert fi >= previous and fi > di and signal == source_signals[signal["id"]], name
        previous = fi
        expected_index = int(valid[np.searchsorted(valid, di, side="right")])
        equal(fi, expected_index, name+"次正常原行")
        equal(fill["Price"], float(raw[fi,3 if signal["side"] == 1 else 2]), name+"約定気配")
        equal(fill["Time"], float(raw[fi,0]), name+"約定時計")
        equal(fill["Quantity"], signal["quantity"], name+"全量")
        equal(fill["Fee"], 0, name+"費用")
        gross = 0.0
        if signal["action"] == "new":
            key = signal["owner"]+"/"+str(signal["campaign"])
            if key not in parents:
                parents[key] = {"owner":signal["owner"],"campaign":signal["campaign"],"side":signal["side"],"first_decision_index":di,"entry_time":fill["Time"],"initial_quantity":fill["Quantity"],"net":0.0,"remaining":0,"movements":[],"lots":[]}
            parent = parents[key]
            assert parent["side"] == signal["side"] and fill["HoldID"] not in lots, name
            lot = {"id":fill["HoldID"],"owner":signal["owner"],"campaign":signal["campaign"],"parent":key,"side":signal["side"],"price":fill["Price"],"quantity":fill["Quantity"],"remaining":fill["Quantity"],"entry_time":fill["Time"],"entry_index":fi,"decision_index":di,"net":0.0,"closes":[]}
            lots[lot["id"]] = lot
            parent["lots"].append(lot["id"])
            parent["remaining"] += fill["Quantity"]
            parent["movements"].append({"index":fi,"action":"new","quantity":fill["Quantity"],"price":fill["Price"]})
        else:
            assert fill["Closed"] == signal["targets"], name
            assert sum(t["quantity"] for t in fill["Closed"]) == fill["Quantity"], name
            assert len(event["pieces"]) == len(fill["Closed"]), name
            for target, saved_piece in zip(fill["Closed"], event["pieces"]):
                lot = lots[target["id"]]
                q = target["quantity"]
                assert 0 < q <= lot["remaining"] and lot["side"] == -signal["side"] and lot["owner"] == signal["owner"] and lot["campaign"] == signal["campaign"], name
                net = lot["side"]*q*(fill["Price"]-lot["price"])*100
                lot["remaining"] -= q
                lot["net"] += net
                close = {"index":fi,"time":fill["Time"],"quantity":q,"price":fill["Price"],"net":net,"reason":signal["reason_code"]}
                lot["closes"].append(close)
                parent = parents[lot["parent"]]
                parent["remaining"] -= q
                parent["net"] += net
                parent["movements"].append({"index":fi,"action":"close","quantity":q,"price":fill["Price"],"entry":lot["price"],"net":net})
                best,worst,_,_ = gains(raw,valid,lot["entry_index"],fi,lot["side"],lot["price"])
                equal(saved_piece["Gross"],net,name+"配賦損益")
                equal(saved_piece["BestGain"],best,name+"配賦前MFE")
                equal(saved_piece["WorstGain"],worst,name+"配賦前MAE")
                assert saved_piece["PositiveThenLoss"] == (best>0 and net<0), name
                decision_mark=float(raw[di,2 if lot["side"]==1 else 3])
                decision_net=lot["side"]*q*(decision_mark-lot["price"])*100
                piece = {**close,"id":lot["id"],"parent":lot["parent"],"owner":lot["owner"],"side":lot["side"],"best_points":best,"worst_points":worst,"positive_then_loss":best>0 and net<0,"protected":saved_piece["Protected"],"floor":saved_piece["Floor"],"protection_at":saved_piece["ProtectionAt"],"decision_time":signal["time"],"decision_index":di,"decision_gain_yen":decision_net,"after_decision_change_yen":net-decision_net}
                pieces.append(piece)
                gross += net
                allocation_profit += max(0,net)
                allocation_loss += max(0,-net)
        equal(event["gross"],gross,name+"返済会計")
        total += gross
    equal(total,case["Gross"],name+"全実現")
    last_index = int(valid[-1])
    for key,col in (("Time",0),("Last",1),("Bid",2),("Ask",3)):
        equal(case["last_quote"][key],float(raw[last_index,col]),name+"最終正常板")
    unreal = 0.0
    for lot in lots.values():
        final = last_index if lot["remaining"] else lot["closes"][-1]["index"]
        best,worst,best_at,worst_at = gains(raw,valid,lot["entry_index"],final,lot["side"],lot["price"])
        lot.update(best_points=best,worst_points=worst,best_at=best_at,worst_at=worst_at)
        saved = case["entries"][lot["id"]]
        for sk,lk in (("Quantity","quantity"),("Remaining","remaining"),("Price","price"),("Gross","net"),("BestPoints","best_points"),("WorstPoints","worst_points"),("BestTime","best_at"),("WorstTime","worst_at")):
            equal(saved[sk],lot[lk],name+"保存玉"+sk)
        lot["unrealized"] = lot["side"]*lot["remaining"]*(float(raw[last_index,2 if lot["side"]==1 else 3])-lot["price"])*100
        unreal += lot["unrealized"]
    assert set(case["entries"]) == set(lots), name
    equal(unreal,case["Unrealized"],name+"未返済含み")
    for key,parent in parents.items():
        peak,low,peak_at,low_at = parent_extrema(parent,raw,valid)
        parent.update(peak=peak,minimum=low,peak_at=peak_at,minimum_at=low_at)
        parent["unrealized"] = sum(lots[k]["unrealized"] for k in parent["lots"])
        parent["equity"] = parent["net"]+parent["unrealized"]
        parent["positive_then_loss"] = parent["remaining"]==0 and peak>0 and parent["net"]<0
        parent["exit_time"] = max((c["time"] for k in parent["lots"] for c in lots[k]["closes"]),default=parent["entry_time"])
        saved = case["parents"][key]
        for sk,lk in (("Realized","net"),("Unrealized","unrealized"),("Equity","equity"),("Remaining","remaining"),("Peak","peak"),("Minimum","minimum"),("PeakAt","peak_at"),("MinimumAt","minimum_at")):
            equal(saved[sk],parent[lk],name+"保存親"+sk)
        assert saved["PositiveThenLoss"] == parent["positive_then_loss"], name
    assert set(case.get("parents") or {}) == set(parents), name
    completed = [p for p in parents.values() if p["remaining"]==0]
    open_realized = sum(p["net"] for p in parents.values() if p["remaining"]>0)
    profit = sum(max(0,p["net"]) for p in completed)
    loss = sum(max(0,-p["net"]) for p in completed)
    equal(profit-loss+open_realized,total,name+"親集計")
    if not scene["partial"]:
        assert not open_realized and not any(l["remaining"] for l in lots.values()) and not case.get("final_pending"), name
    qualification = scene.get("qualification",{}).get("NK225",{}).get("book",{})
    first_last = qualification.get("first",{}).get("last",float(raw[0,1]))
    final_last = qualification.get("last",{}).get("last",float(raw[-1,1]))
    direction = "上昇" if final_last > first_last else "下落" if final_last < first_last else "横ばい"
    row = {"id":ident,"session":scene["session"],"partial":scene["partial"],"direction":direction,"first_last":first_last,"final_last":final_last,"profit":profit,"loss":loss,"net":total,"open_parent_realized":open_realized,"unrealized":unreal,"equity":total+unreal,"entries":len(lots),"entry_quantity":sum(l["quantity"] for l in lots.values()),"parents":len(parents),"completed_parents":len(completed),"remaining_qty":sum(l["remaining"] for l in lots.values()),"positive_then_loss_count":sum(p["positive_then_loss"] for p in completed),"max_parent_loss":max((max(0,-p["net"]) for p in completed),default=0),"allocation_profit":allocation_profit,"allocation_loss":allocation_loss,"positive_then_loss_piece_count":sum(p["positive_then_loss"] for p in pieces),"positive_then_loss_piece_quantity":sum(p["quantity"] for p in pieces if p["positive_then_loss"]),"protected_loss_piece_count":sum(p["protected"] and p["net"]<0 for p in pieces),"unprotected_loss_piece_count":sum(not p["protected"] and p["net"]<0 for p in pieces),"protection_exit_loss":sum(-p["net"] for p in pieces if p["reason"] in (15601,15602) and p["net"]<0),"gate_rejections":len((case.get("protection156") or {}).get("Rejected") or []),"entry_rejections":len((case.get("protection156") or {}).get("EntryRejected") or []),"final_pending_count":len(case.get("final_pending") or []),**verify_limits(case)}
    row["protection_loss_nonnegative_decision"] = sum(-p["net"] for p in pieces if p["reason"] in (15601,15602) and p["net"]<0 and p["decision_gain_yen"]>=0)
    row["protection_loss_negative_decision"] = sum(-p["net"] for p in pieces if p["reason"] in (15601,15602) and p["net"]<0 and p["decision_gain_yen"]<0)
    row["by_owner"]={owner:{"net":sum(p["net"] for p in parents.values() if p["owner"]==owner),"profit":sum(max(0,p["net"]) for p in completed if p["owner"]==owner),"loss":sum(max(0,-p["net"]) for p in completed if p["owner"]==owner),"entries":sum(l["owner"]==owner for l in lots.values()),"parents":sum(p["owner"]==owner for p in parents.values()),"positive_then_loss_count":sum(p["positive_then_loss"] for p in completed if p["owner"]==owner)} for owner in ("core","addon","episode")}
    details = {"row":row,"parents":list(parents.values()),"lots":list(lots.values()),"pieces":pieces,"entry_rejections":(case.get("protection156") or {}).get("EntryRejected") or [],"gate_rejections":(case.get("protection156") or {}).get("Rejected") or []}
    return row,details


def summarize(rows: list[dict]) -> dict:
    """完了場だけの比較値を集計する。

    引数: 主行list。
    返り値: 集計dict。
    """
    keys = ("profit","loss","net","entries","entry_quantity","parents","completed_parents","positive_then_loss_count","positive_then_loss_piece_count","positive_then_loss_piece_quantity","protected_loss_piece_count","unprotected_loss_piece_count","protection_exit_loss","protection_loss_nonnegative_decision","protection_loss_negative_decision","gate_rejections","entry_rejections")
    out = {k:sum(r[k] for r in rows) for k in keys}
    losses = [-r["net"] for r in rows if r["net"]<0]
    out.update(sessions=len(rows),wins=sum(r["net"]>0 for r in rows),losses=len(losses),zeros=sum(r["net"]==0 for r in rows),no_trade=sum(r["entries"]==0 for r in rows),avgloss=statistics.mean(losses) if losses else 0,medianloss=statistics.median(losses) if losses else 0,maxloss=max(losses,default=0),max_parent_loss=max((r["max_parent_loss"] for r in rows),default=0))
    out["ex3"] = out["net"]-sum(sorted([max(0,r["net"]) for r in rows],reverse=True)[:3])
    out["pf"] = out["profit"]/out["loss"] if out["loss"] else None
    return out


def compare_parents(base: dict, other: dict) -> dict:
    """同じ初回原行の親だけを対応させ、消えた勝敗と新設を分離する。

    引数: 基準/候補詳細dict。
    返り値: 差分dict。
    """
    key = lambda p:(p["owner"],p["side"],p["first_decision_index"])
    b = {key(p):p for p in base["parents"]}
    c = {key(p):p for p in other["parents"]}
    assert len(b)==len(base["parents"]) and len(c)==len(other["parents"])
    missing = [b[k] for k in b.keys()-c.keys()]
    added = [c[k] for k in c.keys()-b.keys()]
    shared = [{"key":list(k),"owner":b[k]["owner"],"side":b[k]["side"],"entry_time":b[k]["entry_time"],"base_net":b[k]["net"],"candidate_net":c[k]["net"],"delta":c[k]["net"]-b[k]["net"],"base_peak":b[k]["peak"],"candidate_peak":c[k]["peak"]} for k in b.keys() & c.keys()]
    delta = sum(p["net"] for p in added)-sum(p["net"] for p in missing)+sum(p["delta"] for p in shared)
    equal(delta,other["row"]["net"]-base["row"]["net"],"親差分恒等式")
    return {"session":base["row"]["session"],"id":other["row"]["id"],"delta":delta,"lost_win":sum(max(0,p["net"]) for p in missing),"avoided_loss":sum(max(0,-p["net"]) for p in missing),"added_net":sum(p["net"] for p in added),"shared_delta":sum(p["delta"] for p in shared),"missing":missing,"added":added,"shared":shared}


def baseline_events(scene: dict, case: dict) -> dict:
    """完了場の基準全約定を155保存値と独立照合する。

    引数: 場/基準case。
    返り値: 指紋と件数dict。
    """
    path=BASE.parent/"s01_155"/"results"/(scene["session"]+".json")
    payload=path.read_bytes();digest=hashlib.sha256(payload).hexdigest()
    expected=next(c for c in json.loads(payload)["cases"] if c["method"]=="S01")
    assert len(expected["events"])==len(case["events"] or [])
    for a,b in zip(expected["events"],case["events"] or []):
        sa={k:v for k,v in a["signal"].items() if k!="evidence"}
        sb={k:v for k,v in b["signal"].items() if k!="evidence"}
        assert sa==sb, "基準の注文変更"
        for key in ("fill","decision_index","fill_index","gross"):
            assert a[key]==b[key], "基準約定変更"+key
    equal(expected["gross"],case["Gross"],"基準実現")
    equal(expected["unrealized"],case["Unrealized"],"基準含み")
    assert digest==hashlib.sha256(path.read_bytes()).hexdigest()
    return {"path":str(path),"sha256":digest,"unchanged":True,"events":len(expected["events"]),"match":True}


def main() -> None:
    """登録後に完成した保存結果だけを再会計する。

    引数: CLI --results/--out。
    返り値: なし。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument("--results",type=Path,default=BASE/"results_go")
    parser.add_argument("--out",type=Path,default=BASE/"report156.json")
    args=parser.parse_args()
    manifest=json.loads((BASE/"inputs156.json").read_text(encoding="utf-8"))
    configs=json.loads((BASE/"configs156.json").read_text(encoding="utf-8"))
    scenes=manifest["sessions"]
    assert len(scenes)==27 and len(configs)==26
    files=[args.results/(s["session"]+"_S01.json") for s in scenes]
    if not all(p.exists() for p in files):
        raise SystemExit("27結果が完成する前の集計はしません")
    rows=defaultdict(list); partial=[]; audits=[]; comparisons=defaultdict(list); case_count=0
    for scene,path in zip(scenes,files):
        before=hashlib.sha256(path.read_bytes()).hexdigest()
        saved=json.loads(path.read_text(encoding="utf-8"))
        assert len(saved["cases"])==26 and saved["scene"]["session"]==scene["session"]
        raw,fingerprint=raw_quotes(scene);valid=normal_indices(raw)
        details={}
        for case,cfg in zip(saved["cases"],configs):
            assert case["config"]==cfg
            for key,value in fingerprint["counts"].items():
                equal(case["counts"].get("NK225_"+key,0),value,scene["session"]+key)
            row,detail=analyze_case(case,scene,raw,valid)
            details[cfg["id"]]=detail
            if scene["partial"]:partial.append(row)
            else:rows[cfg["id"]].append(row)
            write_json(BASE/"audit"/"cases"/scene["session"]/(cfg["id"]+".json"),detail)
            case_count+=1
        if not scene["partial"]:
            for cfg in configs[1:]:
                comparisons[cfg["id"]].append(compare_parents(details["S01"],details[cfg["id"]]))
        after=hashlib.sha256(path.read_bytes()).hexdigest();assert before==after
        baseline_check=baseline_events(scene,saved["cases"][0]) if not scene["partial"] else None
        audits.append({"session":scene["session"],"cases":26,"result_sha256":before,"unchanged":True,"raw":fingerprint,"saved_baseline":baseline_check})
        print(json.dumps({"session":scene["session"],"checked":case_count},ensure_ascii=True),flush=True)
    methods=[]
    for cfg in configs:
        rr=rows[cfg["id"]];assert len(rr)==26
        methods.append({"id":cfg["id"],"description":cfg["description"],"config":cfg,"rows":rr,"summary":summarize(rr),"up":summarize([r for r in rr if r["direction"]=="上昇"]),"down":summarize([r for r in rr if r["direction"]=="下落"]),"flat":summarize([r for r in rr if r["direction"]=="横ばい"])})
    baseline=next(m for m in methods if m["id"]=="S01")
    equal(baseline["summary"]["net"],1935000,"155基準26Day収支")
    equal(baseline["summary"]["losses"],8,"155基準26Day赤字場数")
    assert len(partial)==26 and case_count==702
    report={"created_at":datetime.now(JST).isoformat(),"scope":"26完了Dayと1途中Day、26条件、金融再生なしの独立再会計","account":"完結owner/campaign親の純額を正負分類。途中は未完結親実現を別計上。","direction":"入力目録の最初/最後の有効Last代理による事後分類。公式始終値ではなく、売買条件へ渡さない。","methods":methods,"current_rows":partial,"partial":partial,"case_count":case_count,"validation":{"case_accounting_matches":case_count,"saved_baseline_sessions":sum(a["saved_baseline"] is not None for a in audits),"raw_nk_sha_matches":len(audits),"all_fills_next_normal_raw":True,"lots_parents_extrema_from_all_raw":True,"reserved_caps":True,"baseline_155":True,"source_results_unchanged":True},"source_sha256":audits}
    write_json(args.out,report)
    write_json(BASE/"audit"/"comparisons156.json",dict(comparisons))
    write_json(BASE/"audit"/"account156.json",{"cases":case_count,"report_sha256":hashlib.sha256(args.out.read_bytes()).hexdigest(),"sources":audits})
    print(json.dumps({"complete":True,"cases":case_count,"report":str(args.out)},ensure_ascii=True),flush=True)


if __name__=="__main__":
    main()
