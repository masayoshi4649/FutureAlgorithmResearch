"""105の成果と入力指紋を、過去の作業を変えずに保存する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREVIOUS = ROOT/'work/wave_v104'
sys.dont_write_bytecode = True


def read(path: Path) -> dict:
    """
    機能: UTF-8の検証資料を読み取る。
    引数: path(Path)は対象JSON。
    返り値: dictは保存された内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 指定された資料の内容指紋を得る。
    引数: path(Path)は対象資料。
    返り値: strはSHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path: Path, value: dict) -> None:
    """
    機能: 105の新しい証跡を保存する。
    引数: path(Path)は105内の未使用位置、value(dict)は内容。
    返り値: None。既存証跡は上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def module(name: str, path: Path) -> object:
    """
    機能: 自動cache生成を持たない小部品を固有名で読み込む。
    引数: name(str)、path(Path)は識別名とsource。
    返り値: objectは読み込んだ部品。並列実行前に読み込みを済ませる。
    """
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec)
        sys.modules[name] = value
        spec.loader.exec_module(value)
    return sys.modules[name]
