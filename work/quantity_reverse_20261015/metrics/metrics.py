"""外部IOなしで実注文・完結親・返済脚と全場の金額目標を照合する。"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from fractions import Fraction
import math
from numbers import Real
from statistics import median


CAP = {'TOPIX': 10, 'NK225': 20}
MULTIPLIER = {'TOPIX': 1000, 'NK225': 10}
FEE = {'TOPIX': Fraction(418, 10), 'NK225': Fraction(11)}


def exact(value: object) -> Fraction:
    """
    機能: 有限の実数だけを文字列表現に基づく厳密数へ移す。
    引数: value(object)。真偽・非有限・非数値を拒否する。
    返り値: Fraction。未知や欠測をゼロへ置換しない。
    """
    assert isinstance(value, (Real, Decimal)) and not isinstance(value, bool), value
    assert math.isfinite(value), value
    return Fraction(str(value))


def integer(value: object, minimum: int = 0) -> int:
    """
    機能: 有限で整数と等しい識別子又は枚数を検査する。
    引数: value(object)、minimum(int)。
    返り値: int。配列由来の整数値floatを許容し、真偽は拒否する。
    """
    number = exact(value)
    assert number.denominator == 1 and number >= minimum, value
    return int(number)


def fee(quantity: object, symbol: str) -> int:
    """
    機能: 実注文一回ごとの税込料をfloorする。
    引数: quantity(object) は正整数枚数、symbol(str) は商品。
    返り値: int は円料。複数注文をまとめ直さない。
    """
    assert symbol in CAP
    value = integer(quantity, 1) * FEE[symbol]
    return value.numerator // value.denominator


def records(values: object, fields: list[str]) -> list[dict]:
    """
    機能: 記憶内のnative注文配列を辞書行へ変換する。
    引数: values(object) は二次元配列又は行列list、fields(list[str])。
    返り値: list[dict]。外部ファイルは読まない。
    """
    assert len(fields) == len(set(fields))
    rows = values.tolist() if hasattr(values, 'tolist') else values
    assert isinstance(rows, list)
    assert all(isinstance(row, list) and len(row) == len(fields) for row in rows)
    return [dict(zip(fields, row)) for row in rows]


def amounts(values: list[object]) -> dict:
    """
    機能: 完結親netを正負へ分け、主金額割合を計算する。
    引数: values(list[object]) は損失・ゼロを含む完結親net。
    返り値: dict。割合・平均の分母が無い場合はNoneを保持する。
    """
    numbers = [exact(value) for value in values]
    wins = [value for value in numbers if value > 0]
    losses = [-value for value in numbers if value < 0]
    p, loss, net = sum(wins, Fraction()), sum(losses, Fraction()), sum(numbers, Fraction())
    return dict(利益=float(p), 損失=float(loss), 収支=float(net), 親数=len(numbers),
        勝ち親=len(wins), 負け親=len(losses), 零親=len(numbers)-len(wins)-len(losses),
        利益割合=float(p/(p+loss)) if p+loss else None, PF=float(p/loss) if loss else None,
        平均利益=float(p/len(wins)) if wins else None,
        平均損失=float(loss/len(losses)) if losses else None)


def quantities(legs: list[dict]) -> dict:
    """
    機能: 実返済脚のnet符号で決済枚数を分ける。
    引数: legs(list[dict]) は実脚。親netの符号とは区別する。
    返り値: dict は勝ち・負け・零の実枚数。
    """
    result = dict(勝ち枚数=0, 負け枚数=0, 零枚数=0)
    for leg in legs:
        net, q = exact(leg['net_yen']), integer(leg['q'], 1)
        result['勝ち枚数' if net > 0 else '負け枚数' if net < 0 else '零枚数'] += q
    return result


def account(symbol: str, session: str, daily: dict) -> dict:
    """
    機能: 一場のnative実注文・各floor料・脚・完結親・最終現金を厳密照合する。
    引数: symbol/session(str)、daily(dict) はengine.simulateの記憶内返却値。
    返り値: dict は場row。未完結を全場成績として受理しない。
    """
    assert symbol in CAP and isinstance(session, str) and session.endswith(('_Day', '_Night'))
    assert daily['completed'] is True and daily['finish'] is True
    final = daily['final_state']
    for key in ('held_quantity', 'pending_new', 'reserved_quantity', 'exit_queue_count'):
        assert integer(final[key]) == 0
    orders = records(daily['orders'], daily['order_fields'])
    parents, legs = daily['parent'], daily['actual_legs']
    assert isinstance(parents, list) and isinstance(legs, list)
    ids = [(integer(p['parent']), integer(p['uid'])) for p in parents]
    assert len(ids) == len(set(ids))
    assert len({key[0] for key in ids}) == len(ids) and len({key[1] for key in ids}) == len(ids)
    entries, exits = {}, Counter()
    order_cost = 0
    for order in orders:
        cid, q = integer(order['parent']), integer(order['q'], 1)
        side = integer(order['side'], -1)
        assert side in (-1, 1)
        price = exact(order['price'])
        assert price > 0 and integer(order['row']) > integer(order['source_row'])
        cost = integer(order['fee'])
        assert cost == fee(q, symbol)
        order_cost += cost
        new = integer(order['new'])
        assert new in (0, 1)
        if new:
            uid = integer(order['uid'])
            assert (cid, uid) not in entries and q == CAP[symbol]
            assert integer(order['target_uid'], -1) == -1
            entries[cid, uid] = order
        else:
            uid = integer(order['target_uid'])
            assert integer(order['uid'], -1) == -1
            exits[cid, uid, side, q, integer(order['row']), price, cost] += 1
    assert set(entries) == set(ids)
    for parent in parents:
        cid, uid = integer(parent['parent']), integer(parent['uid'])
        entry = entries[cid, uid]
        side, q = integer(parent['side'], -1), integer(parent['quantity'], 1)
        assert side in (-1, 1) and side == integer(entry['side'], -1)
        assert q == integer(entry['q'])
        assert integer(parent['entry_row']) == integer(entry['row'])
        assert exact(parent['entry_price']) == exact(entry['price'])
        own = [leg for leg in legs if integer(leg['parent']) == cid and integer(leg['uid']) == uid]
        assert own and sum(integer(leg['q'], 1) for leg in own) == q
        gross_sum, allocated, exit_fee_sum = Fraction(), Fraction(), 0
        for leg in own:
            amount = integer(leg['q'], 1)
            assert integer(leg['side'], -1) == side
            assert integer(leg['entry_row']) == integer(entry['row'])
            assert exact(leg['entry_price']) == exact(entry['price'])
            gross = side * (exact(leg['exit_price'])-exact(leg['entry_price'])) * amount * MULTIPLIER[symbol]
            alloc = Fraction(integer(entry['fee']) * amount, q)
            cost = fee(amount, symbol)
            assert exact(leg['gross_yen']) == gross
            assert exact(leg['entry_fee_allocated']) == alloc
            assert exact(leg['exit_fee']) == cost
            assert exact(leg['net_yen']) == gross-alloc-cost
            key = (cid, uid, -side, amount, integer(leg['exit_row']), exact(leg['exit_price']), cost)
            assert exits[key] > 0
            exits[key] -= 1
            gross_sum += gross
            allocated += alloc
            exit_fee_sum += cost
        assert integer(parent['exit_row']) == max(integer(leg['exit_row']) for leg in own)
        assert allocated == integer(entry['fee'])
        assert exact(parent['gross_yen']) == gross_sum
        assert exact(parent['fee_yen']) == allocated+exit_fee_sum
        assert exact(parent['net_yen']) == gross_sum-allocated-exit_fee_sum
        for english, japanese in (('gross_yen', '粗損益'), ('fee_yen', '費用'), ('net_yen', '収支')):
            if japanese in parent:
                assert exact(parent[english]) == exact(parent[japanese])
    assert len(legs) == sum(1 for order in orders if integer(order['new']) == 0)
    assert not any(exits.values())
    assert all((integer(leg['parent']), integer(leg['uid'])) in entries for leg in legs)
    gross = sum((exact(p['gross_yen']) for p in parents), Fraction())
    net = sum((exact(p['net_yen']) for p in parents), Fraction())
    assert sum((exact(p['fee_yen']) for p in parents), Fraction()) == order_cost
    assert sum((exact(leg['net_yen']) for leg in legs), Fraction()) == net
    assert exact(final['cash_yen']) == net and exact(final['paid_fee_yen']) == order_cost
    row = dict(symbol=symbol, session=session, **amounts([p['net_yen'] for p in parents]),
        **quantities(legs), 粗損益=float(gross), 費用=order_cost,
        新規枚数=sum(integer(p['quantity'], 1) for p in parents), 全会計合格=True)
    summary = daily['summary']
    for key in ('利益', '損失', '収支', '親数', '勝ち親', '負け親', '零親', '費用', '新規枚数', '勝ち枚数', '負け枚数', '零枚数'):
        assert exact(summary[key]) == exact(row[key]), key
    assert summary['全会計合格'] is True
    return row


def scope(rows: list[dict], parents: list[dict], symbol: str) -> dict:
    """
    機能: 同商品・同期間の親金額と、全場を分母にした安定性と平均を測る。
    引数: rows/parents(list[dict]) は同一条件の対象場と完結親、symbol(str)。
    返り値: dict。無取引は勝ちとせず、日経の円額床はNoneを保つ。
    """
    assert symbol in CAP and rows
    assert all(row['symbol'] == symbol for row in rows)
    ids = [row['session'] for row in rows]
    assert len(ids) == len(set(ids))
    assert all(p['symbol'] == symbol and p['session'] in ids for p in parents)
    sums = amounts([p['net_yen'] for p in parents])
    for row in rows:
        own = [p for p in parents if p['session'] == row['session']]
        actual = amounts([p['net_yen'] for p in own])
        for key in ('利益', '損失', '収支', '親数'):
            assert exact(row[key]) == exact(actual[key])
        assert integer(row['親数']) == len(own)
    wins = [exact(row['収支']) for row in rows if exact(row['収支']) > 0]
    losses = [-exact(row['収支']) for row in rows if exact(row['収支']) < 0]
    active = sum(integer(row['親数']) > 0 for row in rows)
    n = len(rows)
    positive_mean = sum(wins, Fraction()) / len(wins) if wins else None
    worst = max([Fraction()]+losses)
    net = sum((exact(row['収支']) for row in rows), Fraction())
    p, loss = exact(sums['利益']), exact(sums['損失'])
    monetary65 = bool(p+loss and p/(p+loss) >= Fraction(65, 100))
    red20 = Fraction(len(losses), n) <= Fraction(1, 5)
    coverage = positive_mean is not None and worst <= positive_mean
    floor = 100000 if symbol == 'TOPIX' else None
    classical = monetary65 and red20 and coverage
    return dict(aggregate=sums, session_count=n, active_sessions=active,
        positive_sessions=len(wins), losing_sessions=len(losses), no_trade_sessions=n-active,
        flat_active_sessions=active-len(wins)-len(losses), red_full_rate=len(losses)/n,
        red_active_rate=len(losses)/active if active else None,
        mean_session_net_yen=float(net/n), median_session_net_yen=float(median(exact(row['収支']) for row in rows)),
        mean_positive_session_net_yen=float(positive_mean) if positive_mean is not None else None,
        worst_negative_session_abs_yen=float(worst), target65=monetary65,
        target_red20=red20, target_worst_mean=coverage, all_stability_targets=classical,
        target_floor_yen=floor, target_mean_success=bool(net/n >= floor) if floor is not None else None,
        all_main_targets=classical and (floor is None or net/n >= floor),
        actual_quantity_cap=CAP[symbol], net_capacity_points=float(net/(CAP[symbol]*MULTIPLIER[symbol])),
        **{key: sum(integer(row[key]) for row in rows) for key in ('勝ち枚数', '負け枚数', '零枚数')})


def periods(rows: list[dict], parents: list[dict], sessions: list[str], symbol: str,
            legs: list[dict] | None = None) -> dict:
    """
    機能: 全場・前後・昼夜・上位3黒字除外を同じ定義で集計する。
    引数: rows/parents(list[dict])、sessions(list[str])、symbol(str)、legs(list[dict]|None)。
    返り値: dict。方向別は親金額と任意の脚枚数の参考で、方向別の場基準は再判定しない。
    """
    assert sessions and len(sessions) == len(set(sessions))
    assert all(isinstance(s, str) and s.endswith(('_Day', '_Night')) for s in sessions)
    own = [row for row in rows if row['symbol'] == symbol]
    pp = [p for p in parents if p['symbol'] == symbol]
    assert len(own) == len(sessions) and {row['session'] for row in own} == set(sessions)
    top = sorted((row for row in own if exact(row['収支']) > 0), key=lambda row: (-exact(row['収支']), row['session']))[:3]
    excluded = {row['session'] for row in top}
    middle = len(sessions)//2
    groups = {'全場': sessions, '前半': sessions[:middle], '後半': sessions[middle:],
        'デイ': [s for s in sessions if s.endswith('_Day')],
        'ナイト': [s for s in sessions if s.endswith('_Night')],
        '上位3黒字場除外': [s for s in sessions if s not in excluded]}
    result = {}
    for label, ids in groups.items():
        if ids:
            rr = [row for row in own if row['session'] in ids]
            ps = [p for p in pp if p['session'] in ids]
            result[label] = dict(**scope(rr, ps, symbol), sessions=list(ids))
        else:
            result[label] = None
    result['除外場'] = [row['session'] for row in top]
    result['方向'] = {}
    for label, side in (('買い', 1), ('売り', -1)):
        target = [p for p in pp if integer(p['side'], -1) == side]
        row = amounts([p['net_yen'] for p in target])
        if legs is not None:
            ll = [leg for leg in legs if leg['symbol'] == symbol and leg['session'] in sessions and integer(leg['side'], -1) == side]
            assert sum((exact(leg['net_yen']) for leg in ll), Fraction()) == exact(row['収支'])
            row.update(quantities(ll))
        else:
            row.update(勝ち枚数=None, 負け枚数=None, 零枚数=None)
        row['範囲'] = '完結親金額と実脚枚数の参考。方向別の全場三基準は未判定。'
        result['方向'][label] = row
    return result
