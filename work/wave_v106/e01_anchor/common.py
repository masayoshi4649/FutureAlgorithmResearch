"""保存紙上GUと旧会計を読取接続し、今回の保存とJITを隔離する。"""

from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pickle
import sys

import numba


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REFERENCE = HERE.parent / 'e01_reference'
sys.dont_write_bytecode = True
sys.path.insert(1, str(REFERENCE))


def digest(path: Path) -> str:
    """
    機能: 読取資料の内容指紋を求める。
    引数: path(Path)は既存資料。
    返り値: str。原本内容を変更しない。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path: Path) -> object:
    """
    機能: 保存JSON又はpickleを読む。
    引数: path(Path)は読取対象。
    返り値: object。金融再生を伴わない。
    """
    with path.open('rb') as stream:
        return pickle.load(stream) if path.suffix == '.pkl' else json.load(stream)


def save(path: Path, value: object) -> None:
    """
    機能: 今回所有域へ新規JSONだけを保存する。
    引数: path(Path)、value(object)は保存先と内容。
    返り値: None。既存証跡を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf8')


def module(name: str, path: Path) -> object:
    """
    機能: 旧sourceを固有名で読み、mainを実行しない。
    引数: name(str)、path(Path)は名前とsource。
    返り値: object。自身又は旧pure部品。
    """
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec); sys.modules[name] = value
        spec.loader.exec_module(value)
    return sys.modules[name]


@contextmanager
def cache() -> object:
    """
    機能: この実行だけのJIT保存を今回所有域へ隔離する。
    引数: なし。
    返り値: contextmanager。旧保存先は実行後に復元する。
    """
    previous = numba.config.CACHE_DIR; env = os.environ.get('NUMBA_CACHE_DIR')
    numba.config.CACHE_DIR = str(HERE / 'jit'); os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'jit')
    try:
        yield
    finally:
        numba.config.CACHE_DIR = previous
        if env is None:
            os.environ.pop('NUMBA_CACHE_DIR', None)
        else:
            os.environ['NUMBA_CACHE_DIR'] = env


ACCOUNT = module('106の不変E01注文会計', REFERENCE / 'accounting.py')
TIME = module('106の不変E01静観時計', ROOT / 'work/wave_v85/time_filter.py')
QUANTITY = {'TOPIX': 5, 'NK225': 10}
CAP = {'TOPIX': 10, 'NK225': 20}


def sources() -> dict:
    """
    機能: 直接使う注文・会計・参照値sourceを固定する。
    引数: なし。
    返り値: dict[str,str]。原板と過去巨大台帳の再hashはしない。
    """
    paths = set(HERE.glob('*.py'))
    paths.update(REFERENCE / name for name in ('accounting.py', 'specification.py', 'bridge.py'))
    paths.add(ROOT / 'work/wave_v85/time_filter.py')
    return {str(p.relative_to(ROOT)).replace('\\', '/'): digest(p) for p in sorted(paths)}
