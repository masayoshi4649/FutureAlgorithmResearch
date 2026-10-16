"""結果前に準備した全19入口を一場単位で読み、金融へ不変入力を渡す。"""

import gzip
import hashlib
from pathlib import Path
import pickle

import base


HERE = Path(__file__).resolve().parent


def load_session(session: str, verify: bool = True) -> dict:
    """
    機能: 完了した104入口cacheだけを同じbytesの指紋で読み込む。
    引数: session(str)、verify(bool)は場名と新cache照合の要否。
    返り値: dictは全19入口と当時自己・相手根拠。未完了cacheは拒否する。
    """
    metadata = base.read(HERE/'入口準備の全32結果.json')
    assert metadata['全合格'] and metadata['対象場数'] == 32 and metadata['入口数'] == 19
    assert metadata['新金融再生'] == metadata['現在API'] == metadata['実注文'] == 0
    item = metadata['cache'][session]
    path = base.ROOT/item['path']
    assert path.resolve().is_relative_to((HERE/'prepared').resolve())
    saved = path.read_bytes()
    if verify:
        assert hashlib.sha256(saved).hexdigest() == item['SHA256']
        for name, wanted in metadata['source_SHA256'].items():
            assert base.digest(base.ROOT/name) == wanted, name
    value = pickle.loads(gzip.decompress(saved))
    assert value['schema_version'] == 1 and value['session'] == session
    assert set(value['normal']) == set(value['raw']) == {'TOPIX', 'NK225'}
    assert len(value['cases']) == 19
    base.immutable(value)
    return value
