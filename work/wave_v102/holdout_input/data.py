"""追加ナイト一場だけを読み、元31場の選定素材へ混ぜない。"""

import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SESSION = '2026-10-12_Night'
SYMBOLS = ('TOPIX', 'NK225')


def digest(path: Path) -> str:
    """
    機能: 指定した入力資料の内容指紋を一定メモリーで求める。
    引数: path(Path)は読取対象。
    返り値: strのSHA256。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def immutable(value: object) -> None:
    """
    機能: 保存した入力配列の意図しない上書きを拒絶する。
    引数: value(object)は配列、辞書又は列。
    返り値: None。
    """
    if isinstance(value, np.ndarray):
        value.flags.writeable = False
    elif isinstance(value, dict):
        for child in value.values():
            immutable(child)
    elif isinstance(value, (tuple, list)):
        for child in value:
            immutable(child)


def load_inputs(verify: bool = True) -> dict:
    """
    機能: 元31場から隔離した追加ナイト一場の因果入力を返す。
    引数: verify(bool)は原本、入力及び直接使用コードの指紋照合要否。
    返り値: dictは102のprepareへ渡せる一場二口座の素材。
    売買、損益、選定、API及び注文はこの読取処理では実行しない。
    """
    metadata_path = HERE / 'metadata.json'
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    assert metadata['sessions'] == [SESSION] and metadata['accounts'] == 2
    if verify:
        for group in ('原本SHA256', '直接使用コードSHA256', '入力SHA256'):
            for relative, expected in metadata[group].items():
                assert digest(ROOT / relative) == expected, (group, relative)
    path = HERE / 'material_holdout.pkl'
    with path.open('rb') as stream:
        value = pickle.load(stream)
    value['metadata'] = metadata
    value['paths'] = [metadata_path, path, Path(__file__), HERE / 'prepare.py',
                      HERE / '追加入力の人工と原本及び実接頭検査.json', HERE / '入力準備前の素材登録.json']
    keys = {(SESSION, symbol) for symbol in SYMBOLS}
    for name in ('prices', 'features', 'legacy', 'raw_last_records', 'execution_lp_index'):
        assert set(value[name]) == keys, name
    for name in ('grids', 'entries'):
        assert set(value[name]) == {SESSION}, name
    assert set(value['price_lanes']) == {'I0', 'I1', 'I2', 'I3'}
    assert set(value['trend_prices']) == {'I3'}
    immutable(value)
    return value
