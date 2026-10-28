"""費用0の研究会計。元の約定・親・玉別集計をAST複製し、費用定義だけを0へ変更した。

common139.accountのfee代入とcommon143.accountの会計呼出先以外の演算を変えない。
売買生成、注文価格、判断行、数量、残玉判定を変更する機能は持たない。
"""

import numpy as np
import source145 as source

product = source.shared.prior.common.product
holding = source.shared.holding

def financial_account(orders, times, quotes, label, scene, symbol):
    """
    機能: 全注文を商品別に会計し、親・玉UIDの費用後損益を集計する。
    引数: orders/times(ndarray)、quotes(dict)、label/scene/symbol(str)。
    返り値: dictは場・親・玉別損益、枚数、参入数。時価残玉は認めない。
    """
    settings = product(symbol)
    fee = 0
    mult = settings['multiplier']
    parents = {}
    tickets = {}
    held = {1: 0, -1: 0}
    maximum = entries = quantity = 0
    for o in orders:
        i, d, cid, side, qty = map(int, o[:5])
        new = int(o[7])
        uid = int(o[8])
        paid = int(o[9])
        px = float(o[5])
        assert 0 <= d < i < len(times) and side in (-1, 1) and (qty > 0) and (paid == qty * fee // 10)
        assert quotes['quote_valid'][i] and abs(px - (quotes['ask'][i] if side > 0 else quotes['bid'][i])) < 1e-07
        p = parents.setdefault(cid, dict(id=cid, gross=0.0, fees=0.0, side=side, entry=i, exit=i, legs={}))
        leg = p['legs'].setdefault(str(uid), dict(gross=0.0, fees=0.0, entries=0, quantity=0))
        key = (cid, uid)
        p['fees'] += paid
        leg['fees'] += paid
        p['exit'] = i
        if new:
            assert key not in tickets
            tickets[key] = [qty, px, side]
            held[side] += qty
            entries += 1
            quantity += qty
            leg['entries'] += 1
            leg['quantity'] += qty
        else:
            old = tickets[key]
            assert old[0] >= qty and old[2] == -side
            gain = old[2] * (px - old[1]) * qty * mult
            old[0] -= qty
            held[-side] -= qty
            p['gross'] += gain
            leg['gross'] += gain
        assert all((0 <= x <= 10 for x in held.values()))
        maximum = max(maximum, *held.values())
    assert not any(held.values()) and all((t[0] == 0 for t in tickets.values()))
    for p in parents.values():
        p['net'] = p['gross'] - p['fees']
        for leg in p['legs'].values():
            leg['net'] = leg['gross'] - leg['fees']
    gains = sum((p['net'] for p in parents.values() if p['net'] > 0))
    loss = -sum((p['net'] for p in parents.values() if p['net'] < 0))
    cash = float(np.sum(-orders[:, 3] * orders[:, 4] * orders[:, 5] * mult - orders[:, 9])) if len(orders) else 0.0
    assert abs(gains - loss - cash) < 1e-05
    return dict(method=label, session=scene, kind=scene.split('_')[1], symbol=symbol, profit=gains, loss=loss, net=gains - loss, gross=sum((p['gross'] for p in parents.values())), fees=sum((p['fees'] for p in parents.values())), entries=entries, quantity=quantity, max_per_side=maximum, parents=list(parents.values()))


def account(orders, packet, method, label):
    """
    機能: 全注文を元会計で計上し、終了後だけ始終値分類を評価列へ接続する。
    引数: orders(ndarray)、packet(dict)、method(str)、label(dict)は注文と事後評価資料。
    返り値: dictは一場の全損益・深夜除外率・分類。終値を売買関数へ渡さない。
    """
    scene = packet['session']
    ready = packet['inputs'][scene, 'NK225']
    quotes = packet['quotes'][scene, 'NK225']
    result = financial_account(orders, ready['time_s'], quotes, method, scene, 'NK225')
    parents = result.pop('parents')
    result['parent_count'] = len(parents)
    result['parent_records'] = [{k: v for k, v in p.items() if k != 'legs'} for p in parents]
    result['buy_sell'] = {}
    for side, name in ((1, '買い'), (-1, '売り')):
        chosen = [p for p in parents if p['side'] == side]
        result['buy_sell'][name] = dict(parents=len(chosen), profit=sum((p['net'] for p in chosen if p['net'] > 0.0)), loss=-sum((p['net'] for p in chosen if p['net'] < 0.0)), net=sum((p['net'] for p in chosen)))
    entries = orders[orders[:, 7] == 1]
    result['first_minutes'] = float((ready['time_s'][int(entries[0, 0])] - ready['start']) / 60.0) if len(entries) else None
    result['split'] = '既知開発50場'
    index = orders[:, 0].astype(int)
    mid = (quotes['bid'][index] + quotes['ask'][index]) * 0.5
    result['midpoint_gross'] = float(np.sum(-orders[:, 3] * orders[:, 4] * mid * 100.0))
    result['bbo_drag'] = result['midpoint_gross'] - result['gross']
    result.update(holding(orders, ready))
    result.update(direction=label['direction'], opening=label['first_price'], closing=label['final_price'], market_change=label['change'], close_time=label['final_price_time'], close_basis=label['basis'])
    return result
