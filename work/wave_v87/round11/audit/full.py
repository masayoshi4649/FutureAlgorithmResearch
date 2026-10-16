"""相手GU参照の全保存注文を、UID会計と公開時点から独立に検算する。"""

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import pickle
import sys
import numpy as np
import checks


def read(path):
    """
    機能: 保存済みの有限JSONを読み取る。
    引数: path(Path)。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    """
    機能: ファイル内容を分割して指紋化する。
    引数: path(Path)。
    返り値: str。
    """
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()


def feed_from_source(source):
    """
    機能: 元GUの準備証跡から、新規前に確定していたATRを注文へ付ける。
    引数: source(dict)は元GU保存台帳。
    返り値: ndarrayの十列素材。将来の決済損益を判定根拠へ使用しない。
    """
    orders = source['orders']
    result = np.zeros((len(orders), 10))
    result[:, :8] = orders
    preparations = {int(p[0]): p for p in source['prepare_events']}
    links = {int(p[0]): p for p in source['entry_preparations']}
    for number, order in enumerate(orders):
        if not order[7]:
            continue
        link = links[int(order[2])]
        preparation = preparations[int(link[2])]
        assert link[1] == order[0] and preparation[1] <= order[1] < order[0]
        assert preparation[4] > 0 and np.isfinite(preparation[4])
        result[number, 9] = preparation[4]
    return result


def peer_material(ready, other, source):
    """
    機能: 相手の厳密過去・最新有効価格行を独立探索し、元注文を付ける。
    引数: ready/other/source(dict)。
    返り値: dictの相手素材。
    """
    valid = np.flatnonzero(np.isfinite(other['last']) & (other['last'] > 0))
    offset = np.searchsorted(other['time_s'][valid], ready['time_s'], side='left') - 1
    refs = np.full(len(ready['last']), -1, np.int32)
    known = offset >= 0
    refs[known] = valid[offset[known]]
    assert np.all(other['time_s'][refs[known]] < ready['time_s'][known])
    return dict(time_s=other['time_s'], last=other['last'], seq=other['seq'], feed=feed_from_source(source), ref=refs,
        value=1000. if other['symbol'] == 'TOPIX' else 10., fee=41.8 if other['symbol'] == 'TOPIX' else 11.)


def evidence(ready, ledger, config, values, peer, material, time_filter):
    """
    機能: 入口拒否、停止初公開、縮小条件、当行の目標と次行の実約定を独立照合する。
    引数: ready/ledger/config/values/peer(dict)、material/time_filter(module)。
    返り値: dictの判定件数。取引実装の再生は呼ばない。
    """
    mode = config['execution_mode']
    if mode == 'IDEAL':
        assert not len(ledger['peer_events'])
        return dict(入口許可=0, 入口拒否=0, 縮小=0, 公開証跡=0, 実行証跡=0)
    n = len(ready['last'])
    assert np.all(np.isfinite(ready['last']) & (ready['last'] > 0)), '無効行を含む入力は別の有効行伝播が必要'
    state, orders, feed = values['state'], ledger['orders'], ledger['virtual_feed']
    entry, holding = config['entry_mode'], config['holding_mode']
    result = dict(ledger, execution_states=state)
    checks.inspect(ready, feed, peer, result, entry, holding, material)
    np.testing.assert_array_equal(feed, feed_from_source(ledger['core_ledger']))
    proofs, events = ledger['peer_events'], ledger['execution_events']
    source_qty = np.zeros(n)
    np.add.at(source_qty, feed[:, 0].astype(int), feed[:, 3] * feed[:, 4])
    source_qty = np.cumsum(source_qty)
    np.testing.assert_array_equal(source_qty, state[:, 1])
    peer_qty = np.zeros(len(peer['last']))
    np.add.at(peer_qty, peer['feed'][:, 0].astype(int), peer['feed'][:, 3] * peer['feed'][:, 4])
    peer_qty = np.cumsum(peer_qty)
    at = peer['ref']
    visible = np.where(at >= 0, peer_qty[np.maximum(at, 0)], 0)
    np.testing.assert_array_equal(visible, state[:, 2])
    own = {int(o[2]): o for o in feed if o[7]}
    first_actual = {int(o[2]): int(o[0]) for o in orders if o[7]}
    assert len(first_actual) == int(np.sum(orders[:, 7] == 1)), '同一の元親組へ後から新規を繰り返している'
    cid_path = np.full(n, -1.)
    for cid, order in own.items():
        cid_path[int(order[0]):] = cid
    np.testing.assert_array_equal(cid_path, state[:, 0])
    quiet = time_filter.features(ready, 'U')
    scheduled = quiet['active'] | quiet['force'] | (ready['time_s'] >= ready['limit'])
    assert not np.any(state[scheduled, 4:6])
    assert not np.any(state[:, 4] * state[:, 5])
    permissions = {int(e[2]): bool(e[14]) for e in proofs if e[1] == 1}
    reduced = {}
    triggered = []
    for proof in proofs:
        row, code, cid = map(int, proof[:3])
        if code != 2:
            continue
        stop = checks.peer_reference(peer['time_s'], peer['last'], peer['feed'], peer['value'], peer['fee'], int(proof[4]))['stops'][-1]
        side = int(own[cid][3]) if cid in own else 0
        actual = int(state[row, 4] - state[row, 5])
        expected = (holding > 0 and cid not in reduced and permissions.get(cid, False) and not scheduled[row]
            and source_qty[row] != 0 and side == stop['side'] and int(own[cid][0]) < row
            and state[row, 3] == cid and actual * side > 0 and first_actual.get(cid, n) <= row
            and ready['time_s'][row] - peer['time_s'][int(proof[4])] <= 180.)
        assert bool(proof[14]) == bool(expected), (ready['session'], ready['symbol'], config['id'], proof.tolist())
        if expected:
            reduced[cid] = row
            triggered.append(proof.copy())
    trigger_rows = proofs[proofs[:, 1] == 3]
    assert len(trigger_rows) == len(triggered)
    for actual, expected in zip(trigger_rows, triggered):
        expected[1] = 3
        np.testing.assert_array_equal(actual, expected)
    expected_reduced = np.zeros(n)
    for cid, order in own.items():
        expected_reduced[int(order[0]):] = 0
        if cid in reduced:
            expected_reduced[reduced[cid]:] = 1
    np.testing.assert_array_equal(state[:, 8], expected_reduced)
    for cid, allowed in permissions.items():
        selected = orders[orders[:, 2] == cid]
        if not allowed:
            assert not len(selected)
        if cid in reduced:
            assert not np.any((selected[:, 7] == 1) & (selected[:, 0] > reduced[cid]))
            if holding == 2 and reduced[cid] + 1 < n:
                following = state[reduced[cid] + 1:]
                assert not np.any(following[following[:, 3] == cid, 4:6])
    # ----------------------------------------
    # 公開された自己注文又は新しい停止だけが目標を更新する。
    # その行の相手情報で、既に前行から有効な実注文を消さない。
    goal_cid, goal_qty, pending = np.full(n, -1.), np.zeros(n), np.zeros(n)
    expected_real = np.full(n, -1.)
    executed = {int(e[0]): e for e in events if e[1] == 3}
    own_rows = set(feed[:, 0].astype(int))
    changed_rows = own_rows | set(reduced.values())
    for row in sorted(changed_rows | set(executed)):
        if row in executed:
            expected_real[row:] = executed[row][3]
        if row not in changed_rows or scheduled[row]:
            continue
        cid = int(cid_path[row])
        target = int(source_qty[row]) if permissions[cid] else 0
        if cid in reduced and reduced[cid] <= row:
            target = 0 if holding == 2 else int(np.sign(source_qty[row])) * ((abs(int(source_qty[row])) + 1) // 2)
        goal_cid[row:] = cid
        goal_qty[row:] = target
        live_qty = int(state[row, 4] - state[row, 5])
        is_pending = target != live_qty or (expected_real[row] != cid and state[row, 4:6].sum() > 0)
        pending[row] = int(is_pending)
        if not is_pending and state[row, 4:6].sum() == 0:
            expected_real[row:] = cid
    np.testing.assert_array_equal(goal_cid, state[:, 6])
    np.testing.assert_array_equal(goal_qty, state[:, 7])
    np.testing.assert_array_equal(pending, state[:, 9])
    np.testing.assert_array_equal(expected_real, state[:, 3])
    plans = {int(e[0]): e for e in events if e[1] == 2}
    assert set(plans) == set(np.flatnonzero(pending))
    for row, plan in plans.items():
        assert plan[2] == row and plan[3] == goal_cid[row] and plan[4] == goal_qty[row]
    for row, event in executed.items():
        source = int(event[2])
        assert source in plans and row == source + 1 and not scheduled[row]
        assert event[4] == values['qty'][row] == plans[source][4]
    received = events[events[:, 1] == 1]
    np.testing.assert_array_equal(received[:, [0, 3, 4, 5, 6, 8]], feed[:, [0, 2, 3, 4, 5, 7]])
    for order in orders:
        row, source, reason = int(order[0]), int(order[1]), int(order[6])
        if reason in (92, 93):
            assert not order[7] and scheduled[row]
            assert reason == (93 if ready['time_s'][row] >= ready['limit'] else 92)
        else:
            assert row in executed and source == executed[row][2]
        if order[7]:
            cid = int(order[2])
            assert permissions[cid] and source == own[cid][0] and row == source + 1
    return dict(入口許可=sum(permissions.values()), 入口拒否=sum(not a for a in permissions.values()),
        縮小=len(reduced), 公開証跡=len(proofs), 実行証跡=len(events))


def main():
    """
    機能: 全十三条件の全会計・相手根拠・途中三方式の新規不変を検算する。
    引数: なし。
    返り値: None。戦略再生も親会計関数も呼び出さない。
    """
    root, work = checks.ROOT, checks.WORK
    fixed = read(work / '事前固定.json')
    fingerprints = dict(fixed['code_SHA256'], **fixed['基準結果SHA256'])
    for path, expected in fingerprints.items():
        assert sha(root / path) == expected, path
    assert sha(root / 'work/wave_v85/prepared/入力準備の完了.json') == fixed['input_proof_SHA256']
    independent = checks.module('監査87相手注文の独立UID復元', work.parent / 'round10/audit/full.py')
    prepare = checks.module('監査87全相手会計入力', root / 'work/wave_v85/prepare.py')
    inputs, _, input_hashes = prepare.load_inputs(verify=True)
    assert input_hashes == fixed['input_SHA256']
    material = checks.module('監査87全相手時計', work / 'prepare.py')
    time_filter = checks.module('監査87全相手予定', root / 'work/wave_v85/time_filter.py')
    folder = root / 'work/wave_v85/audit'
    sys.path.insert(0, str(folder))
    checks.module('original', folder / 'original.py')
    metrics = checks.module('監査87全相手比率', folder / 'accounts.py')
    ratios = checks.module('監査87全相手期間', root / 'work/wave_v87/audit/allocation_fifo.py')
    source = pickle.loads((root / 'work/wave_v85/observed/ledgers/E01_G_U.pkl').read_bytes())
    source_rows = {(r['session'], r['symbol']): r for r in read(root / 'work/wave_v85/observed/results/E01_G_U.json')['rows']}
    delayed = pickle.loads((work.parent / 'round10/observed/ledgers/GU_N.pkl').read_bytes())
    peers = {key: peer_material(ready, inputs[(key[0], 'NK225' if key[1] == 'TOPIX' else 'TOPIX')],
                               source[(key[0], 'NK225' if key[1] == 'TOPIX' else 'TOPIX')]) for key, ready in inputs.items()}
    totals = dict(条件数=0, 口座数=0, 注文数=0, 決済脚数=0, 親組数=0, 実新規UID数=0,
                  元仮想配列数=0, 入口許可=0, 入口拒否=0, 縮小=0, 公開証跡=0, 実行証跡=0)
    reports, saved = [], {}
    for config in fixed['catalog']:
        ident, mode = config['id'], config['execution_mode']
        path, ledger_path = work / 'observed/results' / (ident + '.json'), work / 'observed/ledgers' / (ident + '.pkl')
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
            elif ident == 'P_E0_H0':
                for name in ('orders', 'trades', 'cycles', 'fees', 'stats', 'order_uids'):
                    np.testing.assert_array_equal(ledger[name], delayed[key][name])
                for name in ('net_trades', 'raw_curve_SHA256', 'curve_SHA256'):
                    assert ledger[name] == delayed[key][name]
            row, proof = independent.settle(ready, ledger, mode, ratios)
            values = independent.trace(ready, ledger, mode, row, proof)
            metrics.ratios(row)
            original = source_rows[key]
            findings = evidence(ready, ledger, config, values, peers[key], material, time_filter)
            row.update(virtual_net=original['net'], virtual_fees=original['fees'], core_net=original['net'],
                execution_net_change=row['net'] - original['net'], execution_fee_change=row['fees'] - original['fees'],
                virtual_unchanged=True, source_campaigns=original['campaigns'],
                no_trade_source_campaigns=original['campaigns'] - row['campaigns'],
                entry_gate_accepts=findings['入口許可'], entry_gate_rejections=findings['入口拒否'], peer_reductions=findings['縮小'])
            assert row['no_trade_source_campaigns'] >= 0
            metrics.equal(row, actual)
            for name, value in findings.items():
                totals[name] += value
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
        print(ident, '全60口座・UID会計・相手公開根拠・目標数量一致', flush=True)
    new_invariant = 0
    for entry in range(4):
        for key in inputs:
            base = saved[f'P_E{entry}_H0'][key]
            for holding in (1, 2):
                other = saved[f'P_E{entry}_H{holding}'][key]
                for ledger in (base, other):
                    assert len(np.unique(ledger['orders'][ledger['orders'][:, 7] == 1, 2])) == int(ledger['orders'][:, 7].sum())
                np.testing.assert_array_equal(base['orders'][base['orders'][:, 7] == 1], other['orders'][other['orders'][:, 7] == 1])
                gate1 = base['peer_events'][base['peer_events'][:, 1] == 1]
                gate2 = other['peer_events'][other['peer_events'][:, 1] == 1]
                np.testing.assert_array_equal(gate1[:, [0, 2, 3, 4, 5, 6, 7, 8, 9, 12, 14, 16, 17, 18, 19, 20]],
                                              gate2[:, [0, 2, 3, 4, 5, 6, 7, 8, 9, 12, 14, 16, 17, 18, 19, 20]])
                new_invariant += 1
    assert totals['条件数'] == 13 and totals['口座数'] == 780 and new_invariant == 480
    for path, expected in fingerprints.items():
        assert sha(root / path) == expected, path
    for report in reports:
        assert sha(work / 'observed/results' / (report['条件'] + '.json')) == report['結果SHA256']
        assert sha(work / 'observed/ledgers' / (report['条件'] + '.pkl')) == report['台帳SHA256']
    checks.save('全13相手参照条件のUID会計と公開根拠監査.json', dict(全合格=True, **totals,
        条件別=reports, 途中方式間の新規完全一致対照数=new_invariant, 元GUと旧無条件の対照口座数=120,
        親会計関数呼出=False, 新戦略再生=False, 入力SHA256=input_hashes, 監査器SHA256=sha(Path(__file__)),
        数量規則='H1は通知時点以後の自己元GU残数量の半分切上げ。H2は親組終了までゼロ。通知は再適用しない。',
        限界='保存結果の会計と公開済み情報の使用順を確認したもので、未知市場の利益を証明しない。'))
    print(json.dumps(dict(全合格=True, **totals), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
