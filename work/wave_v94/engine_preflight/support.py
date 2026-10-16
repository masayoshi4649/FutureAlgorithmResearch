"""新94の損益前検査を、新領域だけのcacheと証跡で実行する共通処理。"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pickle
import sys

import numpy as np


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
sys.dont_write_bytecode=True
os.environ['NUMBA_CACHE_DIR']=str(WORK/'jit_preflight')


def module(name: str,path: Path) -> object:
    """機能: 読取モジュールを固有名へ接続し、旧bytecodeを書かない。

    引数: name(str)、path(Path)。返り値: objectはモジュール。
    """
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value;spec.loader.exec_module(value);return value


def components() -> tuple:
    """機能: 固定前の新94戦略・条件・修正済み入力器を読む。

    引数: なし。返り値: tupleはstrategy/catalog/data_r1。
    """
    return (module('損益前94戦略',WORK/'strategy.py'),module('損益前94条件',WORK/'catalog.py'),
            module('損益前94修正入力',WORK/'data_r1.py'))


def read(path: Path) -> object:
    """機能: 許可済み旧保存台帳又はJSONを読む。

    引数: path(Path)。返り値: objectは保存内容。
    """
    with path.open('rb') as stream:
        return pickle.load(stream) if path.suffix=='.pkl' else json.loads(stream.read().decode('utf-8'))


def digest(path: Path) -> str:
    """機能: 大きい旧台帳も一定メモリーで指紋化する。

    引数: path(Path)。返り値: strはSHA256。
    """
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):value.update(block)
    return value.hexdigest()


def save(name: str,value: dict,paths: list[Path]) -> None:
    """機能: 対象実装と入力のSHAを結んだ損益前証跡を新領域へ保存する。

    引数: name(str)、value(dict)、paths(list[Path])。返り値: None。
    """
    all_paths=[Path(__file__),WORK/'engine.py',WORK/'strategy.py',WORK/'catalog.py',*paths]
    value['SHA256']={str(path.relative_to(ROOT)):digest(path) for path in sorted(set(all_paths))}
    value.update(現在API取得=0,実注文=0,旧変更=0)
    (HERE/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({key:value[key] for key in value if key!='SHA256'},ensure_ascii=False),flush=True)


def prefix(record: dict,signal: dict,stop: int) -> tuple:
    """機能: 原板を切断し、未来格子は残して参照されないことを検査する。

    引数: record/signal(dict)、stop(int)。返り値: tupleは切断原板と信号。
    """
    n=len(record['time_s'])
    r={key:value[:stop].copy() if isinstance(value,np.ndarray) and len(value)==n else value for key,value in record.items()}
    s={key:value[:stop].copy() if key in ('mapped','quality','reset','event') else value for key,value in signal.items()}
    return r,s


def prefix_equal(full: dict,part: dict,stop: int) -> None:
    """機能: 全経済・潜在状態・独立価格源の過去が切断後も完全一致するか調べる。

    引数: full/part(dict)、stop(int)。返り値: None。
    """
    for name,column in (('orders',0),('trades',3),('events',0),('range_parent_diagnostics',3)):
        np.testing.assert_array_equal(full[name][full[name][:,column]<stop],part[name][part[name][:,column]<stop])
    for name in ('curve','source_curve','target_trace','range_state_trace','risk_state_trace','price_source_trace'):
        np.testing.assert_array_equal(full[name][:stop],part[name][:stop])
