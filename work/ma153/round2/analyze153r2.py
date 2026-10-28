"""研究153第二巡の保存会計を初巡と同じ定義で独立検算する。"""

from collections import Counter, defaultdict
import json
from pathlib import Path
import sys


SECOND = Path(__file__).resolve().parent
FIRST = SECOND.parent
sys.path.insert(0, str(FIRST))

from analyze153 import (ROOT, account_case, fingerprint, finish_slopes, merge_groups,
                        read, summarize_method, equal, event_reference)


def describe(config: dict) -> str:
    """第二巡の設定を表向けの短い説明へ変換する。

    引数: config(dict)は固定した条件。
    返り値: strは主な入口、数量、出口。完全仕様は別資料に置く。
    """
    minutes = config["window_seconds"]/60
    stage = (int(config["id"][1:])-1) % 4
    details = ("初回は傾き比例枚数・返済後は冷却して再参加・利益の伸びを追尾",
               "冷却後に再参加・価格位置と1分傾きも確認・初回比例枚数",
               "冷却後に再参加・価格と1分傾き確認・保有中も比例枚数へ増減",
               "冷却後に再参加・価格と1分傾き確認・利益方向だけ追加・2枚差で増減")[stage]
    return f"{minutes:g}分MA・{details}／{config['exit']}出口"


def write_summary(report: dict) -> None:
    """完了場と既知途中を分け、保存基準との変化を記載する。

    引数: report(dict)は検算済み第二巡結果。
    返り値: None。初巡JSONや条件を変更しない。
    """
    lines = ["# 第二巡：再入場と数量調整の修正", "",
             "初巡を見た後の追加条件。初巡と同じ既知51場・二市場であり、未見検証ではない。利益損失は返済FIFO配賦別、方向親合算は別項目。手数料0。", "",
             "|商品|ID|全場収支|赤字場|利益/損失比|昼収支|夜収支|上位3黒字場除外|入口数|追加数|", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for method in report["methods"]:
        total = method["summary"]
        ratio = f"{total['pf']:.3f}" if total["pf"] is not None else "—"
        lines.append(f"|{method['symbol']}|{method['id']}|{total['net']:,.0f}|{total['losses']}/51|{ratio}|{method['day']['net']:,.0f}|{method['night']['net']:,.0f}|{total['ex3']:,.0f}|{total['entries']:,}|{total['additions']:,}|")
    lines += ["", "## 検算", "", f"完了{report['audit']['complete_cases']}条件場、途中{report['audit']['partial_cases']}条件場、{report['audit']['events']:,}約定、{report['audit']['marks']:,}保存時価地点を独立会計。",
              "当場方向は入力目録の最初Lastと資格済み最終Last代理で分類。保有率の分母はデイ420分・ナイト780分。米国前後は返済約定時計で分類し、含み変化込みの区間収支とは区別した。", ""]
    for symbol in ("NK225", "TOPIX"):
        candidates = [method for method in report["methods"] if method["symbol"] == symbol]
        best = max(candidates, key=lambda method: method["summary"]["net"])
        lines += [f"## {symbol}：今回累計の最大値 {best['id']} の赤字上位3場", ""]
        for row in best["worst_sessions"]:
            lines.append(f"- {row['session']}：{row['net']:,.0f}円、{row['direction']}場、初回{row['entries']}回・追加{row['additions']}回。")
            for parent in row["worst_parents"]:
                entry, exit_event = parent["entry"], parent["exit"]
                lines.append(f"  - 親{parent['id']}：{entry['decision_at'][11:19]}判断（原行{entry['decision_line']}）→{entry['fill_price']:g}で新規、傾き{entry['slope']:+.3f}bp/分。{exit_event['fill_at'][11:19]} {exit_event['fill_price']:g}で返済、{parent['net']:,.0f}円。最大順行{parent['peak_gain_points']:g}pt、理由：{parent['exit_reason']}。")
        lines.append("")
    (SECOND/"analysis153r2.md").write_text("\n".join(lines), encoding="utf-8")


def parent_lots(case: dict) -> dict:
    """原判断・約定をキーに、実際の初回玉と追加玉を親ごとに整理する。

    引数: case(dict)は完了場の保存結果。
    返り値: dictは初回原行キーから実約定親への対応。別の売買判断は作らない。
    """
    stored = {lot["ID"]: lot for lot in case.get("Lots") or []}
    parents, sequence = {}, 0
    for event in case.get("Events") or []:
        if event["Order"]["Action"] != "new":
            continue
        sequence += 1
        pid = event["Order"]["ParentID"]
        source = event_reference(event)
        key = (source["decision_index"], source["fill_index"], source["side"], source["fill_price"])
        lot = stored[sequence]
        assert lot["Quantity"] == 0
        if pid not in parents:
            parents[pid] = {"key": key, "id": pid, "first": {"source": source, "lot": lot}, "adds": {}, "net": 0.0}
        else:
            parents[pid]["adds"][key] = {"source": source, "lot": lot}
        parents[pid]["net"] += lot["Realized"]
    result = {parent["key"]: parent for parent in parents.values()}
    assert len(result) == len(parents)
    equal(sum(parent["net"] for parent in result.values()), case["Gross"], "比較親の確定総額")
    return result


def compare_additions(before: dict, after: dict) -> dict:
    """追加制約で残った取引と消えた勝ちの双方を記述する。

    引数: before/after(dict)は同一場の動的増減と追加制約付き保存結果。
    返り値: dictは対応親別の会計差と消えた利益玉参照。反実仮想の利益ではない。
    """
    left, right = parent_lots(before), parent_lots(after)
    common = left.keys() & right.keys()
    first_difference = sum(right[key]["first"]["lot"]["Realized"]-left[key]["first"]["lot"]["Realized"] for key in common)
    add_difference = sum(sum(x["lot"]["Realized"] for x in right[key]["adds"].values())-
                         sum(x["lot"]["Realized"] for x in left[key]["adds"].values()) for key in common)
    missing = -sum(left[key]["net"] for key in left.keys()-right.keys())
    added = sum(right[key]["net"] for key in right.keys()-left.keys())
    difference = after["Gross"]-before["Gross"]
    equal(first_difference+add_difference+missing+added, difference, "追加条件変更の全会計差")
    omitted, losers, quantity_changes = [], [], 0
    for key in common:
        old, new = left[key], right[key]
        for entry, value in old["adds"].items():
            if entry in new["adds"]:
                quantity_changes += value["lot"]["Initial"] != new["adds"][entry]["lot"]["Initial"]
                continue
            record = {"session": before["Session"], "symbol": before["Symbol"], "before_id": before["Config"]["id"],
                      "after_id": after["Config"]["id"], "parent_before": old["id"], "parent_after": new["id"],
                      "initial": old["first"]["source"], "addition": value["source"], "quantity": value["lot"]["Initial"],
                      "realized_in_before": value["lot"]["Realized"], "parent_before_net": old["net"], "parent_after_net": new["net"]}
            if value["lot"]["Realized"] > 0:
                omitted.append(record)
            elif value["lot"]["Realized"] < 0:
                losers.append(record)
    return {"session": before["Session"], "symbol": before["Symbol"], "before": before["Config"]["id"], "after": after["Config"]["id"],
            "before_net": before["Gross"], "after_net": after["Gross"], "net_difference": difference,
            "matched_parents": len(common), "missing_parents": len(left.keys()-right.keys()), "new_parents": len(right.keys()-left.keys()),
            "matched_first_lot_difference": first_difference, "matched_add_lot_difference": add_difference,
            "missing_parent_difference": missing, "new_parent_difference": added,
            "omitted_winning_additions": len(omitted), "omitted_winning_reference_net": sum(x["realized_in_before"] for x in omitted),
            "omitted_losing_additions": len(losers), "omitted_losing_reference_net": sum(x["realized_in_before"] for x in losers),
            "same_entry_quantity_changed": quantity_changes,
            "omitted_win_examples": sorted(omitted, key=lambda x: x["realized_in_before"], reverse=True)[:3],
            "omitted_loss_examples": sorted(losers, key=lambda x: x["realized_in_before"])[:3]}


def write_addition_comparison(rows: list[dict]) -> None:
    """利益方向への追加制限と枚数差制限の複合変更を両面で保存する。

    引数: rows(list[dict])は完了場での保存会計比較。
    返り値: None。消えた基準玉の損益を新条件の節約額とは呼ばない。
    """
    groups = defaultdict(list)
    for row in rows:
        groups[(row["symbol"], row["before"], row["after"])].append(row)
    methods = []
    lines = ["# 第二巡：追加制約で消えた勝ちと残った損失", "",
             "R03→R04、R07→R08は、利益方向への追加制限と2枚差以上の増減制限を同時に加えた比較。単独の因果効果に分けてはいない。初回新規の判断原行・約定原行・売買方向・価格が同一の親だけを対応させる。", "",
             "『消えた利益玉』は比較元では利益だった追加で、比較先に同じ原行の追加がない玉。対応先で時刻や価格が変わった追加がある場合も含み、この基準玉の利益合計を比較先の機会損失額とはみなさない。", "",
             "|比較|収支差|対応親の初回玉差|対応親の追加玉差|消えた親の寄与|新しい親の寄与|消えた利益追加/損失追加|", "|---|---:|---:|---:|---:|---:|---:|"]
    for (symbol, before, after), values in groups.items():
        keys = [key for key, value in values[0].items() if isinstance(value, (int, float))]
        summary = {key: sum(row[key] for row in values) for key in keys}
        examples = sorted((example for row in values for example in row["omitted_win_examples"]), key=lambda x: x["realized_in_before"], reverse=True)[:3]
        methods.append({"symbol": symbol, "before": before, "after": after, "summary": summary, "examples": examples, "rows": values})
        lines.append(f"|{symbol} {before}→{after}|{summary['net_difference']:,.0f}|{summary['matched_first_lot_difference']:,.0f}|{summary['matched_add_lot_difference']:,.0f}|{summary['missing_parent_difference']:,.0f}|{summary['new_parent_difference']:,.0f}|{summary['omitted_winning_additions']:,}/{summary['omitted_losing_additions']:,}|")
    for method in methods:
        lines += ["", f"## {method['symbol']} {method['before']}→{method['after']}：消えた利益追加の上位例", ""]
        for value in method["examples"]:
            source = value["addition"]
            lines.append(f"- {value['session']} {source['decision_at'][11:19]}判断、原行{source['decision_line']}。{source['fill_price']:g}で{value['quantity']}枚追加した基準玉は{value['realized_in_before']:,.0f}円。比較先に同じ原行の追加なし。親全体は{value['parent_before_net']:,.0f}円→{value['parent_after_net']:,.0f}円。")
    (SECOND/"addition_comparison153r2.json").write_text(json.dumps({"methods": methods}, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    (SECOND/"addition_comparison153r2.md").write_text("\n".join(lines)+"\n", encoding="utf-8")


def main() -> None:
    """第二巡の全商品場が揃ってから同じ会計基準で集計する。

    引数: なし。固定条件・入力目録・第二巡保存金融結果のみを読む。
    返り値: None。不足・不整合では停止し、売買再生は行わない。
    """
    manifest_path = FIRST/"data/入力目録153.json"
    config_path = SECOND/"configs153r2.json"
    scenes = {scene["session"]: scene for scene in read(manifest_path)["sessions"]}
    configs = {config["id"]: config for config in read(config_path)}
    assert len(scenes) == 52 and len(configs) == 8
    paths = [SECOND/"results_go"/f"{session}_{symbol}.json" for session in scenes for symbol in ("NK225", "TOPIX")]
    assert all(path.is_file() for path in paths), "第二巡104商品場の完了通知後に集計してください"
    methods, partial, sources, addition_comparisons = {}, [], [], []
    slopes = defaultdict(dict)
    audit = Counter(complete_cases=0, partial_cases=0, events=0, lots=0, marks=0, parents=0)
    for path in paths:
        saved = read(path)
        scene, symbol = scenes[saved["scene"]["session"]], saved["symbol"]
        for key in ("session", "kind", "start", "end", "force_close", "us_open", "cutoff", "partial", "books"):
            assert scene[key] == saved["scene"][key]
        cases = {case["Config"]["id"]: case for case in saved["cases"]}
        assert cases.keys() == configs.keys()
        for identity, case in cases.items():
            assert case["Config"] == configs[identity] and case["Symbol"] == symbol
            row, internal = account_case(scene, case, path.relative_to(ROOT).as_posix())
            saved_orders = {event["Order"]["ID"]: event["Order"] for event in case.get("Events") or []}
            for parent in row["worst_parents"]:
                for event in parent["events"]:
                    original = saved_orders[event["order_id"]]
                    feature = original.get("ShortFeature")
                    if feature is not None:
                        event["short_feature"] = feature
                    event["last_new_price"] = original.get("LastNewPrice")
            row["rejection_rows"] = case.get("Rejections", {})
            audit["partial_cases" if scene["partial"] else "complete_cases"] += 1
            for key in ("events", "lots"):
                audit[key] += internal[key]
            audit["parents"] += internal["parent_count"]
            audit["marks"] += internal["marks"]["checked_marks"]
            key = (symbol, identity)
            if scene["partial"]:
                partial.append({"id": identity, "config": case["Config"], "description": describe(case["Config"]), **row})
            else:
                if key not in methods:
                    methods[key] = {"symbol": symbol, "id": identity, "config": case["Config"], "description": describe(case["Config"]), "rows": []}
                methods[key]["rows"].append(row)
                merge_groups(slopes[key], internal["slope_groups"])
        if not scene["partial"]:
            addition_comparisons.extend([compare_additions(cases["R03"], cases["R04"]), compare_additions(cases["R07"], cases["R08"])])
        sources.append(fingerprint(path))
        print(f"第二巡検算済み {scene['session']} {symbol}：8条件", flush=True)
    assert audit["complete_cases"] == 816 and audit["partial_cases"] == 16
    ordered = []
    initial = {(method["symbol"], method["id"]): method for method in read(FIRST/"report153.json")["methods"]}
    for symbol in ("NK225", "TOPIX"):
        for identity in configs:
            method = methods[(symbol, identity)]
            summarize_method(method)
            method["slope_groups"] = finish_slopes(slopes[(symbol, identity)], 100 if symbol == "NK225" else 1000)
            baseline_id = "M09" if method["config"]["window_seconds"] == 180 else "M19"
            base = initial[(symbol, baseline_id)]
            method["initial_comparison"] = {"id": baseline_id, "net_difference": method["summary"]["net"]-base["summary"]["net"],
                                            "red_session_difference": method["summary"]["losses"]-base["summary"]["losses"],
                                            "entry_difference": method["summary"]["entries"]-base["summary"]["entries"]}
            ordered.append(method)
    report = {"research": "00153_第二巡", "methods": ordered, "partial": partial, "audit": dict(audit),
              "definition": read(FIRST/"analysis_spec153.json"),
              "sources": [fingerprint(manifest_path), fingerprint(config_path), fingerprint(FIRST/"report153.json"),
                          fingerprint(FIRST/"analyze153.py"), fingerprint(SECOND/"spec153r2.md"),
                          *[fingerprint(path) for path in sorted((SECOND/"engine_go").glob("*.go"))], *sources]}
    target = SECOND/"report153r2.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    write_summary(report)
    write_addition_comparison(addition_comparisons)
    (SECOND/"独立会計照合153r2.json").write_text(json.dumps({"state": "全件一致", "audit": dict(audit), "report": fingerprint(target),
                                                       "script": fingerprint(Path(__file__))}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"state": "完了", **dict(audit), "methods": len(ordered), "partial": len(partial)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
