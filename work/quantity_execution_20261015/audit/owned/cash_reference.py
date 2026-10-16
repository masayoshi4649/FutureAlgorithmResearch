"""注文別料金と残量予約について、実装から独立した純期待を作る。"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_FLOOR
from fractions import Fraction
from pathlib import Path
import hashlib
import json


@dataclass(frozen=True)
class Product:
    """機能: 純人工用の商品条件。引数: 料金 Decimal など。返り値: 商品条件。"""

    symbol: str
    quantity: int
    multiplier: int
    tick: Fraction
    fee: Decimal
    base: Fraction


PRODUCTS = (
    Product("TOPIX", 10, 1000, Fraction(1, 2), Decimal("41.8"), Fraction(4000)),
    Product("NK225", 20, 10, Fraction(10), Decimal("11"), Fraction(60000)),
)


def order_fee(product: Product, quantity: int) -> int:
    """
    機能: 注文別の片道料金を十進数から切り捨てる。
    引数: product(Product) 商品、quantity(int) 約定枚数。
    返り値: int 円単位の料金。
    """
    assert quantity >= 0
    return int((product.fee * quantity).to_integral_value(rounding=ROUND_FLOOR))


@dataclass
class Parent:
    """機能: 実親の独立会計。引数: 商品・売買・建値。返り値: 純会計状態。"""

    product: Product
    side: int
    entry: Fraction
    remaining: int = field(init=False)
    paid_fees: int = field(init=False)
    realized_gross: Fraction = Fraction(0)
    reservations: list[tuple[int, int, str]] = field(default_factory=list)
    fills: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        """
        機能: 実新規の全量と新規料金を固定する。
        引数: self(Parent) 初期状態。
        返り値: None。
        """
        assert self.side in (-1, 1)
        self.remaining = self.product.quantity
        self.paid_fees = order_fee(self.product, self.remaining)

    def reserve(self, row: int, quantity: int, reason: str) -> None:
        """
        機能: 古い予約を維持し未予約残玉から返済予約する。
        引数: row(int) 判断行、quantity(int) 枚数、reason(str) 理由。
        返り値: None。
        """
        pending = sum(q for _, q, _ in self.reservations)
        assert 0 <= quantity <= self.remaining - pending
        if quantity:
            self.reservations.append((row, quantity, reason))

    def reserve_all_unreserved(self, row: int, reason: str) -> None:
        """
        機能: 既予約に追加して未予約残玉だけを返済予約する。
        引数: row(int) 判断行、reason(str) 理由。
        返り値: None。
        """
        self.reserve(row, self.remaining - sum(q for _, q, _ in self.reservations), reason)

    def execute(self, row: int, quote: Fraction, normal: bool = True) -> None:
        """
        機能: 過去行で予約した返済を現在の執行正常気配へ順番に約定する。
        引数: row(int) 現在行、quote(Fraction) 返済気配、normal(bool) 執行資格。
        返り値: None。
        """
        if not normal:
            return
        later = []
        for judged, quantity, reason in self.reservations:
            if judged >= row:
                later.append((judged, quantity, reason))
                continue
            assert quantity <= self.remaining
            gross = self.side * (quote - self.entry) * quantity * self.product.multiplier
            fee = order_fee(self.product, quantity)
            self.remaining -= quantity
            self.realized_gross += gross
            self.paid_fees += fee
            self.fills.append({"判断行": judged, "約定行": row, "枚数": quantity, "価格": str(quote), "粗損益": str(gross), "料": fee, "理由": reason})
        self.reservations = later

    def liquidation(self, quote: Fraction) -> Fraction:
        """
        機能: 残返済料を含む現在の親清算損益を返す。
        引数: quote(Fraction) 返済可能気配。
        返り値: Fraction 親の費用後清算損益。
        """
        gross = self.side * (quote - self.entry) * self.remaining * self.product.multiplier
        return self.realized_gross + gross - self.paid_fees - order_fee(self.product, self.remaining)


# ----------------------------------------

def pure_expectations() -> dict:
    """
    機能: 買売対称の会計・予約競合・判断後約定の具体期待を検算する。
    引数: なし。
    返り値: dict 純人工の分子と期待記録。
    """
    checks = 0
    records = []
    for product in PRODUCTS:
        for side in (1, -1):
            entry = product.base + product.tick if side == 1 else product.base
            to_quote = lambda ticks: entry + side * product.tick * ticks
            # 半分 +2T を判断し、次行 +1T で約定、残りはさらに次行 0T。
            parent = Parent(product, side, entry)
            half = product.quantity // 2
            parent.reserve(2, half, "半分利確")
            parent.execute(2, to_quote(2))
            assert parent.remaining == product.quantity and len(parent.fills) == 0
            checks += 1
            parent.execute(3, to_quote(1))
            parent.reserve_all_unreserved(3, "残玉追尾")
            parent.execute(4, to_quote(0))
            expected = product.tick * half * product.multiplier - order_fee(product, product.quantity) - 2 * order_fee(product, half)
            assert parent.remaining == 0 and not parent.reservations
            assert parent.liquidation(to_quote(-100)) == expected
            assert [f["約定行"] for f in parent.fills] == [3, 4]
            assert [f["枚数"] for f in parent.fills] == [half, half]
            checks += 4
            records.append({"商品": product.symbol, "方向": side, "経路": "半分の先行予約と後行の残玉追尾", "期待収支": str(expected), "約定": parent.fills})

            # 数量未知中に強制返済が来ても古い半分を維持し、未予約残のみ追加。
            forced = Parent(product, side, entry)
            forced.reserve(2, half, "半分利確")
            forced.execute(3, to_quote(-2), normal=False)
            forced.reserve_all_unreserved(3, "静観又は場停止")
            forced.reserve_all_unreserved(3, "重複停止")
            assert forced.remaining == product.quantity
            assert sum(q for _, q, _ in forced.reservations) == product.quantity
            forced.execute(4, to_quote(-3))
            expected_forced = -3 * product.tick * product.quantity * product.multiplier - order_fee(product, product.quantity) - 2 * order_fee(product, half)
            assert forced.liquidation(to_quote(100)) == expected_forced
            assert [f["理由"] for f in forced.fills] == ["半分利確", "静観又は場停止"]
            assert forced.remaining == 0 and not forced.reservations
            checks += 5
            records.append({"商品": product.symbol, "方向": side, "経路": "半分予約後の未知と全返済競合", "期待収支": str(expected_forced), "約定": forced.fills})

            # 到着時拡幅を負担し、初期損切りを同約定行で判断しても返済は後行。
            widened_entry = entry + side * 3 * product.tick
            widened = Parent(product, side, widened_entry)
            current_quote = entry - side * product.tick
            immediate = -4 * product.tick * product.quantity * product.multiplier - 2 * order_fee(product, product.quantity)
            assert widened.liquidation(current_quote) == immediate
            widened.reserve_all_unreserved(1, "約定直後の損切り")
            widened.execute(1, current_quote)
            assert widened.remaining == product.quantity
            widened.execute(2, current_quote - side * 2 * product.tick)
            expected_gap = -6 * product.tick * product.quantity * product.multiplier - 2 * order_fee(product, product.quantity)
            assert widened.liquidation(current_quote) == expected_gap
            assert widened.fills[0]["判断行"] < widened.fills[0]["約定行"]
            checks += 4
            records.append({"商品": product.symbol, "方向": side, "経路": "到着拡幅と次行損切りの追加悪化", "期待収支": str(expected_gap), "約定": widened.fills})

            # 予約時点の清算に、未来の有利な約定値を混ぜない。
            pending = Parent(product, side, entry)
            pending.reserve_all_unreserved(2, "利確")
            before = pending.liquidation(to_quote(2))
            assert before == 2 * product.tick * product.quantity * product.multiplier - 2 * order_fee(product, product.quantity)
            assert pending.remaining == product.quantity and not pending.fills
            pending.execute(3, to_quote(-2), normal=False)
            assert pending.remaining == product.quantity and not pending.fills
            checks += 3

    return {"全合格": True, "独立確認数": checks, "期待経路": records, "範囲": "独立有理数・十進数の純会計だけ。新実装未読・未接続・実データ未測定。", "読取": {"新実装": 0, "原入力": 0, "NPZ": 0, "過去金融結果": 0, "台帳": 0, "API": 0}}


def main() -> None:
    """
    機能: 純人工の結果と自分の源指紋を所有領域へ保存する。
    引数: なし。
    返り値: None。
    """
    result = pure_expectations()
    result["独立源_SHA256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    output = Path(__file__).with_name("実装読取前の注文別会計と予約競合の純期待.json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"全合格": result["全合格"], "確認数": result["独立確認数"], "証跡": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
