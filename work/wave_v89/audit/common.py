"""過去の確定監査を読み取り、今回の独立監査だけへ共通道具を提供する。"""

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
SOURCES = ('GU', 'M3', 'C03')


def module(name, path):
    """
    機能: 読取対象を固有名で読み込み、過去の凍結ファイルを変更しない。
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
    機能: 読取専用のファイルから内容指紋を取得する。
    引数: path(Path)。
    返り値: strのSHA256。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def save(name, value):
    """
    機能: 今回の監査領域だけへ有限JSONを保存する。
    引数: name(str)、value(dict)。
    返り値: None。
    """
    path = HERE / name
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def fingerprints(paths):
    """
    機能: 対象コードと既往証拠の指紋を記録する。
    引数: paths(list[Path])。
    返り値: dict[str,str]。
    """
    return {str(path.relative_to(ROOT)): sha(path) for path in paths}


def numeric(array):
    """
    機能: 数値配列を固定形に揃え、すべて有限であることを確認する。
    引数: array(ndarray)。
    返り値: ndarray。
    """
    value = np.asarray(array, float)
    assert np.isfinite(value).all()
    return value


# ----------------------------------------
# 既往の独立監査関数は読取だけで使い、今回のゲート復元は別に作る。
OLD = module('監査89読取用88人工復元', ROOT / 'work/wave_v88/audit/execution_checks.py')
sys.modules.setdefault('execution_checks', OLD)
FULL = module('監査89読取用88全会計復元', ROOT / 'work/wave_v88/audit/full.py')
