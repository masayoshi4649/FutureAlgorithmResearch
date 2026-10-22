"""複数の返済注文を同じ行へ集約せず、各注文料金を決済脚へ配賦する。"""

from collections import defaultdict, deque
import numpy as np

VALUES = {'TOPIX': 1000., 'NK225': 10.}
FEES = {'TOPIX': 41.8, 'NK225': 11.}


def allocate_exit_fees(orders, charge, trades):
    """
    機能: 同一親組・同一行の複数返済注文も、順序を保って各脚へ課金する。
    引数: orders/charge/trades(ndarray)は注文・注文料・返済脚。
    返り値: ndarray[float]。各返済脚へ配賦した返済注文料。
    """
    queues = defaultdict(deque)
    for order, fee in zip(orders, charge):
        if order[7] == 0:
            key = (int(order[2]), int(order[0]), int(order[3]), float(order[5]), int(order[6]))
            queues[key].append([int(order[4]), float(fee)/order[4]])
    allocated = np.zeros(len(trades))
    for index, trade in enumerate(trades):
        key = (int(trade[0]), int(trade[7]), -int(trade[2]), float(trade[5]), int(trade[9]))
        remaining = int(trade[3])
        while remaining:
            assert queues[key], '対応する返済注文数量が不足しています'
            head = queues[key][0]
            quantity = min(remaining, head[0])
            allocated[index] += quantity*head[1]
            remaining -= quantity
            head[0] -= quantity
            if head[0] == 0:
                queues[key].popleft()
    assert all(not queue for queue in queues.values()), '返済注文に未配賦の数量があります'
    assert abs(allocated.sum()-charge[orders[:, 7]==0].sum()) < 1e-7
    return allocated


# ----------------------------------------
# 元会計の円倍率・利益分類・時価計算を保ち、返済料金の対応だけ修正する。


def account(ready: dict, result: dict, config: dict) -> tuple:
    """機能: 全注文に料金を課し、決済別・組別・時価の会計を検算する。

    引数: ready/result/config(dict)。返り値: 集計・台帳・料金後時価(tuple)。
    """
    symbol = ready['symbol']
    orders, trades, cycles = result['orders'], result['trades'], result['cycles']
    scale, fee = VALUES[symbol], FEES[symbol]
    charge = np.floor(orders[:, 4] * fee + 1e-8)
    entries = {(int(o[2]), int(o[0])): (int(o[4]), f, float(o[5]))
        for o, f in zip(orders, charge) if o[7] == 1}
    exit_charge = allocate_exit_fees(orders, charge, trades)
    nets, details = [], []
    for trade_index, trade in enumerate(trades):
        cid, qty, entry_row, exit_row = int(trade[0]), int(trade[3]), int(trade[6]), int(trade[7])
        initial_qty, entry_fee, price = entries[cid, entry_row]
        assert abs(price - trade[4]) < 1e-8
        gross = float(trade[10] * scale)
        allocated = qty * entry_fee / initial_qty + exit_charge[trade_index]
        net = gross - allocated
        nets.append(net)
        details.append(dict(組=cid, 方向=int(trade[2]), 枚数=qty, 新規行=entry_row, 返済行=exit_row,
            新規原本行=int(ready['seq'][entry_row]), 返済原本行=int(ready['seq'][exit_row]),
            新規時刻=float(ready['time_s'][entry_row]), 返済時刻=float(ready['time_s'][exit_row]),
            建値=float(trade[4]), 返済値=float(trade[5]), 理由=int(trade[9]), 利益損失前=gross, 手数料=allocated, 収支=net))
    nets = np.asarray(nets)
    q = trades[:, 3]
    assert abs(float(nets.sum()) - (float(trades[:, 10].sum() * scale) - float(charge.sum()))) < 1e-5
    grouped = np.asarray([sum(t['収支'] for t in details if t['組'] == int(c[0])) for c in cycles])
    risk = np.asarray([c[4] * scale for c in cycles])
    fee_curve = np.zeros(len(ready['last']))
    np.add.at(fee_curve, orders[:, 0].astype(int), charge)
    equity = result['curve'][:, 0] * scale - np.cumsum(fee_curve)
    assert abs(equity[-1] - nets.sum()) < 1e-5
    assert result['stats'][9] == 0
    running = np.maximum.accumulate(np.maximum(equity, 0))
    row = dict(session=ready['session'], symbol=symbol, gross=float(trades[:, 10].sum() * scale),
        fees=int(charge.sum()), net=float(nets.sum()), profit=float(nets[nets > 0].sum()), loss=float(-nets[nets < 0].sum()),
        wins=int((nets > 0).sum()), losses=int((nets < 0).sum()), flats=int((nets == 0).sum()),
        winning_lots=int(q[nets > 0].sum()), losing_lots=int(q[nets < 0].sum()), flat_lots=int(q[nets == 0].sum()),
        campaigns=len(cycles), campaign_wins=int((grouped > 0).sum()), campaign_losses=int((grouped < 0).sum()),
        campaign_profit=float(grouped[grouped > 0].sum()), campaign_loss=float(-grouped[grouped < 0].sum()),
        sum_r=float((grouped / risk).sum()) if len(risk) else 0.,
        max_drawdown=float((running - equity).max(initial=0)),
        max_long=int(result['stats'][2]), max_short=int(result['stats'][3]),
        reason_counts={str(r): sum(t['理由'] == r for t in details) for r in (1, 2, 7, 8, 9, 30, 32)})
    row['win_rate'] = row['wins'] / max(1, row['wins'] + row['losses'] + row['flats'])
    row['payoff'] = (row['profit'] / row['wins']) / (row['loss'] / row['losses']) if row['wins'] and row['losses'] else None
    row['lot_payoff'] = (row['profit'] / row['winning_lots']) / (row['loss'] / row['losing_lots']) if row['winning_lots'] and row['losing_lots'] else None
    row['campaign_payoff'] = (row['campaign_profit'] / row['campaign_wins']) / (row['campaign_loss'] / row['campaign_losses']) if row['campaign_wins'] and row['campaign_losses'] else None
    return row, dict(session=ready['session'], symbol=symbol, config=config, orders=orders.tolist(), trades=details,
        cycles=cycles.tolist(), fees=charge.tolist()), equity
