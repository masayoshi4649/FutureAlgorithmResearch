"""被検査器の旧列形式を独立会計器へ接続する。"""

from __future__ import annotations

import numpy as np

from independent_account import fee, reconstruct


def orders9(orders: np.ndarray) -> np.ndarray:
    """機能: 役割が省略された単玉注文に役割0を追加する。

    引数: orders(np.ndarray)。返り値: 9列注文(np.ndarray)。
    """
    orders = np.asarray(orders, dtype=float)
    assert orders.ndim == 2 and orders.shape[1] in (8, 9)
    return np.column_stack((orders, np.zeros(len(orders)))) if orders.shape[1] == 8 else orders


def trades12(trades: np.ndarray) -> np.ndarray:
    """機能: 役割が省略された単玉決済に役割0を追加する。

    引数: trades(np.ndarray)。返り値: 12列決済(np.ndarray)。
    """
    trades = np.asarray(trades, dtype=float)
    assert trades.ndim == 2 and trades.shape[1] in (11, 12)
    return np.column_stack((trades, np.zeros(len(trades)))) if trades.shape[1] == 11 else trades


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
    account, independent_curve = reconstruct(data, dict(symbol=symbol, session="監査用", orders=orders9(orders)), require_flat)
    expected = np.asarray([[t["campaign"], t["entry_row"], t["exit_row"], t["side"], t["quantity"],
        t["entry"], t["exit"], t["entry_fee"], t["exit_fee"], t["gross"], t["net"], t["role"]]
        for t in account["details"]], dtype=float).reshape((-1, 12))
    np.testing.assert_allclose(trades12(trades), expected, atol=1.e-4, rtol=0)
    # ----------------------------------------
    # 新検査器の曲線は、未返済玉を今すぐ返済する片道料金も引いた清算時価である。
    liquidation_curve = clearing_curve(symbol, orders, independent_curve)
    np.testing.assert_allclose(curve, liquidation_curve, atol=1.e-4, rtol=0)
    account["清算時価最大下落"] = float(np.max(np.maximum.accumulate(np.maximum(liquidation_curve, 0.)) - liquidation_curve))
    account["予定返済料金を控除"] = True
    return account
