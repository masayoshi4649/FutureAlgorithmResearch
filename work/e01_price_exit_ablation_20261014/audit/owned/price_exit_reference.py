"""旧独立参照を保ち、反対価格票による退出だけのON/OFFを分離する。"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
import math
from price_vote_reference import Geometry, supports, spread_admission


@dataclass(frozen=True)
class Row:
    """
    機能: 純人工の当行気配・Last・両市場票・timerを保持する。
    引数: clock/last/bid/ask(float)、normal/quiet(bool)、own/other(dict) は当行人工値。
    返り値: Row は未来の気配を持たない不変観測。
    """
    clock: float
    last: float
    bid: float
    ask: float
    normal: bool
    own: dict
    other: dict
    quiet: bool = False


class Reference:
    """
    機能: 独立小人工で12種の参加/利益保護/場停止を逐次処理する。
    引数: symbol/mode/exit_id(str)、start/end(float) は固定商品/種類/場内期間。
    返り値: Reference は紙上/予約/実玉を別々に持つ状態。実データを参照しない。
    """

    def __init__(self, symbol: str, mode: str, exit_id: str, start: float = 0., end: float = 1000., price_exit_enabled: bool = True):
        """
        機能: 新しい純口座を場の開始から初期化する。
        引数: symbol/mode/exit_id(str)、start/end(float)、price_exit_enabled(bool) は商品/入口/出口/期間/反票退出。
        返り値: None。上限・料金・全実量を仕様の10/20へ固定する。
        """
        assert symbol in ('TOPIX', 'NK225') and mode in ('ORIGIN', 'PULL', 'BREAK', 'ADAPTIVE')
        assert exit_id in ('TARGET', 'TIGHT_TRAIL', 'WIDE_TRAIL')
        self.symbol, self.mode, self.exit_id, self.start, self.end = symbol, mode, exit_id, start, end
        self.price_exit_enabled = price_exit_enabled
        self.cap = 10 if symbol == 'TOPIX' else 20
        self.mult = 1000 if symbol == 'TOPIX' else 10
        self.tick = .5 if symbol == 'TOPIX' else 10.
        self.fee_unit = Decimal('41.8') if symbol == 'TOPIX' else Decimal('11')
        self.paper = None; self.geometry = None; self.pending = None; self.held = None; self.queue = None
        self.realized = Decimal(0); self.cash = Decimal(0); self.paid = 0
        self.scene_notional = None; self.scene_block = False
        self.timer_source = None; self.cid = 0; self.uid = 0
        self.blocked_current = False
        self.orders = []; self.publications = []; self.parents = []; self.curve = []; self.events = []
        self.attempts = []
        self.mark_bid = self.mark_ask = Decimal(0)

    def charge(self, quantity: int) -> int:
        """
        機能: 純参照の一注文料金だけをDecimalで切捨てする。
        引数: quantity(int) は当該実注文枚数。
        返り値: int は円料金。注文同士をまとめて切捨てしない。
        """
        return int((quantity * self.fee_unit).to_integral_value(rounding=ROUND_FLOOR))

    def liquidation(self) -> Decimal:
        """
        機能: 現在実玉の返済側markと残玉返済料から全場netを求める。
        引数: なし。当時markと実heldだけを使用する。
        返り値: Decimal は全場純清算。未知当行で未来markを補わない。
        """
        value = self.cash * self.mult - self.paid
        if self.held:
            h = self.held; mark = self.mark_bid if h['side'] > 0 else self.mark_ask
            value += Decimal(h['side'] * h['q']) * mark * self.mult - self.charge(h['q'])
        return value

    def reset_geometry(self, row: int, point: Row, review_consumed: bool = False) -> None:
        """
        機能: 紙上親のPを保持し、返済/失効後に新しいflat形状を作る。
        引数: row(int)、point(Row)、review_consumed(bool) は当時観測と公開審査消費のresetか。
        返り値: None。実Nや実UIDへ新しいpaper Pを上書きしない。
        """
        if self.paper:
            value = point.last if point.normal and (review_consumed or not self.blocked_current) and math.isfinite(point.last) and point.last > 0 else math.nan
            self.geometry = Geometry(self.paper['side'], self.paper['P'], row, value)
        else:
            self.geometry = None

    def return_all(self, row: int, source: int, point: Row, reason: str) -> None:
        """
        機能: 独立予約UIDの全残玉を当行の正BBOで返済する。
        引数: row/source(int)、point(Row)、reason(str) は約定/判断行・気配・理由。
        返り値: None。親netを確定し、その後の再参加anchorを新設する。
        """
        h = self.held; assert h and source < row
        price = point.bid if h['side'] > 0 else point.ask
        cost = self.charge(h['q']); self.cash += Decimal(h['side'] * h['q']) * Decimal(str(price)); self.paid += cost
        self.orders.append(dict(row=row, source=source, cid=h['cid'], paper=h['paper'], uid=-1,
                                target_uid=h['uid'], side=-h['side'], q=h['q'], price=price, new=False, reason=reason, fee=cost))
        net = self.cash * self.mult - self.paid - h['base']
        self.parents.append(dict(cid=h['cid'], paper=h['paper'], uid=h['uid'], N=h['N'], net=float(net),
                                 initial_q=h['q'], entry=h['row'], close=row))
        self.realized = self.cash * self.mult - self.paid; self.held = None; self.queue = None
        self.reset_geometry(row, point)

    def admit(self, row: int, point: Row, origin: bool) -> None:
        """
        機能: 当時支持/気配費用/形状だけで一回の新規FAKを受理予約する。
        引数: row(int)、point(Row)、origin(bool) は当時行/正常気配/紙上初回か。
        返り値: None。未来firstquoteを使って公開maskを拒否しない。
        """
        if not self.paper:
            return
        if not origin and (self.held or self.pending or self.queue or self.scene_block or point.quiet or self.blocked_current or not point.normal):
            return
        s = self.paper['side']; strong = supports(point.own, point.other, s, .75)
        shape = origin
        if not origin and self.geometry:
            shape = self.geometry.observe(row, point.last, point.normal, self.mode, strong)['entry']
        if not shape:
            return
        price = point.ask if s > 0 else point.bid
        allowed = (not (self.held or self.pending or self.queue or self.scene_block or point.quiet or self.blocked_current) and
                   self.start + 300 <= point.clock < self.end - 300 and point.normal and
                   supports(point.own, point.other, s) and
                   spread_admission(price, point.bid, point.ask, self.cap, self.mult, 2 * self.charge(self.cap)))
        self.attempts.append(dict(row=row, paper=self.paper['cid'], accepted=allowed))
        self.reset_geometry(row, point, review_consumed=True)
        if not allowed:
            return
        allowance = int(strong); cap = price + s * allowance * self.tick
        self.pending = dict(cid=self.cid, paper=self.paper['cid'], side=s, q=self.cap,
                            source=row, cap=cap, allowance=allowance)
        self.cid += 1
        self.publications.append(dict(row=row, cid=self.pending['cid'], paper=self.paper['cid'], side=s, cap=cap, allowance=allowance))

    def step(self, row: int, point: Row, paper_events: list[dict]) -> None:
        """
        機能: timer→既返済→既FAK→紙上→親/場制御の先後で一観測だけを処理する。
        引数: row(int)、point(Row)、paper_events(list[dict]) は当行人工資料。
        返り値: None。当行判断を同じ行で実返済せず次normalへ予約する。
        """
        scheduled = point.quiet or point.clock >= self.end
        self.blocked_current = scheduled or self.timer_source is not None or self.scene_block
        if scheduled and self.timer_source is None: self.timer_source = max(0, row - 1)
        if self.pending and (scheduled or self.timer_source is not None or self.scene_block):
            self.events.append(dict(row=row, kind='取消', cid=self.pending['cid'])); self.pending = None
        if point.normal:
            assert 0 < point.bid < point.ask
            self.mark_bid, self.mark_ask = Decimal(str(point.bid)), Decimal(str(point.ask))
            if self.held and self.timer_source is not None:
                self.return_all(row, self.timer_source, point, '静観/期限')
            elif self.queue and self.held:
                self.return_all(row, self.queue['source'], point, self.queue['reason'])
            if self.timer_source is not None: self.timer_source = None
            if self.pending and not scheduled and not self.scene_block:
                p = self.pending; price = point.ask if p['side'] > 0 else point.bid
                reached = price <= p['cap'] if p['side'] > 0 else price >= p['cap']
                if reached:
                    assert not self.held and p['source'] < row
                    self.held = dict(**p, uid=self.uid, row=row, price=price,
                                     N=Decimal(str(price)) * self.cap * self.mult,
                                     base=self.cash * self.mult - self.paid, peak=Decimal('-Infinity'), armed=False)
                    self.orders.append(dict(row=row, source=p['source'], cid=p['cid'], paper=p['paper'], uid=self.uid,
                                            target_uid=-1, side=p['side'], q=p['q'], price=price, new=True, reason='新規', fee=self.charge(p['q'])))
                    self.uid += 1; self.cash -= Decimal(p['side'] * p['q']) * Decimal(str(price)); self.paid += self.charge(p['q'])
                else:
                    self.events.append(dict(row=row, kind='失効', cid=p['cid'])); self.reset_geometry(row, point)
                self.pending = None
        if self.scene_notional is None and self.start <= point.clock <= self.end and math.isfinite(point.last) and point.last > 0:
            self.scene_notional = Decimal(str(point.last)) * self.cap * self.mult
        origin_row = False; origin_withdrawn = False
        for event in paper_events:
            if event['new']:
                assert self.paper is None or self.paper['remaining'] == 0
                self.paper = dict(cid=event['cid'], side=event['side'], P=event['price'], remaining=event['q'])
                self.reset_geometry(row, point); origin_row = True; origin_withdrawn = False
            else:
                assert self.paper and event['cid'] == self.paper['cid'] and event['q'] <= self.paper['remaining']
                self.paper['remaining'] -= event['q']
                if origin_row: origin_withdrawn = True
                if self.pending and self.pending['paper'] == event['cid']:
                    self.events.append(dict(row=row, kind='paper取消', cid=self.pending['cid'])); self.pending = None
                    self.reset_geometry(row, point)
                if self.paper['remaining'] == 0: self.paper = None; self.geometry = None
        liquid = self.liquidation()
        if point.normal and self.scene_notional is not None and not self.scene_block:
            scene = liquid >= self.scene_notional * Decimal('.00375') or liquid <= -self.scene_notional * Decimal('.0025')
            if scene:
                self.scene_block = True
                if self.pending: self.events.append(dict(row=row, kind='場取消', cid=self.pending['cid'])); self.pending = None
                if self.held and not self.queue: self.queue = dict(source=row, reason='場純利益/損失')
        if self.held:
            h = self.held; local = liquid - h['base']
            if point.normal: h['peak'] = max(h['peak'], local)
            if not scheduled and self.timer_source is None and not self.queue:
                reason = None
                if self.scene_block:
                    reason = '場純利益/損失'
                elif point.normal and local <= -h['N'] * Decimal('.00075'):
                    reason = '親損失'
                elif self.paper is None or self.paper['side'] != h['side']:
                    reason = 'paper撤回/反方向'
                elif self.price_exit_enabled and supports(point.own, point.other, -h['side']):
                    reason = '両市場反対'
                elif point.normal and self.exit_id == 'TARGET' and local >= h['N'] * Decimal('.00125'):
                    reason = '親目標'
                elif point.normal and self.exit_id != 'TARGET':
                    arm, draw, floor = ('.00075', '.00025', '.0005') if self.exit_id == 'TIGHT_TRAIL' else ('.00125', '.000375', '.00075')
                    if h['peak'] >= h['N'] * Decimal(arm): h['armed'] = True
                    if h['armed'] and local <= max(h['N'] * Decimal(floor), h['peak'] - h['N'] * Decimal(draw)):
                        reason = '親追尾'
                if reason: self.queue = dict(source=row, reason=reason)
        if origin_row and not origin_withdrawn:
            self.admit(row, point, True)
        elif not origin_row and self.mode != 'ORIGIN' and self.paper and not scheduled and self.timer_source is None:
            self.admit(row, point, False)
        self.curve.append(dict(row=row, liquidation=float(liquid), realized=float(self.realized),
                               local=float(liquid - self.held['base']) if self.held else None,
                               paper=self.paper['cid'] if self.paper else None, actual=self.held['cid'] if self.held else None,
                               uid=self.held['uid'] if self.held else None, held=self.cap if self.held else 0,
                               scene_block=self.scene_block, pending=self.pending['cid'] if self.pending else None))
