"""E01公開時の取引更新代理を新所有cacheだけで準備する。"""

import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pickle
import sys

import numba

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
os.environ['NUMBA_CACHE_DIR']=str(HERE/'jit')
numba.config.CACHE_DIR=str(HERE/'jit')


def read(path: Path) -> object:
    """
    機能: 保存した小JSON又は一回読取用cacheを返す。
    引数: path(Path)は保存位置。
    返り値: objectは保存内容。金融やAPIを実行しない。
    """
    saved=path.read_bytes()
    if path.suffix=='.json':return json.loads(saved.decode('utf-8-sig'))
    return pickle.loads(gzip.decompress(saved) if path.suffix=='.gz' else saved)


def digest(path: Path) -> str:
    """
    機能: 小資料又はsourceのSHA256を計算する。
    引数: path(Path)は保存位置。
    返り値: strは指紋。大型入力は同一読取bytesで別に照合する。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    """
    機能: 新所有域に未保存の証跡又はcacheを作る。
    引数: path(Path)、value(object)は保存対象。
    返り値: None。旧sourceと既証跡を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(),path
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix=='.json':
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    else:
        with gzip.open(path,'wb',compresslevel=1) as stream:pickle.dump(value,stream,protocol=5)


def module(name: str, path: Path) -> object:
    """
    機能: 不変の小sourceを固有名で読み、旧cacheへの書込みを避ける。
    引数: name(str)、path(Path)はモジュール名とsource。
    返り値: objectは読取部品。本文金融の呼出しはしない。
    """
    if name not in sys.modules:
        spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
        sys.modules[name]=value;spec.loader.exec_module(value)
    return sys.modules[name]


def sources() -> dict:
    """
    機能: 新実装と直接再利用の小数学を固定する。
    引数: なし。
    返り値: dict[str,str]はroot相対位置と指紋。
    """
    return {p.relative_to(ROOT).as_posix():digest(p) for p in sorted(HERE.glob('*.py'))}
