"""全完了許可後に保存約定と原板だけから会計・全玉時価を独立再構成する。"""
from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(ROOT/"work/entry161/audit"))
from audit_results161 import raw_market, normal


def read(path: Path) -> dict:
    """保存されたJSONだけを読む。

    引数: path(Path)。返り値: dict。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    """読み取り資料の指紋を返す。

    引数: path(Path)。返り値: str。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def equal(actual: float, expected: float, context: str) -> None:
    """金額又は数量の一致を小さな丸め差だけ許して確認する。

    引数: actual/expected(float)、context(str)。返り値: None。
    """
    assert np.isclose(actual, expected, rtol=0, atol=1e-7), (context, actual, expected)


def case_account(scene: dict, raw: np.ndarray, good: np.ndarray, case: dict) -> dict:
    """全約定の現金・保有量と全正常原行の清算時価を別算式で確認する。

    引数: scene/case(dict)、raw/good(ndarray)。返り値: dictは会計と検算件数。
    """
    n, multiplier = len(raw), 100
    changes = np.zeros((n, 3), dtype=float)
    lots, parent_pl = {}, defaultdict(float)
    live, cover_live, main_initial = {1: 0, -1: 0}, defaultdict(int), {}
    maxima = {k: 0 for k in ("held_buy", "held_sell", "occupied_buy", "occupied_sell", "gross_held", "net_abs")}
    used, replaced = set(), set()
    closed_reasons = Counter()
    proxy_fills = 0
    real = 0.
    last_fill = -1
    last_normal = int(good[-1])
    decisions = {order["id"]: order for order in case["decisions"]}
    for event in case["events"]:
        order = event["order"]
        identifier = order["id"]
        assert identifier in decisions and decisions[identifier] == order
        assert identifier not in used
        used.add(identifier)
        quantity, side = order["quantity"], order["side"]
        assert type(quantity) is int and 0 < quantity <= 10 and side in (-1, 1)
        if event.get("proxy"):
            assert order["action"] == "close" and order["reason"] == "terminal_proxy"
            assert event["fill_index"] is None and event["fill_time"] == scene["end"]
            i = event["quote_index"]
            assert i == last_normal
            equal(event["quote_time"], raw[i, 0], "代理価格時計")
            equal(event["quote_age"], scene["end"]-raw[i, 0], "代理鮮度")
            assert 0 <= event["quote_age"] <= 360
            proxy_fills += 1
            if event.get("replaced_pending_close"):
                old = decisions[event["replaced_pending_close"]]
                assert old["action"] == "close" and old["target"] == order["target"]
                replaced.add(old["id"])
        else:
            i = event["fill_index"]
            assert type(i) is int and i >= last_fill
            last_fill = i
            j = np.searchsorted(good, order["decision_index"], side="right")
            assert j < len(good) and i == good[j], (case["id"], "次正常行", identifier)
            equal(event["fill_time"], raw[i, 0], "実約定時計")
            equal(order["decision_time"], raw[order["decision_index"], 0], "判断時計")
        price = raw[i, 3 if side == 1 else 2]
        equal(event["price"], price, "売買気配")
        if order["action"] == "new":
            assert not event.get("proxy")
            assert identifier not in lots
            lots[identifier] = {"parent": order["parent"], "role": order["role"], "side": side,
                                "quantity": quantity, "remaining": quantity, "price": price,
                                "entry_index": i, "exit_index": None, "realized": 0.}
            live[side] += quantity
            if order["role"] == "main":
                assert order["parent"] not in main_initial
                main_initial[order["parent"]] = quantity
            else:
                assert order["role"] == "cover"
                cover_live[order["parent"]] += quantity
                assert cover_live[order["parent"]] <= main_initial[order["parent"]]
            equal(event["gross"], 0, "新規実現")
        else:
            assert order["action"] == "close"
            lot = lots[order["target"]]
            assert lot["parent"] == order["parent"] and lot["role"] == order["role"]
            assert side == -lot["side"] and 0 < quantity <= lot["remaining"]
            gross = lot["side"]*(price-lot["price"])*quantity*multiplier
            equal(event["gross"], gross, "返済損益")
            lot["remaining"] -= quantity
            lot["realized"] += gross
            lot["exit_index"] = i
            parent_pl[lot["parent"]] += gross
            real += gross
            live[lot["side"]] -= quantity
            if lot["role"] == "cover":
                cover_live[lot["parent"]] -= quantity
            closed_reasons[order["reason"]] += 1
        for direction in (-1, 1):
            assert 0 <= live[direction] <= 10
        maxima["held_buy"] = max(maxima["held_buy"], live[1])
        maxima["held_sell"] = max(maxima["held_sell"], live[-1])
        maxima["gross_held"] = max(maxima["gross_held"], live[1]+live[-1])
        maxima["net_abs"] = max(maxima["net_abs"], abs(live[1]-live[-1]))
        if not event.get("proxy"):
            changes[i, 0] -= side*price*quantity*multiplier
            if order["action"] == "new":
                changes[i, 1 if side == 1 else 2] += quantity
            else:
                changes[i, 1 if side == -1 else 2] -= quantity
    assert live == {1: 0, -1: 0}
    # ----------------------------------------
    # 元の売買判断は再実行せず、現金・買数量・売数量の積算だけで全時価を再構成。
    after = np.cumsum(changes, axis=0)
    before = after-changes
    equity = np.empty(len(good)*2+1)
    equity[0] = 0
    for offset, values in ((1, before), (2, after)):
        equity[offset::2] = values[good, 0]+(values[good, 1]*raw[good, 2]-values[good, 2]*raw[good, 3])*multiplier
    minimum = float(np.min(equity))
    peak = np.maximum.accumulate(equity)
    drawdown = float(np.max(peak-equity))
    summary = case["summary"]
    equal(summary["minimum_equity"], minimum, "全原板最小時価")
    equal(summary["maximum_drawdown"], drawdown, "全原板最大下落")
    equal(summary["peak_equity"], float(np.max(equity)), "全原板最大時価")
    equal(equity[-1], real, "終端同価格清算の時価保存")
    equal(summary["realized"], real, "確定合計")
    equal(summary["final_mark"]["equity"], real, "最終時価")
    dt = np.diff(np.r_[raw[:, 0], scene["end"]])
    equal(summary["long_quantity_seconds"], np.sum(after[:, 1]*dt), "買数量秒")
    equal(summary["short_quantity_seconds"], np.sum(after[:, 2]*dt), "売数量秒")
    equal(summary["net_abs_quantity_seconds"], np.sum(np.abs(after[:, 1]-after[:, 2])*dt), "純数量秒")
    # ----------------------------------------
    # 通常判断の新規予約は同原行の実保有に上乗せ。返済予約は控除しない。
    pending_at = defaultdict(lambda: {1: 0, -1: 0})
    for order in case["decisions"]:
        if order["action"] != "new":
            continue
        i, side = order["decision_index"], order["side"]
        assert normal(raw[i:i+1])[0]
        pending_at[i][side] += order["quantity"]
        for direction, column, name in ((1, 1, "occupied_buy"), (-1, 2, "occupied_sell")):
            occupied = int(after[i, column])+pending_at[i][direction]
            assert occupied <= 10
            maxima[name] = max(maxima[name], occupied)
    maxima["occupied_buy"] = max(maxima["occupied_buy"], maxima["held_buy"])
    maxima["occupied_sell"] = max(maxima["occupied_sell"], maxima["held_sell"])
    assert summary["maximum_quantities"] == maxima
    cancelled = {v["order"]["id"] for v in case["cancelled_new"]}
    assert set(decisions) == used | cancelled | replaced
    assert not (used & cancelled) and not (used & replaced)
    for value in case["cancelled_new"]:
        assert value["order"]["action"] == "new" and value["time"] == scene["end"]
        assert np.searchsorted(good, value["order"]["decision_index"], side="right") == len(good)
    for source in case["lots"]:
        lot = lots[source["id"]]
        assert source["quantity"] == lot["remaining"] == 0
        equal(source["entry"], lot["price"], "玉建値")
        equal(source["realized"], lot["realized"], "玉収支")
        path = good[(good >= lot["entry_index"]) & (good <= lot["exit_index"])]
        gain = lot["side"]*(raw[path, 2 if lot["side"] == 1 else 3]-lot["price"])
        equal(source["best"], max(0., float(np.max(gain))), "玉最高順行")
        equal(source["worst"], min(0., float(np.min(gain))), "玉最大逆行")
    for role in ("main", "cover"):
        group = [v for v in lots.values() if v["role"] == role]
        expected = {"lots": len(group), "initial_quantity": sum(v["quantity"] for v in group),
                    "net": sum(v["realized"] for v in group), "profit": sum(max(0, v["realized"]) for v in group),
                    "loss": sum(max(0, -v["realized"]) for v in group), "remaining_quantity": 0}
        assert summary["roles"][role] == expected
    assert dict(closed_reasons) == summary["close_reasons"]
    assert proxy_fills == summary["proxy_fills"]
    for parent in summary["parents"]:
        equal(parent["net"], parent_pl[parent["id"]], "親収支")
    for ref in case["reference"]:
        i = ref["index"]
        for key, column in (("physical_line", 6), ("time", 0), ("bid", 2), ("ask", 3), ("last", 1)):
            equal(ref[key], raw[i, column], "原行参照/"+key)
    profit = sum(max(0, v["realized"]) for v in lots.values())
    loss = sum(max(0, -v["realized"]) for v in lots.values())
    return {"id": case["id"], "profit": profit, "loss": loss, "net": real,
            "minimum_equity": minimum, "maximum_drawdown": drawdown,
            "events": len(case["events"]), "lots": len(lots), "normal_marks": len(good)*2,
            "proxy_fills": proxy_fills, "maximum_quantities": maxima}


def audit_scene(scene: dict, result_path: str, expected_sha: str) -> dict:
    """一場の原板を一度だけ読んで26手法の保存会計を検算する。

    引数: scene(dict)、result_path/expected_sha(str)。返り値: dict。
    """
    path = Path(result_path)
    if not path.is_absolute():
        path = ROOT/path
    path = path.resolve()
    assert sha(path) == expected_sha
    saved = read(path)
    assert saved["session"] == scene["session"] and saved["label_input_used"] is False
    raw = raw_market(scene)
    good = np.flatnonzero(normal(raw))
    assert len(raw) == saved["raw_rows"]
    rows = [case_account(scene, raw, good, case) for case in saved["cases"]]
    assert sha(path) == expected_sha
    return {"session": scene["session"], "split": scene["split"], "raw_rows": len(raw),
            "result_sha256": expected_sha, "cases": rows}


def main() -> None:
    """全53場の正式完了を確認して、売買の再判断なしで全原板監査を行う。

    引数: なし。返り値: None。
    """
    gate = read(WORK/"再生全完了162.json")
    assert gate["completed"] is True and type(gate["returncode"]) is int and gate["returncode"] == 0
    assert gate["sessions"] == 53 and gate["cases"] == 1378
    manifest = read(WORK/"inputs162.json")
    scene_map = {s["session"]: s for s in manifest["sessions"]}
    jobs = []
    for stage in ("train_validation", "locked_test"):
        proof = read(WORK/"results"/stage/("再生完了162_"+stage+".json"))
        assert proof["completed"] is True and proof["returncode"] == 0
        jobs.extend((scene_map[row["session"]], row["path"], row["sha256"]) for row in proof["results"])
    assert len(jobs) == 53
    results = []
    with ProcessPoolExecutor(max_workers=4) as pool:
        pending = [pool.submit(audit_scene, *job) for job in jobs]
        for future in as_completed(pending):
            result = future.result()
            results.append(result)
            print(json.dumps({"session": result["session"], "cases": len(result["cases"]), "passed": True}), flush=True)
    results.sort(key=lambda value: value["session"])
    report_path = WORK/"report_data162.json"
    report = read(report_path)
    lookup = {(r["session"], c["id"]): c for r in results for c in r["cases"]}
    for method in report["methods"]:
        for row in method["rows"]:
            checked = lookup[(row["session"], method["id"])]
            for key in ("profit", "loss", "net", "minimum_equity", "maximum_drawdown"):
                equal(row[key], checked[key], "最終報告/"+key)
    value = {"passed": True, "created_at": datetime.now().astimezone().isoformat(),
             "sessions": len(results), "cases": len(lookup), "new_financial_runs": 0,
             "events": sum(c["events"] for c in lookup.values()), "lots": sum(c["lots"] for c in lookup.values()),
             "normal_marks": sum(c["normal_marks"] for c in lookup.values()),
             "report_sha256": sha(report_path), "script_sha256": sha(Path(__file__)),
             "independent_reader_sha256": sha(ROOT/"work/entry161/audit/audit_results161.py"),
             "results": results}
    with (HERE/"audit162.json").open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({k: value[k] for k in ("passed", "sessions", "cases", "events", "lots", "normal_marks")}), flush=True)


if __name__ == "__main__":
    main()
