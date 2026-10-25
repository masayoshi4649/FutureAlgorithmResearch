"""夜間Z04/Z05の差の集中と未改善の損失を、保存注文から原板へ追跡する。"""

import json
import pickle
import sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREV = ROOT/'work/raw_diagnosis141_20261024'
sys.path.insert(0, str(PREV))
from supplement_loss_audit141 import parent_record, cash
from implementation_audit141 import stamp
from loss_raw141 import clean
import run142


def main():
    """
    機能: 夜間25場の保存差を確定し、対照5場・改善1場・絶対赤字3場を原文へ接続する。
    引数: なし。
    返り値: None。金融再生はせず、既存約定の監査資料だけを新規作成する。
    """
    prior = run142.prior
    saved = prior.read(HERE/'結果142.json')
    rows = [r for r in saved['rows'] if r['symbol'] == 'NK225' and r['kind'] == 'Night']
    by = {(r['session'], r['method']):r for r in rows}
    scenes = sorted({r['session'] for r in rows})
    delta = []
    for scene in scenes:
        with np.load(HERE/'measurement'/f'NK225_{scene}.npz') as z:
            methods = {m:z[m].copy() for m in ('B5','Z04','Z05')}
        row = dict(session=scene)
        for method, orders in methods.items():
            core, extra = orders[orders[:,8] != 999], orders[orders[:,8] == 999]
            assert cash(orders) == by[scene,method]['net']
            row[method] = dict(net=cash(orders), core=cash(core), supplement=cash(extra),
                difference=cash(orders)-by[scene,'B5']['net'],
                core_unchanged=bool(np.array_equal(core,methods['B5'][methods['B5'][:,8] != 999])))
        delta.append(row)
    worst = sorted(scenes, key=lambda s:by[s,'Z04']['net'])[:3]
    targets = sorted(set(worst+['2026-09-28_Night','2026-09-29_Night','2026-10-14_Night',
                                '2026-10-21_Night','2026-10-22_Night','2026-10-23_Night']))
    packets, unused, unused2 = run142.first.material()
    records = []
    for scene in targets:
        item = next(p for p in packets if p['session'] == scene)
        packet = pickle.loads((ROOT/item['path']).read_bytes())
        data, inputs, markets, histories = run142.prepared(packet)
        key, peer = (scene,'NK225'), (scene,'TOPIX')
        rawsets = {}
        for symbol in ('NK225','TOPIX'):
            with np.load(PREV/'raw_features'/f'{symbol}_{scene}.npz') as z:
                rawsets[symbol] = {k:z[k] for k in z.files}
        result = dict(session=scene, methods={})
        with np.load(HERE/'measurement'/f'NK225_{scene}.npz') as z:
            for method in ('B5','Z04','Z05'):
                parents = []
                orders = z[method]
                for pid in np.unique(orders[:,2]):
                    selected = orders[orders[:,2] == pid]
                    parent = parent_record(selected,inputs[key],packet['quotes'][key],histories[key],markets[key],
                        rawsets['NK225'],inputs[peer],rawsets['TOPIX'])
                    for order in parent['orders']:
                        row = order['decision']['row']
                        order['decision']['mean5'] = float(histories[key][row,0])
                        order['decision']['mean20'] = float(histories[key][row,1])
                        order['decision']['ofi_own_used'] = float(data['NK225']['features'][row,24])
                        order['decision']['ofi_peer_used'] = float(data['NK225']['features'][row,26])
                    parents.append(parent)
                notes = [] if method == 'B5' else prior.read(HERE/'notes'/f'NK225_{scene}_{method}.json')
                for note in notes:
                    note['価格時計表示'] = stamp(note['価格時計'])
                result['methods'][method] = dict(parents=parents, notes=notes)
        records.append(result)
        print(scene, '保存約定を原文へ接続', flush=True)
    value = dict(financial_replays=0, API=0, real_orders=0, deltas=delta,
        degradation_sessions={m:[r['session'] for r in delta if r[m]['difference']<0] for m in ('Z04','Z05')},
        worst_absolute_sessions=worst, records=records,
        limitations=['Z04/Z05ともB5より悪化した場がないため、未改善の絶対赤字上位3場を代わりに診断。',
            '全場既知の開発標本。改善した分岐の発火数と基準全体の安定性を分けて評価する。',
            '原板の数量変化を参加者の意図・約定・取消へ分解していない。',
            '価格時計での窓と同時刻原行順を使う。独立した共通受信時計の精度は未測定。'])
    content = json.dumps(clean(value),ensure_ascii=False,indent=2,allow_nan=False)
    with (HERE/'夜間切替の改善集中と未改善損失142.json').open('x',encoding='utf-8') as f:
        f.write(content)


if __name__ == '__main__':
    main()
