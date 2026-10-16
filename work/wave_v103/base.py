"""検算済み旧出口へ渡す32場素材を、新原本抽出の正常列へ結び付けて読む。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def module(name: str, path: Path) -> object:
    """
    機能: 既存の入力読取部品を固有名で接続する。
    引数: name(str)、path(Path)は識別名とソース位置。
    返り値: object。旧領域へのバイトコード保存と新金融再生は行わない。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def digest(path: Path) -> str:
    """
    機能: 直接資料の内容指紋を求める。
    引数: path(Path)は小さい直接資料又は新出力。
    返り値: str。SHA256。旧巨大原本の追加走査は行わない。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def immutable(value: object) -> None:
    """
    機能: 接続した入力配列の上書きを拒絶する。
    引数: value(object)は配列、辞書又は列。
    返り値: None。辞書自体の同一性は変更しない。
    """
    if isinstance(value, np.ndarray):
        value.flags.writeable = False
    elif isinstance(value, dict):
        for child in value.values():
            immutable(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            immutable(child)


def load() -> dict:
    """
    機能: 元31と追加Nightを読むだけで結合し、登録済み正常執行5列と期間値を照合する。
    引数: なし。
    返り値: dict。32場素材。損益、選択結果、将来ラベル、現在APIは読まない。
    原本の全件対応は新入力抽出の一回読取証跡に委譲し、ここでは旧cacheの全継承hashを繰り返さない。
    """
    registration = json.loads((HERE / 'input/原本抽出前の32場登録.json').read_text(encoding='utf-8'))
    assert registration['全合格'] and registration['口座数'] == 64
    for relative, wanted in registration['直接コードSHA256'].items():
        assert digest(ROOT / relative) == wanted, relative
    original = module('103の旧31素材読取', ROOT / 'work/wave_v102/data.py').load_inputs(verify=False)
    extra = module('103の追加Night素材読取', ROOT / 'work/wave_v102/holdout_input/data.py').load_inputs(verify=False)
    result = dict(original)
    for name in ('prices', 'features', 'legacy', 'grids', 'entries',
                 'raw_last_records', 'execution_lp_index'):
        assert not set(original[name]) & set(extra[name]), name
        result[name] = {**original[name], **extra[name]}
    for name in ('price_lanes', 'trend_prices'):
        assert set(original[name]) == set(extra[name]), name
        result[name] = {}
        for lane in original[name]:
            assert not set(original[name][lane]) & set(extra[name][lane])
            result[name][lane] = {**original[name][lane], **extra[name][lane]}
    result['metadata'] = dict(original['metadata'], sessions=registration['sessions'],
        references={**original['metadata']['references'], **extra['metadata']['references']})
    result['paths'] = [*original['paths'], *extra['paths'], HERE / 'input/原本抽出前の32場登録.json']
    assert len(result['prices']) == 64 and len(result['metadata']['sessions']) == 32
    for (session, symbol), record in result['prices'].items():
        fixed = registration['accounts'][session + '|' + symbol]['旧正常列']
        for name, specification in fixed['arrays'].items():
            value = record[name]
            assert str(value.dtype) == specification['dtype'] and list(value.shape) == specification['shape']
            assert hashlib.sha256(value.tobytes()).hexdigest() == specification['SHA256'], (session, symbol, name)
        for name, registered_name in (('start', 'start'), ('end', 'end'), ('limit', 'limit'), ('tick', 'tick')):
            assert record[name] == fixed[registered_name]
        reference = result['metadata']['references'][session + '|' + symbol]['ref_open']
        assert reference['known_from_i'] == 0 and np.isfinite(reference['value']) and reference['value'] > 0
    immutable(result)
    return result
