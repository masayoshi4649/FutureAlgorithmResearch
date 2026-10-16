"""103で別保存した全原行入力を、一口座ずつ読み取り専用で返す。"""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SYMBOLS = ('TOPIX', 'NK225')


def digest(path: Path) -> str:
    """
    機能: 新しい出力又は小さい直接依存資料の指紋を求める。
    引数: path(Path)は対象資料。
    返り値: strはSHA256。旧原本の追加二重hashには使わない。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def load_account(session: str, symbol: str, verify: bool = True) -> tuple[dict, dict]:
    """
    機能: 完成した担当入力から一場一商品だけを読み、配列の変更を拒絶する。
    引数: session/symbol(str)、verify(bool)は場、商品及び新出力指紋確認要否。
    返り値: tuple[dict,dict]は原行配列と当該口座の診断。
    生原本を再走査せず、原本指紋は正式抽出時の一回読取証跡へ委譲する。
    """
    metadata_path = HERE / 'metadata.json'
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    assert metadata['全合格'] and metadata['対象場数'] == 32 and metadata['口座数'] == 64
    assert symbol in SYMBOLS and session in metadata['sessions']
    item = metadata['accounts'][session + '|' + symbol]
    path = ROOT / item['出力位置']
    if verify:
        assert digest(path) == item['出力SHA256']
        for relative, wanted in metadata['直接コードSHA256'].items():
            assert digest(ROOT / relative) == wanted, relative
    with np.load(path, allow_pickle=False) as saved:
        arrays = {name: saved[name] for name in saved.files}
    n = item['raw_rows']
    for name, specification in metadata['schema']['columns'].items():
        value = arrays[name]
        assert str(value.dtype) == specification['dtype'], name
        expected = tuple(n if dimension == 'N' else item['normal_execution_rows']
                         if dimension == 'M' else dimension for dimension in specification['shape'])
        assert value.shape == expected, (name, value.shape, expected)
        value.flags.writeable = False
    return arrays, item
