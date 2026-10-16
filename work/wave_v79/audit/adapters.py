"""注文料金と建値番号を持つ新列形式を独立会計器へ接続する。"""

from __future__ import annotations

import numpy as np

from independent_account import fee, reconstruct


def orders9(orders: np.ndarray) -> np.ndarray:
    """機能: 明示注文料金・建値番号を検査し、独立会計器へ役割0で渡す。

    引数: orders(np.ndarray)。返り値: 9列注文(np.ndarray)。
    """
    orders = np.asarray(orders, dtype=float)
    assert orders.ndim == 2 and orders.shape[1] == 10
    return np.column_stack((orders[:, :8], np.zeros(len(orders))))


def trades12(trades: np.ndarray) -> np.ndarray:
    """機能: 建値番号つき12列の全決済明細を受け取る。

    引数: trades(np.ndarray)。返り値: 12列決済(np.ndarray)。
    """
    trades = np.asarray(trades, dtype=float)
    assert trades.ndim == 2 and trades.shape[1] == 12
    return trades


def clearing_curve(symbol: str, orders: np.ndarray, equity: np.ndarray) -> np.ndarray:
    """機能: 未返済の全数量を清算する予定片道料金を時価から控除する。

    引数: symbol(str)、orders/equity(np.ndarray)。返り値: 清算時価(np.ndarray)。
    """
    quantity = 0
    charges = np.zeros(len(equity))
    previous = 0
    for order in orders9(orders):
        row, _, _, side, amount, _, _, _, _ = map(float, order)
        row = int(row)
        charges[previous:row] = fee(symbol, abs(quantity)) if quantity else 0
        quantity += int(side * amount)
        previous = row
    charges[previous:] = fee(symbol, abs(quantity)) if quantity else 0
    return equity - charges


def check(data: dict, symbol: str, orders: np.ndarray, trades: np.ndarray, curve: np.ndarray, require_flat: bool = True) -> dict:
    """機能: 次有効行・売買気配・全明細・料金・全行時価を別会計で照合する。

    引数: data(dict)、symbol(str)、orders/trades/curve(np.ndarray)、require_flat(bool)。
    返り値: 独立会計(dict)。prefixでは未返済を許し、完了セッションだけ全返済を要求する。
    """
    stage_by_campaign = {}
    leg_by_entry = {}
    for order in np.asarray(orders):
        row, _, cid, _, amount, _, _, opened, charged, leg = order
        assert charged == fee(symbol, int(amount)), ("明示注文料金", order)
        if int(opened):
            expected_leg = stage_by_campaign.get(int(cid), 0)
            assert leg == expected_leg and 0 <= leg < 3, ("建値番号", order)
            stage_by_campaign[int(cid)] = expected_leg + 1
            leg_by_entry[(int(cid), int(row))] = int(leg)
        else:
            assert leg == -1, ("全返済の建値番号", order)
    account, independent_curve = reconstruct(data, dict(symbol=symbol, session="監査用", orders=orders9(orders)), require_flat)
    expected = np.asarray([[t["campaign"], t["entry_row"], t["exit_row"], t["side"], t["quantity"],
        t["entry"], t["exit"], t["entry_fee"], t["exit_fee"], t["gross"], t["net"], leg_by_entry[(t["campaign"], t["entry_row"])]]
        for t in account["details"]], dtype=float).reshape((-1, 12))
    np.testing.assert_allclose(trades12(trades), expected, atol=1.e-4, rtol=0)
    # ----------------------------------------
    # 新検査器の曲線は、未返済玉を今すぐ返済する片道料金も引いた清算時価である。
    liquidation_curve = clearing_curve(symbol, orders, independent_curve)
    np.testing.assert_allclose(curve, liquidation_curve, atol=1.e-4, rtol=0)
    account["清算時価最大下落"] = float(np.max(np.maximum.accumulate(np.maximum(liquidation_curve, 0.)) - liquidation_curve))
    account["予定返済料金を控除"] = True
    return account
