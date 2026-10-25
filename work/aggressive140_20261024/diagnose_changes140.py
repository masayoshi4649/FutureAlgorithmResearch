"""保存済み約定だけから、改善と悪化を追加親・見送り親へ分解する。"""

import json
import pickle
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TARGETS = [('NK225', 'C28'), ('NK225', 'C36'), ('NK225', 'R02'),
           ('TOPIX', 'C33'), ('TOPIX', 'C32'), ('NK225', 'C33')]


def read(path):
    """
    機能: 保存資料のJSONを読む。
    引数: path(Path)は位置。
    返り値: dict/listは内容。
    """
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def parents(orders, symbol, times=None):
    """
    機能: 十列約定を玉原価から親単位へ独立会計し、最初と最後の価格・時刻を記録する。
    引数: orders(ndarray)、symbol(str)、times(ndarray/None)は約定と原行時計。
    返り値: dict[int,dict]は親別収支と売買経路。売買判断は実行しない。
    """
    multiplier = 100. if symbol == 'NK225' else 1000.
    out = {}
    tickets = {}
    for o in orders:
        row, source, pid, side, qty = map(int, o[:5])
        new, uid, fee = map(int, o[7:])
        p = out.setdefault(pid, dict(parent=pid, side=side, net=0., fee=0, quantity=0,
                                    entry_row=row, entry_source=source, exit_row=row, orders=[]))
        p['net'] -= fee
        p['fee'] += fee
        p['exit_row'] = row
        key = pid, uid
        if new:
            assert key not in tickets
            tickets[key] = [qty, side, float(o[5])]
            p['quantity'] += qty
        else:
            q, d, entry = tickets[key]
            assert q >= qty and d == -side
            p['net'] += d * (o[5] - entry) * qty * multiplier
            tickets[key][0] -= qty
        rec = dict(row=row, source=source, side=side, quantity=qty, price=float(o[5]),
                   new=bool(new), uid=uid, reason=int(o[6]))
        if times is not None:
            rec['time'] = datetime.fromtimestamp(float(times[row]), ZoneInfo('Asia/Tokyo')).strftime('%H:%M:%S')
            rec['source_time'] = datetime.fromtimestamp(float(times[source]), ZoneInfo('Asia/Tokyo')).strftime('%H:%M:%S')
        p['orders'].append(rec)
    assert all(q == 0 for q, _, _ in tickets.values())
    return out


def main():
    """
    機能: 各比較の増減最大三場と、全期間の追加/見送り寄与を保存する。
    引数: なし。
    返り値: None。新しい金融再生は行わない。
    """
    saved = read(HERE / 'known/結果140.json')
    rows = {(r['symbol'], r['method'], r['session']): r for r in saved['rows']}
    sessions = sorted({r['session'] for r in saved['rows']})
    cache = {(r['symbol'], r['session']): ROOT / r['path'] for r in saved['cache']}
    inputs = {r['session']: ROOT / r['path'] for r in read(HERE / 'known_manifest140.json')['packets']}
    rankings = {}
    required = set()
    for symbol, method in TARGETS:
        ranked = sorted([(rows[symbol, method, s]['net'] - rows[symbol, 'B5', s]['net'], s) for s in sessions])
        rankings[symbol, method] = [('改善', x) for x in ranked[-3:][::-1]] + [('悪化', x) for x in ranked[:3]]
        required.update(s for _, (_, s) in rankings[symbol, method])
    times = {}
    for scene in required:
        packet = pickle.loads(inputs[scene].read_bytes())
        for symbol in ('NK225', 'TOPIX'):
            times[symbol, scene] = packet['inputs'][scene, symbol]['time_s']
    summary = []
    details = []
    for symbol, method in TARGETS:
        total = dict(symbol=symbol, method=method, added_count=0, removed_count=0,
                     added_net=0., removed_net=0., kept_count=0, unchanged_sessions=0)
        top = {s: (label, change) for label, (change, s) in rankings[symbol, method]}
        for scene in sessions:
            with np.load(cache[symbol, scene]) as f:
                base, proposed = f['B5'], f[method]
            clock = times.get((symbol, scene))
            b, p = parents(base, symbol, clock), parents(proposed, symbol, clock)
            removed = sorted(set(b) - set(p))
            added = sorted(set(p) - set(b))
            kept = sorted(set(b) & set(p))
            for pid in kept:
                assert np.array_equal(base[base[:, 2] == pid], proposed[proposed[:, 2] == pid])
            an, rn = sum(p[x]['net'] for x in added), sum(b[x]['net'] for x in removed)
            diff = rows[symbol, method, scene]['net'] - rows[symbol, 'B5', scene]['net']
            assert abs(an - rn - diff) < 1.e-6
            total['added_count'] += len(added)
            total['removed_count'] += len(removed)
            total['kept_count'] += len(kept)
            total['added_net'] += an
            total['removed_net'] += rn
            total['unchanged_sessions'] += int(not added and not removed)
            if scene in top:
                label, _ = top[scene]
                contributions = [dict(role='追加', contribution=p[x]['net'], **p[x]) for x in added]
                contributions += [dict(role='旧取引を見送り', contribution=-b[x]['net'], **b[x]) for x in removed]
                contributions.sort(key=lambda x: abs(x['contribution']), reverse=True)
                details.append(dict(symbol=symbol, method=method, session=scene, change_type=label,
                    baseline_net=rows[symbol, 'B5', scene]['net'], net=rows[symbol, method, scene]['net'],
                    difference=diff, baseline_parents=len(b), proposed_parents=len(p), added_count=len(added),
                    removed_count=len(removed), added_net=an, removed_net=rn, contributions=contributions))
        total['difference'] = total['added_net'] - total['removed_net']
        summary.append(total)
    report = dict(対象='既知47場の保存結果。R12はラベル不備のため不使用。',
                  新金融再生=0, summary=summary, sessions=details)
    (HERE / '増減最大三場と親寄与140.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 保存約定から見た増減の内訳', '', '既知47場の派生集計。新金融再生0。R12は不使用。', '',
             '|商品|案|追加親|追加収支|見送った旧親|その旧収支|差引変化|', '|---|---|---:|---:|---:|---:|---:|']
    for s in summary:
        lines.append(f"|{s['symbol']}|{s['method']}|{s['added_count']}|{s['added_net']:+,.0f}|{s['removed_count']}|{s['removed_net']:+,.0f}|{s['difference']:+,.0f}|")
    for item in details:
        lines += ['', f"## {item['symbol']} {item['method']} {item['session']}（{item['change_type']}）", '',
                  f"B5 {item['baseline_net']:+,.0f}円 → {item['net']:+,.0f}円、差 {item['difference']:+,.0f}円。親数 {item['baseline_parents']}→{item['proposed_parents']}。追加 {item['added_count']}親 {item['added_net']:+,.0f}円、旧 {item['removed_count']}親 {item['removed_net']:+,.0f}円を見送り。", '',
                  '|変更|方向|新規→最終返済|建値→返済値|新規枚数|その親収支|差への寄与|', '|---|---|---|---|---:|---:|---:|']
        for p in item['contributions'][:4]:
            first, last = p['orders'][0], p['orders'][-1]
            lines.append(f"|{p['role']}|{'買' if p['side']>0 else '売'}|{first['time']}→{last['time']}|{first['price']:g}→{last['price']:g}|{p['quantity']}|{p['net']:+,.0f}|{p['contribution']:+,.0f}|")
    (HERE / '増減最大三場の具体売買140.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
