"""新生器を再実行せず、保存注文と原本気配から全損益・保護線・追加枠を再構成する。"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys

import numpy as np

from adapters import clearing_curve, orders9
from independent_account import CAP, POINT, fee, near, reconstruct


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
spec = importlib.util.spec_from_file_location("wave77_audit_study", HERE.parent / "study.py")
study = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = study
spec.loader.exec_module(study)
SUM_FIELDS = ("profit", "loss", "net", "gross", "fees", "trades", "wins", "losses", "flats", "legs", "winning_legs", "losing_legs",
    "winning_lots", "losing_lots", "flat_lots", "campaign_profit", "campaign_loss", "hold_seconds", "adds", "risk_excesses", "spread_drag")


def metrics(a: dict) -> dict:
    """機能: 金額明細比率・平均明細勝敗・組勝率を独立の分母で計算する。

    引数: a(dict)。返り値: 指標を追加したdict。
    """
    p, l = a["profit"], a["loss"]
    a["profit_share"] = p / (p+l) if p+l else None
    a["money_loss_share"] = l / (p+l) if p+l else None
    a["profit_loss_ratio"] = p / l if l else None
    a["average_win"] = p / a["winning_legs"] if a["winning_legs"] else None
    a["average_loss"] = l / a["losing_legs"] if a["losing_legs"] else None
    a["payoff"] = a["average_win"] / a["average_loss"] if a["average_win"] is not None and a["average_loss"] else None
    a["win_rate"] = a["wins"] / a["trades"] if a["trades"] else None
    a["average_net"] = a["net"] / a["trades"] if a["trades"] else None
    a["average_hold_seconds"] = a["hold_seconds"] / a["trades"] if a["trades"] else None
    cp, cl = a["campaign_profit"], a["campaign_loss"]
    a["campaign_profit_share"] = cp / (cp+cl) if cp+cl else None
    a["goal80"] = bool(p+l > 0 and p > 0 and p >= 4*l)
    return a


def same_fields(actual: dict, saved: dict, label: object) -> int:
    """機能: 元帳票の全項目を比較し、円演算誤差だけを許容する。

    引数: actual/saved(dict)、label(object)。返り値: 比較項目数(int)。
    """
    count = 0
    for field, value in saved.items():
        assert field in actual, (label, field, "独立値なし")
        expected = actual[field]
        if isinstance(value, dict):
            assert set(value) == set(expected), (label, field)
            count += same_fields(expected, value, (label, field))
        elif isinstance(value, (float, int)) and not isinstance(value, bool):
            assert abs(value-expected) < 1.e-4, (label, field, value, expected)
        else:
            assert value == expected, (label, field, value, expected)
        count += 1
    return count


def aggregate(rows: list[dict], symbol: str, sessions: list[str]) -> dict:
    """機能: 商品の全明細・組会計を場順に合算し、DDと最大黒字場除外を求める。

    引数: rows(list[dict])、symbol(str)、sessions(list[str])。返り値: 期間会計(dict)。
    """
    own = sorted((r for r in rows if r["symbol"] == symbol and r["session"] in sessions), key=lambda r: sessions.index(r["session"]))
    result = {k: sum(r[k] for r in own) for k in SUM_FIELDS}
    for k in ("max_trade_loss", "max_leg_loss", "max_long", "max_short"):
        result[k] = max((r[k] for r in own), default=0.)
    result["active_sessions"] = sum(r["trades"] > 0 for r in own)
    result["winning_sessions"] = sum(r["net"] > 0 for r in own)
    wealth = maximum = worst = 0.
    for r in own:
        worst = max(worst, r["drawdown"], maximum-(wealth+r["curve_min"]))
        maximum = max(maximum, wealth+r["curve_max"])
        wealth += r["net"]
    result["drawdown"] = worst
    result["max_session_drawdown"] = max((r["drawdown"] for r in own), default=0.)
    best = max(own, key=lambda r: r["net"], default=None)
    result["without_best_session"] = result["net"]-(best["net"] if best else 0.)
    p = result["profit"]-(best["profit"] if best else 0.)
    l = result["loss"]-(best["loss"] if best else 0.)
    result["without_best_profit_share"] = p/(p+l) if p+l else None
    result["without_best_profit_loss_ratio"] = p/l if l else None
    return metrics(result)


def protection(args: tuple, entries: np.ndarray, close: np.ndarray) -> dict:
    """機能: 保護線を独立の累積極値式で再構成し、最初の返済成立行を検査する。

    引数: args(tuple)、entries/close(ndarray)。返り値: 行・保護線・予算・数量・費用(dict)。
    追加約定行を極値更新から除き、当行で作った保護線は次観測から有効とする。
    """
    first = entries[0]
    side, start, finish = int(first[3]), int(first[0]), int(close[1])
    rows = np.arange(start, finish+1)
    stamps = args[0][rows]
    policy, tick, value = args[23], args[14], args[18]
    entry_signed = side*first[5]
    risk = args[20]
    if policy == 4:
        g = int(args[6][int(first[1])])
        reference = args[12][g] if side == 1 else args[13][g]
        risk = side*(first[5]-reference)
    budget = first[4]*max(risk, 0.)*value + 2*first[8]
    quotes = args[1][rows] if side == 1 else args[2][rows]
    qok = np.isfinite(args[1][rows]) & np.isfinite(args[2][rows]) & (args[1][rows] > 0) & (args[2][rows] >= args[1][rows])
    fill_mask = np.isin(rows, entries[:, 0].astype(int))
    update = qok & ~fill_mask
    directed = side*quotes
    peak = np.maximum.accumulate(np.r_[entry_signed, np.where(update, directed, -np.inf)])[1:]
    quantity = np.zeros(len(rows), dtype=np.int64)
    costs = np.zeros(len(rows)); paid = np.zeros(len(rows))
    for order in entries:
        future = rows >= int(order[0])
        quantity[future] += int(order[4]); costs[future] += order[4]*order[5]; paid[future] += order[8]
    exit_fee = quantity*418//10 if args[17] == 10 else quantity*11
    advance = peak-entry_signed
    if policy == 0:
        current = peak-args[21]
        prior = np.r_[entry_signed-args[21], current[:-1]]
    else:
        initial = entry_signed-risk
        trigger = risk*(.5 if policy == 2 else 1.)
        gap = np.where((policy == 3) & (advance >= 2*risk), args[21]*.5, args[21])
        candidates = np.where(update & (advance >= trigger), peak-gap, -np.inf)
        if policy in (2, 3):
            directed_cost = (side*costs+(paid+exit_fee)/value)/quantity
            floor = np.ceil(directed_cost/tick-1.e-8)*tick
            if policy == 3:
                floor = np.maximum(floor, entry_signed+risk)
            candidates = np.maximum(candidates, np.where(update & (advance >= risk*(.5 if policy == 2 else 2.)), floor, -np.inf))
        current = np.maximum.accumulate(np.r_[initial, candidates])[1:]
        prior = np.r_[initial, current[:-1]]
    reason = np.zeros(len(rows), dtype=np.int8)
    reason[stamps >= args[16]-60.] = 4
    if args[22] > 0:
        reason[(reason == 0) & (stamps-args[0][start] >= args[22])] = 3
    if risk <= 0 or policy == 4 and risk > args[20]+tick*1.e-8:
        reason[reason == 0] = 8
    touched = qok & (rows > start) & (directed <= prior+tick*1.e-8)
    if policy == 0:
        classification = np.where(np.abs(prior+args[21]-entry_signed) < tick*1.e-8, 1, 2)
    else:
        classification = np.where(prior < entry_signed-tick*1.e-8, 1, 2)
    chosen = (reason == 0) & touched
    reason[chosen] = classification[chosen]
    add_fill = fill_mask & (rows > start)
    projected = (prior*quantity-side*costs)*value-paid-exit_fee
    if policy != 0:
        chosen = (reason == 0) & add_fill & (-projected > budget+1.e-6)
        reason[chosen] = 8
    mapped = args[6][rows]
    has = mapped >= 0
    safe = np.maximum(mapped, 0)
    usable = has & args[8][safe] & args[3][rows] & ~args[4][rows]
    if policy != 0:
        opposite = args[10 if side == 1 else 11][safe]
        reason[(reason == 0) & usable & opposite] = 6
    if policy == 5:
        began = last_grid = None
        for j in np.flatnonzero(has):
            if not usable[j]:
                began = last_grid = None
                continue
            if reason[j] != 0:
                continue
            stamp = args[7][safe[j]]
            weak = args[9][safe[j]] != side and advance[j] < .5*risk and stamps[j]-args[0][start] >= 300.
            if not weak or last_grid is None or stamp-last_grid > 5.+1.e-8:
                began = None
            if weak:
                if began is None:
                    began = stamp
                if stamp-began >= 30.:
                    reason[j] = 9
            last_grid = stamp
    hits = np.flatnonzero(reason)
    assert len(hits) and rows[hits[0]] == finish and reason[hits[0]] == int(close[6]), ("最初の返済成立行", first, close,
        None if not len(hits) else (rows[hits[0]], reason[hits[0]]))
    return dict(rows=rows, stop=side*current, prior_stop=side*prior, budget=budget, quantity=quantity, cost=costs, paid=paid,
        risk=risk, peak=side*peak)


def check_risk(args: tuple, ledger: dict, paths: dict, symbol: str) -> dict:
    """機能: 全追加判断・追加fillの予算と投影損益を過去建値から独立に照合する。

    引数: args(tuple)、ledger/paths(dict)、symbol(str)。返り値: 計数(dict)。
    """
    orders = ledger["orders"]
    records = ledger["risk_events"]
    phases = {0: {}, 1: {}}
    excesses = expired = 0
    for record in records:
        row, cid, phase, budget, stop, projected, amount, side = record
        row, cid, phase, amount, side = map(int, (row, cid, phase, amount, side))
        assert phase in phases and (cid, row) not in phases[phase]
        paths_cid = paths[cid]; offset = row-int(paths_cid["rows"][0])
        near(budget, paths_cid["budget"], "初回総リスク枠")
        near(stop, paths_cid["stop" if phase == 0 else "prior_stop"][offset], "追加の因果保護線")
        entries = [o for o in orders if int(o[2]) == cid and o[7] == 1 and o[0] <= row]
        quantity = sum(int(o[4]) for o in entries)
        cost = sum(o[4]*o[5] for o in entries)
        paid = sum(fee(symbol, int(o[4])) for o in entries)
        if phase == 0:
            extra = amount-quantity
            assert extra == (CAP[symbol]*3//10 if len(entries) == 1 else CAP[symbol]-quantity)
            price = args[2][row] if side == 1 else args[1][row]
            cost += extra*price; paid += fee(symbol, extra)
            assert -projected <= budget+1.e-6 and amount <= CAP[symbol]
            g = int(args[6][row])
            assert g >= 0 and args[8][g] and args[3][row] and not args[4][row] and args[9][g] == side
            quote = args[1][row] if side == 1 else args[2][row]
            first = entries[0]
            assert side*(quote-first[5]) >= .5*paths_cid["risk"]*len(entries)
            assert row > entries[-1][0] and args[0][row] < args[16]-300.
            fills = [o for o in orders if int(o[2]) == cid and o[7] == 1 and o[6] == 11 and o[1] == row]
            if not fills:
                valid = np.flatnonzero(np.isfinite(args[1]) & np.isfinite(args[2]) & (args[1] > 0) & (args[2] >= args[1]) & (np.arange(len(args[0])) > row))
                assert len(valid) and args[0][valid[0]] >= args[16]-300., "未約定追加の場末以外の消失"
                expired += 1
        else:
            assert quantity == amount and any(o[0] == row and o[6] == 11 for o in entries)
            if -projected > budget+1.e-6:
                close = [o for o in orders if int(o[2]) == cid and o[7] == 0]
                assert len(close) == 1 and close[0][1] == row and close[0][6] == 8
                excesses += 1
        near(projected, side*(stop*amount-cost)*POINT[symbol]-paid-fee(symbol, amount), "全玉stop予測損益")
        phases[phase][(cid, row)] = record
    added = [o for o in orders if o[7] == 1 and o[6] == 11]
    for o in added:
        assert (int(o[2]), int(o[1])) in phases[0]
        if (int(o[2]), int(o[0])) not in phases[1]:
            close = [c for c in orders if int(c[2]) == int(o[2]) and c[7] == 0]
            assert len(close) == 1 and close[0][1] == o[0] and close[0][6] in (1, 2, 3, 4, 8)
    assert excesses == ledger["stats"][6]
    return dict(追加判断証跡数=len(phases[0]), 追加約定証跡数=len(phases[1]), 場末取消追加数=expired,
        約定後予算超過数=excesses)


def row_account(key: tuple, c: dict, args: tuple, ledger: dict, ready: dict) -> dict:
    """機能: 保存台帳の全明細・全行曲線・保護線・追加予算を独立に再計算する。

    引数: key(tuple)、c/ledger/ready(dict)、args(tuple)。返り値: 独立場別商品会計(dict)。
    """
    symbol = key[1]; orders = ledger["orders"]; t = ledger["trades"]
    assert orders.shape[1] == 10 and t.shape[1] == 12 and ledger["stats"].shape == (7,)
    assert np.all(ledger["stats"][:3] == 0), "完成セッションの未返済又は執行待ち"
    data = dict(time_s=args[0], seq=ready["seq"], bid=args[1], ask=args[2])
    account, raw_curve = reconstruct(data, dict(symbol=symbol, session=key[0], orders=orders9(orders)))
    curve = clearing_curve(symbol, orders, raw_curve)
    assert hashlib.sha256(curve.tobytes()).hexdigest() == ledger["curve_hash"], (c["id"], key, "全行清算曲線")
    entry_orders = orders[orders[:, 7] == 1]; close_orders = orders[orders[:, 7] == 0]
    by_entry = {(int(o[2]), int(o[0])): int(o[9]) for o in entry_orders}
    expected = np.array([[d["campaign"], d["entry_row"], d["exit_row"], d["side"], d["quantity"], d["entry"], d["exit"],
        d["entry_fee"], d["exit_fee"], d["gross"], d["net"], by_entry[(d["campaign"], d["entry_row"])]] for d in account["details"]]).reshape((-1, 12))
    np.testing.assert_allclose(t, expected, atol=1.e-4, rtol=0)
    for o in orders:
        assert o[8] == fee(symbol, int(o[4]))
    assert set(close_orders[:, 2]) == set(entry_orders[:, 2]) and len(close_orders) == account["campaigns"]
    paths = {}; hold = 0.; reasons = {}
    for close in close_orders:
        cid = int(close[2]); entries = entry_orders[entry_orders[:, 2] == cid]
        assert [int(o[9]) for o in entries] == list(range(len(entries))) and close[9] == -1
        assert entries[0, 4] == (CAP[symbol] if c["allocation"] == 0 else CAP[symbol]*2//10)
        assert np.all(entries[:, 3] == entries[0, 3]) and entries[0, 6] == 10
        assert np.all(entries[1:, 6] == 11) and (c["allocation"] == 1 or len(entries) == 1)
        for o in entries[1:]:
            assert int(o[4]) == (CAP[symbol]*3//10 if o[9] == 1 else CAP[symbol]*5//10)
        assert close[4] == entries[:, 4].sum()
        first = entries[0]; decision = int(first[1])
        assert args[5][decision] == first[3] and args[3][decision] and not args[4][decision]
        assert args[15]+300. <= args[0][decision] < args[16]-300.
        previous = close_orders[close_orders[:, 0] < first[0]]
        if len(previous):
            assert args[0][decision]-args[0][int(previous[-1, 0])] >= c["cooldown"]
        if c["policy"] == 4:
            g = int(args[6][decision]); assert g >= 0 and args[8][g]
            reference = args[12][g] if first[3] == 1 else args[13][g]
            price = args[2][decision] if first[3] == 1 else args[1][decision]
            assert 2*args[14] <= first[3]*(price-reference) <= args[20]
        paths[cid] = protection(args, entries, close)
        hold += args[0][int(close[0])]-args[0][int(first[0])]
        reason = str(int(close[6])); reasons[reason] = reasons.get(reason, 0)+1
    risk_counts = check_risk(args, ledger, paths, symbol)
    assert ledger["stats"][3] == account["max_long"] and ledger["stats"][4] == account["max_short"]
    adds = sum(o[6] == 11 for o in entry_orders)
    assert ledger["stats"][5] == adds
    net = np.array([d["net"] for d in account["details"]])
    peaks = np.maximum.accumulate(np.r_[0., curve])[1:]
    row = dict(session=key[0], symbol=symbol, profit=account["profit"], loss=account["loss"], net=account["net"],
        gross=account["gross"], fees=account["fees"], trades=account["campaigns"], wins=account["campaign_wins"],
        losses=account["campaign_losses"], flats=account["campaign_flats"], legs=account["trades"],
        winning_legs=account["wins"], losing_legs=account["losses"], winning_lots=account["winning_lots"],
        losing_lots=account["losing_lots"], flat_lots=account["flat_lots"], campaign_profit=account["campaign_profit"],
        campaign_loss=account["campaign_loss"], hold_seconds=float(hold), drawdown=float(np.max(peaks-curve)),
        curve_min=min(0., float(curve.min())), curve_max=max(0., float(curve.max())), max_trade_loss=account["max_campaign_loss"],
        max_leg_loss=max(0., -float(net.min())) if len(net) else 0., max_long=account["max_long"], max_short=account["max_short"],
        adds=int(adds), risk_excesses=risk_counts["約定後予算超過数"],
        spread_drag=sum(.5*(args[2][int(o[0])]-args[1][int(o[0])])*o[4]*POINT[symbol] for o in orders),
        reasons=reasons, active_sessions=int(account["campaigns"] > 0), candidate_count=int(np.count_nonzero(args[5])), **risk_counts)
    late = close_orders[args[0][close_orders[:, 0].astype(int)] >= args[16]]
    row["予定時刻超過返済数"] = len(late)
    row["予定時刻超過最大秒"] = float(max((args[0][int(o[0])]-args[16] for o in late), default=0.))
    row["判断約定最大秒"] = float(max((args[0][int(o[0])]-args[0][int(o[1])] for o in orders), default=0.))
    assert not len(close_orders) or np.all(args[0][close_orders[:, 0].astype(int)] < args[16]+300.)
    return metrics(row)
