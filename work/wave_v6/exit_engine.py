"""方法①の入口を維持して、確定足に基づく返済条件を比較する。"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys

import numpy as np
import pandas as pd


sys.dont_write_bytecode = True
_MODULE_NAME = "_wave_v6_exit_reference"
if _MODULE_NAME not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        _MODULE_NAME, Path(__file__).resolve().parents[2] / "アルゴリズム調査" / "00001_波検知と売買ポイントの調査" / "保存版" / "work" / "wave_v4" / "engine.py")
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_MODULE_NAME] = _module
    _spec.loader.exec_module(_module)
BASE = sys.modules[_MODULE_NAME]

KINDS = ("baseline", "fixed_trail", "current_atr", "breakeven", "stepped",
         "profit_lock", "progressive", "structure", "stagnation", "reversal", "target")


@dataclass(frozen=True)
class ExitRule:
    """機能: 入口から独立した返済条件を保持する。

    引数: kind (str)、trigger/width/retain (float)、window/delay (int)。
    trigger と width は入口ATR倍率、retain は利益保護割合、delay は追加実在足数。
    返り値: 不変な返済条件 (ExitRule)。
    """

    kind: str
    trigger: float = 2.0
    width: float = 1.5
    retain: float = .7
    window: int = 10
    delay: int = 0

    @property
    def key(self) -> str:
        """機能: 全属性から一意の識別文字列を作る。

        引数: self (ExitRule)。返り値: 識別文字列 (str)。
        """
        return f"{self.kind}_開始{self.trigger:g}_幅{self.width:g}_保護{self.retain:g}_本数{self.window}_遅延{self.delay}"


def _check_rule(rule: ExitRule) -> None:
    """機能: 比較条件の範囲と方式を検証する。

    引数: rule (ExitRule)。返り値: なし (None)。不正値は ValueError。
    """
    if rule.kind not in KINDS:
        raise ValueError("未知の返済方式です")
    if (not np.isfinite(rule.trigger) or rule.trigger < 0
            or (rule.trigger == 0 and rule.kind != "reversal")
            or not np.isfinite(rule.width) or rule.width < 0
            or (rule.width == 0 and rule.kind != "structure")
            or not np.isfinite(rule.retain) or not 0 <= rule.retain <= 1
            or not isinstance(rule.window, int) or rule.window < 1
            or not isinstance(rule.delay, int) or rule.delay < 0):
        raise ValueError("返済条件の数値が範囲外です")


def _improve(old: float, new: float, side: int) -> float:
    """機能: 既存の保護価格を緩めずに更新する。

    引数: old/new (float)、side (int)。返り値: 更新保護価格 (float)。
    """
    return max(old, new) if side == 1 else min(old, new)


def _mark(active: dict, close: float, extreme: float, now: pd.Timestamp) -> None:
    """機能: 保有が確認できる価格だけから含み益最大値を記録する。

    引数: active (dict)、close/extreme (float)、now (Timestamp)。
    返り値: なし (None)。extreme は売買方向を掛けた有利価格。
    """
    side = active["side"]
    active["mfe_close_points"] = max(active["mfe_close_points"], side * (close - active["entry_price"]))
    if extreme > active["peak"]:
        active["last_peak_time"] = now
    active["peak"] = max(active["peak"], extreme)
    active["mfe_extreme_points"] = max(active["mfe_extreme_points"], active["peak"] - side * active["entry_price"])


def _finish(active: dict, now: pd.Timestamp, px: float, reason: str) -> None:
    """機能: 返済価格だけを退出足の観測値として確定損益を計算する。

    引数: active (dict)、now (Timestamp)、px (float)、reason (str)。
    返り値: なし (None)。退出足の約定後高安・終値は使わない。
    """
    _mark(active, px, active["side"] * px, now)
    gross = active["side"] * (px - active["entry_price"])
    active.update(exit_time=now, exit_price=float(px), reason=reason, closed=True,
                  duration_min=(now - active["entry_time"]).total_seconds() / 60,
                  gross_points=float(gross), giveback_points=max(0.0, active["mfe_close_points"] - gross))


def _bar_exit(active: dict, bar: np.ndarray, new_entry: bool = False) -> tuple[str, float] | None:
    """機能: 足開始前に存在する保護・利確条件の成立を保守的に判定する。

    引数: active (dict)、bar (ndarray)、new_entry (bool)。
    返り値: 理由・価格 (tuple[str, float]) または None。
    既存建玉の既知始値を先に扱い、足内順序不明なら損切り優先。
    新規足の利確は終値でも到達した場合だけ認める。
    """
    op, high, low, close = bar
    side, stop, target = active["side"], active["stop"], active["target"]
    stop_hit = low <= stop if side == 1 else high >= stop
    target_hit = target is not None and (high >= target if side == 1 else low <= target)
    if not new_entry:
        if side * (op - stop) <= 0:
            return "トレーリング・保護返済", float(op)
        if target is not None and side * (op - target) >= 0:
            return "固定指値利確", float(target)
    if stop_hit:
        if new_entry:
            active["ambiguous_entry"] = True
        active["ambiguous_exit"] = active["ambiguous_exit"] or bool(target_hit or new_entry)
        return ("新規足の順序不明・保護返済" if new_entry else "トレーリング・保護返済"), float(stop)
    if target_hit:
        if not new_entry or side * (close - target) >= 0:
            return "固定指値利確", float(target)
        active["ambiguous_exit"] = True
    return None


def _advance(active: dict, data: dict, rule: ExitRule, k: int, pos: int, trace: bool) -> None:
    """機能: 確定足までの情報から将来有効になる保護価格を計算する。

    引数: active/data (dict)、rule (ExitRule)、k/pos (int)、trace (bool)。
    返り値: なし (None)。更新は次実在足から、delay 本だけ追加遅延する。
    """
    side, atr, tick = active["side"], active["atr"], data["tick"]
    mfe = active["mfe_extreme_points"]
    reached = mfe >= rule.trigger * atr
    multiple, basis = 4.0, atr
    if rule.kind == "fixed_trail":
        multiple = rule.width
    elif rule.kind == "current_atr":
        multiple = rule.width
        current = data["atr"][pos]
        basis = float(current) if np.isfinite(current) else atr
    elif rule.kind == "stepped" and reached:
        multiple = rule.width
    elif rule.kind == "progressive":
        if mfe >= 3 * rule.trigger * atr:
            multiple = rule.width
        elif mfe >= 2 * rule.trigger * atr:
            multiple = 2.0
        elif reached:
            multiple = 3.0
    candidate = side * (active["peak"] - multiple * basis)
    if rule.kind == "target":
        candidate = active["initial_stop"]
    elif rule.kind == "breakeven" and reached:
        candidate = _improve(candidate, active["entry_price"] + side * 2 * tick, side)
    elif rule.kind == "profit_lock" and reached:
        candidate = _improve(candidate, active["entry_price"] + side * rule.retain * mfe, side)
    elif rule.kind == "structure" and reached:
        bars = data["values"][max(0, k - rule.window + 1):k + 1]
        structural = float(np.min(bars[:, 2]) - rule.width * atr) if side == 1 else float(np.max(bars[:, 1]) + rule.width * atr)
        candidate = _improve(candidate, structural, side)
    candidate = BASE.rounded(candidate, tick, side == -1)
    candidate = _improve(active["planned_stop"], candidate, side)
    active["planned_stop"] = candidate
    due = k + 1 + rule.delay
    active["stop_queue"].append((due, candidate))
    if trace:
        times = data["times"]
        active["protection_history"].append(dict(
            time=times[k], effective_time=times[due] if due < len(times) else None,
            stop=float(active["stop"]), next_stop=float(candidate),
            mfe_close_points=float(active["mfe_close_points"]),
            mfe_extreme_points=float(mfe), atr=float(basis)))


def _market_reason(active: dict, now: pd.Timestamp, pos: int, schedule: tuple,
                   cfg: object, rule: ExitRule) -> str | None:
    """機能: 始値時点で既知の停滞・反転条件を判定する。

    引数: active (dict)、now (Timestamp)、pos (int)、schedule (tuple)、cfg (object)、rule (ExitRule)。
    返り値: 成行返済理由 (str) または None。時刻返済の次、足内接触より先に扱う。
    """
    if active["mfe_extreme_points"] < rule.trigger * active["atr"]:
        return None
    if rule.kind == "stagnation":
        if (now - active["last_peak_time"]).total_seconds() / 60 >= rule.window:
            return "有利極値の更新停滞による返済"
    elif rule.kind == "reversal":
        signs, streaks = schedule
        side = int(signs[pos]) * (-1 if cfg.reverse else 1)
        if side == -active["side"] and streaks[pos] >= rule.window:
            return "累積方向の反転確認による返済"
    return None


def _new_active(data: dict, cfg: object, rule: ExitRule, now: pd.Timestamp, direction: int,
                px: float, pending: dict, ambiguous: bool, trace: bool) -> dict:
    """機能: 全方式共通の初期損切りを付けた建玉を作る。

    引数: data/pending (dict)、cfg (object)、rule (ExitRule)、now (Timestamp)、
    direction (int)、px (float)、ambiguous/trace (bool)。返り値: 建玉状態 (dict)。
    """
    tick, atr = data["tick"], float(pending["atr"])
    stop = BASE.rounded(px - direction * 2.5 * atr, tick, direction == -1)
    target = BASE.rounded(px + direction * rule.width * atr, tick, direction == 1) if rule.kind == "target" else None
    result = dict(symbol=data["symbol"], session=data["session"], config=cfg.key, exit_rule=rule.key,
                  side=int(direction), signal_time=pd.Timestamp(pending["signal_time"]), entry_time=now,
                  entry_price=float(px), atr=atr, entry_method=cfg.entry, initial_stop=float(stop),
                  initial_target=float(target) if target is not None else None,
                  stop=stop, planned_stop=stop, stop_queue=[], market_due=None, market_reason=None,
                  target=target, peak=direction * px, last_peak_time=now,
                  exit_time=None, exit_price=None, closed=False, duration_min=None, gross_points=None,
                  reason="観測途中", ambiguous_entry=bool(ambiguous), ambiguous_exit=False,
                  mfe_close_points=0.0, mfe_extreme_points=0.0, giveback_points=None)
    if trace:
        result["protection_history"] = []
    return result


def _simulate(data: dict, schedule: tuple, cfg: object, rule: ExitRule,
              anchor: dict | None, trace: bool) -> list[dict]:
    """機能: 通常の新規再判定、または一つの固定新規からセッションを再生する。

    引数: data (dict)、schedule (tuple)、cfg (object)、rule (ExitRule)、anchor (dict | None)、trace (bool)。
    返り値: 仮想取引一覧 (list[dict])。入口処理は旧実装と同じ条件・丸め・取消順序。
    """
    signs, streaks = schedule
    tick, limit_min = data["tick"], data["limit_min"]
    times, values, positions = data["times"], data["values"], data["positions"]
    atr_array, ref_array = data["atr"], data["ref"]
    active, pending = None, None
    closed = []
    allowed, blocked, last_checked = -1.0, 0, -1
    anchor_time = pd.Timestamp(anchor["entry_time"]) if anchor is not None else None
    entered_anchor = False
    for k, (now, minute, bar, pos) in enumerate(zip(times, data["minutes"], values, positions)):
        if anchor_time is not None and now < anchor_time:
            continue
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
        # 既存建玉は特徴欠測でも保護し、確定済み情報だけを始値時点へ反映する。
        if active is not None:
            direction = active["side"]
            queue = active["stop_queue"]
            while queue and queue[0][0] <= k:
                active["stop"] = _improve(active["stop"], queue.pop(0)[1], direction)
            event = None
            if minute >= limit_min:
                event = ("セッション内の時刻返済", op)
            else:
                if active["market_due"] is None:
                    market_reason = _market_reason(active, now, pos, schedule, cfg, rule)
                    if market_reason is not None:
                        active["market_due"], active["market_reason"] = k + rule.delay, market_reason
                if active["market_due"] is not None and active["market_due"] <= k:
                    event = (active["market_reason"], op)
                else:
                    event = _bar_exit(active, bar)
            if event is not None:
                _finish(active, now, event[1], event[0])
                closed.append(active)
                active, pending = None, None
                allowed = minute + cfg.cooldown
                blocked = direction if cfg.rearm == "opposite" else 0
            else:
                _mark(active, close, high if direction == 1 else -low, now)
                _advance(active, data, rule, k, pos, trace)
        if anchor is not None:
            if entered_anchor:
                if active is None:
                    break
                continue
            if now != anchor_time:
                continue
            direction, px = int(anchor["side"]), float(anchor["entry_price"])
            pending = dict(atr=float(anchor["atr"]), signal_time=anchor["signal_time"])
            ambiguous = bool(anchor.get("ambiguous_entry", False))
            entered_anchor = True
        else:
            if active is not None or minute >= limit_min - 30:
                pending = None
                continue
            if minute < allowed or minute < cfg.warmup or not np.isfinite(atr):
                continue

            # ----------------------------------------
            # 新規注文の作成・期限・反対方向取消・追跡更新は旧方式から変更しない。
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
                if direction == 1:
                    px = min(op, level) if is_limit and (op <= level or low <= level) else max(op, level) if not is_limit and high >= level else None
                else:
                    px = max(op, level) if is_limit and (op >= level or high >= level) else min(op, level) if not is_limit and low <= level else None
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
        # 新規と同じ足は終値のみで有利極値を更新し、同足損切りを優先する。
        active = _new_active(data, cfg, rule, now, direction, px, pending, ambiguous, trace)
        pending = None
        event = _bar_exit(active, bar, new_entry=True)
        if event is not None:
            _finish(active, now, event[1], event[0])
            closed.append(active)
            active = None
            allowed = minute + cfg.cooldown
            blocked = direction if cfg.rearm == "opposite" else 0
        else:
            _mark(active, close, direction * close, now)
            _advance(active, data, rule, k, pos, trace)
    if anchor is not None and not entered_anchor:
        raise ValueError("固定入口の時刻が再生データに存在しません")
    if active is not None:
        if times[-1] >= data["limit"]:
            raise AssertionError("終了済みセッションに未返済があります")
        closed.append(active)
    for trade in closed:
        for field in ("stop", "planned_stop", "stop_queue", "market_due", "market_reason", "target", "peak", "last_peak_time"):
            trade.pop(field, None)
        if trade["closed"]:
            trade["net_points"] = trade["gross_points"] - 2 * tick
            trade["stress_points"] = trade["gross_points"] - 4 * tick
            trade["net_atr"] = trade["net_points"] / trade["atr"]
    return closed


def simulate(data: dict, schedule: tuple, cfg: object, rule: ExitRule,
             anchors: list[dict] | None = None, trace: bool = False) -> list[dict]:
    """機能: 方法①の入口を固定したまま、指定した返済方式を比較する。

    引数: data (dict) は既存 prepare 入力、schedule (tuple) は方向と連続回数、
    cfg (ConfigV5 相当)、rule (ExitRule)、anchors (list[dict] | None)、trace (bool)。
    返り値: 元取引属性と MFE・利益減少・保護履歴を含む取引一覧 (list[dict])。
    anchors=None は同じ入口と返済後待機による再新規を含む実行可能方式。
    anchors 指定は各元入口を独立に再生する出口単独診断で、未来の入口時刻を
    既知として使うため実行可能な新規戦略の成績ではない。重複保有も起こり得る。
    """
    _check_rule(rule)
    if anchors is None:
        return _simulate(data, schedule, cfg, rule, None, trace)
    result = []
    for anchor in anchors:
        if anchor.get("symbol", data["symbol"]) != data["symbol"] or anchor.get("session", data["session"]) != data["session"]:
            raise ValueError("固定入口に別銘柄または別セッションが含まれています")
        result.extend(_simulate(data, schedule, cfg, rule, anchor, trace))
    return sorted(result, key=lambda trade: trade["entry_time"])
