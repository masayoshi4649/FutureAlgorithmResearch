"""完了した待機取消の一場cacheだけを返す。"""

import hashlib
import pickle

import common


def load_session(session: str) -> dict:
    """
    機能: 指紋照合済み一場cacheを返す。
    引数: session(str)は登録済み場名。
    返り値: dictは保存feed・quiet・正常価格・当時方向列。原本再抽出をしない。
    """
    meta=common.read(common.HERE/'全33場の待機取消準備.json');assert meta['全合格'] and meta['新金融']==0
    item=meta['cache'][session];path=common.ROOT/item['path'];saved=path.read_bytes()
    assert hashlib.sha256(saved).hexdigest()==item['SHA256']
    value=pickle.loads(common.gzip.decompress(saved));assert value['session']==session and value['schema_version']==1
    return value

