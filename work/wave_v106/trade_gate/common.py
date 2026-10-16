"""新レンジ観測と候補の保存だけを、所有領域へ隔離する。"""

import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np


sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def module(name: str, path: Path) -> object:
    """
    機能: 読取り専用の小観測sourceを固有名で接続する。
    引数: name(str)、path(Path)はmodule名とsource。
    返り値: objectは観測部品。旧金融・原本・APIを暗黙実行しない。
    """
    if name not in sys.modules:
        spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
        sys.modules[name]=value;spec.loader.exec_module(value)
    return sys.modules[name]


def read(path: Path) -> dict:
    """
    機能: 小さいJSONを読む。
    引数: path(Path)は保存証跡。
    返り値: dictは元内容。金融台帳は対象にしない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path: Path) -> str:
    """
    機能: sourceと小証跡の内容指紋を求める。
    引数: path(Path)は既存ファイル。
    返り値: strはSHA256。巨大cacheは同読取bytesから別に計算する。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    """
    機能: 所有領域へ新規JSONまたは圧縮pickleを保存する。
    引数: path(Path)、value(object)は保存位置と値。
    返り値: None。既存保存源を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(),path
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix=='.json':
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
    else:
        with gzip.open(path,'wb',compresslevel=1) as stream:
            pickle.dump(value,stream,protocol=5)


def unpack(item: dict) -> dict:
    """
    機能: 固定cacheを同bytesで一回読み、内容指紋を照合する。
    引数: item(dict)はroot相対path/SHA256。
    返り値: dictは保存packet。原本再抽出を伴わない。
    """
    path=ROOT/item['path'];saved=path.read_bytes()
    assert hashlib.sha256(saved).hexdigest()==item['SHA256'],path
    return pickle.loads(gzip.decompress(saved))


def immutable(value: object) -> None:
    """
    機能: 旧経済列と候補配列を読取り専用へ固定する。
    引数: value(object)は配列を含む保存値。
    返り値: None。数値を変更しない。
    """
    if isinstance(value,np.ndarray):
        value.flags.writeable=False
    elif isinstance(value,dict):
        for v in value.values():
            immutable(v)
    elif isinstance(value,(list,tuple)):
        for v in value:
            immutable(v)

