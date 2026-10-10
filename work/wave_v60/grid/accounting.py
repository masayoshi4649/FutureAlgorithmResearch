"""週内持越しを含むグリッドの手数料と期間損益の共通会計。"""

from __future__ import annotations

import numpy as np
from numba import njit


@njit(cache=True)
def order_fee(quantity: int, fee_tenths: int) -> int:
    """機能: 一注文の手数料を、浮動小数誤差を避けて1円未満切捨てで求める。

    引数: quantity(int) は約定枚数、fee_tenths(int) は一枚当たり手数料の10倍。
    返り値: 一注文の手数料円(int)。TOPIXminiは418、NK225microは110を指定する。
    """
    assert quantity > 0 and fee_tenths >= 0
    return quantity * fee_tenths // 10


def period_account(gross_profit: float, gross_loss: float, fees: float,
                   opening_unrealized: float, closing_unrealized: float) -> dict:
    """機能: 持越し建玉の含み変化を加え、実現益だけに偏らない期間収支を求める。

    引数: gross_profit/gross_loss/fees/opening_unrealized/closing_unrealized(float)。
    返り値: 粗利益・粗損失・発生手数料・含み増減・期間損益(dict)。
    期首含みは直前セッションの末尾評価を使用し、再開時ギャップは新セッションへ計上する。
    """
    realized_gross = gross_profit - gross_loss
    unrealized_change = closing_unrealized - opening_unrealized
    return dict(gross_profit=float(gross_profit), gross_loss=float(gross_loss), fees=float(fees),
                realized_gross=float(realized_gross), realized_after_fees=float(realized_gross - fees),
                opening_unrealized=float(opening_unrealized), closing_unrealized=float(closing_unrealized),
                unrealized_change=float(unrealized_change), gross_net=float(realized_gross + unrealized_change),
                net=float(realized_gross - fees + unrealized_change))


def check_accounting() -> dict:
    """機能: 注文単位の切捨て、持越し損益、ギャップ、両建ての固定損失を合成検査する。

    引数: なし。返り値: 検査数と合否(dict)。実データ損益を参照しない。
    """
    for quantity in range(1, 101):
        assert order_fee(quantity, 418) == (quantity * 418) // 10
        assert order_fee(quantity, 110) == quantity * 11
    assert 10 * order_fee(1, 418) == 410 and order_fee(10, 418) == 418
    # ----------------------------------------
    # 買い100を95で場末評価、次場90で返済する。再開の5下落を消さない。
    first = period_account(0., 0., 41., 0., -5000.)
    second = period_account(0., 10000., 41., -5000., 0.)
    assert first['net'] == -5041. and second['net'] == -5041.
    assert first['net'] + second['net'] == -10082.
    # ----------------------------------------
    # 買い100・売り90の両建ては、共通中値が動いても含み損10を固定する。
    for mid in (50., 90., 95., 100., 150.):
        unrealized = ((mid - 100.) + (90. - mid)) * 1000.
        assert unrealized == -10000.
    periods = [period_account(2000., 0., 82., 0., -3000.),
               period_account(4000., 6000., 164., -3000., 0.)]
    assert np.isclose(sum(p['net'] for p in periods), -246.)
    return dict(合格=True, 注文手数料検査=200, 注文まとめ方検査=1, 持越しギャップ検査=1,
                両建て含み検査=5, 期間合計検査=1)
