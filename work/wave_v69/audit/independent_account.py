"""ティックIFD台帳を、注文と原本清算気配だけから独立に再会計する。"""

from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
POINT = {"TOPIX": 1000, "NK225": 10}
INITIAL = {"TOPIX": 5, "NK225": 10}
CAP = {"TOPIX": 10, "NK225": 20}


def near(left: float, right: float, label: str) -> None:
    """機能: 円の演算誤差だけを許容して独立会計を照合する。

    引数: left/right(float)、label(str)。返り値: なし(None)。
    """
    assert abs(left - right) < 1.0e-4, (label, left, right)


def fee(symbol: str, quantity: int) -> int:
    """機能: 注文単位の片道料金を浮動小数を使わずに切り捨てる。

    引数: symbol(str)、quantity(int)。返り値: 切捨て後の円額(int)。
    """
    assert quantity > 0
    return quantity * 418 // 10 if symbol == "TOPIX" else quantity * 11


def save(path: Path, value: object) -> None:
    """機能: 独立監査領域だけに有限JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")


def reconstruct(data: dict, ledger: dict, model: str = "quote") -> tuple[dict, np.ndarray]:
    """機能: FIFO・現金・全原本行の清算時価をエンジンに依存せず再構成する。

    引数: data(dict)は原本行のbid/ask/last/seq/time_s、ledger(dict)は注文台帳、
    model(str)はquoteまたはlast。返り値: 会計指標と全行評価損益(tuple[dict,np.ndarray])。
    """
    symbol = ledger["symbol"]
    multiplier = POINT[symbol]
    time_s = np.asarray(data["time_s"], dtype=float)
    raw_sequence = np.asarray(data["seq"], dtype=np.int64)
    n = len(time_s)
    assert n > 0 and len(raw_sequence) == n
    assert np.all(np.diff(raw_sequence) > 0)
    assert np.all(np.diff(time_s) >= 0)
    long_mark = np.asarray(data["bid" if model == "quote" else "last"], dtype=float)
    short_mark = np.asarray(data["ask" if model == "quote" else "last"], dtype=float)
    assert len(long_mark) == len(short_mark) == n
    if model == "quote":
        quote_ok = np.isfinite(long_mark) & np.isfinite(short_mark) & (long_mark > 0) & (short_mark >= long_mark)
        prior_valid = np.maximum.accumulate(np.where(quote_ok, np.arange(n), -1))
        long_mark = np.concatenate(([0.0], long_mark))[prior_valid+1]
        short_mark = np.concatenate(([0.0], short_mark))[prior_valid+1]
    else:
        quote_ok = np.isfinite(long_mark) & (long_mark > 0)
    orders = ledger["orders"]
    assert len(orders) == len(ledger["fees"])
    fifo = defaultdict(deque)
    held = {1: 0, -1: 0}
    maximum = {1: 0, -1: 0}
    group_fees = defaultdict(int)
    group_gross = defaultdict(float)
    gross = cash = 0.0
    total_fee = 0
    prior_row = -1
    order_rows, positions, cashes, derived = [], [], [], []
    entries = exits = 0
    for number, (order, reported_fee) in enumerate(zip(orders, ledger["fees"])):
        row, source, campaign, side, quantity, price, reason, opened = order
        row, source, campaign, side, quantity, reason, opened = map(
            int, (row, source, campaign, side, quantity, reason, opened))
        price = float(price)
        assert 0 <= source < row < n and row >= prior_row, ("判断と約定の順序", order)
        assert raw_sequence[source] < raw_sequence[row]
        assert side in (-1, 1) and opened in (0, 1) and quantity > 0
        assert np.isfinite(price) and price > 0
        assert quote_ok[row], ("無効気配で約定", order)
        expected = short_mark[row] if side == 1 else long_mark[row]
        near(price, float(expected), "次原本行の気配約定")
        charge = fee(symbol, quantity)
        assert charge == reported_fee, ("注文単位の料金", order, charge, reported_fee)
        total_fee += charge
        group_fees[campaign] += charge
        if opened:
            assert quantity == INITIAL[symbol]
            assert held[1] == held[-1] == 0, ("新規時の残玉", order)
            assert not fifo[(campaign, side)]
            fifo[(campaign, side)].append([row, quantity, price, charge / quantity])
            held[side] += quantity
            entries += 1
        else:
            assert held[-side] >= quantity
            held[-side] -= quantity
            exits += 1
            remaining = quantity
            while remaining:
                assert fifo[(campaign, -side)], ("返済対象なし", order)
                lot = fifo[(campaign, -side)][0]
                take = min(remaining, lot[1])
                profit = take * (-side) * (price - lot[2]) * multiplier
                fees = take * (lot[3] + charge / quantity)
                gross += profit
                group_gross[campaign] += profit
                derived.append(dict(campaign=campaign, entry_row=lot[0], exit_row=row,
                    side=-side, quantity=take, entry=lot[2], exit=price, reason=reason,
                    gross=profit, fees=fees, net=profit-fees))
                remaining -= take
                lot[1] -= take
                if not lot[1]:
                    fifo[(campaign, -side)].popleft()
        assert held[1] <= CAP[symbol] and held[-1] <= CAP[symbol]
        maximum[1] = max(maximum[1], held[1])
        maximum[-1] = max(maximum[-1], held[-1])
        cash -= side * quantity * price * multiplier + charge
        order_rows.append(row)
        positions.append(held[1] - held[-1])
        cashes.append(cash)
        prior_row = row
    assert held[1] == held[-1] == 0
    assert all(not value for value in fifo.values())
    near(cash, gross-total_fee, "全玉返済後の現金")
    near(sum(x["net"] for x in derived), cash, "決済取引合計")
    assert sum(x["quantity"] for x in derived) == entries*INITIAL[symbol]

    # ----------------------------------------
    # 注文後の全保有状態を原本行へ展開し、清算気配で時価評価する。
    indices = np.searchsorted(np.asarray(order_rows, dtype=np.int64), np.arange(n), side="right") - 1
    extended_cash = np.concatenate(([0.0], np.asarray(cashes, dtype=float)))[indices+1]
    extended_position = np.concatenate(([0], np.asarray(positions, dtype=np.int64)))[indices+1]
    marks = np.where(extended_position >= 0, long_mark, short_mark)
    assert np.all(np.isfinite(marks[extended_position != 0]))
    equity = extended_cash + np.where(extended_position != 0, extended_position*marks*multiplier, 0.0)
    peaks = np.maximum.accumulate(np.maximum(equity, 0.0))
    drawdown = peaks-equity
    maximum_dd = float(np.max(drawdown))
    minimum_equity = float(np.min(np.minimum(equity, 0.0)))
    near(float(equity[-1]), cash, "場末時価")
    group_net = {campaign: group_gross[campaign]-charge for campaign, charge in group_fees.items()}
    nets = [x["net"] for x in derived]
    result = dict(symbol=symbol, session=ledger["session"], gross=gross, fees=total_fee, net=cash,
        profit=sum(x for x in nets if x > 0), loss=-sum(x for x in nets if x < 0),
        wins=sum(x > 0 for x in nets), losses=sum(x < 0 for x in nets), flats=sum(x == 0 for x in nets),
        winning_lots=sum(x["quantity"] for x in derived if x["net"] > 0),
        losing_lots=sum(x["quantity"] for x in derived if x["net"] < 0),
        flat_lots=sum(x["quantity"] for x in derived if x["net"] == 0),
        campaigns=entries, exits=exits, max_long=maximum[1], max_short=maximum[-1],
        max_drawdown=maximum_dd, min_equity=minimum_equity,
        max_equity=float(np.max(np.maximum(equity, 0.0))), trades=len(derived),
        max_campaign_loss=max((-x for x in group_net.values() if x < 0), default=0.0),
        campaign_profit=sum(x for x in group_net.values() if x > 0),
        campaign_loss=-sum(x for x in group_net.values() if x < 0),
        campaign_wins=sum(x > 0 for x in group_net.values()),
        campaign_losses=sum(x < 0 for x in group_net.values()),
        details=derived)
    return result, equity


def self_test() -> None:
    """機能: 独立会計器を売買反射・気配差・料金負け・全行DDで自己検査する。

    引数: なし。返り値: なし(None)。
    """
    for symbol in INITIAL:
        quantity = INITIAL[symbol]
        data = dict(seq=np.arange(6), time_s=np.array([0, 0, 1, 2, 3, 3.]),
            bid=np.array([99., 99., 100., 103., 101., 101.]),
            ask=np.array([100., 100., 101., 104., 102., 102.]),
            last=np.array([99., 100., 101., 104., 101., 101.]))
        for side in (1, -1):
            entry = data["ask" if side > 0 else "bid"][1]
            exit_price = data["bid" if side > 0 else "ask"][5]
            ledger = dict(symbol=symbol, session="人工", orders=[
                [1, 0, 1, side, quantity, entry, 1, 1],
                [5, 4, 1, -side, quantity, exit_price, 2, 0]],
                fees=[fee(symbol, quantity)]*2)
            result, equity = reconstruct(data, ledger)
            expected = side*quantity*(exit_price-entry)*POINT[symbol]-2*fee(symbol, quantity)
            near(result["net"], expected, "自己検査収支")
            near(float(equity[1]), -quantity*POINT[symbol]-fee(symbol, quantity), "新規直後の気配差と料金")
            independent_peak = 0.0
            independent_dd = 0.0
            for value in equity:
                independent_peak = max(independent_peak, value)
                independent_dd = max(independent_dd, independent_peak-value)
            near(result["max_drawdown"], independent_dd, "逐行清算DD")
    assert fee("TOPIX", 1) == 41 and fee("TOPIX", 5) == 209 and fee("TOPIX", 10) == 418
    assert fee("NK225", 10) == 110
    save(HERE/"独立会計器の自己検査.json", dict(合格=True, 検査=["気配約定", "同秒原本順序", "売買反射", "料金切捨て", "逐行清算DD"]))


if __name__ == "__main__":
    self_test()

