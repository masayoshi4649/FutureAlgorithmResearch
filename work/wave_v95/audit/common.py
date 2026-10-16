"""95の独立監査領域へ、読取・有限JSON保存・厳密比較だけを提供する。"""

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


def module(name: str, path: Path) -> object:
    """
    機能: 読取モジュールを固有名で取り込み、通常import名の衝突を避ける。
    引数: name(str)。固有名。path(Path)。読取対象。
    返り値: object。読取モジュール。
    """
    if name in sys.modules:
        return sys.modules[name]
    specification = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(specification)
    sys.modules[name] = value
    specification.loader.exec_module(value)
    return value


def sha(path: Path) -> str:
    """
    機能: 保存資料の内容指紋を分割読取で求める。
    引数: path(Path)。対象ファイル。
    返り値: str。SHA256。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def fingerprint(paths: list[Path]) -> dict:
    """
    機能: 読取資料と監査コードの指紋を相対パスで記録する。
    引数: paths(list[Path])。対象ファイル列。
    返り値: dict[str,str]。相対パスとSHA256。
    """
    return {str(path.relative_to(ROOT)): sha(path) for path in paths}


def clean(value: object) -> object:
    """
    機能: 配列と数値型を有限JSONへ保存できる標準型に揃える。
    引数: value(object)。辞書、配列又は標準値。
    返り値: object。標準JSON型。
    """
    if isinstance(value, dict):
        return {str(key): clean(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(child) for child in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return clean(value.item())
    return value


def save(name: str, value: dict) -> None:
    """
    機能: 新95/auditだけへ日本語UTF-8の有限JSONを保存する。
    引数: name(str)。ファイル名。value(dict)。証跡。
    返り値: None。
    """
    path = (HERE / name).resolve()
    assert path.is_relative_to(HERE.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def exact(first: object, second: object) -> None:
    """
    機能: 欠測を含む入れ子値・配列を、公差で判定境界を救済せず厳密に比較する。
    引数: first/second(object)。比較対象。
    返り値: None。不一致なら例外。
    """
    if isinstance(first, dict):
        assert first.keys() == second.keys(), (first.keys(), second.keys())
        for key in first:
            exact(first[key], second[key])
    elif isinstance(first, (tuple, list)):
        assert len(first) == len(second)
        for left, right in zip(first, second):
            exact(left, right)
    elif isinstance(first, (np.ndarray, np.number, float, int)) and not isinstance(first, bool):
        np.testing.assert_array_equal(first, second)
    else:
        assert first == second, (first, second)


def same(first: object, second: object) -> None:
    """
    機能: 旧94から読取再利用する会計・集計器だけへ、元と同じ数値比較を提供する。
    引数: first/second(object)。旧比較対象。
    返り値: None。不一致なら例外。旧94のrtol0/atol1e−5を維持する。
    新source識別・入口・四源clock・loss66の比較にはこの関数でなくexactを使用する。
    """
    if isinstance(first, dict):
        assert first.keys() == second.keys(), (first.keys(), second.keys())
        for key in first:
            same(first[key], second[key])
    elif isinstance(first, (tuple, list)):
        assert len(first) == len(second)
        for left, right in zip(first, second):
            same(left, right)
    elif isinstance(first, (np.ndarray, np.number, float, int)) and not isinstance(first, bool):
        np.testing.assert_allclose(first, second, rtol=0, atol=1e-5, equal_nan=True)
    else:
        assert first == second, (first, second)

