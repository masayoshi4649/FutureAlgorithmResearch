"""指定された波のラベルを検知器から分離して評価する。"""

from __future__ import annotations

from typing import Any

import pandas as pd


TICKS = {"NK225": 10.0, "TOPIX": 0.5}
TARGET_SPECS = (
    ("2026-09-21_Day", "2026-09-21 10:45", "2026-09-21 15:40", 1, "開発"),
    ("2026-09-22_Day", "2026-09-22 09:20", "2026-09-22 11:45", -1, "開発"),
    ("2026-09-22_Night", "2026-09-23 00:40", "2026-09-23 03:20", 1, "開発"),
    ("2026-09-23_Day", "2026-09-23 09:05", "2026-09-23 11:15", -1, "答え合わせ"),
)


def target_definitions() -> list[dict[str, Any]]:
    """機能: 両銘柄の指定波を固定ラベルとして作る。

    引数: なし。
    返り値: 日本時間の開始・終了・方向・用途を含むラベル一覧 (list[dict])。
    """
    return [
        dict(
            symbol=symbol,
            session=session,
            begin=pd.Timestamp(begin, tz="Asia/Tokyo"),
            end=pd.Timestamp(end, tz="Asia/Tokyo"),
            target_side=side,
            role=role,
        )
        for session, begin, end, side, role in TARGET_SPECS
        for symbol in TICKS
    ]


def _timestamp(value: Any) -> pd.Timestamp | None:
    """機能: 取引時刻を日本時間へ揃える。

    引数: value (Any)。時刻、文字列、または欠損値。
    返り値: 日本時間の時刻 (Timestamp)、欠損なら None。
    """
    if value is None or pd.isna(value):
        return None
    result = pd.Timestamp(value)
    return result.tz_localize("Asia/Tokyo") if result.tzinfo is None else result.tz_convert("Asia/Tokyo")


def _union_minutes(intervals: list[tuple[pd.Timestamp, pd.Timestamp]]) -> float:
    """機能: 重複した保有時間を二重に数えず合計する。

    引数: intervals (list[tuple[Timestamp, Timestamp]])。半開区間の一覧。
    返り値: 区間の和集合の長さ、分単位 (float)。
    """
    if not intervals:
        return 0.0
    ordered = sorted(intervals)
    begin, end = ordered[0]
    total = 0.0
    for left, right in ordered[1:]:
        if left > end:
            total += (end - begin).total_seconds() / 60
            begin, end = left, right
        else:
            end = max(end, right)
    return total + (end - begin).total_seconds() / 60


def target_metrics(
    one: pd.DataFrame,
    trades: list[dict[str, Any]],
    symbol: str,
    session: str,
    round_trip_ticks: float = 2.0,
) -> list[dict[str, Any]]:
    """機能: 指定波の遅延・時間捕捉・値幅捕捉と区間後の損益を採点する。

    引数: one (DataFrame) は確定済み１分足、trades (list[dict]) は取引、
        symbol/session (str) は銘柄とセッション、round_trip_ticks (float) は往復控除。
    返り値: 対象ラベルがあれば評価１件、なければ空一覧 (list[dict])。
        値幅捕捉は指定区間で切った仮想値であり、実取引損益とは別に記録する。
    """
    labels = [x for x in target_definitions() if x["symbol"] == symbol and x["session"] == session]
    if not labels:
        return []
    label = labels[0]
    begin, end, side = label["begin"], label["end"], label["target_side"]
    result: dict[str, Any] = dict(label)
    minutes = (end - begin).total_seconds() / 60
    window = one[(one.index >= begin) & (one.index < end)]
    available_until = one.index[-1] + pd.Timedelta(minutes=1) if len(one) else None
    complete = bool(available_until is not None and available_until >= end and len(window))
    reference = side * (float(window.close.iloc[-1]) - float(window.open.iloc[0])) if len(window) else None
    correct_intervals: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    opposite_intervals: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    hits: list[pd.Timestamp] = []
    fresh_hits: list[pd.Timestamp] = []
    first_correct_entries: list[pd.Timestamp] = []
    carried_from_before_window = 0
    captured = 0.0
    correct_trade_count = 0
    correct_trade_net = 0.0
    correct_trade_closed = 0
    held_after_count = 0
    post_target_gross = 0.0
    post_target_closed = 0
    cost = round_trip_ticks * TICKS[symbol]

    # ----------------------------------------
    for trade in trades:
        if trade.get("symbol", symbol) != symbol or trade.get("session", session) != session:
            continue
        entry = _timestamp(trade["entry_time"])
        exit_time = _timestamp(trade.get("exit_time"))
        finish = exit_time if exit_time is not None else available_until
        if entry is None or finish is None:
            continue
        left, right = max(entry, begin), min(finish, end)
        if right <= left:
            if begin <= entry < end and finish == entry and int(trade["side"]) == side:
                correct_trade_count += 1
                if trade.get("exit_price") is not None:
                    captured += side * (float(trade["exit_price"]) - float(trade["entry_price"])) - cost
                if trade.get("closed", exit_time is not None) and trade.get("net_points") is not None:
                    correct_trade_closed += 1
                    correct_trade_net += float(trade["net_points"])
            continue
        interval = (left, right)
        if int(trade["side"]) != side:
            opposite_intervals.append(interval)
            continue
        correct_intervals.append(interval)
        duration = (right - left).total_seconds() / 60
        if duration >= 20:
            hits.append(left)
            first_correct_entries.append(entry)
            if begin - pd.Timedelta(minutes=30) <= entry <= begin + pd.Timedelta(minutes=60):
                fresh_hits.append(entry)
            elif entry < begin - pd.Timedelta(minutes=30):
                carried_from_before_window += 1
        correct_trade_count += 1
        if trade.get("closed", exit_time is not None) and trade.get("net_points") is not None:
            correct_trade_closed += 1
            correct_trade_net += float(trade["net_points"])
        segment = one[(one.index >= left) & (one.index < right)]
        if len(segment):
            initial = float(trade["entry_price"]) if left == entry else float(segment.open.iloc[0])
            final = (
                float(trade["exit_price"])
                if exit_time is not None and right == exit_time and trade.get("exit_price") is not None
                else float(segment.close.iloc[-1])
            )
            captured += side * (final - initial) - cost

        # ----------------------------------------
        if finish > end and complete:
            held_after_count += 1
            if exit_time is not None and trade.get("exit_price") is not None:
                post_target_closed += 1
                post_target_gross += side * (float(trade["exit_price"]) - float(window.close.iloc[-1]))

    # ----------------------------------------
    correct = _union_minutes(correct_intervals)
    opposite = _union_minutes(opposite_intervals)
    delay = min((t - begin).total_seconds() / 60 for t in hits) if hits else None
    fresh_delay = min((t - begin).total_seconds() / 60 for t in fresh_hits) if fresh_hits else None
    capture_ratio = captured / reference if reference is not None and reference > 0 else 0.0
    coverage_passed = bool(complete and delay is not None and delay <= 60 and correct / minutes >= 0.6 and capture_ratio >= 0.4)
    passed = coverage_passed and bool(fresh_hits)
    result.update(
        reference_points=reference,
        target_complete=complete,
        detection_delay_min=delay,
        fresh_detection_delay_min=fresh_delay,
        early_entry_lead_min=max(0.0, -fresh_delay) if fresh_delay is not None else None,
        fresh_entry_time=min(fresh_hits) if fresh_hits else None,
        first_correct_entry_time=min(first_correct_entries) if first_correct_entries else None,
        carried_from_before_window_count=carried_from_before_window,
        correct_coverage=correct / minutes,
        opposite_coverage=opposite / minutes,
        overlap_min=correct,
        longest_overlap_min=max(((b - a).total_seconds() / 60 for a, b in correct_intervals), default=0.0),
        captured_points=captured,
        capture_ratio=capture_ratio,
        coverage_pass=coverage_passed,
        passed=passed,
        correct_trade_count=correct_trade_count,
        correct_trade_closed=correct_trade_closed,
        correct_trade_net_points=correct_trade_net,
        held_after_target_count=held_after_count,
        post_target_closed=post_target_closed,
        post_target_gross_points=post_target_gross,
    )
    return [result]
