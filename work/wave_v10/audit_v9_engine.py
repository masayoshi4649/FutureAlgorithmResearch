"""前回の凍結取引と高速化後の同一条件を全件比較する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd

import engine

sys.path.insert(0, str(engine.ROOT / 'work' / 'wave_v9'))
import execution


def main() -> None:
    """機能: 前回90条件・12セルを再生し、凍結取引と全共通属性を照合する。

    引数: なし。返り値: なし (None)。検査記録を日本語JSONへ保存する。
    """
    begin = time.perf_counter()
    old_root = engine.ROOT / 'work' / 'wave_v9'
    trades = json.loads((old_root / '全取引.json').read_text(encoding='utf-8'))
    events = pd.DataFrame(json.loads((old_root / '転換イベント.json').read_text(encoding='utf-8')))
    grouped = defaultdict(list)
    for trade in trades:
        grouped[(trade['セッション'], trade['銘柄'], trade['方式'])].append(trade)
    count, attributes, cells = 0, 0, 0
    summary_old = pd.read_csv(old_root / '全条件セッション集計.csv').set_index(['セッション', '銘柄', '方式'])
    for session in execution.SESSIONS:
        for symbol in execution.SYMBOLS:
            tape = dict(np.load(engine.ROOT / 'work' / 'wave_v8' / 'features' / f'約定系列_{symbol}_{session}.npz'))
            tape['atr'] = execution.atr_at(session, symbol, tape['time_s'])
            subset = events[events['セッション'].eq(session) & events['銘柄'].eq(symbol)]
            prepared = engine.prepare(tape, subset, session, symbol)
            for old_config in execution.configs():
                config = engine.v9_config(old_config)
                actual = engine.simulate(prepared, config)
                expected = grouped[(session, symbol, config['id'])]
                assert len(actual) == len(expected), (session, symbol, config['id'], '取引数', len(actual), len(expected))
                for left, right in zip(actual, expected):
                    for key in left.keys() & right.keys():
                        a, b = left[key], right[key]
                        if isinstance(a, float):
                            assert np.isclose(a, b, rtol=0, atol=1e-8), (session, symbol, config['id'], key, a, b)
                        else:
                            assert a == b, (session, symbol, config['id'], key, a, b)
                        attributes += 1
                    count += 1
                summary = engine.summary(prepared, config)
                expected_summary = summary_old.loc[(session, symbol, config['id'])].to_dict()
                for key in summary.keys() & expected_summary.keys():
                    left, right = summary[key], expected_summary[key]
                    if left is None:
                        assert pd.isna(right)
                    elif isinstance(left, (int, float)):
                        assert np.isclose(left, right, rtol=1e-10, atol=1e-7), (key, left, right)
                    else:
                        assert left == right
                cells += 1
    result = dict(全条件=90, 銘柄セッションセル数=cells, 一致取引数=count, 一致属性数=attributes,
                  集計一致=True, 所要秒=time.perf_counter()-begin,
                  実装SHA256=hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest())
    engine.save(engine.OUT / '前回注文再生との全件一致.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
