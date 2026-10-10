"""売買を再生せず、順行開始ゲートの人工経路と情報境界を独立確認する。"""

from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np
import profit_gate as target

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def fingerprint(path: Path) -> str:
    """機能: 読取実装の内容を固定する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(price: np.ndarray, cuts: tuple[int, ...] = ()) -> tuple:
    """機能: 手計算可能な買い影計画を作り、指定行で組を分ける。

    引数: price (ndarray)、cuts (tuple[int,...])。返り値: ready/影/悪化/公開行/品質 (tuple)。
    """
    n = len(price); plans = np.zeros((n, 37)); previous = 0; group = 0
    for stop in (*cuts, n):
        anchor = price[previous]
        plans[previous:stop, 0] = 1; plans[previous:stop, 1] = group
        plans[previous:stop, 2] = 10.; plans[previous:stop, 3] = anchor
        plans[previous:stop, 5] = previous
        plans[previous:stop, 10] = np.maximum.accumulate(price[previous:stop])
        previous = stop; group += 1
    plans[:, 33] = np.arange(n)
    return (dict(last=price.copy(), time_s=np.floor(np.arange(n)/2), seq=np.arange(n)*3),
            dict(plans=plans), np.full(n, -1, np.int8), np.arange(n, dtype=np.int64), np.ones(n, bool))


def reference(args: tuple, threshold: float, mode: str) -> tuple:
    """機能: 組単位の配列演算で初回到達と許可を別計算する。

    引数: args (tuple)、threshold (float)、mode (str)。返り値: 方向と到達行 (tuple)。
    生成器の一行状態走査を使わず、区間内の有効候補集合から最初の行を得る。
    """
    ready, shadow, bad, source, valid = args
    if threshold == 0:
        return bad.copy(), np.full(len(bad), -1, np.int64)
    plans = shadow['plans']; n = len(bad); output = np.zeros(n, np.int8); arms = np.full(n, -1, np.int64)
    indices = np.arange(n)
    boundary = np.r_[0, np.flatnonzero(np.any(plans[1:, [0, 1, 5]] != plans[:-1, [0, 1, 5]], axis=1))+1, n]
    for begin, end in zip(boundary[:-1], boundary[1:]):
        rows = indices[begin:end]
        if not plans[begin, 0]:
            continue
        p = plans[rows]; price = ready['last'][rows]
        good = np.isfinite(price) & (price > 0) & np.isfinite(p[:, 2:4]).all(axis=1)
        good &= (p[:, 2] > 0) & (p[:, 3] > 0) & np.isfinite(p[:, 10]) & (p[:, 10] > 0)
        with np.errstate(divide='ignore', invalid='ignore'):
            reached = p[:, 0]*(p[:, 10]-p[:, 3])/p[:, 2] >= threshold
        first = rows[good & reached]
        if not len(first):
            continue
        arm = first[0]; arms[arm:end] = arm
        allowed = good & (rows >= arm) & (source[rows] > arm)
        selected = rows[allowed]
        if mode == 'any_valid':
            selected = selected[valid[selected]]; output[selected] = -plans[selected, 0]
        else:
            output[selected] = bad[selected]*(1 if mode == 'direction' else -1)
    return output, arms


def cut(args: tuple, end: int) -> tuple:
    """機能: 同時刻途中でも原本行で人工入力と影を切り出す。

    引数: args (tuple)、end (int)。返り値: 独立コピーした入力 (tuple)。
    """
    ready, shadow, bad, source, valid = args
    return ({k: v[:end].copy() for k, v in ready.items()},
            dict(plans=shadow['plans'][:end].copy()), bad[:end].copy(), source[:end].copy(), valid[:end].copy())


def run(args: tuple, threshold: float, mode: str = 'direction') -> tuple:
    """機能: 人工の同一入力を公開APIへ接続する。

    引数: args (tuple)、threshold (float)、mode (str)。返り値: API出力 (tuple)。
    """
    ready, shadow, bad, source, valid = args
    return target.gate_bad(ready, shadow, bad, source, threshold, mode=mode, valid=valid)


def main() -> None:
    """機能: 手計算、全閾値・方式、未来変更、反射、不正入力を人工で固定する。

    引数: なし。返り値: なし (None)。実損益資料・旧口座再生・現在APIは使わない。
    """
    source = ROOT/'work/wave_v38/engine_shadow_plan.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    columns = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'PLAN_COLUMNS' for t in node.targets))
    assert len(columns) == 37
    for name, index in target.PLAN_COLUMNS.items():
        assert columns[index] == name
    hand = fixture(np.array([100., 100., 110., 115., 114., 113., 118., 90., 100., 115., 114., 113.]), (8,))
    hand[3][2:5] = [1, 3, 3]
    actual = run(hand, 1.5)
    np.testing.assert_array_equal(actual[0], [0, 0, 0, 0, 0, -1, -1, -1, 0, 0, -1, -1])
    np.testing.assert_array_equal(actual[2]['arm_row'], [-1, -1, -1, 3, 3, 3, 3, 3, -1, 9, 9, 9])
    np.testing.assert_array_equal(actual[1], hand[3])
    # ----------------------------------------
    # 有効中立も許す対照と、到達前の古い公開を新しい行へ付け替えないこと。
    neutral = deepcopy(hand); neutral[2][:] = 0; neutral[4][6] = False
    any_direction = run(neutral, 1.5, 'any_valid')[0]
    np.testing.assert_array_equal(any_direction, [0, 0, 0, 0, 0, -1, 0, -1, 0, 0, -1, -1])
    stale = deepcopy(hand); stale[3][3:8] = 3
    assert not run(stale, 1.5)[0][:8].any()
    missing = deepcopy(hand); missing[0]['last'][3] = np.nan
    assert run(missing, 1.5)[2]['arm_row'][3] == -1
    assert run(missing, 1.5)[2]['arm_row'][4] == 4
    held_missing = deepcopy(hand); held_missing[0]['last'][5] = np.nan
    assert run(held_missing, 1.5)[2]['arm_row'][5] == 3 and run(held_missing, 1.5)[0][5] == 0
    flat = deepcopy(hand); flat[1]['plans'][7:9, 0] = 0
    assert not run(flat, 1.5)[0][7:9].any()
    no_hit = fixture(np.array([100., 100., 109., 90., 80.]))
    assert not run(no_hit, 1.)[0].any()
    invalid_scale = deepcopy(hand); invalid_scale[1]['plans'][:, 2] = np.nan
    assert not run(invalid_scale, 1.)[0].any()
    # ----------------------------------------
    # 方向だけを反転し、同じ根拠時刻・元方向0を保つ。
    pairs = [(0., 'direction')]+[(threshold, mode) for threshold in target.THRESHOLDS[1:] for mode in target.MODES]
    counts = dict(別式一致=0, prefix=0, 未来変更=0, 上下反射=0, 入力不変=0)
    fixtures = [hand, neutral, stale, missing, held_missing, flat, no_hit, invalid_scale]
    rng = np.random.default_rng(4401)
    for _ in range(20):
        sample = fixture(1000.+np.cumsum(rng.integers(-7, 9, 80)).astype(float), (20, 40, 60))
        sample[2][:] = rng.choice(np.array([-1, 0, 1], np.int8), 80)
        sample[4][:] = rng.random(80) > .15
        fixtures.append(sample)
    for args in fixtures:
        before = deepcopy(args)
        for threshold, mode in pairs:
            result = run(args, threshold, mode); expected, arms = reference(args, threshold, mode)
            np.testing.assert_array_equal(result[0], expected)
            np.testing.assert_array_equal(result[2]['arm_row'], arms)
            np.testing.assert_array_equal(result[1], args[3]); counts['別式一致'] += 1
            for end in sorted({max(1, len(args[2])*37//100), max(1, len(args[2])*73//100)}):
                prefix = run(cut(args, end), threshold, mode)
                for a, b in zip(prefix[:2], result[:2]):
                    np.testing.assert_array_equal(a, b[:end])
                for field in prefix[2]:
                    np.testing.assert_array_equal(prefix[2][field], result[2][field][:end])
                counts['prefix'] += 1
                future = deepcopy(args)
                future[0]['last'][end:] *= 1.7
                future[1]['plans'][end:, [2, 3, 10]] *= 1.5
                future[2][end:] *= -1; future[4][end:] = ~future[4][end:]
                future_result = run(future, threshold, mode)
                for a, b in zip(future_result[:2], result[:2]):
                    np.testing.assert_array_equal(a[:end], b[:end])
                for field in result[2]:
                    np.testing.assert_array_equal(future_result[2][field][:end], result[2][field][:end])
                counts['未来変更'] += 1
            mirrored = deepcopy(args); mirrored[0]['last'] = 5000.-mirrored[0]['last']
            mirrored[1]['plans'][:, 0] *= -1
            mirrored[1]['plans'][:, [3, 10]] = 5000.-mirrored[1]['plans'][:, [3, 10]]
            mirrored[2][:] *= -1
            reflected = run(mirrored, threshold, mode)
            np.testing.assert_array_equal(reflected[0], -result[0])
            np.testing.assert_array_equal(reflected[1], result[1])
            for field in result[2]:
                np.testing.assert_allclose(reflected[2][field], result[2][field], rtol=0, atol=1e-12)
            counts['上下反射'] += 1
        for old, current in zip(before, args):
            if isinstance(old, dict):
                for name in old: np.testing.assert_array_equal(old[name], current[name])
            else: np.testing.assert_array_equal(old, current)
        counts['入力不変'] += 1
    # ----------------------------------------
    # 無効仕様と未来sourceを拒否し、時間ラベルではなく原本行を使う。
    rejects = 0
    bad_cases = [(hand, .5, 'direction'), (hand, 0., 'inverse'), (hand, 0., 'any_valid'), (hand, 1., '未知')]
    for column, value in ((1, -1), (5, 1000), (33, 1000)):
        malformed = deepcopy(hand); malformed[1]['plans'][4, column] = value
        bad_cases.append((malformed, 1., 'direction'))
    invalid = deepcopy(hand); invalid[3][3] = 4; bad_cases.append((invalid, 1., 'direction'))
    for args, threshold, mode in bad_cases:
        try: run(args, threshold, mode)
        except ValueError: rejects += 1
        else: raise AssertionError('不正入力を受け入れました')
    try: target.gate_bad(*hand[:2], hand[2], hand[3], 1., mode='any_valid')
    except ValueError: rejects += 1
    else: raise AssertionError('公開品質なしの対照を受け入れました')
    proof = dict(全合格=True,手計算と品質境界8種類=True,同時刻別行と公開順序=True,
                 列契約一致=True,人工入力数=len(fixtures),仕様組合せ数=len(pairs),検査数=counts,
                 不正拒否数=rejects,新売買再生=False,実損益資料読取=False,API取得数=0,
                 参照SHA256={p.relative_to(ROOT).as_posix(): fingerprint(p) for p in
                              (Path(__file__), HERE/'profit_gate.py', source)})
    (HERE/'check_profit_gate.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
