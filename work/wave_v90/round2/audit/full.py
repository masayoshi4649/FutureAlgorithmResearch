"""追加15条件を、正式執行器と会計器を呼ばず全原板・全親で独立検算する。"""

from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path
import pickle

import numpy as np

import common
import protocol


def read(path):
    """
    機能: 凍結済み仕様又は保存された結果・台帳を読む。
    引数: path(Path)。
    返り値: object。
    """
    if path.suffix == '.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def array_sha(array):
    """
    機能: 全行を省略せず、同一順の数値配列を内容指紋化する。
    引数: array(ndarray)。
    返り値: strのSHA256。
    """
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def expand(changes, n):
    """
    機能: 疎な行末状態を全原板行へ復元する。
    引数: changes(ndarray)、n(int)。
    返り値: ndarray[n,6]。
    """
    changes = np.asarray(changes, float)
    rows = changes[:, 0].astype(int)
    assert rows[0] == 0 and rows[-1] == n - 1 and (np.diff(rows) > 0).all()
    value = changes[:, 1:]
    return value[np.searchsorted(rows, np.arange(n), side='right') - 1]


def curves(record, orders):
    """
    機能: 注文ごとの源別現金を行番号へ伝播し、最良気配で全原板清算時価を復元する。
    引数: record(dict)、orders(ndarray[17列])。
    返り値: tupleの全行時価、源別時価、源別保有数量、源別現金。
    """
    n = len(record['time_s'])
    unit, fee_unit = (1000., 41.8) if record['symbol'] == 'TOPIX' else (10., 11.)
    cash = np.zeros((n, 2))
    positions = np.zeros((n, 2))
    for source in range(2):
        selected = orders[orders[:, 3] == source]
        rows, values, quantities = [-1], [0.], [0.]
        balance, position = 0., 0.
        for order in selected:
            row = int(order[0])
            balance -= order[4] * order[5] * order[6] * unit + order[9]
            position += order[4] * order[5]
            if rows[-1] == row:
                values[-1], quantities[-1] = balance, position
            else:
                rows.append(row)
                values.append(balance)
                quantities.append(position)
        offsets = np.searchsorted(rows, np.arange(n), side='right') - 1
        cash[:, source] = np.array(values)[offsets]
        positions[:, source] = np.array(quantities)[offsets]
    qok = record['quote_valid'] & np.isfinite(record['bid']) & np.isfinite(record['ask'])
    qok &= (record['bid'] > 0) & (record['ask'] > record['bid'])
    observed = np.maximum.accumulate(np.where(qok, np.arange(n), -1))
    last_bid, last_ask = record['bid'][np.maximum(observed, 0)], record['ask'][np.maximum(observed, 0)]
    source_equity = cash.copy()
    for source in range(2):
        position = positions[:, source]
        holding = position != 0
        assert (observed[holding] >= 0).all()
        price = np.where(position[holding] > 0, last_bid[holding], last_ask[holding])
        source_equity[holding, source] += position[holding] * price * unit - np.floor(np.abs(position[holding]) * fee_unit + 1e-8)
    return source_equity.sum(axis=1), source_equity, positions, cash


def totals(trades):
    """
    機能: 源別親又は方向別親の費用後純利益から、相殺せず利益・損失を算定する。
    引数: trades(ndarray[16列])。
    返り値: dict。
    """
    values = trades[:, 11]
    positive, negative = values > 1e-5, values < -1e-5
    profit, loss = float(values[positive].sum()), float(-values[negative].sum())
    wins, losses = int(positive.sum()), int(negative.sum())
    average_win, average_loss = profit / wins if wins else None, loss / losses if losses else None
    return dict(profit=profit, loss=loss, net=profit - loss, gross=float(trades[:, 10].sum()),
                fees=float((trades[:, 8] + trades[:, 9]).sum()), campaigns=len(trades), winning_campaigns=wins,
                losing_campaigns=losses, flat_campaigns=len(trades) - wins - losses,
                winning_lots=int(trades[positive, 5].sum()), losing_lots=int(trades[negative, 5].sum()),
                flat_lots=int(trades[~(positive | negative), 5].sum()), lots=int(trades[:, 5].sum()),
                profit_share=profit / (profit + loss) if profit + loss else None,
                average_win=average_win, average_loss=average_loss,
                payoff=average_win / average_loss if wins and losses and average_loss > 0 else None)


def path(curve):
    """
    機能: 初期値0を含む全原板清算時価の頂点・底点・最大下落を算定する。
    引数: curve(float配列)。
    返り値: dict。
    """
    values = np.r_[0., curve]
    return dict(equity_peak=float(values.max()), equity_trough=float(values.min()),
                equity_drawdown=float((np.maximum.accumulate(values) - values).max()))


def management(record, signal, config, orders, trades):
    """
    機能: 各源の保有中に最初に成立した損切り・追尾・期限・反対合意・場末を別式で復元する。
    引数: record/signal/config(dict)、orders/trades(ndarray)。
    返り値: intの親照合数。正式保有管理ループは呼ばない。
    """
    times, bid, ask = record['time_s'], record['bid'], record['ask']
    qok = record['quote_valid'] & np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask > bid)
    current_modes = protocol.modes(record, signal)
    n = len(times)
    force = int(np.searchsorted(times, record['limit'] - 60., side='left'))
    assert force < n
    checks = 0
    for trade in trades:
        parent, source, entry, exit_row, side = map(int, trade[:5])
        entry_price = trade[6]
        rows = np.arange(entry + 1, force + 1)
        assert len(rows)
        reasons = np.zeros(len(rows), np.int8)
        if source == 0:
            eligible = rows[qok[rows]]
            quoted = bid[eligible] if side == 1 else ask[eligible]
            favorable = side * quoted
            preceding_peak = np.maximum.accumulate(np.r_[side * entry_price, favorable])[:-1]
            hit = favorable <= preceding_peak - signal['trend_width'] + record['tick'] * 1e-8
            selected = eligible[hit]
            reasons[selected - entry - 1] = np.where(np.abs(preceding_peak[hit] - side * entry_price) < record['tick'] * 1e-8, 1, 2)
            reasons[times[rows] >= times[entry] + config['trend_hold_seconds']] = 3
        else:
            width = config['width_ticks'] * record['tick']
            good = record['price_valid'][rows]
            progress = side * (record['price'][rows] - entry_price)
            if config['exit_opposite_range']:
                reasons[good & (current_modes[rows] == -side)] = 7
            reasons[good & (progress >= config['target_widths'] * width)] = 5
            reasons[good & (progress <= -config['stop_widths'] * width)] = 6
        reasons[-1] = 4
        first = int(np.flatnonzero(reasons)[0])
        trigger = int(rows[first])
        reason = int(reasons[first])
        close = orders[(orders[:, 2] == parent) & (orders[:, 7] == 0)]
        assert len(close) == 1
        assert int(close[0, 8]) == reason, (record['session'], record['symbol'], parent, reason, close[0, 8])
        if reason == 4:
            assert int(close[0, 1]) == trigger - 1 and close[0, 10] == record['limit'] - 60.
        else:
            assert int(close[0, 1]) == trigger and close[0, 10] == times[trigger], (parent, trigger, close)
        checks += 1
    return checks


def maxima(events):
    """
    機能: 行内イベントの各瞬間で保有・未約定占有・合計保有の最大を独立復元する。
    引数: events(ndarray[12列])。
    返り値: float配列[最大買保有,最大売保有,最大買占有,最大売占有,最大合計保有]。
    """
    status, side, quantity = np.zeros(2, int), np.zeros(2, int), np.zeros(2)
    output = np.zeros(5)
    for event in events:
        source, code = int(event[2]), int(event[3])
        if code == 1:
            status[source], side[source], quantity[source] = 1, int(event[4]), event[5]
        elif code == 2:
            status[source] = 3
        elif code == 4:
            status[source] = 2
        elif code in (5, 6):
            status[source] = 0
        occupying = status > 0
        holding = status >= 2
        current = [quantity[holding & (side == 1)].sum(), quantity[holding & (side == -1)].sum(),
                   quantity[occupying & (side == 1)].sum(), quantity[occupying & (side == -1)].sum(), quantity[holding].sum()]
        output = np.maximum(output, current)
    return output


def account(key, record, signal, config, ledger):
    """
    機能: 全注文・決済親・予約占有枠・全原板時価を独立再生し、保存指紋と照合する。
    引数: key(tuple)、record/signal/config/ledger(dict)。
    返り値: tuple[dict,dict]の場会計と件数。
    """
    orders = np.asarray(ledger['orders'], float).reshape(-1, 17)
    trades = np.asarray(ledger['trades'], float).reshape(-1, 16)
    events = np.asarray(ledger['events'], float).reshape(-1, 12)
    assert np.isfinite(orders).all() and np.isfinite(trades).all() and np.isfinite(events).all()
    assert (np.diff(orders[:, 0]) >= 0).all() and len(orders) == 2 * len(trades)
    n, fee_unit, unit = len(record['time_s']), 41.8 if key[1] == 'TOPIX' else 11., 1000. if key[1] == 'TOPIX' else 10.
    assert ledger['input_rows'] == n and np.all(np.asarray(ledger['slots'])[:, 0] == 0)
    assert array_sha(signal['mode']) == ledger['state_SHA256']
    expected_trades, entries = [], {}
    for order in orders:
        row, decision, parent, source, side, quantity, price, new, reason, fee, decision_time, fill_time, limit_price, cycle, method, entry_side, uid = order
        row, decision, parent, source, side, quantity, new, reason, cycle, method, entry_side = map(int, (row, decision, parent, source, side, quantity, new, reason, cycle, method, entry_side))
        assert 0 <= decision < row < n and source in (0, 1) and side in (-1, 1) and quantity > 0
        assert fee == math.floor(quantity * fee_unit + 1e-8) and record['quote_valid'][row]
        assert fill_time == record['time_s'][row]
        if reason == 4 and decision_time == record['limit'] - 60.:
            assert record['time_s'][decision] < decision_time <= fill_time
        else:
            assert decision_time == record['time_s'][decision]
        if method == 1:
            assert new == 1 and source == 1
            assert record['ask'][row] <= limit_price if side == 1 else record['bid'][row] >= limit_price
            expected_price = (record['ask'][row] if side == 1 else record['bid'][row]) if config['improve_limit'] else limit_price
            assert price == expected_price
        else:
            assert method == 0 and price == (record['ask'][row] if side == 1 else record['bid'][row])
        if new:
            assert parent not in entries and side == entry_side
            entries[parent] = order
        else:
            entry = entries.pop(parent)
            assert source == entry[3] and side == -entry[4] and quantity == entry[5] and cycle == entry[13]
            assert entry_side == entry[4]
            gross = entry[4] * (price - entry[6]) * quantity * unit
            expected_trades.append([parent, source, entry[0], row, entry[4], quantity, entry[6], price, entry[9], fee,
                                    gross, gross - entry[9] - fee, entry[8], reason, cycle, entry[1]])
    assert not entries
    common.same(trades, np.asarray(expected_trades).reshape(-1, 16))
    curve, source_curve, positions, cash = curves(record, orders)
    trace = expand(ledger['trace_changes'], n)
    assert array_sha(curve) == ledger['curve_SHA256'], (key, '全原板清算時価指紋')
    assert array_sha(source_curve) == ledger['source_curve_SHA256'], (key, '源別全原板清算時価指紋')
    assert [array_sha(source_curve[:, i]) for i in range(2)] == ledger['source_curve_column_SHA256']
    assert array_sha(trace) == ledger['target_trace_SHA256']
    assert (positions[-1] == 0).all() and not trace[-1].any()
    common.same(trace[:, 0], np.maximum(positions, 0).sum(axis=1))
    common.same(trace[:, 1], np.maximum(-positions, 0).sum(axis=1))
    result = dict(orders=orders, trades=trades, events=events, target_trace=trace)
    checks = protocol.verify(record, signal, config, result)
    checks.update(protocol.activation(record, signal, config, result))
    checks['保有途中の最初返済条件'] = management(record, signal, config, orders, trades)
    common.same(float(curve[-1]), float(trades[:, 11].sum()))
    common.same(float(orders[:, 9].sum()), float((trades[:, 8] + trades[:, 9]).sum()))
    row = dict(session=key[0], symbol=key[1], **totals(trades), **path(curve))
    row['sources'] = {name: dict(**totals(trades[trades[:, 1] == source]), **path(source_curve[:, source]))
                      for source, name in enumerate(('J2', 'O06'))}
    row['directions'] = {name: totals(trades[trades[:, 4] == side]) for side, name in ((1, '買い'), (-1, '売り'))}
    row['maximums'] = {name: int(trace[:, i].max(initial=0)) for i, name in enumerate(ledger['trace_columns'])}
    instant_max = maxima(events)
    for i, name in enumerate(ledger['trace_columns'][:4]):
        row['maximums'][name] = int(instant_max[i])
    row['event_counts'] = {str(int(code)): int((events[:, 3] == code).sum()) for code in np.unique(events[:, 3])}
    stats = np.asarray(ledger['stats'])
    common.same(stats[:4], instant_max[:4])
    common.same(stats[8], instant_max[4])
    common.same(stats[4:8], trace[-1, [0, 1, 4, 5]])
    common.same(stats[9:15], [int(((events[:, 3] == 6) & (events[:, 2] == 1)).sum()),
                             int((events[:, 3] == 7).sum()), int(((events[:, 3] == 9) & (events[:, 2] == 0)).sum()),
                             int(((events[:, 3] == 9) & (events[:, 2] == 1)).sum()),
                             int(((events[:, 3] == 1) & (events[:, 2] == 0)).sum()),
                             int(((events[:, 3] == 1) & (events[:, 2] == 1)).sum())])
    common.same(stats[15], float(cash[-1].sum()))
    row['stats'] = {name: float(stats[i]) for i, name in enumerate(ledger['stat_columns'])}
    checks.update(注文=len(orders), 決済親=len(trades), 全原板行=n)
    return row, checks


def sum_rows(rows):
    """
    機能: 商品内の同一会計列を足し、割合と平均勝負額を独立再算定する。
    引数: rows(list[dict])。
    返り値: dict。
    """
    fields = ('profit', 'loss', 'net', 'gross', 'fees', 'campaigns', 'winning_campaigns', 'losing_campaigns',
              'flat_campaigns', 'winning_lots', 'losing_lots', 'flat_lots', 'lots')
    result = {name: sum(row[name] for row in rows) for name in fields}
    result['profit_share'] = result['profit'] / (result['profit'] + result['loss']) if result['profit'] + result['loss'] else None
    wins, losses = result['winning_campaigns'], result['losing_campaigns']
    result['average_win'] = result['profit'] / wins if wins else None
    result['average_loss'] = result['loss'] / losses if losses else None
    result['payoff'] = result['average_win'] / result['average_loss'] if wins and losses else None
    return result


def aggregate(rows, symbol, sessions):
    """
    機能: 日別・週別・最大利益日除外・全場時価連結を、正式会計から独立に算定する。
    引数: rows(list[dict])、symbol(str)、sessions(list[str])。
    返り値: dict。
    """
    by_key = {(row['session'], row['symbol']): row for row in rows}
    selected = [by_key[(session, symbol)] for session in sessions]
    result = sum_rows(selected)
    balance = high = drawdown = 0.
    for row in selected:
        drawdown = max(drawdown, row['equity_drawdown'], high - balance - row['equity_trough'])
        high = max(high, balance + row['equity_peak'])
        balance += row['net']
    result.update(equity_drawdown=drawdown, positive_sessions=sum(row['net'] > 1e-5 for row in selected),
                  losing_sessions=sum(row['net'] < -1e-5 for row in selected), no_trade_sessions=sum(row['campaigns'] == 0 for row in selected),
                  active_sessions=sum(row['campaigns'] > 0 for row in selected), session_count=len(selected),
                  worst_session=min((row['net'] for row in selected), default=0.),
                  all_sessions_profitable=all(row['net'] > 1e-5 for row in selected))
    result['positive_session_rate'] = result['positive_sessions'] / result['active_sessions'] if result['active_sessions'] else None
    days, weeks = {}, {}
    for row in selected:
        stamp = date.fromisoformat(row['session'][:10])
        for target, label in ((days, str(stamp)), (weeks, str(stamp - timedelta(days=stamp.weekday())))):
            target.setdefault(label, []).append(row)
    result['days'] = {label: sum_rows(values) for label, values in days.items()}
    result['weeks'] = {label: sum_rows(values) for label, values in weeks.items()}
    best = max(result['days'], key=lambda label: result['days'][label]['net'], default=None)
    result['best_day'] = best
    result['without_best_day'] = sum_rows([row for row in selected if row['session'][:10] != best])
    result['sources'] = {name: sum_rows([row['sources'][name] for row in selected]) for name in ('J2', 'O06')}
    result['directions'] = {name: sum_rows([row['directions'][name] for row in selected]) for name in ('買い', '売り')}
    result['maximums'] = {name: max((row['maximums'][name] for row in selected), default=0) for name in selected[0]['maximums']}
    return result


def main():
    """
    機能: 追加15×60口座と全期間150集計を検算し、新しい監査証跡だけを追加する。
    引数: なし。
    返り値: None。
    """
    import sys
    sys.path.insert(0, str(common.WORK))
    sys.modules['data'] = common.module('追加90全監査旧データ読取', common.BASE / 'data.py')
    import data
    import strategy
    fixed = read(common.WORK / '事前固定.json')
    for name, digest in fixed['SHA256'].items():
        assert common.sha(common.ROOT / name) == digest, name
    material = data.load_inputs()
    counters, fingerprints = {}, {}
    conditions = fixed['条件']
    assert len(conditions) == 15
    assert {path.stem for path in (common.WORK / 'results').glob('*.json')} == {value['id'] for value in conditions}
    period_map = {'全30': fixed['全30'], '前16': fixed['前16'], '後14': fixed['後14'],
                  'デイ': [value for value in fixed['全30'] if value.endswith('_Day')],
                  'ナイト': [value for value in fixed['全30'] if value.endswith('_Night')]}
    for config in conditions:
        result_path = common.WORK / 'results' / (config['id'] + '.json')
        ledger_path = common.WORK / 'ledgers' / (config['id'] + '.pkl')
        expected, ledgers = read(result_path), read(ledger_path)
        assert expected['config'] == config and common.sha(ledger_path) == expected['ledger_SHA256']
        assert set(ledgers) == set(material['prices'])
        prepared = strategy.prepare(material, config)
        rows = []
        for key in sorted(ledgers):
            value = prepared[key]
            row, counts = account(key, value['record'], value['signal'], config, ledgers[key])
            rows.append(row)
            for name, count in counts.items():
                counters[name] = counters.get(name, 0) + count
        common.same(rows, expected['rows'])
        for period, sessions in period_map.items():
            for symbol in common.SYMBOLS:
                common.same(aggregate(rows, symbol, sessions), expected['periods'][period][symbol])
                counters['商品期間集計'] = counters.get('商品期間集計', 0) + 1
        counters['口座'] = counters.get('口座', 0) + len(ledgers)
        fingerprints.update(common.fingerprint([result_path, ledger_path]))
        del prepared, ledgers
        print(f'{config["id"]} 全60原板時価・親・予約・最初約定・途中判断・全期間会計合格', flush=True)
    fingerprints.update(common.fingerprint([Path(__file__), Path(common.__file__), Path(protocol.__file__), common.WORK / '事前固定.json']))
    common.save('追加15条件の全原板気配改善と活動基準及び全親会計の独立検算.json',
                dict(全合格=True, 全期間既知=True, 対象='900口座・全150期間商品集計の省略なし独立復元',
                     検査件数=counters, SHA256=fingerprints, 現在API取得=0, 実注文=0, 旧変更=0,
                     固定先行コード変更=0, 新損益による監査条件選別=0))


if __name__ == '__main__':
    main()
