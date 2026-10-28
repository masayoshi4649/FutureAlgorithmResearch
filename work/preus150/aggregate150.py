"""前半の積極性と損益を、保存約定だけから独立会計する。"""

import importlib.util
import json
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT / "work/preus149"
spec = importlib.util.spec_from_file_location("既存の独立会計149", OLD / "aggregate149.py")
accounting = importlib.util.module_from_spec(spec)
spec.loader.exec_module(accounting)


def semantic_events(case, start):
    """後半の判断と約定を、運転ID以外の同一性で比較する。

    引数: case(dict)は保存結果、start(float)は米国開始秒。
    返り値: list[tuple]は時刻・方向・数量・価格・原行番号。
    """
    return [(e["signal"]["owner"], e["signal"]["action"], e["signal"]["side"],
             e["signal"]["time"], e["fill"]["Time"], e["fill"]["Quantity"], e["fill"]["Price"],
             e["decision_index"], e["fill_index"])
            for e in case["events"] or [] if e["fill"]["Time"] >= start]


def activity(scene, case):
    """米国15分前までの保有時間・平均枚数・最初の新規を測る。

    引数: scene(dict)は時刻、case(dict)は保存約定。
    返り値: dictは保有率等。監視だけの時間を保有に含めない。
    """
    start = scene["start"]
    end = min(scene["us_open"] - 900, scene["cutoff"] if scene["partial"] else scene["end"])
    held = 0
    elapsed_held = 0.0
    quantity_seconds = 0.0
    previous = start
    first = None
    for e in case["events"] or []:
        t = e["fill"]["Time"]
        if t >= end:
            break
        assert t >= previous
        duration = t - previous
        elapsed_held += duration if held else 0
        quantity_seconds += duration * held
        if e["signal"]["action"] == "new":
            held += e["fill"]["Quantity"]
            if first is None:
                first = t
        else:
            held -= e["fill"]["Quantity"]
        assert held >= 0
        previous = t
    elapsed_held += end - previous if held else 0
    quantity_seconds += (end - previous) * held
    return {"seconds": elapsed_held, "denominator_seconds": end - start,
            "holding_ratio": elapsed_held / (end - start), "average_quantity": quantity_seconds / (end - start),
            "first_entry_delay_minutes": (first - start) / 60 if first is not None else None}


def entry_parents(scene, case, row):
    """親の初回新規をキーにし、追加・消失・出口変更を区別する。

    引数: scene(dict)、case(dict)、row(dict)は保存時刻・約定・独立会計。
    返り値: dictは前半親の初回入口と最終損益。似た入口の推測対応をしない。
    """
    parents = {p["id"]: p for p in row["parent_details"]}
    result = {}
    done = set()
    for e in case["events"] or []:
        s, f = e["signal"], e["fill"]
        if s["action"] != "new" or f["Time"] >= scene["us_open"]:
            continue
        parent = f"{e['phase']}/{s['owner']}/{s['campaign']}"
        if parent in done:
            continue
        done.add(parent)
        key = json.dumps([s["owner"], s["side"], f["Time"], f["Price"]])
        assert key not in result
        result[key] = parents[parent]["net"]
    return result


def summarize(method):
    """全夜・前後・方向別損益と前半の活動をまとめる。

    引数: method(dict)は25夜の条件結果。返り値: None。辞書へ集計を追加する。
    """
    rows = method["rows"]
    method["summary"] = accounting.totals(rows)
    for segment in ("pre", "post"):
        method[segment] = accounting.totals([r[segment] for r in rows])
    method["by_direction"] = {d: accounting.totals([r for r in rows if r["direction"] == d]) for d in sorted({r["direction"] for r in rows})}
    delays = [r["first_post_delay_minutes"] for r in rows if r["first_post_delay_minutes"] is not None]
    method["post_delay"] = {"n": len(delays), "minimum": min(delays) if delays else None, "median": float(np.median(delays)) if delays else None}
    activities = [r["pre_activity"] for r in rows]
    first = [a["first_entry_delay_minutes"] for a in activities if a["first_entry_delay_minutes"] is not None]
    method["pre_activity"] = {"mean_holding_ratio": float(np.mean([a["holding_ratio"] for a in activities])),
                              "mean_quantity": float(np.mean([a["average_quantity"] for a in activities])),
                              "participating_nights": len(first), "median_first_entry_minutes": float(np.median(first)) if first else None}


def main():
    """初巡17・第二巡6条件と3保存対照の後半不変・全会計を検査する。

    引数: なし。返り値: None。金融判断の再実行は行わない。
    """
    old_report = json.loads((OLD / "report149.json").read_text(encoding="utf-8"))
    labels = {r["session"]: r["direction"] for r in old_report["methods"][0]["rows"]}
    configs = json.loads((HERE / "configs150.json").read_text(encoding="utf-8-sig"))
    additional_path = HERE / "configs_round2_150.json"
    if additional_path.exists():
        configs += json.loads(additional_path.read_text(encoding="utf-8-sig"))
    identifiers = ["C00", "S04", "S02"] + [c["id"] for c in configs]
    old_methods = {m["id"]: m for m in old_report["methods"]}
    byid = {i: {"id": i, "description": old_methods[i]["description"], "config": old_methods[i]["config"], "rows": [], "saved_control": True} for i in identifiers[:3]}
    byid.update({c["id"]: {"id": c["id"], "description": c["description"], "config": c, "rows": [], "saved_control": False} for c in configs})
    manifest = json.loads((OLD / "data/原資料一覧149.json").read_text(encoding="utf-8"))
    partial = []
    changes = []
    post_same = 0
    for scene in manifest["sessions"]:
        session = scene["session"]
        first = json.loads((OLD / "results_go" / f"{session}.json").read_text(encoding="utf-8"))
        second = json.loads((OLD / "results_round2" / f"{session}.json").read_text(encoding="utf-8"))
        new = json.loads((HERE / "results_go" / f"{session}.json").read_text(encoding="utf-8"))
        assert len(new["cases"]) == 17
        if additional_path.exists():
            extra = json.loads((HERE / "results_round2" / f"{session}.json").read_text(encoding="utf-8"))
            assert len(extra["cases"]) == 6
            new["cases"] += extra["cases"]
        cases = {c["config"]["id"]: c for c in first["cases"] + second["cases"] if c["config"]["id"] in identifiers[:3]}
        cases.update({c["config"]["id"]: c for c in new["cases"]})
        rows = {}
        parent_maps = {}
        for identifier in identifiers:
            case = cases[identifier]
            row = accounting.account(scene, case)
            row["pre_activity"] = activity(scene, case)
            row["first_post_delay_minutes"] = (row["first_post_entry"] - scene["us_open"]) / 60 if row["first_post_entry"] is not None else None
            row["diagnostics"] = case.get("diagnostics", {})
            if scene["partial"]:
                partial.append({"id": identifier, **row})
            else:
                row["direction"] = labels[session]
                byid[identifier]["rows"].append(row)
                if identifier.startswith(("A", "B")):
                    assert semantic_events(case, scene["us_open"]) == semantic_events(cases["S04"], scene["us_open"]), (session, identifier, "後半が基準と不一致")
                    post_same += 1
            rows[identifier] = row
            parent_maps[identifier] = entry_parents(scene, case, row)
        # ----------------------------------------
        if not scene["partial"]:
            base = parent_maps["A00"]
            for identifier in identifiers[4:]:
                candidate = parent_maps[identifier]
                added = candidate.keys() - base.keys()
                removed = base.keys() - candidate.keys()
                common = candidate.keys() & base.keys()
                item = {"id": identifier, "session": session, "added_parents": len(added), "added_net": sum(candidate[k] for k in added),
                        "removed_parents": len(removed), "removed_net": sum(base[k] for k in removed),
                        "same_entry_delta": sum(candidate[k] - base[k] for k in common),
                        "pre_delta": rows[identifier]["pre"]["net"] - rows["A00"]["pre"]["net"]}
                assert item["added_net"] - item["removed_net"] + item["same_entry_delta"] == item["pre_delta"]
                changes.append(item)
    expected = [s["session"] for s in manifest["sessions"] if not s["partial"]]
    for method in byid.values():
        assert [r["session"] for r in method["rows"]] == expected
        summarize(method)
    report = {"methods": list(byid.values()), "partial": partial, "entry_changes": changes,
              "definition": "利益損失は親取引の全返済収支。前後は親の初回新規時刻。前半保有率は17時〜US15分前、途中場だけ保存打切り時点まで。損益に手数料0・気配差あり。保存対照3条件は再生せず再会計。",
              "validation": {"expected_complete_nights": len(expected), "all_orders_independently_accounted": True, "cap_and_ids_checked": True, "fee": 0, "point_value": 100, "post_exact_to_S04_method_nights": post_same}}
    (HERE / "report150.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({m["id"]: {"pre": m["pre"]["net"], "net": m["summary"]["net"], "red": m["summary"]["losses"],
                                "pre_entries": m["pre"]["entries"], "pre_nights": m["pre_activity"]["participating_nights"]} for m in byid.values()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
