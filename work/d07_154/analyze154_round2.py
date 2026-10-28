"""00154第二巡の保存会計を、確定済み初巡を変更せず独立に集計する。"""

from __future__ import annotations

import importlib.util
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np


WORK = Path(__file__).resolve().parent
OUT = WORK / "data_audit_round2"
module_spec = importlib.util.spec_from_file_location("初巡会計154", WORK / "analyze154.py")
a = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(a)


def audit_case(scene: dict, case: dict, q: dict) -> tuple[dict, list, list, list, dict]:
    """共通会計で次正常約定・全在庫を照合し、親別の利益返しも評価する。

    引数: scene,case,q(dict)。返り値: (場会計dict,玉list,親list,返済配賦list,時価dict)。
    """
    values, lots, parents, allocations = a.independent_account(scene, case, q)
    last_i = int(np.flatnonzero(q["valid"])[-1])
    risk = a.mark_saved_positions(q, lots, 0, last_i)
    values["equity_drawdown"] = risk["drawdown"]
    values["minimum_equity"] = risk["minimum_equity"]["value"] if risk["minimum_equity"] else 0
    for parent in parents:
        owned = [l for l in lots if l["parent"] == parent["key"]]
        parent.update(a.mark_saved_positions(q, owned, parent["entry"]["index"], parent["exit"]["index"] if parent["closed"] else last_i))
        parent.update(session=scene["session"], kind=scene["kind"])
        parent["giveback"] = parent["peak_equity"]["value"] - parent["net"]
        parent["entry_diagnostics"] = a.diagnostic_snapshot(case, parent["decision"]["index"], parent["owner"])
        parent["peak_diagnostics"] = a.diagnostic_snapshot(case, parent["peak_equity"]["index"], parent["owner"])
        parent["last_diagnostics"] = a.diagnostic_snapshot(case, parent["events"][-1]["decision"]["index"], parent["owner"])
    for lot in lots:
        lot.update(session=scene["session"], kind=scene["kind"])
    row = {"id": case["config"]["id"], "symbol": "NK225", "session": scene["session"], "kind": scene["kind"],
           "direction": a.direction(scene), "direction_source": "当場最初Lastと終了前6分以内の最終Last代理。正式終値ではない。事後採点のみ。", **values}
    row["reference_rejection_notifications"] = len(case.get("reference_rejections") or [])
    row["jab_parents"] = sum(p["owner"] == "core" and (p.get("entry_diagnostics") or {}).get("diagnostics", {}).get("jab_mode154", 0) > 0 for p in parents)
    if scene["partial"]:
        stop = datetime(2026, 10, 27, 11, 21, 41, tzinfo=a.JST).timestamp()
        row["at_actual_stop"] = a.value_at(lots, q, stop)
        row["direction_source"] = "当場最初Lastと取得済み観測末尾Last。場末方向ではない。"
    return row, lots, parents, allocations, risk


def compare(old: list, new: list, scene: dict) -> dict:
    """同入口の数量・出口・追加差と、新設・消失親を区別する。

    引数: old,new(list[dict])、scene(dict)。返り値: dict。
    """
    value = a.compare_parents(old, new)
    value["vanished_examples"] = [a.short_parent(p) for p in value["vanished_examples"]]
    value["appeared_examples"] = [a.short_parent(p) for p in value["appeared_examples"]]
    return {"session": scene["session"], "partial": scene["partial"], **value}


def main() -> None:
    """第二巡全52資料を受領した後にだけ集計し、初巡の指紋不変を確認する。

    引数: なし。返り値: None。金融売買再生は呼び出さない。
    """
    first_path = WORK / "report154.json"
    first_fingerprint = a.fingerprint(first_path)
    assert first_fingerprint["sha256"] == "4609aba84254314a1526cc3a9456822b6e7b123d4bcf764d0804f634190fa70a"
    first = a.load(first_path)
    manifest_path = WORK / "inputs154.json"
    assert a.fingerprint(manifest_path)["sha256"] == "d30747d798397efd31b4ce73c9a9cf0a4519346946c331889037ce724b691b90"
    configs_path = WORK / "configs154_round2.json"
    configs, manifest = a.load(configs_path), a.load(manifest_path)
    ids = [c["id"] for c in configs]
    assert len(ids) == len(set(ids)) == 8
    scenes = manifest["sessions"]
    paths = [WORK / "results_round2" / (s["session"] + "_D07.json") for s in scenes]
    assert all(p.exists() for p in paths), "全52場受領後に集計してください"
    baseline_rows = {r["session"]: r for r in first["session_rows"] + first["current_rows"] if r["id"] == "D07"}
    prior_sources = {Path(p["path"]).name: p for p in first["sources"]["results"]}
    rows, partial, sources = [], [], []
    comparisons, direct = defaultdict(list), defaultdict(list)
    parent_summaries, addition_summaries = defaultdict(list), defaultdict(list)
    verified = decisions = baseline_verified = guard_control_verified = 0
    for scene, path in zip(scenes, paths):
        saved = a.load(path)
        assert saved["scene"]["session"] == scene["session"] and [c["config"]["id"] for c in saved["cases"]] == ids
        q, _ = a.read_quotes(scene)
        prior_path = WORK / "results_go" / path.name
        assert a.fingerprint(prior_path)["sha256"] == prior_sources[path.name]["sha256"]
        prior_saved = a.load(prior_path)
        prior_case = next(c for c in prior_saved["cases"] if c["config"]["id"] == "D07")
        baseline, _, baseline_parents, _ = a.independent_account(scene, prior_case, q)
        baseline_verified += baseline["verified_events"]
        guard_case = next(c for c in prior_saved["cases"] if c["config"]["id"] == "G02")
        guard_values, _, guard_parents, _ = a.independent_account(scene, guard_case, q)
        guard_control_verified += guard_values["verified_events"]
        for key in ("profit", "loss", "net", "unrealized", "equity", "entries", "parents"):
            a.near(baseline[key], baseline_rows[scene["session"]][key], "初巡基準の保存会計不変")
        new_parents = {}
        for case in saved["cases"]:
            identifier = case["config"]["id"]
            row, lots, parents, allocations, risk = audit_case(scene, case, q)
            verified += row["verified_events"]
            decisions += row["verified_decisions"]
            target = OUT / "cases" / scene["session"] / (identifier + ".json")
            a.write(target, {"row": row, "risk": risk, "parents": parents, "lots": lots, "allocations": allocations,
                            "reference_rejections": case.get("reference_rejections") or []})
            new_parents[identifier] = parents
            comparisons[identifier].append(compare(baseline_parents, parents, scene))
            if scene["partial"]:
                partial.append(row)
            else:
                rows.append(row)
                parent_summaries[identifier].extend(a.short_parent(p) for p in parents)
                addition_summaries[identifier].extend(a.short_lot(l) for l in lots if l["type"] == "追撃")
        for old, new in (("S00", "S01"), ("S04", "S02"), ("J01", "J02"), ("J02", "J03")):
            direct[f"{old}→{new}"].append(compare(new_parents[old], new_parents[new], scene))
        direct["G02→S03"].append(compare(guard_parents, new_parents["S03"], scene))
        sources.append(a.fingerprint(path))
        print(f'第二巡会計完了 {scene["session"]} 8条件', flush=True)
    # ----------------------------------------
    # 初巡と同じ列名で8新条件を保存する。初巡15条件は呼出側がそのまま結合できる。
    methods, method_rows, diagnoses = [], [], {}
    d07 = next(m for m in first["methods"] if m["id"] == "D07")
    for cfg in configs:
        identifier = cfg["id"]
        selected = [r for r in rows if r["id"] == identifier]
        summary = a.summarize(selected)
        summary["reference_rejection_notifications"] = sum(r["reference_rejection_notifications"] for r in selected)
        summary["jab_parents"] = sum(r["jab_parents"] for r in selected)
        categories = {name: a.summarize([r for r in selected if r[field] == value])
                      for name, field, value in (("day", "kind", "Day"), ("night", "kind", "Night"),
                          ("up", "direction", "上昇"), ("down", "direction", "下落"), ("flat", "direction", "横ばい"))}
        methods.append({"id": identifier, "symbol": "NK225", "description": cfg["description"], "config": cfg,
                        "rows": selected, "summary": summary, **categories})
        method_rows.append({"id": identifier, "description": cfg["description"], **summary,
            "difference_from_D07": summary["net"] - d07["summary"]["net"],
            "day_net": categories["day"]["net"], "day_losses": categories["day"]["losses"],
            "night_net": categories["night"]["net"], "night_losses": categories["night"]["losses"],
            "up_net": categories["up"]["net"], "down_net": categories["down"]["net"]})
        parents, additions = parent_summaries[identifier], addition_summaries[identifier]
        small = [p for p in parents if p["small_peak_unrealized"] and p["small_peak_unrealized"]["value"] > 0]
        small_equity = [p for p in parents if p["small_peak_equity"] and p["small_peak_equity"]["value"] > 0]
        neg_adds = [l for l in additions if l["net"] < 0]
        diagnoses[identifier] = {"small_positive_parents": len(small), "small_positive_final_loss": sum(p["net"] < 0 for p in small),
            "small_positive_equity_parents": len(small_equity), "small_positive_equity_final_loss": sum(p["net"] < 0 for p in small_equity),
            "additions": a.sign_sums([l["net"] for l in additions]), "losing_additions": len(neg_adds),
            "losing_additions_within300s": sum(l["duration_seconds"] <= 300 for l in neg_adds),
            "worst_additions": sorted(neg_adds, key=lambda l: l["net"])[:10],
            "largest_givebacks": sorted(parents, key=lambda p: p["giveback"], reverse=True)[:10],
            "worst_sessions": [{"session": r["session"], "net": r["net"],
                 "worst_parents": sorted([p for p in parents if p["session"] == r["session"]], key=lambda p: p["net"])[:5]}
                for r in sorted(selected, key=lambda r: r["net"])[:3]]}
    report = {"definition": first["definition"], "summary": {"complete_sessions": 51, "day_sessions": 26,
              "night_sessions": 25, "methods": 8, "current_sessions": 1, "verified_events": verified,
              "verified_decisions": decisions, "rechecked_baseline_events": baseline_verified},
              "methods": methods, "method_rows": method_rows, "session_rows": rows, "current_rows": partial,
              "sources": {"first_report": first_fingerprint, "manifest": a.fingerprint(manifest_path), "configs": a.fingerprint(configs_path),
                          "results": sources, "shared_analyzer": a.fingerprint(WORK / "analyze154.py"), "analyzer": a.fingerprint(Path(__file__))}}
    a.write(OUT / "comparison154_round2.json", dict(comparisons))
    a.write(OUT / "direct_comparison154_round2.json", dict(direct))
    a.write(OUT / "diagnosis154_round2.json", diagnoses)
    target = WORK / "report154_round2.json"
    a.write(target, report)
    combined = {**first,
        "summary": {**first["summary"], "methods": 23,
                    "verified_events": first["summary"]["verified_events"] + verified,
                    "verified_decisions": first["summary"]["verified_decisions"] + decisions,
                    "rechecked_G02_control_events": guard_control_verified},
        "methods": first["methods"] + methods, "method_rows": first["method_rows"] + method_rows,
        "session_rows": first["session_rows"] + rows, "current_rows": first["current_rows"] + partial,
        "sources": {"first_report": first_fingerprint, "second_report": a.fingerprint(target),
                    "shared_manifest": a.fingerprint(manifest_path)}}
    assert len(combined["methods"]) == len({m["id"] for m in combined["methods"]}) == 23
    a.write(WORK / "report154_combined.json", combined)
    assert a.fingerprint(first_path)["sha256"] == first_fingerprint["sha256"]
    a.write(OUT / "会計照合154_round2.json", {"passed": True, **report["summary"], "report": a.fingerprint(target),
              "first_report_unchanged": True, "first_report": first_fingerprint,
              "combined": a.fingerprint(WORK / "report154_combined.json")})
    print(json.dumps({"passed": True, **report["summary"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
