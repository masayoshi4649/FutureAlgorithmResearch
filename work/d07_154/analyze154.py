"""00154の保存された実約定だけを原板と照合し、親・玉・返済配賦の会計を分離する。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work/d07_154"
AUDIT = WORK / "data_audit"
JST = timezone(timedelta(hours=9))
VALUE = 100.0


def load(path: Path) -> dict | list:
    """UTF-8の保存JSONを読む。

    引数: path(Path)は読取専用の資料位置。返り値: dict又はlistは復元した内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path: Path, value: object) -> None:
    """集計結果をUTF-8で保存する。

    引数: path(Path)、value(object)はJSON化可能な値。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def fingerprint(path: Path) -> dict:
    """内容指紋を実際の全バイトから計算する。

    引数: path(Path)。返り値: dictは絶対位置・バイト数・SHA256。
    """
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": h.hexdigest()}


def near(actual: float, expected: float, name: str) -> None:
    """会計・時刻・価格の独立計算値を照合する。

    引数: actual,expected(float)、name(str)。返り値: None。不一致はAssertionError。
    """
    if not math.isclose(float(actual), float(expected), abs_tol=0.00001, rel_tol=1e-10):
        raise AssertionError(f"{name}: {actual} != {expected}")


def clock(at: float | None) -> str | None:
    """UNIX秒を日本時間の明示時計へ変換する。

    引数: at(float又はNone)。返り値: str又はNone。
    """
    return None if at is None else datetime.fromtimestamp(at, JST).isoformat()


def direction(scene: dict) -> str:
    """当場の最初・最後の資格済みLastから事後方向を分類する。

    引数: scene(dict)は凍結目録。返り値: str。指標・売買判断には渡さない。
    """
    edges = scene["qualification"]["NK225"]["book"]
    change = edges["last"]["last"] - edges["first"]["last"]
    return "上昇" if change > 0 else "下落" if change < 0 else "横ばい"


def read_quotes(scene: dict) -> tuple[dict, dict]:
    """原板を戦略と独立に読み、全採用行の時計・BBO・原行番号を保存する。

    引数: scene(dict)は凍結資料。返り値: (dict,dict)は列配列と全文指紋。
    新しい売買条件の計算や金融再生を行わず、約定と保存ポジションの時価だけに使用する。
    """
    path = Path(scene["books"]["NK225"])
    registered = next(x for x in scene["fingerprints"] if Path(x["path"]).resolve() == path.resolve())
    cache = AUDIT / "quote_cache" / (scene["session"] + ".npz")
    meta = cache.with_suffix(".json")
    if cache.exists() and meta.exists():
        saved = load(meta)
        assert saved["source"]["sha256"] == registered["sha256"]
        st = path.stat()
        assert st.st_size == saved["source"]["bytes"] and st.st_mtime_ns == saved["mtime_ns"]
        assert fingerprint(cache)["sha256"] == saved["cache"]["sha256"]
        with np.load(cache) as data:
            return {k: data[k] for k in data.files}, saved
    times, bids, asks, lasts, lines = [], [], [], [], []
    previous, h = scene["start"], hashlib.sha256()
    before = path.stat()
    with path.open("rb") as stream:
        for line_number, raw in enumerate(stream, 1):
            h.update(raw)
            row = json.loads(raw)
            stamp = row.get("CurrentPriceTime")
            if not stamp:
                continue
            try:
                parsed_time = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                if parsed_time.tzinfo is None:
                    continue
                at = parsed_time.timestamp()
            except (ValueError, TypeError):
                continue
            if at < scene["start"] or at > scene["end"] or (scene.get("cutoff", 0) > 0 and at >= scene["cutoff"]) or at < previous:
                continue
            last = row.get("CurrentPrice") or 0
            if not math.isfinite(last) or last <= 0:
                continue
            previous = at
            bid = (row.get("Buy1") or {}).get("Price") or 0
            ask = (row.get("Sell1") or {}).get("Price") or 0
            times.append(at)
            bids.append(bid)
            asks.append(ask)
            lasts.append(last)
            lines.append(line_number)
    after = path.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    assert h.hexdigest() == registered["sha256"], f"原資料変更: {path}"
    q = {"time": np.asarray(times), "bid": np.asarray(bids), "ask": np.asarray(asks),
         "last": np.asarray(lasts), "line": np.asarray(lines, dtype=np.int64)}
    q["valid"] = np.isfinite(q["bid"]) & np.isfinite(q["ask"]) & (q["bid"] > 0) & (q["ask"] > q["bid"])
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, **q)
    saved = {"source": {"path": str(path.resolve()), "sha256": h.hexdigest(), "bytes": after.st_size},
             "mtime_ns": after.st_mtime_ns, "cache": fingerprint(cache), "rows": len(times),
             "normal_quotes": int(q["valid"].sum()), "normal_definition": "有限な0<bid<ask。数量は約定資格に使わない。",
             "clock": "CurrentPriceTime。受信時計ではない。null/逆行/場外/非正Lastを除外し、同一時計原行順を保持。"}
    write(meta, saved)
    return q, saved


def sign_sums(values: list[float]) -> dict:
    """同一粒度の収支を正負へ分解する。

    引数: values(list[float])。返り値: dictは利益・正額の損失・差引・件数。
    """
    return {"profit": sum(max(v, 0) for v in values), "loss": sum(max(-v, 0) for v in values),
            "net": sum(values), "wins": sum(v > 0 for v in values), "losses": sum(v < 0 for v in values),
            "zero": sum(v == 0 for v in values), "count": len(values)}


def reference(q: dict, index: int) -> dict:
    """判断・実約定の原資料上の位置を返す。

    引数: q(dict)は原板列、index(int)は採用列添字。返り値: dict。
    """
    return {"index": int(index), "raw_line": int(q["line"][index]), "time": clock(float(q["time"][index])),
            "unix": float(q["time"][index]), "bid": float(q["bid"][index]), "ask": float(q["ask"][index])}


def independent_account(scene: dict, case: dict, q: dict) -> tuple[dict, list, list, list]:
    """所有ID・返済対象ごとに原会計を再構築し、次の正常原行約定を全件照合する。

    引数: scene,case,q(dict)は目録・保存結果・原板列。返り値: (集計dict,玉list,親list,返済配賦list)。
    """
    events = case.get("events") or []
    valid = np.flatnonzero(q["valid"])
    lots, parents, allocations = {}, {}, []
    executed, decisions = set(), {s["id"]: s for s in (case.get("signals") or [])}
    pending = {s["id"]: s for s in (case.get("final_pending") or [])}
    evidence = case.get("decision_evidence") or {}
    by_signal, prior_time, prior_index = {}, scene["start"], -1
    gross = held = quantity_seconds = 0.0
    current_qty = 0
    max_long = max_short = 0
    for sig in decisions.values():
        i = sig["source_index"]
        assert i >= 0 and i < len(q["time"])
        near(sig["time"], q["time"][i], "判断時計と原行")
        e = evidence[sig["id"]]
        assert e["Index"] == i
        near(e["Time"], q["time"][i], "判断証拠の時計")
        for field, column in (("Bid", "bid"), ("Ask", "ask")):
            expected = q[column][i] if math.isfinite(q[column][i]) else 0
            near(e[field], expected, "判断証拠の気配")
    for ordinal, event in enumerate(events):
        sig, fill = event["signal"], event["fill"]
        sid, i, di = sig["id"], event["fill_index"], event["decision_index"]
        assert sid in decisions and sid not in executed and sid not in pending
        assert fill["SignalID"] == sid and fill["ExecutionID"] not in executed
        assert decisions[sid] == sig
        next_position = np.searchsorted(valid, di, side="right")
        assert next_position < len(valid) and i == int(valid[next_position]), "次正常原行以外への約定"
        assert i > di and di == sig["source_index"] and i >= prior_index
        near(fill["Time"], q["time"][i], "実約定時計と原行")
        assert fill["Time"] >= sig["time"] and fill["Time"] >= prior_time
        near(fill["Price"], q["ask" if sig["side"] > 0 else "bid"][i], "売買BBO約定")
        assert fill["Quantity"] == sig["quantity"] and fill["Quantity"] > 0 and fill["Fee"] == 0
        assert sig["side"] in (-1, 1)
        dt = fill["Time"] - prior_time
        held += dt * (current_qty > 0)
        quantity_seconds += dt * current_qty
        parent_key = f'{sig["owner"]}/{sig["campaign"]}'
        gain = 0.0
        if sig["action"] == "new":
            identifier = fill["HoldID"]
            assert identifier not in lots
            parent = parents.get(parent_key)
            if parent is None:
                parent = parents[parent_key] = {"key": parent_key, "owner": sig["owner"], "campaign": sig["campaign"],
                    "side": sig["side"], "entry": reference(q, i), "decision": reference(q, di), "initial_quantity": fill["Quantity"],
                    "risk": sig["risk"], "net": 0.0, "remaining": 0, "lots": [], "events": [], "allocations": [],
                    "exit": None, "max_quantity": 0}
                kind = "初回"
            else:
                kind = "追撃" if parent["remaining"] else "同親再新規"
            assert parent["side"] == sig["side"]
            lot = lots[identifier] = {"id": identifier, "parent": parent_key, "owner": sig["owner"], "campaign": sig["campaign"],
                 "side": sig["side"], "quantity": fill["Quantity"], "remaining": fill["Quantity"], "price": fill["Price"],
                 "type": kind, "net": 0.0, "entry": reference(q, i), "decision": reference(q, di),
                 "signal_id": sid, "ordinal": ordinal, "reason": sig["reason"], "reason_code": sig["reason_code"], "risk": sig["risk"],
                 "ticket": sig.get("ticket", 0), "closes": [], "quantity_before": parent["remaining"],
                 "decision_evidence": evidence[sid]}
            parent["lots"].append(identifier)
            parent["remaining"] += fill["Quantity"]
            parent["max_quantity"] = max(parent["max_quantity"], parent["remaining"])
        else:
            assert sig["action"] == "close" and parent_key in parents
            parent = parents[parent_key]
            targets = fill.get("Closed") or []
            assert targets == (sig.get("targets") or [])
            assert sum(t["quantity"] for t in targets) == fill["Quantity"]
            for target in targets:
                lot = lots[target["id"]]
                qty = target["quantity"]
                assert lot["parent"] == parent_key and lot["side"] == -sig["side"] and 0 < qty <= lot["remaining"]
                pnl = lot["side"] * qty * (fill["Price"] - lot["price"]) * VALUE
                leg = {"lot_id": lot["id"], "parent": parent_key, "owner": lot["owner"], "side": lot["side"],
                       "quantity": qty, "net": pnl, "exit_price": fill["Price"], "entry_price": lot["price"],
                       "type": lot["type"], "entry": lot["entry"], "decision": reference(q, di), "exit": reference(q, i),
                       "signal_id": sid, "ordinal": ordinal, "reason": sig["reason"], "reason_code": sig["reason_code"]}
                allocations.append(leg)
                lot["closes"].append(leg)
                lot["remaining"] -= qty
                lot["net"] += pnl
                parent["remaining"] -= qty
                parent["net"] += pnl
                parent["allocations"].append(leg)
                gain += pnl
            if not parent["remaining"]:
                parent["exit"] = reference(q, i)
        near(gain, event["gross"], "保存約定損益")
        gross += gain
        parent["events"].append({"ordinal": ordinal, "action": sig["action"], "side": sig["side"],
                                 "quantity": fill["Quantity"], "price": fill["Price"], "net": gain,
                                 "signal_id": sid, "decision": reference(q, di), "fill": reference(q, i),
                                 "reason": sig["reason"], "reason_code": sig["reason_code"]})
        long = sum(l["remaining"] for l in lots.values() if l["side"] > 0)
        short = sum(l["remaining"] for l in lots.values() if l["side"] < 0)
        max_long, max_short = max(max_long, long), max(max_short, short)
        assert long <= 10 and short <= 10
        for owner, capacity in (("core", 5), ("addon", 3), ("episode", 2)):
            assert sum(l["remaining"] for l in lots.values() if l["owner"] == owner) <= capacity
        current_qty = long + short
        executed.add(sid)
        executed.add(fill["ExecutionID"])
        by_signal[sid] = event
        prior_time, prior_index = fill["Time"], i
    assert set(decisions) == set(by_signal) | set(pending)
    for sig in pending.values():
        assert np.searchsorted(valid, sig["source_index"], side="right") == len(valid)
    # ----------------------------------------
    # 約定済みだけでなく、判断済み・未約定の新規枚数を加えた上限も別計算する。
    reservation_deltas = defaultdict(lambda: [0, 0])
    owner_reservations = defaultdict(lambda: defaultdict(int))
    for sig in decisions.values():
        side_column = 0 if sig["side"] > 0 else 1
        if sig["action"] == "new":
            reservation_deltas[sig["source_index"]][side_column] += sig["quantity"]
            owner_reservations[sig["owner"]][sig["source_index"]] += sig["quantity"]
        elif sig["id"] in by_signal:
            # 返済のsideは建玉と逆。返済約定まで新規上限は空かない。
            reservation_deltas[by_signal[sig["id"]]["fill_index"]][1 - side_column] -= sig["quantity"]
            owner_reservations[sig["owner"]][by_signal[sig["id"]]["fill_index"]] -= sig["quantity"]
    reserved_long = reserved_short = 0
    maximum_reserved_long = maximum_reserved_short = 0
    for _, deltas in sorted(reservation_deltas.items()):
        reserved_long += deltas[0]
        reserved_short += deltas[1]
        assert 0 <= reserved_long <= 10 and 0 <= reserved_short <= 10
        maximum_reserved_long = max(maximum_reserved_long, reserved_long)
        maximum_reserved_short = max(maximum_reserved_short, reserved_short)
    for owner, deltas in owner_reservations.items():
        balance = 0
        for _, delta in sorted(deltas.items()):
            balance += delta
            assert 0 <= balance <= {"core": 5, "addon": 3, "episode": 2}[owner]
    near(gross, case["Gross"], "全実現収支")
    last = case["last_quote"]
    last_i = int(valid[-1])
    assert last["Index"] == last_i
    near(last["Time"], q["time"][last_i], "末尾正常板")
    end = float(q["time"][-1]) if scene["partial"] else scene["end"]
    held += (end - prior_time) * (current_qty > 0)
    quantity_seconds += (end - prior_time) * current_qty
    for parent in parents.values():
        parent["pending_new"] = sum(s["quantity"] for s in pending.values() if s["action"] == "new" and f'{s["owner"]}/{s["campaign"]}' == parent["key"])
        parent["closed"] = parent["remaining"] == 0 and parent["pending_new"] == 0
        own = [l for l in lots.values() if l["parent"] == parent["key"]]
        parent["initial_net"] = sum(l["net"] for l in own if l["type"] == "初回")
        parent["addition_net"] = sum(l["net"] for l in own if l["type"] == "追撃")
        parent["reentry_net"] = sum(l["net"] for l in own if l["type"] == "同親再新規")
    unrealized = 0.0
    for identifier, lot in lots.items():
        original = case["entries"][identifier]
        assert original["Remaining"] == lot["remaining"] and original["Quantity"] == lot["quantity"]
        assert original["Owner"] == lot["owner"] and original["Campaign"] == lot["campaign"]
        assert original["Side"] == lot["side"]
        near(original["Price"], lot["price"], "所有玉建値")
        near(original["Time"], lot["entry"]["unix"], "所有玉建時刻")
        near(lot["net"], original["Gross"], "所有玉損益")
        mark = q["bid" if lot["side"] > 0 else "ask"][last_i]
        lot["unrealized"] = float(lot["side"] * lot["remaining"] * (mark - lot["price"]) * VALUE)
        unrealized += lot["unrealized"]
        final_i = lot["closes"][-1]["exit"]["index"] if not lot["remaining"] else last_i
        mark_i = valid[np.searchsorted(valid, lot["entry"]["index"]):np.searchsorted(valid, final_i, side="right")]
        moves = lot["side"] * (q["bid" if lot["side"] > 0 else "ask"][mark_i] - lot["price"])
        best, worst = max(0.0, float(moves.max())), min(0.0, float(moves.min()))
        near(best, original["BestPoints"], "所有玉MFE")
        near(worst, original["WorstPoints"], "所有玉MAE")
        lot["mfe_points"], lot["mae_points"] = best, worst
        lot["mfe_at"] = reference(q, int(mark_i[np.argmax(moves)])) if best > 0 else lot["entry"]
        lot["mae_at"] = reference(q, int(mark_i[np.argmin(moves)])) if worst < 0 else lot["entry"]
        near(original["BestTime"], lot["mfe_at"]["unix"], "MFE到達時計")
        near(original["WorstTime"], lot["mae_at"]["unix"], "MAE到達時計")
        lot["closed"] = not lot["remaining"]
        lot["duration_seconds"] = float(q["time"][final_i] - lot["entry"]["unix"])
        before_realized = before_unrealized = 0.0
        for older in lots.values():
            if older["parent"] != lot["parent"] or older["ordinal"] >= lot["ordinal"]:
                continue
            prior_closes = [c for c in older["closes"] if c["ordinal"] < lot["ordinal"]]
            prior_qty = older["quantity"] - sum(c["quantity"] for c in prior_closes)
            before_realized += sum(c["net"] for c in prior_closes)
            prior_price = q["bid" if older["side"] > 0 else "ask"][lot["entry"]["index"]]
            before_unrealized += older["side"] * prior_qty * (prior_price - older["price"]) * VALUE
        lot["parent_realized_before_entry"] = before_realized
        lot["parent_unrealized_before_entry"] = float(before_unrealized)
        lot["parent_equity_before_entry"] = float(before_realized + before_unrealized)
    near(unrealized, case["Unrealized"], "全未決済含み")
    assert len(lots) == len(case.get("entries") or {})
    if not scene["partial"]:
        assert current_qty == 0 and not pending and all(p["closed"] for p in parents.values())
    summary = sign_sums([p["net"] for p in parents.values() if p["closed"]])
    summary["closed_parent_net"] = summary["net"]
    summary["net"] = gross
    summary["open_parent_realized"] = sum(p["net"] for p in parents.values() if not p["closed"])
    near(summary["profit"] - summary["loss"] + summary["open_parent_realized"], gross, "親会計恒等式")
    slice_values = sign_sums([a["net"] for a in allocations])
    lot_values = sign_sums([l["net"] for l in lots.values() if l["closed"]])
    summary.update({"allocation_profit": slice_values["profit"], "allocation_loss": slice_values["loss"],
        "lot_profit": lot_values["profit"], "lot_loss": lot_values["loss"], "unrealized": unrealized, "equity": gross + unrealized,
        "entries": len(lots), "parents": len(parents), "closed_parents": sum(p["closed"] for p in parents.values()),
        "entry_quantity": sum(l["quantity"] for l in lots.values()), "remaining_qty": current_qty,
        "quantity": sum(l["quantity"] for l in lots.values()), "max_per_side": max(max_long, max_short),
        "max_long": max_long, "max_short": max_short, "held_seconds": held,
        "max_reserved_long": maximum_reserved_long, "max_reserved_short": maximum_reserved_short,
        "held_rate": held / (scene["end"] - scene["start"]), "average_quantity": quantity_seconds / (scene["end"] - scene["start"]),
        "additions": sum(l["type"] == "追撃" for l in lots.values()), "reentries": sum(l["type"] == "同親再新規" for l in lots.values()),
        "pending_orders": len(pending), "first_entry": clock(min((l["entry"]["unix"] for l in lots.values()), default=None)),
        "last_quote": reference(q, last_i), "verified_events": len(events), "verified_decisions": len(decisions)})
    for kind, label in (("初回", "initial"), ("追撃", "addition"), ("同親再新規", "reentry")):
        selected = [l for l in lots.values() if l["type"] == kind]
        summary[label] = sign_sums([l["net"] for l in selected])
        close_qty = sum(l["quantity"] - l["remaining"] for l in selected)
        summary[label].update(entry_quantity=sum(l["quantity"] for l in selected), closed_quantity=close_qty,
                              points_per_closed_contract=summary[label]["net"] / VALUE / close_qty if close_qty else None)
    summary["buy"] = sign_sums([p["net"] for p in parents.values() if p["side"] > 0 and p["closed"]])
    summary["sell"] = sign_sums([p["net"] for p in parents.values() if p["side"] < 0 and p["closed"]])
    near(summary["initial"]["net"] + summary["addition"]["net"] + summary["reentry"]["net"], gross,
         "初回・追撃・再新規の全実現恒等式")
    summary["us_before_net"] = sum(a["net"] for a in allocations if scene["kind"] == "Night" and a["exit"]["unix"] < scene["us_open"])
    summary["us_after_net"] = sum(a["net"] for a in allocations if scene["kind"] == "Night" and a["exit"]["unix"] >= scene["us_open"])
    return summary, list(lots.values()), list(parents.values()), allocations


def mark_saved_positions(q: dict, lots: list, begin: int, finish: int) -> dict:
    """既存約定だけを全正常気配で時価評価し、実現と含みの最高値・下落幅を区別する。

    引数: q(dict)、lots(list[dict])、begin,finish(int)。返り値: dictは時価の診断値。
    前後を同一価格で評価し、返済直前の利益を約定後のゼロ枚で消さない。
    """
    if not lots or finish < begin:
        return {"peak_equity": None, "peak_unrealized": None, "small_peak_equity": None, "small_peak_unrealized": None,
                "minimum_equity": None, "minimum_unrealized": None, "drawdown": 0.0, "drawdown_at": None}
    n = finish - begin + 1
    # ----------------------------------------
    # 各原行の約定後在庫を差分配列から作る。価格条件や新規判断は実行しない。
    long_delta, short_delta, basis_delta, realized_delta = [np.zeros(n) for _ in range(4)]
    for lot in lots:
        index = lot["entry"]["index"] - begin
        assert 0 <= index < n
        qty_delta = long_delta if lot["side"] > 0 else short_delta
        qty_delta[index] += lot["quantity"]
        basis_delta[index] += lot["side"] * lot["quantity"] * lot["price"] * VALUE
        for close in lot["closes"]:
            index = close["exit"]["index"] - begin
            qty_delta[index] -= close["quantity"]
            basis_delta[index] -= lot["side"] * close["quantity"] * lot["price"] * VALUE
            realized_delta[index] += close["net"]
    long, short = np.cumsum(long_delta), np.cumsum(short_delta)
    basis, realized = np.cumsum(basis_delta), np.cumsum(realized_delta)
    indices = np.flatnonzero(q["valid"][begin:finish + 1])
    bid, ask = q["bid"][begin:finish + 1], q["ask"][begin:finish + 1]
    before_unrealized = (long - long_delta) * bid * VALUE - (short - short_delta) * ask * VALUE - (basis - basis_delta)
    after_unrealized = long * bid * VALUE - short * ask * VALUE - basis
    before_equity = before_unrealized + realized - realized_delta
    after_equity = after_unrealized + realized
    before_qty, after_qty = long + short - long_delta - short_delta, long + short
    equity = np.column_stack((before_equity[indices], after_equity[indices])).reshape(-1)
    unrealized = np.column_stack((before_unrealized[indices], after_unrealized[indices])).reshape(-1)
    quantity = np.column_stack((before_qty[indices], after_qty[indices])).reshape(-1)
    source_indices = np.repeat(indices + begin, 2)

    def extrema(values: np.ndarray, maximize: bool, allowed: np.ndarray | None = None) -> dict | None:
        """同一評価列から極値の原行を選ぶ。

        引数: values(np.ndarray)、maximize(bool)、allowed(np.ndarray又はNone)。返り値: dict又はNone。
        """
        candidates = np.arange(len(values)) if allowed is None else np.flatnonzero(allowed)
        if not len(candidates):
            return None
        selected = candidates[np.argmax(values[candidates]) if maximize else np.argmin(values[candidates])]
        return dict(reference(q, int(source_indices[selected])), value=float(values[selected]), quantity=int(quantity[selected]),
                    phase="同原行約定前" if selected % 2 == 0 else "同原行約定後")

    peak = np.maximum.accumulate(np.maximum(equity, 0))
    dd = peak - equity
    small = (quantity >= 1) & (quantity <= 2)
    result = {"peak_equity": extrema(equity, True), "peak_unrealized": extrema(unrealized, True, quantity > 0),
            "small_peak_equity": extrema(equity, True, small), "small_peak_unrealized": extrema(unrealized, True, small),
            "minimum_equity": extrema(equity, False), "minimum_unrealized": extrema(unrealized, False, quantity > 0),
            "drawdown": float(dd.max()), "drawdown_at": extrema(dd, True)}
    # ----------------------------------------
    # 同一原行に複数約定があっても、中間で1～2枚になる状態を落とさない。
    operations = defaultdict(list)
    for lot in lots:
        operations[lot["ordinal"]].append((lot, lot["quantity"], 0.0, lot["entry"]["index"]))
        for close in lot["closes"]:
            operations[close["ordinal"]].append((lot, -close["quantity"], close["net"], close["exit"]["index"]))
    lq = sq = 0
    basis_value = realized_value = 0.0
    for _, legs in sorted(operations.items()):
        for lot, delta, gain, i in legs:
            if lot["side"] > 0:
                lq += delta
            else:
                sq += delta
            basis_value += lot["side"] * delta * lot["price"] * VALUE
            realized_value += gain
        uq = lq * q["bid"][i] * VALUE - sq * q["ask"][i] * VALUE - basis_value
        eq = realized_value + uq
        for field, value, maximize, allow in (("peak_equity", eq, True, True), ("peak_unrealized", uq, True, lq + sq > 0),
             ("small_peak_equity", eq, True, 1 <= lq + sq <= 2), ("small_peak_unrealized", uq, True, 1 <= lq + sq <= 2),
             ("minimum_equity", eq, False, True), ("minimum_unrealized", uq, False, lq + sq > 0)):
            old = result[field]
            if allow and (old is None or (value > old["value"] if maximize else value < old["value"])):
                result[field] = dict(reference(q, i), value=float(value), quantity=lq + sq, phase="個別実約定の直後")
    return result


def value_at(lots: list, q: dict, at: float) -> dict:
    """指定時計までに成立した実約定だけを直前正常板で清算評価する。

    引数: lots(list[dict])、q(dict)、at(float)。返り値: dictは確定・含み・時価。
    """
    eligible = np.flatnonzero(q["valid"] & (q["time"] <= at))
    assert len(eligible)
    i = int(eligible[-1])
    realized = unrealized = 0.0
    quantity = 0
    for lot in lots:
        if lot["entry"]["unix"] > at:
            continue
        legs = [c for c in lot["closes"] if c["exit"]["unix"] <= at]
        remaining = lot["quantity"] - sum(c["quantity"] for c in legs)
        realized += sum(c["net"] for c in legs)
        mark = q["bid" if lot["side"] > 0 else "ask"][i]
        unrealized += lot["side"] * remaining * (mark - lot["price"]) * VALUE
        quantity += remaining
    return {"at": clock(at), "realized": realized, "unrealized": float(unrealized), "equity": float(realized + unrealized),
            "remaining_qty": quantity, "last_quote": reference(q, i), "quote_age_seconds": at - q["time"][i]}


def summarize(rows: list) -> dict:
    """完了場を等しい一場として集計し、通常損失と突出利益への依存を残す。

    引数: rows(list[dict])は途中を含まない場別会計。返り値: dict。
    """
    net = sum(r["net"] for r in rows)
    loss_values = [-r["net"] for r in rows if r["net"] < 0]
    profit_values = sorted([r["net"] for r in rows if r["net"] > 0], reverse=True)
    total_profit, total_loss = sum(r["profit"] for r in rows), sum(r["loss"] for r in rows)
    return {"sessions": len(rows), "profit": total_profit, "loss": total_loss, "net": net,
            "pf": total_profit / total_loss if total_loss else None,
            "wins": sum(r["net"] > 0 for r in rows), "losses": len(loss_values), "zero": sum(r["net"] == 0 for r in rows),
            "no_trade": sum(r["entries"] == 0 for r in rows), "maxloss": max(loss_values, default=0),
            "avgloss": statistics.mean(loss_values) if loss_values else 0,
            "medianloss": statistics.median(loss_values) if loss_values else 0,
            "ex3": net - sum(profit_values[:3]), "entries": sum(r["entries"] for r in rows),
            "parents": sum(r["parents"] for r in rows), "additions": sum(r["additions"] for r in rows),
            "initial_net": sum(r["initial"]["net"] for r in rows), "addition_net": sum(r["addition"]["net"] for r in rows),
            "reentry_net": sum(r["reentry"]["net"] for r in rows), "held_rate": statistics.mean([r["held_rate"] for r in rows]) if rows else 0,
            "buy_profit": sum(r["buy"]["profit"] for r in rows), "buy_loss": sum(r["buy"]["loss"] for r in rows),
            "buy_net": sum(r["buy"]["net"] for r in rows), "sell_profit": sum(r["sell"]["profit"] for r in rows),
            "sell_loss": sum(r["sell"]["loss"] for r in rows), "sell_net": sum(r["sell"]["net"] for r in rows),
            "us_before_net": sum(r["us_before_net"] for r in rows), "us_after_net": sum(r["us_after_net"] for r in rows),
            "allocation_profit": sum(r["allocation_profit"] for r in rows), "allocation_loss": sum(r["allocation_loss"] for r in rows),
            "lot_profit": sum(r["lot_profit"] for r in rows), "lot_loss": sum(r["lot_loss"] for r in rows)}


def compare_parents(baseline: list, candidate: list) -> dict:
    """親の初回判断を一致キーとして、消えた取引と出口変更を区別する。

    引数: baseline,candidate(list[dict])は同じ場の親。返り値: dictは差分恒等式と実例。
    損益を見て入口を近似一致させず、担当・売買方向・初回原判断添字が同じ場合だけ対応させる。
    """
    def key(parent: dict) -> tuple:
        """親入口の事前一致キーを返す。

        引数: parent(dict)。返り値: tuple。
        """
        return parent["owner"], parent["side"], parent["decision"]["index"]

    old, new = {key(p): p for p in baseline}, {key(p): p for p in candidate}
    assert len(old) == len(baseline) and len(new) == len(candidate)
    vanished = [p for k, p in old.items() if k not in new]
    appeared = [p for k, p in new.items() if k not in old]
    matched = [{"owner": old[k]["owner"], "side": old[k]["side"], "decision": old[k]["decision"],
                "baseline": old[k]["net"], "candidate": new[k]["net"], "difference": new[k]["net"] - old[k]["net"],
                "baseline_initial_qty": old[k]["initial_quantity"], "candidate_initial_qty": new[k]["initial_quantity"],
                "initial_quantity_effect": old[k]["initial_net"] * (new[k]["initial_quantity"] / old[k]["initial_quantity"] - 1),
                "initial_exit_effect": new[k]["initial_net"] - old[k]["initial_net"] * new[k]["initial_quantity"] / old[k]["initial_quantity"],
                "addition_effect": new[k]["addition_net"] - old[k]["addition_net"],
                "reentry_effect": new[k]["reentry_net"] - old[k]["reentry_net"]}
               for k in old.keys() & new.keys()]
    for record in matched:
        near(record["difference"], sum(record[k] for k in ("initial_quantity_effect", "initial_exit_effect", "addition_effect", "reentry_effect")),
             "同入口の枚数・出口・追撃差分")
    total_difference = sum(p["net"] for p in candidate) - sum(p["net"] for p in baseline)
    matched_difference = sum(p["difference"] for p in matched)
    appeared_net, vanished_net = sum(p["net"] for p in appeared), sum(p["net"] for p in vanished)
    near(total_difference, matched_difference + appeared_net - vanished_net, "親入口対応の差分恒等式")
    return {"difference": total_difference, "same_entry_count": len(matched), "same_entry_difference": matched_difference,
            "initial_quantity_effect": sum(p["initial_quantity_effect"] for p in matched),
            "initial_exit_effect": sum(p["initial_exit_effect"] for p in matched),
            "addition_effect": sum(p["addition_effect"] for p in matched), "reentry_effect": sum(p["reentry_effect"] for p in matched),
            "vanished": sign_sums([p["net"] for p in vanished]), "appeared": sign_sums([p["net"] for p in appeared]),
            "same_entry_win_to_loss": sum(p["baseline"] > 0 and p["candidate"] < 0 for p in matched),
            "same_entry_loss_to_win": sum(p["baseline"] < 0 and p["candidate"] > 0 for p in matched),
            "vanished_examples": vanished, "appeared_examples": appeared,
            "worst_same_entry": sorted(matched, key=lambda p: p["difference"])[:6],
            "best_same_entry": sorted(matched, key=lambda p: p["difference"], reverse=True)[:6]}


def old145_comparison(rows: list) -> dict:
    """旧145の50場と新Go基準の同じ50場を親会計で比較する。

    引数: rows(list[dict])は今回のD07。返り値: dictは重なる場だけの差分。
    """
    source = ROOT / "work/research145_roles/役割分離の全場結果145.json"
    saved = load(source)
    old_rows = saved["rows"]
    identifier_key = next(k for k in ("id", "method", "method_id") if k in old_rows[0])
    old = {r["session"]: r for r in old_rows if r[identifier_key] == "D07"}
    joined = []
    for row in rows:
        if row["session"] not in old:
            continue
        prior = old[row["session"]]
        joined.append({"session": row["session"], "old_profit": prior["profit"], "old_loss": prior["loss"],
                       "old_net": prior["net"], "new_profit": row["profit"], "new_loss": row["loss"],
                       "new_net": row["net"], "difference": row["net"] - prior["net"]})
    assert len(joined) == 50
    return {"source": fingerprint(source), "sessions": len(joined), "rows": joined,
            "old_net": sum(r["old_net"] for r in joined), "new_net": sum(r["new_net"] for r in joined),
            "difference": sum(r["difference"] for r in joined),
            "different_sessions": sum(abs(r["difference"]) > .00001 for r in joined),
            "limitation": "旧145はPythonの保存特徴・注文模型、今回は現Goの昼夜D07。基準自体の差と改修差を混同しない。10/26Dayは旧145に含まれない。"}


def short_parent(parent: dict) -> dict:
    """概要資料へ必要な親の損失・利得・参照時計だけを写す。

    引数: parent(dict)。返り値: dict。
    """
    keys = ("key", "owner", "campaign", "side", "entry", "decision", "exit", "net", "remaining", "initial_quantity", "max_quantity",
            "risk", "initial_net", "addition_net", "reentry_net", "peak_equity", "peak_unrealized", "small_peak_equity", "small_peak_unrealized", "giveback", "session", "kind")
    return {k: parent[k] for k in keys if k in parent}


def short_lot(lot: dict) -> dict:
    """追加玉の当時判断・約定・最終損益を概要へ写す。

    引数: lot(dict)。返り値: dict。
    """
    return {k: lot[k] for k in ("id", "parent", "owner", "side", "type", "quantity", "remaining", "quantity_before", "price", "net",
             "unrealized", "entry", "decision", "reason", "reason_code", "risk", "mfe_points", "mae_points", "mfe_at", "mae_at",
             "duration_seconds", "parent_realized_before_entry", "parent_unrealized_before_entry", "parent_equity_before_entry",
             "closes", "session", "kind") if k in lot}


def diagnostic_snapshot(case: dict, at_index: int, owner: str) -> dict | None:
    """指定行以前で最後に保存された担当の閾値診断を選ぶ。

    引数: case(dict)、at_index(int)、owner(str)。返り値: dict又はNone。
    古い診断をその原行での再計算値と呼ばず、保存時刻も残す。
    """
    for snapshot in reversed(case.get("snapshots") or []):
        if snapshot["Index"] <= at_index:
            record = next((d for d in (snapshot.get("Diagnostics") or []) if d["owner"] == owner), None)
            if record is not None:
                return {"saved_at": clock(snapshot["Time"]), "saved_index": snapshot["Index"], "diagnostics": record}
    return None


def write_markdown(report: dict, diagnoses: dict) -> None:
    """主結果と具体的な損失の再現先を簡潔な日本語で保存する。

    引数: report,diagnoses(dict)。返り値: None。
    """
    lines = ["# D07の利益消失・追撃の独立集計", "", "51完了場（デイ26・ナイト25）。日経mini片方向上限10枚、手数料0。利益・損失の主表は完結親単位。",
             "現在10/27デイは取得済み原板の観測末尾までで別表。停止後の手動返済価格がないため、実アプリの−90,505円との差を改善額にはしない。", "",
             "|手法|利益|損失|収支|赤字場|平均赤字|最大赤字|上位3黒字除外|", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in report["method_rows"]:
        lines.append(f'|{row["id"]}|{row["profit"]:,.0f}|{row["loss"]:,.0f}|{row["net"]:,.0f}|{row["losses"]}/51|{row["avgloss"]:,.0f}|{row["maxloss"]:,.0f}|{row["ex3"]:,.0f}|')
    lines += ["", "利益の山は後から測る診断値であり、その全額を当時獲得できたという意味ではない。約定は判断後の次の正常ラージBBOで、miniの実約定を保証しない。", "",
              "## 基準D07の赤字上位3場", ""]
    for d in diagnoses["D07"]["worst_sessions"]:
        lines += [f'### {d["session"]}: {d["net"]:,.0f}円', ""]
        for p in d["worst_parents"]:
            peak = p["peak_equity"]
            lines.append(f'- {p["owner"]}・{"買い" if p["side"] > 0 else "売り"}、{p["entry"]["time"]}初回{p["initial_quantity"]}枚。親最高時価{peak["value"]:,.0f}円（{peak["time"]}）から、最終{p["net"]:,.0f}円。詳細は親ID `{p["key"]}`。')
        lines.append("")
    prior = report["old145_comparison"]
    lines += ["## 旧145との差", "", f'重なる50場は旧145 {prior["old_net"]:,.0f}円、新Go基準 {prior["new_net"]:,.0f}円、差 {prior["difference"]:+,.0f}円（差のある場{prior["different_sessions"]}）。',
              prior["limitation"], "", "詳細会計は `data_audit/cases/{session}/{id}.json`、具体的原因は `data_audit/diagnosis154.json`。"]
    (WORK / "analysis154.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """全保存結果が揃ってから会計を実行し、未完了場を統計に混ぜず報告する。

    引数: なし。返り値: None。金融売買エンジンは呼ばない。
    """
    manifest_path = WORK / "inputs154.json"
    manifest = load(manifest_path)
    assert fingerprint(manifest_path)["sha256"] == "d30747d798397efd31b4ce73c9a9cf0a4519346946c331889037ce724b691b90"
    configs = load(WORK / "configs154.json")
    ids = [c["id"] for c in configs]
    assert len(ids) == 15 and len(set(ids)) == 15
    scenes = manifest["sessions"]
    assert len(scenes) == 52 and sum(not s["partial"] for s in scenes) == 51
    files = [WORK / "results_go" / (s["session"] + "_D07.json") for s in scenes]
    assert all(p.exists() for p in files), "全52資料が揃ってから集計してください"
    rows, partial_rows = [], []
    comparisons = defaultdict(list)
    case_paths, quote_sources, result_sources = [], [], []
    all_parent_summaries, all_additions = defaultdict(list), defaultdict(list)
    event_total = decision_total = 0
    for scene, path in zip(scenes, files):
        saved = load(path)
        assert saved["scene"]["session"] == scene["session"]
        assert [c["config"]["id"] for c in saved["cases"]] == ids
        q, qmeta = read_quotes(scene)
        quote_sources.append(qmeta)
        result_sources.append(fingerprint(path))
        last_i = int(np.flatnonzero(q["valid"])[-1])
        same_scene_parents = {}
        for case in saved["cases"]:
            identifier = case["config"]["id"]
            values, lots, parents, allocations = independent_account(scene, case, q)
            event_total += values["verified_events"]
            decision_total += values["verified_decisions"]
            risk = mark_saved_positions(q, lots, 0, last_i)
            values["equity_drawdown"] = risk["drawdown"]
            values["minimum_equity"] = risk["minimum_equity"]["value"] if risk["minimum_equity"] else 0
            for parent in parents:
                owned = [l for l in lots if l["parent"] == parent["key"]]
                parent.update(mark_saved_positions(q, owned, parent["entry"]["index"],
                              parent["exit"]["index"] if parent["closed"] else last_i))
                parent.update(session=scene["session"], kind=scene["kind"])
                parent["giveback"] = parent["peak_equity"]["value"] - parent["net"]
                parent["entry_diagnostics"] = diagnostic_snapshot(case, parent["decision"]["index"], parent["owner"])
                parent["peak_diagnostics"] = diagnostic_snapshot(case, parent["peak_equity"]["index"], parent["owner"])
                parent["last_diagnostics"] = diagnostic_snapshot(case, parent["events"][-1]["decision"]["index"], parent["owner"])
            for lot in lots:
                lot.update(session=scene["session"], kind=scene["kind"])
                if lot["type"] == "追撃":
                    lot["entry_diagnostics"] = diagnostic_snapshot(case, lot["decision"]["index"], lot["owner"])
            row = {"id": identifier, "symbol": "NK225", "session": scene["session"], "kind": scene["kind"],
                   "direction": direction(scene), "direction_source": "当場最初Lastと終了前6分以内の最終Last代理。正式終値ではない。事後採点のみ。",
                   **values}
            target = AUDIT / "cases" / scene["session"] / (identifier + ".json")
            write(target, {"row": row, "risk": risk, "parents": parents, "lots": lots, "allocations": allocations})
            case_paths.append({"session": scene["session"], "id": identifier, "path": str(target)})
            if scene["partial"]:
                stop = datetime(2026, 10, 27, 11, 21, 41, tzinfo=JST).timestamp()
                row["at_actual_stop"] = value_at(lots, q, stop)
                row["direction_source"] = "当場最初Lastと取得済み観測末尾Last。場末方向ではない。"
                partial_rows.append(row)
            else:
                rows.append(row)
                all_parent_summaries[identifier].extend(short_parent(p) for p in parents)
                all_additions[identifier].extend(short_lot(l) for l in lots if l["type"] == "追撃")
            same_scene_parents[identifier] = parents
        for identifier in ids:
            difference = compare_parents(same_scene_parents["D07"], same_scene_parents[identifier])
            difference["vanished_examples"] = [short_parent(p) for p in difference["vanished_examples"]]
            difference["appeared_examples"] = [short_parent(p) for p in difference["appeared_examples"]]
            comparisons[identifier].append({"session": scene["session"], "partial": scene["partial"], **difference})
        print(f'会計完了 {scene["session"]} {len(ids)}条件', flush=True)
    # ----------------------------------------
    # 主集計は完了51場だけ。途中の実現・含み・同一時計比較は別表へ置く。
    methods, method_rows, diagnoses = [], [], {}
    for cfg in configs:
        identifier = cfg["id"]
        selected = [r for r in rows if r["id"] == identifier]
        summary = summarize(selected)
        categories = {name: summarize([r for r in selected if r[field] == value])
                      for name, field, value in (("day", "kind", "Day"), ("night", "kind", "Night"),
                          ("up", "direction", "上昇"), ("down", "direction", "下落"), ("flat", "direction", "横ばい"))}
        methods.append({"id": identifier, "symbol": "NK225", "description": cfg["description"], "config": cfg,
                        "rows": selected, "summary": summary, **categories})
        method_rows.append({"id": identifier, "description": cfg["description"], **summary,
                            "day_net": categories["day"]["net"], "day_losses": categories["day"]["losses"],
                            "night_net": categories["night"]["net"], "night_losses": categories["night"]["losses"],
                            "up_net": categories["up"]["net"], "down_net": categories["down"]["net"]})
        parents = all_parent_summaries[identifier]
        additions = all_additions[identifier]
        small = [p for p in parents if p["small_peak_unrealized"] and p["small_peak_unrealized"]["value"] > 0]
        small_equity = [p for p in parents if p["small_peak_equity"] and p["small_peak_equity"]["value"] > 0]
        negative_adds = [l for l in additions if l["net"] < 0]
        worst = sorted(selected, key=lambda r: r["net"])[:3]
        diagnoses[identifier] = {
            "small_positive_parents": len(small), "small_positive_final_loss": sum(p["net"] < 0 for p in small),
            "small_positive_definition": "実保有1〜2枚の残玉含み益が正。既確定損益を足さない。",
            "small_positive_equity_parents": len(small_equity), "small_positive_equity_final_loss": sum(p["net"] < 0 for p in small_equity),
            "small_positive_equity_definition": "実保有1〜2枚の時点で既確定損益と残玉含みの合計が正。",
            "positive_equity_final_loss": sum(p["peak_equity"]["value"] > 0 and p["net"] < 0 for p in parents),
            "additions": sign_sums([l["net"] for l in additions]), "losing_additions": len(negative_adds),
            "losing_additions_within60s": sum(l["duration_seconds"] <= 60 for l in negative_adds),
            "losing_additions_within300s": sum(l["duration_seconds"] <= 300 for l in negative_adds),
            "worst_additions": sorted(negative_adds, key=lambda l: l["net"])[:10],
            "largest_givebacks": sorted(parents, key=lambda p: p["giveback"], reverse=True)[:10],
            "small_positive_final_losses": sorted([p for p in small if p["net"] < 0], key=lambda p: p["net"])[:10],
            "worst_sessions": [{"session": r["session"], "net": r["net"],
                                "worst_parents": sorted([p for p in parents if p["session"] == r["session"]], key=lambda p: p["net"])[:5]}
                               for r in worst]}
    baseline = next(m for m in methods if m["id"] == "D07")
    for row in method_rows:
        row["difference_from_D07"] = row["net"] - baseline["summary"]["net"]
    report = {"definition": {"financial_replays_in_this_script": 0, "fees": 0, "point_value": VALUE, "cap_per_side": 10,
              "main_profit_loss": "完結親(owner/campaign)の全返済純額を正負分類。返済配賦・新規ID完結は補助列。",
              "partial": "途中は完結親と未完親の部分実現を分離。未返済玉は最終正常BBOで含み評価し、強制清算しない。",
              "fills": "全注文で判断原行より後の最初の正常ラージBBO。売りbid・買いask。mini実気配の再現ではない。",
              "marking": "保存約定の全在庫だけを全正常気配で評価。利益の山は事後診断であり到達時の決済保証ではない。",
              "current_actual": "11:21:41に実運転停止・手動決済。手動価格不明。12:08未満の模型継続と実収支を差引しない。",
              "selection": "既知51場で候補比較した再利用資料。未見検証の成績と呼ばない。夜は全場D07条件の比較で、P05併用標準とは別。"},
              "summary": {"complete_sessions": 51, "day_sessions": 26, "night_sessions": 25, "methods": len(ids),
                          "current_sessions": 1, "verified_events": event_total, "verified_decisions": decision_total},
              "methods": methods, "method_rows": method_rows, "session_rows": rows, "current_rows": partial_rows,
              "old145_comparison": old145_comparison(baseline["rows"]),
              "sources": {"manifest": fingerprint(manifest_path), "configs": fingerprint(WORK / "configs154.json"),
                          "results": result_sources, "quote_sources": quote_sources, "analyzer": fingerprint(Path(__file__))}}
    write(AUDIT / "comparison154.json", dict(comparisons))
    write(AUDIT / "diagnosis154.json", diagnoses)
    write(AUDIT / "accounting_cases154.json", case_paths)
    write(WORK / "report154.json", report)
    write_markdown(report, diagnoses)
    write(AUDIT / "会計照合154.json", {"passed": True, **report["summary"],
          "report": fingerprint(WORK / "report154.json"), "comparison": fingerprint(AUDIT / "comparison154.json"),
          "diagnosis": fingerprint(AUDIT / "diagnosis154.json"), "source_manifest": fingerprint(manifest_path)})
    print(json.dumps({"passed": True, **report["summary"]}, ensure_ascii=False), flush=True)


def self_test() -> None:
    """合成約定だけで部分利確・部分損切り・原行先着検査の会計を試す。

    引数: なし。返り値: None。実市場データを使う金融再生ではない。
    """
    q = {"time": np.arange(6, dtype=float), "bid": np.array([100., 100., 103., 103., 99., 99.]),
         "ask": np.array([101., 101., 104., 104., 100., 100.]), "valid": np.ones(6, dtype=bool),
         "line": np.arange(1, 7), "last": np.ones(6) * 100}
    scene = {"start": 0, "end": 6, "partial": False, "kind": "Day"}
    case = {"events": [], "signals": [], "final_pending": [], "decision_evidence": {}, "Gross": 0., "Unrealized": 0.,
            "last_quote": {"Index": 5, "Time": 5}, "entries": {"玉1": {"Remaining": 0, "Quantity": 2, "Owner": "core",
            "Campaign": 0, "Side": 1, "Price": 101., "Time": 1., "Gross": 0., "BestPoints": 2., "WorstPoints": -2.,
            "BestTime": 2., "WorstTime": 4.}}}
    for n, action, side, qty, di, fi, price, gain in ((1, "new", 1, 2, 0, 1, 101., 0.),
            (2, "close", -1, 1, 2, 3, 103., 200.), (3, "close", -1, 1, 4, 5, 99., -200.)):
        targets = [] if action == "new" else [{"id": "玉1", "quantity": 1}]
        sig = {"id": f"注文{n}", "owner": "core", "campaign": 0, "action": action, "side": side, "quantity": qty,
               "time": float(di), "source_index": di, "reason": "人工試験", "reason_code": n, "risk": 10., "targets": targets}
        fill = {"SignalID": sig["id"], "ExecutionID": f"約定{n}", "HoldID": "玉1", "Quantity": qty, "Price": price,
                "Time": float(fi), "Fee": 0, "Closed": targets}
        case["signals"].append(sig)
        case["events"].append({"signal": sig, "fill": fill, "decision_index": di, "fill_index": fi, "gross": gain})
        case["decision_evidence"][sig["id"]] = {"Index": di, "Time": float(di), "Bid": q["bid"][di], "Ask": q["ask"][di]}
    row, lots, parents, allocations = independent_account(scene, case, q)
    assert row["profit"] == row["loss"] == row["net"] == 0
    assert row["allocation_profit"] == row["allocation_loss"] == 200
    assert len(parents) == len(lots) == 1 and len(allocations) == 2
    marks = mark_saved_positions(q, lots, 0, 5)
    assert marks["peak_equity"]["value"] == 400 and marks["drawdown"] == 400
    assert value_at(lots, q, 3)["equity"] == 400
    assert compare_parents(parents, parents)["difference"] == 0
    partial = json.loads(json.dumps(case))
    partial["events"] = partial["events"][:2]
    partial["signals"] = partial["signals"][:2]
    partial["decision_evidence"].pop("注文3")
    partial["Gross"], partial["Unrealized"] = 200., -200.
    partial["entries"]["玉1"].update(Remaining=1, Gross=200.)
    partial_row, _, _, _ = independent_account(dict(scene, partial=True), partial, q)
    assert partial_row["profit"] == 0 and partial_row["open_parent_realized"] == 200
    assert partial_row["net"] == 200 and partial_row["unrealized"] == -200 and partial_row["equity"] == 0
    case["events"][0]["fill_index"] = 2
    try:
        independent_account(scene, case, q)
    except AssertionError:
        pass
    else:
        raise AssertionError("次正常原行以外の約定を受理")
    print("合成会計試験PASS: 部分利確/損切り、親と配賦の粒度差、全時価、次原行拒否", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="00154保存会計の独立検算。売買再生なし。")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        main()


