"""既存の新規条件を保ち、固定損益比と小さい初期損切りを比較する返済処理。"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys

import numpy as np
import pandas as pd


_BASE_NAME = "_wave_v4_exit_base"
if _BASE_NAME not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_BASE_NAME, Path(__file__).resolve().parent.parent / "wave_v4" / "engine.py")
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_BASE_NAME] = _module
    _spec.loader.exec_module(_module)
BASE = sys.modules[_BASE_NAME]


@dataclass(frozen=True)
class ConfigV5(BASE.Config):
    """機能: 既存の新規設定へ、初期損切りと固定利確の比較条件を加える。

    引数: 継承元の各属性、exit_mode (str)、stop_loss (float) はATR倍率、
    take_profit (float | None) は固定利確のATR倍率。
    返り値: 不変な比較条件 (ConfigV5)。
    """

    exit_mode: str = "nativebaseline"
    stop_loss: float = 1.0
    take_profit: float | None = 3.0

    @property
    def key(self) -> str:
        """機能: 初期損切り・利確を含む全条件を一意に識別する。

        引数: self (ConfigV5)。返り値: 条件識別子 (str)。
        """
        profit = "なし" if self.take_profit is None else f"{self.take_profit:g}"
        return f"{BASE.Config.key.fget(self)}_{self.exit_mode}_損切{self.stop_loss:g}_利確{profit}"


def _bar_exit(active: dict, op: float, high: float, low: float, close: float,
              new_entry: bool = False, entry_at_open: bool = False) -> tuple[str, float, bool] | None:
    """機能: 既知の保護価格・固定利確に対する一分足内の成立を保守的に判定する。

    引数: active (dict) は建玉、op/high/low/close (float) は足、
    new_entry (bool) は新規と同じ足、entry_at_open (bool) は始値での新規成立。
    返り値: 理由・返済価格・順序曖昧印 (tuple[str, float, bool])、不成立なら None。
    利確側の始値ギャップは指値価格で頭打ちにし、損切り側は不利な始値を使う。
    """
    side, stop, target = active["side"], active["stop"], active["target"]
    stop_hit = low <= stop if side == 1 else high >= stop
    profit_hit = target is not None and (high >= target if side == 1 else low <= target)
    if not new_entry:
        if side * (op - stop) <= 0:
            return "初期損切り・追跡返済", op, False
        if target is not None and side * (op - target) >= 0:
            return "固定指値利確", target, False
    if stop_hit:
        reason = "新規足の順序不明・保護返済" if new_entry else "初期損切り・追跡返済"
        return reason, stop, bool(profit_hit or (new_entry and not entry_at_open))
    if profit_hit:
        if not new_entry or entry_at_open or side * (close - target) >= 0:
            return "固定指値利確", target, False
        # 新規前に利益側の高安を付けた可能性があり、同足利確を成立扱いにしない。
        active["ambiguous_exit"] = True
    return None


def _advance_stop(active: dict, cfg: ConfigV5, current_atr: float, peak_value: float,
                  reg: float, r2: float) -> None:
    """機能: 確定した有利価格から追跡保護価格を次足用に更新する。

    引数: active (dict)、cfg (ConfigV5)、current_atr/peak_value/reg/r2 (float)。
    返り値: なし (None)。固定利確型では初期損切りを変更しない。
    """
    if cfg.exit_mode != "small_stop_trail":
        return
    side = active["side"]
    active["peak"] = max(active["peak"], peak_value)
    basis = active["atr"] if cfg.trail_basis == "entry" else current_atr
    if not np.isfinite(basis):
        return
    multiple = cfg.trail
    if cfg.trail_basis == "regime" and not (side * reg > 0 and r2 >= 0.25):
        multiple = 1.0
    candidate = BASE.rounded(side * (active["peak"] - multiple * basis), active["tick"], side == -1)
    active["stop"] = max(active["stop"], candidate) if side == 1 else min(active["stop"], candidate)


def _finish(active: dict, now: pd.Timestamp, price: float, reason: str, ambiguous: bool) -> None:
    """機能: 建玉へ返済時刻・損益・順序不確実性を記録する。

    引数: active (dict)、now (Timestamp)、price (float)、reason (str)、ambiguous (bool)。
    返り値: なし (None)。
    """
    active.update(exit_time=now, exit_price=float(price), reason=reason, closed=True,
                  duration_min=(now - active["entry_time"]).total_seconds() / 60,
                  gross_points=active["side"] * (price - active["entry_price"]),
                  ambiguous_exit=active["ambiguous_exit"] or ambiguous)


def simulate_exit(data: dict, schedule: tuple[np.ndarray, np.ndarray], cfg: ConfigV5 | BASE.Config,
                  limit_penetration_ticks: int = 0) -> list[dict]:
    """機能: 既存と同じ新規条件に、固定損益比または小さい初期損切りを適用する。

    引数: data (dict) は v4.prepare と同じ再生入力、schedule (tuple[ndarray, ndarray]) は方向と連続回数、
    cfg (ConfigV5 | v4.Config)、limit_penetration_ticks (int) は指値貫通条件。
    返り値: セッション内の仮想取引 (list[dict])。
    nativebaseline は既存関数へ委譲する。追加方式も未知順序は損失優先とし、
    新規足の利益側高安だけによる利確を認めず、始値新規または終値到達を必要とする。
    """
    mode = getattr(cfg, "exit_mode", "nativebaseline")
    if mode == "nativebaseline":
        return BASE.simulate(data, schedule, cfg, limit_penetration_ticks=limit_penetration_ticks)
    if mode not in ("fixed_bracket", "small_stop_trail") or cfg.stop_loss <= 0:
        raise ValueError("返済方式または初期損切り倍率が不正です")
    if mode == "fixed_bracket" and (cfg.take_profit is None or cfg.take_profit <= 0):
        raise ValueError("固定利確方式には正の利確倍率が必要です")
    signs, streaks = schedule
    tick, limit_min = data["tick"], data["limit_min"]
    times, values, positions = data["times"], data["values"], data["positions"]
    atr_array, ref_array = data["atr"], data["ref"]
    active, pending = None, None
    closed = []
    allowed, blocked, last_checked = -1.0, 0, -1
    for now, minute, bar, pos in zip(times, data["minutes"], values, positions):
        op, high, low, close = bar
        if pos < 0:
            continue
        side = int(signs[pos]) * (-1 if cfg.reverse else 1)
        if blocked:
            for value in signs[max(0, last_checked + 1):pos + 1]:
                if int(value) * (-1 if cfg.reverse else 1) == -blocked:
                    blocked = 0
                    break
        last_checked = pos
        atr = atr_array[pos]

        # ----------------------------------------
        # 保護・時刻返済は、現在特徴量が欠測していても常に有効。
        if active is not None:
            direction = active["side"]
            event = ("セッション内の時刻返済", op, False) if minute >= limit_min else _bar_exit(active, op, high, low, close)
            if event is not None:
                _finish(active, now, event[1], event[0], event[2])
                closed.append(active)
                active, pending = None, None
                allowed = minute + cfg.cooldown
                blocked = direction if cfg.rearm == "opposite" else 0
            else:
                _advance_stop(active, cfg, float(atr), high if direction == 1 else -low,
                              data["reg"][pos], data["r2"][pos])
        if active is not None or minute >= limit_min - 30:
            pending = None
            continue
        if minute < allowed or minute < cfg.warmup or not np.isfinite(atr):
            continue

        # ----------------------------------------
        # 新規注文の条件・待機・取消は v4 と同じ規則。
        both = cfg.entry in ("straddle_stop", "straddle_trail")
        if pending is not None and (minute - pending["armed"] > 25 or (not both and side == -pending["side"])):
            pending = None
        if pending is None:
            if not both and (side == 0 or side == blocked or streaks[pos] < cfg.confirm):
                continue
            if both and (side == 0 or streaks[pos] < cfg.confirm):
                continue
            ref = ref_array[pos]
            gap = max(tick, cfg.offset * atr)
            pending = dict(side=side, ref=ref, atr=atr, armed=minute, anchor_low=ref, anchor_high=ref,
                           signal_time=data["z"].index[pos] + pd.Timedelta(minutes=1))
            if cfg.entry == "signal_limit":
                pending["level"] = BASE.rounded(ref + side * atr, tick, side == 1)
            elif cfg.entry == "pullback":
                pending["level"] = BASE.rounded(ref - side * gap, tick, side == -1)
            elif cfg.entry in ("stop", "trail"):
                pending["level"] = BASE.rounded(ref + side * gap, tick, side == 1)
            elif both:
                pending["upper"] = BASE.rounded(ref + gap, tick, True)
                pending["lower"] = BASE.rounded(ref - gap, tick, False)
            else:
                raise ValueError("未知の新規方法です")
        direction, px, ambiguous = pending["side"], None, False
        if both:
            up, down = pending["upper"], pending["lower"]
            touched_up, touched_down = high >= up, low <= down
            if op >= up:
                direction, px = 1, op
            elif op <= down:
                direction, px = -1, op
            elif touched_up and touched_down:
                direction = 1 if close - up <= down - close else -1
                px, ambiguous = (up if direction == 1 else down), True
            elif touched_up:
                direction, px = 1, up
            elif touched_down:
                direction, px = -1, down
        else:
            level = pending["level"]
            is_limit = cfg.entry in ("signal_limit", "pullback")
            penetration = limit_penetration_ticks * tick
            if direction == 1:
                px = min(op, level) if is_limit and (op <= level or low <= level - penetration) else max(op, level) if not is_limit and high >= level else None
            else:
                px = max(op, level) if is_limit and (op >= level or high >= level + penetration) else min(op, level) if not is_limit and low <= level else None
        if px is None:
            if cfg.entry in ("trail", "straddle_trail"):
                pending["anchor_low"] = min(pending["anchor_low"], low)
                pending["anchor_high"] = max(pending["anchor_high"], high)
                gap = max(tick, cfg.offset * pending["atr"])
                if both:
                    pending["upper"] = BASE.rounded(pending["anchor_low"] + gap, tick, True)
                    pending["lower"] = BASE.rounded(pending["anchor_high"] - gap, tick, False)
                else:
                    pending["level"] = BASE.rounded(pending["anchor_low"] + gap if direction == 1 else pending["anchor_high"] - gap, tick, direction == 1)
            continue

        # ----------------------------------------
        # 初期保護と固定利確を約定価格から設定する。利益側価格の改善は計上しない。
        stop = BASE.rounded(px - direction * cfg.stop_loss * pending["atr"], tick, direction == -1)
        target = BASE.rounded(px + direction * cfg.take_profit * pending["atr"], tick, direction == 1) if mode == "fixed_bracket" else None
        active = dict(symbol=data["symbol"], session=data["session"], config=cfg.key, side=int(direction),
                      signal_time=pending["signal_time"], entry_time=now, entry_price=float(px), atr=float(pending["atr"]),
                      entry_method=cfg.entry, exit_mode=mode, initial_stop=float(stop), initial_target=float(target) if target is not None else None,
                      stop=stop, target=target, peak=direction * px, tick=tick, exit_time=None, exit_price=None,
                      closed=False, duration_min=None, gross_points=None, reason="観測途中", ambiguous_entry=ambiguous,
                      ambiguous_exit=False)
        pending = None
        event = _bar_exit(active, op, high, low, close, new_entry=True, entry_at_open=bool(px == op))
        if event is not None:
            _finish(active, now, event[1], event[0], event[2])
            if "新規足" in event[0]:
                active["ambiguous_entry"] = True
            closed.append(active)
            active = None
            allowed = minute + cfg.cooldown
            blocked = direction if cfg.rearm == "opposite" else 0
        else:
            # 新規足の高安が新規前か後か不明なため、この足だけは終値で追跡する。
            _advance_stop(active, cfg, float(atr), direction * close, data["reg"][pos], data["r2"][pos])
    if active is not None:
        if times[-1] >= data["limit"]:
            raise AssertionError("終了済みセッションに未返済があります")
        closed.append(active)
    for trade in closed:
        for field in ("stop", "target", "peak", "tick"):
            trade.pop(field, None)
        if trade["closed"]:
            trade["net_points"] = trade["gross_points"] - 2 * tick
            trade["stress_points"] = trade["gross_points"] - 4 * tick
            trade["net_atr"] = trade["net_points"] / trade["atr"]
    return closed
