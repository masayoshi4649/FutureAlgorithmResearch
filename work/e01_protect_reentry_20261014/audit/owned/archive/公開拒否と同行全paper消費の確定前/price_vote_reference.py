"""実装を参照せず、価格代理時計と再参加形状の因果境界を定義する純参照。"""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Point:
    """
    機能: 独立人工の正常Lastと原行の価格代理時計を保持する。
    引数: clock/last(float)、normal(bool)、raw_seq(int) は人工観測値。
    返り値: Point は不変の観測。受信時刻の存在を仮定しない。
    """
    clock: float
    last: float
    normal: bool
    raw_seq: int


def qualified(p: Point) -> bool:
    """
    機能: 人工の正常資格を有限正価格と有限時計へ重ねる。
    引数: p(Point) は一観測。
    返り値: bool は正常Lastとして使えるか。未知Lastを前方補完しない。
    """
    return p.normal and math.isfinite(p.clock) and math.isfinite(p.last) and p.last > 0


def window(points: list[Point], end_row: int, width: float = 60.) -> dict:
    """
    機能: 当時原行までの正常Lastから、cutoffより後の非零隣接更新を一票ずつ数える。
    引数: points(list[Point])、end_row(int)、width(float) は人工列と当時終点/秒幅。
    返り値: dict は既知・票・釣合い。cutoff以前の基準が無ければ未知。
    """
    assert 0 <= end_row < len(points) and width > 0
    end = points[end_row]
    if not qualified(end):
        return dict(known=False, count=0, balance=None, end_row=end_row, reference_row=None, reason='当時終点不適合')
    cutoff = end.clock - width
    eligible = [(i, p) for i, p in enumerate(points[:end_row + 1]) if qualified(p)]
    # 入力の時計適合は価格代理モデルの前提。逆時計をsortして修復しない。
    if any(a[1].clock > b[1].clock for a, b in zip(eligible, eligible[1:])):
        return dict(known=False, count=0, balance=None, end_row=end_row, reference_row=None, reason='時計逆行')
    bases = [(i, p) for i, p in eligible if p.clock <= cutoff]
    if not bases:
        return dict(known=False, count=0, balance=None, end_row=end_row, reference_row=None, reason='cutoff基準なし')
    reference, prior = bases[-1]
    up, down = 0, 0
    for i, point in eligible:
        if i <= reference or point.clock <= cutoff:
            continue
        if point.last > prior.last:
            up += 1
        elif point.last < prior.last:
            down += 1
        prior = point
    count = up + down
    return dict(known=True, count=count, balance=(up - down) / count if count else 0., end_row=end_row,
                reference_row=reference, up=up, down=down, cutoff=cutoff, reason='正常')


def peer(points: list[Point], own_clock: float, width: float = 60., max_age: float = 60.) -> dict:
    """
    機能: 自己時計と同時刻以降を除き、最後の正常peer終点に窓を置く。
    引数: points(list[Point])、own_clock/width/max_age(float) は相手列と自己時計/資格秒。
    返り値: dict はstrict過去かつ期限内の相手票。同clockを過去へ補完しない。
    """
    if not math.isfinite(own_clock):
        return dict(known=False, count=0, balance=None, end_row=None, reason='自己時計なし')
    candidates = [(i, p) for i, p in enumerate(points) if qualified(p) and p.clock < own_clock]
    if not candidates:
        return dict(known=False, count=0, balance=None, end_row=None, reason='strict過去終点なし')
    row, point = candidates[-1]
    age = own_clock - point.clock
    if age > max_age:
        return dict(known=False, count=0, balance=None, end_row=row, reason='期限超過', age=age)
    result = window(points, row, width); result['age'] = age
    return result


def supports(own: dict, other: dict, side: int, threshold: float = .25) -> bool:
    """
    機能: 両市場の既知二票と売買方向へ向けた釣合いを判定する。
    引数: own/other(dict)、side(int)、threshold(float) は純票と売買側/固定境界。
    返り値: bool は両市場支持。片方未知を零票や片側成功へ補完しない。
    """
    assert side in (-1, 1)
    return all(v['known'] and v['count'] >= 2 and v['balance'] is not None and side * v['balance'] >= threshold
               for v in (own, other))


def spread_admission(price: float, bid: float, ask: float, quantity: int, multiplier: int,
                     round_trip_fee: int) -> bool:
    """
    機能: 公開時点の費用だけで、初期spreadを親損失枠の半分以内へ限定する。
    引数: price/bid/ask(float)、quantity/multiplier/round_trip_fee(int) は公開側価格/両気配/実量/料。
    返り値: bool はspread費用審査。将来fill価格を公開へ逆算しない。
    """
    assert quantity > 0 and multiplier > 0
    if not all(math.isfinite(v) for v in (price, bid, ask)) or not 0 < bid < ask or price <= 0:
        return False
    initial_cost = (ask - bid) * quantity * multiplier + round_trip_fee
    available = .5 * price * quantity * multiplier * .00075
    return initial_cost <= available


class Geometry:
    """
    機能: flat中の再参加を、紙上親の公開Pと現在までのLastだけで追跡する。
    引数: side(int)、paper_price(float)、clock/last(float) は新しい活動紙上親と初期観測。
    返り値: Geometry は独立状態。実filledのNやUIDを持たず上書きしない。
    """

    def __init__(self, side: int, paper_price: float, row: int, last: float):
        """
        機能: 新紙上親又は実返済/失効からflat形状を初期化する。
        引数: side(int)、paper_price/last(float)、row(int) は側/P/正常Last/当時行。
        返り値: None。anchor行自身のshape参加は許さない。
        """
        assert side in (-1, 1) and paper_price > 0 and math.isfinite(paper_price)
        self.side, self.P, self.row, self.anchor = side, paper_price, row, last
        self.extreme = last
        self.trough = None

    def observe(self, row: int, last: float, normal: bool, mode: str, strong: bool) -> dict:
        """
        機能: 当時正常Lastだけで押し回復又はanchor突破の形状を判定する。
        引数: row(int)、last(float)、normal/strong(bool)、mode(str) は当時観測と入口種類。
        返り値: dict は各形状と選択。モード切替のみでanchorを再選択しない。
        """
        assert mode in ('ORIGIN', 'PULL', 'BREAK', 'ADAPTIVE')
        if row <= self.row or not normal or not math.isfinite(last) or last <= 0:
            return dict(pull=False, breakout=False, entry=False, branch=None)
        if not math.isfinite(self.anchor):
            self.anchor = self.extreme = last
            self.trough = None
            self.row = row
            return dict(pull=False, breakout=False, entry=False, branch=None)
        s = self.side
        if s * (last - self.extreme) > 0:
            self.extreme = last
        if self.trough is None and s * (self.extreme - last) >= .00025 * self.P:
            self.trough = last
        elif self.trough is not None and s * (last - self.trough) < 0:
            self.trough = last
        pull = self.trough is not None and s * (last - self.trough) >= .000125 * self.P
        breakout = s * (last - self.anchor) >= .00025 * self.P
        branch = 'BREAK' if mode == 'ADAPTIVE' and strong else 'PULL' if mode == 'ADAPTIVE' else mode
        entry = breakout if branch == 'BREAK' else pull if branch == 'PULL' else False
        return dict(pull=pull, breakout=breakout, entry=entry, branch=branch)
