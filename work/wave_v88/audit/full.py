"""固定三源の公開注文から全配分を独立復元し、源間の非干渉も照合する。"""

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import pickle
import numpy as np
import execution_checks as common


def read(path):
    """
    機能: 保存JSONを読み取る。
    引数: path(Path)。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    """
    機能: ファイルを分割読取りして指紋化する。
    引数: path(Path)。
    返り値: str。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def array_sha(array):
    """
    機能: 全配列の値を連続バイトにして指紋化する。
    引数: array(ndarray)。
    返り値: str。
    """
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def restore_execution(ready, source, budgets):
    """
    機能: 価格を使う観測だけ逐次処理し、前予約と当行公開を分離して実注文を復元する。
    引数: ready/source/budgets(dict)。
    返り値: dictの実注文・整数目標。取引実装を呼び出さない。
    """
    n = len(ready['last'])
    assert np.all(np.isfinite(ready['last']) & (ready['last'] > 0))
    factor = 1 if ready['symbol'] == 'TOPIX' else 2
    cap = 10 * factor
    slots = [budgets[name] * factor for name in common.SOURCES]
    assert sum(slots) <= cap
    stop = int(np.flatnonzero(ready['time_s'] >= ready['limit'])[0])
    received = defaultdict(list)
    events = {stop}
    for s, name in enumerate(common.SOURCES):
        for j, order in enumerate(source[name]):
            row = int(order[0])
            assert int(order[1]) < row and order[5] == ready['last'][row]
            if row < stop:
                received[row].append((s, j, order))
                events.update((row, row + 1))
    paper = [dict(cid=-1, side=0, initial=0, remaining=0, target=0) for _ in common.SOURCES]
    live = [dict(cid=-1, side=0, quantity=0, uid=-1) for _ in common.SOURCES]
    queue, orders, trace = [], [], []
    uid = 0
    for row in sorted(events):
        if row >= stop:
            for s, state in enumerate(live):
                if state['quantity']:
                    orders.append([stop, stop, s, state['cid'], -state['side'], state['quantity'], ready['last'][stop], 99, 0, state['uid']])
                    state.update(quantity=0, side=0)
            break
        for decision, s, cid, side, quantity, reason, new in queue:
            assert row == decision + 1
            state = live[s]
            if new:
                assert state['quantity'] == 0 and quantity <= slots[s]
                state.update(cid=cid, side=side, quantity=quantity, uid=uid)
                uid += 1
            else:
                assert state['cid'] == cid and state['side'] == -side and quantity <= state['quantity']
                state['quantity'] -= quantity
            orders.append([row, decision, s, cid, side, quantity, ready['last'][row], reason, new, state['uid']])
            if state['quantity'] == 0:
                state['side'] = 0
            assert sum(v['quantity'] for v in live if v['side'] > 0) <= cap
            assert sum(v['quantity'] for v in live if v['side'] < 0) <= cap
        queue = []
        for s, j, order in sorted(received[row], key=lambda v: v[:2]):
            state = paper[s]
            cid, side, quantity = map(int, order[2:5])
            previous = state['target']
            if order[7]:
                assert state['remaining'] == 0
                state.update(cid=cid, side=side, initial=quantity, remaining=quantity, target=slots[s])
                change = slots[s]
            else:
                assert cid == state['cid'] and side == -state['side'] and quantity <= state['remaining']
                state['remaining'] -= quantity
                state['target'] = slots[s] * state['remaining'] // state['initial']
                change = previous - state['target']
                assert change >= 0
            trace.append([row, s, cid, j, state['side'], state['initial'], state['remaining'], state['target'], change, int(order[7])])
            if change:
                queue.append((row, s, cid, side, change, int(order[6]), int(order[7])))
    assert all(v['quantity'] == 0 for v in live)
    return dict(orders=np.asarray(orders, float).reshape(-1, 10), target_trace=np.asarray(trace, float).reshape(-1, 10), slots=slots)


def account(ready, result):
    """
    機能: UIDの個別注文料と源別親・脚を復元し、全原板清算時価を別の現金台帳から作る。
    引数: ready/result(dict)。
    返り値: tuple[dict,dict,ndarray,ndarray]の会計・台帳・全体時価・源別時価。
    """
    orders = result['orders']
    scale, fee10, cap = (1000, 418, 10) if ready['symbol'] == 'TOPIX' else (10, 110, 20)
    n = len(ready['last'])
    cash_delta, quantity_delta = np.zeros((n, 3)), np.zeros((n, 3))
    positions = [0, 0, 0]
    maximum = [0, 0]
    entries, remaining, parents, legs, fees = {}, {}, {}, [], []
    for order in orders:
        row, decision, s, cid, side, qty, price, reason, new, uid = order
        row, s, cid, side, qty, reason, new, uid = map(int, (row, s, cid, side, qty, reason, new, uid))
        assert decision < row or (reason == 99 and decision == row)
        fee = qty * fee10 // 10
        fees.append(fee)
        cash_delta[row, s] -= side * qty * price * scale + fee
        quantity_delta[row, s] += side * qty
        positions[s] += side * qty
        maximum[0] = max(maximum[0], sum(max(v, 0) for v in positions))
        maximum[1] = max(maximum[1], sum(max(-v, 0) for v in positions))
        assert max(maximum) <= cap
        parent = parents.setdefault((s, cid), dict(source=common.SOURCES[s], cid=cid,
            gross=0., fees=0., net=0., initial_qty=0, entry_row=None, exit_row=None))
        parent['fees'] += fee
        if new:
            assert uid == len(entries) and uid not in entries
            entries[uid] = (s, cid, side, qty, price, fee, row)
            remaining[uid] = qty
            parent.update(initial_qty=qty, entry_row=row)
        else:
            es, ec, ed, eq, ep, ef, er = entries[uid]
            assert (s, cid, side) == (es, ec, -ed) and qty <= remaining[uid]
            remaining[uid] -= qty
            gross = ed * qty * (price - ep) * scale
            allocated = ef * qty / eq + fee
            parent['gross'] += gross
            parent['exit_row'] = row
            legs.append(dict(source=common.SOURCES[s], cid=cid, uid=uid, side=ed, quantity=qty, entry_row=er, exit_row=row,
                entry_price=float(ep), exit_price=float(price), gross=float(gross), fees=float(allocated), net=float(gross - allocated), reason=reason))
    assert not any(positions) and all(v == 0 for v in remaining.values())
    for parent in parents.values():
        parent['net'] = parent['gross'] - parent['fees']
    cash = cash_delta.cumsum(axis=0)
    position = quantity_delta.cumsum(axis=0)
    assert np.all(np.abs(position) <= np.asarray(result['slots']))
    pending_close_fees = np.abs(position).astype(np.int64) * fee10 // 10
    source_equity = cash + position * ready['last'][:, None] * scale - pending_close_fees
    equity = source_equity.sum(axis=1)
    nets = np.asarray([p['net'] for p in parents.values()])
    profit, loss = float(nets[nets > 0].sum()), float(-nets[nets < 0].sum())
    row = dict(session=ready['session'], symbol=ready['symbol'], gross=float(sum(p['gross'] for p in parents.values())),
        fees=sum(fees), net=float(nets.sum()), profit=profit, loss=loss,
        profit_share=profit / (profit + loss) if profit + loss else None,
        campaigns=len(parents), wins=int((nets > 0).sum()), losses=int((nets < 0).sum()),
        new_lots=int(orders[orders[:, 8] == 1, 5].sum()), closed_lots=int(orders[orders[:, 8] == 0, 5].sum()),
        max_long=maximum[0], max_short=maximum[1],
        max_drawdown=float(np.max(np.maximum.accumulate(np.maximum(equity, 0)) - equity, initial=0)),
        curve_min=float(equity.min(initial=0)), curve_max=float(equity.max(initial=0)),
        source_totals={name: dict(gross=float(sum(p['gross'] for p in parents.values() if p['source'] == name)),
            fees=int(sum(p['fees'] for p in parents.values() if p['source'] == name)), net=float(source_equity[-1, s])) for s, name in enumerate(common.SOURCES)})
    assert row['new_lots'] == row['closed_lots']
    assert abs(sum(p['net'] for p in legs) - row['net']) < 1e-5
    assert abs(equity[-1] - row['net']) < 1e-5 and np.all(position[-1] == 0)
    states = np.c_[cash, position]
    changed = np.r_[True, np.any(states[1:] != states[:-1], axis=1)]
    ledger = dict(orders=orders, fees=np.asarray(fees), parents=list(parents.values()), legs=legs,
        target_trace=result['target_trace'], slots=result['slots'], cash_position_changes=np.c_[np.flatnonzero(changed), states[changed]])
    return row, ledger, equity, source_equity


def aggregate(rows, curves):
    """
    機能: 各場の要約下落を使わず全時価列を時間順に連結して期間会計を復元する。
    引数: rows(list[dict])、curves(list[ndarray])。
    返り値: dictの期間集計。
    """
    result = {key: sum(r[key] for r in rows) for key in ('gross', 'fees', 'net', 'profit', 'loss', 'campaigns', 'wins', 'losses', 'new_lots', 'closed_lots')}
    result['profit_share'] = result['profit'] / (result['profit'] + result['loss']) if result['profit'] + result['loss'] else None
    result.update(positive_sessions=sum(r['net'] > 0 for r in rows), negative_sessions=sum(r['net'] < 0 for r in rows),
        no_trade_sessions=sum(r['campaigns'] == 0 for r in rows), sessions=len(rows),
        worst_session=min((r['net'] for r in rows), default=0), max_long=max((r['max_long'] for r in rows), default=0),
        max_short=max((r['max_short'] for r in rows), default=0))
    peak = offset = drawdown = 0.
    for row, curve in zip(rows, curves):
        path = curve + offset
        path_peak = np.maximum.accumulate(np.maximum(path, peak))
        drawdown = max(drawdown, float(np.max(path_peak - path, initial=0)))
        peak = float(path_peak[-1])
        offset += row['net']
    result.update(max_drawdown=drawdown, return_drawdown=result['net'] / drawdown if drawdown else 0.,
        best_three_removed=result['net'] - sum(sorted([r['net'] for r in rows if r['net'] > 0], reverse=True)[:3]))
    return result


def invariant(key, config, ledger, source_equity, reference):
    """
    機能: 同じ源・枚数の注文と会計が他源の配分に依存しないことを照合する。
    引数: key(tuple)、config/ledger/reference(dict)、source_equity(ndarray)。
    返り値: tuple[int,int]の再照合数と無配分対照数。
    """
    count = zeros = 0
    for s, name in enumerate(common.SOURCES):
        qty = config['budgets'][name]
        orders = ledger['orders'][ledger['orders'][:, 2] == s]
        # ----------------------------------------
        # UIDは全源の発注通番なので、他源配分で番号だけ変わることを経済差と混同しない。
        content = dict(orders=array_sha(orders[:, :9]), fees=array_sha(ledger['fees'][ledger['orders'][:, 2] == s]),
            parents=[p for p in ledger['parents'] if p['source'] == name],
            legs=[{k:v for k,v in p.items() if k != 'uid'} for p in ledger['legs'] if p['source'] == name],
            curve=array_sha(source_equity[:, s]))
        token = key, name, qty
        if token in reference:
            common.same(content, reference[token])
            count += 1
        else:
            reference[token] = content
        if qty == 0:
            assert not len(orders) and not content['parents'] and not content['legs']
            assert not np.any(source_equity[:, s])
            zeros += 1
    return count, zeros


def main():
    """
    機能: 全二十二配分の千三百二十口座を独立復元し、入力・実装・結果の指紋を確認する。
    引数: なし。
    返り値: None。凍結済み実行層と会計関数を呼び出さず、保存結果だけを検査する。
    """
    work, root = common.WORK, common.ROOT
    fixed = read(work / '事前固定.json')
    for name, expected in fixed['code_SHA256'].items():
        assert sha(root / name) == expected, name
    prepare = common.module('監査88全保存入力', root / 'work/wave_v85/prepare.py')
    inputs, _, input_hashes = prepare.load_inputs(verify=True)
    assert input_hashes == fixed['input_SHA256']
    source_path = work / 'prepared/source_orders.pkl'
    source_hash = sha(source_path)
    feeds = pickle.loads(source_path.read_bytes())
    assert set(feeds) == set(inputs)
    counts = dict(条件数=0, 口座数=0, 注文数=0, 決済脚数=0, 源別親数=0, UID数=0, 源不変対照数=0, 無配分対照数=0, 期間数=0)
    reports, reference = [], {}
    for config in fixed['catalog']:
        path = work / 'results' / (config['id'] + '.json')
        ledger_path = work / 'ledgers' / (config['id'] + '.pkl')
        packet = read(path)
        assert packet['config'] == config and sha(ledger_path) == packet['ledger_SHA256']
        ledgers = pickle.loads(ledger_path.read_bytes())
        assert set(ledgers) == set(inputs) and len(packet['rows']) == 60
        rows, curves = [], []
        for actual in packet['rows']:
            key = actual['session'], actual['symbol']
            ready, saved = inputs[key], ledgers[key]
            source = {name: feeds[key][name]['orders'] for name in common.SOURCES}
            for name in common.SOURCES:
                np.testing.assert_array_equal(saved['source_orders'][name], source[name])
            expected = restore_execution(ready, source, config['budgets'])
            for name in expected:
                common.same(saved[name], expected[name])
            row, ledger, equity, source_equity = account(ready, expected)
            row['config_id'] = config['id']
            common.same(actual, row)
            for name in ledger:
                common.same(saved[name], ledger[name])
            assert saved['curve_SHA256'] == array_sha(equity)
            assert saved['source_curve_SHA256'] == array_sha(source_equity)
            grid = np.arange(ready['start'] + 60., ready['limit'], 60.)
            indices = np.searchsorted(ready['time_s'], grid, side='right') - 1
            safe = np.maximum(indices, 0)
            valid = (indices >= 0) & (grid - ready['time_s'][safe] <= 180.)
            sample = dict(times=grid, rows=indices, valid=valid, values=np.where(valid, equity[safe], np.nan))
            common.same(saved['samples'], sample)
            matches, zeros = invariant(key, config, ledger, source_equity, reference)
            counts['源不変対照数'] += matches
            counts['無配分対照数'] += zeros
            counts['口座数'] += 1
            counts['注文数'] += len(ledger['orders'])
            counts['決済脚数'] += len(ledger['legs'])
            counts['源別親数'] += len(ledger['parents'])
            counts['UID数'] += int(ledger['orders'][:, 8].sum())
            rows.append(row)
            curves.append(equity)
        for period in ('前16', '後14', '全30', 'Day', 'Night'):
            for symbol in ('TOPIX', 'NK225'):
                selected = [i for i,r in enumerate(rows) if r['symbol'] == symbol and
                    (r['session'].endswith(period) if period in ('Day', 'Night') else r['session'] in fixed[period])]
                result = aggregate([rows[i] for i in selected], [curves[i] for i in selected])
                common.same(result, packet['periods'][period][symbol])
                counts['期間数'] += 1
        counts['条件数'] += 1
        reports.append(dict(条件=config['id'], 結果SHA256=sha(path), 台帳SHA256=packet['ledger_SHA256']))
        print(config['id'], '全60口座・整数執行・注文料・清算時価・源独立性一致', flush=True)
    assert counts['条件数'] == 22 and counts['口座数'] == 1320 and counts['期間数'] == 220
    for name, expected in fixed['code_SHA256'].items():
        assert sha(root / name) == expected, name
    assert sha(source_path) == source_hash
    for report in reports:
        assert sha(work / 'results' / (report['条件'] + '.json')) == report['結果SHA256']
        assert sha(work / 'ledgers' / (report['条件'] + '.pkl')) == report['台帳SHA256']
    common.save('全22配分の公開注文と独立全会計監査.json', dict(全合格=True, **counts,
        条件別=reports, 源注文SHA256=source_hash, 入力SHA256=input_hashes, 監査器SHA256=sha(Path(__file__)),
        親実行関数呼出=False, 親会計関数呼出=False,
        時価='各源の現金＋残数量×現在値−源別全返済注文の見込料金。最大保有は同観測内の注文ごとの瞬間値。',
        源不変='源別配分が同じなら他源配分が変わっても経済注文・親・脚・全時価が不変。全源通番UIDだけは比較から外す。',
        限界='会計と機械的実行の確認であり、実ミニ・マイクロの約定や未知相場での利益を保証しない。'))
    print(json.dumps(dict(全合格=True, **counts), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
