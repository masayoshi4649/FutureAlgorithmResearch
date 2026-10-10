"""待機指値の通過条件・取消・次行返済を人工価格だけで検査する。"""

import json
from pathlib import Path

import numpy as np

import engine_round2 as engine


HERE = Path(__file__).resolve().parent


def main() -> None:
    """機能: 買売鏡像と時刻/原本行期限を含め、新規指値の追加仮定を検査する。

    引数: なし。
    返り値: なし(None)。実データの結果を読まない。
    """
    checks = []
    for side in (1, -1):
        for case in ('through', 'touch_only', 'time_expiry', 'seq_expiry'):
            mid = np.full(6, 1000.)
            mid[3:] = 998. if case != 'touch_only' else 999.
            if side < 0:
                mid = 2000. - mid
            clock = np.arange(6, dtype=float)
            seq = np.arange(6, dtype=np.int64)
            if case == 'time_expiry':
                clock[3:] += 61.
            if case == 'seq_expiry':
                seq[3:] += 2001
            ready = dict(seq=seq, time_s=clock, start=0., limit=3600., tick=1., symbol='TOPIX', session='2026-09-21_Day')
            quotes = dict(seq=seq, time_s=clock, mid=mid, bid=mid - .5, ask=mid + .5)
            config = dict(initial_fraction=.5, fraction=.01, pyramid=False, minutes=60,
                          cooldown_minutes=10, exit_mode=0, passive_entry=True)
            result = engine.execute(ready, quotes, np.array([[1., side, 10.]]), config, True, False)
            if case == 'through':
                assert len(result['orders']) == 1 and result['orders'][0, 3] == seq[3]
                assert result['orders'][0, 7] == (999.5 if side > 0 else 1000.5)
                assert result['fees'] == 209
            else:
                assert len(result['orders']) == 0 and result['fees'] == 0
            checks.append(f'{side}_{case}')
    result = {'合格': True, '検査数': len(checks), '検査': checks,
              '実データ損益計算': False, '待ち順は不明': True, '通過1呼値を必要とする仮定': True}
    (HERE / 'round2/売買器の合成監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
