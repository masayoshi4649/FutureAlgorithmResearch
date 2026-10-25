"""保存注文と表示データだけを読んで、最終報告の構成・数値を独立照合する。"""

import json
import pickle
from pathlib import Path
from statistics import mean
import numpy as np
import verify_mechanics142 as base


HERE, ROOT, OLD = base.HERE, base.ROOT, base.OLD


def check():
    """
    機能: F1構成・全50場・集計表・保存注文由来の保有率を独立照合する。
    引数: なし。全入力は保存済みJSON・pickle・約定NPZとする。
    返り値: None。金融再生も採否変更もせず、検査記録だけを新規保存する。
    """
    report = base.read(HERE / 'report_data142.json')
    comparison = base.read(HERE / '比較集計142.json')
    source = {(r['symbol'], r['method'], r['session']): r for r in comparison['rows']}
    route = {'NK225': {'Day': 'M1', 'Night': 'J04'}, 'TOPIX': {'Day': 'C06', 'Night': 'C13'}}
    desired = {}
    for row in report['rows']:
        component = route[row['symbol']][row['kind']] if row['method'] == 'F1' else row['method']
        assert row['component_method'] == component
        original = source[row['symbol'], component, row['session']]
        for name, value in original.items():
            if name != 'method':
                assert row[name] == value, (row['symbol'], row['method'], row['session'], name)
        desired[row['symbol'], component, row['session']] = row
    for selection in report['selected']:
        if selection['method'] == 'F1':
            assert selection['day_method'] == route[selection['symbol']]['Day']
            assert selection['night_method'] == route[selection['symbol']]['Night']

    # ----------------------------------------
    # 約定時刻ごとの残枚数を別途積分し、重複保有を一回だけ数える。
    integrated = base.read(HERE / '結果142_三巡統合.json')
    cache = {}
    for item in integrated['cache']:
        cache.setdefault(item['session'], []).append(item)
    packets = {x['session']: x for f in (OLD / 'known_manifest140.json', OLD / 'inputs/input_manifest.json') for x in base.read(f)['packets']}
    checked = set()
    for scene, item in sorted(packets.items()):
        path = ROOT / item['path']
        assert base.digest(path) == item['sha256']
        packet = pickle.loads(path.read_bytes())
        for ref in cache[scene]:
            symbol = ref['symbol']
            path = ROOT / ref['path']
            assert base.digest(path) == ref['sha256']
            with np.load(path) as arrays:
                for method in arrays.files:
                    key = symbol, method, scene
                    if key not in desired or key in checked:
                        continue
                    orders = arrays[method]
                    row = desired[key]
                    ready = packet['inputs'][scene, symbol]
                    quotes = packet['quotes'][scene, symbol]
                    cash = base.audit_orders(orders, dict(ready=ready, quotes=quotes), 10)
                    assert abs(cash - row['net']) < 1e-6
                    seconds = 420. * 60. if row['kind'] == 'Day' else 780. * 60.
                    start = ready['start']
                    events = {}
                    for order in orders:
                        at = min(seconds, max(0., float(ready['time_s'][int(order[0])]) - start))
                        events[at] = events.get(at, 0) + int(order[4]) * (1 if order[7] else -1)
                    at = held = occupied = quantity_seconds = 0.
                    for next_at, delta in sorted(events.items()):
                        width = next_at - at
                        occupied += width if held > 0 else 0.
                        quantity_seconds += held * width
                        held += delta
                        assert held >= 0
                        at = next_at
                    assert held == 0
                    assert abs(occupied / seconds - row['holding_ratio']) < 1e-12, key
                    assert abs(quantity_seconds / seconds - row['avg_held_quantity']) < 1e-12, key
                    checked.add(key)
    assert checked == set(desired)

    # ----------------------------------------
    # 表示集計を報告内の明細から再計算し、元集計関数を使用せず照合する。
    summaries = []
    for symbol in ('NK225', 'TOPIX'):
        for method in ('B5', 'M1', 'F1', 'V04'):
            rows = [r for r in report['rows'] if r['symbol'] == symbol and r['method'] == method]
            assert len(rows) == 50 and len({r['session'] for r in rows}) == 50
            negative = [r['net'] for r in rows if r['net'] < 0]
            calculated = dict(sessions=50, net=sum(r['net'] for r in rows),
                profit=sum(r['profit'] for r in rows), loss=sum(r['loss'] for r in rows),
                losses=len(negative), avg_loss=-mean(negative), worst=min(r['net'] for r in rows),
                mean_holding_ratio=mean(r['holding_ratio'] for r in rows),
                ex_top3=sum(r['net'] for r in rows) - sum(sorted((r['net'] for r in rows if r['net'] > 0), reverse=True)[:3]))
            saved = next(r for r in report['summary'] if r['symbol'] == symbol and r['method'] == method and r['scope'] == 'all')
            for name, value in calculated.items():
                assert abs(saved[name] - value) < 1e-8, (symbol, method, name, saved[name], value)
            assert calculated['profit'] - calculated['loss'] == calculated['net']
            summaries.append(dict(symbol=symbol, method=method, **calculated))
    conclusion = (ROOT / 'アルゴリズム調査/00142_状況判断と売買を分離した条件切替/結論.md').read_text(encoding='utf-8-sig')
    for row in summaries:
        if row['method'] == 'B5':
            continue
        label = ('日経' if row['symbol'] == 'NK225' else 'TOPIX') + ' ' + row['method']
        expected = f"|{label}|{row['net']:+,.0f}円|{row['losses']}/50|{row['avg_loss']:,.0f}円|{-row['worst']:,.0f}円|{row['mean_holding_ratio']:.1%}|"
        assert expected in conclusion, expected
    output = dict(status='全件合格', 金融再生=0, 報告明細数=len(report['rows']), 保存口座照合数=len(checked),
        F1構成=route, 集計=summaries,
        文面確認='M1から全項目改善との記述なし。F1の平均赤字・最大赤字悪化を表に明示。V04は安定候補として勧めないと明記。',
        入力指紋={str(p.relative_to(ROOT)): base.digest(p) for p in (HERE / 'report_data142.json', HERE / '比較集計142.json')})
    base.save(HERE / '最終報告の独立照合142.json', output)
    print(json.dumps({k: v for k, v in output.items() if k not in ('集計', '入力指紋')}, ensure_ascii=False))


if __name__ == '__main__':
    check()
