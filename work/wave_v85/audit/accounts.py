"""保存注文から全玉時価・分割料金・P/Cの状態遷移を独立再構成する。"""

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import pickle
import time
import numpy as np

from original import module, read, HERE, WORK, ROOT


def equal(a, b):
    """
    機能: 有限小数の計算順の差だけを許し構造と数値を照合する。
    引数: a/b (object)。
    返り値: None。
    """
    if isinstance(a, dict):
        assert set(a) == set(b), (set(a) - set(b), set(b) - set(a))
        for k in a:
            equal(a[k], b[k])
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            equal(x, y)
    elif a is None or b is None:
        assert a is b
    elif isinstance(a, (float, np.floating)):
        assert math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-5), (a, b)
    else:
        assert a == b, (a, b)


def ratios(row):
    """
    機能: 手数料後の脚・親組の金額比率と回数を独立に追記する。
    引数: row (dict)。
    返り値: dict。
    """
    for prefix in ("", "campaign_"):
        gain, loss = row[prefix + "profit"], row[prefix + "loss"]
        row[prefix + "profit_share"] = gain / (gain + loss) if gain + loss else None
        row[prefix + "pf"] = gain / loss if loss else None
    row.update(cycle_profit=row["campaign_profit"], cycle_loss=row["campaign_loss"], cycle_net=row["net"],
        cycles=row["campaigns"], cycle_wins=row["campaign_wins"], cycle_losses=row["campaign_losses"],
        cycle_profit_share=row["campaign_profit_share"], cycle_pf=row["campaign_pf"], cycle_payoff=row["campaign_payoff"],
        cycle_avg_net=row["net"] / row["campaigns"] if row["campaigns"] else None,
        cycle_win_rate=row["campaign_wins"] / row["campaigns"] if row["campaigns"] else None,
        trades=row["wins"] + row["losses"] + row["flats"],
        settled_lots=row["winning_lots"] + row["losing_lots"] + row["flat_lots"])
    return row


def trace(ready, ledger, row):
    """
    機能: 注文現金と各方向在庫だけから全原板行の会計を復元する。
    引数: ready/ledger/row (dict)。
    返り値: dict の全行時価・確定損益・料金・在庫。
    """
    n = len(ready["last"])
    orders = np.asarray(ledger["orders"]).reshape(-1, 8)
    trades = np.asarray(ledger["trades"]).reshape(-1, 11)
    scale = 1000 if ready["symbol"] == "TOPIX" else 10
    fee_unit = 418 if ready["symbol"] == "TOPIX" else 110
    cash = np.zeros(n)
    qty = np.zeros(n)
    longs, shorts = np.zeros(n), np.zeros(n)
    gross = np.zeros(n)
    fees = np.zeros(n)
    campaign = np.full(n, -1.)
    for o in orders:
        i, side, q = int(o[0]), int(o[3]), int(o[4])
        cash[i] -= side * q * o[5]
        qty[i] += side * q
        fees[i] += q * fee_unit // 10
        direction = side if o[7] else -side
        inventory = longs if direction == 1 else shorts
        inventory[i] += q if o[7] else -q
        if o[7]:
            campaign[i:] = o[2]
    for t in trades:
        gross[int(t[7])] += t[2] * t[3] * (t[5] - t[4])
    cash, qty, longs, shorts, gross, fees = map(np.cumsum, (cash, qty, longs, shorts, gross, fees))
    assert np.all(longs >= 0) and np.all(shorts >= 0) and longs[-1] == shorts[-1] == 0
    raw = cash + qty * ready["last"]
    raw_dd = np.maximum.accumulate(np.maximum.accumulate(np.maximum(raw, 0)) - raw)
    net = raw * scale - fees
    raw_curve = np.c_[raw, gross, longs, shorts, raw_dd, cash, qty, campaign]
    expected_stats = [gross[-1], raw_dd[-1], longs.max(initial=0), shorts.max(initial=0),
        (longs + shorts).max(initial=0), np.abs(qty).max(initial=0), 0., raw.min(initial=0), raw.max(initial=0), 0., 0.]
    np.testing.assert_allclose(ledger["stats"], expected_stats, atol=1e-8, rtol=0)
    assert hashlib.sha256(raw_curve.tobytes()).hexdigest() == ledger["raw_curve_SHA256"]
    assert hashlib.sha256(net.tobytes()).hexdigest() == ledger["curve_SHA256"]
    assert abs(net[-1] - row["net"]) < 1e-5
    row.update(entry_orders=int(np.count_nonzero(orders[:, 7])), exit_orders=int(np.count_nonzero(orders[:, 7] == 0)),
        new_lots=int(orders[orders[:, 7] == 1, 4].sum()), exit_lots=int(orders[orders[:, 7] == 0, 4].sum()),
        max_gross=int((longs + shorts).max(initial=0)), max_net=int(np.abs(longs - shorts).max(initial=0)),
        equity_min=float(net.min(initial=0)), equity_max=float(net.max(initial=0)), residual_long=0, residual_short=0,
        guard_event_count=len(ledger["guard_events"]))
    row["reason_counts"] = {str(int(r)): int(np.count_nonzero(trades[:, 9] == r)) for r in np.unique(trades[:, 9])}
    events = ledger.get("time_events", np.empty((0, 7)))
    windows = ledger.get("time_windows", [])
    row.update(time_forced_exits=int(np.sum(events[:, 2] == 1)),
        time_rejected_preparations=int(np.sum(events[:, 2] == 2)),
        time_exit_lots=int(orders[(orders[:, 7] == 0) & (orders[:, 6] == 71), 4].sum()),
        time_window_count=len(windows), time_first_observation_after_window=sum(w["窓終了後の初観測"] for w in windows))
    return dict(raw=raw, net=net, gross=gross, fees=fees, qty=longs + shorts, scale=scale, fee_unit=fee_unit)


def guards(ready, ledger, trace_values, enabled):
    """
    機能: 実玉の最大清算利益とP予約・元利確との競合を注文会計から照合する。
    引数: ready/ledger/trace_values (dict)、enabled (bool)。
    返り値: int のイベント照合数。
    """
    events = ledger["guard_events"]
    if not enabled:
        assert not len(events)
        return 0
    grouped = defaultdict(list)
    for e in events:
        grouped[int(e[1])].append(e)
    cycles = {int(c[0]): c for c in ledger["cycles"]}
    orders = ledger["orders"]
    scale, fee_unit = trace_values["scale"], trace_values["fee_unit"]
    for cid, items in grouped.items():
        cycle = cycles[cid]
        start, end = int(cycle[1]), int(cycle[2])
        base = trace_values["gross"][start - 1] if start else 0.
        base_fee = trace_values["fees"][start - 1] if start else 0.
        amount = trace_values["raw"][start:end] - base
        actual_fee = (trace_values["fees"][start:end] - base_fee) / scale
        future_fee = np.floor(trace_values["qty"][start:end] * fee_unit / 10) / scale
        liquid = amount - actual_fee - future_fee
        peak = np.maximum.accumulate(np.maximum(liquid, 0))
        pending = -1
        armed = False
        for e in items:
            i, code = int(e[0]), int(e[2])
            assert start <= i <= end and int(e[8]) == int(cycle[8])
            if code in (1, 2):
                p = float(peak[i - start])
                equal(e[4], liquid[i - start])
                equal(e[5], p)
                equal(e[6], p * .5)
                assert p >= 1.5 * cycle[4]
                assert int(e[3]) == i
                if code == 1:
                    assert not armed
                    armed = True
                else:
                    assert armed and pending < 0 and liquid[i - start] <= .5 * p
                    pending = i
            elif code == 3:
                assert pending == int(e[3]) and i > pending
                hit = [o for o in orders if int(o[2]) == cid and int(o[0]) == i and int(o[6]) == 70]
                assert len(hit) == 1 and int(hit[0][1]) == pending and hit[0][4] == e[7]
                pending = -1
            elif code in (4, 5):
                assert pending == int(e[3]) and i > pending
                hit = [o for o in orders if int(o[2]) == cid and int(o[0]) == i and not o[7]]
                if code == 4:
                    assert not hit or any(int(o[6]) == 7 for o in hit)
                else:
                    assert hit and all(int(o[6]) != 7 for o in hit)
                    pending = -1
            else:
                raise AssertionError(code)
        assert pending < 0
    return len(events)


def blocks(ledger, feature, enabled):
    """
    機能: 方向別の確定料金後連敗と、新しい双方EMAによる解除を独立照合する。
    引数: ledger/feature (dict)、enabled (bool)。
    返り値: int の停止・解除イベント数。
    """
    events = ledger["block_events"]
    if not enabled:
        assert not len(events)
        return 0
    ema, own, peer, valid = feature["ema"]
    grouped = defaultdict(float)
    for t in ledger["net_trades"]:
        grouped[int(t["組"])] += t["収支"]
    cycles = {int(c[2]): c for c in ledger["cycles"]}
    by_row = defaultdict(list)
    for e in events:
        by_row[int(e[0])].append(e)
    entries = {int(o[0]): int(o[3]) for o in ledger["orders"] if o[7]}
    loss = {1: 0, -1: 0}
    block = {}
    reset = {}
    for i in sorted(set(cycles) | set(by_row) | set(entries)):
        if i in entries:
            assert entries[i] not in block
        if i in cycles:
            c = cycles[i]
            direction = int(c[8])
            loss[direction] = loss[direction] + 1 if grouped[int(c[0])] < 0 else 0
            expected = loss[direction] >= 2
            assert any(int(e[2]) == 1 and int(e[3]) == direction for e in by_row[i]) == expected
        for e in by_row[i]:
            code, direction = int(e[2]), int(e[3])
            if code != 3:
                equal(e[4], loss[direction])
            if code == 1:
                assert direction not in block and loss[direction] >= 2
                block[direction] = i
            elif code == 2:
                assert direction in block and direction not in reset
                assert valid[i] and ema[i] != direction and own[i] > block[direction] and peer[i] > block[direction]
                reset[direction] = (own[i], peer[i])
            elif code == 3:
                assert direction in block and direction in reset
                assert valid[i] and ema[i] == direction
                assert own[i] > reset[direction][0] and peer[i] > reset[direction][1]
                loss[direction] = 0
                assert e[4] == 0
                del block[direction], reset[direction]
            else:
                raise AssertionError(code)
            assert int(e[6]) == own[i] and int(e[7]) == peer[i]
    return len(events)


def time_windows(ready, ledger, trace_values, strategy, mode):
    """
    機能: 予定停止の初回返済・窓内禁止・終了後の新しい準備を保存注文から確認する。
    引数: ready/ledger/trace_values (dict)、strategy (module)、mode (str)。
    返り値: int の時間イベント数。
    """
    quiet = strategy.time_filter.features(ready, mode)
    equal(ledger.get("time_windows", []), quiet["windows"])
    events = ledger.get("time_events", np.empty((0, 7)))
    orders = ledger["orders"]
    preparations = {(int(v[0]), int(v[1])): int(v[3]) for v in ledger["entry_preparations"]}
    if not mode:
        assert not len(events)
    for o in orders:
        i = int(o[0])
        if o[7]:
            assert not quiet["active"][i] and not quiet["force"][i]
            preparation = preparations[int(o[2]), i]
            assert ready["time_s"][preparation] >= quiet["not_before"][i]
        elif int(o[6]) == 71:
            assert quiet["force"][i] and int(o[1]) == i - 1 and o[5] == ready["last"][i]
    for i in np.flatnonzero(quiet["force"]):
        previous = trace_values["qty"][i - 1] if i else 0.
        assert trace_values["qty"][i] == 0
        closing = [o for o in orders if int(o[0]) == i and int(o[6]) == 71]
        assert sum(o[4] for o in closing) == previous
    for e in events:
        i, code, source = int(e[0]), int(e[2]), int(e[3])
        assert e[6] - e[5] == 1800
        assert any(w["start"] == e[5] and w["end"] == e[6] for w in quiet["windows"])
        if code == 1:
            assert quiet["force"][i] and source == i - 1
            assert sum(o[4] for o in orders if int(o[0]) == i and int(o[6]) == 71) == e[4]
        elif code == 2:
            assert quiet["active"][i] or ready["time_s"][source] < quiet["not_before"][i]
        else:
            raise AssertionError(code)
    return len(events)


def aggregate(old, rows, symbol, names):
    """
    機能: 日次会計から期間の収支・無取引・連結DDを独立再計算する。
    引数: old (module)、rows (list[dict])、symbol (str)、names (list[str])。
    返り値: dict。
    """
    subset = sorted([r for r in rows if r["symbol"] == symbol and r["session"] in names], key=lambda r: r["session"])
    result = old.aggregate(rows, symbol, names)
    wealth = high = dd = 0.
    for row in subset:
        dd = max(dd, row["max_drawdown"], high - wealth - row["equity_min"])
        high = max(high, wealth + row["equity_max"])
        wealth += row["net"]
    best = max(subset, key=lambda r: r["net"]) if subset else None
    result.update(max_drawdown=dd, no_trade_sessions=sum(r["campaigns"] == 0 for r in subset),
        flat_active_sessions=sum(r["campaigns"] > 0 and r["net"] == 0 for r in subset),
        best_session=max((r["net"] for r in subset), default=0.), worst_session=min((r["net"] for r in subset), default=0.),
        best_session_id=best["session"] if best else None, best_session_removed=result["net"] - best["net"] if best else None)
    for name in ("entry_orders", "exit_orders", "new_lots", "exit_lots", "guard_event_count", "time_forced_exits",
                 "time_rejected_preparations", "time_exit_lots", "time_window_count", "time_first_observation_after_window"):
        result[name] = sum(r[name] for r in subset)
    for name in ("max_long", "max_short", "max_gross", "max_net"):
        result[name] = max((r[name] for r in subset), default=0)
    active = sum(r["campaigns"] > 0 for r in subset)
    result["positive_active_share"] = result["positive_sessions"] / active if active else None
    return ratios(result)


def main():
    """
    機能: 完了済み全部品と時間帯の実行を独立FIFO・全行時価・保護停止証跡で検査する。
    引数: --partial (bool) は現時点の保存済みだけを監査する指定。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--partial", action="store_true")
    parser.add_argument("--ids", default="")
    parser.add_argument("--wait", action="store_true")
    args = parser.parse_args()
    chosen = set(args.ids.split(",")) if args.ids else None
    assert chosen is None or args.partial
    fixed = read(WORK / "results/事前固定.json")
    for section, home in (("code_SHA256", WORK), ("legacy_code_SHA256", ROOT), ("reference_SHA256", ROOT)):
        for name, digest in fixed[section].items():
            assert hashlib.sha256((home / name).read_bytes()).hexdigest() == digest
    prepare = module("wave85_audit_prepare", WORK / "prepare.py")
    strategy = module("wave85_strategy", WORK / "strategy.py")
    old = module("wave85_old_independent", ROOT / "work/wave_v67/audit/independent_accounting.py")
    inputs, signals, _ = prepare.load_inputs()
    features = strategy.initialize(inputs, signals)
    totals = dict(条件数=0, 口座数=0, 注文数=0, 決済脚数=0, 組数=0, P証跡数=0, C証跡数=0, 時間証跡数=0, 原版旧一致口座数=0)
    reports = []
    for model in ("specified", "observed"):
        for config in fixed["catalog"]:
            if chosen is not None and config["id"] not in chosen:
                continue
            path = WORK / model / "results" / (config["id"] + ".json")
            if not path.exists() and args.partial:
                continue
            if not path.exists() and args.wait:
                print(model, config["id"], "結果の確定を待機", flush=True)
                until = time.monotonic() + 300
                while not path.exists() and time.monotonic() < until:
                    time.sleep(1)
            packet = read(path)
            ledger_path = WORK / model / "ledgers" / (config["id"] + ".pkl")
            assert hashlib.sha256(ledger_path.read_bytes()).hexdigest() == packet["ledger_SHA256"]
            with ledger_path.open("rb") as stream:
                ledgers = pickle.load(stream)
            assert len(ledgers) == len(packet["rows"]) == 60
            reference = None
            if config["id"] in ("E01", "E01_G"):
                old_id = "E01" if config["id"] == "E01" else "R01"
                reference = {(x["session"], x["symbol"]): x for x in read(ROOT / "work/wave_v67" / model / (old_id + ".json.gz"))["ledgers"]}
            rows = []
            for actual in packet["rows"]:
                key = actual["session"], actual["symbol"]
                ready, ledger = inputs[key], ledgers[key]
                old_format = dict(ledger, config=ledger["settings"], trades=ledger["net_trades"], fees=np.asarray(ledger["fees"]).tolist())
                row, details, raw = old.measure(ready, old_format, model)
                np.testing.assert_array_equal(np.asarray(raw).reshape(-1, 11), ledger["trades"])
                trace_values = trace(ready, ledger, row)
                ratios(row)
                equal(row, actual)
                totals["P証跡数"] += guards(ready, ledger, trace_values, bool(config["mask"] & 2))
                totals["C証跡数"] += blocks(ledger, features[key], bool(config["mask"] & 8))
                totals["時間証跡数"] += time_windows(ready, ledger, trace_values, strategy, config.get("time_mode", ""))
                if reference is not None and key in reference:
                    for name in ("orders", "cycles"):
                        np.testing.assert_array_equal(ledger[name], np.asarray(reference[key][name]).reshape(ledger[name].shape))
                    equal(details, reference[key]["trades"])
                    totals["原版旧一致口座数"] += 1
                rows.append(row)
                totals["口座数"] += 1
                totals["注文数"] += len(ledger["orders"])
                totals["決済脚数"] += len(ledger["trades"])
                totals["組数"] += len(ledger["cycles"])
            periods = {name: {symbol: aggregate(old, rows, symbol, fixed[name]) for symbol in ("TOPIX", "NK225")}
                       for name in ("前16", "後14", "全30")}
            periods["対象"] = periods["全30"]
            equal(periods, packet["periods"])
            totals["条件数"] += 1
            reports.append(dict(モデル=model, 条件=config["id"], 口座数=60, 全行時価SHA一致=True,
                結果SHA256=hashlib.sha256(path.read_bytes()).hexdigest(), 台帳SHA256=packet["ledger_SHA256"]))
            print(model, config["id"], "60口座・全行会計・P/C証跡・全期間一致", flush=True)
    if not args.partial:
        assert totals["条件数"] == 2 * len(fixed["catalog"]) and totals["口座数"] == 120 * len(fixed["catalog"]) and totals["原版旧一致口座数"] == 224
    for section, home in (("code_SHA256", WORK), ("legacy_code_SHA256", ROOT), ("reference_SHA256", ROOT)):
        for name, digest in fixed[section].items():
            assert hashlib.sha256((home / name).read_bytes()).hexdigest() == digest
    result = dict(全合格=True, **totals, 条件別=reports, 親会計の呼出=False,
        実装固定SHA256=fixed["code_SHA256"], コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        限界="注文会計・情報の使用順の一致は、未見市場の利益や小型商品の同価格約定を証明しない。")
    name = "保存済み一部の独立会計監査.json" if args.partial else "全25条件二モデルの独立会計監査.json"
    (HERE / name).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(全合格=True, **totals), ensure_ascii=False))


if __name__ == "__main__":
    main()
