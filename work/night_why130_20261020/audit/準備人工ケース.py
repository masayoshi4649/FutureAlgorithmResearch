"""新核に接続する前の架空注文・FIFO会計と検査項目を準備する。"""

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np


HERE = Path(__file__).resolve().parent


def tape(reflected=False, gap=False):
    """
    機能: 原行順と気配が明示された架空の短い板を作る。
    引数: reflected(bool)は上下反転、gap(bool)は返済待ち中の異常気配。
    返り値: dict[str,ndarray]は時刻・両気配・正常資格。
    """
    bid = np.array([100., 100., 102., 103., 102., 100., 98., 94., 94.])
    ask = bid + .5
    valid = np.ones(len(bid), dtype=bool)
    if gap:
        valid[6] = False
    if reflected:
        bid, ask = 200.-ask, 200.-bid
    return dict(time=np.array([0., 1., 1., 1., 2., 3., 3., 4., 5.]),
                bid=bid, ask=ask, valid=valid)


def partial_orders(quantity, reflected=False, gap=False):
    """
    機能: 初回新規・部分返済・全返済の手計算用注文を作る。
    引数: quantity(int)は5又は10、reflected(bool)は反転、gap(bool)は返済欠測。
    返り値: ndarrayは約定行・判断行・親・注文方向・枚数・価格・理由・新規の8列。
    """
    quote = tape(reflected, gap)
    side = -1 if reflected else 1
    partial = 2 if quantity == 5 else 4
    last_row = 7 if gap else 6
    entry_price = quote["ask" if side == 1 else "bid"][1]
    exit_key = "bid" if side == 1 else "ask"
    return np.array([
        [1, 0, 1, side, quantity, entry_price, 100, 1],
        [3, 2, 1, -side, partial, quote[exit_key][3], 200, 0],
        [last_row, 5, 1, -side, quantity-partial, quote[exit_key][last_row], 300, 0],
    ], dtype=float)


def account_orders(quote, orders, multiplier, fee_tenths, cap):
    """
    機能: 架空の保存注文を独立FIFOで会計し、正常気配行の時価も計算する。
    引数: quote(dict)、orders(ndarray)、multiplier(float)、fee_tenths(int)、cap(int)。
    返り値: dictは注文費用・全親損益・全行時価。未知行の時価はnanで補完しない。
    """
    remaining = []
    parent = defaultdict(lambda: dict(gross=0., fees=0, net=0., entries=0, exits=0))
    fees, realized = 0, 0.
    curve = np.full((len(quote["bid"]), 4), np.nan)
    order_fees = []
    assert np.all(np.diff(orders[:, 0]) >= 0)
    for row in range(len(quote["bid"])):
        for order in orders[orders[:, 0] == row]:
            fill, decision, cid, side, qty, price, _, is_new = order
            fill, decision, cid, side, qty = map(int, (fill, decision, cid, side, qty))
            assert fill > decision and quote["valid"][fill]
            first = next(i for i in range(decision+1, len(quote["bid"])) if quote["valid"][i])
            assert fill == first, (fill, first)
            expected_price = quote["ask" if side == 1 else "bid"][fill]
            assert price == expected_price
            cost = (qty*fee_tenths)//10
            fees += cost
            parent[cid]["fees"] += cost
            order_fees.append(cost)
            if is_new:
                remaining.append(dict(cid=cid, side=side, qty=qty, price=price))
                parent[cid]["entries"] += qty
            else:
                left = qty
                for lot in remaining:
                    if lot["cid"] != cid or lot["side"] != -side or not lot["qty"]:
                        continue
                    amount = min(left, lot["qty"])
                    value = lot["side"]*(price-lot["price"])*amount*multiplier
                    realized += value
                    parent[cid]["gross"] += value
                    parent[cid]["exits"] += amount
                    lot["qty"] -= amount
                    left -= amount
                    if left == 0:
                        break
                assert left == 0, "保有を超える返済"
            for direction in (-1, 1):
                assert sum(l["qty"] for l in remaining if l["side"] == direction) <= cap
        inventory = sum(l["side"]*l["qty"] for l in remaining)
        if quote["valid"][row]:
            unrealized = sum(
                l["side"]*(quote["bid" if l["side"] == 1 else "ask"][row]-l["price"])
                *l["qty"]*multiplier for l in remaining
            )
            curve[row] = (realized-fees+unrealized, inventory, fees, realized-fees)
    for item in parent.values():
        item["net"] = item["gross"]-item["fees"]
    assert not sum(l["qty"] for l in remaining)
    return dict(order_fees=order_fees, parents=dict(parent), curve=curve,
                gross=realized, fees=fees, net=realized-fees)


def main():
    """
    機能: 架空6条件の手計算値を確認し、新核接続前の準備証跡を保存する。
    引数: なし。
    返り値: None。実データ読取・数値核の金融再生・API取得はしない。
    """
    checks = []
    for quantity, multiplier, fee_tenths, expected in (
        (5, 1000., 418, -2917.),
        (10, 10., 110, -270.),
    ):
        outcomes = []
        for reflected in (False, True):
            result = account_orders(tape(reflected), partial_orders(quantity, reflected),
                                    multiplier, fee_tenths, quantity)
            assert result["net"] == expected
            assert result["parents"][1]["net"] == expected
            assert result["parents"][1]["entries"] == result["parents"][1]["exits"] == quantity
            outcomes.append(result)
            checks.append(dict(項目="部分利益後の残玉損を含めた親赤字",
                               枚数=quantity, 反転=reflected, 粗収支=result["gross"],
                               注文費用=result["order_fees"], 純収支=result["net"]))
        np.testing.assert_array_equal(outcomes[0]["curve"][:, [0, 2, 3]],
                                      outcomes[1]["curve"][:, [0, 2, 3]])
        gap = account_orders(tape(gap=True), partial_orders(quantity, gap=True),
                             multiplier, fee_tenths, quantity)
        expected_gap = expected-(3 if quantity == 5 else 6)*4*multiplier
        assert gap["net"] == expected_gap
        assert np.isnan(gap["curve"][6]).all()
        checks.append(dict(項目="判断後の未知行を飛ばし価格飛びを負担",
                           枚数=quantity, 純収支=gap["net"]))
    path = HERE / f"新核接続前の架空会計雛形_{time.time_ns()}.json"
    proof = dict(
        passed=True, scope="人工注文の独立会計だけ。00130の新戦略は未検査・未測定",
        checks=checks, financial_replays=0, api_calls=0, real_data_reads=0,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        kernel_validation_pending=True,
    )
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(dict(passed=True, cases=len(checks), path=str(path)), ensure_ascii=False))


if __name__ == "__main__":
    main()
