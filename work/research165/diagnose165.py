"""登録後に完了した会計を比較し、改善額と失った利益の具体的な親を残す。"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

import control165 as control
from control165 import HERE, BASELINE, read, save, record, summary, stage_results
from control_empty165 import row_from_case

JST = timezone(timedelta(hours=9))


def clock(value: float) -> str:
    """価格時計を日本時間へ表示変換する。

    引数: value(float)はUnix秒。返り値: str。受信時計には読み替えない。
    """
    return datetime.fromtimestamp(value, JST).isoformat()


def parent_rows(case: dict) -> list[dict]:
    """所有玉別の会計を親別へ集計し、売買と正益後赤字を追跡する。

    引数: case(dict)。返り値: list[dict]。
    """
    groups = defaultdict(list)
    events = defaultdict(list)
    for lot in case["actual"]["Lots"].values():
        groups[lot["Parent"]].append(lot)
    for event in case["actual"]["Events"] or []:
        order = event["Order"]
        events[order["Parent"]].append(dict(time=clock(event["FillTime"]),
            decision_time=clock(order["DecisionTime"]), decision_index=order["DecisionIndex"],
            fill_index=event["FillIndex"], side=order["Side"], quantity=order["Quantity"],
            kind=order["Kind"], price=event["Price"], gross=event["Gross"], reason=order["Reason"],
            hold_id=event["HoldID"], pieces=event["Pieces"]))
    return [dict(parent=key, net=sum(l["Gross"] for l in lots),
        positive_then_negative=sum(l["Best"] > 0 and l["Gross"] < 0 for l in lots),
        never_positive_losses=sum(l["Best"] <= 0 and l["Gross"] < 0 for l in lots),
        lots=lots, events=events[key]) for key,lots in sorted(groups.items())]


def lot_diagnostics(cases: list[dict]) -> dict:
    """同じ玉の実損益と過去の返済側最大順行幅を区別して集計する。

    引数: cases(list[dict])。返り値: dict。分子は所有玉、部分返済回数ではない。
    """
    lots = [l for c in cases for l in c["actual"]["Lots"].values()]
    groups = {
        "正益後赤字": [l for l in lots if l["Best"] > 0 and l["Gross"] < 0],
        "一度も正益なしで赤字": [l for l in lots if l["Best"] <= 0 and l["Gross"] < 0],
        "追加玉": [l for l in lots if l["Kind"] == "source_add"],
        "買い玉": [l for l in lots if l["Side"] > 0],
        "売り玉": [l for l in lots if l["Side"] < 0],
    }
    return dict(total_lots=len(lots), groups={k:dict(lots=len(v),
        quantity=sum(l["Quantity"] for l in v), net=sum(l["Gross"] for l in v)) for k,v in groups.items()},
        actions=dict(Counter(t["Action"]+":"+t["Reason"] for c in cases for t in (c.get("trigger_trace") or [])
            if "Action" in t)))


def main() -> None:
    """全段階の固定・完了を確認し、会計比較だけを新規保存する。

    引数: なし。返り値: None。新金融再生は行わない。
    """
    assert read(HERE/"再生全完了165.json")["completed"]
    control.row_from_case = row_from_case
    fixed = read(HERE/"results/selection_frozen165.json")
    scenes, methods = {}, defaultdict(dict)
    for item in read(BASELINE)["cases"]:
        name = item["scene"]["session"]
        scenes[name] = item["scene"]
        methods["NK225_U164_00"][name] = item["case"]
    sources = [record(BASELINE)]
    for stage in ("train_validation", "confirmation"):
        proof, results = stage_results(stage)
        sources.extend(proof["results"])
        for result in results:
            for case in result["cases"]:
                methods[case["config"]["id"]][result["scene"]["session"]] = case
    base = methods["NK225_U164_00"]
    summaries, deltas, parent_changes = [], [], []
    for name,cases in sorted(methods.items()):
        rows = [row_from_case(scenes[s],c) for s,c in sorted(cases.items())]
        summaries.append(dict(id=name, all=summary(rows),
            first20=summary([r for r in rows if r["split"] in ("train","validation")]),
            last7=summary([r for r in rows if r["split"] not in ("train","validation")]),
            lots=lot_diagnostics(list(cases.values()))))
        if name == "NK225_U164_00":
            continue
        for s,c in sorted(cases.items()):
            row = row_from_case(scenes[s],c)
            previous = row_from_case(scenes[s],base[s])
            deltas.append(dict(id=name,session=s,net=row["net"],base_net=previous["net"],
                delta=row["net"]-previous["net"],minimum_equity=row["minimum_equity"],
                base_minimum_equity=previous["minimum_equity"]))
            if name in fixed["shortlist"] or name in ("NK225_U165_05","NK225_U165_06","NK225_U165_08"):
                old = {p["parent"]:p for p in parent_rows(base[s])}
                new = {p["parent"]:p for p in parent_rows(c)}
                for key in sorted(set(old)|set(new)):
                    a,b = old.get(key),new.get(key)
                    difference = (b["net"] if b else 0)-(a["net"] if a else 0)
                    if difference:
                        parent_changes.append(dict(id=name,session=s,parent=key,delta=difference,
                            before=a,after=b,triggers=[t for t in (c.get("trigger_trace") or []) if t.get("Parent")==key]))
    out = dict(new_financial_replays=0,selected=fixed["selected"],shortlist=fixed["shortlist"],
        selection_unchanged=True,summaries=summaries,session_deltas=deltas,parent_changes=parent_changes,sources=sources)
    save(HERE/"損失原因と改修差165.json",out)
    for m in summaries:
        a,b=m["all"],m["last7"]
        print(m["id"],"全",a["net"],"赤",a["negative_sessions"],"平均赤字",round(a["mean_loss"]),
            "無取引",a["no_entries"],"後7",b["net"],"赤",b["negative_sessions"],flush=True)


if __name__ == "__main__":
    main()
