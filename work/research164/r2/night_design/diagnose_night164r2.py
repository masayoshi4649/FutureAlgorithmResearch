"""第二巡の全完了後だけ、元夜間入口と実玉保護の差を保存約定から説明する。"""
from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
import copy
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
BASE_STUDY = STUDY.parent
spec = importlib.util.spec_from_file_location("night_first164", BASE_STUDY/"night_design/diagnose_night164.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def completed_inputs(path: Path):
    """全54場324条件場の完了と選択不変を確認してから結果位置を返す。

    引数: path(Path)。返り値: (dict,list[tuple[str,Path]])。完了前は結果を開かない。
    """
    final = base.read(path)
    assert final.get("completed") is True and type(final.get("returncode")) is int and final["returncode"] == 0
    assert (final["sessions"], final["cases"]) == (54, 324)
    assert final.get("reselection_after_confirmation") is False
    frozen = base.read(base.verify(final["freeze"]))
    assert frozen["test_opened"] is False and frozen["selected"] == final["selected"]
    results, seen, stages = [], set(), set()
    for record in final["proofs"]:
        proof = base.read(base.verify(record))
        stage = proof["stage"]["stage"]
        assert stage not in stages and stage in {"train_validation", "confirmation"}
        stages.add(stage)
        assert proof["completed"] is True and type(proof["returncode"]) is int and proof["returncode"] == 0
        assert proof["sources_unchanged"] is True
        assert (proof["sessions"], proof["cases"]) == ((40,240) if stage == "train_validation" else (14,84))
        if stage == "confirmation":
            assert proof["stage"]["selected"] == final["selected"]
            assert proof["stage"]["freeze_sha256"] == final["freeze"]["sha256"]
        for source in proof["sources"]: base.verify(source)
        for item in proof["results"]:
            assert item["session"] not in seen
            seen.add(item["session"])
            verified = base.verify(item)
            if item["session"].endswith("_Night"):
                assert item["cases"] == 8
                results.append((stage, verified))
    assert len(seen) == 54 and len(results) == 27 and len(stages) == 2
    return final, sorted(results, key=lambda x:x[1].name)


def source_maps(sources: list[dict]) -> dict:
    """元通知だけから各SourceID・親残量と部分返済の判定を再構築する。

    引数: sources(list[dict])。返り値: dict。実候補の独自保護は源残量へ入れない。
    """
    result = {"closes":{}, "initials":{}, "history":defaultdict(dict)}
    holds, totals, initial_qty = {}, defaultdict(int), {}
    for source in sources:
        phase = source["Phase"]
        for stored in source["Signals"] or []:
            signal = {key:stored[field] for key,field in (("ID","id"),("Owner","owner"),("Action","action"),("Side","side"),("Quantity","quantity"),("Time","time"),("SourceIndex","source_index"),("Campaign","campaign"))}
            signal["Targets"] = stored.get("targets") or []
            sid = phase+"/"+signal["ID"]
            if signal["Action"] == "new":
                parent = f"{phase}/{signal['Owner']}/{signal['Campaign']}"
                qty = signal["Quantity"]*10
                holds[sid+"-玉"] = dict(parent=parent, quantity=qty)
                initial = parent not in initial_qty
                if initial: initial_qty[parent] = qty
                result["initials"][sid] = dict(parent=parent, initial=initial, initial_quantity=initial_qty[parent], quantity=qty, signal=signal, phase=phase)
                totals[parent] += qty
            else:
                parents = {holds[phase+"/"+x["id"]]["parent"] for x in signal["Targets"]}
                assert len(parents) == 1
                parent = parents.pop()
                for target in signal["Targets"]:
                    h = holds[phase+"/"+target["id"]]
                    h["quantity"] -= target["quantity"]*10
                    assert h["quantity"] >= 0
                totals[parent] -= signal["Quantity"]*10
                assert totals[parent] >= 0
                result["closes"][sid] = dict(parent=parent, partial=totals[parent]>0, remaining=totals[parent], decision_index=signal["SourceIndex"])
            result["history"][parent][signal["SourceIndex"]] = totals[parent]
    result["history"] = {p:sorted(v.items()) for p,v in result["history"].items()}
    return result


def remaining_source(maps: dict, parent: str, fill_index: int) -> int:
    """当該実約定原行より前に判断済みの源残量を返す。

    引数: maps(dict)、parent(str)、fill_index(int)。返り値: int。
    """
    history = maps["history"].get(parent, [])
    i = bisect_left([x[0] for x in history], fill_index)-1
    return history[i][1] if i >= 0 else 0


def short_quality(short: dict | None) -> str:
    """短期未記録と価格端点未知を区別する。

    引数: short(dict又はNone)。返り値: str。
    """
    if short is None: return "元基準_新短期未記録"
    return "短期両端既知" if short.get("Five",{}).get("Known") and short.get("Fifteen",{}).get("Known") else "短期未知"


def prepare_case(case: dict, session: str, stage: str, maps: dict) -> dict:
    """元SourceIDで実玉と延期通知を結び、資格付与を実約定順で再構築する。

    引数: case/maps(dict)、session/stage(str)。返り値: dict。
    """
    original = case.get("trigger_trace") or []
    adapted = copy.copy(case)
    adapted["trigger_trace"] = [dict(Kind="保護起動" if x["Action"]=="保護起動" else "診断", OrderID=x.get("ActualID", ""), Index=x["Index"], Time=x["Time"]) for x in original] if original and "Action" in original[0] else original
    state = base.prepare_case(adapted, session, stage)
    state["original_case"] = case
    entries = {x["SourceID"]:x for x in original if x.get("Action")=="新規受付" and x["Accepted"]>0}
    active = {}
    for n,event in enumerate(case["actual"]["Events"] or []):
        order = event["Order"]
        if not order["Targets"]:
            lot = state["lots"][event["HoldID"]]
            sid = lot["SourceID"] or order["ID"]
            source = maps["initials"][sid]
            assert source["parent"] == lot["Parent"] and source["signal"]["Side"] == lot["Side"]
            lot.update(source_id=sid, source_initial=source["initial"], source_initial_quantity=source["initial_quantity"], source_quantity=source["quantity"],
                       source_decision_index=source["signal"]["SourceIndex"], source_decision_time=source["signal"]["Time"],
                       role="初回" if source["initial"] else "元Source追撃", delayed=order["Kind"]=="delayed_initial",
                       entry_short=(entries.get(sid) or {}).get("Short"), residual_qualification=None,
                       residual_active=False, residual_best=0., residual_worst=0., residual_first_positive=None,
                       residual_realized=0., residual_pieces=[])
            lot["entry_quality"] = short_quality(lot["entry_short"])
            active[lot["ID"]] = lot["Quantity"]
        else:
            for piece in event["Pieces"]:
                active[piece["ID"]] -= piece["Quantity"]
                lot = state["lots"][piece["ID"]]
                ex = next(x for x in lot["exits"] if x["fill_index"]==event["FillIndex"] and x["decision_index"]==order["DecisionIndex"] and "event_ordinal" not in x)
                ex["event_ordinal"] = n
                if lot["residual_qualification"] is not None:
                    lot["residual_realized"] += piece["Gross"]
                    lot["residual_pieces"].append(ex)
            source_close = maps["closes"].get(order.get("SourceID") or order["ID"])
            if source_close and source_close["partial"] and event["Gross"]>0 and remaining_source(maps, order["Parent"], event["FillIndex"])>0:
                for lid,qty in active.items():
                    lot = state["lots"][lid]
                    if qty>0 and lot["Parent"]==order["Parent"] and lot["residual_qualification"] is None:
                        lot["residual_qualification"] = dict(index=event["FillIndex"], time=event["FillTime"], event_ordinal=n, order_id=order["ID"], quantity=qty, actual_partial_gross=event["Gross"])
    if case["config"].get("residual_floor"):
        for lid,lot in state["lots"].items():
            stored = (case.get("lot_states") or {}).get(lid) or {}
            assert bool(stored.get("ResidualEligible")) == (lot["residual_qualification"] is not None)
    return state


def mark(lot: dict, quote: dict) -> None:
    """実保有全体と部分返済後の残玉を別々に観測する。

    引数: lot/quote(dict)。返り値: None。
    """
    base.mark_lot(lot, quote)
    if lot["residual_active"] and quote["normal"]:
        gain = lot["Side"]*((quote["bid"] if lot["Side"]>0 else quote["ask"])-lot["Entry"])
        lot["residual_best"] = max(lot["residual_best"],gain)
        lot["residual_worst"] = min(lot["residual_worst"],gain)
        if gain>0 and lot["residual_first_positive"] is None: lot["residual_first_positive"] = dict(quote,gain=gain)


def trace_raw(states: list[dict], quotes) -> None:
    """原板を一度読み、次正常約定・保有極値・資格後の残玉を独立照合する。

    引数: states(list[dict])、quotes(iterator)。返り値: None。注文は生成しない。
    """
    wanted, decisions, next_normal, waiting = set(), set(), {}, set()
    for state in states:
        state["event_ordinals"] = {id(e):n for n,e in enumerate(state["case"]["actual"]["Events"] or [])}
        for event in state["case"]["actual"]["Events"] or []:
            decisions.add(event["Order"]["DecisionIndex"])
            wanted.update((event["FillIndex"],event["Order"]["DecisionIndex"]))
        wanted.update(t["Index"] for t in state["case"].get("trigger_trace") or [])
    refs = {}
    for quote in quotes:
        index = quote["index"]
        if quote["normal"]:
            for decision in waiting: next_normal[decision] = index
            waiting.clear()
        if index in decisions: waiting.add(index)
        if index in wanted: refs[index] = quote
        for state in states:
            previous = state["last_quote"]
            for lot in state["active"].values():
                if previous: lot["max_clock_gap"] = max(lot["max_clock_gap"],quote["time"]-previous["time"])
                mark(lot, quote)
            for event in state["fills"].get(index, []):
                assert quote["normal"] and event["Bid"]==quote["bid"] and event["Ask"]==quote["ask"] and event["FillTime"]==quote["time"]
                assert next_normal[event["Order"]["DecisionIndex"]] == index
                ordinal = state["event_ordinals"][id(event)]
                if not event["Order"]["Targets"]:
                    lot = state["lots"][event["HoldID"]];lot["remaining"] = lot["Quantity"]
                    state["active"][lot["ID"]] = lot;lot["entry_raw"] = quote;mark(lot,quote)
                else:
                    for piece in event["Pieces"]:
                        lot = state["active"][piece["ID"]];lot["remaining"] -= piece["Quantity"]
                        if lot["remaining"]==0: del state["active"][piece["ID"]]
                for lot in state["active"].values():
                    qualification = lot["residual_qualification"]
                    if qualification and qualification["event_ordinal"]==ordinal:
                        lot["residual_active"] = True;lot["residual_qualification_raw"] = quote;mark(lot,quote)
            state["last_quote"] = quote
    for state in states:
        assert not state["active"]
        state["references"] = refs
        for lot in state["lots"].values():
            assert abs(lot["Best"]-lot["observed_best"])<1e-6 and abs(lot["Worst"]-lot["observed_worst"])<1e-6
            lot["decision_raw"] = refs[lot["entry_order"]["DecisionIndex"]]
            for ex in lot["exits"]:
                ex["decision_raw"],ex["fill_raw"] = refs[ex["decision_index"]],refs[ex["fill_index"]]
            if lot["activation"]: lot["activation_raw"] = refs[lot["activation"]["Index"]]
            if lot["first_positive"]:
                protection = [x for x in lot["exits"] if x["reason"].startswith("protect_") and x["decision_index"]>=lot["first_positive"]["index"]]
                if protection:
                    first = min(protection,key=lambda x:x["decision_index"])
                    lot["reaction_seconds"] = first["decision_time"]-lot["first_positive"]["time"]
                    lot["reaction_raw_rows"] = first["decision_index"]-lot["first_positive"]["index"]


def summary(lots: list[dict]) -> dict:
    """同じ定義で玉全体・小量初回・資格後残玉・床飛越えを数える。

    引数: lots(list[dict])。返り値: dict。
    """
    value = base.summarize(lots)
    exits = [e for lot in lots for e in lot["exits"]]
    gap = [e for e in exits if e["reason"].startswith("protect_") and e["decision_gain"]>=0 and e["Gross"]<0]
    already_negative = [e for e in exits if e["reason"].startswith("protect_") and e["decision_gain"]<0]
    residual = [lot for lot in lots if lot["residual_qualification"] is not None]
    value.update(floor_gap_negative_pieces=len(gap), floor_gap_negative_net=sum(x["Gross"] for x in gap),
        zero_favorable_loss_net=sum(lot["Gross"] for lot in lots if lot["Best"]<=0 and lot["Gross"]<0),
        floor_decision_already_negative_pieces=len(already_negative), floor_decision_already_negative_net=sum(e["Gross"] for e in already_negative),
        unactivated_loss_lots=sum(x["activation"] is None and x["Gross"]<0 for x in lots),
        unactivated_loss_net=sum(x["Gross"] for x in lots if x["activation"] is None and x["Gross"]<0),
        activated_loss_lots=sum(x["activation"] is not None and x["Gross"]<0 for x in lots),
        activated_loss_net=sum(x["Gross"] for x in lots if x["activation"] is not None and x["Gross"]<0),
        qualified_residual_lots=len(residual), qualified_residual_net=sum(x["residual_realized"] for x in residual),
        residual_positive_then_loss_lots=sum(x["residual_best"]>0 and x["residual_realized"]<0 for x in residual),
        residual_positive_then_loss_net=sum(x["residual_realized"] for x in residual if x["residual_best"]>0 and x["residual_realized"]<0),
        source_decision_to_entry_seconds=base.distribution([x["At"]-x["source_decision_time"] for x in lots]),
        activation_measurement="04〜07の追加保護だけ。00の元P05/D07保護は起動未計測。残玉資格は全案同定義で事後再構築")
    return value


def subsets(lots: list[dict]) -> dict:
    """元通知の役割と数量で比較対象を固定する。

    引数: lots(list[dict])。返り値: dict。
    """
    return {"全玉":summary(lots),"初回":summary([x for x in lots if x["source_initial"]]),
            "小量初回":summary([x for x in lots if x["source_initial"] and x["source_initial_quantity"]<=20]),
            "Source追撃":summary([x for x in lots if not x["source_initial"]]),
            "黒字部分返済後残玉":summary([x for x in lots if x["residual_qualification"] is not None])}


def compare(base_lots: list[dict], new_lots: list[dict]) -> dict:
    """同じ元入口IDを対応し、延期・取消・失った勝ちを独立に分類する。

    引数: base_lots/new_lots(list[dict])。返り値: dict。
    """
    key = lambda x:(x["session"],x["source_id"])
    old,new = {key(x):x for x in base_lots},{key(x):x for x in new_lots}
    assert len(old)==len(base_lots) and len(new)==len(new_lots) and not new.keys()-old.keys()
    rows=[]
    for k,a in sorted(old.items()):
        b=new.get(k)
        if b and not b["method"].endswith("_07"):
            assert (a["At"],a["EntryIndex"],a["Entry"],a["Quantity"])==(b["At"],b["EntryIndex"],b["Entry"],b["Quantity"])
        rows.append(dict(session=k[0],source_id=k[1],owner=a["Owner"],parent=a["Parent"],side=a["Side"],role=a["role"],base_lot=a["ID"],candidate_lot=b["ID"] if b else None,
            base_net=a["Gross"],candidate_net=b["Gross"] if b else 0,delta=(b["Gross"] if b else 0)-a["Gross"],
            base_quantity=a["Quantity"],candidate_quantity=b["Quantity"] if b else 0,delayed=bool(b and b["delayed"]),
            base_entry_time=a["At"],candidate_entry_time=b["At"] if b else None,
            lost_win=a["Gross"]>0 and (b is None or b["Gross"]<a["Gross"]),avoided_loss=a["Gross"]<0 and (b is None or b["Gross"]>a["Gross"])))
    return dict(rows=rows,delta=sum(x["delta"] for x in rows),omitted=sum(x["candidate_lot"] is None for x in rows),
                lost_win_count=sum(x["lost_win"] for x in rows),lost_win_delta=sum(x["delta"] for x in rows if x["lost_win"]),
                avoided_loss_count=sum(x["avoided_loss"] for x in rows),avoided_loss_delta=sum(x["delta"] for x in rows if x["avoided_loss"]))


def build(final: dict, items: list[tuple[str,Path]]) -> dict:
    """許可済み第二巡と保存基準を合わせ、夜27場だけを再会計する。

    引数: final(dict)、items(list[tuple[str,Path]])。返り値: dict。
    """
    _, old_items = base.completed_inputs(BASE_STUDY/"再生全完了164.json")
    old_paths = {path.name:path for _,path in old_items}
    lots,rows,evidence,traces = [],[],[],[]
    for stage,path in items:
        new,old = base.read(path),base.read(old_paths[path.name])
        scene_difference={k:[old["scene"].get(k),v] for k,v in new["scene"].items() if old["scene"].get(k)!=v}
        assert set(scene_difference).issubset({"previously_used"})
        assert {k:v for k,v in new["scene"].items() if k!="previously_used"}=={k:v for k,v in old["scene"].items() if k!="previously_used"}
        assert new["sources"]==old["sources"]
        source = source_maps(new["sources"])
        cases = [c for c in old["cases"] if c["config"]["id"].endswith("_00")]+new["cases"]
        assert len(cases)==10 and len(new["cases"])==8
        states = [prepare_case(c,new["scene"]["session"],stage,source) for c in cases]
        trace_raw(states,base.raw_quotes(new["scene"]))
        for state in states:
            case=state["original_case"];ls=list(state["lots"].values());lots.extend(ls)
            rows.append(dict(session=new["scene"]["session"],stage=stage,id=case["config"]["id"],scope=case["config"]["scope"],groups=subsets(ls),risk=case["actual"]["Risk"],counts=case["counts"]))
            for trace in case.get("trigger_trace") or []:
                if "Action" in trace: traces.append(dict(trace,method=case["config"]["id"],session=new["scene"]["session"],raw=state["references"][trace["Index"]]))
        evidence.append(dict(path=str(path),sha256=base.sha(path),baseline_path=str(old_paths[path.name]),baseline_sha256=base.sha(old_paths[path.name]),source_all_equal=True,nontrading_metadata_difference=scene_difference))
        print("夜間診断完了 "+new["scene"]["session"],flush=True)
    methods={ident:dict(all=subsets([x for x in lots if x["method"]==ident]),stages={stage:subsets([x for x in lots if x["method"]==ident and x["stage"]==stage]) for stage in ("train_validation","confirmation")},
        short_quality={q:summary([x for x in lots if x["method"]==ident and x["entry_quality"]==q]) for q in sorted({x["entry_quality"] for x in lots if x["method"]==ident})}) for ident in sorted({x["method"] for x in lots}|{x["id"] for x in rows})}
    comparisons={}
    for group in ("P","U"):
        baseline=f"NK225_{group}164_00"
        for number in range(4,8):
            ident=f"NK225_{group}164_{number:02d}"
            v=compare([x for x in lots if x["method"]==baseline],[x for x in lots if x["method"]==ident])
            sessions=[]
            for session in sorted({x["session"] for x in rows}):
                a=next(x for x in rows if x["id"]==baseline and x["session"]==session);b=next(x for x in rows if x["id"]==ident and x["session"]==session)
                sessions.append(dict(session=session,stage=a["stage"],base_net=a["groups"]["全玉"]["net"],candidate_net=b["groups"]["全玉"]["net"],delta=b["groups"]["全玉"]["net"]-a["groups"]["全玉"]["net"],base_minimum=a["risk"]["Minimum"],candidate_minimum=b["risk"]["Minimum"],base_dd=a["risk"]["MaxDD"],candidate_dd=b["risk"]["MaxDD"]))
            v["sessions"]=sessions;comparisons[baseline+"→"+ident]=v
    delay={}
    for group in ("P","U"):
        ident=f"NK225_{group}164_07";ts=[x for x in traces if x["method"]==ident]
        delay[ident]=dict(counts=dict(Counter(x["Action"]+":"+x["Reason"] for x in ts)),deferred=[x for x in ts if x["Action"]=="初回延期"],cancelled=[x for x in ts if x["Action"]=="初回取消"],released=[x for x in ts if x["Reason"]=="delayed_initial"],skipped_additions=[x for x in ts if x["Action"]=="追加不採用"])
    examples=[]
    for key,v in comparisons.items():
        for meaning,items2 in (("悪化",sorted(v["rows"],key=lambda x:(x["delta"],x["session"],x["source_id"]))[:1]),("改善",sorted(v["rows"],key=lambda x:(-x["delta"],x["session"],x["source_id"]))[:1])):
            for item in items2:
                selected=[x for x in lots if x["session"]==item["session"] and x["source_id"]==item["source_id"] and x["method"] in key.split("→")]
                examples.append(dict(comparison=key,meaning=meaning,difference=item,lots=selected))
    return dict(completed=True,financial_replays=0,source_changed=False,selected=final["selected"],evidence=evidence,methods=methods,cases=rows,comparisons=comparisons,delays=delay,examples=examples,lots=lots,definitions={
        "scope":"27Nightの米国前/後を別IDで比較。第一巡00を保存会計として再利用。全54場確認後の追加開発。",
        "identity":"同じSourceIDの玉を対応。07延期・量減少・取消を別記。04〜06は入口時刻・価格・数量一致を要求。",
        "residual":"Actualの元部分返済が正益かつ生存Source親残量>0の時、Event順で実残玉へ事後資格。その後だけの最高順行と残玉返済額を集計。00の保護実装がこの資格を使うとは意味しない。",
        "time":"全時計はCurrentPriceTime代理。分内反応の実受信遅延は測れない。",
        "first_round":"第一巡01〜03は別入口/数量/出口全体の試行。第二巡04〜06は元Source入口量固定、07だけ既知失速時の待機。二つを同じ出口効果として混ぜない。"})


def write(report: dict, out: Path) -> None:
    """根拠JSONと最大3具体例の日本語説明を新規保存する。

    引数: report(dict)、out(Path)。返り値: None。
    """
    out.mkdir(parents=True,exist_ok=True)
    with (out/"夜間の具体診断164r2.json").open("x",encoding="utf-8") as stream:
        json.dump(report,stream,ensure_ascii=False,allow_nan=False,separators=(",",":"));stream.write("\n")
    lines=["# 第二巡の夜間診断","","元P05/D07の保存基準と、同じSource入口へ実玉保護を加えた新IDを比較した。全完了後の保存会計・原板診断であり、売買再生や選択変更は行っていない。","","|ID|玉収支|正益後赤字玉|未順行損失|追加保護起動|床判断後の次板赤字|","|---|---:|---:|---:|---:|---:|"]
    for ident,m in report["methods"].items():
        v=m["all"]["全玉"];lines.append(f"|{ident}|{v['net']:,.0f}|{v['positive_then_loss_lots']}|{v['zero_favorable_loss_net']:,.0f}|{v['activated_lots']}|{v['floor_gap_negative_net']:,.0f}|")
    lines += ["","00の元保護起動は今回の追加traceでは未計測。04〜07の追加保護が0であることと、元手法に保護がないことは同義ではない。小量は元初回通知20micro以下だけ、Source追撃は担当名と分離した。","","|対照|全場差|失った元勝ちの差|避けた元負けの差|不採用元玉数|","|---|---:|---:|---:|---:|"]
    for key,v in report["comparisons"].items():lines.append(f"|{key}|{v['delta']:,.0f}|{v['lost_win_delta']:,.0f}|{v['avoided_loss_delta']:,.0f}|{v['omitted']}|")
    lines += ["","黒字部分返済後の残玉は、その返済より後に観測した順行と返済額だけで集計した。部分返済前のピークを残玉の回収可能利益へ流用していない。","","|具体例|元入口|元玉収支|改修玉収支|差|","|---|---|---:|---:|---:|"]
    candidates=sorted(report["examples"],key=lambda x:(x["difference"]["delta"],x["comparison"]))
    chosen=candidates[:2]+sorted((x for x in report["examples"] if x["difference"]["delta"]>0),key=lambda x:-x["difference"]["delta"])[:1]
    for e in chosen:
        d=e["difference"];lines.append(f"|{e['comparison']} {d['session']} {d['source_id']}|{base.timestamp(d['base_entry_time'])}|{d['base_net']:,.0f}|{d['candidate_net']:,.0f}|{d['delta']:,.0f}|")
    lines += ["","各例の判断時刻、次板建値、返済判断と実約定、最初の利益、元通知ID、原板物理行はJSONに保存。07の元判断→実入口の時間には待機と次板待ちを含み、価格時計の同秒後続も原行順で区別する。","","第一巡01〜03は新しい反発/押し目入口と可変枚数を含み、未順行損と売買気配差が支配した。今回は04〜06で入口・量を元Sourceに固定して出口を比べ、07だけ失速時の待機を加えた。比較元を戻したこと自体と保護の効果を混同しない。",""]
    with (out/"夜間の具体診断164r2.md").open("x",encoding="utf-8") as stream:stream.write("\n".join(lines))


def main() -> None:
    """全完了許可の後に限り保存結果診断を開始する。

    引数: CLI(--completion,--out)。返り値: None。
    """
    parser=argparse.ArgumentParser();parser.add_argument("--completion",type=Path,default=STUDY/"再生全完了164r2.json");parser.add_argument("--out",type=Path,default=HERE/"results")
    args=parser.parse_args();final,items=completed_inputs(args.completion);write(build(final,items),args.out)


if __name__=="__main__":main()
