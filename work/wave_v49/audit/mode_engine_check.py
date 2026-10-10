"""自動モード試作器の過去約定禁止・注文会計・因果性を確認する。"""

from __future__ import annotations

import importlib.util
import os
import sys

import numpy as np

from independent_audit import HERE, ROOT, read, save, sha


PATH = ROOT / 'work/wave_v49/modes/engine.py'
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'mode_numba_cache')
spec = importlib.util.spec_from_file_location('v49_mode_engine_audit', PATH)
engine = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = engine
spec.loader.exec_module(engine)


def arrays(prices: list, times: list, sides: list | None = None) -> tuple:
    """機能: 人工経路を試作器の配列へ変換する。

    引数: prices/times (list)、sides (list|None)。返り値: 入力11配列 (tuple)。
    """
    n = len(prices)
    direction = np.ones(n, np.int8) if sides is None else np.asarray(sides, np.int8)
    return (np.asarray(times, float), np.asarray(prices, float), np.repeat(10., n),
            (direction != 0).astype(np.int8), direction, np.zeros(n, np.int8),
            np.zeros(n), np.ones(n, np.bool_), np.zeros(n, np.int8), np.zeros(n), np.repeat(1000., n))


def run(data: tuple, *, limit: float, rules: tuple = (0, 0, 1, 0, 0, 0), flat: bool = True) -> tuple:
    """機能: 人工条件を固定設定で再生する。

    引数: data (tuple)、limit (float)、rules (tuple)、flat (bool)。返り値: 結果5配列 (tuple)。
    """
    return engine.replay(*data, limit, 1., 5, *rules, require_flat=flat)


def check_account(data: tuple, result: tuple) -> dict:
    """機能: 注文から現金・建玉・各行時価を別式で再構成する。

    引数: data/result (tuple)。返り値: 注文と時価の一致証跡 (dict)。
    """
    orders, trades, curve, modes, trace = result
    cash = position = 0.
    cursor = 0
    expected = np.zeros(len(curve))
    for row in range(len(curve)):
        while cursor < len(orders) and int(orders[cursor, 0]) == row:
            order = orders[cursor]
            assert 0 <= order[1] < row
            cash -= order[3] * order[4] * order[5]
            position += order[3] * order[4]
            assert position in (-5, 0, 5)
            cursor += 1
        expected[row] = cash + position * data[1][row]
        assert position == trace[row, 0] * 5
    np.testing.assert_allclose(curve, expected, atol=1e-8, rtol=0)
    assert position == 0
    np.testing.assert_allclose(sum(trades[:, 10]), cash, atol=1e-8, rtol=0)
    assert len(trades) == len(modes)
    for trade in trades:
        np.testing.assert_allclose(trade[10], trade[2] * trade[3] * (trade[5] - trade[4]), atol=1e-8, rtol=0)
    for row in range(1, len(trace)):
        if trace[row, 0] and trace[row - 1, 0] and trace[row, 2] == trace[row - 1, 2]:
            assert trace[row, 0] * (trace[row, 6] - trace[row - 1, 6]) >= -1e-8
        if trace[row, 11]:
            assert trace[row, 18] == int(trace[row, 11] * (data[1][row] - trace[row, 12]) >= -1e-8)
    return dict(注文数=len(orders), 完済組数=len(trades), 全行会計一致=True,
                保有枚数一致=True, ストップ緩和なし=True, 判断後約定=True)


def reflect(data: tuple, center: float) -> tuple:
    """機能: 価格と方向を上下反射する。

    引数: data (tuple)、center (float)。返り値: 反射入力 (tuple)。
    """
    result = [value.copy() for value in data]
    result[1] = center - result[1]
    for index in (4, 5, 6, 8):
        result[index] *= -1
    result[9], result[10] = center - data[10], center - data[9]
    return tuple(result)


def prefix(left: tuple, right: tuple, count: int) -> None:
    """機能: 確定済みの注文・完済・時価・状態を比較する。

    引数: left/right (tuple)、count (int)。返り値: なし (None)。
    """
    for index, column in ((0, 0), (1, 7)):
        np.testing.assert_allclose(left[index][left[index][:, column] < count],
                                   right[index][right[index][:, column] < count], atol=1e-8, rtol=0)
    np.testing.assert_array_equal(left[3][left[1][:, 7] < count], right[3][right[1][:, 7] < count])
    np.testing.assert_allclose(left[2][:count], right[2][:count], atol=1e-8, rtol=0)
    np.testing.assert_allclose(left[4][:count], right[4][:count], atol=1e-8, rtol=0, equal_nan=True)


def check() -> dict:
    """機能: 人工反例と規則の組合せを検査する。

    引数: なし。返り値: 全検査の証跡 (dict)。
    """
    records = []
    path = arrays([100, 102, 117, 105, 104, 104, 104], [0, 1, 2, 1802, 1803, 1900, 1901],
                  [1, 1, 1, 1, 0, 0, 0])
    for mirrored in (False, True):
        data = reflect(path, 200.) if mirrored else path
        result = run(data, limit=1900.)
        assert len(result[1]) == 1
        expected = 96. if mirrored else 104.
        assert result[1][0, 5] == expected
        assert result[0][-1, 0] == 4 and result[0][-1, 1] == 3
        assert result[4][3, 9] == 2
        records.append(dict(検査='既成立の時間短縮stopを次行価格で返済', 売り=mirrored,
                            返済価格=expected, **check_account(data, result)))
        cut = tuple(value[:4].copy() for value in data)
        prefix(result, run(cut, limit=1900., flat=False), 4)
    # ----------------------------------------
    # 既設注文は現在行の取消を遡及適用せず、前行までの取消は約定を止める。
    for early in (False, True):
        data = arrays([100, 100, 102, 102, 102], [0, 1, 1, 1900, 1901],
                      [1, 0 if early else 1, 0, 0, 0])
        result = run(data, limit=1900.)
        assert len(result[1]) == (0 if early else 1)
        records.append(dict(検査='同秒原本群の新規取消', 前行取消=early, **check_account(data, result)))
    # ----------------------------------------
    # 方向・板・反転・出口の組合せを変え、反射と途中切断、未来改変を照合する。
    n = 900
    times = np.repeat(np.arange(n // 3, dtype=float), 3) * 10
    prices = 1000. + np.round(14 * np.sin(np.arange(n) / 18) + np.arange(n) * .01)
    mode = np.where((np.arange(n) // 180) % 2 == 0, 1, 2).astype(np.int8)
    trend = np.where((np.arange(n) // 90) % 2 == 0, 1, -1).astype(np.int8)
    ranges = np.where(prices >= 1005, -1, 1).astype(np.int8)
    data = (times, prices, np.repeat(10., n), mode, trend, ranges, .3 * ranges,
            np.ones(n, np.bool_), ranges, np.repeat(985., n), np.repeat(1015., n))
    fixed = read(ROOT / 'work/wave_v49/modes/方式の事前固定.json')
    variants = [tuple(row[k] for k in ('mode_choice', 'book_rule', 'exit_rule', 'flip_rule', 'mode_exit', 'sr_rule'))
                for row in fixed['方式']]
    assert len(variants) == 20
    for rules in variants:
        result = run(data, limit=times[-4], rules=rules)
        proof = check_account(data, result)
        mirror = run(reflect(data, 3000.), limit=times[-4], rules=rules)
        np.testing.assert_allclose(result[2], mirror[2], atol=1e-8, rtol=0)
        np.testing.assert_allclose(result[1][:, 10], mirror[1][:, 10], atol=1e-8, rtol=0)
        np.testing.assert_array_equal(result[3], mirror[3])
        count = 437
        clipped = run(tuple(value[:count].copy() for value in data), limit=times[-4], rules=rules, flat=False)
        prefix(result, clipped, count)
        changed = [value.copy() for value in data]
        changed[1][count:] += 100 + np.arange(n - count)
        changed[2][count:] *= 3
        for index in (4, 5, 6, 8):
            changed[index][count:] *= -1
        altered = run(tuple(changed), limit=times[-4], rules=rules)
        prefix(result, altered, count)
        records.append(dict(検査='規則組合せの会計因果反射', 規則=list(rules),
                            途中切断一致=True, 同秒群途中切断=True, 未来改変一致=True, 上下反射一致=True, **proof))
    output = dict(全合格=True, ケース数=len(records), 結果=records, エンジンSHA256=sha(PATH),
                  返却列=list(engine.TRACE_COLUMNS), 注意='損益を評価する人工条件ではなく、注文と会計の実装監査。')
    save('自動モード注文器の人工監査.json', output)
    return output


if __name__ == '__main__':
    result = check()
    print({key:value for key,value in result.items() if key not in ('結果', '返却列')})
