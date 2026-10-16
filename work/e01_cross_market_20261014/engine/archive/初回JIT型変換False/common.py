"""汎用出口の人工準備を新所有域だけで行い、旧sourceとcacheを保つ。"""

import hashlib
import json
import os
from pathlib import Path
import sys
import numba

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
os.environ['NUMBA_CACHE_DIR']=str(HERE/'jit')
numba.config.CACHE_DIR=str(HERE/'jit')


def sources() -> dict:
    """
    機能: 汎用出口のsourceを結果前に指紋へ結ぶ。
    引数: なし。
    返り値: dict[str,str] はsource相対pathとSHA256。
    """
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.glob('*.py'))}


def write(name: str, value: dict) -> None:
    """
    機能: 新所有域へ未保存の人工証跡だけを作る。
    引数: name(str)、value(dict) は証跡名と内容。
    返り値: None。正式金融や公共・共通の更新はしない。
    """
    path=HERE/name;assert not path.exists() and path.resolve().is_relative_to(HERE)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
