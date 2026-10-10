"""既存の固定A0注文器への接続を、未来と売買反射から検査する。"""

from __future__ import annotations

import numpy as np

import band_runner as runner


def clipped(ready: dict, count: int) -> dict:
    """機能: 原本行に対応する一次元配列だけを過去の接頭部に切る。

    引数: ready (dict)、count (int)。返り値: 接頭部の入力 (dict)。
    """
    size = len(ready['last'])
    return {k: v[:count].copy() if isinstance(v, np.ndarray) and v.ndim == 1 and len(v) == size else v
        for k, v in ready.items()}


def prefix_equal(reference: dict, actual: dict, count: int) -> None:
    """機能: 将来の切断・改変より前の全曲線と成立済み注文を比較する。

    引数: reference/actual (dict)、count (int)。返り値: なし (None)。
    """
    for name in ('curve', 'atr_curve'):
        assert np.array_equal(reference[name][:count], actual[name][:count], equal_nan=True), name
    for name, column in (('orders', 0), ('trades', 7), ('cycles', 2)):
        left, right = reference[name], actual[name]
        assert np.array_equal(left[left[:, column] < count], right[right[:, column] < count], equal_nan=True), name


def verify(ready: dict, state: np.ndarray, config: dict, result: dict, observed: bool,
           fractions: tuple[float, ...] = (.37,)) -> dict:
    """機能: 接頭部・未来価格ATR方向改変・買売反射を別経路で検査する。

    引数: ready/config/result (dict)、state (ndarray[int8])、observed (bool)、fractions (tuple[float,...])。
    返り値: 検査数 (dict)。信号計算自体の未来検査とは別の注文器接続検査。
    """
    count = len(ready['last'])
    for fraction in fractions:
        end = max(2, min(count - 1, int(count * fraction)))
        partial = clipped(ready, end)
        short = runner.base.engine.run(partial, state[:end].copy(), config, detail=True,
            width_mode=0, observed_fill=observed)
        prefix_equal(result, short, end)
        altered = dict(ready, last=ready['last'].copy(), atr=ready['atr'].copy())
        altered['last'][end:] += 17 * ready['tick']
        altered['atr'][end:] *= 1.7
        direction = state.copy()
        direction[end:] = np.where(direction[end:] == 0, 1, -direction[end:]).astype(np.int8)
        changed = runner.base.engine.run(altered, direction, config, detail=True, width_mode=0, observed_fill=observed)
        prefix_equal(result, changed, end)
    # ----------------------------------------
    # 呼値に整合する価格鏡映で、上昇・下落の実装非対称を検査する。
    offset = 2 * np.ceil(np.max(ready['last']) / ready['tick']) * ready['tick']
    reflected = dict(ready, last=offset - ready['last'])
    mirror = runner.base.engine.run(reflected, -state, config, detail=True, width_mode=0, observed_fill=observed)
    runner.accounting.reconstruct(reflected, mirror, config['symbol'] if 'symbol' in config else ('TOPIX' if config['audit_cap'] == 10 else 'NK225'))
    for name, indexes in (('trades', [0, 1, 3, 6, 7, 8, 9, 10]), ('orders', [0, 1, 2, 4, 6, 7]), ('cycles', list(range(10)))):
        a, b = result[name], mirror[name]
        assert a.shape == b.shape
        if name == 'cycles':
            # 8列目だけが主方向。9列目の返済理由を含む他の値は対称に一致する。
            indexes = [0, 1, 2, 3, 4, 5, 6, 7, 9]
        np.testing.assert_allclose(a[:, indexes], b[:, indexes], rtol=0, atol=1e-6)
    np.testing.assert_allclose(result['cycles'][:, 8], -mirror['cycles'][:, 8], rtol=0, atol=0)
    np.testing.assert_allclose(result['trades'][:, 2], -mirror['trades'][:, 2], rtol=0, atol=0)
    np.testing.assert_allclose(result['trades'][:, 4:6], offset - mirror['trades'][:, 4:6], rtol=0, atol=1e-6)
    np.testing.assert_allclose(result['orders'][:, 3], -mirror['orders'][:, 3], rtol=0, atol=0)
    np.testing.assert_allclose(result['orders'][:, 5], offset - mirror['orders'][:, 5], rtol=0, atol=1e-6)
    np.testing.assert_allclose(result['curve'][:, [0, 1, 4]], mirror['curve'][:, [0, 1, 4]], rtol=0, atol=1e-6)
    np.testing.assert_allclose(result['curve'][:, [2, 3]], mirror['curve'][:, [3, 2]], rtol=0, atol=0)
    return dict(prefix=len(fractions), future=len(fractions), reflection=1)
