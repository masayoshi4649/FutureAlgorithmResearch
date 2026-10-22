"""複数追撃の保存注文を、売買現金とUID別損益で独立に照合する。"""

from collections import defaultdict
import argparse
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def same(left, right):
    """
    機能: 数値の会計差が丸め誤差の範囲か検査する。
    引数: left/right(float)は比較する数値。
    返り値: None。不一致の場合は例外。
    """
    assert abs(left-right) < 1e-6, (left, right)


def ledger(orders, times, bid, ask, valid, fee_tenths, multiplier, cap=10):
    """
    機能: 独立した現金会計と個別玉台帳で保存注文を検査する。
    引数: orders/times/bid/ask/valid(ndarray)、fee_tenths/multiplier/cap(int)。
    返り値: dictは場・親・個別玉の損益と数量検査結果。
    """
    normal = np.flatnonzero(valid & np.isfinite(bid) & np.isfinite(ask)
                            & (bid > 0) & (ask > bid))
    parents = defaultdict(lambda: dict(gross=0., fees=0, cash=0., legs={}))
    inventory = {}
    held = {1: 0, -1: 0}
    maximum = entries = quantity = 0
    origin_rows = {}
    assert orders.ndim == 2 and orders.shape[1] == 10
    assert np.all(np.diff(orders[:, 0]) >= 0)
    for order in orders:
        fill, decision, pid, side, amount = map(int, order[:5])
        price = float(order[5])
        reason, new, uid, fee = map(int, order[6:10])
        assert 0 <= decision < fill < len(times)
        assert side in (-1, 1) and amount > 0 and new in (0, 1)
        assert fee == amount*fee_tenths//10
        at = int(np.searchsorted(normal, fill))
        assert at < len(normal) and int(normal[at]) == fill
        same(price, ask[fill] if side > 0 else bid[fill])
        parent = parents[pid]
        component = parent['legs'].setdefault(uid, dict(gross=0., fees=0, cash=0., entries=0, quantity=0))
        cash = -side*amount*price*multiplier
        for target in (parent, component):
            target['cash'] += cash
            target['fees'] += fee
        parent.setdefault('entry', fill)
        parent.setdefault('side', side)
        parent['exit'] = fill
        key = pid, uid
        if new:
            assert key not in inventory, ('個別玉UIDの再利用', key)
            inventory[key] = [amount, price, side]
            origin_rows[key] = fill
            held[side] += amount
            entries += 1
            quantity += amount
            component['entries'] += 1
            component['quantity'] += amount
        else:
            assert key in inventory, ('建玉なしの返済', key)
            prior = inventory[key]
            assert prior[0] >= amount and prior[2] == -side
            assert fill >= origin_rows[key]
            gains = prior[2]*amount*(price-prior[1])*multiplier
            parent['gross'] += gains
            component['gross'] += gains
            prior[0] -= amount
            held[-side] -= amount
        assert 0 <= held[1] <= cap and 0 <= held[-1] <= cap, ('上限超過', fill, held)
        maximum = max(maximum, held[1], held[-1])
    assert held == {1: 0, -1: 0} and all(v[0] == 0 for v in inventory.values())
    for pid, parent in parents.items():
        same(parent['gross'], parent['cash'])
        parent['net'] = parent['gross']-parent['fees']
        for uid, component in parent['legs'].items():
            same(component['gross'], component['cash'])
            component['net'] = component['gross']-component['fees']
    profits = sum(p['net'] for p in parents.values() if p['net'] > 0)
    losses = -sum(p['net'] for p in parents.values() if p['net'] < 0)
    return dict(profit=profits, loss=losses, net=profits-losses,
                gross=sum(p['gross'] for p in parents.values()),
                fees=sum(p['fees'] for p in parents.values()),
                entries=entries, quantity=quantity, max_per_side=maximum,
                parents=dict(parents), uids=len(inventory))


def compare(saved, observed):
    """
    機能: 保存済みの場・親・個別玉会計を独立会計と照合する。
    引数: saved/observed(dict)は本会計と独立会計。
    返り値: intは一致した数値項目数。
    """
    count = 0
    for key in ('profit', 'loss', 'net', 'gross', 'fees', 'entries', 'quantity', 'max_per_side'):
        same(saved[key], observed[key])
        count += 1
    byid = {int(p['id']): p for p in saved['parents']}
    assert byid.keys() == observed['parents'].keys()
    for pid, parent in observed['parents'].items():
        counterpart = byid[pid]
        for key in ('gross', 'fees', 'net', 'entry', 'exit', 'side'):
            same(parent[key], counterpart[key])
            count += 1
        assert set(parent['legs']) == set(map(int, counterpart['legs']))
        for uid, component in parent['legs'].items():
            for key in ('gross', 'fees', 'net', 'entries', 'quantity'):
                same(component[key], counterpart['legs'][str(uid)][key])
                count += 1
    return count


def expanded(value, index, default):
    """
    機能: 事前設定の単一値または玉別配列から対象玉の値を読む。
    引数: value(float/list[float]/None)、index(int)、default(float)。
    返り値: floatは対象玉の固定設定。
    """
    if value is None:
        return float(default)
    if isinstance(value, (int, float)):
        return float(value)
    return float(value[min(index, len(value)-1)]) if value else float(default)


def conditions(orders, times, bid, ask, valid, atr, market, config):
    """
    機能: 保存済み独自注文が当時の新支持・利益線・停止線を満たしたか照合する。
    引数: orders/times/bid/ask/valid/atr/market(ndarray)、config(dict)は保存素材。
    返り値: dictは根拠を確認した独自注文の件数。
    """
    normal = np.flatnonzero(valid & np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask > bid))
    totals = dict(add=0, recycle=0, trail=0, stop=0, next_normal=0)
    for pid in np.unique(orders[:, 2]) if len(orders) else []:
        parent = orders[orders[:, 2] == pid]
        entries = parent[parent[:, 7] == 1]
        if not len(entries) or int(entries[0, 8]) != 0:
            continue
        initial = entries[0]
        side = int(initial[3])
        risk = max(float(config.get('risk_floor', 20.)), atr[int(initial[1])])
        stages = len(config.get('increments', []))
        for order in parent:
            reason = int(order[6])
            if reason not in (901, 1391, 1392, 1393):
                continue
            fill, decision, uid = int(order[0]), int(order[1]), int(order[8])
            expected = int(normal[np.searchsorted(normal, decision, side='right')])
            assert fill == expected, ('次正常行以外の独自約定', pid, uid, fill, decision, expected)
            totals['next_normal'] += 1
            own = entries[entries[:, 8] == uid]
            assert len(own) == 1
            entry = own[0]
            mark = bid[decision] if side > 0 else ask[decision]
            if reason in (901, 1393):
                before = entries[entries[:, 0] < fill]
                anchor = times[int(before[-1, 0])]
                if reason == 1393:
                    profit_exits = parent[(parent[:, 6] == 1391) & (parent[:, 0] < fill)]
                    assert len(profit_exits)
                    anchor = max(anchor, times[int(profit_exits[-1, 0])])
                    assert times[decision]-times[int(profit_exits[-1, 0])] >= config.get('cooldown', 30.)
                    totals['recycle'] += 1
                else:
                    totals['add'] += 1
                    assert side*(mark-initial[5])+1e-8 >= config['steps'][uid-1]*risk
                assert times[decision]-times[int(initial[0])] >= config.get('min_after_initial', 30.)
                assert times[decision]-times[int(before[-1, 0])] >= config.get('add_min_gap', 0.)
                assert market[decision, 11] == 1. and market[decision, 8] > anchor
                assert side*market[decision, 4] >= .05 and side*market[decision, 6] >= .05
                assert side*market[decision, 5] >= .2 and side*market[decision, 7] >= .2
                since = decision
                for row in range(decision-1, int(before[-1, 0]), -1):
                    good = bool(valid[row] and np.isfinite(bid[row]) and np.isfinite(ask[row]) and 0 < bid[row] < ask[row])
                    support = good and market[row, 11] == 1. and market[row, 8] > anchor
                    support = support and side*market[row, 4] >= .05 and side*market[row, 6] >= .05
                    support = support and side*market[row, 5] >= .2 and side*market[row, 7] >= .2
                    support = support and times[row] >= times[int(initial[0])]+config.get('min_after_initial', 30.)
                    if not support or times[row+1]-times[row] > 15.:
                        break
                    since = row
                assert times[decision]-times[since]+1e-8 >= config.get('support_hold', 15.), ('支持持続が不足', pid, uid)
                continue
            move = side*(mark-entry[5])
            stop_width = expanded(config.get('stop_width'), uid, 0.)
            if reason == 1392:
                assert stop_width > 0 and move <= -stop_width*risk+1e-8
                totals['stop'] += 1
                continue
            sample = normal[(normal >= int(entry[0])) & (normal <= decision)]
            liquid = bid[sample] if side > 0 else ask[sample]
            moves = side*(liquid-entry[5])
            peaks = np.maximum.accumulate(moves)
            activation = expanded(config.get('exit_activation'), uid, 0.)
            width = expanded(config.get('exit_width'), uid, 1.)
            tighten_at = expanded(config.get('tighten_at'), uid, 0.)
            tight_width = expanded(config.get('tight_width'), uid, 1.)
            active = peaks >= activation*risk
            widths = np.full(len(peaks), width*risk)
            if tighten_at > 0:
                widths[peaks >= tighten_at*risk] = tight_width*risk
            floors = np.maximum.accumulate(np.where(active, peaks-widths, -np.inf))
            assert activation > 0 and active[-1] and move <= floors[-1]+1e-8, ('利益保護の根拠不足', pid, uid)
            assert not (stop_width > 0 and move <= -stop_width*risk), ('損切りの優先順位逆転', pid, uid)
            totals['trail'] += 1
    return totals


def read(path):
    """
    機能: 保存証跡をUTF-8で読み込む。
    引数: path(Path)はJSONの位置。
    返り値: dict/listは保存内容。
    """
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(path):
    """
    機能: 保存証跡の内容指紋を求める。
    引数: path(Path)は対象。
    返り値: strはSHA256。
    """
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def audit_stage(stage):
    """
    機能: 保存済み会計を読み、再売買を行わず全条件の独立会計と発注根拠を検査する。
    引数: stage(str)はresults又はextra_results。
    返り値: dictは全検査の件数と指紋。
    """
    sys.path.insert(0, str(HERE))
    from common139 import features129, product
    result = read(HERE/stage/'結果.json')
    planpath = ROOT/result['plan']['path']
    plan = read(planpath)
    assert digest(ROOT/result['plan']['path']) == result['plan']['sha256']
    for path, sha in plan['spec']['implementation'].items():
        assert digest(ROOT/path) == sha, path
    manifest = read(HERE/('manifest139.json' if stage == 'results' else 'manifest139_extra.json'))
    for item in plan['spec']['data']['input_manifests']:
        assert digest(ROOT/item['path']) == item['sha256']
    bykey = {(r['session'], r['symbol'], r['method']): r for r in result['rows']}
    configurations = {c['id']: c for c in plan['configs']}
    cache = {(c['session'], c['symbol']): c for c in result['cache']}
    counters = defaultdict(int)
    totals = defaultdict(lambda: dict(net=0., fees=0., entries=0, quantity=0, black=0, red=0, no_trade=0))
    for info in manifest['packets']:
        scene = info['session']
        assert digest(info['path']) == info['sha256']
        packet = pickle.loads(Path(info['path']).read_bytes())
        prepared = features129.prices_for(packet, 'mid')
        markets = features129.markets(prepared)
        for symbol in ('NK225', 'TOPIX'):
            entry = cache[(scene, symbol)]
            assert digest(ROOT/entry['path']) == entry['sha256']
            ready = prepared[(scene, symbol)]
            quotes = packet['quotes'][(scene, symbol)]
            market = markets[(scene, symbol)]
            setting = product(symbol)
            with np.load(ROOT/entry['path'], allow_pickle=False) as arrays:
                assert set(arrays.files) == set(configurations)
                for method, config in configurations.items():
                    orders = arrays[method]
                    saved = bykey[(scene, symbol, method)]
                    independent = ledger(orders, ready['time_s'], quotes['bid'], quotes['ask'], quotes['quote_valid'],
                                         setting['fee_tenths'], setting['multiplier'])
                    counters['account_fields'] += compare(saved, independent)
                    merged = dict(config, **setting)
                    facts = conditions(orders, ready['time_s'], quotes['bid'], quotes['ask'], quotes['quote_valid'],
                                       ready['atr'], market, merged)
                    for name, value in facts.items():
                        counters['condition_'+name] += value
                    counters['accounts'] += 1
                    counters['orders'] += len(orders)
                    counters['uids'] += independent['uids']
                    total = totals[symbol+'_'+method]
                    for name in ('net', 'fees', 'entries', 'quantity'):
                        total[name] += independent[name]
                    total['black'] += independent['net'] > 0
                    total['red'] += independent['net'] < 0
                    total['no_trade'] += independent['entries'] == 0
        print(scene, '独立会計確認', flush=True)
    outcome = dict(status='合格', stage=stage, counters=dict(counters), totals=dict(totals),
                   input_sha256=digest(HERE/stage/'結果.json'), plan_sha256=digest(planpath),
                   audit_sha256=digest(Path(__file__)), financial_replays=0,
                   scope='保存注文の会計・上限・全返済・次気配・独自注文の当時根拠。未知データ有効性や実mini約定の保証ではない。')
    target = HERE/('金融独立監査_追加.json' if stage == 'extra_results' else '金融独立監査.json')
    target.write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(status='合格', **dict(counters)), ensure_ascii=False))
    return outcome


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('results', 'extra_results'))
    audit_stage(parser.parse_args().stage)
