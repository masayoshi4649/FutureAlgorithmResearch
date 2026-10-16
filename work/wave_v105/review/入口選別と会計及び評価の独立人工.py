"""105純部品を未来勝敗なしの人工だけで独立算式へ照合する。"""

from copy import deepcopy
from decimal import Decimal, ROUND_CEILING
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WAVE = HERE.parent
ROOT = WAVE.parents[1]


def module(name: str, path: Path) -> object:
    """
    機能: 純計算部品だけを固有名へ読取接続する。
    引数: name(str)、path(Path)は小source。
    返り値: object。全入力、金融再生、原本、APIは呼ばない。
    """
    specification = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(specification)
    sys.modules[name] = value
    specification.loader.exec_module(value)
    return value


COMMON = module('105独立純部品のcommon', WAVE/'common.py')
sys.modules['common'] = COMMON
FILTER = module('105独立人工の入口選別', WAVE/'filters.py')
ACCOUNT = module('105独立人工の会計', WAVE/'accounting.py')
EVALUATE = module('105独立人工の評価', WAVE/'evaluation.py')
CATALOG = module('105独立人工の固定候補', WAVE/'catalog.py')


def charge(quantity: int, symbol: str) -> int:
    """
    機能: 注文ごとの料金を十進数から独立に切り捨てる。
    引数: quantity(int)、symbol(str)は実枚数と商品。
    返り値: intは円料。枚数合計を先に相殺しない。
    """
    return int(Decimal(quantity)*Decimal('41.8' if symbol == 'TOPIX' else '11'))


def expected_filter(prepared: dict, case: dict, feature: dict | None, config: dict) -> tuple[bool, int]:
    """
    機能: Decimalの予定余地と有限な方向効率から採否理由を独立に求める。
    引数: prepared/case/config(dict)、feature(dict|None)は人工の当時情報。
    返り値: tuple[bool,int]は採否と理由bit。未来勝敗を参照しない。
    """
    if config['filter_mode'] == 'NONE':
        return True, 0
    if feature is None:
        return False, 1
    row, record = 1, prepared['record']
    side = int(case['event'][row])
    tick = Decimal(str(record['tick']))
    steps = int((Decimal(str(prepared['reference_open']))*Decimal(str(config['initial_stop_fraction']))/tick).to_integral_value(rounding=ROUND_CEILING))
    width = Decimal(max(2, steps))*tick
    entry = Decimal(str(record['ask' if side == 1 else 'bid'][row]))
    quote = Decimal(str(record['bid' if side == 1 else 'ask'][row]))
    support = Decimal(str(case['support_price'][row]))
    stop = max(side*support-config['support_ticks']*tick, side*entry-width)
    clearance = (side*quote-stop)/tick
    mode, reason = config['filter_mode'], 0
    own = feature['own' if config['own_path'] == 'PUBLIC' else 'own_normal'].get(str(config['window']))
    peer = feature['peer'].get(str(config['window']))
    if own is None or not own['known']:
        reason |= 1
    elif own['count'] < 3:
        reason |= 2
    else:
        if 'E' in mode:
            value = own['efficiency']
            if value is not None and not math.isfinite(value):
                reason |= 1
            elif value is None or value <= .5:
                reason |= 4
        if 'N' in mode:
            value = own['max_adverse_ticks']
            if value is None or not math.isfinite(value):
                reason |= 1
            elif clearance <= Decimal(str(value))+Decimal('0.000000001'):
                reason |= 32
    if 'P' in mode:
        if peer is None or not peer['known']:
            reason |= 1
        elif peer['count'] < 3:
            reason |= 8
        else:
            value = peer['efficiency']
            if value is not None and not math.isfinite(value):
                reason |= 1
            elif value is None or value <= .5:
                reason |= 16
    return reason == 0, reason


def filter_fixture(symbol: str, side: int, name: str) -> tuple[dict, dict, dict]:
    """
    機能: 同時計候補、強弱、未知、効率境界と逆行余地境界を作る。
    引数: symbol(str)、side(int)、name(str)は商品と方向及び人工名。
    返り値: tuple[dict,dict,dict]はprepared、case、特徴表。
    """
    tick, reference = (.5, 1000.) if symbol == 'TOPIX' else (10., 10000.)
    record = dict(seq=np.arange(100, 105), tick=tick, time_s=np.array([300., 301., 301., 305., 310.]),
        bid=np.full(5, reference), ask=np.full(5, reference+tick))
    case = dict(event=np.array([0, side, 0, 0, 0]), support_price=np.full(5, reference if side == 1 else reference+tick),
        decisions=[dict(row=1, side=side, raw_seq=101)])
    prepared = dict(record=record, reference_open=reference)
    value = dict(known=True, count=5, efficiency=.8, max_adverse_ticks=.25)
    feature = {role: {'10': deepcopy(value), '30': deepcopy(value)} for role in ('own', 'own_normal', 'peer')}
    if name == '特徴なし':
        return prepared, case, {}
    for window in ('10', '30'):
        own, peer = feature['own_normal'][window], feature['peer'][window]
        if name == '自己未知':
            own['known'] = False
        elif name == '自己2観測':
            own['count'] = 2
        elif name == '効率ちょうど半分':
            own['efficiency'] = .5
        elif name == '効率半分の直上':
            own['efficiency'] = .500000001
        elif name == '逆方向':
            own['efficiency'] = -.8
        elif name == '自己NaN':
            own['efficiency'] = float('nan')
        elif name == '自己Infinity':
            own['efficiency'] = float('inf')
        elif name == '自己停止余地None':
            own['max_adverse_ticks'] = None
        elif name == '逆行余地ちょうど':
            own['max_adverse_ticks'] = 1.
        elif name == '逆行余地厳密下':
            own['max_adverse_ticks'] = .999999998
        elif name == '相手未知':
            peer['known'] = False
        elif name == '相手2観測':
            peer['count'] = 2
        elif name == '相手NaN':
            peer['efficiency'] = float('nan')
        elif name == '公表圧縮だけ強い':
            own['efficiency'] = .1
    return prepared, case, {1: feature}


def financial_fixture(symbol: str, side: int, quantity: int) -> tuple[dict, dict, float]:
    """
    機能: 執行コードを使わず、途中の不正quoteを越える物理注文と現金を作る。
    引数: symbol(str)、side(int)、quantity(int)は商品、方向、枚数。
    返り値: tuple[dict,dict,float]はrecord、人工全会計、独立net。
    """
    tick, reference, multiplier = (.5, 1000., 1000) if symbol == 'TOPIX' else (10., 10000., 10)
    times = np.arange(300., 306.)
    bid = np.array([reference]*4+[reference+side*2*tick]*2)
    ask = bid+tick
    record = dict(seq=np.arange(6), time_s=times, bid=bid, ask=ask,
        quote_valid=np.array([True, True, False, True, True, True]))
    entry, exit_price = float(ask[3] if side == 1 else bid[3]), float(bid[5] if side == 1 else ask[5])
    fee = charge(quantity, symbol)
    gross = float(Decimal(side*quantity*multiplier)*(Decimal(str(exit_price))-Decimal(str(entry))))
    net = gross-2*fee
    orders = np.array([[3, 1, 1, 0, side, quantity, entry, 1, 10, fee, times[1], times[3], 0, 1, 10, side, 1],
        [5, 4, 1, 0, -side, quantity, exit_price, 0, 1, fee, times[4], times[5], 0, 1, 1, side, 2]], float)
    trades = np.array([[1, 0, 3, 5, side, quantity, entry, exit_price, fee, fee, gross, net, 10, 1, 1, 1]], float)
    columns = ['parent_id', 'cohort_id', 'source', 'side', 'quantity', 'decision_row', 'decision_seq', 'decision_time',
        'entry_row', 'entry_seq', 'entry_time', 'entry_price', 'entry_fee', 'order_uid', 'exit_row', 'exit_seq', 'exit_time',
        'exit_price', 'exit_fee_share', 'gross', 'net', 'risk_budget', 'initial_quantity', 'entry_kind', 'parent_final_quantity']
    cohort = np.array([[1, 1, 0, side, quantity, 1, 1, times[1], 3, 3, times[3], entry, fee, 1, 5, 5, times[5],
        exit_price, fee, gross, net, 100, quantity, 0, quantity]], float)
    cash, position = Decimal(0), 0
    curve = []
    for row in range(6):
        for order in orders[orders[:, 0] == row]:
            action = int(order[4])
            cash -= Decimal(action*quantity*multiplier)*Decimal(str(order[6]))+Decimal(fee)
            position += action*quantity
        equity = cash
        if position:
            equity += Decimal(position*multiplier)*Decimal(str(bid[row] if position > 0 else ask[row]))-Decimal(fee)
        curve.append(float(equity))
    curve = np.array(curve)
    trace = np.zeros((6, 6))
    direction = 0 if side == 1 else 1
    trace[1:3, 2+direction] = quantity
    trace[1:3, 4] = quantity
    trace[3:5, direction] = trace[3:5, 2+direction] = quantity
    trace[4, 5] = quantity
    stats = np.zeros(16)
    stats[:4] = trace[:, :4].max(axis=0)
    stats[15] = net
    events = np.array([[1, 1, 0, 1], [3, 1, 0, 4], [4, 1, 0, 2], [5, 1, 0, 5], [5, 1, 0, 8]], float)
    output = dict(orders=orders, trades=trades, curve=curve, source_curve=np.column_stack((curve, np.zeros(6))),
        growth_cohorts=cohort, growth_cohort_columns=columns, target_trace=trace,
        trace_columns=['held_long', 'held_short', 'occupied_long', 'occupied_short', 'pending_entry', 'pending_exit'],
        stats=stats, stat_columns=['項目'+str(i) for i in range(16)], events=events)
    return record, output, net


def evaluation_row(session: str, symbol: str, nets: list, budget: float = 100.) -> dict:
    """
    機能: 取引金額を相殺前に分け、評価人工の一場会計を別算式で作る。
    引数: session/symbol(str)、nets(list[float])、budget(float)は場、商品、実親netと配置単位。
    返り値: dictは評価入力。架空データだけで、実入力は読まない。
    """
    positive, negative = [value for value in nets if value > 0], [value for value in nets if value < 0]
    profit, loss = sum(positive), -sum(negative)
    return dict(session=session, symbol=symbol, profit=profit, loss=loss, net=profit-loss,
        gross=sum(nets), fees=0, campaigns=len(nets), winning_campaigns=len(positive), losing_campaigns=len(negative),
        flat_campaigns=len(nets)-len(positive)-len(negative), winning_lots=len(positive), losing_lots=len(negative),
        flat_lots=len(nets)-len(positive)-len(negative), lots=len(nets), budget_unit=budget,
        equity_drawdown=max([0.]+[-value for value in nets]))


def main() -> None:
    """
    機能: 51候補の入口選別、Decimal物理会計、差分寄与と両商品評価を独立人工で検証する。
    引数: なし。
    返り値: None。私有人工証跡を保存する。新正式金融と巨大入力は未読。
    """
    paths = [Path(__file__), *[WAVE/name for name in ('catalog.py', 'filters.py', 'accounting.py', 'evaluation.py', 'common.py')]]
    before = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    configs = CATALOG.catalog()
    assert len(configs) == 51 and len({value['id'] for value in configs}) == 51
    assert all(value['quantity'] == {'TOPIX': 10, 'NK225': 20} for value in configs)
    counts, checks = {}, {}
    filtered = 0
    names = ('正常', '特徴なし', '自己未知', '自己2観測', '効率ちょうど半分', '効率半分の直上', '逆方向',
        '自己NaN', '自己Infinity', '自己停止余地None', '逆行余地ちょうど', '逆行余地厳密下', '相手未知', '相手2観測', '相手NaN', '公表圧縮だけ強い')
    for config in configs:
        for symbol in ('TOPIX', 'NK225'):
            for side in (1, -1):
                for name in names:
                    prepared, case, features = filter_fixture(symbol, side, name)
                    actual = FILTER.apply(prepared, case, features, config)
                    expected = expected_filter(prepared, case, features.get(1), config)
                    assert (bool(actual[0][1]), int(actual[1][1])) == expected, (config['id'], symbol, side, name, expected, actual[1][1])
                    changed = deepcopy(prepared)
                    changed['record']['bid'][2:] *= 100
                    changed['record']['ask'][2:] *= 100
                    changed['未来の勝敗'] = '任意の勝ち'
                    later = FILTER.apply(changed, case, features, config)
                    np.testing.assert_array_equal(actual[0], later[0])
                    np.testing.assert_array_equal(actual[1], later[1])
                    filtered += 1
    counts['全51条件両市場買売の入口人工'] = filtered
    checks['未来価格と勝敗を変えても当時採否不変'] = True
    physical, corrupt = 0, 0
    for symbol, cap in (('TOPIX', 10), ('NK225', 20)):
        for side in (1, -1):
            for quantity in (1, cap):
                record, output, expected = financial_fixture(symbol, side, quantity)
                actual = ACCOUNT.inspect(('人工', symbol), record, output)
                assert actual['net'] == expected
                physical += 1
                for item in ('次quote', '料金', '時価'):
                    wrong = deepcopy(output)
                    if item == '次quote':
                        wrong['orders'][0, 1] = 3
                    elif item == '料金':
                        wrong['orders'][0, 9] += 1
                    else:
                        wrong['curve'][3] += 1
                        wrong['source_curve'][3, 0] += 1
                    try:
                        ACCOUNT.inspect(('人工', symbol), record, wrong)
                    except AssertionError:
                        corrupt += 1
                    else:
                        raise AssertionError('物理会計破損を拒否しません '+item)
    counts.update(Decimal物理会計人工=physical, 意図的物理破損拒否=corrupt)
    def item(net: float) -> dict:
        """
        機能: 入出対応の差分だけを持つ人工実親を作る。
        引数: net(float)は人工収支。
        返り値: dictは同じ入口価格/行/数量を持つ親。
        """
        return dict(net=net, entry_row=1, quantity=10, entry_price=1000.)
    baseline = {'a': item(-100), 'b': item(500), 'c': item(200), 'd': item(0)}
    changed = {'c': item(150), 'e': item(-50)}
    value = ACCOUNT.contribution(baseline, changed)
    assert value['収支変化'] == -500 and value['避けた基準損失'] == 100 and value['失った基準利益'] == 500
    assert value['共通入口の出口変化'] == -50 and value['新たな入口の収支'] == -50
    assert '保有' in value['注意'] and '予測改善とは呼ばない' in value['注意']
    checks['入口消失を単純な予測成功としない差分恒等式'] = True
    sessions = ['人工'+str(i) for i in range(6)]
    base_rows, strong_rows, rare_rows = [], [], []
    for symbol in ('TOPIX', 'NK225'):
        for i, session in enumerate(sessions):
            base_rows.append(evaluation_row(session, symbol, [100]*4 if i % 2 == 0 else [-50]*4))
            strong_rows.append(evaluation_row(session, symbol, [100]*4))
            rare_rows.append(evaluation_row(session, symbol, [10000]*20 if i == 0 else []))
    judged = EVALUATE.assess({'基準': dict(rows=base_rows), '安定': dict(rows=strong_rows), '一発': dict(rows=rare_rows)}, sessions, '基準')
    assert judged['results']['安定']['adopted'] and not judged['results']['一発']['eligible']
    assert judged['results']['一発']['symbols']['TOPIX']['without_best_net'] == 0
    assert judged['results']['一発']['symbols']['NK225']['no_trade_sessions'] == 5
    assert judged['results']['基準']['symbols']['TOPIX']['profit_share'] == 2/3
    assert judged['results']['安定']['symbols']['TOPIX']['payoff'] is None
    inactive = [evaluation_row(session, symbol, []) for symbol in ('TOPIX', 'NK225') for session in sessions]
    unknown_baseline = EVALUATE.assess({'未知基準': dict(rows=inactive), '安定': dict(rows=strong_rows)}, sessions, '未知基準')
    assert not unknown_baseline['results']['安定']['adopted']
    assert unknown_baseline['results']['未知基準']['symbols']['TOPIX']['profit_share'] is None
    assert not unknown_baseline['results']['未知基準']['all_sessions_positive']
    rejected = 0
    for name in ('重複場', '零予算', 'NaN予算', 'NaN収支'):
        wrong = deepcopy(strong_rows)
        if name == '重複場':
            wrong[1]['session'] = wrong[0]['session']
        elif name == '零予算':
            wrong[0]['budget_unit'] = 0
        elif name == 'NaN予算':
            wrong[0]['budget_unit'] = float('nan')
        else:
            wrong[0]['net'] = float('nan')
        try:
            EVALUATE.summarize(wrong, 'TOPIX', sessions)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError('不正評価入力を拒否しません '+name)
    counts['不正評価入力拒否'] = rejected
    checks['無活動を勝ちとせず大勝ち除外と両商品80を別判定'] = True
    after = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    assert before == after
    proof = dict(全合格=True, scope='105純部品の独立人工。新51×全33金融及び巨大入力は未読。',
        検査件数=counts, 検査=checks, source_SHA256=before,
        限界='寄与分解は会計恒等式。保有/予約で消えた入口とフィルタ拒否の当時理由別分解はrunnerのcontrol保存で別途確認する。配置予算は実リスク幅の等価を意味しない。',
        金融本体再生=0, 正式金融読取=0, 旧巨大入力読取=0, 原本読取=0, NPZ読取=0, API取得=0, goal操作=0)
    target = HERE/'入口選別と会計及び評価の独立人工.json'
    assert not target.exists()
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査件数=counts, SHA256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
