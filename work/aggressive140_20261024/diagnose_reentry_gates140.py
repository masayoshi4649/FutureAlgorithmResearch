"""R01と同じ売買判断に観測カウンタだけを加え、保存約定との一致を確認する。"""

import importlib.util
import json
import pickle
import re
import sys
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'work/tranche139_20261022'))
import common139

FIELDS = ['準備原行', '起点親', '準備中原行数', '押戻り後原行数', '反発距離成立原行数',
          '支持成立原行数', '反発と支持成立原行数', 'そのうち追掛け価格超過', 'そのうち気配幅超過',
          'そのうち休止中', '全条件合致原行数', '持続時間不足原行数', '発注数']


def instrument():
    """
    機能: 売買分岐を変えず、現在までの条件成立回数だけを数える診断用写しを作る。
    引数: なし。
    返り値: moduleは同一条件のreplay関数と診断カウンタを持つ。
    """
    source = (HERE / 'reentry140.py').read_text(encoding='utf-8')
    source = source.replace('    oc = nc = dp = fp = 0\n',
                            '    oc = nc = dp = fp = 0\n    gate = np.zeros((npart*(maximum+1)+16, 13), np.int64)\n    episode = -1\n')
    pattern = r'(?m)^( +)nc = _note\(notes, nc, i, 4, ([^\n]+)\)\n'
    matches = list(re.finditer(pattern, source))
    assert len(matches) == 2
    source = re.sub(pattern, lambda m: m.group(0) + m.group(1) + 'episode += 1\n' + m.group(1) +
                    'gate[episode, 0] = i\n' + m.group(1) + 'gate[episode, 1] = origin\n', source)
    mark = '        if now >= end - cutoff or now - arm_time > expiry:\n'
    assert source.count(mark) == 1
    source = source.replace(mark, '        gate[episode, 2] += 1\n' + mark)
    mark = '        if now - arm_time < cooldown or not quality:\n'
    assert source.count(mark) == 1
    code = '''        observed_known = market[i, 11] == 1. and np.isfinite(market[i, 4:9]).all()
        observed_known = observed_known and arm_time < market[i, 8] < now and now - market[i, 8] <= maxgap
        observed_support = observed_known and side*market[i, 4] >= support30 and side*market[i, 6] >= support30
        observed_support = observed_support and side*market[i, 5] >= support120 and side*market[i, 7] >= support120
        observed_bounce = stage == 1 and i > return_row and z-return_extreme >= bounce*setup_risk
        gate[episode, 3] += int(stage == 1)
        gate[episode, 4] += int(observed_bounce)
        gate[episode, 5] += int(observed_support)
        if observed_bounce and observed_support:
            gate[episode, 6] += 1
            gate[episode, 7] += int(side*quoted > anchor+maxchase*setup_risk)
            gate[episode, 8] += int(ask[i]-bid[i] > spread_limit*current_risk)
            gate[episode, 9] += int(now-arm_time < cooldown)
            gate[episode, 10] += int(quality and now-arm_time >= cooldown)
'''
    source = source.replace(mark, code + mark)
    mark = '                trigger = now - since >= support_hold\n'
    assert source.count(mark) == 1
    source = source.replace(mark, mark + '                gate[episode, 11] += int(not trigger)\n')
    mark = '        if trigger:\n            total_reentries += 1\n'
    assert source.count(mark) == 1
    source = source.replace(mark, '        if trigger:\n            gate[episode, 12] += 1\n            total_reentries += 1\n')
    source = source.replace('return orders[:oc], notes[:nc]', 'return orders[:oc], notes[:nc], gate[:episode+1]')
    source = source.replace('orders, events = _run(', 'orders, events, gate = _run(')
    source = source.replace('return orders, dict(config=cfg,', 'return orders, dict(gate_counts=gate, config=cfg,')
    generated = HERE / 'reentry_gate_diagnostic140.py'
    generated.write_text(source, encoding='utf-8')
    spec = importlib.util.spec_from_file_location('reentry_gate_diagnostic140', generated)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    """
    機能: 旧47場R01を同じ条件で診断再実行し、出力が保存済み約定と全行一致することを確認する。
    引数: なし。
    返り値: None。新条件探索は行わず、原行の頻度を独立試行の確率に読み替えない。
    """
    read = lambda p: json.loads(Path(p).read_text(encoding='utf-8-sig'))
    model = instrument()
    results = read(HERE / 'known/結果140.json')
    cache = {(x['symbol'], x['session']): ROOT / x['path'] for x in results['cache']}
    manifest = read(HERE / 'known_manifest140.json')
    records = []
    for item in manifest['packets']:
        packet = pickle.loads((ROOT / item['path']).read_bytes())
        scene = packet['session']
        inputs = common139.features129.prices_for(packet, 'mid')
        markets = common139.features129.markets(inputs)
        for symbol in ('NK225', 'TOPIX'):
            ready = packet['inputs'][scene, symbol]
            with np.load(cache[symbol, scene]) as f:
                base, expected = f['B5'], f['R01']
            cfg = model.defaults()
            cfg.update(common139.product(symbol))
            orders, diag = model.replay(ready['time_s'], packet['quotes'][scene, symbol], ready['atr'],
                                        markets[scene, symbol], base, ready['limit'], cfg)
            assert np.array_equal(orders, expected), (symbol, scene, '診断追加で約定が変化しました')
            events = diag['gate_counts']
            for event in events:
                if event[12]:
                    status = '実新規あり'
                elif event[3] == 0:
                    status = '新しい押戻りが無い'
                elif event[4] == 0:
                    status = '押戻り後の反発距離が不足'
                elif event[6] == 0:
                    status = '反発と二市場支持が同時成立しない'
                elif event[10] == 0:
                    status = '反発支持時に価格か気配か休止条件が不合格'
                else:
                    status = '全条件が一時成立しても15秒持続しない'
                records.append(dict(symbol=symbol, session=scene, status=status,
                                    counts={label: int(value) for label, value in zip(FIELDS, event)}))
        print(scene, 'R01同値診断済み', flush=True)
    summary = {}
    for symbol in ('NK225', 'TOPIX'):
        items = [x for x in records if x['symbol'] == symbol]
        reasons = {s: sum(x['status'] == s for x in items) for s in sorted({x['status'] for x in items})}
        summary[symbol] = dict(準備数=len(items), 終点の分類=reasons,
                              反発支持が揃ったが追掛け超過のある準備数=sum(x['counts'][FIELDS[7]] > 0 for x in items),
                              全条件が一度以上合致した準備数=sum(x['counts'][FIELDS[10]] > 0 for x in items))
    out = dict(目的='R01保存注文の同値診断。新条件・新しい有効性の証拠ではない。',
               注意='原行数は市場更新頻度に依存し、独立標本や取引正答率ではない。', summary=summary, records=records)
    (HERE / 'R01参加制約の同値診断140.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
