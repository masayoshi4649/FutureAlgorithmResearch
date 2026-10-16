"""96の独立監査だけの読取、指紋、厳密比較、証跡保存を行う。"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pickle
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
sys.dont_write_bytecode = True
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'jit')
sys.path.insert(1, str(BASE))


def module(name: str, path: Path) -> object:
    """
    機能: 監査対象を固有名で読み、旧ファイルへの書込を防ぐ。
    引数: name(str)は固有名、path(Path)は保存コード。
    返り値: object。読取モジュール。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def read(path: Path) -> object:
    """
    機能: 保存済みJSON又はpickleを読む。
    引数: path(Path)は読取対象。
    返り値: object。保存内容。
    """
    if path.suffix == '.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    """
    機能: 現在の保存原本のSHA256を算出する。
    引数: path(Path)はファイル。
    返り値: str。16進指紋。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fingerprint(paths: list[Path]) -> dict:
    """
    機能: 保存原本を変更せず、相対パスと指紋を対応づける。
    引数: paths(list[Path])は読取資料。
    返り値: dict[str,str]。現在指紋。
    """
    return {str(path.relative_to(ROOT)): sha(path) for path in paths}


def exact(actual: object, expected: object, label: str = '') -> None:
    """
    機能: 候補、時計、注文、状態を公差なしで比較する。
    引数: actual/expected(object)、label(str)は失敗箇所。
    返り値: None。不一致は例外。
    """
    np.testing.assert_array_equal(actual, expected, err_msg=label)


def money(actual: object, expected: object, label: str = '') -> None:
    """
    機能: 演算順が異なる全原板現金評価だけ旧会計と同じ絶対公差で比較する。
    引数: actual/expected(object)、label(str)は失敗箇所。
    返り値: None。絶対公差1e-5を超える差は例外。
    """
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-5, equal_nan=True, err_msg=label)


def same(actual: object, expected: object, label: str = '') -> None:
    """
    機能: 会計JSONの構造を厳密照合し、金額数値だけ旧会計の絶対公差を使う。
    引数: actual/expected(object)、label(str)は現在箇所。
    返り値: None。構造又は会計不一致は例外。
    """
    if isinstance(actual, dict) and isinstance(expected, dict):
        assert actual.keys() == expected.keys(), label
        for key in actual:
            same(actual[key], expected[key], label + '/' + key)
    elif isinstance(actual, (list, tuple)) and isinstance(expected, (list, tuple)):
        assert len(actual) == len(expected), label
        for i, (left, right) in enumerate(zip(actual, expected)):
            same(left, right, label + '/' + str(i))
    elif isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        money(actual, expected, label)
    else:
        assert actual == expected, label
def save(path: Path, value: dict) -> None:
    """
    機能: 新しい監査証跡だけをUTF-8で保存し、再読込まで通す。
    引数: path(Path)は96/audit内、value(dict)はJSON化可能な内容。
    返り値: None。保存先逸脱又は保存不一致は例外。
    """
    assert path.resolve().is_relative_to(HERE.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    path.write_text(text + '\n', encoding='utf-8')
    assert read(path) == value


def old_immutable() -> None:
    """
    機能: 95の凍結405依存が元の指紋のままであることを確認する。
    引数: なし。
    返り値: None。不一致は例外。
    """
    fixed = read(ROOT / 'work/wave_v95/事前固定.json')
    for relative, expected in fixed['SHA256'].items():
        assert sha(ROOT / relative) == expected, relative
