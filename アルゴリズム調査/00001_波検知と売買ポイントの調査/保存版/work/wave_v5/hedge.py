"""同時両建てと無作為片建てを、同じ費用・セッション境界で再生する。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math

import numpy as np


@dataclass(frozen=True)
class HedgeConfig:
    """機能: 両建ての小損切りと固定利確または勝ち脚追跡条件を保持する。

    引数: exit_mode (str)、stop/target (float) はATR幅、cooldown/warmup (int) は分。
    返り値: 固定条件 (HedgeConfig)。
    """

    exit_mode: str
    stop: float
    target: float
    cooldown: int
    warmup: int

    @property
    def key(self) -> str:
        """機能: 条件を一意に表す識別子を作る。

        引数: self (HedgeConfig)。返り値: 条件識別子 (str)。
        """
        return f"両建て_{self.exit_mode}_SL{self.stop:g}_幅{self.target:g}_待機{self.cooldown}_開始{self.warmup}"


def rounded(value: float, tick: float, upward: bool) -> float:
    """機能: 注文価格を呼値単位で丸める。

    引数: value/tick (float)、upward (bool)。返り値: 呼値価格 (float)。
    """
    return (math.ceil(value / tick) if upward else math.floor(value / tick)) * tick


def simulate(data: dict, cfg: HedgeConfig, seed: int | None = None, keep_trades: bool = True) -> tuple[list, dict]:
    """機能: 両脚独立返済と、両脚がなくなった後だけの再新規を再生する。

    引数: data (dict) は配列化した保存入力、cfg (HedgeConfig) は出口条件、
        seed (int | None) は片側コイントス種、Noneなら買売各１枚、keep_trades (bool) は取引明細保存。
    返り値: 脚別取引とセッション集計 (tuple[list, dict])。
    新規は既知価格±１ATRの条件指値を共に満たす実在始値で近似し、成行新規は使わない。
    """
    if cfg.exit_mode not in ("固定利確", "勝ち脚追跡"):
        raise ValueError("出口方法が不正です。")
    tick, limit = float(data["tick"]), float(data["limit_min"])
    values, positions = data["values"], data["positions"]
    times, minutes = data["times"], data["minutes"]
    salts = int(hashlib.sha256(f'{data["session"]}/{data["symbol"]}'.encode()).hexdigest()[:8], 16)
    choices = np.random.default_rng(seed + salts).choice([-1, 1], len(times)) if seed is not None else None
    active, completed = [], []
    allowed = float(cfg.warmup)
    cycles = 0
    pair_pnl = {}
    pair_stress = {}
    cumulative_atr, peak_atr, cumulative_points, peak_points = 0.0, 0.0, 0.0, 0.0
    cell = dict(config=cfg.key, session=data["session"], symbol=data["symbol"], seed=seed,
                mode="両建て" if seed is None else "片側コイントス", count=0, closed=0,
                positive_points=0.0, negative_points=0.0, net_points=0.0, stress_points=0.0,
                net_atr=0.0, stress_atr=0.0,
                realized_dd_atr=0.0, realized_dd_points=0.0,
                wins=0, gross_points=0.0, sum_duration_min=0.0, ambiguous=0,
                gross_absolute_entry_quantity=2 if seed is None else 1)
    for k, (now, minute, bar, pos) in enumerate(zip(times, minutes, values, positions)):
        op, high, low, close = bar
        just_closed = False
        new_legs = False
        if not active and minute < limit - 30 and minute >= allowed and pos >= 0:
            atr = float(data["atr"][pos])
            ref = float(data["ref"][pos])
            if not np.isfinite(atr) or atr <= 0 or not np.isfinite(ref):
                continue
            upper, lower = rounded(ref + atr, tick, True), rounded(ref - atr, tick, False)
            if not lower <= op <= upper:
                continue
            cycles += 1
            sides = (1, -1) if seed is None else (int(choices[cycles - 1]),)
            for side in sides:
                active.append(dict(symbol=data["symbol"], session=data["session"], config=cfg.key,
                                   seed=seed, cycle=cycles, side=side, quantity=1,
                                   signal_position=int(pos), entry_position=k, entry_time=now,
                                   entry_price=float(op), atr=atr,
                                   stop=rounded(op - side * cfg.stop * atr, tick, side == -1),
                                   take=rounded(op + side * cfg.target * atr, tick, side == 1),
                                   peak=side * op, closed=False))
            cell["count"] += len(sides)
            new_legs = True

        # ----------------------------------------
        # 足開始に存在した損切りと利確だけを判定し、同じ足の順番は損失側へ倒す。
        survivors = []
        bar_net_atr, bar_net_points = 0.0, 0.0
        for leg in active:
            side, stop = leg["side"], leg["stop"]
            stopped = low <= stop if side == 1 else high >= stop
            taken = (high >= leg["take"] if side == 1 else low <= leg["take"]) and cfg.exit_mode == "固定利確"
            px, reason = None, None
            if minute >= limit:
                px, reason = op, "セッション内の時刻返済"
            elif not new_legs and (op <= stop if side == 1 else op >= stop):
                px, reason = op, "始値の損切り飛び越し"
            elif not new_legs and cfg.exit_mode == "固定利確" and (op >= leg["take"] if side == 1 else op <= leg["take"]):
                px, reason = leg["take"], "始値で成立した固定利確"
            elif stopped:
                px = (min(op, stop) if side == 1 else max(op, stop)) if not new_legs else stop
                reason = "固定損切りまたは追跡返済"
            elif taken:
                px, reason = leg["take"], "固定利確"
            if px is None:
                leg["peak"] = max(leg["peak"], high if side == 1 else -low)
                survivors.append(leg)
                continue
            gross = float(side * (px - leg["entry_price"]))
            net, stress = gross - 2 * tick, gross - 4 * tick
            duration = float(minute - minutes[leg["entry_position"]])
            leg.update(exit_time=now, exit_price=float(px), closed=True, gross_points=gross,
                       net_points=net, stress_points=stress, duration_min=duration,
                       reason=reason, ambiguous=bool(stopped and taken))
            leg.pop("stop", None)
            leg.pop("take", None)
            leg.pop("peak", None)
            if keep_trades:
                completed.append(leg)
            cell["closed"] += 1
            cell["wins"] += net > 0
            cell["gross_points"] += gross
            cell["net_points"] += net
            cell["stress_points"] += stress
            cell["net_atr"] += net / leg["atr"]
            cell["stress_atr"] += stress / leg["atr"]
            bar_net_atr += net / leg["atr"]
            bar_net_points += net
            cell["positive_points"] += max(0.0, net)
            cell["negative_points"] += min(0.0, net)
            cell["sum_duration_min"] += duration
            cell["ambiguous"] += int(stopped and taken)
            pair_pnl[leg["cycle"]] = pair_pnl.get(leg["cycle"], 0.0) + net
            pair_stress[leg["cycle"]] = pair_stress.get(leg["cycle"], 0.0) + stress
            just_closed = True
        active = survivors
        cumulative_atr += bar_net_atr
        cumulative_points += bar_net_points
        peak_atr = max(peak_atr, cumulative_atr)
        peak_points = max(peak_points, cumulative_points)
        cell["realized_dd_atr"] = max(cell["realized_dd_atr"], peak_atr - cumulative_atr)
        cell["realized_dd_points"] = max(cell["realized_dd_points"], peak_points - cumulative_points)
        if not active and just_closed:
            allowed = minute + cfg.cooldown

        # ----------------------------------------
        # 生き残った１脚だけを追跡する。更新価格は必ず次の実在足から有効にする。
        if cfg.exit_mode == "勝ち脚追跡" and len(active) == 1:
            leg = active[0]
            side = leg["side"]
            candidate = rounded(side * (leg["peak"] - cfg.target * leg["atr"]), tick, side == -1)
            leg["stop"] = max(leg["stop"], candidate) if side == 1 else min(leg["stop"], candidate)
    if active:
        raise AssertionError("完全セッションの末尾に未返済の脚があります。")
    pair_values = np.array(list(pair_pnl.values()), dtype=float)
    cell.update(cycle_count=cycles, pair_wins=int((pair_values > 0).sum()),
                pair_positive_points=float(pair_values[pair_values > 0].sum()),
                pair_negative_points=float(pair_values[pair_values < 0].sum()),
                pair_win_rate=float((pair_values > 0).mean()) if cycles else None,
                win_rate=float(cell["wins"] / cell["closed"]) if cell["closed"] else None,
                mean_duration_min=cell["sum_duration_min"] / cell["closed"] if cell["closed"] else None,
                net_points_per_initial_absolute_contract=cell["net_points"] / cell["gross_absolute_entry_quantity"],
                equivalent_two_contract_net_points=cell["net_points"] * (2 / cell["gross_absolute_entry_quantity"]),
                equivalent_two_contract_stress_points=cell["stress_points"] * (2 / cell["gross_absolute_entry_quantity"]))
    cell.update(profit_points=cell["positive_points"], loss_points=-cell["negative_points"],
                net_atr_per_initial_absolute_contract=cell["net_atr"] / cell["gross_absolute_entry_quantity"],
                stress_atr_per_initial_absolute_contract=cell["stress_atr"] / cell["gross_absolute_entry_quantity"])
    cell["wins"] = int(cell["wins"])
    return completed, cell
