"""一度保存済みの 01:53 までのナイト入力で、指定条件の反転を追加参考計算する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import pickle
import sys
import time

import numpy as np
import pandas as pd

import mirror

sys.path.insert(0, str(mirror.SOURCE))
import catalog
import orders
import single


def main() -> None:
    """機能: 既読ナイト原本から元の条件を仮想再生し、同時点・次行反転を比較保存する。

    引数: コマンドライン --ids は条件 ID の JSON 配列ファイル (str)。
    返り値: なし (None)。既読区間の参考計算であり、現在 API は取得しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--ids', type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    ids = json.loads(args.ids.read_text(encoding='utf-8'))
    source_path = mirror.OUT / '既読ナイト入力.pkl'
    saved_configs = json.loads((mirror.SOURCE / '条件一覧.json').read_text(encoding='utf-8'))
    configs = catalog.configs()
    assert [c['id'] for c in configs] == [c['id'] for c in saved_configs]
    for saved, config in zip(saved_configs, configs):
        for name, value in saved.items():
            assert (value is None and isinstance(config[name], float) and np.isinf(config[name])) or value == config[name]
    mapping = {c['id']: i for i, c in enumerate(configs)}
    assert isinstance(ids, list) and all(x in mapping for x in ids)
    with source_path.open('rb') as stream:
        prepared = pickle.load(stream)
    schema = dict(条件=[c['id'] for c in configs], セル=[list(k) for k in prepared])
    rows, details, shortages = [], [], []
    for cell_i, (key, ready) in enumerate(prepared.items()):
        for name in sorted(set(ids)):
            config_i, config = mapping[name], configs[mapping[name]]
            raw = (orders.simulate_array(ready, config)['trades'] if config['engine'] == 'orders'
                   else single.simulate_array(ready, config))
            row, detail, scarce = mirror.process_cell(ready, raw, config, config_i, cell_i)
            row['評価区間'] = '既読ナイト全体・翌01:53まで'
            rows.append(row)
            if len(detail):
                details.append(detail)
            shortages.extend(dict(方式=name, セッション=key[0], 銘柄=key[1], **r) for r in scarce)
        print(f'{key}: {len(set(ids))} 条件の既読ナイト反転完了', flush=True)
    all_details = np.vstack(details) if details else np.empty((0, len(mirror.DETAIL_COLUMNS)))
    pd.DataFrame(rows).to_csv(mirror.OUT / '反転_既読ナイトセッション集計.csv', index=False, encoding='utf-8-sig')
    np.savez_compressed(mirror.OUT / '反転_既読ナイト全取引数値.npz', 反転=all_details)
    mirror.save(mirror.OUT / '反転_既読ナイト数値形式.json', dict(列=mirror.DETAIL_COLUMNS, **schema))
    mirror.export_trades(all_details, schema, prepared, ids, mirror.OUT / '反転_既読ナイト代表取引.json')
    mirror.save(mirror.OUT / '反転_既読ナイト実行記録.json', dict(
        既読参考=True, 現在API取得数=0, 条件ID=sorted(set(ids)), セル数=len(rows), 脚数=len(all_details),
        秒=time.monotonic() - started, 入力SHA256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
        実装SHA256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in [Path(__file__), mirror.OUT / 'mirror.py']},
        説明='前回一度だけ取得し既に結果を閲覧したナイト。未読検証とは呼ばず、17:00〜翌01:53の全体参考。'))


if __name__ == '__main__':
    main()
