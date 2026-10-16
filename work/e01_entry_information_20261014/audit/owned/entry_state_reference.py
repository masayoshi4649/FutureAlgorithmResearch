"""旧独立実玉参照の出口を保ち、ORIGINの情報入口だけを純maskへ置き換える。"""

from pathlib import Path
import sys
from entry_information_reference import Price, fak_allowance


ROOT = Path(__file__).resolve().parents[4]
sys.path.append(str(ROOT / 'work/e01_price_exit_ablation_20261014/audit/owned'))
sys.path.append(str(ROOT / 'work/e01_protect_reentry_20261014/audit/owned'))
from price_exit_reference import Reference, Row
from price_vote_reference import spread_admission


class EntryReference(Reference):
    """
    機能: 既存純参照の親・料・退出を維持し、元紙上新規の情報資格だけを差し替える。
    引数: symbol/exit_id(str)、allowed(list[bool]) は商品・退出・原公開行の独立mask。
    返り値: EntryReference は金融源と独立したORIGIN専用の純状態。
    """
    def __init__(self, symbol: str, exit_id: str, allowed: list[bool]):
        """
        機能: 新しい情報入口の純口座を旧実玉参照から初期化する。
        引数: symbol/exit_id(str)、allowed(list[bool]) は固定商品・出口・公開mask。
        返り値: None。価格反票による独立退出はOFFのまま。
        """
        super().__init__(symbol, 'ORIGIN', exit_id, price_exit_enabled=False)
        self.allowed = allowed

    def admit(self, row: int, point: Row, origin: bool) -> None:
        """
        機能: 元ORIGINだけを共通価格費用資格と独立情報maskで審査する。
        引数: row(int)、point(Row)、origin(bool) は当時行・観測・元新規の資格。
        返り値: None。現在価格票を出来高単独入口へ暗黙ANDしない。
        """
        assert origin
        if not self.paper:
            return
        side = self.paper['side']
        price = point.ask if side > 0 else point.bid
        accepted = (not (self.held or self.pending or self.queue or self.scene_block or point.quiet or self.blocked_current)
                    and self.start + 300 <= point.clock < self.end - 300 and point.normal
                    and self.allowed[row]
                    and spread_admission(price, point.bid, point.ask, self.cap, self.mult, 2 * self.charge(self.cap)))
        self.attempts.append(dict(row=row, paper=self.paper['cid'], accepted=accepted))
        self.reset_geometry(row, point, review_consumed=True)
        if not accepted:
            return
        own = Price(point.own['known'], point.own['count'], point.own['balance'])
        other = Price(point.other['known'], point.other['count'], point.other['balance'])
        allowance = fak_allowance(own, other, side)
        cap = price + side * allowance * self.tick
        self.pending = dict(cid=self.cid, paper=self.paper['cid'], side=side, q=self.cap,
                            source=row, cap=cap, allowance=allowance)
        self.cid += 1
        self.publications.append(dict(row=row, cid=self.pending['cid'], paper=self.paper['cid'], side=side,
                                      cap=cap, allowance=allowance))
