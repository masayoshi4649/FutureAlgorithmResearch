"""00164夜間の保存結果を、全再生完了後にだけ説明用に再会計する。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
JST = timezone(timedelta(hours=9))


def read(path: Path):
    """有限JSONを読み取る。

    引数: path(Path)。返り値: dict又はlist。
    """
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    json.dumps(value, allow_nan=False)
    return value


def sha(path: Path) -> str:
    """根拠ファイルを全読して内容指紋を返す。

    引数: path(Path)。返り値: str。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def resolve(path: str) -> Path:
    """プロジェクト相対又は絶対の根拠位置を解決する。

    引数: path(str)。返り値: Path。
    """
    p = Path(path)
    return p if p.is_absolute() else ROOT/p


def verify(item: dict) -> Path:
    """保存された指紋を先に照合する。

    引数: item(dict)。返り値: Path。不一致は例外にする。
    """
    path = resolve(item["path"])
    assert sha(path) == item["sha256"], f"根拠変更: {path}"
    return path


def completed_inputs(completion: Path) -> tuple[dict, list[tuple[str, Path]]]:
    """rootの全完了証跡を通過してからだけ結果パスを返す。

    引数: completion(Path)。返り値: (dict,list[tuple[str,Path]])。
    """
    final = read(completion)
    assert final.get("completed") is True
    assert type(final.get("returncode")) is int and final["returncode"] == 0
    assert final["sessions"] == 54 and final["cases"] == 540
    assert final.get("reselection_after_confirmation") is False
    frozen = read(verify(final["freeze"]))
    assert frozen["selected"] == final["selected"] and frozen["test_opened"] is False
    results = []
    seen = set()
    for item in final["proofs"]:
        proof = read(verify(item))
        stage = proof["stage"]["stage"]
        assert stage in {"train_validation", "confirmation"}
        assert proof["completed"] is True and proof["returncode"] == 0
        assert proof["sources_unchanged"] is True
        expected = (40, 400) if stage == "train_validation" else (14, 140)
        assert (proof["sessions"], proof["cases"]) == expected
        if stage == "confirmation":
            assert proof["stage"]["selected"] == final["selected"]
            assert proof["stage"]["freeze_sha256"] == final["freeze"]["sha256"]
        for source in proof["sources"]:
            verify(source)
        for result in proof["results"]:
            assert result["session"] not in seen
            seen.add(result["session"])
            path = verify(result)
            if result["session"].endswith("_Night"):
                results.append((stage, path))
    assert len(seen) == 54 and len(results) == 27
    return final, sorted(results, key=lambda x: x[1].name)


def timestamp(value: float | None) -> str | None:
    """価格時計を日本時間の表示へ変換する。

    引数: value(float又はNone)。返り値: str又はNone。
    """
    return datetime.fromtimestamp(value, JST).isoformat() if value is not None else None


def distribution(values: list[float]) -> dict:
    """有限な測定値の件数と補間四分位を返す。

    引数: values(list[float])。返り値: dict。未知を0へしない。
    """
    values = sorted(v for v in values if v is not None and math.isfinite(v))
    def q(p):
        if not values:
            return None
        at = (len(values)-1)*p
        lo = int(at)
        return values[lo]+(values[min(lo+1, len(values)-1)]-values[lo])*(at-lo)
    return {"count":len(values), "q25":q(.25), "median":q(.5), "q75":q(.75), "max":max(values) if values else None}


def raw_quotes(scene: dict):
    """Go読取と同じ採番で日経の原板を独立に読む。

    引数: scene(dict)。返り値: iterator[dict]。受信時計や欠測価格を補間しない。
    """
    path = resolve(scene["books"]["NK225"])
    expected = next(x for x in scene["fingerprints"] if resolve(x["path"]) == path)
    previous = scene["start"]
    index = 0
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for line, raw in enumerate(stream, 1):
            digest.update(raw)
            book = json.loads(raw)
            try:
                at = datetime.fromisoformat(book["CurrentPriceTime"].replace("Z", "+00:00")).timestamp()
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            if at < scene["start"] or at > scene["end"] or (scene["cutoff"] > 0 and at >= scene["cutoff"]):
                continue
            if at < previous:
                continue
            last = book.get("CurrentPrice")
            if not isinstance(last, (int,float)) or not math.isfinite(last) or last <= 0:
                continue
            previous = at
            bid = (book.get("Buy1") or {}).get("Price", 0) or 0
            ask = (book.get("Sell1") or {}).get("Price", 0) or 0
            good = math.isfinite(bid) and math.isfinite(ask) and 0 < bid < ask
            yield {"index":index, "physical_line":line, "time":at, "jst":timestamp(at), "bid":bid, "ask":ask, "last":last, "normal":good}
            index += 1
    assert digest.hexdigest() == expected["sha256"], f"原板変更: {path}"


def quality(features: dict | None) -> str:
    """新層の当時可用性と標本内異常を区別する。

    引数: features(dict又はNone)。返り値: str。
    """
    if features is None:
        return "基準_新層特徴未記録"
    if not (features.get("Known5") and features.get("Known15") and features.get("Path15") and features.get("Known300")):
        return "必要端点未知"
    if any(features.get(k, 0) for k in ("Invalid15","Invalid60","Invalid120","Invalid300","Gaps15","Gaps60","Gaps120","Gaps300")):
        return "既知_内部異常又は空白あり"
    return "既知_内部異常空白なし"


def role(kind: str) -> str:
    """担当名とは別に実注文の数量役割を定義する。

    引数: kind(str)。返り値: str。
    """
    return {"initial":"初回", "source_add":"元Source追加", "初回":"初回", "順行追加":"順行追加", "利益後再参加":"利益後再参加"}.get(kind, kind)


def prepare_case(case: dict, session: str, stage: str) -> dict:
    """保存全約定から玉・配賦・親・当時特徴を対応する。

    引数: case(dict)、session/stage(str)。返り値: dict。
    """
    ledger = case["actual"]
    assert not ledger["Active"] and not ledger["Pending"]
    assert all(x["Remaining"] == 0 for x in ledger["Lots"].values())
    traces = case.get("trigger_trace") or []
    features = {x["OrderID"]:x["Features"] for x in traces if x["Kind"] == "新規"}
    activations = {x["OrderID"]:x for x in traces if x["Kind"] == "保護起動"}
    lots = {}
    fills = defaultdict(list)
    pieces = []
    events = ledger["Events"] or []
    for event in events:
        fills[event["FillIndex"]].append(event)
        order = event["Order"]
        assert event["FillIndex"] > order["DecisionIndex"]
        if not order["Targets"]:
            saved = ledger["Lots"][event["HoldID"]]
            lots[event["HoldID"]] = dict(saved, method=case["config"]["id"], scope=case["config"]["scope"], session=session, stage=stage,
                role=role(order["Kind"]), entry_order=order, entry_event=event, entry_features=features.get(order["ID"]),
                entry_quality=quality(features.get(order["ID"])), activation=activations.get(event["HoldID"]),
                exits=[], first_positive=None, first_minus50=None, first_plus50=None, first_plus100=None,
                small_remaining_first_positive=None, small_remaining_best=0.0,
                observed_best=0.0, observed_worst=0.0, adverse_first60=0.0, bad_bbo_rows=0, max_clock_gap=0.0,
                remaining=0, reaction_seconds=None, reaction_raw_rows=None, initial_guard=case.get("guards",{}).get(event["HoldID"]))
        else:
            reconstructed = 0.0
            for piece in event["Pieces"]:
                lot = lots[piece["ID"]]
                assert piece["Quantity"] > 0 and piece["Entry"] == lot["Entry"]
                gross = lot["Side"]*(piece["Exit"]-piece["Entry"])*piece["Quantity"]*10
                assert abs(gross-piece["Gross"]) < 1e-6
                entry = lot["entry_event"]
                mid_move = lot["Side"]*((event["Bid"]+event["Ask"])-(entry["Bid"]+entry["Ask"]))/2*piece["Quantity"]*10
                spread = ((event["Ask"]-event["Bid"])+(entry["Ask"]-entry["Bid"]))/2*piece["Quantity"]*10
                assert abs(gross-(mid_move-spread)) < 1e-6
                detail = dict(piece, reason=order["Reason"], decision_index=order["DecisionIndex"], decision_time=order["DecisionTime"],
                    remaining_before=lot["Quantity"]-sum(x["Quantity"] for x in lot["exits"]),
                    fill_index=event["FillIndex"], fill_time=event["FillTime"], decision_jst=timestamp(order["DecisionTime"]), fill_jst=timestamp(event["FillTime"]),
                    decision_bid=order["DecisionBid"], decision_ask=order["DecisionAsk"], fill_bid=event["Bid"], fill_ask=event["Ask"],
                    mid_move_yen=mid_move, bbo_cost_yen=spread,
                    decision_gain=lot["Side"]*((order["DecisionBid"] if lot["Side"] > 0 else order["DecisionAsk"])-lot["Entry"]),
                    decision_to_fill_seconds=event["FillTime"]-order["DecisionTime"], decision_to_fill_rows=event["FillIndex"]-order["DecisionIndex"])
                lot["exits"].append(detail)
                pieces.append(dict(detail, method=case["config"]["id"], session=session, role=lot["role"]))
                reconstructed += gross
            assert abs(reconstructed-event["Gross"]) < 1e-6
    assert abs(sum(x["Gross"] for x in lots.values())-ledger["Realized"]) < 1e-6
    for lot in lots.values():
        assert sum(x["Quantity"] for x in lot["exits"]) == lot["Quantity"]
        assert abs(sum(x["Gross"] for x in lot["exits"])-lot["Gross"]) < 1e-6
    return {"case":case, "lots":lots, "fills":fills, "pieces":pieces, "active":{}, "last_quote":None, "references":{}}


def mark_lot(lot: dict, quote: dict) -> None:
    """実保有中だけ返済側の初到達と順逆行を記録する。

    引数: lot/quote(dict)。返り値: None。元退出後へ伸ばさない。
    """
    if not quote["normal"]:
        lot["bad_bbo_rows"] += 1
        return
    price = quote["bid"] if lot["Side"] > 0 else quote["ask"]
    gain = lot["Side"]*(price-lot["Entry"])
    if 0 < lot["remaining"] <= 20:
        lot["small_remaining_best"] = max(lot["small_remaining_best"], gain)
        if gain > 0 and lot["small_remaining_first_positive"] is None:
            lot["small_remaining_first_positive"] = dict(quote, gain=gain, remaining_micro=lot["remaining"])
    lot["observed_best"] = max(lot["observed_best"], gain)
    lot["observed_worst"] = min(lot["observed_worst"], gain)
    if quote["time"]-lot["At"] <= 60:
        lot["adverse_first60"] = min(lot["adverse_first60"], gain)
    for key, reached in (("first_positive",gain>0),("first_minus50",gain<=-50),("first_plus50",gain>=50),("first_plus100",gain>=100)):
        if reached and lot[key] is None:
            lot[key] = dict(quote, gain=gain)


def trace_raw(states: list[dict], quotes) -> None:
    """全候補の保存約定を同じ原行へ当て、保有中の事後診断だけを行う。

    引数: states(list[dict])、quotes(iterator)。返り値: None。新規判断や注文を生成しない。
    """
    wanted = set()
    for state in states:
        for event in state["case"]["actual"]["Events"] or []:
            wanted.add(event["FillIndex"])
            wanted.add(event["Order"]["DecisionIndex"])
        for trace in state["case"].get("trigger_trace") or []:
            wanted.add(trace["Index"])
    references = {}
    for quote in quotes:
        index = quote["index"]
        if index in wanted:
            references[index] = quote
        for state in states:
            prev = state["last_quote"]
            for lot in state["active"].values():
                if prev is not None:
                    lot["max_clock_gap"] = max(lot["max_clock_gap"], quote["time"]-prev["time"])
                mark_lot(lot, quote)
            for event in state["fills"].get(index, []):
                assert quote["normal"] and abs(event["FillTime"]-quote["time"]) < 1e-5
                assert event["Bid"] == quote["bid"] and event["Ask"] == quote["ask"]
                if not event["Order"]["Targets"]:
                    lot = state["lots"][event["HoldID"]]
                    lot["remaining"] = lot["Quantity"]
                    state["active"][lot["ID"]] = lot
                    lot["entry_raw"] = quote
                    mark_lot(lot, quote)
                else:
                    for piece in event["Pieces"]:
                        lot = state["active"][piece["ID"]]
                        lot["remaining"] -= piece["Quantity"]
                        if lot["remaining"] == 0:
                            del state["active"][piece["ID"]]
            state["last_quote"] = quote
    for state in states:
        assert not state["active"]
        state["references"] = references
        for lot in state["lots"].values():
            assert abs(lot["observed_best"]-lot["Best"]) < 1e-5
            assert abs(lot["observed_worst"]-lot["Worst"]) < 1e-5
            for ex in lot["exits"]:
                ex["decision_raw"] = references[ex["decision_index"]]
                ex["fill_raw"] = references[ex["fill_index"]]
            lot["decision_raw"] = references[lot["entry_order"]["DecisionIndex"]]
            activation = lot["activation"]
            if activation:
                lot["activation_raw"] = references[activation["Index"]]
            if lot["first_positive"]:
                protective = [x for x in lot["exits"] if x["reason"] == "利益床" and x["decision_index"] >= lot["first_positive"]["index"]]
                if protective:
                    first = min(protective, key=lambda x:x["decision_index"])
                    lot["reaction_seconds"] = first["decision_time"]-lot["first_positive"]["time"]
                    lot["reaction_raw_rows"] = first["decision_index"]-lot["first_positive"]["index"]


def summarize(lots: list[dict]) -> dict:
    """完結玉と返済配賦を分離して要約する。

    引数: lots(list[dict])。返り値: dict。
    """
    exits = [x for lot in lots for x in lot["exits"]]
    return {"lots":len(lots), "quantity_micro":sum(x["Quantity"] for x in lots), "net":sum(x["Gross"] for x in lots),
        "profit_completed_lots":sum(max(0,x["Gross"]) for x in lots), "loss_completed_lots":sum(max(0,-x["Gross"]) for x in lots),
        "positive_then_loss_lots":sum(x["Best"]>0 and x["Gross"]<0 for x in lots),
        "positive_then_loss_lot_net":sum(x["Gross"] for x in lots if x["Best"]>0 and x["Gross"]<0),
        "positive_then_loss_pieces":sum(x["Best"]>0 and x["Gross"]<0 for x in exits),
        "initial_small_positive_then_loss_lots":sum(x["Quantity"]<=20 and x["Best"]>0 and x["Gross"]<0 for x in lots),
        "small_residual_positive_then_negative_pieces":sum(ex["remaining_before"]<=20 and ex["Gross"]<0 and lot["small_remaining_first_positive"] is not None and lot["small_remaining_first_positive"]["index"]<=ex["fill_index"] for lot in lots for ex in lot["exits"]),
        "zero_favorable_loss_lots":sum(x["Best"]<=0 and x["Gross"]<0 for x in lots),
        "first60_adverse50_lots":sum(x["adverse_first60"]<=-50 for x in lots),
        "activated_lots":sum(x["activation"] is not None for x in lots),
        "activation_measurement":"新案だけ。基準00の保護起動はこのtraceでは未測定",
        "floor_gap_negative_pieces":sum(x["reason"]=="利益床" and x["decision_gain"]>=0 and x["Gross"]<0 for x in exits),
        "floor_gap_negative_net":sum(x["Gross"] for x in exits if x["reason"]=="利益床" and x["decision_gain"]>=0 and x["Gross"]<0),
        "mid_move_yen":sum(x["mid_move_yen"] for x in exits), "bbo_cost_yen":sum(x["bbo_cost_yen"] for x in exits),
        "decision_to_entry_seconds":distribution([x["At"]-x["entry_order"]["DecisionTime"] for x in lots]),
        "decision_to_exit_seconds":distribution([x["decision_to_fill_seconds"] for x in exits]),
        "first_positive_to_floor_decision_seconds":distribution([x["reaction_seconds"] for x in lots]),
        "first_positive_to_floor_decision_raw_rows":distribution([x["reaction_raw_rows"] for x in lots]),
        "holding_seconds":distribution([x["exits"][-1]["fill_time"]-x["At"] for x in lots]),
        "quality_counts":dict(Counter(x["entry_quality"] for x in lots)),
        "holding_gap_gt15_lots":sum(x["max_clock_gap"]>15 for x in lots),
        "holding_gap_gt60_lots":sum(x["max_clock_gap"]>60 for x in lots),
        "holding_bad_bbo_lots":sum(x["bad_bbo_rows"]>0 for x in lots)}


def pair_lots(base: list[dict], candidate: list[dict]) -> dict:
    """同じ判断原行・方向・数量役割・担当の実玉だけを対応し、それ以外は別掲する。

    引数: base/candidate(list[dict])。返り値: dict。時間の近さで勝手に同波扱いしない。
    """
    def key(x):
        return x["session"],x["entry_order"]["DecisionIndex"],x["Side"],x["role"],x["Owner"]
    left, right = defaultdict(list), defaultdict(list)
    for x in base: left[key(x)].append(x)
    for x in candidate: right[key(x)].append(x)
    matched=[]
    paired=set()
    ambiguous=[]
    for k in sorted(left.keys() & right.keys()):
        if len(left[k])!=1 or len(right[k])!=1:
            ambiguous.append({"key":list(k),"base_count":len(left[k]),"candidate_count":len(right[k])})
            continue
        a,b=left[k][0],right[k][0]
        paired.add(k)
        matched.append({"session":a["session"],"decision_index":k[1],"side":k[2],"role":k[3],"owner":k[4],"base_id":a["ID"],"candidate_id":b["ID"],
            "base_quantity":a["Quantity"],"candidate_quantity":b["Quantity"],"base_net":a["Gross"],"candidate_net":b["Gross"],"delta":b["Gross"]-a["Gross"]})
    return {"matched":matched,"ambiguous_unmatched_keys":ambiguous,
        "base_only":[{"session":x["session"],"id":x["ID"],"net":x["Gross"]} for k in sorted(left.keys()-paired) for x in left[k]],
        "candidate_only":[{"session":x["session"],"id":x["ID"],"net":x["Gross"]} for k in sorted(right.keys()-paired) for x in right[k]]}



def build_report(final: dict, items: list[tuple[str,Path]]) -> dict:
    """許可済み夜27場の診断を組み立てる。

    引数: final(dict)、items(list[tuple[str,Path]])。返り値: dict。売買再生は呼ばない。
    """
    all_lots=[];case_rows=[];evidence=[]
    for stage,path in items:
        saved=read(path);scene=saved["scene"];assert scene["kind"]=="Night" and len(saved["cases"])==8
        states=[prepare_case(c,scene["session"],stage) for c in saved["cases"]]
        trace_raw(states,raw_quotes(scene))
        for state in states:
            case=state["case"];lots=list(state["lots"].values());all_lots.extend(lots)
            case_rows.append({"session":scene["session"],"stage":stage,"id":case["config"]["id"],"scope":case["config"]["scope"],
                "summary":summarize(lots),"risk":case["actual"]["Risk"],"counts":case["counts"],
                "roles":{name:summarize([x for x in lots if x["role"]==name]) for name in sorted({x["role"] for x in lots})}})
        evidence.append({"path":str(path),"sha256":sha(path),"raw":next(x for x in scene["fingerprints"] if resolve(x["path"])==resolve(scene["books"]["NK225"]))})
        print("診断完了 "+scene["session"],flush=True)
    methods={}
    for ident in sorted({x["id"] for x in case_rows}):
        lots=[x for x in all_lots if x["method"]==ident]
        methods[ident]={"all":summarize(lots),"stages":{s:summarize([x for x in lots if x["stage"]==s]) for s in ("train_validation","confirmation")},
            "roles":{r:summarize([x for x in lots if x["role"]==r]) for r in sorted({x["role"] for x in lots})},
            "quality":{q:summarize([x for x in lots if x["entry_quality"]==q]) for q in sorted({x["entry_quality"] for x in lots})}}
    comparisons={}
    for group in ("P","U"):
        for left,right in ((0,1),(0,2),(0,3),(1,2),(2,3)):
            a,b=f"NK225_{group}164_{left:02d}",f"NK225_{group}164_{right:02d}"
            rows=[]
            for scene in sorted({x["session"] for x in case_rows}):
                old=next(x for x in case_rows if x["id"]==a and x["session"]==scene)
                new=next(x for x in case_rows if x["id"]==b and x["session"]==scene)
                rows.append({"session":scene,"stage":old["stage"],"base_net":old["summary"]["net"],"candidate_net":new["summary"]["net"],"delta":new["summary"]["net"]-old["summary"]["net"],
                    "base_minimum":old["risk"]["Minimum"],"candidate_minimum":new["risk"]["Minimum"],"base_dd":old["risk"]["MaxDD"],"candidate_dd":new["risk"]["MaxDD"]})
            comparisons[a+"→"+b]={"type":"手法全体差。入口が異なる" if left==0 else "事前固定の累積対照。ただし退出後の入口系列変化も含む", "sessions":rows,
                "worst":min(rows,key=lambda x:(x["delta"],x["session"])),"best":max(rows,key=lambda x:(x["delta"],x["session"])),
                "lots":pair_lots([x for x in all_lots if x["method"]==a],[x for x in all_lots if x["method"]==b])}
    examples=[]
    for key, comparison in comparisons.items():
        if "_00→" in key:
            continue
        base_id,candidate_id=key.split("→")
        for label in ("worst","best"):
            row=comparison[label]
            candidates={}
            for ident in (base_id,candidate_id):
                chosen=sorted((x for x in all_lots if x["method"]==ident and x["session"]==row["session"]),key=lambda x:(-abs(x["Gross"]),x["EntryIndex"],x["ID"]))[:3]
                candidates[ident]=chosen
            examples.append({"comparison":key,"selection":label,"scene_difference":row,"largest_absolute_lots":candidates,
                "meaning":"場差の最大局面で寄与額の大きい実玉を抽出。同じ波又は同じ親と認定したものではない"})
    return {"completed":True,"financial_replays":0,"source_changed":False,"selected":final["selected"],"definitions":{
        "positive_then_loss":"実新規約定IDごと。保有中最高返済側gain>0かつ完結全返済Gross<0。部分piece件数とは別",
        "reaction":"最初の正利益観測から利益床の最初の返済判断まで。基準00は新層の起動trace未測定。判断→次板実約定を別記",
        "additional_adverse":"追加実約定後60価格秒内に返済側gain<=-50を観測。実保有終了までで打切り、未来の回復を含めない",
        "quality":"当時端点既知と内部異常/空白は別。基準00の新層特徴は未記録で未知扱いしない",
        "ownership":"担当名addonとsource_add/順行追加を混同しない。買売・役割・親IDは各保存通知に従う",
        "time":"CurrentPriceTimeの代理。受信時計・実注文所要時間の保証ではない"},"evidence":evidence,"methods":methods,"cases":case_rows,"comparisons":comparisons,"examples":examples,"lots":all_lots}


def write_report(report: dict, out: Path) -> None:
    """診断を新規JSONと短い日本語表へ保存する。

    引数: report(dict)、out(Path)。返り値: None。既存成果を上書きしない。
    """
    out.mkdir(parents=True,exist_ok=True)
    path=out/"夜間の具体診断164.json"
    with path.open("x",encoding="utf-8") as stream:
        json.dump(report,stream,ensure_ascii=False,allow_nan=False,separators=(",",":"));stream.write("\n")
    lines=["# 夜間の具体診断164","","保存約定と同じ原板だけを再会計した事後説明。入口・選択・金融結果は変更していない。","","|手法|完結玉収支|正利益後の赤字玉|順行ゼロ赤字玉|保護床の次板赤字配賦|","|---|---:|---:|---:|---:|"]
    for ident,method in report["methods"].items():
        v=method["all"];lines.append(f"|{ident}|{v['net']:,.0f}|{v['positive_then_loss_lots']}|{v['zero_favorable_loss_lots']}|{v['floor_gap_negative_pieces']}|")
    lines += ["","00→01は入口・数量・出口を含む手法全体差。01→02は利益保護、02→03は再参加の対照だが、早期退出後の入口系列も変化する。同じ原行・方向・数量役割の玉だけ対応し、消えた玉と新しく生じた玉はJSONへ別記した。","","|対照|最悪差の場|収支差|改善最大の場|収支差|","|---|---|---:|---|---:|"]
    for key,v in report["comparisons"].items():
        if "_00→" in key:continue
        a,b=v["worst"],v["best"];lines.append(f"|{key}|{a['session']}|{a['delta']:,.0f}|{b['session']}|{b['delta']:,.0f}|")
    lines += ["","|主要悪化場の候補玉|入口時刻・方向・建値|最終返済時刻|micro数|玉収支|","|---|---|---|---:|---:|"]
    for example in sorted((x for x in report["examples"] if x["selection"]=="worst"),key=lambda x:x["scene_difference"]["delta"])[:3]:
        ident=example["comparison"].split("→")[1]
        lots=example["largest_absolute_lots"][ident]
        if not lots:continue
        lot=lots[0];side="買" if lot["Side"]>0 else "売"
        lines.append(f"|{lot['session']} {ident} {lot['role']}|{timestamp(lot['At'])} {side} {lot['Entry']:g}|{lot['exits'][-1]['fill_jst']}|{lot['Quantity']}|{lot['Gross']:,.0f}|")
    lines += ["","上の玉は場差への寄与額が大きい事後説明例で、元手法と同一の親とは限らない。役割別損益、各玉の初正利益・追加後60秒逆行、全返済判断/次板約定、原板物理行、時価最悪/DDの根拠はJSONに保存。利益起動のtraceがない基準00を無保護と認定していない。5/15秒等は価格時計に基づく観測で、通信や取引所での瞬間応答を測った値ではない。",""]
    with (out/"夜間の具体診断164.md").open("x",encoding="utf-8") as stream:stream.write("\n".join(lines))


def main() -> None:
    """root全完了の検査後に限り夜間診断を実行する。

    引数: CLI(--completion,--out)。返り値: None。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument("--completion",type=Path,default=STUDY/"再生全完了164.json")
    parser.add_argument("--out",type=Path,default=HERE/"results")
    args=parser.parse_args()
    final,items=completed_inputs(args.completion)
    report=build_report(final,items)
    write_report(report,args.out)


if __name__=="__main__":
    main()
