"""金融前の一般状態器。幅は外部の当時情報Policyから受け、固定研究値を内蔵しない。"""
from __future__ import annotations

from dataclasses import dataclass, field
import math


@dataclass(frozen=True)
class Quote:
    """採用原行と正常BBO・元条件が公開される観測点を表す。"""
    index: int
    time: float
    bid: float
    ask: float
    phase: str
    observation: bool = True

    @property
    def valid(self) -> bool:
        """有限で順序の正しいBBOかを返す。

        引数: self(Quote)。返り値: bool。
        """
        return math.isfinite(self.bid) and math.isfinite(self.ask) and 0 < self.bid < self.ask

    def exit_price(self, side: int) -> float:
        """既存玉を返済する側の気配を返す。

        引数: self(Quote)、side(int)。返り値: float。
        """
        return self.bid if side == 1 else self.ask

    def entry_price(self, side: int) -> float:
        """新規を約定する側の気配を返す。

        引数: self(Quote)、side(int)。返り値: float。
        """
        return self.ask if side == 1 else self.bid


@dataclass(frozen=True)
class Policy:
    """根拠が確定してから外部で渡す価格幅。各玉の発注判断時に固定する。"""
    grid_step: float
    cover_activation: float
    cover_trail: float
    cover_stop: float | None = None

    def validate(self) -> None:
        """未知・非有限・不正な値幅を拒否する。

        引数: self(Policy)。返り値: None。不正値は例外。
        """
        if not math.isfinite(self.grid_step) or self.grid_step <= 0 or not math.isfinite(self.cover_trail) or self.cover_trail <= 0:
            raise ValueError("段間隔と追尾幅は有限正値が必要")
        if not math.isfinite(self.cover_activation) or self.cover_activation < 0:
            raise ValueError("起動幅は有限非負が必要")
        if self.cover_stop is not None and (not math.isfinite(self.cover_stop) or self.cover_stop <= 0):
            raise ValueError("比較用の損切り幅は有限正値が必要")


@dataclass(frozen=True)
class Config:
    """数量・境界・再配置だけを定め、訓練資料から未確定の幅は含めない。"""
    force_close: float
    start: float
    side_cap: int = 10
    main_wanted: int = 10
    multiplier: float = 100
    main_target: float = 100
    main_stop: float | None = None
    main_interval: float = 60
    main_end: str = "flatten_cover"
    boundary: str = "carry"
    rearm: str = "fixed_recross"
    profit_only_after_activation: bool = False
    use_cover: bool = True
    immediate_cover_trail: bool = False


@dataclass
class Order:
    """発注確定予約。未発火のstop段はOrderに含めない。"""
    id: str
    action: str
    parent: str
    role: str
    side: int
    quantity: int
    decision_index: int
    decision_time: float
    reason: str
    target: str | None = None
    slot: int | None = None
    policy: Policy | None = None


@dataclass
class Lot:
    """主とカバーを別IDで保持し、実建値と価格追尾を混ぜない。"""
    id: str
    parent: str
    role: str
    side: int
    quantity: int
    entry: float
    entry_index: int
    entry_time: float
    policy: Policy
    slot: int | None = None
    best: float = 0
    worst: float = 0
    active: bool = False
    floor: float | None = None
    trail_peak: float | None = None
    realized: float = 0


@dataclass
class Slot:
    """親に紐づいた未発火stop段と再配置状態。数量枠は発火まで拘束しない。"""
    number: int
    threshold: float
    state: str = "armed"
    lot: str | None = None
    pending: str | None = None
    last_close_index: int = -1


@dataclass
class Parent:
    """一つの主信号の所有範囲。他親の玉と相殺・転用しない。"""
    id: str
    side: int
    quantity: int
    phase: str
    entry: float | None = None
    grid_anchor: float | None = None
    main_lot: str | None = None
    ending: bool = False
    slots: list[Slot] = field(default_factory=list)


class Engine:
    """全原行の口座状態から次原行注文を作る。将来到達ラベルを受け取らない。"""

    def __init__(self, config: Config, skip_unchanged: bool = True):
        """空口座と初期0のリスク基準を作る。

        引数: config(Config)、skip_unchanged(bool)は同値行省略。返り値: None。
        """
        if config.main_end not in ("flatten_cover", "manage_cover") or config.boundary not in ("carry", "flatten"):
            raise ValueError("未定義の親終了又は境界方針")
        if config.rearm not in ("none", "fixed_recross", "moving_stop"):
            raise ValueError("未定義の再配置方針")
        if config.side_cap <= 0 or config.main_wanted <= 0 or config.force_close <= config.start:
            raise ValueError("数量又は場時計が不正")
        self.config = config
        self.skip_unchanged = skip_unchanged
        self.skipped_rows = 0
        self.parents: dict[str, Parent] = {}
        self.active_parents: dict[str, Parent] = {}
        self.lots: dict[str, Lot] = {}
        self.active_lots: dict[str, Lot] = {}
        self.pending: list[Order] = []
        self.events, self.decisions, self.rejections = [], [], []
        self.cover_capacity = {}
        self.cover_capacity_rows = 0
        self.last_cover_capacity_index = -1
        self.last_cover_capacity_keys = []
        self.edges: dict[str, tuple[bool, bool]] = {}
        self.sequence = 0
        self.last_index = -1
        self.last_time = config.start
        self.last_main_decision: dict[str,float] = {}
        self.last_phase = None
        self.boundary_pending = False
        self.realized = 0.
        self.peak_equity = 0.
        self.minimum_equity = 0.
        self.max_drawdown = 0.
        self.risk_points = []
        self.last_mark = {"index":-1,"time":config.start,"realized":0.,"unrealized":0.,"equity":0.,"long":0,"short":0,"long_reserved":0,"short_reserved":0}
        self.peak_at = self.last_mark.copy()
        self.minimum_at = self.last_mark.copy()
        self.drawdown_from = self.last_mark.copy()
        self.drawdown_to = self.last_mark.copy()
        self.long_seconds = self.short_seconds = 0.
        self.net_abs_seconds = 0.
        self.maximum_quantities = {k:0 for k in ("held_buy","held_sell","occupied_buy","occupied_sell","gross_held","net_abs")}
        self.last_normal: Quote | None = None
        self.cancellations = []
        self.finished = False

    def identifier(self, prefix: str) -> str:
        """口座内で一意な注文・親IDを発行する。

        引数: self(Engine)、prefix(str)。返り値: str。
        """
        self.sequence += 1
        return f"{prefix}{self.sequence:06d}"

    def held(self, side: int) -> int:
        """当口座の主・カバーの実保有を合計する。

        引数: self(Engine)、side(int)。返り値: int。
        """
        return sum(l.quantity for l in self.active_lots.values() if l.side == side)

    def reserved(self, side: int) -> int:
        """発注確定した新規予約だけを数える。

        引数: self(Engine)、side(int)。返り値: int。
        """
        return sum(o.quantity for o in self.pending if o.action == "new" and o.side == side)

    def free(self, side: int) -> int:
        """返済予定を先に控除せず方向空きを返す。

        引数: self(Engine)、side(int)。返り値: int。
        """
        return max(0, self.config.side_cap-self.held(side)-self.reserved(side))

    def close_pending(self, lot: Lot) -> bool:
        """対象玉の既発注返済があるかを返す。

        引数: self(Engine)、lot(Lot)。返り値: bool。
        """
        return any(o.action == "close" and o.target == lot.id for o in self.pending)

    def record_mark(self, q: Quote) -> None:
        """約定前/逐次約定後に全玉の清算時価と極値を記録する。

        引数: self(Engine)、q(Quote)。返り値: None。
        """
        unrealized = 0.
        for lot in self.active_lots.values():
            if not lot.quantity:
                continue
            gain = lot.side*(q.exit_price(lot.side)-lot.entry)
            lot.best, lot.worst = max(lot.best, gain), min(lot.worst, gain)
            unrealized += gain*lot.quantity*self.config.multiplier
        equity = self.realized+unrealized
        prior_peak,prior_minimum,prior_drawdown = self.peak_equity,self.minimum_equity,self.max_drawdown
        changed = not self.risk_points or equity > self.peak_equity or equity < self.minimum_equity or self.peak_equity-equity > self.max_drawdown
        self.peak_equity = max(self.peak_equity, equity)
        self.minimum_equity = min(self.minimum_equity, equity)
        self.max_drawdown = max(self.max_drawdown, self.peak_equity-equity)
        point = {"index":q.index,"time":q.time,"realized":self.realized,"unrealized":unrealized,"equity":equity,
                 "long":self.held(1),"short":self.held(-1),"long_reserved":self.reserved(1),"short_reserved":self.reserved(-1)}
        quantities = {"held_buy":point["long"],"held_sell":point["short"],"occupied_buy":point["long"]+point["long_reserved"],
                      "occupied_sell":point["short"]+point["short_reserved"],"gross_held":point["long"]+point["short"],"net_abs":abs(point["long"]-point["short"])}
        self.maximum_quantities = {key:max(self.maximum_quantities[key],value) for key,value in quantities.items()}
        if q.index > self.last_index and self.last_normal is not None:
            point.update(proxy=True,quote_index=self.last_normal.index,quote_time=self.last_normal.time,quote_age=q.time-self.last_normal.time)
        self.last_mark = point
        if equity > prior_peak:
            self.peak_at = point.copy()
        if equity < prior_minimum:
            self.minimum_at = point.copy()
        if prior_peak-equity > prior_drawdown:
            self.drawdown_from,self.drawdown_to = self.peak_at.copy(),point.copy()
        if changed:
            self.risk_points.append(point)

    def request_close(self, lot: Lot, q: Quote, reason: str) -> None:
        """所有IDの残玉全量だけを次正常板返済へ予約する。

        引数: self(Engine)、lot(Lot)、q(Quote)、reason(str)。返り値: None。
        """
        if lot.quantity <= 0 or self.close_pending(lot):
            return
        order = Order(self.identifier("O"),"close",lot.parent,lot.role,-lot.side,lot.quantity,q.index,q.time,reason,lot.id,lot.slot)
        self.pending.append(order)
        self.decisions.append(order)

    def fill_pending(self, q: Quote) -> None:
        """前原行までに発注済みの予約を次正常BBOで約定する。

        引数: self(Engine)、q(Quote)。返り値: None。境界後でも既発注を消さない。
        """
        due = [o for o in self.pending if o.decision_index < q.index]
        for order in due:
            self.pending.remove(order)
            parent = self.parents[order.parent]
            price = q.entry_price(order.side)
            if order.action == "new":
                assert order.policy is not None
                lot = Lot(order.id,parent.id,order.role,order.side,order.quantity,price,q.index,q.time,order.policy,order.slot)
                self.lots[lot.id] = lot
                self.active_lots[lot.id] = lot
                if order.role == "main":
                    parent.entry, parent.main_lot = price, lot.id
                    parent.grid_anchor = (q.bid+q.ask)/2
                    parent.slots = [Slot(i,parent.grid_anchor-parent.side*order.policy.grid_step*i) for i in range(1,order.quantity+1)]
                else:
                    slot = parent.slots[order.slot-1]
                    assert slot.pending == order.id and slot.lot is None
                    slot.pending, slot.lot = None, lot.id
                    if self.config.immediate_cover_trail:
                        lot.active = True
                        lot.trail_peak = lot.side*(q.exit_price(lot.side)-lot.entry)
                        lot.floor = lot.trail_peak-lot.policy.cover_trail
                gross = 0.
            else:
                lot = self.lots[order.target]
                assert lot.parent == order.parent and lot.quantity >= order.quantity
                gross = lot.side*(price-lot.entry)*order.quantity*self.config.multiplier
                lot.quantity -= order.quantity
                lot.realized += gross
                self.realized += gross
                if lot.quantity == 0:
                    del self.active_lots[lot.id]
                if lot.role == "cover" and lot.quantity == 0:
                    slot = parent.slots[lot.slot-1]
                    slot.lot, slot.last_close_index = None,q.index
                    slot.state = {"none":"off","fixed_recross":"wait_inside","moving_stop":"seed"}[self.config.rearm]
            self.events.append({"order":order,"fill_index":q.index,"fill_time":q.time,"price":price,"gross":gross})
            self.record_mark(q)
        assert all(self.held(s)+self.reserved(s) <= self.config.side_cap for s in (-1,1))

    def cover_exits(self, q: Quote) -> None:
        """各カバーの実建値・最高順行から起動済み追尾を優先評価する。

        引数: self(Engine)、q(Quote)。返り値: None。損益>0再条件は明示variantだけ。
        """
        for lot in self.active_lots.values():
            if lot.role != "cover" or lot.quantity <= 0 or self.close_pending(lot):
                continue
            gain = lot.side*(q.exit_price(lot.side)-lot.entry)
            threshold = lot.policy.cover_activation
            if self.config.immediate_cover_trail:
                assert lot.trail_peak is not None
                lot.trail_peak = max(lot.trail_peak,gain)
            elif (gain > 0 if threshold == 0 else gain >= threshold):
                lot.active = True
            if lot.active:
                candidate = lot.trail_peak-lot.policy.cover_trail if self.config.immediate_cover_trail else max(0.,lot.best-lot.policy.cover_trail)
                lot.floor = max(lot.floor if lot.floor is not None else -math.inf,candidate)
                if gain <= lot.floor and (not self.config.profit_only_after_activation or gain > 0):
                    self.request_close(lot,q,"cover_trail")
                    continue
            if lot.policy.cover_stop is not None and gain <= -lot.policy.cover_stop:
                self.request_close(lot,q,"cover_stop")

    def cover_entries(self, q: Quote, policy: Policy) -> None:
        """親開始順と段順で発火したカバーを空き枠まで予約する。

        引数: self(Engine)、q(Quote)、policy(Policy)。返り値: None。
        """
        self.last_cover_capacity_keys = []
        if not self.config.use_cover:
            return
        for parent in self.active_parents.values():
            if parent.ending or parent.main_lot is None or self.lots[parent.main_lot].quantity == 0 or self.close_pending(self.lots[parent.main_lot]):
                continue
            mark = (q.bid+q.ask)/2
            for slot in parent.slots:
                if slot.pending or slot.lot or slot.state == "off" or q.index <= slot.last_close_index:
                    continue
                if slot.state == "wait_inside":
                    if parent.side*(mark-slot.threshold) > 0:
                        slot.state = "armed"
                    continue
                if slot.state == "seed":
                    slot.threshold = mark-parent.side*policy.grid_step
                    slot.state = "armed"
                    continue
                if parent.side*(mark-slot.threshold) <= 0 and self.free(-parent.side) == 0:
                    key = (parent.id,slot.number)
                    if key not in self.cover_capacity:
                        self.cover_capacity[key] = {"parent":parent.id,"slot":slot.number,"side":-parent.side,"rows":0,"first_index":q.index,"first_time":q.time}
                    self.last_cover_capacity_keys.append(key)
                    self.record_capacity(key,q)
                elif parent.side*(mark-slot.threshold) <= 0:
                    order = Order(self.identifier("O"),"new",parent.id,"cover",-parent.side,1,q.index,q.time,"cover_stop_entry",slot=slot.number,policy=policy)
                    self.pending.append(order)
                    self.decisions.append(order)
                    slot.pending, slot.state = order.id,"occupied"

    def record_capacity(self, key: tuple[str,int], q: Quote) -> None:
        """変化しない板を省略した原行も含め、同じ枠不足を一貫して数える。

        引数: self(Engine)、key(tuple[str,int])、q(Quote)。返り値: None。
        """
        record = self.cover_capacity[key]
        record.update(rows=record["rows"]+1,last_index=q.index,last_time=q.time)
        if self.last_cover_capacity_index != q.index:
            self.cover_capacity_rows += 1
            self.last_cover_capacity_index = q.index

    def step(self, q: Quote, long_signal: bool, short_signal: bool, policy: Policy) -> None:
        """一原行の約定・退出・新主・カバーを固定優先順で処理する。

        引数: self(Engine)、q(Quote)、long_signal/short_signal(bool)、policy(Policy)。
        返り値: None。入力signalとPolicyは当時の情報だけで外部生成する。
        """
        policy.validate()
        if self.finished:
            raise ValueError("終了済み口座を再開しない")
        if q.index <= self.last_index or q.time < self.last_time:
            raise ValueError("原行順又は価格時計が巻き戻った")
        dt = q.time-self.last_time
        self.long_seconds += dt*self.held(1)
        self.short_seconds += dt*self.held(-1)
        self.net_abs_seconds += dt*abs(self.held(1)-self.held(-1))
        self.last_time,self.last_index = q.time,q.index
        boundary = self.last_phase is not None and q.phase != self.last_phase
        if boundary and self.config.boundary == "flatten":
            self.boundary_pending = True
        self.last_phase = q.phase
        edge = 0
        if q.observation:
            previous = self.edges.get(q.phase,(False,False))
            self.edges[q.phase] = (bool(long_signal),bool(short_signal))
            if long_signal != short_signal:
                edge = 1 if long_signal and not previous[0] else -1 if short_signal and not previous[1] else 0
        if not q.valid:
            return
        previous_quote = self.last_normal
        self.last_normal = q
        needs_rearm = any(slot.state == "seed" or (slot.state == "wait_inside" and parent.side*((q.bid+q.ask)/2-slot.threshold) > 0)
                          for parent in self.active_parents.values() if not parent.ending for slot in parent.slots)
        if (self.skip_unchanged and previous_quote is not None and q.bid == previous_quote.bid and q.ask == previous_quote.ask
                and not q.observation and not self.pending and not self.boundary_pending and q.time < self.config.force_close and not needs_rearm):
            self.skipped_rows += 1
            for key in self.last_cover_capacity_keys:
                self.record_capacity(key,q)
            self.last_mark = {**self.last_mark,"index":q.index,"time":q.time}
            return
        self.record_mark(q)
        self.fill_pending(q)
        # ----------------------------------------
        # 全返済と親出口が最優先。他親の玉には親出口を適用しない。
        flatten = q.time >= self.config.force_close or self.boundary_pending
        if flatten:
            self.last_cover_capacity_keys = []
            for parent in self.active_parents.values():
                parent.ending = True
                for slot in parent.slots:
                    slot.state = "off"
            for lot in self.active_lots.values():
                self.request_close(lot,q,"session_end" if q.time >= self.config.force_close else "phase_boundary")
        else:
            for parent in self.active_parents.values():
                if parent.main_lot is None:
                    continue
                main = self.lots[parent.main_lot]
                gain = parent.side*(q.exit_price(parent.side)-main.entry)
                stop = self.config.main_stop is not None and gain <= -self.config.main_stop
                if main.quantity > 0 and (gain >= self.config.main_target or stop):
                    parent.ending = True
                    self.request_close(main,q,"main_stop" if stop else "main_target")
                if parent.ending and self.config.main_end == "flatten_cover":
                    for lot in self.active_lots.values():
                        if lot.parent == parent.id and lot.role == "cover":
                            self.request_close(lot,q,"main_end_cover")
            self.cover_exits(q)
        # ----------------------------------------
        # 新主を先に発注確定し、残枠へカバーを配分する。返済予約は枠を空けない。
        if edge and not flatten:
            reason = "interval" if q.time-self.last_main_decision.get(q.phase,-math.inf) < self.config.main_interval else "capacity" if self.free(edge) == 0 else ""
            if reason:
                self.rejections.append({"index":q.index,"time":q.time,"phase":q.phase,"side":edge,"reason":reason})
            else:
                quantity = min(self.config.main_wanted,self.free(edge))
                parent = Parent(self.identifier("P"),edge,quantity,q.phase)
                self.parents[parent.id] = parent
                self.active_parents[parent.id] = parent
                order = Order(self.identifier("O"),"new",parent.id,"main",edge,quantity,q.index,q.time,"source_edge",policy=policy)
                self.pending.append(order)
                self.decisions.append(order)
                self.last_main_decision[q.phase] = q.time
        if not flatten:
            self.cover_entries(q,policy)
        if self.boundary_pending and not self.held(1) and not self.held(-1) and not self.pending:
            self.boundary_pending = False
        occupied = {lot.parent for lot in self.active_lots.values()} | {order.parent for order in self.pending}
        self.active_parents = {key: parent for key, parent in self.active_parents.items() if key in occupied}
        self.record_mark(q)
        assert all(self.held(s)+self.reserved(s) <= self.config.side_cap for s in (-1,1))

    def finish(self, end: float, maximum_age: float = 360) -> dict:
        """場末の既知タイマーで最終既知板による明示的な端末精算代理を行う。

        引数: self(Engine)、end/maximum_age(float)。返り値: dictは代理精算/未決の証跡。
        通常約定と区別し、古すぎる板では玉を消さず異常状態を返す。
        """
        if self.finished or end < self.last_time:
            raise ValueError("二重終了又は時計巻戻り")
        self.finished = True
        dt = end-self.last_time
        self.long_seconds += dt*self.held(1)
        self.short_seconds += dt*self.held(-1)
        self.net_abs_seconds += dt*abs(self.held(1)-self.held(-1))
        self.last_time = end
        quote = self.last_normal
        age = end-quote.time if quote is not None else math.inf
        for order in self.pending:
            if order.action == "new":
                self.cancellations.append({"order":order,"time":end,"reason":"terminal_unfilled_new"})
        self.pending = [o for o in self.pending if o.action == "close"]
        if quote is None or age > maximum_age:
            return {"completed":False,"reason":"terminal_quote_stale","age":age,"long":self.held(1),"short":self.held(-1)}
        proxy = Quote(self.last_index+1,end,quote.bid,quote.ask,quote.phase,False)
        self.record_mark(proxy)
        prior_closes = {o.target:o.id for o in self.pending}
        self.pending = []
        for lot in list(self.active_lots.values()):
            order = Order(self.identifier("O"),"close",lot.parent,lot.role,-lot.side,lot.quantity,proxy.index,end,"terminal_proxy",lot.id,lot.slot)
            price = quote.exit_price(lot.side)
            gross = lot.side*(price-lot.entry)*lot.quantity*self.config.multiplier
            lot.quantity = 0
            lot.realized += gross
            self.realized += gross
            del self.active_lots[lot.id]
            self.decisions.append(order)
            self.events.append({"order":order,"fill_index":None,"fill_time":end,"price":price,"gross":gross,
                                "proxy":True,"quote_index":quote.index,"quote_time":quote.time,"quote_age":age,
                                "replaced_pending_close":prior_closes.get(lot.id)})
            self.record_mark(proxy)
        self.active_parents = {}
        for parent in self.parents.values():
            parent.ending = True
            for slot in parent.slots:
                slot.state,slot.pending,slot.lot = "off",None,None
        return {"completed":True,"proxy":True,"time":end,"quote_index":quote.index,"quote_time":quote.time,"age":age,
                "cancelled_new":len(self.cancellations),"long":self.held(1),"short":self.held(-1)}
