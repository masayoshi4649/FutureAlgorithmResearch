"""会計監査が全指標の欠落・改竄を拒否することを人工データで確認する。"""

from __future__ import annotations

import copy
import numpy as np
import band_runner as runner
import band_independent_statistics as statistics


def rejects(left: dict, right: dict) -> None:
    """機能: 不一致を合格させる比較器を拒否する。

    引数: left/right (dict)。返り値: なし (None)。
    """
    try:
        statistics.equal(left, right)
    except AssertionError:
        return
    raise AssertionError('破損した統計を許可しました')


def main() -> None:
    """機能: 無取引・上下・反転・停滞と全項目削除を検査する。

    引数: なし。返り値: なし (None)。実原本の損益は使わない。
    """
    x = np.arange(361, dtype=float)
    manager = runner.read(runner.HERE.parent / 'wave_v35/探索条件の固定.json')['manager']
    rows, series, rejected = [], {}, 0
    for symbol, tick in (('TOPIX', .5), ('NK225', 10.)):
        for i, path in enumerate((x / 5, -x / 5, np.minimum(x, 180) / 4 - np.maximum(x - 180, 0) / 3,
                                  np.zeros(361), 10 * np.sin(x / 11), x / 5)):
            session = f'合成{i}'
            ready = dict(last=(1000 + np.round(path)) * tick, time_s=x * 30, seq=np.arange(len(x)),
                atr=np.full(len(x), 4 * tick), tick=tick, start=0., limit=10740., us_open=np.inf,
                session=session, symbol=symbol)
            state = np.zeros(len(x), np.int8) if i == 5 else np.ones(len(x), np.int8)
            cfg = runner.base.managers.make_config(manager, symbol, ready)
            result = runner.base.engine.run(ready, state, cfg, detail=True, width_mode=0)
            independent, curves = runner.accounting.reconstruct(ready, result, symbol)
            actual = statistics.session('合成条件', ready, result, cfg, independent, curves)
            expected = runner.base.research.summarize(result, cfg, symbol, session, '合成条件')
            expected.update(two_largest_cycle_profits=sorted([float(v) * cfg['point_value'] for v in result['cycles'][:, 3] if v > 0], reverse=True)[:2],
                long_unit_minutes=float(np.sum(curves['long'] * np.diff(ready['time_s'], append=ready['time_s'][-1]) / 60.)),
                short_unit_minutes=float(np.sum(curves['short'] * np.diff(ready['time_s'], append=ready['time_s'][-1]) / 60.)),
                opening_orders=int(np.sum(result['orders'][:, 7] == 1)),
                retracements=runner.base.retracements(result, ready, cfg['point_value']))
            statistics.equal(actual, expected)
            for field in expected:
                damaged = copy.deepcopy(expected); del damaged[field]
                rejects(damaged, actual); rejected += 1
            for field in ('opening_orders', 'net_r', 'long_unit_minutes', 'reversals', 'maximum_trade_profit'):
                damaged = copy.deepcopy(expected); damaged[field] += 1
                rejects(damaged, actual); rejected += 1
            if expected['retracements']:
                damaged = copy.deepcopy(expected); damaged['retracements'][0]['retracement_yen'] += 1
                rejects(damaged, actual); rejected += 1
            rows.append(actual); series[(session, symbol)] = curves['equity']
    names = sorted({r['session'] for r in rows})
    aggregate = runner.period(rows, names)
    for symbol in runner.SYMBOLS:
        actual = statistics.period(rows, series, names, symbol, runner.accounting.MULT[symbol])
        statistics.equal(actual, aggregate[symbol])
        for field in actual:
            damaged = copy.deepcopy(actual); del damaged[field]
            rejects(damaged, actual); rejected += 1
        damaged = copy.deepcopy(actual); damaged['retracement']['all']['sum_yen'] += 1
        rejects(damaged, actual); rejected += 1
    output = dict(全人工合格=True, 入力数=12, 期間数=2, 破損拒否数=rejected, 新損益使用=False,
        SHA256={p.relative_to(runner.ROOT).as_posix(): runner.digest(p) for p in
            (runner.HERE / 'band_independent_statistics.py', runner.HERE / 'band_statistics_selftest.py', runner.HERE / 'band_accounting_audit.py')})
    runner.save(runner.HERE / 'band_statistics_selftest.json', output)
    print(output, flush=True)


if __name__ == '__main__':
    main()
