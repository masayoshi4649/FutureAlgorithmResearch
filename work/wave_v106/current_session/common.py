"""未取得ナイトへの接続を、現在場の所有領域だけに隔離する。"""

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
    機能: 小さい不変sourceを通常名と衝突せず読取接続する。
    引数: name(str)、path(Path)は識別子とsource。
    返り値: objectは部品。金融main/API取得は暗黙実行しない。
    """
    if name not in sys.modules:
        spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
        sys.modules[name]=value;spec.loader.exec_module(value)
    return sys.modules[name]


def digest(path: Path) -> str:
    """
    機能: source/小証跡の内容指紋を計算する。
    引数: path(Path)は既存ファイル。
    返り値: strはSHA256。現在API本文はextract_streamの同一走査で計算する。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> str:
    """
    機能: 所有域へ新規JSON又はpickleを保存する。
    引数: path(Path)、value(object)は未存在の保存先と内容。
    返り値: strは保存bytesのSHA256。原板/旧cacheを変更しない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(),path
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix=='.json':
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
    else:
        with gzip.open(path,'wb',compresslevel=1) as stream:pickle.dump(value,stream,protocol=5)
    return digest(path)


def immutable(value: object) -> None:
    """
    機能: 保存された当時入力の数値列を読取専用へ固定する。
    引数: value(object)は配列を含む値。
    返り値: None。metadata又は原seq数値を変更しない。
    """
    if isinstance(value,np.ndarray):value.flags.writeable=False
    elif isinstance(value,dict):
        for item in value.values():immutable(item)
    elif isinstance(value,(tuple,list)):
        for item in value:immutable(item)
