"""所有領域のcacheと不変小sourceの読取りを管理する。"""

import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pickle
import sys

import numba


sys.dont_write_bytecode = True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
REFERENCE=ROOT/'work/wave_v106/e01_reference'
os.environ['NUMBA_CACHE_DIR']=str(HERE/'jit')
numba.config.CACHE_DIR=str(HERE/'jit')


def module(name: str, path: Path) -> object:
    """
    機能: 不変の小sourceを固有名で読み、旧sourceを変更せず再利用する。
    引数: name(str)、path(Path)はmodule名とsource。
    返り値: objectは読取部品。紙上金融やAPIを実行しない。
    """
    if name not in sys.modules:
        spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
        sys.modules[name]=value;spec.loader.exec_module(value)
    return sys.modules[name]


def read(path: Path) -> object:
    """
    機能: 既存JSONまたはpickleを読む。
    引数: path(Path)は保存資料。
    返り値: objectは保存値。旧原本やpaper再生には接続しない。
    """
    content=path.read_bytes()
    if path.suffix=='.json':
        return json.loads(content.decode('utf-8-sig'))
    return pickle.loads(gzip.decompress(content) if path.suffix=='.gz' else content)


def digest(path: Path) -> str:
    """
    機能: sourceと小証跡のSHA256を求める。
    引数: path(Path)は保存資料。
    返り値: strは内容指紋。巨大cacheは同読取bytesから別に照合する。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    """
    機能: 所有領域へ新しいJSONまたはgzip cacheだけを保存する。
    引数: path(Path)、value(object)は位置と値。
    返り値: None。既存sourceや証跡を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(),path
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix=='.json':
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
    else:
        with gzip.open(path,'wb',compresslevel=1) as stream:
            pickle.dump(value,stream,protocol=5)


def source_hashes() -> dict:
    """
    機能: 新所有sourceと直接再利用する価格・料金・休止数学を固定する。
    引数: なし。
    返り値: dictはroot相対pathからSHA256への対応。
    """
    files=list(HERE.glob('*.py'))+[ROOT/'work/wave_v106/e01_pair_filter/core.py',
        ROOT/'work/wave_v106/e01_daily/core.py',ROOT/'work/wave_v85/time_filter.py',
        REFERENCE/'engine.py',REFERENCE/'order_kernel.py']
    return {p.relative_to(ROOT).as_posix():digest(p) for p in sorted(set(files))}

