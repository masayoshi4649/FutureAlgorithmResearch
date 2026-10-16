"""今回の独立監査領域だけへ、読取・指紋・有限証跡の共通道具を提供する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SYMBOLS = ('TOPIX', 'NK225')
SOURCES = ('追従', '往復')


def module(name, path):
    """
    機能: 読取対象を固有名で読み込み、既往の成果へ書き込まない。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def sha(path):
    """
    機能: 大きな保存物から内容指紋を取得する。
    引数: path(Path)。
    返り値: strのSHA256。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def clean(value):
    """
    機能: NumPy値を同値の標準型へ揃え、証跡を有限JSONにする。
    引数: value(object)。
    返り値: object。
    """
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    return value


def save(name, value):
    """
    機能: 今回の監査領域だけへ証跡を保存する。
    引数: name(str)、value(dict)。
    返り値: None。
    """
    path = HERE / name
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def fingerprint(paths):
    """
    機能: 使用した読取入力と今回コードの指紋を記録する。
    引数: paths(list[Path])。
    返り値: dict[str,str]。
    """
    return {str(path.relative_to(ROOT)): sha(path) for path in paths}


def same(a, b):
    """
    機能: 入れ子の結果を、欠けたキーや配列を許さず比較する。
    引数: a/b(object)。
    返り値: None。
    """
    if isinstance(a, dict):
        assert a.keys() == b.keys(), (a.keys(), b.keys())
        for key in a:
            same(a[key], b[key])
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b), (len(a), len(b))
        for first, second in zip(a, b):
            same(first, second)
    elif isinstance(a, np.ndarray):
        np.testing.assert_allclose(a, b, rtol=0, atol=1e-6, equal_nan=True)
    elif isinstance(a, (int, float, np.number)) and not isinstance(a, bool):
        np.testing.assert_allclose(float(a), float(b), rtol=0, atol=1e-6, equal_nan=True)
    else:
        assert a == b, (a, b)
