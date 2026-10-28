"""研究153の保存判断と実約定を独立再会計し、数量対照・場別成績・損失箇所を整理する。"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
JST = timezone(timedelta(hours=9))
BINS = [(0.25, 0.5), (0.5, 1), (1, 1.5), (1.5, 2.5), (2.5, math.inf)]


def read(path: Path):
    """保存JSONを読み取る。

    引数: path(Path)は入力資料。
    返り値: dict又はlistは復号値。原資料や会計へ書き込まない。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fingerprint(path: Path) -> dict:
    """再集計根拠の全文指紋を記録する。

    引数: path(Path)は保存資料。
    返り値: dictは相対位置・サイズ・SHA256。
    """
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha}


def equal(actual: float, expected: float, label: str) -> None:
    """独立計算と保存数値の有限性・一致を確認する。

    引数: actual/expected(float)、label(str)は検査箇所。
    返り値: None。不一致では集計を停止する。
    """
    assert math.isfinite(actual) and math.isfinite(expected), label
    assert math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-5), (label, actual, expected)


def clock(value: float) -> str:
    """価格時計を日本時間の明示文字列へ変換する。

    引数: value(float)はUNIX秒。
    返り値: strはISO時計。未観測0は空欄。
    """
    return datetime.fromtimestamp(value, JST).isoformat() if value else ""


def slope_bin(value: float) -> str:
    """結果前に固定した傾き絶対値区間へ分類する。

    引数: value(float)はbp/分。
    返り値: strは下限以上・上限未満の分類名。
    """
    value = abs(value)
    for lower, upper in BINS:
        if lower <= value < upper:
            return f"{lower:g}〜{upper:g}" if math.isfinite(upper) else f"{lower:g}以上"
    return "0.25未満"


def describe(config: dict) -> str:
    """固定設定を簡潔な日本語へ変換する。

    引数: config(dict)は保存設定。
    返り値: strは入口枚数と出口の説明。
    """
    allocation = {"entry": "入口だけ傾き比例枚数", "dynamic": "保有中も傾き比例で増減", "fixed1": "固定1枚", "fixed10": "固定10枚"}[config["allocation"]]
    exit_name = {"T": "利益追尾", "Z": "利益追尾＋傾き反転", "D": "利益追尾＋傾き反転・増勢後の半減"}[config["exit"]]
    return f"{config['window_seconds']:g}秒の時間加重平均を{config['lag_seconds']:g}秒前と比較。{allocation}、{exit_name}で返済。"


def totals(rows: list[dict]) -> dict:
    """完了した場の会計と通常損失の深さを集約する。

    引数: rows(list[dict])は対象場だけの行。
    返り値: dictは合計・勝敗・損失規模・上位3場除外値。
    """
    profits, losses = sum(x["profit"] for x in rows), sum(x["loss"] for x in rows)
    positive = [x["net"] for x in rows if x["net"] > 0]
    negative = [-x["net"] for x in rows if x["net"] < 0]
    top = sorted((x["net"] for x in rows if x["net"] > 0), reverse=True)[:3]
    formal = sum(x.get("formal_seconds", 0) for x in rows)
    return {"sessions": len(rows), "profit": profits, "loss": losses, "net": sum(x["net"] for x in rows),
            "pf": profits/losses if losses else None, "profit_fraction": profits/(profits+losses) if profits+losses else None,
            "wins": len(positive), "losses": len(negative), "flat": sum(x["net"] == 0 for x in rows),
            "no_trade": sum(x["entries"] == 0 for x in rows), "maxloss": max(negative, default=0),
            "avgloss": mean(negative) if negative else 0, "medianloss": median(negative) if negative else 0,
            "avgwin": mean(positive) if positive else 0, "medianwin": median(positive) if positive else 0,
            "ex3": sum(x["net"] for x in rows)-sum(top), "top3_positive_sum": sum(top),
            "entries": sum(x["entries"] for x in rows), "additions": sum(x["additions"] for x in rows),
            "reductions": sum(x["reductions"] for x in rows), "parent_profit": sum(x["parent_profit"] for x in rows),
            "parent_loss": sum(x["parent_loss"] for x in rows), "entry_quantity": sum(x["entry_quantity"] for x in rows),
            "held_seconds": sum(x["held_seconds"] for x in rows), "held_rate": sum(x["held_seconds"] for x in rows)/formal if formal else 0,
            "equity_drawdown": max((x["equity_drawdown"] for x in rows), default=0),
            "max_qty": max((x["max_qty"] for x in rows), default=0)}


def event_reference(event: dict) -> dict:
    """判断と約定の原行・価格・傾きを失わない小さな参照を作る。

    引数: event(dict)は保存Event。
    返り値: dictは読取診断用の確定参照。
    """
    order = event["Order"]
    return {"order_id": order["ID"], "parent_id": order["ParentID"], "action": order["Action"], "reason": order["Reason"],
            "side": order["Side"], "quantity": order["Quantity"], "decision_at": clock(order["DecisionTime"]),
            "decision_time": order["DecisionTime"], "decision_index": order["DecisionIndex"], "decision_line": order.get("DecisionLine"),
            "decision_bid": order.get("DecisionBid"), "decision_ask": order.get("DecisionAsk"),
            "ma": order["Feature"]["MA"], "previous_ma": order["Feature"]["Previous"], "slope": order["Feature"]["Slope"],
            "fill_at": clock(event["FillTime"]), "fill_time": event["FillTime"], "fill_index": event["FillIndex"], "fill_line": event["FillLine"],
            "fill_price": event["Price"], "fill_bid": event.get("FillBid"), "fill_ask": event.get("FillAsk"), "gross": event["Gross"],
            "entry_slope": order["EntrySlope"], "peak_slope": order["PeakSlope"], "peak_gain_points": order["PeakGain"]}


def verify_marks(events: list[dict], case: dict, multiplier: float) -> dict:
    """約定を再生せず既約定の所有残数を積み上げ、保存時価と極値地点を検算する。

    引数: events(list[dict])は保存約定、case(dict)は場会計、multiplier(float)は商品倍率。
    返り値: dictは検算した地点数とサンプル上の最大DD。売買判断は実施しない。
    """
    snapshots = list(case.get("Snapshots") or [])
    extrema = [(key, case.get(key)) for key in ("MaximumDrawdownAt", "MaximumDrawdownFrom", "MinimumEquityAt", "MinimumUnrealizedAt", "FinalSnapshot")]
    marks = [(f"snapshot:{i}", value) for i, value in enumerate(snapshots)] + [(key, value) for key, value in extrema if value and value.get("Time")]
    active, pointer, lot_sequence, realized = {}, 0, 0, 0.0
    peak, sample_dd = 0.0, 0.0
    for name, mark in sorted(marks, key=lambda item: item[1]["Index"]):
        while pointer < len(events) and events[pointer]["FillIndex"] <= mark["Index"]:
            event = events[pointer]
            order = event["Order"]
            if order["Action"] == "new":
                lot_sequence += 1
                active[lot_sequence] = {"side": order["Side"], "quantity": order["Quantity"], "price": event["Price"]}
            else:
                for target in event["Closed"]:
                    lot = active[target["LotID"]]
                    lot["quantity"] -= target["Quantity"]
                    realized += lot["side"]*target["Quantity"]*(event["Price"]-lot["price"])*multiplier
                    if lot["quantity"] == 0:
                        del active[target["LotID"]]
            pointer += 1
        held = sum(lot["quantity"] for lot in active.values())
        signed = sum(lot["side"]*lot["quantity"] for lot in active.values())
        assert held == mark["Quantity"], (case["Session"], name, "時価枚数")
        assert (0 if signed == 0 else 1 if signed > 0 else -1) == mark["Side"], (case["Session"], name, "時価方向")
        unrealized = sum(lot["side"]*lot["quantity"]*((mark["Bid"] if lot["side"] > 0 else mark["Ask"])-lot["price"])*multiplier for lot in active.values())
        equal(realized, mark["Realized"], name+"確定")
        equal(unrealized, mark["Unrealized"], name+"含み")
        equal(realized+unrealized, mark["Equity"], name+"時価")
        peak = max(peak, mark["Equity"])
        sample_dd = max(sample_dd, peak-mark["Equity"])
    if case["MaximumDrawdown"] > 0:
        equal(case["MaximumDrawdownFrom"]["Equity"]-case["MaximumDrawdownAt"]["Equity"], case["MaximumDrawdown"], "最大DDの起点と終点")
    if case["MinimumEquity"] < 0:
        equal(case["MinimumEquityAt"]["Equity"], case["MinimumEquity"], "最低時価")
    if case["MinimumUnrealized"] < 0:
        equal(case["MinimumUnrealizedAt"]["Unrealized"], case["MinimumUnrealized"], "最低含み")
    assert sample_dd <= case["MaximumDrawdown"]+1e-5, "サンプルDDが保存全行DDを超過"
    return {"checked_marks": len(marks), "sample_drawdown": sample_dd}


def account_case(scene: dict, case: dict, source: str) -> tuple[dict, dict]:
    """新規約定からlot・FIFO配賦・親・保有秒を独立構築して保存会計と照合する。

    引数: scene/case(dict)は保存時計と会計、source(str)は根拠ファイル。
    返り値: tuple[dict,dict]は表示行と内部分析。戦略条件の再評価を行わない。
    """
    multiplier = 100.0 if case["Symbol"] == "NK225" else 1000.0
    equal(case["PointValue"], multiplier, "商品倍率")
    events = case.get("Events") or []
    lots, parents, open_ids, order_ids = {}, {}, [], set()
    quantity, side, maximum, held, quantity_seconds = 0, 0, 0, 0.0, 0.0
    previous_time, previous_index = scene["start"], -1
    gross = profit = loss = 0.0
    additions = reductions = 0
    phases = {"前": {"profit": 0.0, "loss": 0.0, "net": 0.0}, "後": {"profit": 0.0, "loss": 0.0, "net": 0.0}}
    reasons = defaultdict(lambda: {"events": 0, "quantity": 0, "profit": 0.0, "loss": 0.0, "net": 0.0})
    for event in events:
        order = event["Order"]
        count, at = order["Quantity"], event["FillTime"]
        assert order["ID"] not in order_ids and count > 0 and isinstance(count, int)
        order_ids.add(order["ID"])
        assert event["FillIndex"] > order["DecisionIndex"] and event["FillIndex"] > previous_index
        assert scene["start"] <= order["DecisionTime"] <= at <= scene["end"] and at >= previous_time
        if scene["partial"]:
            assert at < scene["cutoff"]
        held += (at-previous_time)*(quantity > 0)
        quantity_seconds += (at-previous_time)*quantity
        previous_time, previous_index = at, event["FillIndex"]
        if "FillBid" in event:
            assert event["FillBid"] > 0 and event["FillAsk"] > event["FillBid"]
            equal(event["Price"], event["FillAsk"] if order["Side"] > 0 else event["FillBid"], "次板の売買側")
        pid = order["ParentID"]
        reference = event_reference(event)
        decision_price = order.get("DecisionAsk") if order["Side"] > 0 else order.get("DecisionBid")
        reference["adverse_fill_yen"] = order["Side"]*(event["Price"]-decision_price)*count*multiplier if decision_price and math.isfinite(decision_price) and decision_price > 0 else None
        if order["Action"] == "new":
            assert order["Feature"]["Known"] and abs(order["Feature"]["Slope"]) >= .25-1e-12
            if quantity == 0:
                assert pid not in parents
                side = order["Side"]
                parents[pid] = {"id": pid, "side": side, "entry": reference, "exit": None, "events": [], "net": 0.0,
                                "entry_quantity": count, "all_entry_quantity": 0, "remaining": 0, "entry_slope": abs(order["Feature"]["Slope"]),
                                "entry_time": at, "close_time": None}
            else:
                assert pid in parents and order["Side"] == side
                additions += 1
            lid = len(lots)+1
            lots[lid] = {"id": lid, "parent_id": pid, "side": side, "initial": count, "remaining": count, "price": event["Price"],
                         "at": at, "realized": 0.0, "slope": abs(order["Feature"]["Slope"]), "slope_bin": slope_bin(order["Feature"]["Slope"]),
                         "entry": reference}
            open_ids.append(lid)
            parents[pid]["all_entry_quantity"] += count
            quantity += count
            equal(event["Gross"], 0, "新規確定利益0")
        else:
            assert order["Action"] == "close" and quantity >= count and order["Side"] == -side and pid in parents
            remaining, event_gross = count, 0.0
            expected_targets = []
            for lid in open_ids:
                lot = lots[lid]
                take = min(lot["remaining"], remaining)
                if not take:
                    continue
                allocation = side*take*(event["Price"]-lot["price"])*multiplier
                lot["remaining"] -= take
                lot["realized"] += allocation
                event_gross += allocation
                profit += max(0, allocation)
                loss += max(0, -allocation)
                expected_targets.append((lid, take, lot["price"], event["Price"], allocation))
                remaining -= take
                if not remaining:
                    break
            assert remaining == 0 and len(expected_targets) == len(event["Closed"])
            for expected, actual in zip(expected_targets, event["Closed"]):
                assert expected[:2] == (actual["LotID"], actual["Quantity"]), "FIFO返済順"
                for value, key in zip(expected[2:], ("EntryPrice", "ExitPrice", "Gross")):
                    equal(value, actual[key], "返済配賦"+key)
                if scene["kind"] == "Night":
                    target = phases["前" if at < scene["us_open"] else "後"]
                    target["profit"] += max(0, expected[4]); target["loss"] += max(0, -expected[4]); target["net"] += expected[4]
                reason = reasons[order["Reason"]]
                reason["quantity"] += expected[1]; reason["profit"] += max(0, expected[4]); reason["loss"] += max(0, -expected[4]); reason["net"] += expected[4]
            reasons[order["Reason"]]["events"] += 1
            equal(event_gross, event["Gross"], "返済実現")
            gross += event_gross
            parents[pid]["net"] += event_gross
            quantity -= count
            if quantity:
                reductions += 1
            else:
                parents[pid]["exit"], parents[pid]["close_time"] = reference, at
                side = 0
            open_ids = [lid for lid in open_ids if lots[lid]["remaining"]]
        parents[pid]["remaining"] = quantity
        parents[pid]["events"].append(reference)
        maximum = max(maximum, quantity)
        assert 0 <= quantity <= 10
    observation_end = case["ObservationEnd"]
    assert observation_end >= previous_time
    held += (observation_end-previous_time)*(quantity > 0)
    quantity_seconds += (observation_end-previous_time)*quantity
    equal(held, case["HeldSeconds"], "実保有秒")
    equal((observation_end if case["Partial"] else scene["end"])-scene["start"], case["EligibleSeconds"], "評価分母の秒")
    for value, key in ((gross, "Gross"), (profit, "Profit"), (loss, "Loss"), (maximum, "MaxQuantity")):
        equal(value, case[key], key)
    assert len(lots) == len(case.get("Lots") or [])
    for stored in case.get("Lots") or []:
        lot = lots[stored["ID"]]
        for key, other in (("ParentID", "parent_id"), ("Side", "side"), ("Initial", "initial"), ("Quantity", "remaining"), ("Price", "price"), ("At", "at"), ("Realized", "realized")):
            equal(stored[key], lot[other], "lot "+key)
    for stored in (case.get("Parents") or []) + ([case["open_parent"]] if case.get("open_parent") else []):
        parent = parents[stored["ID"]]
        equal(parent["net"], stored["Realized"], "親の実現")
        equal(parent["entry_slope"], stored["EntrySlope"], "親の入口傾き")
        parent.update(peak_gain_points=stored["PeakGain"], peak_gain_at=clock(stored["PeakGainTime"]),
                      worst_gain_points=stored["WorstGain"], worst_gain_at=clock(stored["WorstGainTime"]),
                      last_slope=stored["LastSlope"], last_slope_at=clock(stored["LastSlopeTime"]),
                      peak_slope=stored["PeakSlope"], strengthened=stored["Strengthened"],
                      initial_anchor=stored["Anchor"], exit_reason=stored["ExitReason"],
                      crossed_us=scene["kind"] == "Night" and parent["entry_time"] < scene["us_open"] <= (parent["close_time"] or observation_end))
    assert len(parents) == len(case.get("Parents") or []) + bool(case.get("open_parent"))
    assert case["MaxReserved"] <= 10
    if not case["Partial"]:
        assert quantity == 0 and case.get("Pending") is None and case["FlatAt"] > 0
    marks = verify_marks(events, case, multiplier)
    last_quote = case["last_normal_quote"]
    final = case.get("FinalSnapshot") or (case.get("Snapshots") or [{}])[-1]
    bid, ask = last_quote.get("Bid", final.get("Bid")), last_quote.get("Ask", final.get("Ask"))
    assert bid is not None and ask is not None, "最終気配の記録がありません"
    unrealized = sum(lot["side"]*lot["remaining"]*((bid if lot["side"] > 0 else ask)-lot["price"])*multiplier for lot in lots.values())
    equal(unrealized, case["Unrealized"], "最終含み")
    closing = case.get("ClosingMid", (bid+ask)/2)
    equal(closing, (bid+ask)/2, "終端正常中値")
    middle_direction = "上昇" if closing > case["OpeningMid"] else "下落" if closing < case["OpeningMid"] else "横ばい"
    qualified = scene["qualification"][case["Symbol"]]["book"]
    opening_last, closing_last = qualified["first"]["last"], qualified["last"]["last"]
    direction = "上昇" if closing_last > opening_last else "下落" if closing_last < opening_last else "横ばい"
    completed = [value for value in parents.values() if value["remaining"] == 0]
    parent_profit = sum(max(0, value["net"]) for value in completed)
    parent_loss = sum(max(0, -value["net"]) for value in completed)
    open_realized = sum(value["net"] for value in parents.values() if value["remaining"])
    equal(parent_profit-parent_loss+open_realized, gross, "親別と配賦別の純収支")
    formal = scene["end"]-scene["start"]
    row = {"session": case["Session"], "kind": case["Kind"], "symbol": case["Symbol"], "partial": case["Partial"],
           "profit": profit, "loss": loss, "net": gross, "parent_profit": parent_profit, "parent_loss": parent_loss,
           "open_parent_realized": open_realized, "entries": len(parents), "additions": additions, "reductions": reductions,
           "entry_quantity": sum(value["initial"] for value in lots.values()), "max_qty": maximum, "max_reserved": case["MaxReserved"],
           "held_seconds": held, "formal_seconds": formal, "held_rate": held/formal, "observation_seconds": observation_end-scene["start"],
           "eligible_seconds": case["EligibleSeconds"],
           "quantity_seconds": quantity_seconds, "known_seconds": case["KnownSeconds"], "first_known_at": clock(case.get("FirstKnownAt", 0)),
           "equity_drawdown": case["MaximumDrawdown"], "minimum_equity": case["MinimumEquity"], "minimum_unrealized": case["MinimumUnrealized"],
           "unrealized": unrealized, "equity": gross+unrealized, "remaining_qty": quantity, "pending": case.get("Pending"),
           "direction": direction, "direction_source": "資格済みの当場最初Lastと最後Last。完了場の最後は終了前6分以内の代理で正式終値ではない。途中場は観測末尾の代理。",
           "opening_last": opening_last, "closing_last": closing_last, "opening_last_at": qualified["first"]["time"], "closing_last_at": qualified["last"]["time"],
           "opening_mid": case["OpeningMid"], "closing_mid": closing, "mid_direction": middle_direction,
           "market_change_bp": (closing_last/opening_last-1)*10000, "mid_market_change_bp": (closing/case["OpeningMid"]-1)*10000,
           "first_entry": clock(case["FirstEntry"]), "last_entry": clock(case["LastEntry"]), "flat_at": clock(case["FlatAt"]),
           "observation_end": clock(observation_end), "exit_reasons": dict(reasons), "us_by_close_time": phases if scene["kind"] == "Night" else None,
           "us_crossing_parents": sum(value.get("crossed_us", False) for value in parents.values()),
           "source": source, "worst_parents": sorted((value for value in completed if value["net"] < 0), key=lambda value: value["net"])[:3]}
    slope_groups = defaultdict(lambda: {"lots": 0, "quantity": 0, "net": 0.0, "unit_sum_yen": 0.0, "unit_sum_points": 0.0, "winning_lots": 0, "losing_lots": 0})
    for lot in lots.values():
        if lot["remaining"]:
            continue
        group = slope_groups[lot["slope_bin"]]
        group["lots"] += 1; group["quantity"] += lot["initial"]; group["net"] += lot["realized"]
        group["unit_sum_yen"] += lot["realized"]/lot["initial"]; group["unit_sum_points"] += lot["realized"]/(lot["initial"]*multiplier)
        group["winning_lots"] += lot["realized"] > 0; group["losing_lots"] += lot["realized"] < 0
    return row, {"slope_groups": dict(slope_groups), "parent_count": len(parents), "lots": len(lots), "events": len(events), "marks": marks,
                 "parent_units": {pid: {"quantity": value["entry_quantity"], "net": value["net"], "slope": value["entry_slope"]} for pid, value in parents.items()}}


# ----------------------------------------
# 数量だけの違いと、独立した場単位の診断を集約する。

def route_signature(case: dict) -> list[dict]:
    """数量・金額を除いた全判断と約定の比較列を作る。

    引数: case(dict)は一条件の保存結果。
    返り値: list[dict]は原行、時計、価格、方向、指標、理由の完全な経路。
    """
    result = []
    for event in case.get("Events") or []:
        order = dict(event["Order"])
        del order["Quantity"]
        result.append({"order": order, "fill_index": event["FillIndex"], "fill_line": event["FillLine"],
                       "fill_time": event["FillTime"], "price": event["Price"], "bid": event["FillBid"], "ask": event["FillAsk"]})
    if case.get("Pending"):
        pending = dict(case["Pending"])
        del pending["Quantity"]
        result.append({"pending": pending})
    return result


def compare_quantities(cases: dict, internals: dict, session: str, symbol: str) -> dict:
    """同じ入口出口を通った固定枚数と比例枚数の数量効果だけを照合する。

    引数: cases/internals(dict)はID別保存結果と独立親会計、session/symbol(str)は対象。
    返り値: dictは経路一致と枚数乗数の検査結果。不一致では止まる。
    """
    baseline = cases["F01"]
    signature = route_signature(baseline)
    for identity in ("M09", "F10"):
        assert route_signature(cases[identity]) == signature, (session, symbol, identity, "数量以外の判断経路が相違")
    for name in ("Gross", "Profit", "Loss", "Unrealized", "MaximumDrawdown", "MinimumEquity", "MinimumUnrealized"):
        equal(cases["F10"][name], baseline[name]*10, "固定10枚="+name+"×10")
    unit = internals["F01"]["parent_units"]
    variable = internals["M09"]["parent_units"]
    fixed = internals["F10"]["parent_units"]
    assert unit.keys() == variable.keys() == fixed.keys()
    for pid, parent in unit.items():
        assert parent["quantity"] == 1 and fixed[pid]["quantity"] == 10
        quantity = 1+math.floor(9*max(0, min(1, (parent["slope"]-.25)/2.25)))
        assert variable[pid]["quantity"] == quantity
        equal(variable[pid]["net"], parent["net"]*quantity, "比例親の数量乗数")
        equal(fixed[pid]["net"], parent["net"]*10, "固定親の数量乗数")
    return {"session": session, "symbol": symbol, "partial": baseline["Partial"], "matched": True,
            "events": len(baseline.get("Events") or []), "parents": len(unit),
            "F01_net": baseline["Gross"], "F10_net": cases["F10"]["Gross"], "M09_net": cases["M09"]["Gross"],
            "F01_unrealized": baseline["Unrealized"], "F10_unrealized": cases["F10"]["Unrealized"],
            "M09_unrealized": cases["M09"]["Unrealized"]}


def merge_groups(destination: dict, source: dict) -> None:
    """場別の固定区間に対応する十分統計量だけを加える。

    引数: destination/source(dict)は同一項目の集計領域と追加値。
    返り値: None。各場や各玉が独立標本という仮定は加えない。
    """
    for key, values in source.items():
        if key not in destination:
            destination[key] = {name: 0 for name in values}
        for name, value in values.items():
            destination[key][name] += value


def finish_slopes(groups: dict, multiplier: float) -> list[dict]:
    """傾き区間の枚数加重平均と玉単純平均を区別して作る。

    引数: groups(dict)は完結新規玉の集計、multiplier(float)は商品倍率。
    返り値: list[dict]は固定した全区間。取引なしの平均はNone。
    """
    result = []
    for label in ["0.25未満"]+[slope_bin(lower) for lower, _ in BINS]:
        group = groups.get(label, {})
        n, qty = group.get("lots", 0), group.get("quantity", 0)
        row = {"bin": label, **group, "lots": n, "quantity": qty,
               "average_per_lot_unit_yen": group.get("unit_sum_yen", 0)/n if n else None,
               "average_per_lot_unit_points": group.get("unit_sum_points", 0)/n if n else None,
               "quantity_weighted_unit_yen": group.get("net", 0)/qty if qty else None,
               "quantity_weighted_unit_points": group.get("net", 0)/(qty*multiplier) if qty else None,
               "winning_lot_rate": group.get("winning_lots", 0)/n if n else None}
        result.append(row)
    return result


def summarize_method(method: dict) -> None:
    """同一手法の全場・昼夜・方向別・返済時計別を整理する。

    引数: method(dict)は完了場だけを含む表示対象。
    返り値: None。rowsは時計順に並べ、既知途中は混ぜない。
    """
    rows = method["rows"]
    rows.sort(key=lambda x: x["session"])
    assert len(rows) == 51 and not any(row["partial"] for row in rows)
    cumulative = 0
    for row in rows:
        cumulative += row["net"]
        row["cumulative"] = cumulative
    method["summary"] = totals(rows)
    for key, predicate in (("day", lambda x: x["kind"] == "Day"), ("night", lambda x: x["kind"] == "Night"),
                           ("up", lambda x: x["direction"] == "上昇"), ("down", lambda x: x["direction"] == "下落"),
                           ("flat", lambda x: x["direction"] == "横ばい")):
        method[key] = totals([row for row in rows if predicate(row)])
    method["kind_direction"] = {f"{kind}_{direction}": totals([row for row in rows if row["kind"] == kind and row["direction"] == direction])
                                for kind in ("Day", "Night") for direction in ("上昇", "下落", "横ばい")}
    by_time = {"前": {"profit": 0.0, "loss": 0.0, "net": 0.0}, "後": {"profit": 0.0, "loss": 0.0, "net": 0.0}}
    for row in rows:
        if row["us_by_close_time"]:
            for phase in by_time:
                for key in by_time[phase]:
                    by_time[phase][key] += row["us_by_close_time"][phase][key]
    equal(sum(v["net"] for v in by_time.values()), method["night"]["net"], "米国前後の返済時計分類")
    method["us_by_close_time"] = by_time
    method["us_crossing_parents"] = sum(row["us_crossing_parents"] for row in rows)
    method["worst_sessions"] = sorted((row for row in rows if row["net"] < 0), key=lambda row: row["net"])[:3]
    reasons = {}
    for row in rows:
        merge_groups(reasons, row["exit_reasons"])
    method["exit_reasons"] = reasons


def write_analysis(report: dict) -> None:
    """検算済み集計と原判断参照を短い読み物にまとめる。

    引数: report(dict)は確定した集計。
    返り値: None。傾向と原因候補を分け、未実験の修正を成功扱いしない。
    """
    lines = ["# 移動平均の傾きと比例枚数の検証153", "",
             "51完了場を商品ごとに26条件で比較。日経mini・TOPIXminiとも片方向10枚まで、手数料0。既知の10月26日ナイト途中は全場集計から除外。",
             "利益・損失は返済FIFO配賦ごと。部分利確後に別の返済で損失が出る場合があるため、完結した方向親全体の利益・損失も別掲した。",
             "当場の上昇・下落は、資格済みの最初Lastと終了前6分以内の最終Last代理で判定した。正式終値ではなく、判断入力には使用しない。",
             "原板価格時計による時間加重平均であり、画像の角度や5分足の見た目ではない。各玉・各場の結果は独立標本として統計的な保証に変換していない。", ""]
    for symbol in ("NK225", "TOPIX"):
        methods = [method for method in report["methods"] if method["symbol"] == symbol]
        lines += [f"## {symbol}：全26条件", "", "|ID|全場収支|黒字/赤字/無取引|利益/損失比|昼収支|夜収支|上昇場収支|下落場収支|上位3黒字場除外|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for method in methods:
            s = method["summary"]
            pf = f"{s['pf']:.2f}" if s["pf"] is not None else "—"
            lines.append(f"|{method['id']}|{s['net']:,.0f}|{s['wins']}/{s['losses']}/{s['no_trade']}|{pf}|{method['day']['net']:,.0f}|{method['night']['net']:,.0f}|{method['up']['net']:,.0f}|{method['down']['net']:,.0f}|{s['ex3']:,.0f}|")
        lines += ["", "### 数量だけの対照", "", "M09・F01・F10は入口出口の全原行・時計・価格・方向・指標・理由が同一であることを照合した。F10の確定/含み/時価DDはF01の10倍。M09の違いは入口枚数だけである。", ""]
        selected = {method["id"]: method for method in methods}
        for identity in ("F01", "M09", "F10"):
            s = selected[identity]["summary"]
            lines.append(f"- {identity}：収支{s['net']:,.0f}円、赤字{s['losses']}/51場、最大赤字{s['maxloss']:,.0f}円。")
        lines += ["", "### 固定1枚で見る、入口傾きと1枚当たり確定損益", "", "|傾き絶対値bp/分|完結玉数|平均pt/枚|玉別黒字率|", "|---|---:|---:|---:|"]
        for group in selected["F01"]["slope_groups"]:
            if not group["lots"]:
                continue
            lines.append(f"|{group['bin']}|{group['lots']}|{group['average_per_lot_unit_points']:.3f}|{group['winning_lot_rate']:.1%}|")
        lines += ["", "傾き区間は実測前に固定した。これは既に発注した玉に条件付けた記述であり、その区間を新たな入口へ採用した成績ではない。", ""]
        best = max(methods, key=lambda method: (method["summary"]["net"], -method["summary"]["losses"]))
        identities = list(dict.fromkeys(["M09", best["id"]]))
        for identity in identities:
            method = selected[identity]
            lines += [f"### {identity}の赤字上位3場と具体箇所", ""]
            for row in method["worst_sessions"]:
                lines.append(f"- **{row['session']}**：収支{row['net']:,.0f}円、{row['direction']}場、初回{row['entries']}回、追加{row['additions']}回、縮小{row['reductions']}回。")
                for parent in row["worst_parents"]:
                    entry, exit_event = parent["entry"], parent["exit"]
                    side = "買い" if parent["side"] > 0 else "売り"
                    lines.append(f"  - 親{parent['id']} {side}：判断{entry['decision_at'][11:19]}（原行{entry['decision_line']}）→約定{entry['fill_at'][11:19]} {entry['fill_price']:g}、入口傾き{entry['slope']:+.3f}bp/分。最大順行{parent['peak_gain_points']:g}pt（{parent['peak_gain_at'][11:19]}）、最大逆行{parent['worst_gain_points']:g}pt（{parent['worst_gain_at'][11:19]}）。{exit_event['fill_at'][11:19]} {exit_event['fill_price']:g}で完結、{parent['net']:,.0f}円。返済理由：{parent['exit_reason']}。")
            lines.append("")
        lines += ["### 返済理由の実測（M09）", "", "|理由|返済回数|利益|損失|収支|", "|---|---:|---:|---:|---:|"]
        for reason, value in sorted(selected["M09"]["exit_reasons"].items(), key=lambda item: item[1]["net"]):
            lines.append(f"|{reason}|{value['events']}|{value['profit']:,.0f}|{value['loss']:,.0f}|{value['net']:,.0f}|")
        lines.append("")
    lines += ["## 検査と解釈の限界", "",
              f"- 完了{report['audit']['complete_cases']}条件場、途中{report['audit']['partial_cases']}条件場を独立会計。全{report['audit']['events']:,}約定、{report['audit']['lots']:,}新規玉、{report['audit']['marks']:,}保存時価地点を検算。",
              f"- 数量経路対照は{len(report['quantity_comparison'])}商品場で一致。全原行の最大時価DDの地点を再評価したが、間引き時価から全原行最大値を再証明したものではない。",
              "- 米国前/後は返済約定時計の分類。米国開始を跨ぐ親があるため、区間の含み変化を含む時価収支と同じではない。",
              "- 対象は既知の短い保存期間。全条件は同じ資料で比較しており、未見期間での安定性を証明していない。", ""]
    (HERE/"analysis153.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    """全保存結果が揃った後だけ検算・集計を行う。

    引数: なし。固定された目録、条件、金融結果を読み取る。
    返り値: None。不一致や不足は出力更新前に停止する。
    """
    manifest_path, config_path = HERE/"data/入力目録153.json", HERE/"configs153.json"
    manifest, configs = read(manifest_path), read(config_path)
    scenes = {scene["session"]: scene for scene in manifest["sessions"]}
    assert len(scenes) == 52 and sum(not scene["partial"] for scene in scenes.values()) == 51
    config_by_id = {config["id"]: config for config in configs}
    assert len(config_by_id) == 26
    paths = [HERE/"results_go"/f"{session}_{symbol}.json" for session in scenes for symbol in ("NK225", "TOPIX")]
    assert all(path.is_file() for path in paths), "104商品場の保存結果が揃ってから集計してください"
    methods, partial, comparisons, sources = {}, [], [], []
    slope_acc = defaultdict(dict)
    audit = Counter(complete_cases=0, partial_cases=0, events=0, lots=0, marks=0, parents=0)
    for path in paths:
        saved = read(path)
        session, symbol = saved["scene"]["session"], saved["symbol"]
        scene = scenes[session]
        assert symbol in ("NK225", "TOPIX")
        for key in ("session", "kind", "start", "end", "force_close", "us_open", "cutoff", "partial", "books"):
            assert saved["scene"][key] == scene[key], (path.name, key)
        cases = {case["Config"]["id"]: case for case in saved["cases"]}
        assert cases.keys() == config_by_id.keys()
        internal_cases = {}
        for identity, case in cases.items():
            assert case["Config"] == config_by_id[identity] and case["Session"] == session and case["Symbol"] == symbol
            row, internal = account_case(scene, case, path.relative_to(ROOT).as_posix())
            internal_cases[identity] = internal
            audit["partial_cases" if scene["partial"] else "complete_cases"] += 1
            for item in ("events", "lots"):
                audit[item] += internal[item]
            audit["marks"] += internal["marks"]["checked_marks"]
            audit["parents"] += internal["parent_count"]
            key = (symbol, identity)
            if scene["partial"]:
                partial.append({"id": identity, "description": describe(case["Config"]), "config": case["Config"], **row})
            else:
                if key not in methods:
                    methods[key] = {"symbol": symbol, "id": identity, "config": case["Config"], "description": describe(case["Config"]), "rows": []}
                methods[key]["rows"].append(row)
                merge_groups(slope_acc[key], internal["slope_groups"])
        comparisons.append(compare_quantities(cases, internal_cases, session, symbol))
        sources.append(fingerprint(path))
        print(f"検算済み {session} {symbol}：26条件", flush=True)
    assert audit["complete_cases"] == 2652 and audit["partial_cases"] == 52
    ordered = []
    for symbol in ("NK225", "TOPIX"):
        for identity in config_by_id:
            method = methods[(symbol, identity)]
            summarize_method(method)
            method["slope_groups"] = finish_slopes(slope_acc[(symbol, identity)], 100 if symbol == "NK225" else 1000)
            ordered.append(method)
    report = {"research": "00153", "description": "原板時間加重平均の傾き・比例枚数・利益追尾の固定26条件。金融再生ではなく保存会計の独立集計。",
              "definition": read(HERE/"analysis_spec153.json"), "methods": ordered, "partial": partial,
              "quantity_comparison": comparisons, "audit": dict(audit),
              "sources": [fingerprint(manifest_path), fingerprint(config_path), fingerprint(HERE/"analysis_spec153.json"), *sources]}
    serialized = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2)
    target = HERE/"report153.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(serialized, encoding="utf-8")
    temporary.replace(target)
    write_analysis(report)
    (HERE/"独立会計照合153.json").write_text(json.dumps({"state": "全件一致", "audit": dict(audit), "route_cases": len(comparisons),
                                                     "report": fingerprint(target), "script": fingerprint(Path(__file__))}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"state": "完了", **dict(audit), "methods": len(ordered), "partial": len(partial)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
