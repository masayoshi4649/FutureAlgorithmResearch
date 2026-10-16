"""原入力なしで注文floor料と親・脚の異符号及び全場基準を検査する。"""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path

import metrics


HERE = Path(__file__).resolve().parent
PROOF = HERE / '注文別floor料と完結親金額及び全場分母の純人工.json'
FIELDS = ['row', 'source_row', 'parent', 'uid', 'target_uid', 'side', 'q', 'price', 'new', 'reason', 'fee', 'raw_seq', 'source_raw_seq']


def fixture(symbol: str, side: int, split: bool = False) -> dict:
    """
    機能: 注文ごとの独立手計算から完結親と返済脚を構築する。
    引数: symbol(str)、side(int)、split(bool)。
    返り値: dict は合成native返却形。原相場や既結果を使わない。
    """
    cap = 10 if symbol == 'TOPIX' else 20
    mult = 1000 if symbol == 'TOPIX' else 10
    unit_fee = Fraction(209, 5) if symbol == 'TOPIX' else Fraction(11)
    entry_price = 4000 if symbol == 'TOPIX' else 70000
    tick = Fraction(1, 2) if symbol == 'TOPIX' else Fraction(10)
    first_fee = int(unit_fee*cap)
    orders = [[1, 0, 3, 7, -1, side, cap, entry_price, 1, 90, first_fee, 101, 100]]
    legs = []
    q = cap//2 if split else cap
    # 分割時は勝ち脚・負け脚を持つ一つの負け親。全量時は正の一親。
    ticks = [2, -2] if split else [2]
    gross_sum = 0
    costs = first_fee
    for i, delta in enumerate(ticks):
        row = 3+i
        price = Fraction(entry_price)+side*delta*tick
        gross = side*(price-entry_price)*q*mult
        allocation = Fraction(first_fee*q, cap)
        cost = int(unit_fee*q)
        net = gross-allocation-cost
        orders.append([row, row-1, 3, -1, 7, -side, q, float(price), 0, 143 if split and i == 0 else 142, cost, 100+row, 99+row])
        legs.append(dict(parent=3, uid=7, side=side, q=q, entry_row=1, exit_row=row,
            entry_price=entry_price, exit_price=float(price), gross_yen=float(gross),
            entry_fee_allocated=float(allocation), exit_fee=cost, net_yen=float(net)))
        gross_sum += gross
        costs += cost
    net = gross_sum-costs
    parent = dict(parent=3, uid=7, side=side, quantity=cap, entry_row=1, exit_row=3+int(split),
        entry_price=entry_price, gross_yen=float(gross_sum), fee_yen=costs, net_yen=float(net),
        粗損益=float(gross_sum), 費用=costs, 収支=float(net))
    summary = dict(利益=max(0, float(net)), 損失=max(0, -float(net)), 収支=float(net),
        親数=1, 勝ち親=int(net>0), 負け親=int(net<0), 零親=int(net==0), 費用=costs,
        新規枚数=cap, 勝ち枚数=sum(leg['q'] for leg in legs if leg['net_yen']>0),
        負け枚数=sum(leg['q'] for leg in legs if leg['net_yen']<0), 零枚数=0, 全会計合格=True)
    return dict(completed=True, finish=True, orders=orders, order_fields=FIELDS, parent=[parent],
        actual_legs=legs, summary=summary, final_state=dict(held_quantity=0, pending_new=0,
        reserved_quantity=0, exit_queue_count=0, cash_yen=float(net), paid_fee_yen=costs))


def empty() -> dict:
    """
    機能: 無取引の完了口座を合成する。
    引数: なし。
    返り値: dict は注文・親・脚とも空の口座。
    """
    summary = {key: 0 for key in ('利益', '損失', '収支', '親数', '勝ち親', '負け親', '零親',
                                 '費用', '新規枚数', '勝ち枚数', '負け枚数', '零枚数')}
    summary['全会計合格'] = True
    return dict(completed=True, finish=True, orders=[], order_fields=FIELDS, parent=[], actual_legs=[],
        summary=summary, final_state=dict(held_quantity=0, pending_new=0, reserved_quantity=0,
        exit_queue_count=0, cash_yen=0, paid_fee_yen=0))


def reject(callable_: object) -> None:
    """
    機能: 壊した契約を検査関数が受理しないことを確認する。
    引数: callable_(Callable) は引数なしの処理。
    返り値: None。AssertionError以外の停止を成功として数えない。
    """
    try:
        callable_()
    except AssertionError:
        return
    raise AssertionError('不正な値を受理した')


def main() -> None:
    """
    機能: 料金・親脚単位・未定義・拒否境界・全33分母を合成だけで検査する。
    引数: なし。
    返り値: None。外部データ・金融実行・APIは使用しない。
    """
    assert not PROOF.exists()
    count, refusals = 0, 0
    examples = []
    for symbol in ('TOPIX', 'NK225'):
        for side in (1, -1):
            for split in (False, True):
                daily = fixture(symbol, side, split)
                row = metrics.account(symbol, '2026-10-01_Day', daily)
                expected_fee = 836 if symbol == 'TOPIX' else 440
                assert row['費用'] == expected_fee
                assert row['勝ち枚数'] == (metrics.CAP[symbol]//2 if split else metrics.CAP[symbol])
                assert row['負け枚数'] == (metrics.CAP[symbol]//2 if split else 0)
                if split:
                    assert row['利益'] == 0 and row['損失'] == expected_fee
                examples.append(dict(symbol=symbol, side=side, split=split, row=row))
                count += 5
    assert metrics.fee(1, 'TOPIX') == 41
    assert metrics.fee(2, 'TOPIX') == 83
    assert metrics.fee(5, 'TOPIX') == 209
    assert metrics.fee(10, 'NK225') == 110
    assert metrics.fee(1, 'TOPIX')*2 != metrics.fee(2, 'TOPIX')
    count += 5
    for bad in (True, False, None, float('nan'), float('inf'), -float('inf'), '1'):
        reject(lambda bad=bad: metrics.exact(bad))
        refusals += 1
    for key, value in (('completed', False), ('finish', False)):
        broken = fixture('TOPIX', 1)
        broken[key] = value
        reject(lambda broken=broken: metrics.account('TOPIX', '2026-10-01_Day', broken))
        refusals += 1
    for category in ('fee', 'allocation', 'parent', 'cash', 'quantity', 'unclosed', 'summary', 'extra_leg', 'bool_order'):
        broken = fixture('TOPIX', 1, True)
        if category == 'fee': broken['orders'][1][10] += 1
        elif category == 'allocation': broken['actual_legs'][0]['entry_fee_allocated'] += 1
        elif category == 'parent': broken['parent'][0]['net_yen'] += 1
        elif category == 'cash': broken['final_state']['cash_yen'] += 1
        elif category == 'quantity': broken['actual_legs'][0]['q'] += 1
        elif category == 'unclosed': broken['final_state']['reserved_quantity'] = 1
        elif category == 'summary': broken['summary']['親数'] = True
        elif category == 'extra_leg': broken['actual_legs'].append(deepcopy(broken['actual_legs'][0]))
        elif category == 'bool_order': broken['orders'][0][10] = True
        reject(lambda broken=broken: metrics.account('TOPIX', '2026-10-01_Day', broken))
        refusals += 1

    # ----------------------------------------
    sessions = [f'2026-10-{i+1:02d}_' + ('Day' if i%2 == 0 else 'Night') for i in range(33)]
    rows, parents, legs = [], [], []
    for symbol in ('TOPIX', 'NK225'):
        for i, session in enumerate(sessions):
            daily = fixture(symbol, 1 if i%2 == 0 else -1) if i == 0 else empty()
            rows.append(metrics.account(symbol, session, daily))
            parents.extend(dict(p, symbol=symbol, session=session) for p in daily['parent'])
            legs.extend(dict(p, symbol=symbol, session=session) for p in daily['actual_legs'])
        pp = metrics.periods(rows, parents, sessions, symbol, legs)
        full = pp['全場']
        assert full['session_count'] == 33 and full['active_sessions'] == 1
        assert full['positive_sessions'] == 1 and full['no_trade_sessions'] == 32
        assert full['red_full_rate'] == 0 and full['all_stability_targets'] is True
        assert full['all_main_targets'] is (symbol == 'NK225')
        assert full['target_mean_success'] is (False if symbol == 'TOPIX' else None)
        assert pp['上位3黒字場除外']['aggregate']['利益割合'] is None
        assert pp['上位3黒字場除外']['all_main_targets'] is False
        assert pp['ナイト']['no_trade_sessions'] == 16
        assert pp['方向']['売り']['親数'] == 0
        assert pp['方向']['売り']['利益割合'] is None
        assert pp['方向']['売り']['勝ち枚数'] == 0
        count += 13
    empty_scope = metrics.scope([metrics.account('NK225', sessions[0], empty())], [], 'NK225')
    assert empty_scope['mean_positive_session_net_yen'] is None
    assert empty_scope['aggregate']['利益割合'] is None and empty_scope['all_main_targets'] is False
    count += 2
    reject(lambda: metrics.periods(rows, parents, sessions+[sessions[0]], 'TOPIX', legs))
    refusals += 1
    broken = deepcopy(rows)
    broken[0]['利益'] = float('nan')
    reject(lambda: metrics.periods(broken, parents, sessions, 'TOPIX', legs))
    refusals += 1
    bound_rows = [dict(symbol='NK225', session=s, 利益=100 if i < 4 else 0, 損失=100 if i == 4 else 0,
        収支=100 if i < 4 else -100 if i == 4 else 0, 親数=int(i < 5), 勝ち枚数=20 if i<4 else 0,
        負け枚数=20 if i==4 else 0, 零枚数=0) for i, s in enumerate(sessions)]
    bound_parents = [dict(symbol='NK225', session=sessions[i], net_yen=100 if i<4 else -100, side=1) for i in range(5)]
    boundary = metrics.scope(bound_rows, bound_parents, 'NK225')
    assert boundary['aggregate']['利益割合'] == .8 and boundary['target_worst_mean'] is True
    assert boundary['losing_sessions'] == 1 and boundary['no_trade_sessions'] == 28
    count += 4
    proof = dict(全合格=True, 算術境界=count, 拒否境界=refusals, 合成会計8例=examples,
        source_SHA256={name: hashlib.sha256((HERE/name).read_bytes()).hexdigest()
                       for name in ('metrics.py', 'artificial_metrics.py')},
        規模留保='一勝32無取引が日経の数式基準を満たす人工も含む。実用的な活動の成功とは扱わない。',
        方向の範囲='完結親の金額と実返済脚の勝負枚数のみ参考。方向別の場基準は再判定しない。',
        未知='利益割合・平均勝ち・日経円床・未提供脚枚数は分母なし又は未指定ならNone。',
        原入力=0, 金融結果=0, 既結果=0, API=0)
    PROOF.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(全合格=True, 算術境界=count, 拒否境界=refusals,
        SHA256=hashlib.sha256(PROOF.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
