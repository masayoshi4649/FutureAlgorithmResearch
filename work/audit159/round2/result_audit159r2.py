"""00159第二巡の保存約定・全原板時価・超過返済を独立照合する。新しい売買再生は行わない。"""
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import datetime as dt
import json
import math
from pathlib import Path
import traceback

import numpy as np

from base_audit159 import read, save, reference, support_check, holding_check, exact_and_phases
from raw_result157 import close, read_market, support_arrays, raw_risk, reserved_cap, normal_mask
from raw_result1572 import support_at1572

ROOT = Path(__file__).resolve().parents[3]
WORK = ROOT / "work/audit159/round2"
SOURCE = ROOT / "work/night159/round2"
OUTPUT = WORK / "金融結果の独立監査159r2.json"


def normalized_signals(saved: dict) -> dict:
    """元通知を時間帯と対象所有玉から親へ結び直す。

    引数: saved(dict)。返り値: dict[int,list[dict]]は判断原行ごとの元通知。
    """
    rows = defaultdict(list)
    for source in saved["sources"]:
        phase = source["Phase"]
        for original in source["Signals"] or []:
            sig = dict(original)
            owner, campaign = sig["owner"], sig["campaign"]
            if sig["action"] == "close":
                keys = {(source["Lots"][t["id"]]["Owner"], source["Lots"][t["id"]]["Campaign"]) for t in sig["targets"]}
                assert len(keys) == 1
                owner, campaign = next(iter(keys))
            sig["parent"] = f"{phase}/{owner}/{campaign}"
            sig["id"] = phase + "/" + sig["id"]
            sig["targets"] = [{"id": phase + "/" + t["id"], "quantity": t["quantity"]*10} for t in sig.get("targets") or []]
            sig["quantity"] *= 10
            rows[sig["source_index"]].append(sig)
    return rows


def support_value(own: dict, peer: dict, cache: dict, index: int, side: int) -> dict:
    """原行の支持を再計算し、同じ照合中だけ再利用する。

    引数: own/peer/cache(dict)、index/side(int)。返り値: dictは当時支持。
    """
    key = (index, side)
    if key not in cache:
        cache[key] = support_at1572(own, peer, index, side)
    return cache[key]


def opposed_five(raw: np.ndarray, own: dict, peer: dict, cache: dict, index: int, side: int, created: int) -> dict:
    """逆支持の連続五秒を当時以前の原行だけから確認する。

    引数: raw(ndarray)、own/peer/cache(dict)、index/side/created(int)。返り値: dictは確認開始行。
    """
    at = raw[index, 0]
    later = index
    for i in range(index, created, -1):
        assert np.isfinite(raw[i, 2:4]).all() and 0 < raw[i, 2] < raw[i, 3], ("逆支持中の不正板", i)
        assert raw[later, 0]-raw[i, 0] <= 5, ("逆支持の観測空白", i, later)
        s = support_value(own, peer, cache, i, side)
        assert s["Known"] and s["Opp"] >= .5 and side*s["Own15"] < 0 and side*s["Own5"] <= 0, ("逆支持未継続", i, s)
        if at-raw[i, 0] >= 5:
            return {"from_index": i, "to_index": index, "elapsed": float(at-raw[i, 0])}
        later = i
    raise AssertionError(("親発生後の逆支持五秒がない", created, index))


def lot_and_risk_check(raw: np.ndarray, ledger: dict, risk: dict, start: float) -> dict:
    """所有別損益・順逆行極値と、全正常板の最低含みを独立に確認する。

    引数: raw(ndarray)、ledger/risk(dict)、start(float)。返り値: dictは照合件数と追加極値。
    """
    valid = normal_mask(raw)
    active, quantities, gross, entries = {}, {}, defaultdict(float), {}
    realized = minimum_realized = minimum_unrealized = 0.0
    piece_count = 0
    for event in ledger["Events"] or []:
        o, i = event["Order"], event["FillIndex"]
        if not o.get("Targets"):
            entries[event["HoldID"]] = event
            quantities[event["HoldID"]] = o["Quantity"]
            active[event["HoldID"]] = o["Quantity"]
        else:
            assert len(event["Pieces"]) == len(o["Targets"])
            for piece, target in zip(event["Pieces"], o["Targets"]):
                ident = target["ID"]
                old = entries[ident]
                first = old["FillIndex"]
                side = old["Order"]["Side"]
                prices = raw[first:i+1, 2 if side == 1 else 3][valid[first:i+1]]
                gains = side*(prices-old["Price"])
                best, worst = max(0.0, float(gains.max())), min(0.0, float(gains.min()))
                assert piece["ID"] == ident and piece["Quantity"] == target["Quantity"]
                close(piece["Best"], best, "返済配賦の最高順行")
                close(piece["Worst"], worst, "返済配賦の最大逆行")
                close(piece["Entry"], old["Price"], "配賦建値")
                close(piece["Exit"], event["Price"], "配賦返済値")
                expected = side*target["Quantity"]*(event["Price"]-old["Price"])*10
                close(expected, piece["Gross"], "玉の配賦損益")
                gross[ident] += expected
                quantities[ident] -= target["Quantity"]
                active[ident] -= target["Quantity"]
                piece_count += 1
                if active[ident] == 0:
                    lot = ledger["Lots"][ident]
                    close(lot["Best"], best, "玉最終順行")
                    close(lot["Worst"], worst, "玉最終逆行")
                    for field, target_value in (("BestAt", best), ("WorstAt", worst)):
                        if target_value == 0:
                            close(lot[field], old["FillTime"], "未更新極値の初回約定時計")
                        else:
                            choices = np.flatnonzero(valid[first:i+1])
                            local = int(np.argmax(gains) if field == "BestAt" else np.argmin(gains))
                            close(lot[field], raw[first+choices[local], 0], field)
        realized += event["Gross"]
        minimum_realized = min(minimum_realized, realized)
        unrealized = sum(entries[k]["Order"]["Side"]*q*(raw[i, 2 if entries[k]["Order"]["Side"] == 1 else 3]-entries[k]["Price"])*10 for k, q in active.items() if q)
        minimum_unrealized = min(minimum_unrealized, unrealized)
    for ident, lot in ledger["Lots"].items():
        assert quantities[ident] == lot["Remaining"] == 0
        close(gross[ident], lot["Gross"], "全玉最終損益")
    # ----------------------------------------
    # 全正常板の前後と同板内の各約定後を含め、確定と含みを別々に検算する。
    path = risk.pop("_path")
    after, indices, after_equity = path["after"], path["indices"], path["equity"]
    before = np.vstack((np.zeros((1, 4)), after[:-1]))
    before_equity = (before[:, 0]+before[:, 1]*raw[indices, 2]-before[:, 2]*raw[indices, 3])*10
    minimum_unrealized = min(minimum_unrealized, float(np.min(before_equity-before[:, 3])), float(np.min(after_equity-after[:, 3])))
    close(minimum_realized, ledger["Risk"]["MinimumRealized"], "逐次最小確定")
    close(minimum_unrealized, ledger["Risk"]["MinimumUnrealized"], "全原板最小含み")
    for name, value in (("MinimumAt", risk["min_equity"]), ("MinimumRealizedAt", minimum_realized), ("MinimumUnrealizedAt", minimum_unrealized), ("PeakAt", ledger["Risk"]["Peak"]), ("DDFrom", None), ("DDTo", None)):
        mark = ledger["Risk"][name]
        i = mark["Index"]
        if i < 0:
            assert i == -1 and mark["Time"] == start and mark["Equity"] == 0
            continue
        assert valid[i]
        close(mark["Time"], raw[i, 0], "極値時計")
        close(mark["Bid"], raw[i, 2], "極値Bid")
        close(mark["Ask"], raw[i, 3], "極値Ask")
        unrealized = sum(ledger["Lots"][k]["Side"]*q*(raw[i, 2 if ledger["Lots"][k]["Side"] == 1 else 3]-ledger["Lots"][k]["Entry"])*10 for k, q in (mark["Lots"] or {}).items())
        close(unrealized, mark["Unrealized"], "極値所有含み")
        close(mark["Equity"], mark["Realized"]+unrealized, "極値総時価")
        if value is not None:
            field = "Realized" if name == "MinimumRealizedAt" else "Unrealized" if name == "MinimumUnrealizedAt" else "Equity"
            close(mark[field], value, "極値断面値")
    close(ledger["Risk"]["DDFrom"]["Equity"]-ledger["Risk"]["DDTo"]["Equity"], risk["max_drawdown"], "最大DD断面差")
    risk["min_realized"] = minimum_realized
    risk["min_unrealized"] = minimum_unrealized
    return {"lots": len(entries), "pieces": piece_count}


def quantity_check(saved: dict, case: dict, raw: np.ndarray, own: dict, peer: dict, cache: dict) -> dict:
    """保存通知と既存予約だけを読み、元比例返済と超過返済の予算を確認する。

    引数: saved/case/own/peer/cache(dict)、raw(ndarray)。返り値: dictは検査件数と超過根拠。
    """
    source_rows = normalized_signals(saved)
    events = case["actual"]["Events"] or []
    decisions, fills, excess_rows, requests = (defaultdict(list) for _ in range(4))
    lots = case["actual"]["Lots"]
    for event in events:
        decisions[event["Order"]["DecisionIndex"]].append(event["Order"])
        fills[event["FillIndex"]].append(event)
    for item in case.get("excess_exits") or []:
        excess_rows[item["Index"]].append(item)
    for item in case.get("requests") or []:
        requests[item["Index"]].append(item)
    held, pending, source_qty, source_holds = {}, {}, defaultdict(int), defaultdict(int)
    parent_creation, initial_source, initial_factor = {}, {}, {}
    checked, details = defaultdict(int), []

    def reserved(ident: str) -> int:
        """検算中の予約返済数を返す。

        引数: ident(str)。返り値: int。
        """
        return sum(t["Quantity"] for order in pending.values() for t in order.get("Targets") or [] if t["ID"] == ident)

    for index in sorted(set(source_rows)|set(decisions)|set(fills)|set(excess_rows)|set(requests)):
        for event in fills[index]:
            order = event["Order"]
            assert pending.pop(order["ID"]) == order
            if order.get("Targets"):
                for target in order["Targets"]:
                    held[target["ID"]] -= target["Quantity"]
                    assert held[target["ID"]] >= 0
            else:
                assert event["HoldID"] not in held
                held[event["HoldID"]] = order["Quantity"]
        orders = decisions[index]
        source_orders = [o for o in orders if o["Reason"] in ("source_partial", "source_end")]
        expected_source_orders = []
        expected_reservations = defaultdict(int)
        for sig in source_rows[index]:
            if sig["action"] != "close":
                continue
            key = sig["parent"]
            before = source_qty[key]
            source_qty[key] -= sig["quantity"]
            assert source_qty[key] >= 0
            # 前半の元数量厳密写像はN00の全イベント一致で別検査し、後半の比例返済と混ぜない。
            candidates = sorted((ident for ident, q in held.items() if q and lots[ident]["Parent"] == key and key.startswith("後半/")), key=lambda ident:(lots[ident]["EntryIndex"], list(held).index(ident)))
            for ident in candidates:
                available = held[ident]-reserved(ident)-expected_reservations[ident]
                if source_qty[key] == 0:
                    q = available
                    reason = "source_end"
                else:
                    source_id = lots[ident]["SourceID"]
                    ratio = sig["quantity"]/max(1, before)
                    if source_id:
                        ratio = next((t["quantity"]/max(1, source_holds[t["id"]]) for t in sig["targets"] if t["id"] == source_id+"-玉"), 0)
                    q = min(available, int(math.floor(held[ident]*min(1, ratio)+1e-10)))
                    reason = "source_partial"
                if q > 0:
                    expected_source_orders.append((key, ident, q, reason))
                    expected_reservations[ident] += q
            for target in sig["targets"]:
                source_holds[target["id"]] -= target["quantity"]
                assert source_holds[target["id"]] >= 0
        got_source_orders = [(o["Parent"], t["ID"], t["Quantity"], o["Reason"]) for o in source_orders for t in o["Targets"]]
        assert got_source_orders == expected_source_orders, ("元部分/全返済写像", case["config"]["id"], index, got_source_orders, expected_source_orders)
        checked["source_close_orders"] += len(source_orders)
        # ----------------------------------------
        # 元退出・境界予約を先に控除し、その後に超過の新しい玉への配賦を照合する。
        extra_orders = [o for o in orders if o["Reason"].startswith("後半超過分")]
        for order in orders:
            if order.get("Targets") and order not in extra_orders:
                pending[order["ID"]] = order
        by_parent = defaultdict(list)
        for item in excess_rows[index]:
            by_parent[item["Parent"]].append(item)
        assert len(extra_orders) == len(excess_rows[index]), ("超過注文と記録数", index)
        for key, items in by_parent.items():
            free_by_id = {ident: q-reserved(ident) for ident, q in held.items() if lots[ident]["Parent"] == key and q-reserved(ident) > 0}
            free = sum(free_by_id.values())
            excess = max(0, free-source_qty[key])
            left, allocated = excess, {}
            for ident in sorted(free_by_id, key=lambda ident:(lots[ident]["EntryIndex"], ident), reverse=True):
                q = min(left, free_by_id[ident])
                if q:
                    allocated[ident] = q
                    left -= q
            total = 0
            for item in items:
                ident = item["LotID"]
                lot = lots[ident]
                assert key.startswith("後半/") and item["SourceRemaining"] == source_qty[key]
                assert item["FreeRemaining"] == free and item["Excess"] == excess
                assert item["Closed"] == allocated[ident] > 0
                matching = [o for o in extra_orders if o["Parent"] == key and o["Targets"] == [{"ID": ident, "Quantity": item["Closed"]}] and o["Reason"] == item["Reason"]]
                assert len(matching) == 1
                close(item["Time"], raw[index, 0], "超過判断時計")
                support_check(item["Support"], index, lot["Side"], own, peer, cache)
                span = raw[lot["EntryIndex"]:index+1]
                good = normal_mask(span)
                mark = raw[index, 2 if lot["Side"] == 1 else 3]
                peak = max(0.0, float((lot["Side"]*(span[good, 2 if lot["Side"] == 1 else 3]-lot["Entry"])).max()))
                gain = lot["Side"]*(mark-lot["Entry"])
                close(item["Gain"], gain, "超過返済判断損益幅")
                close(item["Peak"], peak, "超過玉既知最高幅")
                floor = lot["Entry"]+lot["Side"]*max(0, peak-case["config"]["protection_trail"])
                if item["Reason"] == "後半超過分の固定利益追尾":
                    assert peak >= case["config"]["protection_start"]
                    close(item["Floor"], floor, "超過利益床")
                    assert lot["Side"]*(mark-floor) <= 0
                else:
                    assert case["config"].get("excess_loss_guard") and gain <= -80
                    assert peak < case["config"]["protection_start"] or lot["Side"]*(mark-floor) > 0
                    opposed_five(raw, own, peer, cache, index, lot["Side"], parent_creation[key])
                total += item["Closed"]
                pending[matching[0]["ID"]] = matching[0]
                checked["excess_orders"] += 1
                details.append({"index": index, "time": item["Time"], "parent": key, "lot": ident, "source_remaining": source_qty[key], "free_after_prior_close": free, "excess": excess, "closed": item["Closed"], "reason": item["Reason"], "gain": gain, "peak": peak})
            assert total <= excess and free-total >= source_qty[key]
        # ----------------------------------------
        # 初回だけ未知時の基準量を使い、追加は初回確定係数をそのまま写す。
        for sig in source_rows[index]:
            if sig["action"] != "new":
                continue
            key = sig["parent"]
            initial = key not in initial_source
            source_qty[key] += sig["quantity"]
            source_holds[sig["id"]+"-玉"] += sig["quantity"]
            if initial:
                parent_creation[key] = index
                initial_source[key] = sig["quantity"]
            phase = key.split("/", 1)[0]
            found = [r for r in requests[index] if r["SourceID"] == sig["id"]]
            if phase == "前半":
                assert not found
                continue
            assert len(found) == 1
            req = found[0]
            s = req["Support"]
            assert req["Initial"] == initial and req["SourceQuantity"] == sig["quantity"]
            support_check(s, index, sig["side"], own, peer, cache)
            desired = (int(math.floor(10+90*s["M"]*s["T"]+1e-10)) if s["Known"] else sig["quantity"]) if initial else int(math.floor(sig["quantity"]*initial_factor[key]+1e-10))
            assert req["Requested"] == desired and 0 <= req["Accepted"] <= desired, ("初回/追加量", key, req, desired)
            if initial:
                initial_factor[key] = req["Accepted"]/sig["quantity"]
            actual_new = [o for o in orders if not o.get("Targets") and o["SourceID"] == sig["id"]]
            assert sum(o["Quantity"] for o in actual_new) == req["Accepted"]
            checked["source_new_requests"] += 1
        for order in orders:
            if not order.get("Targets"):
                pending[order["ID"]] = order
    assert not pending and all(q == 0 for q in held.values())
    assert all(q == 0 for q in source_qty.values())
    return {"counts": dict(checked), "excess_evidence": details}


def audit_scene(scene: dict) -> dict:
    """一夜の四条件と元対照を全原板に対して独立検算する。

    引数: scene(dict)。返り値: dictは保存証跡と件数。
    """
    path = SOURCE / "results_go" / (scene["session"]+".json")
    old_path = ROOT / "work/night159/results_go" / path.name
    before, old_before = reference(path), reference(old_path)
    saved, old = read(path), read(old_path)
    assert [c["config"]["id"] for c in saved["cases"]] == ["R00", "R01", "R02", "R03"]
    assert saved["sources"] == old["sources"], "元Source不一致"
    assert saved["transitions"] == old["transitions"] and saved["counts"] == old["counts"]
    base = saved["control"]
    assert base == next(c for c in old["cases"] if c["config"]["id"] == "N00"), "元N00全状態不一致"
    source = exact_and_phases({**saved, "cases": [base]})
    raw, raw_ref = read_market(scene, "NK225")
    peer_raw, peer_ref = read_market(scene, "TOPIX")
    own, peer, cache = support_arrays(raw), support_arrays(peer_raw), {}
    source_supports = 0
    for src in saved["sources"]:
        for initial in src["Initials"] or []:
            support_check(initial["Support"], initial["Index"], initial["Side"], own, peer, cache)
            source_supports += 1
    rows = []
    for case in [base]+saved["cases"]:
        assert case["actual"] == case["canonical"], "H形式の判断台帳と実台帳不一致"
        risk = raw_risk(raw, case["actual"], scene["start"], include_path=True)
        lot_checks = lot_and_risk_check(raw, case["actual"], risk, scene["start"])
        assert risk["final_long"] == risk["final_short"] == 0 and not case["actual"]["Pending"]
        caps = reserved_cap(case["actual"])
        holding = holding_check(raw, case, scene["start"])
        quantity = None
        if case["config"]["id"] != "N00":
            assert [e for e in case["actual"]["Events"] or [] if e["Order"]["Owner"].startswith("前半/")] == [e for e in base["actual"]["Events"] or [] if e["Order"]["Owner"].startswith("前半/")], "前半完全維持"
            quantity = quantity_check(saved, case, raw, own, peer, cache)
        rows.append({"id": case["config"]["id"], "risk": risk, "caps": caps, "holding": holding, "lots": lot_checks, "quantity": quantity})
    assert before == reference(path) and old_before == reference(old_path)
    proof = {"passed": True, "session": scene["session"], "source": source, "source_initial_supports": source_supports, "old_source_and_n00_equal": True, "input_results": [before, old_before], "raw": [raw_ref, peer_ref], "rows": rows}
    save(WORK / "cases" / path.name, proof)
    return proof


def main() -> None:
    """完了受領後の保存百三十条件場だけを監査し、証跡を保存する。

    引数: なし。返り値: None。金融再生器は呼び出さない。
    """
    proof = {"passed": False, "new_financial_replays": 0, "started_at": dt.datetime.now().astimezone().isoformat()}
    try:
        execution = ROOT / "work/research159/round2/金融実行159r2.json"
        done = read(execution)
        assert done["exit_code"] == 0 and done["sources_unchanged"] is True
        assert len(done["output_files"]) == 26
        manifest = SOURCE / "inputs159r2.json"
        manifest_before = reference(manifest)
        scenes = read(manifest)["sessions"]
        assert len(scenes) == 26 and all(s["kind"] == "Night" for s in scenes)
        evidence = []
        errors = []
        with ProcessPoolExecutor(max_workers=4) as pool:
            jobs = {pool.submit(audit_scene, scene): scene["session"] for scene in scenes}
            for job in as_completed(jobs):
                try:
                    row = job.result()
                except Exception as error:
                    errors.append({"session": jobs[job], "error": repr(error), "traceback": traceback.format_exc()})
                    print(json.dumps({"session": jobs[job], "passed": False, "error": repr(error)}, ensure_ascii=False), flush=True)
                    continue
                evidence.append(row)
                print(json.dumps({"session": row["session"], "passed": True, "cases": 5}, ensure_ascii=False), flush=True)
        if errors:
            proof["scene_errors"] = errors
            raise AssertionError(f"保存監査で{len(errors)}場に不一致")
        assert manifest_before == reference(manifest)
        totals = defaultdict(int)
        for scene in evidence:
            totals["source_initial_supports"] += scene["source_initial_supports"]
            totals["source_events"] += scene["source"]["source_events"]
            for row in scene["rows"]:
                totals["cases"] += 1
                totals["events"] += row["risk"]["event_checks"]
                totals["normal_marks"] += row["risk"]["normal_rows"]
                totals["lots"] += row["lots"]["lots"]
                totals["pieces"] += row["lots"]["pieces"]
                if row["quantity"]:
                    for key, value in row["quantity"]["counts"].items():
                        totals[key] += value
        assert totals["cases"] == 130
        files = [reference(p) for p in sorted(WORK.glob("*.py"))]
        proof.update(passed=True, totals=dict(totals), new_candidate_cases=104, reused_control_cases=26, execution=reference(execution), manifest=manifest_before, audit_sources=files, scenes=[{"session": x["session"], "input_results": x["input_results"]} for x in sorted(evidence, key=lambda x:x["session"])], finished_at=dt.datetime.now().astimezone().isoformat())
        save(OUTPUT, proof)
    except Exception as error:
        proof.update(error=repr(error), traceback=traceback.format_exc(), finished_at=dt.datetime.now().astimezone().isoformat())
        save(OUTPUT, proof)
        raise


if __name__ == "__main__":
    main()
