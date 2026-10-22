"""知見追記予定を既所有結果と二場の保存注文だけで照合する。"""

from collections import defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
OWN = WORK / 'audit_result120e1' / 'owned'


def inventory_trace(orders: np.ndarray, quotes: dict, cap: int, multiplier: int,
                    fee: int) -> dict:
    """
    機能: 保存済み注文の現金と実在庫を復元し、逆側超過と両上限を確認する。
    引数: orders(np.ndarray)は一政策18列、quotes(dict)は所有気配、cap/int・multiplier/int・fee/intは契約値。
    返り値: dictは注文原行だけの最初の超過・解消・上限と超過区間数。売買判断を再生しない。
    """
    byrow = defaultdict(list)
    for order in orders:
        byrow[int(order[4])].append(order)
    index = {int(row): i for i, row in enumerate(quotes['row'])}
    held = {}
    cash = 0.0
    seed = 0
    previous_excess = False
    baseline = 0.0
    excess = []
    lost = []
    saturated = []
    for raw, group in sorted(byrow.items()):
        if not held:
            baseline = cash
            seed = 0
            previous_excess = False
        counter_profit_close = False
        for order in group:
            uid, kind, side = map(int, order[:3])
            if kind == 1:
                assert uid not in held
                if seed == 0:
                    seed = side
                held[uid] = (side, float(order[7]))
                cash -= order[8]
            else:
                oldside, oldprice = held.pop(uid)
                assert side == -oldside
                cash += oldside * (order[7] - oldprice) * multiplier - order[8]
                counter_profit_close |= oldside == -seed and int(order[9]) == 1
        i = index[raw]
        equity = cash + sum(side * ((quotes['bid'][i] if side == 1 else quotes['ask'][i]) - price)
                            * multiplier - fee for side, price in held.values())
        long = sum(side == 1 for side, price in held.values())
        short = sum(side == -1 for side, price in held.values())
        main, cover = (long, short) if seed == 1 else (short, long)
        now_excess = main > 0 and cover > main
        item = dict(raw=raw, long=long, short=short, equity=float(equity),
                    cash=float(cash), basket_net=float(equity-baseline))
        if now_excess and not previous_excess:
            excess.append(item)
        if previous_excess and not now_excess and main > 0 and counter_profit_close:
            lost.append(item)
        if long == cap and short == cap:
            saturated.append(item)
        previous_excess = now_excess
    assert not held
    return dict(counter_excess_episodes=len(excess), first_counter_excess=excess[0] if excess else None,
                first_lost_excess=lost[0] if lost else None,
                first_both_caps=saturated[0] if saturated else None, cash=float(cash))


def main() -> None:
    """
    機能: 新三法則の金額・枚数・分母を所有保存物で検査し独立小証跡を保存する。
    引数: なし。対象二場は根が事前指定したROTATE_S2_T1の各商品最低収支場。
    返り値: None。原結果・原市場の追加読取、金融再生、共通知見への書込はしない。
    """
    result = json.loads((OWN / '完成結果.json').read_text(encoding='utf-8'))
    methods = ('ROTATE_S2_T1', 'KEEP_S2_T1', 'RESCUE_S2_T1')
    totals = {symbol: {method: sum(row['net'] for row in result['runs']
                                 if row['symbol'] == symbol and row['method'] == method)
                       for method in methods} for symbol in ('TOPIX', 'NK225')}
    assert totals == {'TOPIX': dict(zip(methods, (-3368506, -1420096, -1614124))),
                      'NK225': dict(zip(methods, (-1427588, -711362, -718660)))}
    assert all(sum(row['net'] for row in result['runs']
                   if row['symbol'] == symbol and row['method'] == spec['id']) < 0
               for symbol in ('TOPIX', 'NK225') for spec in result['specs'])
    examples = []
    for symbol, scene, cap, multiplier, fee in (
        ('TOPIX', '2026-10-16_Night', 10, 1000, 41),
        ('NK225', '2026-10-14_Night', 20, 10, 11)):
        with np.load(OWN / symbol / (scene + '.npz'), allow_pickle=False) as stored:
            quotes = {key: stored['quotes__' + key] for key in ('row', 'bid', 'ask')}
            orders = stored['orders']
            for method in methods:
                policy = next(i for i, spec in enumerate(result['specs']) if spec['id'] == method)
                trace = inventory_trace(orders[orders[:, 0] == policy, 1:], quotes, cap, multiplier, fee)
                row = next(row for row in result['runs'] if
                           (row['symbol'], row['session'], row['method']) == (symbol, scene, method))
                assert trace['cash'] == row['net']
                examples.append(dict(symbol=symbol, session=scene, method=method, **trace))
    top = next(x for x in examples if x['symbol'] == 'TOPIX' and x['method'] == methods[0])
    nk = next(x for x in examples if x['symbol'] == 'NK225' and x['method'] == methods[0])
    assert (top['counter_excess_episodes'], nk['counter_excess_episodes']) == (10, 13)
    assert {key: top['first_counter_excess'][key] for key in ('long', 'short', 'equity', 'cash')} == {
        'long': 2, 'short': 3, 'equity': -10796, 'cash': 13409}
    assert {key: top['first_lost_excess'][key] for key in ('long', 'short', 'equity', 'cash')} == {
        'long': 6, 'short': 4, 'equity': -33436, 'cash': 37474}
    keep = next(x for x in examples if x['symbol'] == 'TOPIX' and x['method'] == methods[1])
    assert {key: keep['first_both_caps'][key] for key in ('long', 'short', 'equity', 'basket_net')} == {
        'long': 10, 'short': 10, 'equity': -35068, 'basket_net': -56640}
    expected = {'TOPIX': (-323646, -35068, 11186), 'NK225': (-201544, 1896, 1896)}
    for symbol, values in expected.items():
        assert tuple(next(x['cash'] for x in examples if x['symbol'] == symbol and x['method'] == method)
                     for method in methods) == values
    source = WORK / 'knowledge120.py'
    proof = dict(passed=True, knowledge_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                 result_sha256='63766637c69f8572465b1ec3cc3c735e8eef234c1657b3ca0542bd3b6fa9f2ba',
                 totals=totals, examples=examples, original_market_reads=0, original_result_reads=0,
                 original_cache_reads=0, financial_replay=0, common_changes=0,
                 留保='既所有二場の保存注文会計。逆側超過は注文原行での状態遷移で時間占有率や全場確率ではない。純人工4経路は実装一致で方向予測成績ではない。')
    output = HERE / '最終知見八法則の追加三法則と所有二場の独立照合.json'
    assert not output.exists()
    raw = (json.dumps(proof, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    output.write_bytes(raw)
    print(json.dumps(dict(passed=True, sha256=hashlib.sha256(raw).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
