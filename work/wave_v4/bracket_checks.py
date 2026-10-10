"""無作為方向の新規後、固定利確指値と損切り逆指値を比較する。"""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

from engine import Config, rounded
from null_checks import DIRECTION_SEEDS, summarize_runs
from research import save_json, schedule_for


BRACKETS = ((0.5, 2.0), (1.0, 1.0), (2.0, 0.5))
OUT = Path(__file__).resolve().parent


def simulate_bracket(data: dict, schedule: tuple, cfg: Config, take_atr: float, stop_atr: float) -> list[dict]:
    """機能: 確定条件の新規と、同じ返済方向の指値・逆指値を保守的に再生する。

    引数: data (dict) は再生入力、schedule (tuple[ndarray, ndarray]) は方向と確認回数、
        cfg (Config) は新規条件、take_atr/stop_atr (float) は新規時 ATR に対する利確・損切り幅。
    返り値: 取引の一覧 (list[dict])。同じ足で利確と損切りの両方に触れたら損切りを優先する。
    """
    if cfg.entry not in ("signal_limit", "stop", "pullback", "trail"):
        raise ValueError("固定返済の対照は一方向の指値・逆指値・追跡新規を対象とします。")
    signs, streaks = schedule
    tick, limit_min = data["tick"], data["limit_min"]
    active, pending = None, None
    trades = []
    allowed, blocked, last_checked = -1.0, 0, -1
    for now, minute, bar, pos in zip(data["times"], data["minutes"], data["values"], data["positions"]):
        op, high, low, close = bar
        if pos < 0:
            continue
        side = int(signs[pos])
        if blocked and any(int(value) == -blocked for value in signs[max(0, last_checked + 1):pos + 1]):
            blocked = 0
        last_checked = pos
        atr = data["atr"][pos]
        if not np.isfinite(atr):
            continue

        # ----------------------------------------
        if active is not None:
            direction, stop, take = active["side"], active["stop"], active["take"]
            stopped = low <= stop if direction == 1 else high >= stop
            taken = high >= take if direction == 1 else low <= take
            price, reason = None, None
            if minute >= limit_min:
                price, reason = op, "セッション内の時刻返済"
            elif stopped:
                price, reason = min(op, stop) if direction == 1 else max(op, stop), "固定損切り"
            elif taken:
                price, reason = take, "固定利確"
            if price is not None:
                active.update(exit_time=now, exit_price=float(price), closed=True,
                              gross_points=float(direction * (price - active["entry_price"])), reason=reason,
                              ambiguous_exit=bool(stopped and taken))
                trades.append(active)
                active = None
                pending = None
                allowed = minute + cfg.cooldown
                blocked = direction if cfg.rearm == "opposite" else 0
        if active is not None or minute >= limit_min - 30:
            pending = None
            continue
        if minute < allowed or minute < cfg.warmup:
            continue

        # ----------------------------------------
        if pending is not None and (minute - pending["armed"] > 25 or side == -pending["side"]):
            pending = None
        if pending is None:
            if side == 0 or side == blocked or streaks[pos] < cfg.confirm:
                continue
            ref = data["ref"][pos]
            gap = max(tick, cfg.offset * atr)
            pending = dict(side=side, ref=ref, atr=atr, armed=minute, anchor_low=ref, anchor_high=ref)
            if cfg.entry == "signal_limit":
                pending["level"] = rounded(ref + side * atr, tick, side == 1)
            elif cfg.entry == "pullback":
                pending["level"] = rounded(ref - side * gap, tick, side == -1)
            else:
                pending["level"] = rounded(ref + side * gap, tick, side == 1)
        direction, level = pending["side"], pending["level"]
        is_limit = cfg.entry in ("signal_limit", "pullback")
        if direction == 1:
            price = min(op, level) if is_limit and low <= level else max(op, level) if not is_limit and high >= level else None
        else:
            price = max(op, level) if is_limit and high >= level else min(op, level) if not is_limit and low <= level else None
        if price is None:
            if cfg.entry == "trail":
                pending["anchor_low"] = min(pending["anchor_low"], low)
                pending["anchor_high"] = max(pending["anchor_high"], high)
                gap = max(tick, cfg.offset * pending["atr"])
                pending["level"] = rounded(pending["anchor_low"] + gap if direction == 1 else pending["anchor_high"] - gap, tick, direction == 1)
            continue

        # ----------------------------------------
        stop = rounded(price - direction * stop_atr * pending["atr"], tick, direction == -1)
        take = rounded(price + direction * take_atr * pending["atr"], tick, direction == 1)
        active = dict(symbol=data["symbol"], session=data["session"], side=direction,
                      entry_time=now, entry_price=float(price), atr=float(pending["atr"]),
                      stop=stop, take=take, exit_time=None, exit_price=None, closed=False,
                      gross_points=None, reason="観測途中", ambiguous_exit=False)
        pending = None
        stopped = low <= stop if direction == 1 else high >= stop
        taken = high >= take if direction == 1 else low <= take
        take_order_known = (not is_limit) or price == op
        if stopped or (taken and take_order_known):
            exit_price = stop if stopped else take
            active.update(exit_time=now, exit_price=float(exit_price), closed=True,
                          gross_points=float(direction * (exit_price - price)),
                          reason="新規足の固定損切り" if stopped else "新規足の固定利確",
                          ambiguous_exit=bool(stopped and taken))
            trades.append(active)
            active = None
            allowed = minute + cfg.cooldown
            blocked = direction if cfg.rearm == "opposite" else 0
    if active is not None:
        if data["times"][-1] >= data["limit"]:
            raise AssertionError("完了セッションに未返済があります。")
        trades.append(active)
    for trade in trades:
        trade.pop("stop", None)
        trade.pop("take", None)
        if trade["closed"]:
            trade["net_points"] = trade["gross_points"] - 2 * tick
            trade["stress_points"] = trade["gross_points"] - 4 * tick
    return trades


def run_brackets(data: dict, cfg: Config | dict[str, Config]) -> dict:
    """機能: 事前固定３組の利確・損切り幅を100種ずつ比較する。

    引数: data (dict) は開発用保存再生入力、cfg (Config | dict[str, Config]) は共通または銘柄別の採用新規条件。
    返り値: 全セルと種別集計、手順を含む辞書 (dict)。
    """
    samples, summary = [], []
    configs = cfg if isinstance(cfg, dict) else {symbol: cfg for symbol in ("NK225", "TOPIX")}
    entries = {symbol: candidate.entry if candidate.entry in ("signal_limit", "stop", "pullback", "trail") else "stop" for symbol, candidate in configs.items()}
    for take_atr, stop_atr in BRACKETS:
        group = f"利確{take_atr:g}ATR・損切り{stop_atr:g}ATR"
        group_rows = []
        for seed in DIRECTION_SEEDS:
            candidates = {symbol: replace(original, family=101, param=1.0, reverse=False, seed=seed, entry=entries[symbol]) for symbol, original in configs.items()}
            schedules = {symbol: schedule_for(data, candidate) for symbol, candidate in candidates.items()}
            for key, item in data.items():
                trades = simulate_bracket(item, schedules[key[1]][key], candidates[key[1]], take_atr, stop_atr)
                closed = [trade for trade in trades if trade["closed"]]
                row = dict(group=group, seed=seed, symbol=key[1], session=key[0], count=len(trades),
                           closed=len(closed), wins=sum(trade["net_points"] > 0 for trade in closed),
                           net_points=sum(trade["net_points"] for trade in closed),
                           stress_points=sum(trade["stress_points"] for trade in closed),
                           ambiguous=sum(trade["ambiguous_exit"] for trade in closed))
                group_rows.append(row)
                samples.append(row)
        for value in summarize_runs(group_rows):
            subset = [row for row in group_rows if row["symbol"] == value["symbol"]]
            total_closed = sum(row["closed"] for row in subset)
            value.update(group=group,
                         pooled_win_rate=sum(row["wins"] for row in subset) / total_closed if total_closed else None,
                         mean_stress_points=sum(row["stress_points"] for row in subset) / len(DIRECTION_SEEDS),
                         ambiguous_count=sum(row["ambiguous"] for row in subset))
            summary.append(value)
    result = dict(config={symbol: asdict(candidate) for symbol, candidate in configs.items()}, entry=entries, brackets=BRACKETS, seeds=DIRECTION_SEEDS,
                  summary=summary,
                  method="新規約定後、同じ返済方向の利確指値と損切り逆指値を監視するIFD-OCO相当。利確は指値価格、損切り飛び越しは不利な始値。両方接触は損切り。指値新規の足で利確が新規後か不明なら、その足の利確を認めない。")
    pd.DataFrame(samples).to_csv(OUT / "固定利確損切り_全種.csv", index=False, encoding="utf-8-sig")
    save_json(OUT / "固定利確損切り_集計.json", result)
    lines = ["# 固定利確・固定損切りのコイントス対照", "", result["method"], "",
             "３組を先に固定し、各100種の公平な方向を使った。採用条件と同じ新規方法・待機時間で、方向は30分ごとに決めた。勝率は往復２ティック控除後の利益件数から計算する。", "",
             "|利確・損切り|銘柄|平均損益|中央値|5〜95百分位|利益となった種|取引勝率|平均取引数|４ティック控除平均|",
             "|---|---|---:|---:|---|---:|---:|---:|---:|"]
    for value in summary:
        lines.append(f'|{value["group"]}|{value["symbol"]}|{value["mean"]:.2f}|{value["median"]:.2f}|{value["percentile_05"]:.2f}〜{value["percentile_95"]:.2f}|{value["profitable_seed_fraction"]:.0%}|{value["pooled_win_rate"]:.1%}|{value["mean_count"]:.2f}|{value["mean_stress_points"]:.2f}|')
    lines.extend(["", "NK225は円幅、TOPIXはポイント。100種は同じ市場上の乱数の違いであり、独立した100日ではない。小さい利確と大きい損切りで勝率を上げても、純利益が改善するとは限らない。注文数量の増額や損失後の倍掛けは使用しない。", ""])
    (OUT / "固定利確損切り対照.md").write_text("\n".join(lines), encoding="utf-8")
    return result
