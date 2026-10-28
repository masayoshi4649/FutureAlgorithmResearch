"""全27夜の完了後だけ、保存約定を全正常原板へ戻して再会計する。"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import statistics
import sys
import traceback

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
WORK = ROOT / "work/research165"
HERE = WORK / "audit"
sys.path.insert(0, str(ROOT / "work/allocation_157/audit"))
sys.path.insert(0, str(ROOT / "work/allocation_157"))
from raw_result157 import close, normal_mask, raw_risk, reserved_cap
from ledger_analysis157 import reconcile


def read(path: Path):
    """有限値の保存JSONを読み取る。

    引数: path(Path)。返り値: dict又はlist。
    """
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    json.dumps(value, allow_nan=False)
    return value


def sha(path: Path) -> str:
    """内容指紋を逐次計算する。

    引数: path(Path)。返り値: str。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def resolve(path: str | Path) -> Path:
    """相対証跡パスをルート基準へ揃える。

    引数: path(str又はPath)。返り値: Path。
    """
    path = Path(path)
    return (path if path.is_absolute() else ROOT / path).resolve()


def record(path: Path) -> dict:
    """ルート相対パスとSHAを返す。

    引数: path(Path)。返り値: dict。
    """
    path = path.resolve()
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=sha(path))


def save(path: Path, value) -> None:
    """別名の新規監査成果だけを保存する。

    引数: path(Path)、value(dict又はlist)。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def verify_records(items: list[dict]) -> None:
    """保存された全参照のSHAを照合する。

    引数: items(list[dict])。返り値: None。
    """
    for item in items:
        assert sha(resolve(item["path"])) == item["sha256"], item["path"]


def control_module():
    """既存の読取検査関数を読み込み、登録や金融は実行しない。

    引数: なし。返り値: module。
    """
    spec = importlib.util.spec_from_file_location("control165_audit", WORK / "control165.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def raw_market(scene: dict) -> tuple[np.ndarray, np.ndarray, dict]:
    """原板を採番規則だけで読み、物理行とSHAを独立に復元する。

    引数: scene(dict)。返り値: 原板ndarray、物理行ndarray、読取根拠dict。
    """
    path = Path(scene["books"]["NK225"])
    digest, rows, lines, counts = hashlib.sha256(), [], [], Counter()
    previous = scene["start"]
    with path.open("rb") as stream:
        for physical, line in enumerate(stream, 1):
            digest.update(line)
            counts["physical"] += 1
            obj = json.loads(line)
            try:
                at = datetime.fromisoformat(obj["CurrentPriceTime"]).timestamp()
            except (KeyError, ValueError, TypeError):
                counts["clock_missing"] += 1
                continue
            if at < scene["start"] or at > scene["end"] or (scene.get("cutoff", 0) > 0 and at >= scene["cutoff"]):
                counts["outside"] += 1
                continue
            if at < previous:
                counts["backwards"] += 1
                continue
            last = float(obj.get("CurrentPrice") or 0)
            if last <= 0 or not math.isfinite(last):
                counts["last_missing"] += 1
                continue
            previous = at
            bid, ask = obj.get("Buy1") or {}, obj.get("Sell1") or {}
            rows.append((at, last, float(bid.get("Price") or 0), float(ask.get("Price") or 0),
                float(bid.get("Qty") or 0), float(ask.get("Qty") or 0)))
            lines.append(physical)
    expected = next(item["sha256"] for item in scene["fingerprints"] if Path(item["path"]) == path)
    assert digest.hexdigest() == expected, "原資料指紋不一致"
    raw = np.asarray(rows, dtype=np.float64)
    assert raw.ndim == 2 and raw.shape[1] == 6 and len(raw)
    counts["adopted"] = len(raw)
    return raw, np.asarray(lines, dtype=np.int64), dict(path=str(path), sha256=expected, counts=dict(counts))


def owner_reservations(ledger: dict) -> dict:
    """新規予約と所有ID別返済予約を原行順に追い、二重返済を検出する。

    引数: ledger(dict)。返り値: dict。
    """
    orders, fills = defaultdict(list), defaultdict(list)
    for event in ledger["Events"] or []:
        orders[event["Order"]["DecisionIndex"]].append(event["Order"])
        fills[event["FillIndex"]].append(event)
    live, close_reserved, pending = {}, Counter(), {}
    for index in sorted(set(orders) | set(fills)):
        for event in fills[index]:
            order = event["Order"]
            assert pending.pop(order["ID"]) == order
            if not order["Targets"]:
                assert event["HoldID"] not in live
                live[event["HoldID"]] = order["Quantity"]
            else:
                for target in order["Targets"]:
                    key, quantity = target["ID"], target["Quantity"]
                    live[key] -= quantity
                    close_reserved[key] -= quantity
                    assert 0 <= close_reserved[key] <= live[key]
        for order in orders[index]:
            assert order["ID"] not in pending
            pending[order["ID"]] = order
            for target in order["Targets"] or []:
                key, quantity = target["ID"], target["Quantity"]
                assert quantity > 0 and quantity <= live[key] - close_reserved[key]
                close_reserved[key] += quantity
    assert not pending and not any(live.values()) and not any(close_reserved.values())
    return dict(orders=sum(map(len, orders.values())), duplicate_close_reservations=0, final_unmanaged=0)


def snapshot_accounting_view(ledger: dict, ident: str) -> tuple[dict, list[dict]]:
    """約定から極値時の所有枚数を復元し、12の誤った診断mapだけを別写しで読む。

    引数: ledger(dict)、ident(str)。返り値: 検算用台帳dictと相違記録list。
    原保存JSON・損益・時価・枚数・注文は変更しない。
    """
    view, differences = deepcopy(ledger), []
    for name in ("MinimumAt", "PeakAt", "DDFrom", "DDTo", "MinimumRealizedAt", "MinimumUnrealizedAt"):
        snapshot = ledger["Risk"][name]
        if snapshot["Index"] < 0:
            continue
        live, realized, candidates = {}, 0., []
        for event in ledger["Events"] or []:
            if event["FillIndex"] > snapshot["Index"]:
                break
            if event["FillIndex"] == snapshot["Index"]:
                candidates.append((realized, dict(live)))
            if event["HoldID"]:
                live[event["HoldID"]] = event["Order"]["Quantity"]
            else:
                for target in event["Order"]["Targets"]:
                    live[target["ID"]] -= target["Quantity"]
            realized += event["Gross"]
        candidates.append((realized, dict(live)))
        matching = {}
        for cash, holdings in candidates:
            holdings = {key: q for key, q in holdings.items() if q}
            long = sum(q for key, q in holdings.items() if ledger["Lots"][key]["Side"] == 1)
            short = sum(q for key, q in holdings.items() if ledger["Lots"][key]["Side"] == -1)
            unrealized = sum(ledger["Lots"][key]["Side"] * q *
                ((snapshot["Bid"] if ledger["Lots"][key]["Side"] == 1 else snapshot["Ask"]) - ledger["Lots"][key]["Entry"]) * 10
                for key, q in holdings.items())
            if long == snapshot["Long"] and short == snapshot["Short"] and abs(cash - snapshot["Realized"]) < 1e-5 \
                and abs(unrealized - snapshot["Unrealized"]) < 1e-5:
                matching[tuple(sorted(holdings.items()))] = holdings
        saved = {key: q for key, q in (snapshot["Lots"] or {}).items() if q}
        if tuple(sorted(saved.items())) in matching:
            continue
        assert ident == "NK225_U165_12" and name in ("PeakAt", "DDFrom"), (ident, name, "未定義の診断不整合")
        assert len(matching) == 1, (ident, name, "約定から一意に復元できない")
        corrected = next(iter(matching.values()))
        assert saved and set(saved) == set(corrected) and all(saved[key] * 2 == q for key, q in corrected.items())
        differences.append(dict(field=name, time=snapshot["Time"], index=snapshot["Index"],
            saved_lots=snapshot["Lots"], reconstructed_lots=corrected,
            realized=snapshot["Realized"], unrealized=snapshot["Unrealized"], equity=snapshot["Equity"],
            financial_numbers_unchanged=True, reconstruction="全実約定から同原行の前・各約定後を復元し数量/確定/含みが一意一致"))
        view["Risk"][name]["Lots"] = corrected
    return view, differences


def path_extrema(raw: np.ndarray, good: np.ndarray, events: list[dict], start: float) -> dict:
    """一親の現金・買売数量だけから、全正常板の時価極値を求める。

    引数: raw/good(ndarray)、events(list[dict])、start(float)。返り値: dict。
    """
    if not events:
        return dict(peak=0., minimum=0., peak_index=-1, minimum_index=-1)
    first, last = events[0]["FillIndex"], events[-1]["FillIndex"]
    selected = good[(good >= first) & (good <= last)]
    changes = np.zeros((len(selected), 3))
    for event in events:
        order = event["Order"]
        position = int(np.searchsorted(selected, event["FillIndex"]))
        side, quantity = order["Side"], order["Quantity"]
        changes[position, 0] -= side * quantity * event["Price"]
        if order["Targets"]:
            changes[position, 1 if side == -1 else 2] -= quantity
        else:
            changes[position, 1 if side == 1 else 2] += quantity
    after = np.cumsum(changes, axis=0)
    before = after - changes
    bid, ask = raw[selected, 2], raw[selected, 3]
    pre = (before[:, 0] + before[:, 1] * bid - before[:, 2] * ask) * 10
    post = (after[:, 0] + after[:, 1] * bid - after[:, 2] * ask) * 10
    assert np.all(post <= pre + 1e-5)
    values = np.r_[0., np.column_stack((pre, post)).ravel()]
    hi, lo = int(np.argmax(values)), int(np.argmin(values))
    return dict(peak=float(values[hi]), minimum=float(values[lo]),
        peak_index=int(selected[(hi - 1) // 2]) if hi else -1,
        minimum_index=int(selected[(lo - 1) // 2]) if lo else -1)


def extrema_diagnostics(raw: np.ndarray, good: np.ndarray, ledger: dict, account: dict, start: float) -> dict:
    """玉の正益後赤字と親時価の利益返しを別々に原板から確認する。

    引数: raw/good(ndarray)、ledger/account(dict)、start(float)。返り値: dict。
    """
    lots, parents, pieces = [], [], []
    for lot in account["lots"]:
        saved = ledger["Lots"][lot["id"]]
        stop = max(close_["index"] for close_ in lot["closes"])
        selected = good[(good >= lot["index"]) & (good <= stop)]
        gains = lot["side"] * (raw[selected, 2 if lot["side"] == 1 else 3] - lot["price"])
        best, worst = max(0., float(np.max(gains))), min(0., float(np.min(gains)))
        close(saved["Best"], best, "玉の全保有原板MFE")
        close(saved["Worst"], worst, "玉の全保有原板MAE")
        item = dict(id=lot["id"], parent=lot["parent"], owner=lot["owner"], kind=lot["kind"],
            side=lot["side"], quantity=lot["quantity"], entry=lot["price"], entry_time=lot["time"],
            entry_index=lot["index"], exit_index=stop, net=lot["gross"], best=best, worst=worst,
            positive_then_loss=best > 0 and lot["gross"] < 0, never_positive=best <= 0)
        lots.append(item)
    for event in ledger["Events"] or []:
        for piece in event["Pieces"] or []:
            lot = ledger["Lots"][piece["ID"]]
            selected = good[(good >= lot["EntryIndex"]) & (good <= event["FillIndex"])]
            gains = lot["Side"] * (raw[selected, 2 if lot["Side"] == 1 else 3] - lot["Entry"])
            best, worst = max(0., float(np.max(gains))), min(0., float(np.min(gains)))
            close(piece["Best"], best, "配賦時点MFE")
            close(piece["Worst"], worst, "配賦時点MAE")
            pieces.append(dict(id=piece["ID"], quantity=piece["Quantity"], gross=piece["Gross"],
                time=event["FillTime"], index=event["FillIndex"], best=best, worst=worst,
                positive_then_loss=best > 0 and piece["Gross"] < 0))
    for parent in account["parents"]:
        events = [event for event in ledger["Events"] or [] if event["Order"]["Parent"] == parent["id"]]
        path = path_extrema(raw, good, events, start)
        saved = ledger["Parents"][parent["id"]]
        close(path["peak"], saved["Peak"], "親の全原板最高時価")
        close(path["minimum"], saved["Minimum"], "親の全原板最悪時価")
        parents.append(dict(id=parent["id"], owner=parent["owner"], net=parent["realized"],
            positive_then_loss=path["peak"] > 0 and parent["realized"] < 0, **path))
    return dict(lots=lots, parents=parents, pieces=pieces,
        lot_positive_then_loss=sum(item["positive_then_loss"] for item in lots),
        parent_positive_then_loss=sum(item["positive_then_loss"] for item in parents),
        piece_positive_then_loss=sum(item["positive_then_loss"] for item in pieces),
        piece_positive_then_loss_micro=sum(item["quantity"] for item in pieces if item["positive_then_loss"]))


def economic_events(ledger: dict, source_ids: bool) -> list[dict]:
    """手法固有IDを除いて同じ通知・配賦・約定経路を比較する。

    引数: ledger(dict)、source_ids(bool)。返り値: list[dict]。
    """
    identities, result = {}, []
    for event in ledger["Events"] or []:
        order = event["Order"]
        if event["HoldID"]:
            key = order["SourceID"] if source_ids else len(identities)
            identities[event["HoldID"]] = key
        result.append(dict(source=order["SourceID"] if source_ids else None,
            owner=order["Owner"], campaign=order["Campaign"], side=order["Side"], quantity=order["Quantity"],
            decision_index=order["DecisionIndex"], decision_time=order["DecisionTime"],
            fill_index=event["FillIndex"], fill_time=event["FillTime"], price=event["Price"],
            bid=event["Bid"], ask=event["Ask"], gross=event["Gross"],
            targets=[dict(id=identities[t["ID"]], quantity=t["Quantity"]) for t in order["Targets"] or []],
            pieces=[dict(id=identities[p["ID"]], quantity=p["Quantity"], entry=p["Entry"],
                exit=p["Exit"], gross=p["Gross"], best=p["Best"], worst=p["Worst"]) for p in event["Pieces"] or []]))
    return result


def half_control(full: dict, half: dict, source_ids: bool) -> dict:
    """半量対照が新規集合・時計・価格・配賦を変えず厳密半額か調べる。

    引数: full/half(dict)、source_ids(bool)。返り値: dict。
    """
    expected = economic_events(full, source_ids)
    for item in expected:
        assert item["quantity"] % 2 == 0
        item["quantity"] //= 2
        item["gross"] /= 2
        for value in item["targets"] + item["pieces"]:
            assert value["quantity"] % 2 == 0
            value["quantity"] //= 2
            if "gross" in value:
                value["gross"] /= 2
    assert expected == economic_events(half, source_ids), "半量対照で取引経路又は配賦が変化"
    for key in ("Peak", "Minimum", "MaxDD", "MinimumRealized", "MinimumUnrealized",
        "MaxLong", "MaxShort", "MaxGross", "MaxNetAbs", "GrossSeconds", "NetAbsSeconds", "NetSignedSeconds"):
        close(half["Risk"][key], full["Risk"][key] / 2, "厳密半量/" + key)
    for key in ("HeldSeconds", "HedgedSeconds"):
        close(half["Risk"][key], full["Risk"][key], "同一保有時間/" + key)
    close(half["Realized"], full["Realized"] / 2, "半量確定")
    return dict(passed=True, events=len(expected), exact_half_net=half["Realized"])


def normalized(value, name: str):
    """手法IDの文字列だけを共通記号へ置換する。

    引数: value(JSON値)、name(str)。返り値: JSON値。
    """
    if isinstance(value, dict):
        return {key.replace(name, "比較"): normalized(item, name) for key, item in value.items()}
    if isinstance(value, list):
        return [normalized(item, name) for item in value]
    return value.replace(name, "比較") if isinstance(value, str) else value


def direction(raw: np.ndarray, indices: np.ndarray, scope: str) -> dict:
    """当区間の採用Last始終を事後分類し、判断入力にしない。

    引数: raw/indices(ndarray)、scope(str)。返り値: dict。
    """
    assert len(indices)
    first, last = int(indices[0]), int(indices[-1])
    delta = raw[last, 1] - raw[first, 1]
    return dict(direction="上昇" if delta > 0 else "下落" if delta < 0 else "同値",
        scope=scope, first_last=float(raw[first, 1]), final_last=float(raw[last, 1]),
        first_index=first, final_index=last, first_clock=float(raw[first, 0]), final_clock=float(raw[last, 0]),
        formal_close=False, decision_input=False)


def scene_check(scene: dict, baseline: dict, run_folder: str) -> dict:
    """一夜の新14台帳と保存基準を同じ原板で独立監査する。

    引数: scene/baseline(dict)、run_folder(str)。返り値: dict。
    """
    stage = "train_validation" if scene["split"] in ("train", "validation") else "confirmation"
    path = WORK / "results" / stage / (scene["session"] + ".json")
    before = record(path)
    saved = read(path)
    assert saved["scene"] == scene
    assert saved["control"]["actual"] == baseline["actual"], "旧U00全実台帳差"
    raw, physical, raw_source = raw_market(scene)
    valid = normal_mask(raw)
    good = np.flatnonzero(valid)
    totals, rows = Counter(), []
    configs = {value["id"]: value for value in read(WORK / "night_engine/configs165.json")}
    assert len(saved["cases"]) == 14 and {case["config"]["id"] for case in saved["cases"]} == set(configs)
    for quote in saved["reference"] or []:
        index = quote["Index"]
        assert quote["Line"] == physical[index] and quote["Normal"] == bool(valid[index])
        for key, column in (("Time", 0), ("Last", 1), ("Bid", 2), ("Ask", 3)):
            close(quote[key], raw[index, column], "原行参照/" + key)
    cases = saved["cases"] + [baseline]
    for case in cases:
        ident = case["config"]["id"]
        if ident in configs:
            assert case["config"] == configs[ident]
        ledger = case["actual"]
        start = scene["us_open"] + 900
        accounting_view, snapshot_differences = snapshot_accounting_view(ledger, ident)
        account = reconcile(accounting_view, start, ledger["LastTime"])
        assert not ledger["Pending"] and account["remaining_qty"] == 0
        risk = raw_risk(raw, ledger, start)
        cap = reserved_cap(ledger)
        ownership = owner_reservations(ledger)
        extremes = extrema_diagnostics(raw, good, ledger, account, start)
        for event in ledger["Events"] or []:
            assert event["Order"]["DecisionTime"] >= start
            if event["HoldID"]:
                assert event["Order"]["DecisionTime"] < scene["force_close"]
        # ----------------------------------------
        # 確定額は同原行の返済順でも変わるため、逐次再会計の最小値を使う。
        risk["min_realized"] = account["min_realized"]["value"]
        rows.append(dict(id=ident, session=scene["session"], split=scene["split"],
            profit=account["allocation_profit"], loss=account["allocation_loss"], net=account["net"],
            minimum_equity=risk["min_equity"], maximum_dd=risk["max_drawdown"],
            minimum_realized=risk["min_realized"], new_orders=account["entries"],
            no_entry=int(account["entries"] == 0), closed_micro=sum(p["quantity"] for p in extremes["pieces"]),
            held_seconds=account["quantities"]["held_seconds"], gross_seconds=account["quantities"]["gross_seconds"],
            risk=risk, capacity=cap, ownership=ownership, extrema=extremes,
            saved_snapshot_differences=snapshot_differences,
            lot_positive_then_loss=extremes["lot_positive_then_loss"],
            parent_positive_then_loss=extremes["parent_positive_then_loss"],
            quantity_time=account["quantities"], peak_equity=ledger["Risk"]["Peak"]))
        totals.update(cases=1, events=len(ledger["Events"] or []), lots=len(ledger["Lots"] or {}),
            raw_marks=len(good), owned_orders=ownership["orders"], reference_rows=len(saved["reference"] or []))
        totals["snapshot_different_cases"] += int(bool(snapshot_differences))
        totals["snapshot_different_maps"] += len(snapshot_differences)
    indexed = {case["config"]["id"]: case for case in cases}
    controls = {"01_vs_U164_00": half_control(baseline["actual"], indexed["NK225_U165_01"]["actual"], True),
        "12_vs_11": half_control(indexed["NK225_U165_11"]["actual"], indexed["NK225_U165_12"]["actual"], False)}
    assert normalized(indexed["NK225_U165_12"]["virtual_control"], "NK225_U165_12") == \
        normalized(indexed["NK225_U165_11"]["actual"], "NK225_U165_11"), "12の仮想枠が11と異なる"
    post = np.flatnonzero(raw[:, 0] >= scene["us_open"] + 900)
    bad = int(np.sum(~valid[post]))
    post_good = good[raw[good, 0] >= scene["us_open"] + 900]
    quality = dict(adopted_rows=len(post), normal_rows=len(post_good), invalid_bbo=bad,
        same_price_clock_rows=int(np.sum(np.diff(raw[post_good, 0]) == 0)),
        price_clock_gaps_gt60=int(np.sum(np.diff(raw[post_good, 0]) > 60)),
        last_normal_index=int(good[-1]), last_normal_clock=float(raw[good[-1], 0]),
        last_normal_age_to_end=float(scene["end"] - raw[good[-1], 0]), end_proxy_used=False,
        reception_clock_available=False, volume_changes_are_trade_attribution=False)
    assert 0 <= scene["end"] - raw[-1, 0] <= 360, "Last終端が直前6分内でない"
    answer = dict(passed=True, session=scene["session"], source=before, raw=raw_source, totals=dict(totals),
        baseline_all_actual_fields_equal=True, quantity_controls=controls, rows=rows, quality=quality,
        session_direction=direction(raw, np.arange(len(raw)), "Night全体の採用Last始終"),
        postus_direction=direction(raw, post, "US+15分から原資料末尾までの採用Last始終"))
    assert record(path) == before
    result_path = Path(run_folder) / (scene["session"] + ".json")
    save(result_path, answer)
    return dict(totals=dict(totals), source=record(result_path), session=scene["session"])


def summary(rows: list[dict]) -> dict:
    """全場の悪い側四分位と勝敗を含む比較指標を別計算する。

    引数: rows(list[dict])。返り値: dict。
    """
    assert rows
    nets = [row["net"] for row in rows]
    negatives = [-value for value in nets if value < 0]
    quarter = sorted(nets)[:(len(nets) + 3) // 4]
    profit, loss = sum(row["profit"] for row in rows), sum(row["loss"] for row in rows)
    closed = sum(row["closed_micro"] for row in rows)
    return dict(sessions=len(rows), profit=profit, loss=loss, net=sum(nets),
        negative_sessions=len(negatives), no_entries=sum(row["new_orders"] == 0 for row in rows),
        mean_loss=sum(negatives) / len(negatives) if negatives else 0.,
        median_loss=statistics.median(negatives) if negatives else 0., maximum_loss=max(negatives, default=0.),
        worst_quarter_loss=sum(max(0., -value) for value in quarter) / len(quarter),
        worst_quarter_mean=sum(quarter) / len(quarter), excluding_top3=sum(sorted(nets)[:-3]),
        minimum_equity=min(row["minimum_equity"] for row in rows), maximum_dd=max(row["maximum_dd"] for row in rows),
        loss_share=loss / (profit + loss) if profit + loss else None,
        net_per_closed_micro_point=sum(nets) / (closed * 10) if closed else None,
        closed_micro=closed, new_orders=sum(row["new_orders"] for row in rows),
        held_seconds=sum(row["held_seconds"] for row in rows),
        profit_loss_ratio=profit / loss if loss else None,
        lot_positive_then_loss=sum(row["lot_positive_then_loss"] for row in rows),
        parent_positive_then_loss=sum(row["parent_positive_then_loss"] for row in rows))


def make_report(results: list[dict], fixed: dict, definitions: list[dict], audit_path: Path) -> dict:
    """監査済み全405行を15手法の簡潔な表示用会計へ整形する。

    引数: results/definitions(list[dict])、fixed(dict)、audit_path(Path)。返り値: dict。
    """
    groups = defaultdict(list)
    for checked in results:
        for row in checked["rows"]:
            clean = {key: value for key, value in row.items() if key not in ("extrema", "capacity", "ownership", "quantity_time")}
            clean.update(kind="Night", source_scope="PostUS", direction=checked["postus_direction"]["direction"],
                postus_direction=checked["postus_direction"]["direction"], session_direction=checked["session_direction"]["direction"],
                direction_source=dict(postus=checked["postus_direction"], session=checked["session_direction"]),
                quality=checked["quality"], net_per_closed_micro_point=row["net"] / (row["closed_micro"] * 10) if row["closed_micro"] else None)
            groups[row["id"]].append(clean)
    methods = []
    all_definitions = [dict(id="NK225_U164_00", description="保存基準・米国後D07", scope="PostUS", reused_baseline=True)] + definitions
    for config in all_definitions:
        rows = sorted(groups[config["id"]], key=lambda row: row["session"])
        assert len(rows) == 27
        total = 0.
        for row in rows:
            total += row["net"]
            row["cumulative"] = total
        grouped = {"全場": rows, "前20夜": [row for row in rows if row["split"] in ("train", "validation")],
            "後7夜": [row for row in rows if row["split"] not in ("train", "validation")]}
        summaries = {name: summary(values) for name, values in grouped.items()}
        descriptions = {"NK225_U165_07": "反対板で初回を見送り、同方向の板が続く時だけ追撃",
            "NK225_U165_08": "反対板で初回見送り・追撃抑制、利益残玉の返済と逆行半減",
            "NK225_U165_09": "初回見送り・追撃抑制・残玉返済・逆行半減を15秒窓で判定"}
        methods.append(dict(id=config["id"], description=descriptions.get(config["id"], config["description"]), scope="PostUS", configuration=config,
            selected=config["id"] == fixed["selected"]["PostUS"],
            quantity_control=config["id"] in ("NK225_U165_01", "NK225_U165_12"), rows=rows, summary=summaries))
    controls = {item["id"]: item for item in fixed["comparisons"]}
    for method in methods:
        expected = controls[method["id"]]["summary"]
        for key, value in expected.items():
            got = method["summary"]["前20夜"][key]
            if value is None:
                assert got is None
            else:
                close(got, value, "前20凍結比較/" + key)
    return dict(methods=methods, selected=fixed["selected"], selected_eligible=fixed["selected_eligible"],
        adoption_confirmed=False, known_development=True, independent_unseen=False, new_financial_replays=0,
        accounting="実返済Piece別の正負。損失は正額、収支=利益−損失。場内最悪は全実玉の確定＋返済気配含み。",
        units=dict(product="NK225micro", point_value=10, max_per_side=100, equivalent_mini_per_side=10, fee=0),
        notes=["全27夜は既知資料。前20夜で固定した後、後7夜の結果で選び直していない。",
            "01と12は厳密半量対照。数量減少だけを売買判断の改善としない。",
            "Last始終の事後方向はPostUS区間とNight全体を分け、売買入力には使わない。",
            "価格時計は受信時計ではなく、同時計の原行順を使用。ラージ気配による約定模型。",
            "場末の別代理精算は加えていない。全玉は元の終了判断後の次正常原板で完済。",
            "半量12の一部保存極値断面は所有枚数mapが二重半減。約定から復元した別断面で検算し、元JSON・損益・Risk金額は変更していない。"],
        sources=[record(audit_path), record(WORK / "results/selection_frozen165.json"), record(WORK / "再生全完了165.json")])


def verify_stages(scenes: list[dict], definitions: list[dict]) -> None:
    """登録済み読取器を変更せず、無取引nullを許して両段階の証跡を照合する。

    引数: scenes/definitions(list[dict])。返り値: None。
    """
    for stage, count in (("train_validation", 20), ("confirmation", 7)):
        proof = read(WORK / "results" / stage / ("再生完了165_" + stage + ".json"))
        assert proof["completed"] and proof["returncode"] == 0 and proof["sources_unchanged"]
        assert proof["sessions"] == count and proof["cases"] == count * 14
        assert proof["stage"]["stage"] == stage
        for key, path in (("manifest_sha256", WORK / "inputs165.json"),
            ("spec_sha256", WORK / "計画165.md"), ("configs_sha256", WORK / "night_engine/configs165.json")):
            assert proof["stage"][key] == sha(path)
        expected = {scene["session"] for scene in scenes
            if (scene["split"] in ("train", "validation")) == (stage == "train_validation")}
        assert len(proof["results"]) == count and {item["session"] for item in proof["results"]} == expected
        verify_records(proof["results"])
        if stage == "confirmation":
            assert proof["stage"]["freeze_sha256"] == sha(WORK / "results/selection_frozen165.json")


def main() -> None:
    """両段階の全完了を必須にして監査と表示用集計を実行する。

    引数: なし。返り値: None。新たな売買判断は生成しない。
    """
    complete = read(WORK / "再生全完了165.json")
    assert complete["completed"] and complete["returncode"] == 0 and complete["cases"] == 378
    assert complete["sessions"] == 27 and complete["reselection_after_confirmation"] is False
    assert not (HERE / "audit165.json").exists() and not (WORK / "report_data165.json").exists()
    control = control_module()
    receipt = control.verify_receipt()
    frozen = control.verified_freeze()
    verify_records(complete["proofs"] + [complete["freeze"]])
    definitions = control.configs()
    scenes = read(WORK / "inputs165.json")["sessions"]
    verify_stages(scenes, definitions)
    baseline = {item["scene"]["session"]: item["case"] for item in read(WORK / "baseline165.json")["cases"]}
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    folder = HERE / "結果監査" / stamp
    totals, completed = Counter(), []
    proof = dict(passed=False, new_financial_replays=0, started_at=datetime.now().astimezone().isoformat())
    try:
        with ProcessPoolExecutor(max_workers=4) as pool:
            jobs = {pool.submit(scene_check, scene, baseline[scene["session"]], str(folder)): scene["session"] for scene in scenes}
            for job in as_completed(jobs):
                result = job.result()
                totals.update(result["totals"])
                completed.append(result["source"])
                print(json.dumps(dict(session=result["session"], checked=len(completed)), ensure_ascii=False), flush=True)
        assert len(completed) == 27 and totals["cases"] == 405
        verify_records(receipt["sources"])
        results = [read(resolve(item["path"])) for item in sorted(completed, key=lambda item: item["path"])]
        proof.update(passed=True, totals=dict(totals), results=completed, source_unchanged=True,
            saved_snapshot_payload_fully_consistent=totals["snapshot_different_maps"] == 0,
            diagnostic_correction_only=totals["snapshot_different_maps"] > 0,
            complete=record(WORK / "再生全完了165.json"), selection=record(WORK / "results/selection_frozen165.json"),
            implementation=[record(Path(__file__)), record(ROOT / "work/allocation_157/audit/raw_result157.py"),
                record(ROOT / "work/allocation_157/ledger_analysis157.py")],
            finished_at=datetime.now().astimezone().isoformat(),
            limitations=["同価格時計内は原行順。真の受信時計は観測していない。",
                "全正常板の再会計であり、実市場の約定を保証するものではない。",
                "計画済み売買条件を再実行せず、保存通知・実約定・原板の会計だけを照合。"])
        save(HERE / "audit165.json", proof)
        report = make_report(results, frozen, definitions, HERE / "audit165.json")
        save(WORK / "report_data165.json", report)
        print(json.dumps(dict(passed=True, audit=record(HERE / "audit165.json"), report=record(WORK / "report_data165.json"), totals=dict(totals)), ensure_ascii=False))
    except Exception:
        proof["error"] = traceback.format_exc()
        save(HERE / ("監査失敗165_" + stamp + ".json"), proof)
        raise


if __name__ == "__main__":
    main()
