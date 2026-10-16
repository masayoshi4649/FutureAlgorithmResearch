"""独立追加の全保存結果を、元玉指紋・建値別会計・合算時価から検算する。"""

from collections import defaultdict
import hashlib
import math
from pathlib import Path
import pickle
import sys
import numpy as np
from checks import ROOT, HERE, WORK, module, save


def read(path):
    """
    機能: 保存済み日本語JSONを読み込む。
    引数: path(Path)。
    返り値: object。
    """
    import json
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    """
    機能: 固定ソース・結果・台帳の指紋を取得する。
    引数: path(Path)。
    返り値: str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def settle(ready, ledger, fifo):
    """
    機能: 元玉と追加玉の建値を識別して全注文料・決済脚・親組を独立集計する。
    引数: ready/ledger(dict)、fifo(module)は比率集計だけを再利用。
    返り値: dictの基本会計。異なる独立建玉を単一FIFOで取り違えない。
    """
    orders, trades, cycles = ledger['orders'], ledger['trades'], ledger['cycles']
    fee = 41.8 if ready['symbol'] == 'TOPIX' else 11.
    scale = 1000 if ready['symbol'] == 'TOPIX' else 10
    entries, exits = {}, defaultdict(list)
    charges = []
    parent_held = defaultdict(lambda: [0, 0])
    parent_max = defaultdict(lambda: [0, 0])
    maximum = [0, 0]
    held = [0, 0]
    for o in orders:
        row, source, cid, side, q = map(int, o[:5])
        assert 0 <= source < row < len(ready['last']) and q > 0
        paid = math.floor(q * fee + 1e-8)
        charges.append(paid)
        d = side if o[7] else -side
        index = 0 if d > 0 else 1
        change = q if o[7] else -q
        held[index] += change
        parent_held[cid][index] += change
        assert min(held) >= 0 and max(held) <= ledger['settings']['audit_cap']
        assert min(parent_held[cid]) >= 0
        maximum = [max(a, b) for a, b in zip(maximum, held)]
        parent_max[cid][0] = max(parent_max[cid][0], sum(parent_held[cid]))
        parent_max[cid][1] = max(parent_max[cid][1], abs(parent_held[cid][0] - parent_held[cid][1]))
        if o[7]:
            key = cid, row, side
            assert key not in entries
            entries[key] = [q, q, o[5], paid]
        else:
            exits[cid, row, side, o[5], int(o[6])].append([q, paid / q])
    assert not any(held) and all(not any(v) for v in parent_held.values())
    np.testing.assert_array_equal(charges, ledger['fees'])
    details = []
    grouped = defaultdict(list)
    for t in trades:
        cid, side, q, entry, end = int(t[0]), int(t[2]), int(t[3]), int(t[6]), int(t[7])
        lot = entries[cid, entry, side]
        assert lot[0] >= q and lot[2] == t[4]
        lot[0] -= q
        key = cid, end, -side, t[5], int(t[9])
        remaining = q
        exit_fee = 0.
        while remaining:
            assert exits[key]
            order = exits[key][0]
            part = min(remaining, order[0])
            exit_fee += part * order[1]
            order[0] -= part
            remaining -= part
            if not order[0]:
                exits[key].pop(0)
        gross = side * q * (t[5] - t[4]) * scale
        assert abs(gross - t[10] * scale) < 1e-5
        allocated = q * lot[3] / lot[1] + exit_fee
        detail = dict(組=cid, 方向=side, 枚数=q, 新規行=entry, 返済行=end,
            新規原本行=int(ready['seq'][entry]), 返済原本行=int(ready['seq'][end]),
            新規時刻=float(ready['time_s'][entry]), 返済時刻=float(ready['time_s'][end]),
            建値=float(t[4]), 返済値=float(t[5]), 理由=int(t[9]), 利益損失前=gross,
            手数料=allocated, 収支=gross - allocated)
        details.append(detail)
        grouped[cid].append(detail)
    assert all(v[0] == 0 for v in entries.values()) and all(not v for v in exits.values())
    fifo.same(details, ledger['net_trades'])
    core_cycles = {int(c[0]): c for c in ledger['core_ledger']['cycles']}
    risks, nets = [], []
    assert set(grouped) == set(core_cycles) == {int(c[0]) for c in cycles}
    for c in cycles:
        cid = int(c[0])
        original = core_cycles[cid]
        parts = grouped[cid]
        assert c[1] == original[1] and c[4] == original[4] and c[5] == original[5] and c[8] == original[8]
        assert c[2] == max(t['返済行'] for t in parts) and c[9] == parts[-1]['理由']
        assert abs(c[3] * scale - math.fsum(t['利益損失前'] for t in parts)) < 1e-5
        assert c[6:8].tolist() == parent_max[cid]
        risks.append(c[4] * scale)
        nets.append(math.fsum(t['収支'] for t in parts))
    win = [t for t in details if t['収支'] > 0]
    loss = [t for t in details if t['収支'] < 0]
    flat = [t for t in details if t['収支'] == 0]
    row = dict(session=ready['session'], symbol=ready['symbol'],
        gross=math.fsum(t['利益損失前'] for t in details), fees=sum(charges), net=math.fsum(nets),
        profit=math.fsum(t['収支'] for t in win), loss=-math.fsum(t['収支'] for t in loss),
        wins=len(win), losses=len(loss), flats=len(flat), winning_lots=sum(t['枚数'] for t in win),
        losing_lots=sum(t['枚数'] for t in loss), flat_lots=sum(t['枚数'] for t in flat),
        campaigns=len(nets), campaign_wins=sum(n > 0 for n in nets), campaign_losses=sum(n < 0 for n in nets),
        campaign_profit=math.fsum(n for n in nets if n > 0), campaign_loss=-math.fsum(n for n in nets if n < 0),
        sum_r=math.fsum(n / r for n, r in zip(nets, risks)), max_drawdown=0.,
        max_long=maximum[0], max_short=maximum[1])
    assert abs(row['gross'] - row['fees'] - row['net']) < 1e-5
    fifo.ratios(row)
    return row


def components(ledger, baseline):
    """
    機能: 元玉の全保存値を基準へ照合し、追加以外の変更がないことを確認する。
    引数: ledger/baseline(dict)。
    返り値: intの元玉配列照合数。
    """
    core = ledger['core_ledger']
    count = 0
    for name, value in baseline.items():
        if isinstance(value, np.ndarray):
            np.testing.assert_array_equal(value, core[name], err_msg=name)
            count += 1
        else:
            assert value == core[name], name
    sat_orders, sat_trades = ledger['satellite_orders'], ledger['satellite_trades']
    orders = np.concatenate((sat_orders, core['orders']))
    trades = np.concatenate((sat_trades, core['trades']))
    orders = orders[np.argsort(orders[:, 0], kind='stable')]
    trades = trades[np.argsort(trades[:, 7], kind='stable')]
    np.testing.assert_array_equal(orders, ledger['orders'])
    np.testing.assert_array_equal(trades, ledger['trades'])
    return count


def event_order(ready, ledger, config, strategy):
    """
    機能: 追加の一回制限・前観測予約・元終了後返済・更新線の有効順を確認する。
    引数: ready/ledger/config(dict)、strategy(module)。
    返り値: intの確認証跡数。
    """
    events = ledger['satellite_events']
    sat = ledger['satellite_orders']
    core = ledger['core_ledger']
    if not config['relation']:
        assert not len(events) and not len(sat)
        return 0
    quiet = strategy.old.time_filter.features(ready, 'U')
    previous_row = -1
    for e in events:
        row, cid, code = map(int, e[:3])
        assert row >= previous_row
        previous_row = row
        if code in (1, 3, 6):
            assert e[3] == row
        elif code in (2, 4):
            assert e[3] < row
            match = sat[(sat[:, 0] == row) & (sat[:, 2] == cid) & (sat[:, 7] == (code == 2))]
            assert len(match) == 1
            o = match[0]
            assert e[3] == o[1] and e[5] == o[4] and e[6] == o[5]
    for cid in np.unique(sat[:, 2]):
        own = sat[sat[:, 2] == cid]
        entry = own[own[:, 7] == 1]
        close = own[own[:, 7] == 0]
        assert len(entry) == len(close) == 1
        opening, ending = entry[0], close[0]
        source = int(opening[1])
        initial = core['orders'][(core['orders'][:, 2] == cid) & (core['orders'][:, 7] == 1)][0]
        assert opening[3] == initial[3] * config['relation'] and opening[4] == initial[4]
        start = int(opening[0])
        assert not quiet['active'][start] and not quiet['force'][start]
        assert ready['time_s'][start] < ready['limit'] - ledger['settings']['entry_cutoff_min'] * 60
        updates = events[(events[:, 1] == cid) & (events[:, 2] == 3)]
        prior = None
        for event in updates:
            i = int(event[0])
            side, atr = opening[3], event[8]
            if i == start:
                level = opening[5] - side * max(ready['tick'], config['stop_atr'] * atr)
                assert event[9] == 81
            else:
                values = ready['last'][start + 1:i + 1]
                peak = max(opening[5], np.max(values)) if side > 0 else min(opening[5], np.min(values))
                assert side * (peak - opening[5]) >= config['activation_atr'] * atr - 1e-8
                level = peak - side * max(ready['tick'], config['trail_atr'] * atr)
                assert event[9] == 82 and event[11] == 1
            level = (math.floor(level / ready['tick'] + 1e-9) if side > 0 else math.ceil(level / ready['tick'] - 1e-9)) * ready['tick']
            assert abs(event[6] - level) < 1e-7
            assert prior is None or side * (event[6] - prior) > 0
            prior = event[6]
        i, reason = int(ending[0]), int(ending[6])
        if reason in (81, 82):
            last = updates[updates[:, 0] < i][-1]
            assert ending[1] == last[0] and reason == last[9]
        elif reason == 83:
            finished = core['cycles'][core['cycles'][:, 0] == cid][0]
            origin = int(finished[2])
            assert ending[1] == origin and i > origin
            valid = np.flatnonzero(np.isfinite(ready['last'][origin + 1:]) & (ready['last'][origin + 1:] > 0))
            assert i == origin + 1 + valid[0]
        elif reason == 84:
            assert quiet['active'][i] or quiet['force'][i]
        else:
            assert reason == 85 and ready['time_s'][i] >= ready['limit']
    assert not np.any(ledger['satellite_stats'][:2])
    return len(events)


def main():
    """
    機能: 全二十二保存結果の口座・期間・元玉不変・独立追加差額を確認する。
    引数: なし。
    返り値: None。戦略を再生せず、全結果の完了後に実行する。
    """
    fixed = read(WORK / '事前固定.json')
    for field in ('code_SHA256', '基準結果SHA256'):
        for path, value in fixed[field].items():
            assert digest(ROOT / path) == value, path
    strategy = module('監査87保存独立追加戦略', WORK / 'strategy.py')
    prepare = module('監査87保存独立追加入力', ROOT / 'work/wave_v85/prepare.py')
    inputs, _, _ = prepare.load_inputs(verify=False)
    prior_folder = ROOT / 'work/wave_v85/audit'
    sys.path.insert(0, str(prior_folder))
    module('original', prior_folder / 'original.py')
    account = module('監査87保存独立追加比率', prior_folder / 'accounts.py')
    fifo = module('監査87保存独立追加集計', ROOT / 'work/wave_v87/audit/allocation_fifo.py')
    reports = []
    totals = dict(口座数=0, 注文数=0, 決済脚数=0, 元玉配列一致数=0, 追加証跡数=0)
    for model in fixed['models']:
        baseline = pickle.loads((ROOT / f'work/wave_v85/{model}/ledgers/E01_G_U.pkl').read_bytes())
        for config in fixed['catalog']:
            path = WORK / model / 'results' / f"{config['id']}.json"
            ledger_path = WORK / model / 'ledgers' / f"{config['id']}.pkl"
            packet = read(path)
            assert packet['config'] == config and packet['run']['code_SHA256'] == fixed['code_SHA256']
            assert packet['run']['input_SHA256'] == fixed['input_SHA256']
            assert digest(ledger_path) == packet['ledger_SHA256']
            ledgers = pickle.loads(ledger_path.read_bytes())
            rows = []
            for actual in packet['rows']:
                key = actual['session'], actual['symbol']
                ledger, ready = ledgers[key], inputs[key]
                totals['元玉配列一致数'] += components(ledger, baseline[key])
                row = settle(ready, ledger, fifo)
                trace = account.trace(ready, ledger, row)
                row['max_drawdown'] = float(np.max(np.maximum.accumulate(np.maximum(trace['net'], 0)) - trace['net'], initial=0))
                account.ratios(row)
                sat_orders, sat_trades = ledger['satellite_orders'], ledger['satellite_trades']
                sat_fee = sum(math.floor(o[4] * strategy.previous.FEES[key[1]] + 1e-8) for o in sat_orders)
                sat_gross = math.fsum(t[10] * strategy.previous.VALUES[key[1]] for t in sat_trades)
                core_net = math.fsum(t['収支'] for t in baseline[key]['net_trades'])
                assert abs(row['net'] - core_net - sat_gross + sat_fee) < 1e-5
                row.update(core_net=core_net, satellite_gross=sat_gross, satellite_fees=float(sat_fee),
                    satellite_net=sat_gross - sat_fee, core_unchanged=True,
                    satellite_entries=int(np.count_nonzero(sat_orders[:, 7])))
                account.equal(row, actual)
                totals['追加証跡数'] += event_order(ready, ledger, config, strategy)
                totals['口座数'] += 1
                totals['注文数'] += len(ledger['orders'])
                totals['決済脚数'] += len(ledger['trades'])
                rows.append(row)
            periods = {p: {s: account.aggregate(fifo, rows, s, fixed[p]) for s in ('TOPIX', 'NK225')}
                       for p in ('前16', '後14', '全30')}
            account.equal(periods, packet['periods'])
            reports.append(dict(モデル=model, 条件=config['id'], 結果SHA256=digest(path), 台帳SHA256=digest(ledger_path)))
            print(model, config['id'], '元玉完全一致・全会計・独立追加順序一致', flush=True)
    assert totals['口座数'] == 1320 and len(reports) == 22
    for path, value in fixed['code_SHA256'].items():
        assert digest(ROOT / path) == value, path
    save('全11独立追加条件の元玉不変と全会計監査.json', dict(全合格=True, 条件数=len(reports),
        **totals, 条件別=reports, 親会計関数呼出=False, 監査器SHA256=digest(Path(__file__))))


if __name__ == '__main__':
    main()
