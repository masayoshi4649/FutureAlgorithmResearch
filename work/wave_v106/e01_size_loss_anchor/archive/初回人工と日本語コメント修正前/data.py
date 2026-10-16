"""結果前に束縛した旧E01保存inputを、正式金融の一場一回だけ返す。"""

import hashlib
import pickle
import common


def load(item: dict) -> dict:
    """
    機能: 指定された旧保存cache/台帳を同bytes一読してSHA照合する。
    引数: item(dict)は固定root相対path/SHA256。
    返り値: dictは保存値。原板・原NPZ・現在板・APIへ接続しない。
    """
    path=common.ROOT/item['path'];assert path.resolve().is_relative_to(common.ROOT/'work')
    saved=path.read_bytes();assert hashlib.sha256(saved).hexdigest()==item['SHA256']
    return pickle.loads(common.gzip.decompress(saved))
