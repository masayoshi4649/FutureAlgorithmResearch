"""機能: 両建てと縮小・復帰のキャッシュフロー同等性を人工気配で独立確認する。"""

import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def fee(quantity, rate):
    """機能: 注文全体の片道手数料を1円未満切捨てで計算する。

    引数: quantity(int)は枚数、rate(float)は1枚の片道料金。
    返り値: intの注文料金。数量0の場合は0。
    """
    return math.floor(quantity * rate + 1e-9)


def order(cash, side, quantity, bid, ask, value, rate):
    """機能: 人工気配で成行注文の代金と料金を現金台帳に反映する。

    引数: cash(float)、side(int)は買い1/売り-1、quantity(int)、
    bid/ask/value/rate(float)は買気配・売気配・倍率・片道手数料。
    返り値: floatの注文後現金。
    """
    price = ask if side == 1 else bid
    return cash - side * quantity * price * value - fee(quantity, rate)


def scenario(symbol, total, hedge, value, rate, prices, flatten_while_covered):
    """機能: 同じ売買で両建てと縮小復帰を再生し、途中・終了差額を確認する。

    引数: symbol(str)、total/hedge(int)、value/rate(float)、
    prices(list[tuple[float,float]])は各時点気配、flatten_while_covered(bool)。
    返り値: dictの検査値。恒等式に反する場合はAssertionError。
    """
    b0, a0 = prices[0]
    b1, a1 = prices[1]
    b2, a2 = prices[2]
    bc, ac = prices[3]
    cash_cover = order(0.0, 1, total, b0, a0, value, rate)
    cash_reduce = cash_cover
    cash_cover = order(cash_cover, -1, hedge, b1, a1, value, rate)
    cash_reduce = order(cash_reduce, -1, hedge, b1, a1, value, rate)
    cover_equity = cash_cover + total * b2 * value - hedge * a2 * value
    reduce_equity = cash_reduce + (total - hedge) * b2 * value
    expected_interim = -hedge * (a2 - b2) * value
    assert abs((cover_equity - reduce_equity) - expected_interim) < 1e-6
    # ----------------------------------------
    if flatten_while_covered:
        cash_cover = order(cash_cover, -1, total, bc, ac, value, rate)
        cash_cover = order(cash_cover, 1, hedge, bc, ac, value, rate)
        cash_reduce = order(cash_reduce, -1, total - hedge, bc, ac, value, rate)
        expected_final = -hedge * (ac - bc) * value
        expected_final -= fee(total, rate) + fee(hedge, rate) - fee(total - hedge, rate)
    else:
        cash_cover = order(cash_cover, 1, hedge, b2, a2, value, rate)
        cash_reduce = order(cash_reduce, 1, hedge, b2, a2, value, rate)
        cash_cover = order(cash_cover, -1, total, bc, ac, value, rate)
        cash_reduce = order(cash_reduce, -1, total, bc, ac, value, rate)
        expected_final = 0.0
    assert abs((cash_cover - cash_reduce) - expected_final) < 1e-6
    return {
        '商品': symbol,
        '初回枚数': total,
        '保険枚数': hedge,
        '保険を残して全返済': flatten_while_covered,
        '途中の両建て側差額': cover_equity - reduce_equity,
        '途中の理論差額': expected_interim,
        '両建て終了収支': cash_cover,
        '縮小復帰終了収支': cash_reduce,
        '終了差額': cash_cover - cash_reduce,
        '終了の理論差額': expected_final,
        '恒等式合格': True,
    }


def main():
    """機能: 逆行・往復・変動スプレッドの人工経路を両商品で検査して保存する。

    引数: なし。
    返り値: None。結果は理論内の両建てと縮小対照の恒等式.jsonへ保存する。
    """
    rows = []
    for symbol, total, value, rate, tick in (
        ('TOPIXmini', 10, 1000.0, 41.8, 0.5),
        ('NK225micro', 20, 10.0, 11.0, 10.0),
    ):
        for mid_path, spreads in (
            ([100, 96, 92, 88], [1, 1, 1, 1]),
            ([100, 96, 99, 105], [1, 1, 1, 1]),
            ([100, 96, 92, 104], [1, 2, 3, 2]),
        ):
            prices = [((m - s / 2) * tick, (m + s / 2) * tick)
                      for m, s in zip(mid_path, spreads)]
            for hedge in (total // 2, total):
                for flatten_while_covered in (False, True):
                    rows.append(scenario(symbol, total, hedge, value, rate,
                                         prices, flatten_while_covered))
    result = {
        '対象': '保存板ではなく人工経路のみ。今回損益を参照していない。',
        '人工経路数': len(rows),
        '全合格': all(r['恒等式合格'] for r in rows),
        '検査': rows,
    }
    (ROOT / '両建てと縮小対照の恒等式.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'人工経路数': len(rows), '全合格': result['全合格']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
