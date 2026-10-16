"""105の完了した軽量入力だけを、一場一読取で返す専用loader。"""

import gzip
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
METADATA = HERE/'全33場の因果特徴準備.json'


def read_json(path: Path) -> dict:
    """
    機能: 小さいUTF-8の入力証跡を読む。
    引数: path(Path)はmetadata又は計画。
    返り値: dictは保存JSON。金融又は原板をロードしない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: source又は小証跡のSHA256を確認する。
    引数: path(Path)は既存source又は完了証跡。
    返り値: strは指紋。巨大packetは保存bytesから別に一回計算する。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def immutable(value: object) -> None:
    """
    機能: loader返却配列を読取り専用にし、元入口列の偶発変更を防ぐ。
    引数: value(object)は配列を含む辞書・list・tuple等。
    返り値: None。辞書の業務値は変更しない。
    """
    if isinstance(value, np.ndarray):
        value.flags.writeable = False
    elif isinstance(value, dict):
        for item in value.values():
            immutable(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            immutable(item)


def load_session(session: str, verify: bool = True) -> dict:
    """
    機能: 完了した105の一場を返し、旧33packetや原本を暗黙再読しない。
    引数: session(str)、verify(bool)は場名と指紋照合の要否。
    返り値: dictはprepared/cases/features/raw_features。未完了又は不合格は拒否する。
    """
    metadata = read_json(METADATA)
    assert metadata['全合格'] and metadata['対象場数'] == 33 and metadata['口座数'] == 66
    assert metadata['新金融再生'] == metadata['原本再読取'] == metadata['現在API'] == 0
    assert metadata['旧64base再prepare'] == metadata['旧source変更'] == 0
    assert metadata['入口'] == ['C_OWN', 'C_N30', 'U_P10']
    item = metadata['cache'][session]
    path = (ROOT/item['path']).resolve()
    assert path.is_relative_to((HERE/'cache').resolve())
    saved = path.read_bytes()
    if verify:
        assert hashlib.sha256(saved).hexdigest() == item['SHA256']
        for name, expected in metadata['loader_source_SHA256'].items():
            assert digest(ROOT/name) == expected, name
    value = pickle.loads(gzip.decompress(saved))
    assert value['schema_version'] == 1 and value['session'] == session
    assert set(value['prepared']) == {'TOPIX', 'NK225'}
    assert set(value['cases']) == set(value['features']) == {'C_OWN', 'C_N30', 'U_P10'}
    immutable(value)
    return value
