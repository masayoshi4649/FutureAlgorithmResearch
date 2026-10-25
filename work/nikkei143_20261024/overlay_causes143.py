"""登録済み第一巡の保存注文を再集計し、救った負けと消した勝ちを分離する。"""

import json
import sys
import numpy as np
import common143 as common
sys.path.insert(0, str(common.ROOT / 'work/raw_diagnosis141_20261024'))
from supplement_loss_audit141 import parent_record
from loss_raw141 import clean


def main():
    """
    機能: O系十二案の全親差と主要反例の当時原板を、金融再生なしで保存する。
    引数: なし。
    返り値: None。既存の会計・源を変更しない。
    """
    saved = common.read(common.HERE / '第一巡結果143.json')
    lookup = {(r['session'], r['method']): r for r in saved['rows']}
    sessions = sorted({r['session'] for r in saved['rows']})
    changes, aggregates = [], []
    for method in [f'O{i:02d}' for i in range(12)]:
        for scene in sessions:
            old = lookup[scene, 'B0']['parent_records']
            new = {p['id']: p for p in lookup[scene, method]['parent_records']}
            for p in old:
                q = new.get(p['id'])
                delta = (q['net'] if q else 0.) - p['net']
                if delta or q is None:
                    changes.append(dict(session=scene, method=method, parent=p['id'], side=p['side'],
                        old_net=p['net'], new_net=q['net'] if q else 0., change=delta,
                        old_entry=p['entry'], old_exit=p['exit'],
                        new_entry=q['entry'] if q else None, new_exit=q['exit'] if q else None,
                        removed=q is None, win_to_loss=p['net'] > 0. and q is not None and q['net'] < 0.,
                        loss_to_win=p['net'] < 0. and q is not None and q['net'] > 0.))
        for kind in ('Day', 'Night'):
            rows = [lookup[s, method] for s in sessions if s.endswith(kind)]
            diffs = [c for c in changes if c['method'] == method and c['session'].endswith(kind)]
            profit, loss = sum(r['profit'] for r in rows), sum(r['loss'] for r in rows)
            aggregates.append(dict(method=method, kind=kind, profit=profit, loss=loss,
                net=profit-loss, pf=profit/loss if loss else None,
                red=sum(r['net'] < 0. for r in rows), zero=sum(r['entries'] == 0 for r in rows),
                mean_holding=sum(r['holding_ratio'] for r in rows)/len(rows),
                changed_parents=len(diffs), improvement=sum(max(c['change'], 0.) for c in diffs),
                worsening=sum(max(-c['change'], 0.) for c in diffs),
                lost_winners=sum(c['removed'] and c['old_net'] > 0. for c in diffs),
                lost_winner_net=sum(c['old_net'] for c in diffs if c['removed'] and c['old_net'] > 0.),
                avoided_losers=sum(c['removed'] and c['old_net'] < 0. for c in diffs),
                avoided_loser_net=-sum(c['old_net'] for c in diffs if c['removed'] and c['old_net'] < 0.),
                win_to_loss=sum(c['win_to_loss'] for c in diffs), loss_to_win=sum(c['loss_to_win'] for c in diffs)))
    selected = [('2026-10-22_Day', 'O03', 0), ('2026-09-28_Day', 'O02', 1),
                ('2026-10-21_Night', 'O03', 4000000), ('2026-10-21_Night', 'O03', 1)]
    packets, _, _ = common.material()
    sources = {p['session']: p for p in packets}
    examples = []
    for scene in sorted({c[0] for c in selected}):
        packet = common.packet_from(sources[scene])
        data, inputs, market, history = common.previous.prepared(packet)
        k = scene, 'NK225'
        raw = {}
        for symbol in ('NK225', 'TOPIX'):
            with np.load(common.ROOT / 'work/raw_diagnosis141_20261024/raw_features' / f'{symbol}_{scene}.npz') as z:
                raw[symbol] = {key: z[key] for key in z.files}
        with np.load(common.HERE / 'round1/measurement' / f'NK225_{scene}.npz') as z:
            arrays = {name: z[name] for name in ('B0', 'O02', 'O03')}
        with np.load(common.HERE / 'round1/traces' / f'NK225_{scene}.npz') as z:
            traces = {name: z[name] for name in ('O02', 'O03')}
        for _, method, pid in [x for x in selected if x[0] == scene]:
            parents = {}
            for key in ('B0', method):
                orders = arrays[key][arrays[key][:, 2] == pid]
                if len(orders):
                    parents[key] = parent_record(orders, inputs[k], packet['quotes'][k], history[k], market[k],
                                                raw['NK225'], inputs[scene, 'TOPIX'], raw['TOPIX'])
                    for o in parents[key]['orders']:
                        i = o['decision']['row']
                        o['decision']['features30'] = data['NK225']['features'][i]
                        o['decision']['own_ma20'] = history[k][i, 1]
                        o['decision']['public_atr'] = inputs[k]['atr'][i]
                        o['decision']['source_path'] = str(raw['NK225']['source_path'])
                        o['decision']['line_sha256'] = raw['NK225']['line_sha256'][o['decision']['seq']].tobytes().hex()
                else:
                    parents[key] = None
            examples.append(dict(session=scene, method=method, parent=pid, saved=parents,
                trace=traces[method][traces[method][:, 1] == pid]))
    output = dict(金融再生=0, source=common.prior.ref(common.HERE/'第一巡結果143.json'),
                  集計=aggregates, 全変更親=changes, 原板付き反例=examples)
    with (common.HERE/'O系の勝敗変化143.json').open('x', encoding='utf-8') as f:
        json.dump(clean(output), f, ensure_ascii=False, indent=2, allow_nan=False)
    for x in examples:
        print(x['session'], x['method'], x['parent'], flush=True)
        for key, parent in x['saved'].items():
            if parent:
                print(key, parent['net'], [(o['fill_time'], o['quantity'], o['price']) for o in parent['orders']], flush=True)


if __name__ == '__main__':
    main()
