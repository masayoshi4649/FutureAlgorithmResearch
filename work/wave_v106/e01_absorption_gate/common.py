"""同価格逆板の表示維持を、新所有域へ非金融測定する共通部品。"""

import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def read_json(path: Path) -> dict:
    """
    機能: 既存の小さい仕様又は由来JSONだけを読む。
    引数: path(Path)はJSON位置。
    返り値: dictは保存資料。金融・大型入力・APIは実行しない。
    """
    assert path.suffix == '.json'
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path: Path) -> str:
    """
    機能: 小資料又は静的実装のSHA256を求める。
    引数: path(Path)は対象位置。
    返り値: strは指紋。大型入力の事前走査には使用しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    """
    機能: 新所有域へ未保存の資料又は準備cacheを保存する。
    引数: path(Path)、value(object)は保存位置と値。
    返り値: None。既保存資料及び他所有域の上書きを拒否する。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == '.json':
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n',
                        encoding='utf-8', newline='\n')
    else:
        assert path.name.endswith('.pkl.gz')
        with gzip.open(path, 'wb', compresslevel=1) as stream:
            pickle.dump(value, stream, protocol=5)


def sources() -> dict:
    """
    機能: 新所有実装の版を小sourceだけから固定する。
    引数: なし。
    返り値: dict[str,str]はroot相対位置とSHA256。旧sourceを変更しない。
    """
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(HERE.glob('*.py'))}


def module(name: str, path: Path) -> object:
    """
    機能: JITを持たない静的モジュールを固有名で読む。
    引数: name(str)、path(Path)は名前とsource位置。
    返り値: objectは読み込んだ部品。金融・旧JITを呼ばない。
    """
    specification = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(specification)
    sys.modules[name] = value
    specification.loader.exec_module(value)
    return value
