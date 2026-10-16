"""第三段階の所有域だけに新資料を保存する。"""

import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WAVE = HERE.parent


def module(name: str, path: Path) -> object:
    """
    機能: 固有名で既存の小部品を接続し、普通名との衝突を防ぐ。
    引数: name(str)は識別名、path(Path)はsource。
    返り値: objectは部品。正式金融を暗黙には開始しない。
    """
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec)
        sys.modules[name] = value
        spec.loader.exec_module(value)
    return sys.modules[name]


def digest(path: Path) -> str:
    """
    機能: 小source又は保存bytesの指紋を確認する。
    引数: path(Path)は対象。
    返り値: strはSHA256。原板は読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 保存されたUTF-8資料を読む。
    引数: path(Path)はJSON。
    返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: dict) -> None:
    """
    機能: 新しい証跡を所有域へ保存する。
    引数: path(Path)は保存先、value(dict)は内容。
    返り値: None。既完了資料を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE.resolve()) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def pack(path: Path, value: dict) -> str:
    """
    機能: 新入力又は台帳を同一形式の圧縮pickleで保存する。
    引数: path(Path)、value(dict)は未使用の所有域と値。
    返り値: strは保存bytesのSHA256。
    """
    assert path.resolve().is_relative_to(HERE.resolve()) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as raw:
        with gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0,compresslevel=2) as stream:
            pickle.dump(value,stream,protocol=5)
    return digest(path)


def unpack(item: dict) -> dict:
    """
    機能: 既存cache一個を読取り、同じbytesをhash確認して展開する。
    引数: item(dict)はpathとSHA256。
    返り値: dictは保存packet。原本を再抽出しない。
    """
    payload = (ROOT/item['path']).read_bytes()
    assert hashlib.sha256(payload).hexdigest()==item['SHA256'],item['path']
    return pickle.loads(gzip.decompress(payload))


def immutable(value: object) -> None:
    """
    機能: 配列を読取り専用にして入口の偶発改変を防ぐ。
    引数: value(object)はdict/list/tuple/ndarray。
    返り値: None。業務値は変更しない。
    """
    if isinstance(value,np.ndarray):
        value.flags.writeable=False
    elif isinstance(value,dict):
        for child in value.values(): immutable(child)
    elif isinstance(value,(list,tuple)):
        for child in value: immutable(child)
