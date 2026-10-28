"""初巡の損失について保存約定から気配差と再入場を追加診断する。"""

from collections import defaultdict
import json
from pathlib import Path
from statistics import mean, median

from analyze153 import HERE, ROOT, read, equal, clock, event_reference


def describe_case(case: dict) -> dict:
    """約定の中値移動・気配差負担・同方向再入場を恒等分解する。

    引数: case(dict)は保存済み一場の金融結果。
    返り値: dictは確定記述。価格や売買条件を変更した再生は行わない。
    """
    multiplier = case["PointValue"]
    lots, parents = {}, {}
    directional = spread = gross = 0.0
    for event in case["Events"] or []:
        order = event["Order"]
        if order["Action"] == "new":
            lid = len(lots)+1
            lots[lid] = {"side": order["Side"], "mid": (event["FillBid"]+event["FillAsk"])/2,
                         "spread": event["FillAsk"]-event["FillBid"], "price": event["Price"]}
            if order["ParentID"] not in parents:
                parents[order["ParentID"]] = {"entry": event_reference(event), "exit": None, "gross": 0.0, "mid_move": 0.0, "spread": 0.0}
        else:
            parent = parents[order["ParentID"]]
            for allocation in event["Closed"]:
                lot = lots[allocation["LotID"]]
                quantity = allocation["Quantity"]
                mid = lot["side"]*((event["FillBid"]+event["FillAsk"])/2-lot["mid"])*quantity*multiplier
                cost = (lot["spread"]+event["FillAsk"]-event["FillBid"])/2*quantity*multiplier
                equal(mid-cost, allocation["Gross"], "中値移動と両気配差の恒等式")
                directional += mid; spread += cost; gross += allocation["Gross"]
                parent["mid_move"] += mid; parent["spread"] += cost; parent["gross"] += allocation["Gross"]
            parent["exit"] = event_reference(event)
    equal(gross, case["Gross"], "気配差分解の全確定")
    source_parents = {parent["ID"]: parent for parent in case.get("Parents") or []}
    completed = [parent for identity, parent in parents.items() if identity in source_parents]
    same, same_after_loss, examples, loss_no_favorable, duration = [], [], [], [], []
    previous = None
    for identity, parent in parents.items():
        if identity not in source_parents:
            continue
        original = source_parents[identity]
        parent.update(id=identity, side=original["Side"], peak_gain=original["PeakGain"], worst_gain=original["WorstGain"],
                      reason=original["ExitReason"], slope=original["EntrySlope"], session=case["Session"])
        duration.append(parent["exit"]["fill_time"]-parent["entry"]["fill_time"])
        if parent["gross"] < 0 and parent["peak_gain"] <= 0:
            loss_no_favorable.append(parent["gross"])
        if previous is not None:
            gap = parent["entry"]["decision_time"]-previous["exit"]["fill_time"]
            if parent["side"] == previous["side"] and 0 <= gap <= 60:
                same.append(parent["gross"])
                if previous["gross"] < 0:
                    same_after_loss.append(parent["gross"])
                    if parent["gross"] < 0:
                        examples.append({"previous": previous, "next": parent, "gap_seconds": gap})
        previous = parent
    return {"session": case["Session"], "symbol": case["Symbol"], "id": case["Config"]["id"], "net": gross,
            "mid_move": directional, "spread": spread, "parents": len(completed),
            "same_reentry_count": len(same), "same_reentry_net": sum(same),
            "after_loss_reentry_count": len(same_after_loss), "after_loss_reentry_net": sum(same_after_loss),
            "after_loss_reentry_loss_count": sum(value < 0 for value in same_after_loss),
            "loss_without_favorable_count": len(loss_no_favorable), "loss_without_favorable_net": sum(loss_no_favorable),
            "hold_seconds": duration, "examples": sorted(examples, key=lambda item: item["previous"]["gross"]+item["next"]["gross"])[:2]}


def main() -> None:
    """完了場だけの事後原因診断を保存する。

    引数: なし。
    返り値: None。途中場、他条件の再計算、金融判断は含めない。
    """
    groups = defaultdict(list)
    for path in sorted((HERE/"results_go").glob("*.json")):
        saved = read(path)
        if saved["scene"]["partial"]:
            continue
        for case in saved["cases"]:
            if case["Config"]["id"] in ("F01", "M09", "M19"):
                row = describe_case(case)
                groups[(case["Symbol"], case["Config"]["id"])].append(row)
    result = {"definition": "初巡結果後の追加診断。実約定収支=実約定中値間の方向損益−入口出口の半気配差。中値で売買できる仮定の新戦略ではない。再入場は直前親返済から60秒以内かつ同方向の次親で、原板途中に傾き反転が無かったとは断定しない。", "methods": []}
    lines = ["# 初巡損失の追加診断", "", result["definition"], "", "|商品・ID|確定収支|中値間の方向損益|入口出口の気配差負担|平均/中央保有秒|直前赤字後60秒以内の同方向再入場：件数/収支|", "|---|---:|---:|---:|---:|---:|"]
    keys = ("net", "mid_move", "spread", "parents", "same_reentry_count", "same_reentry_net", "after_loss_reentry_count", "after_loss_reentry_net", "after_loss_reentry_loss_count", "loss_without_favorable_count", "loss_without_favorable_net")
    for (symbol, identity), rows in groups.items():
        summary = {key: sum(row[key] for row in rows) for key in keys}
        duration = [value for row in rows for value in row["hold_seconds"]]
        summary.update(average_hold=mean(duration), median_hold=median(duration))
        examples = sorted((example for row in rows for example in row["examples"]), key=lambda item: item["previous"]["gross"]+item["next"]["gross"])[:3]
        result["methods"].append({"symbol": symbol, "id": identity, "summary": summary, "examples": examples, "rows": rows})
        lines.append(f"|{symbol} {identity}|{summary['net']:,.0f}|{summary['mid_move']:,.0f}|{summary['spread']:,.0f}|{summary['average_hold']:.1f}/{summary['median_hold']:.1f}|{summary['after_loss_reentry_count']:,} / {summary['after_loss_reentry_net']:,.0f}|")
    lines += ["", "## 同方向へ短時間で再入場し、再び損失となった具体例", ""]
    for method in result["methods"]:
        if method["id"] != "M09":
            continue
        lines += [f"### {method['symbol']} M09", ""]
        for item in method["examples"]:
            a, b = item["previous"], item["next"]
            side = "買い" if b["side"] > 0 else "売り"
            lines.append(f"- {a['session']}：{a['exit']['fill_at'][11:19]}に{side}親{a['id']}を{a['gross']:,.0f}円で返済（{a['reason']}）。{item['gap_seconds']:g}秒後の{b['entry']['decision_at'][11:19]}、傾き{b['entry']['slope']:+.3f}bp/分で再び{side}、{b['entry']['fill_price']:g}で新規。{b['exit']['fill_at'][11:19]}に{b['exit']['fill_price']:g}で返済し{b['gross']:,.0f}円（{b['reason']}）。判断原行{b['entry']['decision_line']}、約定原行{b['entry']['fill_line']}。")
        lines.append("")
    lines += ["これらの再入場を無くした収支とは解釈しない。実際に入口を変えると、その後の保持・出口・再入場も変わるため、別の事前登録された再生が必要。", ""]
    (HERE/"loss_decomposition153.json").write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    (HERE/"loss_decomposition153.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps([{key: value for key, value in method.items() if key in ("symbol", "id", "summary")} for method in result["methods"]], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
