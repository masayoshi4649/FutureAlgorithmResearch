"""活動だけの一場cacheを読み、後の金融処理へ不変packet/pulseを渡す。"""

import gzip
import hashlib
import importlib.util
import io
from pathlib import Path
import pickle
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
_specification = importlib.util.spec_from_file_location('103活動cache内部core', HERE/'core.py')
core = importlib.util.module_from_spec(_specification)
sys.modules[_specification.name] = core
_specification.loader.exec_module(core)


def read_npz_once(path: Path, wanted: str) -> dict:
    """
    機能: 新v2NPZのbytesを一回だけ読み、同じbytesでSHAと44配列を確認する。
    引数: path(Path)、wanted(str)は保存済み指紋。
    返り値: dict[str,ndarray]は読取配列。生原本又は金融結果を開かない。
    """
    payload = path.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == wanted, str(path)
    with np.load(io.BytesIO(payload), allow_pickle=False) as saved:
        arrays = {name: saved[name] for name in saved.files}
    return arrays


def verify_arrays(arrays: dict, item: dict, specification: dict) -> None:
    """
    機能: v2の44列shape/dtypeと原行順及び旧normal五列を照合する。
    引数: arrays/item/specification(dict)は入力配列・口座metadata・schema。
    返り値: None。不一致を補完せず拒否する。
    """
    assert set(arrays) == set(specification['columns']) and len(arrays) == 44
    for name, field in specification['columns'].items():
        value = arrays[name]
        shape = tuple(item['raw_rows'] if size == 'N' else item['normal_execution_rows'] if size == 'M' else size for size in field['shape'])
        assert value.shape == shape and str(value.dtype) == field['dtype'], name
    seq, mapping = arrays['raw_seq'], arrays['execution_to_raw_index']
    assert np.array_equal(seq, np.arange(item['raw_rows'], dtype=np.int64))
    assert len(mapping) == item['normal_execution_rows']
    assert np.all((mapping >= 0) & (mapping < len(seq))) and np.all(np.diff(mapping) > 0)
    assert np.array_equal(arrays['normal_execution_row'][mapping], np.arange(len(mapping)))
    assert np.array_equal(np.flatnonzero(arrays['normal_execution_row'] >= 0), mapping)
    for source, old in (('raw_seq', 'seq'), ('price_time_s', 'time_s'), ('last', 'price'), ('bid', 'bid'), ('ask', 'ask')):
        value, expected = arrays[source][mapping], item['旧正常列']['arrays'][old]
        assert str(value.dtype) == expected['dtype'] and list(value.shape) == expected['shape']
        assert hashlib.sha256(value.tobytes()).hexdigest() == expected['SHA256'], old
    for name in ('start', 'end', 'limit', 'tick'):
        assert item[name] == item['旧正常列'][name]
    for value in arrays.values():
        value.flags.writeable = False


def immutable(value: object) -> None:
    """
    機能: cache内の全数値配列をreadonlyへ固定する。
    引数: value(object)は辞書・列・配列。
    返り値: None。packetとnormal信号の内容を後段が上書きしない。
    """
    if isinstance(value, np.ndarray):
        value.flags.writeable = False
    elif isinstance(value, dict):
        for child in value.values():
            immutable(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            immutable(child)


def dump_session(path: Path, payload: dict) -> str:
    """
    機能: 新活動cacheを再現可能なgzipヘッダで一場単位に保存する。
    引数: path(Path)、payload(dict)は保存先と一場活動。
    返り値: strは出力SHA256。既存cacheを上書きしない。
    """
    assert path.resolve().is_relative_to(HERE.resolve()) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as target:
        with gzip.GzipFile(filename='', mode='wb', fileobj=target, mtime=0, compresslevel=3) as zipped:
            pickle.dump(payload, zipped, protocol=5)
    return core.digest(path)


def load_session(session: str, verify: bool = True) -> dict:
    """
    機能: 完了済み活動cacheを一場だけ読み、packet/pulseと正常列を返す。
    引数: session(str)、verify(bool)は新cache及び小さい直接source照合の要否。
    返り値: dictはschema_version/session/accounts/case_routes/summary。未完了又は旧cacheは拒否する。
    """
    metadata = core.read(HERE/'全32の状態可用性と発火.json')
    assert metadata['全合格'] and metadata['対象場数'] == 32 and metadata['口座数'] == 64
    assert metadata['正式金融再生'] == metadata['現在API取得'] == metadata['実注文'] == 0
    assert session in metadata['sessions']
    item = metadata['cache'][session]
    path = ROOT/item['位置']
    assert path.resolve().is_relative_to((HERE/'cache').resolve())
    saved = path.read_bytes()
    if verify:
        assert hashlib.sha256(saved).hexdigest() == item['SHA256']
        for name, wanted in metadata['開始SHA256'].items():
            assert core.digest(ROOT/name) == wanted, name
    payload = pickle.loads(gzip.decompress(saved))
    assert payload['schema_version'] == 1 and payload['session'] == session
    assert set(payload['accounts']) == set(core.SYMBOLS) and len(payload['case_routes']) == 19
    assert payload['case_routes']['OLD_G0'] is None
    assert payload['summary'] == metadata['by_session'][session]
    for symbol, account in payload['accounts'].items():
        assert account['item']['symbol'] == symbol and account['item']['session'] == session
        assert len(account['packets']) == 12 and len(account['pulses']) == 15
        assert len(account['case_to_packet']) == 14 and account['summaries']['OLD_G0'] is None
    immutable(payload)
    return payload
