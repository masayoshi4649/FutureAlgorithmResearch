"""追加２セッションの途中で未来を捨て、候補２系統の信号を初めから再生成する。"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path

import numpy as np
import pandas as pd

import reference
from audit_input_prefix import compare_value

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
TARGETS = ['N03', 'N15']


def compare_frames(whole: pd.DataFrame, shortened: pd.DataFrame, cutoff: float, family: str) -> dict:
    """機能: 対象系統の全体計算と未来打切り再計算の信号を値ごとに比較する。

    引数: whole/shortened (DataFrame)、cutoff (float)、family (str)。返り値: 件数と合否 (dict)。
    """
    left = whole.loc[(whole.family == family) & (whole.time_s <= cutoff)].reset_index(drop=True)
    right = shortened.loc[shortened.family == family].reset_index(drop=True)
    assert len(left) == len(right), f'{family}: 信号数が一致しません'
    cells = 0
    for before, after in zip(left.to_dict('records'), right.to_dict('records')):
        assert set(before) == set(after)
        for column in before:
            compare_value(before[column], after[column], column, 0, 0)
            cells += 1
    return dict(系統=family, 一致信号数=len(left), 一致セル数=cells, 完全一致=True)


def main() -> None:
    """機能: 追加２区間を開始２時間・４時間で打切り、N03/N15 の未来不変性を検査する。

    引数: なし。返り値: なし (None)。保留区間・損益・通信を利用しない。
    """
    base = reference.previous.data.signals_module()
    sessions = ['2026-09-24_Night', '2026-09-25_Day']
    for session in sessions:
        base.CANDLE_OVERRIDES[session] = ROOT
        base.FEATURE_OVERRIDES[session] = OUT/'features'
    signals = reference.previous.new_signals
    signals.configure(base)
    records = []
    for session in sessions:
        features = {symbol: pd.read_csv(OUT/'features'/f'{symbol}_{session}.csv') for symbol in reference.SYMBOLS}
        start = reference.engine.bounds(session)[0]
        for symbol in reference.SYMBOLS:
            peer_symbol = reference.SYMBOLS[1-reference.SYMBOLS.index(symbol)]
            own, peer = features[symbol], features[peer_symbol]
            whole, _ = signals.build_events(session, symbol, own, peer)
            for hours in [2, 4]:
                cutoff = start + hours*3600
                own_cut = own.loc[own.time_s <= cutoff].copy()
                peer_cut = peer.loc[peer.time_s <= cutoff].copy()
                shortened, _ = signals.build_events(session, symbol, own_cut, peer_cut, cutoff=cutoff)
                actual_cutoff = float(own_cut.time_s.iloc[-1])
                checks = [compare_frames(whole, shortened, actual_cutoff, family) for family in TARGETS]
                row = dict(セッション=session, 銘柄=symbol, 開始後時間=hours,
                           打切り時刻_この時刻以下採用=pd.Timestamp(cutoff, unit='s', tz='UTC').tz_convert('Asia/Tokyo').isoformat(),
                           打切り後の自銘柄特徴行数=len(own_cut), 打切り後の他銘柄特徴行数=len(peer_cut), 系統別=checks)
                records.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
    result = dict(合格=True, API取得数=0, 最終保留利用=False, 損益計算=False,
                  方法='既存の信号配列を切っただけではない。封印解除済み板特徴の未来を両銘柄とも捨て、１分足指標・逐次推定・板回帰・イベント採択を build_events から再計算。元足は内部の開始＋２分／５分足開始＋６分の利用時刻制限を適用。',
                  監査対象系統=TARGETS, 再計算ケース数=len(records), 系統比較数=len(records)*len(TARGETS),
                  一致信号数=sum(check['一致信号数'] for row in records for check in row['系統別']),
                  監査=records)
    (OUT/'候補２系統の未来打切り監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key != '監査'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
