"""原公開行の出来高方向票と現在二市場価格票を別々の純述語へ分離する。"""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class Price:
    """
    機能: 数量や出来高と独立した現在価格方向票を保持する。
    引数: known(bool)、count(int)、balance(float) は当時窓の資格・票数・上昇方向釣合い。
    返り値: Price は不変な純人工の入力型。
    """
    known: bool
    count: int
    balance: float


@dataclass(frozen=True)
class Volume:
    """
    機能: 一つの紙上新規公開原行に属する出来高代理票の系譜を保持する。
    引数: 公開行・原行・seq(int)、時計(float)、known(bool)、票数(int)、signed釣合い(float|None)。
    返り値: Volume は不変な純人工の入力型。釣合いは既に候補方向を掛けた値。
    """
    publication_row: int
    raw_row: int
    raw_seq: int
    price_time: float
    known: bool
    up: int | None
    down: int | None
    count: int | None
    signed_balance: float | None


# ----------------------------------------
def price_both(own: Price, peer: Price, side: int) -> bool:
    """
    機能: 現在両市場の正常Last更新票による旧入口述語を判定する。
    引数: own/peer(Price)、side(int:±1) は現在票と候補方向。
    返り値: bool は両既知・各二票以上・候補方向釣合い各0.25以上。
    """
    assert side in (-1, 1)
    return all(p.known and p.count >= 2 and isfinite(p.balance)
               and side * p.balance >= .25 for p in (own, peer))


def fak_allowance(own: Price, peer: Price, side: int) -> int:
    """
    機能: 入口の採否とは独立して旧価格票の不利一呼値許容を求める。
    引数: own/peer(Price)、side(int:±1) は現在票と候補方向。
    返り値: int は両既知かつ候補方向釣合い各0.75以上なら1、他0。二票条件を追加しない。
    """
    assert side in (-1, 1)
    return int(all(p.known and isfinite(p.balance) and side * p.balance >= .75
                   for p in (own, peer)))


def volume_allowed(value: Volume | None, symbol: str, side: int,
                   row: int, raw_row: int, raw_seq: int, stamp: float,
                   selected: bool = False) -> bool:
    """
    機能: 原新規公開行のsigned出来高代理票を当時系譜と整合させて判定する。
    引数: value(Volume|None)、symbol(str)、side/row/raw_row/raw_seq(int)、stamp(float)、selected(bool)。
    返り値: bool は既知・二票以上・指定釣合い以上。別行の特徴を持ち越さない。
    """
    assert side in (-1, 1) and symbol in ('TOPIX', 'NK225')
    if value is None:
        return False
    assert (value.publication_row, value.raw_row, value.raw_seq, value.price_time) == (row, raw_row, raw_seq, stamp)
    assert isfinite(stamp)
    if not value.known:
        return False
    assert type(value.up) is int and type(value.down) is int and type(value.count) is int
    assert value.up >= 0 and value.down >= 0 and value.count == value.up + value.down
    if value.count == 0:
        assert value.signed_balance is None
        return False
    assert value.signed_balance is not None and isfinite(value.signed_balance)
    expected = side * (value.up - value.down) / value.count
    assert abs(value.signed_balance - expected) <= 1e-12
    threshold = .5 if selected and symbol == 'TOPIX' else .25
    return value.count >= 2 and value.signed_balance >= threshold


def admitted(entry: str, volume_ok: bool, selected_ok: bool,
             current_price_ok: bool, common_ok: bool = True) -> bool:
    """
    機能: 四入口の情報述語を共通の価格・費用資格へ結ぶ。
    引数: entry(str)、volume_ok/selected_ok/current_price_ok/common_ok(bool) は独立資格。
    返り値: bool は入口採否。出来高単独へ旧価格票資格を暗黙追加しない。
    """
    values = {'PRICE_BOTH': current_price_ok, 'VOL_SELECTED': selected_ok,
              'VOL25': volume_ok, 'VOL25_PRICE_BOTH': volume_ok and current_price_ok}
    assert entry in values
    return bool(common_ok and values[entry])
