"""指値・逆指値・反発待ち新規と、確定一分ごとの追跡返済を比較する。"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import math

import numpy as np
import pandas as pd

TICKS = {"NK225": 10.0, "TOPIX": 0.5}


@dataclass(frozen=True)
class Config:
    """機能: 一つの再現可能な比較条件を保持する。

    引数: 各属性に宣言した型。返り値: 条件インスタンス (Config)。
    """
    family: int
    param: float = 1.0
    entry: str = "signal_limit"
    offset: float = 0.5
    trail: float = 2.5
    cooldown: int = 15
    rearm: str = "cooldown"
    confirm: int = 1
    reverse: bool = False
    seed: int = 271828
    trail_basis: str = "entry"
    warmup: int = 14

    @property
    def key(self) -> str:
        """機能: 条件を一意に表す名前を返す。

        引数: self (Config)。返り値: 条件識別子 (str)。
        """
        return f"{self.family:03d}_{self.param:g}_{self.entry}_{self.offset:g}_{self.trail:g}_{self.cooldown}_{self.rearm}_{self.confirm}_{int(self.reverse)}_{self.seed}_{self.trail_basis}_{self.warmup}"


def deadline(index: pd.DatetimeIndex) -> pd.Timestamp:
    """機能: 保存セッション内の事前指定返済時刻を求める。

    引数: index (DatetimeIndex)。返り値: 返済指示時刻 (Timestamp)。
    """
    first = index[0]
    return first.normalize() + (pd.Timedelta(days=1, hours=5, minutes=50) if first.hour >= 16 else pd.Timedelta(hours=5, minutes=50) if first.hour < 7 else pd.Timedelta(hours=15, minutes=35))


def prepare(one: pd.DataFrame, z: pd.DataFrame, symbol: str, session: str) -> dict:
    """機能: 仮想約定用の実在足と、二分遅延した特徴量参照位置を固定する。

    引数: one/z (DataFrame)、symbol/session (str)。返り値: 配列化した再生入力 (dict)。
    """
    limit = deadline(one.index)
    if one.index[-1] >= limit + pd.Timedelta(minutes=5):
        raise ValueError("別セッションの価格を含む入力です")
    start = z.index[0]
    minutes = ((one.index - start).total_seconds() / 60).astype(int).to_numpy()
    positions = np.searchsorted((z.index + pd.Timedelta(minutes=2)).asi8, one.index.asi8, side="right") - 1
    return dict(one=one, z=z, symbol=symbol, session=session, times=one.index, minutes=minutes,
                values=one[["open", "high", "low", "close"]].to_numpy(float), positions=positions,
                atr=z.atr.to_numpy(float), ref=z.close.to_numpy(float),
                reg=z.reg15.to_numpy(float) if "reg15" in z else np.zeros(len(z)),
                r2=z.r2_15.to_numpy(float) if "r2_15" in z else np.zeros(len(z)), limit=limit,
                limit_min=(limit-start).total_seconds()/60, tick=TICKS[symbol])


def sign_schedule(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """機能: 過去から連続する方向確認回数を計算する。

    引数: values (ndarray) は符号付き信号。返り値: 方向と連続回数 (tuple[ndarray, ndarray])。
    """
    signs = np.sign(np.nan_to_num(values)).astype(np.int8)
    streaks = np.zeros(len(signs), dtype=np.int32)
    for i, side in enumerate(signs):
        streaks[i] = streaks[i-1] + 1 if i and side and side == signs[i-1] else int(side != 0)
    return signs, streaks


def rounded(value: float, tick: float, upward: bool) -> float:
    """機能: 注文条件価格を指定した方向へ呼値単位で丸める。

    引数: value/tick (float)、upward (bool)。返り値: 呼値単位の価格 (float)。
    """
    return (math.ceil(value / tick) if upward else math.floor(value / tick)) * tick


def simulate(data: dict, schedule: tuple[np.ndarray, np.ndarray], cfg: Config,
             limit_penetration_ticks: int = 0) -> list[dict]:
    """機能: 条件新規とトレーリング逆指値返済を保守的な一分足で再生する。

    引数: data (dict)、schedule (tuple[ndarray, ndarray])、cfg (Config)、
    limit_penetration_ticks (int) は指値を通過する必要ティック数。返り値: 仮想取引 (list[dict])。
    高安の順序不明な新規足で保護価格にも触れた場合は損失側を採る。
    追跡価格は確定足の後に更新し、次の実在足から有効。実際の連続監視型trailとは分ける。
    """
    signs, streaks = schedule
    tick, limit_min = data["tick"], data["limit_min"]
    times, values, positions = data["times"], data["values"], data["positions"]
    active, pending = None, None
    closed = []
    allowed, blocked, last_checked = -1.0, 0, -1
    atr_array, ref_array = data["atr"], data["ref"]
    for k, (now, minute, bar, pos) in enumerate(zip(times, data["minutes"], values, positions)):
        op, high, low, close = bar
        if pos < 0:
            continue
        side = int(signs[pos]) * (-1 if cfg.reverse else 1)
        if blocked:
            for value in signs[max(0, last_checked+1):pos+1]:
                if int(value) * (-1 if cfg.reverse else 1) == -blocked:
                    blocked = 0
                    break
        last_checked = pos
        atr = atr_array[pos]
        if not np.isfinite(atr):
            continue

        # ----------------------------------------
        # 既存建玉は予定時刻または事前に存在する保護価格だけで返済する。
        if active is not None:
            direction, stop = active["side"], active["stop"]
            reason, px = None, None
            if minute >= limit_min:
                reason, px = "セッション内の時刻返済", op
            elif direction == 1 and low <= stop:
                reason, px = "トレーリング・保護返済", min(op, stop)
            elif direction == -1 and high >= stop:
                reason, px = "トレーリング・保護返済", max(op, stop)
            if reason is not None:
                active.update(exit_time=now, exit_price=float(px), reason=reason, closed=True,
                              duration_min=(now-active["entry_time"]).total_seconds()/60,
                              gross_points=direction*(px-active["entry_price"]))
                closed.append(active)
                active = None
                allowed = minute + cfg.cooldown
                blocked = direction if cfg.rearm == "opposite" else 0
                pending = None
            else:
                active["peak"] = max(active["peak"], high if direction == 1 else -low)
                basis = active["atr"] if cfg.trail_basis == "entry" else float(atr)
                multiple = cfg.trail
                if cfg.trail_basis == "regime" and not (direction * data["reg"][pos] > 0 and data["r2"][pos] >= .25):
                    multiple = 1.0
                candidate = direction * (active["peak"] - multiple * basis)
                candidate = rounded(candidate, tick, direction == -1)
                active["stop"] = max(stop, candidate) if direction == 1 else min(stop, candidate)
        if active is not None or minute >= limit_min - 30:
            pending = None
            continue
        if minute < allowed or minute < cfg.warmup:
            continue

        # ----------------------------------------
        # 注文は信号時点で既知の価格から作り、期限や反対信号で取消する。
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
                           signal_time=data["z"].index[pos]+pd.Timedelta(minutes=1))
            if cfg.entry == "signal_limit":
                pending["level"] = rounded(ref + side * atr, tick, side == 1)
            elif cfg.entry == "pullback":
                pending["level"] = rounded(ref - side * gap, tick, side == -1)
            elif cfg.entry in ("stop", "trail"):
                pending["level"] = rounded(ref + side * gap, tick, side == 1)
            elif both:
                pending["upper"] = rounded(ref + gap, tick, True)
                pending["lower"] = rounded(ref - gap, tick, False)
            else:
                raise ValueError("未知の新規方法です")
        direction = pending["side"]
        px = None
        ambiguous = False
        if both:
            up, down = pending["upper"], pending["lower"]
            touched_up, touched_down = high >= up, low <= down
            if op >= up:
                direction, px = 1, op
            elif op <= down:
                direction, px = -1, op
            elif touched_up and touched_down:
                # 同分で両側へ到達した場合は、その足の終値に対して不利な側を先着扱いにする。
                direction = 1 if close - up <= down - close else -1
                px = up if direction == 1 else down
                ambiguous = True
            elif touched_up:
                direction, px = 1, up
            elif touched_down:
                direction, px = -1, down
        else:
            level = pending["level"]
            is_limit = cfg.entry in ("signal_limit", "pullback")
            penetration = limit_penetration_ticks * tick
            if direction == 1:
                px = min(op, level) if is_limit and (op <= level or low <= level-penetration) else max(op, level) if not is_limit and high >= level else None
            else:
                px = max(op, level) if is_limit and (op >= level or high >= level+penetration) else min(op, level) if not is_limit and low <= level else None
        if px is None:
            if cfg.entry in ("trail", "straddle_trail"):
                pending["anchor_low"] = min(pending["anchor_low"], low)
                pending["anchor_high"] = max(pending["anchor_high"], high)
                gap = max(tick, cfg.offset * pending["atr"])
                if both:
                    pending["upper"] = rounded(pending["anchor_low"]+gap, tick, True)
                    pending["lower"] = rounded(pending["anchor_high"]-gap, tick, False)
                else:
                    pending["level"] = rounded(pending["anchor_low"]+gap if direction == 1 else pending["anchor_high"]-gap, tick, direction == 1)
            continue

        # ----------------------------------------
        # 約定分の不明な順序は保守的に処理し、未到来の返済価格は作らない。
        stop = rounded(px-direction*min(2.5, cfg.trail)*pending["atr"], tick, direction == -1)
        active = dict(symbol=data["symbol"], session=data["session"], config=cfg.key, side=int(direction),
                      signal_time=pending["signal_time"], entry_time=now, entry_price=float(px), atr=float(pending["atr"]),
                      entry_method=cfg.entry, stop=stop, peak=direction*px, exit_time=None, exit_price=None,
                      closed=False, duration_min=None, gross_points=None, reason="観測途中", ambiguous_entry=ambiguous)
        pending = None
        if (direction == 1 and low <= stop) or (direction == -1 and high >= stop):
            # 逆指値新規後の保護価格到達を否定できない場合、同じ足で保護返済したものとする。
            active.update(exit_time=now, exit_price=float(stop), closed=True, duration_min=0.0,
                          gross_points=direction*(stop-px), reason="新規足の順序不明・保護返済", ambiguous_entry=True)
            closed.append(active)
            active = None
            allowed = minute+cfg.cooldown
            blocked = direction if cfg.rearm == "opposite" else 0
        else:
            active["peak"] = max(active["peak"], direction*close)
            candidate = rounded(direction*(active["peak"]-cfg.trail*active["atr"]), tick, direction == -1)
            active["stop"] = max(stop, candidate) if direction == 1 else min(stop, candidate)
    if active is not None:
        if times[-1] >= data["limit"]:
            raise AssertionError("終了済みセッションに未返済があります")
        closed.append(active)
    for trade in closed:
        trade.pop("stop", None)
        trade.pop("peak", None)
        if trade["closed"]:
            trade["net_points"] = trade["gross_points"]-2*tick
            trade["stress_points"] = trade["gross_points"]-4*tick
            trade["net_atr"] = trade["net_points"]/trade["atr"]
    return closed
