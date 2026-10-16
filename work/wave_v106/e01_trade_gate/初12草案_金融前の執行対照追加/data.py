"""指紋照合済みE01公開時確認cacheだけを返す。"""

import hashlib
import pickle

import common


def load_session(session: str) -> dict:
    """
    機能: 一場cacheを同bytes一読して照合する。
    引数: session(str)は固定された33場の一つ。
    返り値: dictは保存feed・normal気配・当時票。paper・金融を再計算しない。
    """
    meta=common.read(common.HERE/'全33場のE01取引更新準備.json');assert meta['全合格']
    item=meta['cache'][session];saved=(common.ROOT/item['path']).read_bytes()
    assert hashlib.sha256(saved).hexdigest()==item['SHA256']
    value=pickle.loads(common.gzip.decompress(saved));assert value['session']==session
    return value
