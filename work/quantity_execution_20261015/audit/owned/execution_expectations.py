"""機能別の具体的な期待を、実装の出力を参照せず固定する。"""

from __future__ import annotations

from fractions import Fraction

from cash_reference import PRODUCTS, order_fee


def fixtures() -> list[dict]:
    """
    機能: 各出口・売買・商品の約定行と損益を先に固定する。
    引数: なし。
    返り値: list[dict] 独立期待。価格は新規基準からの観測呼値で表す。
    """
    out = []
    paths = (
        (0, [-1, -1, 2, 1, 1], [(2, 3, Fraction(1), Fraction(1))]),
        (1, [-1, -1, 4, 3, 3], [(2, 3, Fraction(1), Fraction(3))]),
        (2, [-1, -1, 3, 5, 4, 3, 3], [(4, 5, Fraction(1), Fraction(3))]),
        (3, [-1, -1, 2, 1, 0, 0], [(2, 3, Fraction(1, 2), Fraction(1)), (3, 4, Fraction(1, 2), Fraction(0))]),
    )
    for product in PRODUCTS:
        for side in (1, -1):
            for mode, ticks, fills in paths:
                expected_gross = sum(g * product.tick * int(frac * product.quantity) * product.multiplier for _, _, frac, g in fills)
                fees = order_fee(product, product.quantity) + sum(order_fee(product, int(frac * product.quantity)) for _, _, frac, _ in fills)
                out.append({
                    "name": f"{product.symbol}_{side}_E{mode + 1}",
                    "symbol": product.symbol,
                    "side": side,
                    "mode": mode,
                    "ticks": ticks,
                    "fills": fills,
                    "gross": expected_gross,
                    "fees": fees,
                    "net": expected_gross - fees,
                })
    return out


def first_raw_decision(public_row: int, public_seq: int, arrival_row: int, arrival_seq: int,
                       execution_normal: bool, quiet_or_force: bool, scene_stopped: bool) -> str:
    """
    機能: 受理済みの新規を直後の原行一回だけで判定する。
    引数: 行と原連番(int)、資格・停止状態(bool)。締切は新規公開だけへ適用する。
    返り値: str 約定又は永久取消の分類。
    """
    if quiet_or_force or scene_stopped:
        return "予定停止取消"
    if arrival_row != public_row + 1 or arrival_seq != public_seq + 1:
        return "原連番取消"
    if not execution_normal:
        return "資格取消"
    return "約定"


def event_eligible(mode: int, event_type: int, side: int, initial_opposite: Fraction,
                   minimum_opposite: Fraction, bid_quantity: Fraction, ask_quantity: Fraction) -> bool:
    """
    機能: 事象の公開済み数量だけから三入口を対称に判定する。
    引数: mode/type/side(int)、初期・最小・公開当時の数量(Fraction)。
    返り値: bool 入口資格。未来の先着値は受け取らない。
    """
    if mode == 0:
        return event_type == 0
    if event_type != 1 or minimum_opposite < initial_opposite:
        return False
    same, opposite = (bid_quantity, ask_quantity) if side == 1 else (ask_quantity, bid_quantity)
    return mode == 1 or same >= opposite


def reference_checks() -> dict:
    """
    機能: 直後行資格と数量の厳密な境界を純検算する。
    引数: なし。
    返り値: dict 純期待と確認数。
    """
    checks = 0
    truth = []
    for row in (5, 6, 7):
        for seq in (100, 101, 102):
            for normal in (False, True):
                for scheduled in (False, True):
                    for scene in (False, True):
                        got = first_raw_decision(5, 100, row, seq, normal, scheduled, scene)
                        wanted = "約定" if row == 6 and seq == 101 and normal and not scheduled and not scene else "取消"
                        assert (got == "約定") == (wanted == "約定")
                        truth.append([row, seq, normal, scheduled, scene, got])
                        checks += 1
    for side in (1, -1):
        for mode in (0, 1, 2):
            for typ in (0, 1):
                for minimum in (Fraction(9), Fraction(10), Fraction(11)):
                    for same in (Fraction(9), Fraction(10), Fraction(11)):
                        b, a = (same, Fraction(10)) if side == 1 else (Fraction(10), same)
                        actual = event_eligible(mode, typ, side, Fraction(10), minimum, b, a)
                        expected = typ == 0 if mode == 0 else typ == 1 and minimum >= 10 and (mode == 1 or same >= 10)
                        assert actual == expected
                        checks += 1
    paths = fixtures()
    assert len(paths) == 16
    checks += 1
    return {"全合格": True, "確認数": checks, "直後原行の真偽表": truth, "具体経路数": len(paths), "新実装への接続": False}
