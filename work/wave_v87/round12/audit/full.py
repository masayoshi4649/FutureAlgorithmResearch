"""有利指値の全保存会計を注文から復元し、成立親と見送り親の差を独立照合する。"""

from collections import defaultdict
import json
import math
from pathlib import Path
import pickle
import sys
import numpy as np
import checks


def roles(ledger, mode):
    """
    機能: 今回の単独元玉を全て役割ゼロとし、予定返済だけ役割を限定しない。
    引数: ledger(dict)、mode(str)。
    返り値: ndarray[int]。UID検算器へ渡す分類であり取引は生成しない。
    """
    result = np.zeros(len(ledger['orders']), int)
    result[np.isin(ledger['orders'][:, 6], (92, 93))] = -1
    return result


def trace(ready, ledger, mode, row, proof, independent):
    """
    機能: 注文別現金・数量・料金を原板全行へ展開し、全時価と最大下落を復元する。
    引数: ready/ledger/row/proof(dict)、mode(str)、independent(module)は指紋道具。
    返り値: dictの密な状態・数量・現金・時価。
    """
    orders, trades = ledger['orders'], ledger['trades']
    n = len(ready['last'])
    scale = 1000 if ready['symbol'] == 'TOPIX' else 10
    cash, qty, gross, fees, longs, shorts = (np.zeros(n) for _ in range(6))
    for order, fee in zip(orders, ledger['fees']):
        i, side, q = int(order[0]), int(order[3]), int(order[4])
        cash[i] -= side * q * order[5]
        qty[i] += side * q
        fees[i] += fee
        holding = longs if (side if order[7] else -side) > 0 else shorts
        holding[i] += q if order[7] else -q
    for trade in trades:
        gross[int(trade[7])] += trade[2] * trade[3] * (trade[5] - trade[4])
    cash, qty, gross, fees, longs, shorts = map(np.cumsum, (cash, qty, gross, fees, longs, shorts))
    raw = cash + qty * ready['last']
    raw_dd = np.maximum.accumulate(np.maximum.accumulate(np.maximum(raw, 0)) - raw)
    net = raw * scale - fees
    if mode == 'IDEAL':
        cid = np.full(n, -1.)
        for order in orders:
            if order[7]:
                cid[int(order[0]):] = order[2]
        state = None
    else:
        changes = ledger['execution_state_changes']
        indices = changes[:, 0].astype(int)
        assert indices[0] == 0 and np.all(np.diff(indices) > 0)
        state = np.repeat(changes[:, 1:], np.diff(np.r_[indices, n]), axis=0)
        assert independent.array_sha(state) == ledger['execution_states_SHA256']
        np.testing.assert_array_equal(state[:, 3], longs)
        np.testing.assert_array_equal(state[:, 4], shorts)
        cid = state[:, 2]
        assert independent.array_sha(qty) == ledger['net_inventory_SHA256']
    raw_curve = np.c_[raw, gross, longs, shorts, raw_dd, cash, qty, cid]
    assert independent.array_sha(raw_curve) == ledger['raw_curve_SHA256']
    assert independent.array_sha(raw) == ledger['gross_equity_SHA256']
    assert independent.array_sha(net) == ledger['curve_SHA256']
    assert abs(net[-1] - row['net']) < 1e-5 and longs[-1] == shorts[-1] == 0
    expected = [gross[-1], raw_dd[-1], *proof['maximum'], 0., raw.min(initial=0), raw.max(initial=0), 0., 0.]
    np.testing.assert_allclose(ledger['stats'], expected, rtol=0, atol=1e-8)
    time_events = ledger.get('time_events', np.empty((0, 7)))
    windows = ledger['time_windows']
    reason = 71 if mode == 'IDEAL' else 92
    scheduled = orders[(orders[:, 7] == 0) & (orders[:, 6] == reason)]
    row.update(max_drawdown=float(np.max(np.maximum.accumulate(np.maximum(net, 0)) - net, initial=0)),
        entry_orders=int(np.count_nonzero(orders[:, 7])), exit_orders=int(np.count_nonzero(orders[:, 7] == 0)),
        new_lots=int(orders[orders[:, 7] == 1, 4].sum()), exit_lots=int(orders[orders[:, 7] == 0, 4].sum()),
        max_gross=proof['maximum'][2], max_net=proof['maximum'][3], equity_min=float(net.min(initial=0)),
        equity_max=float(net.max(initial=0)), residual_long=0, residual_short=0,
        guard_event_count=len(ledger.get('guard_events', [])),
        reason_counts={str(int(reason)): int(np.sum(trades[:, 9] == reason)) for reason in np.unique(trades[:, 9])},
        time_forced_exits=int(np.sum(time_events[:, 2] == 1)) if mode == 'IDEAL' else len(np.unique(scheduled[:, 0])),
        time_rejected_preparations=int(np.sum(time_events[:, 2] == 2)), time_exit_lots=int(scheduled[:, 4].sum()),
        time_window_count=len(windows), time_first_observation_after_window=sum(w['窓終了後の初観測'] for w in windows))
    return dict(cash=cash, qty=qty, raw=raw, net=net, state=state)


def evidence(ready, ledger, config, values, baseline, source_feed, time_filter):
    """
    機能: 待機・最初接触・初返済取消・次行返済と全疎証跡を独立復元する。
    引数: ready/ledger/config/values/baseline(dict)、source_feed(ndarray)、time_filter(module)。
    返り値: dictの公開根拠と成立・見送り件数。
    """
    mode = config['execution_mode']
    if mode == 'IDEAL':
        assert not len(ledger['limit_events'])
        return dict(成立親数=0, 見送り親数=0, 入口改善幅枚数積=0., 公開証跡=0, 実行証跡=0)
    feed, state = ledger['virtual_feed'], values['state']
    orders, proofs, events = ledger['orders'], ledger['limit_events'], ledger['execution_events']
    np.testing.assert_array_equal(feed, source_feed)
    prices = ready['last']
    n = len(prices)
    assert np.all(np.isfinite(prices) & (prices > 0)), '欠測行は人工監査で扱い、保存素材では全行有効を要する'
    quiet = time_filter.features(ready, 'U')
    scheduled = quiet['active'] | quiet['force'] | (ready['time_s'] >= ready['limit'])
    found = checks.inspect(ready, ledger, feed, config['offset_atr'], mode == 'NEXT',
                           quiet['active'], quiet['force'], ready['limit'], baseline)
    source_qty = np.zeros(n)
    np.add.at(source_qty, feed[:, 0].astype(int), feed[:, 3] * feed[:, 4])
    source_qty = np.cumsum(source_qty)
    np.testing.assert_array_equal(source_qty, state[:, 1])
    expected = np.zeros_like(state)
    expected[:, :1] = -1
    expected[:, 2] = -1
    expected[:, 1] = source_qty
    expected[:, 3:5] = state[:, 3:5]
    openings = {int(o[2]): o for o in orders if o[7]}
    source_entries = {int(o[2]): o for o in feed if o[7]}
    assert len(openings) == int(orders[:, 7].sum()), '同一親へ二度新規している'
    assert not np.any(state[scheduled, 3:5]) and not np.any(state[:, 3] * state[:, 4])
    for cid, original in source_entries.items():
        row = int(original[0])
        expected[row:, 0] = cid
        expected[row:, 5:8] = 0
        expected[row:, 8] = checks.line(original[5], int(original[3]), original[9], config['offset_atr'], ready['tick'])
        own_proof = proofs[proofs[:, 2] == cid]
        end = next((int(o[0]) for other, o in source_entries.items() if int(o[0]) > row), n)
        if cid in openings:
            hit = int(openings[cid][0])
            expected[row:hit, 5] = 1
            expected[hit:end, 7] = 1
            expected[hit:, 2] = cid
        else:
            cancellation = own_proof[np.isin(own_proof[:, 1], (3, 4))]
            at = int(cancellation[0, 0]) if len(cancellation) else row
            assert len(cancellation) == 1 or scheduled[row]
            expected[row:at, 5] = 1
            expected[at:end, 6] = 1
    for o in feed:
        row, cid = int(o[0]), int(o[2])
        if not o[7] and cid in openings and int(openings[cid][0]) <= row and not scheduled[row] and state[row, 3:5].sum() > 0:
            expected[row, 9] += 1
    np.testing.assert_array_equal(expected, state)
    # ----------------------------------------
    # 指値証跡は元注文受領後か、当行の元注文を読む前かを種別ごとに分ける。
    paper_after_order = {}
    cumulative = 0.
    for o in feed:
        cumulative += o[3] * o[4]
        paper_after_order[(int(o[0]), int(o[2]), int(o[7]), int(o[6]), int(o[4]))] = cumulative
    for p in proofs:
        row, code, cid = map(int, p[:3])
        original = source_entries[cid]
        source, side, amount = int(original[0]), int(original[3]), int(original[4])
        line = checks.line(original[5], side, original[9], config['offset_atr'], ready['tick'])
        prior_qty = source_qty[row - 1] if row else 0
        if code == 1:
            paper = paper_after_order[(row, cid, 1, int(original[6]), amount)]
            restored = [row, 1, cid, source, side, amount, original[5], original[9], line, prices[row], -1,
                abs(paper), state[row, 3:5].sum(), int(not scheduled[row]), int(scheduled[row]), config['offset_atr'], row, original[6]]
        elif code == 2:
            restored = [row, 2, cid, source, side, amount, original[5], original[9], line, prices[row], row,
                abs(prior_qty), amount, 0, 0, config['offset_atr'], -1, 90]
        elif code == 3:
            order = feed[(feed[:, 2] == cid) & (feed[:, 7] == 0)][0]
            assert int(order[0]) == row
            paper = paper_after_order[(row, cid, 0, int(order[6]), int(order[4]))]
            restored = [row, 3, cid, source, side, amount, original[5], original[9], line, prices[row], -1,
                abs(paper), 0, 0, 1, config['offset_atr'], row, order[6]]
        else:
            assert code == 4 and scheduled[row]
            restored = [row, 4, cid, source, side, amount, original[5], original[9], line, prices[row], -1,
                abs(prior_qty), 0, 0, 1, config['offset_atr'], -1, 93 if ready['time_s'][row] >= ready['limit'] else 92]
        np.testing.assert_array_equal(restored, p)
    received = events[events[:, 1] == 1]
    assert len(received) == len(feed)
    cumulative = 0.
    for event, original in zip(received, feed):
        row, cid, side, qty = int(original[0]), int(original[2]), int(original[3]), int(original[4])
        cumulative += side * qty
        restored = [row, 1, row, cid, side, qty, original[5], 0, original[7], cumulative,
                    int(bool(original[7]) and not scheduled[row]), values['qty'][row]]
        np.testing.assert_array_equal(restored, event)
    executions = events[events[:, 1] != 1]
    assert len(executions) == len(orders)
    net_qty = 0
    for event, order in zip(executions, orders):
        row, source, cid, side, amount = map(int, order[:5])
        net_qty += side * amount
        reason = int(order[6])
        prior_qty = source_qty[row - 1] if row else 0
        if reason in (92, 93):
            assert not order[7] and scheduled[row] and source == row - 1
            restored = [row, 4, source, cid, side, amount, order[5], -1, 0, prior_qty, 0, 0]
        else:
            assert reason == (90 if order[7] else 91) and source < row and not scheduled[row]
            if order[7]:
                assert source == source_entries[cid][0]
                pending = 0
            else:
                assert row == source + 1
                pending = state[row - 1, 5]
                matching = feed[(feed[:, 0] == source) & (feed[:, 2] == cid) & (feed[:, 7] == 0)]
                assert any(o[3] == side and o[4] == amount for o in matching)
            restored = [row, 3, source, cid, side, amount, order[5], 0, order[7], prior_qty, pending, net_qty]
        np.testing.assert_array_equal(restored, event)
    return dict(**found, 公開証跡=len(proofs), 実行証跡=len(events))


def entry_proofs(ready, ledger, baseline, ratios):
    """
    機能: 成立した全親の入口差と、見送り親を除いた全体差を独立会計で表す。
    引数: ready/ledger/baseline(dict)、ratios(module)は比較道具。
    返り値: dictの差分内訳。実行器の生成済み証明をそのまま採用しない。
    """
    scale = 1000 if ready['symbol'] == 'TOPIX' else 10
    result = []
    actual_parents = set()
    for order in ledger['orders']:
        if not order[7]:
            continue
        cid = int(order[2])
        actual_parents.add(cid)
        mine = ledger['orders'][ledger['orders'][:, 2] == cid]
        original = baseline['orders'][baseline['orders'][:, 2] == cid]
        entry = original[original[:, 7] == 1][0]
        np.testing.assert_array_equal(mine[mine[:, 7] == 0], original[original[:, 7] == 0])
        delta = float(order[3] * (entry[5] - order[5]))
        assert delta >= -1e-8 and order[0] >= entry[0]
        benefit = float(order[4] * delta * scale)
        difference = (ledger['trades'][ledger['trades'][:, 0] == cid, 10].sum()
                      - baseline['trades'][baseline['trades'][:, 0] == cid, 10].sum()) * scale
        assert abs(difference - benefit) < 1e-5
        assert ledger['fees'][ledger['orders'][:, 2] == cid].sum() == baseline['fees'][baseline['orders'][:, 2] == cid].sum()
        result.append(dict(組=cid, 枚数=int(order[4]), 方向=int(order[3]), 対照新規行=int(entry[0]), 指値新規行=int(order[0]),
            対照建値=float(entry[5]), 指値建値=float(order[5]), 有利価格差=delta, 料金前改善=benefit, 返済と料金同一=True))
    result.sort(key=lambda v: v['組'])
    ratios.same(result, ledger['entry_price_proof'])
    by_parent = defaultdict(float)
    for part in baseline['net_trades']:
        by_parent[part['組']] += part['収支']
    skipped = [v for cid, v in by_parent.items() if cid not in actual_parents]
    benefit = math.fsum(p['料金前改善'] for p in result)
    skipped_wins = math.fsum(v for v in skipped if v > 0)
    skipped_losses = -math.fsum(v for v in skipped if v < 0)
    net = math.fsum(p['収支'] for p in ledger['net_trades'])
    reference_net = math.fsum(p['収支'] for p in baseline['net_trades'])
    assert abs(net - reference_net - benefit + skipped_wins - skipped_losses) < 1e-5
    return dict(成立入口改善=benefit, 見送り利益=skipped_wins, 回避損失=skipped_losses,
                対照収支=reference_net, 実収支=net, 全体差=net - reference_net)


def nested(ledgers, inputs):
    """
    機能: 指値を深くした条件の成立親が浅い条件の部分集合であり、同じ親の入値が悪化しないか確認する。
    引数: ledgers(dict)、inputs(dict)。
    返り値: tuple[int,int]の隣接口座比較数と共通親数。
    """
    compared = matched = 0
    for key in inputs:
        for digit in range(7):
            first = ledgers[f'L_D{digit*10:02d}'][key]
            second = ledgers[f'L_D{(digit+1)*10:02d}'][key]
            a = {int(o[2]): o for o in first['orders'] if o[7]}
            b = {int(o[2]): o for o in second['orders'] if o[7]}
            assert set(b).issubset(a)
            for cid, order in b.items():
                assert order[0] >= a[cid][0]
                assert order[3] * (a[cid][5] - order[5]) >= -1e-8
                returns1 = first['orders'][(first['orders'][:, 2] == cid) & (first['orders'][:, 7] == 0)]
                returns2 = second['orders'][(second['orders'][:, 2] == cid) & (second['orders'][:, 7] == 0)]
                np.testing.assert_array_equal(returns1, returns2)
                matched += 1
            compared += 1
    return compared, matched


def main():
    """
    機能: 全十条件六百口座の会計、待機取消順序、成立部分集合と期間合算を監査する。
    引数: なし。
    返り値: None。新戦略再生や親会計関数の呼出は行わない。
    """
    root, work = checks.ROOT, checks.WORK
    independent = checks.module('監査87有利指値独立注文復元', work.parent / 'round10/audit/full.py')
    independent.roles = roles
    source_tools = checks.module('監査87有利指値原根拠', work.parent / 'round11/audit/full.py')
    read, sha = independent.read, independent.sha
    fixed = read(work / '事前固定.json')
    frozen = dict(fixed['code_SHA256'], **fixed['基準結果SHA256'])
    for path, expected in frozen.items():
        assert sha(root / path) == expected, path
    assert sha(root / 'work/wave_v85/prepared/入力準備の完了.json') == fixed['input_proof_SHA256']
    prepare = checks.module('監査87全指値入力', root / 'work/wave_v85/prepare.py')
    inputs, _, input_hashes = prepare.load_inputs(verify=True)
    assert input_hashes == fixed['input_SHA256']
    time_filter = checks.module('監査87全指値予定', root / 'work/wave_v85/time_filter.py')
    folder = root / 'work/wave_v85/audit'
    sys.path.insert(0, str(folder))
    checks.module('original', folder / 'original.py')
    metrics = checks.module('監査87指値全比率', folder / 'accounts.py')
    ratios = checks.module('監査87指値全期間', root / 'work/wave_v87/audit/allocation_fifo.py')
    source = pickle.loads((root / 'work/wave_v85/observed/ledgers/E01_G_U.pkl').read_bytes())
    source_rows = {(r['session'], r['symbol']): r for r in read(root / 'work/wave_v85/observed/results/E01_G_U.json')['rows']}
    delayed = pickle.loads((work.parent / 'round10/observed/ledgers/GU_G.pkl').read_bytes())
    totals = dict(条件数=0, 口座数=0, 注文数=0, 決済脚数=0, 親組数=0, 実新規UID数=0,
                  元仮想配列数=0, 成立親数=0, 見送り親数=0, 公開証跡=0, 実行証跡=0)
    reports, saved, differences = [], {}, []
    for config in fixed['catalog']:
        ident, mode = config['id'], config['execution_mode']
        path = work / 'observed/results' / (ident + '.json')
        ledger_path = work / 'observed/ledgers' / (ident + '.pkl')
        packet = read(path)
        assert packet['config'] == config and packet['run']['code_SHA256'] == fixed['code_SHA256']
        assert packet['run']['input_SHA256'] == fixed['input_SHA256'] and packet['run']['sessions'] == fixed['全30']
        assert sha(ledger_path) == packet['ledger_SHA256']
        ledgers = pickle.loads(ledger_path.read_bytes())
        assert set(ledgers) == set(inputs) and len(packet['rows']) == 60
        for virtual in packet['仮想源行']:
            metrics.equal(virtual, source_rows[virtual['session'], virtual['symbol']])
        rows = []
        for actual in packet['rows']:
            key = actual['session'], actual['symbol']
            ready, ledger = inputs[key], ledgers[key]
            totals['元仮想配列数'] += independent.unchanged(ledger['virtual_ledger'], source[key])
            totals['元仮想配列数'] += independent.unchanged(ledger['core_ledger'], source[key])
            if mode == 'IDEAL':
                independent.unchanged(ledger, source[key])
            elif mode == 'NEXT':
                for name in ('orders', 'trades', 'cycles', 'fees', 'stats', 'order_uids'):
                    np.testing.assert_array_equal(ledger[name], delayed[key][name])
                for name in ('net_trades', 'raw_curve_SHA256', 'curve_SHA256'):
                    assert ledger[name] == delayed[key][name]
            row, proof = independent.settle(ready, ledger, mode, ratios)
            values = trace(ready, ledger, mode, row, proof, independent)
            metrics.ratios(row)
            findings = evidence(ready, ledger, config, values, delayed[key], source_tools.feed_from_source(source[key]), time_filter)
            original = source_rows[key]
            row.update(virtual_net=original['net'], virtual_fees=original['fees'], core_net=original['net'],
                execution_net_change=row['net'] - original['net'], execution_fee_change=row['fees'] - original['fees'],
                virtual_unchanged=True, source_campaigns=original['campaigns'],
                no_trade_source_campaigns=original['campaigns'] - row['campaigns'])
            assert row['no_trade_source_campaigns'] >= 0
            events = ledger['limit_events']
            row.update(limit_reservations=int(np.sum(events[:, 1] == 1)), limit_fills=int(np.sum(events[:, 1] == 2)),
                limit_source_cancellations=int(np.sum(events[:, 1] == 3)), limit_schedule_cancellations=int(np.sum(events[:, 1] == 4)))
            if mode != 'IDEAL':
                difference = entry_proofs(ready, ledger, delayed[key], ratios)
                row['matched_entry_improvement'] = difference['成立入口改善']
                differences.append(dict(条件=ident, セッション=key[0], 商品=key[1], **difference))
            metrics.equal(row, actual)
            for name in ('成立親数', '見送り親数', '公開証跡', '実行証跡'):
                totals[name] += findings[name]
            totals['口座数'] += 1
            totals['注文数'] += len(ledger['orders'])
            totals['決済脚数'] += len(ledger['trades'])
            totals['親組数'] += proof['parents']
            totals['実新規UID数'] += proof['uid'] if mode != 'IDEAL' else 0
            rows.append(row)
        periods = {p: {s: metrics.aggregate(ratios, rows, s, fixed[p]) for s in ('TOPIX', 'NK225')} for p in ('前16', '後14', '全30')}
        metrics.equal(periods, packet['periods'])
        totals['条件数'] += 1
        saved[ident] = ledgers
        reports.append(dict(条件=ident, 結果SHA256=sha(path), 台帳SHA256=packet['ledger_SHA256']))
        print(ident, '全60口座・UID会計・待機取消・元返済一致', flush=True)
    subset_count, shared_count = nested(saved, inputs)
    assert totals['条件数'] == 10 and totals['口座数'] == 600 and subset_count == 420
    for path, expected in frozen.items():
        assert sha(root / path) == expected, path
    for report in reports:
        assert sha(work / 'observed/results' / (report['条件'] + '.json')) == report['結果SHA256']
        assert sha(work / 'observed/ledgers' / (report['条件'] + '.pkl')) == report['台帳SHA256']
    checks.save('全10指値条件のUID会計と成立親不変監査.json', dict(全合格=True, **totals,
        条件別=reports, 深い指値の部分集合対照口座数=subset_count, 隣接幅の共通親照合数=shared_count,
        元GUと旧無条件の対照口座数=120, 全親差分=differences, 親会計関数呼出=False, 新戦略再生=False,
        入力SHA256=input_hashes, 監査器SHA256=sha(Path(__file__)),
        差額恒等式='全体差＝成立親の入口改善−見送った対照利益＋回避した対照損失。深い指値の成立親は浅い指値の部分集合。',
        限界='会計と観測順の監査であり、指値の有利化が全体黒字や未知市場の安定利益を保証するものではない。'))
    print(json.dumps(dict(全合格=True, **totals), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
