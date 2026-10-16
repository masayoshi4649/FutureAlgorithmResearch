"""今回の独立監査だけへ読取・指紋・有限証跡の道具を提供する。"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SYMBOLS = ('TOPIX', 'NK225')
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'jit')


def module(name, path):
    """
    機能: 読取対象を固有名で読み込み既往成果の通常名と衝突させない。
    引数: name (str)、path (Path)。
    返り値: object のモジュール。
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
    機能: 保存資料から内容指紋を取得する。
    引数: path (Path)。
    返り値: str の SHA256。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def clean(value):
    """
    機能: 配列値を標準型へ揃え有限 JSON の証跡にする。
    引数: value (object)。
    返り値: object。
    """
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(item) for item in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    return value


def save(name, value):
    """
    機能: 今回の監査領域だけへ証跡を保存する。
    引数: name (str)、value (dict)。
    返り値: None。
    """
    path = HERE / name
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def fingerprint(paths):
    """
    機能: 読取入力と今回の監査コードの指紋を記録する。
    引数: paths (list[Path])。
    返り値: dict[str,str]。
    """
    return {str(path.relative_to(ROOT)): sha(path) for path in paths}


def same(a, b):
    """
    機能: 入れ子結果を配列・欠けた列も含めて独立比較する。
    引数: a/b (object)。
    返り値: None。
    """
    if isinstance(a, dict):
        assert a.keys() == b.keys(), (a.keys(), b.keys())
        for key in a:
            same(a[key], b[key])
    elif isinstance(a, (tuple, list)):
        assert len(a) == len(b)
        for first, second in zip(a, b):
            same(first, second)
    elif isinstance(a, np.ndarray):
        np.testing.assert_allclose(a, b, rtol=0, atol=1e-5, equal_nan=True)
    elif isinstance(a, (int, float, np.number)) and not isinstance(a, bool):
        np.testing.assert_allclose(a, b, rtol=0, atol=1e-5, equal_nan=True)
    else:
        assert a == b, (a, b)
