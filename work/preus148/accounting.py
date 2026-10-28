"""玉IDの現金と評価額を照合する、売買判断を持たない研究会計。"""

from datetime import datetime, timezone, timedelta
import numpy as np

JST = timezone(timedelta(hours=9))


def clock(value):
    """日本時間へ表記を変換する。

    引数: value(float)はUNIX秒。
    返り値: strは時差付きの時刻。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def account(orders, data, allow_open=False, strict_next=True):
    """全約定を玉・親別に集計し、実現損益と評価損益を分離する。

    引数: orders(ndarray[N,10])、data(dict)、allow_open(bool)、strict_next(bool)。
    返り値: dictは損益・枚数・親取引と約定明細。未返済を黒字集計へ混ぜない。
    """
    orders = np.asarray(orders, float).reshape(-1, 10)
    times, quotes = data['ready']['time_s'], data['quotes']
    good = quotes['quote_valid'] & np.isfinite(quotes['bid']) & np.isfinite(quotes['ask']) & (quotes['ask'] > quotes['bid']) & (quotes['bid'] > 0)
    parents, tickets, records = {}, {}, []
    max_side = entries = quantity = 0
    last_fill = -1
    for row in orders:
        fill, decided, parent, side, qty = map(int, row[:5])
        px, reason, new, uid, fee = row[5:]
        key = (parent, int(uid))
        assert 0 <= decided < fill < len(times) and fill >= last_fill
        last_fill = fill
        assert side in (-1, 1) and qty > 0 and qty == row[4] and fee == 0
        assert good[fill] and px == (quotes['ask'][fill] if side == 1 else quotes['bid'][fill])
        if strict_next:
            assert not good[decided+1:fill].any(), (decided, fill)
        item = parents.setdefault(parent, dict(id=parent, side=side, net=0., entry=fill, exit=fill, closed=True))
        gain = 0.
        if new:
            assert key not in tickets
            tickets[key] = dict(side=side, qty=qty, entry=px, entry_index=fill)
            entries += 1
            quantity += qty
        else:
            old = tickets[key]
            assert old['side'] == -side and old['qty'] >= qty
            gain = old['side'] * (px - old['entry']) * qty * 100.
            old['qty'] -= qty
            item['net'] += gain
            item['exit'] = fill
        maximum = max(sum(t['qty'] for t in tickets.values() if t['side'] == d) for d in (-1, 1))
        assert maximum <= 10
        max_side = max(max_side, maximum)
        records.append(dict(time=clock(times[fill]), decision_time=clock(times[decided]), parent=parent, uid=int(uid),
                            side='買い' if side == 1 else '売り', new=bool(new), qty=qty, price=px, reason=int(reason), pnl=gain))
    # ----------------------------------------
    # 途中場は未返済の玉を返済気配で評価し、完結親の利益損失と分けて残す。
    last = int(np.flatnonzero(good)[-1])
    positions, unrealized = [], 0.
    for (parent, uid), ticket in tickets.items():
        if not ticket['qty']:
            continue
        parents[parent]['closed'] = False
        mark = quotes['bid'][last] if ticket['side'] == 1 else quotes['ask'][last]
        pnl = ticket['side'] * (mark - ticket['entry']) * ticket['qty'] * 100.
        unrealized += pnl
        positions.append(dict(parent=parent, uid=uid, **ticket, mark=mark, unrealized=pnl))
    assert allow_open or not positions
    closed = [p for p in parents.values() if p['closed']]
    profit = sum(p['net'] for p in closed if p['net'] > 0)
    loss = -sum(p['net'] for p in closed if p['net'] < 0)
    realized = sum(p['net'] for p in parents.values())
    cash = float(np.sum(-orders[:, 3] * orders[:, 4] * orders[:, 5] * 100.))
    market = sum(t['side'] * t['qty'] * (quotes['bid'][last] if t['side'] == 1 else quotes['ask'][last]) * 100. for t in tickets.values())
    assert abs(cash + market - realized - unrealized) < 1e-5
    if not positions:
        assert abs(profit - loss - realized) < 1e-5
    for p in parents.values():
        p['entry_time'] = clock(times[p['entry']])
        p['exit_time'] = clock(times[p['exit']])
    return dict(profit=profit, loss=loss, net=realized, unrealized=unrealized, equity=realized+unrealized,
                entries=entries, quantity=quantity, max_per_side=max_side, parent_count=len(parents),
                parents=list(parents.values()), positions=positions, records=records)


def summary(rows):
    """同条件の複数場を、赤字頻度と深さも含めて集計する。

    引数: rows(list[dict])は完了場だけの会計。
    返り値: dictは総損益・中央値・上位3黒字除外後収支。
    """
    values = np.array([row['net'] for row in rows], float)
    losses = values[values < 0]
    profit, loss = sum(r['profit'] for r in rows), sum(r['loss'] for r in rows)
    return dict(sessions=len(rows), profit=profit, loss=loss, net=float(values.sum()), pf=profit/loss if loss else None,
                wins=int((values > 0).sum()), losses=len(losses), zero=int((values == 0).sum()),
                maxloss=float(-losses.min()) if len(losses) else 0.,
                avgloss=float(-losses.mean()) if len(losses) else 0.,
                medianloss=float(-np.median(losses)) if len(losses) else 0., median=float(np.median(values)),
                ex3=float(values.sum()-sum(sorted(values[values > 0], reverse=True)[:3])),
                entries=sum(row['entries'] for row in rows), zero_entries=sum(row['entries'] == 0 for row in rows))
