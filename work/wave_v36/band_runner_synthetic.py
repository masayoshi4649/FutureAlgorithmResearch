"""新信号を接続する前に、旧固定注文器と保存器を人工経路で確認する。"""

from __future__ import annotations

import numpy as np

import band_runner as runner
import engine_connection_audit as connection


def main() -> None:
    """機能: 上下・反転・停滞の人工価格で両市場/両約定仮定を検査する。

    引数: なし。返り値: なし (None)。既知原本の新規成績は計算しない。
    """
    x = np.arange(361, dtype=float)
    paths = [x / 5, -x / 5, np.minimum(x, 180) / 4 - np.maximum(x - 180, 0) / 3,
        -np.minimum(x, 200) / 4 + np.maximum(x - 200, 0) / 2,
        np.zeros(361), 10 * np.sin(x / 11) + x / 25]
    manager = runner.read(runner.HERE.parent / 'wave_v35/探索条件の固定.json')['manager']
    count, trades, prefixes = 0, 0, 0
    for symbol, tick in (('TOPIX', .5), ('NK225', 10.)):
        for path in paths:
            price = (1000 + np.round(path)) * tick
            ready = dict(last=price, time_s=x * 30, seq=np.arange(len(x)), atr=np.full(len(x), 4 * tick),
                tick=tick, start=0., limit=10740., us_open=np.inf, session='合成', symbol=symbol)
            config = runner.base.managers.make_config(manager, symbol, ready)
            for kind in range(3):
                state = np.ones(len(x), np.int8) if kind == 0 else -np.ones(len(x), np.int8)
                if kind == 2:
                    state = np.where((x.astype(int) // 4) % 5 == 0, 1, 0).astype(np.int8)
                for observed in (False, True):
                    result = runner.base.engine.run(ready, state, config, detail=True, width_mode=0, observed_fill=observed)
                    summary, _ = runner.accounting.reconstruct(ready, result, symbol)
                    proof = connection.verify(ready, state, config, result, observed, (.37, .73))
                    assert summary['最終残玉'] == 0 and summary['max_long'] <= config['audit_cap']
                    assert summary['max_short'] <= config['audit_cap']
                    # 保存しないATR詳細にはNaNがあるが、保存台帳にはない。
                    import json
                    json.dumps({f: result[f].tolist() for f in runner.STORED}, allow_nan=False)
                    count += 1; trades += len(result['trades']); prefixes += proof['prefix']
    assert count == 72 and trades > 0 and prefixes == 144
    output = dict(人工経路72合格=True, 全行独立会計=True, 全玉場内返済=True,
        prefix=144, future=144, reflection=72, JSON非有限拒否=True, 返済明細数=trades,
        新規原本成績使用=False, 実装SHA256=runner.digest(runner.HERE / 'band_runner_synthetic.py'),
        runner_SHA256=runner.digest(runner.HERE / 'band_runner.py'),
        独立会計SHA256=runner.digest(runner.HERE.parent / 'wave_v35/accounting_reconstruction_vectorized.py'),
        接続検査SHA256=runner.digest(runner.HERE / 'engine_connection_audit.py'),
        注文器SHA256=runner.digest(runner.HERE.parent / 'wave_v33/engine_dynamic_atr.py'))
    runner.save(runner.HERE / 'band_runner_synthetic.json', output)
    print(output, flush=True)


if __name__ == '__main__':
    main()
