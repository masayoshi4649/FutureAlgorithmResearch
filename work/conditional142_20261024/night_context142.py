"""既に保存された補完の判断原行について、5夜の時間軸と複合経路を非金融比較する。"""

import json
import pickle
import sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREV = ROOT/'work/raw_diagnosis141_20261024'
OLD = ROOT/'work/aggressive140_20261024'
sys.path.insert(0, str(OLD))
sys.path.insert(0, str(PREV))
import run140_v2 as prior
import active140_v2 as active
import evidence141_v2 as evidence
from implementation_audit141 import stamp, clean
import night_selector142 as selector


def main():
    """
    機能: 過去に保存したB5補完の判断時点だけを取り出し、新判定の根拠を記録する。
    引数: なし。
    返り値: None。注文生成・損益計算・金融再生は行わない。
    """
    packets = prior.read(OLD/'known_manifest140.json')['packets']+prior.read(OLD/'inputs/input_manifest.json')['packets']
    records = []
    for scene in ('2026-09-28_Night', '2026-09-29_Night', '2026-10-21_Night',
                  '2026-10-22_Night', '2026-10-23_Night'):
        item = next(p for p in packets if p['session'] == scene)
        packet = pickle.loads((ROOT/item['path']).read_bytes())
        inputs, market, history, _ = prior.common.features129.build(packet, 'mid', 0.)
        prepared = evidence.attach(packet, active.prepare(packet, 40))
        key = scene, 'NK225'
        ready, quote = inputs[key], packet['quotes'][key]
        with np.load(PREV/'results/measurement'/f'NK225_{scene}.npz') as z:
            old = z['B5']
        entry = old[(old[:, 8] == 999)&(old[:, 7] == 1)][0]
        i = int(entry[1])
        h, m, raw = history[key][i], market[key][i], prepared['NK225']['features'][i, 24:28]
        mid = (quote['bid'][i]+quote['ask'][i])*.5
        risk = max(ready['atr'][i], .5*(h[3]-h[4]), 8.*ready['tick'])
        choices = []
        for config in selector.configurations():
            route, side, reason = selector.entry_policy(h, m, mid, risk, ready['tick'], raw, config['selector_mode'])
            allowed, readiness = selector.entry_ready(h, m, mid, raw, config['selector_mode'], route, side)
            choices.append(dict(method=config['id'], route=route, route_name=selector.ROUTES[route],
                side=side, reason=selector.REASONS[reason], ready=allowed,
                readiness=selector.REASONS[readiness]))
        records.append(dict(session=scene, decision_row=i, seq=int(ready['seq'][i]),
            clock=stamp(ready['time_s'][i]), baseline_side=int(entry[3]), mid=mid, risk=risk,
            mean5=h[0], mean20=h[1], own5=h[6], peer5=h[10], own20=h[7], peer20=h[11],
            own_from_open=mid-h[8], peer_from_open=h[13],
            own30=m[4], own120=m[5], peer30=m[6], peer120=m[7],
            raw_ofi_own=raw[0], raw_ofi_peer=raw[2], peer_valid=m[11], choices=choices))
    value = dict(financial_replays=0, new_orders=0, API=0, records=records,
        limitation='既知5場の保存判断行を確認しただけで、全場の収益性の証拠ではない。価格時計上の厳密過去接続であり受信同期を保証しない。')
    with (HERE/'夜間5場の初回判定根拠142.json').open('x', encoding='utf-8') as stream:
        json.dump(clean(value), stream, ensure_ascii=False, indent=2, allow_nan=False)
    for record in records:
        print(record['session'], '旧方向', record['baseline_side'],
              [(r['method'],r['route'],r['side'],r['ready']) for r in record['choices']], flush=True)


if __name__ == '__main__':
    main()
