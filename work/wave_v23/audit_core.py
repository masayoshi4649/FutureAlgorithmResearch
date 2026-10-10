"""実装の返済台帳から、現金・建玉・時価評価と因果的な執行を独立に検算する。"""

from __future__ import annotations

import numpy as np


def check_accounting(ready: dict, result: dict, config: dict) -> dict:
    """機能: 注文から現金と売買別在庫を再構成し、全行の記録を検算する。

    引数: ready/result/config (dict) は入力、詳細再生結果、固定設定。
    返り値: 検査件数・数量・損益の要約 (dict)。
    """
    trades, orders, curve, stats = (result[name] for name in ('trades', 'orders', 'curve', 'stats'))
    n = len(ready['last'])
    assert curve.shape == (n, 8), ('詳細の資産曲線がありません', curve.shape, n)
    if len(orders):
        assert np.all(orders[:, 0] > orders[:, 1]), '注文決定行以前での約定'
        assert np.all(orders[:, 4] > 0) and np.all(orders[:, 4] == orders[:, 4].astype(int))
        assert np.all(np.isin(orders[:, 3], [-1, 1]))
        assert np.all(np.isin(orders[:, 7], [0, 1]))
        assert np.all(np.diff(orders[:, 0]) >= 0)
    signed = orders[:, 3] * orders[:, 4]
    rows = orders[:, 0].astype(int)
    cash = np.cumsum(np.bincount(rows, weights=-signed * orders[:, 5], minlength=n))
    net = np.cumsum(np.bincount(rows, weights=signed, minlength=n))
    opening = orders[:, 7] == 1
    long_open = opening & (orders[:, 3] > 0)
    long_close = ~opening & (orders[:, 3] < 0)
    short_open = opening & (orders[:, 3] < 0)
    short_close = ~opening & (orders[:, 3] > 0)
    long = np.cumsum(np.bincount(rows, weights=orders[:, 4] * (long_open.astype(int) - long_close.astype(int)), minlength=n))
    short = np.cumsum(np.bincount(rows, weights=orders[:, 4] * (short_open.astype(int) - short_close.astype(int)), minlength=n))
    assert np.min(long) >= 0 and np.min(short) >= 0
    assert np.max(long) <= config['audit_cap'] and np.max(short) <= config['audit_cap']
    np.testing.assert_allclose(net, long - short, rtol=0, atol=1e-8)
    equity = cash + net * ready['last']
    values = trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4])
    np.testing.assert_allclose(values, trades[:, 10], rtol=0, atol=1e-8)
    assert np.all(trades[:, 6] < trades[:, 7]), '新規と同じ行以前での返済'
    realised = np.cumsum(np.bincount(trades[:, 7].astype(int), weights=values, minlength=n))
    peak = np.maximum.accumulate(np.r_[0., equity])[1:]
    dd = np.maximum.accumulate(peak - equity)
    expected = np.column_stack([equity, realised, long, short, dd, cash, net])
    np.testing.assert_allclose(expected, curve[:, :7], rtol=0, atol=1e-7)
    np.testing.assert_allclose([values.sum(), dd[-1], long.max(), short.max(), (long + short).max(), np.abs(net).max()], stats[:6], rtol=0, atol=1e-7)
    np.testing.assert_allclose([equity.min(), equity.max(), long[-1] + short[-1]], stats[7:10], rtol=0, atol=1e-7)
    np.testing.assert_allclose(result['cycles'][:, 3].sum(), values.sum(), rtol=0, atol=1e-7)
    assert long[-1] == short[-1] == 0, 'セッション末に建玉あり'
    assert stats[6] < 1e-7
    if len(orders):
        assert np.all(ready['time_s'][rows[opening]] < ready['limit']), '返済期限後の新規'
    return dict(全行検算=n, 注文件数=len(orders), 返済件数=len(trades), 確定損益=float(values.sum()),
                最大買い枚数=int(long.max()), 最大売り枚数=int(short.max()), 場末建玉=0,
                注文は次行以降=True, 現金と建玉による全行時価評価一致=True)


def truncate_ready(ready: dict, count: int) -> dict:
    """機能: 原本行に対応する配列だけを先頭から指定件数へ切り詰める。

    引数: ready (dict)、count (int)。返り値: 原本を変更しない入力のコピー (dict)。
    """
    n = len(ready['last'])
    return {key: (value[:count].copy() if isinstance(value, np.ndarray) and value.ndim and len(value) == n else value)
            for key, value in ready.items()}


def check_execution_prefix(engine, ready: dict, direction: np.ndarray, config: dict,
                           result: dict, fractions: tuple = (.25, .5, .75)) -> dict:
    """機能: 未来の原本を消しても過去の注文と資産曲線が変わらないか照合する。

    引数: engine (module)、ready/config/result (dict)、direction (ndarray)、fractions (tuple[float])。
    返り値: 切断点と合致件数 (dict)。途中切断時に場末返済を作らないことも確認する。
    """
    records = []
    for fraction in fractions:
        count = max(1, int(len(direction) * fraction))
        short = engine.run(truncate_ready(ready, count), direction[:count], config, detail=True)
        np.testing.assert_allclose(short['curve'], result['curve'][:count], rtol=0, atol=1e-7)
        for name, row_column in [('orders', 0), ('trades', 7), ('cycles', 2)]:
            expected = result[name][result[name][:, row_column] < count]
            np.testing.assert_allclose(short[name], expected, rtol=0, atol=1e-7)
        records.append(dict(切断行=count, 注文件数=len(short['orders']), 過去不変=True))
    return dict(切断比較=records)
