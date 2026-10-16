"""私有JITと結果前の指紋だけを管理し、原入力や登録・金融を自動開始しない。"""

import hashlib
import json
import os
from pathlib import Path
import sys

import numba

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.dont_write_bytecode=True
os.environ['NUMBA_CACHE_DIR']=str(HERE/'jit')
numba.config.CACHE_DIR=str(HERE/'jit')


def sources() -> dict:
    """
    機能: 有効な私有sourceを全て指紋に含める。
    引数: なし。
    返り値: dict[str,str] はroot相対path/SHA256。旧JITを使わない。
    """
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.glob('*.py'))}


def write(name: str,value: dict) -> None:
    """
    機能: 所有域の未保存証跡を非有限JSON禁止で保存する。
    引数: name(str)、value(dict) は新しい証跡名と内容。
    返り値: None。旧成功/False・公共・共通を上書きしない。
    """
    path=HERE/name;assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
