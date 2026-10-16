"""保存済み実注文を別の建玉台帳へ読み替え、十三条件の全会計と差引恒等式を監査する。"""

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import pickle
import sys
import numpy as np
from checks import ROOT, HERE, WORK, module, save


def read(path):
    """
    機能: 凍結済み資料を読み取る。
    引数: path(Path)。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    """
    機能: ファイルを分割読取りで指紋化する。
    引数: path(Path)。
    返り値: str。
    """
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def array_sha(value):
    """
    機能: 復元配列の全内容を指紋化する。
    引数: value(ndarray)。
    返り値: str。
    """
    return hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()


def unchanged(actual, reference, virtual=False):
    """
    機能: 元玉又は仮想源の全保存要素が元台帳のままか照合する。
    引数: actual/reference(dict)、virtual(bool)は仮想源の後付け内訳を別照合する指定。
    返り値: intの配列照合数。
    """
    count = 0
    for name, value in reference.items():
        if virtual and name in ('core_ledger', 'satellite_orders', 'satellite_trades', 'satellite_stats'):
            # ----------------------------------------
            # 旧実行器が後付けした内訳は仮想会計に再格納されない。
            # 元玉は別の全要素照合、保険注文は仮想入力の役割付き列で確認する。
            continue
        if isinstance(value, np.ndarray):
            np.testing.assert_array_equal(value, actual[name], err_msg=name)
            count += 1
        else:
            assert actual[name] == value, name
    return count


def roles(ledger, mode):
    """
    機能: Gの実注文を前観測の仮想列へ対応付け、N/Fの実玉を差引役割へ分類する。
    引数: ledger(dict)、mode(str)。
    返り値: ndarray[int]。予定強制返済だけは役割を限定しない。
    """
    orders = ledger['orders']
    result = np.full(len(orders), 2, int)
    forced = np.isin(orders[:, 6], [92, 93])
    result[forced] = -1
    if mode != 'G':
        return result
    feed = ledger['virtual_feed']
    for source in np.unique(orders[~forced, 1]):
        index = np.flatnonzero((orders[:, 1] == source) & ~forced)
        original = feed[feed[:, 0] == source]
        np.testing.assert_array_equal(orders[index][:, [2, 3, 4, 7]], original[:, [2, 3, 4, 7]])
        result[index] = original[:, 8].astype(int)
    return result


def settle(ready, ledger, mode, ratios):
    """
    機能: 実注文順にUID建玉を生成・返済し、脚と親組の費用後損益を独立復元する。
    引数: ready/ledger(dict)、mode(str)、ratios(module)は比率だけを再利用。
    返り値: tuple[dict,dict]。基本会計と瞬間保有・手数料等の証跡。
    """
    orders, trades, cycles = ledger['orders'], ledger['trades'], ledger['cycles']
    rate = 418 if ready['symbol'] == 'TOPIX' else 110
    scale = 1000 if ready['symbol'] == 'TOPIX' else 10
    cap = 10 if ready['symbol'] == 'TOPIX' else 20
    active = mode != 'IDEAL'
    order_roles = roles(ledger, mode) if active else np.zeros(len(orders), int)
    charges = []
    slots, details, recreated = [], [], []
    held = [0, 0]
    maxima = [0, 0, 0, 0]
    parent_held = defaultdict(lambda: [0, 0])
    parent_max = defaultdict(lambda: [0, 0])
    parent_parts = defaultdict(list)
    last_row = -1
    for oi, order in enumerate(orders):
        row, source, cid, side, qty = map(int, order[:5])
        price, reason, new = float(order[5]), int(order[6]), int(order[7])
        role = int(order_roles[oi])
        assert 0 <= source < row < len(ready['last']) and row >= last_row
        assert qty == order[4] and qty > 0 and side in (-1, 1)
        assert price == ready['last'][row] and np.isfinite(price) and price > 0
        last_row = row
        fee = qty * rate // 10
        charges.append(fee)
        direction = side if new else -side
        at = 0 if direction > 0 else 1
        change = qty if new else -qty
        held[at] += change
        parent_held[cid][at] += change
        assert min(held) >= 0 and max(held) <= cap
        assert min(parent_held[cid]) >= 0
        maxima = [max(a, b) for a, b in zip(maxima, (held[0], held[1], sum(held), abs(held[0] - held[1])))]
        parent_max[cid] = [max(a, b) for a, b in zip(parent_max[cid],
                          (sum(parent_held[cid]), abs(parent_held[cid][0] - parent_held[cid][1])))]
        if new:
            uid = len(slots)
            if active:
                assert ledger['order_uids'][oi] == uid
            slots.append(dict(uid=uid, qty=qty, initial=qty, fee=fee, side=side, price=price,
                              row=row, cid=cid, role=role))
            continue
        if active:
            assert ledger['order_uids'][oi] == -1
        remaining = qty
        for lot in slots:
            if remaining == 0:
                break
            if not lot['qty'] or lot['cid'] != cid or lot['side'] != -side:
                continue
            if active and role >= 0 and role != lot['role']:
                continue
            amount = min(remaining, lot['qty'])
            gross_pt = -side * amount * (price - lot['price'])
            allocated = amount * lot['fee'] / lot['initial'] + amount * fee / qty
            detail = dict(組=cid, 方向=-side, 枚数=amount, 新規行=lot['row'], 返済行=row,
                新規原本行=int(ready['seq'][lot['row']]), 返済原本行=int(ready['seq'][row]),
                新規時刻=float(ready['time_s'][lot['row']]), 返済時刻=float(ready['time_s'][row]),
                建値=lot['price'], 返済値=price, 理由=reason, 利益損失前=gross_pt * scale,
                手数料=allocated, 収支=gross_pt * scale - allocated)
            details.append(detail)
            parent_parts[cid].append(detail)
            recreated.append([cid, lot['uid'], -side, amount, lot['price'], price,
                              lot['row'], row, lot['role'], reason, gross_pt])
            lot['qty'] -= amount
            remaining -= amount
        assert remaining == 0
    assert not any(held) and all(not any(v) for v in parent_held.values())
    assert all(lot['qty'] == 0 for lot in slots)
    np.testing.assert_array_equal(charges, ledger['fees'])
    restored = np.asarray(recreated, float).reshape(-1, 11)
    if active:
        np.testing.assert_array_equal(restored, trades)
    else:
        # ----------------------------------------
        # 元GUは旧部分枠番号を残すので、経済列と元台帳の完全一致を別々に確認する。
        np.testing.assert_array_equal(restored[:, [0, 2, 3, 4, 5, 6, 7, 9, 10]], trades[:, [0, 2, 3, 4, 5, 6, 7, 9, 10]])
    ratios.same(details, ledger['net_trades'])
    assert set(parent_parts) == {int(c[0]) for c in cycles}
    core = {int(c[0]): c for c in ledger['core_ledger']['cycles']}
    nets, risks = [], []
    for cycle in cycles:
        cid = int(cycle[0])
        parts = parent_parts[cid]
        assert cycle[1] == min(d['新規行'] for d in parts)
        assert cycle[2] == max(d['返済行'] for d in parts)
        assert cycle[9] == parts[-1]['理由']
        assert cycle[6:8].tolist() == parent_max[cid]
        np.testing.assert_array_equal(cycle[[4, 5, 8]], core[cid][[4, 5, 8]])
        assert abs(cycle[3] * scale - math.fsum(d['利益損失前'] for d in parts)) < 1e-5
        nets.append(math.fsum(d['収支'] for d in parts))
        risks.append(cycle[4] * scale)
    winners = [d for d in details if d['収支'] > 0]
    losers = [d for d in details if d['収支'] < 0]
    flats = [d for d in details if d['収支'] == 0]
    row = dict(session=ready['session'], symbol=ready['symbol'],
        gross=math.fsum(d['利益損失前'] for d in details), fees=sum(charges), net=math.fsum(nets),
        profit=math.fsum(d['収支'] for d in winners), loss=-math.fsum(d['収支'] for d in losers),
        wins=len(winners), losses=len(losers), flats=len(flats), winning_lots=sum(d['枚数'] for d in winners),
        losing_lots=sum(d['枚数'] for d in losers), flat_lots=sum(d['枚数'] for d in flats),
        campaigns=len(nets), campaign_wins=sum(v > 0 for v in nets), campaign_losses=sum(v < 0 for v in nets),
        campaign_profit=math.fsum(v for v in nets if v > 0), campaign_loss=-math.fsum(v for v in nets if v < 0),
        sum_r=math.fsum(v / r for v, r in zip(nets, risks)), max_long=maxima[0], max_short=maxima[1])
    assert abs(row['net'] - row['gross'] + row['fees']) < 1e-5
    assert abs(math.fsum(d['手数料'] for d in details) - row['fees']) < 1e-5
    ratios.ratios(row)
    return row, dict(maximum=maxima, parents=len(nets), uid=len(slots))


def trace(ready, ledger, mode, row, proof):
    """
    機能: 全注文の現金・数量と全原板価格から時価・最大下落・疎状態の指紋を復元する。
    引数: ready/ledger/row/proof(dict)、mode(str)。
    返り値: dict。全原板数量・現金・時価と状態を返す。
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
    for t in trades:
        gross[int(t[7])] += t[2] * t[3] * (t[5] - t[4])
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
        index = changes[:, 0].astype(int)
        assert index[0] == 0 and np.all(np.diff(index) > 0)
        state = np.repeat(changes[:, 1:], np.diff(np.r_[index, n]), axis=0)
        assert array_sha(state) == ledger['execution_states_SHA256']
        np.testing.assert_array_equal(state[:, 4], longs)
        np.testing.assert_array_equal(state[:, 5], shorts)
        cid = state[:, 3]
        assert array_sha(qty) == ledger['net_inventory_SHA256']
    raw_curve = np.c_[raw, gross, longs, shorts, raw_dd, cash, qty, cid]
    assert array_sha(raw_curve) == ledger['raw_curve_SHA256']
    assert array_sha(raw) == ledger['gross_equity_SHA256']
    assert array_sha(net) == ledger['curve_SHA256']
    assert abs(net[-1] - row['net']) < 1e-5 and longs[-1] == shorts[-1] == 0
    expected_stats = [gross[-1], raw_dd[-1], *proof['maximum'], 0., raw.min(initial=0), raw.max(initial=0), 0., 0.]
    np.testing.assert_allclose(ledger['stats'], expected_stats, rtol=0, atol=1e-8)
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


def causality(ready, ledger, mode, traces, time_filter, reference):
    """
    機能: 仮想情報の当行受付と次観測実行、予定優先、Fの元玉終了後差引ゼロを照合する。
    引数: ready/ledger/traces/reference(dict)、mode(str)、time_filter(module)。
    返り値: intのイベント照合数。
    """
    if mode == 'IDEAL':
        return 0
    orders, feed, events = ledger['orders'], ledger['virtual_feed'], ledger['execution_events']
    state = traces['state']
    n = len(ready['last'])
    np.testing.assert_array_equal(feed[:, :8], ledger['virtual_ledger']['orders'])
    core, sat = ledger['core_ledger']['orders'], reference.get('satellite_orders', np.empty((0, 8)))
    np.testing.assert_array_equal(feed[feed[:, 8] == 0, :8], core)
    np.testing.assert_array_equal(feed[feed[:, 8] == 1, :8], sat)
    vcore, vsat = np.zeros(n), np.zeros(n)
    for role, array in ((0, vcore), (1, vsat)):
        subset = feed[feed[:, 8] == role]
        np.add.at(array, subset[:, 0].astype(int), subset[:, 3] * subset[:, 4])
    vcore, vsat = np.cumsum(vcore), np.cumsum(vsat)
    np.testing.assert_array_equal(state[:, 1], vcore)
    np.testing.assert_array_equal(state[:, 2], vsat)
    expected_virtual = np.full(n, -1.)
    expected_closed = np.zeros(n)
    virtual_end = {}
    for cid in np.unique(core[:, 2]):
        group = core[core[:, 2] == cid]
        initial = group[group[:, 7] == 1][0]
        first, last = int(initial[0]), int(group[-1, 0])
        expected_virtual[first:] = cid
        expected_closed[first:] = 0
        expected_closed[last:] = 1
        virtual_end[int(cid)] = last
    np.testing.assert_array_equal(state[:, 0], expected_virtual)
    np.testing.assert_array_equal(state[:, 8], expected_closed)
    quiet = time_filter.features(ready, 'U')
    scheduled = quiet['active'] | quiet['force'] | (ready['time_s'] >= ready['limit'])
    assert not np.any(traces['qty'][scheduled])
    assert not np.any(state[scheduled, 4:6])
    if mode != 'G':
        assert not np.any(state[:, 4] * state[:, 5])
    expected_real = np.full(n, -1.)
    for o in orders:
        if o[7]:
            expected_real[int(o[0]):] = o[2]
    if mode != 'G':
        for event in events:
            i, code = int(event[0]), int(event[1])
            if code == 3:
                expected_real[i:] = event[3]
        # ----------------------------------------
        # 空玉かつ新しい差引注文が不要な観測でも、元の親IDを受け継ぐ。
        for i in np.unique(feed[:, 0].astype(int)):
            target = 0 if mode == 'F' and expected_closed[i] else vcore[i] + vsat[i]
            if not scheduled[i] and traces['qty'][i] == 0 and target == 0:
                next_change = np.flatnonzero((np.arange(n) > i) & (expected_real != expected_real[i]))
                end = int(next_change[0]) if len(next_change) else n
                expected_real[i:end] = expected_virtual[i]
    np.testing.assert_array_equal(state[:, 3], expected_real)
    received = events[events[:, 1] == 1]
    assert len(received) == len(feed)
    np.testing.assert_array_equal(received[:, [0, 3, 4, 5, 6, 7, 8]], feed[:, [0, 2, 3, 4, 5, 8, 7]])
    assert np.all(received[:, 2] == received[:, 0])
    plans = {int(e[0]): e for e in events if e[1] == 2}
    executions = {(int(e[0]), int(e[2])) for e in events if e[1] == 3}
    for event in events:
        i, code, source = map(int, event[:3])
        if code == 2:
            assert source == i
            target = 0 if mode == 'F' and expected_closed[i] else vcore[i] + vsat[i]
            assert event[4] == target and not scheduled[i]
        elif code == 3:
            assert source < i and source in plans
            valid = np.flatnonzero(np.isfinite(ready['last'][source + 1:]) & (ready['last'][source + 1:] > 0))
            assert i == source + 1 + valid[0]
            assert not scheduled[i]
            assert event[4] == traces['qty'][i] and event[4] == plans[source][4]
        elif code == 4:
            assert source < i and scheduled[i]
            matches = orders[(orders[:, 0] == i) & np.isin(orders[:, 6], [92, 93])]
            assert any(o[1] == source and o[3] == event[4] and o[4] == event[5] for o in matches)
    for order in orders:
        i, source = int(order[0]), int(order[1])
        if order[6] in (92, 93):
            assert not order[7] and scheduled[i]
            assert int(order[6]) == (93 if ready['time_s'][i] >= ready['limit'] else 92)
        else:
            assert source in plans and not scheduled[i]
            assert (i, source) in executions
        if order[7]:
            assert not scheduled[i]
    if mode == 'F':
        for cid, end in virtual_end.items():
            after = end + 1
            if after < n:
                assert traces['qty'][after] == 0
    assert traces['qty'][-1] == vcore[-1] == vsat[-1] == 0
    return len(events)


def exposure(ready, ledger):
    """
    機能: 比較方式の売買現金と差引数量だけを独立に復元する。
    引数: ready/ledger(dict)。
    返り値: tuple[ndarray,ndarray,ndarray]の現金・数量・料金前時価。
    """
    cash, qty = np.zeros(len(ready['last'])), np.zeros(len(ready['last']))
    for o in ledger['orders']:
        i = int(o[0])
        cash[i] -= o[3] * o[4] * o[5]
        qty[i] += o[3] * o[4]
    cash, qty = np.cumsum(cash), np.cumsum(qty)
    return cash, qty, cash + qty * ready['last']


def main():
    """
    機能: 全十三結果・七百八十口座を戦略再生なしに独立検算する。
    引数: なし。
    返り値: None。監査資料のみを今回の監査領域へ保存する。
    """
    fixed = read(WORK / '事前固定.json')
    snapshots = dict(fixed['code_SHA256'], **fixed['基準結果SHA256'])
    for path, digest in snapshots.items():
        assert sha(ROOT / path) == digest, path
    assert sha(ROOT / 'work/wave_v85/prepared/入力準備の完了.json') == fixed['input_proof_SHA256']
    prepare = module('監査87全実注文入力', ROOT / 'work/wave_v85/prepare.py')
    inputs, _, input_sha = prepare.load_inputs(verify=True)
    assert input_sha == fixed['input_SHA256']
    time_filter = module('監査87全実注文予定', ROOT / 'work/wave_v85/time_filter.py')
    folder = ROOT / 'work/wave_v85/audit'
    sys.path.insert(0, str(folder))
    module('original', folder / 'original.py')
    metric = module('監査87全実注文比率', folder / 'accounts.py')
    ratios = module('監査87全実注文期間', ROOT / 'work/wave_v87/audit/allocation_fifo.py')
    paths = {'E01_G_U': ROOT / 'work/wave_v85', 'C_H05_S25': WORK.parent / 'round7',
             'C_H05_S50': WORK.parent / 'round7', 'I_P00_R50_C1': WORK.parent / 'round8'}
    references = {name: pickle.loads((path / 'observed/ledgers' / (name + '.pkl')).read_bytes()) for name, path in paths.items()}
    reference_rows = {name: {(r['session'], r['symbol']): r for r in read(path / 'observed/results' / (name + '.json'))['rows']}
                      for name, path in paths.items()}
    counts = dict(条件数=0, 口座数=0, 注文数=0, 決済脚数=0, 親組数=0, 実新規UID数=0, 仮想元配列数=0, 実行証跡数=0)
    summaries, results = [], {}
    for config in fixed['catalog']:
        identifier, mode, source = config['id'], config['execution_mode'], config['source_id']
        result_path = WORK / 'observed/results' / (identifier + '.json')
        ledger_path = WORK / 'observed/ledgers' / (identifier + '.pkl')
        packet = read(result_path)
        assert packet['config'] == config and packet['run']['code_SHA256'] == fixed['code_SHA256']
        assert packet['run']['input_SHA256'] == fixed['input_SHA256'] and packet['run']['sessions'] == fixed['全30']
        assert sha(ledger_path) == packet['ledger_SHA256']
        ledgers = pickle.loads(ledger_path.read_bytes())
        assert set(ledgers) == set(inputs) and len(packet['rows']) == 60
        rows = []
        for actual in packet['rows']:
            key = actual['session'], actual['symbol']
            ready, ledger = inputs[key], ledgers[key]
            counts['仮想元配列数'] += unchanged(ledger['virtual_ledger'], references[source][key], virtual=True)
            counts['仮想元配列数'] += unchanged(ledger['core_ledger'], references['E01_G_U'][key])
            if mode == 'IDEAL':
                unchanged(ledger, references['E01_G_U'][key])
            row, proof = settle(ready, ledger, mode, ratios)
            values = trace(ready, ledger, mode, row, proof)
            metric.ratios(row)
            original = reference_rows[source][key]
            row.update(virtual_net=original['net'], virtual_fees=original['fees'], core_net=reference_rows['E01_G_U'][key]['net'],
                execution_net_change=row['net'] - original['net'], execution_fee_change=row['fees'] - original['fees'], virtual_unchanged=True)
            metric.equal(row, actual)
            counts['実行証跡数'] += causality(ready, ledger, mode, values, time_filter, references[source][key])
            counts['口座数'] += 1
            counts['注文数'] += len(ledger['orders'])
            counts['決済脚数'] += len(ledger['trades'])
            counts['親組数'] += proof['parents']
            counts['実新規UID数'] += proof['uid'] if mode != 'IDEAL' else 0
            rows.append(row)
        periods = {p: {s: metric.aggregate(ratios, rows, s, fixed[p]) for s in ('TOPIX', 'NK225')} for p in ('前16', '後14', '全30')}
        metric.equal(periods, packet['periods'])
        counts['条件数'] += 1
        results[identifier] = (packet, ledgers)
        summaries.append(dict(条件=identifier, 結果SHA256=sha(result_path), 台帳SHA256=packet['ledger_SHA256']))
        print(identifier, '全60口座・UID・全時価・親組・予定と次観測実行一致', flush=True)
    comparisons = []
    for source in paths:
        prefix = 'GU' if source == 'E01_G_U' else source
        pg, lg = results[prefix + '_G']
        pn, ln = results[prefix + '_N']
        pf, lf = results[prefix + '_F']
        for key, ready in sorted(inputs.items()):
            g, n, f = lg[key], ln[key], lf[key]
            cg, qg, eg = exposure(ready, g)
            cn, qn, en = exposure(ready, n)
            cf, qf, ef = exposure(ready, f)
            for first, second in ((cg, cn), (qg, qn), (eg, en)):
                np.testing.assert_array_equal(first, second)
            assert g['gross_equity_SHA256'] == n['gross_equity_SHA256'] and g['net_inventory_SHA256'] == n['net_inventory_SHA256']
            scale = 1000 if key[1] == 'TOPIX' else 10
            gross_difference = float(np.dot((qf - qn)[:-1], np.diff(ready['last']))) * scale
            real_difference = float(f['trades'][:, 10].sum() - n['trades'][:, 10].sum()) * scale
            assert abs(gross_difference - real_difference) < 1e-5
            net_difference = math.fsum(t['収支'] for t in f['net_trades']) - math.fsum(t['収支'] for t in n['net_trades'])
            fee_difference = int(f['fees'].sum() - n['fees'].sum())
            assert abs(net_difference - gross_difference + fee_difference) < 1e-5
            if prefix == 'GU':
                for other in (n, f):
                    for name in ('orders', 'fees', 'cycles', 'order_uids'):
                        np.testing.assert_array_equal(g[name], other[name])
                    np.testing.assert_array_equal(g['trades'][:, [0, 1, 2, 3, 4, 5, 6, 7, 9, 10]], other['trades'][:, [0, 1, 2, 3, 4, 5, 6, 7, 9, 10]])
                    for name in ('raw_curve_SHA256', 'curve_SHA256', 'net_trades'):
                        assert g[name] == other[name]
                assert np.all(g['trades'][:, 8] == 0) and np.all(n['trades'][:, 8] == 2) and np.all(f['trades'][:, 8] == 2)
            comparisons.append(dict(仮想源=source, セッション=key[0], 商品=key[1], GN全行一致=True,
                NF露出による料金前差額=gross_difference, NF手数料差=fee_difference, NF収支差=net_difference))
    assert counts['条件数'] == 13 and counts['口座数'] == 780 and len(comparisons) == 240
    for path, digest in snapshots.items():
        assert sha(ROOT / path) == digest, path
    for entry in summaries:
        ident = entry['条件']
        assert sha(WORK / 'observed/results' / (ident + '.json')) == entry['結果SHA256']
        assert sha(WORK / 'observed/ledgers' / (ident + '.pkl')) == entry['台帳SHA256']
    save('全13実行方式のUID全会計と差引恒等式監査.json', dict(全合格=True, **counts, 条件別=summaries,
        GN比較口座数=240, NF全額差分=comparisons, GU三方式の経済的一致口座数=60,
        GU役割差='Gの脚役割0とN/Fの脚役割2はラベル差であり、注文・料金・親組・全原板時価は同じ。',
        親会計関数呼出=False, 新戦略再生=False, 入力SHA256=input_sha, 監査器SHA256=sha(Path(__file__)),
        限界='会計と過去情報の使用順の一致であり、未知相場の収益や小型商品の同価格約定を証明しない。'))
    print(json.dumps(dict(全合格=True, **counts), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
