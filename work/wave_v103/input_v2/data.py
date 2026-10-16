"""v1原本対応へ由来を結び、二配列を訂正したv2原行入力だけを返す。"""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(path: Path) -> str:
    """
    機能: 小さい由来資料又は新しいnpzの内容指紋を求める。
    引数: path(Path)は読取資料。
    返り値: strはSHA256。生原本の再hashには使わない。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def load_account(session: str, symbol: str, verify: bool = True) -> tuple[dict, dict]:
    """
    機能: 訂正済みv2の一口座をreadonlyで返し、v1の未訂正usableを金融入力へ渡さない。
    引数: session/symbol(str)、verify(bool)は場、商品及び新出力・小直接由来の照合要否。
    返り値: tuple[dict,dict]は44配列と一口座の診断。原本再読取は行わない。
    """
    metadata = json.loads((HERE/'metadata.json').read_text(encoding='utf-8'))
    assert metadata['全合格'] and metadata['schema']['version'] == 2
    assert metadata['口座数'] == metadata['正式全64派生'] == 64
    item = metadata['accounts'][session+'|'+symbol]
    path = ROOT/item['出力位置']
    if verify:
        assert digest(path) == item['出力SHA256']
        for name, wanted in metadata['小直接依存SHA256'].items():
            assert digest(ROOT/name) == wanted, name
    with np.load(path, allow_pickle=False) as saved:
        arrays = {name: saved[name] for name in saved.files}
    assert set(arrays) == set(metadata['schema']['columns'])
    for name, specification in metadata['schema']['columns'].items():
        value = arrays[name]
        shape = tuple(item['raw_rows'] if size == 'N' else item['normal_execution_rows']
                      if size == 'M' else size for size in specification['shape'])
        assert value.shape == shape and str(value.dtype) == specification['dtype'], name
        value.flags.writeable = False
    return arrays, item
