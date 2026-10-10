"""E01を観測順に実行する、外部通信を持たない仮想売買エンジン。"""

from __future__ import annotations

from copy import deepcopy
import math


PRODUCTS = {
    "TOPIX": {"quantity": 5, "cap": 10, "tick": 0.5, "point_value": 1000},
    "NK225": {"quantity": 10, "cap": 20, "tick": 10.0, "point_value": 10},
}
REASONS = {
    1: "組の損切り", 2: "追跡返済", 7: "2ATRの部分利確",
    8: "360分の保有上限", 9: "セッション内返済", 20: "追跡新規",
    30: "順行後の悪化で半減", 32: "実建玉の1ATR損失予算", 90: "運転上の返済",
}


def _rounded(value: float, tick: float, side: int) -> float:
    """機能: 注文方向に応じ、研究と同じ呼値へ丸める。

    引数: value(float)価格、tick(float)呼値、side(int)注文方向。
    返り値: 丸めた価格(float)。
    """
    return (math.ceil(value / tick - 1e-9) if side > 0 else math.floor(value / tick + 1e-9)) * tick


def _new_shadow() -> dict:
    """機能: 独立した影運転の初期状態を作る。

    引数: なし。返り値: JSON保存可能な状態(dict)。
    """
    return dict(direction=0, campaign=-1, quantity=0, anchor=0.0, atr=0.0,
                extreme=0.0, realized=0.0, entry_time=0.0, entry_row=-1,
                last_exit=None, split_done=False, trail_floor=None, plan=None,
                pending=None, prepare_count=0, gate_arm=-1)


def _new_actual() -> dict:
    """機能: 元枠を保持する実仮想建玉の初期状態を作る。

    引数: なし。返り値: JSON保存可能な状態(dict)。
    """
    return dict(direction=0, campaign=-1, anchor=0.0, atr=0.0, slots=[], alive=[],
                realized=0.0, reductions=0, barrier=-1, pending=None, budget=None,
                entry_row=-1, entry_time=0.0)


class E01Engine:
    """通信・実注文を行わず、前観測で作った条件だけを現在価格に適用する。"""

    VERSION = 1

    def __init__(self, symbol: str, session_id: str, session_start: float,
                 force_close_time: float, session_close_time: float,
                 state: dict | None = None, fill_mode: str = "specified") -> None:
        """機能: 固定E01を初期化するか、保存状態から復元する。

        引数: symbol/session_id(str)、各時刻(float、UNIX秒)、state(dict|None)、
        fill_mode(str、specified=既設条件価格、observed=現在観測価格)。
        返り値: なし(None)。
        """
        if symbol not in PRODUCTS or fill_mode not in ("specified", "observed"):
            raise ValueError("銘柄又は約定方式が不正です")
        if not all(math.isfinite(t) for t in (session_start, force_close_time, session_close_time)):
            raise ValueError("セッション時刻が不正です")
        if not session_start < force_close_time < session_close_time:
            raise ValueError("開始、返済判断、終場の時刻順が不正です")
        self.product = PRODUCTS[symbol]
        self.observed_recovery = False
        if state is None:
            self.s = dict(version=self.VERSION, symbol=symbol, session_id=session_id,
                          start=float(session_start), end=float(force_close_time),
                          close=float(session_close_time), fill_mode=fill_mode,
                          row=-1, last_time=None, last_price=None, realized_yen=0.0,
                          normal=_new_shadow(), exit=_new_shadow(), actual=_new_actual(),
                          halted=False)
        else:
            self.s = deepcopy(state)
            expected = (self.VERSION, symbol, session_id, float(session_start),
                        float(force_close_time), float(session_close_time), fill_mode)
            found = tuple(self.s[k] for k in ("version", "symbol", "session_id", "start", "end", "close", "fill_mode"))
            if found != expected:
                raise ValueError("保存状態と運転条件が一致しません")
            self._check_positions()

    def snapshot(self) -> dict:
        """機能: 永続化用に状態を複製する。

        引数: なし。返り値: JSON保存可能な状態(dict)。
        """
        return deepcopy(self.s)

    def status(self) -> dict:
        """機能: 現在建玉と影の待機状況を返す。

        引数: なし。返り値: 表示用状態(dict)。
        """
        a = self.s["actual"]
        return dict(symbol=self.s["symbol"], session_id=self.s["session_id"], row=self.s["row"],
                    quantity=sum(a["slots"]), direction=a["direction"], entry_price=a["anchor"],
                    initial_atr=a["atr"], realized_yen=self.s["realized_yen"],
                    normal_shadow=deepcopy(self.s["normal"]), exit_shadow=deepcopy(self.s["exit"]),
                    pending_entry=deepcopy(self.s["normal"]["pending"]),
                    gate_armed=self.s["normal"]["gate_arm"] >= 0, halted=self.s["halted"])

    def positions(self) -> list[dict]:
        """機能: 現存する片方向の仮想建玉を返す。

        引数: なし。返り値: 建玉一覧(list[dict])。
        """
        a = self.s["actual"]
        if not sum(a["slots"]):
            return []
        return [dict(symbol=self.s["symbol"], direction=a["direction"], quantity=sum(a["slots"]),
                     entry_price=a["anchor"], initial_atr=a["atr"], campaign=a["campaign"])]

    def cancel_entry(self) -> None:
        """機能: 未約定の新規準備だけを取り消し、返済条件と保有影を維持する。

        引数: なし。返り値: なし(None)。
        """
        self.s["normal"]["pending"] = None
        self.s["exit"]["pending"] = None

    def _check_positions(self) -> None:
        """機能: 枚数上限と元枠の整合性を検査する。

        引数: なし。返り値: なし(None)。
        """
        a = self.s["actual"]
        if len(a["slots"]) != len(a["alive"]) or len(a["slots"]) not in (0, self.product["quantity"]):
            raise ValueError("元枠の数が不正です")
        if any(type(v) is not bool for v in a["slots"] + a["alive"]):
            raise ValueError("元枠の状態が不正です")
        if sum(a["slots"]) > self.product["cap"] or any(x and not y for x, y in zip(a["slots"], a["alive"])):
            raise ValueError("片方向保有上限又は元枠の生存条件に違反しました")
        if a["direction"] not in (-1, 0, 1) or bool(sum(a["slots"])) != bool(a["direction"]):
            raise ValueError("建玉の方向と枚数が一致しません")

    def _shadow_tick(self, sh: dict, t: float, p: float, atr: float | None,
                     direction: int, allow_prepare: bool, tight: bool) -> tuple[dict | None, bool]:
        """機能: 影の既設条件を執行し、次観測用の条件を作る。

        引数: sh(dict)影状態、t/p(float)、atr(float|None)、direction(int)、
        allow_prepare/tight(bool)。返り値: 今回の影約定と新規準備の有無(tuple)。
        """
        row, q0, tick = self.s["row"], self.product["quantity"], self.product["tick"]
        action, prepared = None, False
        plan = sh["plan"]
        if sh["direction"] and plan:
            if plan["action"]:
                action = dict(reason=plan["action"], price=p, source=plan["action_row"])
            else:
                best = None
                for reason, level, flag in plan["levels"]:
                    side = sh["direction"] if reason == 7 else -sh["direction"]
                    if level is None or (not flag and side * (p - level) < -1e-8):
                        continue
                    distance = 0.0 if flag else max(0.0, side * (level - self.s["last_price"]))
                    if best is None or distance < best - 1e-9:
                        best = distance
                        fill = p if flag or self.observed_recovery or self.s["fill_mode"] == "observed" else level
                        action = dict(reason=reason, price=fill, source=row - 1)
        elif not sh["direction"] and sh["pending"]:
            pend = sh["pending"]
            if t < pend["until"] and t < self.s["end"] - 300 and pend["direction"] * (p - pend["level"]) >= -1e-8:
                fill = p if self.s["fill_mode"] == "observed" else pend["level"]
                sh.update(direction=pend["direction"], campaign=sh["campaign"] + 1,
                          quantity=q0, anchor=fill, atr=pend["atr"], extreme=fill,
                          realized=0.0, entry_time=t, entry_row=row, split_done=False,
                          trail_floor=None, gate_arm=-1)
                action = dict(reason=20, price=fill, source=pend["row"])
                sh["pending"] = None
        if action:
            action.update(direction=sh["direction"], campaign=sh["campaign"], atr=sh["atr"], anchor=sh["anchor"])
            if action["reason"] != 20:
                quantity = max(1, sh["quantity"] // 2) if action["reason"] == 7 else sh["quantity"]
                sh["realized"] += quantity * sh["direction"] * (action["price"] - sh["anchor"])
                sh["quantity"] -= quantity
                if action["reason"] == 7:
                    sh["split_done"] = True
                if not sh["quantity"]:
                    sh.update(direction=0, last_exit=t, pending=None, gate_arm=-1)
        # ----------------------------------------
        # 現在観測に基づく条件はここから作り、次の価格観測まで執行しない。
        sh["plan"] = None
        if sh["direction"]:
            d, a, anchor = sh["direction"], sh["atr"], sh["anchor"]
            sh["extreme"] = max(sh["extreme"], p) if d > 0 else min(sh["extreme"], p)
            risk = q0 * a * (0.75 if tight else 1.0)
            floor = -risk
            stop = _rounded(anchor + (floor - sh["realized"]) / (d * sh["quantity"]), tick, -d)
            favorable = d * (sh["extreme"] - anchor)
            if favorable >= 1.5 * a:
                width = 0.75 if tight and favorable >= 3.0 * a else 3.0
                candidate = _rounded(sh["extreme"] - d * width * a, tick, -d)
                if sh["trail_floor"] is None or d * (candidate - sh["trail_floor"]) > 0:
                    sh["trail_floor"] = candidate
                if sh["gate_arm"] < 0:
                    sh["gate_arm"] = row
            split = _rounded(anchor + d * 2.0 * a, tick, d) if not sh["split_done"] and sh["quantity"] >= 2 else None
            levels = [(1, stop), (2, sh["trail_floor"]), (7, split)]
            pending_action = 0
            if t >= self.s["end"]:
                pending_action = 9
            elif sh["realized"] + sh["quantity"] * d * (p - anchor) <= floor - 1e-8:
                pending_action = 1
            elif t - sh["entry_time"] >= 360 * 60:
                pending_action = 8
            sh["plan"] = dict(action=pending_action, action_row=row,
                              levels=[(reason, level, level is not None and (d if reason == 7 else -d) * (p - level) >= -1e-8)
                                      for reason, level in levels])
        else:
            pend = sh["pending"]
            if pend and (t >= pend["until"] or direction != pend["direction"]):
                sh["pending"] = None
                pend = None
            if pend:
                d = pend["direction"]
                pend["extreme"] = min(pend["extreme"], p) if d > 0 else max(pend["extreme"], p)
                level = _rounded(pend["extreme"] + d * 0.25 * pend["atr"], tick, d)
                if level != pend["level"]:
                    pend.update(level=level, row=row)
            cooldown = sh["last_exit"] is None or t >= sh["last_exit"] + 300
            if (allow_prepare and not sh["pending"] and direction and cooldown
                    and t >= self.s["start"] + 1200 and t < self.s["end"] - 300
                    and atr is not None and math.isfinite(atr) and atr > 0):
                a = max(atr, tick * 2)
                sh["pending"] = dict(direction=direction, atr=a, level=_rounded(p + direction * 0.25 * a, tick, direction),
                                     extreme=p, until=t + 300, row=row, prepare_row=row,
                                     prepare_id=sh["prepare_count"])
                sh["prepare_count"] += 1
                prepared = True
        return action, prepared

    def _event(self, event: str, quantity: int, price: float, reason: int,
               source: int, t: float, direction: int, pnl: float = 0.0,
               custom_reason: str | None = None) -> dict:
        """機能: 保存対象となる仮想約定記録を作る。

        引数: event/custom_reason(str|None)、quantity/reason/source/direction(int)、
        price/t/pnl(float)。返り値: 約定記録(dict)。
        """
        a = self.s["actual"]
        return dict(session_id=self.s["session_id"], symbol=self.s["symbol"], strategy="E01",
                    event=event, direction=direction, quantity=quantity, price=price,
                    reason=custom_reason or REASONS[reason], reason_code=reason,
                    campaign=a["campaign"], row=self.s["row"], source_row=source,
                    timestamp=t, initial_atr=a["atr"], entry_price=a["anchor"],
                    realized_points=pnl, realized_yen=pnl * self.product["point_value"],
                    position_after=sum(a["slots"]), position_direction=a["direction"],
                    fill_mode="observed_recovery" if self.observed_recovery else ("observed" if reason == 90 else self.s["fill_mode"]))

    def _close(self, selected: list[int], price: float, reason: int, source: int,
               t: float, retire: bool = False, custom_reason: str | None = None) -> list[dict]:
        """機能: 指定した元枠だけを返済し、現金損益を加算する。

        引数: selected(list[int])、price/t(float)、reason/source(int)、retire(bool)、
        custom_reason(str|None)。返り値: 約定があれば一件の記録(list[dict])。
        """
        a = self.s["actual"]
        quantity = sum(a["slots"][i] for i in selected)
        d = a["direction"]
        for i in selected:
            a["slots"][i] = False
            if retire:
                a["alive"][i] = False
        pnl = quantity * d * (price - a["anchor"])
        a["realized"] += pnl
        self.s["realized_yen"] += pnl * self.product["point_value"]
        a["barrier"] = self.s["row"]
        if not sum(a["slots"]):
            a.update(direction=0, pending=None, budget=None)
        return [self._event("返済", quantity, price, reason, source, t, d, pnl, custom_reason)] if quantity else []

    def on_tick(self, timestamp: float, price: float, atr: float | None, direction: int,
                adverse: int = 0, adverse_source: int | None = None, allow_entry: bool = True,
                input_index: int | None = None, observed_recovery: bool = False) -> list[dict]:
        """機能: 一つの価格観測を進め、前観測で準備した仮想注文を判定する。

        引数: timestamp/price(float)、atr(float|None)、direction/adverse(int)、
        adverse_source/input_index(int|None、銘柄別観測連番)、allow_entry(bool)。
        observed_recovery(bool) は欠測後の既設返済を観測価格で評価する指定。
        返り値: 新規・返済の記録(list[dict])。未確定・未来の指標を渡してはならない。
        """
        t, p = float(timestamp), float(price)
        self.observed_recovery = observed_recovery
        if not math.isfinite(t) or not math.isfinite(p) or p <= 0 or direction not in (-1, 0, 1) or adverse not in (-1, 0, 1):
            raise ValueError("観測又は方向が不正です")
        if self.s["last_time"] is not None and t < self.s["last_time"]:
            raise ValueError("観測時刻が逆転しています")
        row = self.s["row"] + 1
        if input_index is not None and input_index != row:
            raise ValueError("特徴量と注文器の観測連番が一致しません")
        source = row if adverse_source is None else int(adverse_source)
        if source < -1 or source > row or (adverse and source < 0):
            raise ValueError("悪化根拠の観測連番が不正です")
        if t >= self.s["close"] and self.positions():
            raise ValueError("終場を越えた未返済があります。過去価格で約定させず異常処理してください")
        self.s["row"] = row
        allowed = allow_entry and not self.s["halted"] and t < self.s["close"]
        # データ品質遮断は未約定の新規条件を直ちに取り消す。返済条件は維持する。
        if not allowed:
            self.s["normal"]["pending"] = None
            self.s["exit"]["pending"] = None
        current_direction = direction if allowed else 0
        _, prepared = self._shadow_tick(self.s["normal"], t, p, atr, current_direction, allowed, False)
        action, _ = self._shadow_tick(self.s["exit"], t, p, atr, current_direction, prepared, True)
        a, events, acted = self.s["actual"], [], False
        if action and action["reason"] == 20:
            if a["direction"]:
                raise ValueError("未返済のまま新しい組を開始しようとしました")
            a = _new_actual()
            a.update(direction=action["direction"], campaign=action["campaign"], anchor=action["price"],
                     atr=action["atr"], slots=[True] * self.product["quantity"],
                     alive=[True] * self.product["quantity"], barrier=row, entry_row=row, entry_time=t)
            self.s["actual"] = a
            events.append(self._event("新規", self.product["quantity"], action["price"], 20, action["source"], t, a["direction"]))
            acted = True
        elif action and a["direction"]:
            a["pending"] = None
            selected = list(range(self.product["quantity"] // 2 if action["reason"] == 7 else self.product["quantity"]))
            events += self._close(selected, action["price"], action["reason"], action["source"], t, retire=True)
            acted = True
        elif a["direction"] and a["budget"] is not None:
            events += self._close(list(range(self.product["quantity"])), p, 32, a["budget"], t, retire=True)
            acted = True
        elif a["direction"] and a["pending"]:
            pending = a["pending"]
            a["pending"] = None
            events += self._close(pending["slots"], p, 30, pending["row"], t)
            a["reductions"] += 1
            acted = True
        # ----------------------------------------
        # 通常影の初到達より後の新しい悪化情報だけを、次観測の減量注文に使う。
        if a["direction"]:
            equity = a["realized"] + sum(a["slots"]) * a["direction"] * (p - a["anchor"])
            if equity <= -self.product["quantity"] * a["atr"] and a["budget"] is None:
                a["budget"] = row
                a["pending"] = None
            normal = self.s["normal"]
            if (not acted and a["pending"] is None and a["budget"] is None and a["reductions"] < 1
                    and normal["direction"] and normal["campaign"] == a["campaign"]
                    and normal["gate_arm"] >= 0 and source > normal["gate_arm"]
                    and adverse == -a["direction"] and source > a["barrier"]):
                count = min(sum(a["alive"]) - 1, max(1, int(0.5 * sum(a["alive"]))))
                selected = [i for i, value in enumerate(a["slots"]) if value and a["alive"][i]][:count]
                if selected:
                    a["pending"] = dict(slots=selected, row=row, evidence=source)
        self.s.update(last_time=t, last_price=p)
        self._check_positions()
        return events

    def force_flatten(self, timestamp: float, price: float, reason: str = "停止時返済") -> list[dict]:
        """機能: 利用可能な現在観測価格で建玉を返済し、新規準備を取り消す。

        引数: timestamp/price(float、実際に観測できた時刻・価格)、reason(str)。
        返り値: 仮想返済記録(list[dict])。古い値を現在の約定とみなしてはならない。
        """
        t, p = float(timestamp), float(price)
        if not math.isfinite(t) or not math.isfinite(p) or p <= 0:
            raise ValueError("返済用の現在観測が不正です")
        if t >= self.s["close"] and self.positions():
            raise ValueError("終場後に前セッション建玉を遡及返済できません")
        if self.s["last_time"] is not None and t < self.s["last_time"]:
            raise ValueError("返済観測が過去です")
        events = self._close(list(range(len(self.s["actual"]["slots"]))), p, 90,
                             self.s["row"], t, retire=True, custom_reason=reason)
        for key in ("normal", "exit"):
            old = self.s[key]
            fresh = _new_shadow()
            fresh.update(campaign=old["campaign"], last_exit=t, prepare_count=old["prepare_count"])
            self.s[key] = fresh
        self.s.update(last_time=t, last_price=p)
        self._check_positions()
        return events
