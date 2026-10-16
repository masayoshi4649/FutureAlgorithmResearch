"""101監査の厳密配列比較と会計公差を分離する。"""

import hashlib
import numpy as np


def array_sha(value: np.ndarray) -> str:
    """
    機能: 保存台帳の生配列指紋を独立計算する。
    引数: value(ndarray)は数値配列。
    返り値: str。原バイトSHA256。
    """
    return hashlib.sha256(value.tobytes()).hexdigest()


def exact(actual: object, expected: object, label: str = '') -> None:
    """
    機能: 注文・源・数量・状態を公差なしで比較する。
    引数: actual/expected(object)、label(str)は不一致箇所。
    返り値: None。不一致は例外。
    """
    np.testing.assert_array_equal(actual, expected, err_msg=label)


def money(actual: object, expected: object, label: str = '') -> None:
    """
    機能: 演算順だけが違う現金会計を旧監査と同じ絶対公差で比較する。
    引数: actual/expected(object)、label(str)。
    返り値: None。絶対1e-5を超す金額差で例外。数量・源には適用しない。
    """
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-5, equal_nan=True, err_msg=label)


def same(actual: object, expected: object, label: str = '') -> None:
    """
    機能: JSON会計の構造を厳密比較し、金額だけ会計公差を適用する。
    引数: actual/expected(object)、label(str)。
    返り値: None。キー・列・文字又は金額の不一致で例外。
    """
    if isinstance(actual, dict) and isinstance(expected, dict):
        assert actual.keys() == expected.keys(), label
        for key in actual:
            same(actual[key], expected[key], label+'/'+str(key))
    elif isinstance(actual, (list,tuple)) and isinstance(expected, (list,tuple)):
        assert len(actual) == len(expected), label
        for index,(left,right) in enumerate(zip(actual,expected)):
            same(left,right,label+'/'+str(index))
    elif isinstance(actual,(int,float)) and isinstance(expected,(int,float)):
        money(actual,expected,label)
    else:
        assert actual == expected, label


def prepared_sha(prepared: dict) -> str:
    """
    機能: 共有入力の全配列・型・形・入れ子キーを読み取って結合指紋を作る。
    引数: prepared(dict)は原板/源/信号/保存始値の共有素材。
    返り値: str。前後の指紋一致で共有配列の不変を確認する。
    """
    digest = hashlib.sha256()
    def visit(value: object) -> None:
        """
        機能: 入れ子を決定的なキー順で読取し、外側のdigestだけを更新する。
        引数: value(object)は配列、辞書、列又は通常値。
        返り値: None。対象配列を書き換えない。
        """
        if isinstance(value,np.ndarray):
            digest.update(repr((value.dtype.str,value.shape)).encode('utf-8'))
            digest.update(value.tobytes())
        elif isinstance(value,dict):
            for key in sorted(value,key=repr):
                digest.update(repr(key).encode('utf-8'))
                visit(value[key])
        elif isinstance(value,(list,tuple)):
            for item in value:
                visit(item)
        else:
            digest.update(repr(value).encode('utf-8'))
    visit(prepared)
    return digest.hexdigest()
