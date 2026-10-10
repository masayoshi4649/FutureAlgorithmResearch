"""小開始・順行追加・全量返済の料金と一組の分母を独立会計で確認する。"""

from __future__ import annotations

import numpy as np

from independent_account import CAP, POINT, HERE, fee, near, reconstruct, save
from adapters import check


def run_case(symbol: str, side: int) -> dict:
    """機能: 追加3建値を一括返済し、料金配賦と含み損を含む全時価を検査する。

    引数: symbol(str)、side(int)。返り値: 人工会計の要約(dict)。
    新規手数料は個別注文、返済手数料は合計注文から累積枚数で配賦する。
    """
    quantities = [2, 3, 5] if symbol == "TOPIX" else [4, 6, 10]
    scale = 1 if symbol == "TOPIX" else 5
    base = 4000. if symbol == "TOPIX" else 60000.
    entry = base + side * np.array([1., 6., 10.]) * scale
    exit_price = base + side * 8. * scale
    bid = np.full(6, base)
    ask = bid + scale
    if side == 1:
        ask[1:4], bid[1:4] = entry, entry - scale
        bid[5], ask[5] = exit_price, exit_price + scale
    else:
        bid[1:4], ask[1:4] = entry, entry + scale
        ask[5], bid[5] = exit_price, exit_price - scale
    data = dict(seq=np.arange(6), time_s=np.array([0., 1., 1., 2., 3., 4.]), bid=bid, ask=ask)
    orders = np.array([[i+1, i, 1, side, q, entry[i], 10 if i == 0 else 20, 1, 0]
        for i, q in enumerate(quantities)] + [[5, 4, 1, -side, CAP[symbol], exit_price, 2, 0, 0]], dtype=float)
    account, raw_curve = reconstruct(data, dict(symbol=symbol, session="追加人工", orders=orders))
    exit_fee = fee(symbol, CAP[symbol])
    cumulative = 0
    expected_allocations = []
    for q in quantities:
        expected_allocations.append(exit_fee * (cumulative + q) // CAP[symbol] - exit_fee * cumulative // CAP[symbol])
        cumulative += q
    assert [d["exit_fee"] for d in account["details"]] == expected_allocations
    assert sum(expected_allocations) == exit_fee
    assert [d["entry_fee"] for d in account["details"]] == [fee(symbol, q) for q in quantities]
    assert account["campaigns"] == 1 and account["entry_orders"] == 3 and account["exit_orders"] == 1
    assert account["trades"] == 3 and account["campaign_wins"] == 1
    assert account["loss"] > 0 and account["campaign_loss"] == 0
    assert account["max_long" if side == 1 else "max_short"] == CAP[symbol]
    near(account["net"], sum(q * side * (exit_price - p) * POINT[symbol] for q, p in zip(quantities, entry))
        - sum(fee(symbol, q) for q in quantities) - exit_fee, "追加全玉収支")
    near(account["profit"] - account["loss"], account["campaign_profit"], "明細損益と組損益")
    trades = np.array([[d["campaign"], d["entry_row"], d["exit_row"], d["side"], d["quantity"],
        d["entry"], d["exit"], d["entry_fee"], d["exit_fee"], d["gross"], d["net"], leg]
        for leg, d in enumerate(account["details"])], dtype=float)
    planned = np.array([0, exit_fee if quantities[0] == CAP[symbol] else fee(symbol, quantities[0]),
        fee(symbol, sum(quantities[:2])), exit_fee, exit_fee, 0])
    liquidation_curve = raw_curve - planned
    new_orders = np.column_stack((orders[:, :8], [fee(symbol, int(o[4])) for o in orders], [0, 1, 2, -1]))
    checked = check(data, symbol, new_orders, trades, liquidation_curve)
    near(checked["net"], account["net"], "全清算曲線の終端")
    return dict(symbol=symbol, side=side, quantities=quantities, entry_fees=[fee(symbol, q) for q in quantities],
        exit_allocations=expected_allocations, profit=account["profit"], loss=account["loss"], net=account["net"],
        campaigns=account["campaigns"], legs=account["trades"],
        money_profit_share=account["profit"] / (account["profit"] + account["loss"]), campaign_win_rate=1.)


def main() -> None:
    """機能: 二商品両方向の追加と整数配賦を検査し、利益組の負け玉も記録する。

    引数: なし。返り値: なし(None)。新engineではなく独立会計器の自己検査。
    """
    results = [run_case(s, side) for s in CAP for side in (1, -1)]
    assert results[0]["exit_allocations"] == [83, 126, 209]
    assert results[0]["entry_fees"] == [83, 125, 209]
    save(HERE / "追加と全返済料金配賦の人工独立会計.json", dict(合格=True,
        商品方向検査数=4, 人工会計=results,
        確認="全3建値の明細利益・損失を保持。3追加注文でも組は1つ、全量返済1注文の料金は整数累積配賦。",
        限界="独立会計器の自己検査であり、未実装の新engineの合格ではない。",
        原本取得=0, API取得=0, 実注文=0))


if __name__ == "__main__":
    main()
