"""新規公開時のATRと両気配だけで、予定リスクを払える整数量を列挙する。"""

import math

VALUE = {'TOPIX': 1000., 'NK225': 10.}
FEE = {'TOPIX': 41.8, 'NK225': 11.}
BUDGET = {'TOPIX': 5000., 'NK225': 2000.}
CAP = {'TOPIX': 5, 'NK225': 10}
PAPER_STOP_ATR = .75


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 一注文の片道料を整数枚数で切り捨てる。
    引数: quantity(int)、symbol(str)は枚数と商品。
    返り値: intは一注文の料。実注文・仮想注文は作らない。
    """
    assert symbol in FEE and isinstance(quantity, int) and not isinstance(quantity, bool) and quantity >= 0
    return math.floor(quantity*FEE[symbol])


def measure(atr: float, bid: float, ask: float, symbol: str) -> dict:
    """
    機能: 公開時の1ATR＋気配差の予定リスクで、元上限以下の整数qを列挙する。
    引数: atr/bid/ask(float)、symbol(str)は当時ATR、両気配、商品。
    返り値: dictは既知/未知・q上限・各q予定額。実約定後リスクや損益ではない。
    """
    assert symbol in CAP
    result = dict(known=False, reason=0, proposed_quantity=None, risk_by_quantity=[],
                  budget_yen=BUDGET[symbol], maximum_quantity=CAP[symbol], paper_stop_atr=PAPER_STOP_ATR)
    if not math.isfinite(atr) or atr <= 0:
        result['reason'] |= 1
    if not (math.isfinite(bid) and math.isfinite(ask) and 0 < bid < ask):
        result['reason'] |= 2
    if result['reason']:
        return result
    spread = ask-bid
    unit = (atr+spread)*VALUE[symbol]
    if not math.isfinite(unit) or unit < 0:
        result['reason'] = 4
        return result
    proposed = 0
    for q in range(1, CAP[symbol]+1):
        amount = q*unit+2*fee(q, symbol)
        if not math.isfinite(amount):
            result['reason'] = 8
            return result
        affordable = amount <= BUDGET[symbol]
        result['risk_by_quantity'].append(dict(quantity=q, planned_risk_yen=amount, affordable=affordable))
        if affordable:
            proposed = q
    result.update(known=True, proposed_quantity=proposed, spread=spread,
                  planned_risk_per_lot_without_fees=unit,
                  original_quantity_risk=result['risk_by_quantity'][-1]['planned_risk_yen'])
    return result


def gate(base: dict, mode: str) -> tuple:
    """
    機能: 保存W60のVETO/CONFIRM/KNOWN_VETOの公開採否を純真偽で返す。
    引数: base(dict)、mode(str)は当時票と元条件。
    返り値: tuple[bool,int]は元採否と拒否理由。保有busy・実取引を判定しない。
    """
    assert mode in ('VETO', 'CONFIRM', 'KNOWN_VETO')
    if not base['known']:
        return (True, 0) if mode == 'VETO' else (False, 100+int(base['reason']))
    if base['direction_votes'] < 2:
        return (True, 0) if mode == 'VETO' else (False, 200)
    if mode == 'CONFIRM':
        return (True, 0) if base['balance'] >= .25 else (False, 201)
    return (False, 202) if base['balance'] <= -.25 else (True, 0)
