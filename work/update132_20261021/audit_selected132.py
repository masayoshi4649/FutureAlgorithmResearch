"""保存注文だけから00132追加分の会計・次正常原行約定を独立検算する。売買条件の再生は行わない。"""

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
from pathlib import Path
import pickle
import statistics

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRIOR = ROOT / "work/regime131_20261020/公開候補の43場統合.json"
JST = timezone(timedelta(hours=9))


def read(path):
    """
    機能: JSON証拠を読み取る。
    引数: path(Path又はstr) は保存場所。
    返り値: dict又はlist は保存内容。
    """
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def fingerprint(path):
    """
    機能: 監査対象の内容指紋を求める。
    引数: path(Path) はプロジェクト内ファイル。
    返り値: dict[str,str] は相対パスとSHA256。
    """
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def save(path, value):
    """
    機能: 今回の監査領域へ新しい証跡を保存する。
    引数: path(Path)、value(dict) は保存先と内容。
    返り値: None。既存結果を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def decimal(value):
    """
    機能: 保存された有限数値を十進数へ変換する。
    引数: value(int又はfloat) は金額又は価格。
    返り値: Decimal は十進の値。
    """
    return Decimal(str(float(value)))


def equal(actual, expected, name):
    """
    機能: 円会計と価格の微小丸めだけを許容して一致を検査する。
    引数: actual/expected(float又はndarray)、name(str) は比較値と項目。
    返り値: None。不一致で停止する。
    """
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-7, equal_nan=False, err_msg=name)


def audit_orders(orders, ready, quotes, symbol):
    """
    機能: 注文キャッシュフローから親会計・枚数推移を再構成し、BBOと次正常原行を独立検査する。
    引数: orders(ndarray[n,12])、ready/quotes(dict)、symbol(str) は保存注文と元の測定入力。
    返り値: tuple[dict,dict] は独立会計と方向別枚数配列。研究用会計関数は使用しない。
    """
    orders = np.asarray(orders)
    assert orders.ndim == 2 and orders.shape[1] == 12 and np.isfinite(orders).all()
    times, sequence = np.asarray(ready["time_s"]), np.asarray(ready["seq"])
    bid, ask = np.asarray(quotes["bid"]), np.asarray(quotes["ask"])
    valid = np.asarray(quotes["quote_valid"], dtype=bool) & np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask > bid)
    n = len(times)
    assert n and all(len(x) == n for x in (sequence, bid, ask, valid))
    assert np.all(np.diff(times) >= 0) and np.all(np.diff(sequence) > 0)
    normal = np.flatnonzero(valid)
    cap, multiplier, fee = (10, Decimal(1000), Decimal("41.8")) if symbol == "TOPIX" else (20, Decimal(10), Decimal(11))
    parents = {}
    holdings = {1: 0, -1: 0}
    changes = {1: np.zeros(n, dtype=np.int64), -1: np.zeros(n, dtype=np.int64)}
    maximum = {1: 0, -1: 0}
    max_gross = 0
    previous = -1
    next_row_checks = []
    for order in orders:
        row, source, identifier, side, qty, reason, opening = (int(order[k]) for k in (0, 1, 2, 3, 4, 6, 7))
        assert all(order[k] == int(order[k]) for k in (0, 1, 2, 3, 4, 6, 7, 11))
        assert 0 <= source < row < n and row >= previous and sequence[source] < sequence[row]
        assert side in (-1, 1) and qty > 0 and opening in (0, 1) and order[5] > 0
        expected_row_offset = int(np.searchsorted(normal, source, side="right"))
        assert expected_row_offset < len(normal) and row == normal[expected_row_offset], "判断後最初の正常原行以外で約定"
        equal(order[5], ask[row] if side > 0 else bid[row], "約定BBO")
        equal(order[9], times[row], "約定時計")
        equal(order[10], times[source], "判断時計")
        paid = (fee * qty).to_integral_value(rounding=ROUND_FLOOR)
        assert decimal(order[8]) == paid, "注文毎切捨て料金不一致"
        notional = -Decimal(side * qty) * decimal(order[5]) * multiplier
        if opening:
            assert identifier not in parents and times[row] < ready["limit"], "親重複又は新規期限超過"
            parents[identifier] = {"parent_id": identifier, "side": side, "quantity": qty, "remaining": qty,
                "entry_row": row, "entry_source": source, "entry_price": float(order[5]),
                "entry_reason": reason, "entry_phase": int(order[11]), "exit_row": None, "exit_reason": None,
                "gross_decimal": notional, "fees_decimal": paid, "exit_price_sum": Decimal(0)}
            held_side, delta = side, qty
        else:
            assert identifier in parents, "新規がない親の返済"
            parent = parents[identifier]
            assert parent["side"] == -side and 0 < qty <= parent["remaining"], "方向又は返済枚数不整合"
            parent["remaining"] -= qty
            parent["gross_decimal"] += notional
            parent["fees_decimal"] += paid
            parent["exit_price_sum"] += decimal(order[5]) * qty
            parent["exit_row"], parent["exit_reason"] = row, reason
            held_side, delta = parent["side"], -qty
        holdings[held_side] += delta
        changes[held_side][row] += delta
        assert all(0 <= size <= cap for size in holdings.values()), "各注文後の方向別保有上限超過"
        maximum[held_side] = max(maximum[held_side], holdings[held_side])
        max_gross = max(max_gross, sum(holdings.values()))
        next_row_checks.append({"parent_id": identifier, "source_index": source, "fill_index": row,
            "source_seq": int(sequence[source]), "fill_seq": int(sequence[row]),
            "same_price_clock": bool(times[source] == times[row])})
        previous = row
    assert holdings == {1: 0, -1: 0}, "場末に未返済あり"
    material = []
    for parent in parents.values():
        assert parent["remaining"] == 0 and parent["exit_row"] is not None
        result = {k: v for k, v in parent.items() if k not in ("gross_decimal", "fees_decimal", "exit_price_sum")}
        result.update(gross=float(parent["gross_decimal"]), fees=float(parent["fees_decimal"]),
            net=float(parent["gross_decimal"]-parent["fees_decimal"]),
            exit_price=float(parent["exit_price_sum"]/parent["quantity"]))
        material.append(result)
    nets = [p["net"] for p in material]
    summary = {"profit": sum(x for x in nets if x > 0), "loss": -sum(x for x in nets if x < 0),
        "net": sum(nets), "gross": sum(p["gross"] for p in material), "fees": sum(p["fees"] for p in material),
        "entries": len(material), "quantity": sum(p["quantity"] for p in material),
        "parent_wins": sum(x > 0 for x in nets), "parent_losses": sum(x < 0 for x in nets),
        "max_long": maximum[1], "max_short": maximum[-1], "max_gross_quantity": max_gross,
        "parents": material, "next_row_checks": next_row_checks}
    return summary, {"long_quantity": np.cumsum(changes[1]), "short_quantity": np.cumsum(changes[-1])}


def audit_measurement(row, arrays, packet):
    """
    機能: 独立注文会計を保存親・集計・枚数曲線と照合する。
    引数: row(dict)、arrays(dict)、packet(dict) は測定会計・配列・保存入力。
    返り値: dict は対象商品場の独立検算結果。
    """
    key = row["session"], row["symbol"]
    ready, quotes = packet["inputs"][key], packet["quotes"][key]
    independent, quantities = audit_orders(arrays["orders"], ready, quotes, row["symbol"])
    for field in ("profit", "loss", "net", "gross", "fees", "entries", "quantity", "parent_wins", "parent_losses", "max_long", "max_short", "max_gross_quantity"):
        equal(row[field], independent[field], field)
    for field, quantity in quantities.items():
        equal(arrays[field], quantity, field)
    equal(arrays["curve"][:, 1], quantities["long_quantity"]-quantities["short_quantity"], "曲線の符号数量")
    equal(arrays["curve"][-1, 0], independent["net"], "場末清算時価")
    equal(arrays["curve"][-1, 2], independent["net"], "場末実現収支")
    equal(arrays["input_seq"], ready["seq"], "保存原行番号")
    equal(arrays["input_time_s"], ready["time_s"], "保存価格時計")
    trades = arrays["trades"]
    assert trades.shape == (independent["entries"], 17)
    assert len(set(trades[:, 0])) == len(trades), "保存親番号重複"
    for parent in independent["parents"]:
        matches = trades[trades[:, 0] == parent["parent_id"]]
        assert len(matches) == 1
        record = matches[0]
        for column, field in ((1, "entry_row"), (2, "exit_row"), (3, "side"), (4, "quantity"),
                              (5, "entry_price"), (6, "exit_price"), (7, "gross"), (8, "fees"), (9, "net"),
                              (13, "entry_phase"), (15, "entry_reason"), (16, "exit_reason")):
            equal(record[column], parent[field], "保存親の"+field)
    for title, low, high in (("旧核", 0, 1000000), ("追加", 1000000, float("inf"))):
        subset = [p for p in independent["parents"] if low <= p["parent_id"] < high]
        checks = {"entries": len(subset), "profit": sum(p["net"] for p in subset if p["net"] > 0),
            "loss": -sum(p["net"] for p in subset if p["net"] < 0), "net": sum(p["net"] for p in subset),
            "gross": sum(p["gross"] for p in subset), "fees": sum(p["fees"] for p in subset)}
        for field, value in checks.items():
            equal(row["components"][title][field], value, title+field)
    for side, title in ((1, "買い"), (-1, "売り")):
        subset = [p for p in independent["parents"] if p["side"] == side]
        equal(row["direction"][title]["entries"], len(subset), title+"親数")
        equal(row["direction"][title]["net"], sum(p["net"] for p in subset), title+"収支")
    date = datetime.fromisoformat(row["session"].split("_")[0]).replace(tzinfo=JST)
    end = date.replace(hour=15, minute=45) if row["kind"] == "Day" else date.replace(hour=6)+timedelta(days=1)
    assert np.all(arrays["orders"][:, 9] <= end.timestamp()), "場外約定"
    assert independent["entries"] >= 1, "無取引場"
    return {"session": key[0], "symbol": key[1], "passed": True, **independent}


def totals(rows):
    """
    機能: 商品別・昼夜別の全場会計を集計する。
    引数: rows(list[dict]) は旧保存行と新独立会計行。
    返り値: dict は合計、黒赤場数、赤字規模、大勝ち除外後収支。
    """
    result = {}
    for symbol in ("TOPIX", "NK225"):
        result[symbol] = {}
        for kind in ("all", "Day", "Night"):
            selected = [r for r in rows if r["symbol"] == symbol and (kind == "all" or r["session"].endswith("_"+kind))]
            nets = [r["net"] for r in selected]
            positives, losses = [x for x in nets if x > 0], [-x for x in nets if x < 0]
            result[symbol][kind] = {"sessions": len(selected),
                **{field: sum(r[field] for r in selected) for field in ("profit", "loss", "net", "gross", "fees", "entries", "quantity")},
                "winning_sessions": len(positives), "losing_sessions": len(losses), "zero_sessions": sum(x == 0 for x in nets),
                "no_trade_sessions": sum(r["entries"] == 0 for r in selected),
                "average_loss": statistics.mean(losses) if losses else 0,
                "median_loss": statistics.median(losses) if losses else 0,
                "max_loss": max(losses, default=0),
                "without_top_three_net": sum(nets)-sum(sorted(positives, reverse=True)[:3])}
    return result


def artificial():
    """
    機能: 部分返済・両建て・切捨て料金と不正約定の検出を人工数値で検査する。
    引数: なし。
    返り値: dict は独立の手計算との一致結果。市場データを使用しない。
    """
    times = np.arange(6, dtype=float)
    ready = {"seq": np.arange(6)*3, "time_s": times, "limit": 100}
    quotes = {"bid": np.array([100, 100, 101, 104, 105, 106.]),
              "ask": np.array([100.5, 100.5, 101.5, 104.5, 105.5, 106.5]),
              "quote_valid": np.array([True, True, False, True, False, True])}
    orders = np.array([
        [1, 0, 0, 1, 5, 100.5, 20, 1, 209, 1, 0, 0],
        [3, 1, 0, -1, 2, 104, 7, 0, 83, 3, 1, 0],
        [3, 1, 1000000, -1, 5, 104, 82, 1, 209, 3, 1, 0],
        [5, 3, 0, -1, 3, 106, 2, 0, 125, 5, 3, 0],
        [5, 3, 1000000, 1, 5, 106.5, 32, 0, 209, 5, 3, 0]], dtype=float)
    result, _ = audit_orders(orders, ready, quotes, "TOPIX")
    expected = {"gross": 11000., "fees": 835., "net": 10165., "profit": 23083., "loss": 12918.,
                "max_long": 5, "max_short": 5, "max_gross_quantity": 8, "entries": 2, "quantity": 10}
    for key, value in expected.items():
        equal(result[key], value, "人工"+key)
    refused = []
    for problem in ("料金水増し", "BBO不一致", "同原行約定", "次正常行の飛越", "未返済", "片方向上限超過"):
        broken = orders.copy()
        if problem == "料金水増し":
            broken[0, 8] += 1
        elif problem == "BBO不一致":
            broken[0, 5] += .5
        elif problem == "同原行約定":
            broken[0, 1] = 1
        elif problem == "次正常行の飛越":
            broken[0, 0], broken[0, 5], broken[0, 9] = 3, 104.5, 3
        elif problem == "未返済":
            broken = broken[:-1]
        else:
            broken[0, 4], broken[0, 8] = 11, 459
        try:
            audit_orders(broken, ready, quotes, "TOPIX")
        except AssertionError:
            refused.append(problem)
        else:
            raise AssertionError("人工不正を受理: "+problem)
    return {"passed": True, "manual_expected": expected, "rejected": refused,
            "financial_replays": 0, "market_reads": 0}


def run(result_path, output):
    """
    機能: 完成した測定物を内容指紋付きで検算し、旧43場へ新2場を追加集計する。
    引数: result_path/output(Path) は保存会計と新監査出力。
    返り値: None。注文の生成や売買条件の選別を行わない。
    """
    result, prior = read(result_path), read(PRIOR)
    assert result["passed"] and result["prior_result"] == fingerprint(PRIOR)
    assert len(prior["rows"]) == 86 and len(result["rows"]) == 4
    assert len({r["session"] for r in prior["rows"]}) == 43
    assert {r["session"] for r in result["rows"]} == {"2026-10-20_Night", "2026-10-21_Day"}
    references = {ref["session"]: ref for ref in result["input_packets"]}
    packets = {}
    for scene, ref in references.items():
        path = ROOT / ref["path"]
        assert fingerprint(path)["sha256"] == ref["sha256"]
        packets[scene] = pickle.loads(path.read_bytes())
    caches = {(r["session"], r["symbol"]): r for r in result["cache"]}
    audited = []
    for row in result["rows"]:
        key = row["session"], row["symbol"]
        ref = caches[key]
        path = ROOT / ref["path"]
        assert fingerprint(path)["sha256"] == ref["sha256"]
        with np.load(path, allow_pickle=False) as archive:
            arrays = {name: archive[name] for name in archive.files}
        audited.append(audit_measurement(row, arrays, packets[key[0]]))
    combined = prior["rows"] + audited
    assert len({(r["session"], r["symbol"]) for r in combined}) == 90
    for row in combined:
        equal(row["profit"]-row["loss"], row["net"], "全行の利益−損失")
        equal(row["gross"]-row["fees"], row["net"], "全行の手数料後")
    result = {"passed": True, "source": fingerprint(result_path), "prior_source": fingerprint(PRIOR),
        "auditor": fingerprint(Path(__file__)), "manual_test": artificial(), "new_rows": audited,
        "new_totals": totals(audited), "all_45_session_totals": totals(combined),
        "scope": "追加注文のみ独立会計。旧86行は既存保存会計から再集計し、旧金融判断を再生しない。",
        "financial_replays": 0, "API": 0, "real_orders": 0}
    save(output, result)
    print(json.dumps({"passed": True, "new_totals": result["new_totals"],
                      "all_45_session_totals": result["all_45_session_totals"]}, ensure_ascii=False))


def main():
    """
    機能: 人工検査又は保存注文監査を実行する。
    引数: CLIは--self-test又は--result/--output。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--result", type=Path, default=HERE / "results/追加セッションの会計.json")
    parser.add_argument("--output", type=Path, default=HERE / "audit/独立注文会計と45場合計.json")
    args = parser.parse_args()
    if args.self_test:
        save(args.output, artificial())
    else:
        run(args.result, args.output)


if __name__ == "__main__":
    main()
