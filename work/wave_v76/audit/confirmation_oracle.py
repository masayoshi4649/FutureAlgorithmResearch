"""有効な同一状態の継続時間を、時計差で独立算定する。"""

from __future__ import annotations

import numpy as np

from independent_account import save, HERE


def durations(times: np.ndarray, states: np.ndarray, valid: np.ndarray, step: float = 5.) -> np.ndarray:
    """機能: 同一有効状態が連続した時計差を、行数に置換せず計算する。

    引数: times(np.ndarray[float])、states(np.ndarray[int])、valid(np.ndarray[bool])、step(float)。
    返り値: 継続秒数(np.ndarray[float])。無効は-1、初回や状態変化は0。
    中立や矛盾の状態値にも対応し、意味に応じて被検査器への接続側で分類する。
    """
    times, states, valid = np.asarray(times), np.asarray(states), np.asarray(valid, dtype=bool)
    assert len(times) == len(states) == len(valid)
    assert np.all(np.isfinite(times)) and np.all(np.diff(times) > 0) and step > 0
    output = np.full(len(times), -1., dtype=float)
    start = None
    for row in range(len(times)):
        if not valid[row]:
            start = None
            continue
        same = row > 0 and valid[row - 1] and states[row] == states[row - 1]
        continuous = row > 0 and abs(float(times[row] - times[row - 1]) - step) <= 1.e-7
        if start is None or not same or not continuous:
            start = float(times[row])
        output[row] = float(times[row]) - start
    return output


def confirmed(times: np.ndarray, states: np.ndarray, valid: np.ndarray, seconds: float, step: float = 5.) -> np.ndarray:
    """機能: 有効同一状態の継続が指定秒数以上になった原本格子を判定する。

    引数: times/states/valid(np.ndarray)、seconds/step(float)。
    返り値: 条件達成行(np.ndarray[bool])。状態値を入口や返済方向と解釈しない。
    """
    assert seconds >= 0
    return durations(times, states, valid, step) >= seconds


def confirmed_progress(times: np.ndarray, states: np.ndarray, valid: np.ndarray,
        own_source: np.ndarray, peer_source: np.ndarray, seconds: float, step: float = 5.) -> np.ndarray:
    """機能: 同一状態の連続時間と、両銘柄の原本参照行更新を独立判定する。

    引数: times/states/valid/own_source/peer_source(np.ndarray)、seconds/step(float)。
    返り値: 確認成立行(np.ndarray[bool])。確認開始から両側の参照行が進むことを要求する。
    瞬時snapshot入口は別仕様であり、この更新必須関数へ接続しない。
    """
    assert len(times) == len(states) == len(valid) == len(own_source) == len(peer_source)
    assert seconds >= 0
    eligible = np.asarray(valid, dtype=bool) & (own_source >= 0) & (peer_source >= 0)
    duration = durations(times, states, eligible, step)
    result = np.zeros(len(times), dtype=bool)
    start = None
    for row, elapsed in enumerate(duration):
        if elapsed < 0:
            start = None
            continue
        if elapsed == 0:
            start = row
        assert start is not None
        result[row] = elapsed >= seconds and own_source[row] > own_source[start] and peer_source[row] > peer_source[start]
    return result


def self_test() -> None:
    """機能: 15/30秒境界・欠測・中立・矛盾・格子欠落を人工検査する。

    引数: なし。返り値: なし(None)。将来のモデル損益は読み込まない。
    """
    checks = 0
    t = np.arange(0., 85., 5.)
    for seconds in (15., 30.):
        state = np.ones(len(t), dtype=np.int8)
        valid = np.ones(len(t), dtype=bool)
        result = durations(t, state, valid)
        np.testing.assert_array_equal(result, t)
        assert np.flatnonzero(confirmed(t, state, valid, seconds))[0] == seconds / 5
        checks += 2
        # ----------------------------------------
        # 1回の欠測・格子欠落で、それ以前の確認時間を破棄する。
        valid[2] = False
        np.testing.assert_array_equal(durations(t, state, valid)[:7], [0., 5., -1., 0., 5., 10., 15.])
        checks += 1
        valid[:] = True
        gap = np.delete(np.arange(len(t)), 2)
        np.testing.assert_array_equal(durations(t[gap], state[gap], valid[gap])[:6], [0., 5., 0., 5., 10., 15.])
        checks += 1
        # ----------------------------------------
        # 中立0・矛盾2・逆方向-1は別状態とし、直接引継ぎを禁止する。
        for token in (0, 2, -1):
            changed = state.copy()
            changed[2] = token
            np.testing.assert_array_equal(durations(t, changed, valid)[:7], [0., 5., 0., 0., 5., 10., 15.])
            checks += 1
    assert not len(durations(np.array([]), np.array([]), np.array([], dtype=bool)))
    checks += 1
    # ----------------------------------------
    # 時間だけ進んだ同一snapshot、片側だけ更新、両側更新を区別する。
    state, valid = np.ones(len(t), dtype=np.int8), np.ones(len(t), dtype=bool)
    own = np.full(len(t), 10, dtype=np.int64)
    peer = np.full(len(t), 100, dtype=np.int64)
    assert not confirmed_progress(t, state, valid, own, peer, 15.).any()
    checks += 1
    own[2:] = 11
    assert not confirmed_progress(t, state, valid, own, peer, 15.).any()
    checks += 1
    peer[3:] = 101
    np.testing.assert_array_equal(np.flatnonzero(confirmed_progress(t, state, valid, own, peer, 15.)), np.arange(3, len(t)))
    checks += 1
    valid[4] = False
    assert not confirmed_progress(t, state, valid, own, peer, 15.)[4:].any()
    checks += 1
    save(HERE / "確認時間参照器の自己検査.json", dict(合格=True, 人工検査数=checks,
        方式="有効同状態の連続5秒格子を時計差で算定し、確認中の両側参照行更新も別判定。欠測・状態変更・格子欠落で破棄。",
        注意="モデル実装の検査前に参照器だけを検査した記録。モデル合格を意味しない。",
        原本取得=0, API取得=0, 実注文=0))


if __name__ == "__main__":
    self_test()
