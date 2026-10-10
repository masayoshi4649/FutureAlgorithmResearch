"""提示された注文単位手数料を、整数演算で正確に計上する。"""


def order_fee(symbol: str, quantity: int) -> int:
    """機能: 一注文ごとに端数を切り捨てた手数料を求める。

    引数: symbol(str) は TOPIX または NK225、quantity(int) は注文の実約定枚数。
    返り値: 税込手数料の円整数(int)。TOPIX mini は floor(41.8×枚数)、NK micro は11×枚数。
    """
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ValueError('実約定枚数は正の整数で指定してください')
    if symbol == 'TOPIX':
        return 418 * quantity // 10
    if symbol == 'NK225':
        return 11 * quantity
    raise ValueError(f'未知の銘柄: {symbol}')


def instrument(symbol: str) -> dict:
    """機能: 比較で固定する小型契約の数量・価格倍率・上限・注文手数料を返す。

    引数: symbol(str) はラージ板の銘柄識別子。
    返り値: qty/value/max_qty/fee の辞書(dict)。売買方向や市場の状態では変更しない。
    """
    if symbol == 'TOPIX':
        quantity, value, maximum = 5, 1000., 10
    elif symbol == 'NK225':
        quantity, value, maximum = 10, 10., 20
    else:
        raise ValueError(f'未知の銘柄: {symbol}')
    return {'qty': quantity, 'value': value, 'max_qty': maximum, 'fee': order_fee(symbol, quantity)}
