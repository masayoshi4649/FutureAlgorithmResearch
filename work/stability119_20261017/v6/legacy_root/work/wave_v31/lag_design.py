"""方向情報だけの30・60分遅延と、開始待ちだけの対照を固定する。"""

from __future__ import annotations

import numpy as np


def catalog() -> list[dict]:
    """機能: 元配列・二つの古い方向・二つの開始待ちを列挙する。

    引数: なし。返り値: 成績を参照しない5変形 (list[dict])。
    """
    return [
        {'id': 'V000', 'name': '元の方向情報', 'delay_seconds': 0., 'mode': 'identity'},
        {'id': 'V030', 'name': '30分古い方向情報', 'delay_seconds': 1800., 'mode': 'lag'},
        {'id': 'V060', 'name': '60分古い方向情報', 'delay_seconds': 3600., 'mode': 'lag'},
        {'id': 'W030', 'name': '30分遅延信号の初回まで待ち、以後は現在情報', 'delay_seconds': 1800., 'mode': 'start_only'},
        {'id': 'W060', 'name': '60分遅延信号の初回まで待ち、以後は現在情報', 'delay_seconds': 3600., 'mode': 'start_only'},
    ]


def transform(times: np.ndarray, entry: np.ndarray, main: np.ndarray,
              own: np.ndarray, variant: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """機能: 同一セッション内で入口と二つの保有方向を因果的に変換する。

    引数: times (ndarray[float]) は記録時刻、entry/main/own (ndarray[int8]) は公開済み方向、variant (dict) は固定変形。
    返り値: 変換入口・両市場・自己・参照元行 (tuple[ndarray, ndarray, ndarray, ndarray])。
    注意: Wの参照元行は解放条件に使う過去行。解放後の方向そのものは現在行を参照する。
    """
    n = len(times)
    assert n > 0 and np.all(np.diff(times) >= 0)
    assert all(v.shape == (n,) and v.dtype == np.int8 and np.isin(v, [-1, 0, 1]).all() for v in (entry, main, own))
    delay, mode = variant['delay_seconds'], variant['mode']
    if mode == 'identity':
        assert delay == 0
        return entry.copy(), main.copy(), own.copy(), np.arange(n, dtype=np.int64)
    assert mode in ('lag', 'start_only') and delay > 0
    source = np.searchsorted(times, times - delay, side='right') - 1
    valid = source >= 0
    assert np.all(source[valid] < np.flatnonzero(valid))
    assert np.all(times[source[valid]] <= times[valid] - delay)
    delayed = []
    for value in (entry, main, own):
        output = np.zeros(n, dtype=np.int8)
        output[valid] = value[source[valid]]
        delayed.append(output)
    if mode == 'lag':
        return *delayed, source
    # ----------------------------------------
    # 一度でも遅延入口が非0になった現在行から解放する。末尾の最初の信号を過去へ返さない。
    gate = np.maximum.accumulate(delayed[0] != 0)
    current = [np.where(gate, value, 0).astype(np.int8) for value in (entry, main, own)]
    return *current, source
