"""登録後に実夜間一場で旧同値・未来不変・上下対称・全注文会計を独立検査する。"""

import copy
import json
import pickle
import sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT/'work/raw_diagnosis141_20261024'))
import supplemental141_v3 as original
import night_trader142 as revised
import run142


def validate(orders, ready, quote):
    """
    機能: 保存形式の全注文を独立に照合し、次原行・気配・枚数・円会計を確認する。
    引数: orders(ndarray[m,10])、ready/quote(dict)は約定と原行資料。
    返り値: dictは件数と費用。収益性を評価する指標ではない。
    """
    lots, held = {}, {1:0, -1:0}
    gross = fee = 0.
    normal = np.flatnonzero(quote['quote_valid'] & np.isfinite(quote['bid']) & np.isfinite(quote['ask'])
        & (quote['bid'] > 0.) & (quote['ask'] > quote['bid']))
    for row in orders:
        i, d, parent, side, qty = map(int, row[:5])
        assert 0 <= d < i < len(ready['time_s'])
        assert i == normal[np.searchsorted(normal, d, side='right')]
        assert row[5] == (quote['ask'][i] if side > 0 else quote['bid'][i])
        assert row[9] == qty*385//10
        key = parent, int(row[8])
        fee += row[9]
        if row[7]:
            assert key not in lots
            lots[key] = [side, qty, row[5]]
            held[side] += qty
        else:
            old = lots[key]
            assert old[0] == -side and old[1] >= qty
            gross += old[0]*(row[5]-old[2])*qty*100.
            old[1] -= qty
            held[-side] -= qty
        assert all(0 <= x <= 10 for x in held.values())
    assert all(x == 0 for x in held.values()) and all(x[1] == 0 for x in lots.values())
    cash = float(np.sum(-orders[:, 3]*orders[:, 4]*orders[:, 5]*100.-orders[:, 9]))
    assert abs(cash-(gross-fee)) < 1.e-6
    return dict(orders=len(orders), fee_yen=fee, all_flat=True, cash_consistent=True)


def main():
    """
    機能: 事前登録と実装指紋を確認した後だけ、限定した機械整合試験を実行する。
    引数: なし。
    返り値: None。新しい条件・パラメータ探索や有効性判定は行わない。
    """
    prior = run142.prior
    registration = prior.read(HERE/'登録142.json')
    assert registration['returncode'] == 0
    plan = prior.read(HERE/'試行計画142.json')
    for path, sha in plan['spec']['implementation'].items():
        assert prior.ref(ROOT/path)['sha256'] == sha, path
    packets, bases, _ = run142.first.material()
    scene, symbol = '2026-09-29_Night', 'NK225'
    item = next(p for p in packets if p['session'] == scene)
    packet = pickle.loads((ROOT/item['path']).read_bytes())
    data, inputs, markets, histories = run142.prepared(packet)
    key = scene, symbol
    base = run142.first.load_arrays(bases[key])['B5']
    core = base[base[:, 8] != 999]
    ready, quote, history, market, extra = inputs[key], packet['quotes'][key], histories[key], markets[key], data[symbol]['features']
    legacy = []
    for config in original.configurations():
        a, an = original.replay(ready, quote, history, market, core, config)
        b, bn = revised.replay(ready, quote, history, market, core, config, extra=extra)
        np.testing.assert_array_equal(a, b)
        assert an == bn
        legacy.append(dict(method=config['id'], exact_orders=True, exact_notes=True))
    # ----------------------------------------
    # 未来の価格・特徴・通知価格を変えても変更前の原行までの注文は一致する。
    cut = int(np.searchsorted(ready['time_s'], ready['us_open']+1860., side='left'))
    future_q = {k:v.copy() for k,v in quote.items()}
    future_q['bid'][cut:] += 100.
    future_q['ask'][cut:] += 100.
    future_h, future_m, future_x = history.copy(), market.copy(), extra.copy()
    future_h[cut:, [6,7,10,11,13]] *= -1.
    future_m[cut:, 4:8] *= -1.
    future_x[cut:, 24:28] *= -1.
    future_core = core.copy()
    for row in future_core:
        if int(row[0]) >= cut:
            row[5] = future_q['ask'][int(row[0])] if row[3] > 0 else future_q['bid'][int(row[0])]
    # ----------------------------------------
    # 公開済み水準は鏡像、方向量は符号反転。時刻・幅・費用・方向無依存値は維持する。
    axis = float(quote['bid'][0]+quote['ask'][0])
    mirrored_q = {k:v.copy() for k,v in quote.items()}
    mirrored_q['bid'], mirrored_q['ask'] = axis-quote['ask'], axis-quote['bid']
    mirrored_h, mirrored_m, mirrored_x = history.copy(), market.copy(), extra.copy()
    for col in (0,1,8):
        mirrored_h[:, col] = axis-history[:, col]
    mirrored_h[:, 3], mirrored_h[:, 4] = axis-history[:, 4], axis-history[:, 3]
    for col in (6,7,10,11,13):
        mirrored_h[:, col] *= -1.
    mirrored_m[:, 4:8] *= -1.
    mirrored_x[:, 24:28] *= -1.
    mirrored_core = core.copy()
    mirrored_core[:, 3] *= -1.
    mirrored_core[:, 5] = axis-core[:, 5]
    rows = []
    for config in revised.configurations():
        actual, notes = revised.replay(ready, quote, history, market, core, config, extra=extra)
        future, _ = revised.replay(ready, future_q, future_h, future_m, future_core, config, extra=future_x)
        np.testing.assert_array_equal(actual[actual[:, 0] < cut], future[future[:, 0] < cut])
        mirrored, _ = revised.replay(ready, mirrored_q, mirrored_h, mirrored_m, mirrored_core, config, extra=mirrored_x)
        np.testing.assert_allclose(actual[:, [0,1,2,4,6,7,8,9]], mirrored[:, [0,1,2,4,6,7,8,9]], atol=0., rtol=0.)
        np.testing.assert_allclose(actual[:, 3], -mirrored[:, 3], atol=0., rtol=0.)
        np.testing.assert_allclose(actual[:, 5], axis-mirrored[:, 5], atol=1.e-9, rtol=0.)
        counted = validate(actual, ready, quote)
        validate(future, ready, future_q)
        validate(mirrored, ready, mirrored_q)
        assert all(n['原seq'] == ready['seq'][n['原行']] for n in notes)
        rows.append(dict(method=config['id'], prefix_unchanged=True, mirror=True, trace_seq=True, **counted))
        print(config['id'], '実原行の因果・対称・全会計検査合格', flush=True)
    with (HERE/'夜間選択の実原行機械検査142.json').open('x', encoding='utf-8') as stream:
        json.dump(dict(session=scene, symbol=symbol, legacy=legacy, checks=rows,
            purpose='登録済み仕様の限定した同値・因果・会計確認。有効性の独立標本ではない。',
            API=0, real_orders=0), stream, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
