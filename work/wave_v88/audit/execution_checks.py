"""三源の配分実行を逐次注文台帳と独立会計で人工検査する。"""

from collections import defaultdict
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SOURCES = ('GU', 'M3', 'C03')


def module(name, path):
    """
    機能: 読取対象を今回だけの固有名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def hashes():
    """
    機能: 実行層・会計・配分と本検査器の指紋を記録する。
    引数: なし。
    返り値: dict[str,str]。編集中の研究実行器と源準備を含めない。
    """
    files = [WORK / n for n in ('execution.py', 'accounting.py', 'catalog.py')] + [Path(__file__)]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def save(name, value):
    """
    機能: 監査領域だけへ有限JSONを保存する。
    引数: name(str)、value(dict)。
    返り値: None。
    """
    path = HERE / name
    assert path.resolve().is_relative_to(HERE)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def same(a, b):
    """
    機能: 入れ子の会計を、キーを省略せず独立復元と比較する。
    引数: a/b(object)。
    返り値: None。
    """
    if isinstance(a, dict):
        assert a.keys() == b.keys(), (a.keys(), b.keys())
        for key in a:
            same(a[key], b[key])
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b)
        for first, second in zip(a, b):
            same(first, second)
    elif isinstance(a, np.ndarray):
        np.testing.assert_allclose(a, b, rtol=0, atol=1e-6)
    elif isinstance(a, (int, float, np.number)) and not isinstance(a, bool):
        assert math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-6), (a, b)
    else:
        assert a == b, (a, b)


def sample(symbol, reflected, scenario):
    """
    機能: 三源の同方向・反対方向・整数減量・同観測往復と場末予約を作る。
    引数: symbol(str)、reflected(bool)、scenario(str)。
    返り値: tuple[dict,dict]の価格素材と三源注文。
    """
    prices = np.array([100, 100, 101, 104, 103, 97, 99, 103, 108, 102, 101, 104, 103, 100, 98, 97, 99, 100, 102, 101.])
    times = np.arange(len(prices), dtype=float)
    data = {
        'GU': [(2, 0, 1, 5, 1), (6, 0, -1, 2, 0), (11, 0, -1, 3, 0)],
        'M3': [(2, 0, 1, 7, 1), (7, 0, -1, 1, 0), (12, 0, -1, 6, 0)],
        'C03': [(2, 0, 1, 3, 1), (5, 0, -1, 1, 0), (8, 0, -1, 1, 0), (13, 0, -1, 1, 0)]}
    limit = 17.
    if scenario == '反対方向が同時保有':
        data['M3'] = [(r, c, -s, q, new) for r, c, s, q, new in data['M3']]
    elif scenario == '同観測の新規と全返済':
        data = {name: [(2, 0, 1, q, 1), (2, 0, -1, q, 0)] for name, q in zip(SOURCES, (5, 7, 3))}
    elif scenario == '同観測の返済と新親の反転':
        data['GU'] = [(2, 0, 1, 5, 1), (6, 0, -1, 5, 0), (6, 9, -1, 4, 1), (11, 9, 1, 4, 0)]
    elif scenario == '同観測に三段の整数返済':
        data['GU'] = [(2, 0, 1, 5, 1), (6, 0, -1, 2, 0), (6, 0, -1, 2, 0), (6, 0, -1, 1, 0)]
    elif scenario == '紙上残一枚だが実玉ゼロ':
        data['M3'] = [(2, 0, 1, 101, 1), (5, 0, -1, 100, 0), (14, 0, -1, 1, 0)]
    elif scenario == '終端直前の新規予約取消':
        data = {name: [(16, 0, 1, q, 1), (18, 0, -1, q, 0)] for name, q in zip(SOURCES, (5, 7, 3))}
    elif scenario == '終端直前の返済予約を予定優先':
        data = {name: [(2, 0, 1, q, 1), (16, 0, -1, q, 0)] for name, q in zip(SOURCES, (5, 7, 3))}
    elif scenario == '終端を越えた紙上保持':
        data = {name: [(2, 0, 1, q, 1), (19, 0, -1, q, 0)] for name, q in zip(SOURCES, (5, 7, 3))}
    elif scenario == '同時計でも次原本行':
        times[3] = times[2]
        times[7] = times[6]
    elif scenario == '大きな欠番の親ID':
        data = {name: [(r, 5007 + c, s, q, new) for r, c, s, q, new in values] for name, values in data.items()}
    elif scenario == '一源だけ先に静観返済':
        data['GU'] = [(2, 0, 1, 5, 1), (4, 0, -1, 5, 0)]
    elif scenario == '全源が取引なし':
        data = {name: [] for name in SOURCES}
    elif scenario == 'GUだけ取引なし':
        data['GU'] = []
    factor = 1 if symbol == 'TOPIX' else 20
    amount = 1 if symbol == 'TOPIX' else 2
    prices = (200 - prices if reflected else prices) * factor
    sign = -1 if reflected else 1
    source = {}
    for name in SOURCES:
        source[name] = np.array([[r, max(0, r - 1), c, sign * s, q * amount, prices[r], 20 if new else 1, new]
            for r, c, s, q, new in data[name]], float).reshape(-1, 8)
    ready = dict(symbol=symbol, session='人工配分', last=prices, time_s=times, limit=limit)
    return ready, source


def reference(ready, source, budgets):
    """
    機能: 一観測ずつ前予約を処理し、当行公開の紙上数量から次観測目標を作る。
    引数: ready/source/budgets(dict)。
    返り値: dict。実装の計画先行方式とは別の逐次台帳。
    """
    n = len(ready['last'])
    factor = 1 if ready['symbol'] == 'TOPIX' else 2
    slots = [budgets[name] * factor for name in SOURCES]
    published = defaultdict(list)
    for s, name in enumerate(SOURCES):
        for j, order in enumerate(source[name]):
            if int(order[0]) < n:
                published[int(order[0])].append((s, j, order))
    paper = [dict(cid=-1, side=0, initial=0, remaining=0, target=0) for _ in SOURCES]
    live = [dict(cid=-1, side=0, quantity=0, uid=-1) for _ in SOURCES]
    queue, orders, trace = [], [], []
    uid = 0
    ended = False
    for row in range(n):
        if ready['time_s'][row] >= ready['limit']:
            if not ended:
                for s, state in enumerate(live):
                    if state['quantity']:
                        orders.append([row, row, s, state['cid'], -state['side'], state['quantity'], ready['last'][row], 99, 0, state['uid']])
                        state.update(quantity=0, side=0)
            queue = []
            ended = True
            continue
        for decision, s, cid, side, qty, reason, new in queue:
            state = live[s]
            if new:
                assert state['quantity'] == 0
                state.update(cid=cid, side=side, quantity=qty, uid=uid)
                uid += 1
            else:
                assert state['cid'] == cid and state['side'] == -side and qty <= state['quantity']
                state['quantity'] -= qty
            orders.append([row, decision, s, cid, side, qty, ready['last'][row], reason, new, state['uid']])
            if not state['quantity']:
                state['side'] = 0
        queue = []
        for s, j, order in sorted(published[row], key=lambda v: v[:2]):
            state = paper[s]
            cid, side, qty = map(int, order[2:5])
            before = state['target']
            if order[7]:
                state.update(cid=cid, side=side, initial=qty, remaining=qty, target=slots[s])
                change = slots[s]
            else:
                state['remaining'] -= qty
                state['target'] = math.floor(slots[s] * state['remaining'] / state['initial'])
                change = before - state['target']
            trace.append([row, s, cid, j, state['side'], state['initial'], state['remaining'], state['target'], change, int(order[7])])
            if change:
                queue.append((row, s, cid, side, change, int(order[6]), int(order[7])))
    return dict(orders=np.asarray(orders, float).reshape(-1, 10), target_trace=np.asarray(trace, float).reshape(-1, 10), terminal=live, slots=slots)


def independent_account(ready, result):
    """
    機能: 注文UID、源別親、実現脚、現金と原板評価を別の逐次台帳から復元する。
    引数: ready/result(dict)。
    返り値: tuple[dict,dict,ndarray,ndarray]の集計・台帳・全体時価・源別時価。
    """
    scale = 1000 if ready['symbol'] == 'TOPIX' else 10
    fee10 = 418 if ready['symbol'] == 'TOPIX' else 110
    orders = result['orders']
    by_row = defaultdict(list)
    for number, order in enumerate(orders):
        by_row[int(order[0])].append((number, order))
    entries, left, parents, legs, charges = {}, {}, {}, [], []
    cash, qty = [0., 0., 0.], [0, 0, 0]
    source_curve, states = [], []
    max_long = max_short = 0
    for row, price in enumerate(ready['last']):
        for number, order in by_row[row]:
            _, decision, s, cid, side, amount, fill, reason, new, uid = order
            s, cid, side, amount, uid = map(int, (s, cid, side, amount, uid))
            assert fill == price and amount > 0
            assert decision < row or (reason == 99 and decision == row and ready['time_s'][row] >= ready['limit'])
            fee = amount * fee10 // 10
            charges.append(fee)
            cash[s] -= side * amount * price * scale + fee
            qty[s] += side * amount
            max_long = max(max_long, sum(max(v, 0) for v in qty))
            max_short = max(max_short, sum(max(-v, 0) for v in qty))
            key = s, cid
            if key not in parents:
                parents[key] = dict(source=SOURCES[s], cid=cid, gross=0., fees=0., net=0., initial_qty=0, entry_row=None, exit_row=None)
            parent = parents[key]
            parent['fees'] += fee
            if new:
                assert uid not in entries
                assert uid == len(entries)
                entries[uid] = (s, cid, side, amount, price, fee, row)
                left[uid] = amount
                parent.update(initial_qty=amount, entry_row=row)
            else:
                es, ec, ed, eq, ep, ef, er = entries[uid]
                assert (es, ec, -ed) == (s, cid, side) and amount <= left[uid]
                left[uid] -= amount
                gross = ed * (price - ep) * amount * scale
                fee_part = ef * amount / eq + fee
                parent['gross'] += gross
                parent['exit_row'] = row
                legs.append(dict(source=SOURCES[s], cid=cid, uid=uid, side=ed, quantity=amount, entry_row=er, exit_row=row,
                    entry_price=float(ep), exit_price=float(price), gross=float(gross), fees=float(fee_part), net=float(gross - fee_part), reason=int(reason)))
        source_curve.append([cash[s] + qty[s] * price * scale - abs(qty[s]) * fee10 // 10 for s in range(3)])
        states.append(cash.copy() + qty.copy())
    assert all(v == 0 for v in left.values()) and not any(qty)
    for parent in parents.values():
        parent['net'] = parent['gross'] - parent['fees']
    source_curve = np.asarray(source_curve)
    curve = source_curve.sum(axis=1)
    nets = [p['net'] for p in parents.values()]
    profit = sum(v for v in nets if v > 0)
    loss = -sum(v for v in nets if v < 0)
    row = dict(session=ready['session'], symbol=ready['symbol'], gross=sum(p['gross'] for p in parents.values()),
        fees=sum(charges), net=sum(nets), profit=profit, loss=loss, profit_share=profit / (profit + loss) if profit + loss else None,
        campaigns=len(nets), wins=sum(v > 0 for v in nets), losses=sum(v < 0 for v in nets),
        new_lots=int(orders[orders[:, 8] == 1, 5].sum()), closed_lots=int(orders[orders[:, 8] == 0, 5].sum()),
        max_long=max_long, max_short=max_short,
        max_drawdown=float(np.max(np.maximum.accumulate(np.maximum(curve, 0)) - curve, initial=0)),
        curve_min=float(curve.min(initial=0)), curve_max=float(curve.max(initial=0)),
        source_totals={name: dict(gross=sum(p['gross'] for p in parents.values() if p['source'] == name),
            fees=sum(p['fees'] for p in parents.values() if p['source'] == name), net=source_curve[-1, s]) for s, name in enumerate(SOURCES)})
    states = np.asarray(states)
    change = np.r_[True, np.any(states[1:] != states[:-1], axis=1)]
    ledger = dict(orders=orders, fees=np.asarray(charges), parents=list(parents.values()), legs=legs,
        target_trace=result['target_trace'], slots=result['slots'], cash_position_changes=np.c_[np.flatnonzero(change), states[change]])
    assert abs(curve[-1] - row['net']) < 1e-6
    assert abs(sum(p['net'] for p in legs) - row['net']) < 1e-6
    return row, ledger, curve, source_curve


def rejection_tests(execution, config):
    """
    機能: 有効観測契約違反と、無配分でも必須の三源キー欠落を明示的に拒否するか確認する。
    引数: execution(module)、config(dict)。
    返り値: intの拒否対照数。
    """
    count = 0
    for value in (np.nan, np.inf, 0., -1.):
        ready, source = sample('TOPIX', False, '三源の通常部分返済')
        ready['last'][4] = value
        try:
            execution.execute(ready, source, config['budgets'])
        except AssertionError:
            count += 1
        else:
            raise AssertionError('無効価格を受理した')
    for name in SOURCES:
        ready, source = sample('TOPIX', False, '三源の通常部分返済')
        del source[name]
        try:
            execution.execute(ready, source, dict(GU=0, M3=0, C03=0))
        except KeyError:
            count += 1
        else:
            raise AssertionError('必須源の欠落を受理した')
    return count


def aggregate_test(accounting, rows, curves):
    """
    機能: 場を連結した全時価から累積下落を求め、要約値による期間集計と比較する。
    引数: accounting(module)、rows(list[dict])、curves(list[ndarray])。
    返り値: None。
    """
    continuity = [(r['curve_min'], r['curve_max'], r['max_drawdown']) for r in rows]
    actual = accounting.aggregate(rows, continuity)
    connected, offset = [], 0.
    for row, curve in zip(rows, curves):
        connected.extend((curve + offset).tolist())
        offset += row['net']
    values = np.asarray(connected)
    dd = float(np.max(np.maximum.accumulate(np.maximum(values, 0)) - values, initial=0))
    assert abs(actual['max_drawdown'] - dd) < 1e-6
    assert abs(actual['net'] - values[-1]) < 1e-6
    for key in ('gross', 'fees', 'net', 'profit', 'loss', 'campaigns', 'wins', 'losses', 'new_lots', 'closed_lots'):
        same(actual[key], sum(r[key] for r in rows))
    assert actual['no_trade_sessions'] == sum(r['campaigns'] == 0 for r in rows)


def main():
    """
    機能: 二商品・売買反射・全配分の人工執行、会計、全観測切断を一括検査する。
    引数: なし。
    返り値: None。実データの新成績は再生しない。
    """
    execution = module('監査88配分実行', WORK / 'execution.py')
    accounting = module('監査88配分会計', WORK / 'accounting.py')
    catalog = module('監査88配分条件', WORK / 'catalog.py')
    before = hashes()
    scenarios = ['三源の通常部分返済', '反対方向が同時保有', '同観測の新規と全返済',
        '同観測の返済と新親の反転', '同観測に三段の整数返済', '紙上残一枚だが実玉ゼロ',
        '終端直前の新規予約取消', '終端直前の返済予約を予定優先', '終端を越えた紙上保持',
        '同時計でも次原本行', '大きな欠番の親ID', '一源だけ先に静観返済', '全源が取引なし', 'GUだけ取引なし']
    records, prefixes = [], 0
    all_rows, all_curves = defaultdict(list), defaultdict(list)
    for symbol in ('TOPIX', 'NK225'):
        for reflected in (False, True):
            for scenario in scenarios:
                ready, sources = sample(symbol, reflected, scenario)
                for config in catalog.catalog():
                    actual = execution.execute(ready, sources, config['budgets'])
                    expected = reference(ready, sources, config['budgets'])
                    for name in expected:
                        same(actual[name], expected[name])
                    row, ledger, curve, source_curve = accounting.account(ready, actual)
                    erow, eledger, ecurve, esource_curve = independent_account(ready, actual)
                    same(row, erow)
                    same(ledger, eledger)
                    same(curve, ecurve)
                    same(source_curve, esource_curve)
                    if scenario == '同観測の新規と全返済':
                        assert row['max_long' if not reflected else 'max_short'] == max(actual['slots'])
                    if scenario == '全源が取引なし':
                        assert row['profit_share'] is None and row['wins'] == row['campaigns'] == 0
                    for count in range(1, len(ready['last'])):
                        short_ready = dict(ready, last=ready['last'][:count], time_s=ready['time_s'][:count])
                        short = execution.execute(short_ready, sources, config['budgets'], finish=False)
                        np.testing.assert_array_equal(short['orders'], actual['orders'][actual['orders'][:, 0] < count])
                        np.testing.assert_array_equal(short['target_trace'], actual['target_trace'][actual['target_trace'][:, 0] < count])
                        expected_short = reference(short_ready, sources, config['budgets'])
                        same(short['terminal'], expected_short['terminal'])
                        prefixes += 1
                    all_rows[symbol].append(row)
                    all_curves[symbol].append(curve)
                    records.append(dict(商品=symbol, 反射=reflected, 人工経路=scenario, 配分=config['id'],
                        注文数=len(actual['orders']), 親組数=row['campaigns'], 最大買枚数=row['max_long'], 最大売枚数=row['max_short']))
    rejected = rejection_tests(execution, catalog.catalog()[0])
    for symbol in all_rows:
        aggregate_test(accounting, all_rows[symbol], all_curves[symbol])
    assert before == hashes()
    save('三源配分の逐次執行と独立会計の人工検査.json', dict(全合格=True, 検査数=len(records),
        未来切断地点数=prefixes, 不正入力拒否数=rejected, 源別時価照合=True, 期間全時価接続照合=2,
        検査=records, コードSHA256=before,
        修正確認='同観測の新規と返済でも、注文ごとの瞬間最大保有が実際の配分枚数として報告される。',
        素材契約='入力価格は前準備済みの有効観測だけ。無効価格は拒否。無配分でも三源キーは必須、取引なしは空配列で表す。'))
    print(json.dumps(dict(全合格=True, 検査数=len(records), 未来切断地点数=prefixes, 不正入力拒否数=rejected), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
