"""表示範囲の境界を区別して板数量の変化を測り、最良気配OFIも独立に計算する。"""

from __future__ import annotations


def visible_or_better(price: float, book: dict, side: str) -> bool:
    """機能: 指定価格の現表示量を0と判定できる表示範囲にあるかを返す。

    引数: price(float)、book(dict[float,float])、side(str:bid/ask)。
    返り値: 表示範囲内または最良より良い価格ならTrue(bool)。遠方側10段外はFalse。
    """
    assert side in ('bid', 'ask') and book
    return price >= min(book) if side == 'bid' else price <= max(book)


def side_changes(before: dict, after: dict, side: str) -> dict:
    """機能: 共通価格差分・既知の表示消失/出現・遠方表示外の不明量を分ける。

    引数: before/after(dict[float,float]) は完全かつ正しい10段、side(str:bid/ask)。
    返り値: 表示数量の変化(dict)。取消・消費・注文主体の分類はしない。
    """
    assert before and after and side in ('bid', 'ask')
    common = before.keys() & after.keys()
    add = sum(max(0., after[price] - before[price]) for price in common)
    remove = sum(max(0., before[price] - after[price]) for price in common)
    disappeared, outside_old, appeared, outside_new = 0., 0., 0., 0.
    disappeared_prices, unknown_old_prices, appeared_prices, unknown_new_prices = [], [], [], []
    for price in before.keys() - after.keys():
        if visible_or_better(price, after, side):
            disappeared += before[price]
            disappeared_prices.append(price)
        else:
            outside_old += before[price]
            unknown_old_prices.append(price)
    for price in after.keys() - before.keys():
        if visible_or_better(price, before, side):
            appeared += after[price]
            appeared_prices.append(price)
        else:
            outside_new += after[price]
            unknown_new_prices.append(price)
    best = max if side == 'bid' else min
    old_best, new_best = best(before), best(after)
    worse = new_best < old_best if side == 'bid' else new_best > old_best
    best_disappeared = before[old_best] if worse else 0.
    assert not worse or old_best not in after
    return dict(common_add=add, common_remove=remove, known_disappeared=disappeared,
                known_appeared=appeared, unknown_old_quantity=outside_old,
                unknown_new_quantity=outside_new, known_add=add + appeared,
                known_remove=remove + disappeared, best_disappeared=best_disappeared,
                disappeared_prices=sorted(disappeared_prices), appeared_prices=sorted(appeared_prices),
                unknown_old_prices=sorted(unknown_old_prices), unknown_new_prices=sorted(unknown_new_prices))


def best_ofi(before_bid: tuple, before_ask: tuple, after_bid: tuple, after_ask: tuple) -> float:
    """機能: 二時点の最良価格・数量から標準的な最良気配OFIを求める。

    引数: before_bid/before_ask/after_bid/after_ask(tuple[float,float]) は価格と数量。
    返り値: 買い方向を正とする表示変化量(float)。実成行売買数量とは異なる。
    """
    old_bid, old_bid_qty = before_bid
    old_ask, old_ask_qty = before_ask
    bid, bid_qty = after_bid
    ask, ask_qty = after_ask
    bid_part = bid_qty if bid > old_bid else -old_bid_qty if bid < old_bid else bid_qty - old_bid_qty
    ask_part = old_ask_qty if ask > old_ask else -ask_qty if ask < old_ask else old_ask_qty - ask_qty
    return float(bid_part + ask_part)


def synthetic_checks() -> dict:
    """機能: 最良消失と遠方表示外を区別し、OFIの全価格変化分岐を合成値で検査する。

    引数: なし。返り値: 合格した具体例と検査結果(dict)。心理や取消を正解ラベルにしない。
    """
    before_bid = {100. - index: float(index + 1) for index in range(10)}
    lower_bid = {99. - index: float(index + 2) for index in range(10)}
    decline = side_changes(before_bid, lower_bid, 'bid')
    assert decline['known_disappeared'] == 1. and decline['best_disappeared'] == 1.
    assert decline['unknown_new_quantity'] == 11. and decline['known_appeared'] == 0.
    higher_bid = {101.: 7., **{price: qty for price, qty in before_bid.items() if price != 91.}}
    rise = side_changes(before_bid, higher_bid, 'bid')
    assert rise['unknown_old_quantity'] == 10. and rise['known_disappeared'] == 0.
    assert rise['known_appeared'] == 7.
    before_ask = {101. + index: float(index + 2) for index in range(10)}
    higher_ask = {102. + index: float(index + 3) for index in range(10)}
    ask_rise = side_changes(before_ask, higher_ask, 'ask')
    assert ask_rise['known_disappeared'] == 2. and ask_rise['best_disappeared'] == 2.
    assert ask_rise['unknown_new_quantity'] == 12.
    lower_ask = {100.: 8., **{price: qty for price, qty in before_ask.items() if price != 110.}}
    ask_fall = side_changes(before_ask, lower_ask, 'ask')
    assert ask_fall['unknown_old_quantity'] == 11. and ask_fall['known_disappeared'] == 0.
    assert ask_fall['known_appeared'] == 8.
    hole = {100.: 1., 98.: 3., 97.: 4.}
    covered = side_changes({100.: 1., 99.: 2., 98.: 3.}, hole, 'bid')
    assert covered['known_disappeared'] == 2. and covered['unknown_new_quantity'] == 4.
    assert best_ofi((100., 3.), (101., 4.), (100., 5.), (101., 2.)) == 4.
    assert best_ofi((100., 3.), (101., 4.), (99., 8.), (102., 6.)) == 1.
    assert best_ofi((100., 3.), (102., 4.), (101., 7.), (101.5, 9.)) == -2.
    # ----------------------------------------
    # 執行理由の入力を受け取らない。同一の表示遷移なら消費/取消の物語で値を変えない。
    assert side_changes(before_bid, lower_bid, 'bid') == decline
    return dict(合格=True, 板側合成ケース数=5, OFI分岐ケース数=3,
                最良買い消失例=decline, 遠方表示外の旧買い板例=rise,
                最良売り消失例=ask_rise, 遠方表示外の旧売り板例=ask_fall,
                範囲内未表示例=covered,
                消費取消='同一表示遷移を区別する入力がなく、原因を返さない。両者を識別したと主張しない。')
