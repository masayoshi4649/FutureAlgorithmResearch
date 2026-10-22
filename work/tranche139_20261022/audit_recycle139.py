"""保存済み再追加注文を独立会計し、利益枚数の信用・消費・上限を監査する。"""

from collections import defaultdict
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
JST = timezone(timedelta(hours=9))


def read(path):
    """
    機能: 保存JSONを読み取る。
    引数: path(Path)は所在。
    返り値: dict又はlistは記録。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def checked(ref):
    """
    機能: 記録された指紋と実ファイルを照合する。
    引数: ref(dict)はpathとsha256。
    返り値: Pathは照合済みの絶対位置。
    """
    path = ROOT / ref['path']
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    assert actual == ref['sha256'], path
    return path


def originals(scene, symbol, known, extra, generated):
    """
    機能: 当該商品の保存元主担当を目録の指紋付きで読む。
    引数: scene/symbol(str)、known/extra/generated(list[dict])は検索目録。
    返り値: ndarrayは既に生成済みの12列元通知。金融核を実行しない。
    """
    found = next((x for x in known if x['session'] == scene and x['symbol'] == symbol), None)
    if found:
        path = checked(found['orders'])
        prefix = '' if found['prefix'] == 'なし' else found['prefix']
    else:
        found = next((x for x in extra + generated if x['session'] == scene and x['symbol'] == symbol), None)
        assert found is not None, (scene, symbol)
        path, prefix = checked(found), ''
    with np.load(path, allow_pickle=False) as data:
        return data[prefix + 'core_orders'].copy()


def inspect(orders, original, quotes, times, cfg, symbol):
    """
    機能: 約定列だけから玉別損益と補充信用を復元し、初回残存と親終端を照合する。
    引数: orders/original/times(ndarray)、quotes/cfg(dict)、symbol(str)は保存注文と入力。
    返り値: tuple[dict,list[dict]]は会計と監査イベント。独立の現金収支でも照合する。
    """
    fee, multiplier = (385, 100.) if symbol == 'NK225' else (418, 1000.)
    terminal = {int(pid): int(original[original[:, 2] == pid][-1, 0]) for pid in np.unique(original[:, 2])}
    tickets = {}
    parents = {}
    credit = defaultdict(int)
    cycles = defaultdict(int)
    held = {1: 0, -1: 0}
    parentheld = defaultdict(int)
    events = []
    netcash = 0.
    maximum = entries = totalquantity = 0
    for order in orders:
        i, decision, pid, side, quantity = map(int, order[:5])
        px, reason = float(order[5]), int(order[6])
        new, uid, paid = map(int, order[7:10])
        assert 0 <= decision < i < len(times)
        assert quotes['quote_valid'][i] and abs(px - quotes['ask' if side > 0 else 'bid'][i]) < 1e-8
        assert paid == quantity * fee // 10 and quantity > 0
        key = pid, uid
        parent = parents.setdefault(pid, dict(gross=0., fees=0., side=side))
        parent['fees'] += paid
        netcash -= side * px * quantity * multiplier + paid
        stamp = datetime.fromtimestamp(float(times[i]), JST).isoformat()
        if new:
            assert key not in tickets, '同じUIDを再利用'
            if reason == 1393:
                assert pid in terminal and i < terminal[pid], '元親終端後の補充'
                assert tickets[(pid, 0)]['quantity'] > 0, '初回玉消滅後の補充'
                assert credit[pid] >= quantity, '実現利益枚数以上の補充'
                before = credit[pid]
                credit[pid] -= quantity
                cycles[pid] += 1
                assert cycles[pid] <= cfg['recycle_rounds']
                events.append(dict(parent=pid, uid=uid, time=stamp, event='補充約定で信用消費', quantity=quantity,
                                   credit_before=before, credit_after=credit[pid], cycles=cycles[pid]))
            tickets[key] = dict(quantity=quantity, entry=px, side=side, fee_remaining=paid)
            held[side] += quantity
            parentheld[pid] += quantity
            entries += 1
            totalquantity += quantity
        else:
            ticket = tickets[key]
            assert ticket['quantity'] >= quantity and ticket['side'] == -side
            allocated = ticket['fee_remaining'] * quantity // ticket['quantity']
            ticket['fee_remaining'] -= allocated
            gain = ticket['side'] * (px - ticket['entry']) * quantity * multiplier
            closed_net = gain - allocated - paid
            parent['gross'] += gain
            ticket['quantity'] -= quantity
            held[-side] -= quantity
            parentheld[pid] -= quantity
            if uid > 0 and uid != 999 and pid in terminal and i < terminal[pid] and closed_net > 0.:
                before = credit[pid]
                credit[pid] += quantity
                events.append(dict(parent=pid, uid=uid, time=stamp, event='実現利益返済で信用発生', quantity=quantity,
                                   net=closed_net, allocated_entry_fee=allocated, exit_fee=paid,
                                   credit_before=before, credit_after=credit[pid], remaining=ticket['quantity']))
        assert 0 <= parentheld[pid] <= cfg['target']
        assert all(0 <= value <= 10 for value in held.values())
        maximum = max(maximum, *held.values())
    assert not any(held.values()) and all(x['quantity'] == x['fee_remaining'] == 0 for x in tickets.values())
    gains = [v['gross'] - v['fees'] for v in parents.values()]
    profit = sum(v for v in gains if v > 0.)
    loss = -sum(v for v in gains if v < 0.)
    assert abs(profit - loss - netcash) < 1e-5
    return dict(profit=profit, loss=loss, net=profit-loss, gross=sum(v['gross'] for v in parents.values()),
                fees=sum(v['fees'] for v in parents.values()), entries=entries, quantity=totalquantity,
                max_per_side=maximum, recycle_entries=sum(cycles.values())), events


def main():
    """
    機能: 保存済み8条件・全47場の金融結果を再生せず会計監査する。
    引数: なし。
    返り値: None。別の独立監査JSONを新規保存する。
    """
    result = read(HERE / 'recycle_results/結果.json')
    plan = read(checked(result['plan']))
    configurations = {c['id']: c for c in plan['configs']}
    known = read(HERE / 'manifest139.json')
    extra = read(HERE / 'manifest139_extra.json')
    generated = read(HERE / 'extra_results/結果.json')['generated']
    paths = {p['session']: p for p in known['packets'] + extra['packets']}
    cached = {(c['session'], c['symbol']): c for c in result['cache']}
    original_rows = {(r['session'], r['symbol'], r['method']): r for r in result['rows']}
    verified = []
    details = []
    for scene, inputref in paths.items():
        with checked(inputref).open('rb') as stream:
            packet = pickle.load(stream)
        for symbol in ('NK225', 'TOPIX'):
            ready, quotes = packet['inputs'][(scene, symbol)], packet['quotes'][(scene, symbol)]
            source = originals(scene, symbol, known['references'], extra['existing_orders'], generated)
            with np.load(checked(cached[(scene, symbol)]), allow_pickle=False) as arrays:
                for method, cfg in configurations.items():
                    account, evidence = inspect(arrays[method], source, quotes, ready['time_s'], cfg, symbol)
                    expected = original_rows[(scene, symbol, method)]
                    for field, value in account.items():
                        assert abs(value - expected[field]) < 1e-5, (scene, symbol, method, field, value, expected[field])
                    verified.append(dict(session=scene, symbol=symbol, method=method, **account))
                    details.extend(dict(session=scene, symbol=symbol, method=method, **event) for event in evidence)
        print(scene + ' 独立信用会計監査完了', flush=True)
    out = dict(passed=True, accounts=len(verified), rows=verified, credit_events=details,
               checks=['価格・方向・手数料・注文単位切捨て', '新規費用残の比例配賦と全消費',
                       '親・UID別の独立損益と現金収支', '費用後プラス返済だけを一度だけ信用化',
                       '約定時だけ信用消費・残存信用非負', '再追加回数上限・初回玉残存・親終端優先',
                       '親targetと口座片方向10枚の上限・最終全返済'],
               financial_replays=0, API=0, real_orders=0,
               limitation='保存約定と元親終端による独立検算。入口支持の条件式を再実行した優位性評価ではない。')
    with (HERE / 'recycle_financial_audit139.json').open('x', encoding='utf-8') as stream:
        json.dump(out, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print('独立監査合格: ' + str(len(verified)) + '会計', flush=True)


if __name__ == '__main__':
    main()
