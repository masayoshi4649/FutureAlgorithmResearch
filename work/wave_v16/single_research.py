"""旧単独11,163条件を追加２区間へ適用し、先頭９区間だけで比較する。"""

from __future__ import annotations

from collections import defaultdict
import json
import pickle
import time

import numpy as np
import pandas as pd

import reference

OUT, OLD = reference.OUT, reference.OLD
metrics = reference.import_v14('metrics')
guard = reference.import_v14('risk_guard')
research = reference.import_v14('research')


def main() -> None:
    """機能: 旧７区間の同一性を確認したうえで追加２区間を再生し、既存選択指標を計算する。

    引数: なし。返り値: なし (None)。最終保留と現在APIは読まない。
    """
    prepared = reference.load_inputs('development')
    evidence = json.loads((OUT / '入力準備記録.json').read_text(encoding='utf-8'))
    if not evidence['旧７区間再利用可能']:
        raise RuntimeError('旧７区間の同一性を確認できないためキャッシュ再利用を中止します')
    configs = [c for c in reference.configs() if c['engine'] == 'single']
    bases = [c for c in configs if 'guard' not in c]
    children = defaultdict(list)
    for cfg in configs:
        if 'guard' in cfg:
            children[cfg['base_id']].append(cfg)
    reference.save(OUT / '単独_実行前記録.json', dict(時刻=pd.Timestamp.now(tz='Asia/Tokyo').isoformat(),
        条件数=len(configs), 基本条件=len(bases), 追加再生=reference.DEVELOPMENT[7:], 最終保留を含む=False,
        条件一覧SHA256=reference.sha256(OLD / '全条件一覧.json'),
        実装SHA256=reference.sha256(OUT / 'single_research.py')))
    with (OLD / '単独_サイクル.pkl').open('rb') as stream:
        by_key = pickle.load(stream)
    if set(by_key) != {(c['id'], k) for c in configs for k in reference.SYMBOLS}:
        raise AssertionError('旧サイクルの対象条件が一致しません')
    started = time.monotonic()
    for session in reference.DEVELOPMENT[7:]:
        for symbol in reference.SYMBOLS:
            ready = prepared[(session, symbol)]
            cache = {}
            for index, cfg in enumerate(bases):
                key = cfg['id'][:-1] if session.endswith('Day') and cfg['id'].endswith(('_U0', '_U1')) else cfg['id']
                if key not in cache:
                    raw = reference.engine.simulate(ready, cfg['family'], cfg)['raw']
                    cache[key] = raw
                raw = cache[key]
                by_key[(cfg['id'], symbol)].extend(metrics.from_raw(raw, cfg['id'], symbol, session, cfg['max_legs'], ready['time_s']))
                for child in children[cfg['id']]:
                    kept, _ = guard.filter_raw(raw, child)
                    by_key[(child['id'], symbol)].extend(metrics.from_raw(kept, child['id'], symbol, session, child['max_legs'], ready['time_s']))
                if index % 1500 == 0:
                    print(f'単独 {session} {symbol} {index}/{len(bases)}、累計{time.monotonic()-started:.1f}秒', flush=True)
            print(f'単独 {session} {symbol} 完了', flush=True)
    with (OUT / '単独_サイクル.pkl').open('wb') as stream:
        pickle.dump(by_key, stream, protocol=pickle.HIGHEST_PROTOCOL)
    # ----------------------------------------
    # 過去３〜７区間の指標は同一条件・同一原本の保存値をそのまま再使用する。
    previous_walk = pd.read_csv(OLD / '単独_時間順候補.csv')
    previous_seven = pd.read_csv(OLD / '単独_探索集計.csv')
    mapping = {c['id']: c for c in configs}
    development, count_eight = [], []
    for index, ((method, symbol), cycles) in enumerate(by_key.items()):
        cfg = mapping[method]
        development.append(research.scalar_metrics(cycles, reference.DEVELOPMENT, cfg, symbol))
        count_eight.append(research.scalar_metrics(cycles, reference.DEVELOPMENT[:8], cfg, symbol))
        if index % 3000 == 0:
            print(f'単独 比率集計 {index}/{len(by_key)}、累計{time.monotonic()-started:.1f}秒', flush=True)
    pd.DataFrame(development).to_csv(OUT / '単独_探索集計.csv', index=False, encoding='utf-8-sig')
    pd.concat([previous_walk, previous_seven, pd.DataFrame(count_eight)], ignore_index=True).to_csv(
        OUT / '単独_時間順候補.csv', index=False, encoding='utf-8-sig')
    reference.save(OUT / '単独_完了記録.json', dict(条件数=len(configs), 銘柄条件数=len(by_key),
        探索区間=reference.DEVELOPMENT, 最終保留計算=False, 所要秒=time.monotonic()-started,
        サイクル数=sum(len(v) for v in by_key.values())))


if __name__ == '__main__':
    main()
