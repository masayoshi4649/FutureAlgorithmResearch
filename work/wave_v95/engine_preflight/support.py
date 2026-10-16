"""95の損益前検査を新領域だけのキャッシュと対象指紋へ結ぶ。"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pickle
import sys

import numba
import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.dont_write_bytecode = True
os.environ['NUMBA_CACHE_DIR'] = str(WORK / 'jit_preflight')
numba.config.CACHE_DIR = os.environ['NUMBA_CACHE_DIR']


def module(name: str, path: Path) -> object:
    """
    機能: 読取実装を固有名に接続し、旧bytecode/cacheを変更しない。
    引数: name(str)、path(Path)。
    返り値: objectはモジュール。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def components() -> tuple:
    """
    機能: 新95の戦略・条件と読み取り入力器を接続する。
    引数: なし。
    返り値: tuple[object,object,object]は実装三部品。
    """
    return (module('損益前95戦略', WORK / 'strategy.py'),
            module('損益前95条件', WORK / 'catalog.py'),
            module('損益前95入力', WORK / 'data.py'))


def digest(path: Path) -> str:
    """
    機能: 大きい資料の内容指紋を分割読み取りで計算する。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def read(path: Path) -> object:
    """
    機能: 許可済み旧会計又は保存入力の内容を読む。
    引数: path(Path)。
    返り値: objectはpickle又はJSON。新候補の正式損益は読まない。
    """
    with path.open('rb') as stream:
        return pickle.load(stream) if path.suffix=='.pkl' else json.loads(stream.read().decode('utf-8'))


def save(name: str, value: dict, paths: list[Path]) -> None:
    """
    機能: 現在の対象実装と検査結果を結び新preflight領域へ保存する。
    引数: name(str)、value(dict)、paths(list[Path])。
    返り値: None。旧成果及び正式新損益は変更しない。
    """
    files = [Path(__file__), WORK/'engine.py', WORK/'strategy.py', WORK/'catalog.py', *paths]
    value['SHA256'] = {str(path.relative_to(ROOT)): digest(path) for path in sorted(set(files))}
    value.update(正式新損益実行=0, 現在API取得=0, 実注文=0, 旧変更=0)
    (HERE/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({key:item for key,item in value.items() if key!='SHA256'}, ensure_ascii=False), flush=True)


def prefix(record: dict, signal: dict, stop: int) -> tuple:
    """
    機能: 自市場原行を切断し、未参照の未来格子を残した厳密接頭検査にする。
    引数: record/signal(dict)、stop(int)。
    返り値: tuple[dict,dict]は人工又は実原行の過去入力。
    """
    size = len(record['time_s'])
    r = {key:value[:stop].copy() if isinstance(value,np.ndarray) and len(value)==size else value
         for key,value in record.items()}
    fields = ('mapped','quality','reset','event','execution_lp_index')
    s = {key:value[:stop].copy() if key in fields else value for key,value in signal.items()}
    return r,s


def prefix_equal(full: dict, part: dict, stop: int) -> None:
    """
    機能: 全経済・旧状態・新反転証拠が未来切断で変わらないことを照合する。
    引数: full/part(dict)、stop(int)。
    返り値: Noneは全過去の一致確認。
    """
    for name,column in (('orders',0),('trades',3),('events',0),('range_parent_diagnostics',3),('loss_reentry_events',0)):
        np.testing.assert_array_equal(full[name][full[name][:,column]<stop],part[name])
    for name in ('curve','source_curve','target_trace','range_state_trace','risk_state_trace','price_source_trace'):
        np.testing.assert_array_equal(full[name][:stop],part[name])
