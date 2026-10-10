"""公開標本の数量差分を、状態更新を使わない配列式で独立再計算する。"""

from __future__ import annotations

from copy import deepcopy
import math

import numpy as np


def numeric(value: object) -> float:
    """機能: 欠測とは区別して、有限の非負数量を検査する。

    引数: value (object)。返り値: 有限非負値 (float)。不正値はAssertionError。
    """
    assert isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, (bool, np.bool_))
    number = float(value)
    assert math.isfinite(number) and number >= 0
    return number


def close(actual: float, expected: object, label: str) -> float:
    """機能: 配列集計と保存値を比較し、浮動小数点の丸め差だけ許す。

    引数: actual (float)、expected (object)、label (str)。返り値: 符号付き差 (float)。
    """
    saved = numeric(expected)
    assert math.isclose(actual, saved, rel_tol=1e-12, abs_tol=1e-12), (label, actual, saved)
    return actual - saved


def verify(trial: dict) -> dict:
    """機能: 旧試行の公開標本だけから減少・最初の減少後の増加・比率を検算する。

    引数: trial (dict)。samples、complete、decrease、increase_after_decrease、recovery_ratioが必須。
    返り値: 独立計算値と保存値との差 (dict)。入力を書き換えず、通信や売買を行わない。
    隣接差分は両端の数量が既知のときだけ有効。比率は完了・全数量既知・減少正のときだけ定義する。
    """
    assert isinstance(trial, dict) and isinstance(trial['samples'], list)
    assert isinstance(trial['complete'], (bool, np.bool_))
    samples = trial['samples']
    valid = np.array([s['quantity'] is not None for s in samples], dtype=bool)
    quantities = np.array([numeric(s['quantity']) if ok else np.nan
                           for s, ok in zip(samples, valid)], dtype=np.float64)
    known = bool(valid.all())
    # ----------------------------------------
    # 全差分を一度に作り、最初の負差分の位置より後にある正差分だけを集計する。
    adjacent = valid[1:] & valid[:-1]
    differences = np.diff(quantities)
    usable = np.where(adjacent, differences, 0.)
    negatives = np.flatnonzero(usable < 0)
    decrease = float(np.sum(np.maximum(-usable, 0.)))
    increase = float(np.sum(np.maximum(usable[negatives[0] + 1:], 0.))) if len(negatives) else 0.
    ratio = increase / decrease if trial['complete'] and known and decrease > 0 else None
    delta_d = close(decrease, trial['decrease'], '減少量')
    delta_i = close(increase, trial['increase_after_decrease'], '最初の減少後の増加量')
    if ratio is None:
        assert trial['recovery_ratio'] is None, '未完了・欠測・減少ゼロの比率は不明'
        delta_u = None
    else:
        delta_u = close(ratio, trial['recovery_ratio'], '回復比率')
    if 'sample_count' in trial:
        assert trial['sample_count'] == len(samples)
    if 'quantity_known' in trial:
        assert isinstance(trial['quantity_known'], (bool, np.bool_))
        assert bool(trial['quantity_known']) == known
    if 'quantity_start' in trial:
        expected_start = samples[0]['quantity'] if samples else None
        if expected_start is None:
            assert trial['quantity_start'] is None
        else:
            close(float(expected_start), trial['quantity_start'], '試行開始数量')
    return dict(decrease=decrease, increase_after_decrease=increase, recovery_ratio=ratio,
                quantity_known=known, sample_count=len(samples),
                difference=dict(decrease=delta_d, increase_after_decrease=delta_i, recovery_ratio=delta_u))


def selftest() -> dict:
    """機能: 手計算した8経路と保存値の改変を使い、独立式の境界を確認する。

    引数: なし。返り値: 合格件数・不正値の拒否証跡 (dict)。実相場を読まない。
    """
    cases = (
        ('最初の減少前の増加を除外', [5., 9., 6., 8.], True, 3., 2., 2. / 3.),
        ('複数の減少と増加', [10., 4., 7., 2., 9.], True, 11., 10., 10. / 11.),
        ('減少後の欠測を跨がない', [10., 5., None, 30., 32., 28.], True, 9., 2., None),
        ('開始欠測も不明', [None, 100., 80., 90.], True, 20., 10., None),
        ('減少ゼロ', [0., 0., 3., 3.], True, 0., 0., None),
        ('未完了は比率未定義', [10., 5., 8.], False, 5., 3., None),
        ('単一標本', [7.], True, 0., 0., None),
        ('標本なし', [], False, 0., 0., None),
    )
    results = []
    material = []
    for name, quantities, complete, decrease, increase, ratio in cases:
        trial = dict(samples=[dict(quantity=q) for q in quantities], complete=complete,
                     decrease=decrease, increase_after_decrease=increase, recovery_ratio=ratio,
                     quantity_known=all(q is not None for q in quantities), sample_count=len(quantities),
                     quantity_start=quantities[0] if quantities else None)
        previous = deepcopy(trial)
        got = verify(trial)
        assert trial == previous
        results.append(dict(検査=name, 全一致=True, **got))
        material.append(trial)
    # ----------------------------------------
    # 未定義をゼロへ偽装、欠測跨ぎ、最初の減少前の増加混入を受け入れない。
    rejected = []
    changes = (
        ('減少量改変', 0, 'decrease', 4.),
        ('最初の減少前の増加混入', 0, 'increase_after_decrease', 6.),
        ('比率改変', 0, 'recovery_ratio', 1.),
        ('欠測比率をゼロに偽装', 2, 'recovery_ratio', 0.),
        ('欠測跨ぎの増加', 2, 'increase_after_decrease', 27.),
        ('未完了なのに比率設定', 5, 'recovery_ratio', .6),
        ('減少ゼロなのに比率設定', 4, 'recovery_ratio', 0.),
        ('欠測品質を既知に偽装', 3, 'quantity_known', True),
    )
    for name, index, field, value in changes:
        trial = deepcopy(material[index])
        trial[field] = value
        try:
            verify(trial)
        except AssertionError:
            rejected.append(name)
        else:
            raise AssertionError('保存値改変を受け入れた: ' + name)
    for value in (float('nan'), float('inf'), -1., True):
        trial = deepcopy(material[0])
        trial['samples'][0]['quantity'] = value
        try:
            verify(trial)
        except AssertionError:
            rejected.append('不正数量:' + str(value))
        else:
            raise AssertionError('不正数量を受け入れた')
    return dict(全合格=True, 人工検査数=len(results), 改変拒否数=len(rejected),
                結果=results, 改変拒否=rejected, 新損益再生=False, API取得数=0)


if __name__ == '__main__':
    import json
    print(json.dumps(selftest(), ensure_ascii=False, allow_nan=False, indent=2))
