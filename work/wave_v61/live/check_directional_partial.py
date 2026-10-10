"""現在取得なしに、方向性途中会計と同時計の既知境界を人工データで検査する。"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

import directional_replay as live


HERE = Path(__file__).resolve().parent


def main() -> None:
    """機能: 未決済・返済・未執行・空場・原本順境界の会計を人工ケースで検査する。

    引数: なし。
    返り値: なし(None)。本体コードの変更・原本取得は行わない。
    """
    original_build, original_candidates = live.features.build, live.signals.candidates
    try:
        mids = np.full(30, 1000.)
        seq = np.arange(30, dtype=np.int64)
        # 最初の5行は同時計でも、行2で新規を実行したか否かは境界seqで区別する。
        times = np.r_[np.zeros(5), np.arange(1, 26) * 60.]
        ready = dict(seq=seq, time_s=times, start=0., limit=3600., symbol='TOPIX', session='2026-09-21_Day', tick=1.)
        quote = dict(seq=seq, time_s=times, bid=mids - .5, ask=mids + .5, mid=mids)
        config = dict(family='D1', fraction=.01, initial_fraction=.5, pyramid=False, cooldown_minutes=10, minutes=60)
        live.features.build = lambda *args: pd.DataFrame({'can_trade': [True]})
        live.signals.candidates = lambda *args: {'D1': np.array([[1., 1., 10.]])}
        checks = []
        for count in (0, 2, 3, 30):
            account = live.partial_account(ready, quote, config, True, count)
            assert account['net'] == -5209. and account['long_qty'] == 5
            assert account['fees_incurred'] == 209. and account['unrealized_end'] == -5000.
            assert account['既知境界']['net'] == (0. if count < 3 else -5209.)
            assert account['追加区間純変化'] == (-5209. if count < 3 else 0.)
            checks.append(f'既知{count}行境界と未決済評価')
        account = live.partial_account(ready, quote, config, False, 2)
        assert account['net'] == -209. and account['unrealized_end'] == 0.
        checks.append('中値独立参考の発生費用')
        closed = live.partial_account(ready, quote, dict(config, minutes=5), True, 3)
        assert closed['net'] == -5418. and closed['long_qty'] == 0 and closed['fees_incurred'] == 418.
        assert closed['既知境界']['net'] == -5209. and closed['追加区間純変化'] == -209.
        assert closed['追加区間']['gross_realized'] == -5000. and closed['追加区間']['unrealized'] == 5000.
        checks.append('境界残玉の返済で含みを二重計上しない')
        live.signals.candidates = lambda *args: {'D1': np.array([[29., 1., 10.]])}
        pending = live.partial_account(ready, quote, config, True, 30)
        assert pending['net'] == 0 and pending['fees_incurred'] == 0 and pending['long_qty'] == 0
        checks.append('最終行の未執行新規は建玉や費用にしない')
        empty_ready = dict(ready, seq=seq[:0], time_s=times[:0])
        empty = live.partial_account(empty_ready, {k: v[:0] for k, v in quote.items()}, config, True, 0)
        assert empty['net'] == 0 and empty['追加区間純変化'] == 0
        checks.append('空場の準備待ち')
    finally:
        live.features.build, live.signals.candidates = original_build, original_candidates
    record = {'合格': True, '検査数': len(checks), '検査': checks, '実データ損益計算': False,
              'ネットワーク取得': False, '固定売買コード変更': False}
    (HERE / '方向性途中会計の合成監査.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False))


if __name__ == '__main__':
    main()
