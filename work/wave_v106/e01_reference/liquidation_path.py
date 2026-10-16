"""残玉をUID別に清算した場合の料金を加え、保存経路の利益機会だけを診断する。"""

from decimal import Decimal, ROUND_FLOOR
import numpy as np

from bridge import HERE, digest, read, save
from diagnose import packet
from specification import FEE


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 一つの残玉返済注文に必要な円料金を求める。
    引数: quantity(int)、symbol(str)は返済残枚数と商品。
    返り値: int。親/UIDごとの注文金額を切り捨てる。
    """
    return int((Decimal(quantity) * Decimal(str(FEE[symbol]))).to_integral_value(rounding=ROUND_FLOOR))


def remaining_fees(ledger: dict, n: int, symbol: str) -> np.ndarray:
    """
    機能: 当行までの実注文だけをFIFOに適用し、未返済UIDの料金を全行へ展開する。
    引数: ledger(dict)は注文とUID、n(int)は行数、symbol(str)は商品。
    返り値: ndarray[int64]。未来のtrade返済行/将来損益を使用しない。
    """
    orders = ledger['orders']; uids = ledger['order_uids']
    outstanding = {}; reserved = np.zeros(n, np.int64); previous = 0; total = 0
    pointer = 0
    while pointer < len(orders):
        row = int(orders[pointer, 0]); assert previous <= row < n
        reserved[previous:row] = total
        while pointer < len(orders) and int(orders[pointer, 0]) == row:
            o = orders[pointer]; cid, side, quantity, new = map(int, (o[2], o[3], o[4], o[7]))
            assert quantity > 0
            if new:
                uid = int(uids[pointer]); assert uid >= 0 and uid not in outstanding
                outstanding[uid] = [cid, side, quantity]
            else:
                remaining = quantity
                for uid, state in outstanding.items():
                    if state[0] != cid or state[1] != -side or state[2] == 0:
                        continue
                    amount = min(remaining, state[2]); remaining -= amount; state[2] -= amount
                    if not remaining:
                        break
                assert remaining == 0
            pointer += 1
        total = sum(fee(state[2], symbol) for state in outstanding.values() if state[2] > 0)
        previous = row
    reserved[previous:] = total
    return reserved


def liquidation_curve(ledger: dict, symbol: str) -> tuple[np.ndarray, np.ndarray]:
    """
    機能: 実注文料控除済みbid/ask時価から残UID返済料も控除する。
    引数: ledger(dict)、symbol(str)は保存BBO会計と商品。
    返り値: tuple[ndarray,ndarray]。全行正味清算経路と残返済料。
    """
    baseline = ledger['equity_yen']; reserved = remaining_fees(ledger, len(baseline), symbol)
    assert reserved[-1] == 0 and np.isclose(baseline[-1], ledger['summary']['収支'], atol=1e-7, rtol=0.)
    return baseline - reserved, reserved


def artificial() -> None:
    """
    機能: 複数UIDと部分返済がある場合の残料を独立整数期待値で検証する。
    引数: なし。
    返り値: None。私有人工のみで金融結果を変えない。
    """
    target = HERE / 'UID別残返済料の人工検査.json'; assert not target.exists()
    rows = np.array([[1, 0, 0, 1, 5, 100., 0, 1], [2, 1, 0, 1, 2, 100., 0, 1],
                     [3, 2, 0, -1, 3, 100., 0, 0], [4, 3, 0, -1, 4, 100., 0, 0]])
    ledger = dict(orders=rows, order_uids=np.array([0, 1, -1, -1]))
    actual = remaining_fees(ledger, 6, 'TOPIX')
    # UID0が5→2、UID1は2枚。2UID各83円で166円、合算4枚167円にはしない。
    np.testing.assert_array_equal(actual, [0, 209, 292, 166, 0, 0])
    clipped = dict(orders=rows[:3], order_uids=np.array([0, 1, -1]))
    np.testing.assert_array_equal(remaining_fees(clipped, 4, 'TOPIX'), actual[:4])
    future = rows.copy(); future[3, 5] += 1000
    np.testing.assert_array_equal(remaining_fees(dict(orders=future, order_uids=ledger['order_uids']), 6, 'TOPIX'), actual)
    save(target, dict(全合格=True, 検査数=3, 期待値=[0, 209, 292, 166, 0, 0],
        複数UID料金をまとめない=True, 部分返済FIFO=True, 接頭未来変更不変=True,
        sourceSHA256=digest(HERE / 'liquidation_path.py'), 金融再生=0))


if __name__ == '__main__':
    artificial()
