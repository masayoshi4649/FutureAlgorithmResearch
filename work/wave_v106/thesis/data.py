"""途中判断の完了cacheのみを一場単位で読む。原本・金融の暗黙再生はしない。"""

import gzip
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def immutable(value: object) -> None:
    """
    機能: 返却cacheの配列を読取り専用にする。
    引数: value(object)は辞書・配列・配列を含む値。
    返り値: None。数値・列順を変更しない。
    """
    if isinstance(value, np.ndarray):
        value.flags.writeable = False
    elif isinstance(value, dict):
        for item in value.values():
            immutable(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            immutable(item)


def load_session(session: str) -> dict:
    """
    機能: 指紋が一致した新thesis一場入力だけを読み込む。
    引数: session(str)は登録済み場名。
    返り値: dictは正常入力・三入口・保有中相手観測。未完了cacheは拒否する。
    """
    metadata = json.loads((HERE/'全33場の途中相手準備.json').read_text(encoding='utf-8'))
    assert metadata['全合格'] and metadata['金融再生'] == 0
    item = metadata['cache'][session]
    path = (ROOT/item['path']).resolve()
    assert path.is_relative_to(HERE/'cache')
    saved = path.read_bytes()
    assert hashlib.sha256(saved).hexdigest() == item['SHA256']
    value = pickle.loads(gzip.decompress(saved))
    assert value['session'] == session and value['schema_version'] == 1
    immutable(value)
    return value
