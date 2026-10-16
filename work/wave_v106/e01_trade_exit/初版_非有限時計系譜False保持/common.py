"""新領域への保存と既存実注文の読み取りだけを提供する。"""

import gzip
import hashlib
import json
from pathlib import Path
import pickle
import sys


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REFERENCE = ROOT/'work/wave_v106/e01_reference'


def digest(path: Path) -> str:
    """
    機能: 保存済み資料のSHA256を求める。
    引数: path(Path)は既存資料。
    返り値: strは内容指紋。原本を変更しない。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path: Path) -> object:
    """
    機能: 小JSONまたは保存pickleを読む。
    引数: path(Path)は資料の位置。
    返り値: objectは保存内容。旧paper再生は行わない。
    """
    if path.suffix == '.json':
        return json.loads(path.read_text(encoding='utf-8-sig'))
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rb') as stream:
        return pickle.load(stream)


def write(path: Path, value: object) -> None:
    """
    機能: 所有領域へ新規JSONまたはgzip台帳を保存する。
    引数: path(Path)、value(object)は保存先と内容。
    返り値: None。既存証跡は上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == '.json':
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n',
            encoding='utf-8', newline='\n')
    else:
        with gzip.open(path, 'wb', compresslevel=1) as stream:
            pickle.dump(value, stream, protocol=5)


def source_hashes() -> dict:
    """
    機能: 新政策実装の全小sourceを固定する。
    引数: なし。
    返り値: dictはルート相対パスからSHA256への対応。
    """
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(HERE.glob('*.py'))}

