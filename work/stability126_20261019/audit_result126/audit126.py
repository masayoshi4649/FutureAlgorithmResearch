"""完成した保存会計だけを一読し、注文から全行の現金・在庫・時価を独立復元する。"""

from __future__ import annotations

from collections import Counter, defaultdict
from io import BytesIO
import ast
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
READS = {}


def read_once(path, expected=None):
    """
    機能: 指定した保存結果を一度だけ読み、同じバイト列で指紋を確認する。
    引数: path(Path)、expected(str|None)は期待指紋。
    返り値: bytesは読取内容。同じ監査で同じファイルを再読しない。
    """
    path = path.resolve()
    assert path.is_relative_to(WORK), str(path)
    key = path.relative_to(ROOT).as_posix()
    assert key not in READS, ("同じ監査の再読", key)
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    assert expected is None or digest == expected, (key, digest, expected)
    READS[key] = dict(reads=1, sha256=digest, bytes=len(payload))
    return payload


def number_equal(actual, expected, label):
    """
    機能: 円換算前の価格算術を許容誤差内で照合する。
    引数: actual/expected(float|ndarray)、label(str)は位置説明。
    返り値: None。不一致は例外。
    """
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-6, err_msg=label)


def audit_account(row, arrays, price=None):
    """
    機能: エンジンの会計関数を使わず、全注文・元玉・返済脚・親組を再構成する。
    引数: row(dict)、arrays(dict[str,ndarray])、price(ndarray|None)は保存会計と当時価格。
    返り値: dictは独立再計算した損益・数量・全行監査の要約。
    """
    symbol = row["symbol"]
    multiplier, quantity, cap = (1000., 5, 10) if symbol == "TOPIX" else (10., 10, 20)
    orders, trades, cycles = (arrays[name] for name in ("orders", "trades", "cycles"))
    assert orders.ndim == 2 and orders.shape[1] == 8
    assert trades.ndim == 2 and trades.shape[1] == 11
    assert cycles.ndim == 2 and cycles.shape[1] == 10
    for name, values in arrays.items():
        assert np.isfinite(values).all(), (row["session"], symbol, row["method"], name)
    assert np.all(np.diff(orders[:, 0]) >= 0) if len(orders) else True
    assert np.all(orders[:, 0] == orders[:, 0].astype(int))
    assert np.all(orders[:, 4] == orders[:, 4].astype(int)) and np.all(orders[:, 4] > 0)
    assert np.all(np.isin(orders[:, 3], [-1., 1.]))
    held, entries, entry_by_leg, order_exits = {}, {}, {}, Counter()
    parent_gain = defaultdict(float)
    cash, signed, long_qty, short_qty = 0., 0., 0., 0.
    max_long, max_short, max_gross, max_net = 0., 0., 0., 0.
    entry_count, close_qty = 0, 0
    n = 0 if price is None else len(price)
    cash_changes = np.zeros(n)
    net_changes = np.zeros(n)
    long_changes = np.zeros(n)
    short_changes = np.zeros(n)
    realized_changes = np.zeros(n)
    for order in orders:
        raw, source, cid, side, qty = (int(v) for v in order[:5])
        fill, reason, role = float(order[5]), int(order[6]), int(order[7])
        assert 0 <= source < raw, (row["method"], raw, source)
        if price is not None:
            assert 0 <= raw < n
            number_equal(fill, price[raw], "観測Last約定")
        if role == 1:
            assert cid not in held and qty == quantity, (cid, qty, quantity)
            assert not any(v[0] for v in held.values()), "別親の残玉中に新規した"
            held[cid] = [qty, side, fill, raw]
            entries[cid] = [qty, side, fill, raw]
            entry_by_leg[entry_count] = [cid, qty, side, fill, raw]
            entry_count += 1
            if side > 0:
                long_qty += qty
            else:
                short_qty += qty
        else:
            assert role == 0 and cid in held
            position = held[cid]
            assert position[0] >= qty and position[1] == -side
            gain = -side * qty * (fill-position[2])
            parent_gain[cid] += gain
            position[0] -= qty
            close_qty += qty
            if side < 0:
                long_qty -= qty
            else:
                short_qty -= qty
            order_exits[(raw, cid, -side, qty, fill, reason)] += 1
            if price is not None:
                realized_changes[raw] += gain
        cash -= side * qty * fill
        signed += side * qty
        max_long, max_short = max(max_long, long_qty), max(max_short, short_qty)
        max_gross, max_net = max(max_gross, long_qty+short_qty), max(max_net, abs(signed))
        assert 0 <= long_qty <= cap and 0 <= short_qty <= cap
        if price is not None:
            cash_changes[raw] -= side*qty*fill
            net_changes[raw] += side*qty
            if (role == 1 and side > 0) or (role == 0 and side < 0):
                long_changes[raw] += qty if role == 1 else -qty
            else:
                short_changes[raw] += qty if role == 1 else -qty
    assert not any(v[0] for v in held.values()) and long_qty == short_qty == signed == 0
    observed_exits = Counter()
    returned = defaultdict(int)
    gain_by_trade = []
    for trade in trades:
        cid, leg, direction, qty = (int(v) for v in trade[:4])
        entry, fill, entry_row, close_row, _, reason, saved_gain = trade[4:]
        assert leg in entry_by_leg
        original = entry_by_leg[leg]
        assert [cid, direction, float(entry), int(entry_row)] == [original[0], original[2], original[3], original[4]]
        returned[leg] += qty
        assert returned[leg] <= original[1]
        gain = direction * qty * (fill-entry)
        number_equal(saved_gain, gain, "返済脚の外部算術")
        gain_by_trade.append(gain)
        observed_exits[(int(close_row), cid, direction, qty, float(fill), int(reason))] += 1
    assert observed_exits == order_exits
    assert all(returned[k] == v[1] for k, v in entry_by_leg.items())
    assert len(cycles) == len(entries)
    for cycle in cycles:
        cid, entry_row, close_row = (int(v) for v in cycle[:3])
        assert cid in entries and entry_row == entries[cid][3]
        own = trades[trades[:, 0] == cid]
        assert len(own) and close_row == own[:, 7].max()
        assert cycle[8] == entries[cid][1]
        number_equal(cycle[3], parent_gain[cid], "親組の外部算術")
        number_equal(cycle[4], quantity*cycle[5], "親組初回固定リスク")
    gains = np.asarray(gain_by_trade, float)*multiplier
    parents = np.asarray([parent_gain[int(v)] for v in cycles[:, 0]], float)*multiplier
    profit = float(gains[gains > 0].sum())
    loss = float(-gains[gains < 0].sum())
    net = profit-loss
    checks = dict(profit=profit, loss=loss, net=net, fees=0,
        parent_profit=float(parents[parents > 0].sum()), parent_loss=float(-parents[parents < 0].sum()),
        parent_wins=int((parents > 0).sum()), parent_losses=int((parents < 0).sum()),
        entry_orders=entry_count, entry_quantity=int(orders[orders[:, 7] == 1, 4].sum()),
        closed_quantity=close_qty, winning_quantity=int(trades[gains > 0, 3].sum()),
        losing_quantity=int(trades[gains < 0, 3].sum()), groups=len(cycles), unclosed=0,
        max_long=max_long, max_short=max_short,
        long_net=float(gains[trades[:, 2] > 0].sum()), short_net=float(gains[trades[:, 2] < 0].sum()))
    for name, value in checks.items():
        if name in row:
            number_equal(row[name], value, name)
    number_equal(net, cash*multiplier, "最終現金と損益")
    number_equal(net, parents.sum(), "全親組合計")
    if price is not None:
        curve, stats = arrays["curve"], arrays["stats"]
        assert curve.shape == (n, 8)
        cash_curve = np.cumsum(cash_changes)
        position_curve = np.cumsum(net_changes)
        long_curve, short_curve = np.cumsum(long_changes), np.cumsum(short_changes)
        realized_curve = np.cumsum(realized_changes)
        equity = cash_curve + position_curve*price
        high = np.maximum.accumulate(np.maximum(0., equity))
        maximum_drawdown = np.maximum.accumulate(high-equity)
        for col, values in ((0, equity), (1, realized_curve), (2, long_curve), (3, short_curve),
                            (4, maximum_drawdown), (5, cash_curve), (6, position_curve)):
            number_equal(curve[:, col], values, "全行曲線列"+str(col))
        for col, expected in ((0, net/multiplier), (1, maximum_drawdown[-1]),
                              (2, max_long), (3, max_short), (4, max_gross), (5, max_net),
                              (7, min(0., equity.min())), (8, max(0., equity.max())), (9, 0.)):
            number_equal(stats[col], expected, "統計列"+str(col))
        assert stats[6] <= 1e-6
    return dict(method=row["method"], session=row["session"], symbol=symbol,
                profit=profit, loss=loss, net=net, entry_orders=entry_count,
                entry_quantity=checks["entry_quantity"], closed_quantity=close_qty,
                rows=n, order_rows=len(orders), trade_rows=len(trades), groups=len(cycles),
                curve_audited=price is not None)


def totals(rows):
    """
    機能: 個別会計から商品別の累計と各場収支を独立集計する。
    引数: rows(list[dict])は独立検算済み行。
    返り値: list[dict]は各条件各商品の合計と活動数。
    """
    output = []
    for method in sorted({r["method"] for r in rows}):
        for symbol in ("TOPIX", "NK225"):
            own = [r for r in rows if r["method"] == method and r["symbol"] == symbol]
            amounts = sorted(float(r["net"]) for r in own)
            output.append(dict(method=method, symbol=symbol,
                profit=sum(r["profit"] for r in own), loss=sum(r["loss"] for r in own),
                net=sum(amounts), black=sum(v > 0 for v in amounts), red=sum(v < 0 for v in amounts),
                zero=sum(v == 0 for v in amounts), activity=sum(r["entry_orders"] > 0 for r in own),
                median=float(np.median(amounts)), worst=min(amounts), top3_excluded=sum(amounts[:-3])))
    return output


def main():
    """
    機能: 完成会計の指紋を先に拘束し、新金融をせず全商品場を独立監査する。
    引数: コマンド行の結果ＳＨＡ２５６(str)を一つ受け取る。
    返り値: None。各会計と累計の一致を監査所有域へ保存する。
    """
    assert len(sys.argv) == 2 and len(sys.argv[1]) == 64
    result_path = WORK/"原版と十五改修の全四十一場会計.json"
    result = json.loads(read_once(result_path, sys.argv[1]))
    assert result["passed"] and result["new_financial_accounts"] == 1252
    assert result["reused_accounts"] == 60 and result["displayed_accounts"] == 1312
    rows = result["rows"]
    index = {(r["method"], r["session"], r["symbol"]):r for r in rows}
    assert len(index) == 1312 and len(result["sessions"]) == 41
    specs = {r["id"]:r for r in result["specs"]}
    assert len(specs) == 16
    assert set(index) == {(m, s, p) for m in specs for s in result["sessions"] for p in ("TOPIX", "NK225")}
    fixed = json.loads(read_once(WORK/"固定計画_確定書式.json"))
    manifest = json.loads(read_once(ROOT/fixed["input"]["path"], fixed["input"]["sha256"]))
    baseline = json.loads(read_once(ROOT/result["baseline"]["path"], result["baseline"]["sha256"]))
    old_rows = {(r["session"], r["symbol"]):r for r in baseline["rows"]}
    old_data = np.load(BytesIO(read_once(ROOT/baseline["cache"]["path"], baseline["cache"]["sha256"])), allow_pickle=False)
    summaries, total_curve_rows, cache_reads = [], 0, []
    metadata = {(r["session"], r["symbol"]):r for r in result["metadata"]}
    caches = {(r["session"], r["symbol"]):r for r in result["cache"]}
    assert len(caches) == len(metadata) == 82
    for packet_item in manifest["packets"]:
        packet = pickle.loads(read_once(ROOT/packet_item["path"], packet_item["sha256"]))
        scene = packet["session"]
        assert scene == packet_item["session"] and scene in result["sessions"]
        assert set(packet["inputs"]) == {(scene, "TOPIX"), (scene, "NK225")}
        for symbol in ("TOPIX", "NK225"):
            ready = packet["inputs"][(scene, symbol)]
            assert ready["session"] == scene and ready["symbol"] == symbol
            price = np.asarray(ready["last"], float)
            assert np.isfinite(price).all() and (price > 0).all()
            assert np.all(np.diff(ready["time_s"]) >= 0) and np.all(np.diff(ready["seq"]) >= 0)
            assert ready["time_s"][0] >= ready["start"]
            assert ready["time_s"][-1] <= ready.get("session_close", ready["limit"]+600.)
            meta = metadata[(scene, symbol)]
            number_equal([meta["first"], meta["last"]], [price[0], price[-1]], "事後分類価格")
            difference = price[-1]/price[0]-1.
            expected_regime = "上昇" if difference > 0 else "下落" if difference < 0 else "同値"
            assert meta["regime"] == expected_regime
            assert meta["strong_regime"] == (expected_regime if abs(difference) >= .0025 else "小変動")
            item = caches[(scene, symbol)]
            payload = read_once(ROOT/item["path"], item["sha256"])
            with np.load(BytesIO(payload), allow_pickle=False) as archive:
                methods = {k.split("__")[0] for k in archive.files}
                expected = set(specs)-({"E01"} if (scene, symbol) in old_rows else set())
                assert methods == expected
                for method in sorted(methods):
                    values = {name:archive[method+"__"+name] for name in ("orders", "trades", "cycles", "curve", "stats", "policy_events126")}
                    summaries.append(audit_account(index[(method, scene, symbol)], values, price))
                    total_curve_rows += len(price)
                cache_reads.append(dict(path=item["path"], accounts=len(methods), rows=len(price)))
            if (scene, symbol) in old_rows:
                prefix = symbol+"_"+scene+"__"
                values = {name:old_data[prefix+name] for name in ("orders", "trades", "cycles")}
                summaries.append(audit_account(index[("E01", scene, symbol)], values))
        print(scene+" の全保存注文・在庫・時価を独立照合", flush=True)
    old_data.close()
    assert len(summaries) == 1312
    assert sum(r["curve_audited"] for r in summaries) == 1252
    assert len(cache_reads) == 82
    artificial_paths = [WORK/"audit_artificial"/name for name in (
        "原版と十六条件の最終源による独立純人工監査.json",
        "相手厳密過去と窓端の独立純人工監査.json",
        "通常影の五分待機と設定有限JSONの最終純人工監査.json")]
    artificial = [json.loads(read_once(path)) for path in artificial_paths]
    assert all(v["全合格"] for v in artificial)
    registration_path = WORK/"正式登録_確定書式の全出力.json"
    registration = json.loads(read_once(registration_path))
    assert registration["終了コード"] == 0
    registered = json.loads(registration["stdout"])
    assert registered["spec"]["implementation"] == result["sources"] == fixed["sources"]
    completed_artificial = max(path.stat().st_mtime_ns for path in artificial_paths)
    completed_registration = registration_path.stat().st_mtime_ns
    first_result = min((ROOT/p["path"]).stat().st_mtime_ns for p in result["cache"])
    assert completed_artificial < completed_registration < first_result
    runner_source = (WORK/"run126.py").read_text(encoding="utf-8")
    runner_tree = ast.parse(runner_source)
    play_calls = [node for node in ast.walk(runner_tree) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute) and node.func.attr == "play"]
    assert len(play_calls) == 1
    assert [ast.unparse(v) for v in play_calls[0].args] == ["runtime", "config", "ready", "feature", "market"]
    execute_node = next(n for n in runner_tree.body if isinstance(n, ast.FunctionDef) and n.name == "execute")
    early_check = next(n.lineno for n in ast.walk(execute_node) if isinstance(n, ast.Assert)
                       and "registered['終了コード']" in ast.unparse(n))
    assert early_check < play_calls[0].lineno
    audit = dict(passed=True, result_sha256=sys.argv[1], accounts=1312,
        new_accounts_audited=1252, old_accounts_reused_audited=60,
        full_curve_rows=total_curve_rows, rows=summaries, totals=totals(summaries),
        input_and_result_reads=READS, new_financial_replays=0,
        original_market_reads=0, API=0, real_orders=0,
        classification="上昇下落は全41場の事後採点。価格終端は公的終値とは限らない。",
        scope="新1252口座は全注文・返済脚・親組・全行現金在庫時価、旧60は保存注文返済と親組の独立検算。旧30場の売買再生なし。",
        timeline=dict(artificial_completed_ns=completed_artificial,
                      registration_completed_ns=completed_registration,
                      first_financial_output_ns=first_result,
                      order="純人工成功の保存→成功登録の保存→最初の金融出力。源でも登録確認をplay前に拘束。"),
        retrospective_labels="分類metadataをpolicy.playへ渡さず、固定catalogを全場へ実行するASTを確認。",
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    output = HERE/"全千三百十二会計と全行時価及び累計の独立監査.json"
    assert not output.exists()
    output.write_text(json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(dict(passed=True, accounts=len(summaries), full_curve_rows=total_curve_rows), ensure_ascii=False))


if __name__ == "__main__":
    main()
