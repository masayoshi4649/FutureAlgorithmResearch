"""00151保存約定を別の玉別計算で検算する。市場の金融再生や戦略判断は呼ばない。"""

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "work/hedge151"
OUT = Path(__file__).resolve().parent


def read(path: Path) -> dict:
    """
    機能: 保存JSONを読取専用で読み込む。
    引数: path(Path)。返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def near(a: float, b: float, context: str = "") -> None:
    """
    機能: 独立計算との数値一致を確認する。
    引数: a,b(float)、context(str)。返り値: None。不一致なら停止する。
    """
    assert math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-5), (context, a, b)


def canonical(events: list, new: bool) -> list:
    """
    機能: 二種類の保存約定を値段・数量・対象IDへ射影する。
    引数: events(list)、new(bool)。返り値: listは会計だけに使う記録。
    """
    rows = []
    for e in events or []:
        if new:
            p = e["order"]
            rows.append(dict(id=p["id"], action=p["action"], side=p["side"], qty=p["quantity"], price=e["price"],
                             time=e["fill_time"], index=e["fill_index"], decision_time=p["decision_time"], decision_index=p["decision_index"],
                             lot=p["lot_id"], targets=[] if p["action"] == "new" else [(p["lot_id"], p["quantity"])], gross=e["gross"], reason=p["reason"]))
        else:
            p, f = e["signal"], e["fill"]
            assert f["Fee"] == 0 and f["Quantity"] == p["quantity"]
            targets = f.get("Closed") if f.get("Closed") is not None else (p.get("targets") or [])
            if f.get("Closed") is not None:
                assert f["Closed"] == p.get("targets"), p["id"]
            rows.append(dict(id=e["phase"] + "/" + p["id"], action=p["action"], side=p["side"], qty=f["Quantity"], price=f["Price"],
                             time=f["Time"], index=e["fill_index"], decision_time=p["time"], decision_index=e["decision_index"],
                             lot=f.get("HoldID", ""), targets=[(x["id"], x["quantity"]) for x in targets], gross=e["gross"], reason=p.get("reason", "")))
    return rows


def ledger(rows: list) -> dict:
    """
    機能: 新規IDごとの全返済を集め、数量と損益を別計算する。
    引数: rows(list)。返り値: dictは全玉と独立会計。
    """
    lots = {}
    previous_index, previous_time = -1, -math.inf
    for order_number, e in enumerate(rows):
        assert e["index"] > e["decision_index"] and e["time"] >= e["decision_time"]
        assert e["index"] >= previous_index and e["time"] >= previous_time
        assert e["qty"] > 0 and isinstance(e["qty"], int) and e["side"] in (-1, 1) and e["price"] > 0
        previous_index, previous_time = e["index"], e["time"]
        if e["action"] == "new":
            assert e["lot"] not in lots
            lots[e["lot"]] = dict(id=e["lot"], side=e["side"], qty=e["qty"], price=e["price"], index=e["index"], time=e["time"], closes=[], remaining=e["qty"], net=0.)
            near(e["gross"], 0.)
        else:
            assert e["action"] == "close"
            gain = 0.
            assert sum(qty for _, qty in e["targets"]) == e["qty"]
            for key, qty in e["targets"]:
                lot = lots[key]
                assert 0 < qty <= lot["remaining"] and lot["side"] == -e["side"]
                value = qty * lot["side"] * (e["price"] - lot["price"]) * 100
                lot["remaining"] -= qty
                lot["net"] += value
                lot["closes"].append(dict(qty=qty, price=e["price"], index=e["index"], time=e["time"], net=value, reason=e["reason"]))
                gain += value
            near(gain, e["gross"], "返済金額")
    closed = [v for v in lots.values() if not v["remaining"]]
    return dict(lots=lots, profit=sum(max(0, x["net"]) for x in closed), loss=sum(max(0, -x["net"]) for x in closed),
                net=sum(x["net"] for x in lots.values()), entries=len(lots), remaining_lots=len(lots)-len(closed),
                cash=sum(-x["side"] * x["qty"] * x["price"] * 100 for x in rows),
                open_lot_realized=sum(x["net"] for x in lots.values() if x["remaining"]))


def state_at(lots: dict, index: int, bid: float = 0., ask: float = 0.) -> dict:
    """
    機能: 指定添字までの実玉と、指定気配での清算損益を復元する。
    引数: lots(dict)、index(int)、bid,ask(float)。返り値: dictは枚数・確定・含み。
    """
    long = short = 0
    realized = unrealized = 0.
    for lot in lots.values():
        if lot["index"] > index:
            continue
        closed = [x for x in lot["closes"] if x["index"] <= index]
        quantity = lot["qty"] - sum(x["qty"] for x in closed)
        realized += sum(x["net"] for x in closed)
        if lot["side"] > 0:
            long += quantity
        else:
            short += quantity
        if quantity and (bid or ask):
            assert ask > bid > 0
            price = bid if lot["side"] > 0 else ask
            unrealized += lot["side"] * quantity * (price - lot["price"]) * 100
    return dict(long=long, short=short, realized=realized, unrealized=unrealized, equity=realized+unrealized)


def audit_target(scene: dict, c: dict, notices: list) -> dict:
    """
    機能: 新条件の玉・予約上限・境界・時価・保有時間を独立照合する。
    引数: scene,c(dict)、notices(list)。返り値: dictは対象区間の検算値。
    """
    rows = canonical(c["events"], True)
    a = ledger(rows)
    for key in ("profit", "loss"):
        near(a[key], c[key], key)
    near(a["net"], c["gross"], "対象収支")
    last = c["last_quote"]
    final = state_at(a["lots"], last["index"], last["bid"], last["ask"])
    near(final["unrealized"], c["unrealized"], "最終含み")
    if not a["remaining_lots"]:
        near(a["cash"], a["net"], "全返済後の売買現金")
    saved_lots = {v["id"]: v for v in c["lots"]}
    assert set(saved_lots) == set(a["lots"])
    for key, lot in a["lots"].items():
        saved = saved_lots[key]
        assert lot["remaining"] == saved["quantity"] and lot["qty"] == saved["original_quantity"]
        near(lot["net"], saved["gross"])
    if not scene["partial"]:
        assert not a["remaining_lots"] and not c["pending"] and not c["arms"] and c["flat_at"] > 0
    assert c["scheduled_close"] == (scene["us_open"]-900 if c["config"]["scope"] == "pre" else scene["force_close"])

    # ----------------------------------------
    # 注文の判断添字と約定添字から予約占有を直接復元する。
    new_orders = []
    for e in c["events"] or []:
        p = e["order"]
        if p["action"] == "new":
            new_orders.append(dict(order=p, fill_index=e["fill_index"]))
        if p["reason"] == "境界全返済":
            assert p["decision_time"] >= c["scheduled_close"]
    for p in c["pending"] or []:
        if p["action"] == "new":
            new_orders.append(dict(order=p, fill_index=math.inf))
    ids = [x["order"]["id"] for x in new_orders]
    assert len(ids) == len(set(ids))
    times = {e["index"]: e["time"] for e in rows}
    indices = set(times) | {x["order"]["decision_index"] for x in new_orders}
    maximum = dict(long=0, short=0, reserved_long=0, reserved_short=0)
    for index in sorted(indices):
        current = state_at(a["lots"], index)
        pending = [x["order"] for x in new_orders if x["order"]["decision_index"] <= index < x["fill_index"]]
        reserved_long = current["long"] + sum(p["quantity"] for p in pending if p["side"] > 0)
        reserved_short = current["short"] + sum(p["quantity"] for p in pending if p["side"] < 0)
        assert max(current["long"], current["short"], reserved_long, reserved_short) <= 10
        if c["config"]["no_opposite"]:
            assert not (reserved_long and reserved_short)
        for key, value in (("long", current["long"]), ("short", current["short"]), ("reserved_long", reserved_long), ("reserved_short", reserved_short)):
            maximum[key] = max(maximum[key], value)
    for key, stored in (("long", "max_long"), ("short", "max_short"), ("reserved_long", "max_long_reserved"), ("reserved_short", "max_short_reserved")):
        assert maximum[key] == c[stored], (key, maximum[key], c[stored])

    # ----------------------------------------
    # 元通知の受理は同原行の再参加より先。直前予約込みの枚数も独立に検査する。
    expected = [n for n in notices if c["config"]["scope"] != "pre" or n["phase"] == "前半"]
    assert [d["notice"] for d in c["decisions"]] == expected
    index = None
    reserved_long = reserved_short = 0
    for d in c["decisions"]:
        n = d["notice"]
        if n["index"] != index:
            index = n["index"]
            s = state_at(a["lots"], index)
            earlier = [x["order"] for x in new_orders if x["order"]["decision_index"] < index < x["fill_index"]]
            reserved_long = s["long"] + sum(x["quantity"] for x in earlier if x["side"] > 0)
            reserved_short = s["short"] + sum(x["quantity"] for x in earlier if x["side"] < 0)
        assert (d["long_reserved"], d["short_reserved"]) == (reserved_long, reserved_short)
        assert d["accepted"] + d["rejected"] == n["quantity"]
        if d["accepted"]:
            occupied = reserved_long if n["side"] > 0 else reserved_short
            wanted = min(n["quantity"], 10-occupied)
            if c["config"]["quantity_limit"]:
                wanted = min(wanted, c["config"]["quantity_limit"])
            assert d["accepted"] == wanted
            selected = [x for x in new_orders if x["order"]["reason"] == "仮想D07入口" and x["order"]["source"] == n]
            assert len(selected) == 1 and selected[0]["order"]["quantity"] == wanted
            if n["side"] > 0:
                reserved_long += wanted
            else:
                reserved_short += wanted

    # ----------------------------------------
    # 実約定間の長さから保有時間を復元する。未約定・待機は数えない。
    duration = dict(held_seconds=0., hedged_seconds=0., long_cap_seconds=0., short_cap_seconds=0.)
    previous_time, previous_index = scene["start"], -1
    for current_index, at in sorted(times.items()):
        s = state_at(a["lots"], previous_index)
        dt = at-previous_time
        assert dt >= 0
        for key, enabled in (("held_seconds", s["long"]+s["short"] > 0), ("hedged_seconds", bool(s["long"] and s["short"])), ("long_cap_seconds", s["long"] == 10), ("short_cap_seconds", s["short"] == 10)):
            duration[key] += dt*enabled
        previous_time, previous_index = at, current_index
    s = state_at(a["lots"], previous_index)
    dt = c["observation_end_time"]-previous_time
    for key, enabled in (("held_seconds", s["long"]+s["short"] > 0), ("hedged_seconds", bool(s["long"] and s["short"])), ("long_cap_seconds", s["long"] == 10), ("short_cap_seconds", s["short"] == 10)):
        duration[key] += dt*enabled
        near(duration[key], c[key], key)
    snapshots = list(c["snapshots"] or []) + [c[k] for k in ("minimum_equity_at", "minimum_unrealized_at", "maximum_drawdown_at", "maximum_drawdown_from")]
    for snapshot in snapshots:
        s = state_at(a["lots"], snapshot["index"], snapshot["bid"], snapshot["ask"])
        for key in ("long", "short", "realized", "unrealized", "equity"):
            near(s[key], snapshot[key], "時価" + key)
    near(c["minimum_equity_at"]["equity"], c["minimum_equity"])
    near(c["minimum_unrealized_at"]["unrealized"], c["minimum_unrealized"])
    near(c["maximum_drawdown_from"]["equity"]-c["maximum_drawdown_at"]["equity"], c["maximum_drawdown"])
    assert c["maximum_drawdown_from"]["index"] <= c["maximum_drawdown_at"]["index"]
    reasons = {}
    for reason in ("利益追尾", "境界全返済"):
        gains = [e["gross"] for e in rows if e["action"] == "close" and e["reason"] == reason]
        reasons[reason] = dict(profit=sum(max(0, x) for x in gains), loss=sum(max(0, -x) for x in gains), net=sum(gains), count=len(gains))
    near(sum(x["net"] for x in reasons.values()), a["net"])
    bad = sum(e["order"]["reason"] == "利益追尾" and e["order"]["decision_gain"] > 0 and e["gross"] < 0 for e in c["events"])
    assert bad == c["positive_decision_negative_fill"]
    a.update(unrealized=final["unrealized"], snapshots_checked=len(snapshots), reasons=reasons, maximum=maximum, duration=duration, positive_decision_negative_fill=bad)
    return a


def summary(rows: list) -> dict:
    """
    機能: 完了夜の金額・赤字頻度・深さを独立集計する。
    引数: rows(list)。返り値: dictは同一条件の集計。
    """
    nets = [r["net"] for r in rows]
    reds = [-x for x in nets if x < 0]
    positives = sorted([x for x in nets if x > 0], reverse=True)
    return dict(profit=sum(r["profit"] for r in rows), loss=sum(r["loss"] for r in rows), net=sum(nets),
                losses=len(reds), wins=len(positives), maxloss=max(reds, default=0), avgloss=mean(reds) if reds else 0,
                medianloss=median(reds) if reds else 0, ex3=sum(nets)-sum(positives[:3]), entries=sum(r["entries"] for r in rows))


def main() -> None:
    """
    機能: 保存18改修と2対照を独立検算し、結果JSONを担当領域へ保存する。
    引数: なし。返り値: None。金融再生・台帳変更は行わない。
    """
    report = read(BASE / "report151.json")
    methods = {m["id"]: m for m in report["methods"]}
    reported = {(m["id"], r["session"]): r for m in report["methods"] for r in m["rows"]}
    reported.update({(r["id"], r["session"]): r for r in report["partial"]})
    receipt = read(BASE / "登録受領151.json")
    references = [receipt[k] for k in ("plan", "implementation", "inputs")] + receipt["sources"]
    assert receipt["registered"] and receipt["returncode"] == 0
    for ref in references:
        assert hashlib.sha256((ROOT/ref["path"]).read_bytes()).hexdigest() == ref["sha256"]
    complete = defaultdict(list)
    partial = {}
    evidence = []
    counts = dict(new_cases=0, complete_new_cases=0, partial_new_cases=0, saved_control_cases=0, post_exact_cases=0, prefix_cases=0, events=0, lots=0, snapshots=0)
    pairs = [("P01", "N01"), ("P02", "N02"), ("P03", "N03"), ("P06", "N04"), ("P09", "N05"), ("P10", "N06"), ("P11", "N07")]
    for path in sorted((BASE / "results_go").glob("*.json")):
        saved = read(path)
        scene = saved["scene"]
        session = scene["session"]
        case_by_id = {c["config"]["id"]: c for c in saved["cases"]}
        assert len(case_by_id) == 18 and saved["fees"] == saved["real_orders"] == 0
        s04 = next(x for x in read(ROOT/f"work/preus149/results_round2/{session}.json")["cases"] if x["config"]["id"] == "S04")
        post_events = [e for e in (s04["events"] or []) if e["phase"] == "後半"]
        post_rows = canonical(post_events, False)
        post = ledger(post_rows)
        first_post_decision = min((e["decision_time"] for e in post_rows if e["action"] == "new"), default=0)
        assert not post["remaining_lots"]
        for identifier, folder in (("C00", "work/preus149/results_go"), ("B04", "work/preus150/results_round2")):
            old = next(x for x in read(ROOT/f"{folder}/{session}.json")["cases"] if x["config"]["id"] == identifier)
            a = ledger(canonical(old["events"], False))
            near(a["net"], old["Gross"])
            a["unrealized"] = old["Unrealized"]
            counts["saved_control_cases"] += 1
            check_report(identifier, session, a, reported)
            compact = {k: a[k] for k in ("profit", "loss", "net", "entries", "unrealized")}
            compact["session"] = session
            (partial if scene["partial"] else complete)[identifier] = compact if scene["partial"] else complete[identifier] + [compact]
        for identifier, c in case_by_id.items():
            a = audit_target(scene, c, saved["source_notices"])
            counts["new_cases"] += 1
            counts["complete_new_cases"] += not scene["partial"]
            counts["partial_new_cases"] += scene["partial"]
            counts["events"] += len(c["events"])
            counts["lots"] += len(a["lots"])
            counts["snapshots"] += a["snapshots_checked"]
            result = {k: a[k] for k in ("profit", "loss", "net", "entries", "unrealized", "remaining_lots", "open_lot_realized")}
            target = dict(result)
            if c["config"]["scope"] == "pre":
                reused_rows = canonical(c["reused_post"]["events"], False)
                fields = ("action", "side", "qty", "price", "time", "index", "decision_time", "decision_index", "lot", "targets", "gross")
                assert [[e[k] for k in fields] for e in reused_rows] == [[e[k] for k in fields] for e in post_rows]
                if first_post_decision:
                    assert 0 < c["flat_at"] < first_post_decision
                for key in ("profit", "loss", "net", "entries", "remaining_lots", "open_lot_realized"):
                    result[key] += post[key]
                counts["post_exact_cases"] += 1
            else:
                assert not c["reused_post"]["events"] and c["reused_post"]["gross"] == 0
            near(result["net"], c["combined_gross"])
            check_report(identifier, session, result, reported)
            result.update(session=session, target=target, trail=a["reasons"]["利益追尾"], boundary=a["reasons"]["境界全返済"], positive_decision_negative_fill=a["positive_decision_negative_fill"], maximum=a["maximum"], **a["duration"])
            if scene["partial"]:
                partial[identifier] = result
            else:
                complete[identifier].append(result)
        for left, right in pairs:
            l = [e for e in canonical(case_by_id[left]["events"], True) if e["time"] < scene["us_open"]-900]
            r = [e for e in canonical(case_by_id[right]["events"], True) if e["time"] < scene["us_open"]-900]
            fields = ("action", "side", "qty", "price", "time", "index", "decision_time", "decision_index", "gross", "reason")
            assert [[e[k] for k in fields] for e in l] == [[e[k] for k in fields] for e in r]
            counts["prefix_cases"] += 1
        evidence.append(dict(session=session, result_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    assert counts["new_cases"] == 468 and counts["complete_new_cases"] == 450 and counts["partial_new_cases"] == 18
    assert counts["saved_control_cases"] == 52 and counts["post_exact_cases"] == 286 and counts["prefix_cases"] == 182
    statistics = {}
    for identifier, rows in complete.items():
        assert len(rows) == 25
        s = summary(rows)
        for key, value in s.items():
            near(value, methods[identifier]["summary"][key], "集計"+identifier+key)
        if identifier not in ("C00", "B04"):
            s["target"] = summary([r["target"] for r in rows])
            for kind in ("trail", "boundary"):
                s[kind] = {k: sum(r[kind][k] for r in rows) for k in ("profit", "loss", "net", "count")}
            s["positive_decision_negative_fill"] = sum(r["positive_decision_negative_fill"] for r in rows)
        statistics[identifier] = s
    contrasts = []
    for base, changed in [("P02", "P08"), ("P02", "P06"), ("P02", "P07"), ("P02", "P09"), ("N02", "N05"), ("P02", "P10"), ("P06", "P11"), ("N02", "N06"), ("N04", "N07")]:
        b = {r["session"]: r for r in complete[base]}
        delta = [dict(session=r["session"], delta=r["net"]-b[r["session"]]["net"]) for r in complete[changed]]
        total = sum(x["delta"] for x in delta)
        contrasts.append(dict(base=base, changed=changed, delta=total, better=sum(x["delta"] > 0 for x in delta), worse=sum(x["delta"] < 0 for x in delta), same=sum(x["delta"] == 0 for x in delta), delta_ex3=total-sum(sorted([x["delta"] for x in delta if x["delta"] > 0], reverse=True)[:3]), by_session=delta))
    output = dict(financial_replays=0, new_raw_market_reads=0, frozen_references_checked=len(references), all_fingerprints_match=True,
                  **counts, total_complete_display_cases=500, total_partial_display_cases=20, methods=statistics, partial=partial,
                  contrasts=contrasts, evidence=evidence, all_checks_passed=True,
                  limits=["保存した極値時点の数量・時価は再計算したが、全原板を独立に読み直して他の極値がないことを再証明したものではない。", "独立比較は同じ既知25夜であり未見成績ではない。"])
    (OUT/"最終会計の独立確認.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in output.items() if k not in ("methods", "partial", "contrasts", "evidence", "limits")}, ensure_ascii=False))


def check_report(identifier: str, session: str, a: dict, reported: dict) -> None:
    """
    機能: 別担当の全場公開会計と独立計算を照合する。
    引数: identifier,session(str)、a,reported(dict)。返り値: None。
    """
    row = reported[(identifier, session)]
    for key in ("profit", "loss", "net", "entries", "unrealized"):
        near(a[key], row[key], identifier+session+key)
    near(a["net"]+a["unrealized"], row["equity"])


if __name__ == "__main__":
    main()
