"""保存小目録と一読cacheの同bytesを照合し、新所有台帳だけを保存する。"""

import gzip
import hashlib
import json
from pathlib import Path
import pickle
import common


def digest(path: Path) -> str:
    """
    機能: 計画で許可された小資料又はsourceのSHA256を求める。
    引数: path(Path) は明示資料。大型cacheはloadの一読bytesから検算する。
    返り値: str は十六進SHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 保存JSON小目録を読み、金融sourceや板の取得を実行しない。
    引数: path(Path) は固定計画・登録・保存会計などの小資料。
    返り値: dict はJSON辞書。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def load(item: dict) -> dict:
    """
    機能: 根の登録後だけ指定input又は旧台帳を同bytes一読で検証する。
    引数: item(dict) はroot相対path/SHA256。
    返り値: dict は保存口座又は台帳。原板・NPZ・現在APIを読まない。
    """
    path=common.ROOT/item['path'];assert path.resolve().is_relative_to(common.ROOT/'work')
    saved=path.read_bytes();assert hashlib.sha256(saved).hexdigest()==item['SHA256'],item['path']
    return pickle.loads(gzip.decompress(saved))


def save(path: Path, value: dict) -> None:
    """
    機能: 新所有域の未保存台帳だけへgzip/pickleを保存する。
    引数: path(Path)、value(dict) は新台帳名と実会計。
    返り値: None。既成果・公共・共通・旧JITを上書きしない。
    """
    assert path.resolve().is_relative_to(common.HERE) and not path.exists()
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(gzip.compress(pickle.dumps(value,protocol=5),compresslevel=4,mtime=0))
