"""完了公開・厳密過去・途中復帰禁止・窓の境界を独立の人工台帳で検査する。"""

from copy import deepcopy
from pathlib import Path
import json
import numpy as np
import common
import independent


def fingerprints():
    """
    機能: 今回の対象と独立検査器、既往の読取道具の指紋を記録する。
    引数: なし。
    返り値: dict[str,str]。
    """
    paths = [common.WORK / name for name in ('engine.py', 'strategy.py', 'catalog.py')]
    paths += [Path(__file__), common.HERE / 'common.py', common.HERE / 'independent.py']
    paths += [common.ROOT / 'work/wave_v88/audit/execution_checks.py', common.ROOT / 'work/wave_v88/audit/full.py',
        common.ROOT / 'work/wave_v88/execution.py', common.ROOT / 'work/wave_v88/accounting.py']
    return common.fingerprints(paths)


def history(ready, budgets, values, clock=-100.):
    """
    機能: 完了済みだけからなる前場の検査用履歴を、商品と配分別に作る。
    引数: ready/budgets(dict)、values(list[float])、clock(float)。
    返り値: dict[str,list[dict]]。
    """
    factor = 1 if ready['symbol'] == 'TOPIX' else 2
    result = {name: [] for name in common.SOURCES}
    for name in common.SOURCES:
        q = budgets[name] * factor
        if not q:
            continue
        for j, net in enumerate(values):
            fees = 2 * (q * (418 if ready['symbol'] == 'TOPIX' else 110) // 10)
            result[name].append(dict(source=name, symbol=ready['symbol'], session='人工前場', cid=-1000 + j,
                allocated_quantity=q, entry_row=1, entry_price=100., side=1, gross=float(net + fees), fees=fees,
                net=float(net), last_exit_row=2, allocated_flat_row=2, publish_row=2,
                publish_time=float(clock + j), source_end_decision_row=1, source_ended=True,
                reason=1, publication='source_end'))
    return result


def series(symbol, reflected, scenario):
    """
    機能: 四件準備・窓の最古脱落・拒否後回復・同時計公開を検査する長い人工系列を作る。
    引数: symbol(str)、reflected(bool)、scenario(str)。
    返り値: tuple[dict,dict]の有効価格と三源注文。
    """
    n = 90
    prices = np.full(n, 100.)
    times = np.arange(n, dtype=float)
    result = {name: [] for name in common.SOURCES}
    for j in range(24):
        row = j * 3 + 1
        change = -2. if j < 9 else 2.
        if scenario == '仮想連敗とゼロの混在':
            change = -2. if j % 5 < 3 else 2.
        if scenario == '仮想先勝ち後負け':
            change = 2. if j < 9 else -2.
        prices[row + 1] = 100.
        prices[row + 2] = 100. + change
        if scenario == '完了と次判断が同時計':
            times[row + 3] = times[row + 2]
        for name, q in zip(common.SOURCES, (5, 7, 3)):
            result[name].extend([(row, row - 1, j * 19 + 7, 1, q, 100., 20, 1),
                (row + 1, row, j * 19 + 7, -1, q, 100., 1, 0)])
    factor, sign = (1 if symbol == 'TOPIX' else 20), (-1 if reflected else 1)
    prices = (200 - prices if reflected else prices) * factor
    lot_factor = 1 if symbol == 'TOPIX' else 2
    source = {}
    for name, values in result.items():
        source[name] = np.asarray([[r, d, cid, side * sign, q * lot_factor, prices[r], reason, new]
            for r, d, cid, side, q, p, reason, new in values], float).reshape(-1, 8)
    ready = dict(symbol=symbol, session='人工連続親', last=prices, time_s=times, limit=87.)
    return ready, source


def compare(actual, expected):
    """
    機能: 逐次実行の全注文・目標・完了・採否根拠を独立復元と照合する。
    引数: actual/expected(dict)。
    返り値: None。
    """
    for name in ('orders', 'target_trace', 'terminal', 'slots', 'completion_records', 'history_out'):
        common.OLD.same(actual[name], expected[name])
    for name in ('orders', 'target_trace', 'terminal', 'slots'):
        common.OLD.same(actual['virtual_result'][name], expected['virtual_result'][name])
    assert len(actual['gate_trace']) == len(expected['gate_trace'])
    for a, b in zip(actual['gate_trace'], expected['gate_trace']):
        for name in b:
            if name != 'reason':
                common.OLD.same(a[name], b[name])
        assert all(r['publish_time'] < a['time'] for r in a['selected'])


def direct(engine):
    """
    機能: 比率ちょうど0.6・厳密過去・準備不足・ゼロ分母・連敗解除の独立反例を検査する。
    引数: engine(module)。
    返り値: list[dict]。
    """
    records = []
    ready = dict(symbol='TOPIX')
    budgets = dict(GU=6, M3=2, C03=2)
    cases = [([], '準備0件'), ([1., -2., 0.], '準備3件'), ([3., -2., 0., 0.], '比率厳密0.6'),
        ([0.] * 4, 'ゼロ分母'), ([-1.] * 17 + [2.] * 8, '最古損失が窓外'),
        ([2.] * 17 + [-1.] * 8, '最古利益が窓外')]
    for values, label in cases:
        values = history(ready, budgets, values)['GU']
        for window in (8, 16):
            base = dict(mode='share', window=window, threshold=.6, minimum_completed=4)
            normal = engine.decide(base, values, 0., 6)
            reverse = engine.decide(dict(base, reverse=True), values, 0., 6)
            for gate, observed in ((base, normal), (dict(base, reverse=True), reverse)):
                expected = independent.evaluate(gate, values, 6)
                for key in expected:
                    if key != 'reason':
                        common.OLD.same(observed[key], expected[key])
            if len(values) >= 4 and normal['profit_share'] is not None:
                assert normal['allowed'] != reverse['allowed']
            else:
                assert normal['allowed'] and reverse['allowed']
            if label == '比率厳密0.6':
                assert normal['profit_share'] == .6 and normal['allowed'] and not reverse['allowed']
            records.append(dict(検査=label, 窓=window, 通常採用=normal['allowed'], 逆対照採用=reverse['allowed'],
                使用件数=len(normal['selected']), 割合=normal['profit_share']))
    for values in ([-1.], [-1.] * 3, [-1.] * 5 + [0.], [-1.] * 5 + [1.]):
        values = history(ready, budgets, values)['GU']
        for losses in (1, 2, 3):
            gate = dict(mode='streak', loss_count=losses, minimum_completed=4)
            observed = engine.decide(gate, values, 0., 6)
            expected = independent.evaluate(gate, values, 6)
            assert observed['allowed'] == expected['allowed'] and not observed['warmup']
            assert observed['loss_streak'] == expected['loss_streak']
            records.append(dict(検査='初回からの連敗とゼロ解除', 閾値=losses, 過去損益=[r['net'] for r in values],
                連敗数=observed['loss_streak'], 採用=observed['allowed']))
    same_time = history(ready, budgets, [1., 1., 1., 1.], clock=-4.)['GU']
    same_time.extend(history(ready, budgets, [-1000000.], clock=0.)['GU'])
    for mode in ('share', 'streak'):
        gate = dict(mode=mode, window=8 if mode == 'share' else 0, threshold=.6, loss_count=1, minimum_completed=4)
        observed = engine.decide(gate, same_time, 0., 6)
        assert observed['allowed'] and observed['available'] == 4
        later = engine.decide(gate, same_time, .1, 6)
        assert not later['allowed'] and later['available'] == 5
        records.append(dict(検査='同時計の後続seqも未公開', 手法=mode, 同時計採用=observed['allowed'], 後時計採用=later['allowed']))
    return records


def main():
    """
    機能: 全81条件に人工境界を当て、実データの新損益を計算せず凍結前証拠を保存する。
    引数: なし。
    返り値: None。
    """
    engine = common.module('監査89対象実行', common.WORK / 'engine.py')
    catalog = common.module('監査89対象条件', common.WORK / 'catalog.py')
    accounting = common.module('監査89読取88会計', common.ROOT / 'work/wave_v88/accounting.py')
    before = fingerprints()
    configs = catalog.catalog()
    assert len(configs) == 81
    direct_records = direct(engine)
    scenarios = ['三源の通常部分返済', '反対方向が同時保有', '同観測の新規と全返済',
        '同観測の返済と新親の反転', '同観測に三段の整数返済', '紙上残一枚だが実玉ゼロ',
        '終端直前の新規予約取消', '終端直前の返済予約を予定優先', '終端を越えた紙上保持',
        '同時計でも次原本行', '大きな欠番の親ID', '一源だけ先に静観返済', '全源が取引なし', 'GUだけ取引なし',
        '仮想連敗後の勝ちで復帰', '仮想先勝ち後負け', '仮想連敗とゼロの混在', '完了と次判断が同時計']
    records, cuts, poisons = [], 0, 0
    for symbol in ('TOPIX', 'NK225'):
        for reflected in (False, True):
            for scenario in scenarios:
                ready, source = series(symbol, reflected, scenario) if scenario in scenarios[-4:] else common.OLD.sample(symbol, reflected, scenario)
                for config in configs:
                    gate, budgets = config['gate'], config['budgets']
                    inherited = history(ready, budgets, [3., -2., 0., -4., 10., -2., -5., 0., 2.])
                    actual = engine.execute(ready, source, budgets, gate, inherited)
                    expected = independent.execution(ready, source, budgets, gate, inherited)
                    compare(actual, expected)
                    row, ledger, equity, source_equity = accounting.account(ready, actual)
                    erow, eledger, ecurve, esource = common.OLD.independent_account(ready, actual)
                    common.OLD.same(row, erow)
                    common.OLD.same(ledger, eledger)
                    common.OLD.same(equity, ecurve)
                    common.OLD.same(source_equity, esource)
                    allowed = {(common.SOURCES.index(r['source']), r['cid']) for r in actual['gate_trace'] if r['allowed']}
                    kept = np.asarray([order for order in actual['virtual_result']['orders']
                        if (int(order[2]), int(order[3])) in allowed], float).reshape(-1, 10)
                    np.testing.assert_array_equal(actual['orders'][:, :9], kept[:, :9])
                    vrow, vledger, _, _ = accounting.account(ready, actual['virtual_result'])
                    virtual_parents = {(p['source'], p['cid']): p for p in vledger['parents']}
                    for parent in ledger['parents']:
                        common.OLD.same(parent, virtual_parents[parent['source'], parent['cid']])
                    if scenario == '全源が取引なし':
                        assert row['profit_share'] is None and row['wins'] == row['campaigns'] == 0
                    if scenario == '紙上残一枚だが実玉ゼロ' and budgets['M3']:
                        item = next(r for r in actual['completion_records'] if r['source'] == 'M3')
                        assert item['allocated_flat_row'] == 6 and item['publish_row'] == 15
                    if gate['mode'] == 'all':
                        common.OLD.same(actual['orders'], actual['virtual_result']['orders'])
                        common.OLD.same(actual['target_trace'], actual['virtual_result']['target_trace'])
                    if scenario in ('三源の通常部分返済', '紙上残一枚だが実玉ゼロ', '完了と次判断が同時計'):
                        count_set = set(range(1, len(ready['last']))) if scenario != '完了と次判断が同時計' else {2, 7, 13, 25, 43, 61, 73}
                        for count in sorted(count_set):
                            short = dict(ready, last=ready['last'][:count], time_s=ready['time_s'][:count])
                            partial = engine.execute(short, source, budgets, gate, inherited, finish=False)
                            np.testing.assert_array_equal(partial['orders'], actual['orders'][actual['orders'][:, 0] < count])
                            np.testing.assert_array_equal(partial['target_trace'], actual['target_trace'][actual['target_trace'][:, 0] < count])
                            common.OLD.same(partial['completion_records'], [r for r in actual['completion_records'] if r['publish_row'] < count])
                            common.OLD.same(partial['gate_trace'], [r for r in actual['gate_trace'] if r['row'] < count])
                            short_expected = independent.execution(short, source, budgets, gate, inherited, finish=False)
                            compare(partial, short_expected)
                            cuts += 1
                        count = 10
                        poison = dict(ready, last=ready['last'].copy())
                        poison['last'][count:] = poison['last'][count:] * 17 + 3000
                        changed = engine.execute(poison, source, budgets, gate, inherited)
                        np.testing.assert_array_equal(changed['orders'][changed['orders'][:, 0] < count], actual['orders'][actual['orders'][:, 0] < count])
                        common.OLD.same([r for r in changed['gate_trace'] if r['row'] < count], [r for r in actual['gate_trace'] if r['row'] < count])
                        poisons += 1
                    records.append(dict(商品=symbol, 売買反射=reflected, 人工経路=scenario, 条件=config['id'],
                        実注文数=len(actual['orders']), 仮想注文数=len(actual['virtual_result']['orders']),
                        完了数=len(actual['completion_records']), 採否数=len(actual['gate_trace']),
                        実親数=row['campaigns'], 最大買枚数=row['max_long'], 最大売枚数=row['max_short']))
            print(symbol, reflected, '人工逐次台帳・公開完了・会計一致', flush=True)
    assert before == fingerprints()
    common.save('仮想完了ゲートの順序と全81条件の人工検査.json', dict(全合格=True, 条件数=len(configs),
        人工口座数=len(records), 未来切断地点数=cuts, 将来価格毒入れ数=poisons,
        独立境界検査=direct_records, 検査=records, コード素材SHA256=before,
        新全期間損益計算=False, 確定公開='元紙上親の全返済判断の次有効観測。整数配分が途中ゼロでも終了公開まで待つ。',
        厳密過去='publish_time < 新規判断timeだけ使用。同時計の後続seqも参照不可。',
        会計='手数料を整数十分の一円から注文ごと切捨てし、独立源親と原板清算時価を照合。無取引・ゼロ損益は勝ちにしない。'))
    print(json.dumps(dict(全合格=True, 人工口座数=len(records), 未来切断地点数=cuts, 将来価格毒入れ数=poisons), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
