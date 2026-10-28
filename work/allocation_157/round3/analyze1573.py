"""00157第三巡の金融実行完了後、保存約定だけから報告用会計を生成する。"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger_analysis157 import equal, reconcile
from report157_common import attach_cumulative, quantity_distribution, summarize


BASE = Path(__file__).resolve().parent
FIRST = BASE.parent
SECOND = FIRST / "round2"
SECOND_SHA = "24b17a9f41290400a2d4bf08d3f3db20054f5aa5347cb59367523f562bb93597"
OLD = FIRST.parent / "s01_156"
FIRST_SHA = "2eaed2a7759a9763abbc69c1c331f6d7c86c708c7fe4b57d6214d61a7b837b26"
JST = timezone(timedelta(hours=9))


def read(path: Path) -> dict | list:
    """UTF-8の登録内容・保存結果を読む。

    引数: path(Path)。返り値: dict又はlist。既存原資料は書き換えない。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, value: object) -> None:
    """非有限値を拒否して集計資料をUTF-8で保存する。

    引数: path(Path)、value(JSON互換値)。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def mark_view(mark: dict, start: float) -> dict:
    """エンジンの極値断面を公開用の共通キーへ変換する。

    引数: mark(dict)、start(float)は当場開始。返り値: dict。
    """
    at = mark["Time"] or start
    return {"time": at, "at": datetime.fromtimestamp(at, JST).isoformat(),
            "index": mark["Index"] if mark["Time"] else -1,
            "bid": mark["Bid"], "ask": mark["Ask"], "realized": mark["Realized"],
            "unrealized": mark["Unrealized"], "equity": mark["Equity"],
            "long_quantity": mark["Long"], "short_quantity": mark["Short"],
            "lots": mark.get("Lots") or {}}


def verify_exact(case: dict, source: dict, row: dict, old_row: dict) -> dict:
    """C00を旧S01の数量10倍・倍率1/10の同額対照として照合する。

    引数: case/source(dict)は157/156、row/old_row(dict)は各会計行。
    返り値: dictは全約定・親会計・極値一致の記録。
    """
    current, previous = case["actual"].get("Events") or [], source.get("events") or []
    assert len(current) == len(previous)
    ids = {}
    for new, old in zip(current, previous):
        order, signal, fill = new["Order"], old["signal"], old["fill"]
        assert order["Side"] == signal["side"]
        assert order["Quantity"] == fill["Quantity"] * 10
        assert order["DecisionIndex"] == old["decision_index"]
        assert new["FillIndex"] == old["fill_index"]
        equal(new["FillTime"], fill["Time"], "C00約定時刻")
        equal(new["Price"], fill["Price"], "C00価格")
        equal(new["Gross"], old["gross"], "C00実現")
        if signal["action"] == "new":
            assert not order.get("Targets")
            ids[fill["HoldID"]] = new["HoldID"]
        else:
            expected = sorted((ids[t["id"]], t["quantity"] * 10) for t in fill["Closed"])
            actual = sorted((t["ID"], t["Quantity"]) for t in order["Targets"])
            assert expected == actual
    for key in ("profit", "loss", "net", "unrealized", "equity"):
        equal(row[key], old_row.get(key, old_row["net"] if key == "equity" else 0), f"C00会計/{key}")
    for key in ("min_equity", "max_drawdown", "min_realized"):
        equal(row["intraday_risk"][key], old_row["intraday_risk"][key], f"C00場内/{key}")
    return {"session": row["session"], "events": len(current), "same_value": True}


def make_row(case: dict, label: dict) -> tuple[dict, dict]:
    """実/CANONICAL台帳を別々に再会計して、一場の報告行を構築する。

    引数: case(dict)は保存結果、label(dict)は旧資料の事後場方向。
    返り値: (row, details)。双方を合算せず別会計で保持する。
    """
    scene, config, ledger = case["scene"], case["config"], case["actual"]
    finished = {key: parent["Finished"] for key, parent in case["parents"].items()}
    actual = reconcile(ledger, scene["start"], ledger["LastTime"], finished)
    canonical = reconcile(case["canonical"], scene["start"], case["canonical"]["LastTime"], finished)
    risk = ledger["Risk"]
    denominator = (scene["cutoff"] if scene.get("partial") else scene["end"]) - scene["start"]
    quantities = dict(actual["quantities"])
    quantities.update({"eligible_seconds": denominator,
                       "observed_seconds": ledger["LastTime"] - scene["start"],
                       "average_gross": quantities["gross_seconds"] / denominator,
                       "average_net_abs": quantities["net_abs_seconds"] / denominator,
                       "held_rate": quantities["held_seconds"] / denominator})
    adverse = []
    for book_name, account in (("actual", actual), ("canonical", canonical)):
        for lot in account["lots"]:
            if lot["kind"] != "adverse" and "adverse" not in lot["canonical_kinds"]:
                continue
            comp = lot["average_comparison"]
            value = comp["average_improvement"]
            category = "比較元なし" if value is None else "有利" if value > 1e-7 else "不利" if value < -1e-7 else "同値"
            adverse.append({"ledger": book_name, "category": category, "id": lot["id"],
                            "attribution": "役割単独" if lot["kind"] == "adverse" else "関連する純量投影・役割へ配賦しない",
                            "canonical_kinds": lot["canonical_kinds"],
                            "parent": lot["parent"], "quantity": lot["quantity"], "time": lot["time"],
                            "index": lot["index"], "side": lot["side"], "price": lot["price"],
                            "realized": lot["gross"], "unrealized": lot["unrealized"], **comp})
    row = {"id": config["id"], "session": scene["session"], "partial": scene.get("partial", False),
           "direction": label["direction"], "kind": scene["kind"],
           **{key: actual[key] for key in ("profit", "loss", "net", "open_parent_realized", "unrealized",
                                           "equity", "entries", "remaining_qty", "long_qty", "short_qty")},
           "parents": len(actual["parents"]),
           "completed_parents": sum(p["completed"] for p in actual["parents"]),
           "entry_quantity": sum(lot["quantity"] for lot in actual["lots"]),
           "entry_types": actual["entry_types"], "canonical_entry_types": canonical["entry_types"],
           "initial_quantities": quantity_distribution([p["initial_quantity"] for p in actual["parents"]]),
           "canonical_initial_quantities": quantity_distribution([p["initial_quantity"] for p in canonical["parents"]]),
           "quantities": quantities, "counts": case["counts"], "stopped": case["stopped"],
           "intraday_risk": {"min_equity": risk["Minimum"], "max_drawdown": risk["MaxDD"],
                              "min_realized": actual["min_realized"]["value"],
                              "min_realized_at": actual["min_realized"],
                              "min_unrealized": risk["MinimumUnrealized"],
                              "min_unrealized_at": mark_view(risk["MinimumUnrealizedAt"], scene["start"]),
                              "min_equity_at": mark_view(risk["MinimumAt"], scene["start"]),
                              "drawdown_peak": mark_view(risk["DDFrom"], scene["start"]),
                              "drawdown_trough": mark_view(risk["DDTo"], scene["start"])},
           "projection_checks": case.get("projection_checks", 0),
           "projection_max_difference": case.get("projection_max_difference", 0),
           "adverse_recovery": adverse}
    if not row["partial"]:
        assert row["remaining_qty"] == 0 and not ledger.get("Pending"), "完了場残玉/予約"
        equal(row["profit"] - row["loss"], row["net"], "完了親集計")
    return row, {"actual": actual, "canonical": canonical,
                 "policy_parents": case["parents"], "decisions": case.get("decisions") or []}


def main() -> None:
    """正常終了の証跡を確認後、全条件場の保存結果を集計する。

    引数: なし。返り値: None。金融再生の呼出しは一切含まない。
    """
    completed = read(BASE / "金融実行1573.json")
    assert completed["終了コード"] == 0 and completed["参照改変数"] == 0
    first_path = FIRST / "report157.json"
    assert hashlib.sha256(first_path.read_bytes()).hexdigest() == FIRST_SHA
    first_report = read(first_path)
    second_path = SECOND / "report1572.json"
    assert hashlib.sha256(second_path.read_bytes()).hexdigest() == SECOND_SHA
    second_report = read(second_path)
    configs = read(BASE / "configs1573.json")
    manifest = read(OLD / "inputs156.json")
    previous = read(OLD / "report156_all.json")
    source_hash = hashlib.sha256((OLD / "report156_all.json").read_bytes()).hexdigest()
    source_method = next(method for method in previous["methods"] if method["id"] == "S01")
    labels = {row["session"]: row for row in source_method["rows"]}
    labels.update({row["session"]: row for row in previous["current_rows"] if row["id"] == "S01"})
    wanted = {config["id"] for config in configs}
    files = sorted((BASE / "results_go").glob("*.json"))
    assert len(files) == len(manifest["sessions"])
    by_method, current, exact, inputs, accounts = defaultdict(list), [], [], [], {}
    for path in files:
        saved = read(path)
        scene = saved["scene"]
        assert {case["config"]["id"] for case in saved["cases"]} == wanted
        second_saved = read(SECOND / "results_go" / path.name)
        reference = next(case for case in second_saved["cases"] if case["config"]["id"] == "J02")
        inputs.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        for case in saved["cases"]:
            row, detail = make_row(case, labels[scene["session"]])
            if row["id"] == "O00":
                for book in ("actual", "canonical"):
                    # 名前だけが異なる同値対照のID接頭辞を揃え、台帳全体を照合する。
                    normalized = json.loads(json.dumps(case[book]).replace('"O00', '"J02'))
                    assert normalized == reference[book], f"O00/J02の{book}台帳不一致"
                exact.append({"session": row["session"], "same_value": True,
                              "events": len(case["actual"].get("Events") or [])})
            save(BASE / "audit" / "cases" / row["session"] / f'{row["id"]}.json', {"row": row, **detail})
            accounts[(row["session"], row["id"])] = detail["actual"]["parents"]
            if row["partial"]:
                current.append(row)
            else:
                by_method[row["id"]].append(row)
        print(f'再会計 {scene["session"]} {len(saved["cases"])}条件', flush=True)
    methods = []
    for config in configs:
        rows = attach_cumulative(by_method[config["id"]])
        assert len(rows) == 26
        summary = summarize(rows)
        summary["entry_types"] = {}
        summary["canonical_entry_types"] = {}
        summary["counts"] = {}
        summary["rejections"] = {}
        summary["adverse_recovery"] = {}
        for row in rows:
            for scope in ("entry_types", "canonical_entry_types"):
                for kind, values in row[scope].items():
                    target = summary[scope].setdefault(kind, {})
                    for key, value in values.items():
                        target[key] = target.get(key, 0) + value
            for key, value in row["counts"].items():
                summary["counts"][key] = summary["counts"].get(key, 0) + value
                if any(word in key for word in ("拒否", "枠不足", "予約競合")):
                    summary["rejections"][key] = summary["rejections"].get(key, 0) + value
            for entry in row["adverse_recovery"]:
                key = f'{entry["ledger"]}/{entry["attribution"]}/{entry["category"]}'
                target = summary["adverse_recovery"].setdefault(key, {"entries": 0, "quantity": 0, "realized": 0.0})
                target["entries"] += 1
                target["quantity"] += entry["quantity"]
                target["realized"] += entry["realized"]
        summary["quantities"] = {"average_gross": sum(r["quantities"]["average_gross"] for r in rows) / len(rows),
                                 "average_net_abs": sum(r["quantities"]["average_net_abs"] for r in rows) / len(rows),
                                 "held_rate": sum(r["quantities"]["held_rate"] for r in rows) / len(rows),
                                 "maximum_gross": max(r["quantities"]["max"]["gross"] for r in rows),
                                 "maximum_net_abs": max(r["quantities"]["max"]["net_abs"] for r in rows)}
        methods.append({"id": config["id"], "description": config["description"], "config": config,
                        "rows": rows, "summary": summary,
                        "up": summarize([row for row in rows if row["direction"] == "上昇"]),
                        "down": summarize([row for row in rows if row["direction"] == "下落"]),
                        "flat": summarize([row for row in rows if row["direction"] == "同値"])})
    controls = read(FIRST / "比較元の場内赤字.json")["pure_scalings"]
    comparisons = []
    for method in methods:
        control = method["config"].get("control")
        if not control:
            continue
        for row in method["rows"]:
            if (row["session"], control) in accounts:
                previous_account = accounts[(row["session"], control)]
            else:
                previous_account = read(SECOND / "audit/cases" / row["session"] / f"{control}.json")["actual"]["parents"]
            previous_parents = {p["id"]: p for p in previous_account}
            new_parents = {p["id"]: p for p in accounts[(row["session"], method["id"]) ]}
            removed = [p for key, p in previous_parents.items() if key not in new_parents]
            added = [p for key, p in new_parents.items() if key not in previous_parents]
            common = [{"parent": key, "before": previous_parents[key]["realized"],
                       "after": p["realized"], "delta": p["realized"] - previous_parents[key]["realized"]}
                      for key, p in new_parents.items() if key in previous_parents]
            delta = sum(p["realized"] for p in added) - sum(p["realized"] for p in removed) + sum(p["delta"] for p in common)
            equal(delta, row["net"] - sum(p["realized"] for p in previous_parents.values()), "親対応の収支差")
            comparisons.append({"id": method["id"], "control": control, "session": row["session"], "net_delta": delta,
                                "removed": removed, "added": added, "common": common,
                                "removed_wins": sum(p["realized"] > 0 for p in removed),
                                "removed_losses": sum(p["realized"] < 0 for p in removed)})
    save(BASE / "audit" / "comparisons1573.json", comparisons)
    result = {"methods": methods, "current_rows": current,
              "arithmetic_controls": [control for control in controls if control["scale"] in (0.5, 0.2)],
              "definition": {"profit_loss": "完結Source親の最終純額を正負分類。途中の未完親確定と含みは別列。",
                             "product": "日経micro相当", "point_value": 10, "cap_per_side": 100,
                             "fees": 0, "support": "未校正支持値。確率ではない。",
                             "canonical": "実口座へ合算しない。H/Q相殺はSource親内のみ。役割損益はCanonicalで、純量版の実種別projectionへ擬似配賦しない。",
                             "adverse": "逆行回復追加。新実約定の平均建値改善を有利/同値/不利/比較元なしへ分離。実帳簿とCanonicalを混ぜない。"},
              "audit": {"cases": len(files) * len(configs), "exact_o00": exact,
                        "source_report_sha256": source_hash, "saved_result_fingerprints": inputs}}
    assert hashlib.sha256((OLD / "report156_all.json").read_bytes()).hexdigest() == source_hash
    assert hashlib.sha256(first_path.read_bytes()).hexdigest() == FIRST_SHA
    assert hashlib.sha256(second_path.read_bytes()).hexdigest() == SECOND_SHA
    save(BASE / "report1573.json", result)
    # 数量分布の整数キーはJSON保存時に文字列になるため、双方の保存表現で照合する。
    saved_second = read(BASE / "report1573.json")
    reference_rows = next(method for method in second_report["methods"] if method["id"] == "J02")["rows"]
    duplicate_rows = next(method for method in saved_second["methods"] if method["id"] == "O00")["rows"]
    normalized_rows = json.loads(json.dumps(duplicate_rows).replace('"O00', '"J02'))
    assert reference_rows == normalized_rows, "O00/J02の全26場不一致"
    reference_partial = next(row for row in second_report["current_rows"] if row["id"] == "J02")
    duplicate_partial = next(row for row in saved_second["current_rows"] if row["id"] == "O00")
    assert reference_partial == json.loads(json.dumps(duplicate_partial).replace('"O00', '"J02')), "O00/J02の途中会計不一致"
    previous_methods = first_report["methods"] + [method for method in second_report["methods"] if method["id"] != "C00"]
    previous_current = first_report["current_rows"] + [row for row in second_report["current_rows"] if row["id"] != "C00"]
    previous_ids = {method["id"] for method in previous_methods}
    new_ids = {method["id"] for method in methods}
    assert not previous_ids & new_ids, "第三巡IDの衝突"
    combined = dict(first_report)
    combined["methods"] = previous_methods + [method for method in methods if method["id"] != "O00"]
    combined["current_rows"] = previous_current + [row for row in current if row["id"] != "O00"]
    combined["audit"] = {
        "round1": first_report["audit"], "round2": second_report["audit"], "round3": result["audit"],
        "round1_report_sha256": FIRST_SHA,
        "round2_report_sha256": SECOND_SHA,
        "round3_report_sha256": hashlib.sha256((BASE / "report1573.json").read_bytes()).hexdigest(),
        "duplicate_c00_exact": True, "duplicate_o00_j02_exact": True,
        "unique_cases": len(combined["methods"]) * len(files),
    }
    assert len(combined["methods"]) == len(previous_ids | new_ids) - 1
    save(FIRST / "report157_all.json", combined)
    print(json.dumps({"methods": len(methods), "complete_rows": sum(len(m["rows"]) for m in methods),
                      "current_rows": len(current), "exact_controls": len(exact),
                      "combined_methods": len(combined["methods"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
