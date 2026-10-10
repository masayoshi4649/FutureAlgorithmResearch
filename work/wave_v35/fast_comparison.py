"""監査の比較内容を保ったまま、数値配列の一致検査だけを一巡で実行する。"""

from __future__ import annotations

import numpy as np
from numba import njit

ORIGINAL_CLOSE = np.testing.assert_allclose
ORIGINAL_EQUAL = np.testing.assert_array_equal


@njit(cache=True)
def _equal(a: np.ndarray, b: np.ndarray, count: int) -> bool:
    """機能: 同型数値配列の同値とNaN位置を一巡で検査する。

    引数: a/b (一次元ndarray)、count (int)。返り値: 一致 (bool)。
    """
    for i in range(count):
        x, y = a[0 if len(a) == 1 else i], b[0 if len(b) == 1 else i]
        if x != y and not (np.isnan(x) and np.isnan(y)):
            return False
    return True


@njit(cache=True)
def _close(a: np.ndarray, b: np.ndarray, count: int, atol: float, rtol: float, equal_nan: bool) -> bool:
    """機能: 基準側の絶対値を用いた同じ許容式で配列を一巡比較する。

    引数: a/b (一次元float64配列)、count (int)、atol/rtol (float)、equal_nan (bool)。
    返り値: 全値が許容範囲内 (bool)。NaN位置・無限大の符号を保持する。
    """
    for i in range(count):
        x, y = a[0 if len(a) == 1 else i], b[0 if len(b) == 1 else i]
        if x == y:
            continue
        if np.isnan(x) or np.isnan(y):
            if equal_nan and np.isnan(x) and np.isnan(y):
                continue
            return False
        if not np.isfinite(x) or not np.isfinite(y) or not abs(x - y) <= atol + rtol * abs(y):
            return False
    return True


def _shape(actual: object, desired: object, strict: bool) -> tuple | None:
    """機能: 旧比較器の形状と厳密型条件に一致する数値入力だけを選ぶ。

    引数: actual/desired (object)、strict (bool)。返り値: 配列と比較数 (tuple|None)。
    """
    a, b = np.asanyarray(actual), np.asanyarray(desired)
    if type(a) is not np.ndarray or type(b) is not np.ndarray:
        return None
    if strict and (a.shape != b.shape or a.dtype != b.dtype):
        return None
    if a.shape != b.shape and a.ndim and b.ndim:
        return None
    if a.dtype.kind not in 'biuf' or b.dtype.kind not in 'biuf':
        return None
    count = a.size if a.ndim else b.size
    return a, b, count


def assert_array_equal(actual, desired, err_msg='', verbose=True, *, strict=False) -> None:
    """機能: 数値同型の一致を高速確認し、対象外・不一致時は元比較器へ委譲する。

    引数: actual/desired (object)、err_msg (str)、verbose/strict (bool)。返り値: なし (None)。
    """
    prepared = _shape(actual, desired, strict)
    if prepared is not None:
        a, b, count = prepared
        if a.dtype == b.dtype and a.dtype != np.float16 and _equal(a.ravel(), b.ravel(), count):
            return
    ORIGINAL_EQUAL(actual, desired, err_msg=err_msg, verbose=verbose, strict=strict)


def assert_allclose(actual, desired, rtol=1e-7, atol=0, equal_nan=True, err_msg='', verbose=True, *, strict=False) -> None:
    """機能: float64又は整数の許容比較を高速化し、低精度等は元比較器を保つ。

    引数: actual/desired (object)、rtol/atol (float)、equal_nan/verbose/strict (bool)、err_msg (str)。
    返り値: なし (None)。float32の丸めや異型文字比較の意味を変更しない。
    """
    prepared = _shape(actual, desired, strict)
    if prepared is not None and np.ndim(atol) == np.ndim(rtol) == 0 and np.isfinite(atol) and np.isfinite(rtol) and atol >= 0 and rtol >= 0:
        a, b, count = prepared
        supported = all(v.dtype.kind in 'biu' or v.dtype == np.dtype('float64') for v in (a, b))
        if supported and _close(np.asarray(a, float).ravel(), np.asarray(b, float).ravel(), count, float(atol), float(rtol), bool(equal_nan)):
            return
    ORIGINAL_CLOSE(actual, desired, rtol=rtol, atol=atol, equal_nan=equal_nan, err_msg=err_msg, verbose=verbose, strict=strict)


def install() -> None:
    """機能: この監査プロセス内だけで比較器を差し替える。

    引数: なし。返り値: なし (None)。旧ファイル・注文器・別プロセスには変更を加えない。
    """
    np.testing.assert_allclose = assert_allclose
    np.testing.assert_array_equal = assert_array_equal


def self_test() -> dict:
    """機能: NaN・無限大・形状・型・許容境界の旧判定との同値を人工配列で確認する。

    引数: なし。返り値: 合成判定数と結果 (dict)。
    """
    def passed(function, left, right, **kwargs):
        """機能: 比較の成否と例外型を記録する。

        引数: function (callable)、left/right (object)、kwargs (dict)。返り値: 判定 (str)。
        """
        try:
            with np.errstate(all='ignore'):
                function(left, right, **kwargs)
            return '一致'
        except Exception as exc:
            return type(exc).__name__
    cases = []
    for dtype in (np.bool_, np.int8, np.int64, np.uint64, np.float16, np.float32, np.float64):
        a = np.arange(12).astype(dtype).reshape(3, 4)
        cases += [(a, a.copy()), (a[:, ::2], a[:, ::2].copy()), (a, a.reshape(-1)), (a, a[:1]),
                  (a, a.astype(float)), (np.array([], dtype=dtype), np.array([], dtype=dtype)),
                  (np.zeros((2, 3), dtype=dtype), np.array(0, dtype=dtype))]
        b = a.copy(); b.flat[-1] = 0
        cases.append((a, b))
    cases += [(np.array(a, float), np.array(b, float)) for a, b in (
        ([np.nan, np.inf, -np.inf, -0.], [np.nan, np.inf, -np.inf, 0.]),
        ([np.nan, 1.], [1., np.nan]), ([np.inf], [-np.inf]), ([1e308], [-1e308]),
        ([1.], [1. + 1e-6]), ([1.], [1. + 1.0000001e-6]),
        ([], [0.]), ([0.], []), ([0.], [1e-308]))]
    cases += [(1., np.zeros(0)), (np.zeros(0), 1.), (np.array(1), np.array(1.)),
              (np.array(['あ']), np.array(['い'])), (np.array([1 + 2j]), np.array([1 + 2j]))]
    comparisons = 0
    for a, b in cases:
        for strict in (False, True):
            assert passed(ORIGINAL_EQUAL, a, b, strict=strict) == passed(assert_array_equal, a, b, strict=strict)
            comparisons += 1
            for atol, rtol, equal_nan in ((0., 0., True), (1e-6, 0., True), (1e-6, .2, True), (0., 0., False),
                (np.inf, 0., True), (0., np.inf, True), (np.nan, 0., True), (-1., 0., True)):
                kwargs = dict(atol=atol, rtol=rtol, equal_nan=equal_nan, strict=strict)
                assert passed(ORIGINAL_CLOSE, a, b, **kwargs) == passed(assert_allclose, a, b, **kwargs), (a, b, kwargs)
                comparisons += 1
    return dict(全判定一致=True, 比較数=comparisons, NaN位置=True, 無限大符号=True, 形状型=True, 基準側rtol=True,
        低精度旧比較委譲=True, 空配列とscalar=True, 旧ファイル変更=False, 売買条件変更=False)
