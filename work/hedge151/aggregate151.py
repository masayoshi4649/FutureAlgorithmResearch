"""研究151の保存約定を新規実約定ID単位で独立再会計する。売買判断・金融再生は行わない。"""

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
POINT_VALUE = 100


def close_enough(actual: float, expected: float, label: str) -> None:
    """独立計算と保存値の一致を確認する。

    引数: actual,expected(float)は比較値、label(str)は検算箇所。
    返り値: None。不一致では処理を止める。
    """
    assert math.isfinite(actual) and math.isfinite(expected), label
    assert math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-5), (label, actual, expected)


def load(path: Path) -> dict:
    """保存された会計又は登録用JSONを読み取る。

    引数: path(Path)はファイル。
    返り値: dictは保存値。原板には使用しない。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fingerprint(path: Path) -> dict:
    """再集計の根拠ファイルの指紋を記録する。

    引数: path(Path)は読み取り専用の保存会計。
    返り値: dictは相対パス、サイズ、SHA256。
    """
    raw = path.read_bytes()
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def select_case(value: dict, identifier: str) -> dict:
    """複数条件の保存値から指定IDを一意に選ぶ。

    引数: value(dict)は場の保存会計、identifier(str)は手法ID。
    返り値: dictは指定条件。不在又は重複なら停止する。
    """
    cases = [case for case in value["cases"] if case["config"]["id"] == identifier]
    assert len(cases) == 1, identifier
    return cases[0]


def normalize_saved(events: list) -> list:
    """149/150保存約定を所有ID付きの共通会計形式にする。

    引数: events(list[dict])は元会計の実約定。
    返り値: list[dict]は価格・数量・返済対象・時刻だけの会計記録。
    """
    result = []
    for event in events or []:
        signal, fill = event["signal"], event["fill"]
        assert fill["Fee"] == 0
        assert fill["Quantity"] == signal["quantity"]
        targets = fill.get("Closed")
        if targets is None:
            targets = signal.get("targets") or []
        if fill.get("Closed") is not None and signal.get("targets"):
            assert [(t["id"], t["quantity"]) for t in fill["Closed"]] == [(t["id"], t["quantity"]) for t in signal["targets"]]
        result.append({"action": signal["action"], "side": signal["side"], "quantity": fill["Quantity"],
                       "price": fill["Price"], "time": fill["Time"], "index": event["fill_index"],
                       "decision_time": signal["time"], "decision_index": event["decision_index"],
                       "lot_id": fill.get("HoldID", ""), "targets": targets,
                       "phase": event["phase"], "owner": signal["owner"], "reason": signal.get("reason", ""),
                       "gross": event["gross"], "generation": 0})
    return result


def normalize_new(events: list) -> list:
    """151の独立実玉約定を共通会計形式にする。

    引数: events(list[dict])は新条件の保存約定。
    返り値: list[dict]は所有ID・予約時刻を保つ会計記録。
    """
    result = []
    for event in events or []:
        order = event["order"]
        result.append({"action": order["action"], "side": order["side"], "quantity": order["quantity"],
                       "price": event["price"], "time": event["fill_time"], "index": event["fill_index"],
                       "decision_time": order["decision_time"], "decision_index": order["decision_index"],
                       "lot_id": order["lot_id"],
                       "targets": [] if order["action"] == "new" else [{"id": order["lot_id"], "quantity": order["quantity"]}],
                       "phase": order["source"]["phase"], "owner": order["source"]["owner"], "reason": order["reason"],
                       "gross": event["gross"], "generation": order["generation"]})
    return result


def lot_summary(lots: list) -> dict:
    """新規実約定IDごとの完結損益と未完結玉の部分実現を区別する。

    引数: lots(list[dict])は独立に復元した建玉。
    返り値: dictは完結利益・損失と全実現収支・件数。
    """
    closed = [lot for lot in lots if lot["remaining"] == 0]
    positive = [lot for lot in closed if lot["net"] > 0]
    negative = [lot for lot in closed if lot["net"] < 0]
    return {"profit": sum(lot["net"] for lot in positive), "loss": -sum(lot["net"] for lot in negative),
            "net": sum(lot["net"] for lot in lots), "open_lot_realized": sum(lot["net"] for lot in lots if lot["remaining"]),
            "entries": len(lots), "entry_quantity": sum(lot["original_quantity"] for lot in lots),
            "closed_lots": len(closed), "winning_lots": len(positive), "losing_lots": len(negative),
            "zero_lots": sum(lot["net"] == 0 for lot in closed), "remaining_lots": len(lots) - len(closed)}


def account(events: list, start: float, end: float) -> dict:
    """約定の所有IDと数量から会計・実保有時間を独立に復元する。

    引数: events(list[dict])は共通約定形式、start,end(float)は観測開始・終端秒。
    返り値: dictは全玉明細・現金・最大保有・保有時間。
    """
    lots = {}
    cash = 0.0
    realized = 0.0
    long = short = 0
    max_long = max_short = 0
    previous_time = start
    previous_index = -1
    held = hedged = long_cap = short_cap = 0.0
    for event in events:
        assert event["action"] in ("new", "close") and event["side"] in (-1, 1)
        qty, side, price = event["quantity"], event["side"], event["price"]
        assert isinstance(qty, int) and qty > 0 and price > 0
        assert event["index"] > event["decision_index"] and event["time"] >= event["decision_time"]
        assert event["time"] >= previous_time and event["index"] >= previous_index
        dt = event["time"] - previous_time
        held += dt * (long + short > 0)
        hedged += dt * (long > 0 and short > 0)
        long_cap += dt * (long == 10)
        short_cap += dt * (short == 10)
        if event["index"] != previous_index:
            max_long, max_short = max(max_long, long), max(max_short, short)
        cash -= side * qty * price * POINT_VALUE
        gain = 0.0
        if event["action"] == "new":
            assert event["lot_id"] not in lots
            lots[event["lot_id"]] = {"id": event["lot_id"], "side": side, "original_quantity": qty, "remaining": qty,
                                     "price": price, "entry_time": event["time"], "entry_index": event["index"],
                                     "exit_time": None, "exit_index": None, "phase": event["phase"], "owner": event["owner"],
                                     "generation": event["generation"], "net": 0.0, "closes": []}
        else:
            closed_quantity = 0
            for target in event["targets"]:
                lot = lots[target["id"]]
                quantity = target["quantity"]
                assert lot["side"] == -side and 0 < quantity <= lot["remaining"]
                value = lot["side"] * quantity * (price - lot["price"]) * POINT_VALUE
                lot["remaining"] -= quantity
                lot["net"] += value
                lot["closes"].append({"time": event["time"], "index": event["index"], "price": price,
                                       "quantity": quantity, "net": value, "reason": event["reason"]})
                if not lot["remaining"]:
                    lot["exit_time"], lot["exit_index"] = event["time"], event["index"]
                gain += value
                closed_quantity += quantity
            assert closed_quantity == qty
        close_enough(gain, event["gross"], "各返済約定")
        realized += gain
        long = sum(lot["remaining"] for lot in lots.values() if lot["side"] > 0)
        short = sum(lot["remaining"] for lot in lots.values() if lot["side"] < 0)
        assert long <= 10 and short <= 10
        previous_time, previous_index = event["time"], event["index"]
    assert end >= previous_time
    dt = end - previous_time
    held += dt * (long + short > 0)
    hedged += dt * (long > 0 and short > 0)
    long_cap += dt * (long == 10)
    short_cap += dt * (short == 10)
    max_long, max_short = max(max_long, long), max(max_short, short)
    values = list(lots.values())
    result = lot_summary(values)
    close_enough(result["net"], realized, "玉別と全実現")
    close_enough(result["profit"] - result["loss"] + result["open_lot_realized"], realized, "完結玉と未完結玉の実現")
    if long + short == 0:
        close_enough(cash, realized, "無保有時の現金")
    return dict(result, lots=values, cash=cash, max_long=max_long, max_short=max_short,
                long=long, short=short, held_seconds=held, hedged_seconds=hedged,
                long_cap_seconds=long_cap, short_cap_seconds=short_cap)


def snapshot_account(lots: list, snapshot: dict) -> dict:
    """保存された極値時点の在庫とBBO清算時価を約定から復元する。

    引数: lots(list[dict])は実約定玉、snapshot(dict)は価格・添字付きの状態。
    返り値: dictは復元した確定・含み・合計。
    """
    index = snapshot["index"]
    long = short = 0
    realized = unrealized = 0.0
    for lot in lots:
        if lot["entry_index"] > index:
            continue
        closed = [leg for leg in lot["closes"] if leg["index"] <= index]
        remaining = lot["original_quantity"] - sum(leg["quantity"] for leg in closed)
        realized += sum(leg["net"] for leg in closed)
        if remaining:
            assert snapshot["ask"] > snapshot["bid"] > 0
            price = snapshot["bid"] if lot["side"] > 0 else snapshot["ask"]
            unrealized += lot["side"] * remaining * (price - lot["price"]) * POINT_VALUE
        if lot["side"] > 0:
            long += remaining
        else:
            short += remaining
    assert long == snapshot["long"] and short == snapshot["short"]
    close_enough(realized, snapshot["realized"], "極値時点の確定")
    close_enough(unrealized, snapshot["unrealized"], "極値時点の含み")
    close_enough(realized + unrealized, snapshot["equity"], "極値時点の時価")
    return {"realized": realized, "unrealized": unrealized, "equity": realized + unrealized}


def summarize(rows: list) -> dict:
    """完了セッションの利益・損失・安定性を集計する。

    引数: rows(list[dict])は途中場を除いた同じ手法の場会計。
    返り値: dictは総計、赤字頻度、通常損失、上位3黒字除外収支。
    """
    nets = [row["net"] for row in rows]
    reds = [-x for x in nets if x < 0]
    greens = [x for x in nets if x > 0]
    profit = sum(row["profit"] for row in rows)
    loss = sum(row["loss"] for row in rows)
    return {"sessions": len(rows), "profit": profit, "loss": loss, "net": sum(nets), "pf": profit / loss if loss else None,
            "wins": len(greens), "losses": len(reds), "zero": sum(x == 0 for x in nets),
            "maxloss": max(reds, default=0), "avgloss": mean(reds) if reds else 0,
            "medianloss": median(reds) if reds else 0, "median": median(nets) if nets else None,
            "ex3": sum(nets) - sum(sorted(greens, reverse=True)[:3]),
            "entries": sum(row["entries"] for row in rows), "zero_entries": sum(row["entries"] == 0 for row in rows),
            "all_sessions_have_entry": bool(rows) and all(row["entries"] > 0 for row in rows)}


def classify_decisions(case: dict) -> dict:
    """在庫上限による拒否を、意図した一通知あたり枚数制限と区別する。

    引数: case(dict)は新条件の保存判断。
    返り値: dictは拒否・縮小・再参加の実数と判断数。
    """
    decisions = case["decisions"] or []
    limit = case["config"]["quantity_limit"]
    cap_count = cap_quantity = 0
    for decision in decisions:
        desired = decision["notice"]["quantity"]
        desired = min(desired, limit) if limit > 0 else desired
        reserved = decision["long_reserved"] if decision["notice"]["side"] > 0 else decision["short_reserved"]
        if decision["reason"] in ("片側上限", "新規予約") and desired > 10 - reserved:
            cap_count += 1
            cap_quantity += desired - max(0, 10 - reserved)
        assert decision["accepted"] + decision["rejected"] == decision["notice"]["quantity"]
    actual_reentry = sum(e["order"]["action"] == "new" and e["order"]["reason"] == "利益返済後の追尾再新規" for e in case["events"] or [])
    assert actual_reentry <= case["reentry_new_count"]
    return {"source_notices": len(decisions), "rejected_notices": sum(d["accepted"] == 0 for d in decisions),
            "reduced_notices": sum(d["accepted"] > 0 and d["rejected"] > 0 for d in decisions),
            "rejected_quantity": sum(d["rejected"] for d in decisions),
            "cap_rejected_notices": cap_count, "cap_rejected_quantity": cap_quantity,
            "opposite_rejected_notices": sum(d["reason"] == "反対側の保有又は新規予約あり" for d in decisions),
            "reentry_entries": actual_reentry, "reentry_decisions": case["reentry_new_count"],
            "reentry_cap_wait_rows": case["reentry_cap_wait_rows"], "reentry_arms_cancelled": case["reentry_arms_cancelled"],
            "rejection_reasons": dict(Counter(d["reason"] for d in decisions if d["accepted"] == 0))}


def target_account(scene: dict, case: dict) -> dict:
    """新条件の玉会計・極値・保有時間・返済理由別内訳を照合する。

    引数: scene(dict)は時刻定義、case(dict)は新条件の保存結果。
    返り値: dictは対象区間の独立会計。
    """
    events = normalize_new(case["events"])
    observed_end = case["observation_end_time"]
    result = account(events, scene["start"], observed_end)
    close_enough(result["net"], case["gross"], "新条件総実現")
    close_enough(result["profit"], case["profit"], "新条件完結利益")
    close_enough(result["loss"], case["loss"], "新条件完結損失")
    assert result["max_long"] == case["max_long"] and result["max_short"] == case["max_short"]
    assert case["max_long_reserved"] <= 10 and case["max_short_reserved"] <= 10
    for key in ("held_seconds", "hedged_seconds", "long_cap_seconds", "short_cap_seconds"):
        close_enough(result[key], case[key], key)
    stored = {lot["id"]: lot for lot in case["lots"]}
    assert set(stored) == {lot["id"] for lot in result["lots"]}
    for lot in result["lots"]:
        other = stored[lot["id"]]
        assert lot["side"] == other["side"] and lot["original_quantity"] == other["original_quantity"]
        assert lot["remaining"] == other["quantity"] and lot["entry_index"] == other["index"]
        close_enough(lot["price"], other["price"], "玉の新規価格")
        close_enough(lot["net"], other["gross"], "玉の全返済損益")
        if not lot["remaining"]:
            assert lot["exit_time"] == other["exit_time"] and lot["exit_index"] == other["exit_index"]
    if not scene["partial"]:
        assert result["remaining_lots"] == 0 and not case["pending"] and case["flat_at"] > 0

    # ----------------------------------------
    # 全原行で記録された極値の時点を再会計する。分単位のスナップショットだけで極値を代用しない。
    for name in ("minimum_equity_at", "minimum_unrealized_at", "maximum_drawdown_at", "maximum_drawdown_from"):
        snapshot_account(result["lots"], case[name])
    close_enough(case["minimum_equity_at"]["equity"], case["minimum_equity"], "最小時価の時点")
    close_enough(case["minimum_unrealized_at"]["unrealized"], case["minimum_unrealized"], "最小含みの時点")
    close_enough(case["maximum_drawdown_from"]["equity"] - case["maximum_drawdown_at"]["equity"], case["maximum_drawdown"], "DDの山谷")
    assert case["maximum_drawdown_from"]["index"] <= case["maximum_drawdown_at"]["index"]
    snapshot_checks = 4
    for snapshot in case["snapshots"] or []:
        snapshot_account(result["lots"], snapshot)
        assert snapshot["equity"] >= case["minimum_equity"] - 1e-5
        assert snapshot["unrealized"] >= case["minimum_unrealized"] - 1e-5
        snapshot_checks += 1
    last = case["last_quote"]
    unrealized = sum(lot["side"] * lot["remaining"] * ((last["bid"] if lot["side"] > 0 else last["ask"]) - lot["price"]) * POINT_VALUE for lot in result["lots"])
    close_enough(unrealized, case["unrealized"], "最終正常板の含み")

    reasons = {}
    for name in ("利益追尾", "境界全返済"):
        legs = [event for event in events if event["action"] == "close" and event["reason"] == name]
        reasons[name] = {"profit": sum(max(0, e["gross"]) for e in legs), "loss": sum(max(0, -e["gross"]) for e in legs),
                         "net": sum(e["gross"] for e in legs), "trades": len(legs), "quantity": sum(e["quantity"] for e in legs)}
    close_enough(sum(value["net"] for value in reasons.values()), result["net"], "通常追尾と境界清算")
    actual_bad_fill = sum(e["order"]["action"] == "close" and e["order"]["reason"] == "利益追尾" and e["order"]["decision_gain"] > 0 and e["gross"] < 0 for e in case["events"] or [])
    assert actual_bad_fill == case["positive_decision_negative_fill"]
    result.update(unrealized=unrealized, equity=result["net"] + unrealized,
                  trail=reasons["利益追尾"], boundary=reasons["境界全返済"],
                  max_unrealized_loss=max(0, -case["minimum_unrealized"]), equity_drawdown=case["maximum_drawdown"],
                  minimum_equity=case["minimum_equity"], extreme_snapshots={k: case[k] for k in ("minimum_equity_at", "minimum_unrealized_at", "maximum_drawdown_at", "maximum_drawdown_from")},
                  risk_scope="米国前のみ" if case["config"]["scope"] == "pre" else "全夜",
                  scheduled_close=case["scheduled_close"], flat_at=case["flat_at"], observation_end_time=observed_end,
                  positive_decision_negative_fill=actual_bad_fill, snapshot_checks=snapshot_checks,
                  max_long_reserved=case["max_long_reserved"], max_short_reserved=case["max_short_reserved"],
                  **classify_decisions(case))
    return result


def saved_account(scene: dict, case: dict, phase: str | None = None) -> dict:
    """既存対照の全約定又は保存後半を同じ玉単位へ再集計する。

    引数: scene,case(dict)は元保存値、phase(str|None)は対象段。
    返り値: dictは再分類した利益・損失。旧保存値は変更しない。
    """
    source = [event for event in case["events"] or [] if phase is None or event["phase"] == phase]
    normalized = normalize_saved(source)
    end = min(scene["cutoff"], scene["end"])
    result = account(normalized, scene["start"], end)
    if phase is None:
        close_enough(result["net"], case["Gross"], "対照の元総収支")
        assert max(result["max_long"], result["max_short"]) == case["max_per_side"]
        result["unrealized"] = case["Unrealized"]
    else:
        assert result["remaining_lots"] == 0
        result["unrealized"] = 0.0
    if not scene["partial"]:
        assert result["remaining_lots"] == 0
    result["equity"] = result["net"] + result["unrealized"]
    return result


def public_row(scene: dict, target: dict, post: dict | None, control: bool = False) -> dict:
    """対象区間会計と独立保存後半を全夜表示へ整形する。

    引数: scene,target(dict)、post(dict|None)は会計、control(bool)は既存対照か。
    返り値: dictは明細行。未測定内訳を0で埋めない。
    """
    lots = target["lots"] + (post["lots"] if post else [])
    combined = lot_summary(lots)
    unrealized = target["unrealized"] + (post["unrealized"] if post else 0)
    row = dict(combined, session=scene["session"], partial=scene["partial"], unrealized=unrealized,
               equity=combined["net"] + unrealized, lot_details=lots,
               max_long=max(target["max_long"], post["max_long"] if post else 0),
               max_short=max(target["max_short"], post["max_short"] if post else 0),
               first_entry=min((lot["entry_time"] for lot in lots), default=None),
               target=target if not control else None, post=post,
               target_net=target["net"] if not control else None,
               target_entries=target["entries"] if not control else None)
    row["max_per_side"] = max(row["max_long"], row["max_short"])
    for key in ("max_unrealized_loss", "equity_drawdown", "minimum_equity", "held_seconds", "hedged_seconds", "long_cap_seconds", "short_cap_seconds",
                "rejected_notices", "reduced_notices", "cap_rejected_notices", "cap_rejected_quantity", "opposite_rejected_notices",
                "reentry_entries", "reentry_decisions", "reentry_cap_wait_rows", "positive_decision_negative_fill"):
        row[key] = None if control else target[key]
    row["risk_scope"] = "未集計" if control else target["risk_scope"]
    for name in ("trail", "boundary"):
        row[name] = None if control else target[name]
    assert scene["partial"] or row["remaining_lots"] == 0
    if not scene["partial"]:
        close_enough(row["profit"] - row["loss"], row["net"], "全夜の完結玉集計")
    return row


def main() -> None:
    """再生完了後の26場を集計する。金融再生を呼び出さない。

    引数: なし。
    返り値: None。report151.jsonと原会計照合証跡を保存する。
    """
    configs = load(HERE / "configs151.json")
    manifest = load(ROOT / "work/preus149/data/原資料一覧149.json")
    scenes = {scene["session"]: scene for scene in manifest["sessions"]}
    complete = [scene["session"] for scene in manifest["sessions"] if not scene["partial"]]
    assert len(complete) == 25 and len(scenes) == 26
    labels_source = load(ROOT / "work/preus150/report150.json")
    labels = {row["session"]: row["direction"] for row in labels_source["methods"][0]["rows"]}
    frozen_b04 = load(HERE / "data/B04保存会計の指紋151.json")
    b04_hashes = {row["session"]: row["sha256"] for row in frozen_b04["files"]}
    byid = {identifier: {"id": identifier, "description": text, "config": {"id": identifier, "scope": "control"}, "saved_control": True, "rows": []}
            for identifier, text in (("C00", "現行D07・保存対照を新規実約定ID単位で再会計"), ("B04", "米国前の浅い押戻り・保存対照を新規実約定ID単位で再会計"))}
    for config in configs:
        assert config["id"] not in byid
        byid[config["id"]] = {"id": config["id"], "description": config["description"], "config": config, "saved_control": False, "rows": []}
    partial = []
    sources = []
    checks = {"case_count": 0, "snapshots": 0, "complete_case_count": 0, "saved_controls": 0, "post_reuses": 0}
    for session, scene in scenes.items():
        paths = {"new": HERE / "results_go" / f"{session}.json",
                 "C00": ROOT / "work/preus149/results_go" / f"{session}.json",
                 "B04": ROOT / "work/preus150/results_round2" / f"{session}.json",
                 "S04": ROOT / "work/preus149/results_round2" / f"{session}.json"}
        values = {}
        for identifier, path in paths.items():
            record = fingerprint(path)
            if identifier == "B04":
                assert record["sha256"] == b04_hashes[session]
            sources.append(record)
            values[identifier] = load(path)
            assert all(values[identifier]["scene"][key] == scene[key] for key in values[identifier]["scene"])
        saved_post = saved_account(scene, select_case(values["S04"], "S04"), "後半")
        post_events = normalize_saved([e for e in select_case(values["S04"], "S04")["events"] or [] if e["phase"] == "後半"])
        assert {case["config"]["id"] for case in values["new"]["cases"]} == {c["id"] for c in configs}
        rows = []
        for identifier in ("C00", "B04"):
            original = select_case(values[identifier], identifier)
            accounted = saved_account(scene, original)
            row = public_row(scene, accounted, None, True)
            row["legacy_parent_profit"] = original["Profit"]
            row["legacy_parent_loss"] = original["Loss"]
            rows.append((identifier, row))
            checks["saved_controls"] += 1
        for case in values["new"]["cases"]:
            identifier = case["config"]["id"]
            assert case["config"] == byid[identifier]["config"]
            target = target_account(scene, case)
            post = None
            if case["config"]["scope"] == "pre":
                reused = normalize_saved(case["reused_post"]["events"])
                # 理由文字列は保存Goの軽量型で省略されるため、約定の実体だけを比較する。
                fields = ("action", "side", "quantity", "price", "time", "index", "decision_time", "decision_index", "lot_id", "targets", "phase", "owner", "gross")
                assert [[e[k] for k in fields] for e in reused] == [[e[k] for k in fields] for e in post_events]
                post = saved_post
                first_post = min((lot["entry_time"] for lot in post["lots"]), default=None)
                if first_post is not None:
                    assert case["flat_at"] > 0 and case["flat_at"] < first_post
                close_enough(post["net"], case["reused_post"]["gross"], "保存後半の収支")
                checks["post_reuses"] += 1
            row = public_row(scene, target, post)
            close_enough(row["net"], case["combined_gross"], "保存後半を加えた全夜収支")
            rows.append((identifier, row))
            checks["case_count"] += 1
            checks["snapshots"] += target["snapshot_checks"]
            checks["complete_case_count"] += not scene["partial"]
        for identifier, row in rows:
            row["direction"] = "途中" if scene["partial"] else labels[session]
            if scene["partial"]:
                partial.append(dict(id=identifier, **row))
            else:
                byid[identifier]["rows"].append(row)
    for method in byid.values():
        assert [row["session"] for row in method["rows"]] == complete
        method["summary"] = summarize(method["rows"])
        method["by_direction"] = {direction: summarize([row for row in method["rows"] if row["direction"] == direction]) for direction in sorted(set(labels.values()))}
        if not method["saved_control"]:
            method["target_summary"] = summarize([row["target"] for row in method["rows"]])
            for key in ("max_unrealized_loss", "equity_drawdown"):
                method["summary"][key] = max(row[key] for row in method["rows"])
            for key in ("held_seconds", "hedged_seconds", "long_cap_seconds", "short_cap_seconds", "rejected_notices", "cap_rejected_notices", "cap_rejected_quantity", "reentry_entries", "positive_decision_negative_fill"):
                method["summary"][key] = sum(row[key] for row in method["rows"])
            for name in ("trail", "boundary"):
                method["summary"][name] = {key: sum(row[name][key] for row in method["rows"]) for key in ("profit", "loss", "net", "trades", "quantity")}
    report = {"created_at": datetime.now(timezone(timedelta(hours=9))).isoformat(), "methods": list(byid.values()), "partial": partial,
              "definition": "利益・損失は新規実約定IDごとの全返済損益を正負に分類。旧親単位の利益損失とは異なる。途中場の未完結玉の部分実現はopen_lot_realizedへ分離し、netは全実現、equityはnetと最終正常板の含みの合計。Pのリスクと返済理由別内訳は米国前の対象区間だけ。Nは全夜。保存対照の未測定内訳はnull。",
              "validation": dict(checks, expected_complete_nights=25, partial_excluded=True, fee=0, point_value=POINT_VALUE,
                                 all_orders_independently_accounted=True, cap_and_ids_checked=True,
                                 extremes_revalued_from_executions=True, raw_market_replays=0), "sources": sources}
    (HERE / "report151.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({m["id"]: {key: m["summary"][key] for key in ("net", "profit", "loss", "losses", "maxloss", "ex3", "zero_entries")} for m in byid.values()}, ensure_ascii=True))


def self_test() -> None:
    """部分返済の利益・損失を同じ新規IDへ正しく合算する人工会計を確認する。

    引数: なし。
    返り値: None。過去資料の金融再生やレポート生成は行わない。
    """
    common = {"phase": "人工", "owner": "人工", "reason": "人工", "generation": 0}
    events = [dict(common, action="new", side=1, quantity=2, price=100, time=1, index=1, decision_time=0, decision_index=0, lot_id="a", targets=[], gross=0),
              dict(common, action="close", side=-1, quantity=1, price=110, time=2, index=2, decision_time=1, decision_index=1, lot_id="", targets=[{"id": "a", "quantity": 1}], gross=1000),
              dict(common, action="close", side=-1, quantity=1, price=95, time=3, index=3, decision_time=2, decision_index=2, lot_id="", targets=[{"id": "a", "quantity": 1}], gross=-500)]
    result = account(events, 0, 4)
    assert result["profit"] == 500 and result["loss"] == 0 and result["net"] == 500
    assert result["held_seconds"] == 2 and result["closed_lots"] == 1
    partial = account(events[:2], 0, 3)
    assert partial["profit"] == 0 and partial["loss"] == 0 and partial["open_lot_realized"] == 1000
    assert partial["net"] == 1000 and partial["remaining_lots"] == 1
    state = {"index": 2, "bid": 105, "ask": 106, "long": 1, "short": 0, "realized": 1000, "unrealized": 500, "equity": 1500}
    snapshot_account(result["lots"], state)


if __name__ == "__main__":
    main()
