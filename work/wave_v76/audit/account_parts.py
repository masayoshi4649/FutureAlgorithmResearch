"""短期途中管理の全台帳・清算曲線・金額指標を独立集計する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from adapters import clearing_curve, orders9, trades12
import importlib.util
import os
import sys
import numba
from independent_account import near, reconstruct, save


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
os.environ.setdefault("NUMBA_CACHE_DIR", str(HERE / "cache"))
sys.path.insert(0, str(HERE.parent))
spec = importlib.util.spec_from_file_location("wave76_audit_study", HERE.parent / "study.py")
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)
numba.config.CACHE_DIR = str(HERE / "cache")
SUM_FIELDS = ("profit", "loss", "net", "gross", "fees", "wins", "losses", "flats", "trades",
    "winning_lots", "losing_lots", "flat_lots", "pause_count", "resume_count", "paused_seconds",
    "resumed_trades", "resumed_net", "hold_seconds", "spread_drag", "flip_count", "flip_cancel_count")


def metrics(a: dict) -> dict:
    """機能: 期間指標を合計金額から独立に計算する。

    引数: a(dict)。返り値: 比率等を追加した会計(dict)。
    """
    profit, loss, count = a["profit"], a["loss"], a["trades"]
    a.update(money_loss_share=loss / (profit + loss) if profit + loss else None,
        profit_loss_ratio=profit / loss if loss else None,
        average_win=profit / a["wins"] if a["wins"] else None,
        average_loss=loss / a["losses"] if a["losses"] else None,
        average_net=a["net"] / count if count else None,
        win_rate=a["wins"] / count if count else None,
        payoff=(profit / a["wins"]) / (loss / a["losses"]) if a["wins"] and a["losses"] else None,
        average_hold_seconds=a["hold_seconds"] / count if count else None)
    return a



def reservation_counts(r: dict, f: dict, args: tuple, orders: np.ndarray) -> tuple:
    """機能: 実返済から後の原本と格子を探索し、反転予約の実新規と取消を別計算する。

    引数: r/f(dict)、args(tuple)、orders(ndarray)。返り値: 約定反転数、注文前取消数、注文後場末失効数(tuple)。
    """
    filled = cancelled = submitted_expired = 0
    times, mapped = r["time_s"], args[6]
    grid, valid, strong = args[15:18]
    qok = np.isfinite(f["bid"]) & np.isfinite(f["ask"]) & (f["bid"] > 0) & (f["ask"] >= f["bid"])
    valid_rows = np.flatnonzero(qok)
    new_by_decision = {int(o[1]): o for o in orders if o[7] == 1 and o[6] == 12}
    for close in orders:
        if close[7] or close[6] != 6 or args[22] not in (2, 3):
            continue
        exit_i, desired = int(close[0]), int(close[3])
        exit_stamp = times[exit_i]
        if exit_stamp >= r["limit"] - 300.:
            continue
        until = exit_stamp + args[25]
        right = min(len(times), int(np.searchsorted(times, until, side="right")) + 1)
        rows = np.arange(exit_i + 1, right)
        first_expiry = rows[(times[rows] > until) | (times[rows] >= r["limit"] - 300.)]
        action_i = int(first_expiry[0]) if len(first_expiry) else len(times)
        action = "取消" if len(first_expiry) else "未決"
        candidate = rows[mapped[rows] >= 0]
        if len(candidate):
            g = mapped[candidate]
            candidate = candidate[grid[g] > exit_stamp]
            for i in candidate:
                if i >= action_i:
                    break
                g = int(mapped[i])
                usable = valid[g] and args[3][i] and not f["reset"][i]
                if not usable or strong[g] != desired:
                    action_i, action = int(i), "取消"
                    break
                ready = args[21][g] if desired == 1 else args[20][g]
                if ready and qok[i]:
                    action_i, action = int(i), "新規判断"
                    break
        if action == "取消":
            cancelled += 1
        elif action == "新規判断":
            fill_pos = np.searchsorted(valid_rows, action_i, side="right")
            assert fill_pos < len(valid_rows), ("反転発注後に有効気配なし", r["limit"], action_i)
            fill_i = int(valid_rows[fill_pos])
            if times[fill_i] >= r["limit"] - 300.:
                assert action_i not in new_by_decision
                submitted_expired += 1
            else:
                assert action_i in new_by_decision
                order = new_by_decision[action_i]
                assert int(order[0]) == fill_i and int(order[3]) == desired
                filled += 1
        else:
            raise AssertionError(("保存終端まで未解決の反転予約", exit_i, exit_stamp, until))
    return filled, cancelled, submitted_expired


def row_account(key: tuple, c: dict, r: dict, f: dict, args: tuple, ledger: dict) -> dict:
    """機能: 全注文と料金、保険・管理理由、ドテン順序、全行清算時価を独立検算する。

    引数: key(tuple)、c/r/f/ledger(dict)、args(tuple)。返り値: 独立場会計(dict)。
    """
    symbol = key[1]
    data = dict(time_s=r["time_s"], seq=r["seq"], bid=f["bid"], ask=f["ask"])
    a, equity = reconstruct(data, dict(symbol=symbol, session=key[0], orders=orders9(ledger["orders"])), True)
    curve = clearing_curve(symbol, ledger["orders"], equity)
    assert hashlib.sha256(curve.tobytes()).hexdigest() == ledger["curve_hash"], ("全行清算曲線指紋", key, c["id"])
    expected = np.asarray([[d["campaign"], d["entry_row"], d["exit_row"], d["side"], d["quantity"], d["entry"], d["exit"],
        d["entry_fee"], d["exit_fee"], d["gross"], d["net"], 0] for d in a["details"]], dtype=float).reshape((-1, 12))
    np.testing.assert_allclose(trades12(ledger["trades"]), expected, rtol=0, atol=1.e-4)
    orders, trades, pauses, stats = ledger["orders"], ledger["trades"], ledger["pauses"], ledger["stats"]
    assert stats[0] == 0 and stats[1] in (0, 1) and stats[2] == 0 and len(orders) == 2 * len(trades)
    assert len(pauses) == 0 and np.all(stats[3:7] == 0)
    qty = 10 if symbol == "TOPIX" else 20
    multiplier = 1000. if symbol == "TOPIX" else 10.
    assert args[10] == qty and args[11] == multiplier
    width, entry_width = args[13:15]
    direct, mapped = args[5:7]
    grid, valid, strong = args[15:18]
    qok = np.isfinite(f["bid"]) & np.isfinite(f["ask"]) & (f["bid"] > 0) & (f["ask"] >= f["bid"])
    by_cid = {int(trade[0]): trade for trade in trades}
    prior_exit = None
    for order in orders:
        row, decision, cid, side, quantity, _, reason, opened = order
        row, decision, cid, side, reason = map(int, (row, decision, cid, side, reason))
        assert quantity == qty
        stamp = r["time_s"][decision]
        if opened:
            assert qok[decision] and args[3][decision] and not f["reset"][decision]
            assert r["start"] + 300. <= stamp < r["limit"] - 300. and r["time_s"][row] < r["limit"] - 300.
            if reason == 10:
                assert int(direct[decision]) == side
                if prior_exit is not None:
                    assert stamp - r["time_s"][int(prior_exit[0])] >= c["cooldown"]
            else:
                assert reason == 12 and c["manage_mode"] in (2, 3) and prior_exit is not None
                exit_i = int(prior_exit[0])
                g = int(mapped[decision])
                assert prior_exit[6] == 6 and int(prior_exit[3]) == side
                assert decision > exit_i and g >= 0 and grid[g] > r["time_s"][exit_i]
                assert stamp <= r["time_s"][exit_i] + c["flip_expiry"]
                assert valid[g] and strong[g] == side
                assert (args[21][g] if side == 1 else args[20][g])
        else:
            trade = by_cid[cid]
            entry_i, held_side, entry = int(trade[1]), int(trade[3]), float(trade[5])
            assert row > decision > entry_i and r["time_s"][row] < r["limit"] + 300.
            deadline = stamp >= r["limit"] - 60.
            timeout = c["hold_seconds"] > 0 and stamp - r["time_s"][entry_i] >= c["hold_seconds"]
            if reason == 4:
                assert deadline
            elif reason == 3:
                assert not deadline and timeout
            else:
                assert not deadline and not timeout
                indices = np.arange(entry_i + 1, decision + 1)[qok[entry_i + 1:decision + 1]]
                quote = f["bid"] if held_side == 1 else f["ask"]
                extreme = max(entry, float(np.max(quote[indices]))) if held_side == 1 else min(entry, float(np.min(quote[indices])))
                insurance = qok[decision] and held_side * (quote[decision] - extreme) <= -width + r["tick"] * 1.e-8
                if reason in (1, 2):
                    assert insurance and reason == (1 if abs(extreme - entry) < r["tick"] * 1.e-8 else 2)
                else:
                    assert not insurance and reason in (6, 7)
                    g = int(mapped[decision])
                    assert g >= 0 and valid[g] and args[3][decision] and not f["reset"][decision]
                    assert grid[g] <= stamp <= grid[g] + 10.
                    opposite = args[20][g] if held_side == 1 else args[21][g]
                    if reason == 6:
                        assert c["manage_mode"] != 0 and opposite
                    else:
                        assert c["manage_mode"] == 3 and not opposite
                        assert (args[18][g] if held_side == 1 else args[19][g])
            prior_exit = order
    flips, cancelled, submitted_expired = reservation_counts(r, f, args, orders)
    assert flips == int(stats[7]) == int(((orders[:, 6] == 12) & (orders[:, 7] == 1)).sum())
    assert cancelled == int(stats[8])
    mid = (f["bid"] + f["ask"]) / 2.
    ideal_gross = sum(t[3] * (mid[int(t[2])] - mid[int(t[1])]) * qty * multiplier for t in trades)
    a.update(pause_count=0, resume_count=0, paused_seconds=0., resumed_trades=0, resumed_net=0.,
        hold_seconds=float(sum(r["time_s"][int(t[2])] - r["time_s"][int(t[1])] for t in trades)),
        width=float(width), entry_width=float(entry_width), spread_drag=float(ideal_gross - a["gross"]),
        missing_reference=False, max_trade_loss=max(0., max((-t["net"] for t in a["details"]), default=0.)),
        drawdown=float(np.max(np.maximum.accumulate(np.maximum(curve, 0.)) - curve)), equity_min=float(curve.min()), equity_max=float(curve.max()),
        reasons={str(code): int(((orders[:, 6] == code) & (orders[:, 7] == 0)).sum()) for code in study.engine.REASONS},
        flip_count=flips, flip_cancel_count=cancelled, candidate_count=int(np.count_nonzero(direct)))
    a["発注後場末失効の反転数"] = submitted_expired
    a["予定撤収時刻超過返済数"] = int(sum(r["time_s"][int(order[0])] >= r["limit"] for order in orders if order[7] == 0))
    a["予定撤収超過最大秒"] = max((max(0., r["time_s"][int(order[0])] - r["limit"]) for order in orders if order[7] == 0), default=0.)
    a["判断から約定の最大秒"] = max((r["time_s"][int(order[0])] - r["time_s"][int(order[1])] for order in orders), default=0.)
    return metrics(a)


def aggregate(rows: list[dict], symbol: str, sessions: list[str]) -> dict:
    """機能: 商品別全場損益を再合計し、黒字場除外や期間下落も独立に求める。

    引数: rows(list[dict])、symbol(str)、sessions(list[str])。返り値: 期間会計(dict)。
    """
    subset = sorted((r for r in rows if r["symbol"] == symbol and r["session"] in sessions), key=lambda r: r["session"])
    a = {field: sum(row[field] for row in subset) for field in SUM_FIELDS}
    a.update(active_sessions=sum(row["trades"] > 0 for row in subset), positive_sessions=sum(row["net"] > 0 for row in subset),
        max_trade_loss=max((row["max_trade_loss"] for row in subset), default=0.),
        without_best_session=a["net"] - max((row["net"] for row in subset), default=0.),
        max_long=max((row["max_long"] for row in subset), default=0), max_short=max((row["max_short"] for row in subset), default=0),
        missing_reference_sessions=sum(row["missing_reference"] for row in subset))
    total = peak = dd = 0.
    for row in subset:
        dd = max(dd, row["drawdown"], peak - total - row["equity_min"])
        peak = max(peak, total + row["equity_max"])
        total += row["net"]
    a["drawdown"] = dd
    return metrics(a)


def same_fields(actual: dict, expected: dict, label: object) -> int:
    """機能: 保存された全項目を独立会計に照合する。

    引数: actual/expected(dict)、label(object)。返り値: 比較項目数(int)。
    """
    for field, value in expected.items():
        assert field in actual, ("独立値に項目がない", field, label)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            near(actual[field], value, str((label, field)))
        else:
            assert actual[field] == value, (label, field, actual[field], value)
    return len(expected)

