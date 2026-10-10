"""複数玉・両建て台帳を、気配と注文だけで独立会計する。"""

from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
POINT = {"TOPIX": 1000, "NK225": 10}
CAP = {"TOPIX": 10, "NK225": 20}


def near(left: float, right: float, label: str) -> None:
    """機能: 円の演算誤差だけを許容して独立会計を照合する。

    引数: left/right(float)、label(str)。返り値: なし(None)。
    """
    assert abs(left - right) < 1.0e-4, (label, left, right)


def fee(symbol: str, quantity: int) -> int:
    """機能: 注文単位の片道料金を整数演算で切り捨てる。

    引数: symbol(str)、quantity(int)。返り値: 切捨て後の円額(int)。
    """
    assert quantity > 0
    return quantity * 418 // 10 if symbol == "TOPIX" else quantity * 11


def save(path: Path, value: object) -> None:
    """機能: 独立監査領域だけに有限 JSON を保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")


def reconstruct(data: dict, ledger: dict, require_flat: bool = True) -> tuple[dict, np.ndarray]:
    """機能: 役割別 FIFO・累積整数料金配賦・両建て評価を再構成する。

    引数: data(dict) は time_s/seq/bid/ask、ledger(dict) は symbol/session/orders。
    orders の列は fill_i/decision_i/cid/side/qty/price/reason/new/role。
    require_flat(bool) は全返済の要求。返り値: 会計指標と全行評価曲線(tuple)。
    """
    symbol = ledger["symbol"]
    multiplier = POINT[symbol]
    times = np.asarray(data["time_s"], dtype=float)
    sequence = np.asarray(data["seq"], dtype=np.int64)
    bids = np.asarray(data["bid"], dtype=float)
    asks = np.asarray(data["ask"], dtype=float)
    n = len(times)
    assert n > 0 and len(sequence) == len(bids) == len(asks) == n
    assert np.all(np.diff(sequence) > 0) and np.all(np.diff(times) >= 0)
    valid = np.isfinite(bids) & np.isfinite(asks) & (bids > 0) & (asks >= bids)
    prior_valid = np.maximum.accumulate(np.where(valid, np.arange(n), -1))
    long_mark = np.concatenate(([0.0], bids))[prior_valid + 1]
    short_mark = np.concatenate(([0.0], asks))[prior_valid + 1]
    valid_rows = np.flatnonzero(valid)
    fifo = defaultdict(deque)
    held = {1: 0, -1: 0}
    maximum = {1: 0, -1: 0}
    group_fees, group_gross = defaultdict(int), defaultdict(float)
    role_fees, role_gross = defaultdict(float), defaultdict(float)
    cash = gross = 0.0
    total_fee = entries = exits = 0
    prior_row = -1
    order_rows, cashes, longs, shorts, details = [], [], [], [], []
    campaigns = set()
    for order in ledger["orders"]:
        assert len(order) == 9, ("注文列数", len(order))
        row, source, cid, side, quantity, price, reason, opened, role = order
        row, source, cid, side, quantity, reason, opened, role = map(
            int, (row, source, cid, side, quantity, reason, opened, role))
        price = float(price)
        assert 0 <= source < row < n and row >= prior_row, ("判断と約定順序", order)
        assert sequence[source] < sequence[row]
        assert side in (-1, 1) and opened in (0, 1) and role in (0, 1)
        assert quantity > 0 and np.isfinite(price) and price > 0
        assert valid[row], ("無効気配約定", order)
        first_valid = valid_rows[np.searchsorted(valid_rows, source, side="right")]
        assert row == first_valid, ("次の有効気配行", order, first_valid)
        near(price, float(asks[row] if side == 1 else bids[row]), "売買気配約定")
        charge = fee(symbol, quantity)
        total_fee += charge
        group_fees[cid] += charge
        role_fees[role] += charge
        campaigns.add(cid)
        if opened:
            fifo[(cid, side, role)].append([row, quantity, price, charge, quantity, 0])
            held[side] += quantity
            entries += 1
        else:
            assert held[-side] >= quantity, ("返済数量", order, held)
            held[-side] -= quantity
            exits += 1
            remaining = quantity
            exit_closed = 0
            while remaining:
                key = (cid, -side, role)
                assert fifo[key], ("返済対象役割の FIFO", order, key)
                lot = fifo[key][0]
                take = min(remaining, lot[1])
                profit = take * (-side) * (price - lot[2]) * multiplier
                charge_open = lot[3] * (lot[5] + take) // lot[4] - lot[3] * lot[5] // lot[4]
                charge_close = charge * (exit_closed + take) // quantity - charge * exit_closed // quantity
                net = profit - charge_open - charge_close
                gross += profit
                group_gross[cid] += profit
                role_gross[role] += profit
                details.append(dict(campaign=cid, entry_row=lot[0], exit_row=row,
                    side=-side, quantity=take, entry=lot[2], exit=price, reason=reason,
                    role=role, entry_fee=charge_open, exit_fee=charge_close,
                    gross=profit, net=net))
                remaining -= take
                lot[1] -= take
                lot[5] += take
                exit_closed += take
                if not lot[1]:
                    fifo[key].popleft()
        assert held[1] <= CAP[symbol] and held[-1] <= CAP[symbol], ("片方向上限", order, held)
        maximum[1] = max(maximum[1], held[1])
        maximum[-1] = max(maximum[-1], held[-1])
        cash -= side * quantity * price * multiplier + charge
        order_rows.append(row)
        cashes.append(cash)
        longs.append(held[1])
        shorts.append(held[-1])
        prior_row = row
    if require_flat:
        assert held[1] == held[-1] == 0, ("場内未返済", held)
        assert all(not value for value in fifo.values())
        near(cash, gross - total_fee, "全玉返済後の現金")
        near(sum(x["net"] for x in details), cash, "部分返済の料金配賦合計")

    # ----------------------------------------
    # 両建ては買玉と売玉を別の気配で清算し、含み損を隠さない。
    indices = np.searchsorted(np.asarray(order_rows, dtype=np.int64), np.arange(n), side="right") - 1
    extended_cash = np.concatenate(([0.0], np.asarray(cashes, dtype=float)))[indices + 1]
    extended_long = np.concatenate(([0], np.asarray(longs, dtype=np.int64)))[indices + 1]
    extended_short = np.concatenate(([0], np.asarray(shorts, dtype=np.int64)))[indices + 1]
    equity = extended_cash + multiplier * (extended_long * long_mark - extended_short * short_mark)
    peaks = np.maximum.accumulate(np.maximum(equity, 0.0))
    group_net = {cid: group_gross[cid] - group_fees[cid] for cid in campaigns}
    nets = [x["net"] for x in details]
    result = dict(symbol=symbol, session=ledger["session"], gross=gross, fees=total_fee,
        net=float(equity[-1]), profit=sum(x for x in nets if x > 0),
        loss=-sum(x for x in nets if x < 0), wins=sum(x > 0 for x in nets),
        losses=sum(x < 0 for x in nets), flats=sum(x == 0 for x in nets),
        winning_lots=sum(x["quantity"] for x in details if x["net"] > 0),
        losing_lots=sum(x["quantity"] for x in details if x["net"] < 0),
        flat_lots=sum(x["quantity"] for x in details if x["net"] == 0),
        campaigns=len(campaigns), entry_orders=entries, exit_orders=exits,
        max_long=maximum[1], max_short=maximum[-1], trades=len(details),
        drawdown=float(np.max(peaks - equity)), equity_min=float(np.min(np.minimum(equity, 0.0))),
        equity_max=float(np.max(np.maximum(equity, 0.0))),
        max_campaign_loss=max((-x for x in group_net.values() if x < 0), default=0.0),
        campaign_profit=sum(x for x in group_net.values() if x > 0),
        campaign_loss=-sum(x for x in group_net.values() if x < 0),
        campaign_wins=sum(x > 0 for x in group_net.values()),
        campaign_losses=sum(x < 0 for x in group_net.values()),
        campaign_flats=sum(x == 0 for x in group_net.values()),
        role_net={str(role): role_gross[role] - role_fees[role] for role in (0, 1)},
        core_net=role_gross[0] - role_fees[0], cover_net=role_gross[1] - role_fees[1],
        details=details, curve_hash=hashlib.sha256(equity.tobytes()).hexdigest())
    return result, equity


def self_test() -> None:
    """機能: 両建て・部分返済・料金切捨てと減玉対照を自己検査する。

    引数: なし。返り値: なし(None)。
    """
    bids = np.array([100., 100., 98., 97., 95., 96., 99., 101., 102.])
    data = dict(seq=np.arange(9), time_s=np.arange(9, dtype=float), bid=bids, ask=bids+1)
    orders = np.array([
        [1, 0, 1, 1, 10, 101., 10, 1, 0],
        [2, 1, 1, -1, 3, 98., 20, 1, 1],
        [3, 2, 1, -1, 2, 97., 20, 1, 1],
        [5, 4, 1, 1, 4, 97., 21, 0, 1],
        [6, 5, 1, 1, 1, 100., 21, 0, 1],
        [7, 6, 1, -1, 4, 101., 22, 0, 0],
        [8, 7, 1, -1, 6, 102., 23, 0, 0]], dtype=float)
    result, curve = reconstruct(data, dict(symbol="TOPIX", session="人工", orders=orders))
    assert result["max_long"] == 10 and result["max_short"] == 5
    assert result["trades"] == 5
    near(result["gross"], 6000., "両建て人工粗損益")
    near(sum(x["entry_fee"] for x in result["details"]), 626., "新規手数料配賦")
    near(sum(x["exit_fee"] for x in result["details"]), 625., "返済手数料配賦")
    near(result["net"], 4749., "両建て人工手数料後収支")
    wrong = 7 * 98 * POINT["TOPIX"]
    correct = (10 * 98 - 3 * 99) * POINT["TOPIX"]
    assert wrong - correct == 3000

    # ----------------------------------------
    # 同じ露出経路なら両建ての損益は減玉・再取得と同じ粗値になる。
    reduced = orders.copy()
    reduced[1:3, 7:9] = [0, 0]
    reduced[3:5, 7:9] = [1, 0]
    reduced_result, reduced_curve = reconstruct(data, dict(symbol="TOPIX", session="人工", orders=reduced))
    near(reduced_result["gross"], result["gross"], "同一露出経路の粗損益対照")
    near(reduced_result["net"], result["net"], "同一注文数量の料金対照")
    assert np.all(curve <= reduced_curve + 1.e-8)
    assert np.min(curve - reduced_curve) == -5000
    allocation_cases = 0
    for symbol, cap in CAP.items():
        for quantity in range(1, cap + 1):
            charged = fee(symbol, quantity)
            for split in range(1, quantity + 1):
                chunks = [split] * (quantity // split)
                if quantity % split:
                    chunks.append(quantity % split)
                previous = cumulative = total = 0
                for chunk in chunks:
                    cumulative += chunk
                    current = charged * cumulative // quantity
                    total += current - previous
                    previous = current
                assert cumulative == quantity and total == charged
                allocation_cases += 1
    save(HERE / "独立会計器の自己検査.json", dict(合格=True,
        検査=["同方向役割別 FIFO", "部分返済料金配賦", "片方向上限", "両建て全玉 MTM",
            "注文単位切捨て", "同一露出経路の減玉対照"],
        両建て収支=result["net"], 減玉対照収支=reduced_result["net"],
        MTM気配差最大=float(np.max(reduced_curve - curve)),
        料金配賦組合せ=allocation_cases))


if __name__ == "__main__":
    self_test()
