"""凍結480条件の全台帳・全清算曲線・期間会計・前半選定を独立集計する。"""

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
spec = importlib.util.spec_from_file_location("wave75_study", HERE.parent / "study.py")
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)
numba.config.CACHE_DIR = str(HERE / "cache")
SUM_FIELDS = ("profit", "loss", "net", "gross", "fees", "wins", "losses", "flats", "trades",
    "winning_lots", "losing_lots", "flat_lots", "pause_count", "resume_count", "paused_seconds",
    "resumed_trades", "resumed_net", "hold_seconds", "spread_drag")


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


def row_account(key: tuple, c: dict, r: dict, f: dict, p: dict, ledger: dict) -> dict:
    """機能: 注文から全金額を再構成し、料金後連敗と追跡返済理由を検査する。

    引数: key(tuple)、c/r/f/p/ledger(dict)。返り値: 独立場会計(dict)。
    pは事前監査済みの共同pulseを疎な自市場判断行へ写した方向配列である。
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
    assert stats[0] == 0 and stats[1] in (0, 1) and len(orders) == 2 * len(trades)
    qty = 10 if symbol == "TOPIX" else 20
    multiplier = 1000. if symbol == "TOPIX" else 10.
    width = max(2., np.ceil(p["open_price"] * c["width_fraction"] / r["tick"] - 1.e-10)) * r["tick"]
    entry_width = r["tick"]
    direct = p["direction"]
    qok = np.isfinite(f["bid"]) & np.isfinite(f["ask"]) & (f["bid"] > 0) & (f["ask"] >= f["bid"])
    by_cid = {int(trade[0]): trade for trade in trades}
    for order in orders:
        row, decision, cid, side, quantity, _, reason, opened = order
        row, decision, cid, side, reason = map(int, (row, decision, cid, side, reason))
        assert quantity == qty
        if opened:
            assert qok[decision] and p["quality"][decision] and not f["reset"][decision]
            assert int(direct[decision]) == side
            assert r["start"] + 300. <= r["time_s"][decision] < r["limit"] - 300. and r["time_s"][row] < r["limit"] - 300.
            assert reason == (10 if c["entry_type"] == 0 else 11)
        else:
            trade = by_cid[cid]
            entry_i, held_side, entry = int(trade[1]), int(trade[3]), float(trade[5])
            assert row > decision > entry_i and r["time_s"][row] < r["limit"] + 300., ("返済の監視区間境界", c["id"], key, order.tolist(), entry_i, r["time_s"][row], r["limit"])
            if reason == 4:
                assert r["time_s"][decision] >= r["limit"] - 60.
            elif reason == 3:
                assert r["time_s"][decision] - r["time_s"][entry_i] >= c["hold_seconds"]
            elif reason in (1, 2):
                indices = np.arange(entry_i + 1, decision + 1)[qok[entry_i + 1:decision + 1]]
                quote = f["bid"] if held_side == 1 else f["ask"]
                extreme = max(entry, float(np.max(quote[indices]))) if held_side == 1 else min(entry, float(np.min(quote[indices])))
                assert held_side * (quote[decision] - extreme) <= -width + r["tick"] * 1.e-8
                assert reason == (1 if abs(extreme - entry) < r["tick"] * 1.e-8 else 2)
            else:
                assert reason == 5 and c["exit_on_reverse"] and direct[decision] == -held_side
    starts = list(pauses[pauses[:, 1] == 0, 0].astype(int))
    ends = list(pauses[pauses[:, 1] == 1, 0].astype(int))
    assert len(starts) == stats[5] and len(ends) == stats[6]
    assert len(starts) in (len(ends), len(ends) + 1)
    pause_span = []
    for index, began in enumerate(starts):
        ended = ends[index] if index < len(ends) else len(r["time_s"])
        assert ended > began and (index == 0 or began > ends[index - 1])
        for order in orders[orders[:, 7] == 1]:
            assert not began <= int(order[1]) < ended, ("休止中の入口", key, c["id"], order)
        pause_span.append(max(0., min(r["time_s"][ended] if ended < len(r["time_s"]) else r["limit"] - 60., r["limit"] - 60.) - r["time_s"][began]))
        if ended < len(r["time_s"]) and c["pause_mode"] in (1, 2, 4, 5):
            wait = 600. if c["pause_mode"] in (1, 4) else 1800.
            assert r["time_s"][ended] - r["time_s"][began] >= wait
    events = {int(event[0]): event for event in pauses}
    exiting = {int(trade[2]): float(trade[10]) for trade in trades}
    streak = 0
    for row in sorted(set(events) | set(exiting)):
        if row in exiting:
            streak = streak + 1 if exiting[row] < 0 else 0 if exiting[row] > 0 else streak
        if row in events:
            event = events[row]
            assert int(event[4]) == streak and int(event[2]) == c["pause_mode"]
            if event[1] == 0:
                assert row in exiting and exiting[row] < 0 and streak >= (3 if c["pause_mode"] == 5 else 2)
            else:
                streak = 0
    assert int(stats[4]) == streak
    resumed = set()
    for ended in ends:
        candidates = np.flatnonzero(trades[:, 1] > ended)
        if len(candidates):
            resumed.add(int(candidates[0]))
    mid = (f["bid"] + f["ask"]) / 2.
    ideal_gross = sum(t[3] * (mid[int(t[2])] - mid[int(t[1])]) * qty * multiplier for t in trades)
    a.update(pause_count=len(starts), resume_count=len(ends), paused_seconds=float(sum(pause_span)),
        resumed_trades=len(resumed), resumed_net=float(sum(trades[j, 10] for j in resumed)),
        hold_seconds=float(sum(r["time_s"][int(t[2])] - r["time_s"][int(t[1])] for t in trades)),
        width=float(width), entry_width=float(entry_width), spread_drag=float(ideal_gross - a["gross"]),
        missing_reference=p["missing_previous"] and c["reference"] in (1, 2),
        max_trade_loss=max((-t["net"] for t in a["details"]), default=0.),
        drawdown=float(np.max(np.maximum.accumulate(np.maximum(curve, 0.)) - curve)), equity_min=float(curve.min()), equity_max=float(curve.max()),
        reasons={str(code): int(((orders[:, 6] == code) & (orders[:, 7] == 0)).sum()) for code in study.engine.REASONS})
    a["予定撤収時刻超過返済数"] = int(sum(r["time_s"][int(order[0])] >= r["limit"] for order in orders if order[7] == 0))
    a["予定撤収超過最大秒"] = max((max(0., r["time_s"][int(order[0])] - r["limit"]) for order in orders if order[7] == 0), default=0.)
    a["判断から約定の最大秒"] = max((r["time_s"][int(order[0])] - r["time_s"][int(order[1])] for order in orders), default=0.)
    a["max_trade_loss"] = max(0., a["max_trade_loss"])
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

