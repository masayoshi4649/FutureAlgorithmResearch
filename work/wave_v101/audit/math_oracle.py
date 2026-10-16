"""実fill・注文別料金から101の増玉と全玉停止を独立有理数で計算する。"""

from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class Cohort:
    """
    機能: 一回の実新規注文を、実fill作成順・実枚数・実価格・実料金で保持する。
    引数: ordinal(int)、quantity(int)、price(Fraction)、entry_fee(int)。
    返り値: Cohort。未約定の追加予約は実cohortへ加えない。
    """
    ordinal: int
    quantity: int
    price: Fraction
    entry_fee: int


def rational(value: object) -> Fraction:
    """
    機能: 十進入力を有理数へ変換する。
    引数: value(object)は有限数値又はFraction。
    返り値: Fraction。価格線の上限へ公差を足さない。
    """
    return value if isinstance(value, Fraction) else Fraction(str(value))


def order_fee(quantity: int, unit_fee: object) -> int:
    """
    機能: 一注文の片道手数料を整数円へ切り捨てる。
    引数: quantity(int)は正の実注文枚数、unit_fee(object)は一枚料金。
    返り値: int。実注文をまとめ直して丸めない。
    """
    assert isinstance(quantity, int) and quantity > 0
    amount = quantity*rational(unit_fee)
    assert amount >= 0
    return amount.numerator // amount.denominator


def cohort(ordinal: int, quantity: int, price: object, unit_fee: object) -> Cohort:
    """
    機能: 仮定又は実fill一注文の数学記録を作る。
    引数: ordinal/quantity(int)、price/unit_fee(object)。
    返り値: Cohort。hypothesis用記録を実保有へ適用するかは呼出し側で分離する。
    """
    assert ordinal >= 0 and rational(price) > 0
    return Cohort(ordinal, quantity, rational(price), order_fee(quantity, unit_fee))


def quantity_for(config: dict, symbol: str) -> int:
    """
    機能: 初回絶対数量を商品間で暗黙換算せず取得する。
    引数: config(dict)、symbol(str)はTOPIX又はNK225。
    返り値: int。Noneの旧全量だけ8/16、宣言1/2/4は両商品で同じ。
    """
    assert symbol in ('TOPIX', 'NK225')
    value = config['trend_initial_quantity']
    if value is None:
        return 8 if symbol == 'TOPIX' else 16
    assert type(value) is int and value in (1, 2, 4)
    return value


def next_quantity(quantity: int, maximum: int, pending_quantity: int = 0) -> int:
    """
    機能: 追加予約がない時だけ同方向実保有数を倍増する追加枚数を求める。
    引数: quantity/maximum/pending_quantity(int)は実数と予約数。
    返り値: int。予約中又は上限なら0、実保有を予約数で膨らませない。
    """
    assert 0 < quantity <= maximum and pending_quantity >= 0
    assert quantity+pending_quantity <= maximum
    return 0 if pending_quantity else min(quantity, maximum-quantity)


def totals(cohorts: list[Cohort], multiplier: object, unit_fee: object) -> dict:
    """
    機能: 実cohortから全玉数量・価格金額・実新規料金と全量一注文返済料金を求める。
    引数: cohorts(list[Cohort])、multiplier/unit_fee(object)。
    返り値: dict。Q/E/entry_fee/close_fee/F/weighted_entry。料金配分前の全体会計。
    """
    assert cohorts and len({c.ordinal for c in cohorts}) == len(cohorts)
    assert all(c.quantity > 0 and c.price > 0 and c.entry_fee >= 0 for c in cohorts)
    q = sum(c.quantity for c in cohorts)
    entry = sum(c.entry_fee for c in cohorts)
    exposure = sum((c.quantity*c.price*rational(multiplier) for c in cohorts), Fraction())
    close = order_fee(q, unit_fee)
    return dict(Q=q, E=exposure, entry_fee=entry, close_fee=close, F=entry+close,
                weighted_entry=exposure/(q*rational(multiplier)))


def liquidation(cohorts: list[Cohort], quote: object, side: int,
                multiplier: object, unit_fee: object) -> dict:
    """
    機能: 現時点清算quoteを使い全実玉のgross/netを求める。
    引数: cohorts(list[Cohort])、quote/multiplier/unit_fee(object)、side(int)は±1。
    返り値: dict。未保有玉へ過去peakを掛けず、買いはbid、売りはaskを与える。
    """
    assert side in (-1, 1) and rational(quote) > 0
    result = totals(cohorts, multiplier, unit_fee)
    result['gross'] = side*(result['Q']*rational(multiplier)*rational(quote)-result['E'])
    result['net'] = result['gross']-result['F']
    return result


def fixed_risk(first: Cohort, initial_width: object, multiplier: object, unit_fee: object) -> Fraction:
    """
    機能: 初回実fillの数量と実料金からR0を固定する。
    引数: first(Cohort)、initial_width/multiplier/unit_fee(object)。
    返り値: Fraction。増玉後Qへ比例増額しない。
    """
    return first.quantity*rational(initial_width)*rational(multiplier)+first.entry_fee+order_fee(first.quantity, unit_fee)


def tick_round(price: object, tick: object, side: int) -> Fraction:
    """
    機能: 価格全体を買いceil/売りfloorで保護方向へ丸める。
    引数: price/tick(object)、side(int)は±1。
    返り値: Fraction。非呼値weighted価格の幅だけを丸めない。
    """
    assert side in (-1, 1) and rational(tick) > 0
    units = rational(price)/rational(tick)
    count = -((-units.numerator)//units.denominator) if side == 1 else units.numerator//units.denominator
    return count*rational(tick)


def budget_line(cohorts: list[Cohort], risk: object, side: int,
                multiplier: object, unit_fee: object, tick: object) -> Fraction:
    """
    機能: 全玉netが−R0以上となる理論価格線を保護方向へ丸める。
    引数: cohorts(list[Cohort])、risk/multiplier/unit_fee/tick(object)、side(int)。
    返り値: Fraction。R0−Fが負でも0へ置換しない。
    """
    value = totals(cohorts, multiplier, unit_fee)
    price = (value['E']+side*(value['F']-rational(risk)))/(value['Q']*rational(multiplier))
    return tick_round(price, tick, side)


def fee_line(cohorts: list[Cohort], side: int, multiplier: object,
             unit_fee: object, tick: object) -> Fraction:
    """
    機能: 全玉費用損益分岐価格を価格全体で丸め、有利方向一呼値を追加する。
    引数: cohorts(list[Cohort])、side(int)、multiplier/unit_fee/tick(object)。
    返り値: Fraction。cohort追加による加重価格の非呼値を安全に扱う。
    """
    value = totals(cohorts, multiplier, unit_fee)
    breakeven = (value['E']+side*value['F'])/(value['Q']*rational(multiplier))
    return tick_round(breakeven, tick, side)+side*rational(tick)


def integrated_line(cohorts: list[Cohort], side: int, risk: object, old_line: object,
                    initial_line: object, peak: object, trail: object, active: bool,
                    multiplier: object, unit_fee: object, tick: object) -> dict:
    """
    機能: 初回固定初期線・非緩和旧線・同親価格peak・予算線・有効費用床を統合する。
    引数: cohorts(list[Cohort])、side(int)、active(bool)、その他価格と費用(object)。
    返り値: dict。有効lineと独立各構成線。増玉で初期線又は価格peakを作り直さない。
    """
    parts = dict(旧線=rational(old_line), 初回初期線=rational(initial_line),
                 常時追尾=rational(peak)-side*rational(trail),
                 固定予算=budget_line(cohorts, risk, side, multiplier, unit_fee, tick))
    if active:
        parts['費用床'] = fee_line(cohorts, side, multiplier, unit_fee, tick)
    return dict(line=side*max(side*line for line in parts.values()), parts=parts)


def projected_add(cohorts: list[Cohort], quantity: int, bid: object, ask: object,
                  side: int, risk: object, old_line: object, initial_line: object,
                  peak: object, initial_width: object, trail: object, active: bool,
                  protected: bool, cushion_ticks: int, multiplier: object,
                  unit_fee: object, tick: object) -> dict:
    """
    機能: 現在気配で追加想定全玉のnetと統合線余裕を独立算定する。
    引数: cohorts(list[Cohort])、quantity/side/cushion_ticks(int)、active/protected(bool)、価格・費用(object)。
    返り値: dict。hypothesisのみであり、資格合格を実fillへ書き換えない。
    """
    assert rational(ask) > rational(bid) > 0 and quantity > 0
    price, close = (ask, bid) if side == 1 else (bid, ask)
    hypothetical = cohorts+[cohort(max(c.ordinal for c in cohorts)+1, quantity, price, unit_fee)]
    value = liquidation(hypothetical, close, side, multiplier, unit_fee)
    threshold = cohorts[0].quantity*2*rational(initial_width)*rational(multiplier)
    proposed_active = bool(active or (protected and value['gross'] >= threshold))
    integrated = integrated_line(hypothetical, side, risk, old_line, initial_line,
                                 peak, trail, proposed_active, multiplier, unit_fee, tick)
    clearance = side*(rational(close)-integrated['line'])
    return dict(hypothetical=hypothetical, net=value['net'], gross=value['gross'],
                active=proposed_active, line=integrated['line'], parts=integrated['parts'],
                clearance=clearance, allowed=value['net'] >= 0 and clearance >= cushion_ticks*rational(tick))


def allocate_close(cohorts: list[Cohort], total_fee: int) -> dict[int, int]:
    """
    機能: 全量一注文の料金を枚数比例floorと剰余降順で配分する。
    引数: cohorts(list[Cohort])、total_fee(int)は実全量返済料金。
    返り値: dict[int,int]。同率は実fill作成順ordinalの早いもの優先。
    """
    assert total_fee >= 0
    total_q = sum(c.quantity for c in cohorts)
    portions = {c.ordinal: total_fee*c.quantity//total_q for c in cohorts}
    ranked = sorted(cohorts, key=lambda c: (-(total_fee*c.quantity % total_q), c.ordinal))
    for item in ranked[:total_fee-sum(portions.values())]:
        portions[item.ordinal] += 1
    assert sum(portions.values()) == total_fee
    return portions


def completed_cohorts(cohorts: list[Cohort], price: object, side: int,
                      multiplier: object, unit_fee: object) -> dict:
    """
    機能: 一回全量返済の実費用を各実fillへ割当し、cohortと親の損益を一致させる。
    引数: cohorts(list[Cohort])、price/multiplier/unit_fee(object)、side(int)。
    返り値: dict。cohort別net・費用配分・親net・相殺前GP/GL。
    """
    value = liquidation(cohorts, price, side, multiplier, unit_fee)
    fees = allocate_close(cohorts, value['close_fee'])
    nets = {c.ordinal: side*c.quantity*(rational(price)-c.price)*rational(multiplier)-c.entry_fee-fees[c.ordinal]
            for c in cohorts}
    assert sum(nets.values()) == value['net']
    return dict(nets=nets, close_fees=fees, parent_net=value['net'],
                gross_profit=sum((n for n in nets.values() if n > 0), Fraction()),
                gross_loss=-sum((n for n in nets.values() if n < 0), Fraction()))


def pending_order(prior_exit: bool, static_cut: bool, deadline: bool,
                  quote_normal: bool, first_stop_now: bool) -> list[str]:
    """
    機能: 追加予約に対する現在行の操作順を、将来価格を使わず明示する。
    引数: prior_exit/static_cut/deadline/quote_normal/first_stop_now(bool)。
    返り値: list[str]。既存返済・期限は取消先、それ以外は追加fill後に現在停止判断。
    """
    if prior_exit:
        return ['未fill追加取消', '旧実数量の返済実fill'] if quote_normal else ['未fill追加取消', '返済pending維持']
    if static_cut or deadline:
        return ['未fill追加取消', '旧実数量の返済判断']
    if not quote_normal:
        return ['追加pending維持']
    result = ['追加実fill', '実価格と実料金で停止線更新']
    if first_stop_now:
        result.append('全実数量の返済判断')
    return result
