"""固定済み54条件を既知原本へ適用し、同銘柄サイクルの損小利大を比較する。"""

from pathlib import Path
import hashlib
import json
import pickle
import time

import numpy as np
import pandas as pd

import grid_engine
import metrics
import reference
import research

OUT = Path(__file__).resolve().parent


def main() -> None:
    """機能: 保存７完全区間を探索し、既知ナイト前半は別診断として保存する。

    引数: なし。返り値: なし (None)。現在APIを取得せず、旧成果を書き換えない。
    """
    frozen = json.loads((OUT / '格子条件_損益前固定.json').read_text(encoding='utf-8'))
    assert frozen['条件一覧'] == grid_engine.catalog()
    audit = json.loads((OUT / '格子再生_手計算と未来打切り監査.json').read_text(encoding='utf-8'))
    assert audit['合格'] and audit['実装SHA256'] == hashlib.sha256((OUT / 'grid_engine.py').read_bytes()).hexdigest()
    cfgs = [dict(cfg, engine='grid') for cfg in frozen['条件一覧']]
    reference.save(OUT / '格子条件一覧.json', cfgs)
    prepared = reference.load_inputs()
    cells = list(prepared)
    by_key = {(cfg['id'], symbol): [] for cfg in cfgs for symbol in reference.SYMBOLS}
    rows, raw_blocks, cells_cache = [], [], {}
    started = time.monotonic()
    for cell_index, ((session, symbol), ready) in enumerate(prepared.items()):
        for method_index, cfg in enumerate(cfgs):
            result = grid_engine.simulate(ready, cfg)
            cycles = metrics.from_raw(result['raw'], cfg['id'], symbol, session, cfg['max_legs'],
                                      ready['time_s'], incomplete_cycle_ids=result['incomplete_cycle_ids'])
            by_key[(cfg['id'], symbol)].extend(cycles)
            rows.append(dict(方式=cfg['id'], 系統=cfg['family'], 思想=cfg['philosophy'],
                セッション=session, 銘柄=symbol, 設定最大枚数=cfg['max_legs'],
                用途='探索' if session in reference.TRAIN else '既知ナイト前半・診断のみ', **result['summary']))
            cells_cache[(cfg['id'], session, symbol)] = dict(raw=result['raw'], summary=result['summary'],
                incomplete_cycle_ids=result['incomplete_cycle_ids'])
            if len(result['raw']):
                raw_blocks.append(np.column_stack([np.full(len(result['raw']), method_index),
                                                  np.full(len(result['raw']), cell_index), result['raw']]))
        print(f'格子 {session} {symbol} {len(cfgs)}条件、{time.monotonic()-started:.1f}秒', flush=True)
    pd.DataFrame(rows).to_csv(OUT / '格子_セッション集計.csv', index=False, encoding='utf-8-sig')
    np.savez_compressed(OUT / '格子_全脚数値.npz', trades=np.vstack(raw_blocks))
    reference.save(OUT / '格子_数値形式.json', dict(条件=[cfg['id'] for cfg in cfgs], セル=cells,
        列=['条件index', 'セルindex', *grid_engine.RAW_COLUMNS]))
    with (OUT / '格子_再生結果.pkl').open('wb') as stream:
        pickle.dump(cells_cache, stream, protocol=pickle.HIGHEST_PROTOCOL)
    research.evaluate_pool(by_key, cfgs, '格子')
    diagnostic = []
    for (method, symbol), cycles in by_key.items():
        selected = [cycle for cycle in cycles if cycle['session'] == reference.KNOWN_NIGHT]
        row = metrics.summarize(selected, [reference.KNOWN_NIGHT], 'yen')
        diagnostic.append(dict(method=method, symbol=symbol,
            **{key: value for key, value in row.items() if key not in ('method', 'symbol') and not isinstance(value, (dict, list))}))
    pd.DataFrame(diagnostic).to_csv(OUT / '格子_既知ナイト前半診断.csv', index=False, encoding='utf-8-sig')
    reference.save(OUT / '格子_実行完了.json', dict(条件数=len(cfgs), セル数=len(rows),
        全脚数=sum(len(block) for block in raw_blocks), 秒=time.monotonic() - started,
        実装SHA256=hashlib.sha256((OUT / 'grid_engine.py').read_bytes()).hexdigest(),
        サイクル指標SHA256=hashlib.sha256((OUT / 'metrics.py').read_bytes()).hexdigest(),
        原本追加取得=0, 探索区間=reference.TRAIN, 既知夜間は選択不使用=True))


if __name__ == '__main__':
    main()
