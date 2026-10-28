"""00157の実/CANONICAL台帳を、保存約定だけから独立に配賦する。"""

from collections import defaultdict
import math


def equal(actual: float, expected: float, label: str) -> None:
    """会計値が有限かつ許容差以内で一致することを検査する。

    引数: actual/expected(float)、label(str)は対象名。
    返り値: None。不一致なら停止する。
    """
    if not math.isfinite(actual) or not math.isfinite(expected) or abs(actual - expected) > 1e-5:
        raise AssertionError((label, actual, expected))


def reconcile(ledger: dict, start: float, end: float, finished: dict[str, bool] | None = None) -> dict:
    """保存新規/返済を所有IDへ配賦し、親会計・数量時間・極値断面を検算する。

    引数: ledger(dict)はLedger157、start/end(float)は開始と観測末尾。
    finished(dict[str,bool]|None)は政策側の親終了。Noneは人工例の全実玉返済判定。
    返り値: dictは全親/玉会計、種別分類、数量時間。新しい売買は作らない。
    """
    lots, parents, kinds = {}, {}, {}
    realized = 0.0
    previous_time, previous_index = start, -1
    long_qty = short_qty = 0
    quantity_time = defaultdict(float)
    maxima = defaultdict(int)
    minimum_realized = {"value": 0.0, "time": start, "index": -1, "event": -1}
    checkpoints = defaultdict(list)
    closed_allocation_profit = closed_allocation_loss = 0.0

    def advance(at: float) -> None:
        """約定前から現在まで保持した枚数を時間積分する。

        引数: at(float)は現在時計。返り値: None、外側の積分値を更新。
        """
        nonlocal previous_time
        assert at >= previous_time
        dt = at - previous_time
        quantity_time["held_seconds"] += dt * int(long_qty + short_qty > 0)
        quantity_time["gross_seconds"] += dt * (long_qty + short_qty)
        quantity_time["net_abs_seconds"] += dt * abs(long_qty - short_qty)
        quantity_time["net_signed_seconds"] += dt * (long_qty - short_qty)
        quantity_time["hedged_seconds"] += dt * int(long_qty > 0 and short_qty > 0)
        previous_time = at

    def current_state() -> dict:
        """当時の全実玉と確定額を小さな断面へ保存する。

        引数: なし。返り値: dictは所有ID残数と確定額。
        """
        return {"realized": realized, "lots": {key: lot["remaining"] for key, lot in lots.items() if lot["remaining"]}}

    for number, event in enumerate(ledger.get("Events") or []):
        order = event["Order"]
        index, at, price, quantity = event["FillIndex"], event["FillTime"], event["Price"], order["Quantity"]
        assert isinstance(quantity, int) and quantity > 0
        assert index >= previous_index and index > order["DecisionIndex"]
        assert order["DecisionTime"] <= at
        assert math.isfinite(event["Bid"]) and 0 < event["Bid"] < event["Ask"] < math.inf
        equal(price, event["Ask"] if order["Side"] == 1 else event["Bid"], "約定BBO")
        advance(at)
        if not checkpoints[index]:
            checkpoints[index].append(current_state())
        parent = parents.setdefault(order["Parent"], {"id": order["Parent"], "owner": order["Owner"],
                    "campaign": order["Campaign"], "lots": [], "realized": 0.0,
                    "initial_quantity": 0, "entries": 0, "first_time": None})
        gross = 0.0
        if not order.get("Targets"):
            key = event["HoldID"]
            assert key and key not in lots
            comparison = [lot for lot in lots.values() if lot["parent"] == order["Parent"]
                          and lot["side"] == order["Side"] and lot["kind"] != "cover" and lot["remaining"]]
            compared = sum(lot["remaining"] for lot in comparison) if order["Kind"] != "cover" else 0
            prior_average = sum(lot["remaining"] * lot["price"] for lot in comparison) / compared if compared else None
            new_average = (prior_average * compared + price * quantity) / (compared + quantity) if compared else None
            improvement = order["Side"] * (prior_average - new_average) if compared else None
            if "ComparedQuantity" in event:
                assert event["ComparedQuantity"] == compared
                for field, value in (("PreviousAverage", prior_average), ("NewAverage", new_average),
                                     ("AverageImprovement", improvement)):
                    equal(event[field], value if value is not None else 0, f"新規平均建値/{field}")
            lot = {"id": key, "parent": order["Parent"], "owner": order["Owner"], "kind": order["Kind"],
                   "side": order["Side"], "quantity": quantity, "remaining": quantity, "price": price,
                   "time": at, "index": index, "decision_index": order["DecisionIndex"],
                   "source_id": order.get("SourceID", ""), "support": order.get("Support"),
                   "reason": order["Reason"], "gross": 0.0, "closes": [],
                   "canonical_kinds": order.get("CanonicalKinds") or [],
                   "canonical_order_ids": order.get("CanonicalOrderIDs") or [],
                   "average_comparison": {"compared_quantity": compared, "previous_average": prior_average,
                                          "new_average": new_average, "average_improvement": improvement,
                                          "entry_advantage": order["Side"] * (prior_average - price) if compared else None,
                                          "scope": "当該台帳の同親・同方向・cover以外の残玉"}}
            lots[key] = lot
            parent["lots"].append(key)
            parent["entries"] += 1
            if parent["first_time"] is None:
                parent["first_time"], parent["initial_quantity"] = at, quantity
            if order["Side"] == 1:
                long_qty += quantity
            else:
                assert order["Side"] == -1
                short_qty += quantity
        else:
            assert len(order["Targets"]) == len(event.get("Pieces") or [])
            assert sum(target["Quantity"] for target in order["Targets"]) == quantity
            pieces = {piece["ID"]: piece for piece in event["Pieces"]}
            for target in order["Targets"]:
                lot = lots[target["ID"]]
                q = target["Quantity"]
                assert 0 < q <= lot["remaining"] and lot["side"] == -order["Side"]
                assert lot["parent"] == order["Parent"]
                value = lot["side"] * q * (price - lot["price"]) * 10
                lot["remaining"] -= q
                lot["gross"] += value
                lot["closes"].append({"time": at, "index": index, "price": price, "quantity": q,
                                      "gross": value, "reason": order["Reason"]})
                piece = pieces[lot["id"]]
                assert piece["Quantity"] == q and piece["Kind"] == lot["kind"]
                equal(piece["Entry"], lot["price"], "配賦建値")
                equal(piece["Exit"], price, "配賦返済値")
                equal(piece["Gross"], value, "配賦Gross")
                gross += value
                if value > 0:
                    closed_allocation_profit += value
                else:
                    closed_allocation_loss -= value
                if lot["side"] == 1:
                    long_qty -= q
                else:
                    short_qty -= q
        equal(gross, event["Gross"], "約定Gross")
        realized += gross
        parent["realized"] += gross
        checkpoints[index].append(current_state())
        maxima["long"] = max(maxima["long"], long_qty)
        maxima["short"] = max(maxima["short"], short_qty)
        maxima["gross"] = max(maxima["gross"], long_qty + short_qty)
        maxima["net_abs"] = max(maxima["net_abs"], abs(long_qty - short_qty))
        assert 0 <= long_qty <= 100 and 0 <= short_qty <= 100, "実約定片側上限"
        if realized < minimum_realized["value"]:
            minimum_realized = {"value": realized, "time": at, "index": index, "event": number}
        previous_index = index
    advance(end)
    equal(realized, ledger["Realized"], "台帳確定")
    assert set(lots) == set(ledger.get("Lots") or {})
    mark = ledger["Last"]
    for key, lot in lots.items():
        saved = ledger["Lots"][key]
        assert lot["remaining"] == saved["Remaining"] and lot["quantity"] == saved["Quantity"]
        equal(lot["price"], saved["Entry"], "新規実建値")
        equal(lot["gross"], saved["Gross"], "玉確定")
        price = mark["Bid"] if lot["side"] == 1 else mark["Ask"]
        lot["unrealized"] = lot["side"] * lot["remaining"] * (price - lot["price"]) * 10
        group = kinds.setdefault(lot["kind"], {"entries": 0, "quantity": 0, "remaining": 0,
                                "realized": 0.0, "unrealized": 0.0, "wins": 0, "losses": 0})
        group["entries"] += 1
        group["quantity"] += lot["quantity"]
        group["remaining"] += lot["remaining"]
        group["realized"] += lot["gross"]
        group["unrealized"] += lot["unrealized"]
        group["wins"] += int(lot["remaining"] == 0 and lot["gross"] > 0)
        group["losses"] += int(lot["remaining"] == 0 and lot["gross"] < 0)
    for parent in parents.values():
        parent["remaining"] = sum(lots[key]["remaining"] for key in parent["lots"])
        parent["unrealized"] = sum(lots[key]["unrealized"] for key in parent["lots"])
        parent["equity"] = parent["realized"] + parent["unrealized"]
        parent["completed"] = finished[parent["id"]] if finished is not None else parent["remaining"] == 0
        assert not parent["completed"] or parent["remaining"] == 0
        saved = ledger["Parents"][parent["id"]]
        equal(parent["realized"], saved["Realized"], "親確定")
        equal(parent["unrealized"], saved["Unrealized"], "親含み")
    unrealized = sum(lot["unrealized"] for lot in lots.values())
    equal(unrealized, mark["Unrealized"], "末尾含み")
    equal(realized + unrealized, mark["Equity"], "末尾時価")
    risk = ledger["Risk"]
    for own, saved in (("held_seconds", "HeldSeconds"), ("gross_seconds", "GrossSeconds"),
                       ("net_abs_seconds", "NetAbsSeconds"), ("net_signed_seconds", "NetSignedSeconds"),
                       ("hedged_seconds", "HedgedSeconds")):
        equal(quantity_time[own], risk[saved], f"数量時間/{own}")
    for own, saved in (("long", "MaxLong"), ("short", "MaxShort"), ("gross", "MaxGross"), ("net_abs", "MaxNetAbs")):
        if saved not in risk:
            continue
        equal(maxima[own], risk[saved], f"最大枚数/{own}")
    if "MinimumRealized" in risk:
        equal(minimum_realized["value"], risk["MinimumRealized"], "最低確定")
    for name in ("MinimumAt", "PeakAt", "DDFrom", "DDTo", "MinimumRealizedAt", "MinimumUnrealizedAt"):
        if name not in risk:
            continue
        snapshot = risk[name]
        if snapshot["Index"] < 0 or snapshot["Time"] == 0:
            equal(snapshot["Equity"], 0, "当場開始時価")
            continue
        valued = 0.0
        for key, q in (snapshot.get("Lots") or {}).items():
            lot = lots[key]
            assert lot["index"] <= snapshot["Index"] and 0 <= q <= lot["quantity"]
            price = snapshot["Bid"] if lot["side"] == 1 else snapshot["Ask"]
            valued += lot["side"] * q * (price - lot["price"]) * 10
        equal(valued, snapshot["Unrealized"], f"極値含み/{name}")
        equal(valued + snapshot["Realized"], snapshot["Equity"], f"極値時価/{name}")
    equal(risk["DDFrom"]["Equity"] - risk["DDTo"]["Equity"], risk["MaxDD"], "DD起終点")
    profit = sum(parent["realized"] for parent in parents.values() if parent["completed"] and parent["realized"] > 0)
    loss = -sum(parent["realized"] for parent in parents.values() if parent["completed"] and parent["realized"] < 0)
    open_realized = sum(parent["realized"] for parent in parents.values() if not parent["completed"])
    equal(profit - loss + open_realized, realized, "完結/未完親")
    return {"profit": profit, "loss": loss, "net": realized, "open_parent_realized": open_realized,
            "unrealized": unrealized, "equity": realized + unrealized, "parents": list(parents.values()),
            "lots": list(lots.values()), "entry_types": kinds, "entries": len(lots),
            "remaining_qty": long_qty + short_qty, "long_qty": long_qty, "short_qty": short_qty,
            "quantities": {"max": dict(maxima), **dict(quantity_time)},
            "min_realized": minimum_realized,
            "allocation_profit": closed_allocation_profit, "allocation_loss": closed_allocation_loss}
