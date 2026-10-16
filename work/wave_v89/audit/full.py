"""凍結済み全81条件の採否・源親・全原板時価を、取引実装と別に復元する。"""

from collections import defaultdict
from pathlib import Path
import hashlib
import json
import pickle
import numpy as np
import common
import independent


def read(path):
    """
    機能: 保存された有限JSONを読み取る。
    引数: path(Path)。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def array_sha(value):
    """
    機能: 配列の全行を省略せず内容指紋化する。
    引数: value(ndarray)。
    返り値: str。
    """
    return hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()


def clean(value):
    """
    機能: 証跡中のNumPy数値を、同値の有限JSON標準値へ揃える。
    引数: value(object)。
    返り値: object。
    """
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def fingerprints(fixed):
    """
    機能: 既往全固定依存、今回の固定条件と本監査の指紋を確認する。
    引数: fixed(dict)。
    返り値: dict[str,str]。
    """
    result = {}
    for name, digest in fixed['code_SHA256'].items():
        assert common.sha(common.ROOT / name) == digest, name
        result[name] = digest
    result |= common.fingerprints([common.WORK / '事前固定.json', Path(__file__)])
    return result


def restore(ready, source, budgets, gate, history, virtual, completions):
    """
    機能: 公開イベントだけを順に処理し、過去完了ゲートと前行予約から実注文を独立再生する。
    引数: ready/source/budgets/gate/history/virtual(dict)、completions(list[dict])。
    返り値: dict。今回の取引engineは呼び出さない。
    """
    n = len(ready['last'])
    times = ready['time_s']
    cut = int(np.searchsorted(times, ready['limit'], side='left'))
    assert cut < n
    factor = 1 if ready['symbol'] == 'TOPIX' else 2
    slots = [budgets[name] * factor for name in common.SOURCES]
    incoming = {name: list(history[name]) if gate['history_mode'] == 'carry' else [] for name in common.SOURCES}
    published = defaultdict(list)
    events = {cut}
    for s, name in enumerate(common.SOURCES):
        for j, order in enumerate(source[name]):
            row = int(order[0])
            if row < min(n, cut):
                assert row >= 0
                published[row].append((s, j, order))
                events.update((row, row + 1))
    paper = [dict(cid=-1, side=0, initial=0, remaining=0, target=0, accepted=False) for _ in common.SOURCES]
    live = [dict(cid=-1, side=0, quantity=0, uid=-1) for _ in common.SOURCES]
    plans, actual, trace, gates = defaultdict(list), [], [], []
    uid = 0
    for row in sorted(events):
        if row >= cut:
            for s, state in enumerate(live):
                if state['quantity']:
                    actual.append([cut, cut, s, state['cid'], -state['side'], state['quantity'], ready['last'][cut], 99, 0, state['uid']])
                    state.update(quantity=0, side=0)
            break
        for decision, s, cid, side, qty, reason, new in plans[row]:
            state = live[s]
            if new:
                assert not state['quantity'] and qty <= slots[s]
                state.update(cid=cid, side=side, quantity=qty, uid=uid)
                uid += 1
            else:
                assert (state['cid'], -state['side']) == (cid, side) and qty <= state['quantity']
                state['quantity'] -= qty
            actual.append([row, decision, s, cid, side, qty, ready['last'][row], reason, new, state['uid']])
            if not state['quantity']:
                state['side'] = 0
            assert sum(v['quantity'] for v in live if v['side'] > 0) <= 10 * factor
            assert sum(v['quantity'] for v in live if v['side'] < 0) <= 10 * factor
        for s, j, order in sorted(published[row], key=lambda value: value[:2]):
            state = paper[s]
            cid, side, qty = map(int, order[2:5])
            before = state['target']
            if order[7]:
                assert not state['remaining']
                name = common.SOURCES[s]
                available = [record for record in incoming[name] + [record for record in completions if record['source'] == name]
                    if record['publish_time'] < times[row]]
                assert all(record['symbol'] == ready['symbol'] and record['allocated_quantity'] == slots[s] for record in available)
                answer = independent.evaluate(gate, available, slots[s])
                gates.append(dict(row=row, time=float(times[row]), source=name, cid=cid, **answer))
                target = slots[s] if answer['allowed'] else 0
                state.update(cid=cid, side=side, initial=qty, remaining=qty, target=target, accepted=answer['allowed'])
                change = target
            else:
                assert (state['cid'], -state['side']) == (cid, side) and qty <= state['remaining']
                state['remaining'] -= qty
                state['target'] = slots[s] * state['remaining'] // state['initial'] if state['accepted'] else 0
                change = before - state['target']
                assert change >= 0
            trace.append([row, s, cid, j, state['side'], state['initial'], state['remaining'], state['target'], change, int(order[7])])
            if change and row + 1 < cut:
                plans[row + 1].append((row, s, cid, side, change, int(order[6]), int(order[7])))
    assert all(not state['quantity'] for state in live)
    return dict(orders=np.asarray(actual, float).reshape(-1, 10), target_trace=np.asarray(trace, float).reshape(-1, 10),
        terminal=live, slots=slots, completion_records=completions, gate_trace=gates,
        history_out={name: incoming[name] + [record for record in completions if record['source'] == name] for name in common.SOURCES})


def compare_trace(actual, expected):
    """
    機能: 全採否の当時根拠を省略せず比較し、厳密過去と商品源隔離を確認する。
    引数: actual/expected(list[dict])。
    返り値: tuple[int,int]の採用数と拒否数。
    """
    assert len(actual) == len(expected)
    for first, second in zip(actual, expected):
        for key in second:
            if key != 'reason':
                common.OLD.same(first[key], second[key])
        assert all(record['publish_time'] < first['time'] and record['source'] == first['source'] for record in first['selected'])
    eligible = [row for row in actual if row['allocated_quantity']]
    return int(sum(row['allowed'] for row in eligible)), int(sum(not row['allowed'] for row in eligible))


def subset(ready, result, ledger, baseline):
    """
    機能: 親初回採否が全注文を選ぶだけであり、採用親の料金後損益を変えないことを証明する。
    引数: ready/result/ledger/baseline(dict)。
    返り値: dictの親数・拒否損失・逃し利益・収支差。
    """
    allowed = {(common.SOURCES.index(record['source']), record['cid']) for record in result['gate_trace'] if record['allowed']}
    source_orders = baseline['orders']
    kept = np.asarray([order for order in source_orders if (int(order[2]), int(order[3])) in allowed], float).reshape(-1, 10)
    np.testing.assert_array_equal(result['orders'][:, :9], kept[:, :9])
    base = {(parent['source'], parent['cid']): parent for parent in baseline['parents']}
    actual = {(parent['source'], parent['cid']): parent for parent in ledger['parents']}
    assert set(actual) <= set(base)
    for key, parent in actual.items():
        common.OLD.same(parent, base[key])
    skipped = [parent for key, parent in base.items() if key not in actual]
    saved_loss = sum(-parent['net'] for parent in skipped if parent['net'] < 0)
    missed_profit = sum(parent['net'] for parent in skipped if parent['net'] > 0)
    difference = sum(parent['net'] for parent in actual.values()) - sum(parent['net'] for parent in base.values())
    common.OLD.same(difference, saved_loss - missed_profit)
    return dict(採用親完全一致数=len(actual), 拒否親数=len(skipped), 拒否損失=float(saved_loss),
        逃し利益=float(missed_profit), 収支差=float(difference))


def filtered_orders(orders, keys):
    """
    機能: 重複許可された親の全注文を抽出し、独立会計用にUIDだけ連続へ詰め直す。
    引数: orders(ndarray)、keys(set[tuple[str,int]])。
    返り値: ndarray10列。
    """
    kept = np.asarray([order.copy() for order in orders if (common.SOURCES[int(order[2])], int(order[3])) in keys], float).reshape(-1, 10)
    mapping = {}
    for order in kept:
        old = int(order[9])
        if order[8]:
            assert old not in mapping
            mapping[old] = len(mapping)
        order[9] = mapping[old]
    return kept


def complement(data, catalog, proof_hashes):
    """
    機能: 通常60%と逆60%の全親・料金・現金時価が停止なしと準備重複の和になることを照合する。
    引数: data(dict)、catalog(module)、proof_hashes(dict)。
    返り値: list[dict]。
    """
    records = []
    for profile in catalog.PROFILES:
        all_path = common.WORK / 'ledgers' / f'B{profile}_ALL.pkl'
        with all_path.open('rb') as stream:
            all_ledgers = pickle.load(stream)
        for scope in ('S', 'C'):
            for window in (8, 16):
                normal_id = f'B{profile}_{scope}{window:02d}_P60'
                reverse_id = f'B{profile}_{scope}{window:02d}_R60'
                npath = common.WORK / 'ledgers' / f'{normal_id}.pkl'
                rpath = common.WORK / 'ledgers' / f'{reverse_id}.pkl'
                assert common.sha(npath) == proof_hashes[str(npath.relative_to(common.ROOT))]
                assert common.sha(rpath) == proof_hashes[str(rpath.relative_to(common.ROOT))]
                with npath.open('rb') as stream:
                    normal = pickle.load(stream)
                with rpath.open('rb') as stream:
                    reverse = pickle.load(stream)
                for key in sorted(data):
                    a, n, r = all_ledgers[key], normal[key], reverse[key]
                    amap = {(p['source'], p['cid']): p for p in a['parents']}
                    nmap = {(p['source'], p['cid']): p for p in n['parents']}
                    rmap = {(p['source'], p['cid']): p for p in r['parents']}
                    assert set(nmap) | set(rmap) == set(amap)
                    overlap = set(nmap) & set(rmap)
                    bootstrap = {(row['source'], row['cid']) for row in n['gate_trace']
                        if row['allocated_quantity'] and (row['warmup'] or row['profit_share'] is None)} & set(amap)
                    assert overlap == bootstrap
                    assert len(n['gate_trace']) == len(r['gate_trace'])
                    for nt, rt in zip(n['gate_trace'], r['gate_trace']):
                        for field in ('row', 'time', 'source', 'cid', 'available', 'selected', 'warmup', 'profit', 'loss', 'profit_share'):
                            common.OLD.same(nt[field], rt[field])
                        if nt['allocated_quantity'] and not nt['warmup'] and nt['profit_share'] is not None:
                            assert nt['allowed'] != rt['allowed']
                    for field in ('net', 'gross', 'fees'):
                        lhs = sum(p[field] for p in nmap.values()) + sum(p[field] for p in rmap.values())
                        rhs = sum(p[field] for p in amap.values()) + sum(amap[p][field] for p in overlap)
                        common.OLD.same(lhs, rhs)
                    for sign in (1, -1):
                        measure = lambda values: sum(sign * p['net'] for p in values if sign * p['net'] > 0)
                        common.OLD.same(measure(nmap.values()) + measure(rmap.values()),
                            measure(amap.values()) + measure(amap[p] for p in overlap))
                    overlap_result = dict(orders=filtered_orders(a['orders'], overlap), slots=a['slots'], target_trace=np.empty((0, 10)))
                    ar, _, ae, _ = common.FULL.account(data[key], a)
                    nr, _, ne, _ = common.FULL.account(data[key], n)
                    rr, _, re, _ = common.FULL.account(data[key], r)
                    br, _, be, _ = common.FULL.account(data[key], overlap_result)
                    np.testing.assert_allclose(ne + re, ae + be, rtol=0, atol=1e-4)
                    for field in ('profit', 'loss', 'net', 'gross', 'fees', 'campaigns', 'wins', 'losses', 'new_lots', 'closed_lots'):
                        common.OLD.same(nr[field] + rr[field], ar[field] + br[field])
                    records.append(dict(セッション=key[0], 商品=key[1], 通常=normal_id, 逆対照=reverse_id,
                        元親数=len(amap), 通常親数=len(nmap), 逆親数=len(rmap), 準備重複親数=len(overlap),
                        全原板時価恒等式=True))
        print(profile, '通常/逆/準備重複の全親・時価恒等式一致', flush=True)
    return records


def main():
    """
    機能: 全4,860口座と期間、720対照口座を復元し、凍結済み成果の独立全数監査を保存する。
    引数: なし。
    返り値: None。既存の凍結コードと成果は変更しない。
    """
    fixed = read(common.WORK / '事前固定.json')
    before = fingerprints(fixed)
    catalog = common.module('監査89全数条件', common.WORK / 'catalog.py')
    assert catalog.catalog() == fixed['catalog'] and len(fixed['catalog']) == 81
    prepare = common.module('監査89全数入力', common.ROOT / 'work/wave_v85/prepare.py')
    data, _, input_hashes = prepare.load_inputs(verify=True)
    assert input_hashes == fixed['input_SHA256']
    source_path = common.ROOT / 'work/wave_v88/prepared/source_orders.pkl'
    assert common.sha(source_path) == fixed['code_SHA256'][str(source_path.relative_to(common.ROOT))]
    with source_path.open('rb') as stream:
        feeds = pickle.load(stream)
    assert set(feeds) == set(data) and len(data) == 60
    expected_files = {config['id'] for config in fixed['catalog']}
    assert {path.stem for path in (common.WORK / 'results').glob('*.json')} == expected_files
    records, result_hashes, virtual_cache, old_ledgers = [], {}, {}, {}
    for profile, config in catalog.PROFILES.items():
        path = common.ROOT / 'work/wave_v88/ledgers' / f'{config["reference_id"]}.pkl'
        with path.open('rb') as stream:
            old_ledgers[profile] = pickle.load(stream)
        for key in sorted(data):
            source = {name: feeds[key][name]['orders'] for name in common.SOURCES}
            virtual = common.FULL.restore_execution(data[key], source, config['budgets'])
            baseline = old_ledgers[profile][key]
            np.testing.assert_array_equal(virtual['orders'], baseline['orders'])
            np.testing.assert_array_equal(virtual['target_trace'], baseline['target_trace'])
            common.OLD.same(virtual['slots'], baseline['slots'])
            completions = independent.completed(data[key], source, virtual)
            assert len(completions) == len(baseline['parents'])
            by_parent = {(p['source'], p['cid']): p for p in baseline['parents']}
            for completion in completions:
                parent = by_parent[completion['source'], completion['cid']]
                for field in ('net', 'gross', 'fees'):
                    common.OLD.same(completion[field], parent[field])
                assert completion['publish_row'] >= parent['exit_row']
            virtual_cache[profile, key] = virtual, completions
    print('三配分の独立常時仮想180口座と元v88全台帳が一致', flush=True)
    total_orders = total_parents = total_gate = total_completion = 0
    for config in fixed['catalog']:
        identifier = config['id']
        result_path = common.WORK / 'results' / f'{identifier}.json'
        ledger_path = common.WORK / 'ledgers' / f'{identifier}.pkl'
        result = read(result_path)
        assert result['config'] == config and common.sha(ledger_path) == result['ledger_SHA256']
        result_hashes[str(result_path.relative_to(common.ROOT))] = common.sha(result_path)
        result_hashes[str(ledger_path.relative_to(common.ROOT))] = result['ledger_SHA256']
        with ledger_path.open('rb') as stream:
            ledgers = pickle.load(stream)
        assert set(ledgers) == set(data) and len(result['rows']) == 60
        stored_rows = {(row['session'], row['symbol']): row for row in result['rows']}
        assert len(stored_rows) == 60
        histories = {symbol: {name: [] for name in common.SOURCES} for symbol in ('TOPIX', 'NK225')}
        rows, curves = {}, {}
        for key in sorted(data):
            ready, stored = data[key], ledgers[key]
            source = {name: feeds[key][name]['orders'] for name in common.SOURCES}
            for name in common.SOURCES:
                np.testing.assert_array_equal(stored['source_orders'][name], source[name])
            virtual, completions = virtual_cache[config['profile_id'], key]
            expected = restore(ready, source, config['budgets'], config['gate'], histories[key[1]], virtual, completions)
            histories[key[1]] = expected['history_out']
            for name in ('orders', 'target_trace', 'slots', 'completion_records'):
                common.OLD.same(stored[name], expected[name])
            allowed, rejected = compare_trace(stored['gate_trace'], expected['gate_trace'])
            row, ledger, curve, source_curve = common.FULL.account(ready, expected)
            for field in ledger:
                common.OLD.same(stored[field], ledger[field])
            assert array_sha(curve) == stored['curve_SHA256']
            trace = [record for record in stored['gate_trace'] if record['allocated_quantity']]
            row.update(config_id=identifier, gate_eligible=len(trace), gate_allowed=allowed, gate_rejected=rejected,
                gate_warmup=sum(record['warmup'] for record in trace), virtual_campaigns=len(completions))
            common.OLD.same(row, stored_rows[key])
            parent_proof = subset(ready, expected, ledger, old_ledgers[config['profile_id']][key])
            assert stored['parent_subset_proof']['採用親完全一致数'] == parent_proof['採用親完全一致数']
            rows[key], curves[key] = row, curve
            total_orders += len(ledger['orders'])
            total_parents += row['campaigns']
            total_gate += len(stored['gate_trace'])
            total_completion += len(completions)
            records.append(dict(条件=identifier, セッション=key[0], 商品=key[1], 実注文数=len(ledger['orders']),
                仮想完了数=len(completions), 採否数=len(stored['gate_trace']), 採用=allowed, 拒否=rejected,
                最大買枚数=row['max_long'], 最大売枚数=row['max_short'], **parent_proof))
        for period in ('前16', '後14', '全30', 'Day', 'Night'):
            for symbol in ('TOPIX', 'NK225'):
                keys = [key for key in sorted(data) if key[1] == symbol and
                    (key[0] in fixed[period] if period in fixed else key[0].endswith(period))]
                prows, pcurves = [rows[key] for key in keys], [curves[key] for key in keys]
                stat = common.FULL.aggregate(prows, pcurves)
                for name in ('gate_eligible', 'gate_allowed', 'gate_rejected', 'gate_warmup', 'virtual_campaigns'):
                    stat[name] = sum(row[name] for row in prows)
                common.OLD.same(stat, result['periods'][period][symbol])
        print(identifier, '全60採否・親・料金・全原板時価・期間一致', flush=True)
    complement_records = complement(data, catalog, result_hashes)
    assert before == fingerprints(fixed)
    for name, digest in result_hashes.items():
        assert common.sha(common.ROOT / name) == digest
    common.save('全81停止再開の公開根拠と全会計及び逆対照恒等式監査.json', clean(dict(全合格=True,
        条件数=len(fixed['catalog']), 実口座数=len(records), 常時仮想独立対照口座数=len(virtual_cache),
        全実注文数=total_orders, 全実親数=total_parents, 全採否根拠数=total_gate, 全仮想完了照合数=total_completion,
        全原板時価指紋照合数=len(records), 期間商品集計照合数=len(fixed['catalog']) * 10,
        通常逆対照恒等式口座数=len(complement_records), 検査=records, 通常逆対照= complement_records,
        コード素材SHA256=before, 新結果SHA256=result_hashes, 原入力SHA256=input_hashes,
        検査方法='取引engineを使わず、源公開注文から整数常時仮想・紙上終了後公開・厳密過去採否を復元。独立UID会計と全観測時価から場・期間を再計算。',
        恒等式='採用親は停止なしと不変。全収支差＝拒否損失−逃し利益。通常60%＋逆60%＝停止なし＋準備不足又はゼロ分母の重複親。全原板清算時価でも同一。',
        商品履歴隔離=True, 場内全返済=True, 片方向合計上限=True, API取得数=0, 実注文数=0)))
    print(json.dumps(dict(全合格=True, 実口座数=len(records), 全実注文数=total_orders,
        全採否根拠数=total_gate, 通常逆対照恒等式口座数=len(complement_records)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
