"""保存済みの約定だけを再会計する独立検算。売買条件の再生は行わない。"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median


BASE = Path(__file__).resolve().parents[1]
AUDIT = Path(__file__).resolve().parent


def same(actual: float, expected: float, label: str) -> None:
    """数値を独立照合する。

    引数: actual/expected(float)は比較値、label(str)は不整合位置。
    返り値: None。不一致はAssertionErrorとする。
    """
    assert abs(actual - expected) < 0.00001, (label, actual, expected)


def reconcile_case(case: dict) -> dict:
    """約定と返済対象から玉・親の全損益を再構築する。

    引数: case(dict)は保存された一条件一場。返り値: dictは独立会計。
    """
    lots: dict = {}
    parents: dict = {}
    fills: set = set()
    gross = 0.0
    max_side = {1: 0, -1: 0}
    snapshots = {s["Index"]: s for s in case["snapshots"] or []}
    label = f"{case['scene']['session']}/{case['config']['id']}"
    for event in case["events"] or []:
        sig, fill = event["signal"], event["fill"]
        assert fill["SignalID"] == sig["id"] and fill["ExecutionID"] not in fills, label
        fills.add(fill["ExecutionID"])
        assert event["fill_index"] > event["decision_index"] == sig["source_index"], label
        assert fill["Time"] >= sig["time"] and fill["Quantity"] == sig["quantity"], label
        snap = snapshots[event["fill_index"]]
        same(fill["Price"], snap["Ask"] if sig["side"] > 0 else snap["Bid"], label + "/約定側")
        key = f"{sig['owner']}:{sig['campaign']}"
        if sig["action"] == "new":
            hold = fill["HoldID"]
            assert hold not in lots, label
            if key not in parents:
                parents[key] = {
                    "owner": sig["owner"], "campaign": sig["campaign"], "side": sig["side"],
                    "first_decision_index": sig["source_index"], "first_time": fill["Time"],
                    "first_price": fill["Price"], "first_quantity": fill["Quantity"],
                    "net": 0.0, "first_lot_net": 0.0, "added_lot_net": 0.0,
                    "new_orders": 0, "new_quantity": 0, "closes": [], "lots": [],
                }
            p = parents[key]
            lot = {
                "id": hold, "parent": key, "quantity": fill["Quantity"], "remaining": fill["Quantity"],
                "side": sig["side"], "price": fill["Price"], "entry_time": fill["Time"],
                "entry_index": event["fill_index"], "reason": sig["reason_code"],
                "first": p["new_orders"] == 0, "net": 0.0, "closes": [],
            }
            lots[hold] = lot
            p["lots"].append(hold)
            p["new_orders"] += 1
            p["new_quantity"] += fill["Quantity"]
            same(event["gross"], 0.0, label + "/新規損益")
        else:
            subtotal = 0.0
            targets = fill["Closed"] or []
            assert targets == sig["targets"], label
            assert sum(t["quantity"] for t in targets) == fill["Quantity"], label
            for target in targets:
                lot = lots[target["id"]]
                assert lot["remaining"] >= target["quantity"] and lot["side"] == -sig["side"], label
                p = parents[lot["parent"]]
                assert p["owner"] == sig["owner"] and p["campaign"] == sig["campaign"], label
                amount = lot["side"] * (fill["Price"] - lot["price"]) * target["quantity"] * 100
                lot["remaining"] -= target["quantity"]
                lot["net"] += amount
                detail = {"time": fill["Time"], "index": event["fill_index"], "price": fill["Price"],
                          "quantity": target["quantity"], "net": amount, "reason": sig["reason_code"]}
                lot["closes"].append(detail)
                p["closes"].append(detail)
                p["net"] += amount
                p["first_lot_net" if lot["first"] else "added_lot_net"] += amount
                subtotal += amount
            same(subtotal, event["gross"], label + "/返済損益")
            gross += subtotal
        for side in (1, -1):
            held = sum(l["remaining"] for l in lots.values() if l["side"] == side)
            assert held <= 10, label
            max_side[side] = max(max_side[side], held)
        for owner, cap in (("core", 5), ("addon", 3), ("episode", 2)):
            held = sum(l["remaining"] for l in lots.values() if parents[l["parent"]]["owner"] == owner)
            assert held <= cap, label
    same(gross, case["Gross"], label + "/場収支")
    same(sum(p["net"] for p in parents.values()), gross, label + "/親収支")
    assert set(lots) == set(case["entries"]), label
    unrealized = 0.0
    for hold, lot in lots.items():
        saved = case["entries"][hold]
        assert saved["Quantity"] == lot["quantity"] and saved["Remaining"] == lot["remaining"], label
        same(saved["Gross"], lot["net"], label + "/玉収支")
        same(saved["Price"], lot["price"], label + "/玉建値")
        if lot["closes"]:
            for close in lot["closes"]:
                gain = lot["side"] * (close["price"] - lot["price"])
                assert saved["WorstPoints"] <= gain + 0.00001, (label, "返済行最大逆行", hold)
                assert saved["BestPoints"] >= gain - 0.00001, (label, "返済行最大順行", hold)
        if lot["remaining"]:
            mark = case["last_quote"]["Bid" if lot["side"] == 1 else "Ask"]
            unrealized += lot["side"] * (mark - lot["price"]) * lot["remaining"] * 100
    same(unrealized, case["Unrealized"], label + "/途中含み")
    if not case["scene"]["partial"]:
        assert not case["final_pending"] and all(l["remaining"] == 0 for l in lots.values()), label
    complete_parents = [p for p in parents.values() if all(lots[h]["remaining"] == 0 for h in p["lots"])]
    # ----------------------------------------
    # 判断順に新規予約を戻し、返済予約で空き枠を先取りしていないか確認する。
    timeline = []
    signals = {s["id"]: s for s in case["signals"] or []}
    assert len(signals) == len(case["signals"] or []), label
    for sig in signals.values():
        timeline.append((sig["source_index"], 1, sig))
    for event in case["events"] or []:
        assert event["signal"] == signals[event["signal"]["id"]], label
        timeline.append((event["fill_index"], 0, event["signal"]))
    reservations = {}
    owned = defaultdict(int)
    held_side = defaultdict(int)
    for _, phase, sig in sorted(timeline, key=lambda item: (item[0], item[1])):
        if phase == 1:
            reservations[sig["id"]] = sig
        else:
            assert sig["id"] in reservations, label
            del reservations[sig["id"]]
            delta = sig["quantity"] if sig["action"] == "new" else -sig["quantity"]
            position_side = sig["side"] if sig["action"] == "new" else -sig["side"]
            owned[sig["owner"]] += delta
            held_side[position_side] += delta
        for owner, cap in (("core", 5), ("addon", 3), ("episode", 2)):
            reserved = sum(s["quantity"] for s in reservations.values() if s["action"] == "new" and s["owner"] == owner)
            assert 0 <= owned[owner] + reserved <= cap, (label, "予約込み担当上限", owner)
        for side in (1, -1):
            reserved = sum(s["quantity"] for s in reservations.values() if s["action"] == "new" and s["side"] == side)
            assert 0 <= held_side[side] + reserved <= 10, (label, "予約込み片方向上限", side)
    assert set(reservations) == {s["id"] for s in case["final_pending"] or []}, label
    profit = sum(max(0, p["net"]) for p in complete_parents)
    loss = sum(max(0, -p["net"]) for p in complete_parents)
    open_parent_realized = gross - profit + loss
    return {
        "id": case["config"]["id"], "session": case["scene"]["session"],
        "kind": case["scene"]["kind"], "partial": case["scene"]["partial"],
        "profit": profit, "loss": loss, "net": gross, "unrealized": unrealized,
        "equity": gross + unrealized, "open_parent_realized": open_parent_realized,
        "orders": len(case["events"] or []), "new_orders": len(lots),
        "new_quantity": sum(l["quantity"] for l in lots.values()), "parent_count": len(parents),
        "max_long": max_side[1], "max_short": max_side[-1], "parents": parents, "lots": lots,
    }


def summarize(rows: list[dict]) -> dict:
    """独立場会計を集計する。

    引数: rows(list[dict])は完了場。返り値: dictは累計と損失頻度。
    """
    values = [r["net"] for r in rows]
    red = [-v for v in values if v < 0]
    return {
        "sessions": len(rows), "net": sum(values), "profit": sum(r["profit"] for r in rows),
        "loss": sum(r["loss"] for r in rows), "red": len(red), "zero": values.count(0),
        "no_trade": sum(r["new_orders"] == 0 for r in rows),
        "mean_red": mean(red) if red else 0, "median_red": median(red) if red else 0,
        "max_red": max(red, default=0), "median_net": median(values) if values else 0,
        "exclude_top3": sum(values) - sum(sorted((v for v in values if v > 0), reverse=True)[:3]),
        "new_orders": sum(r["new_orders"] for r in rows), "new_quantity": sum(r["new_quantity"] for r in rows),
    }


def main() -> None:
    """全保存結果の完成を確認して独立再会計する。

    引数: なし。返り値: None。研究器を呼ばず、保存約定の全件だけを読む。
    """
    files = sorted((BASE / "results_go").glob("*_D07.json"))
    assert len(files) == 52, ("結果未完成", len(files))
    grouped: dict = defaultdict(list)
    hashes = []
    case_dir = AUDIT / "cases"
    case_dir.mkdir(exist_ok=True)
    for path in files:
        raw = path.read_bytes()
        saved = json.loads(raw)
        assert len(saved["cases"]) == 15
        hashes.append({"file": path.name, "sha256": hashlib.sha256(raw).hexdigest()})
        for case in saved["cases"]:
            row = reconcile_case(case)
            (case_dir / f"{row['session']}_{row['id']}.json").write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
            grouped[row["id"]].append({k: v for k, v in row.items() if k not in ("parents", "lots")})
    result = {"金融再生": False, "源ファイル数": len(files), "条件場数": sum(map(len, grouped.values())), "入力指紋": hashes, "methods": []}
    for method, rows in grouped.items():
        complete = [r for r in rows if not r["partial"]]
        assert len(complete) == 51 and len(rows) == 52
        result["methods"].append({"id": method, "summary": summarize(complete),
                                  "day": summarize([r for r in complete if r["kind"] == "Day"]),
                                  "night": summarize([r for r in complete if r["kind"] == "Night"]),
                                  "rows": rows})
    report_path = BASE / "report154.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8-sig"))
        for method in report["methods"]:
            own = next(m for m in result["methods"] if m["id"] == method["id"])
            for row in method["rows"]:
                candidate = next(r for r in own["rows"] if r["session"] == row["session"])
                for key in ("profit", "loss", "net", "unrealized"):
                    if key in row:
                        same(candidate[key], row[key], f"報告照合/{method['id']}/{row['session']}/{key}")
        result["報告書照合"] = True
    (AUDIT / "独立結果会計154.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"条件場数": result["条件場数"], "methods": [{"id": m["id"], **m["summary"]} for m in result["methods"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
