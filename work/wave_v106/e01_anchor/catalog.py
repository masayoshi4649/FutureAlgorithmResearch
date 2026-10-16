"""指値の基準価格だけを変える三対照。全条件は結果前に固定する。"""

import numpy as np

import common


def catalog() -> list[dict]:
    """
    機能: 同じ有利幅0.2ATRへ三つの当時参照値を割り当てる。
    引数: なし。
    返り値: list[dict]。元の途中判断・返済・数量は変えない。
    """
    return [dict(id='A_EXEC', mode='即時側', execution='気配指値', offset_atr=.2),
            dict(id='A_MID', mode='中値', execution='気配指値', offset_atr=.2),
            dict(id='A_PASSIVE', mode='受動側', execution='気配指値', offset_atr=.2)]


def anchors(ready: dict, quote: dict, feed: np.ndarray, mode: str) -> np.ndarray:
    """
    機能: 紙上新規が観測済みの行にだけ、正常気配から参照値を固定する。
    引数: ready/quote(dict)、feed(ndarray)、mode(str)は保存観測と三参照。
    返り値: ndarray[float64]。不正公開行はNaNのままで将来行へ移さない。
    """
    assert mode in ('即時側', '中値', '受動側')
    result = np.full(len(ready['last']), np.nan)
    for order in feed:
        if int(order[7]) != 1:
            continue
        row, side = int(order[0]), int(order[3])
        bid, ask = quote['bid'][row], quote['ask'][row]
        valid = quote['quote_valid'][row] and np.isfinite(bid) and np.isfinite(ask) and 0 < bid < ask
        if not valid:
            continue
        result[row] = (ask if side > 0 else bid) if mode == '即時側' else (
            (bid + ask) / 2 if mode == '中値' else bid if side > 0 else ask)
    return result
