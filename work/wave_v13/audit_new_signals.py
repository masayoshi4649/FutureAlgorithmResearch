"""新規信号の過去打切り不変性と学習正解の時間制約を保存データで監査する。"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

import data
import new_signals

OUT = Path(__file__).resolve().parent


def compare_events(full: pd.DataFrame, cut: pd.DataFrame, stamp: float) -> int:
    """機能: 将来を切り捨てても既知通知と根拠が変わらないことを検査する。

    引数: full/cut (DataFrame)、stamp (float)。返り値: 比較した通知数 (int)。
    """
    expected = full.loc[full.time_s <= stamp].reset_index(drop=True)
    actual = cut.reset_index(drop=True)
    pd.testing.assert_frame_equal(expected.drop(columns='reason'), actual.drop(columns='reason'), check_dtype=False)
    for left, right in zip(expected.reason, actual.reason):
        assert left.keys() == right.keys()
        for key in left:
            if isinstance(left[key], (int, float)):
                np.testing.assert_allclose(left[key], right[key], rtol=1e-9, atol=1e-9, equal_nan=True)
            else:
                assert left[key] == right[key]
    return len(expected)


def run() -> None:
    """機能: 学習６セッションで18信号の生成と打切りを監査する。

    引数: なし。返り値: なし (None)。
    """
    start = time.perf_counter()
    base = data.signals_module()
    new_signals.configure(base)
    reports, counts = [], []
    for session in data.TRAIN:
        frames = {s: pd.read_csv(data.FEATURES/f'{s}_{session}.csv') for s in data.SYMBOLS}
        for symbol in data.SYMBOLS:
            peer_symbol = data.SYMBOLS[1-data.SYMBOLS.index(symbol)]
            frame, peer = frames[symbol], frames[peer_symbol]
            full, audit = new_signals.build_events(session, symbol, frame, peer)
            full.to_json(OUT/f'新規通知_{symbol}_{session}.json', orient='records', force_ascii=False, indent=1)
            counts.append(dict(session=session, symbol=symbol, **audit['系統別']))
            for fraction in [.3137, .6137, .9137]:
                index = min(len(frame)-1, int(len(frame)*fraction))
                stamp = float(frame.time_s.iloc[index])
                cut, _ = new_signals.build_events(session, symbol, frame.loc[frame.time_s <= stamp],
                                                 peer.loc[peer.time_s+60 <= stamp], cutoff=stamp)
                compared = compare_events(full, cut, stamp)
                paired = cut.peer_available_time_s.notna()
                assert (cut.source_last_seq < cut.seq).all()
                assert (cut.loc[paired, 'peer_source_last_seq'] < cut.loc[paired, 'peer_seq']).all()
                assert (cut.loc[paired, 'peer_available_time_s'] <= cut.loc[paired, 'time_s']).all()
                reports.append(dict(session=session, symbol=symbol, cutoff=stamp, compared=compared))
            print(session, symbol, len(full), flush=True)
    pd.DataFrame(counts).to_csv(OUT/'新規信号数.csv', index=False, encoding='utf-8-sig')
    result = dict(合格=True, 新規系統数=18, 打切り数=len(reports), 比較通知合計=sum(x['compared'] for x in reports),
                  詳細=reports, 秒=time.perf_counter()-start, 最終保留参照=False, API取得回数=0,
                  ソースSHA256=hashlib.sha256((OUT/'new_signals.py').read_bytes()).hexdigest())
    (OUT/'新規信号_打切り監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k != '詳細'}, ensure_ascii=False))


if __name__ == '__main__':
    run()
