"""注文から再構成する独立会計。旧式の有限配列の極値走査だけを高速化。

生成元は v29 selected_accounting_audit.py の close / integer / reconstruct。
注文・元建玉・現金・数量・損益・曲線・上限・場末の検査は旧式を保持する。
最初に価格の全有限・正値を検査し、注文値の有限性も全件検査する。
その後の非空で有限な配列に対する極値だけを NumPy reduction へ置換する。
旧モジュールや売買エンジンを呼び出さない。生成器の逆置換で本文同値を検査済み。
"""

from __future__ import annotations

import numpy as np

MULT = {'TOPIX': 1000., 'NK225': 10.}
CAP = {'TOPIX': 10, 'NK225': 20}


def close(left: object, right: object, label: str) -> None:
    """機能: 金額・価格の浮動小数誤差だけを許容して比較する。

    引数: left/right (object) は比較値、label (str) は比較名。返り値: なし (None)。
    """
    np.testing.assert_allclose(left, right, atol=1e-6, rtol=0, err_msg=label)


def integer(value: float, label: str) -> int:
    """機能: 数量・行番号が厳密な整数であることを検査する。

    引数: value (float)、label (str)。返り値: 整数値 (int)。
    """
    assert np.isfinite(value) and value == round(value), label
    return int(value)


def reconstruct(ready: dict, result: dict, symbol: str, closed: bool = True) -> tuple[dict, dict]:
    """機能: 約定注文から現金・在庫を、元建玉と返済から実現損益を再構成する。

    引数: ready/result (dict)、symbol (str)、closed (bool) は全返済を要求するか。
    返り値: 独立集計と独立時系列 (tuple[dict,dict])。エンジンの損益欄は比較先にしか使わない。
    """
    prices, times = ready['last'], ready['time_s']
    n = len(prices)
    assert n > 1 and np.isfinite(prices).all() and (prices > 0).all()
    assert np.all(np.diff(times) >= 0)
    orders, trades, cycles = (result[k] for k in ('orders', 'trades', 'cycles'))
    assert orders.shape[1] == 8 and trades.shape[1] == 11 and cycles.shape[1] == 10
    cash_change, long_change, short_change, realized_change = (np.zeros(n) for _ in range(4))
    legs, pnl, quantities, campaign_pnl = [], [], [], {}
    campaigns, reasons = {}, {}
    long_qty = short_qty = 0
    close_index, last_fill = 0, -1
    # ----------------------------------------
    # 一枚でも元建玉の数量を超えて返済すれば失敗する。損失玉も同じ経路で計上する。
    for order in orders:
        row, source, campaign, side, qty, price, reason, opening = order
        row, source, campaign, side, qty, reason, opening = [integer(v, '注文の整数欄') for v in
                                                            (row, source, campaign, side, qty, reason, opening)]
        assert 0 <= source < row < n and row >= last_fill
        assert side in (-1, 1) and qty > 0 and opening in (0, 1)
        assert np.isfinite(price) and price > 0 and campaign >= 0
        assert times[row] >= ready['start'] and times[row] <= ready['limit'] + 300
        last_fill = row
        cash_change[row] -= side * qty * price
        campaigns.setdefault(campaign, []).append(row)
        reasons[campaign] = reason
        if opening:
            assert reason in (20, 21, 22, 23)
            legs.append({'side': side, 'qty': qty, 'remaining': qty, 'price': price,
                         'row': row, 'campaign': campaign})
            if side == 1:
                long_qty += qty
                long_change[row] += qty
            else:
                short_qty += qty
                short_change[row] += qty
        else:
            assert close_index < len(trades), '返済注文に対応する明細がない'
            trade = trades[close_index]
            close_index += 1
            leg_id = integer(trade[1], '元建玉番号')
            assert 0 <= leg_id < len(legs)
            leg = legs[leg_id]
            assert leg['remaining'] >= qty and leg['row'] < row
            close(trade[[0, 2, 3, 4, 5, 6, 7, 9]],
                  [campaign, -side, qty, leg['price'], price, leg['row'], row, reason], '注文と元建玉の照合')
            assert leg['side'] == -side and leg['campaign'] == campaign
            assert integer(trade[8], '主玉・カバー区分') in (0, 1)
            value = leg['side'] * qty * (price - leg['price'])
            close(trade[10], value, '返済損益を建値・枚数から再計算')
            pnl.append(value)
            quantities.append(qty)
            campaign_pnl[campaign] = campaign_pnl.get(campaign, 0.) + value
            realized_change[row] += value
            leg['remaining'] -= qty
            if leg['side'] == 1:
                long_qty -= qty
                long_change[row] -= qty
            else:
                short_qty -= qty
                short_change[row] -= qty
        assert 0 <= long_qty <= CAP[symbol] and 0 <= short_qty <= CAP[symbol], '注文途中の保有上限'
    assert close_index == len(trades), '注文が存在しない返済明細'
    if closed:
        assert long_qty == short_qty == 0 and all(x['remaining'] == 0 for x in legs)
    # ----------------------------------------
    # 時価曲線は約定金額と現在価格だけで計算し、エンジン内の実現損益を使わない。
    cash = np.cumsum(cash_change)
    longs, shorts = np.cumsum(long_change), np.cumsum(short_change)
    net = longs - shorts
    equity = cash + net * prices
    realized = np.cumsum(realized_change)
    high = np.maximum.accumulate(np.maximum(0., equity))
    drawdown = np.maximum.accumulate(high - equity)
    curve = result['curve']
    assert curve.shape == (n, 8), 'detail=True の曲線が必要'
    independent = np.column_stack([equity, realized, longs, shorts, drawdown, cash, net])
    close(curve[:, :7], independent, '全観測行の現金・保有・時価・最大下落')
    close(result['stats'][:6], [realized[-1], drawdown[-1], np.max(longs), np.max(shorts),
                               np.max(longs + shorts), np.max(abs(net))], '集計検算')
    close(result['stats'][7:10], [min(0., np.min(equity)), max(0., np.max(equity)), long_qty + short_qty], '残玉と最大最小時価')
    completed = []
    for cycle in cycles:
        campaign = integer(cycle[0], '組番号')
        rows = campaigns[campaign]
        first, last = min(rows), max(rows)
        assert all(x['remaining'] == 0 for x in legs if x['campaign'] == campaign)
        close(cycle[[1, 2, 3, 6, 7]], [first, last, campaign_pnl.get(campaign, 0.),
                    np.max((longs + shorts)[first:last + 1]), np.max(abs(net[first:last + 1]))], '組単位の損益と最大枚数')
        assert cycle[4] > 0 and cycle[5] > 0
        completed.append(campaign)
    assert len(set(completed)) == len(completed)
    if closed:
        assert set(completed) == set(campaigns), '全玉返済済みの組が集計から脱落'
        close(cash[-1], sum(pnl), '全返済後の現金と全損益')
    at_limit = np.flatnonzero(times >= ready['limit'])
    if closed and len(at_limit) > 1:
        after = int(at_limit[0]) + 1
        assert not (longs[after:] + shorts[after:]).any(), '場末判断の次観測以降に持越し'
    values, units = np.asarray(pnl) * MULT[symbol], np.asarray(quantities)
    wins, losses = values > 1e-6, values < -1e-6
    cv = np.asarray([campaign_pnl[x] for x in completed]) * MULT[symbol]
    summary = {'symbol': symbol, 'session': ready.get('session', '合成'),
               'gross_profit_yen': float(values[wins].sum()), 'gross_loss_yen': float(-values[losses].sum()),
               'net_yen': float(values.sum()), 'profit_units': int(units[wins].sum()),
               'loss_units': int(units[losses].sum()), 'zero_units': int(units[~(wins | losses)].sum()),
               'closed_units': int(units.sum()), 'max_long': int(np.max(longs)), 'max_short': int(np.max(shorts)),
               'drawdown_yen': float(drawdown[-1] * MULT[symbol]),
               'min_equity_yen': float(min(0., np.min(equity)) * MULT[symbol]),
               'max_equity_yen': float(max(0., np.max(equity)) * MULT[symbol]),
               'cycles': len(cycles), 'cycle_wins': int((cv > 0).sum()), 'cycle_losses': int((cv < 0).sum()),
               'cycle_profit_yen': float(cv[cv > 0].sum()), 'cycle_loss_yen': float(-cv[cv < 0].sum()),
               '新規注文数': len(legs), '返済明細数': len(trades), '検算した観測行数': n,
               '最終残玉': int(long_qty + short_qty), '買い返済枚数': int(sum(t[3] for t in trades if t[2] > 0)),
               '売り返済枚数': int(sum(t[3] for t in trades if t[2] < 0))}
    return summary, {'equity': equity, 'realized': realized, 'cash': cash, 'long': longs, 'short': shorts}
