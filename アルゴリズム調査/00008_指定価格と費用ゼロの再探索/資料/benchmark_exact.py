"""保存済み学習データだけを使い、理想約定再生器の実行時間を測る。"""

import json
import time

import data
import exact_engine


def main() -> None:
    """機能: 学習初日の夜間を繰り返し再生し、速度と基本集計を表示する。

    引数: なし。返り値: なし (None)。
    """
    signals = data.signals_module()
    inputs = signals.load_inputs(['2026-09-21_Night'])
    item = inputs[('2026-09-21_Night', 'NK225')]
    ready = exact_engine.prepare(item['tape'], item['events'], '2026-09-21_Night', 'NK225', item['state'])
    config = dict(entry_mode='trail', entry_atr=.25, initial_stop_atr=.75, trail_atr=2., trail_start_atr=1.)
    result = exact_engine.simulate(ready, 'P01', config)
    begin = time.perf_counter()
    for _ in range(100):
        result = exact_engine.simulate(ready, 'P01', config)
    elapsed = time.perf_counter() - begin
    print(json.dumps(dict(原本行数=len(ready['seq']), 百回秒=elapsed, 一回秒=elapsed / 100,
                         損益=result['summary']), ensure_ascii=False))


if __name__ == '__main__':
    main()
