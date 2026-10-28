"""金融完了後に保存約定と全正常原板だけを再会計する独立監査。"""
from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import traceback

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
WORK = ROOT / "work/research164"
HERE = WORK / "audit"
sys.path.insert(0, str(ROOT / "work/allocation_157/audit"))
sys.path.insert(0, str(ROOT / "work/allocation_157"))
from raw_result157 import close, read_market, normal_mask, raw_risk, reserved_cap
from ledger_analysis157 import reconcile


def read(path: Path):
    """保存JSONを読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def record(path: Path) -> dict:
    """内容指紋を保存する。

    引数: path(Path)。返り値: dict。
    """
    with path.open("rb") as stream:
        return dict(path=path.relative_to(ROOT).as_posix(), sha256=hashlib.file_digest(stream, "sha256").hexdigest())


def save(path: Path, value) -> None:
    """監査専用成果を保存する。

    引数: path(Path)、value(dict)。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def normalized(value, prefix: str):
    """手法の所有ID接頭辞だけを共通化する。

    引数: value(JSON値)、prefix(str)。返り値: JSON値。
    """
    if isinstance(value, dict):
        return {k.replace(prefix, "基準"): normalized(v, prefix) for k, v in value.items()}
    if isinstance(value, list):
        return [normalized(v, prefix) for v in value]
    if isinstance(value, str):
        return value.replace(prefix, "基準")
    return value


def baseline_day(saved: dict) -> dict:
    """旧00157第二巡J02と日中00の保存経路を照合する。

    引数: saved(dict)。返り値: dict。追加完了Dayは旧途中時刻までの比較を別記する。
    """
    scene = saved["scene"]
    path = ROOT / "work/allocation_157/round2/results_go" / (scene["session"] + "_S01.json")
    assert path.exists()
    old_saved = read(path)
    old = next(c for c in old_saved["cases"] if c["config"]["id"] == "J02")
    now = next(c for c in saved["cases"] if c["config"]["id"] == "NK225_D164_00")
    partial = bool(old_saved["scene"].get("partial"))
    cutoff = old_saved["scene"].get("cutoff", 0)
    counts = {}
    for ledger_name in ("actual", "canonical"):
        a = old[ledger_name]
        b = now[ledger_name]
        old_events = a["Events"] or []
        new_events = b["Events"] or []
        if partial:
            new_events = [e for e in new_events if e["FillTime"] < cutoff]
        left = normalized(old_events, "J02")
        right = normalized(new_events, "NK225_D164_00")
        assert left == right, (scene["session"], ledger_name, "旧J02の全イベント不一致")
        if not partial:
            for key in ("Lots", "Parents", "Risk", "Realized", "Last"):
                assert normalized(a[key], "J02") == normalized(b[key], "NK225_D164_00"), (scene["session"], ledger_name, key)
        counts[ledger_name] = len(left)
    return dict(passed=True, prior=record(path), prior_partial=partial, prefix_cutoff=cutoff if partial else None, event_counts=counts)


def baseline_night(saved: dict) -> dict:
    """P/U別Sourceの全約定・Targets十倍と独立基準台帳を照合する。

    引数: saved(dict)。返り値: dict。
    """
    count = 0
    for source in saved["sources"]:
        phase = source["Phase"]
        scope = "PreUS" if phase == "前半" else "PostUS"
        current = next(c for c in saved["cases"] if c["config"]["scope"] == scope and c["config"].get("native"))
        actual = current["actual"]["Events"] or []
        old = source["Events"] or []
        assert len(actual) == len(old)
        for e, native in zip(actual, old):
            s, order = native["Signal"], e["Order"]
            assert order["ID"] == phase + "/" + s["id"]
            for key, value in (("Side", s["side"]), ("Quantity", s["quantity"] * 10), ("DecisionIndex", s["source_index"]), ("DecisionTime", s["time"])):
                close(order[key], value, "夜基準通知")
            for key in ("FillIndex", "FillTime", "Price", "Gross"):
                close(e[key], native[key], "夜基準約定")
            assert {x["ID"]: x["Quantity"] for x in order["Targets"] or []} == {phase + "/" + x["id"]: x["quantity"] * 10 for x in s.get("targets") or []}
            count += 1
        close(current["actual"]["Realized"], source["Gross"], "夜基準総確定")
    return dict(passed=True, native_events=count)


def overlap(ledgers: list[dict]) -> dict:
    """前後手法の実約定区間と共有上限を原行順で確認する。

    引数: ledgers(list[dict])はPとUの台帳。返り値: dict。
    """
    fills = defaultdict(list)
    orders = defaultdict(list)
    for group, ledger in enumerate(ledgers):
        for e in ledger["Events"] or []:
            fills[e["FillIndex"]].append((group, e))
            orders[e["Order"]["DecisionIndex"]].append((group, e["Order"]))
    held = [[0, 0], [0, 0]]
    reserved = [[0, 0], [0, 0]]
    max_long = max_short = 0
    overlap_rows = []
    for index in sorted(set(fills) | set(orders)):
        for group, e in fills[index]:
            o = e["Order"]
            side = 0 if o["Side"] == 1 else 1
            q = o["Quantity"]
            if o["Targets"]:
                held[group][1 - side] -= q
            else:
                reserved[group][side] -= q
                held[group][side] += q
            assert min(held[group] + reserved[group]) >= 0
            if sum(held[0]) and sum(held[1]):
                overlap_rows.append(index)
            max_long = max(max_long, sum(h[0] + r[0] for h, r in zip(held, reserved)))
            max_short = max(max_short, sum(h[1] + r[1] for h, r in zip(held, reserved)))
        for group, order in orders[index]:
            if not order["Targets"]:
                reserved[group][0 if order["Side"] == 1 else 1] += order["Quantity"]
            max_long = max(max_long, sum(h[0] + r[0] for h, r in zip(held, reserved)))
            max_short = max(max_short, sum(h[1] + r[1] for h, r in zip(held, reserved)))
    return dict(no_overlap=not overlap_rows, overlap_indices=sorted(set(overlap_rows)), max_long_reserved=max_long, max_short_reserved=max_short, shared_cap_ok=max(max_long, max_short) <= 100)


def night_features(raw: np.ndarray, good: np.ndarray, index: int) -> dict:
    """現在までの正常標本と過去端から夜の短期・ER・範囲を別式で求める。

    引数: raw/good(ndarray)、index(int)。返り値: dict。
    """
    at = raw[index, 0]
    result = dict(Mid=float(np.mean(raw[index, 2:4])), Spread=float(raw[index, 3] - raw[index, 2]))
    for span in (5, 15, 60, 120, 300):
        result["Known" + str(span)] = False
        p = int(np.searchsorted(raw[good, 0], at - span, side="right")) - 1
        if p < 0:
            continue
        old = int(good[p])
        assert old < index
        elapsed = at - raw[old, 0]
        if at - span - raw[old, 0] > (1 if span < 60 else 15):
            continue
        result["Known" + str(span)] = True
        mids = np.mean(raw[good[(good >= old) & (good <= index)], 2:4], axis=1)
        delta = float(mids[-1] - mids[0])
        result["Own" + str(span)] = delta * span / elapsed if span < 60 else delta
        if span < 60:
            result["Elapsed" + str(span)] = float(elapsed)
        if span in (15, 120):
            distance = float(np.sum(np.abs(np.diff(mids))))
            result["ER" + str(span)] = abs(delta) / distance if distance > 0 else 0.
            result["Path" + str(span)] = True
        if span == 60:
            result.update(High60=float(np.max(mids)), Low60=float(np.min(mids)))
        if span == 300:
            result["Range300"] = float(np.ptp(mids))
    return result


def night_risk_budget(raw: np.ndarray, good: np.ndarray, case: dict) -> int:
    """各新規直前の実玉と未約定新規から停止線危険を再構成する。

    引数: raw/good(ndarray)、case(dict)。返り値: intは確認注文数。
    """
    events = case["actual"]["Events"] or []
    traces = [t for t in case["trigger_trace"] or [] if t["Kind"] == "新規"]
    new_events = {e["Order"]["ID"]: e for e in events if not e["Order"]["Targets"]}
    assert set(new_events) == {t["OrderID"] for t in traces}
    radii = {t["OrderID"]: t["R"] for t in traces}
    accepted = set()
    for trace in traces:
        index = trace["Index"]
        remaining = {}
        for event in events:
            if event["FillIndex"] > index:
                break
            if not event["Order"]["Targets"]:
                remaining[event["HoldID"]] = [event, event["Order"]["Quantity"]]
            else:
                for target in event["Order"]["Targets"]:
                    remaining[target["ID"]][1] -= target["Quantity"]
        before = 0.
        for event, quantity in remaining.values():
            if quantity <= 0:
                continue
            order = event["Order"]
            radius = radii[order["ID"]]
            region = good[(good >= event["FillIndex"]) & (good <= index)]
            prices = raw[region, 2 if order["Side"] == 1 else 3]
            best = max(0., float(np.max(order["Side"] * (prices - event["Price"]))))
            active = best > 0 if case["config"]["protection"] == "正利益開始" else best >= radius
            floor = max(0., best - radius) if active else -radius
            before += max(0., -floor) * quantity * 10
        for order_id in accepted:
            event = new_events[order_id]
            if event["Order"]["DecisionIndex"] <= index < event["FillIndex"]:
                before += radii[order_id] * event["Order"]["Quantity"] * 10
        close(trace["RiskBefore"], before, "独立の未約定込み停止危険")
        after = before + trace["R"] * trace["Quantity"] * 10
        close(trace["RiskAfter"], after, "独立の採用後停止危険")
        assert after <= 50000 + 1e-6
        accepted.add(trace["OrderID"])
    return len(traces)


def scene_check(scene: dict) -> dict:
    """一場の全実台帳と原板時価を照合する。

    引数: scene(dict)。返り値: dict。戦略は実行しない。
    """
    stage = "train_validation" if scene["split"] in ("train", "validation") else "confirmation"
    path = WORK / "results" / stage / (scene["session"] + ".json")
    before = record(path)
    saved = read(path)
    raw, reference = read_market(scene, "NK225")
    good = np.flatnonzero(normal_mask(raw))
    rows, totals = [], Counter()
    base = baseline_day(saved) if scene["kind"] == "Day" else baseline_night(saved)
    for case in saved["cases"]:
        ledger = case["actual"]
        start = scene["start"] if scene["kind"] == "Day" else case["Start"]
        account = reconcile(ledger, start, ledger["LastTime"])
        assert not ledger["Pending"] and account["remaining_qty"] == 0
        risk = raw_risk(raw, ledger, start)
        cap = reserved_cap(ledger)
        if scene["kind"] == "Day":
            reconcile(case["canonical"], start, case["canonical"]["LastTime"])
            assert case["projection_max_difference"] == 0
        elif not case["config"].get("native"):
            totals["independent_risk_reservations"] += night_risk_budget(raw, good, case)
            for tr in case["trigger_trace"] or []:
                i = tr["Index"]
                assert int(i) == i and normal_mask(raw[i:i + 1])[0]
                close(tr["Time"], raw[i, 0], "夜判断時計")
                f = tr["Features"]
                if not f["FirstNormal"]:
                    continue
                expected = night_features(raw, good, i)
                for key, value in expected.items():
                    if isinstance(value, bool):
                        assert f[key] == value, (key, f[key], value)
                    else:
                        close(f[key], value, "夜観測特徴/" + key, 1e-7)
                if tr["Kind"] == "新規":
                    assert tr["RiskAfter"] <= 50000 + 1e-6
                    expected_r = np.ceil(max(40 if case["config"]["scope"] == "PreUS" else 60, 2 * expected["Spread"], expected["Range300"] / 4) / 10) * 10
                    close(tr["R"], expected_r, "新規判断固定R")
                totals["night_feature_decisions"] += 1
        totals.update(cases=1, events=len(ledger["Events"] or []), lots=len(ledger["Lots"]), raw_marks=len(good))
        rows.append(dict(id=case["config"]["id"], profit=account["allocation_profit"], loss=account["allocation_loss"], net=account["net"], risk=risk, peak_equity=ledger["Risk"]["Peak"], capacity=cap, quantities=account["quantities"], new_orders=account["entries"]))
    overlaps = []
    if scene["kind"] == "Night":
        for pre in [c for c in saved["cases"] if c["config"]["scope"] == "PreUS"]:
            for post in [c for c in saved["cases"] if c["config"]["scope"] == "PostUS"]:
                overlaps.append(dict(pre=pre["config"]["id"], post=post["config"]["id"], **overlap([pre["actual"], post["actual"]])))
    assert record(path) == before
    answer = dict(passed=True, session=scene["session"], source=before, raw=reference, baseline=base, rows=rows, totals=dict(totals), schedule_overlap=overlaps,
        direction="上昇" if raw[-1, 1] > raw[0, 1] else "下落" if raw[-1, 1] < raw[0, 1] else "同値",
        direction_source=dict(first_last=float(raw[0, 1]), final_last=float(raw[-1, 1]), final_clock=float(raw[-1, 0]), formal_close=False))
    save(HERE / "結果監査" / (scene["session"] + ".json"), answer)
    return answer


def main() -> None:
    """全金融完了と固定源一致を条件に保存会計を監査する。

    引数: なし。返り値: None。
    """
    proof = dict(passed=False, new_financial_replays=0, started_at=datetime.now().astimezone().isoformat())
    try:
        complete = read(WORK / "再生全完了164.json")
        assert complete["completed"] and complete["returncode"] == 0 and complete["cases"] == 540
        receipt = read(WORK / "登録受領164.json")
        for item in receipt["sources"]:
            assert record(ROOT / item["path"])["sha256"] == item["sha256"]
        scenes = read(WORK / "inputs164.json")["sessions"]
        totals, results = Counter(), []
        with ProcessPoolExecutor(max_workers=4) as pool:
            jobs = {pool.submit(scene_check, scene): scene["session"] for scene in scenes}
            for job in as_completed(jobs):
                result = job.result()
                totals.update(result["totals"])
                results.append(record(HERE / "結果監査" / (result["session"] + ".json")))
                print(json.dumps(dict(session=result["session"], completed=len(results)), ensure_ascii=False), flush=True)
        assert totals["cases"] == 540 and len(results) == 54
        for item in receipt["sources"]:
            assert record(ROOT / item["path"])["sha256"] == item["sha256"]
        proof.update(passed=True, totals=dict(totals), results=results, sources_unchanged=True, complete=record(WORK / "再生全完了164.json"), finished_at=datetime.now().astimezone().isoformat())
    except Exception:
        proof["error"] = traceback.format_exc()
        save(HERE / "audit164.json", proof)
        raise
    save(HERE / "audit164.json", proof)


if __name__ == "__main__":
    main()
