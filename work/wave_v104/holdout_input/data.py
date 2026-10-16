"""追加Day一場の新入力だけをreadonlyで返し、既知32へ混ぜない。"""

import hashlib
import io
import json
from pathlib import Path
import pickle
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SESSION = '2026-10-13_Day'
SYMBOLS = ('TOPIX', 'NK225')


def digest(path: Path) -> str:
    """
    機能: 小さい直接依存と所有域出力を指紋化する。
    引数: path(Path)はソース又は新出力。
    返り値: strはSHA256。新旧生原本の再hashには使わない。
    """
    assert path.resolve().parts[-1] != SESSION+'.jsonl'
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def immutable(value: object) -> None:
    """
    機能: 消費側が新入力を変更しないよう、全配列を読取専用にする。
    引数: value(object)は辞書・配列・列。
    返り値: None。原本又は旧入力への書込みは行わない。
    """
    if isinstance(value, np.ndarray):
        value.flags.writeable = False
    elif isinstance(value, dict):
        for child in value.values():
            immutable(child)
    elif isinstance(value, (tuple, list)):
        for child in value:
            immutable(child)


def metadata(verify: bool = True) -> dict:
    """
    機能: 追加Day一場の完成と小直接依存の不変を確認する。
    引数: verify(bool)は直接依存指紋の照合要否。
    返り値: dictは完成資料。原本を再読せず、正式終端の一回hashへ委譲する。
    """
    value = json.loads((HERE/'metadata.json').read_text(encoding='utf-8'))
    assert value['全合格'] and value['sessions'] == [SESSION] and value['口座数'] == 2
    assert value['正式原本各一回読取'] == 2 and value['金融再生'] == 0
    if verify:
        for name, wanted in value['小直接依存SHA256'].items():
            assert digest(ROOT/name) == wanted, name
    return value


def load_account(session: str, symbol: str, verify: bool = True) -> tuple[dict, dict]:
    """
    機能: 追加Dayの訂正済み全原行44配列と旧normal対応を返す。
    引数: session/symbol(str)は固定場・商品、verify(bool)は新出力指紋の照合要否。
    返り値: tuple[dict,dict]はreadonly配列と口座診断。原本再読、金融、APIはない。
    """
    assert session == SESSION and symbol in SYMBOLS
    saved = metadata(verify)
    item = saved['accounts'][session+'|'+symbol]
    path = ROOT/item['出力位置']
    assert path.resolve().is_relative_to(HERE.resolve())
    payload = path.read_bytes()
    if verify:
        assert hashlib.sha256(payload).hexdigest() == item['出力SHA256']
    with np.load(io.BytesIO(payload), allow_pickle=False) as stream:
        arrays = {name: stream[name] for name in stream.files}
    assert set(arrays) == set(saved['schema']['columns'])
    for name, spec in saved['schema']['columns'].items():
        expected = tuple(item['raw_rows'] if size == 'N' else item['normal_execution_rows'] if size == 'M' else size
                         for size in spec['shape'])
        assert arrays[name].shape == expected and str(arrays[name].dtype) == spec['dtype'], name
    immutable(arrays)
    return arrays, item


def load_bundle(verify: bool = True) -> dict:
    """
    機能: 完全旧materialと旧102.prepareを新一場だけ読み出す。
    引数: verify(bool)は新pickleと小直接依存の指紋照合要否。
    返り値: dictはmaterial/prepared。新入力再抽出や金融playを呼ばない。
    """
    saved = metadata(verify)
    path = HERE/'materialと完全旧prepare.pkl'
    payload = path.read_bytes()
    if verify:
        assert hashlib.sha256(payload).hexdigest() == saved['入力SHA256'][str(path.relative_to(ROOT))]
    value = pickle.loads(payload)
    assert value['material']['metadata']['sessions'] == [SESSION]
    assert set(value['prepared']) == {(SESSION, symbol) for symbol in SYMBOLS}
    immutable(value)
    return value


def load_inputs(verify: bool = True) -> dict:
    """
    機能: 102.prepare互換materialだけを一場として返す。
    引数: verify(bool)は出力指紋照合要否。
    返り値: dictは元31/既知32と混合しない旧入力構造。
    """
    return load_bundle(verify)['material']


def load_prepared(verify: bool = True) -> dict:
    """
    機能: 追加DayのO/B/Tに必要な完全旧prepareだけを返す。
    引数: verify(bool)は出力指紋照合要否。
    返り値: dict[(session,symbol),dict]はrecord/signal/reference_open。簡易代用はしない。
    """
    return load_bundle(verify)['prepared']
