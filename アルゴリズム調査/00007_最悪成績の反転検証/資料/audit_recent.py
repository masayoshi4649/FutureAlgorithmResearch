"""既読ナイト参考の反転会計・時系列・数量・集計を独立に確認する。"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent


def main() -> None:
    """機能: 保存済みナイトの原板と反転明細を再計算し集計に突き合わせる。

    引数: なし。返り値: なし (None)。通信やシミュレーション条件の変更は行わない。
    """
    schema = json.loads((OUT/'反転_既読ナイト数値形式.json').read_text(encoding='utf-8'))
    details = np.load(OUT/'反転_既読ナイト全取引数値.npz')['反転']
    prepared = pickle.loads((OUT/'既読ナイト入力.pkl').read_bytes())
    configs = {c['id']: c for c in json.loads((OUT.parent/'wave_v11'/'条件一覧.json').read_text(encoding='utf-8'))}
    bins = defaultdict(lambda: defaultdict(float))
    order_qty = defaultdict(int)
    inventory = defaultdict(lambda: defaultdict(int))
    for row in details:
        cid, cell = int(row[0]), int(row[1])
        name = schema['条件'][cid]
        session, symbol = schema['セル'][cell]
        ready = prepared[(session, symbol)]
        multiplier, tick = (1000., 10.) if symbol == 'NK225' else (10000., .5)
        side, start, end = row[4], int(row[5]), int(row[6])
        own_entry = ready['ask' if side > 0 else 'bid'][start]
        own_exit = ready['bid' if side > 0 else 'ask'][end]
        original = side*(own_exit-own_entry)-2*tick
        reverse = -side*(ready['ask' if side > 0 else 'bid'][end]-ready['bid' if side > 0 else 'ask'][start])-2*tick
        assert np.isclose(original, row[11]) and np.isclose(reverse, row[15])
        key = (name, session, symbol)
        for prefix, value, closed in [('元', original, bool(row[7])), ('理論反転', reverse, bool(row[7]))]:
            bins[key][prefix+'総評価円'] += value*multiplier
            bins[key][prefix+'収支円'] += value*multiplier if closed else 0
        # ----------------------------------------
        for offset, prefix in [(17, '容量反転'), (23, '次行反転')]:
            first, last, closed = int(row[offset]), int(row[offset+1]), bool(row[offset+2])
            if first < 0:
                continue
            lag = int(prefix == '次行反転')
            assert first >= start+lag
            if closed:
                assert last >= end+lag
            entry = ready['bid' if side > 0 else 'ask'][first]
            exit_quote = ready['ask' if side > 0 else 'bid'][last]
            value = -side*(exit_quote-entry)-2*tick
            np.testing.assert_allclose(row[offset+3:offset+6], [entry, exit_quote, value])
            order_qty[(name, cell, prefix, first, 'bid' if side > 0 else 'ask')] += 1
            inventory[(name, cell, prefix)][first] += 1
            if closed:
                order_qty[(name, cell, prefix, last, 'ask' if side > 0 else 'bid')] += 1
                inventory[(name, cell, prefix)][last] -= 1
            bins[key][prefix+'総評価円'] += value*multiplier
            bins[key][prefix+'収支円'] += value*multiplier if closed else 0
    for (name, cell, prefix, index, side), used in order_qty.items():
        ready = prepared[tuple(schema['セル'][cell])]
        assert used <= ready[side+'_qty'][index]
    for (name, cell, prefix), events in inventory.items():
        held = 0
        for index, delta in sorted(events.items()):
            held += delta
            assert 0 <= held <= configs[name].get('max_positions', 1)
    table = pd.read_csv(OUT/'反転_既読ナイトセッション集計.csv').set_index(['方式', 'セッション', '銘柄'])
    comparisons = 0
    for key, row in table.iterrows():
        for prefix in ('元', '理論反転', '容量反転', '次行反転'):
            for metric in ('総評価円', '収支円'):
                assert np.isclose(row[prefix+metric], bins[key][prefix+metric])
                comparisons += 1
    report = dict(原板会計照合脚数=len(details), 元集計との照合値数=comparisons,
                  反転側数量共有の照合行数=len(order_qty), 仮想約定からの次行遅延確認=True,
                  最大保有上限確認=True, 現在API取得数=0, 未読評価ではない=True, 合格=True,
                  入力SHA256=hashlib.sha256((OUT/'既読ナイト入力.pkl').read_bytes()).hexdigest())
    (OUT/'既読ナイト反転の独立監査.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
