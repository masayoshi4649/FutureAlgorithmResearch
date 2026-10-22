"""00125の保存注文と群から全tick会計を復元し、金融規則を再実行せずに照合する。"""

from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_FLOOR
import hashlib
from io import BytesIO
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OWNER = HERE.parent
RESULT = OWNER / "十二条件と二商品全四十一場の会計.json"
CHECKS = 0
READS = {"完成結果": 0, "保存入力": 0, "保存結果NPZ": 0, "原市場": 0, "旧cache": 0, "金融再実行": 0}
CONTRACTS = {"TOPIX": (10, 1000., "41.8", .5), "NK225": (20, 10., "11", 10.)}


def check(condition: bool, note: str) -> None:
    """
    機能: 保存値と独立期待値の一致を検査して数える。
    引数: condition (bool) 条件、note (str) 検査名。
    返り値: None。
    """
    global CHECKS
    assert bool(condition), note
    CHECKS += 1


def near(actual: object, expected: object, note: str) -> None:
    """
    機能: 有限会計値または同形配列を独立値と照合する。
    引数: actual/expected (object) 値、note (str) 検査名。
    返り値: None。
    """
    check(np.shape(actual) == np.shape(expected), note + "形状")
    check(np.allclose(actual, expected, atol=1e-5, rtol=1e-11, equal_nan=False), note)


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 一注文の税込料金を十進数で独立切捨てする。
    引数: quantity (int) 枚数、symbol (str) 銘柄。
    返り値: int 円単位片道料金。
    """
    return int((Decimal(quantity) * Decimal(CONTRACTS[symbol][2])).to_integral_value(rounding=ROUND_FLOOR))


def save(name: str, value: dict) -> dict:
    """
    機能: 所有監査領域へ新規の有限 JSON を保存する。
    引数: name (str) 保存名、value (dict) 内容。
    返り値: dict 位置と SHA256。
    """
    target = HERE / name
    check(not target.exists(), "監査結果を上書きしない")
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    target.write_bytes(payload)
    return {"path": target.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(payload).hexdigest()}


def packet(info: dict, expected_root: Path, kind: str) -> dict:
    """
    機能: 指定の125保存NPZを一回だけ読み、同bytesを確認してメモリへ展開する。
    引数: info (dict) 位置・指紋、expected_root (Path) 許可先、kind (str) 入出力区分。
    返り値: dict 配列。
    """
    path = (ROOT / info["path"]).resolve()
    check(path.is_relative_to(expected_root), "新保存NPZの所有域")
    stat = path.stat()
    payload = path.read_bytes()
    READS[kind] += 1
    check(hashlib.sha256(payload).hexdigest() == info["sha256"] and (stat.st_size, stat.st_mtime_ns) == (path.stat().st_size, path.stat().st_mtime_ns), "保存NPZ同bytes不変")
    with np.load(BytesIO(payload), allow_pickle=False) as archive:
        return {key: archive[key].copy() for key in archive.files}


def column_rows(table: np.ndarray, columns: list[str]) -> list[dict]:
    """
    機能: 保存された固定列名と各行を対応させる。
    引数: table (ndarray) 二次元配列、columns (list[str]) 列名。
    返り値: list[dict] 列名付き行。
    """
    check(table.ndim == 2 and table.shape[1] == len(columns) and np.isfinite(table).all(), "台帳の形状と有限値")
    return [dict(zip(columns, row)) for row in table]


def reconstruct(q: dict, order_table: np.ndarray, trade_table: np.ndarray, curve: np.ndarray,
                given: dict, spec: dict, columns: dict) -> dict:
    """
    機能: 実注文のUID・群・枚数・費用から全tick資産と終端代理を独立復元する。
    引数: q (dict) 保存観測、各table/curve (ndarray) 台帳、given/spec/columns (dict) 小結果と契約。
    返り値: dict 独立確認した群・料金・収支・最大数量等。入口・出口の選択規則は再生しない。
    """
    symbol = given["symbol"]
    cap, multiplier, _, tick = CONTRACTS[symbol]
    n = len(q["row"])
    check(n > 0 and all(len(q[key]) == n for key in ("time", "last", "bid", "ask")), "入力列の長さ")
    check(np.all(np.diff(q["row"]) > 0) and np.all(np.diff(q["time"]) >= 0), "入力の原row順と非減少価格時計")
    check(all(np.isfinite(q[key]).all() for key in ("row", "time", "last", "bid", "ask")) and np.all((q["last"] > 0) & (q["bid"] > 0) & (q["ask"] > q["bid"])), "全観測の正常気配資格")
    orders = column_rows(order_table, columns["orders"])
    trades = column_rows(trade_table, columns["trades"])
    check(len({int(row["group_id"]) for row in trades}) == len(trades), "完結群ID重複なし")
    trade_by_group = {int(row["group_id"]): row for row in trades}
    check(order_table.shape[1] == 20 and trade_table.shape[1] == 25 and curve.ndim == 2 and curve.shape[1] == 8 and np.isfinite(curve).all(), "固定20/25/8列")
    cash_delta = np.zeros(n)
    realized_delta = np.zeros(n)
    position_delta = np.zeros(n, dtype=np.int64)
    basis_delta = np.zeros(n)
    groups = {}
    active = None
    paid = 0
    entry_quantity = entry_orders = add_orders = 0
    actual_entry_notional = 0.
    previous_fill = -1
    running_cash = 0.
    for number, order in enumerate(orders, 1):
        for key in ("order_uid", "group_id", "kind", "side", "quantity", "decision_row", "fill_row", "reason", "position_after"):
            check(order[key] == int(order[key]), "注文の離散欄は整数")
        uid, gid, kind, side, amount = map(int, (order["order_uid"], order["group_id"], order["kind"], order["side"], order["quantity"]))
        check(uid == number and kind in (1, 2) and side in (-1, 1) and 0 < amount <= cap, "注文UID連続・種別・売買・上限")
        di = int(np.searchsorted(q["row"], int(order["decision_row"])))
        fi = int(np.searchsorted(q["row"], int(order["fill_row"])))
        check(di < n and fi < n and int(q["row"][di]) == order["decision_row"] and int(q["row"][fi]) == order["fill_row"], "判断・約定の原row実在")
        check(fi == di + 1 and fi > previous_fill, "約定は最初の厳密次正常原行")
        previous_fill = fi
        near(order["decision_time"], q["time"][di], "判断価格時計")
        near(order["fill_time"], q["time"][fi], "約定価格時計")
        near([order["decision_last"], order["decision_bid"], order["decision_ask"]], [q["last"][di], q["bid"][di], q["ask"][di]], "判断当時の三価格")
        price = q["ask" if side == 1 else "bid"][fi]
        near(order["price"], price, "買ask・売bid約定")
        cost = fee(amount, symbol)
        near(order["fee"], cost, "注文別料金切捨て")
        paid += cost
        cash_delta[fi] -= cost
        running_cash -= cost
        if kind == 1:
            check(q["time"][fi] < given["session_end"] - 1800, "新規・追加は当場締切前")
            check(gid in trade_by_group, "新規群の固定幅が保存されている")
            width = trade_by_group[gid]["initial_w"]
            for index in (di, fi):
                check(q["ask"][index] - q["bid"][index] + 2 * float(CONTRACTS[symbol][2]) / multiplier <= .5 * width + 1e-10, "新規は判断・実行双方で費用幅資格を満たす")
            entry_quantity += amount
            entry_orders += 1
            actual_entry_notional += amount * price * multiplier
            if active is None:
                check(gid == len(groups) + 1 and amount == cap // 2 and int(order["reason"]) in (1, 2, 3, 4, 5), "初回半上限・次の群ID・入口理由")
                groups[gid] = {"side": side, "quantity": 0, "notional": 0., "fees": 0, "entry_count": 0, "first_index": fi, "first_row": int(q["row"][fi]), "first_time": q["time"][fi], "reason": int(order["reason"]), "exit": None, "entry_order_indices": []}
                active = gid
            else:
                check(active == gid and groups[gid]["side"] == side and spec["add_enabled"] and groups[gid]["entry_count"] == 1 and amount == cap - groups[gid]["quantity"] and int(order["reason"]) == 20, "追加は同じ群の残容量一回のみ")
                add_orders += 1
            state = groups[gid]
            state["quantity"] += amount
            state["notional"] += amount * price
            state["fees"] += cost
            state["entry_count"] += 1
            state["entry_order_indices"].append(number - 1)
            position_delta[fi] += side * amount
            basis_delta[fi] += side * amount * price
            near(order["realized_net"], 0, "新規の実現損益は0")
            near(order["position_after"], side * state["quantity"], "新規後純建玉")
            near(order["average_entry_after"], state["notional"] / state["quantity"], "新規後平均建値")
        else:
            check(active == gid and gid in groups, "返済は現に保有する群だけ")
            state = groups[gid]
            check(state["side"] == -side and state["quantity"] == amount and state["exit"] is None, "返済方向・全量・過剰返済なし")
            gross = state["side"] * (price * amount - state["notional"]) * multiplier
            net = gross - state["fees"] - cost
            near(order["realized_net"], net, "全量返済の群実現損益")
            cash_delta[fi] += gross
            running_cash += gross
            realized_delta[fi] += net
            position_delta[fi] += side * amount
            basis_delta[fi] -= state["side"] * state["notional"]
            state["exit"] = order
            state["exit_index"] = fi
            near([order["position_after"], order["average_entry_after"]], [0, 0], "返済完了後の平坦化")
            active = None
        near(order["cash_after"], running_cash, "各注文直後の実現現金")
    # ----------------------------------------
    position = np.cumsum(position_delta)
    cash = np.cumsum(cash_delta)
    realized = np.cumsum(realized_delta)
    basis = np.cumsum(basis_delta)
    check(np.all(abs(position) <= cap), "全tick純建玉の片方向上限")
    reserved = np.floor(np.abs(position) * float(CONTRACTS[symbol][2]) + 1e-9)
    close_reference = np.where(position >= 0, q["bid"], q["ask"])
    equity = cash + (position * close_reference - basis) * multiplier - reserved
    highwater = np.maximum.accumulate(np.maximum(equity, 0))
    dd = highwater - equity
    curve_indices = [0]
    while True:
        nxt = int(np.searchsorted(q["time"], q["time"][curve_indices[-1]] + 60, side="left"))
        if nxt >= n:
            break
        curve_indices.append(nxt)
    curve_indices.append(n - 1)
    ci = np.asarray(curve_indices, dtype=np.int64)
    expected_curve = np.column_stack((q["row"][ci], q["time"][ci], equity[ci], cash[ci], realized[ci], np.maximum(position[ci], 0), np.maximum(-position[ci], 0), dd[ci]))
    near(curve, expected_curve, "保存全curve・EOF代理前の在庫時価")
    # ----------------------------------------
    proxy_fees = 0
    proxy_count = 0
    trade_net = []
    forced = 0
    forced_net = 0.
    for trade in trades:
        gid = int(trade["group_id"])
        check(gid in groups, "全完結群は実新規由来")
        state = groups[gid]
        side, amount = state["side"], state["quantity"]
        proxy = bool(trade["proxy_flag"])
        check(trade["proxy_flag"] in (0, 1), "代理flagは0/1")
        if proxy:
            check(active == gid and state["exit"] is None and proxy_count == 0, "代理はEOFの残在庫一群だけ・通常注文なし")
            check(given["session_end"] - 360 <= q["time"][-1] <= given["session_end"], "代理終端は引け直前六分窓")
            exit_index = n - 1
            xp = q["bid" if side == 1 else "ask"][-1]
            check(trade["exit_decision_row"] == trade["exit_row"] == -1 and trade["reference_row"] == q["row"][-1] and trade["planned_exit_time"] == given["session_end"] and trade["exit_reason"] == 16, "代理に架空通常約定を作らない")
            proxy_count += 1
            proxy_fees += fee(amount, symbol)
        else:
            check(state["exit"] is not None, "通常完結群に実返済注文あり")
            order = state["exit"]
            exit_index = state["exit_index"]
            xp = order["price"]
            near([trade["exit_decision_row"], trade["exit_row"], trade["exit_reason"], trade["reference_row"], trade["planned_exit_time"]], [order["decision_row"], order["fill_row"], order["reason"], order["fill_row"], order["decision_time"]], "通常返済群と実注文系譜")
        gross = side * (xp * amount - state["notional"]) * multiplier
        exit_fee = fee(amount, symbol)
        net = gross - state["fees"] - exit_fee
        average = state["notional"] / amount
        expected = {"side": side, "quantity": amount, "entry_notional": state["notional"], "average_entry": average, "first_entry_row": state["first_row"], "first_entry_time": state["first_time"], "exit_time": q["time"][exit_index], "exit_price": xp, "gross": gross, "entry_fees": state["fees"], "exit_fee": exit_fee, "net": net, "entry_reason": state["reason"], "entry_orders": state["entry_count"]}
        for key, value in expected.items():
            near(trade[key], value, "全群の独立会計:" + key)
        baseline = realized[state["first_index"]]
        marks = equity[state["first_index"]:exit_index + 1] - baseline
        near(trade["mfe"], max(0., float(max(marks)), net), "全tick群MFE")
        near(trade["mae"], min(0., float(min(marks)), net), "全tick群MAE")
        check(trade["initial_w"] > 0 and state["entry_count"] in (1, 2), "群の幅と初回追加数")
        first = orders[state["entry_order_indices"][0]]
        base_stop = first["price"] - side * spec["stop_w"] * trade["initial_w"]
        check(side * (trade["initial_stop"] - base_stop) >= -1e-8, "支持線で初期撤回を広げていない")
        trade_net.append(net)
        forced += int(state["reason"] == 5)
        forced_net += net if state["reason"] == 5 else 0
    check(len(trades) == len(groups), "開始群と通常/代理完結群の保存則")
    check((active is not None) == bool(proxy_count), "通常終端の未返済は代理だけで清算")
    net = sum(trade_net)
    gain = sum(max(0., value) for value in trade_net)
    loss = sum(max(0., -value) for value in trade_net)
    total_paid = paid + proxy_fees
    final_cash = cash[-1]
    if proxy_count:
        final_cash += trade_net[-1] + groups[active]["fees"]
    near(final_cash, net, "代理後全実現現金と全群net")
    near(equity[-1], net, "最終BBO全費用時価とflat後純損益")
    maximum_long = max(0, int(max(position)))
    maximum_short = max(0, int(max(-position)))
    independent = {"net": net, "cash": final_cash, "profit": gain, "loss": loss, "fees_paid": total_paid, "closed_groups": len(trades), "wins": sum(value > 0 for value in trade_net), "losses": sum(value < 0 for value in trade_net), "unclosed_quantity": 0, "unclosed": 0, "position": 0, "max_long": maximum_long, "max_short": maximum_short, "max_drawdown": max(dd), "min_equity": min(0., min(equity)), "entry_orders": entry_orders, "entry_quantity": entry_quantity, "clock_rejected": 0, "forced_groups": forced, "normal_groups": len(groups) - forced, "add_orders": add_orders, "groups_started": len(groups), "first_entry_time": min((state["first_time"] for state in groups.values()), default=-1), "last_time": q["time"][-1], "last_equity": net, "normal_closed_groups": len(trades) - proxy_count, "proxy_closed_groups": proxy_count, "proxy_quantity": abs(position[-1]), "proxy_reference_row": q["row"][-1] if proxy_count else -1, "proxy_reference_time": q["time"][-1] if proxy_count else -1, "normal_unclosed_before_proxy": abs(position[-1])}
    for key, value in independent.items():
        near(given["summary"][key], value, "保存summary独立会計:" + key)
    row_expected = {"net": net, "profit": gain, "loss": loss, "fees": total_paid, "entry_quantity": entry_quantity, "entry_orders": entry_orders, "groups": len(trades), "wins": independent["wins"], "losses": independent["losses"], "proxy_groups": proxy_count, "normal_groups": len(trades) - proxy_count, "max_long": maximum_long, "max_short": maximum_short, "forced_groups": forced, "forced_net": forced_net, "signal_groups": len(trades) - forced, "signal_net": net - forced_net}
    for key, value in row_expected.items():
        near(given[key], value, "小結果行の独立会計:" + key)
    rates = {"reference_price": q["last"][0], "capacity_notional": q["last"][0] * cap * multiplier, "actual_entry_notional": actual_entry_notional}
    for key, value in rates.items():
        near(given["rate_components"][key], value, "利益率の元本成分:" + key)
    return {"session": given["session"], "symbol": symbol, "method": given["method"], "passed": True, "groups": len(groups), "orders": len(orders), "proxy_groups": proxy_count, "net": net, "fees": total_paid, "max_long": maximum_long, "max_short": maximum_short, "all_tick_max_dd": float(max(dd)), "forced_groups": forced, "signal_groups": len(groups) - forced}


def main(expected_sha: str) -> None:
    """
    機能: 根の完成SHAを拘束して82入力・82結果NPZの984会計だけを保存監査する。
    引数: expected_sha (str) 根が金融完了後に通知する正式結果SHA。
    返り値: None。未知の利益率分母や目標合否を設定しない。
    """
    check(len(expected_sha) == 64, "根の正式結果SHA必須")
    result_bytes = RESULT.read_bytes()
    READS["完成結果"] += 1
    check(hashlib.sha256(result_bytes).hexdigest() == expected_sha, "完成結果同bytes")
    result = json.loads(result_bytes)
    fixed = json.loads((OWNER / "固定計画.json").read_bytes())
    check(result["passed"] and result["financial_accounts"] == 984 and len(result["cache"]) == 82 and len(result["rows"]) == 984, "十二条件二商品全四十一場の完成件数")
    check(result["sources"] == fixed["sources"], "完成結果の金融前固定源一致")
    for relative, value in fixed["sources"].items():
        path = ROOT / relative
        check(path.suffix == ".py" and path.resolve().is_relative_to(OWNER) and hashlib.sha256(path.read_bytes()).hexdigest() == value, "凍結源不変")
    manifest_bytes = (ROOT / fixed["inputs"]["path"]).read_bytes()
    check(hashlib.sha256(manifest_bytes).hexdigest() == fixed["inputs"]["sha256"], "固定入力目録同bytes")
    manifest = json.loads(manifest_bytes)
    check(result["sessions"] == manifest["sessions"] and len(manifest["inputs"]) == 82, "固定41場と82入力")
    check(result["original_market_reads"] == result["API"] == result["real_orders"] == 0, "新金融の原市場API実注文0")
    specs = {row["id"]: row for row in result["specs"]}
    check(result["specs"] == fixed["specs"], "結果の十二仕様は金融前固定と同一")
    check(len(specs) == 12 and set(specs) == {family + f"{i:02}" for family in ("A", "B", "C") for i in range(4)}, "固定十二条件の集合")
    lookup = {(row["session"], row["symbol"], row["method"]): row for row in result["rows"]}
    check(len(lookup) == 984, "結果行の識別欠落重複なし")
    metadata = {(item["session"], item["symbol"]): item for item in manifest["inputs"]}
    check(len(metadata) == 82, "入力82識別重複なし")
    columns = {"orders": result["order_columns"], "trades": result["trade_columns"]}
    certificates = []
    for info in result["cache"]:
        scene, symbol = info["session"], info["symbol"]
        item = metadata[scene, symbol]
        inp = packet(item, OWNER / "prepared", "保存入力")
        data = packet(info, OWNER / "measurement", "保存結果NPZ")
        check(set(data) == {ident + "__" + kind for ident in specs for kind in ("orders", "trades", "curve")}, "結果NPZは十二条件の三配列だけ")
        for ident, spec in specs.items():
            row = dict(lookup[scene, symbol, ident], session_end=item["end"])
            cert = reconstruct(inp, data[ident + "__orders"], data[ident + "__trades"], data[ident + "__curve"], row, spec, columns)
            certificates.append(cert)
        print(json.dumps({"完了口座": len(certificates), "session": scene, "symbol": symbol, "検査数": CHECKS}, ensure_ascii=False), flush=True)
    check(READS == {"完成結果": 1, "保存入力": 82, "保存結果NPZ": 82, "原市場": 0, "旧cache": 0, "金融再実行": 0}, "所有入力と結果は各一読のみ")
    proof = {"passed": True, "全合格": True, "result_sha256": expected_sha, "source_sha256": result["sources"], "audit_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "checks": CHECKS, "reads": READS, "audited_accounts": len(certificates), "全口座実終端flat": True, "proxyを通常注文へ偽装しない": True, "certificates": certificates, "目標合否": None, "利益率分母": "ユーザー確認待ち。元本成分のみ独立検証し合否を付けない。", "監査対象外": ["未記録のキャンセル判断カウンタとpending判定の完全再現", "入口と出口の戦略選択規則の再生", "真の受信順・実ミニ/マイクロ板・ライブ約定"], "金融再実行": 0, "原市場": 0, "旧cache": 0}
    print(json.dumps(save("十二条件と全九百八十四会計の独立保存監査.json", proof), ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    try:
        main(args.expected_sha)
    except BaseException as exc:
        name = "途中失敗_" + str(CHECKS) + ".json"
        if not (HERE / name).exists():
            save(name, {"passed": False, "型": type(exc).__name__, "理由": str(exc), "checks": CHECKS, "reads": READS, "金融再実行": 0})
        raise
