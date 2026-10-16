"""旧30場の最小入力と保存済み追加デイを、損益を読まず接続する。"""

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


def digest(path):
    """
    機能: 指定入力資料の内容指紋を求める。
    引数: path (Path)。
    返り値: str のSHA256。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def immutable(value):
    """
    機能: 入力配列の意図しない書換えを禁止する。
    引数: value (object)。
    返り値: None。
    """
    if isinstance(value, np.ndarray):
        value.flags.writeable = False
    elif isinstance(value, dict):
        for child in value.values():
            immutable(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            immutable(child)


def load_inputs(verify=True):
    """
    機能: 旧入力の完全保持と追加場の指紋を確かめ、全31場62口座を返す。
    引数: verify (bool) は保存指紋を照合するか。
    返り値: dict はprices/grids/legacy/entries/features/metadata/paths。
    損益台帳、将来ラベル、現在API、実注文を使わない。
    """
    metadata_path = HERE / 'metadata.json'
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    if verify:
        for relative, expected in metadata['旧指紋'].items():
            assert digest(ROOT / relative) == expected, ('旧入力変更', relative)
        for relative, expected in metadata['新入力指紋'].items():
            assert digest(HERE / relative) == expected, ('追加入力変更', relative)
        for relative, expected in metadata['新コード指紋'].items():
            assert digest(ROOT / relative) == expected, ('新入力コード変更', relative)
        for relative, expected in metadata['直接使用旧コード指紋'].items():
            assert digest(ROOT / relative) == expected, ('旧抽出コード変更', relative)
    name = '保存入力90の不変接続91'
    spec = importlib.util.spec_from_file_location(name, ROOT / 'work/wave_v90/data.py')
    old = importlib.util.module_from_spec(spec); sys.modules[name] = old; spec.loader.exec_module(old)
    value = old.load_inputs(verify=verify)
    extra_path = HERE / 'material_extra.pkl'
    with extra_path.open('rb') as stream:
        extra = pickle.load(stream)
    for kind in ('prices', 'grids', 'legacy', 'entries', 'features'):
        assert not set(value[kind]) & set(extra[kind])
        value[kind] = dict(value[kind], **{})
        value[kind].update(extra[kind])
    value['metadata'] = metadata
    value['paths'] = [*value['paths'], metadata_path, extra_path,
                      HERE / '追加Dayの原本と品質及び因果検査.json', Path(__file__), HERE / 'prepare.py']
    assert len(value['prices']) == len(value['legacy']) == len(value['features']) == 62
    assert len(value['grids']) == len(value['entries']) == 31
    assert set(value['grids']) == set(value['entries']) == set(metadata['sessions'])
    assert set(value['prices']) == {(session, symbol) for session in value['grids'] for symbol in ('TOPIX', 'NK225')}
    immutable(value)
    return value
