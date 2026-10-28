"""第二巡の保存約定・拒否記録だけを独立再会計する。金融再生を呼び出さない。"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from reconcile154 import reconcile_case, same, summarize


BASE = Path(__file__).resolve().parents[1]
AUDIT = Path(__file__).resolve().parent


def semantic_events(case: dict, owners: set[str]) -> list:
    """注文IDの連番差を除き、実売買と返済対象の対応を比較できる形式にする。

    引数: case(dict)は保存結果、owners(set[str])は対象担当。返り値: listは売買経路。
    """
    keys, ordinal, result = {}, defaultdict(int), []
    for e in case["events"] or []:
        s, f = e["signal"], e["fill"]
        if s["owner"] not in owners:
            continue
        parent = (s["owner"], s["campaign"])
        if s["action"] == "new":
            keys[f["HoldID"]] = (*parent, ordinal[parent])
            ordinal[parent] += 1
        targets = tuple((keys[t["id"]], t["quantity"]) for t in (f.get("Closed") or s.get("targets") or []))
        result.append((s["owner"], s["campaign"], s["action"], s["side"], s["quantity"],
                       s["time"], s["source_index"], s["reason_code"], s.get("ticket", 0),
                       f["Price"], f["Time"], e["fill_index"], e["gross"], targets))
    return result


def inventory_at(case: dict, index: int, owner: str) -> tuple[list[dict], int, bool]:
    """保存結果から当該行までに実約定した玉と既発注の未確定だけを再構成する。

    引数: case(dict)、index(int)、owner(str)。返り値: (残玉list, 最新採用親int, 未確定bool)。
    後の約定は監査上の終了確認にのみ用い、売買条件の再生には使わない。
    """
    lots, parent, pending = {}, -1, False
    for e in case["events"] or []:
        s, f = e["signal"], e["fill"]
        if s["owner"] != owner or e["fill_index"] > index:
            continue
        if s["action"] == "new":
            lots[f["HoldID"]] = {"quantity": f["Quantity"], "price": f["Price"], "side": s["side"],
                                  "campaign": s["campaign"], "fixed_r": s["evidence"]["fixed_r"]}
        else:
            for t in f.get("Closed") or s.get("targets") or []:
                lots[t["id"]]["quantity"] -= t["quantity"]
    fills = {e["signal"]["id"]: e["fill_index"] for e in case["events"] or []}
    for s in case["signals"] or []:
        if s["owner"] != owner or s["source_index"] > index:
            continue
        if s["action"] == "new":
            parent = s["campaign"]
        if fills.get(s["id"], float("inf")) > index:
            pending = True
    return [v for v in lots.values() if v["quantity"] > 0], parent, pending


def verify_reference(case: dict, baseline: dict) -> list:
    """影の拒否が同じ原行までの基準実玉・予約で説明できることを照合する。

    引数: case/baseline(dict)。返り値: listは確認済み拒否。
    """
    out = []
    for reject in case.get("reference_rejections") or []:
        assert reject["owner"] == "episode", reject
        held, campaign, pending = inventory_at(baseline, reject["index"], "episode")
        recorded = reject["reference"]
        assert recorded is not None and recorded["campaign"] == campaign, (case["config"], reject, campaign)
        assert recorded["occupied"] == bool(held or pending), (reject, held, pending)
        assert recorded["occupied"] and campaign != reject["campaign"], reject
        same(recorded["at"], reject["time"], "影当行時計")
        assert not any(s["owner"] == "episode" and s["action"] == "new" and s["campaign"] == reject["campaign"]
                       for s in case["signals"] or []), ("拒否親の後追い採用", reject)
        out.append(reject)
    return out


def verify_j_quantity(case: dict) -> list:
    """Jの初回数量が当時の同方向実episodeの数量加重含み条件に一致することを確認する。

    引数: case(dict)。返り値: listは判定時の幅と選択枚数。
    """
    if case["scene"]["kind"] != "Day":
        # 夜の補完初回は元から4枚などを含むため、全売買経路の基準同値で検査する。
        return []
    seen, out = set(), []
    for s in case["signals"] or []:
        if s["owner"] != "core" or s["action"] != "new" or s["campaign"] in seen:
            continue
        seen.add(s["campaign"])
        held, _, _ = inventory_at(case, s["source_index"], "episode")
        same_side = held and all(l["side"] == s["side"] for l in held)
        width = None
        gate = False
        if case["scene"]["kind"] == "Day" and same_side:
            q = sum(l["quantity"] for l in held)
            average = sum(l["quantity"] * l["price"] for l in held) / q
            o = s["evidence"]["observation"]
            mark = o["Bid"] if s["side"] > 0 else o["Ask"]
            width = s["side"] * (mark - average)
            fixed_r = held[0]["fixed_r"]
            assert all(abs(l["fixed_r"] - fixed_r) < 1e-8 for l in held)
            gate = width >= fixed_r
        assert s["quantity"] == (1 if gate else 5), (case["scene"]["session"], case["config"]["id"], s, width)
        out.append({"session": case["scene"]["session"], "id": case["config"]["id"], "time": s["time"],
                    "index": s["source_index"], "side": s["side"], "campaign": s["campaign"],
                    "quantity": s["quantity"], "episode_width": width})
    return out


def compare_parents(original: dict, candidate: dict) -> dict:
    """同じ初回判断を持つ親と、失われた親・新設親へ場収支差を分ける。

    引数: original/candidate(dict)は独立再会計。返り値: dictは差分恒等式。
    """
    def keyed(row: dict) -> dict:
        """独立再会計から比較キーを作る。

        引数: row(dict)。返り値: dictは担当・売買方向・初回原行から親への対応。
        """
        return {(p["owner"], p["side"], p["first_decision_index"]): p for p in row["parents"].values()}
    old, new = keyed(original), keyed(candidate)
    matched, vanished, appeared = old.keys() & new.keys(), old.keys() - new.keys(), new.keys() - old.keys()
    quantity = sum(old[k]["first_lot_net"] * (new[k]["first_quantity"] / old[k]["first_quantity"] - 1) for k in matched)
    first_exit = sum(new[k]["first_lot_net"] - old[k]["first_lot_net"] * new[k]["first_quantity"] / old[k]["first_quantity"] for k in matched)
    additional = sum(new[k]["added_lot_net"] - old[k]["added_lot_net"] for k in matched)
    lost = sum(old[k]["net"] for k in vanished)
    fresh = sum(new[k]["net"] for k in appeared)
    difference = candidate["net"] - original["net"]
    same(quantity + first_exit + additional - lost + fresh, difference, "親対応差分恒等式")
    return {"session": candidate["session"], "partial": candidate["partial"], "difference": difference,
            "old_net": original["net"], "new_net": candidate["net"], "initial_quantity_effect": quantity,
            "first_exit_effect": first_exit, "additional_or_reentry_effect": additional,
            "vanished_count": len(vanished), "vanished_net": lost,
            "appeared_count": len(appeared), "appeared_net": fresh,
            "vanished": [old[k] for k in sorted(vanished)], "appeared": [new[k] for k in sorted(appeared)]}


def main() -> None:
    """全第二巡保存結果完成後に独立会計・対照範囲・影・J数量を照合する。

    引数: なし。返り値: None。研究器は実行しない。
    """
    files = sorted((BASE / "results_round2").glob("*_D07.json"))
    assert len(files) == 52, ("結果未完成", len(files))
    grouped, rejections, quantities, hashes = defaultdict(list), [], [], []
    comparisons = defaultdict(list)
    pairs = [("D07", "S00"), ("S00", "S01"), ("D07", "S04"), ("S04", "S02"), ("G02", "S03"),
             ("D07", "J01"), ("D07", "J02"), ("J01", "J02"), ("J02", "J03"),
             ("D07", "S01"), ("D07", "S02"), ("D07", "S03"), ("D07", "J03")]
    case_dir = AUDIT / "cases_round2"
    case_dir.mkdir(exist_ok=True)
    for path in files:
        raw = path.read_bytes()
        saved = json.loads(raw)
        controls = {c["config"]["id"]: c for c in json.loads((BASE / "results_go" / path.name).read_bytes())["cases"]}
        assert len(saved["cases"]) == 8
        hashes.append({"file": path.name, "sha256": hashlib.sha256(raw).hexdigest()})
        own_cases = {}
        for case in saved["cases"]:
            method = case["config"]["id"]
            row = reconcile_case(case)
            own_cases[method] = row
            (case_dir / f"{row['session']}_{method}.json").write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
            grouped[method].append({k: v for k, v in row.items() if k not in ("parents", "lots")})
            baseline = controls["D07"]
            if method in ("S00", "S01", "S04", "S02"):
                assert semantic_events(case, {"core", "addon"}) == semantic_events(baseline, {"core", "addon"}), (row["session"], method, "対象外担当差")
            if method == "S03":
                assert semantic_events(case, {"core", "addon"}) == semantic_events(controls["G02"], {"core", "addon"}), (row["session"], method, "G02対象外差")
            if method in ("S01", "S02", "S03"):
                rejections.extend({"session": row["session"], "id": method, **r} for r in verify_reference(case, baseline))
            if method.startswith("J"):
                quantities.extend(verify_j_quantity(case))
                owners = {"core", "addon", "episode"} if row["kind"] == "Night" else ({"addon", "episode"} if method != "J03" else {"episode"})
                assert semantic_events(case, owners) == semantic_events(baseline, owners), (row["session"], method, "J対象外差")
                if method == "J03" and row["kind"] == "Day":
                    assert semantic_events(case, {"addon"}) == semantic_events(controls["A01"], {"addon"}), (row["session"], "J03追撃差")
        for original, candidate in pairs:
            old = own_cases.get(original)
            if old is None:
                old = json.loads((AUDIT / "cases" / f"{saved['scene']['session']}_{original}.json").read_bytes())
            comparisons[f"{original}→{candidate}"].append(compare_parents(old, own_cases[candidate]))
    result = {"金融再生": False, "条件場数": sum(map(len, grouped.values())), "入力指紋": hashes,
              "影拒否照合件数": len(rejections), "J親初回数量照合件数": len(quantities), "methods": []}
    for method, rows in grouped.items():
        complete = [r for r in rows if not r["partial"]]
        assert len(complete) == 51 and len(rows) == 52
        result["methods"].append({"id": method, "summary": summarize(complete),
                                  "day": summarize([r for r in complete if r["kind"] == "Day"]),
                                  "night": summarize([r for r in complete if r["kind"] == "Night"]), "rows": rows})
    report_path = BASE / "report154_round2.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8-sig"))
        by_id = {m["id"]: m for m in result["methods"]}
        for m in report["methods"]:
            if m["id"] not in by_id:
                continue
            own = {r["session"]: r for r in by_id[m["id"]]["rows"]}
            for row in m["rows"]:
                for key in ("profit", "loss", "net", "unrealized"):
                    if key in row:
                        same(own[row["session"]][key], row[key], f"報告照合/{m['id']}/{row['session']}/{key}")
        result["報告書照合"] = True
    diff_summary = {}
    for pair, rows in comparisons.items():
        full = [r for r in rows if not r["partial"]]
        positive = sorted((r["difference"] for r in full if r["difference"] > 0), reverse=True)
        diff_summary[pair] = {k: sum(r[k] for r in full) for k in ("difference", "initial_quantity_effect", "first_exit_effect", "additional_or_reentry_effect", "vanished_count", "vanished_net", "appeared_count", "appeared_net")}
        diff_summary[pair].update({"exclude_top3_improvements": sum(r["difference"] for r in full) - sum(positive[:3]),
                                  "new_red": [r["session"] for r in full if r["new_net"] < 0 <= r["old_net"]],
                                  "rescued": [r["session"] for r in full if r["old_net"] < 0 <= r["new_net"]]})
    for name, value in (("独立結果会計154r2.json", result), ("影拒否とJ初回数量の照合154r2.json", {"rejections": rejections, "quantities": quantities}),
                        ("親対応の独立差分154r2.json", {"summary": diff_summary, "rows": comparisons})):
        (AUDIT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("入力指紋", "methods")}, ensure_ascii=False))
    print(json.dumps([{ "id": m["id"], **m["summary"]} for m in result["methods"]], ensure_ascii=False))


if __name__ == "__main__":
    main()
